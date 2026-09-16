"""SessionLimit — the Budget cap, pushed to the charger that enforces it.

ADR 0031 decision 2. OCPP 1.6 has no per-transaction energy limit
(SetChargingProfile is power-over-time; MaxEnergyOnInvalidId is charge-point
wide), so the cap travels as a vendor DataTransfer:

    vendorId=VOLTLYNC  messageId=SessionLimit
    data={"transactionId": <id>, "maxEnergy": <Wh>, "maxCost": null, "maxTime": null}

``maxEnergy`` is the TOTAL energy this transaction may deliver, counted from
``meterStart``, in whole Wh — the whole current limit, never an increment, so
re-sending is idempotent. Keyed on ``transactionId``, never ``idTag`` (a
per-User value reused across every session that customer ever has).

The number comes from the SAME Redis session rows the server-side budget
checks read (``qr_session:{txn}`` / ``wallet_session:{txn}``), so the two
enforcers cannot disagree about the budget. The Wh conversion ROUNDS DOWN:
rounding up would make over-delivery past what the customer paid structural
rather than bounded by RemoteStop latency. Server-side
``check_budget_and_auto_stop`` / ``check_balance_and_auto_stop`` stay as the
redundant failsafe — whichever enforcer fires first wins.

Three triggers, all funnelling through :func:`push_session_limit`:
  1. after ``StartTransaction.conf`` (``ChargePoint.after_start_transaction``)
  2. on WebSocket connect, for every open transaction on the charger
     (``ChargePoint.reassert_session_limits`` — Boot needs no separate hook)
  3. on budget change — ADR 0021 stacking MUST call this after raising
     ``budget_limit_paise``; there is no other live trigger today.
"""
import asyncio
import json
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from ocpp.v16 import call

from core.connection_manager import connection_manager
from redis_manager import redis_manager
from services.monitoring_service import OCPPMetrics
from utils import safe_create_task

logger = logging.getLogger("ocpp-server")

VENDOR_ID = "VOLTLYNC"
MESSAGE_ID = "SessionLimit"
PUSH_TIMEOUT_SECONDS = 15


def budget_to_wh(budget_rupees: Decimal, tariff_rate: Decimal, gst_percent: Decimal) -> Optional[int]:
    """Whole Wh a budget buys at a GST-inclusive per-kWh price. Rounds DOWN.

    Mirrors the server-side cost formula (energy × rate × (1 + gst)) inverted,
    so at ``maxEnergy`` the computed cost never exceeds the budget.
    """
    if tariff_rate <= 0 or budget_rupees < 0:
        return None
    per_kwh = tariff_rate * (Decimal("1") + gst_percent / Decimal("100"))
    kwh = budget_rupees / per_kwh
    return int((kwh * Decimal("1000")).to_integral_value(rounding=ROUND_DOWN))


def _limit_from_session(session: dict) -> Optional[int]:
    if "budget_limit_paise" in session:
        budget = Decimal(session["budget_limit_paise"]) / Decimal("100")
    else:
        budget = Decimal(str(session["budget_limit"]))
    return budget_to_wh(
        budget,
        Decimal(str(session["tariff_rate"])),
        Decimal(str(session.get("gst_percent", 18))),
    )


async def compute_session_limit_wh(transaction_id: int) -> Optional[int]:
    """The charger-side cap for a transaction, or None when no cap applies.

    None for internal-role sessions (ADR 0004 — no session row is ever
    cached for them), for sessions with no tariff, and for anything that is
    neither a QR nor a wallet session.
    """
    from services.qr_payment_service import QRPaymentService
    from services.wallet_session_service import WalletSessionService

    session = await QRPaymentService._load_or_rebuild_qr_session(transaction_id)
    if session is None:
        session = await redis_manager.get_wallet_session(transaction_id)
    if session is None:
        session = await WalletSessionService._rebuild_session_from_db(transaction_id)
    if session is None:
        return None
    return _limit_from_session(session)


def build_payload(transaction_id: int, max_energy_wh: int) -> str:
    """Field names mirror OCPP 2.1 TransactionLimit so a later migration is a
    transport swap; only maxEnergy is populated."""
    return json.dumps({
        "transactionId": transaction_id,
        "maxEnergy": max_energy_wh,
        "maxCost": None,
        "maxTime": None,
    })


async def push_session_limit(charge_point_id: str, transaction_id: int, trigger: str) -> Optional[str]:
    """Compute and send the limit. Returns the outcome label, or None if no cap
    applies. Never raises — a rejected or unanswered push must not fail the
    session; the server-side check still stands behind it.
    """
    max_energy_wh = await compute_session_limit_wh(transaction_id)
    if max_energy_wh is None:
        logger.info(f"📏 No SessionLimit for txn {transaction_id} on {charge_point_id} ({trigger}): no budget cap applies")
        return None
    outcome = await _send(charge_point_id, transaction_id, max_energy_wh)
    logger.log(
        logging.INFO if outcome == "accepted" else logging.WARNING,
        f"📏 SessionLimit push to {charge_point_id} for txn {transaction_id} "
        f"({trigger}): maxEnergy={max_energy_wh} Wh → {outcome}",
    )
    safe_create_task(OCPPMetrics.record_session_limit_push(
        charge_point_id, transaction_id, max_energy_wh, trigger, outcome,
    ))
    return outcome


async def _send(charge_point_id: str, transaction_id: int, max_energy_wh: int) -> str:
    """One DataTransfer round trip, classified. Outcomes: accepted, rejected,
    unknown_message_id, unknown_vendor_id, no_response, timeout, not_connected, error."""
    conn = connection_manager.connected_charge_points.get(charge_point_id)
    cp = conn.get("cp") if conn else None
    if cp is None:
        return "not_connected"
    req = call.DataTransfer(
        vendor_id=VENDOR_ID, message_id=MESSAGE_ID,
        data=build_payload(transaction_id, max_energy_wh),
    )
    try:
        response = await asyncio.wait_for(cp.call(req), timeout=PUSH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return "timeout"
    except Exception as e:
        logger.error(f"📏 SessionLimit push error for {charge_point_id}: {e}", exc_info=True)
        return "error"
    if response is None:
        return "no_response"
    status = str(getattr(response, "status", "") or "")
    return {
        "Accepted": "accepted", "Rejected": "rejected",
        "UnknownMessageId": "unknown_message_id", "UnknownVendorId": "unknown_vendor_id",
    }.get(status, f"unexpected:{status}")
