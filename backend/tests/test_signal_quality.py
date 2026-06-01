"""Tests for the SignalQuality / Modem-telemetry surface.

Covers the DataTransfer handler (`ChargePoint._handle_signal_quality`) and
the admin signal-quality endpoint (`GET /api/admin/chargers/{id}/signal-quality`).
The OCPP packet shape was identified in staging on 2026-06-01:

  vendorId  = "VoltLync"
  messageId = "SignalQuality"
  data      = '{"rssi":18,"ber":99,"temperature":38.2,"timestamp":"6870"}'

See ADR 0009 for why this lives in `signal_quality` and not `meter_value`.
"""
import json

import pytest

from main import ChargePoint
from models import SignalQuality


pytestmark = pytest.mark.asyncio


def _bind_handler(charge_point_string_id: str) -> ChargePoint:
    """Build a partially-constructed ChargePoint instance for unit-testing
    handler methods. We skip the parent OcppChargePoint constructor (which
    expects a WebSocket connection) and set only the attributes the handler
    reads — ``self.id``.
    """
    handler = object.__new__(ChargePoint)
    handler.id = charge_point_string_id
    return handler


async def test_handler_stores_temperature_when_present(client, test_charger):
    """Modern firmware sends rssi/ber/temperature in one packet."""
    handler = _bind_handler(test_charger.charge_point_string_id)
    payload = json.dumps({"rssi": 18, "ber": 99, "temperature": 38.2, "timestamp": "6870"})

    result = await handler._handle_signal_quality(payload)
    assert result.status == "Accepted"

    row = await SignalQuality.filter(charger_id=test_charger.id).order_by("-id").first()
    assert row is not None
    assert row.rssi == 18
    assert row.ber == 99
    assert row.temperature_celsius == pytest.approx(38.2)


async def test_handler_stores_null_temperature_for_legacy_firmware(client, test_charger):
    """Older firmware omits ``temperature`` entirely — the row is still
    created (rssi/ber are the load-bearing fields) and ``temperature_celsius``
    is NULL. Guards against an accidental "temperature is required" check
    that would reject every legacy packet."""
    handler = _bind_handler(test_charger.charge_point_string_id)
    payload = json.dumps({"rssi": 22, "ber": 99, "timestamp": "100"})

    result = await handler._handle_signal_quality(payload)
    assert result.status == "Accepted"

    row = await SignalQuality.filter(charger_id=test_charger.id).order_by("-id").first()
    assert row is not None
    assert row.rssi == 22
    assert row.temperature_celsius is None


async def test_handler_drops_non_numeric_temperature_but_accepts_packet(
    client, test_charger
):
    """A garbage ``temperature`` value (firmware bug) must not reject the
    whole packet — rssi/ber are still valuable. The temperature is dropped
    quietly to NULL and a warning logged."""
    handler = _bind_handler(test_charger.charge_point_string_id)
    payload = json.dumps({"rssi": 15, "ber": 99, "temperature": "hot", "timestamp": "1"})

    result = await handler._handle_signal_quality(payload)
    assert result.status == "Accepted"

    row = await SignalQuality.filter(charger_id=test_charger.id).order_by("-id").first()
    assert row is not None
    assert row.temperature_celsius is None


async def test_endpoint_surfaces_temperature_per_row_and_envelope(
    client_admin, test_charger
):
    """The admin endpoint exposes ``temperature_celsius`` on every row and
    ``latest_temperature_celsius`` on the envelope (matching the existing
    ``latest_rssi`` / ``latest_ber`` pattern)."""
    await SignalQuality.create(
        charger=test_charger, rssi=20, ber=99, temperature_celsius=37.5, timestamp="1"
    )
    await SignalQuality.create(
        charger=test_charger, rssi=22, ber=99, temperature_celsius=None, timestamp="2"
    )
    await SignalQuality.create(
        charger=test_charger, rssi=18, ber=99, temperature_celsius=38.4, timestamp="3"
    )

    resp = await client_admin.get(f"/api/admin/chargers/{test_charger.id}/signal-quality")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["latest_temperature_celsius"] == pytest.approx(38.4)
    temps_by_rssi = {row["rssi"]: row["temperature_celsius"] for row in body["data"]}
    assert temps_by_rssi[20] == pytest.approx(37.5)
    assert temps_by_rssi[22] is None
    assert temps_by_rssi[18] == pytest.approx(38.4)
