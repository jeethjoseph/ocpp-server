"""
Service for connector-type-aware charger behavior.

One `connector_type` column carries TWO orthogonal physical properties, so
each canonical type declares both in CONNECTOR_TRAITS:

- `starts_from_available` — does the connector lack a Control Pilot signal?
  Socket-type chargers (Mode 1&2) can't detect a plugged-in vehicle, never
  emit Preparing, and so must be startable from Available.
- `latching` — does the connector lock into the vehicle inlet? A latched
  cable can't be removed mid-session, so a disconnected session can safely
  be held for the long suspend window (see policy.py).

Type2 is the reason these are two axes, not one: it starts from Available
(same bucket as Socket) but latches (opposite bucket from Socket).

Mirrors the frontend `isSocketCharger` taxonomy in `frontend/lib/utils.ts`
(start-gate axis only) — keep the two in sync.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional, Set, Union

from models import ChargerStatusEnum, Connector, ConnectorTypeEnum

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConnectorTraits:
    starts_from_available: bool
    latching: bool


CONNECTOR_TRAITS = {
    ConnectorTypeEnum.SOCKET: ConnectorTraits(starts_from_available=True, latching=False),
    ConnectorTypeEnum.DOMESTIC: ConnectorTraits(starts_from_available=True, latching=False),
    ConnectorTypeEnum.TYPE1: ConnectorTraits(starts_from_available=True, latching=True),
    ConnectorTypeEnum.TYPE2: ConnectorTraits(starts_from_available=True, latching=True),
    ConnectorTypeEnum.CCS: ConnectorTraits(starts_from_available=False, latching=True),
    ConnectorTypeEnum.CHADEMO: ConnectorTraits(starts_from_available=False, latching=True),
    ConnectorTypeEnum.GBT: ConnectorTraits(starts_from_available=False, latching=True),
}

# Unknown types get the safe default on each axis independently: require
# Preparing to start (never widen the start gate for an unrecognised type)
# and the short suspend window (never hold a possibly-unlatched cable 12h).
UNKNOWN_TRAITS = ConnectorTraits(starts_from_available=False, latching=False)


def _normalize(value: Union[str, ConnectorTypeEnum]) -> str:
    return re.sub(r"[\s_\-/]+", "", str(value).strip().lower())


_NORMALIZED_TO_ENUM = {_normalize(member.value): member for member in ConnectorTypeEnum}
# Real-world labels that canonicalize onto an enum member (not typos): CCS1 and
# CCS2 are the two CCS combo variants — both are CCS for every behavior we key
# off connector_type (tethered start gate, latching suspend window).
_NORMALIZED_TO_ENUM.update({
    "ccs1": ConnectorTypeEnum.CCS,
    "ccs2": ConnectorTypeEnum.CCS,
})


def canonical_connector_type(
    value: Optional[Union[str, ConnectorTypeEnum]],
) -> Optional[ConnectorTypeEnum]:
    """Map a raw connector-type string to its canonical enum member.

    Case/space/underscore/hyphen/slash-insensitive ("type 2" -> TYPE2,
    "gb/t" -> GBT). Returns None for empty or unrecognised input.
    """
    if isinstance(value, ConnectorTypeEnum):
        return value
    if not value:
        return None
    return _NORMALIZED_TO_ENUM.get(_normalize(value))


def traits_for(connector_type: Optional[Union[str, ConnectorTypeEnum]]) -> ConnectorTraits:
    member = canonical_connector_type(connector_type)
    return CONNECTOR_TRAITS[member] if member else UNKNOWN_TRAITS


def is_socket_connector_type(connector_type: Optional[Union[str, ConnectorTypeEnum]]) -> bool:
    """True for untethered (socket / Type1 / Type2 / domestic) connector types."""
    return traits_for(connector_type).starts_from_available


def is_latching_connector_type(connector_type: Optional[Union[str, ConnectorTypeEnum]]) -> bool:
    """True when the connector latches into the vehicle inlet (long suspend
    window is safe). Unknown -> False (short window is the safe default)."""
    return traits_for(connector_type).latching


def startable_statuses(
    connector_type: Optional[Union[str, ConnectorTypeEnum]],
) -> Set[ChargerStatusEnum]:
    """Charger statuses from which a remote start may be dispatched.

    Single source of truth for the Preparing-vs-Available start gate —
    replaces the previously hand-rolled sets in routers/chargers.py and
    services/qr_payment_service.py.
    """
    if traits_for(connector_type).starts_from_available:
        return {ChargerStatusEnum.PREPARING, ChargerStatusEnum.AVAILABLE}
    return {ChargerStatusEnum.PREPARING}


async def _connector_type_for_charge_point(
    charge_point_string_id: str,
) -> Optional[str]:
    connector = await Connector.filter(
        charger__charge_point_string_id=charge_point_string_id
    ).first()
    return connector.connector_type if connector else None


async def is_socket_charger(charge_point_string_id: str) -> bool:
    """Check if charger has an untethered (socket-type) connector."""
    return is_socket_connector_type(
        await _connector_type_for_charge_point(charge_point_string_id)
    )


async def is_latching_charger(charge_point_string_id: str) -> bool:
    """Check if charger's connector latches (drives the suspend window).

    Resolution uses the charger's first connector — valid under the current
    1:1 charger:connector invariant. Revisit with multi-connector support.
    """
    return is_latching_connector_type(
        await _connector_type_for_charge_point(charge_point_string_id)
    )


async def is_latching_charger_by_charger_id(charger_id: int) -> bool:
    """Same as is_latching_charger, keyed by Charger PK (for Transaction rows)."""
    connector = await Connector.filter(charger_id=charger_id).first()
    return is_latching_connector_type(connector.connector_type) if connector else False


async def startable_statuses_for_charger(
    charge_point_string_id: str,
) -> Set[ChargerStatusEnum]:
    """Startable-statuses set resolved from the charger's connector."""
    return startable_statuses(
        await _connector_type_for_charge_point(charge_point_string_id)
    )


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
