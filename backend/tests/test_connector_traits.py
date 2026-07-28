"""Tests for the connector traits taxonomy and per-type suspend windows (ADR 0027).

Covers:
1. The CONNECTOR_TRAITS table: enum<->traits bijection, both axes per type,
   unknown-type safe defaults, canonicalization.
2. startable_statuses — the shared Preparing-vs-Available start gate.
3. Per-charger suspend-window resolution (latched 12h / unlatched 45min).
4. The post-boot regression (txn 999): BootNotification arms the connector
   type's window, never the old 300s timer.
5. /api/users/active-session includes SUSPENDED sessions.
"""
import uuid
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from models import (
    Charger,
    ChargerStatusEnum,
    Connector,
    ConnectorTypeEnum,
    Transaction,
    TransactionStatusEnum,
)
from services.charger_type_service import (
    CONNECTOR_TRAITS,
    UNKNOWN_TRAITS,
    canonical_connector_type,
    is_latching_connector_type,
    is_socket_connector_type,
    startable_statuses,
    traits_for,
)
from policy import (
    SUSPEND_WINDOW_LATCHED_SECONDS,
    SUSPEND_WINDOW_UNLATCHED_SECONDS,
)


# ============================================================================
# 1. Traits table — pure, no DB
# ============================================================================

def test_every_enum_member_has_a_traits_row():
    """A new connector type cannot be added without declaring both physical
    properties — the whole point of the table."""
    assert set(CONNECTOR_TRAITS.keys()) == set(ConnectorTypeEnum)


@pytest.mark.parametrize("member,starts_from_available,latching", [
    (ConnectorTypeEnum.SOCKET, True, False),
    (ConnectorTypeEnum.DOMESTIC, True, False),
    (ConnectorTypeEnum.TYPE1, True, True),
    (ConnectorTypeEnum.TYPE2, True, True),
    (ConnectorTypeEnum.CCS, False, True),
    (ConnectorTypeEnum.CHADEMO, False, True),
    (ConnectorTypeEnum.GBT, False, True),
])
def test_traits_table(member, starts_from_available, latching):
    traits = CONNECTOR_TRAITS[member]
    assert traits.starts_from_available is starts_from_available
    assert traits.latching is latching


def test_type2_is_the_orthogonality_case():
    """Type2 and Socket agree on the start gate but split on latching —
    the reason these are two axes, not one predicate."""
    assert is_socket_connector_type("Type2") == is_socket_connector_type("Socket")
    assert is_latching_connector_type("Type2") != is_latching_connector_type("Socket")


@pytest.mark.parametrize("raw,expected", [
    ("Type2", ConnectorTypeEnum.TYPE2),
    ("type 2", ConnectorTypeEnum.TYPE2),
    ("TYPE-2", ConnectorTypeEnum.TYPE2),
    ("type_2", ConnectorTypeEnum.TYPE2),
    ("gb/t", ConnectorTypeEnum.GBT),
    ("GBT", ConnectorTypeEnum.GBT),
    ("chademo", ConnectorTypeEnum.CHADEMO),
    ("  Socket  ", ConnectorTypeEnum.SOCKET),
    ("Domestic", ConnectorTypeEnum.DOMESTIC),
    ("Type2Socket", None),
    ("NACS", None),
    ("", None),
    (None, None),
])
def test_canonical_connector_type(raw, expected):
    assert canonical_connector_type(raw) == expected


def test_canonical_passes_enum_through():
    assert canonical_connector_type(ConnectorTypeEnum.CCS) is ConnectorTypeEnum.CCS


def test_unknown_type_gets_safe_defaults_on_both_axes():
    traits = traits_for("SomeFutureConnector")
    assert traits == UNKNOWN_TRAITS
    assert traits.starts_from_available is False  # never widen the start gate
    assert traits.latching is False               # never hold 12h on unknown


# ============================================================================
# 2. startable_statuses — the shared start gate
# ============================================================================

@pytest.mark.parametrize("connector_type", ["Socket", "Type1", "Type2", "domestic"])
def test_startable_from_available_for_socket_like(connector_type):
    assert startable_statuses(connector_type) == {
        ChargerStatusEnum.PREPARING,
        ChargerStatusEnum.AVAILABLE,
    }


@pytest.mark.parametrize("connector_type", ["CCS", "CHAdeMO", "GB/T", "Unknown", None])
def test_preparing_only_for_tethered_and_unknown(connector_type):
    assert startable_statuses(connector_type) == {ChargerStatusEnum.PREPARING}


# ============================================================================
# 3. Per-charger suspend-window resolution
# ============================================================================

async def _make_charger(test_station, connector_type=None) -> Charger:
    charger = await Charger.create(
        charge_point_string_id=str(uuid.uuid4()),
        station_id=test_station.id,
        name=f"Traits {connector_type or 'bare'}",
        latest_status="Available",
    )
    if connector_type is not None:
        await Connector.create(
            charger_id=charger.id, connector_id=1, connector_type=connector_type
        )
    return charger


class TestSuspendWindowResolution:

    @pytest.mark.asyncio
    async def test_latched_charger_gets_long_window(self, client, test_station):
        from services.disconnect_handler import suspend_window_seconds_for_charge_point
        charger = await _make_charger(test_station, "Type2")
        assert await suspend_window_seconds_for_charge_point(
            charger.charge_point_string_id
        ) == SUSPEND_WINDOW_LATCHED_SECONDS

    @pytest.mark.asyncio
    async def test_socket_charger_gets_short_window(self, client, test_station):
        from services.disconnect_handler import suspend_window_seconds_for_charge_point
        charger = await _make_charger(test_station, "Socket")
        assert await suspend_window_seconds_for_charge_point(
            charger.charge_point_string_id
        ) == SUSPEND_WINDOW_UNLATCHED_SECONDS

    @pytest.mark.asyncio
    async def test_connectorless_charger_gets_short_window(self, client, test_station):
        """No connector row -> unknown -> the safe (short) window."""
        from services.disconnect_handler import suspend_window_seconds_for_charge_point
        charger = await _make_charger(test_station, None)
        assert await suspend_window_seconds_for_charge_point(
            charger.charge_point_string_id
        ) == SUSPEND_WINDOW_UNLATCHED_SECONDS


# ============================================================================
# 4. Post-boot regression (txn 999) — boot arms the type's window, not 300s
# ============================================================================

@pytest.fixture
def swallow_background_tasks():
    def fake_create_task(coro):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()
    with patch("main.safe_create_task", side_effect=fake_create_task), \
            patch("services.transaction_finalizer.safe_create_task",
                  side_effect=fake_create_task):
        yield


class TestPostBootWindow:

    def _fake_chargepoint(self, charge_point_string_id):
        from main import ChargePoint
        fake = MagicMock(spec=ChargePoint)
        fake.id = charge_point_string_id
        fake._suspend_timeout = AsyncMock()
        return fake

    @pytest.mark.asyncio
    async def test_boot_arms_latched_window_for_type2(
        self, client, test_charger, test_user, swallow_background_tasks
    ):
        """txn 999 regression: a reboot must arm the connector type's window
        (12h for Type2), never the old 300s post-boot timer that killed 9
        sessions fleet-wide."""
        from main import ChargePoint
        recent = datetime.now(timezone.utc) - timedelta(seconds=30)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=recent,
            start_meter_kwh=0.0,
        )
        fake_cp = self._fake_chargepoint(test_charger.charge_point_string_id)
        now = datetime.now(timezone.utc)
        await ChargePoint._handle_ongoing_transaction_on_boot(fake_cp, txn, now)

        fake_cp._suspend_timeout.assert_called_once_with(
            txn.id, now, SUSPEND_WINDOW_LATCHED_SECONDS
        )

    @pytest.mark.asyncio
    async def test_boot_arms_short_window_for_socket(
        self, client, test_station, test_user, swallow_background_tasks
    ):
        from main import ChargePoint
        charger = await _make_charger(test_station, "Socket")
        recent = datetime.now(timezone.utc) - timedelta(seconds=30)
        txn = await Transaction.create(
            charger=charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=recent,
            start_meter_kwh=0.0,
        )
        fake_cp = self._fake_chargepoint(charger.charge_point_string_id)
        now = datetime.now(timezone.utc)
        await ChargePoint._handle_ongoing_transaction_on_boot(fake_cp, txn, now)

        fake_cp._suspend_timeout.assert_called_once_with(
            txn.id, now, SUSPEND_WINDOW_UNLATCHED_SECONDS
        )


# ============================================================================
# 5. /api/users/active-session includes SUSPENDED
# ============================================================================

class TestActiveSessionIncludesSuspended:

    @pytest.mark.asyncio
    async def test_suspended_session_is_visible(self, client, test_charger, test_user):
        """A session held through a disconnect is still the customer's live,
        paid session — the app must show it, not pretend nothing exists."""
        from main import app
        from auth_middleware import get_current_user_with_db

        await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=datetime.now(timezone.utc),
            start_meter_kwh=0.0,
        )
        app.dependency_overrides[get_current_user_with_db] = lambda: test_user
        try:
            resp = await client.get("/api/users/active-session")
        finally:
            app.dependency_overrides.pop(get_current_user_with_db, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["data"][0]["status"] == "SUSPENDED"
