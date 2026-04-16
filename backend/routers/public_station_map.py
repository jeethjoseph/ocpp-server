"""Public (no-auth) endpoint for charger map with real-time availability."""
import time
import logging
from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routers.public_stations import (
    ConnectorInfo,
    _fetch_stations_with_availability,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/public/stations/map",
    tags=["Public Station Map"],
)

# --- rate limiting (same pattern as public_qr_transactions) ----------------
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW = 60  # seconds


def _check_rate_limit(client_ip: str):
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    _rate_limit_store[client_ip] = [
        ts for ts in _rate_limit_store[client_ip] if ts > window_start
    ]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
        )
    _rate_limit_store[client_ip].append(now)


# --- response model (no individual charger IDs exposed) --------------------
class MapStationResponse(BaseModel):
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


class MapStationsListResponse(BaseModel):
    data: List[MapStationResponse]
    total: int


# --- endpoint --------------------------------------------------------------
@router.get("", response_model=MapStationsListResponse)
async def list_map_stations(request: Request):
    """Public charger map: returns stations with availability (no auth)."""
    _check_rate_limit(request.client.host)

    full_stations = await _fetch_stations_with_availability(
        include_charger_details=False,
    )

    map_stations = [
        MapStationResponse(
            id=s.id,
            name=s.name,
            latitude=s.latitude,
            longitude=s.longitude,
            address=s.address,
            available_chargers=s.available_chargers,
            total_chargers=s.total_chargers,
            connector_types=s.connector_types,
            connector_details=s.connector_details,
            price_per_kwh=s.price_per_kwh,
        )
        for s in full_stations
    ]

    return MapStationsListResponse(data=map_stations, total=len(map_stations))
