# routers/transactions.py
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime, timezone
import logging

from models import Transaction, MeterValue, User, Charger, WalletTransaction, QRPayment, CommissionLedgerEntry, GSTInvoice
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.functions import Sum
from auth_middleware import require_admin
from core.roles import INTERNAL_ROLES
from crud import log_audit_event
from services.qr_payment_service import QRPaymentService

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

class TransactionListResponse(BaseModel):
    data: List[TransactionResponse]
    total: int
    page: int
    limit: int
    summary: Dict

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


def _as_float(v) -> Optional[float]:
    return float(v) if v is not None else None


def _build_revenue(transaction, qrp, settlement, invoice) -> RevenueBreakdown:
    """Assemble the per-session revenue tally from the transaction + its QR
    payment, settlement entry, and GST invoice. Any of qrp/settlement/invoice
    may be None (wallet/internal sessions, or non-billable bands)."""
    razorpay_fee = None
    if qrp and (qrp.razorpay_commission is not None or qrp.razorpay_gst is not None):
        razorpay_fee = float((qrp.razorpay_commission or 0) + (qrp.razorpay_gst or 0))
    return RevenueBreakdown(
        paid_amount=_as_float(qrp.amount_paid) if qrp else None,
        energy_consumed_kwh=_as_float(transaction.energy_consumed_kwh),
        energy_amount=_as_float(transaction.energy_charge),
        gst_amount=_as_float(transaction.gst_amount),
        gst_rate_percent=_as_float(transaction.gst_rate_percent),
        total_billed=_as_float(transaction.total_billed),
        invoice_number=invoice.invoice_number if invoice else None,
        razorpay_fee=razorpay_fee,
        refund_amount=_as_float(qrp.refund_amount) if qrp else None,
        refund_speed=qrp.razorpay_refund_speed_processed if qrp else None,
        settlement_amount=_as_float(settlement.franchisee_payout) if settlement else None,
        tds_amount=_as_float(settlement.tds_amount) if settlement else None,
    )


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

async def _apply_funding_filters(query, funding_source: Optional[List[str]], payment_status: Optional[str]):
    """Constrain a Transaction query by the derived Funding Source / Payment
    Status axes (Transactions Console). Both are computed, not columns, so we
    translate them to id/user-id constraints. payment_status is QR-only —
    filtering by it implies QR funding."""
    if payment_status:
        qr_ids = await QRPayment.filter(status=payment_status).values_list("transaction_id", flat=True)
        query = query.filter(id__in=[i for i in qr_ids if i is not None])

    if funding_source:
        wanted = {s.upper() for s in funding_source}
        qr_ids = set(i for i in await QRPayment.all().values_list("transaction_id", flat=True) if i is not None)
        internal_ids = set(await User.filter(role__in=INTERNAL_ROLES).values_list("id", flat=True))
        clause = Q()
        if "QR" in wanted:
            clause |= Q(id__in=qr_ids)
        if "WALLET" in wanted:
            clause |= (~Q(id__in=qr_ids) & ~Q(user_id__in=internal_ids))
        if "NONE" in wanted:
            clause |= (~Q(id__in=qr_ids) & Q(user_id__in=internal_ids))
        query = query.filter(clause)
    return query


async def _enrich_funding_payment(transactions) -> Dict[int, tuple]:
    """Batch-resolve (funding_source, payment_status) for a page of sessions —
    one QRPayment query + one User query, stitched in memory (no N+1).
    Native QR status shown verbatim; wallet/internal carry no payment status."""
    if not transactions:
        return {}
    txn_ids = [t.id for t in transactions]
    user_ids = {t.user_id for t in transactions}
    qr_rows = await QRPayment.filter(transaction_id__in=txn_ids).values(
        "transaction_id", "status", "razorpay_refund_speed_processed", "refund_amount"
    )
    qr_by_txn = {r["transaction_id"]: r for r in qr_rows}
    internal_ids = set(await User.filter(id__in=user_ids, role__in=INTERNAL_ROLES).values_list("id", flat=True))
    out = {}
    for t in transactions:
        if t.id in qr_by_txn:
            r = qr_by_txn[t.id]
            amt = r["refund_amount"]
            out[t.id] = ("QR", r["status"], r["razorpay_refund_speed_processed"],
                         float(amt) if amt is not None else None)
        elif t.user_id in internal_ids:
            out[t.id] = ("NONE", None, None, None)
        else:
            out[t.id] = ("WALLET", None, None, None)
    return out


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
    query = await _apply_funding_filters(query, funding_source, payment_status)

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
    summary = {
        "total_energy_consumed": total_energy_consumed,
        "active_sessions": await Transaction.filter(transaction_status__in=["STARTED", "RUNNING"]).count(),
        "suspended_sessions": await Transaction.filter(transaction_status="SUSPENDED").count(),
        "completed_sessions": await Transaction.filter(transaction_status="COMPLETED").count()
    }

    enrichment = await _enrich_funding_payment(transactions)
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

    live_energy_kwh: Optional[float] = None
    if transaction.start_meter_kwh is not None and meter_values:
        latest_reading = meter_values[-1].reading_kwh
        live_energy_kwh = float(latest_reading - transaction.start_meter_kwh)

    funding_source, qr_session = await _resolve_funding(transaction_id, user)

    # Read-only money/payout drill-down (Transactions Console). Payment status
    # is the verbatim QR native value (None for wallet/internal). Settlement
    # status is the franchisee-payout state, shown here only — never a filter.
    payment_status = None
    refund_speed = None
    refund_amount = None
    customer_vpa = None
    qrp = None
    if funding_source == "QR":
        qrp = await QRPayment.filter(transaction_id=transaction_id).first()
        if qrp:
            payment_status = qrp.status
            refund_speed = qrp.razorpay_refund_speed_processed
            refund_amount = float(qrp.refund_amount) if qrp.refund_amount is not None else None
            customer_vpa = qrp.customer_vpa
    settlement = await CommissionLedgerEntry.filter(transaction_id=transaction_id).first()
    settlement_status = settlement.settlement_status if settlement else None
    invoice = await GSTInvoice.filter(transaction_id=transaction_id).first()
    revenue = _build_revenue(transaction, qrp, settlement, invoice)

    return TransactionDetailResponse(
        transaction=TransactionResponse.model_validate(transaction, from_attributes=True),
        user=UserBasicInfo.model_validate(user, from_attributes=True),
        charger=ChargerBasicInfo.model_validate(charger, from_attributes=True),
        meter_values=[MeterValueResponse.model_validate(mv, from_attributes=True) for mv in meter_values],
        wallet_transactions=[WalletTransactionResponse.model_validate(wt, from_attributes=True) for wt in wallet_transactions],
        live_energy_kwh=live_energy_kwh,
        funding_source=funding_source,
        qr_session=qr_session,
        payment_status=payment_status,
        settlement_status=settlement_status,
        refund_speed=refund_speed,
        refund_amount=refund_amount,
        customer_vpa=customer_vpa,
        revenue=revenue,
    )


async def _resolve_funding(transaction_id: int, user: User) -> tuple[str, Optional[QRSessionBudget]]:
    """Classify the funding source for a Transaction and, for QR sessions,
    fetch the live budget snapshot.

    Decision order: a present QRPayment row wins (matches CONTEXT.md
    [[qr-session]]); otherwise an internal-role user is "NONE" per ADR 0004;
    otherwise "WALLET". The QR snapshot is None when the session has no
    cached/derivable budget row (e.g. the QR session was already finalised).
    """
    qr_payment_exists = await QRPayment.filter(transaction_id=transaction_id).exists()
    if qr_payment_exists:
        snapshot = await QRPaymentService.compute_budget_snapshot(transaction_id)
        qr_session = None
        if snapshot is not None:
            qr_session = QRSessionBudget(
                budget_limit=f"{snapshot.budget_limit:.2f}",
                cost_so_far=f"{snapshot.cost_so_far:.2f}",
                remaining=f"{snapshot.remaining:.2f}",
            )
        return "QR", qr_session

    if user.role in INTERNAL_ROLES:
        return "NONE", None
    return "WALLET", None

@router.post("/{transaction_id}/stop", response_model=dict)
async def force_stop_transaction(transaction_id: int, request: StopTransactionRequest, admin_user: User = Depends(require_admin())):
    """Force stop a transaction (admin override)"""

    transaction = await Transaction.filter(id=transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    if transaction.transaction_status in ["STOPPED", "COMPLETED", "CANCELLED"]:
        raise HTTPException(status_code=409, detail="Transaction is already stopped")
    
    # Get charger for OCPP command
    charger = await Charger.filter(id=transaction.charger_id).first()
    if not charger:
        raise HTTPException(status_code=500, detail="Charger not found")
    
    # Check if charger is connected (via Redis - works across all workers)
    from redis_manager import redis_manager
    charger_connected = await redis_manager.is_charger_connected(charger.charge_point_string_id)

    # Try to send OCPP stop command if charger is connected
    if charger_connected:
        from main import send_ocpp_request
        
        success, response = await send_ocpp_request(
            charger.charge_point_string_id,
            "RemoteStopTransaction",
            {"transactionId": transaction_id}
        )
        
        if not success:
            logger.warning(f"Failed to send OCPP stop command for transaction {transaction_id}: {response}")
    
    # Force stop the transaction in database
    previous_status = transaction.transaction_status
    transaction.transaction_status = "STOPPED"
    transaction.stop_reason = f"Force stopped by admin: {request.reason}"
    transaction.end_time = datetime.now(timezone.utc)
    await transaction.save()

    await log_audit_event(
        action="transaction.status_changed",
        entity_type="transaction",
        entity_id=transaction_id,
        actor_type="admin",
        actor=admin_user,
        changes={"previous_status": str(previous_status), "new_status": "STOPPED", "trigger": "AdminForceStop"},
    )
    await log_audit_event(
        action="transaction.force_stopped",
        entity_type="transaction",
        entity_id=transaction_id,
        actor_type="admin",
        actor=admin_user,
        changes={"reason": request.reason},
    )

    # For SUSPENDED transactions, energy_consumed_kwh may be None — calculate from last meter value
    if not transaction.energy_consumed_kwh or transaction.energy_consumed_kwh <= 0:
        latest_meter_value = await MeterValue.filter(
            transaction_id=transaction_id
        ).order_by("-created_at").first()
        if latest_meter_value:
            transaction.end_meter_kwh = latest_meter_value.reading_kwh
            transaction.energy_consumed_kwh = transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
            await transaction.save()
            logger.info(f"Calculated energy for force-stopped transaction {transaction_id}: {transaction.energy_consumed_kwh} kWh")

    # Process wallet billing
    final_amount = None
    billing_message = "No billing processed"

    if transaction.energy_consumed_kwh and transaction.energy_consumed_kwh > 0:
        from services.wallet_service import WalletService
        try:
            success, message, billing_amount = await WalletService.process_transaction_billing(transaction_id)
            if success:
                final_amount = float(billing_amount) if billing_amount else 0.0
                billing_message = f"Billing successful: ₹{billing_amount}" if billing_amount else message
                logger.info(f"💰 Force stop billing successful for transaction {transaction_id}: ₹{billing_amount}")
            else:
                billing_message = f"Billing failed: {message}"
                logger.warning(f"💰 Force stop billing failed for transaction {transaction_id}: {message}")
        except Exception as billing_error:
            billing_message = f"Billing error: {str(billing_error)}"
            logger.error(f"💰 Force stop billing error for transaction {transaction_id}: {billing_error}")
            try:
                await Transaction.filter(id=transaction_id).update(
                    transaction_status="BILLING_FAILED"
                )
            except Exception as update_error:
                logger.error(f"Failed to update transaction status to BILLING_FAILED: {update_error}")
    else:
        billing_message = "No energy consumed - no billing required"
    
    return {
        "success": True,
        "message": "Transaction force stopped successfully",
        "final_amount": final_amount,
        "billing_message": billing_message
    }

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