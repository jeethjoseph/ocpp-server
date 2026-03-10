# routers/logs.py
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime, timezone
import logging

from models import OCPPLog, User, AuditLog, Charger, Transaction
from auth_middleware import require_admin
from tortoise.queryset import Q

logger = logging.getLogger(__name__)

# Pydantic schemas
from typing import Union, Any


def _parse_date(value: str, field_name: str) -> datetime:
    """Parse an ISO date string, rejecting ambiguous inputs without timezone info."""
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format. Use ISO 8601 with timezone (e.g. 2026-03-10T00:00:00Z)",
        )
    if dt.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must include timezone info (e.g. append 'Z' for UTC). Got: {value}",
        )
    return dt


class LogResponse(BaseModel):
    id: int
    created_at: datetime
    charge_point_id: Optional[str]
    message_type: Optional[str]
    direction: str
    payload: Optional[Union[dict, list, Any]]  # Allow dict, list, or any other type
    status: Optional[str]
    correlation_id: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True

class LogsResponse(BaseModel):
    data: List[LogResponse]
    total: int
    limit: int
    has_more: bool
    message: Optional[str] = None

# Create router
router = APIRouter(prefix="/api/admin/logs", tags=["admin-logs"])

@router.get("/charger/{charge_point_id}", response_model=LogsResponse)
async def get_charger_logs(
    charge_point_id: str,
    start_date: Optional[str] = Query(None, description="Start date in ISO format with timezone (e.g. 2026-03-10T00:00:00Z)"),
    end_date: Optional[str] = Query(None, description="End date in ISO format with timezone (e.g. 2026-03-10T23:59:59Z)"),
    limit: int = Query(100, ge=1, le=100000, description="Number of logs to return (max 100,000)"),
    admin_user: User = Depends(require_admin())
):
    """
    Get OCPP logs for a specific charger with optional date filtering.
    Limited to 100,000 rows maximum. Results ordered by most recent first.
    """
    try:
        # Build query
        query = OCPPLog.filter(charge_point_id=charge_point_id)

        if start_date:
            start_dt = _parse_date(start_date, "start_date")
            query = query.filter(timestamp__gte=start_dt)

        if end_date:
            end_dt = _parse_date(end_date, "end_date")
            query = query.filter(timestamp__lte=end_dt)

        # Get total count before limiting
        total = await query.count()

        # Check if we're hitting the limit
        has_more = total > limit
        message = None
        if total > 100000:
            message = "This query returns more than 100,000 logs. Please use more specific date filters to narrow results."
            limit = min(limit, 100000)  # Enforce 100,000 row limit

        # Get logs ordered by most recent first
        logs = await query.order_by('-timestamp').limit(limit)

        return LogsResponse(
            data=[LogResponse.model_validate(log) for log in logs],
            total=total,
            limit=limit,
            has_more=has_more,
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching logs for charger {charge_point_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching logs")

@router.get("/charger/{charge_point_id}/summary")
async def get_charger_log_summary(
    charge_point_id: str,
    admin_user: User = Depends(require_admin())
):
    """
    Get summary statistics for charger logs (useful for the frontend to show total counts)
    """
    try:
        total_logs = await OCPPLog.filter(charge_point_id=charge_point_id).count()

        # Get date range
        oldest_log = await OCPPLog.filter(charge_point_id=charge_point_id).order_by('timestamp').first()
        newest_log = await OCPPLog.filter(charge_point_id=charge_point_id).order_by('-timestamp').first()

        # Count by direction
        inbound_count = await OCPPLog.filter(charge_point_id=charge_point_id, direction="IN").count()
        outbound_count = await OCPPLog.filter(charge_point_id=charge_point_id, direction="OUT").count()

        return {
            "charge_point_id": charge_point_id,
            "total_logs": total_logs,
            "inbound_logs": inbound_count,
            "outbound_logs": outbound_count,
            "oldest_log_date": oldest_log.timestamp if oldest_log else None,
            "newest_log_date": newest_log.timestamp if newest_log else None,
        }

    except Exception as e:
        logger.error(f"Error fetching log summary for charger {charge_point_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching log summary")


# ============ Audit Log Endpoints ============

class AuditLogResponse(BaseModel):
    id: int
    created_at: datetime
    actor_type: str
    actor_id: Optional[int]
    actor_email: Optional[str]
    action: str
    entity_type: str
    entity_id: str
    changes: Optional[dict]

    class Config:
        from_attributes = True

class AuditLogListResponse(BaseModel):
    data: List[AuditLogResponse]
    total: int
    page: int
    limit: int

@router.get("/audit", response_model=AuditLogListResponse)
async def get_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    entity_type: Optional[str] = Query(None, description="Filter by entity type (charger, transaction, station, firmware)"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    action: Optional[str] = Query(None, description="Filter by action (e.g. charger.connected)"),
    actor_type: Optional[str] = Query(None, description="Filter by actor type (system, admin, ocpp, webhook)"),
    start_date: Optional[str] = Query(None, description="Start date in ISO format with timezone (e.g. 2026-03-10T00:00:00Z)"),
    end_date: Optional[str] = Query(None, description="End date in ISO format with timezone (e.g. 2026-03-10T23:59:59Z)"),
    admin_user: User = Depends(require_admin()),
):
    """
    Get audit log entries with filtering and pagination.
    """
    query = AuditLog.all()

    if entity_type:
        query = query.filter(entity_type=entity_type)
    if entity_id:
        query = query.filter(entity_id=entity_id)
    if action:
        query = query.filter(action=action)
    if actor_type:
        query = query.filter(actor_type=actor_type)

    if start_date:
        start_dt = _parse_date(start_date, "start_date")
        query = query.filter(created_at__gte=start_dt)

    if end_date:
        end_dt = _parse_date(end_date, "end_date")
        query = query.filter(created_at__lte=end_dt)

    total = await query.count()

    offset = (page - 1) * limit
    logs = await query.order_by("-created_at").offset(offset).limit(limit)

    return AuditLogListResponse(
        data=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/audit/charger-timeline/{charge_point_id}", response_model=AuditLogListResponse)
async def get_charger_timeline(
    charge_point_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    action: Optional[str] = Query(None),
    actor_type: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    admin_user: User = Depends(require_admin()),
):
    """
    Get all audit events related to a charger: charger events + transaction events
    for transactions that belong to this charger.
    """
    # Find transaction IDs belonging to this charger
    charger = await Charger.filter(charge_point_string_id=charge_point_id).first()
    transaction_ids = []
    if charger:
        transaction_ids = await Transaction.filter(charger_id=charger.id).values_list("id", flat=True)

    # Build OR query: charger events + transaction events for this charger
    if transaction_ids:
        str_ids = [str(tid) for tid in transaction_ids]
        query = AuditLog.filter(
            Q(entity_type="charger", entity_id=charge_point_id)
            | Q(entity_type="transaction", entity_id__in=str_ids)
        )
    else:
        query = AuditLog.filter(entity_type="charger", entity_id=charge_point_id)

    if action:
        query = query.filter(action=action)
    if actor_type:
        query = query.filter(actor_type=actor_type)

    if start_date:
        start_dt = _parse_date(start_date, "start_date")
        query = query.filter(created_at__gte=start_dt)

    if end_date:
        end_dt = _parse_date(end_date, "end_date")
        query = query.filter(created_at__lte=end_dt)

    total = await query.count()
    offset = (page - 1) * limit
    logs = await query.order_by("-created_at").offset(offset).limit(limit)

    return AuditLogListResponse(
        data=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        limit=limit,
    )
