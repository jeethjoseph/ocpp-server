"""The Asset Code backfill's mapped path (ADR 0028, slice 03).

This file exists because local development runs the migration's SEQUENTIAL
branch and never touches the mapped one — so without these tests the code that
actually executes against production and staging would ship completely
unexercised, and its first run would be the real one, on the real fleet.

The migration is loaded by path rather than imported, because migration modules
are not a package.
"""
import importlib.util
import uuid

import pytest
from tortoise import connections

from models import Charger, ChargerPurposeEnum, ChargerStatusEnum

MIGRATION_PATH = "/app/migrations/models/59_20260908221453_asset_code_backfill.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("asset_code_backfill", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


async def _charger(station, ocpp_id, name="unit", code=None):
    """Create a charger, optionally in the PRE-MIGRATION state (no code).

    `asset_code` is NOT NULL on the model, so a codeless row cannot be built
    through Tortoise — which is the point of the migration. Reproduce the real
    starting state by writing a throwaway code and clearing it in SQL.
    """
    charger = await Charger.create(
        charge_point_string_id=ocpp_id,
        station_id=station.id,
        name=name,
        serial_number=f"SN{uuid.uuid4().hex[:8]}",
        asset_code=code or f"VOWS9{uuid.uuid4().int % 100000:05d}",
        latest_status=ChargerStatusEnum.AVAILABLE,
    )
    if code is None:
        await connections.get("default").execute_query(
            'UPDATE "charger" SET "asset_code" = NULL WHERE "id" = $1', [charger.id]
        )
        charger.asset_code = None
    return charger


@pytest.fixture
async def pre_migration_schema(client):
    """Drop the NOT NULL the model declares, so the migration can add it.

    The test schema is generated from models.py, which already declares
    `asset_code` NOT NULL — i.e. the post-migration shape. The migration under
    test is the thing that establishes that constraint, so it has to start from
    the state that existed before it ran.
    """
    conn = connections.get("default")
    await conn.execute_script('ALTER TABLE "charger" ALTER COLUMN "asset_code" DROP NOT NULL;')
    yield
    await conn.execute_script('ALTER TABLE "charger" ALTER COLUMN "asset_code" DROP NOT NULL;')


async def _run(sql):
    # execute_script so the temp table, DO blocks and UPDATE run as one unit,
    # exactly as aerich runs the migration body.
    await connections.get("default").execute_script(sql)


@pytest.mark.unit
class TestMapIntegrity:
    """The baked-in map must match the reviewed worksheet exactly."""

    def test_row_counts(self):
        assert len(migration.ASSET_CODE_BACKFILL["production"]) == 13
        assert len(migration.ASSET_CODE_BACKFILL["staging"]) == 9

    def test_every_code_is_in_its_register_series(self):
        for code, _ in migration.ASSET_CODE_BACKFILL["production"].values():
            assert code.startswith("VOW") and not code.startswith("VOWS")
        for code, _ in migration.ASSET_CODE_BACKFILL["staging"].values():
            assert code.startswith("VOWS")

    def test_codes_are_unique_within_each_register(self):
        for env, mapping in migration.ASSET_CODE_BACKFILL.items():
            codes = [c for c, _ in mapping.values()]
            assert len(codes) == len(set(codes)), f"duplicate Asset Code in {env}"

    def test_keys_are_uuids_not_row_ids(self):
        # Keyed on charge_point_string_id precisely because row ids differ per
        # register and can be reused after a delete.
        for mapping in migration.ASSET_CODE_BACKFILL.values():
            for key in mapping:
                uuid.UUID(key)

    def test_purposes_are_declared_values_only(self):
        allowed = {e.value for e in ChargerPurposeEnum}
        for mapping in migration.ASSET_CODE_BACKFILL.values():
            for _, purpose in mapping.values():
                assert purpose in allowed

    def test_production_gaps_at_four_and_five_are_not_filled(self):
        # Those two units live at the staging site. Allocation is monotonic and
        # gaps are never backfilled, so production's next new unit is VOW0016.
        codes = {c for c, _ in migration.ASSET_CODE_BACKFILL["production"].values()}
        assert "VOW0004" not in codes
        assert "VOW0005" not in codes
        assert "VOW0003" in codes and "VOW0006" in codes

    def test_the_eight_fleet_units_are_public_and_the_rest_are_test(self):
        prod = migration.ASSET_CODE_BACKFILL["production"]
        public = sorted(c for c, p in prod.values() if p == "PUBLIC")
        assert public == [
            "VOW0001", "VOW0002", "VOW0003", "VOW0006",
            "VOW0007", "VOW0008", "VOW0009", "VOW0010",
        ]
        assert len(prod) - len(public) == 5  # the five production bench units

    def test_development_is_deliberately_unmapped(self):
        # A local database holds arbitrary chargers; requiring a map would
        # break every dev box on migrate.
        assert "development" not in migration.ASSET_CODE_BACKFILL


@pytest.mark.unit
class TestMappedBackfill:
    """The branch that runs in staging and production."""

    @pytest.mark.asyncio
    async def test_applies_codes_and_purposes_from_the_map(self, client, pre_migration_schema, test_station):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        await _charger(test_station, a, name="fleet")
        await _charger(test_station, b, name="bench")

        await _run(migration._mapped_upgrade({
            a: ("VOWS0001", "PUBLIC"),
            b: ("VOWS0002", "TEST"),
        }))

        assert (await Charger.get(charge_point_string_id=a)).asset_code == "VOWS0001"
        bench = await Charger.get(charge_point_string_id=b)
        assert bench.asset_code == "VOWS0002"
        assert bench.purpose == ChargerPurposeEnum.TEST

    @pytest.mark.asyncio
    async def test_never_reads_charger_name(self, client, pre_migration_schema, test_station):
        # The whole point of an explicit map: a row whose `name` bears no
        # relationship to its code still gets the mapped code.
        ocpp_id = str(uuid.uuid4())
        await _charger(test_station, ocpp_id, name="Chargemode_1")
        await _run(migration._mapped_upgrade({ocpp_id: ("VOWS0007", "TEST")}))
        assert (await Charger.get(charge_point_string_id=ocpp_id)).asset_code == "VOWS0007"

    @pytest.mark.asyncio
    async def test_guard_1_raises_when_the_map_names_an_absent_charger(self, client, pre_migration_schema, test_station):
        present = str(uuid.uuid4())
        await _charger(test_station, present)
        absent = str(uuid.uuid4())
        with pytest.raises(Exception, match="absent from this register"):
            await _run(migration._mapped_upgrade({
                present: ("VOWS0001", "PUBLIC"),
                absent: ("VOWS0002", "PUBLIC"),
            }))

    @pytest.mark.asyncio
    async def test_a_charger_created_since_the_csv_is_allocated_not_fatal(
        self, client, pre_migration_schema, test_station
    ):
        # THE production-safety property. The entrypoint runs `aerich upgrade`
        # under `set -e` on every boot, so a raising migration does not print an
        # error — it stops the backend booting and takes the fleet offline. A
        # charger onboarded between the worksheet and deploy day is routine, so
        # it must be allocated, not fatal.
        mapped = str(uuid.uuid4())
        latecomer = str(uuid.uuid4())
        await _charger(test_station, mapped)
        await _charger(test_station, latecomer, name="created after the CSV")

        await _run(migration._mapped_upgrade({mapped: ("VOWS0001", "PUBLIC")}))

        assert (await Charger.get(charge_point_string_id=mapped)).asset_code == "VOWS0001"
        # Allocated past the highest mapped code, not colliding with it.
        allocated = (await Charger.get(charge_point_string_id=latecomer)).asset_code
        assert allocated == "VOWS0002"

    @pytest.mark.asyncio
    async def test_an_unmapped_charger_stays_public(
        self, client, pre_migration_schema, test_station
    ):
        # Fail-open: a row the worksheet never classified keeps billing and
        # stays visible rather than silently going dark.
        bench = str(uuid.uuid4())
        latecomer = str(uuid.uuid4())
        await _charger(test_station, bench)
        await _charger(test_station, latecomer)

        # The map classifies the known bench unit; the latecomer is absent.
        await _run(migration._mapped_upgrade({bench: ("VOWS0001", "TEST")}))

        assert (await Charger.get(charge_point_string_id=bench)).purpose == ChargerPurposeEnum.TEST
        row = await Charger.get(charge_point_string_id=latecomer)
        assert row.purpose == ChargerPurposeEnum.PUBLIC
        assert row.asset_code == "VOWS0002"

    @pytest.mark.asyncio
    async def test_guard_3_re_running_is_a_no_op(self, client, pre_migration_schema, test_station):
        ocpp_id = str(uuid.uuid4())
        await _charger(test_station, ocpp_id)
        sql = migration._mapped_upgrade({ocpp_id: ("VOWS0001", "PUBLIC")})
        await _run(sql)
        await _run(sql)  # must not raise on UNIQUE
        assert (await Charger.get(charge_point_string_id=ocpp_id)).asset_code == "VOWS0001"

    @pytest.mark.asyncio
    async def test_an_existing_code_is_never_reassigned(self, client, pre_migration_schema, test_station):
        # A code is immutable for the life of the unit — it is painted on the
        # hardware and printed on issued invoices.
        ocpp_id = str(uuid.uuid4())
        await _charger(test_station, ocpp_id, code="VOWS0042")
        await _run(migration._mapped_upgrade({ocpp_id: ("VOWS0001", "PUBLIC")}))
        assert (await Charger.get(charge_point_string_id=ocpp_id)).asset_code == "VOWS0042"


@pytest.mark.unit
class TestEnvironmentRouting:
    def test_production_and_staging_take_the_mapped_branch(self):
        for env in ("production", "staging"):
            assert migration.ASSET_CODE_BACKFILL.get(env) is not None

    @pytest.mark.parametrize("env", ["development", "qa", "", "local"])
    def test_unmapped_environments_take_the_sequential_branch(self, env):
        assert migration.ASSET_CODE_BACKFILL.get(env) is None

    def test_sequential_branch_never_mints_a_production_series_code(self):
        # Fail-safe: an unrecognised ENVIRONMENT must not produce VOW####,
        # which migration 58's series CHECK would reject anyway — but the
        # belt-and-braces matters because this runs before anyone looks.
        from policy import charger_code_series
        sql = migration._sequential_upgrade(charger_code_series("qa"))
        assert "'VOWS'" in sql
        assert "'VOW'" not in sql
