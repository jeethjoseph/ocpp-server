"""Support resolves a customer-quoted Asset Code (ADR 0028, slice 05).

Without this, slice 04 has handed customers an identifier nobody internally
can resolve.
"""
import uuid

import pytest
from fastapi import status
from httpx import AsyncClient

from models import Charger, ChargerPurposeEnum, ChargerStatusEnum


async def _charger(station, code, name="unit", purpose=ChargerPurposeEnum.PUBLIC):
    return await Charger.create(
        charge_point_string_id=str(uuid.uuid4()),
        station_id=station.id,
        name=name,
        serial_number=f"SN{uuid.uuid4().hex[:8]}",
        asset_code=code,
        purpose=purpose,
        latest_status=ChargerStatusEnum.AVAILABLE,
    )


async def _search(client_admin, term):
    response = await client_admin.get(f"/api/admin/chargers?search={term}")
    assert response.status_code == status.HTTP_200_OK
    return [c["asset_code"] for c in response.json()["data"]]


@pytest.mark.unit
class TestSupportLookup:
    @pytest.mark.asyncio
    async def test_exact_code_resolves(self, client_admin: AsyncClient, test_station):
        await _charger(test_station, "VOWS0001")
        await _charger(test_station, "VOWS0002")
        assert await _search(client_admin, "VOWS0001") == ["VOWS0001"]

    @pytest.mark.parametrize("typed", ["VOWS0001", "VOWS00001", "vows1", "VOWS1", "vows0001"])
    @pytest.mark.asyncio
    async def test_any_padding_resolves_to_the_same_unit(
        self, client_admin: AsyncClient, test_station, typed
    ):
        # The property that makes ADR 0028's minimum-width rule safe. A customer
        # reading "VOWS1" off a label and an admin pasting "VOWS0001" must land
        # on the same charger.
        await _charger(test_station, "VOWS0001")
        assert await _search(client_admin, typed) == ["VOWS0001"]

    @pytest.mark.asyncio
    async def test_a_foreign_series_resolves_to_nothing(
        self, client_admin: AsyncClient, test_station
    ):
        # THE important one. This register is VOWS; a production code must find
        # nothing rather than resolving to the local unit with the same number.
        # Coercing it would hand support the wrong charger on a support call —
        # a wrong-answer bug, which is worse than a no-answer one.
        await _charger(test_station, "VOWS0001")
        assert await _search(client_admin, "VOW0001") == []

    @pytest.mark.asyncio
    async def test_a_partial_code_still_narrows_the_list(
        self, client_admin: AsyncClient, test_station
    ):
        # "VOWS00" is not a resolvable code, but an admin half-way through
        # typing should see the list narrow rather than empty out.
        await _charger(test_station, "VOWS0001")
        await _charger(test_station, "VOWS0002")
        assert sorted(await _search(client_admin, "VOWS00")) == ["VOWS0001", "VOWS0002"]

    @pytest.mark.asyncio
    async def test_name_search_still_works(self, client_admin: AsyncClient, test_station):
        # The Asset Code arm is additive; it must not break the existing
        # workflow of searching by the operator's own label.
        await _charger(test_station, "VOWS0001", name="Airport Bay 3")
        await _charger(test_station, "VOWS0002", name="Depot")
        assert await _search(client_admin, "Airport") == ["VOWS0001"]

    @pytest.mark.asyncio
    async def test_ocpp_id_search_still_works(self, client_admin: AsyncClient, test_station):
        # Ops correlates logs by OCPP identity; that path stays.
        charger = await _charger(test_station, "VOWS0001")
        found = await _search(client_admin, charger.charge_point_string_id[:8])
        assert found == ["VOWS0001"]

    @pytest.mark.asyncio
    async def test_admin_list_exposes_code_and_purpose(
        self, client_admin: AsyncClient, test_station
    ):
        # The TEST badge in the admin UI reads `purpose`; the code is what
        # support quotes back.
        await _charger(test_station, "VOWS0001", purpose=ChargerPurposeEnum.TEST)
        response = await client_admin.get("/api/admin/chargers")
        row = response.json()["data"][0]
        assert row["asset_code"] == "VOWS0001"
        assert row["purpose"] == "TEST"

    @pytest.mark.asyncio
    async def test_admin_still_sees_the_ocpp_identity(
        self, client_admin: AsyncClient, test_station
    ):
        # Scrubbed from customers, retained for ops — log correlation and
        # firmware deploys both need it.
        charger = await _charger(test_station, "VOWS0001")
        response = await client_admin.get("/api/admin/chargers")
        row = response.json()["data"][0]
        assert row["charge_point_string_id"] == charger.charge_point_string_id
