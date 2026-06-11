"""
Tests for PostBootState DataTransfer feature.

Unit tests mock the ChargePoint.call() method and test the logic of
_push_post_boot_state and after_boot_notification.

Integration tests connect to a running server and verify the full flow.
"""

import pytest
import json
import asyncio
import time
import websocket
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    ChargingStation, Charger, Transaction, MeterValue,
    TransactionStatusEnum, User
)


# --- Unit Tests ---

@pytest.mark.unit
class TestPushPostBootStateWithTransaction:
    """Test _push_post_boot_state when a suspended transaction exists."""

    @pytest.mark.asyncio
    async def test_payload_with_suspended_transaction(self, client, test_charger, test_user):
        """Verify correct payload when a suspended transaction with meter values exists."""
        from main import ChargePoint

        txn = await Transaction.create(
            user=test_user,
            charger=test_charger,
            start_meter_kwh=10.0,
            transaction_status=TransactionStatusEnum.SUSPENDED,
        )
        await MeterValue.create(transaction=txn, reading_kwh=15.34, power_kw=3.5)

        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id

        mock_response = MagicMock()
        mock_response.status = "Accepted"
        cp.call = AsyncMock(return_value=mock_response)

        await cp._push_post_boot_state(transaction=txn)

        cp.call.assert_called_once()
        req = cp.call.call_args[0][0]
        assert req.vendor_id == "VOLTLYNC"
        assert req.message_id == "PostBootState"

        data = json.loads(req.data)
        assert data["hasPendingTransaction"] is True
        assert data["transactionId"] == txn.id
        assert data["startMeterValueWh"] == 10000
        assert data["lastMeterValueWh"] == 15340
        assert data["energyConsumedWh"] == 5340

    @pytest.mark.asyncio
    async def test_payload_no_meter_values(self, client, test_charger, test_user):
        """When no MeterValues exist, lastMeterValueWh should equal startMeterValueWh."""
        from main import ChargePoint

        txn = await Transaction.create(
            user=test_user,
            charger=test_charger,
            start_meter_kwh=10.0,
            transaction_status=TransactionStatusEnum.SUSPENDED,
        )

        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id
        mock_response = MagicMock()
        mock_response.status = "Accepted"
        cp.call = AsyncMock(return_value=mock_response)

        await cp._push_post_boot_state(transaction=txn)

        data = json.loads(cp.call.call_args[0][0].data)
        assert data["lastMeterValueWh"] == 10000
        assert data["energyConsumedWh"] == 0


@pytest.mark.unit
class TestPushPostBootStateNoTransaction:
    """Test _push_post_boot_state when no transaction is active."""

    @pytest.mark.asyncio
    async def test_payload_with_completed_transaction(self, client, test_charger, test_user):
        """Verify lastMeterValueWh comes from most recent completed transaction."""
        from main import ChargePoint
        import datetime

        await Transaction.create(
            user=test_user,
            charger=test_charger,
            start_meter_kwh=5.0,
            end_meter_kwh=15.34,
            transaction_status=TransactionStatusEnum.COMPLETED,
            end_time=datetime.datetime.now(datetime.timezone.utc),
        )

        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id
        mock_response = MagicMock()
        mock_response.status = "Accepted"
        cp.call = AsyncMock(return_value=mock_response)

        await cp._push_post_boot_state(transaction=None)

        data = json.loads(cp.call.call_args[0][0].data)
        assert data["hasPendingTransaction"] is False
        assert data["lastMeterValueWh"] == 15340

    @pytest.mark.asyncio
    async def test_payload_no_history(self, client, test_charger):
        """When no transactions ever existed, lastMeterValueWh should be 0."""
        from main import ChargePoint

        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id
        mock_response = MagicMock()
        mock_response.status = "Accepted"
        cp.call = AsyncMock(return_value=mock_response)

        await cp._push_post_boot_state(transaction=None)

        data = json.loads(cp.call.call_args[0][0].data)
        assert data["hasPendingTransaction"] is False
        assert data["lastMeterValueWh"] == 0


@pytest.mark.unit
class TestPushPostBootStateErrorHandling:
    """Test graceful degradation on errors."""

    @pytest.mark.asyncio
    async def test_charger_rejects(self, client, test_charger):
        """No exception raised when charger rejects the DataTransfer."""
        from main import ChargePoint

        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id
        mock_response = MagicMock()
        mock_response.status = "UnknownMessageId"
        cp.call = AsyncMock(return_value=mock_response)

        # Should not raise
        await cp._push_post_boot_state(transaction=None)
        cp.call.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout(self, client, test_charger):
        """No exception raised when DataTransfer times out."""
        from main import ChargePoint

        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id
        cp.call = AsyncMock(side_effect=asyncio.TimeoutError())

        # Should not raise
        await cp._push_post_boot_state(transaction=None)

    @pytest.mark.asyncio
    async def test_none_response(self, client, test_charger):
        """No AttributeError when call() resolves to None (unparseable/dropped
        reply) — regression for OCPP-BACKEND-1Q."""
        from main import ChargePoint

        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id
        cp.call = AsyncMock(return_value=None)

        # Should not raise AttributeError on response.status
        await cp._push_post_boot_state(transaction=None)
        cp.call.assert_called_once()


# --- Integration Tests ---

@pytest.mark.integration
class TestPostBootStateIntegration:
    """Integration tests using FastAPI TestClient (in-process WebSocket).

    Drives the OCPP WebSocket route end-to-end via TestClient instead of a
    live external server. Uses the sync_client_admin + sync_db fixtures from
    conftest.py to seed chargers and bypass admin auth.
    """

    def _drain_for_data_transfer(self, ws, max_messages: int = 10):
        """Read messages until a server-initiated DataTransfer CALL appears."""
        for _ in range(max_messages):
            raw = ws.receive_text()
            parsed = json.loads(raw)
            if parsed[0] == 2 and parsed[2] == "DataTransfer":
                return parsed
        return None

    def test_post_boot_state_no_transaction(self, sync_client_admin):
        """BootNotification with no active transactions should receive meter-only PostBootState."""
        import uuid

        # Seed station + charger via TestClient HTTP — runs on the same
        # event loop as the WebSocket request, sharing Tortoise's pool.
        station_resp = sync_client_admin.post(
            "/api/admin/stations",
            json={
                "name": f"PostBoot Station {uuid.uuid4().hex[:6]}",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "address": "Test Address",
            },
        )
        assert station_resp.status_code == 201, station_resp.text
        station_id = station_resp.json()["station"]["id"]

        cp_id = f"test-postboot-{uuid.uuid4().hex[:8]}"
        charger_resp = sync_client_admin.post(
            "/api/admin/chargers",
            json={
                "station_id": station_id,
                "name": "PostBoot Test Charger",
                "model": "TestModel",
                "vendor": "VOLTLYNC",
                "external_charger_id": cp_id,
                "connectors": [{"connector_id": 1, "connector_type": "Type2", "max_power_kw": 22.0}],
            },
        )
        assert charger_resp.status_code == 201, charger_resp.text
        cp_string_id = charger_resp.json()["charger"]["charge_point_string_id"]

        with sync_client_admin.websocket_connect(
            f"/ocpp/{cp_string_id}", subprotocols=["ocpp1.6"]
        ) as ws:
            ws.send_text(json.dumps([2, "boot1", "BootNotification", {
                "chargePointModel": "TestModel",
                "chargePointVendor": "VOLTLYNC",
            }]))

            msg = self._drain_for_data_transfer(ws)
            assert msg is not None, "No DataTransfer received after BootNotification"

            payload = msg[3]
            assert payload["vendorId"] == "VOLTLYNC"
            assert payload["messageId"] == "PostBootState"

            data = json.loads(payload["data"])
            assert data["hasPendingTransaction"] is False
            assert "lastMeterValueWh" in data

            # Accept the DataTransfer CALL
            ws.send_text(json.dumps([3, msg[1], {"status": "Accepted"}]))
