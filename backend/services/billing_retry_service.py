# Background service for retrying failed billing transactions
import asyncio
import logging
from typing import List
from datetime import datetime, timedelta, timezone

from utils import safe_create_task
from services.wallet_service import WalletService
from services.razorpay_service import razorpay_service
from models import Transaction, TransactionStatusEnum, MeterValue, QRPayment, QRPaymentStatusEnum

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
        self._task = safe_create_task(self._periodic_retry_loop())
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
                await self._process_failed_qr_refunds()
                await self._cleanup_orphaned_qr_payments()
                await self._cleanup_stale_suspended_transactions()
                await asyncio.sleep(self.retry_interval_minutes * 60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in billing retry loop: {e}", exc_info=True)
                # Continue running even if there's an error
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    async def _process_failed_billing_transactions(self):
        """Process all failed billing transactions that are eligible for retry"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=self.max_retry_age_hours)
        
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
    
    async def _process_failed_qr_refunds(self):
        """Retry failed QR payment refunds (e.g. insufficient Razorpay balance)"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=self.max_retry_age_hours)

        failed_refunds = await QRPayment.filter(
            status=QRPaymentStatusEnum.REFUND_FAILED,
            updated_at__gte=cutoff_time,
        ).all()

        if not failed_refunds:
            logger.debug("No failed QR refunds to retry")
            return

        logger.info(f"🔄 Retrying {len(failed_refunds)} failed QR refunds")

        success_count = 0
        failure_count = 0

        for qr_payment in failed_refunds:
            try:
                refund_amount = qr_payment.refund_amount
                if not refund_amount or refund_amount <= 0:
                    logger.warning(f"QR payment {qr_payment.id} has no refund_amount, skipping")
                    continue

                refund_result = razorpay_service.refund_payment(
                    qr_payment.razorpay_payment_id,
                    amount=refund_amount,
                    notes={"qr_payment_id": str(qr_payment.id), "reason": "Retry: " + (qr_payment.failure_reason or "unknown")},
                )
                qr_payment.razorpay_refund_id = refund_result.get("id")
                qr_payment.status = QRPaymentStatusEnum.REFUNDED
                qr_payment.failure_reason = None
                await qr_payment.save()
                success_count += 1
                logger.info(f"✅ QR refund retry successful: payment {qr_payment.id}, ₹{refund_amount}")

            except Exception as e:
                failure_count += 1
                qr_payment.failure_reason = str(e)
                await qr_payment.save()
                logger.warning(f"❌ QR refund retry failed for payment {qr_payment.id}: {e}")

            await asyncio.sleep(0.1)

        if success_count > 0 or failure_count > 0:
            logger.info(f"🔄 QR refund retry completed: {success_count} successful, {failure_count} failed")

    async def _cleanup_orphaned_qr_payments(self):
        """Refund QR payments stuck in PAID or CHARGING with no linked transaction.

        This catches edge cases where:
        - handle_payment_without_plug task died (server restart)
        - RemoteStart succeeded but StartTransaction never came
        - Any other gap between payment and charging
        """
        from services.qr_payment_service import QRPaymentService, QR_PAYMENT_PENDING_TIMEOUT

        # PAID payments older than 2x the pending timeout are definitely orphaned
        stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=QR_PAYMENT_PENDING_TIMEOUT * 2)

        orphaned_payments = await QRPayment.filter(
            status=QRPaymentStatusEnum.PAID,
            transaction_id__isnull=True,
            created_at__lt=stale_cutoff,
        ).all()

        if not orphaned_payments:
            return

        logger.info(f"🧹 Found {len(orphaned_payments)} orphaned QR payments to refund")

        for qr_payment in orphaned_payments:
            try:
                age_minutes = (datetime.now(timezone.utc) - qr_payment.created_at).total_seconds() / 60
                logger.info(
                    f"Refunding orphaned QR payment {qr_payment.id}: "
                    f"₹{qr_payment.amount_paid}, status={qr_payment.status.value}, "
                    f"age={age_minutes:.0f}m"
                )
                qr_payment.status = QRPaymentStatusEnum.EXPIRED
                qr_payment.failure_reason = "Orphaned payment - no transaction linked"
                await qr_payment.save()
                await QRPaymentService._full_refund(qr_payment, "Orphaned payment cleanup")
            except Exception as e:
                logger.error(f"Failed to refund orphaned QR payment {qr_payment.id}: {e}", exc_info=True)

            await asyncio.sleep(0.1)

    async def _cleanup_stale_suspended_transactions(self):
        """Auto-stop SUSPENDED transactions orphaned by server restarts.

        The in-memory asyncio timeout task is lost on restart, so this catches
        any SUSPENDED transaction whose suspend window has expired.

        Uses an atomic compare-and-swap update to avoid racing with
        _suspend_timeout or other code paths that also transition SUSPENDED
        transactions.
        """
        from main import SUSPEND_TIMEOUT_SECONDS

        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=SUSPEND_TIMEOUT_SECONDS)

        stale_transactions = await Transaction.filter(
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at__lt=cutoff_time
        ).all()

        if not stale_transactions:
            return

        logger.info(f"🧹 Found {len(stale_transactions)} stale SUSPENDED transactions to clean up")

        for transaction in stale_transactions:
            try:
                # Atomic compare-and-swap: only update if still SUSPENDED
                rows_affected = await Transaction.filter(
                    id=transaction.id,
                    transaction_status=TransactionStatusEnum.SUSPENDED
                ).update(
                    transaction_status=TransactionStatusEnum.STOPPED,
                    stop_reason="SUSPENDED_TIMEOUT",
                    end_time=datetime.now(timezone.utc),
                )

                if rows_affected == 0:
                    # Another code path already transitioned this transaction
                    logger.debug(f"Transaction {transaction.id} already handled by another path, skipping")
                    continue

                # Refresh from DB after the atomic update
                txn_id = transaction.id
                transaction = await Transaction.filter(id=txn_id).first()
                if not transaction:
                    logger.warning(f"Transaction {txn_id} disappeared after CAS update, skipping")
                    continue

                # Calculate energy from last meter value
                latest_meter_value = await MeterValue.filter(
                    transaction_id=transaction.id
                ).order_by("-created_at").first()

                if latest_meter_value:
                    transaction.end_meter_kwh = latest_meter_value.reading_kwh
                    transaction.energy_consumed_kwh = transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
                    await transaction.save()

                logger.info(f"🛑 Auto-stopped stale SUSPENDED transaction {transaction.id}")

                # Process billing
                if transaction.energy_consumed_kwh is not None and transaction.energy_consumed_kwh > 0:
                    success, message, billing_amount = await WalletService.process_transaction_billing(transaction.id)
                    if success:
                        logger.info(f"💰 Billed stale transaction {transaction.id}: ₹{billing_amount}")
                    else:
                        logger.warning(f"💰 Billing failed for stale transaction {transaction.id}: {message}")

            except Exception as e:
                logger.error(f"Error cleaning up stale SUSPENDED transaction {transaction.id}: {e}", exc_info=True)

    async def cleanup_old_failed_transactions(self, max_age_days: int = 7):
        """
        Clean up very old failed billing transactions that are beyond retry.
        This could be called periodically to prevent table bloat.
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        
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