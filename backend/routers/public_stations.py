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
    count: int

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
    
    # Get all stations with their chargers and connectors
    stations = await ChargingStation.all().prefetch_related(
        Prefetch('chargers', queryset=Charger.all().prefetch_related('connectors', 'tariffs'))
    )
    
    station_responses = []
    
    for station in stations:
        # Calculate availability
        total_chargers = len(station.chargers)
        available_chargers = sum(1 for charger in station.chargers 
                               if charger.latest_status == ChargerStatusEnum.AVAILABLE)
        
        # Get unique connector types and their details
        connector_type_counts = {}
        all_connector_types = set()
        
        for charger in station.chargers:
            for connector in charger.connectors:
                connector_type = connector.connector_type
                all_connector_types.add(connector_type)
                
                if connector_type not in connector_type_counts:
                    connector_type_counts[connector_type] = {
                        'count': 0,
                        'max_power_kw': connector.max_power_kw
                    }
                connector_type_counts[connector_type]['count'] += 1
                
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
                count=details['count']
            )
            for conn_type, details in connector_type_counts.items()
        ]
        
        # Get pricing - use the most common tariff rate or global rate
        price_per_kwh = None
        if station.chargers:
            # Try to get a tariff from any charger, or global tariff
            for charger in station.chargers:
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
    
    station = await ChargingStation.filter(id=station_id).prefetch_related(
        Prefetch('chargers', queryset=Charger.all().prefetch_related('connectors', 'tariffs'))
    ).first()
    
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    
    # Same logic as above but for single station
    total_chargers = len(station.chargers)
    available_chargers = sum(1 for charger in station.chargers 
                           if charger.latest_status == ChargerStatusEnum.AVAILABLE)
    
    connector_type_counts = {}
    all_connector_types = set()
    
    for charger in station.chargers:
        for connector in charger.connectors:
            connector_type = connector.connector_type
            all_connector_types.add(connector_type)
            
            if connector_type not in connector_type_counts:
                connector_type_counts[connector_type] = {
                    'count': 0,
                    'max_power_kw': connector.max_power_kw
                }
            connector_type_counts[connector_type]['count'] += 1
            
            if (connector.max_power_kw and 
                connector_type_counts[connector_type]['max_power_kw'] and
                connector.max_power_kw > connector_type_counts[connector_type]['max_power_kw']):
                connector_type_counts[connector_type]['max_power_kw'] = connector.max_power_kw
    
    connector_details = [
        ConnectorInfo(
            connector_type=conn_type,
            max_power_kw=details['max_power_kw'],
            count=details['count']
        )
        for conn_type, details in connector_type_counts.items()
    ]
    
    # Get pricing
    price_per_kwh = None
    if station.chargers:
        for charger in station.chargers:
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