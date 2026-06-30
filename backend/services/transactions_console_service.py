# services/transactions_console_service.py
"""Domain logic for the admin Transactions Console.

Centralizes the money/funding computation that previously lived inline in
``routers/transactions.py`` (review item M3): the funding-source classification
(QR / WALLET / NONE), the page-level funding/payment enrichment, the
subquery-based funding/payment filters (M4), and the per-session revenue tally.

Funding source is a *derived* axis (not a column). The single canonical
definition lives here; the router (and any future caller) reuses it rather than
re-deriving QR-vs-WALLET-vs-internal independently.
"""
from typing import Dict, List, Optional, Tuple

from tortoise.expressions import Q, Subquery

from core.roles import INTERNAL_ROLES
from models import (
    CommissionLedgerEntry,
    GSTInvoice,
    QRPayment,
    Transaction,
    User,
)


def _as_float(v) -> Optional[float]:
    return float(v) if v is not None else None


class TransactionsConsoleService:
    """Cohesive home for the Transactions Console's derived money/funding logic."""

    # -- Filtering (list endpoint) ------------------------------------------

    @staticmethod
    def apply_funding_filters(
        query,
        funding_source: Optional[List[str]],
        payment_status: Optional[str],
    ):
        """Constrain a Transaction query by the derived Funding Source / Payment
        Status axes. Both are computed, not columns, so we translate them to
        SQL ``IN (SELECT ...)`` subqueries — never materialized id lists — so
        the filter stays bounded as QRPayment / internal-user tables grow
        (review item M4). ``payment_status`` is QR-only, so filtering by it
        implies QR funding.
        """
        if payment_status:
            qr_with_status = Subquery(
                QRPayment.filter(
                    status=payment_status, transaction_id__not_isnull=True
                ).values_list("transaction_id", flat=True)
            )
            query = query.filter(id__in=qr_with_status)

        if funding_source:
            wanted = {s.upper() for s in funding_source}
            qr_txn_ids = Subquery(
                QRPayment.filter(transaction_id__not_isnull=True).values_list(
                    "transaction_id", flat=True
                )
            )
            internal_user_ids = Subquery(
                User.filter(role__in=INTERNAL_ROLES).values_list("id", flat=True)
            )
            clause = Q()
            if "QR" in wanted:
                clause |= Q(id__in=qr_txn_ids)
            if "WALLET" in wanted:
                clause |= ~Q(id__in=qr_txn_ids) & ~Q(user_id__in=internal_user_ids)
            if "NONE" in wanted:
                clause |= ~Q(id__in=qr_txn_ids) & Q(user_id__in=internal_user_ids)
            query = query.filter(clause)
        return query

    # -- Page enrichment (list endpoint) ------------------------------------

    @staticmethod
    async def enrich_funding_payment(transactions) -> Dict[int, tuple]:
        """Batch-resolve ``(funding_source, payment_status, refund_speed,
        refund_amount)`` for a page of sessions — one QRPayment query + one
        User query, stitched in memory (no N+1). Native QR status shown
        verbatim; wallet/internal carry no payment status.
        """
        if not transactions:
            return {}
        txn_ids = [t.id for t in transactions]
        user_ids = {t.user_id for t in transactions}
        qr_rows = await QRPayment.filter(transaction_id__in=txn_ids).values(
            "transaction_id", "status", "razorpay_refund_speed_processed", "refund_amount"
        )
        qr_by_txn = {r["transaction_id"]: r for r in qr_rows}
        internal_ids = set(
            await User.filter(id__in=user_ids, role__in=INTERNAL_ROLES).values_list(
                "id", flat=True
            )
        )
        out = {}
        for t in transactions:
            if t.id in qr_by_txn:
                r = qr_by_txn[t.id]
                out[t.id] = (
                    "QR",
                    r["status"],
                    r["razorpay_refund_speed_processed"],
                    _as_float(r["refund_amount"]),
                )
            elif t.user_id in internal_ids:
                out[t.id] = ("NONE", None, None, None)
            else:
                out[t.id] = ("WALLET", None, None, None)
        return out

    # -- Funding classification (detail endpoint) ---------------------------

    @staticmethod
    async def classify_funding_source(transaction_id: int, user: User) -> str:
        """Canonical funding-source derivation for a single session.

        Decision order: a present QRPayment row wins (matches CONTEXT.md
        [[qr-session]]); otherwise an internal-role user is ``"NONE"`` per
        ADR 0004; otherwise ``"WALLET"``.
        """
        if await QRPayment.filter(transaction_id=transaction_id).exists():
            return "QR"
        if user.role in INTERNAL_ROLES:
            return "NONE"
        return "WALLET"

    # -- Revenue tally (detail endpoint) ------------------------------------

    @staticmethod
    def build_revenue(transaction, qrp, settlement, invoice) -> dict:
        """Assemble the per-session revenue tally from the transaction + its QR
        payment, settlement entry, and GST invoice. Any of qrp/settlement/invoice
        may be None (wallet/internal sessions, or non-billable bands).

        Returned as a plain dict so the response Pydantic model (owned by the
        router, where FastAPI needs it) stays the serialization boundary while
        the *computation* lives here. Sourced so the figures reconcile:
        ``paid = total_billed + refund``; ``total_billed = energy_amount + gst``;
        ``settlement = gross − platform_commission − tds − pg_fee``. razorpay_fee
        is the ACTUAL Razorpay deduction (commission + its GST), not 2%.
        """
        razorpay_fee = None
        if qrp and (qrp.razorpay_commission is not None or qrp.razorpay_gst is not None):
            razorpay_fee = float((qrp.razorpay_commission or 0) + (qrp.razorpay_gst or 0))
        return {
            "paid_amount": _as_float(qrp.amount_paid) if qrp else None,
            "energy_consumed_kwh": _as_float(transaction.energy_consumed_kwh),
            "energy_amount": _as_float(transaction.energy_charge),
            "gst_amount": _as_float(transaction.gst_amount),
            "gst_rate_percent": _as_float(transaction.gst_rate_percent),
            "total_billed": _as_float(transaction.total_billed),
            "invoice_number": invoice.invoice_number if invoice else None,
            "razorpay_fee": razorpay_fee,
            "refund_amount": _as_float(qrp.refund_amount) if qrp else None,
            "refund_speed": qrp.razorpay_refund_speed_processed if qrp else None,
            "settlement_amount": _as_float(settlement.franchisee_payout) if settlement else None,
            "tds_amount": _as_float(settlement.tds_amount) if settlement else None,
        }

    @staticmethod
    async def gather_detail_money(transaction_id: int, funding_source: str) -> dict:
        """Fetch the read-only money/payout drill-down for the detail endpoint:
        QRPayment (for QR sessions), CommissionLedgerEntry settlement, and the
        GST invoice. Returns the assembled ``revenue`` dict plus the scalar
        drill-down fields the response surfaces directly.
        """
        transaction = await Transaction.get(id=transaction_id)
        qrp = None
        payment_status = refund_speed = refund_amount = customer_vpa = None
        if funding_source == "QR":
            qrp = await QRPayment.filter(transaction_id=transaction_id).first()
            if qrp:
                payment_status = qrp.status
                refund_speed = qrp.razorpay_refund_speed_processed
                refund_amount = _as_float(qrp.refund_amount)
                customer_vpa = qrp.customer_vpa
        settlement = await CommissionLedgerEntry.filter(transaction_id=transaction_id).first()
        invoice = await GSTInvoice.filter(transaction_id=transaction_id).first()
        return {
            "payment_status": payment_status,
            "settlement_status": settlement.settlement_status if settlement else None,
            "refund_speed": refund_speed,
            "refund_amount": refund_amount,
            "customer_vpa": customer_vpa,
            "revenue": TransactionsConsoleService.build_revenue(
                transaction, qrp, settlement, invoice
            ),
        }
