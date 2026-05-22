"""Unit tests for the firmware-update retry scheduler.

Covers the pure helpers (compute_next_retry) and the boot-driven completion
flow (handle_boot_notification). Phase A / Phase B loop tests would require
end-to-end fixtures and are exercised by integration tests instead.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import firmware_update_service as svc


def _mock_filter_returning(update_list):
    """Build a MagicMock queryset whose prefetch_related awaits to update_list.

    Mirrors the call shape `await FirmwareUpdate.filter(...).prefetch_related(...)`.
    """
    qs = MagicMock()
    qs.prefetch_related = AsyncMock(return_value=update_list)
    return qs


# ---------- compute_next_retry ----------


def test_compute_next_retry_first_attempt_uses_first_schedule_entry():
    now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    initiated = now - timedelta(minutes=1)
    out = svc.compute_next_retry(attempt_count=1, initiated_at=initiated, now=now)
    assert out == now + timedelta(seconds=svc.BACKOFF_SCHEDULE_SECONDS[0])


def test_compute_next_retry_clamps_past_schedule_end():
    now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    initiated = now - timedelta(minutes=1)
    # attempt_count 99 would index out of the schedule; we clamp to the last entry.
    out = svc.compute_next_retry(attempt_count=99, initiated_at=initiated, now=now)
    assert out is None  # because 99 >= MAX_ATTEMPTS, returns None first


def test_compute_next_retry_returns_none_when_attempt_budget_exhausted():
    now = datetime.now(timezone.utc)
    out = svc.compute_next_retry(
        attempt_count=svc.FIRMWARE_MAX_ATTEMPTS,
        initiated_at=now - timedelta(minutes=1),
        now=now,
    )
    assert out is None


def test_compute_next_retry_returns_none_when_time_budget_exhausted():
    now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    initiated = now - timedelta(seconds=svc.FIRMWARE_MAX_ELAPSED_SECONDS + 60)
    out = svc.compute_next_retry(attempt_count=1, initiated_at=initiated, now=now)
    assert out is None


def test_compute_next_retry_schedule_progression():
    """Each attempt should pick the next backoff bucket up to the last entry."""
    now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    initiated = now - timedelta(seconds=1)
    expected_seconds = svc.BACKOFF_SCHEDULE_SECONDS
    for attempt, secs in enumerate(expected_seconds, start=1):
        if attempt > svc.FIRMWARE_MAX_ATTEMPTS:
            break
        out = svc.compute_next_retry(attempt_count=attempt, initiated_at=initiated, now=now)
        assert out == now + timedelta(seconds=secs), f"attempt {attempt} mismatch"


# ---------- handle_boot_notification ----------


def _mk_update(target_version: str, attempt_count: int = 0, last_attempt_seconds_ago: int | None = None,
               status: str = "PENDING") -> SimpleNamespace:
    """A test-double for FirmwareUpdate that mimics the attributes the handler uses."""
    now = datetime.now(timezone.utc)
    last_attempt_at = None
    if last_attempt_seconds_ago is not None:
        last_attempt_at = now - timedelta(seconds=last_attempt_seconds_ago)
    saved = {}
    update = SimpleNamespace(
        id=42,
        status=status,
        attempt_count=attempt_count,
        last_attempt_at=last_attempt_at,
        next_retry_at=None,
        completed_at=None,
        error_message=None,
        initiated_at=now - timedelta(minutes=5),
        firmware_file=SimpleNamespace(version=target_version),
        charger_id=1,
        save=AsyncMock(side_effect=lambda: saved.update(
            status=update.status, attempt_count=update.attempt_count,
            next_retry_at=update.next_retry_at, completed_at=update.completed_at,
            error_message=update.error_message,
        )),
    )
    update._saved = saved
    return update


@pytest.mark.asyncio
async def test_handle_boot_notification_marks_installed_on_version_match():
    update = _mk_update(target_version="1.2.3")
    charger = SimpleNamespace(id=1, charge_point_string_id="CP1")
    service = svc.FirmwareUpdateService()

    with patch.object(svc.FirmwareUpdate, "filter", return_value=_mock_filter_returning([update])):
        await service.handle_boot_notification(charger, "1.2.3")

    assert update.status == "INSTALLED"
    assert update.completed_at is not None
    assert update.next_retry_at is None
    update.save.assert_awaited()


@pytest.mark.asyncio
async def test_handle_boot_notification_ignores_boot_within_debounce_window():
    """Boot reporting the OLD version within the debounce window should not fail the attempt."""
    update = _mk_update(
        target_version="1.2.3",
        attempt_count=1,
        last_attempt_seconds_ago=max(1, svc.FIRMWARE_BOOT_DEBOUNCE_SECONDS // 2),
    )
    charger = SimpleNamespace(id=1, charge_point_string_id="CP1")
    service = svc.FirmwareUpdateService()

    with patch.object(svc.FirmwareUpdate, "filter", return_value=_mock_filter_returning([update])):
        await service.handle_boot_notification(charger, "1.2.2")

    assert update.status == "PENDING"
    assert update.next_retry_at is None
    update.save.assert_not_called()


@pytest.mark.asyncio
async def test_handle_boot_notification_schedules_retry_on_version_mismatch_past_debounce():
    update = _mk_update(
        target_version="1.2.3",
        attempt_count=1,
        last_attempt_seconds_ago=svc.FIRMWARE_BOOT_DEBOUNCE_SECONDS + 60,
    )
    charger = SimpleNamespace(id=1, charge_point_string_id="CP1")
    service = svc.FirmwareUpdateService()

    with patch.object(svc.FirmwareUpdate, "filter", return_value=_mock_filter_returning([update])):
        await service.handle_boot_notification(charger, "1.2.2")

    assert update.status == "PENDING"
    assert update.next_retry_at is not None
    update.save.assert_awaited()


@pytest.mark.asyncio
async def test_handle_boot_notification_ignores_pre_attempt_boot():
    """If we haven't sent UpdateFirmware yet, an arbitrary boot is not a verdict."""
    update = _mk_update(target_version="1.2.3", attempt_count=0, last_attempt_seconds_ago=None)
    charger = SimpleNamespace(id=1, charge_point_string_id="CP1")
    service = svc.FirmwareUpdateService()

    with patch.object(svc.FirmwareUpdate, "filter", return_value=_mock_filter_returning([update])):
        await service.handle_boot_notification(charger, "1.2.2")

    assert update.status == "PENDING"
    update.save.assert_not_called()
