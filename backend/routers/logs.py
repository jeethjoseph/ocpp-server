# routers/logs.py
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime, timezone
import logging

from models import OCPPLog, User
from auth_middleware import require_admin
from tortoise.queryset import Q

logger = logging.getLogger(__name__)

# Pydantic schemas
from typing import Union, Any

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
    start_date: Optional[str] = Query(None, description="Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"),
    end_date: Optional[str] = Query(None, description="End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"),
    limit: int = Query(100, ge=1, le=10000, description="Number of logs to return (max 10,000)"),
    admin_user: User = Depends(require_admin())
):
    """
    Get OCPP logs for a specific charger with optional date filtering.
    Limited to 10,000 rows maximum. Results ordered by most recent first.
    """
    try:
        # Build query
        query = OCPPLog.filter(charge_point_id=charge_point_id)
        
        # Parse and apply date filters
        if start_date:
            try:
                # Handle both date-only and datetime formats
                if 'T' in start_date:
                    # If timezone is provided, use as-is
                    if start_date.endswith('Z') or '+' in start_date[-6:] or '-' in start_date[-6:]:
                        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                    else:
                        # No timezone provided - treat as local time and convert to UTC
                        # Assume local timezone (you may want to make this configurable)
                        from zoneinfo import ZoneInfo
                        local_tz = ZoneInfo("Asia/Kolkata")  # Adjust to your local timezone
                        naive_dt = datetime.fromisoformat(start_date)
                        local_dt = naive_dt.replace(tzinfo=local_tz)
                        start_dt = local_dt.astimezone(timezone.utc)
                else:
                    # Date only - treat as local date start of day
                    from zoneinfo import ZoneInfo
                    local_tz = ZoneInfo("Asia/Kolkata")  # Adjust to your local timezone
                    naive_dt = datetime.fromisoformat(start_date + "T00:00:00")
                    local_dt = naive_dt.replace(tzinfo=local_tz)
                    start_dt = local_dt.astimezone(timezone.utc)

                query = query.filter(timestamp__gte=start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")
        
        if end_date:
            try:
                # Handle both date-only and datetime formats
                if 'T' in end_date:
                    # If timezone is provided, use as-is
                    if end_date.endswith('Z') or '+' in end_date[-6:] or '-' in end_date[-6:]:
                        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    else:
                        # No timezone provided - treat as local time and convert to UTC
                        from zoneinfo import ZoneInfo
                        local_tz = ZoneInfo("Asia/Kolkata")  # Adjust to your local timezone
                        naive_dt = datetime.fromisoformat(end_date)
                        local_dt = naive_dt.replace(tzinfo=local_tz)
                        end_dt = local_dt.astimezone(timezone.utc)
                else:
                    # Date only - treat as local date end of day
                    from zoneinfo import ZoneInfo
                    local_tz = ZoneInfo("Asia/Kolkata")  # Adjust to your local timezone
                    naive_dt = datetime.fromisoformat(end_date + "T23:59:59")
                    local_dt = naive_dt.replace(tzinfo=local_tz)
                    end_dt = local_dt.astimezone(timezone.utc)

                query = query.filter(timestamp__lte=end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")
        
        # Get total count before limiting
        total = await query.count()
        
        # Check if we're hitting the limit
        has_more = total > limit
        message = None
        if total > 10000:
            message = "This query returns more than 10,000 logs. Please contact the database administrator for a complete export or use more specific date filters."
            limit = min(limit, 10000)  # Enforce 10,000 row limit
        
        # Get logs ordered by most recent first
        logs = await query.order_by('-timestamp').limit(limit)
        
        return LogsResponse(
            data=[LogResponse.model_validate(log) for log in logs],
            total=total,
            limit=limit,
            has_more=has_more,
            message=message
        )
        
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