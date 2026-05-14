# Wallet service for handling billing and wallet transactions
import asyncio
import time
from utils import safe_create_task
from crud import log_audit_event
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple
from tortoise.transactions import atomic, in_transaction
import logging

from models import (
    Wallet, WalletTransaction, Transaction, Tariff, User,
    TransactionTypeEnum, TransactionStatusEnum, PaymentStatusEnum
)
from services.monitoring_service import trace_function, MetricsCollector, SentryHelper, OCPPMetrics
from redis_manager import redis_manager
from tortoise import Tortoise

logger = logging.getLogger(__name__)

# Canonical SQL for deriving a wallet balance from the wallet_transaction
# log. Only TOP_UP rows whose payment_metadata.status is COMPLETED
# contribute — PENDING and FAILED Razorpay orders must not be credited
# until the webhook flips them to COMPLETED. CHARGE_DEDUCT rows have no
# status field and are always final at write time, so they contribute
# unconditionally. Tortoise 0.25 doesn't expose JSONField `->>` traversal
# as a filter lookup, so this stays as raw SQL.
#
# Two other sites must stay aligned with this formula:
#   - `scripts/reconcile_wallet_balance.py:_DERIVATION_SQL` — read-only
#     diagnostic that compares legacy stored balance against this derivation.
#   - `migrations/models/33_*_wallet_ledger_migration.py` — the SUM inside
#     step 2 (drift-correction adjustment row inserts).
# If you change the COMPLETED-TOP_UP filter or the sign convention, update
# all three. (Migration text is frozen once shipped; only future
# migrations would need to mirror an evolved formula.)
_BALANCE_SQL = """
    SELECT COALESCE(
        SUM(
            CASE
                WHEN type = 'TOP_UP' AND payment_metadata->>'status' = 'COMPLETED'
                    THEN amount
                WHEN type = 'CHARGE_DEDUCT'
                    THEN -amount
                ELSE 0
            END
        ),
        0
    )::numeric AS balance
    FROM wallet_transaction
    WHERE wallet_id = $1
"""


class WalletService:
    """Service for handling wallet operations with proper locking and transactions"""

    @staticmethod
    async def get_balance(wallet_id: int) -> Decimal:
        """Return a wallet's current balance derived from the wallet_transaction log.

        Balance is `SUM(amount)` over COMPLETED TOP_UP rows minus
        `SUM(amount)` over CHARGE_DEDUCT rows. PENDING / FAILED TOP_UPs
        (Razorpay orders that haven't been confirmed by webhook) are
        excluded so unpaid recharges never credit the wallet.

        `Tortoise.get_connection("default")` resolves through a ContextVar
        bound to the current asyncio task, so a query issued from inside
        an `@atomic()` block or an `async with in_transaction()` body runs
        on the transaction's connection and sees that block's uncommitted
        writes. Verified by `test_get_balance_sees_uncommitted_writes`.

        A Redis cache shields the hot read path (/users/me); invalidated
        post-commit by every WalletTransaction write via the outer
        process_* wrappers.

        If `balance < 0`, log a warning and emit a metric. Engineering
        needs to see this because it means either the in-session budget
        cap failed to fire (WalletSessionService) or this is a historical
        session from before the cap was deployed. Display layers may
        clamp at zero; the source-of-truth read is exact.
        """
        cached = await redis_manager.get_wallet_balance(wallet_id)
        if cached is not None:
            MetricsCollector.increment_counter("Custom/Wallet/BalanceCacheHit")
            return Decimal(cached) / Decimal("100")

        MetricsCollector.increment_counter("Custom/Wallet/BalanceCacheMiss")
        conn = Tortoise.get_connection("default")
        _, rows = await conn.execute_query(_BALANCE_SQL, [wallet_id])
        balance = Decimal(rows[0]["balance"]).quantize(Decimal("0.01"))

        if balance < 0:
            logger.warning(
                f"Negative derived balance for wallet {wallet_id}: ₹{balance}. "
                "Indicates an unenforced budget cap or a pre-budget-cap historical session."
            )
            MetricsCollector.increment_counter("Custom/Wallet/NegativeBalance")

        await redis_manager.set_wallet_balance(wallet_id, int(balance * 100))
        return balance

    @staticmethod
    async def _invalidate_balance_cache(wallet_id: int) -> None:
        """Invalidate Redis after any wallet_transaction write."""
        await redis_manager.invalidate_wallet_balance(wallet_id)
        MetricsCollector.increment_counter("Custom/Wallet/BalanceCacheInvalidated")

    @staticmethod
    async def get_applicable_tariff(charger_id: int) -> Optional[Tariff]:
        """
        Get the applicable tariff for a charger.
        Priority: Charger-specific tariff -> Global tariff -> None
        Returns the full Tariff object (rate_per_kwh + gst_percent).
        """
        charger_tariff = await Tariff.filter(charger_id=charger_id).first()
        if charger_tariff:
            logger.info(f"Using charger-specific tariff: ₹{charger_tariff.rate_per_kwh}/kWh (GST {charger_tariff.gst_percent}%) for charger {charger_id}")
            return charger_tariff

        global_tariff = await Tariff.filter(is_global=True).first()
        if global_tariff:
            logger.info(f"Using global tariff: ₹{global_tariff.rate_per_kwh}/kWh (GST {global_tariff.gst_percent}%) for charger {charger_id}")
            return global_tariff

        logger.warning(f"No tariff found for charger {charger_id}")
        return None
    
    @staticmethod
    def calculate_billing_amount(
        energy_consumed_kwh: float, rate_per_kwh: Decimal, gst_percent: Decimal
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Calculate billing with GST added on top of tariff.
        Returns: (energy_charge, gst_amount, total_billed)
        """
        if energy_consumed_kwh <= 0:
            return Decimal('0.00'), Decimal('0.00'), Decimal('0.00')

        energy_decimal = Decimal(str(energy_consumed_kwh))

        energy_charge = (energy_decimal * rate_per_kwh).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        gst_amount = (energy_charge * gst_percent / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        total_billed = energy_charge + gst_amount

        logger.info(
            f"Calculated billing: {energy_consumed_kwh} kWh × ₹{rate_per_kwh}/kWh = ₹{energy_charge} "
            f"+ GST {gst_percent}% ₹{gst_amount} = ₹{total_billed}"
        )
        return energy_charge, gst_amount, total_billed
    
    @staticmethod
    async def process_transaction_billing(transaction_id: int) -> Tuple[bool, str, Optional[Decimal]]:
        """Bill a completed charging transaction.

        Thin wrapper around `_do_transaction_billing` that invalidates the
        balance cache *after* the outer transaction commits. Doing the
        invalidation inside the transaction races with concurrent readers:
        a reader that arrives between the invalidation and the commit
        repopulates the cache with stale pre-commit data, which then sticks
        until the TTL elapses.

        Returns: (success: bool, message: str, amount: Optional[Decimal])
        """
        success, msg, amount, wallet_id = await WalletService._do_transaction_billing(
            transaction_id
        )
        if success and wallet_id is not None:
            await WalletService._invalidate_balance_cache(wallet_id)
        return success, msg, amount

    @staticmethod
    @atomic()
    @trace_function(name="WalletService._do_transaction_billing")
    async def _do_transaction_billing(transaction_id: int) -> Tuple[bool, str, Optional[Decimal], Optional[int]]:
        """Inner — does all the DB work in one transaction. Returns a 4-tuple
        whose last element is the wallet_id when a new CHARGE_DEDUCT row was
        written (signal for the wrapper to invalidate the cache), or None
        for every no-op / error path."""
        try:
            # Set Sentry context
            SentryHelper.set_context("billing", {"transaction_id": transaction_id})

            # Get transaction with lock
            transaction = await Transaction.filter(id=transaction_id).select_for_update().first()
            if not transaction:
                return False, f"Transaction {transaction_id} not found", None, None

            # Skip wallet billing for QR payment sessions
            from models import QRPayment
            qr_payment = await QRPayment.filter(transaction_id=transaction_id).first()
            if qr_payment:
                logger.info(f"Transaction {transaction_id} is a QR payment session, skipping wallet billing")
                return True, "QR payment session - billed via QR payment flow", Decimal('0.00'), None

            # Idempotency guard: skip if already billed (prevents double billing
            # when BootNotification and StopTransaction both trigger billing)
            existing_charge = await WalletTransaction.filter(
                charging_transaction_id=transaction_id,
                type=TransactionTypeEnum.CHARGE_DEDUCT
            ).first()
            if existing_charge:
                logger.info(f"Transaction {transaction_id} already billed (wallet_txn={existing_charge.id}), skipping")
                return True, f"Already billed ₹{abs(existing_charge.amount)}", abs(existing_charge.amount), None

            # Validate transaction state
            if not transaction.energy_consumed_kwh or transaction.energy_consumed_kwh <= 0:
                logger.info(f"Transaction {transaction_id} has no energy consumption, skipping billing")
                return True, "No energy consumed - no billing required", Decimal('0.00'), None
            
            # Get applicable tariff
            tariff = await WalletService.get_applicable_tariff(transaction.charger_id)
            if not tariff:
                await Transaction.filter(id=transaction_id).update(
                    transaction_status=TransactionStatusEnum.BILLING_FAILED
                )
                safe_create_task(log_audit_event(
                    action="transaction.status_changed",
                    entity_type="transaction",
                    entity_id=transaction_id,
                    actor_type="system",
                    changes={"new_status": "BILLING_FAILED", "trigger": "BillingFailed", "reason": "No tariff configuration found"},
                ))
                safe_create_task(OCPPMetrics.record_billing_failed(transaction_id, "no_tariff"))
                return False, "No tariff configuration found", None, None

            tariff_rate = tariff.rate_per_kwh
            gst_percent = tariff.gst_percent

            # Calculate billing amount with GST
            energy_charge, gst_amount, billing_amount = WalletService.calculate_billing_amount(
                transaction.energy_consumed_kwh,
                tariff_rate,
                gst_percent,
            )

            if billing_amount <= 0:
                logger.info(f"Transaction {transaction_id} calculated amount is ₹0, skipping wallet deduction")
                return True, "Zero amount - no billing required", Decimal('0.00'), None

            # Get user's wallet with lock — locking the wallet row still
            # serialises concurrent billings for this user even though
            # `balance` is no longer stored on it.
            wallet = await Wallet.filter(user_id=transaction.user_id).select_for_update().first()
            if not wallet:
                await Transaction.filter(id=transaction_id).update(
                    transaction_status=TransactionStatusEnum.BILLING_FAILED
                )
                safe_create_task(log_audit_event(
                    action="transaction.status_changed",
                    entity_type="transaction",
                    entity_id=transaction_id,
                    actor_type="system",
                    changes={"new_status": "BILLING_FAILED", "trigger": "BillingFailed", "reason": f"Wallet not found for user {transaction.user_id}"},
                ))
                safe_create_task(OCPPMetrics.record_billing_failed(transaction_id, "no_wallet"))
                return False, f"Wallet not found for user {transaction.user_id}", None, None

            # Balance is derived from the wallet_transaction log; no stored
            # column. The CHARGE_DEDUCT insert IS the deduction. Read the
            # pre-balance for the metadata snapshot via the ledger helper.
            current_balance = await WalletService.get_balance(wallet.id)
            new_balance = current_balance - billing_amount

            logger.info(f"Wallet billing: ₹{current_balance} - ₹{billing_amount} = ₹{new_balance}")

            # The in_transaction() savepoint still bundles the deduction
            # insert with the Transaction billing-breakdown update below,
            # so a failure on the breakdown rolls back the deduction too.
            # Cache invalidation lives in the outer wrapper so it runs
            # AFTER commit and a concurrent reader can't repopulate stale
            # data between the invalidation and the commit point.
            async with in_transaction():
                await WalletTransaction.create(
                    wallet=wallet,
                    amount=billing_amount,  # Positive; direction carried by type=CHARGE_DEDUCT
                    type=TransactionTypeEnum.CHARGE_DEDUCT,
                    description=f"Charging session - {transaction.energy_consumed_kwh:.2f} kWh @ ₹{tariff_rate}/kWh + GST {gst_percent}%",
                    charging_transaction=transaction,
                    payment_metadata={
                        "energy_consumed_kwh": float(transaction.energy_consumed_kwh),
                        "rate_per_kwh": float(tariff_rate),
                        "energy_charge": float(energy_charge),
                        "gst_percent": float(gst_percent),
                        "gst_amount": float(gst_amount),
                        "total_billed": float(billing_amount),
                        "previous_balance": float(current_balance),
                        "new_balance": float(new_balance)
                    }
                )

                # Store billing breakdown on transaction — inside savepoint so it
                # rolls back atomically with the wallet deduction if anything fails.
                await Transaction.filter(id=transaction_id).update(
                    energy_charge=energy_charge,
                    gst_amount=gst_amount,
                    gst_rate_percent=gst_percent,
                    total_billed=billing_amount,
                )

            # Record billing success metrics
            MetricsCollector.record_metric("Custom/Billing/Amount", float(billing_amount))
            MetricsCollector.increment_counter("Custom/Billing/Success")

            logger.info(f"✅ Successfully billed transaction {transaction_id}: ₹{billing_amount}")
            return True, f"Successfully billed ₹{billing_amount}", billing_amount, wallet.id

        except Exception as e:
            logger.error(f"❌ Error processing billing for transaction {transaction_id}: {e}", exc_info=True)

            # Record billing failure metrics
            MetricsCollector.increment_counter("Custom/Billing/Failed")
            safe_create_task(OCPPMetrics.record_billing_failed(transaction_id, type(e).__name__))
            SentryHelper.capture_exception(e, extra={"transaction_id": transaction_id})

            # Mark transaction as billing failed
            try:
                await Transaction.filter(id=transaction_id).update(
                    transaction_status=TransactionStatusEnum.BILLING_FAILED
                )
                safe_create_task(log_audit_event(
                    action="transaction.status_changed",
                    entity_type="transaction",
                    entity_id=transaction_id,
                    actor_type="system",
                    changes={"new_status": "BILLING_FAILED", "trigger": "BillingFailed", "reason": str(e)},
                ))
            except Exception as update_error:
                logger.error(f"Failed to update transaction status: {update_error}")

            return False, f"Billing failed: {str(e)}", None, None

    @staticmethod
    async def retry_failed_billing(transaction_id: int) -> Tuple[bool, str, Optional[Decimal]]:
        """
        Retry billing for a transaction marked as BILLING_FAILED.
        This can be called by periodic jobs.
        """
        logger.info(f"🔄 Retrying billing for transaction {transaction_id}")
        
        # Verify transaction is in BILLING_FAILED state
        transaction = await Transaction.filter(id=transaction_id).first()
        if not transaction:
            return False, "Transaction not found", None
            
        if transaction.transaction_status != TransactionStatusEnum.BILLING_FAILED:
            return False, f"Transaction status is {transaction.transaction_status}, not BILLING_FAILED", None
        
        # Process billing
        success, message, amount = await WalletService.process_transaction_billing(transaction_id)
        
        if success:
            # Update transaction status back to COMPLETED
            await Transaction.filter(id=transaction_id).update(
                transaction_status=TransactionStatusEnum.COMPLETED
            )
            safe_create_task(log_audit_event(
                action="transaction.status_changed",
                entity_type="transaction",
                entity_id=transaction_id,
                actor_type="system",
                changes={"previous_status": "BILLING_FAILED", "new_status": "COMPLETED", "trigger": "BillingRetry"},
            ))
            logger.info(f"✅ Retry successful for transaction {transaction_id}")
        else:
            logger.warning(f"🔄 Retry failed for transaction {transaction_id}: {message}")
        
        return success, message, amount
    
    @staticmethod
    async def get_failed_billing_transactions() -> list:
        """
        Get all transactions with BILLING_FAILED status for periodic retry jobs.
        """
        failed_transactions = await Transaction.filter(
            transaction_status=TransactionStatusEnum.BILLING_FAILED
        ).all()

        return [{"id": t.id, "user_id": t.user_id, "energy_kwh": t.energy_consumed_kwh} for t in failed_transactions]

    @staticmethod
    async def process_wallet_topup(
        wallet_transaction_id: int,
        razorpay_payment_id: str,
        razorpay_signature: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Decimal]]:
        """Process wallet top-up after payment verification.

        Thin wrapper around `_do_wallet_topup` that invalidates the balance
        cache *after* the outer transaction commits — see the matching note
        on `process_transaction_billing` for why the post-commit ordering
        matters.

        Returns: (success: bool, message: str, new_balance: Optional[Decimal])
        """
        success, msg, new_balance, wallet_id = await WalletService._do_wallet_topup(
            wallet_transaction_id, razorpay_payment_id, razorpay_signature
        )
        if success and wallet_id is not None:
            await WalletService._invalidate_balance_cache(wallet_id)
        return success, msg, new_balance

    @staticmethod
    @atomic()
    @trace_function(name="WalletService._do_wallet_topup")
    async def _do_wallet_topup(
        wallet_transaction_id: int,
        razorpay_payment_id: str,
        razorpay_signature: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Decimal], Optional[int]]:
        """Inner — flips a PENDING WalletTransaction to COMPLETED inside one
        transaction. Returns a 4-tuple whose last element is wallet_id when
        a row was actually flipped (cache invalidation needed), or None on
        idempotent / error paths."""
        try:
            # Set Sentry context
            SentryHelper.set_context("wallet_topup", {
                "wallet_transaction_id": wallet_transaction_id,
                "razorpay_payment_id": razorpay_payment_id
            })
            # Get wallet transaction with lock
            wallet_txn = await WalletTransaction.filter(
                id=wallet_transaction_id
            ).select_for_update().first()

            if not wallet_txn:
                return False, f"Wallet transaction {wallet_transaction_id} not found", None, None

            # Check if already completed (idempotency)
            current_status = wallet_txn.payment_metadata.get("status")
            if current_status == PaymentStatusEnum.COMPLETED.value:
                wallet = await wallet_txn.wallet
                logger.info(f"Wallet transaction {wallet_transaction_id} already completed, returning current balance")
                # No state change → no cache invalidation needed.
                return True, "Payment already processed", await WalletService.get_balance(wallet.id), None

            # Get wallet with lock — balance is derived; the lock still
            # serialises concurrent top-ups on the same wallet.
            wallet = await Wallet.filter(id=wallet_txn.wallet_id).select_for_update().first()
            if not wallet:
                return False, "Wallet not found", None, None

            # The PENDING wallet_transaction row created at recharge-init
            # time becomes COMPLETED here and then contributes its amount
            # to the derived balance.
            current_balance = await WalletService.get_balance(wallet.id)
            top_up_amount = wallet_txn.amount
            new_balance = current_balance + top_up_amount

            logger.info(
                f"Processing wallet top-up: "
                f"Transaction {wallet_transaction_id}, "
                f"₹{current_balance} + ₹{top_up_amount} = ₹{new_balance}"
            )

            # Savepoint bundles the metadata update so a failure rolls back
            # the status flip and keeps the row PENDING for retry. Cache
            # invalidation runs in the outer wrapper after commit.
            async with in_transaction():
                updated_metadata = wallet_txn.payment_metadata or {}
                updated_metadata.update({
                    "status": PaymentStatusEnum.COMPLETED.value,
                    "razorpay_payment_id": razorpay_payment_id,
                    "razorpay_signature": razorpay_signature,
                    "completed_at": int(time.time()),
                    "previous_balance": float(current_balance),
                    "new_balance": float(new_balance)
                })

                await WalletTransaction.filter(id=wallet_transaction_id).update(
                    description=f"Wallet recharge - ₹{top_up_amount} (Completed)",
                    payment_metadata=updated_metadata
                )

            # Record topup success metrics
            MetricsCollector.record_metric("Custom/Wallet/TopupAmount", float(top_up_amount))
            MetricsCollector.increment_counter("Custom/Wallet/TopupSuccess")

            logger.info(
                f"✅ Successfully processed wallet top-up: "
                f"Transaction {wallet_transaction_id}, "
                f"Amount ₹{top_up_amount}, "
                f"New balance ₹{new_balance}"
            )

            return True, f"Successfully added ₹{top_up_amount} to wallet", new_balance, wallet.id

        except Exception as e:
            logger.error(
                f"❌ Error processing wallet top-up for transaction {wallet_transaction_id}: {e}",
                exc_info=True
            )

            # Record topup failure metrics
            MetricsCollector.increment_counter("Custom/Wallet/TopupFailed")
            SentryHelper.capture_exception(e, extra={"wallet_transaction_id": wallet_transaction_id})

            # Mark transaction as failed
            try:
                wallet_txn = await WalletTransaction.get(id=wallet_transaction_id)
                updated_metadata = wallet_txn.payment_metadata or {}
                updated_metadata["status"] = PaymentStatusEnum.FAILED.value
                updated_metadata["error"] = str(e)
                await WalletTransaction.filter(id=wallet_transaction_id).update(
                    description=f"Wallet recharge - ₹{wallet_txn.amount} (Failed)",
                    payment_metadata=updated_metadata
                )
            except Exception as update_error:
                logger.error(f"Failed to update transaction status: {update_error}")

            return False, f"Top-up failed: {str(e)}", None, None