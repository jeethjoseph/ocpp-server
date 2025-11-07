from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal
from datetime import datetime
import logging

from auth_middleware import require_user
from models import User, Wallet, WalletTransaction, TransactionTypeEnum, PaymentStatusEnum
from services.razorpay_service import razorpay_service
from services.wallet_service import WalletService

logger = logging.getLogger("wallet-payments-router")
router = APIRouter(prefix="/api/wallet", tags=["Wallet Payments"])

# Request/Response Schemas
class CreateRechargeRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to recharge in rupees (must be positive)")

    class Config:
        json_schema_extra = {
            "example": {
                "amount": 500.00
            }
        }

class CreateRechargeResponse(BaseModel):
    order_id: str
    amount: float
    currency: str
    key_id: str
    wallet_transaction_id: int

    class Config:
        json_schema_extra = {
            "example": {
                "order_id": "order_MkT6xGHq8gQp8B",
                "amount": 500.00,
                "currency": "INR",
                "key_id": "rzp_test_1234567890",
                "wallet_transaction_id": 123
            }
        }

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

    class Config:
        json_schema_extra = {
            "example": {
                "razorpay_order_id": "order_MkT6xGHq8gQp8B",
                "razorpay_payment_id": "pay_MkT7FKhJuD9Z8Q",
                "razorpay_signature": "a1b2c3d4e5f6g7h8i9j0"
            }
        }

class VerifyPaymentResponse(BaseModel):
    success: bool
    message: str
    wallet_balance: float
    transaction_id: int

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Payment verified and wallet recharged successfully",
                "wallet_balance": 1500.00,
                "transaction_id": 123
            }
        }

class PaymentStatusResponse(BaseModel):
    transaction_id: int
    amount: float
    status: str
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    created_at: str

    class Config:
        json_schema_extra = {
            "example": {
                "transaction_id": 123,
                "amount": 500.00,
                "status": "COMPLETED",
                "razorpay_order_id": "order_MkT6xGHq8gQp8B",
                "razorpay_payment_id": "pay_MkT7FKhJuD9Z8Q",
                "created_at": "2025-01-15T10:30:00Z"
            }
        }


@router.post("/create-recharge", response_model=CreateRechargeResponse)
async def create_recharge_order(
    request: CreateRechargeRequest,
    current_user: User = Depends(require_user())
):
    """
    Create a Razorpay order for wallet recharge

    Flow:
    1. Validates user has a wallet
    2. Creates Razorpay order
    3. Creates pending wallet transaction
    4. Returns order details for frontend to open Razorpay checkout
    """
    try:
        # Check if Razorpay is configured
        if not razorpay_service.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Payment service is currently unavailable. Please contact support."
            )

        # Get or create user's wallet
        wallet = await Wallet.filter(user=current_user).first()
        if not wallet:
            # Create wallet if it doesn't exist
            wallet = await Wallet.create(user=current_user, balance=Decimal('0.00'))
            logger.info(f"Created wallet for user {current_user.id}")

        # Convert amount to Decimal
        amount = Decimal(str(request.amount))

        # Create receipt ID for tracking
        receipt_id = f"wallet_recharge_{current_user.id}_{int(datetime.utcnow().timestamp())}"

        # Create Razorpay order
        order = razorpay_service.create_order(
            amount=amount,
            currency="INR",
            receipt=receipt_id,
            notes={
                "user_id": current_user.id,
                "user_email": current_user.email,
                "type": "wallet_recharge"
            }
        )

        # Create pending wallet transaction
        wallet_transaction = await WalletTransaction.create(
            wallet=wallet,
            amount=amount,
            type=TransactionTypeEnum.TOP_UP,
            description=f"Wallet recharge - ₹{amount} (Pending)",
            payment_metadata={
                "status": PaymentStatusEnum.PENDING.value,
                "razorpay_order_id": order["id"],
                "razorpay_receipt": receipt_id,
                "amount_in_paise": order["amount"],
                "currency": order["currency"],
                "created_at": order["created_at"]
            }
        )

        logger.info(
            f"Created recharge order for user {current_user.id}: "
            f"Order ID {order['id']}, Amount ₹{amount}, "
            f"Transaction ID {wallet_transaction.id}"
        )

        return CreateRechargeResponse(
            order_id=order["id"],
            amount=float(amount),
            currency="INR",
            key_id=razorpay_service.api_key,
            wallet_transaction_id=wallet_transaction.id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating recharge order for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create recharge order: {str(e)}"
        )


@router.post("/verify-payment", response_model=VerifyPaymentResponse)
async def verify_payment(
    request: VerifyPaymentRequest,
    current_user: User = Depends(require_user())
):
    """
    Verify payment from frontend callback (secondary verification)

    Note: This is a fallback. The webhook is the primary source of truth.
    This endpoint provides immediate feedback to the user.
    """
    try:
        # Verify payment signature
        is_valid = razorpay_service.verify_payment_signature(
            razorpay_order_id=request.razorpay_order_id,
            razorpay_payment_id=request.razorpay_payment_id,
            razorpay_signature=request.razorpay_signature
        )

        if not is_valid:
            logger.warning(
                f"Invalid payment signature from user {current_user.id}: "
                f"Order {request.razorpay_order_id}"
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid payment signature. Payment verification failed."
            )

        # Find the wallet transaction
        # Note: Tortoise ORM doesn't support filtering by JSON field keys directly
        # So we fetch all user's TOP_UP transactions and filter in Python
        wallet_transactions = await WalletTransaction.filter(
            wallet__user=current_user,
            type=TransactionTypeEnum.TOP_UP
        ).all()

        # Filter by order_id in Python
        wallet_transaction = None
        for txn in wallet_transactions:
            if txn.payment_metadata and txn.payment_metadata.get("razorpay_order_id") == request.razorpay_order_id:
                wallet_transaction = txn
                break

        if not wallet_transaction:
            logger.error(
                f"Wallet transaction not found for order {request.razorpay_order_id}, "
                f"user {current_user.id}"
            )
            raise HTTPException(
                status_code=404,
                detail="Transaction not found. Please contact support."
            )

        # Check if already completed (idempotency)
        current_status = wallet_transaction.payment_metadata.get("status")
        if current_status == PaymentStatusEnum.COMPLETED.value:
            logger.info(
                f"Payment already completed for transaction {wallet_transaction.id}, "
                f"returning success"
            )
            wallet = await wallet_transaction.wallet
            return VerifyPaymentResponse(
                success=True,
                message="Payment already verified",
                wallet_balance=float(wallet.balance),
                transaction_id=wallet_transaction.id
            )

        # Process the top-up
        success, message, new_balance = await WalletService.process_wallet_topup(
            wallet_transaction_id=wallet_transaction.id,
            razorpay_payment_id=request.razorpay_payment_id,
            razorpay_signature=request.razorpay_signature
        )

        if success:
            logger.info(
                f"Payment verified successfully for user {current_user.id}: "
                f"Order {request.razorpay_order_id}, "
                f"Amount ₹{wallet_transaction.amount}, "
                f"New balance ₹{new_balance}"
            )

            return VerifyPaymentResponse(
                success=True,
                message=message,
                wallet_balance=float(new_balance),
                transaction_id=wallet_transaction.id
            )
        else:
            logger.error(
                f"Failed to process wallet top-up for user {current_user.id}: {message}"
            )
            raise HTTPException(status_code=500, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error verifying payment for user {current_user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to verify payment. Please contact support if amount was deducted."
        )


@router.get("/payment-status/{transaction_id}", response_model=PaymentStatusResponse)
async def get_payment_status(
    transaction_id: int,
    current_user: User = Depends(require_user())
):
    """
    Get the status of a wallet recharge transaction
    """
    try:
        # Get wallet transaction and verify it belongs to the user
        wallet_transaction = await WalletTransaction.filter(
            id=transaction_id,
            wallet__user=current_user,
            type=TransactionTypeEnum.TOP_UP
        ).first()

        if not wallet_transaction:
            raise HTTPException(
                status_code=404,
                detail="Transaction not found or access denied"
            )

        payment_metadata = wallet_transaction.payment_metadata or {}

        return PaymentStatusResponse(
            transaction_id=wallet_transaction.id,
            amount=float(wallet_transaction.amount),
            status=payment_metadata.get("status", "UNKNOWN"),
            razorpay_order_id=payment_metadata.get("razorpay_order_id"),
            razorpay_payment_id=payment_metadata.get("razorpay_payment_id"),
            created_at=wallet_transaction.created_at.isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting payment status for transaction {transaction_id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve payment status"
        )


@router.get("/recharge-history", response_model=dict)
async def get_recharge_history(
    current_user: User = Depends(require_user())
):
    """
    Get user's wallet recharge history (TOP_UP transactions only)
    """
    try:
        wallet = await Wallet.filter(user=current_user).first()

        if not wallet:
            return {
                "data": [],
                "total": 0
            }

        # Get all TOP_UP transactions
        recharge_transactions = await WalletTransaction.filter(
            wallet=wallet,
            type=TransactionTypeEnum.TOP_UP
        ).order_by('-created_at')

        transaction_data = []
        for txn in recharge_transactions:
            metadata = txn.payment_metadata or {}
            transaction_data.append({
                "id": txn.id,
                "amount": float(txn.amount),
                "status": metadata.get("status", "UNKNOWN"),
                "razorpay_order_id": metadata.get("razorpay_order_id"),
                "razorpay_payment_id": metadata.get("razorpay_payment_id"),
                "description": txn.description,
                "created_at": txn.created_at.isoformat()
            })

        return {
            "data": transaction_data,
            "total": len(transaction_data)
        }

    except Exception as e:
        logger.error(
            f"Error getting recharge history for user {current_user.id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve recharge history"
        )
