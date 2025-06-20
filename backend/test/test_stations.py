# tests/test_stations.py
import pytest
from httpx import AsyncClient
from fastapi import status
from tortoise.contrib.test import initializer, finalizer

from main import app
from models import ChargingStation, Charger

# Test database URL - use a separate test database
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
    await ChargingStation.all().delete()
    await Charger.all().delete()
    yield
    # Cleanup after test if needed

class TestStationEndpoints:
    """Integration tests for Station Management API"""
    
    async def test_create_station(self, client: AsyncClient):
        """Test creating a new station"""
        station_data = {
            "name": "Test Station",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "address": "123 Test Street, Bangalore"
        }
        
        response = await client.post("/api/admin/stations", json=station_data)
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["message"] == "Station created successfully"
        assert data["station"]["name"] == station_data["name"]
        assert data["station"]["latitude"] == station_data["latitude"]
        assert data["station"]["longitude"] == station_data["longitude"]
        assert "id" in data["station"]
        
        # Verify in database
        station = await ChargingStation.get(id=data["station"]["id"])
        assert station.name == station_data["name"]
    
    async def test_list_stations_empty(self, client: AsyncClient):
        """Test listing stations when none exist"""
        response = await client.get("/api/admin/stations")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 0
        assert data["data"] == []
        assert data["page"] == 1
        assert data["limit"] == 10
    
    async def test_list_stations_with_pagination(self, client: AsyncClient):
        """Test station listing with pagination"""
        # Create multiple stations
        for i in range(15):
            await ChargingStation.create(
                name=f"Station {i}",
                latitude=12.9716 + i * 0.01,
                longitude=77.5946 + i * 0.01,
                address=f"Address {i}"
            )
        
        # Test first page
        response = await client.get("/api/admin/stations?page=1&limit=10")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 15
        assert len(data["data"]) == 10
        assert data["page"] == 1
        
        # Test second page
        response = await client.get("/api/admin/stations?page=2&limit=10")
        data = response.json()
        assert len(data["data"]) == 5
        assert data["page"] == 2
    
    async def test_list_stations_with_search(self, client: AsyncClient):
        """Test station search functionality"""
        # Create test stations
        await ChargingStation.create(name="Bangalore Central", latitude=12.97, longitude=77.59, address="Central")
        await ChargingStation.create(name="Mumbai Station", latitude=19.07, longitude=72.87, address="Mumbai")
        await ChargingStation.create(name="Delhi Hub", latitude=28.61, longitude=77.20, address="Delhi")
        
        # Search for "Central"
        response = await client.get("/api/admin/stations?search=Central")
        data = response.json()
        assert data["total"] == 1
        assert data["data"][0]["name"] == "Bangalore Central"
    
    async def test_get_station_details(self, client: AsyncClient):
        """Test getting station details with chargers"""
        # Create station
        station = await ChargingStation.create(
            name="Test Station",
            latitude=12.9716,
            longitude=77.5946,
            address="Test Address"
        )
        
        # Create associated chargers
        await Charger.create(
            charge_point_string_id="charger-1",
            station_id=station.id,
            name="Charger 1",
            latest_status="AVAILABLE"
        )
        await Charger.create(
            charge_point_string_id="charger-2",
            station_id=station.id,
            name="Charger 2",
            latest_status="CHARGING"
        )
        
        response = await client.get(f"/api/admin/stations/{station.id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["station"]["name"] == "Test Station"
        assert len(data["chargers"]) == 2
        assert data["chargers"][0]["name"] == "Charger 1"
        assert data["chargers"][1]["latest_status"] == "CHARGING"
    
    async def test_get_station_not_found(self, client: AsyncClient):
        """Test getting non-existent station"""
        response = await client.get("/api/admin/stations/9999")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Station not found"
    
    async def test_update_station(self, client: AsyncClient):
        """Test updating station information"""
        # Create station
        station = await ChargingStation.create(
            name="Old Name",
            latitude=12.9716,
            longitude=77.5946,
            address="Old Address"
        )
        
        # Update station
        update_data = {
            "name": "New Name",
            "address": "New Address"
        }
        response = await client.put(f"/api/admin/stations/{station.id}", json=update_data)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["station"]["name"] == "New Name"
        assert data["station"]["address"] == "New Address"
        assert data["station"]["latitude"] == 12.9716  # Unchanged
        
        # Verify in database
        updated_station = await ChargingStation.get(id=station.id)
        assert updated_station.name == "New Name"
    
    async def test_update_station_partial(self, client: AsyncClient):
        """Test partial update of station"""
        station = await ChargingStation.create(
            name="Original",
            latitude=12.9716,
            longitude=77.5946,
            address="Original Address"
        )
        
        # Update only latitude
        response = await client.put(f"/api/admin/stations/{station.id}", json={"latitude": 13.0000})
        
        data = response.json()
        assert data["station"]["latitude"] == 13.0000
        assert data["station"]["name"] == "Original"  # Unchanged
    
    async def test_delete_station(self, client: AsyncClient):
        """Test deleting a station"""
        # Create station with charger
        station = await ChargingStation.create(
            name="To Delete",
            latitude=12.9716,
            longitude=77.5946,
            address="Delete Address"
        )
        charger = await Charger.create(
            charge_point_string_id="charger-delete",
            station_id=station.id,
            name="Charger to Delete",
            latest_status="AVAILABLE"
        )
        
        response = await client.delete(f"/api/admin/stations/{station.id}")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["message"] == "Station deleted successfully"
        
        # Verify station and charger are deleted
        assert await ChargingStation.filter(id=station.id).first() is None
        assert await Charger.filter(id=charger.id).first() is None
    
    async def test_delete_station_not_found(self, client: AsyncClient):
        """Test deleting non-existent station"""
        response = await client.delete("/api/admin/stations/9999")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Station not found"

# Run with: pytest tests/test_stations.py -v