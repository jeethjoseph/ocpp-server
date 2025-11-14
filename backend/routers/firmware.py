# routers/firmware.py
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/firmware", tags=["firmware"])

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

    class Config:
        from_attributes = True

class FirmwareHistoryResponse(BaseModel):
    data: List[FirmwareUpdateResponse]
    total: int
    page: int
    limit: int

class BulkUpdateResult(BaseModel):
    success: List[dict]
    failed: List[dict]

class UpdateStatusSummary(BaseModel):
    pending: int
    downloading: int
    installing: int
    completed_today: int
    failed_today: int

class UpdateStatusDashboardResponse(BaseModel):
    in_progress: List[dict]
    summary: UpdateStatusSummary


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
        # Save file to storage
        storage_result = await storage_service.save_firmware_file(file, version)

        # Create database record
        firmware_file = await FirmwareFile.create(
            version=version,
            filename=storage_result['filename'],
            file_path=storage_result['file_path'],
            file_size=storage_result['file_size'],
            checksum=storage_result['checksum'],
            description=description,
            uploaded_by_id=user.id,
            is_active=True
        )

        logger.info(f"📦 ✅ Firmware uploaded successfully: ID={firmware_file.id}, version={version}")

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

    # Soft delete
    firmware_file.is_active = False
    await firmware_file.save()

    logger.info(f"📦 Firmware file ID={firmware_id} (version={firmware_file.version}) soft deleted by user {user.id}")

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
    Trigger firmware update for a single charger (Admin only)

    Performs safety checks:
    - Charger must be online (heartbeat within 90 seconds)
    - No active charging session
    - Version validation (warn if same version)

    Sends OCPP UpdateFirmware command immediately.
    """
    # Get charger
    charger = await Charger.get_or_none(id=charger_id).prefetch_related('station')
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Get firmware file
    firmware_file = await FirmwareFile.get_or_none(id=update_request.firmware_file_id, is_active=True)
    if not firmware_file:
        raise HTTPException(status_code=404, detail="Firmware file not found or inactive")

    # Validate charger can receive update
    validation_error = await _validate_charger_for_update(charger, firmware_file.version)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)

    # Generate download URL
    base_url = str(request.base_url).rstrip('/')
    download_url = storage_service.get_firmware_download_url(firmware_file.filename, base_url)

    logger.info(f"📦 Initiating firmware update for charger {charger.charge_point_string_id} to version {firmware_file.version}")
    logger.info(f"📦 Download URL: {download_url}")

    # Create FirmwareUpdate record
    firmware_update = await FirmwareUpdate.create(
        charger_id=charger.id,
        firmware_file_id=firmware_file.id,
        status=FirmwareUpdateStatusEnum.PENDING,
        initiated_by_id=user.id,
        download_url=download_url
    )

    # Send OCPP UpdateFirmware command
    from datetime import datetime, timezone
    retrieve_date = datetime.now(timezone.utc).isoformat()

    payload = {
        "location": download_url,
        "retrieve_date": retrieve_date,
        "retries": 3,
        "retry_interval": 300  # 5 minutes between retries
    }

    # Import here to avoid circular import
    from main import send_ocpp_request

    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "UpdateFirmware",
        payload
    )

    if not success:
        # Update failed - update record
        firmware_update.status = FirmwareUpdateStatusEnum.DOWNLOAD_FAILED
        firmware_update.error_message = f"Failed to send OCPP command: {response}"
        firmware_update.completed_at = datetime.now(timezone.utc)
        await firmware_update.save()

        logger.error(f"📦 ❌ Failed to send UpdateFirmware command: {response}")
        raise HTTPException(status_code=500, detail=f"Failed to send update command: {response}")

    logger.info(f"📦 ✅ UpdateFirmware command sent successfully to {charger.charge_point_string_id}")

    return FirmwareUpdateResponse.from_orm(firmware_update)


@router.post("/bulk-update", response_model=BulkUpdateResult)
async def bulk_update_firmware(
    bulk_request: BulkFirmwareUpdateRequest,
    request: Request,
    user: User = Depends(require_admin())
):
    """
    Trigger firmware update for multiple chargers (Admin only)

    Applies same safety checks as single update for each charger.
    Returns list of successes and failures.
    """
    # Get firmware file
    firmware_file = await FirmwareFile.get_or_none(id=bulk_request.firmware_file_id, is_active=True)
    if not firmware_file:
        raise HTTPException(status_code=404, detail="Firmware file not found or inactive")

    success_list = []
    failed_list = []

    for charger_id in bulk_request.charger_ids:
        charger = await Charger.get_or_none(id=charger_id)
        if not charger:
            failed_list.append({
                "charger_id": charger_id,
                "reason": "Charger not found"
            })
            continue

        # Validate charger
        validation_error = await _validate_charger_for_update(charger, firmware_file.version)
        if validation_error:
            failed_list.append({
                "charger_id": charger_id,
                "charger_name": charger.name,
                "reason": validation_error
            })
            continue

        # Generate download URL
        base_url = str(request.base_url).rstrip('/')
        download_url = storage_service.get_firmware_download_url(firmware_file.filename, base_url)

        # Create FirmwareUpdate record
        firmware_update = await FirmwareUpdate.create(
            charger_id=charger.id,
            firmware_file_id=firmware_file.id,
            status=FirmwareUpdateStatusEnum.PENDING,
            initiated_by_id=user.id,
            download_url=download_url
        )

        # Send OCPP UpdateFirmware command
        from datetime import datetime, timezone
        retrieve_date = datetime.now(timezone.utc).isoformat()

        payload = {
            "location": download_url,
            "retrieve_date": retrieve_date,
            "retries": 3,
            "retry_interval": 300
        }

        # Import here to avoid circular import
        from main import send_ocpp_request

        success, response = await send_ocpp_request(
            charger.charge_point_string_id,
            "UpdateFirmware",
            payload
        )

        if not success:
            # Update failed
            firmware_update.status = FirmwareUpdateStatusEnum.DOWNLOAD_FAILED
            firmware_update.error_message = f"Failed to send OCPP command: {response}"
            firmware_update.completed_at = datetime.now(timezone.utc)
            await firmware_update.save()

            failed_list.append({
                "charger_id": charger_id,
                "charger_name": charger.name,
                "reason": f"OCPP command failed: {response}"
            })
        else:
            success_list.append({
                "charger_id": charger_id,
                "charger_name": charger.name,
                "update_id": firmware_update.id
            })

    logger.info(f"📦 Bulk update completed: {len(success_list)} succeeded, {len(failed_list)} failed")

    return BulkUpdateResult(
        success=success_list,
        failed=failed_list
    )


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
    updates = await FirmwareUpdate.filter(charger_id=charger_id).order_by('-initiated_at').offset(offset).limit(limit)

    return FirmwareHistoryResponse(
        data=[FirmwareUpdateResponse.from_orm(u) for u in updates],
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
    - In-progress updates with charger details
    - Summary statistics (pending, downloading, installing, completed today, failed today)
    """
    from datetime import datetime, timedelta, timezone

    # Get in-progress updates
    in_progress_updates = await FirmwareUpdate.filter(
        status__in=["PENDING", "DOWNLOADING", "DOWNLOADED", "INSTALLING"]
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
            "started_at": update.started_at.isoformat() if update.started_at else None,
            "initiated_at": update.initiated_at.isoformat()
        })

    # Calculate summary statistics
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    pending_count = await FirmwareUpdate.filter(status="PENDING").count()
    downloading_count = await FirmwareUpdate.filter(status="DOWNLOADING").count()
    installing_count = await FirmwareUpdate.filter(status="INSTALLING").count()
    completed_today = await FirmwareUpdate.filter(
        status="INSTALLED",
        completed_at__gte=today_start
    ).count()
    failed_today = await FirmwareUpdate.filter(
        status__in=["DOWNLOAD_FAILED", "INSTALLATION_FAILED"],
        completed_at__gte=today_start
    ).count()

    summary = UpdateStatusSummary(
        pending=pending_count,
        downloading=downloading_count,
        installing=installing_count,
        completed_today=completed_today,
        failed_today=failed_today
    )

    return UpdateStatusDashboardResponse(
        in_progress=in_progress_list,
        summary=summary
    )
