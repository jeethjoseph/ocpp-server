# Background service for retrying failed billing transactions
import asyncio
import logging
from typing import List
from datetime import datetime, timedelta

from services.wallet_service import WalletService
from models import Transaction, TransactionStatusEnum

logger = logging.getLogger(__name__)

class BillingRetryService:
    """Background service to periodically retry failed billing transactions"""
    
    def __init__(self, retry_interval_minutes: int = 30, max_retry_age_hours: int = 24):
        self.retry_interval_minutes = retry_interval_minutes
        self.max_retry_age_hours = max_retry_age_hours
        self.is_running = False
        self._task = None
    
    async def start(self):
        """Start the periodic billing retry service"""
        if self.is_running:
            logger.warning("Billing retry service is already running")
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._periodic_retry_loop())
        logger.info(f"✅ Started billing retry service (interval: {self.retry_interval_minutes}m, max age: {self.max_retry_age_hours}h)")
    
    async def stop(self):
        """Stop the periodic billing retry service"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("🛑 Stopped billing retry service")
    
    async def _periodic_retry_loop(self):
        """Main loop for periodic billing retries"""
        while self.is_running:
            try:
                await self._process_failed_billing_transactions()
                await asyncio.sleep(self.retry_interval_minutes * 60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in billing retry loop: {e}", exc_info=True)
                # Continue running even if there's an error
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    async def _process_failed_billing_transactions(self):
        """Process all failed billing transactions that are eligible for retry"""
        cutoff_time = datetime.utcnow() - timedelta(hours=self.max_retry_age_hours)
        
        # Get failed billing transactions within the retry window
        failed_transactions = await Transaction.filter(
            transaction_status=TransactionStatusEnum.BILLING_FAILED,
            updated_at__gte=cutoff_time
        ).all()
        
        if not failed_transactions:
            logger.debug("No failed billing transactions to retry")
            return
        
        logger.info(f"🔄 Processing {len(failed_transactions)} failed billing transactions")
        
        success_count = 0
        failure_count = 0
        
        for transaction in failed_transactions:
            try:
                success, message, billing_amount = await WalletService.retry_failed_billing(transaction.id)
                
                if success:
                    success_count += 1
                    if billing_amount and billing_amount > 0:
                        logger.info(f"✅ Retry successful for transaction {transaction.id}: ₹{billing_amount}")
                    else:
                        logger.info(f"✅ Retry successful for transaction {transaction.id}: {message}")
                else:
                    failure_count += 1
                    logger.warning(f"❌ Retry failed for transaction {transaction.id}: {message}")
                
                # Small delay between retries to avoid overwhelming the database
                await asyncio.sleep(0.1)
                
            except Exception as e:
                failure_count += 1
                logger.error(f"❌ Exception during retry for transaction {transaction.id}: {e}")
        
        if success_count > 0 or failure_count > 0:
            logger.info(f"🔄 Billing retry completed: {success_count} successful, {failure_count} failed")
    
    async def cleanup_old_failed_transactions(self, max_age_days: int = 7):
        """
        Clean up very old failed billing transactions that are beyond retry.
        This could be called periodically to prevent table bloat.
        """
        cutoff_time = datetime.utcnow() - timedelta(days=max_age_days)
        
        old_failed = await Transaction.filter(
            transaction_status=TransactionStatusEnum.BILLING_FAILED,
            updated_at__lt=cutoff_time
        ).all()
        
        if old_failed:
            logger.info(f"🧹 Found {len(old_failed)} old failed billing transactions (>{max_age_days} days old)")
            # You might want to:
            # 1. Move them to an archive table
            # 2. Mark them as permanently failed
            # 3. Send notifications to administrators
            # For now, just log them
            for transaction in old_failed:
                logger.warning(f"Old failed billing transaction {transaction.id} from {transaction.updated_at}")

# Global instance
billing_retry_service = BillingRetryService()

# Functions to integrate with FastAPI startup/shutdown
async def start_billing_retry_service():
    """Start the billing retry service (call this on app startup)"""
    await billing_retry_service.start()

async def stop_billing_retry_service():
    """Stop the billing retry service (call this on app shutdown)"""
    await billing_retry_service.stop()