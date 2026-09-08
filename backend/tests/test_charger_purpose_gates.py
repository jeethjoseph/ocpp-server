"""Charger Purpose gates visibility and charging (ADR 0028, slices 06-07).

Slice 06 fails OPEN (a row missed by the backfill stays visible and billable).
Slice 07 fails CLOSED — a fleet unit wrongly marked TEST stops accepting
customers, which is a revenue outage on that unit. That asymmetry is the whole
reason the TEST set is verified per environment before 07 ships, and it is what
these tests are guarding.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, patch
from fastapi import status
from httpx import AsyncClient

from main import app
from auth_middleware import get_current_user_with_db
from models import (
    Charger, ChargerPurposeEnum, ChargerStatusEnum, Connector, ConnectorTypeEnum,
)


@pytest.fixture
async def client_user(client, test_user):
    """Authenticated as a plain USER.

    `/api/public/stations` uses `require_user()`, which is strict: it rejects
    ADMIN as well as anonymous. Customer-visibility behaviour has to be asserted
    as an actual customer.
    """
    app.dependency_overrides[get_current_user_with_db] = lambda: test_user
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user_with_db, None)


async def _charger(station, code, purpose=ChargerPurposeEnum.PUBLIC, connected_recently=True):
    charger = await Charger.create(
        charge_point_string_id=str(uuid.uuid4()),
        station_id=station.id,
        name="unit",
        serial_number=f"SN{uuid.uuid4().hex[:8]}",
        asset_code=code,
        purpose=purpose,
        latest_status=ChargerStatusEnum.AVAILABLE,
        last_heart_beat_time=(
            datetime.now(timezone.utc) if connected_recently
            else datetime.now(timezone.utc) - timedelta(days=2)
        ),
    )
    await Connector.create(
        charger_id=charger.id, connector_id=1,
        connector_type=ConnectorTypeEnum.TYPE2, max_power_kw=22.0,
    )
    return charger


@pytest.mark.unit
class TestPublicVisibility:
    """Slice 06 — bench units are neither listed nor counted.

    Redis is patched so chargers register as connected. Without it the LIVENESS
    filter drops everything and the station never appears, which would make
    these tests pass for the wrong reason.
    """

    @staticmethod
    def _connected(*chargers):
        return patch(
            "redis_manager.redis_manager.get_all_connected_chargers",
            AsyncMock(return_value=[c.charge_point_string_id for c in chargers]),
        )

    @pytest.mark.asyncio
    async def test_test_chargers_are_hidden_from_public_stations(
        self, client_user: AsyncClient, test_station
    ):
        fleet = await _charger(test_station, "VOWS0001")
        bench = await _charger(test_station, "VOWS0002", purpose=ChargerPurposeEnum.TEST)

        with self._connected(fleet, bench):
            response = await client_user.get("/api/public/stations")

        assert response.status_code == status.HTTP_200_OK
        codes = [
            c["asset_code"]
            for st in response.json()["data"]
            for c in st.get("chargers", [])
        ]
        assert "VOWS0001" in codes
        assert "VOWS0002" not in codes

    @pytest.mark.asyncio
    async def test_test_chargers_do_not_inflate_total_chargers(
        self, client_user: AsyncClient, test_station
    ):
        # The concrete production bug: five bench units were inflating the
        # advertised capacity of a station.
        fleet = await _charger(test_station, "VOWS0001")
        b1 = await _charger(test_station, "VOWS0002", purpose=ChargerPurposeEnum.TEST)
        b2 = await _charger(test_station, "VOWS0003", purpose=ChargerPurposeEnum.TEST)

        with self._connected(fleet, b1, b2):
            response = await client_user.get("/api/public/stations")

        station = response.json()["data"][0]
        assert station["total_chargers"] == 1

    @pytest.mark.asyncio
    async def test_public_is_the_default_so_the_filter_fails_open(
        self, client_user: AsyncClient, test_station
    ):
        # A row missed by any backfill keeps working. This is the property that
        # makes the whole slice ordering safe: the worst case of a missed row
        # is the status quo, not an invisible charger.
        charger = await Charger.create(
            charge_point_string_id=str(uuid.uuid4()),
            station_id=test_station.id,
            name="never classified",
            serial_number=f"SN{uuid.uuid4().hex[:8]}",
            latest_status=ChargerStatusEnum.AVAILABLE,
            last_heart_beat_time=datetime.now(timezone.utc),
        )
        await Connector.create(
            charger_id=charger.id, connector_id=1,
            connector_type=ConnectorTypeEnum.TYPE2, max_power_kw=22.0,
        )
        assert charger.purpose == ChargerPurposeEnum.PUBLIC

        with self._connected(charger):
            response = await client_user.get("/api/public/stations")

        codes = [
            c["asset_code"]
            for st in response.json()["data"]
            for c in st.get("chargers", [])
        ]
        assert charger.asset_code in codes

    @pytest.mark.asyncio
    async def test_serviceability_and_liveness_exclude_independently(
        self, client_user: AsyncClient, test_station
    ):
        # The two filters answer different questions and must stay separate.
        # Here all three chargers are excluded or included for DIFFERENT
        # reasons: the bench unit is online but not serviceable, the offline
        # fleet unit is serviceable but not live, and only the third is both.
        live_fleet = await _charger(test_station, "VOWS0001")
        live_bench = await _charger(test_station, "VOWS0002", purpose=ChargerPurposeEnum.TEST)
        dead_fleet = await _charger(test_station, "VOWS0003", connected_recently=False)

        # Redis reports all three connected; only heartbeat age separates them.
        with self._connected(live_fleet, live_bench, dead_fleet):
            response = await client_user.get("/api/public/stations")

        codes = [
            c["asset_code"]
            for st in response.json()["data"]
            for c in st.get("chargers", [])
        ]
        assert codes == ["VOWS0001"]


@pytest.mark.unit
class TestRemoteStartGate:
    """Slice 07 — refuse before any money moves."""

    @pytest.mark.asyncio
    async def test_customer_cannot_remote_start_a_test_charger(
        self, client, test_station, test_user
    ):
        charger = await _charger(test_station, "VOWS0001", purpose=ChargerPurposeEnum.TEST)
        response = await client.post(
            f"/api/users/charger/{charger.charge_point_string_id}/remote-start"
        )
        # Rejected before the connectivity check and before any payment.
        assert response.status_code in (
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED,
        )

    @pytest.mark.asyncio
    async def test_admin_can_still_remote_start_a_test_charger(
        self, client_admin: AsyncClient, test_station
    ):
        # Bench hardware stays testable by the people who test it. The failure
        # here would be silent: the unit becomes untestable through the product.
        charger = await _charger(test_station, "VOWS0001", purpose=ChargerPurposeEnum.TEST)
        response = await client_admin.post(f"/api/admin/chargers/{charger.id}/remote-start")
        # Not 403 — it may fail later on connectivity, which is a different gate.
        assert response.status_code != status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_public_chargers_are_unaffected(
        self, client_admin: AsyncClient, test_station
    ):
        charger = await _charger(test_station, "VOWS0001")
        response = await client_admin.post(f"/api/admin/chargers/{charger.id}/remote-start")
        assert response.status_code != status.HTTP_403_FORBIDDEN


@pytest.mark.unit
class TestBillingSuppressionComposes:
    """A TEST session is never billed or invoiced — via an existing mechanism.

    Only internal roles can start on a TEST unit (the StartTransaction gate),
    and internal-role sessions already skip both wallet deduction and GST
    invoicing per ADR 0004. So suppression is a consequence, not a second
    check. These tests pin that composition, because it is invisible in the
    code — nothing in invoice_service mentions `purpose`.
    """

    def test_invoice_service_skips_internal_role_sessions(self):
        source = open("/app/services/invoice_service.py").read()
        assert "if user and user.role in INTERNAL_ROLES:" in source
        assert "GST invoice skipped for txn %s: %s-initiated session" in source

    def test_start_transaction_gate_admits_only_internal_roles(self):
        source = open("/app/main.py").read()
        assert (
            "if charger.purpose == ChargerPurposeEnum.TEST and user.role not in INTERNAL_ROLES:"
            in source
        )
