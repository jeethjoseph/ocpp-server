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
from typing import Dict

from models import Transaction, TransactionStatusEnum
from crud import log_audit_event
from utils import safe_create_task
from services.monitoring_service import OCPPMetrics

logger = logging.getLogger("ocpp-server")

DISCONNECT_SUSPEND_TIMEOUT = int(
    os.environ.get("DISCONNECT_SUSPEND_TIMEOUT_SECONDS", "180")
)
SUSPEND_TIMEOUT = int(
    os.environ.get("SUSPEND_TIMEOUT_SECONDS", "300")
)

# Pathological-flap detection: count consecutive disconnects WITHOUT energy
# progress between them. The counter is zeroed by zero_energy_watchdog when
# MeterValues show energy advancing, so a healthy long session with intermittent
# disconnects (cellular flake) never trips. Only sustained no-progress flap
# (>= MAX_RESETS_WITHOUT_PROGRESS) is treated as pathological — at that point
# we stop resetting suspended_at and let the existing timer fire.
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
        logger.warning(
            f"⏸️ Charger {charge_point_id} disconnected — suspending "
            f"{len(active_transactions)} active transaction(s)"
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

            safe_create_task(
                _disconnect_suspend_timeout(
                    transaction.id, now, DISCONNECT_SUSPEND_TIMEOUT
                )
            )

            safe_create_task(
                OCPPMetrics.record_disconnect_suspended(charge_point_id, transaction.id)
            )

    except Exception as e:
        logger.error(
            f"Error suspending transactions on disconnect for "
            f"{charge_point_id}: {e}", exc_info=True
        )


async def _disconnect_suspend_timeout(
    transaction_id: int,
    original_suspended_at: datetime,
    timeout_seconds: int,
) -> None:
    """Auto-stop a SUSPENDED transaction if charger doesn't reconnect."""
    try:
        await asyncio.sleep(timeout_seconds)

        transaction = await Transaction.filter(id=transaction_id).first()
        if not transaction:
            return

        # CAS guard: only act if still SUSPENDED with same suspended_at
        # If charger reconnected, BootNotification resets suspended_at
        if (
            transaction.transaction_status != TransactionStatusEnum.SUSPENDED
            or transaction.suspended_at != original_suspended_at
        ):
            logger.info(
                f"⏸️ Disconnect timeout for transaction {transaction_id} — "
                f"status already changed, skipping"
            )
            return

        from services.transaction_finalizer import finalize_stopped_transaction
        await finalize_stopped_transaction(transaction, "DISCONNECT_TIMEOUT")

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(
            f"Error in disconnect timeout for transaction "
            f"{transaction_id}: {e}", exc_info=True
        )


def stale_suspended_cutoff_seconds() -> int:
    """Longest legitimate suspend window + buffer.

    A SUSPENDED row doesn't record whether it was suspended by a disconnect
    (DISCONNECT_SUSPEND_TIMEOUT window) or a reboot (SUSPEND_TIMEOUT window), so
    a backstop sweep must wait the longer of the two before treating a row as
    orphaned — otherwise it pre-empts the in-flight primary timer and kills live
    sessions inside their reconnect grace window.
    """
    return max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + 60


async def finalize_stale_suspended_transactions(stop_reason: str) -> int:
    """Find SUSPENDED transactions past the longest legitimate suspend window
    and finalize them via the canonical finalizer.

    Single source of truth for the stale-suspended backstop, shared by the
    startup sweep and the recurring billing-retry sweep so their cutoff and
    finalize path can never drift apart. Returns the number swept.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=stale_suspended_cutoff_seconds()
    )

    stale_transactions = await Transaction.filter(
        transaction_status=TransactionStatusEnum.SUSPENDED,
        suspended_at__lt=cutoff,
    ).all()

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
