# routers/logs.py
import csv
import io
import json
from typing import AsyncIterator, List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import logging

from models import OCPPLog, User, AuditLog, Charger, Transaction
from auth_middleware import require_admin
from tortoise.queryset import Q
from utils import to_ist, csv_safe_cell

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
    offset: int
    limit: int
    has_more: bool
    message: Optional[str] = None

# Create router
router = APIRouter(prefix="/api/admin/logs", tags=["admin-logs"])

# Default bounded window for the Logs Console — see ADR 0014. The date range is
# never unbounded; absent an explicit range we look back this many hours.
DEFAULT_WINDOW_HOURS = 24
# Hard caps on the query surface (ADR 0014). The list endpoint pages with
# OFFSET; the CSV export streams in chunks but still stops at a sane ceiling.
MAX_LIST_LIMIT = 5000
EXPORT_CHUNK_SIZE = 1000
MAX_EXPORT_ROWS = 100000

# The OCPPLog.status value that marks a non-error frame. `errors_only` returns
# rows whose status is present AND is not this value (mirrors the prior
# client-side `(status ?? "SUCCESS") === "SUCCESS"` success test, server-side).
SUCCESS_STATUS = "SUCCESS"


def _build_logs_query(
    charge_point_id: Optional[str],
    message_type: Optional[List[str]],
    start_date: Optional[str],
    end_date: Optional[str],
    direction: Optional[str] = None,
    errors_only: bool = False,
):
    """Build the shared, bounded OCPPLog queryset for the list + export endpoints.

    Always applies a bounded time window (defaulting to the last 24h) plus the
    optional charger / OCPP-action / direction / errors-only filters. See ADR
    0014. Ordering is deterministic (timestamp desc, id desc tiebreak) so OFFSET
    pagination is stable.
    """
    now = datetime.now(tz=timezone.utc)
    start_dt = _parse_date(start_date, "start_date") if start_date else now - timedelta(hours=DEFAULT_WINDOW_HOURS)
    end_dt = _parse_date(end_date, "end_date") if end_date else now

    query = OCPPLog.filter(timestamp__gte=start_dt, timestamp__lte=end_dt)
    if charge_point_id:
        query = query.filter(charge_point_id=charge_point_id)
    if message_type:
        query = query.filter(message_type__in=message_type)
    if direction:
        query = query.filter(direction=direction)
    if errors_only:
        query = query.filter(status__not_isnull=True).filter(~Q(status=SUCCESS_STATUS))
    return query.order_by("-timestamp", "-id")


@router.get("", response_model=LogsResponse)
async def get_logs(
    charge_point_id: Optional[str] = Query(None, description="Filter to a single charger (charge_point_string_id)"),
    message_type: Optional[List[str]] = Query(None, description="Filter by one or more OCPP actions (repeat the param)"),
    start_date: Optional[str] = Query(None, description="Start date ISO 8601 w/ tz. Defaults to 24h ago."),
    end_date: Optional[str] = Query(None, description="End date ISO 8601 w/ tz. Defaults to now."),
    direction: Optional[str] = Query(None, description="Filter by direction: IN or OUT"),
    errors_only: bool = Query(False, description="Return only non-success (error/failed) rows"),
    offset: int = Query(0, ge=0, description="Row offset for pagination"),
    limit: int = Query(100, ge=1, le=MAX_LIST_LIMIT, description="Number of logs to return (max 5,000)"),
    admin_user: User = Depends(require_admin()),
):
    """
    Fleet-wide OCPP message log query for the Logs Console. The date window is
    always bounded (defaults to the last 24h) to keep the query off a full
    sequential scan of the log table — see ADR 0014. Newest first, OFFSET-paged.
    """
    try:
        query = _build_logs_query(charge_point_id, message_type, start_date, end_date, direction, errors_only)
        total = await query.count()
        logs = await query.offset(offset).limit(limit)
        has_more = offset + len(logs) < total
        return LogsResponse(
            data=[LogResponse.model_validate(log) for log in logs],
            total=total,
            offset=offset,
            limit=limit,
            has_more=has_more,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching logs: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching logs")


_EXPORT_COLUMNS = [
    "timestamp_ist", "charge_point_id", "direction",
    "message_type", "status", "message_id", "payload",
]


def _log_to_row(log: OCPPLog) -> List[str]:
    """Map one OCPPLog to a CSV row matching _EXPORT_COLUMNS.

    Timestamps are emitted in IST (UTC+5:30) — the admin-facing convention.
    Stored values are UTC; ``to_ist`` converts, and the ``+05:30`` offset in the
    ISO string keeps the column unambiguous and machine-parseable. See the
    "Timestamps" section in CLAUDE.md.
    """
    return [
        to_ist(log.timestamp).isoformat() if log.timestamp else "",
        # charge_point_id and message_type (OCPP Action) are charger-self-reported;
        # payload/status/correlation_id are likewise data — neutralize formula cells.
        csv_safe_cell(log.charge_point_id or ""),
        str(log.direction.value if hasattr(log.direction, "value") else log.direction),
        csv_safe_cell(log.message_type or ""),
        csv_safe_cell(log.status or ""),
        csv_safe_cell(log.correlation_id or ""),
        csv_safe_cell(json.dumps(log.payload) if log.payload is not None else ""),
    ]


async def _stream_logs_csv(query) -> AsyncIterator[str]:
    """Page through the queryset in bounded chunks via KEYSET pagination,
    yielding CSV text.

    Keyset (seek) on the ``(timestamp, id)`` sort key instead of OFFSET: deep
    OFFSET re-scans every skipped row on each chunk (O(n²) over a large export)
    and isn't snapshot-consistent — rows inserted mid-export shift the window and
    cause skipped/duplicated rows. Seeking on the last ``(timestamp, id)`` is
    O(log n) per chunk (rides the index) and stable against concurrent inserts.
    Memory stays bounded to one chunk; capped at MAX_EXPORT_ROWS.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_COLUMNS)
    yield _drain(buffer)

    fetched = 0
    cursor = None  # (timestamp, id) of the last emitted row
    while fetched < MAX_EXPORT_ROWS:
        page = query
        if cursor is not None:
            last_ts, last_id = cursor
            # Next row after the cursor under the -timestamp, -id ordering.
            page = page.filter(
                Q(timestamp__lt=last_ts)
                | (Q(timestamp=last_ts) & Q(id__lt=last_id))
            )
        limit = min(EXPORT_CHUNK_SIZE, MAX_EXPORT_ROWS - fetched)
        chunk = await page.limit(limit)
        if not chunk:
            break
        for log in chunk:
            writer.writerow(_log_to_row(log))
        yield _drain(buffer)
        fetched += len(chunk)
        last = chunk[-1]
        cursor = (last.timestamp, last.id)
        if len(chunk) < EXPORT_CHUNK_SIZE:
            break


def _drain(buffer: io.StringIO) -> str:
    """Return the buffer's contents and reset it for the next chunk."""
    text = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return text


@router.get("/export")
async def export_logs(
    charge_point_id: Optional[str] = Query(None, description="Filter to a single charger (charge_point_string_id)"),
    message_type: Optional[List[str]] = Query(None, description="Filter by one or more OCPP actions (repeat the param)"),
    start_date: Optional[str] = Query(None, description="Start date ISO 8601 w/ tz. Defaults to 24h ago."),
    end_date: Optional[str] = Query(None, description="End date ISO 8601 w/ tz. Defaults to now."),
    direction: Optional[str] = Query(None, description="Filter by direction: IN or OUT"),
    errors_only: bool = Query(False, description="Return only non-success (error/failed) rows"),
    admin_user: User = Depends(require_admin()),
):
    """
    Stream the filtered OCPP logs as CSV. Same filters as the list endpoint;
    paged through in bounded chunks so memory stays flat regardless of result
    size, and capped at MAX_EXPORT_ROWS rows. See ADR 0014.
    """
    query = _build_logs_query(charge_point_id, message_type, start_date, end_date, direction, errors_only)
    return StreamingResponse(
        _stream_logs_csv(query),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ocpp-logs.csv"},
    )


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
