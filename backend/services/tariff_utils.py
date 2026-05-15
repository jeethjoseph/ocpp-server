"""Shared helpers for tariff display (tax-inclusive math + per-station range)."""
from decimal import Decimal
from typing import Iterable, Optional, Tuple


def compute_incl_tax(rate_per_kwh: Decimal, gst_percent: Decimal) -> Decimal:
    """Compute tax-inclusive rate from excl-tax rate + GST percent. 4 dp."""
    multiplier = Decimal("1") + (gst_percent / Decimal("100"))
    return (rate_per_kwh * multiplier).quantize(Decimal("0.0001"))


def _charger_tariff(charger, global_tariff) -> Optional[object]:
    """Return the applicable tariff for a charger: charger-specific else global."""
    if getattr(charger, "tariffs", None):
        return charger.tariffs[0]
    return global_tariff


def compute_station_tariff_range(
    chargers: Iterable,
    global_tariff,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Min/max tariff (excl + incl tax) across `chargers`.

    Falls back to `global_tariff` for any charger without its own tariff. Returns
    `(min_excl, max_excl, min_incl, max_incl)` as floats — all `None` if no
    charger has any tariff.
    """
    excl_values: list[Decimal] = []
    incl_values: list[Decimal] = []
    for charger in chargers:
        tariff = _charger_tariff(charger, global_tariff)
        if tariff is None:
            continue
        excl_values.append(Decimal(tariff.rate_per_kwh))
        incl_values.append(compute_incl_tax(tariff.rate_per_kwh, tariff.gst_percent))
    if not excl_values:
        return None, None, None, None
    return (
        float(min(excl_values)),
        float(max(excl_values)),
        float(min(incl_values)),
        float(max(incl_values)),
    )
