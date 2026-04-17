# routers/public_stations.py
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
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

class ChargerConnectorInfo(BaseModel):
    connector_type: str
    max_power_kw: Optional[float]

class StationChargerInfo(BaseModel):
    charge_point_string_id: str
    name: str
    latest_status: str
    connectors: List[ChargerConnectorInfo]

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
    chargers: List[StationChargerInfo] = Field(default_factory=list)
    price_per_kwh: Optional[float]
    # Operator / franchisee business name for payer-payee transparency
    # (RBI Payment Aggregator mandate). None means the platform operates
    # this station directly.
    franchisee_name: Optional[str] = None

    class Config:
        from_attributes = True

class PublicStationsListResponse(BaseModel):
    data: List[PublicStationResponse]
    total: int


async def _fetch_stations_with_availability(
    include_charger_details: bool = True,
    station_filter=None,
) -> List[PublicStationResponse]:
    """Shared helper: fetch stations with real-time availability from Redis/heartbeat.

    Args:
        include_charger_details: If True, include individual charger info list.
        station_filter: Optional Tortoise queryset to filter stations.
    """
    from redis_manager import redis_manager
    from datetime import timezone

    qs = station_filter if station_filter is not None else ChargingStation.all()
    stations = await qs.prefetch_related(
        Prefetch('chargers', queryset=Charger.all().prefetch_related('connectors', 'tariffs'))
    ).select_related('franchisee')

    connected_charger_ids = set(await redis_manager.get_all_connected_chargers())
    current_time = datetime.now(timezone.utc)
    station_responses: List[PublicStationResponse] = []

    for station in stations:
        real_chargers = _filter_real_chargers(
            station.chargers, connected_charger_ids, current_time,
        )
        if not real_chargers:
            continue

        total_chargers = len(real_chargers)
        available_chargers = sum(
            1 for c in real_chargers if c.latest_status == ChargerStatusEnum.AVAILABLE
        )

        connector_details, all_connector_types = _aggregate_connectors(real_chargers)
        price_per_kwh = await _resolve_price(real_chargers)

        charger_info_list: List[StationChargerInfo] = []
        if include_charger_details:
            charger_info_list = _build_charger_info(real_chargers)

        station_responses.append(PublicStationResponse(
            id=station.id,
            name=station.name or f"Station {station.id}",
            latitude=station.latitude,
            longitude=station.longitude,
            address=station.address or "Address not available",
            available_chargers=available_chargers,
            total_chargers=total_chargers,
            connector_types=sorted(list(all_connector_types)),
            connector_details=sorted(connector_details, key=lambda x: x.connector_type),
            chargers=charger_info_list,
            price_per_kwh=price_per_kwh,
            franchisee_name=station.franchisee.business_name if station.franchisee else None,
        ))

    return station_responses


def _filter_real_chargers(chargers, connected_ids: set, now) -> list:
    """Return chargers that are WebSocket-connected and have a recent heartbeat."""
    from datetime import timezone

    real = []
    for charger in chargers:
        if charger.charge_point_string_id not in connected_ids:
            continue
        if not charger.last_heart_beat_time:
            continue
        diff = now - charger.last_heart_beat_time.replace(tzinfo=timezone.utc)
        if diff.total_seconds() > 120:
            continue
        real.append(charger)
    return real


def _aggregate_connectors(real_chargers):
    """Aggregate connector type counts and availability across chargers."""
    connector_type_counts: Dict[str, dict] = {}
    all_connector_types: set = set()

    for charger in real_chargers:
        charger_available = charger.latest_status == ChargerStatusEnum.AVAILABLE
        for conn in charger.connectors:
            ct = conn.connector_type
            all_connector_types.add(ct)
            if ct not in connector_type_counts:
                connector_type_counts[ct] = {
                    'available_count': 0, 'total_count': 0,
                    'max_power_kw': conn.max_power_kw,
                }
            connector_type_counts[ct]['total_count'] += 1
            if charger_available:
                connector_type_counts[ct]['available_count'] += 1
            if (conn.max_power_kw and connector_type_counts[ct]['max_power_kw']
                    and conn.max_power_kw > connector_type_counts[ct]['max_power_kw']):
                connector_type_counts[ct]['max_power_kw'] = conn.max_power_kw

    details = [
        ConnectorInfo(
            connector_type=ct,
            max_power_kw=d['max_power_kw'],
            available_count=d['available_count'],
            total_count=d['total_count'],
        )
        for ct, d in connector_type_counts.items()
    ]
    return details, all_connector_types


async def _resolve_price(real_chargers) -> Optional[float]:
    """Get price_per_kwh from charger tariffs or global tariff."""
    for charger in real_chargers:
        if charger.tariffs:
            return float(charger.tariffs[0].rate_per_kwh)
    global_tariff = await Tariff.filter(is_global=True).first()
    if global_tariff:
        return float(global_tariff.rate_per_kwh)
    return None


def _build_charger_info(real_chargers) -> List[StationChargerInfo]:
    """Build per-charger detail list."""
    result = []
    for charger in real_chargers:
        connectors = [
            ChargerConnectorInfo(
                connector_type=c.connector_type, max_power_kw=c.max_power_kw,
            )
            for c in charger.connectors
        ]
        result.append(StationChargerInfo(
            charge_point_string_id=charger.charge_point_string_id,
            name=charger.name or f"Charger {charger.id}",
            latest_status=charger.latest_status.value,
            connectors=connectors,
        ))
    return result


# Create router
router = APIRouter(
    prefix="/api/public/stations",
    tags=["Public Stations"]
)

@router.get("", response_model=PublicStationsListResponse)
async def list_public_stations(current_user: User = Depends(require_user())):
    """Get all charging stations with real-time availability and connector information (users only)"""
    station_responses = await _fetch_stations_with_availability(include_charger_details=True)
    return PublicStationsListResponse(
        data=station_responses,
        total=len(station_responses),
    )

@router.get("/{station_id}", response_model=PublicStationResponse)
async def get_public_station_details(station_id: int, current_user: User = Depends(require_user())):
    """Get detailed information for a specific station (users only)"""
    station_exists = await ChargingStation.filter(id=station_id).exists()
    if not station_exists:
        raise HTTPException(status_code=404, detail="Station not found")

    results = await _fetch_stations_with_availability(
        include_charger_details=True,
        station_filter=ChargingStation.filter(id=station_id),
    )
    if not results:
        raise HTTPException(status_code=404, detail="Station has no active chargers")

    return results[0]