"""Public endpoint surfacing a customer's in-progress QR sessions by UPI VPA.

Read-only by design — see ADR 0006 for why no remote-stop action is exposed
behind the VPA-only auth model. The frontend polls this endpoint while the
customer is on /my-charges; live KPIs (energy delivered, spent so far, refund
if stopped now, power draw) are derived from the existing `qr_session:{txn_id}`
Redis cache and the latest MeterValue row.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from core.validators import VPA_PATTERN
from models import (
    MeterValue, QRPayment, QRPaymentStatusEnum, Tariff, Transaction,
)
from redis_manager import redis_manager
from services.monitoring_service import MetricsCollector
from services.qr_payment_service import QR_PAYMENT_PENDING_TIMEOUT
from services.qr_session_state import (
    ACTIVE_TXN_STATES, WAITING, customer_sub_state,
)
from services.tariff_utils import synthetic_platform_fee


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/public/qr-active-sessions",
    tags=["Public QR Active Sessions"],
)


RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW = 60


async def _resolve_session_context(qr_payment: QRPayment, txn: Transaction) -> dict:
    """Return tariff_rate / gst_percent / platform_fee / budget_limit_paise /
    start_meter_kwh for a session. Reads the qr_session Redis cache first,
    falls back to recomputing from the DB (mirror of `check_budget_and_auto_stop`).

    On cache miss: logs a structured warning and increments a counter so ops
    can detect Redis instability or operator-edits-mid-session. The fallback
    uses the *current* Tariff, which matches the live billing path — drift is
    accepted (see review item #2 / issue 05).
    """
    session = await redis_manager.get_qr_session(txn.id)
    if session:
        return session

    logger.warning(
        "qr_session cache miss in active-sessions endpoint for txn %s — "
        "recomputing from DB. Tariff may have drifted from session start.",
        txn.id,
    )
    MetricsCollector.increment_counter("Custom/ActiveSession/CacheMiss")

    tariff = await Tariff.filter(charger_id=qr_payment.charger_id).first()
    if tariff is None:
        tariff = await Tariff.filter(is_global=True).first()
    tariff_rate = Decimal(tariff.rate_per_kwh) if tariff else Decimal("0")
    gst_percent = Decimal(tariff.gst_percent) if tariff else Decimal("18")
    platform_fee = synthetic_platform_fee(qr_payment.amount_paid)
    budget_limit_paise = int(
        ((qr_payment.amount_paid - platform_fee) * Decimal("100"))
        .quantize(Decimal("1"))
    )
    return {
        "tariff_rate": str(tariff_rate),
        "gst_percent": str(gst_percent),
        "platform_fee": str(platform_fee),
        "budget_limit_paise": budget_limit_paise,
        "start_meter_kwh": str(txn.start_meter_kwh) if txn.start_meter_kwh else "0",
    }


async def _latest_meter_snapshot(ctx: dict, txn: Transaction) -> tuple[Optional[Decimal], Optional[float]]:
    """Return `(reading_kwh, power_kw)` for the most recent MeterValue.

    Reads from the qr_session cache first (`latest_reading_kwh` / `latest_power_kw`,
    stamped by `check_budget_and_auto_stop` on every MeterValues frame — review
    item #4, 2026-05-22). Falls back to a one-row MeterValue DB query only when
    the cache is missing the snapshot (pre-first-frame, cache miss from a TTL
    expiry, or in-flight legacy cache rows). Returns `(None, None)` when no
    MeterValue exists yet.
    """
    cached_reading = ctx.get("latest_reading_kwh")
    if cached_reading is not None:
        reading = Decimal(str(cached_reading))
        power = ctx.get("latest_power_kw")
        power_f = float(power) if power is not None else None
        return reading, power_f

    # Cache miss — fall back to DB (rare, only on cache rebuild or pre-first-frame).
    MetricsCollector.increment_counter("Custom/ActiveSession/MeterSnapshotDbFallback")
    latest = await MeterValue.filter(transaction_id=txn.id).order_by("-id").first()
    if latest is None:
        return None, None
    return Decimal(latest.reading_kwh), latest.power_kw


async def _compute_live_kpis(qr_payment: QRPayment, txn: Transaction) -> dict:
    """Compute the live KPI block for a charging/paused/stopping session.

    Live meter readings come from the qr_session cache (filled by every
    MeterValues frame); falls back to a MeterValue DB query only when the
    cache row lacks a snapshot. Accepts both string-form (new) and float-form
    (legacy) cache values via `Decimal(str(v))`.
    """
    ctx = await _resolve_session_context(qr_payment, txn)
    reading_kwh, power_kw = await _latest_meter_snapshot(ctx, txn)

    tariff_rate = Decimal(str(ctx["tariff_rate"]))
    gst_percent = Decimal(str(ctx["gst_percent"]))
    platform_fee = Decimal(str(ctx["platform_fee"]))
    start_kwh = Decimal(str(ctx["start_meter_kwh"]))

    if reading_kwh is None:
        return {
            "energy_kwh": "0.000",
            "spent_so_far": str(platform_fee.quantize(Decimal("0.01"))),
            "refund_if_stopped_now": str(
                (qr_payment.amount_paid - platform_fee).quantize(Decimal("0.01"))
            ),
            "power_kw": None,
        }

    energy_kwh = max(Decimal("0"), reading_kwh - start_kwh)
    energy_cost = energy_kwh * tariff_rate
    gst_amount = energy_cost * gst_percent / Decimal("100")
    spent_so_far = (energy_cost + gst_amount + platform_fee).quantize(Decimal("0.01"))
    refund = max(Decimal("0"), qr_payment.amount_paid - spent_so_far).quantize(Decimal("0.01"))

    return {
        "energy_kwh": str(energy_kwh.quantize(Decimal("0.001"))),
        "spent_so_far": str(spent_so_far),
        "refund_if_stopped_now": str(refund),
        "power_kw": power_kw,
    }


def _build_entry(qr_payment: QRPayment, txn: Optional[Transaction], sub_state: str) -> dict:
    """Build the static (non-KPI) portion of a session entry. The live KPI block
    is merged in by the caller for non-waiting states.
    """
    charger = qr_payment.charger
    station = charger.station if charger else None
    franchisee = station.franchisee if station else None

    entry = {
        "qr_payment_id": qr_payment.id,
        "transaction_id": txn.id if txn else None,
        "amount_paid": str(qr_payment.amount_paid),
        "started_at": qr_payment.created_at.isoformat(),
        "charger_name": charger.name if charger else None,
        "station_name": station.name if station else None,
        "franchisee_name": franchisee.business_name if franchisee else None,
        "sub_state": sub_state,
        "energy_kwh": None,
        "spent_so_far": None,
        "refund_if_stopped_now": None,
        "power_kw": None,
    }
    if sub_state == WAITING:
        age = (datetime.now(timezone.utc) - qr_payment.created_at).total_seconds()
        entry["stale_threshold_seconds"] = max(0, QR_PAYMENT_PENDING_TIMEOUT - int(age))
    return entry


async def _process_payment(qr_payment: QRPayment) -> Optional[dict]:
    """Classify and shape a single QRPayment. Returns None to exclude.

    Wrapped in try/except by the caller — one bad row doesn't break the list.
    """
    txn = qr_payment.transaction if qr_payment.transaction_id else None
    if txn is not None and txn.transaction_status not in ACTIVE_TXN_STATES:
        # The transaction has moved past active (e.g. STOPPED, COMPLETED).
        # Treat as no-active-txn — the QRPayment status still drives the
        # classifier, which will return None for CHARGING-without-txn.
        txn = None

    sub_state = customer_sub_state(
        qr_payment, txn, stale_threshold_seconds=QR_PAYMENT_PENDING_TIMEOUT,
    )
    if sub_state is None:
        return None

    entry = _build_entry(qr_payment, txn, sub_state)
    if sub_state != WAITING and txn is not None:
        entry.update(await _compute_live_kpis(qr_payment, txn))
    return entry


@router.get("")
async def list_active_sessions_by_vpa(
    request: Request,
    vpa: str = Query(..., description="UPI VPA to look up active sessions for"),
):
    """Return in-progress QR sessions for `vpa`, classified into 4 sub-states.

    No auth — VPA is the implicit identifier. Same rate-limit and trust model
    as `/api/public/qr-transactions`. See ADR 0006 for why this view is
    deliberately read-only (no remote-stop action behind a VPA check).
    """
    client_ip = request.client.host if request.client else "unknown"
    allowed = await redis_manager.rate_limit_check(
        f"public_qr_active_sessions:{client_ip}", RATE_LIMIT_MAX, RATE_LIMIT_WINDOW,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    vpa = vpa.lower().strip()
    if not VPA_PATTERN.match(vpa):
        raise HTTPException(status_code=400, detail="Invalid UPI ID format")

    candidate_payments = await QRPayment.filter(
        customer_vpa=vpa,
        status__in=[QRPaymentStatusEnum.PAID, QRPaymentStatusEnum.CHARGING],
    ).prefetch_related("charger__station__franchisee", "transaction").order_by("-created_at")

    results = []
    for p in candidate_payments:
        try:
            entry = await _process_payment(p)
        except Exception as exc:  # pragma: no cover — exercised via tests
            logger.exception(
                "Failed to compute active-session entry for qr_payment %s: %s", p.id, exc,
            )
            MetricsCollector.increment_counter("Custom/ActiveSession/SessionComputeError")
            continue
        if entry is not None:
            results.append(entry)
            MetricsCollector.increment_counter(
                f"Custom/ActiveSession/SubState/{entry['sub_state']}",
            )

    MetricsCollector.increment_counter("Custom/ActiveSession/Request")
    return {"data": results, "total": len(results)}
