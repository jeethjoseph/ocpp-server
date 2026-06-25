# routers/transactions.py
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime, timezone
import logging

from models import Transaction, MeterValue, User, Charger, WalletTransaction
from tortoise.functions import Sum
from auth_middleware import require_admin
from crud import log_audit_event
from services.qr_payment_service import QRPaymentService
from services.transactions_console_service import TransactionsConsoleService

logger = logging.getLogger(__name__)

# Pydantic schemas
class MeterValueResponse(BaseModel):
    id: int
    reading_kwh: float
    current: Optional[float]
    voltage: Optional[float]
    power_kw: Optional[float]
    created_at: datetime
    
    class Config:
        from_attributes = True

class TransactionResponse(BaseModel):
    id: int
    user_id: int
    charger_id: int
    start_meter_kwh: Optional[float]
    end_meter_kwh: Optional[float]
    energy_consumed_kwh: Optional[float]
    start_time: datetime
    end_time: Optional[datetime]
    stop_reason: Optional[str]
    transaction_status: str
    suspended_at: Optional[datetime] = None
    resumed_at: Optional[datetime] = None
    resume_count: int = 0
    created_at: datetime
    updated_at: datetime
    # Transactions Console enrichment (CONTEXT.md "Transactions Console").
    # funding_source: "QR" / "WALLET" / "NONE" (internal-role). payment_status:
    # the verbatim native QRPaymentStatusEnum value for QR sessions; None for
    # wallet/internal (CHARGE_DEDUCT carries no status — not derived to fill it).
    funding_source: str = "WALLET"
    payment_status: Optional[str] = None
    # Refund drill-down (QR sessions only). refund_speed is Razorpay's processed
    # speed: "instant" / "normal" / None. A refund requested instant but showing
    # "normal" is the float-too-low downgrade (see CONTEXT.md Razorpay float).
    refund_speed: Optional[str] = None
    refund_amount: Optional[float] = None

    class Config:
        from_attributes = True

class UserBasicInfo(BaseModel):
    id: int
    full_name: Optional[str]
    email: Optional[str]
    phone_number: Optional[str]
    
    class Config:
        from_attributes = True

class ChargerBasicInfo(BaseModel):
    id: int
    name: str
    charge_point_string_id: str
    
    class Config:
        from_attributes = True

class WalletTransactionResponse(BaseModel):
    id: int
    amount: float
    type: str
    description: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

class TransactionListSummary(BaseModel):
    """Aggregate tallies for the current filtered set (NOT the page). Keys are
    consumed verbatim by the frontend (frontend/lib/api-services.ts
    TransactionListSummary) — do not rename without a coordinated FE change."""
    total_energy_consumed: float
    active_sessions: int
    suspended_sessions: int
    completed_sessions: int


class TransactionListResponse(BaseModel):
    data: List[TransactionResponse]
    total: int
    page: int
    limit: int
    summary: TransactionListSummary

class QRSessionBudget(BaseModel):
    # ₹ figures as Decimal-encoded strings to preserve precision over the wire.
    budget_limit: str
    cost_so_far: str
    remaining: str


class TransactionDetailResponse(BaseModel):
    transaction: TransactionResponse
    user: UserBasicInfo
    charger: ChargerBasicInfo
    meter_values: List[MeterValueResponse]
    wallet_transactions: List[WalletTransactionResponse]
    # Derived per-request from the latest MeterValue, not stored. Kept separate
    # from Transaction.energy_consumed_kwh, which is only populated at
    # StopTransaction and would otherwise read as 0 during an active session.
    live_energy_kwh: Optional[float] = None
    # "QR" when a QRPayment row references this transaction; "NONE" for
    # Internal-role Sessions (ADMIN/FRANCHISEE — see ADR 0004); "WALLET"
    # for everyone else. Matches the CONTEXT.md funding-source axis.
    funding_source: str = "WALLET"
    # Present only when funding_source == "QR".
    qr_session: Optional[QRSessionBudget] = None
    # Read-only Transactions Console drill-down fields. payment_status: verbatim
    # QRPaymentStatusEnum for QR sessions, else None. settlement_status: the
    # franchisee-payout SettlementStatusEnum (CommissionLedgerEntry) — detail
    # only, intentionally NOT a list filter axis (payout triage lives elsewhere).
    payment_status: Optional[str] = None
    settlement_status: Optional[str] = None
    # Refund drill-down (QR sessions only). See TransactionResponse.refund_speed.
    refund_speed: Optional[str] = None
    refund_amount: Optional[float] = None
    # Payer UPI ID for QR sessions (QRPayment.customer_vpa); None otherwise.
    customer_vpa: Optional[str] = None
    # Per-session revenue tally (read-only). Present for all sessions; fields
    # that don't apply to the funding source / band are null.
    revenue: Optional["RevenueBreakdown"] = None


class RevenueBreakdown(BaseModel):
    """Read-only revenue tally for one session, sourced so the figures reconcile:
    `paid = total_billed + refund`; `total_billed = energy_amount + gst`;
    `settlement = gross − platform_commission − tds − pg_fee`. razorpay_fee is the
    ACTUAL Razorpay deduction (commission + its GST), not the synthetic 2%."""
    paid_amount: Optional[float] = None         # QRPayment.amount_paid (QR only)
    energy_consumed_kwh: Optional[float] = None  # Transaction.energy_consumed_kwh
    energy_amount: Optional[float] = None        # Transaction.energy_charge (pre-GST)
    gst_amount: Optional[float] = None           # Transaction.gst_amount
    gst_rate_percent: Optional[float] = None
    total_billed: Optional[float] = None         # Transaction.total_billed
    invoice_number: Optional[str] = None         # GSTInvoice.invoice_number
    razorpay_fee: Optional[float] = None         # actual: razorpay_commission + razorpay_gst
    refund_amount: Optional[float] = None         # QRPayment.refund_amount
    refund_speed: Optional[str] = None
    settlement_amount: Optional[float] = None     # CommissionLedgerEntry.franchisee_payout
    tds_amount: Optional[float] = None           # CommissionLedgerEntry.tds_amount


# Resolve the forward reference now that RevenueBreakdown is defined.
TransactionDetailResponse.model_rebuild()

class MeterValuesListResponse(BaseModel):
    meter_values: List[MeterValueResponse]
    energy_chart_data: Dict

class StopTransactionRequest(BaseModel):
    reason: str

# Create router
router = APIRouter(
    prefix="/api/admin/transactions",
    tags=["Transaction Management"]
)

@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    charger_id: Optional[int] = None,
    funding_source: Optional[List[str]] = Query(None),
    payment_status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    sort: Optional[str] = Query("-created_at", regex="^-?(created_at|updated_at|start_time|end_time)$")
):
    """List all transactions with filtering options"""

    query = Transaction.all()

    # Apply filters
    if status:
        query = query.filter(transaction_status=status)
    if user_id:
        query = query.filter(user_id=user_id)
    if charger_id:
        query = query.filter(charger_id=charger_id)
    if start_date:
        query = query.filter(start_time__gte=start_date)
    if end_date:
        query = query.filter(start_time__lte=end_date)
    query = TransactionsConsoleService.apply_funding_filters(query, funding_source, payment_status)

    # Get total count
    total = await query.count()

    # Total energy over the FULL filtered set (not just the current page) — DB-side Sum.
    # Page-scoped summing made this read 0.00 whenever page 1 held zero-energy rows.
    energy_agg = await query.annotate(total_energy=Sum("energy_consumed_kwh")).values("total_energy")
    total_energy_consumed = float(energy_agg[0]["total_energy"] or 0) if energy_agg else 0.0

    # Apply sorting
    if sort.startswith("-"):
        query = query.order_by(f"-{sort[1:]}")
    else:
        query = query.order_by(sort)

    # Apply pagination
    offset = (page - 1) * limit
    transactions = await query.offset(offset).limit(limit)

    # Build summary statistics
    summary = TransactionListSummary(
        total_energy_consumed=total_energy_consumed,
        active_sessions=await Transaction.filter(transaction_status__in=["STARTED", "RUNNING"]).count(),
        suspended_sessions=await Transaction.filter(transaction_status="SUSPENDED").count(),
        completed_sessions=await Transaction.filter(transaction_status="COMPLETED").count(),
    )

    enrichment = await TransactionsConsoleService.enrich_funding_payment(transactions)
    transaction_responses = []
    for t in transactions:
        resp = TransactionResponse.model_validate(t, from_attributes=True)
        resp.funding_source, resp.payment_status, resp.refund_speed, resp.refund_amount = enrichment.get(
            t.id, ("WALLET", None, None, None))
        transaction_responses.append(resp)

    return TransactionListResponse(
        data=transaction_responses,
        total=total,
        page=page,
        limit=limit,
        summary=summary
    )

@router.get("/{transaction_id}", response_model=TransactionDetailResponse)
async def get_transaction_details(transaction_id: int):
    """Get transaction details with related data"""
    
    transaction = await Transaction.filter(id=transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Get related data
    user = await User.filter(id=transaction.user_id).first()
    charger = await Charger.filter(id=transaction.charger_id).first()
    meter_values = await MeterValue.filter(transaction_id=transaction_id).order_by("created_at")
    wallet_transactions = await WalletTransaction.filter(charging_transaction_id=transaction_id).all()
    
    if not user or not charger:
        raise HTTPException(status_code=500, detail="Related data not found")

    live_energy_kwh = _derive_live_energy(transaction, meter_values)
    funding_source, qr_session = await _resolve_funding(transaction_id, user)
    # Read-only money/payout drill-down (Transactions Console). Computation lives
    # in the service; the router only serializes. customer_vpa, refund_*, revenue,
    # settlement_status are surfaced here verbatim.
    money = await TransactionsConsoleService.gather_detail_money(transaction_id, funding_source)

    return TransactionDetailResponse(
        transaction=TransactionResponse.model_validate(transaction, from_attributes=True),
        user=UserBasicInfo.model_validate(user, from_attributes=True),
        charger=ChargerBasicInfo.model_validate(charger, from_attributes=True),
        meter_values=[MeterValueResponse.model_validate(mv, from_attributes=True) for mv in meter_values],
        wallet_transactions=[WalletTransactionResponse.model_validate(wt, from_attributes=True) for wt in wallet_transactions],
        live_energy_kwh=live_energy_kwh,
        funding_source=funding_source,
        qr_session=qr_session,
        revenue=RevenueBreakdown(**money.pop("revenue")),
        **money,
    )


def _derive_live_energy(transaction, meter_values) -> Optional[float]:
    """Live energy delta from the latest MeterValue. Read-only and decoupled
    from Transaction.energy_consumed_kwh (only populated at StopTransaction)."""
    if transaction.start_meter_kwh is None or not meter_values:
        return None
    return float(meter_values[-1].reading_kwh - transaction.start_meter_kwh)


async def _resolve_funding(transaction_id: int, user: User) -> tuple[str, Optional[QRSessionBudget]]:
    """Classify the funding source for a Transaction and, for QR sessions,
    fetch the live budget snapshot.

    Classification is delegated to the canonical service helper. The QR snapshot
    is None when the session has no cached/derivable budget row (e.g. the QR
    session was already finalised).
    """
    funding_source = await TransactionsConsoleService.classify_funding_source(transaction_id, user)
    if funding_source != "QR":
        return funding_source, None

    snapshot = await QRPaymentService.compute_budget_snapshot(transaction_id)
    qr_session = None
    if snapshot is not None:
        qr_session = QRSessionBudget(
            budget_limit=f"{snapshot.budget_limit:.2f}",
            cost_so_far=f"{snapshot.cost_so_far:.2f}",
            remaining=f"{snapshot.remaining:.2f}",
        )
    return "QR", qr_session

@router.post("/{transaction_id}/stop", response_model=dict)
async def force_stop_transaction(transaction_id: int, request: StopTransactionRequest, admin_user: User = Depends(require_admin())):
    """Force stop a transaction (admin override).

    Billing semantics intentionally NOT delegated to transaction_finalizer:
    the energy-recalc + WalletService.process_transaction_billing path here is
    the established force-stop behavior. Logic is split into local helpers only
    (review item M1), no behavioral change.
    """
    transaction = await Transaction.filter(id=transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.transaction_status in ["STOPPED", "COMPLETED", "CANCELLED"]:
        raise HTTPException(status_code=409, detail="Transaction is already stopped")

    charger = await Charger.filter(id=transaction.charger_id).first()
    if not charger:
        raise HTTPException(status_code=500, detail="Charger not found")

    await _dispatch_remote_stop(charger, transaction_id)
    await _mark_force_stopped(transaction, request.reason, admin_user)
    await _recalc_energy_if_missing(transaction)
    final_amount, billing_message = await _run_force_stop_billing(transaction)

    return {
        "success": True,
        "message": "Transaction force stopped successfully",
        "final_amount": final_amount,
        "billing_message": billing_message,
    }


async def _dispatch_remote_stop(charger, transaction_id: int) -> None:
    """Best-effort OCPP RemoteStopTransaction when the charger is connected.
    Connection state is read via Redis so it works across all workers."""
    from redis_manager import redis_manager
    if not await redis_manager.is_charger_connected(charger.charge_point_string_id):
        return
    from main import send_ocpp_request
    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "RemoteStopTransaction",
        {"transactionId": transaction_id},
    )
    if not success:
        logger.warning(f"Failed to send OCPP stop command for transaction {transaction_id}: {response}")


async def _mark_force_stopped(transaction, reason: str, admin_user: User) -> None:
    """Persist STOPPED status + force-stop metadata and emit the two audit
    events (status change + force stop)."""
    previous_status = transaction.transaction_status
    transaction.transaction_status = "STOPPED"
    transaction.stop_reason = f"Force stopped by admin: {reason}"
    transaction.end_time = datetime.now(timezone.utc)
    await transaction.save()
    await log_audit_event(
        action="transaction.status_changed",
        entity_type="transaction",
        entity_id=transaction.id,
        actor_type="admin",
        actor=admin_user,
        changes={"previous_status": str(previous_status), "new_status": "STOPPED", "trigger": "AdminForceStop"},
    )
    await log_audit_event(
        action="transaction.force_stopped",
        entity_type="transaction",
        entity_id=transaction.id,
        actor_type="admin",
        actor=admin_user,
        changes={"reason": reason},
    )


async def _recalc_energy_if_missing(transaction) -> None:
    """For SUSPENDED transactions energy_consumed_kwh may be None/0 — backfill
    it from the last MeterValue before billing."""
    if transaction.energy_consumed_kwh and transaction.energy_consumed_kwh > 0:
        return
    latest_meter_value = await MeterValue.filter(
        transaction_id=transaction.id
    ).order_by("-created_at").first()
    if latest_meter_value:
        transaction.end_meter_kwh = latest_meter_value.reading_kwh
        transaction.energy_consumed_kwh = transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
        await transaction.save()
        logger.info(f"Calculated energy for force-stopped transaction {transaction.id}: {transaction.energy_consumed_kwh} kWh")


async def _run_force_stop_billing(transaction) -> tuple[Optional[float], str]:
    """Run wallet billing for the force-stopped session. Returns
    (final_amount, billing_message). On error, flips the row to BILLING_FAILED."""
    if not (transaction.energy_consumed_kwh and transaction.energy_consumed_kwh > 0):
        return None, "No energy consumed - no billing required"

    transaction_id = transaction.id
    from services.wallet_service import WalletService
    try:
        success, message, billing_amount = await WalletService.process_transaction_billing(transaction_id)
        if success:
            final_amount = float(billing_amount) if billing_amount else 0.0
            billing_message = f"Billing successful: ₹{billing_amount}" if billing_amount else message
            logger.info(f"💰 Force stop billing successful for transaction {transaction_id}: ₹{billing_amount}")
            return final_amount, billing_message
        logger.warning(f"💰 Force stop billing failed for transaction {transaction_id}: {message}")
        return None, f"Billing failed: {message}"
    except Exception as billing_error:
        logger.error(f"💰 Force stop billing error for transaction {transaction_id}: {billing_error}")
        try:
            await Transaction.filter(id=transaction_id).update(transaction_status="BILLING_FAILED")
        except Exception as update_error:
            logger.error(f"Failed to update transaction status to BILLING_FAILED: {update_error}")
        return None, f"Billing error: {str(billing_error)}"

@router.get("/{transaction_id}/meter-values", response_model=MeterValuesListResponse)
async def get_transaction_meter_values(transaction_id: int):
    """Get meter values for a specific transaction"""
    
    transaction = await Transaction.filter(id=transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    meter_values = await MeterValue.filter(transaction_id=transaction_id).order_by("created_at")
    
    # Build energy chart data for frontend visualization
    energy_chart_data = {
        "labels": [mv.created_at.isoformat() for mv in meter_values],
        "energy_data": [mv.reading_kwh for mv in meter_values],
        "power_data": [mv.power_kw or 0 for mv in meter_values]
    }
    
    meter_value_responses = [MeterValueResponse.model_validate(mv, from_attributes=True) for mv in meter_values]
    
    return MeterValuesListResponse(
        meter_values=meter_value_responses,
        energy_chart_data=energy_chart_data
    )