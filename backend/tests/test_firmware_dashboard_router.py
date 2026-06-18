"""Unit test for the firmware update-status dashboard endpoint.

Covers `.scratch/firmware-update-hardening/issues/03-…`: the in_progress item
shape must carry `error_message` so the admin Active Updates table can surface
the last-attempt failure reason on a retrying PENDING row.

Calls `get_update_status_dashboard` directly as a coroutine with FirmwareUpdate
queries mocked, so no DB or HTTP plumbing is needed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from routers import firmware as firmware_router


class _FakeQuery:
    """Stands in for a Tortoise queryset: awaitable (returns rows) and supports
    the .prefetch_related().order_by() chain plus .count()."""

    def __init__(self, rows):
        self._rows = rows

    def prefetch_related(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def __await__(self):
        async def _coro():
            return self._rows
        return _coro().__await__()

    async def count(self):
        return len(self._rows)


@pytest.mark.asyncio
async def test_dashboard_in_progress_item_includes_error_message():
    """A retrying PENDING row exposes its last-attempt error_message in the dict."""
    update = SimpleNamespace(
        id=7,
        charger=SimpleNamespace(id=10, name="CP-Alpha", charge_point_string_id="CP-ALPHA-01"),
        firmware_file=SimpleNamespace(version="1.5.0"),
        status="PENDING",
        attempt_count=3,
        last_attempt_at=None,
        next_retry_at=None,
        started_at=None,
        initiated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        error_message="download failed: charger offline",
    )

    with patch.object(firmware_router.FirmwareUpdate, "filter", return_value=_FakeQuery([update])):
        result = await firmware_router.get_update_status_dashboard(user=SimpleNamespace(id=1))

    assert len(result.in_progress) == 1
    item = result.in_progress[0]
    assert item["error_message"] == "download failed: charger offline"
    assert item["update_id"] == 7
    assert item["attempt_count"] == 3
