# tests/test_logs_console.py
import pytest
from datetime import datetime, timezone, timedelta

from httpx import AsyncClient
from fastapi import status

from models import OCPPLog


async def _make_log(charge_point_id: str, message_type: str, direction: str = "IN", age_hours: float = 0.0):
    """Create an OCPPLog row, back-dating its timestamp via update() since
    `timestamp` is auto_now_add and cannot be set at create time."""
    log = await OCPPLog.create(
        charge_point_id=charge_point_id,
        message_type=message_type,
        direction=direction,
        payload={"status": "ok"},
        status="SUCCESS",
    )
    if age_hours:
        ts = datetime.now(tz=timezone.utc) - timedelta(hours=age_hours)
        await OCPPLog.filter(id=log.id).update(timestamp=ts)
    return log


@pytest.mark.unit
class TestLogsConsole:
    @pytest.mark.asyncio
    async def test_action_filter_single(self, client_admin: AsyncClient, test_charger):
        cp = test_charger.charge_point_string_id
        await _make_log(cp, "BootNotification")
        await _make_log(cp, "Heartbeat")
        await _make_log(cp, "MeterValues")

        resp = await client_admin.get(f"/api/admin/logs?message_type=BootNotification")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()["data"]
        assert len(data) == 1
        assert all(r["message_type"] == "BootNotification" for r in data)

    @pytest.mark.asyncio
    async def test_action_filter_multi(self, client_admin: AsyncClient, test_charger):
        cp = test_charger.charge_point_string_id
        await _make_log(cp, "BootNotification")
        await _make_log(cp, "StatusNotification")
        await _make_log(cp, "Heartbeat")

        resp = await client_admin.get(
            "/api/admin/logs?message_type=BootNotification&message_type=StatusNotification"
        )
        assert resp.status_code == status.HTTP_200_OK
        actions = {r["message_type"] for r in resp.json()["data"]}
        assert actions == {"BootNotification", "StatusNotification"}

    @pytest.mark.asyncio
    async def test_no_action_filter_returns_all(self, client_admin: AsyncClient, test_charger):
        cp = test_charger.charge_point_string_id
        await _make_log(cp, "BootNotification")
        await _make_log(cp, "Heartbeat")

        resp = await client_admin.get("/api/admin/logs")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["total"] >= 2

    @pytest.mark.asyncio
    async def test_charger_filter(self, client_admin: AsyncClient, test_charger):
        cp = test_charger.charge_point_string_id
        await _make_log(cp, "BootNotification")
        await _make_log("some-other-charger", "BootNotification")

        resp = await client_admin.get(f"/api/admin/logs?charge_point_id={cp}")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()["data"]
        assert len(data) == 1
        assert all(r["charge_point_id"] == cp for r in data)

    @pytest.mark.asyncio
    async def test_default_window_excludes_old_rows(self, client_admin: AsyncClient, test_charger):
        cp = test_charger.charge_point_string_id
        await _make_log(cp, "Heartbeat", age_hours=0.0)        # within 24h
        await _make_log(cp, "BootNotification", age_hours=48.0)  # older than the default window

        resp = await client_admin.get(f"/api/admin/logs?charge_point_id={cp}")
        assert resp.status_code == status.HTTP_200_OK
        actions = {r["message_type"] for r in resp.json()["data"]}
        assert "Heartbeat" in actions
        assert "BootNotification" not in actions

    @pytest.mark.asyncio
    async def test_explicit_range_includes_old_rows(self, client_admin: AsyncClient, test_charger):
        cp = test_charger.charge_point_string_id
        await _make_log(cp, "BootNotification", age_hours=48.0)

        start = (datetime.now(tz=timezone.utc) - timedelta(hours=72)).isoformat()
        resp = await client_admin.get(
            "/api/admin/logs", params={"charge_point_id": cp, "start_date": start}
        )
        assert resp.status_code == status.HTTP_200_OK
        actions = {r["message_type"] for r in resp.json()["data"]}
        assert "BootNotification" in actions
