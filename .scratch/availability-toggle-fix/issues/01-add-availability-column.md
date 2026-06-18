Status: ready-for-agent

# Add `availability` column to `Charger` model + Aerich migration

## What to build

A new column on the `charger` table that captures admin-set availability intent, decoupled from `latest_status` (which is driven by OCPP `StatusNotification`).

- New enum `ChargerAvailabilityEnum(str, enum.Enum)` with values `OPERATIVE = "Operative"` and `INOPERATIVE = "Inoperative"` (the string values match the OCPP `ChangeAvailability.type` field exactly so endpoint code can write `type` straight to the column)
- New column on `Charger`: `availability = fields.CharEnumField(ChargerAvailabilityEnum, default=ChargerAvailabilityEnum.OPERATIVE)`
- Aerich-generated migration that adds the column with default `Operative` — backfills all existing rows

This issue is **schema-only**. No endpoint or frontend changes. Behavior is identical to today after this lands.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Boolean column `is_operative` | Loses OCPP-aligned vocabulary; admin endpoint already uses Operative/Inoperative strings; converting between bool ↔ enum at the boundary adds friction |
| Reuse `latest_status` with a new `UnavailableAdminSet` enum value | Conflates two orthogonal concepts (admin intent vs charger-reported state). Status pill, OCPP routing, and other consumers of `latest_status` would all need to learn about the distinction |
| Connector-level column (`Connector.availability`) | Existing endpoint operates at whole-charger granularity (`routers/chargers.py:743-751`). Per-connector control isn't exposed via the UI; adding it now would create a column with no consumer |
| Default `Inoperative` and require explicit Opt-in | Wrong default for backfill — every existing charger was admin-intent-Operative until we have a reason to think otherwise |

## What to change

### `backend/models.py`

Add the enum near `ChargerStatusEnum` (around line 19):

```python
class ChargerAvailabilityEnum(str, enum.Enum):
    OPERATIVE = "Operative"
    INOPERATIVE = "Inoperative"
```

Add the column to `Charger` (around line 311, right after `latest_status`):

```python
# Admin-set availability intent — orthogonal to latest_status which
# reflects what the charger reports. The toggle in the admin UI reads
# THIS field, not latest_status. See ADR 0008.
availability = fields.CharEnumField(
    ChargerAvailabilityEnum,
    default=ChargerAvailabilityEnum.OPERATIVE,
)
```

### Aerich migration

Generate normally via the project's standard workflow:

```bash
docker exec ocpp-backend aerich migrate --name add_charger_availability
```

Expected file: `backend/migrations/models/42_<timestamp>_add_charger_availability.py`

The generated SQL should be approximately:

```sql
-- upgrade
ALTER TABLE "charger" ADD "availability" VARCHAR(11) NOT NULL DEFAULT 'Operative';

-- downgrade
ALTER TABLE "charger" DROP COLUMN "availability";
```

**Verify before merging:**
- The `VARCHAR(11)` is correct (max enum value length: "Inoperative" = 11 chars)
- The default is `'Operative'`
- No accidental rewrites of other rows / no unrelated ALTERs (see `feedback_aerich_snapshot_poisoning.md` — review the diff carefully)

If Aerich tries to generate unrelated changes alongside this, **stop and ask** rather than committing them blindly (see `feedback_stop_before_handwriting_migration.md`).

### Apply locally to verify

```bash
docker exec ocpp-backend aerich upgrade
docker exec ocpp-backend python -c "
import asyncio
from tortoise import Tortoise
from database import TORTOISE_ORM

async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    from models import Charger, ChargerAvailabilityEnum
    c = await Charger.first()
    print(f'First charger availability: {c.availability!r}')
    print(f'Enum has correct values: {[e.value for e in ChargerAvailabilityEnum]}')

asyncio.run(check())
"
```

Expected output:
- `availability = ChargerAvailabilityEnum.OPERATIVE` (or just `'Operative'` depending on Tortoise serialization)
- Enum values: `['Operative', 'Inoperative']`

## Verification

Before declaring done:

1. **Migration generated cleanly** — only the new column appears in the diff, nothing else
2. **All existing chargers have `availability='Operative'`** after `aerich upgrade`
3. **Test suite still passes**: `docker exec ocpp-backend pytest`
4. **The CLAUDE.md baseline flake (`gst_rate_percent` ERROR set) is unchanged** — pre-existing, not caused by this change

## Definition of done

- `models.py` includes `ChargerAvailabilityEnum` and `Charger.availability`
- Aerich migration committed under `backend/migrations/models/`
- `aerich upgrade` runs cleanly on the local Docker postgres
- No behavior change observed in the UI or API yet (this is intentional — that's issue 02 + 03)
- PR merged to `develop`
