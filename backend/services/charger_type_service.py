"""
Service for connector-type-aware charger behavior.

Socket-type chargers (Mode 1&2) lack a Control Pilot signal and may not
reliably report Preparing/Charging statuses. This service provides helpers
to adapt OCPP handling based on connector type.
"""
import logging
import re
from typing import Optional

from models import Connector

logger = logging.getLogger(__name__)

# Untethered connector types — the driver plugs in their own cable, so the
# charger idles in "Available" and CAN be remote-started from Available.
# Tethered/DC types (CCS, CHAdeMO, GB/T) go to "Preparing" first; anything we
# don't recognise defaults to tethered. Mirrors the frontend `isSocketCharger`
# taxonomy in `frontend/lib/utils.ts` — keep the two in sync.
# See socket-charger-classification issue 01.
SOCKET_CONNECTOR_TYPES = {"socket", "type1", "type2", "domestic"}


def is_socket_connector_type(connector_type: Optional[str]) -> bool:
    """True for untethered (socket / Type1 / Type2 / domestic) connector types."""
    if not connector_type:
        return False
    normalized = re.sub(r"[\s_-]+", "", connector_type.strip().lower())
    return normalized in SOCKET_CONNECTOR_TYPES


async def is_socket_charger(charge_point_string_id: str) -> bool:
    """Check if charger has an untethered (socket-type) connector."""
    connector = await Connector.filter(
        charger__charge_point_string_id=charge_point_string_id
    ).first()
    return is_socket_connector_type(connector.connector_type) if connector else False


async def is_socket_charger_cached(
    charge_point_string_id: str,
    cache: dict,
) -> bool:
    """Check socket type using in-memory cache, falling back to DB."""
    cp_data = cache.get(charge_point_string_id)
    if cp_data and "connector_type" in cp_data:
        return is_socket_connector_type(cp_data["connector_type"])
    # Cache miss — query DB and populate cache
    connector = await Connector.filter(
        charger__charge_point_string_id=charge_point_string_id
    ).first()
    if not connector:
        return False
    if cp_data is not None:
        cp_data["connector_type"] = connector.connector_type
    return is_socket_connector_type(connector.connector_type)


def should_use_grace_period(status: str) -> bool:
    """Only grant a grace period for Available status on socket chargers.

    Faulted, Unavailable, and Reserved still trigger immediate failure
    because they indicate real hardware or operational issues.
    """
    return status == "Available"
