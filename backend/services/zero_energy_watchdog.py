"""
Zero-Energy Watchdog Service

Monitors running transactions for stalled energy consumption. If the energy
register (Energy.Active.Import.Register) hasn't advanced for a configurable
duration, automatically sends RemoteStopTransaction to the charger.

Configuration (environment variables):
  ZERO_ENERGY_TIMEOUT_SECONDS     - Stall duration before auto-stop (default: 120)
  ZERO_ENERGY_GRACE_PERIOD_SECONDS - Grace period after transaction start (default: 60)
"""

import os
import asyncio
import logging
from datetime import datetime, timezone

from models import Transaction
from redis_manager import redis_manager

logger = logging.getLogger("ocpp-server")

ZERO_ENERGY_TIMEOUT_SECONDS = int(
    os.environ.get("ZERO_ENERGY_TIMEOUT_SECONDS", "120")
)
ZERO_ENERGY_GRACE_PERIOD_SECONDS = int(
    os.environ.get("ZERO_ENERGY_GRACE_PERIOD_SECONDS", "60")
)


async def check_zero_energy(
    transaction_id: int, reading_kwh: float, transaction_start_time: datetime
):
    """Check if energy has stalled and trigger auto-stop if needed."""
    now = datetime.now(timezone.utc)

    # Grace period: skip check during initial charging negotiation
    if transaction_start_time:
        start_aware = transaction_start_time.replace(tzinfo=timezone.utc) \
            if transaction_start_time.tzinfo is None else transaction_start_time
        elapsed = (now - start_aware).total_seconds()
        if elapsed < ZERO_ENERGY_GRACE_PERIOD_SECONDS:
            return

    state = await redis_manager.get_zero_energy_state(transaction_id)
    now_iso = now.isoformat()

    if state is None:
        # First check after grace period — store initial state
        await redis_manager.set_zero_energy_state(transaction_id, {
            "last_advancing_kwh": reading_kwh,
            "last_advancing_at": now_iso,
            "previous_kwh": reading_kwh,
        })
        return

    previous_kwh = state.get("previous_kwh", 0)
    last_advancing_at = state.get("last_advancing_at", now_iso)

    if reading_kwh > previous_kwh:
        # Energy is advancing — reset the stall clock
        await redis_manager.set_zero_energy_state(transaction_id, {
            "last_advancing_kwh": reading_kwh,
            "last_advancing_at": now_iso,
            "previous_kwh": reading_kwh,
        })
        # Zero the disconnect-flap counter — real charging progress means
        # the session is healthy, regardless of any prior disconnects
        try:
            from services.disconnect_handler import _disconnect_reset_count
            _disconnect_reset_count.pop(transaction_id, None)
        except Exception as e:
            logger.debug(f"Flap counter reset error (non-fatal): {e}")
        return

    # Energy stalled — check duration
    await _handle_stalled_energy(
        transaction_id, reading_kwh, last_advancing_at, now, now_iso, state
    )


async def _handle_stalled_energy(
    transaction_id, reading_kwh, last_advancing_at, now, now_iso, state
):
    """Handle a stalled energy reading and trigger stop if timeout exceeded."""
    last_advance_time = datetime.fromisoformat(last_advancing_at)
    stalled_seconds = (now - last_advance_time).total_seconds()

    # Update previous_kwh but keep last_advancing_at unchanged
    await redis_manager.set_zero_energy_state(transaction_id, {
        "last_advancing_kwh": state.get("last_advancing_kwh", reading_kwh),
        "last_advancing_at": last_advancing_at,
        "previous_kwh": reading_kwh,
    })

    if stalled_seconds < ZERO_ENERGY_TIMEOUT_SECONDS:
        return

    logger.warning(
        f"Zero-energy timeout for txn {transaction_id}: "
        f"energy stalled at {reading_kwh} kWh for {stalled_seconds:.0f}s, "
        f"scheduling RemoteStopTransaction"
    )

    transaction = await Transaction.filter(
        id=transaction_id
    ).prefetch_related("charger").first()

    if not transaction:
        logger.error(f"Zero-energy stop: transaction {transaction_id} not found")
        return

    # Clean up Redis before sending stop to prevent re-triggering
    await redis_manager.delete_zero_energy_state(transaction_id)

    # Metric for alerting on stalled-charge spikes
    try:
        from services.monitoring_service import OCPPMetrics
        charger_id = transaction.charger.charge_point_string_id if transaction.charger else "unknown"
        asyncio.create_task(OCPPMetrics.record_zero_energy_stopped(
            transaction_id=transaction_id,
            charger_id=charger_id,
            stalled_seconds=stalled_seconds,
        ))
    except Exception as e:
        logger.debug(f"Zero-energy metric error (non-fatal): {e}")

    # Schedule as background task — do NOT await here.
    # This runs inside the MeterValues handler; awaiting would deadlock.
    asyncio.create_task(_send_zero_energy_stop(transaction, transaction_id))


async def _send_zero_energy_stop(transaction, transaction_id: int):
    """Send RemoteStopTransaction as a background task."""
    from core.connection_manager import connection_manager

    try:
        success, result = await connection_manager.send_ocpp_request(
            transaction.charger.charge_point_string_id,
            "RemoteStopTransaction",
            {"transaction_id": transaction_id},
        )
        if success:
            logger.info(f"Zero-energy auto-stop sent for txn {transaction_id}")
        else:
            logger.error(
                f"Failed to send zero-energy stop for txn {transaction_id}: {result}"
            )
    except Exception as e:
        logger.error(
            f"Error sending zero-energy stop for txn {transaction_id}: {e}"
        )


async def clear_zero_energy_tracking(transaction_id: int):
    """Clean up zero-energy tracking state when a transaction stops."""
    await redis_manager.delete_zero_energy_state(transaction_id)
