"""Unit tests for the hardened bulk firmware deploy endpoint.

Covers `.scratch/firmware-update-hardening/issues/04-…`: bulk deploy must be
idempotent and classify each charger into success / skipped / failed, never
disturbing an in-flight update (PENDING with attempt_count > 0).

Tests call `_bulk_classify_charger` and `bulk_update_firmware` directly with
FirmwareUpdate / Charger queries mocked — no DB or HTTP plumbing.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routers import firmware as firmware_router
from models import FirmwareUpdateStatusEnum
from services.firmware_update_service import FIRMWARE_MAX_ATTEMPTS

FW = SimpleNamespace(id=5, version="1.5.0")
DL = "https://signed.example/fw"
ADMIN = SimpleNamespace(id=1)


def _charger(firmware_version="1.4.0", id=10):
    return SimpleNamespace(id=id, name=f"CP-{id}", firmware_version=firmware_version)


@pytest.mark.asyncio
async def test_skips_charger_already_on_target_version():
    """Same-version charger is skipped without ever looking up a row."""
    with patch.object(firmware_router.FirmwareUpdate, "get_or_none", new=AsyncMock()) as get_or_none:
        bucket, entry = await firmware_router._bulk_classify_charger(
            _charger(firmware_version="1.5.0"), FW, DL, ADMIN
        )
    assert bucket == "skipped"
    assert entry["reason"] == "already on 1.5.0"
    get_or_none.assert_not_called()


@pytest.mark.asyncio
async def test_skips_in_flight_update_byte_for_byte_untouched():
    """A PENDING row with attempt_count > 0 is left completely unmodified."""
    existing = SimpleNamespace(
        id=9,
        status=FirmwareUpdateStatusEnum.PENDING,
        attempt_count=3,
        last_attempt_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        next_retry_at=datetime(2026, 6, 1, 1, tzinfo=timezone.utc),
        started_at=None,
        completed_at=None,
        error_message="download failed",
        download_url="old-url",
        initiated_by_id=99,
        save=AsyncMock(),
    )
    before = copy.copy(existing)

    with patch.object(firmware_router.FirmwareUpdate, "get_or_none", new=AsyncMock(return_value=existing)):
        bucket, entry = await firmware_router._bulk_classify_charger(_charger(), FW, DL, ADMIN)

    assert bucket == "skipped"
    assert entry["reason"] == f"in-flight, attempt 3/{FIRMWARE_MAX_ATTEMPTS}"
    assert entry["update_id"] == 9
    existing.save.assert_not_called()
    # Every mutable field is exactly as it was.
    for field in ("status", "attempt_count", "last_attempt_at", "next_retry_at",
                  "started_at", "completed_at", "error_message", "download_url", "initiated_by_id"):
        assert getattr(existing, field) == getattr(before, field)


@pytest.mark.asyncio
@pytest.mark.parametrize("prev_status", [
    FirmwareUpdateStatusEnum.FAILED,
    FirmwareUpdateStatusEnum.INSTALLED,
    FirmwareUpdateStatusEnum.CANCELLED,
])
async def test_resets_terminal_row_to_fresh_pending(prev_status):
    """Terminal rows are reset to a fresh PENDING and reported as success."""
    existing = SimpleNamespace(
        id=9, status=prev_status, attempt_count=5,
        last_attempt_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        next_retry_at=None, started_at=None,
        completed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        error_message="boom", download_url="old", initiated_by_id=99,
        save=AsyncMock(),
    )
    with patch.object(firmware_router.FirmwareUpdate, "get_or_none", new=AsyncMock(return_value=existing)):
        bucket, entry = await firmware_router._bulk_classify_charger(_charger(), FW, DL, ADMIN)

    assert bucket == "success"
    assert entry["update_id"] == 9
    existing.save.assert_awaited_once()
    assert existing.status == FirmwareUpdateStatusEnum.PENDING
    assert existing.attempt_count == 0
    assert existing.error_message is None
    assert existing.next_retry_at is None
    assert existing.download_url == DL


@pytest.mark.asyncio
async def test_resets_pending_zero_attempt_row():
    """A PENDING row that never fired (attempt 0) is re-UPSERTed, not skipped."""
    existing = SimpleNamespace(
        id=9, status=FirmwareUpdateStatusEnum.PENDING, attempt_count=0,
        last_attempt_at=None, next_retry_at=None, started_at=None,
        completed_at=None, error_message=None, download_url="old",
        initiated_by_id=99, save=AsyncMock(),
    )
    with patch.object(firmware_router.FirmwareUpdate, "get_or_none", new=AsyncMock(return_value=existing)):
        bucket, _ = await firmware_router._bulk_classify_charger(_charger(), FW, DL, ADMIN)
    assert bucket == "success"
    existing.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_creates_new_row_when_none_exists():
    """No existing row → a fresh PENDING row is created and reported as success."""
    created = SimpleNamespace(id=100)
    with patch.object(firmware_router.FirmwareUpdate, "get_or_none", new=AsyncMock(return_value=None)), \
         patch.object(firmware_router.FirmwareUpdate, "create", new=AsyncMock(return_value=created)) as create:
        bucket, entry = await firmware_router._bulk_classify_charger(_charger(), FW, DL, ADMIN)
    assert bucket == "success"
    assert entry["update_id"] == 100
    create.assert_awaited_once()


def _request_stub():
    return SimpleNamespace(base_url="https://app.voltlync.test/")


@pytest.mark.asyncio
async def test_bulk_returns_three_buckets_and_handles_not_found():
    """End-to-end: a not-found charger lands in failed; others classify normally."""
    fresh = _charger(id=10)  # on 1.4.0 → eligible
    same = _charger(firmware_version="1.5.0", id=11)  # already on target → skipped

    async def fake_get_charger(id):
        return {10: fresh, 11: same}.get(id)  # id 12 → None (not found)

    fake_storage = MagicMock()
    fake_storage.get_firmware_download_url_for_file = MagicMock(return_value=DL)

    req = SimpleNamespace(firmware_file_id=5, charger_ids=[10, 11, 12])

    with patch.object(firmware_router.FirmwareFile, "get_or_none", new=AsyncMock(return_value=FW)), \
         patch.object(firmware_router.Charger, "get_or_none", new=AsyncMock(side_effect=fake_get_charger)), \
         patch.object(firmware_router.FirmwareUpdate, "get_or_none", new=AsyncMock(return_value=None)), \
         patch.object(firmware_router.FirmwareUpdate, "create", new=AsyncMock(return_value=SimpleNamespace(id=100))), \
         patch.object(firmware_router, "storage_service", fake_storage), \
         patch.object(firmware_router, "log_audit_event", new=AsyncMock()):
        result = await firmware_router.bulk_update_firmware(req, _request_stub(), ADMIN)

    assert [e["charger_id"] for e in result.success] == [10]
    assert [e["charger_id"] for e in result.skipped] == [11]
    assert result.skipped[0]["reason"] == "already on 1.5.0"
    assert [e["charger_id"] for e in result.failed] == [12]
    assert result.failed[0]["reason"] == "Charger not found"
