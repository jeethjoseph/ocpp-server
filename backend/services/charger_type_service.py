"""
Service for connector-type-aware charger behavior.

Socket-type chargers (Mode 1&2) lack a Control Pilot signal and may not
reliably report Preparing/Charging statuses. This service provides helpers
to adapt OCPP handling based on connector type.
"""
import logging
from typing import Optional

from models import Connector

logger = logging.getLogger(__name__)


async def is_socket_charger(charge_point_string_id: str) -> bool:
    """Check if charger has a socket-type connector (Mode 1&2)."""
    connector = await Connector.filter(
        charger__charge_point_string_id=charge_point_string_id
    ).first()
    if not connector:
        return False
    return connector.connector_type.lower() == "socket"


async def is_socket_charger_cached(
    charge_point_string_id: str,
    cache: dict,
) -> bool:
    """Check socket type using in-memory cache, falling back to DB."""
    cp_data = cache.get(charge_point_string_id)
    if cp_data and "connector_type" in cp_data:
        return cp_data["connector_type"].lower() == "socket"
    # Cache miss — query DB and populate cache
    connector = await Connector.filter(
        charger__charge_point_string_id=charge_point_string_id
    ).first()
    if not connector:
        return False
    if cp_data is not None:
        cp_data["connector_type"] = connector.connector_type
    return connector.connector_type.lower() == "socket"


def should_use_grace_period(status: str) -> bool:
    """Only grant a grace period for Available status on socket chargers.

    Faulted, Unavailable, and Reserved still trigger immediate failure
    because they indicate real hardware or operational issues.
    """
    return status == "Available"
