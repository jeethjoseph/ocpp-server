"""Meter monotonicity observation — ADR 0031 decision 7.

The charger owns the meter and is the instrument of record. The CSMS observes
and does not correct: a cumulative reading LOWER than one already reported for
the same transaction is logged, audited and alerted, and then stored and
billed exactly as reported. No clamping, no rejection, no session interruption.

Why it matters: an involuntary register reset (the meter chip losing power in
a site outage) resets the register and drops the link in the same event. The
firmware is required to reconstruct the true cumulative value from persisted
state before reporting (CONTEXT.md "Meter reporting invariant"). With
PostBootState retired there is no server-side recovery fallback and no credit
note to correct an invoice issued on a bad figure — so this observation is the
ONLY field signal that charger-side meter persistence has failed. The ADR 0022
sweep found 3 reboot-resets in 11 disconnect-finalized sessions.

Cost: one Redis GET + SET per frame (a high-water mark keyed by transaction),
never a DB query on the per-frame path. On a cache miss — first frame, or a
server restart — the mark is seeded once from the latest stored reading and
the transaction's meterStart, so a first reading below meterStart is caught
too. Terminal-transaction replays are observed as well: a reset after a
write-off is still a persistence failure worth knowing about.
"""
import logging
from decimal import Decimal
from typing import Optional

from crud import log_audit_event
from redis_manager import redis_manager
from services.monitoring_service import OCPPMetrics
from utils import safe_create_task

logger = logging.getLogger("ocpp-server")


async def _high_water(transaction) -> Optional[Decimal]:
    cached = await redis_manager.get_meter_high_water(transaction.id)
    if cached is not None:
        return Decimal(cached)
    from services.meter_readings import latest_meter_value
    latest = await latest_meter_value(transaction.id)
    candidates = [c for c in (transaction.start_meter_kwh, latest.reading_kwh if latest else None) if c is not None]
    return max(Decimal(str(c)) for c in candidates) if candidates else None


async def observe_reading(transaction, charge_point_id: str, reading_kwh: Decimal) -> bool:
    """Record the reading against the transaction's high-water mark.

    Returns True when the reading went BACKWARDS (a violation). Always
    advances the mark to max(previous, reading) so a single bad frame is
    reported once and a genuine reset keeps reporting until the register
    climbs back past the old mark.
    """
    reading = Decimal(str(reading_kwh))
    previous = await _high_water(transaction)
    violated = previous is not None and reading < previous
    if violated:
        await _report(transaction, charge_point_id, previous, reading)
    new_mark = previous if (previous is not None and previous > reading) else reading
    await redis_manager.set_meter_high_water(transaction.id, str(new_mark))
    return violated


async def _report(transaction, charge_point_id: str, previous: Decimal, reading: Decimal) -> None:
    delta = reading - previous
    logger.warning(
        f"📉 Meter regression on txn {transaction.id} from {charge_point_id}: "
        f"reading {reading} kWh < previous {previous} kWh (delta {delta} kWh) — "
        f"stored and billed as reported; charger-side meter persistence suspect"
    )
    try:
        await log_audit_event(
            action="transaction.meter_regression",
            entity_type="transaction",
            entity_id=transaction.id,
            actor_type="ocpp",
            changes={
                "charger_id": charge_point_id,
                "previous_kwh": float(previous),
                "current_kwh": float(reading),
                "delta_kwh": float(delta),
                "status": str(transaction.transaction_status),
            },
        )
    except Exception as audit_err:
        logger.warning(f"meter-regression audit write failed for txn {transaction.id} (non-fatal): {audit_err}")
    safe_create_task(OCPPMetrics.record_meter_regression(
        charge_point_id, transaction.id, float(previous), float(reading),
    ))
