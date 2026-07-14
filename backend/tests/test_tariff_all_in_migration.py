"""Unit tests for the runtime base-rate back-calculation helper.

Post-ADR 0026 the tariff EXCLUDES the gateway entirely. The operator types a
GST-inclusive, gateway-exclusive price (`rate_gst_included`) and the base rate
is derived as:

    base_rate = rate_gst_included / (1 + gst_pct/100)

This is the identity exercised by the admin Tariff write path via
`services.tariff_utils.back_calc_base_rate`.

The historical migration-36 backfill smoke tests were removed here: migration
48 (`tariff_excludes_gateway_rename`) renamed the `tariff_per_kwh_all_in`
column to `rate_gst_included` and reversed the old synthetic-2%-shrink
back-derivation, so the migration-36 backfill SQL (which still targets the
now-renamed column and the superseded 2% semantics) no longer applies to the
current schema. See ADR 0026.
"""
from decimal import Decimal

from services.tariff_utils import back_calc_base_rate


# ----- back_calc_base_rate unit tests ----------------------------------------

def test_back_calc_30_at_18_pct_gst():
    """₹30 GST-inclusive at 18% GST → base = 30 / 1.18 = 25.4237."""
    rate = back_calc_base_rate(
        rate_gst_included=Decimal("30.00"),
        gst_percent=Decimal("18.00"),
    )
    # 30 / 1.18 = 25.42372881... → ROUND_HALF_UP to 4dp = 25.4237
    assert rate == Decimal("25.4237")


def test_back_calc_recovers_fixture_base_rate():
    """The conftest fixture pairing (rate_gst_included=17.70, gst=18) must
    back-calculate to the base rate 15.0000 exactly."""
    rate = back_calc_base_rate(Decimal("17.70"), Decimal("18.00"))
    assert rate == Decimal("15.0000")


def test_back_calc_identity_holds_round_trip():
    """For any GST-inclusive value: back-calc → multiply back ≈ original."""
    for gst_incl in [Decimal("1.0"), Decimal("17.70"), Decimal("25.00"), Decimal("99.99")]:
        base = back_calc_base_rate(gst_incl, Decimal("18.00"))
        reconstructed = base * Decimal("1.18")
        assert abs(reconstructed - gst_incl) < Decimal("0.0002"), (
            f"identity broke at gst_incl={gst_incl}: reconstructed={reconstructed}"
        )


def test_back_calc_handles_zero_gst():
    """For a 0% GST tariff: base == the GST-inclusive value unchanged."""
    rate = back_calc_base_rate(Decimal("10.00"), Decimal("0.00"))
    assert rate == Decimal("10.0000")


def test_back_calc_quantizes_to_4dp():
    """Result is always quantized to 4 decimal places."""
    rate = back_calc_base_rate(Decimal("99.99"), Decimal("18.00"))
    assert rate.as_tuple().exponent == -4
