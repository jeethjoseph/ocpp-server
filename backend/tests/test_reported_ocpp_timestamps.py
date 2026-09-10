"""Charger-reported OCPP timestamps: parsing, the clock guard, and read ordering.

Covers ADR 0031 decision 8 — we retain what the charger says it measured,
alongside (never instead of) server receipt time, and only when it is plausible.
"""
import datetime

import pytest

from models import MeterValue, Transaction, TransactionStatusEnum
from services.meter_readings import latest_meter_value, meter_series
from utils import OCPP_CLOCK_SKEW_SECONDS, get_utc_now, parse_ocpp_timestamp

UTC = datetime.timezone.utc


# ---------------------------------------------------------------- parsing --

@pytest.mark.parametrize("raw,expected", [
    ("2026-09-09T04:30:49.000Z", datetime.datetime(2026, 9, 9, 4, 30, 49, tzinfo=UTC)),
    ("2026-09-09T04:30:49Z", datetime.datetime(2026, 9, 9, 4, 30, 49, tzinfo=UTC)),
    ("2026-09-09T10:00:49+05:30", datetime.datetime(2026, 9, 9, 4, 30, 49, tzinfo=UTC)),
    # Naive input is assumed UTC, matching the rest of the codebase.
    ("2026-09-09T04:30:49", datetime.datetime(2026, 9, 9, 4, 30, 49, tzinfo=UTC)),
])
def test_parses_ocpp_timestamp_forms_to_utc(raw, expected):
    assert parse_ocpp_timestamp(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "not-a-timestamp", "2026-13-45T99:99:99Z", []])
def test_absent_or_unparseable_returns_none(raw):
    assert parse_ocpp_timestamp(raw) is None


def test_rejects_timestamp_beyond_future_skew():
    """A charger reporting a time that has not happened yet has a bad clock."""
    too_far = get_utc_now() + datetime.timedelta(seconds=OCPP_CLOCK_SKEW_SECONDS + 120)
    assert parse_ocpp_timestamp(too_far.isoformat()) is None


def test_accepts_timestamp_inside_future_skew():
    """Ordinary NTP drift must not throw away an otherwise good reading."""
    slightly_ahead = get_utc_now() + datetime.timedelta(seconds=30)
    assert parse_ocpp_timestamp(slightly_ahead.isoformat()) is not None


def test_rejects_timestamp_before_the_floor():
    """A reset RTC must not be able to backdate a reading out of its session."""
    start = get_utc_now() - datetime.timedelta(hours=1)
    ancient = (start - datetime.timedelta(days=400)).isoformat()
    assert parse_ocpp_timestamp(ancient, not_before=start) is None


def test_accepts_old_but_in_session_timestamp():
    """Offline continuity means legitimately old readings — 40h is not suspect."""
    start = get_utc_now() - datetime.timedelta(hours=48)
    mid_session = (start + datetime.timedelta(hours=40)).isoformat()
    assert parse_ocpp_timestamp(mid_session, not_before=start) is not None


# --------------------------------------------------------------- ordering --

async def _txn(charger, user, *, started_hours_ago=0):
    txn = await Transaction.create(
        charger=charger, user=user, start_meter_kwh=0,
        transaction_status=TransactionStatusEnum.RUNNING,
    )
    if started_hours_ago:
        # start_time is auto_now_add, so backdate it after creation.
        started = get_utc_now() - datetime.timedelta(hours=started_hours_ago)
        await Transaction.filter(id=txn.id).update(start_time=started)
        txn = await Transaction.get(id=txn.id)
    return txn


@pytest.mark.asyncio
async def test_billing_baseline_is_receipt_order_and_series_is_measured_order(
    client, test_charger, test_user
):
    """The two readers answer different questions and order differently.

    ``latest_meter_value`` is the billing baseline and orders by RECEIPT — the
    last frame we got is the latest, full stop. ``meter_series`` is the
    delivery curve and orders by MEASURED time, which is what the retained
    timestamp is for. Insert them so the two orderings disagree, and assert
    each reader gives its own answer.
    """
    txn = await _txn(test_charger, test_user)
    base = get_utc_now() - datetime.timedelta(hours=6)

    # Measured LATER but received FIRST.
    await MeterValue.create(
        transaction=txn, reading_kwh=9, measured_at=base + datetime.timedelta(hours=3),
    )
    # Measured EARLIER but received LAST.
    await MeterValue.create(
        transaction=txn, reading_kwh=4, measured_at=base + datetime.timedelta(hours=1),
    )

    # Billing baseline: the last thing received, regardless of its stamp.
    latest = await latest_meter_value(txn.id)
    assert float(latest.reading_kwh) == 4.0

    # Delivery curve: by when the charger says each reading was taken.
    series = await meter_series(txn.id)
    assert [float(m.reading_kwh) for m in series] == [4.0, 9.0]


@pytest.mark.asyncio
async def test_baseline_survives_a_clock_stepping_backwards(
    client, test_charger, test_user
):
    """Regression pin for the ordering bug found in review.

    The clock guard deliberately admits a charger running up to 300 s fast. A
    frame stamped +4 min, then an NTP correction, then a later frame stamped
    +1 min: ordering by measured time put the EARLIER, LOWER reading on top and
    the finalizer would have billed 1.0 kWh for a 9.0 kWh session. Receipt
    order is monotonic and cannot do this. Reproduced on the dev DB before the
    fix (A id=321 1.0 kWh measured +4m; B id=322 9.0 kWh measured +1m; latest
    returned A).
    """
    txn = await _txn(test_charger, test_user)
    now = get_utc_now()

    # A: clock 4 min fast, inside the guard. Low reading. Received first.
    await MeterValue.create(
        transaction=txn, reading_kwh=1.0,
        measured_at=now + datetime.timedelta(minutes=4),
    )
    # B: clock corrected, so stamped EARLIER despite arriving LATER. High reading.
    await MeterValue.create(
        transaction=txn, reading_kwh=9.0,
        measured_at=now + datetime.timedelta(minutes=1),
    )

    latest = await latest_meter_value(txn.id)
    assert float(latest.reading_kwh) == 9.0, (
        "billing baseline went backwards on a clock step — the finalizer would "
        "under-bill this session"
    )


@pytest.mark.asyncio
async def test_falls_back_to_receipt_time_when_measured_at_null(client, test_charger, test_user):
    """Pre-migration rows and clock-guard rejections carry NULL and must still
    order sensibly rather than sorting to one end."""
    txn = await _txn(test_charger, test_user)
    await MeterValue.create(transaction=txn, reading_kwh=2, measured_at=None)
    await MeterValue.create(transaction=txn, reading_kwh=7, measured_at=None)

    latest = await latest_meter_value(txn.id)
    assert float(latest.reading_kwh) == 7.0


@pytest.mark.asyncio
async def test_measured_and_null_rows_coexist(client, test_charger, test_user):
    """A session spanning the migration has both kinds; COALESCE must order the
    union, not silently drop or float the NULLs."""
    txn = await _txn(test_charger, test_user)
    await MeterValue.create(transaction=txn, reading_kwh=1, measured_at=None)
    await MeterValue.create(
        transaction=txn, reading_kwh=5,
        measured_at=get_utc_now() + datetime.timedelta(minutes=1),
    )
    latest = await latest_meter_value(txn.id)
    assert float(latest.reading_kwh) == 5.0


@pytest.mark.asyncio
async def test_no_readings_returns_none(client, test_charger, test_user):
    txn = await _txn(test_charger, test_user)
    assert await latest_meter_value(txn.id) is None
    assert await meter_series(txn.id) == []


# -------------------------------------------------------------- retention --

@pytest.mark.asyncio
async def test_reported_times_are_recorded_beside_receipt_times(client, test_charger, test_user):
    """reported_* must never displace start_time / end_time, which stay the
    billing and GST-invoice basis (ADR 0031 decision 5)."""
    reported_end = get_utc_now() - datetime.timedelta(hours=30)
    txn = await Transaction.create(
        charger=test_charger, user=test_user, start_meter_kwh=0,
        transaction_status=TransactionStatusEnum.COMPLETED,
        end_time=get_utc_now(),
        reported_end_time=reported_end,
    )
    fresh = await Transaction.get(id=txn.id)
    assert fresh.reported_end_time is not None
    # The charger says it stopped ~30h before we heard about it.
    gap = (fresh.end_time - fresh.reported_end_time).total_seconds()
    assert gap > 29 * 3600


# ------------------------------------------------------- handler wiring --

@pytest.mark.asyncio
async def test_meter_values_handler_persists_frame_timestamp(
    client, test_charger, test_user
):
    """End-to-end through the real handler: the frame's own timestamp lands on
    the row, and is NOT the same as server receipt time."""
    from unittest.mock import MagicMock
    from main import ChargePoint

    txn = await _txn(test_charger, test_user, started_hours_ago=3)
    # A reading measured two hours ago, delivered now — the replay shape.
    measured = (get_utc_now() - datetime.timedelta(hours=2)).replace(microsecond=0)

    fake_cp = MagicMock(spec=ChargePoint)
    fake_cp.id = test_charger.charge_point_string_id
    await ChargePoint.on_meter_values(
        fake_cp,
        connector_id=1,
        transaction_id=txn.id,
        meter_value=[{
            "timestamp": measured.isoformat().replace("+00:00", "Z"),
            "sampledValue": [{
                "value": "4200", "unit": "Wh",
                "measurand": "Energy.Active.Import.Register",
            }],
        }],
    )

    row = await latest_meter_value(txn.id)
    assert row is not None
    assert float(row.reading_kwh) == 4.2
    assert row.measured_at == measured
    # The whole point: measured time is hours behind receipt time.
    assert (row.created_at - row.measured_at).total_seconds() > 3600


@pytest.mark.asyncio
async def test_meter_values_handler_stores_null_for_bad_clock(
    client, test_charger, test_user
):
    """A charger reporting a wildly future time gets NULL, not a poisoned row —
    readers then fall back to receipt time."""
    from unittest.mock import MagicMock
    from main import ChargePoint

    txn = await _txn(test_charger, test_user)
    bogus = get_utc_now() + datetime.timedelta(days=365)

    fake_cp = MagicMock(spec=ChargePoint)
    fake_cp.id = test_charger.charge_point_string_id
    await ChargePoint.on_meter_values(
        fake_cp,
        connector_id=1,
        transaction_id=txn.id,
        meter_value=[{
            "timestamp": bogus.isoformat().replace("+00:00", "Z"),
            "sampledValue": [{
                "value": "1000", "unit": "Wh",
                "measurand": "Energy.Active.Import.Register",
            }],
        }],
    )

    row = await latest_meter_value(txn.id)
    assert row is not None
    assert row.measured_at is None
    assert float(row.reading_kwh) == 1.0


@pytest.mark.asyncio
async def test_meter_values_handler_rejects_reading_before_its_session(
    client, test_charger, test_user
):
    """A reset RTC can report a time that predates the session it belongs to.
    The floor catches it: NULL, not a reading backdated out of its own
    transaction. This is the guard that makes measured_at safe to order by."""
    from unittest.mock import MagicMock
    from main import ChargePoint

    txn = await _txn(test_charger, test_user)
    before_session = get_utc_now() - datetime.timedelta(days=2)

    fake_cp = MagicMock(spec=ChargePoint)
    fake_cp.id = test_charger.charge_point_string_id
    await ChargePoint.on_meter_values(
        fake_cp,
        connector_id=1,
        transaction_id=txn.id,
        meter_value=[{
            "timestamp": before_session.isoformat().replace("+00:00", "Z"),
            "sampledValue": [{
                "value": "500", "unit": "Wh",
                "measurand": "Energy.Active.Import.Register",
            }],
        }],
    )

    row = await latest_meter_value(txn.id)
    assert row is not None and row.measured_at is None


@pytest.mark.asyncio
async def test_start_transaction_rejects_unsynced_rtc(client, test_charger, test_user):
    """A session can never START offline, so a reported start is always within
    seconds of receipt. A charger whose RTC came up at epoch — before NITZ/NTP
    sync, which is what happens when power returns and someone plugs straight
    in — must not write 1970 into the forensic column."""
    from unittest.mock import MagicMock
    from main import ChargePoint

    fake_cp = MagicMock(spec=ChargePoint)
    fake_cp.id = test_charger.charge_point_string_id

    await ChargePoint.on_start_transaction(
        fake_cp,
        connector_id=1,
        id_tag=test_user.rfid_card_id,
        meter_start=0,
        timestamp="1970-01-01T00:00:00Z",
    )

    txn = await Transaction.filter(charger=test_charger).order_by("-id").first()
    assert txn is not None
    assert txn.reported_start_time is None
    # start_time (server receipt) is unaffected and still populated.
    assert txn.start_time is not None


@pytest.mark.asyncio
async def test_start_transaction_keeps_a_sane_reported_time(
    client, test_charger, test_user
):
    """The floor must not throw away a normal, correctly-clocked start."""
    from unittest.mock import MagicMock
    from main import ChargePoint

    fake_cp = MagicMock(spec=ChargePoint)
    fake_cp.id = test_charger.charge_point_string_id

    await ChargePoint.on_start_transaction(
        fake_cp,
        connector_id=1,
        id_tag=test_user.rfid_card_id,
        meter_start=0,
        timestamp=get_utc_now().isoformat().replace("+00:00", "Z"),
    )

    txn = await Transaction.filter(charger=test_charger).order_by("-id").first()
    assert txn is not None and txn.reported_start_time is not None
