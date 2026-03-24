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


# --- Integration Tests ---

WS_URL = "ws://localhost:8000"


@pytest.mark.integration
class TestPostBootStateIntegration:
    """Integration tests — require server running at localhost:8000."""

    def _connect(self, charge_point_id: str):
        try:
            ws = websocket.create_connection(f"{WS_URL}/ocpp/{charge_point_id}", timeout=10)
            return ws
        except (ConnectionRefusedError, websocket.WebSocketException):
            pytest.skip("Server not running at localhost:8000")

    def _send_and_recv(self, ws, action: str, payload: dict, msg_id: str = "1"):
        ws.send(json.dumps([2, msg_id, action, payload]))
        while True:
            raw = ws.recv()
            response = json.loads(raw)
            if response[0] == 3 and response[1] == msg_id:
                return response[2]
            if response[0] == 2:
                # Server CALL — accept it and continue waiting
                ws.send(json.dumps([3, response[1], {"status": "Accepted"}]))

    def _wait_for_data_transfer(self, ws, timeout: float = 15.0):
        """Wait for a DataTransfer CALL from the server."""
        ws.settimeout(timeout)
        try:
            while True:
                raw = ws.recv()
                parsed = json.loads(raw)
                if parsed[0] == 2 and parsed[2] == "DataTransfer":
                    return {"message_id": parsed[1], "payload": parsed[3]}
        except websocket.WebSocketTimeoutException:
            return None

    def test_post_boot_state_no_transaction(self):
        """BootNotification with no active transactions should receive meter-only PostBootState."""
        charge_point_id = "test-postboot-no-txn"
        ws = self._connect(charge_point_id)

        try:
            self._send_and_recv(ws, "BootNotification", {
                "chargePointModel": "TestModel",
                "chargePointVendor": "VOLTLYNC",
            }, msg_id="boot1")

            msg = self._wait_for_data_transfer(ws, timeout=10)
            assert msg is not None, "No DataTransfer received after BootNotification"

            payload = msg["payload"]
            assert payload["vendorId"] == "VOLTLYNC"
            assert payload["messageId"] == "PostBootState"

            data = json.loads(payload["data"])
            assert data["hasPendingTransaction"] is False
            assert "lastMeterValueWh" in data

            # Accept it
            ws.send(json.dumps([3, msg["message_id"], {"status": "Accepted"}]))
        finally:
            ws.close()
