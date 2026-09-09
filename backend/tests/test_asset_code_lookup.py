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


@pytest.mark.unit
class TestChargerReferenceResolution:
    """The QR landing page accepts an Asset Code OR a legacy UUID (ADR 0028).

    Accepting both is what makes moving the route safe: every link already in a
    browser history, a bookmark or a sticker printed before the change keeps
    resolving, while nothing new publishes the OCPP identity — which is the
    Basic Auth username for the live diagnostics-upload endpoint.
    """

    @pytest.mark.asyncio
    async def test_resolves_by_asset_code(self, client, test_station):
        from services import charger_code_service

        charger = await _charger(test_station, "VOWS0001")
        found = await charger_code_service.resolve_charger("VOWS0001")
        assert found is not None and found.id == charger.id

    @pytest.mark.asyncio
    async def test_resolves_by_asset_code_at_any_padding(self, client, test_station):
        from services import charger_code_service

        charger = await _charger(test_station, "VOWS0001")
        for typed in ("VOWS1", "vows0001", "VOWS00001"):
            found = await charger_code_service.resolve_charger(typed)
            assert found is not None and found.id == charger.id, typed

    @pytest.mark.asyncio
    async def test_still_resolves_a_legacy_ocpp_uuid(self, client, test_station):
        # The back-compatibility guarantee. A sticker printed before ADR 0028
        # must keep working indefinitely.
        from services import charger_code_service

        charger = await _charger(test_station, "VOWS0001")
        found = await charger_code_service.resolve_charger(charger.charge_point_string_id)
        assert found is not None and found.id == charger.id

    @pytest.mark.asyncio
    async def test_foreign_series_does_not_resolve(self, client, test_station):
        # Must not fall through to the local unit with the same number.
        from services import charger_code_service

        await _charger(test_station, "VOWS0001")
        assert await charger_code_service.resolve_charger("VOW0001") is None

    @pytest.mark.asyncio
    async def test_junk_does_not_resolve(self, client, test_station):
        from services import charger_code_service

        await _charger(test_station, "VOWS0001")
        for junk in ("", "nope", "VOWS", "../../etc/passwd"):
            assert await charger_code_service.resolve_charger(junk) is None, junk

    @pytest.mark.asyncio
    async def test_landing_page_endpoint_accepts_the_asset_code(
        self, client, test_station, test_user
    ):
        from main import app
        from auth_middleware import get_current_user_with_db

        charger = await _charger(test_station, "VOWS0001")
        app.dependency_overrides[get_current_user_with_db] = lambda: test_user
        try:
            by_code = await client.get("/api/users/charger/VOWS0001")
            by_uuid = await client.get(
                f"/api/users/charger/{charger.charge_point_string_id}"
            )
        finally:
            app.dependency_overrides.pop(get_current_user_with_db, None)

        assert by_code.status_code == status.HTTP_200_OK
        assert by_uuid.status_code == status.HTTP_200_OK
        assert by_code.json()["charger"]["asset_code"] == "VOWS0001"


@pytest.mark.unit
class TestPublicPayloadHidesTheOcppIdentity:
    def test_station_charger_info_has_no_ocpp_id_field(self):
        # The UUID is the Basic Auth username for POST /api/diagnostics/bundles.
        # Publishing it in an unauthenticated payload enumerated usernames.
        from routers.public_stations import StationChargerInfo

        assert "charge_point_string_id" not in StationChargerInfo.model_fields
        assert "asset_code" in StationChargerInfo.model_fields
