"""Firmware update scheduler with BootNotification-driven completion.

Completion signal: BootNotification with matching firmware_version. The OCPP
FirmwareStatusNotification channel is unreliable (charger modems suspend WS
during download); see comprehensive-architecture-documentation.md.

Retry semantics:
- Per-attempt: send OCPP UpdateFirmware. Wait for BootNotification.
- BootNotification with matching version  → INSTALLED.
- BootNotification with non-matching version, outside debounce window
  → failed attempt. Schedule next attempt via exponential backoff.
- No BootNotification within ATTEMPT_TIMEOUT seconds → same as above.
- Budget exhausted (attempts or elapsed time) → FAILED.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from tortoise.expressions import Q

from utils import safe_create_task
from models import FirmwareUpdate, FirmwareUpdateStatusEnum, Charger, Transaction

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, falling back to %d", name, raw, default)
        return default


FIRMWARE_MAX_ATTEMPTS = _env_int("FIRMWARE_MAX_ATTEMPTS", 5)
FIRMWARE_MAX_ELAPSED_SECONDS = _env_int("FIRMWARE_MAX_ELAPSED_SECONDS", 21600)  # 6h
FIRMWARE_ATTEMPT_TIMEOUT_SECONDS = _env_int("FIRMWARE_ATTEMPT_TIMEOUT_SECONDS", 7200)  # 2h
FIRMWARE_BOOT_DEBOUNCE_SECONDS = _env_int("FIRMWARE_BOOT_DEBOUNCE_SECONDS", 300)  # 5min

# Backoff between attempts. Index by (attempt_count - 1); clamps at the last entry.
BACKOFF_SCHEDULE_SECONDS = [300, 1800, 7200, 14400]  # 5min, 30min, 2h, 4h

# After a successful UpdateFirmware send, allow WS to drop for this long without alarms.
WS_DROP_EXPECTED_SECONDS = 1800  # 30min


def compute_next_retry(attempt_count: int, initiated_at: datetime, now: datetime):
    """Return the next retry timestamp, or None if budget is exhausted."""
    if attempt_count >= FIRMWARE_MAX_ATTEMPTS:
        return None
    if (now - initiated_at).total_seconds() >= FIRMWARE_MAX_ELAPSED_SECONDS:
        return None
    idx = min(max(attempt_count, 1) - 1, len(BACKOFF_SCHEDULE_SECONDS) - 1)
    return now + timedelta(seconds=BACKOFF_SCHEDULE_SECONDS[idx])


class FirmwareUpdateService:
    """Background service for OCPP-driven firmware updates.

    Each loop iteration runs two phases:
    - Phase B: declare timed-out attempts failed (last_attempt_at older than
      ATTEMPT_TIMEOUT with no next_retry_at scheduled).
    - Phase A: send UpdateFirmware for rows that are due (never attempted, or
      next_retry_at has been reached).

    handle_boot_notification is the third entry point, called synchronously
    from the OCPP BootNotification handler.
    """

    def __init__(self, check_interval_seconds: int = 60):
        self.check_interval_seconds = check_interval_seconds
        self.is_running = False
        self._task = None

    async def start(self):
        if self.is_running:
            logger.warning("Firmware update service is already running")
            return
        self.is_running = True
        self._task = safe_create_task(self._periodic_check_loop())
        logger.info(
            "📦 ✅ Started firmware update service "
            "(interval=%ds, max_attempts=%d, max_elapsed=%ds, attempt_timeout=%ds, boot_debounce=%ds)",
            self.check_interval_seconds,
            FIRMWARE_MAX_ATTEMPTS,
            FIRMWARE_MAX_ELAPSED_SECONDS,
            FIRMWARE_ATTEMPT_TIMEOUT_SECONDS,
            FIRMWARE_BOOT_DEBOUNCE_SECONDS,
        )

    async def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("📦 🛑 Stopped firmware update service")

    async def _periodic_check_loop(self):
        while self.is_running:
            try:
                now = datetime.now(timezone.utc)
                await self._process_timed_out_attempts(now)
                await self._process_due_attempts(now)
                await asyncio.sleep(self.check_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("📦 ❌ Error in firmware update loop: %s", e, exc_info=True)
                await asyncio.sleep(60)

    async def _process_timed_out_attempts(self, now: datetime):
        cutoff = now - timedelta(seconds=FIRMWARE_ATTEMPT_TIMEOUT_SECONDS)
        timed_out = await FirmwareUpdate.filter(
            status=FirmwareUpdateStatusEnum.PENDING,
            last_attempt_at__lte=cutoff,
            next_retry_at__isnull=True,
        ).prefetch_related('charger', 'firmware_file')

        for update in timed_out:
            try:
                await self._handle_attempt_failed(
                    update, now,
                    reason="attempt timeout: no BootNotification received within ATTEMPT_TIMEOUT",
                )
            except Exception as e:
                logger.error("📦 ❌ Error timing out update %s: %s", update.id, e, exc_info=True)

    async def _process_due_attempts(self, now: datetime):
        # Eligible: never-attempted OR scheduled retry that has come due.
        candidates = await FirmwareUpdate.filter(
            Q(status=FirmwareUpdateStatusEnum.PENDING)
            & (Q(last_attempt_at__isnull=True) | Q(next_retry_at__lte=now))
        ).prefetch_related('charger', 'firmware_file')

        if not candidates:
            return

        logger.info("📦 Processing %d due firmware update(s)", len(candidates))
        for update in candidates:
            try:
                await self._try_trigger_update(update, now)
            except Exception as e:
                logger.error("📦 ❌ Error triggering update %s: %s", update.id, e, exc_info=True)

    async def _try_trigger_update(self, update: FirmwareUpdate, now: datetime):
        """Send UpdateFirmware to the charger if preconditions pass."""
        charger = update.charger
        firmware_version = update.firmware_file.version

        # Pure non-OCPP chargers (never connected via WS) skip silently.
        # The polling endpoint /api/firmware/latest delivers to them.
        if not charger.last_heart_beat_time:
            logger.debug(
                "📦 Charger %s has never sent heartbeat, skipping (polling-path expected)",
                charger.charge_point_string_id,
            )
            return

        time_since_heartbeat = now - charger.last_heart_beat_time.replace(tzinfo=timezone.utc)
        if time_since_heartbeat.total_seconds() > 90:
            logger.debug(
                "📦 Charger %s offline (%ds since heartbeat), skipping",
                charger.charge_point_string_id,
                int(time_since_heartbeat.total_seconds()),
            )
            return

        active_transaction = await Transaction.filter(
            charger_id=charger.id,
            transaction_status__in=["STARTED", "PENDING_START", "RUNNING"],
        ).first()
        if active_transaction:
            logger.debug(
                "📦 Charger %s has active transaction %s, skipping",
                charger.charge_point_string_id, active_transaction.id,
            )
            return

        # Already on target version — close as INSTALLED.
        if charger.firmware_version == firmware_version:
            logger.info(
                "📦 Charger %s already on version %s, marking INSTALLED",
                charger.charge_point_string_id, firmware_version,
            )
            update.status = FirmwareUpdateStatusEnum.INSTALLED
            update.completed_at = now
            update.next_retry_at = None
            await update.save()
            return

        # Refresh presigned URL — old URL may have expired if this is a retry.
        from services import storage_service
        update.download_url = storage_service.get_firmware_download_url_for_file(update.firmware_file)

        payload = {
            "location": update.download_url,
            "retrieve_date": now.isoformat(),
            "retries": 3,
            "retry_interval": 300,
        }

        logger.info(
            "📦 Triggering firmware update attempt %d/%d: %s → %s (current: %s)",
            update.attempt_count + 1, FIRMWARE_MAX_ATTEMPTS,
            charger.charge_point_string_id, firmware_version,
            charger.firmware_version or "unknown",
        )

        from main import send_ocpp_request
        success, response = await send_ocpp_request(
            charger.charge_point_string_id,
            "UpdateFirmware",
            payload,
        )

        update.attempt_count += 1
        update.last_attempt_at = now
        update.next_retry_at = None
        if update.started_at is None:
            update.started_at = now

        if success:
            logger.info(
                "📦 ✅ UpdateFirmware sent to %s (attempt %d)",
                charger.charge_point_string_id, update.attempt_count,
            )
            await update.save()
            await self._mark_ws_drop_expected(charger.charge_point_string_id, now)
        else:
            logger.error(
                "📦 ❌ UpdateFirmware send failed for %s: %s",
                charger.charge_point_string_id, response,
            )
            await update.save()
            await self._handle_attempt_failed(
                update, now,
                reason=f"UpdateFirmware send failed: {response}",
            )

    async def _mark_ws_drop_expected(self, charge_point_id: str, now: datetime):
        """Set the in-memory flag so disconnect handlers don't alarm during firmware download."""
        try:
            from main import connected_charge_points
            entry = connected_charge_points.get(charge_point_id)
            if entry is not None:
                entry["expected_ws_drop_until"] = now + timedelta(seconds=WS_DROP_EXPECTED_SECONDS)
        except Exception as e:
            logger.debug("📦 Could not set expected_ws_drop_until for %s: %s", charge_point_id, e)

    async def _handle_attempt_failed(self, update: FirmwareUpdate, now: datetime, reason: str):
        """Apply backoff or mark FAILED if budget exhausted."""
        next_retry = compute_next_retry(update.attempt_count, update.initiated_at, now)
        if next_retry is None:
            update.status = FirmwareUpdateStatusEnum.FAILED
            update.completed_at = now
            update.next_retry_at = None
            update.error_message = (
                f"retry budget exhausted ({update.attempt_count} attempts): {reason}"
            )
            logger.error(
                "📦 ❌ Firmware update %s for charger %s FAILED: %s",
                update.id, update.charger_id, update.error_message,
            )
        else:
            update.next_retry_at = next_retry
            update.error_message = reason
            logger.warning(
                "📦 ⚠️ Firmware update %s attempt %d failed (%s); next retry at %s",
                update.id, update.attempt_count, reason, next_retry.isoformat(),
            )
        await update.save()

    async def handle_boot_notification(self, charger: Charger, reported_version):
        """Cross-check pending firmware updates against the version reported on boot.

        Called from the OCPP BootNotification handler (main.py).
        - Matching version → INSTALLED.
        - Mismatch within debounce window → ignore (charger may still be downloading/installing).
        - Mismatch outside debounce window → treat current attempt as failed; schedule retry or fail.
        """
        if not reported_version:
            return
        now = datetime.now(timezone.utc)

        pending = await FirmwareUpdate.filter(
            charger_id=charger.id,
            status=FirmwareUpdateStatusEnum.PENDING,
        ).prefetch_related('firmware_file')

        for update in pending:
            if reported_version == update.firmware_file.version:
                update.status = FirmwareUpdateStatusEnum.INSTALLED
                update.completed_at = now
                update.next_retry_at = None
                update.error_message = None
                await update.save()
                logger.info(
                    "📦 ✅ Firmware update %s INSTALLED for charger %s (boot reported %s)",
                    update.id, charger.charge_point_string_id, reported_version,
                )
                continue

            if update.last_attempt_at is None:
                # We haven't sent UpdateFirmware yet — this boot isn't our concern.
                continue

            last_attempt = update.last_attempt_at.replace(tzinfo=timezone.utc) \
                if update.last_attempt_at.tzinfo is None else update.last_attempt_at
            seconds_since_attempt = (now - last_attempt).total_seconds()
            if seconds_since_attempt < FIRMWARE_BOOT_DEBOUNCE_SECONDS:
                logger.debug(
                    "📦 Ignoring boot from %s within debounce window (%ds since last attempt)",
                    charger.charge_point_string_id, int(seconds_since_attempt),
                )
                continue

            try:
                await self._handle_attempt_failed(
                    update, now,
                    reason=(
                        f"BootNotification reported version {reported_version!r} "
                        f"!= target {update.firmware_file.version!r}"
                    ),
                )
            except Exception as e:
                logger.error(
                    "📦 ❌ Error handling boot-driven failure for update %s: %s",
                    update.id, e, exc_info=True,
                )


# Global service instance
firmware_update_service = FirmwareUpdateService(check_interval_seconds=60)


async def start_firmware_update_service():
    await firmware_update_service.start()


async def stop_firmware_update_service():
    await firmware_update_service.stop()
