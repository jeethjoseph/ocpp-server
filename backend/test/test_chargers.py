# tests/test_chargers.py
import pytest
from httpx import AsyncClient
from fastapi import status
from tortoise.contrib.test import initializer, finalizer
from unittest.mock import patch, MagicMock
import uuid

from main import app, connected_charge_points
from models import ChargingStation, Charger, Connector, Transaction, OCPPLog

TEST_DB_URL = "postgres://user:pass@localhost:5432/test_ocpp_db"

@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="module")
async def client():
    initializer(
        ["models"],
        db_url=TEST_DB_URL,
        app_label="models",
    )
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    finalizer()

@pytest.fixture(autouse=True)
async def cleanup_db():
    """Clean up database before each test"""
    await Transaction.all().delete()
    await Connector.all().delete()
    await Charger.all().delete()
    await ChargingStation.all().delete()
    await OCPPLog.all().delete()
    # Clear connected charge points
    connected_charge_points.clear()
    yield

@pytest.fixture
async def test_station():
    """Create a test station"""
    return await ChargingStation.create(
        name="Test Station",
        latitude=12.9716,
        longitude=77.5946,
        address="Test Address"
    )

@pytest.fixture
async def test_charger(test_station):
    """Create a test charger"""
    charger = await Charger.create(
        charge_point_string_id=str(uuid.uuid4()),
        station_id=test_station.id,
        name="Test Charger",
        model="Model X",
        vendor="Vendor Y",
        serial_number="SN12345",
        latest_status="AVAILABLE"
    )
    # Create connectors
    await Connector.create(
        charger_id=charger.id,
        connector_id=1,
        connector_type="Type2",
        max_power_kw=22.0
    )
    return charger

class TestChargerEndpoints:
    """Integration tests for Charger Management API"""
    
    async def test_create_charger(self, client: AsyncClient, test_station):
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
        
        response = await client.post("/api/admin/chargers", json=charger_data)
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["message"] == "Charger onboarded successfully"
        assert data["charger"]["name"] == "New Charger"
        assert data["charger"]["latest_status"] == "UNAVAILABLE"
        assert "charge_point_string_id" in data["charger"]
        assert "ocpp_url" in data
        assert data["ocpp_url"].endswith(data["charger"]["charge_point_string_id"])
        
        # Verify connectors were created
        connectors = await Connector.filter(charger_id=data["charger"]["id"]).all()
        assert len(connectors) == 2
        assert connectors[0].connector_type in ["CCS2", "CHAdeMO"]
    
    async def test_create_charger_station_not_found(self, client: AsyncClient):
        """Test creating charger with non-existent station"""
        charger_data = {
            "station_id": 9999,
            "name": "New Charger",
            "connectors": [{"connector_id": 1, "connector_type": "Type2"}]
        }
        
        response = await client.post("/api/admin/chargers", json=charger_data)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Station not found"
    
    async def test_list_chargers(self, client: AsyncClient, test_station):
        """Test listing chargers with filters"""
        # Create multiple chargers
        for i in range(3):
            await Charger.create(
                charge_point_string_id=f"charger-{i}",
                station_id=test_station.id,
                name=f"Charger {i}",
                latest_status="AVAILABLE" if i < 2 else "CHARGING"
            )
        
        # Test basic listing
        response = await client.get("/api/admin/chargers")
        data = response.json()
        assert data["total"] == 3
        assert len(data["data"]) == 3
        
        # Test status filter
        response = await client.get("/api/admin/chargers?status=AVAILABLE")
        data = response.json()
        assert data["total"] == 2
        
        # Test station filter
        response = await client.get(f"/api/admin/chargers?station_id={test_station.id}")
        data = response.json()
        assert data["total"] == 3
    
    async def test_get_charger_details(self, client: AsyncClient, test_charger, test_station):
        """Test getting charger details"""
        response = await client.get(f"/api/admin/chargers/{test_charger.id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["charger"]["name"] == "Test Charger"
        assert data["station"]["name"] == "Test Station"
        assert len(data["connectors"]) == 1
        assert data["connectors"][0]["connector_type"] == "Type2"
        assert data["current_transaction"] is None
    
    async def test_get_charger_with_active_transaction(self, client: AsyncClient, test_charger):
        """Test getting charger with active transaction"""
        # Create active transaction
        transaction = await Transaction.create(
            user_id=1,
            charger_id=test_charger.id,
            vehicle_id=1,
            status="RUNNING"
        )
        
        response = await client.get(f"/api/admin/chargers/{test_charger.id}")
        data = response.json()
        
        assert data["current_transaction"] is not None
        assert data["current_transaction"]["id"] == transaction.id
        assert data["current_transaction"]["status"] == "RUNNING"
    
    async def test_update_charger(self, client: AsyncClient, test_charger):
        """Test updating charger information"""
        update_data = {
            "name": "Updated Charger",
            "latest_status": "UNAVAILABLE"
        }
        
        response = await client.put(f"/api/admin/chargers/{test_charger.id}", json=update_data)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["charger"]["name"] == "Updated Charger"
        assert data["charger"]["latest_status"] == "UNAVAILABLE"
        assert data["charger"]["model"] == "Model X"  # Unchanged
    
    async def test_delete_charger(self, client: AsyncClient, test_charger):
        """Test deleting a charger"""
        response = await client.delete(f"/api/admin/chargers/{test_charger.id}")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["message"] == "Charger removed successfully"
        
        # Verify charger and connectors are deleted
        assert await Charger.filter(id=test_charger.id).first() is None
        assert await Connector.filter(charger_id=test_charger.id).count() == 0
    
    @patch('main.send_ocpp_request')
    async def test_remote_stop_charging(self, mock_send_ocpp, client: AsyncClient, test_charger):
        """Test remote stop charging command"""
        # Create active transaction
        transaction = await Transaction.create(
            user_id=1,
            charger_id=test_charger.id,
            vehicle_id=1,
            status="RUNNING"
        )
        
        # Mock charger as connected
        connected_charge_points[test_charger.charge_point_string_id] = {
            "cp": MagicMock(),
            "websocket": MagicMock()
        }
        
        # Mock OCPP response
        mock_send_ocpp.return_value = (True, {"status": "Accepted"})
        
        response = await client.post(
            f"/api/admin/chargers/{test_charger.id}/remote-stop",
            json={"reason": "Operator request"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Stop command sent successfully"
        assert data["transaction_id"] == str(transaction.id)
        
        # Verify OCPP command was called
        mock_send_ocpp.assert_called_once_with(
            test_charger.charge_point_string_id,
            "RemoteStopTransaction",
            {"transactionId": transaction.id}
        )
    
    async def test_remote_stop_charger_not_connected(self, client: AsyncClient, test_charger):
        """Test remote stop when charger is offline"""
        # Create transaction
        await Transaction.create(
            user_id=1,
            charger_id=test_charger.id,
            vehicle_id=1,
            status="RUNNING"
        )
        
        response = await client.post(f"/api/admin/chargers/{test_charger.id}/remote-stop")
        
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["detail"] == "Charger is not connected"
    
    @patch('main.send_ocpp_request')
    async def test_change_availability(self, mock_send_ocpp, client: AsyncClient, test_charger):
        """Test changing charger availability"""
        # Mock charger as connected
        connected_charge_points[test_charger.charge_point_string_id] = {
            "cp": MagicMock(),
            "websocket": MagicMock()
        }
        
        # Mock OCPP response
        mock_send_ocpp.return_value = (True, {"status": "Accepted"})
        
        response = await client.post(
            f"/api/admin/chargers/{test_charger.id}/change-availability?type=Inoperative&connector_id=1"
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Availability changed to Inoperative successfully"
        
        # Verify OCPP command
        mock_send_ocpp.assert_called_once_with(
            test_charger.charge_point_string_id,
            "ChangeAvailability",
            {"connectorId": 1, "type": "Inoperative"}
        )
    
    async def test_change_availability_invalid_type(self, client: AsyncClient, test_charger):
        """Test change availability with invalid type"""
        response = await client.post(
            f"/api/admin/chargers/{test_charger.id}/change-availability?type=Invalid&connector_id=1"
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    async def test_get_charger_logs(self, client: AsyncClient, test_charger):
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
        response = await client.get(f"/api/admin/chargers/{test_charger.id}/logs")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 5
        assert len(data["data"]) == 5
        
        # Test direction filter
        response = await client.get(f"/api/admin/chargers/{test_charger.id}/logs?direction=IN")
        data = response.json()
        assert data["total"] == 3  # 3 IN messages
        
        # Test pagination
        response = await client.get(f"/api/admin/chargers/{test_charger.id}/logs?page=1&limit=2")
        data = response.json()
        assert len(data["data"]) == 2
        assert data["page"] == 1

# Run with: pytest tests/test_chargers.py -v