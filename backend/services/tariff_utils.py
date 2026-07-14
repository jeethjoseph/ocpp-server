"""Shared tariff helpers (ADR 0026).

Post-ADR 0026 the tariff excludes the gateway entirely:
  • `rate_gst_included` — operator-typed, customer-displayed GST-inclusive,
    gateway-EXCLUSIVE energy price. Source of truth for display.
  • `rate_per_kwh` — the base rate, back-calculated as
    `rate_gst_included / (1 + gst_pct/100)`, used by line-item billing math.

The gateway fee is no longer synthetic: it is the ACTUAL Razorpay fee captured
on the QRPayment row and billed as a separate customer line. The synthetic-fee
helpers (`synthetic_platform_fee`, `synthetic_fee_split`, `back_derive_rate_per_kwh`)
were removed here — see ADR 0026 / ADR 0001 (superseded).
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional, Tuple


def back_calc_base_rate(
    rate_gst_included: Decimal,
    gst_percent: Decimal,
) -> Decimal:
    """Back-calculate the GST-exclusive base rate from the operator-typed,
    GST-inclusive tariff.

        base_rate = rate_gst_included / (1 + gst_pct/100)

    Quantized to 4dp to match the `rate_per_kwh` column precision. See ADR 0026.
    """
    gst_multiplier = Decimal("1") + (Decimal(str(gst_percent)) / Decimal("100"))
    return (Decimal(str(rate_gst_included)) / gst_multiplier).quantize(
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
    """Min/max tariff across `chargers`, as `(min_excl, max_excl, min_gst_incl,
    max_gst_incl)` floats.

    `*_gst_incl` are the operator-set, customer-facing `rate_gst_included`
    values. `*_excl` are the base rates (`rate_per_kwh`) — retained so the
    public stations API's GST-exclusive `price_per_kwh` field stays populated.
    Falls back to `global_tariff` for any charger without its own tariff.
    All `None` if no charger has any tariff.
    """
    excl_values: list[Decimal] = []
    gst_incl_values: list[Decimal] = []
    for charger in chargers:
        tariff = _charger_tariff(charger, global_tariff)
        if tariff is None:
            continue
        excl_values.append(Decimal(tariff.rate_per_kwh))
        gst_incl_values.append(Decimal(tariff.rate_gst_included))
    if not excl_values:
        return None, None, None, None
    return (
        float(min(excl_values)),
        float(max(excl_values)),
        float(min(gst_incl_values)),
        float(max(gst_incl_values)),
    )
