"""Shared helpers for the synthetic-fee policy (ADR 0001) and tariff display (ADR 0003).

Post-ADR 0003, tariffs carry both:
  • `tariff_per_kwh_all_in` — operator-typed, customer-displayed all-inclusive
    rate. Includes GST and the synthetic gateway fee. Authoritative for display.
  • `rate_per_kwh` — internal back-derived rate used by line-item billing math.

This module is the single place that knows:
  • the synthetic platform-fee math (`synthetic_platform_fee`, `synthetic_fee_split`),
  • the back-derivation formula (`back_derive_rate_per_kwh`),
  • the station-level aggregation logic (`compute_station_tariff_range`).

Callers should not roll their own. Both the QR payment service and the invoice
service consume these helpers.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional, Tuple

from core.config import RAZORPAY_PLATFORM_FEE_PERCENT


def synthetic_platform_fee(amount_paid: Decimal) -> Decimal:
    """Fixed-percentage platform fee used for every customer-facing calculation.

    Returns `amount_paid × RAZORPAY_PLATFORM_FEE_PERCENT / 100`, quantized to 2dp.
    Pure function — no DB I/O. See ADR 0001 for why we use this instead of the
    actual Razorpay fee for budget cap, refund math, and invoice gateway lines.
    """
    return (amount_paid * RAZORPAY_PLATFORM_FEE_PERCENT / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def synthetic_fee_split(amount_paid: Decimal) -> Tuple[Decimal, Decimal]:
    """Synthetic fee's all-in breakdown into (commission, GST-on-commission).

    The synthetic fee is treated as all-in: it already includes Razorpay's 18%
    GST on their commission. So commission = total / 1.18, GST = total - commission.
    Returns both quantized to 2dp; their sum equals `synthetic_platform_fee` exactly
    (GST is computed as the residual, not independently rounded).
    """
    total = synthetic_platform_fee(amount_paid)
    commission = (total / Decimal("1.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    gst = total - commission
    return commission, gst


def back_derive_rate_per_kwh(
    tariff_per_kwh_all_in: Decimal,
    gst_percent: Decimal,
    platform_fee_percent: Decimal,
) -> Decimal:
    """Derive the internal `rate_per_kwh` from the operator-entered all-in rate.

    Formula (gateway fee deducted first, then GST backed out):
        rate = all_in × (1 - fee_pct/100) / (1 + gst_pct/100)

    Result is quantized to 4dp to match the `rate_per_kwh` column precision.
    See ADR 0003.
    """
    fee_factor = Decimal("1") - (platform_fee_percent / Decimal("100"))
    gst_multiplier = Decimal("1") + (gst_percent / Decimal("100"))
    return (tariff_per_kwh_all_in * fee_factor / gst_multiplier).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def _charger_tariff(charger, global_tariff) -> Optional[object]:
    """Return the applicable tariff for a charger: charger-specific else global."""
    if getattr(charger, "tariffs", None):
        return charger.tariffs[0]
    return global_tariff


def compute_station_tariff_range(
    chargers: Iterable,
    global_tariff,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Min/max tariff (excl-GST `rate_per_kwh` and operator-set `all_in`) across `chargers`.

    Falls back to `global_tariff` for any charger without its own tariff. Returns
    `(min_excl, max_excl, min_all_in, max_all_in)` as floats — all `None` if no
    charger has any tariff.
    """
    excl_values: list[Decimal] = []
    all_in_values: list[Decimal] = []
    for charger in chargers:
        tariff = _charger_tariff(charger, global_tariff)
        if tariff is None:
            continue
        excl_values.append(Decimal(tariff.rate_per_kwh))
        all_in_values.append(Decimal(tariff.tariff_per_kwh_all_in))
    if not excl_values:
        return None, None, None, None
    return (
        float(min(excl_values)),
        float(max(excl_values)),
        float(min(all_in_values)),
        float(max(all_in_values)),
    )
