"""
Tests for socket-type charger support.

Socket chargers (Mode 1&2) lack a Control Pilot signal and need special handling:
- Available status during a transaction triggers a grace period instead of immediate failure
- Remote start is allowed from Available state
- QR payments can start from Available state
"""

import pytest
import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    ChargingStation, Charger, Connector, Transaction, MeterValue,
    TransactionStatusEnum, User, ChargerStatusEnum,
)
from main import connected_charge_points
from services.charger_type_service import (
    is_socket_charger,
    is_socket_charger_cached,
    should_use_grace_period,
)


# --- Unit Tests: charger_type_service ---

@pytest.mark.unit
class TestChargerTypeService:
    """Test the charger type detection helpers."""

    @pytest.mark.asyncio
    async def test_is_socket_charger_true(self, client, test_station):
        charger = await Charger.create(
            charge_point_string_id="socket-charger-1",
            station_id=test_station.id,
            name="Socket Charger",
            latest_status=ChargerStatusEnum.AVAILABLE,
        )
        await Connector.create(
            charger_id=charger.id,
            connector_id=1,
            connector_type="Socket",
            max_power_kw=3.3,
        )
        assert await is_socket_charger("socket-charger-1") is True

    @pytest.mark.asyncio
    async def test_is_socket_charger_false_for_type2(self, client, test_charger):
        assert await is_socket_charger(test_charger.charge_point_string_id) is False

    @pytest.mark.asyncio
    async def test_is_socket_charger_false_when_not_found(self, client):
        assert await is_socket_charger("nonexistent-charger") is False

    @pytest.mark.asyncio
    async def test_is_socket_charger_cached_from_cache(self, client):
        cache = {"cp-1": {"connector_type": "Socket"}}
        assert await is_socket_charger_cached("cp-1", cache) is True

    @pytest.mark.asyncio
    async def test_is_socket_charger_cached_type2(self, client):
        cache = {"cp-2": {"connector_type": "Type2"}}
        assert await is_socket_charger_cached("cp-2", cache) is False

    @pytest.mark.asyncio
    async def test_is_socket_charger_cached_falls_back_to_db(self, client, test_station):
        charger = await Charger.create(
            charge_point_string_id="socket-cached-test",
            station_id=test_station.id,
            name="Socket DB",
            latest_status=ChargerStatusEnum.AVAILABLE,
        )
        await Connector.create(
            charger_id=charger.id,
            connector_id=1,
            connector_type="Socket",
            max_power_kw=3.3,
        )
        # Cache exists but without connector_type — should query DB and populate
        cache = {"socket-cached-test": {}}
        result = await is_socket_charger_cached("socket-cached-test", cache)
        assert result is True
        assert cache["socket-cached-test"]["connector_type"] == "Socket"

    def test_should_use_grace_period_available(self):
        assert should_use_grace_period("Available") is True

    def test_should_use_grace_period_faulted(self):
        assert should_use_grace_period("Faulted") is False

    def test_should_use_grace_period_unavailable(self):
        assert should_use_grace_period("Unavailable") is False

    def test_should_use_grace_period_reserved(self):
        assert should_use_grace_period("Reserved") is False


# --- Unit Tests: StatusNotification grace period ---

@pytest.mark.unit
class TestSocketGracePeriod:
    """Test that socket chargers get grace period on Available, Type 2 fails immediately."""

    @pytest.fixture
    async def socket_charger(self, test_station):
        charger = await Charger.create(
            charge_point_string_id="socket-sn-test",
            station_id=test_station.id,
            name="Socket SN Test",
            latest_status=ChargerStatusEnum.CHARGING,
        )
        await Connector.create(
            charger_id=charger.id,
            connector_id=1,
            connector_type="Socket",
            max_power_kw=3.3,
        )
        return charger

    @pytest.mark.asyncio
    async def test_socket_available_starts_grace_period(self, client, socket_charger, test_user):
        """Socket charger + Available should NOT immediately fail the transaction."""
        txn = await Transaction.create(
            user=test_user,
            charger=socket_charger,
            start_meter_kwh=0.0,
            transaction_status=TransactionStatusEnum.RUNNING,
        )

        from main import ChargePoint
        cp = ChargePoint.__new__(ChargePoint)
        cp.id = socket_charger.charge_point_string_id

        with patch('main.redis_manager') as mock_redis:
            mock_redis.get_socket_grace_period = AsyncMock(return_value=None)
            mock_redis.set_socket_grace_period = AsyncMock(return_value=True)

            await cp._start_socket_grace_period([txn])

            mock_redis.set_socket_grace_period.assert_called_once()
            call_args = mock_redis.set_socket_grace_period.call_args
            assert txn.id in call_args[0][1]  # transaction_ids

        # Verify transaction is still RUNNING (not failed)
        txn = await Transaction.filter(id=txn.id).first()
        assert txn.transaction_status == TransactionStatusEnum.RUNNING

    @pytest.mark.asyncio
    async def test_socket_grace_skips_if_already_active(self, client, socket_charger, test_user):
        """Duplicate grace periods should not be spawned."""
        txn = await Transaction.create(
            user=test_user,
            charger=socket_charger,
            start_meter_kwh=0.0,
            transaction_status=TransactionStatusEnum.RUNNING,
        )

        from main import ChargePoint
        cp = ChargePoint.__new__(ChargePoint)
        cp.id = socket_charger.charge_point_string_id

        with patch('main.redis_manager') as mock_redis:
            mock_redis.get_socket_grace_period = AsyncMock(
                return_value={"transaction_ids": [txn.id], "started_at": "2026-03-24T00:00:00+00:00"}
            )
            mock_redis.set_socket_grace_period = AsyncMock(return_value=True)

            await cp._start_socket_grace_period([txn])

            # Should NOT set a new grace period
            mock_redis.set_socket_grace_period.assert_not_called()

    @pytest.mark.asyncio
    async def test_type2_available_fails_immediately(self, client, test_charger, test_user):
        """Type 2 charger + Available should immediately fail the transaction."""
        txn = await Transaction.create(
            user=test_user,
            charger=test_charger,
            start_meter_kwh=0.0,
            transaction_status=TransactionStatusEnum.RUNNING,
        )
        await MeterValue.create(transaction=txn, reading_kwh=1.5, power_kw=3.0)

        from main import ChargePoint
        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id

        with patch('services.wallet_service.WalletService.process_transaction_billing', new_callable=AsyncMock) as mock_bill:
            mock_bill.return_value = (True, "OK", Decimal("10.00"))

            await cp._fail_transaction_with_billing(txn, "STATUS_CHANGE_TO_Available")

        txn = await Transaction.filter(id=txn.id).first()
        assert txn.transaction_status == TransactionStatusEnum.FAILED
        assert txn.stop_reason == "STATUS_CHANGE_TO_Available"

    @pytest.mark.asyncio
    async def test_socket_faulted_still_fails_immediately(self, client, socket_charger, test_user):
        """Faulted on socket charger should NOT get grace period."""
        assert should_use_grace_period("Faulted") is False


# --- Unit Tests: Grace timeout ---

@pytest.mark.unit
class TestSocketGraceTimeout:
    """Test the grace timeout background task."""

    @pytest.mark.asyncio
    async def test_grace_timeout_fails_when_no_meter_values(self, client, test_charger, test_user):
        """After grace period, transaction fails if no MeterValues arrived."""
        txn = await Transaction.create(
            user=test_user,
            charger=test_charger,
            start_meter_kwh=0.0,
            transaction_status=TransactionStatusEnum.RUNNING,
        )

        from main import ChargePoint
        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id

        grace_started = datetime.datetime.now(datetime.timezone.utc)

        with patch('services.wallet_service.WalletService.process_transaction_billing', new_callable=AsyncMock) as mock_bill:
            mock_bill.return_value = (True, "OK", Decimal("0"))
            # Use timeout=0 to avoid sleeping in tests
            await cp._socket_grace_timeout(txn.id, grace_started, timeout_seconds=0)

        txn = await Transaction.filter(id=txn.id).first()
        assert txn.transaction_status == TransactionStatusEnum.FAILED
        assert txn.stop_reason == "SOCKET_GRACE_TIMEOUT"

    @pytest.mark.asyncio
    async def test_grace_timeout_keeps_alive_with_meter_values(self, client, test_charger, test_user):
        """If MeterValues arrived during grace period, transaction stays RUNNING."""
        txn = await Transaction.create(
            user=test_user,
            charger=test_charger,
            start_meter_kwh=0.0,
            transaction_status=TransactionStatusEnum.RUNNING,
        )
        grace_started = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)

        # MeterValue created after grace started
        await MeterValue.create(transaction=txn, reading_kwh=1.0, power_kw=3.0)

        from main import ChargePoint
        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id

        await cp._socket_grace_timeout(txn.id, grace_started, timeout_seconds=0)

        txn = await Transaction.filter(id=txn.id).first()
        assert txn.transaction_status == TransactionStatusEnum.RUNNING

    @pytest.mark.asyncio
    async def test_grace_timeout_skips_completed_transaction(self, client, test_charger, test_user):
        """If transaction already completed, grace timeout does nothing."""
        txn = await Transaction.create(
            user=test_user,
            charger=test_charger,
            start_meter_kwh=0.0,
            end_meter_kwh=5.0,
            energy_consumed_kwh=5.0,
            transaction_status=TransactionStatusEnum.COMPLETED,
        )

        from main import ChargePoint
        cp = ChargePoint.__new__(ChargePoint)
        cp.id = test_charger.charge_point_string_id

        grace_started = datetime.datetime.now(datetime.timezone.utc)
        await cp._socket_grace_timeout(txn.id, grace_started, timeout_seconds=0)

        txn = await Transaction.filter(id=txn.id).first()
        assert txn.transaction_status == TransactionStatusEnum.COMPLETED


# --- Unit Tests: Remote start ---

@pytest.mark.unit
class TestSocketRemoteStart:
    """Test remote start status checks for socket vs Type 2 chargers."""

    @pytest.mark.asyncio
    async def test_remote_start_socket_from_available(self, client_admin, test_station, test_user):
        """Socket charger in Available should allow remote start."""
        charger = await Charger.create(
            charge_point_string_id="socket-rs-test",
            station_id=test_station.id,
            name="Socket RS",
            latest_status="Available",
        )
        await Connector.create(
            charger_id=charger.id,
            connector_id=1,
            connector_type="Socket",
            max_power_kw=3.3,
        )

        test_user.rfid_card_id = "TEST123"
        await test_user.save()

        # Mock charger as connected
        connected_charge_points["socket-rs-test"] = {
            "connected_at": datetime.datetime.now(datetime.timezone.utc),
            "connector_type": "Socket",
        }

        # send_ocpp_request lives in main.py and is lazy-imported by the chargers
        # router, so the patch target must be `main.send_ocpp_request`.
        with patch('main.send_ocpp_request', new_callable=AsyncMock) as mock_send, \
             patch('routers.chargers.is_charger_connected', new_callable=AsyncMock) as mock_connected:
            mock_connected.return_value = True
            mock_send.return_value = (True, {"status": "Accepted"})

            response = await client_admin.post(f"/api/admin/chargers/{charger.id}/remote-start")
            assert response.status_code == 200

        connected_charge_points.pop("socket-rs-test", None)

    @pytest.mark.asyncio
    async def test_remote_start_type2_from_available_fails(self, client_admin, test_charger, test_user):
        """Type 2 charger in Available should reject remote start."""
        test_charger.latest_status = "Available"
        await test_charger.save()

        test_user.rfid_card_id = "TEST456"
        await test_user.save()

        connected_charge_points[test_charger.charge_point_string_id] = {
            "connected_at": datetime.datetime.now(datetime.timezone.utc),
            "connector_type": "Type2",
        }

        with patch('routers.chargers.is_charger_connected', new_callable=AsyncMock) as mock_connected:
            mock_connected.return_value = True

            response = await client_admin.post(f"/api/admin/chargers/{test_charger.id}/remote-start")
            assert response.status_code == 409
            assert "Preparing" in response.json()["detail"]

        connected_charge_points.pop(test_charger.charge_point_string_id, None)


# --- Unit Tests: Create charger with Socket ---

@pytest.mark.unit
class TestCreateSocketCharger:
    """Test creating a charger with Socket connector type."""

    @pytest.mark.asyncio
    async def test_create_charger_with_socket_connector(self, client_admin, test_station):
        charger_data = {
            "station_id": test_station.id,
            "name": "Socket Charger",
            "model": "SocketPro",
            "vendor": "VoltLync",
            "connectors": [
                {
                    "connector_id": 1,
                    "connector_type": "Socket",
                    "max_power_kw": 3.3,
                }
            ],
        }
        response = await client_admin.post("/api/admin/chargers", json=charger_data)
        assert response.status_code == 201

        data = response.json()
        charger_id = data["charger"]["id"]

        connector = await Connector.filter(charger_id=charger_id).first()
        assert connector is not None
        assert connector.connector_type == "Socket"
        assert connector.max_power_kw == 3.3
