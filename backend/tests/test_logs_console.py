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

    @pytest.mark.asyncio
    async def test_limit_over_ceiling_rejected(self, client_admin: AsyncClient):
        resp = await client_admin.get("/api/admin/logs", params={"limit": 5001})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_limit_at_ceiling_accepted(self, client_admin: AsyncClient):
        resp = await client_admin.get("/api/admin/logs", params={"limit": 5000})
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_offset_pagination_slices(self, client_admin: AsyncClient, test_charger):
        cp = test_charger.charge_point_string_id
        for _ in range(5):
            await _make_log(cp, "Heartbeat")

        page1 = await client_admin.get(
            "/api/admin/logs", params={"charge_point_id": cp, "limit": 2, "offset": 0}
        )
        page2 = await client_admin.get(
            "/api/admin/logs", params={"charge_point_id": cp, "limit": 2, "offset": 2}
        )
        page3 = await client_admin.get(
            "/api/admin/logs", params={"charge_point_id": cp, "limit": 2, "offset": 4}
        )
        for r in (page1, page2, page3):
            assert r.status_code == status.HTTP_200_OK

        b1, b2, b3 = page1.json(), page2.json(), page3.json()
        assert b1["total"] == 5 and b1["offset"] == 0 and b1["limit"] == 2
        assert len(b1["data"]) == 2 and b1["has_more"] is True
        assert len(b2["data"]) == 2 and b2["has_more"] is True
        assert len(b3["data"]) == 1 and b3["has_more"] is False

        # Stable, non-overlapping slices (deterministic ordering by -timestamp, -id).
        ids = [r["id"] for r in b1["data"] + b2["data"] + b3["data"]]
        assert len(ids) == len(set(ids)) == 5

    @pytest.mark.asyncio
    async def test_export_streams_csv(self, client_admin: AsyncClient, test_charger):
        cp = test_charger.charge_point_string_id
        await _make_log(cp, "BootNotification")
        await _make_log(cp, "Heartbeat")

        resp = await client_admin.get(
            "/api/admin/logs/export", params={"charge_point_id": cp}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.headers["content-type"].startswith("text/csv")
        assert resp.headers["content-disposition"] == "attachment; filename=ocpp-logs.csv"

        lines = [ln for ln in resp.text.splitlines() if ln.strip()]
        header = lines[0]
        assert header == "timestamp,charge_point_id,direction,message_type,status,message_id,payload"
        assert len(lines) == 3  # header + 2 rows
        assert "BootNotification" in resp.text and "Heartbeat" in resp.text
