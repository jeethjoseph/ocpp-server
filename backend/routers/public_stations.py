# routers/public_stations.py
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime
from enum import Enum

from models import ChargingStation, Charger, Connector, Tariff, ChargerStatusEnum, User
from tortoise.functions import Count, Sum
from tortoise.query_utils import Prefetch
from auth_middleware import require_user

# Pydantic schemas for public API
class ConnectorInfo(BaseModel):
    connector_type: str
    max_power_kw: Optional[float]
    available_count: int
    total_count: int

class PublicStationResponse(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    address: str
    available_chargers: int
    total_chargers: int
    connector_types: List[str]
    connector_details: List[ConnectorInfo]
    price_per_kwh: Optional[float]
    
    class Config:
        from_attributes = True

class PublicStationsListResponse(BaseModel):
    data: List[PublicStationResponse]
    total: int

# Create router
router = APIRouter(
    prefix="/api/public/stations",
    tags=["Public Stations"]
)

@router.get("", response_model=PublicStationsListResponse)
async def list_public_stations(current_user: User = Depends(require_user())):
    """Get all charging stations with real-time availability and connector information (users only)"""

    # Import Redis manager for checking real connections
    from redis_manager import redis_manager
    from datetime import timezone

    # Get all stations with their chargers and connectors
    stations = await ChargingStation.all().prefetch_related(
        Prefetch('chargers', queryset=Charger.all().prefetch_related('connectors', 'tariffs'))
    )

    # Get connected chargers from Redis
    connected_charger_ids = set(await redis_manager.get_all_connected_chargers())

    station_responses = []

    for station in stations:
        # Filter to only chargers that are actually connected and have recent heartbeats
        current_time = datetime.now(timezone.utc)
        real_chargers = []

        for charger in station.chargers:
            # Check if charger is in Redis (connected via WebSocket)
            is_connected_redis = charger.charge_point_string_id in connected_charger_ids
            if not is_connected_redis:
                continue

            # Check heartbeat timeout (90 seconds)
            if charger.last_heart_beat_time:
                time_diff = current_time - charger.last_heart_beat_time.replace(tzinfo=timezone.utc)
                if time_diff.total_seconds() > 90:
                    continue
            else:
                continue

            # Only include chargers that pass both checks
            real_chargers.append(charger)

        # Skip stations with no real connected chargers
        if not real_chargers:
            continue

        # Calculate availability from REAL connected chargers only
        total_chargers = len(real_chargers)
        available_chargers = sum(1 for charger in real_chargers
                               if charger.latest_status == ChargerStatusEnum.AVAILABLE)
        
        # Get unique connector types and their details from REAL chargers only
        connector_type_counts = {}
        all_connector_types = set()

        for charger in real_chargers:
            charger_is_available = charger.latest_status == ChargerStatusEnum.AVAILABLE

            for connector in charger.connectors:
                connector_type = connector.connector_type
                all_connector_types.add(connector_type)

                if connector_type not in connector_type_counts:
                    connector_type_counts[connector_type] = {
                        'available_count': 0,
                        'total_count': 0,
                        'max_power_kw': connector.max_power_kw
                    }

                # Count total connectors
                connector_type_counts[connector_type]['total_count'] += 1

                # Count available connectors (only if charger is available)
                if charger_is_available:
                    connector_type_counts[connector_type]['available_count'] += 1

                # Keep the highest power rating for this connector type
                if (connector.max_power_kw and
                    connector_type_counts[connector_type]['max_power_kw'] and
                    connector.max_power_kw > connector_type_counts[connector_type]['max_power_kw']):
                    connector_type_counts[connector_type]['max_power_kw'] = connector.max_power_kw
        
        # Create connector details
        connector_details = [
            ConnectorInfo(
                connector_type=conn_type,
                max_power_kw=details['max_power_kw'],
                available_count=details['available_count'],
                total_count=details['total_count']
            )
            for conn_type, details in connector_type_counts.items()
        ]
        
        # Get pricing - use the most common tariff rate or global rate from REAL chargers only
        price_per_kwh = None
        if real_chargers:
            # Try to get a tariff from any real charger, or global tariff
            for charger in real_chargers:
                if charger.tariffs:
                    # Use the first available tariff
                    price_per_kwh = float(charger.tariffs[0].rate_per_kwh)
                    break

            # If no charger-specific tariff, check for global tariffs
            if price_per_kwh is None:
                global_tariff = await Tariff.filter(is_global=True).first()
                if global_tariff:
                    price_per_kwh = float(global_tariff.rate_per_kwh)
        
        station_response = PublicStationResponse(
            id=station.id,
            name=station.name or f"Station {station.id}",
            latitude=station.latitude,
            longitude=station.longitude,
            address=station.address or "Address not available",
            available_chargers=available_chargers,
            total_chargers=total_chargers,
            connector_types=sorted(list(all_connector_types)),
            connector_details=sorted(connector_details, key=lambda x: x.connector_type),
            price_per_kwh=price_per_kwh
        )
        
        station_responses.append(station_response)
    
    return PublicStationsListResponse(
        data=station_responses,
        total=len(station_responses)
    )

@router.get("/{station_id}", response_model=PublicStationResponse)
async def get_public_station_details(station_id: int, current_user: User = Depends(require_user())):
    """Get detailed information for a specific station (users only)"""

    # Import Redis manager for checking real connections
    from redis_manager import redis_manager
    from datetime import timezone

    station = await ChargingStation.filter(id=station_id).prefetch_related(
        Prefetch('chargers', queryset=Charger.all().prefetch_related('connectors', 'tariffs'))
    ).first()

    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    # Get connected chargers from Redis
    connected_charger_ids = set(await redis_manager.get_all_connected_chargers())

    # Filter to only chargers that are actually connected and have recent heartbeats
    current_time = datetime.now(timezone.utc)
    real_chargers = []

    for charger in station.chargers:
        # Check if charger is in Redis (connected via WebSocket)
        is_connected_redis = charger.charge_point_string_id in connected_charger_ids
        if not is_connected_redis:
            continue

        # Check heartbeat timeout (90 seconds)
        if charger.last_heart_beat_time:
            time_diff = current_time - charger.last_heart_beat_time.replace(tzinfo=timezone.utc)
            if time_diff.total_seconds() > 90:
                continue
        else:
            continue

        # Only include chargers that pass both checks
        real_chargers.append(charger)

    # Return 404 if no real connected chargers
    if not real_chargers:
        raise HTTPException(status_code=404, detail="Station has no active chargers")

    # Calculate availability from REAL connected chargers only
    total_chargers = len(real_chargers)
    available_chargers = sum(1 for charger in real_chargers
                           if charger.latest_status == ChargerStatusEnum.AVAILABLE)
    
    connector_type_counts = {}
    all_connector_types = set()

    for charger in real_chargers:
        charger_is_available = charger.latest_status == ChargerStatusEnum.AVAILABLE

        for connector in charger.connectors:
            connector_type = connector.connector_type
            all_connector_types.add(connector_type)

            if connector_type not in connector_type_counts:
                connector_type_counts[connector_type] = {
                    'available_count': 0,
                    'total_count': 0,
                    'max_power_kw': connector.max_power_kw
                }

            # Count total connectors
            connector_type_counts[connector_type]['total_count'] += 1

            # Count available connectors (only if charger is available)
            if charger_is_available:
                connector_type_counts[connector_type]['available_count'] += 1

            if (connector.max_power_kw and
                connector_type_counts[connector_type]['max_power_kw'] and
                connector.max_power_kw > connector_type_counts[connector_type]['max_power_kw']):
                connector_type_counts[connector_type]['max_power_kw'] = connector.max_power_kw
    
    connector_details = [
        ConnectorInfo(
            connector_type=conn_type,
            max_power_kw=details['max_power_kw'],
            available_count=details['available_count'],
            total_count=details['total_count']
        )
        for conn_type, details in connector_type_counts.items()
    ]
    
    # Get pricing from REAL chargers only
    price_per_kwh = None
    if real_chargers:
        for charger in real_chargers:
            if charger.tariffs:
                price_per_kwh = float(charger.tariffs[0].rate_per_kwh)
                break

        if price_per_kwh is None:
            global_tariff = await Tariff.filter(is_global=True).first()
            if global_tariff:
                price_per_kwh = float(global_tariff.rate_per_kwh)
    
    return PublicStationResponse(
        id=station.id,
        name=station.name or f"Station {station.id}",
        latitude=station.latitude,
        longitude=station.longitude,
        address=station.address or "Address not available",
        available_chargers=available_chargers,
        total_chargers=total_chargers,
        connector_types=sorted(list(all_connector_types)),
        connector_details=sorted(connector_details, key=lambda x: x.connector_type),
        price_per_kwh=price_per_kwh
    )