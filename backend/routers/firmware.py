# routers/firmware.py
import asyncio
from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request
from pydantic import BaseModel
from datetime import datetime
import os
import logging

from models import (
    FirmwareFile,
    FirmwareUpdate,
    Charger,
    User,
    Transaction,
    FirmwareUpdateStatusEnum
)
from auth_middleware import require_admin, require_user_or_admin
from services import storage_service
from services.firmware_update_service import FIRMWARE_MAX_ATTEMPTS
from crud import log_audit_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/firmware", tags=["firmware"])
public_router = APIRouter(prefix="/api/firmware", tags=["firmware-public"])

# Pydantic schemas
class FirmwareFileResponse(BaseModel):
    id: int
    version: str
    filename: str
    file_size: int
    checksum: str
    description: Optional[str]
    uploaded_by_id: int
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True

class FirmwareFileListResponse(BaseModel):
    data: List[FirmwareFileResponse]
    total: int
    page: int
    limit: int

class FirmwareUpdateRequest(BaseModel):
    firmware_file_id: int

class BulkFirmwareUpdateRequest(BaseModel):
    firmware_file_id: int
    charger_ids: List[int]

class FirmwareUpdateResponse(BaseModel):
    id: int
    charger_id: int
    firmware_file_id: int
    status: str
    download_url: str
    initiated_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    attempt_count: int = 0
    last_attempt_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    firmware_version: Optional[str] = None

    class Config:
        from_attributes = True

class FirmwareHistoryResponse(BaseModel):
    data: List[FirmwareUpdateResponse]
    total: int
    page: int
    limit: int

class BulkUpdateResult(BaseModel):
    success: List[dict]
    skipped: List[dict]
    failed: List[dict]

class UpdateStatusSummary(BaseModel):
    pending: int
    completed_today: int
    failed_today: int

class UpdateStatusDashboardResponse(BaseModel):
    in_progress: List[dict]
    summary: UpdateStatusSummary

class LatestFirmwareResponse(BaseModel):
    version: str
    filename: str
    download_url: str
    checksum: str
    file_size: int

    class Config:
        from_attributes = True


# ============ Firmware Management Endpoints ============

@router.post("/upload", response_model=FirmwareFileResponse)
async def upload_firmware(
    file: UploadFile = File(...),
    version: str = Form(...),
    description: Optional[str] = Form(None),
    user: User = Depends(require_admin())
):
    """
    Upload a new firmware file (Admin only)

    - **file**: Firmware binary file (.bin, .hex, .fw)
    - **version**: Version string (e.g., "1.2.3")
    - **description**: Optional release notes
    """
    logger.info(f"📦 Firmware upload requested by user {user.id}: version={version}, filename={file.filename}")

    # Validate file extension
    allowed_extensions = ['.bin', '.hex', '.fw']
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file extension. Allowed: {', '.join(allowed_extensions)}"
        )

    # Validate file size (max 100MB)
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB in bytes
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Seek back to start

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size ({file_size / 1024 / 1024:.2f}MB) exceeds maximum allowed size (100MB)"
        )

    # Check if version already exists
    existing = await FirmwareFile.filter(version=version).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Firmware version '{version}' already exists"
        )

    try:
        file_content = await file.read()
        safe_filename = f"{version}_{file.filename}"

        # Storage backend selection: presence of AWS_S3_FIRMWARE_BUCKET picks S3;
        # empty/unset falls back to local-disk storage. The legacy local path is
        # a stopgap so charger firmware with a short URL-buffer can ingest the
        # download location until the device-side parser is patched.
        if os.getenv("AWS_S3_FIRMWARE_BUCKET"):
            s3_key = storage_service.build_firmware_s3_key(version, safe_filename)
            await asyncio.to_thread(storage_service.upload_firmware_to_s3, s3_key, file_content)
            file_path = ""
            storage_backend = "s3"
        else:
            s3_key = None
            file_path = os.path.join(storage_service.FIRMWARE_DIR, safe_filename)
            with open(file_path, "wb") as f:
                f.write(file_content)
            storage_backend = "local"

        checksum = storage_service.calculate_checksum_from_bytes(file_content)

        firmware_file = await FirmwareFile.create(
            version=version,
            filename=safe_filename,
            file_path=file_path,
            s3_key=s3_key,
            file_size=len(file_content),
            checksum=checksum,
            description=description,
            uploaded_by_id=user.id,
            is_active=True,
        )

        if storage_backend == "s3":
            logger.info(f"📦 ✅ Firmware uploaded to S3: ID={firmware_file.id}, version={version}, s3_key={s3_key}")
        else:
            logger.info(f"📦 ✅ Firmware uploaded to local disk: ID={firmware_file.id}, version={version}, file_path={file_path}")

        await log_audit_event(
            action="firmware.uploaded",
            entity_type="firmware",
            entity_id=firmware_file.id,
            actor_type="admin",
            actor=user,
            changes={
                "version": version,
                "filename": safe_filename,
                "storage_backend": storage_backend,
                "s3_key": s3_key,
                "file_path": file_path or None,
            },
        )

        return FirmwareFileResponse.from_orm(firmware_file)

    except Exception as e:
        logger.error(f"📦 ❌ Error uploading firmware: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload firmware: {str(e)}")


@router.get("", response_model=FirmwareFileListResponse)
async def list_firmware_files(
    page: int = 1,
    limit: int = 20,
    is_active: Optional[bool] = True,
    user: User = Depends(require_admin())
):
    """
    List all firmware files (Admin only)

    - **page**: Page number (starts at 1)
    - **limit**: Items per page
    - **is_active**: Filter by active status (default: True)
    """
    offset = (page - 1) * limit

    query = FirmwareFile.all()
    if is_active is not None:
        query = query.filter(is_active=is_active)

    total = await query.count()
    firmware_files = await query.order_by('-created_at').offset(offset).limit(limit)

    return FirmwareFileListResponse(
        data=[FirmwareFileResponse.from_orm(f) for f in firmware_files],
        total=total,
        page=page,
        limit=limit
    )


@router.delete("/{firmware_id}")
async def delete_firmware_file(
    firmware_id: int,
    user: User = Depends(require_admin())
):
    """
    Soft delete a firmware file (Admin only)

    Sets is_active=False. Does not delete the physical file.
    Cannot delete if any charger is currently using this version.
    """
    firmware_file = await FirmwareFile.get_or_none(id=firmware_id)
    if not firmware_file:
        raise HTTPException(status_code=404, detail="Firmware file not found")

    # Check if any charger is using this version
    chargers_using = await Charger.filter(firmware_version=firmware_file.version).count()
    if chargers_using > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete firmware version {firmware_file.version}. {chargers_using} charger(s) are currently using it."
        )

    # Auto-cancel any pending updates that reference this firmware file
    pending_updates = await FirmwareUpdate.filter(
        firmware_file_id=firmware_id,
        status=FirmwareUpdateStatusEnum.PENDING
    )
    cancelled_count = 0
    for update in pending_updates:
        update.status = FirmwareUpdateStatusEnum.CANCELLED
        await update.save()
        cancelled_count += 1

    if cancelled_count > 0:
        logger.info(f"📦 Auto-cancelled {cancelled_count} pending update(s) for firmware ID={firmware_id}")

    # Soft delete
    firmware_file.is_active = False
    await firmware_file.save()

    logger.info(f"📦 Firmware file ID={firmware_id} (version={firmware_file.version}) soft deleted by user {user.id}")

    await log_audit_event(
        action="firmware.deleted",
        entity_type="firmware",
        entity_id=firmware_id,
        actor_type="admin",
        actor=user,
        changes={"version": firmware_file.version},
    )

    return {"success": True, "message": f"Firmware version {firmware_file.version} deleted"}


# ============ Firmware Update Operations ============

async def _validate_charger_for_update(charger: Charger, target_version: str) -> Optional[str]:
    """
    Validate if charger can receive firmware update

    Returns:
        None if validation passes, error message string if validation fails
    """
    # Check 1: Charger online (heartbeat within 90 seconds)
    if charger.last_heart_beat_time:
        from datetime import datetime, timedelta, timezone
        time_since_heartbeat = datetime.now(timezone.utc) - charger.last_heart_beat_time.replace(tzinfo=timezone.utc)
        if time_since_heartbeat.total_seconds() > 90:
            return f"Charger is offline (last heartbeat {int(time_since_heartbeat.total_seconds())}s ago)"
    else:
        return "Charger has never sent a heartbeat (offline)"

    # Check 2: No active transaction
    active_transaction = await Transaction.filter(
        charger_id=charger.id,
        transaction_status__in=["STARTED", "PENDING_START", "RUNNING"]
    ).first()
    if active_transaction:
        return f"Charger has an active charging session (transaction ID: {active_transaction.id})"

    # Check 3: Version validation
    if charger.firmware_version == target_version:
        return f"Charger already has firmware version {target_version}"

    # Note: We're not doing semantic version comparison for downgrades
    # Just warning if same version

    return None  # Validation passed


@router.post("/chargers/{charger_id}/update", response_model=FirmwareUpdateResponse)
async def update_charger_firmware(
    charger_id: int,
    update_request: FirmwareUpdateRequest,
    request: Request,
    user: User = Depends(require_admin())
):
    """
    Schedule firmware update for a single charger (Admin only)

    Creates or updates a firmware_update record with PENDING status.
    The background service will automatically trigger the update when:
    - Charger is online (heartbeat within 90 seconds)
    - No active charging session
    - Charger is not already on the target version

    Can be scheduled even when charger is offline - update will trigger when ready.
    """
    # Get charger
    charger = await Charger.get_or_none(id=charger_id).prefetch_related('station')
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Get firmware file
    firmware_file = await FirmwareFile.get_or_none(id=update_request.firmware_file_id, is_active=True)
    if not firmware_file:
        raise HTTPException(status_code=404, detail="Firmware file not found or inactive")

    # No validation checks here - background service will validate when triggering
    # This allows scheduling updates for offline chargers

    base_url = str(request.base_url).rstrip('/')
    download_url = storage_service.get_firmware_download_url_for_file(firmware_file, base_url)

    logger.info(f"📦 Scheduling firmware update for charger {charger.charge_point_string_id} to version {firmware_file.version}")

    # UPSERT: reset any existing row (INSTALLED/FAILED/CANCELLED/PENDING) for this charger+firmware combo.
    # Resetting INSTALLED is intentional — admin may want to re-flash the same version.
    firmware_update = await FirmwareUpdate.get_or_none(
        charger_id=charger.id,
        firmware_file_id=firmware_file.id
    )

    if firmware_update:
        logger.info(f"📦 Resetting existing update record (ID: {firmware_update.id}, prev status: {firmware_update.status})")
        firmware_update.status = FirmwareUpdateStatusEnum.PENDING
        firmware_update.initiated_by_id = user.id
        firmware_update.download_url = download_url
        firmware_update.started_at = None
        firmware_update.completed_at = None
        firmware_update.error_message = None
        firmware_update.attempt_count = 0
        firmware_update.last_attempt_at = None
        firmware_update.next_retry_at = None
        await firmware_update.save()
    else:
        logger.info(f"📦 Creating new update record for charger+firmware combination")
        firmware_update = await FirmwareUpdate.create(
            charger_id=charger.id,
            firmware_file_id=firmware_file.id,
            status=FirmwareUpdateStatusEnum.PENDING,
            initiated_by_id=user.id,
            download_url=download_url,
            attempt_count=0,
        )

    logger.info(f"📦 ✅ Firmware update scheduled (will be processed by background service)")
    logger.info(f"📦 Background service will check if charger is ready and trigger update automatically")

    await log_audit_event(
        action="firmware.update_initiated",
        entity_type="charger",
        entity_id=charger.charge_point_string_id,
        actor_type="admin",
        actor=user,
        changes={"firmware_version": firmware_file.version, "update_id": firmware_update.id},
    )

    return FirmwareUpdateResponse.from_orm(firmware_update)


async def _bulk_classify_charger(charger, firmware_file, download_url, user):
    """Classify one charger for a bulk deploy and (re)schedule if eligible.

    Returns (bucket, entry) where bucket is "success" | "skipped". Idempotent
    and safe to re-run: chargers already on the target version, and in-flight
    rows (PENDING with attempt_count > 0), are skipped untouched. Only
    re-deployable rows (PENDING attempt 0 / INSTALLED / FAILED / CANCELLED) are
    reset to a fresh PENDING. See [[in-flight-firmware-update]] in CONTEXT.md.
    """
    base = {"charger_id": charger.id, "charger_name": charger.name}
    if charger.firmware_version == firmware_file.version:
        return "skipped", {**base, "reason": f"already on {firmware_file.version}"}

    existing = await FirmwareUpdate.get_or_none(charger_id=charger.id, firmware_file_id=firmware_file.id)
    if existing and existing.status == FirmwareUpdateStatusEnum.PENDING and existing.attempt_count > 0:
        return "skipped", {
            **base,
            "update_id": existing.id,
            "reason": f"in-flight, attempt {existing.attempt_count}/{FIRMWARE_MAX_ATTEMPTS}",
        }

    if existing:
        existing.status = FirmwareUpdateStatusEnum.PENDING
        existing.initiated_by_id = user.id
        existing.download_url = download_url
        existing.started_at = None
        existing.completed_at = None
        existing.error_message = None
        existing.attempt_count = 0
        existing.last_attempt_at = None
        existing.next_retry_at = None
        await existing.save()
    else:
        existing = await FirmwareUpdate.create(
            charger_id=charger.id,
            firmware_file_id=firmware_file.id,
            status=FirmwareUpdateStatusEnum.PENDING,
            initiated_by_id=user.id,
            download_url=download_url,
            attempt_count=0,
        )
    return "success", {**base, "update_id": existing.id}


@router.post("/bulk-update", response_model=BulkUpdateResult)
async def bulk_update_firmware(
    bulk_request: BulkFirmwareUpdateRequest,
    request: Request,
    user: User = Depends(require_admin())
):
    """
    Schedule firmware updates for multiple chargers (Admin only)

    Idempotent bulk deploy. Each charger lands in exactly one bucket:
    - **success**: a fresh PENDING row was created or a re-deployable row reset.
    - **skipped**: already on the target version, or an in-flight update
      (PENDING, attempt_count > 0) left completely untouched.
    - **failed**: charger not found.

    Chargers can be offline — the background service triggers when each is ready.
    Re-running the same deploy disturbs nothing already handled or in-flight.
    """
    firmware_file = await FirmwareFile.get_or_none(id=bulk_request.firmware_file_id, is_active=True)
    if not firmware_file:
        raise HTTPException(status_code=404, detail="Firmware file not found or inactive")

    # One presigned URL for the whole batch — same firmware_file for every charger.
    base_url = str(request.base_url).rstrip('/')
    download_url = storage_service.get_firmware_download_url_for_file(firmware_file, base_url)

    buckets = {"success": [], "skipped": [], "failed": []}
    for charger_id in bulk_request.charger_ids:
        charger = await Charger.get_or_none(id=charger_id)
        if not charger:
            buckets["failed"].append({"charger_id": charger_id, "reason": "Charger not found"})
            continue
        bucket, entry = await _bulk_classify_charger(charger, firmware_file, download_url, user)
        buckets[bucket].append(entry)

    logger.info(
        f"📦 Bulk deploy {firmware_file.version}: {len(buckets['success'])} scheduled, "
        f"{len(buckets['skipped'])} skipped, {len(buckets['failed'])} failed"
    )

    await log_audit_event(
        action="firmware.bulk_update_initiated",
        entity_type="firmware",
        entity_id=firmware_file.id,
        actor_type="admin",
        actor=user,
        changes={
            "firmware_version": firmware_file.version,
            "scheduled_count": len(buckets["success"]),
            "skipped_count": len(buckets["skipped"]),
            "failed_count": len(buckets["failed"]),
        },
    )

    return BulkUpdateResult(**buckets)


@router.get("/chargers/{charger_id}/history", response_model=FirmwareHistoryResponse)
async def get_firmware_history(
    charger_id: int,
    page: int = 1,
    limit: int = 10,
    user: User = Depends(require_user_or_admin)
):
    """
    Get firmware update history for a charger (Admin + User)

    Returns all firmware update attempts with status and timestamps.
    """
    # Verify charger exists
    charger = await Charger.get_or_none(id=charger_id)
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    offset = (page - 1) * limit

    total = await FirmwareUpdate.filter(charger_id=charger_id).count()
    updates = await FirmwareUpdate.filter(charger_id=charger_id).prefetch_related('firmware_file').order_by('-initiated_at').offset(offset).limit(limit)

    response_list = []
    for u in updates:
        resp = FirmwareUpdateResponse.from_orm(u)
        resp.firmware_version = u.firmware_file.version if u.firmware_file else None
        response_list.append(resp)

    return FirmwareHistoryResponse(
        data=response_list,
        total=total,
        page=page,
        limit=limit
    )


@router.get("/updates/status", response_model=UpdateStatusDashboardResponse)
async def get_update_status_dashboard(
    user: User = Depends(require_admin())
):
    """
    Get dashboard view of all firmware updates (Admin only)

    Returns:
    - PENDING updates with charger details (the only active state in the v2 state machine)
    - Summary statistics (pending count, completed today, failed today)
    """
    from datetime import datetime, timezone

    in_progress_updates = await FirmwareUpdate.filter(
        status=FirmwareUpdateStatusEnum.PENDING
    ).prefetch_related('charger', 'firmware_file').order_by('-initiated_at')

    in_progress_list = []
    for update in in_progress_updates:
        in_progress_list.append({
            "update_id": update.id,
            "charger_id": update.charger.id,
            "charger_name": update.charger.name,
            "charge_point_id": update.charger.charge_point_string_id,
            "firmware_version": update.firmware_file.version,
            "status": update.status,
            "attempt_count": update.attempt_count,
            "last_attempt_at": update.last_attempt_at.isoformat() if update.last_attempt_at else None,
            "next_retry_at": update.next_retry_at.isoformat() if update.next_retry_at else None,
            "started_at": update.started_at.isoformat() if update.started_at else None,
            "initiated_at": update.initiated_at.isoformat(),
            # Last-attempt failure reason for retrying PENDING rows (attempt_count > 0).
            # Surfaced inline in the admin Active Updates table so a stalled/failing
            # rollout shows *why* without an API/log dive.
            "error_message": update.error_message,
        })

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    pending_count = await FirmwareUpdate.filter(status=FirmwareUpdateStatusEnum.PENDING).count()
    completed_today = await FirmwareUpdate.filter(
        status=FirmwareUpdateStatusEnum.INSTALLED,
        completed_at__gte=today_start
    ).count()
    failed_today = await FirmwareUpdate.filter(
        status=FirmwareUpdateStatusEnum.FAILED,
        completed_at__gte=today_start
    ).count()

    summary = UpdateStatusSummary(
        pending=pending_count,
        completed_today=completed_today,
        failed_today=failed_today
    )

    return UpdateStatusDashboardResponse(
        in_progress=in_progress_list,
        summary=summary
    )


@router.post("/updates/{update_id}/cancel")
async def cancel_firmware_update(
    update_id: int,
    user: User = Depends(require_admin())
):
    """Cancel a not-yet-attempted firmware update (Admin only).

    Only PENDING rows with attempt_count == 0 can be cancelled. Once an
    UpdateFirmware has been sent, the charger may already be downloading;
    use mark-failed instead if you need to close out an in-flight row.
    """
    update = await FirmwareUpdate.get_or_none(id=update_id)
    if not update:
        raise HTTPException(status_code=404, detail="Firmware update not found")

    if update.status != FirmwareUpdateStatusEnum.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel update with status '{update.status}'. Only PENDING updates can be cancelled."
        )
    if update.attempt_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel update that has been attempted ({update.attempt_count} attempt(s)). Use mark-failed to close it out."
        )

    update.status = FirmwareUpdateStatusEnum.CANCELLED
    update.completed_at = datetime.utcnow()
    await update.save()

    logger.info(f"Firmware update {update_id} cancelled by user {user.id}")
    return {"message": "Firmware update cancelled successfully", "update_id": update_id}


@router.post("/updates/{update_id}/mark-installed", response_model=FirmwareUpdateResponse)
async def mark_firmware_update_installed(
    update_id: int,
    user: User = Depends(require_admin())
):
    """Manually close a firmware update as INSTALLED (Admin only).

    Intended for polling/out-of-network chargers where the server can't observe
    the install via BootNotification. Also updates Charger.firmware_version to
    reflect that the target version is now live.
    """
    update = await FirmwareUpdate.get_or_none(id=update_id).prefetch_related('charger', 'firmware_file')
    if not update:
        raise HTTPException(status_code=404, detail="Firmware update not found")
    if update.status not in (FirmwareUpdateStatusEnum.PENDING, FirmwareUpdateStatusEnum.FAILED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark INSTALLED from current status '{update.status}'."
        )

    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)
    update.status = FirmwareUpdateStatusEnum.INSTALLED
    update.completed_at = now
    update.next_retry_at = None
    update.error_message = None
    await update.save()

    charger = update.charger
    charger.firmware_version = update.firmware_file.version
    await charger.save()

    await log_audit_event(
        action="firmware.marked_installed",
        entity_type="firmware_update",
        entity_id=update.id,
        actor_type="admin",
        actor=user,
        changes={"version": update.firmware_file.version, "charger_id": charger.id},
    )

    resp = FirmwareUpdateResponse.from_orm(update)
    resp.firmware_version = update.firmware_file.version
    return resp


@router.post("/updates/{update_id}/mark-failed", response_model=FirmwareUpdateResponse)
async def mark_firmware_update_failed(
    update_id: int,
    user: User = Depends(require_admin())
):
    """Manually close a firmware update as FAILED (Admin only).

    Use for stuck PENDING rows (e.g. polling charger that never reported back,
    or OCPP charger that's gone offline permanently). Does NOT change
    Charger.firmware_version.
    """
    update = await FirmwareUpdate.get_or_none(id=update_id).prefetch_related('firmware_file')
    if not update:
        raise HTTPException(status_code=404, detail="Firmware update not found")
    if update.status != FirmwareUpdateStatusEnum.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark FAILED from current status '{update.status}'."
        )

    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)
    update.status = FirmwareUpdateStatusEnum.FAILED
    update.completed_at = now
    update.next_retry_at = None
    update.error_message = (update.error_message or "") + " [admin marked FAILED]"
    await update.save()

    await log_audit_event(
        action="firmware.marked_failed",
        entity_type="firmware_update",
        entity_id=update.id,
        actor_type="admin",
        actor=user,
        changes={"version": update.firmware_file.version},
    )

    resp = FirmwareUpdateResponse.from_orm(update)
    resp.firmware_version = update.firmware_file.version
    return resp


# ============ Public Firmware Discovery Endpoint ============

@public_router.get("/latest", response_model=Optional[LatestFirmwareResponse])
async def get_latest_firmware(
    request: Request,
    charger_id: Optional[str] = None,
    external_charger_id: Optional[str] = None,
    current_firmware_version: Optional[str] = None,
):
    """Get the latest available firmware for a polling (non-OCPP) charge point.

    Public endpoint — no auth. Polling chargers should hit this once per
    interval. If the row's target matches `current_firmware_version`, the
    update is auto-closed as INSTALLED (server learns the charger has applied
    the firmware out-of-band).

    Modes:
    1. external_charger_id: row scoped to charger identified by external ID
    2. charger_id (charge_point_string_id): row scoped to that specific charger
    3. neither: latest active firmware file (legacy/backward compatibility)
    """
    charger: Optional[Charger] = None
    latest_update = None
    latest_firmware = None

    async def _resolve_active_update(charger_obj: Charger):
        return await FirmwareUpdate.filter(
            charger_id=charger_obj.id,
            status=FirmwareUpdateStatusEnum.PENDING,
            firmware_file__is_active=True,
        ).prefetch_related('firmware_file').order_by('-initiated_at').first()

    if external_charger_id:
        logger.info(f"📦 Latest firmware requested for external_charger_id={external_charger_id}")
        charger = await Charger.get_or_none(external_charger_id=external_charger_id)
        if not charger:
            raise HTTPException(
                status_code=404,
                detail=f"Charger not found with external_charger_id: {external_charger_id}"
            )
        latest_update = await _resolve_active_update(charger)

    elif charger_id:
        logger.info(f"📦 Latest firmware requested for charger_id={charger_id}")
        charger = await Charger.get_or_none(charge_point_string_id=charger_id)
        if not charger:
            raise HTTPException(
                status_code=404,
                detail=f"Charger not found: {charger_id}"
            )
        latest_update = await _resolve_active_update(charger)

    else:
        logger.info("📦 Latest firmware requested (global mode)")
        latest_firmware = await FirmwareFile.filter(is_active=True).order_by('-created_at').first()
        if not latest_firmware:
            return None

    # Charger-specific resolution
    if charger is not None:
        if not latest_update:
            return None

        # Auto-detect: charger reports its current version. If it already matches
        # the pending target, close the row as INSTALLED and return nothing —
        # nothing left to do for this charger on this poll.
        if current_firmware_version and current_firmware_version == latest_update.firmware_file.version:
            from datetime import timezone as _tz
            now = datetime.now(_tz.utc)
            latest_update.status = FirmwareUpdateStatusEnum.INSTALLED
            latest_update.completed_at = now
            latest_update.next_retry_at = None
            latest_update.error_message = None
            await latest_update.save()
            charger.firmware_version = current_firmware_version
            await charger.save()
            logger.info(
                f"📦 Auto-detected install for {charger.charge_point_string_id} "
                f"(reported {current_firmware_version}); update {latest_update.id} → INSTALLED"
            )
            return None

        latest_firmware = latest_update.firmware_file

    base_url = str(request.base_url).rstrip('/')
    download_url = storage_service.get_firmware_download_url_for_file(latest_firmware, base_url)

    return LatestFirmwareResponse(
        version=latest_firmware.version,
        filename=latest_firmware.filename,
        download_url=download_url,
        checksum=latest_firmware.checksum,
        file_size=latest_firmware.file_size
    )
