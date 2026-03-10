# Background service for processing pending firmware updates
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from utils import safe_create_task
from models import FirmwareUpdate, FirmwareUpdateStatusEnum, Charger, Transaction

logger = logging.getLogger(__name__)

class FirmwareUpdateService:
    """
    Background service to process pending firmware updates.

    This service periodically checks for firmware updates in PENDING status
    and attempts to trigger them if the charger is ready (online and not charging).
    """

    def __init__(self, check_interval_seconds: int = 60):
        """
        Initialize the firmware update service.

        Args:
            check_interval_seconds: How often to check for pending updates (default: 60s)
        """
        self.check_interval_seconds = check_interval_seconds
        self.is_running = False
        self._task = None

    async def start(self):
        """Start the periodic update processor"""
        if self.is_running:
            logger.warning("Firmware update service is already running")
            return

        self.is_running = True
        self._task = safe_create_task(self._periodic_check_loop())
        logger.info(f"📦 ✅ Started firmware update service (interval: {self.check_interval_seconds}s)")

    async def stop(self):
        """Stop the service gracefully"""
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
        """Main loop that checks for pending updates at regular intervals"""
        while self.is_running:
            try:
                await self._process_pending_updates()
                await asyncio.sleep(self.check_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"📦 ❌ Error in firmware update loop: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 minute before retrying on error

    async def _process_pending_updates(self):
        """Find and process all pending firmware updates"""
        pending_updates = await FirmwareUpdate.filter(
            status=FirmwareUpdateStatusEnum.PENDING
        ).prefetch_related('charger', 'firmware_file')

        if not pending_updates:
            logger.debug("📦 No pending firmware updates")
            return

        logger.info(f"📦 Processing {len(pending_updates)} pending firmware update(s)")

        for update in pending_updates:
            try:
                await self._try_trigger_update(update)
            except Exception as e:
                logger.error(f"📦 ❌ Error processing update {update.id}: {e}", exc_info=True)

    async def _try_trigger_update(self, update: FirmwareUpdate):
        """
        Try to trigger a single firmware update.

        Performs validation checks:
        1. Charger is online (heartbeat within 90 seconds)
        2. No active charging transaction
        3. Charger not already on target version

        If all checks pass, sends OCPP UpdateFirmware command.
        """
        charger = update.charger
        firmware_version = update.firmware_file.version

        # Check 1: Charger has sent heartbeat
        if not charger.last_heart_beat_time:
            logger.debug(f"📦 Charger {charger.charge_point_string_id} has never sent heartbeat, skipping")
            return

        # Check 2: Charger is online (heartbeat within 90 seconds)
        time_since_heartbeat = datetime.now(timezone.utc) - charger.last_heart_beat_time.replace(tzinfo=timezone.utc)
        if time_since_heartbeat.total_seconds() > 90:
            logger.debug(
                f"📦 Charger {charger.charge_point_string_id} offline "
                f"({int(time_since_heartbeat.total_seconds())}s since heartbeat), skipping"
            )
            return

        # Check 3: No active transaction
        active_transaction = await Transaction.filter(
            charger_id=charger.id,
            transaction_status__in=["STARTED", "PENDING_START", "RUNNING"]
        ).first()

        if active_transaction:
            logger.debug(
                f"📦 Charger {charger.charge_point_string_id} has active transaction "
                f"(ID: {active_transaction.id}), skipping"
            )
            return

        # Check 4: Not already on target version
        if charger.firmware_version == firmware_version:
            logger.info(
                f"📦 Charger {charger.charge_point_string_id} already has version {firmware_version}, "
                f"marking as INSTALLED"
            )
            update.status = FirmwareUpdateStatusEnum.INSTALLED
            update.completed_at = datetime.now(timezone.utc)
            await update.save()
            return

        # All checks passed - send OCPP UpdateFirmware command
        logger.info(
            f"📦 Triggering firmware update: {charger.charge_point_string_id} → "
            f"{firmware_version} (current: {charger.firmware_version or 'unknown'})"
        )

        # Import here to avoid circular dependency
        from main import send_ocpp_request

        payload = {
            "location": update.download_url,
            "retrieve_date": datetime.now(timezone.utc).isoformat(),
            "retries": 3,
            "retry_interval": 300  # 5 minutes between retries
        }

        success, response = await send_ocpp_request(
            charger.charge_point_string_id,
            "UpdateFirmware",
            payload
        )

        if success:
            logger.info(f"📦 ✅ UpdateFirmware command sent to {charger.charge_point_string_id}")
            update.started_at = datetime.now(timezone.utc)
            # Status stays PENDING until charger sends FirmwareStatusNotification
        else:
            logger.error(f"📦 ❌ Failed to send UpdateFirmware to {charger.charge_point_string_id}: {response}")
            update.status = FirmwareUpdateStatusEnum.DOWNLOAD_FAILED
            update.error_message = f"Failed to send OCPP command: {response}"
            update.retry_count += 1
            update.completed_at = datetime.now(timezone.utc)

        await update.save()


# Global service instance
firmware_update_service = FirmwareUpdateService(check_interval_seconds=60)

# Functions to integrate with FastAPI startup/shutdown
async def start_firmware_update_service():
    """Start the firmware update service (call this on app startup)"""
    await firmware_update_service.start()

async def stop_firmware_update_service():
    """Stop the firmware update service (call this on app shutdown)"""
    await firmware_update_service.stop()
