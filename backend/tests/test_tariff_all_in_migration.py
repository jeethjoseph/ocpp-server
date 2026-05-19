"""Smoke test for migration 36 (tariff_per_kwh_all_in column + backfill).

Verifies the backfill SQL preserves the customer-facing displayed number
while shrinking rate_per_kwh by 2%, and that the back-derivation identity
`all_in × 0.98 / 1.18 = rate_per_kwh` holds for every row within ±0.0001.

Also covers the runtime back-derivation helper used by the admin Tariff
write path (issue 04).

See ADR 0003 and `.scratch/qr-billing-overhaul/issues/03-...md`.
"""
import uuid
from decimal import Decimal

import pytest
from tortoise import connections

from models import Tariff, Charger, ChargingStation
from services.tariff_utils import back_derive_rate_per_kwh


# ----- back_derive_rate_per_kwh unit tests -----------------------------------

def test_back_derive_30_at_18_pct_gst_and_2_pct_fee():
    """Worked example from CONTEXT.md: ₹30 all-in → rate = 24.9153."""
    rate = back_derive_rate_per_kwh(
        tariff_per_kwh_all_in=Decimal("30.00"),
        gst_percent=Decimal("18.00"),
        platform_fee_percent=Decimal("2.0"),
    )
    # 30 × 0.98 / 1.18 = 24.91525... → ROUND_HALF_UP to 4dp = 24.9153
    assert rate == Decimal("24.9153")


def test_back_derive_identity_holds_round_trip():
    """For any all_in: back-derive → multiply back ≈ original (within rounding)."""
    for all_in in [Decimal("1.0"), Decimal("17.70"), Decimal("25.00"), Decimal("99.99")]:
        rate = back_derive_rate_per_kwh(
            all_in, Decimal("18.00"), Decimal("2.0")
        )
        reconstructed = rate * Decimal("1.18") / Decimal("0.98")
        assert abs(reconstructed - all_in) < Decimal("0.0002"), (
            f"identity broke at all_in={all_in}: reconstructed={reconstructed}"
        )


def test_back_derive_handles_zero_gst():
    """For a 0% GST tariff: rate = all_in × 0.98."""
    rate = back_derive_rate_per_kwh(
        Decimal("10.00"), Decimal("0.00"), Decimal("2.0"),
    )
    assert rate == Decimal("9.8000")


# ----- migration backfill smoke tests ----------------------------------------


# Pre-migration rate / GST pairs that we want to verify under the backfill.
# Picked to cover common Indian GST rates and a wide rupee range.
BACKFILL_FIXTURES = [
    # (pre_rate, gst_percent)
    (Decimal("12.0000"), Decimal("18.00")),
    (Decimal("20.7627"), Decimal("18.00")),   # from the worked example in CONTEXT.md
    (Decimal("8.5000"),  Decimal("5.00")),    # lower GST rate
    (Decimal("33.0000"), Decimal("12.00")),   # middle GST bracket (real Indian rate)
    (Decimal("45.0000"), Decimal("28.00")),   # higher GST rate
    (Decimal("0.5000"),  Decimal("18.00")),   # smallest realistic rate
    (Decimal("999.9999"), Decimal("18.00")),  # widest precision
]


# Import the production backfill SQL directly from the migration module so
# this test can't drift from what actually ships. Production runs the SQL
# unscoped (whole-table); the test scopes by id via the WHERE clause appended
# below.
import importlib.util
import pathlib

_migration_path = (
    pathlib.Path(__file__).parent.parent
    / "migrations" / "models" / "36_20260518101531_tariff_all_in_column.py"
)
_spec = importlib.util.spec_from_file_location("_mig36", _migration_path)
_mig36 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mig36)
MIGRATION_36_BACKFILL_SQL = _mig36.BACKFILL_UPDATE_SQL.strip().rstrip(";") + " WHERE id = $1"


@pytest.fixture
async def station_and_charger():
    station = await ChargingStation.create(
        name=f"Mig36 Station {uuid.uuid4().hex[:6]}",
        latitude=12.0, longitude=77.0, address="—",
    )
    charger = await Charger.create(
        charge_point_string_id=f"mig36-{uuid.uuid4().hex[:8]}",
        station_id=station.id,
        name="Mig36 Charger",
        model="X", vendor="Y",
        serial_number=f"SN{uuid.uuid4().hex[:8]}",
        latest_status="Available",
    )
    return station, charger


@pytest.mark.asyncio
@pytest.mark.parametrize("pre_rate, gst_percent", BACKFILL_FIXTURES)
async def test_backfill_sql_preserves_customer_price_and_holds_identity(
    client, station_and_charger, pre_rate, gst_percent
):
    """For every fixture row: applying the migration UPDATE produces an all_in
    equal to the pre-migration "incl. GST" display, shrinks rate_per_kwh by
    exactly 2%, and the back-calc identity holds within ±0.0001.
    """
    _, charger = station_and_charger

    # Insert a row representing pre-migration state. The post-migration schema
    # has `tariff_per_kwh_all_in NOT NULL`, so we can't NULL it to mimic the
    # nullable intermediate state. Instead we seed a deliberately-wrong
    # placeholder (₹0.0001) and assert the migration's UPDATE overwrites it
    # with the correct backfill value. The "NOT NULL after migration" property
    # is enforced by the schema itself and covered by the next test.
    tariff = await Tariff.create(
        charger=charger,
        rate_per_kwh=pre_rate,
        gst_percent=gst_percent,
        tariff_per_kwh_all_in=Decimal("0.0001"),
    )

    conn = connections.get("default")
    # Run the migration's backfill SQL on this one row.
    await conn.execute_query(MIGRATION_36_BACKFILL_SQL, [tariff.id])

    # Refetch.
    rows = await conn.execute_query(
        'SELECT rate_per_kwh, gst_percent, tariff_per_kwh_all_in '
        'FROM "tariff" WHERE id = $1',
        [tariff.id],
    )
    row = rows[1][0]
    new_rate = Decimal(str(row["rate_per_kwh"]))
    new_all_in = Decimal(str(row["tariff_per_kwh_all_in"]))

    # 1. Customer-facing displayed number preserved.
    expected_all_in = (pre_rate * (Decimal("1") + gst_percent / Decimal("100"))).quantize(
        Decimal("0.0001")
    )
    assert new_all_in == expected_all_in, (
        f"all_in mismatch for ({pre_rate}, {gst_percent}%): "
        f"expected {expected_all_in}, got {new_all_in}"
    )

    # 2. rate_per_kwh shrunk by exactly 2%.
    expected_rate = (pre_rate * Decimal("0.98")).quantize(Decimal("0.0001"))
    assert new_rate == expected_rate

    # 3. Back-derivation identity holds within ±0.0001.
    derived = (new_all_in * Decimal("0.98") / (Decimal("1") + gst_percent / Decimal("100")))
    assert abs(derived - new_rate) < Decimal("0.0001"), (
        f"Identity check failed: derived={derived}, stored={new_rate}, "
        f"delta={derived - new_rate}"
    )


# NOTE: a previous `test_backfill_all_in_is_not_null_after_migration` was
# deleted in issue 02 — it queried `WHERE tariff_per_kwh_all_in IS NULL` against
# a schema that already enforces NOT NULL via the Tortoise model, so the
# assertion always passed regardless of what the migration did. The NOT NULL
# property is enforced structurally and validated implicitly every time
# anything inserts into Tariff without supplying the column.
