"""socket-charger-classification issue 01.

- `is_socket_connector_type` taxonomy: Type2/Type1/Socket/domestic are untethered
  (start-from-Available); CCS/CHAdeMO/GB-T and anything unknown are tethered.
- An admin can edit `connector_type` via PUT /api/admin/chargers/{id}; invalid
  values are rejected; the change flips socket classification.
- The charger list now carries `connectors` so the Edit form can pre-fill.
"""
import pytest

from models import Connector
from services.charger_type_service import is_socket_connector_type, is_socket_charger


@pytest.mark.parametrize("raw,expected", [
    ("Type2", True), ("type2", True), ("Type 2", True), ("Type1", True),
    ("Socket", True), ("socket", True), ("DOMESTIC", True),
    ("CCS", False), ("CCS2", False), ("CHAdeMO", False), ("GB/T", False),
    ("Frobnicator", False), ("", False), (None, False),
])
def test_is_socket_connector_type(raw, expected):
    assert is_socket_connector_type(raw) is expected


@pytest.mark.asyncio
async def test_update_connector_type_persists_and_flips_socket(client_admin, test_charger):
    # conftest seeds a Type2 connector → currently a socket charger.
    assert await is_socket_charger(test_charger.charge_point_string_id) is True

    resp = await client_admin.put(
        f"/api/admin/chargers/{test_charger.id}", json={"connector_type": "CCS"}
    )
    assert resp.status_code == 200

    conn = await Connector.filter(charger_id=test_charger.id).first()
    assert conn.connector_type == "CCS"
    # CCS is tethered → no longer start-from-Available.
    assert await is_socket_charger(test_charger.charge_point_string_id) is False


@pytest.mark.asyncio
async def test_update_connector_type_rejects_invalid(client_admin, test_charger):
    resp = await client_admin.put(
        f"/api/admin/chargers/{test_charger.id}", json={"connector_type": "Bogus"}
    )
    assert resp.status_code == 400
    conn = await Connector.filter(charger_id=test_charger.id).first()
    assert conn.connector_type == "Type2"  # unchanged


@pytest.mark.asyncio
async def test_charger_list_includes_connectors(client_admin, test_charger):
    resp = await client_admin.get("/api/admin/chargers")
    assert resp.status_code == 200
    row = next(c for c in resp.json()["data"] if c["id"] == test_charger.id)
    assert row["connectors"][0]["connector_type"] == "Type2"
