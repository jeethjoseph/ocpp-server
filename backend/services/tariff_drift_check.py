"""Startup-time invariant check for `Tariff` rows.

Catches the scenario where `RAZORPAY_PLATFORM_FEE_PERCENT` was changed in the
environment AFTER migration 36 ran. The migration's backfill is frozen at the
2% assumption (encoded as the literal `0.98` in its UPDATE SQL — see ADR 0003);
if the env subsequently moved to, say, 2.5%, the runtime back-derivation
formula uses `0.975` and the per-row identity

    tariff_per_kwh_all_in × (1 − fee_pct/100) / (1 + gst_pct/100) ≈ rate_per_kwh

is violated for every row that hasn't been re-saved via the new admin form.

This module samples up to N rows on startup and warns once if drift is found,
naming each affected charger. Operators re-enter the affected tariffs via the
admin form to clear the drift (the admin save recomputes rate_per_kwh under
the current env-var value).
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import List

from models import Tariff
from services.monitoring_service import MetricsCollector
from services.tariff_utils import back_derive_rate_per_kwh


# Tolerance for the back-calc identity. Per-row rounding in the migration
# backfill is at most 0.00005 per multiplication × 2 multiplications + 4dp
# quantization noise; 0.0002 leaves comfortable margin without missing real
# drift from a moved fee percent.
IDENTITY_EPSILON = Decimal("0.0002")

# Default sample size on startup. Production has a handful of tariff rows; even
# scanning the whole table is cheap. The sample cap exists so a future
# multi-thousand-tariff fleet doesn't slow startup measurably.
DEFAULT_SAMPLE_SIZE = 10


@dataclass(frozen=True)
class DriftingTariff:
    tariff_id: int
    charger_id: int
    stored_rate_per_kwh: Decimal
    expected_rate_per_kwh: Decimal
    drift: Decimal  # signed: stored - expected


async def find_drifting_tariffs(
    fee_percent: Decimal,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> List[DriftingTariff]:
    """Sample `Tariff` rows and return those whose stored `rate_per_kwh`
    violates the back-calc identity by more than `IDENTITY_EPSILON`.

    Pure read — no writes. Empty list means no drift was detected.
    """
    sampled = await Tariff.all().limit(sample_size)
    drifting: List[DriftingTariff] = []
    for tariff in sampled:
        expected = back_derive_rate_per_kwh(
            tariff.tariff_per_kwh_all_in,
            tariff.gst_percent,
            fee_percent,
        )
        delta = tariff.rate_per_kwh - expected
        if abs(delta) > IDENTITY_EPSILON:
            drifting.append(DriftingTariff(
                tariff_id=tariff.id,
                charger_id=tariff.charger_id or 0,
                stored_rate_per_kwh=tariff.rate_per_kwh,
                expected_rate_per_kwh=expected,
                drift=delta,
            ))
    return drifting


async def warn_on_tariff_identity_drift(
    fee_percent: Decimal,
    logger,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> List[DriftingTariff]:
    """Run the drift check and emit ops signals. Returns the drifting list
    so callers/tests can assert on it.

    - One `WARNING` log per drifting row (named by charger id + drift magnitude).
    - `Custom/Tariff/IdentityDrift` counter incremented ONCE per call if any
      drift detected (not per row — avoids alert storms on a fleet-wide change).
    """
    drifting = await find_drifting_tariffs(fee_percent, sample_size)
    if not drifting:
        return drifting

    logger.warning(
        "Tariff identity drift detected: %d row(s) violate the back-calc "
        "identity at the current RAZORPAY_PLATFORM_FEE_PERCENT=%s. "
        "Operator must re-save affected charger tariffs via the admin form "
        "to clear the drift. See ADR 0003.",
        len(drifting), fee_percent,
    )
    for d in drifting:
        logger.warning(
            "  tariff_id=%d charger_id=%d stored_rate=%s expected_rate=%s drift=%s",
            d.tariff_id, d.charger_id,
            d.stored_rate_per_kwh, d.expected_rate_per_kwh, d.drift,
        )
    MetricsCollector.increment_counter("Custom/Tariff/IdentityDrift")
    return drifting
