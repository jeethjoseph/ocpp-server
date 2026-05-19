# tests/test_chargers.py
import pytest
from httpx import AsyncClient
from fastapi import status
from unittest.mock import patch, MagicMock
import uuid
import random

from decimal import Decimal

from main import connected_charge_points
from models import Charger, Connector, Transaction, OCPPLog, Tariff, User, VehicleProfile, ChargerStatusEnum

@pytest.mark.unit
class TestChargerEndpoints:
    """Integration tests for Charger Management API"""
    
    @pytest.mark.asyncio
    async def test_create_charger(self, client_admin: AsyncClient, test_station):
        """Test creating a new charger"""
        charger_data = {
            "station_id": test_station.id,
            "name": "New Charger",
            "model": "FastCharge Pro",
            "vendor": "ChargeTech",
            "serial_number": "FCH123456",
            "connectors": [
                {
                    "connector_id": 1,
                    "connector_type": "CCS2",
                    "max_power_kw": 150.0
                },
                {
                    "connector_id": 2,
                    "connector_type": "CHAdeMO",
                    "max_power_kw": 50.0
                }
            ]
        }
        
        response = await client_admin.post("/api/admin/chargers", json=charger_data)
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["message"] == "Charger onboarded successfully"
        assert data["charger"]["name"] == "New Charger"
        assert data["charger"]["latest_status"] == ChargerStatusEnum.UNAVAILABLE.value
        assert "charge_point_string_id" in data["charger"]
        assert "ocpp_url" in data
        assert data["ocpp_url"].endswith(data["charger"]["charge_point_string_id"])
        
        # Verify connectors were created
        connectors = await Connector.filter(charger_id=data["charger"]["id"]).all()
        assert len(connectors) == 2
        assert connectors[0].connector_type in ["CCS2", "CHAdeMO"]
    
    @pytest.mark.asyncio
    async def test_create_charger_station_not_found(self, client_admin: AsyncClient):
        """Test creating charger with non-existent station"""
        charger_data = {
            "station_id": 9999,
            "name": "New Charger",
            "connectors": [{"connector_id": 1, "connector_type": "Type2"}]
        }
        
        response = await client_admin.post("/api/admin/chargers", json=charger_data)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Station not found"
    
    @pytest.mark.asyncio
    async def test_list_chargers(self, client_admin: AsyncClient, test_station):
        """Test listing chargers with filters"""
        # Create multiple chargers
        for i in range(3):
            await Charger.create(
                charge_point_string_id=f"charger-{i}",
                station_id=test_station.id,
                name=f"Charger {i}",
                latest_status=ChargerStatusEnum.AVAILABLE if i < 2 else ChargerStatusEnum.CHARGING
            )

        # Test basic listing
        response = await client_admin.get("/api/admin/chargers")
        data = response.json()
        assert data["total"] == 3
        assert len(data["data"]) == 3

        # Test status filter
        response = await client_admin.get(f"/api/admin/chargers?status={ChargerStatusEnum.AVAILABLE.value}")
        data = response.json()
        assert data["total"] == 2
        
        # Test station filter
        response = await client_admin.get(f"/api/admin/chargers?station_id={test_station.id}")
        data = response.json()
        assert data["total"] == 3
    
    @pytest.mark.asyncio
    async def test_get_charger_details(self, client_admin: AsyncClient, test_charger, test_station):
        """Test getting charger details"""
        response = await client_admin.get(f"/api/admin/chargers/{test_charger.id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["charger"]["name"] == "Test Charger"
        assert data["station"]["name"] == "Test Station"
        assert len(data["connectors"]) == 1
        assert data["connectors"][0]["connector_type"] == "Type2"
        assert data["current_transaction"] is None
    
    @pytest.mark.asyncio
    async def test_get_charger_with_active_transaction(self, client_admin: AsyncClient, test_charger, test_user, test_vehicle):
        """Test getting charger with active transaction"""
        # Only call test_vehicle once and reuse
        vehicle = test_vehicle
        user = test_user
        # Create active transaction with unique status
        transaction = await Transaction.create(
            user_id=user.id,
            charger_id=test_charger.id,
            vehicle_id=vehicle.id,
            transaction_status="RUNNING"
        )
        response = await client_admin.get(f"/api/admin/chargers/{test_charger.id}")
        data = response.json()
        assert data["current_transaction"] is not None
        # CurrentTransactionInfo Pydantic model now exposes only `transaction_id`
        assert data["current_transaction"]["transaction_id"] == transaction.id
    
    @pytest.mark.asyncio
    async def test_update_charger(self, client_admin: AsyncClient, test_charger):
        """Test updating charger information"""
        update_data = {
            "name": "Updated Charger",
            "latest_status": ChargerStatusEnum.UNAVAILABLE.value
        }

        response = await client_admin.put(f"/api/admin/chargers/{test_charger.id}", json=update_data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["charger"]["name"] == "Updated Charger"
        assert data["charger"]["latest_status"] == ChargerStatusEnum.UNAVAILABLE.value
        assert data["charger"]["model"] == "Model X"  # Unchanged
    
    @pytest.mark.asyncio
    async def test_delete_charger(self, client_admin: AsyncClient, test_charger):
        """Test deleting a charger"""
        response = await client_admin.delete(f"/api/admin/chargers/{test_charger.id}")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["message"] == "Charger removed successfully"
        
        # Verify charger and connectors are deleted
        assert await Charger.filter(id=test_charger.id).first() is None
        assert await Connector.filter(charger_id=test_charger.id).count() == 0
    
    @pytest.mark.asyncio
    @patch('main.send_ocpp_request')
    async def test_remote_stop_charging(self, mock_send_ocpp, client_admin: AsyncClient, test_charger):
        """Test remote stop charging command"""
        # Create unique user and vehicle for this test
        suffix = random.randint(100000000, 999999999)
        user = await User.create(
            email=f"stop_{suffix}@voltlync.test",
            phone_number=f"9{suffix}",
        )
        vehicle = await VehicleProfile.create(user=user)
        # Create active transaction
        transaction = await Transaction.create(
            user_id=user.id,
            charger_id=test_charger.id,
            vehicle_id=vehicle.id,
            transaction_status="RUNNING"
        )
        # Mock charger as connected
        connected_charge_points[test_charger.charge_point_string_id] = {
            "cp": MagicMock(),
            "websocket": MagicMock()
        }
        # Mock OCPP response
        mock_send_ocpp.return_value = (True, {"status": "Accepted"})
        response = await client_admin.post(
            f"/api/admin/chargers/{test_charger.id}/remote-stop",
            json={"reason": "Operator request"}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        # Endpoint message text changed when admin override path was added
        assert "stop command sent" in data["message"].lower()
        # transaction_id is now an int in the response, not a string
        assert data["transaction_id"] == transaction.id
        # Verify OCPP command was called — payload key changed from
        # transactionId (camelCase) to transaction_id (snake_case)
        mock_send_ocpp.assert_called_once_with(
            test_charger.charge_point_string_id,
            "RemoteStopTransaction",
            {"transaction_id": transaction.id}
        )
    
    @pytest.mark.asyncio
    async def test_remote_stop_charger_not_connected(self, client_admin: AsyncClient, test_charger):
        """Test remote stop when charger is offline"""
        # Create unique user and vehicle for this test
        suffix = random.randint(100000000, 999999999)
        user = await User.create(
            email=f"stop_offline_{suffix}@voltlync.test",
            phone_number=f"9{suffix}",
        )
        vehicle = await VehicleProfile.create(user=user)
        # Create transaction
        await Transaction.create(
            user_id=user.id,
            charger_id=test_charger.id,
            vehicle_id=vehicle.id,
            transaction_status="RUNNING"
        )
        response = await client_admin.post(f"/api/admin/chargers/{test_charger.id}/remote-stop")
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["detail"] == "Charger is not connected"
    
    @pytest.mark.asyncio
    @patch('main.send_ocpp_request')
    async def test_change_availability(self, mock_send_ocpp, client_admin: AsyncClient, test_charger):
        """Test changing charger availability"""
        # Mock charger as connected
        connected_charge_points[test_charger.charge_point_string_id] = {
            "cp": MagicMock(),
            "websocket": MagicMock()
        }
        
        # Mock OCPP response
        mock_send_ocpp.return_value = (True, {"status": "Accepted"})
        
        response = await client_admin.post(
            f"/api/admin/chargers/{test_charger.id}/change-availability?type=Inoperative&connector_id=1"
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        # Endpoint message text was simplified — was "Availability changed to ... successfully"
        assert "ChangeAvailability" in data["message"]

        # Verify OCPP command — payload key changed from connectorId to connector_id
        mock_send_ocpp.assert_called_once_with(
            test_charger.charge_point_string_id,
            "ChangeAvailability",
            {"connector_id": 1, "type": "Inoperative"}
        )
    
    @pytest.mark.asyncio
    async def test_change_availability_invalid_type(self, client_admin: AsyncClient, test_charger):
        """Test change availability with invalid type"""
        response = await client_admin.post(
            f"/api/admin/chargers/{test_charger.id}/change-availability?type=Invalid&connector_id=1"
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    @pytest.mark.asyncio
    async def test_get_charger_logs(self, client_admin: AsyncClient, test_charger):
        """Test getting OCPP logs for a charger"""
        # Create some logs
        for i in range(5):
            await OCPPLog.create(
                charge_point_id=test_charger.charge_point_string_id,
                direction="IN" if i % 2 == 0 else "OUT",
                message_type="OCPP",
                payload={"test": f"message{i}"},
                status="received"
            )
        
        # Test basic log retrieval
        response = await client_admin.get(f"/api/admin/chargers/{test_charger.id}/logs")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 5
        assert len(data["data"]) == 5
        
        # Test direction filter
        response = await client_admin.get(f"/api/admin/chargers/{test_charger.id}/logs?direction=IN")
        data = response.json()
        assert data["total"] == 3  # 3 IN messages
        
        # Test pagination
        response = await client_admin.get(f"/api/admin/chargers/{test_charger.id}/logs?page=1&limit=2")
        data = response.json()
        assert len(data["data"]) == 2
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_list_chargers_includes_tariff(
        self, client_admin: AsyncClient, test_charger, test_tariff
    ):
        """List endpoint populates tariff_per_kwh, tariff_gst_percent, and the
        operator-set tariff_per_kwh_all_in (post-ADR 0003)."""
        response = await client_admin.get("/api/admin/chargers")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        row = next(c for c in data["data"] if c["id"] == test_charger.id)
        assert row["tariff_per_kwh"] == pytest.approx(15.0, rel=1e-6)
        assert row["tariff_gst_percent"] == pytest.approx(18.0, rel=1e-6)
        # Fixture sets tariff_per_kwh_all_in to 17.70 (= 15 × 1.18, migration-equivalent)
        assert row["tariff_per_kwh_all_in"] == pytest.approx(17.70, rel=1e-6)
        # Legacy field is gone from responses.
        assert "tariff_per_kwh_incl_tax" not in row

    @pytest.mark.asyncio
    async def test_update_charger_with_all_in_tariff_back_derives_rate(
        self, client_admin: AsyncClient, test_charger, test_tariff
    ):
        """Updating with tariff_per_kwh_all_in back-derives rate_per_kwh
        server-side. ADR 0003 acceptance criterion."""
        response = await client_admin.put(
            f"/api/admin/chargers/{test_charger.id}",
            json={"tariff_per_kwh_all_in": 30.00},
        )
        assert response.status_code == status.HTTP_200_OK
        # 30 × 0.98 / 1.18 = 24.9152542... → 24.9153 (4dp, ROUND_HALF_UP)
        tariff = await Tariff.filter(charger_id=test_charger.id).first()
        assert tariff is not None
        assert tariff.tariff_per_kwh_all_in == Decimal("30.0000")
        assert tariff.rate_per_kwh == Decimal("24.9153")
        assert tariff.gst_percent == Decimal("18.00")
        assert response.json()["charger"]["tariff_per_kwh_all_in"] == pytest.approx(30.0, rel=1e-6)

    @pytest.mark.asyncio
    async def test_update_charger_validates_all_in_lower_bound(
        self, client_admin: AsyncClient, test_charger
    ):
        """tariff_per_kwh_all_in below ₹1.0 returns 422."""
        response = await client_admin.put(
            f"/api/admin/chargers/{test_charger.id}",
            json={"tariff_per_kwh_all_in": 0.5},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_update_charger_validates_all_in_upper_bound(
        self, client_admin: AsyncClient, test_charger
    ):
        """tariff_per_kwh_all_in above ₹100.0 returns 422."""
        response = await client_admin.put(
            f"/api/admin/chargers/{test_charger.id}",
            json={"tariff_per_kwh_all_in": 150.0},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_update_charger_rejects_legacy_tariff_fields(
        self, client_admin: AsyncClient, test_charger
    ):
        """The pre-ADR-0003 fields tariff_per_kwh and tariff_per_kwh_incl_tax
        are no longer accepted — `extra='forbid'` returns 422."""
        for legacy_field in ("tariff_per_kwh", "tariff_per_kwh_incl_tax"):
            response = await client_admin.put(
                f"/api/admin/chargers/{test_charger.id}",
                json={legacy_field: 12.0},
            )
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, (
                f"Legacy field {legacy_field} should be rejected"
            )

    @pytest.mark.asyncio
    async def test_create_charger_with_all_in_tariff(
        self, client_admin: AsyncClient, test_station
    ):
        """Creating a charger with tariff_per_kwh_all_in back-derives rate_per_kwh."""
        payload = {
            "station_id": test_station.id,
            "name": "All-in Charger",
            "connectors": [{"connector_id": 1, "connector_type": "Type2", "max_power_kw": 22.0}],
            "tariff_per_kwh_all_in": 25.0,
        }
        response = await client_admin.post("/api/admin/chargers", json=payload)
        assert response.status_code == status.HTTP_201_CREATED
        charger_id = response.json()["charger"]["id"]
        tariff = await Tariff.filter(charger_id=charger_id).first()
        assert tariff is not None
        # 25 × 0.98 / 1.18 = 20.7627 (4dp)
        assert tariff.rate_per_kwh == Decimal("20.7627")
        assert tariff.tariff_per_kwh_all_in == Decimal("25.0000")

    # ========================================================================
    # Transactional atomicity (issue 05 / M6)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_create_charger_rolls_back_on_tariff_failure(
        self, client_admin: AsyncClient, test_station
    ):
        """If Tariff.create raises mid-request, neither the Charger nor the
        Connector rows persist — all three writes are wrapped in a transaction.
        The audit row IS written (rollback-audit, issue 05) so the attempted
        creation is captured even though the data was rolled back."""
        from unittest.mock import patch
        from tortoise.exceptions import IntegrityError
        from models import Connector, AuditLog

        charger_count_before = await Charger.filter(station_id=test_station.id).count()
        connector_count_before = await Connector.all().count()
        failed_audit_count_before = await AuditLog.filter(
            action="charger.create_failed"
        ).count()

        payload = {
            "station_id": test_station.id,
            "name": "Rollback Test Charger",
            "serial_number": "ROLLBACK-001",
            "connectors": [
                {"connector_id": 1, "connector_type": "Type2", "max_power_kw": 22.0}
            ],
            "tariff_per_kwh_all_in": 25.0,
        }

        # Patch Tariff.create to raise — simulates a DB constraint blowing up
        # the third step of the create sequence.
        with patch(
            "routers.chargers.Tariff.create",
            side_effect=IntegrityError("simulated tariff insert failure"),
        ):
            response = await client_admin.post("/api/admin/chargers", json=payload)

        # Backend should surface a 400 (the existing except branch catches it).
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Critical assertion: NO charger or connector row was created. The
        # transaction rolled back atomically.
        charger_count_after = await Charger.filter(station_id=test_station.id).count()
        connector_count_after = await Connector.all().count()
        assert charger_count_after == charger_count_before, (
            "Charger persisted despite tariff insert failure — transaction rollback broken"
        )
        assert connector_count_after == connector_count_before, (
            "Connector persisted despite tariff insert failure — transaction rollback broken"
        )

        # The audit row is written OUTSIDE the transaction so it survives
        # rollback. Ops needs this signal to investigate failed onboardings.
        failed_audit_count_after = await AuditLog.filter(
            action="charger.create_failed"
        ).count()
        assert failed_audit_count_after == failed_audit_count_before + 1, (
            "Rollback-audit not written — operators can't see failed create attempts"
        )

    @pytest.mark.asyncio
    async def test_create_charger_happy_path_persists_all_three_rows(
        self, client_admin: AsyncClient, test_station
    ):
        """Regression guard for the transaction wrapper: happy path still
        creates Charger + Connector + Tariff."""
        from models import Connector

        payload = {
            "station_id": test_station.id,
            "name": "Happy Path Charger",
            "serial_number": "HAPPY-001",
            "connectors": [
                {"connector_id": 1, "connector_type": "Type2", "max_power_kw": 22.0},
                {"connector_id": 2, "connector_type": "CCS", "max_power_kw": 50.0},
            ],
            "tariff_per_kwh_all_in": 18.0,
        }
        response = await client_admin.post("/api/admin/chargers", json=payload)
        assert response.status_code == status.HTTP_201_CREATED

        charger_id = response.json()["charger"]["id"]
        charger = await Charger.filter(id=charger_id).first()
        assert charger is not None
        assert await Connector.filter(charger_id=charger_id).count() == 2
        assert await Tariff.filter(charger_id=charger_id).count() == 1

# Run with: pytest tests/test_chargers.py -v