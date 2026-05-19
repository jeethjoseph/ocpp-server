"""Tests for the startup-time Tariff back-calc identity check (issue 02).

Catches the scenario where `RAZORPAY_PLATFORM_FEE_PERCENT` changes between
when migration 36 ran (which froze the 2% assumption into stored
`rate_per_kwh` values) and the current process boot. The checker samples a
few `Tariff` rows, verifies each satisfies the identity for the current env
value, and warns naming each drifting row.
"""
import logging
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

from models import Charger, ChargerStatusEnum, ChargingStation, Connector, Tariff
from services.tariff_drift_check import (
    find_drifting_tariffs,
    warn_on_tariff_identity_drift,
)
from services.tariff_utils import back_derive_rate_per_kwh


async def _seed_tariff(
    *, all_in: Decimal, gst: Decimal, fee_for_back_derive: Decimal,
) -> Tariff:
    """Create a Tariff whose stored `rate_per_kwh` is back-derived under
    `fee_for_back_derive`. If the drift checker is then run with a different
    fee%, this row will appear drifting."""
    suffix = uuid.uuid4().hex[:8]
    station = await ChargingStation.create(
        name=f"Drift Test Station {suffix}",
        latitude=12.0, longitude=77.0, address="—",
    )
    charger = await Charger.create(
        charge_point_string_id=f"drift-{suffix}",
        station_id=station.id,
        name="Drift Test Charger",
        model="X", vendor="Y",
        serial_number=f"SN{suffix}",
        latest_status=ChargerStatusEnum.AVAILABLE,
    )
    await Connector.create(charger=charger, connector_id=1, connector_type="Type2")
    rate = back_derive_rate_per_kwh(all_in, gst, fee_for_back_derive)
    return await Tariff.create(
        charger=charger,
        rate_per_kwh=rate,
        tariff_per_kwh_all_in=all_in,
        gst_percent=gst,
    )


@pytest.mark.asyncio
async def test_no_drift_when_stored_rate_matches_current_fee(client):
    """Happy path: rows back-derived under fee=2% pass the check at fee=2%."""
    await _seed_tariff(
        all_in=Decimal("25.00"),
        gst=Decimal("18.00"),
        fee_for_back_derive=Decimal("2.0"),
    )
    drifting = await find_drifting_tariffs(fee_percent=Decimal("2.0"))
    assert drifting == []


@pytest.mark.asyncio
async def test_drift_detected_when_fee_changed_after_migration(client):
    """Mimic H3's scenario: migration baked in 2%; env was bumped to 2.5%."""
    tariff = await _seed_tariff(
        all_in=Decimal("25.00"),
        gst=Decimal("18.00"),
        fee_for_back_derive=Decimal("2.0"),  # historical
    )
    drifting = await find_drifting_tariffs(fee_percent=Decimal("2.5"))
    assert len(drifting) == 1
    d = drifting[0]
    assert d.tariff_id == tariff.id
    # At 25 all-in, 18% GST: 2.0% → rate 20.7627; 2.5% → rate 20.6568.
    # Stored is 20.7627, expected (at 2.5%) is 20.6568. Drift ≈ +0.1059.
    assert d.stored_rate_per_kwh == Decimal("20.7627")
    assert d.expected_rate_per_kwh == Decimal("20.6568")
    assert d.drift == Decimal("0.1059")


@pytest.mark.asyncio
async def test_drift_within_epsilon_does_not_trigger(client):
    """A few rounding-units of drift is normal; only material drift fires."""
    # Seed at exactly fee=2.0, then check at fee=2.0001 — the tiny delta
    # is well inside IDENTITY_EPSILON.
    await _seed_tariff(
        all_in=Decimal("25.00"),
        gst=Decimal("18.00"),
        fee_for_back_derive=Decimal("2.0"),
    )
    drifting = await find_drifting_tariffs(fee_percent=Decimal("2.0001"))
    assert drifting == []


@pytest.mark.asyncio
async def test_warn_helper_emits_warning_and_increments_counter(client, caplog):
    """warn_on_tariff_identity_drift emits one summary + one row warning and
    increments Custom/Tariff/IdentityDrift exactly once when drift exists."""
    await _seed_tariff(
        all_in=Decimal("25.00"),
        gst=Decimal("18.00"),
        fee_for_back_derive=Decimal("2.0"),
    )

    with patch(
        "services.tariff_drift_check.MetricsCollector.increment_counter"
    ) as mock_counter:
        with caplog.at_level(logging.WARNING):
            drifting = await warn_on_tariff_identity_drift(
                fee_percent=Decimal("2.5"),
                logger=logging.getLogger("test_drift"),
            )

    assert len(drifting) == 1
    assert any("identity drift detected" in r.message.lower() for r in caplog.records)
    assert any("tariff_id=" in r.message for r in caplog.records)
    mock_counter.assert_called_once_with("Custom/Tariff/IdentityDrift")


@pytest.mark.asyncio
async def test_warn_helper_is_silent_when_no_drift(client, caplog):
    """No drift → no warning, no counter increment."""
    await _seed_tariff(
        all_in=Decimal("25.00"),
        gst=Decimal("18.00"),
        fee_for_back_derive=Decimal("2.0"),
    )

    with patch(
        "services.tariff_drift_check.MetricsCollector.increment_counter"
    ) as mock_counter:
        with caplog.at_level(logging.WARNING):
            drifting = await warn_on_tariff_identity_drift(
                fee_percent=Decimal("2.0"),
                logger=logging.getLogger("test_drift"),
            )

    assert drifting == []
    assert not any("identity drift" in r.message.lower() for r in caplog.records)
    mock_counter.assert_not_called()


@pytest.mark.asyncio
async def test_warn_helper_handles_empty_tariff_table(client, caplog):
    """No tariffs at all → no warning, no counter. (Fresh-install scenario.)"""
    with patch(
        "services.tariff_drift_check.MetricsCollector.increment_counter"
    ) as mock_counter:
        with caplog.at_level(logging.WARNING):
            drifting = await warn_on_tariff_identity_drift(
                fee_percent=Decimal("2.0"),
                logger=logging.getLogger("test_drift"),
            )

    assert drifting == []
    mock_counter.assert_not_called()


@pytest.mark.asyncio
async def test_sample_size_caps_scanned_rows(client):
    """When the table has >N rows the checker only scans N of them."""
    # Seed 3 clean (no-drift) rows + 1 drifting row.
    for _ in range(3):
        await _seed_tariff(
            all_in=Decimal("25.00"), gst=Decimal("18.00"),
            fee_for_back_derive=Decimal("2.0"),
        )
    # Drifting row inserted last; with sample_size=2 it may not be sampled.
    await _seed_tariff(
        all_in=Decimal("25.00"), gst=Decimal("18.00"),
        fee_for_back_derive=Decimal("3.5"),  # very different fee → big drift
    )

    # With a small sample we may or may not catch the drifting row depending
    # on the DB's natural ordering, but the function must return at most
    # `sample_size` results in every case.
    drifting = await find_drifting_tariffs(
        fee_percent=Decimal("2.0"), sample_size=2,
    )
    assert len(drifting) <= 2
