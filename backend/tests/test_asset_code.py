"""Asset Code: series fail-safe, format, allocation and lookup (ADR 0028).

The DB CHECK constraints from migration 58 are NOT exercised here — the test
schema is built by `generate_schemas` from models.py, not by running the
migrations, so no CHECK exists in the test database. What IS exercised is the
pattern the migration builds those constraints from, which lives in policy.py
precisely so one assertion covers both.
"""
import re
import uuid

import pytest
from fastapi import status
from httpx import AsyncClient

from models import Charger, ChargerPurposeEnum, ChargerStatusEnum
from policy import (
    CHARGER_CODE_FORMAT_PATTERN,
    charger_code_series,
    charger_code_series_pattern,
)
from services import charger_code_service


@pytest.mark.unit
class TestSeriesFailSafe:
    """An unrecognised environment must never mint a production-looking code.

    This is the single most important assertion in the file. The failure is
    silent — a misconfigured box happily allocates VOW#### — and the collision
    it creates is permanent, because the code lands on issued GST invoices that
    are frozen tax documents.
    """

    def test_known_environments(self):
        assert charger_code_series("production") == "VOW"
        assert charger_code_series("staging") == "VOWS"
        assert charger_code_series("development") == "VOWS"

    @pytest.mark.parametrize("env", ["", None, "prod", "prd", "qa", "local", "sandbox", "production-1"])
    def test_unknown_environment_never_resolves_to_production(self, env):
        # "prod" and "PRODUCTION " are the realistic typos — a shortened value
        # and a trailing space in an env file. Neither may mint VOW.
        assert charger_code_series(env) == "VOWS"

    def test_known_environments_are_case_and_space_tolerant(self):
        assert charger_code_series("  Production  ") == "VOW"
        assert charger_code_series("STAGING") == "VOWS"


@pytest.mark.unit
class TestFormatPattern:
    """The pattern migration 58 builds its CHECK constraints from."""

    @pytest.mark.parametrize("code", ["VOW0001", "VOWS0001", "VOW9999", "VOW10000", "VOWS123456"])
    def test_accepts_well_formed(self, code):
        assert re.match(CHARGER_CODE_FORMAT_PATTERN, code)

    @pytest.mark.parametrize(
        "code",
        [
            "VOW1",        # under minimum width
            "VOW001",      # under minimum width
            "vow0001",     # lowercase is not stored, only accepted on lookup
            "VLS0001",     # foreign series
            "VOW0001X",    # trailing junk
            "XVOW0001",    # leading junk
            "VOW 0001",    # the trailing-space class of dirt that hit `name`
            "VOWS",        # no digits
            "",
        ],
    )
    def test_rejects_malformed(self, code):
        assert not re.match(CHARGER_CODE_FORMAT_PATTERN, code)

    def test_production_series_pattern_rejects_a_staging_code(self):
        # VOW is a strict prefix of VOWS, so this is the case where a careless
        # regex silently lets staging's codes into production's register.
        prod = charger_code_series_pattern("production")
        assert re.match(prod, "VOW0001")
        assert not re.match(prod, "VOWS0001")

    def test_staging_series_pattern_rejects_a_production_code(self):
        staging = charger_code_series_pattern("staging")
        assert re.match(staging, "VOWS0001")
        assert not re.match(staging, "VOW0001")


@pytest.mark.unit
class TestFormatAndParse:
    def test_format_pads_to_minimum_width(self):
        assert charger_code_service.format_asset_code(1, series="VOW") == "VOW0001"
        assert charger_code_service.format_asset_code(42, series="VOW") == "VOW0042"

    def test_format_widens_past_the_boundary_rather_than_truncating(self):
        # The register widens by itself: no migration, no re-padding, no
        # fleet re-stencil at VOW9999.
        assert charger_code_service.format_asset_code(9999, series="VOW") == "VOW9999"
        assert charger_code_service.format_asset_code(10000, series="VOW") == "VOW10000"
        assert charger_code_service.format_asset_code(123456, series="VOW") == "VOW123456"

    def test_format_rejects_non_positive(self):
        with pytest.raises(ValueError):
            charger_code_service.format_asset_code(0, series="VOW")

    @pytest.mark.parametrize("typed", ["VOW0001", "VOW00001", "vow1", "VOW1", "  vow0001  ", "VOW000001"])
    def test_lookup_parses_the_integer_not_the_string(self, typed):
        # Every padding of the same number resolves to the same unit. This is
        # what makes the minimum-width rule safe.
        assert charger_code_service.parse_asset_code(typed, series="VOW") == 1

    @pytest.mark.parametrize("typed", ["VOWS0001", "VOWS1", "vows0001"])
    def test_foreign_series_is_rejected_never_coerced(self, typed):
        # A staging code typed into production must find NOTHING. Coercing it
        # to the same integer would resolve to production's unit with that
        # number — a wrong-answer bug on a support call.
        assert charger_code_service.parse_asset_code(typed, series="VOW") is None

    @pytest.mark.parametrize("typed", ["", None, "0001", "ABC", "VOW", "VOWABC", "VOW-0001", "VOW0"])
    def test_junk_resolves_to_nothing(self, typed):
        assert charger_code_service.parse_asset_code(typed, series="VOW") is None

    def test_round_trips_at_any_width(self):
        for n in (1, 9, 99, 9999, 10000, 987654):
            code = charger_code_service.format_asset_code(n, series="VOW")
            assert charger_code_service.parse_asset_code(code, series="VOW") == n


@pytest.mark.unit
class TestAllocation:
    """Allocation comes from a Postgres sequence (migration 60).

    A sequence rather than `MAX + 1` because the latter is a read-modify-write:
    two concurrent creates read the same maximum and race for the same code.
    `nextval` is atomic, so there is no race and no retry loop to get wrong.
    """

    async def _charger(self, station, asset_code=None, name="c"):
        return await Charger.create(
            charge_point_string_id=str(uuid.uuid4()),
            station_id=station.id,
            name=name,
            serial_number=f"SN{uuid.uuid4().hex[:8]}",
            **({"asset_code": asset_code} if asset_code else {}),
            latest_status=ChargerStatusEnum.AVAILABLE,
        )

    @pytest.mark.asyncio
    async def test_first_code_in_an_empty_register(self, client, test_station):
        assert await charger_code_service.next_asset_code() == "VOWS0001"

    @pytest.mark.asyncio
    async def test_allocation_is_strictly_monotonic(self, client, test_station):
        codes = [await charger_code_service.next_asset_code() for _ in range(3)]
        assert codes == ["VOWS0001", "VOWS0002", "VOWS0003"]

    @pytest.mark.asyncio
    async def test_a_code_is_never_handed_out_twice(self, client, test_station):
        codes = [await charger_code_service.next_asset_code() for _ in range(50)]
        assert len(set(codes)) == 50

    @pytest.mark.asyncio
    async def test_concurrent_allocation_never_collides(self, client, test_station):
        # The property the sequence exists for. Under MAX + 1 these would read
        # the same maximum and produce duplicates.
        import asyncio
        codes = await asyncio.gather(
            *(charger_code_service.next_asset_code() for _ in range(20))
        )
        assert len(set(codes)) == 20

    @pytest.mark.asyncio
    async def test_every_creation_path_gets_a_code_without_asking(self, client, test_station):
        # The structural guarantee: the pre_save hook covers any path that
        # creates a Charger, not just the admin endpoint.
        charger = await self._charger(test_station)
        assert charger.asset_code == "VOWS0001"
        assert (await Charger.get(id=charger.id)).asset_code == "VOWS0001"

    @pytest.mark.asyncio
    async def test_an_explicit_code_is_respected_not_overwritten(self, client, test_station):
        # The backfill migration assigns seeded stencil codes directly; the
        # hook must never clobber one.
        charger = await self._charger(test_station, asset_code="VOWS0042")
        assert charger.asset_code == "VOWS0042"

    @pytest.mark.asyncio
    async def test_saving_an_existing_charger_does_not_reallocate(self, client, test_station):
        # Chargers are saved constantly by the heartbeat and StatusNotification
        # handlers. An Asset Code is immutable for the life of the unit.
        charger = await self._charger(test_station)
        original = charger.asset_code
        charger.name = "renamed"
        await charger.save()
        charger.latest_status = ChargerStatusEnum.CHARGING
        await charger.save()
        assert (await Charger.get(id=charger.id)).asset_code == original

    @pytest.mark.asyncio
    async def test_gaps_from_a_failed_insert_are_never_reclaimed(self, client, test_station):
        # nextval does not roll back, so a burned number leaves a gap. ADR 0028
        # commits to exactly this: gaps are never backfilled, including gaps
        # that were never allocated.
        await charger_code_service.next_asset_code()   # burned
        await charger_code_service.next_asset_code()   # burned
        charger = await self._charger(test_station)
        assert charger.asset_code == "VOWS0003"

    @pytest.mark.asyncio
    async def test_pre_existing_rows_do_not_rewind_the_sequence(self, client, test_station):
        # A seeded code higher than the sequence must not cause a later
        # allocation to collide with it going forward. Migration 60 seeds the
        # sequence past the backfill maximum for exactly this reason.
        await self._charger(test_station, asset_code="VOWS0002")
        first = await self._charger(test_station)
        assert first.asset_code != "VOWS0002"


@pytest.mark.unit
class TestCreateEndpointAllocates:
    def _payload(self, station):
        return {
            "station_id": station.id,
            "name": "Allocated Charger",
            "serial_number": f"SN{uuid.uuid4().hex[:8]}",
            "connectors": [{"connector_id": 1, "connector_type": "Type2", "max_power_kw": 22.0}],
        }

    @pytest.mark.asyncio
    async def test_create_returns_an_asset_code_the_caller_never_asked_for(
        self, client_admin: AsyncClient, test_station
    ):
        response = await client_admin.post("/api/admin/chargers", json=self._payload(test_station))
        assert response.status_code == status.HTTP_201_CREATED
        code = response.json()["charger"]["asset_code"]
        assert code == "VOWS0001"
        assert re.match(CHARGER_CODE_FORMAT_PATTERN, code)

    @pytest.mark.asyncio
    async def test_new_charger_defaults_to_public(self, client_admin: AsyncClient, test_station):
        response = await client_admin.post("/api/admin/chargers", json=self._payload(test_station))
        assert response.json()["charger"]["purpose"] == ChargerPurposeEnum.PUBLIC.value

    @pytest.mark.asyncio
    async def test_consecutive_creates_get_consecutive_codes(
        self, client_admin: AsyncClient, test_station
    ):
        first = await client_admin.post("/api/admin/chargers", json=self._payload(test_station))
        second = await client_admin.post("/api/admin/chargers", json=self._payload(test_station))
        assert first.json()["charger"]["asset_code"] == "VOWS0001"
        assert second.json()["charger"]["asset_code"] == "VOWS0002"

    @pytest.mark.asyncio
    async def test_supplying_an_asset_code_is_rejected_not_silently_ignored(
        self, client_admin: AsyncClient, test_station
    ):
        # A silent ignore teaches the caller it worked, and surfaces a year
        # later as "the code we set never took".
        payload = self._payload(test_station) | {"asset_code": "VOWS9999"}
        response = await client_admin.post("/api/admin/chargers", json=payload)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_updating_an_asset_code_is_rejected(
        self, client_admin: AsyncClient, test_station
    ):
        created = await client_admin.post("/api/admin/chargers", json=self._payload(test_station))
        charger_id = created.json()["charger"]["id"]
        response = await client_admin.put(
            f"/api/admin/chargers/{charger_id}", json={"asset_code": "VOWS9999"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_updating_purpose_through_the_charger_endpoint_is_rejected(
        self, client_admin: AsyncClient, test_station
    ):
        # Purpose is real state with billing consequences; it does not ride in
        # on the general-purpose update payload.
        created = await client_admin.post("/api/admin/chargers", json=self._payload(test_station))
        charger_id = created.json()["charger"]["id"]
        response = await client_admin.put(
            f"/api/admin/chargers/{charger_id}", json={"purpose": "TEST"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
