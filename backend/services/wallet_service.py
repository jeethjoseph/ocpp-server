# Wallet service for handling billing and wallet transactions
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple
from tortoise.transactions import atomic
import logging

from models import (
    Wallet, WalletTransaction, Transaction, Tariff, User,
    TransactionTypeEnum, TransactionStatusEnum, PaymentStatusEnum
)

logger = logging.getLogger(__name__)

class WalletService:
    """Service for handling wallet operations with proper locking and transactions"""
    
    @staticmethod
    async def get_applicable_tariff(charger_id: int) -> Optional[Decimal]:
        """
        Get the applicable tariff rate for a charger.
        Priority: Charger-specific tariff -> Global tariff -> None
        """
        # First try to get charger-specific tariff
        charger_tariff = await Tariff.filter(charger_id=charger_id).first()
        if charger_tariff:
            logger.info(f"Using charger-specific tariff: ₹{charger_tariff.rate_per_kwh}/kWh for charger {charger_id}")
            return charger_tariff.rate_per_kwh
        
        # Fallback to global tariff
        global_tariff = await Tariff.filter(is_global=True).first()
        if global_tariff:
            logger.info(f"Using global tariff: ₹{global_tariff.rate_per_kwh}/kWh for charger {charger_id}")
            return global_tariff.rate_per_kwh
        
        logger.warning(f"No tariff found for charger {charger_id}")
        return None
    
    @staticmethod
    def calculate_billing_amount(energy_consumed_kwh: float, rate_per_kwh: Decimal) -> Decimal:
        """
        Calculate the billing amount with proper rounding to 2 decimal places.
        """
        if energy_consumed_kwh <= 0:
            return Decimal('0.00')
        
        # Convert to Decimal for precise calculation
        energy_decimal = Decimal(str(energy_consumed_kwh))
        
        # Calculate amount and round to 2 decimal places
        amount = (energy_decimal * rate_per_kwh).quantize(
            Decimal('0.01'), 
            rounding=ROUND_HALF_UP
        )
        
        logger.info(f"Calculated billing: {energy_consumed_kwh} kWh × ₹{rate_per_kwh}/kWh = ₹{amount}")
        return amount
    
    @staticmethod
    @atomic()
    async def process_transaction_billing(transaction_id: int) -> Tuple[bool, str, Optional[Decimal]]:
        """
        Process billing for a completed charging transaction.
        
        Returns:
            (success: bool, message: str, amount: Optional[Decimal])
        """
        try:
            # Get transaction with lock
            transaction = await Transaction.filter(id=transaction_id).select_for_update().first()
            if not transaction:
                return False, f"Transaction {transaction_id} not found", None
            
            # Validate transaction state
            if not transaction.energy_consumed_kwh or transaction.energy_consumed_kwh <= 0:
                logger.info(f"Transaction {transaction_id} has no energy consumption, skipping billing")
                return True, "No energy consumed - no billing required", Decimal('0.00')
            
            # Get applicable tariff
            tariff_rate = await WalletService.get_applicable_tariff(transaction.charger_id)
            if not tariff_rate:
                await Transaction.filter(id=transaction_id).update(
                    transaction_status=TransactionStatusEnum.BILLING_FAILED
                )
                return False, "No tariff configuration found", None
            
            # Calculate billing amount
            billing_amount = WalletService.calculate_billing_amount(
                transaction.energy_consumed_kwh, 
                tariff_rate
            )
            
            if billing_amount <= 0:
                logger.info(f"Transaction {transaction_id} calculated amount is ₹0, skipping wallet deduction")
                return True, "Zero amount - no billing required", Decimal('0.00')
            
            # Get user's wallet with lock
            wallet = await Wallet.filter(user_id=transaction.user_id).select_for_update().first()
            if not wallet:
                await Transaction.filter(id=transaction_id).update(
                    transaction_status=TransactionStatusEnum.BILLING_FAILED
                )
                return False, f"Wallet not found for user {transaction.user_id}", None
            
            # Get current balance (allowing None)
            current_balance = wallet.balance or Decimal('0.00')
            new_balance = current_balance - billing_amount
            
            logger.info(f"Wallet billing: ₹{current_balance} - ₹{billing_amount} = ₹{new_balance}")
            
            # Update wallet balance (allowing negative)
            await Wallet.filter(id=wallet.id).update(balance=new_balance)
            
            # Create wallet transaction record
            wallet_transaction = await WalletTransaction.create(
                wallet=wallet,
                amount=-billing_amount,  # Negative for deduction
                type=TransactionTypeEnum.CHARGE_DEDUCT,
                description=f"Charging session - {transaction.energy_consumed_kwh:.2f} kWh @ ₹{tariff_rate}/kWh",
                charging_transaction=transaction,
                payment_metadata={
                    "energy_consumed_kwh": transaction.energy_consumed_kwh,
                    "rate_per_kwh": float(tariff_rate),
                    "calculated_amount": float(billing_amount),
                    "previous_balance": float(current_balance),
                    "new_balance": float(new_balance)
                }
            )
            
            logger.info(f"✅ Successfully billed transaction {transaction_id}: ₹{billing_amount}")
            return True, f"Successfully billed ₹{billing_amount}", billing_amount
                
        except Exception as e:
            logger.error(f"❌ Error processing billing for transaction {transaction_id}: {e}", exc_info=True)
            
            # Mark transaction as billing failed
            try:
                await Transaction.filter(id=transaction_id).update(
                    transaction_status=TransactionStatusEnum.BILLING_FAILED
                )
            except Exception as update_error:
                logger.error(f"Failed to update transaction status: {update_error}")
            
            return False, f"Billing failed: {str(e)}", None
    
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
    @atomic()
    async def process_wallet_topup(
        wallet_transaction_id: int,
        razorpay_payment_id: str,
        razorpay_signature: str
    ) -> Tuple[bool, str, Optional[Decimal]]:
        """
        Process wallet top-up after payment verification

        Args:
            wallet_transaction_id: ID of the pending wallet transaction
            razorpay_payment_id: Payment ID from Razorpay
            razorpay_signature: Signature from Razorpay

        Returns:
            (success: bool, message: str, new_balance: Optional[Decimal])
        """
        try:
            # Get wallet transaction with lock
            wallet_txn = await WalletTransaction.filter(
                id=wallet_transaction_id
            ).select_for_update().first()

            if not wallet_txn:
                return False, f"Wallet transaction {wallet_transaction_id} not found", None

            # Check if already completed (idempotency)
            current_status = wallet_txn.payment_metadata.get("status")
            if current_status == PaymentStatusEnum.COMPLETED.value:
                wallet = await wallet_txn.wallet
                logger.info(f"Wallet transaction {wallet_transaction_id} already completed, returning current balance")
                return True, "Payment already processed", wallet.balance

            # Get wallet with lock
            wallet = await Wallet.filter(id=wallet_txn.wallet_id).select_for_update().first()
            if not wallet:
                return False, "Wallet not found", None

            # Get current balance (allowing None)
            current_balance = wallet.balance or Decimal('0.00')
            top_up_amount = wallet_txn.amount
            new_balance = current_balance + top_up_amount

            logger.info(
                f"Processing wallet top-up: "
                f"Transaction {wallet_transaction_id}, "
                f"₹{current_balance} + ₹{top_up_amount} = ₹{new_balance}"
            )

            # Update wallet balance
            await Wallet.filter(id=wallet.id).update(balance=new_balance)

            # Update wallet transaction metadata
            updated_metadata = wallet_txn.payment_metadata or {}
            updated_metadata.update({
                "status": PaymentStatusEnum.COMPLETED.value,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature,
                "completed_at": int(__import__('time').time()),
                "previous_balance": float(current_balance),
                "new_balance": float(new_balance)
            })

            await WalletTransaction.filter(id=wallet_transaction_id).update(
                description=f"Wallet recharge - ₹{top_up_amount} (Completed)",
                payment_metadata=updated_metadata
            )

            logger.info(
                f"✅ Successfully processed wallet top-up: "
                f"Transaction {wallet_transaction_id}, "
                f"Amount ₹{top_up_amount}, "
                f"New balance ₹{new_balance}"
            )

            return True, f"Successfully added ₹{top_up_amount} to wallet", new_balance

        except Exception as e:
            logger.error(
                f"❌ Error processing wallet top-up for transaction {wallet_transaction_id}: {e}",
                exc_info=True
            )

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

            return False, f"Top-up failed: {str(e)}", None