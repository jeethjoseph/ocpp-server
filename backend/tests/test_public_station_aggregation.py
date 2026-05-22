"""Unit tests for the per-plug-type aggregation in public_stations.

Covers the 3-bucket status mapping (Ready / In use / Out of service) and the
per-plug-type tariff range emitted on ConnectorInfo.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from models import ChargerStatusEnum
from routers.public_stations import _aggregate_connectors, _status_bucket


pytestmark = pytest.mark.asyncio


def _make_charger(status: ChargerStatusEnum, connector_type: str,
                  power_kw: float, tariff_all_in: float | None):
    """Build a duck-typed charger that satisfies _aggregate_connectors."""
    tariff = (
        SimpleNamespace(tariff_per_kwh_all_in=Decimal(str(tariff_all_in)))
        if tariff_all_in is not None else None
    )
    return SimpleNamespace(
        latest_status=status,
        connectors=[SimpleNamespace(connector_type=connector_type,
                                    max_power_kw=power_kw)],
        tariffs=[tariff] if tariff is not None else [],
    )


def test_status_bucket_mapping():
    assert _status_bucket(ChargerStatusEnum.AVAILABLE) == "ready"
    assert _status_bucket(ChargerStatusEnum.CHARGING) == "in_use"
    assert _status_bucket(ChargerStatusEnum.PREPARING) == "in_use"
    assert _status_bucket(ChargerStatusEnum.FINISHING) == "in_use"
    assert _status_bucket(ChargerStatusEnum.SUSPENDED_EV) == "in_use"
    assert _status_bucket(ChargerStatusEnum.SUSPENDED_EVSE) == "in_use"
    assert _status_bucket(ChargerStatusEnum.FAULTED) == "out_of_service"
    assert _status_bucket(ChargerStatusEnum.UNAVAILABLE) == "out_of_service"
    assert _status_bucket(ChargerStatusEnum.RESERVED) == "out_of_service"


async def test_aggregate_buckets_two_chargers_same_type():
    chargers = [
        _make_charger(ChargerStatusEnum.AVAILABLE, "Type2", 7.4, 25.0),
        _make_charger(ChargerStatusEnum.CHARGING,  "Type2", 7.4, 25.0),
    ]
    details, types = _aggregate_connectors(chargers, global_tariff=None)
    assert types == {"Type2"}
    assert len(details) == 1
    row = details[0]
    assert row.total_count == 2
    assert row.ready_count == 1
    assert row.in_use_count == 1
    assert row.out_of_service_count == 0
    assert row.available_count == 1
    assert row.min_tariff_all_in == 25.0
    assert row.max_tariff_all_in == 25.0


async def test_aggregate_faulted_and_unavailable_collapse_to_out_of_service():
    chargers = [
        _make_charger(ChargerStatusEnum.FAULTED,     "Socket", 3.3, 20.0),
        _make_charger(ChargerStatusEnum.UNAVAILABLE, "Socket", 3.3, 20.0),
    ]
    details, _ = _aggregate_connectors(chargers, global_tariff=None)
    row = details[0]
    assert row.out_of_service_count == 2
    assert row.ready_count == 0
    assert row.in_use_count == 0


async def test_aggregate_per_type_tariff_range():
    chargers = [
        _make_charger(ChargerStatusEnum.AVAILABLE, "Type2",  7.4, 22.0),
        _make_charger(ChargerStatusEnum.AVAILABLE, "Type2",  7.4, 25.0),
        _make_charger(ChargerStatusEnum.AVAILABLE, "Socket", 3.3, 20.0),
    ]
    details, types = _aggregate_connectors(chargers, global_tariff=None)
    assert types == {"Type2", "Socket"}
    by_type = {d.connector_type: d for d in details}
    assert by_type["Type2"].min_tariff_all_in == 22.0
    assert by_type["Type2"].max_tariff_all_in == 25.0
    assert by_type["Socket"].min_tariff_all_in == 20.0
    assert by_type["Socket"].max_tariff_all_in == 20.0


async def test_aggregate_falls_back_to_global_tariff():
    global_tariff = SimpleNamespace(tariff_per_kwh_all_in=Decimal("18.50"))
    chargers = [
        _make_charger(ChargerStatusEnum.AVAILABLE, "Type2", 7.4, tariff_all_in=None),
    ]
    details, _ = _aggregate_connectors(chargers, global_tariff=global_tariff)
    assert details[0].min_tariff_all_in == 18.5
    assert details[0].max_tariff_all_in == 18.5


async def test_aggregate_no_tariffs_at_all():
    chargers = [
        _make_charger(ChargerStatusEnum.AVAILABLE, "Type2", 7.4, tariff_all_in=None),
    ]
    details, _ = _aggregate_connectors(chargers, global_tariff=None)
    assert details[0].min_tariff_all_in is None
    assert details[0].max_tariff_all_in is None
