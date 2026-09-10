from tortoise import BaseDBAsyncClient

from models import CONNECTOR_TYPE_CHECK, connector_type_check_sql

# A CHECK constraint on `connector.connector_type`, following the spliced-CHECK
# pattern of migrations 50 and 58. Aerich generates nothing here: Tortoise models
# a CharEnumField as a plain VARCHAR, so the enum exists only in Python.
#
# Why it is needed. Migration 49 promoted `connector_type` from free text to
# `CharEnumField(ConnectorTypeEnum)` but only retyped the column and added a
# comment -- no normalisation, no constraint. Tortoise 0.25's
# `CharEnumFieldInstance.to_python_value` calls `self.enum_type(value)`, which
# raises ValueError on anything that is not byte-exactly one of the members. So a
# single non-canonical row makes every path that loads a Connector raise:
# suspend-window selection on disconnect, remote start, QR start, the admin
# charger list, and the public stations endpoint.
#
# The data is currently clean -- verified 2026-09-09 by live query against both
# registers (staging: Socket 6 / Type2 3; production: Socket 8 / Type2 5) -- and
# both API write paths canonicalise through `canonical_connector_type`. This makes
# that a structural guarantee rather than a property that happens to hold and has
# to be re-audited. The failure mode is fleet-wide and silent until it isn't.
#
# The statement is built from ConnectorTypeEnum via `connector_type_check_sql()`
# in models.py, shared with the test harness (which builds its schema from the
# models and so would otherwise never see this constraint at all). Adding a member
# to the enum therefore needs a migration that widens this CHECK -- the same
# reviewed-step property migration 58 relies on.


async def upgrade(db: BaseDBAsyncClient) -> str:
    return connector_type_check_sql()


async def downgrade(db: BaseDBAsyncClient) -> str:
    return f'ALTER TABLE "connector" DROP CONSTRAINT IF EXISTS "{CONNECTOR_TYPE_CHECK}";'
