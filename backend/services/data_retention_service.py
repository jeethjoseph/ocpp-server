# Background service for cleaning up old telemetry and log data
import asyncio
import logging
from datetime import datetime, timedelta

from models import SignalQuality, OCPPLog

logger = logging.getLogger(__name__)

class DataRetentionService:
    """
    Background service to periodically clean up old data
    - Signal quality data older than 90 days
    - OCPP logs older than 90 days
    """

    def __init__(self, retention_days: int = 90, cleanup_interval_hours: int = 24):
        """
        Initialize data retention service

        Args:
            retention_days: Number of days to retain data (default: 90)
            cleanup_interval_hours: How often to run cleanup (default: 24 hours)
        """
        self.retention_days = retention_days
        self.cleanup_interval_hours = cleanup_interval_hours
        self.is_running = False
        self._task = None

    async def start(self):
        """Start the periodic data cleanup service"""
        if self.is_running:
            logger.warning("Data retention service is already running")
            return

        self.is_running = True
        self._task = asyncio.create_task(self._periodic_cleanup_loop())
        logger.info(f"✅ Started data retention service (retention: {self.retention_days} days, interval: {self.cleanup_interval_hours}h)")

    async def stop(self):
        """Stop the periodic data cleanup service"""
        if not self.is_running:
            return

        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("🛑 Stopped data retention service")

    async def _periodic_cleanup_loop(self):
        """Main loop for periodic data cleanup"""
        # Run cleanup immediately on startup, then periodically
        while self.is_running:
            try:
                await self._cleanup_old_data()

                # Wait for next cleanup interval
                await asyncio.sleep(self.cleanup_interval_hours * 3600)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"❌ Error in data retention cleanup loop: {e}", exc_info=True)
                # Wait a bit before retrying on error
                await asyncio.sleep(3600)  # Retry in 1 hour

    async def _cleanup_old_data(self):
        """Delete old signal quality data and OCPP logs"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)
            logger.info(f"🗑️  Running data retention cleanup (deleting data older than {cutoff_date.isoformat()})")

            # Clean up old signal quality data
            signal_quality_deleted = await self._cleanup_signal_quality(cutoff_date)

            # Clean up old OCPP logs
            ocpp_logs_deleted = await self._cleanup_ocpp_logs(cutoff_date)

            logger.info(
                f"✅ Data retention cleanup complete: "
                f"deleted {signal_quality_deleted} signal_quality records, "
                f"{ocpp_logs_deleted} OCPP log records"
            )

        except Exception as e:
            logger.error(f"❌ Error during data cleanup: {e}", exc_info=True)

    async def _cleanup_signal_quality(self, cutoff_date: datetime) -> int:
        """Delete signal quality records older than cutoff date"""
        try:
            # Count records to be deleted
            count = await SignalQuality.filter(created_at__lt=cutoff_date).count()

            if count == 0:
                logger.info("🗑️  No old signal quality data to delete")
                return 0

            # Delete old records
            await SignalQuality.filter(created_at__lt=cutoff_date).delete()
            logger.info(f"🗑️  Deleted {count} signal quality records older than {self.retention_days} days")

            return count

        except Exception as e:
            logger.error(f"❌ Error cleaning up signal quality data: {e}", exc_info=True)
            return 0

    async def _cleanup_ocpp_logs(self, cutoff_date: datetime) -> int:
        """Delete OCPP log records older than cutoff date"""
        try:
            # Count records to be deleted
            count = await OCPPLog.filter(created_at__lt=cutoff_date).count()

            if count == 0:
                logger.info("🗑️  No old OCPP logs to delete")
                return 0

            # Delete old records
            await OCPPLog.filter(created_at__lt=cutoff_date).delete()
            logger.info(f"🗑️  Deleted {count} OCPP log records older than {self.retention_days} days")

            return count

        except Exception as e:
            logger.error(f"❌ Error cleaning up OCPP logs: {e}", exc_info=True)
            return 0


# Global service instance
_data_retention_service = None

async def start_data_retention_service(retention_days: int = 90, cleanup_interval_hours: int = 24):
    """Start the data retention background service"""
    global _data_retention_service

    if _data_retention_service is None:
        _data_retention_service = DataRetentionService(
            retention_days=retention_days,
            cleanup_interval_hours=cleanup_interval_hours
        )

    await _data_retention_service.start()

async def stop_data_retention_service():
    """Stop the data retention background service"""
    global _data_retention_service

    if _data_retention_service:
        await _data_retention_service.stop()
