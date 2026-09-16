# services/disconnect_handler.py
"""
Handles transaction suspension when a charger disconnects unexpectedly.

When the heartbeat monitor detects a charger has gone silent, this module
suspends active transactions and starts a timeout. If the charger doesn't
reconnect in time, transactions are stopped with billing processed.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from models import Transaction, TransactionStatusEnum, MeterValue
from crud import log_audit_event
from utils import safe_create_task
from services.monitoring_service import OCPPMetrics
from policy import (
    SUSPEND_WINDOW_LATCHED_SECONDS,
    SUSPEND_WINDOW_UNLATCHED_SECONDS,
    STALE_SUSPENDED_BUFFER_SECONDS,
)

logger = logging.getLogger("ocpp-server")


async def suspend_window_seconds_for_charge_point(charge_point_id: str) -> int:
    """Suspend window for a charger, keyed by its connector's latching trait.

    Latching connectors (Type2/CCS/...) hold the cable locked in the car, so
    the session can safely wait the long window for a reconnect; unlatched sockets get the
    short window. Values and rationale live in policy.py.
    """
    from services.charger_type_service import is_latching_charger
    if await is_latching_charger(charge_point_id):
        return SUSPEND_WINDOW_LATCHED_SECONDS
    return SUSPEND_WINDOW_UNLATCHED_SECONDS


async def suspend_window_seconds_for_transaction(transaction: Transaction) -> int:
    """Suspend window for a SUSPENDED transaction row (via its charger)."""
    from services.charger_type_service import is_latching_charger_by_charger_id
    if await is_latching_charger_by_charger_id(transaction.charger_id):
        return SUSPEND_WINDOW_LATCHED_SECONDS
    return SUSPEND_WINDOW_UNLATCHED_SECONDS

# Pathological-flap detection: count consecutive disconnects WITHOUT energy
# progress between them. The counter is zeroed by zero_energy_watchdog when
# MeterValues show energy advancing, so a healthy long session with intermittent
# disconnects (cellular flake) never trips. Only sustained no-progress flap
# (>= MAX_RESETS_WITHOUT_PROGRESS) is treated as pathological — at that point
# we stop resetting suspended_at and let the existing timer fire. Under the
# silence clock that reads: past the cap, a reboot no longer counts as "heard
# from" — only a MeterValues frame does, and a frame with no energy progress
# is the zero-energy watchdog's problem, not this module's.
_disconnect_reset_count: Dict[int, int] = {}
MAX_RESETS_WITHOUT_PROGRESS = int(
    os.environ.get("MAX_DISCONNECT_RESETS_WITHOUT_PROGRESS", "3")
)


async def suspend_transactions_on_disconnect(charge_point_id: str) -> None:
    """Suspend active transactions when a charger disconnects."""
    try:
        active_transactions = await Transaction.filter(
            charger__charge_point_string_id=charge_point_id,
            transaction_status__in=[
                TransactionStatusEnum.RUNNING,
                TransactionStatusEnum.STARTED,
                TransactionStatusEnum.PENDING_START,
                TransactionStatusEnum.PENDING_STOP,
            ]
        ).all()

        if not active_transactions:
            return

        now = datetime.now(timezone.utc)
        window_seconds = await suspend_window_seconds_for_charge_point(charge_point_id)
        logger.warning(
            f"⏸️ Charger {charge_point_id} disconnected — suspending "
            f"{len(active_transactions)} active transaction(s) "
            f"(window={window_seconds}s)"
        )

        for transaction in active_transactions:
            previous_status = transaction.transaction_status
            transaction.transaction_status = TransactionStatusEnum.SUSPENDED
            transaction.suspended_at = now
            await transaction.save()
            # Initialize the flap counter on first suspend. The counter is
            # checked & incremented in main.py's BootNotification handler
            # (which is where the actual reset happens on a flapping charger).
            _disconnect_reset_count.setdefault(transaction.id, 0)

            logger.info(
                f"⏸️ Suspended transaction {transaction.id} "
                f"(was {previous_status}) due to charger disconnect"
            )

            safe_create_task(log_audit_event(
                action="transaction.suspended",
                entity_type="transaction",
                entity_id=transaction.id,
                actor_type="system",
                changes={
                    "previous_status": str(previous_status),
                    "new_status": "SUSPENDED",
                    "trigger": "disconnect",
                },
            ))

            arm_suspend_timer(transaction.id, window_seconds, "DISCONNECT_TIMEOUT")

            safe_create_task(
                OCPPMetrics.record_disconnect_suspended(charge_point_id, transaction.id)
            )

    except Exception as e:
        logger.error(
            f"Error suspending transactions on disconnect for "
            f"{charge_point_id}: {e}", exc_info=True
        )


# --- Silence clock (ADR 0031 decision 3) ---------------------------------
#
# The suspend window measures SILENCE: time since we last heard anything about
# THIS transaction, by receipt time. It does not measure session age. Three
# consumers share the two helpers below so they cannot disagree: the suspend
# timers (hold_until_silent), the stale-suspended sweep, and the resume
# staleness guard (transaction_finalizer.is_resume_too_stale).
#
# What counts as "heard about the transaction": the suspend itself, a
# MeterValues frame for it (receipt time — a charger replaying an hours-old
# queue has just proved it is alive), and as a floor the transaction start.
# A BootNotification counts by re-stamping suspended_at (capped by the flap
# guard below). A Heartbeat, StatusNotification or bare WebSocket reconnect
# does NOT count: the charger has said it is alive, but nothing about the
# session, and under continuity firmware the queue replay follows immediately.
#
# Derived, not stored: a last-contact column would cost a transaction-row
# write per MeterValues frame, the highest-frequency path in the system.

async def last_heard_at(transaction: Transaction) -> Optional[datetime]:
    """Receipt time of the most recent signal about this transaction.

    start_time is a FALLBACK only, used when there is neither a suspend nor a
    reading — it is when the session began, not the last time we heard from
    it, and letting it compete in the max would make a freshly created row
    look "heard from just now".
    """
    candidates = [transaction.suspended_at] if transaction.suspended_at else []
    latest_mv = await MeterValue.filter(
        transaction_id=transaction.id
    ).order_by("-created_at").first()
    if latest_mv:
        candidates.append(latest_mv.created_at)
    if not candidates and transaction.start_time:
        candidates.append(transaction.start_time)
    return max(candidates) if candidates else None


async def silence_seconds(transaction: Transaction) -> Optional[float]:
    """Seconds since we last heard about this transaction; None if never."""
    heard = await last_heard_at(transaction)
    if heard is None:
        return None
    return (datetime.now(timezone.utc) - heard).total_seconds()


# One live timer per transaction. Arming again (a reboot inside the window)
# replaces the previous one rather than stacking a second.
_suspend_timers: Dict[int, asyncio.Task] = {}


def arm_suspend_timer(transaction_id: int, window_seconds: int, stop_reason: str) -> asyncio.Task:
    """Start (or replace) the silence timer for a SUSPENDED transaction."""
    previous = _suspend_timers.get(transaction_id)
    if previous and not previous.done():
        previous.cancel()
    task = safe_create_task(
        hold_until_silent(transaction_id, window_seconds, stop_reason),
        name=f"suspend-timer-{transaction_id}",
    )
    _suspend_timers[transaction_id] = task
    return task


async def hold_until_silent(transaction_id: int, window_seconds: int, stop_reason: str) -> None:
    """Finalize a SUSPENDED transaction once it has been silent for its window.

    Sleeps the window, then re-checks: if the charger has been heard from in
    the meantime the timer re-arms for the remainder instead of finalizing.
    Exits without action as soon as the transaction is no longer SUSPENDED
    (resumed, or finalized by another path). Replaces the old compare-and-swap
    on suspended_at, which could only see reboots, not readings.
    """
    remaining: float = window_seconds
    try:
        while True:
            await asyncio.sleep(remaining)
            transaction = await Transaction.filter(id=transaction_id).first()
            if not transaction or transaction.transaction_status != TransactionStatusEnum.SUSPENDED:
                logger.info(f"⏸️ Suspend timer for transaction {transaction_id} — no longer SUSPENDED, exiting")
                return
            silence = await silence_seconds(transaction)
            if silence is not None and silence < window_seconds:
                remaining = window_seconds - silence
                logger.info(
                    f"⏸️ Transaction {transaction_id} heard from {silence:.0f}s ago — "
                    f"re-arming suspend timer for {remaining:.0f}s"
                )
                continue
            from services.transaction_finalizer import finalize_stopped_transaction
            await finalize_stopped_transaction(transaction, stop_reason)
            return
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in suspend timer for transaction {transaction_id}: {e}", exc_info=True)
    finally:
        if _suspend_timers.get(transaction_id) is asyncio.current_task():
            _suspend_timers.pop(transaction_id, None)


def min_stale_suspended_cutoff_seconds() -> int:
    """Shortest possible stale cutoff — used only to pre-filter sweep candidates."""
    return SUSPEND_WINDOW_UNLATCHED_SECONDS + STALE_SUSPENDED_BUFFER_SECONDS


async def stale_suspended_cutoff_seconds_for(transaction: Transaction) -> int:
    """Per-transaction staleness cutoff: the transaction's own suspend window
    plus a buffer.

    Derived, never configured independently, so the backstop sweep and the
    resume-staleness guard fire strictly AFTER the primary timer for that
    transaction's connector type — the ADR 0022 invariant, preserved per-row
    now that the primary window is per-connector-type.
    """
    window = await suspend_window_seconds_for_transaction(transaction)
    return window + STALE_SUSPENDED_BUFFER_SECONDS


async def finalize_stale_suspended_transactions(stop_reason: str) -> int:
    """Find SUSPENDED transactions past their own suspend window (+ buffer)
    and finalize them via the canonical finalizer.

    Single source of truth for the stale-suspended backstop, shared by the
    startup sweep and the recurring billing-retry sweep so their cutoff and
    finalize path can never drift apart. Candidates are pre-filtered with the
    shortest cutoff, then each row is checked against its own per-type cutoff.
    Returns the number swept.
    """
    now = datetime.now(timezone.utc)
    candidate_cutoff = now - timedelta(seconds=min_stale_suspended_cutoff_seconds())

    candidates = await Transaction.filter(
        transaction_status=TransactionStatusEnum.SUSPENDED,
        suspended_at__lt=candidate_cutoff,
    ).all()

    # suspended_at is only the cheap PRE-FILTER (it is never later than the
    # silence clock). The decision is made on derived silence per row.
    stale_transactions = []
    for transaction in candidates:
        cutoff_seconds = await stale_suspended_cutoff_seconds_for(transaction)
        silence = await silence_seconds(transaction)
        if silence is not None and silence > cutoff_seconds:
            stale_transactions.append(transaction)

    if not stale_transactions:
        return 0

    logger.warning(
        f"🧹 Found {len(stale_transactions)} stale suspended transaction(s) "
        f"— cleaning up ({stop_reason})"
    )
    safe_create_task(OCPPMetrics.record_stale_suspended_swept(len(stale_transactions)))

    from services.transaction_finalizer import finalize_stopped_transaction
    for transaction in stale_transactions:
        try:
            await finalize_stopped_transaction(transaction, stop_reason)
        except Exception as e:
            logger.error(
                f"Error sweeping stale transaction {transaction.id}: {e}",
                exc_info=True,
            )
    return len(stale_transactions)


async def sweep_stale_suspended_transactions() -> None:
    """
    Startup safety net for server restarts.

    In-memory timeout tasks die when the process restarts. This finds
    SUSPENDED transactions older than the max window and stops them.
    Called once at startup.
    """
    swept = await finalize_stale_suspended_transactions("STALE_SUSPEND_SWEEP")
    if swept == 0:
        logger.info("🧹 No stale suspended transactions found at startup")
