import time

from fastapi import APIRouter, HTTPException, Request, Header
from svix import Webhook
from models import User, UserRoleEnum, Wallet, WalletTransaction, PaymentStatusEnum, TransactionTypeEnum
from tortoise.expressions import Q
import logging
import json
import os
from clerk_backend_api import Clerk
from services.razorpay_service import razorpay_service, extract_fee_from_payment
from services.wallet_service import WalletService
from crud import log_webhook_event
from models import WebhookSourceEnum

logger = logging.getLogger("webhooks")
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


async def _find_txn_by_order_id(order_id: str):
    """Find a TOP_UP WalletTransaction by indexed razorpay_order_id column.

    Falls back to JSON scan for rows created before the column was backfilled.
    """
    txn = await WalletTransaction.filter(
        type=TransactionTypeEnum.TOP_UP,
        razorpay_order_id=order_id,
    ).first()
    if txn:
        return txn

    recent_txns = await WalletTransaction.filter(
        type=TransactionTypeEnum.TOP_UP,
        razorpay_order_id__isnull=True,
    ).order_by("-created_at").limit(200)
    for candidate in recent_txns:
        if candidate.payment_metadata and candidate.payment_metadata.get("razorpay_order_id") == order_id:
            return candidate
    return None


CLERK_WEBHOOK_SECRET = os.getenv("CLERK_WEBHOOK_SECRET")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")

if not CLERK_WEBHOOK_SECRET:
    raise ValueError("CLERK_WEBHOOK_SECRET must be set in environment variables")
if not CLERK_SECRET_KEY:
    raise ValueError("CLERK_SECRET_KEY must be set in environment variables")

# Initialize Clerk client
clerk_client = Clerk(bearer_auth=CLERK_SECRET_KEY)

@router.post("/clerk")
async def handle_clerk_webhook(
    request: Request,
    svix_id: str = Header(None, alias="svix-id"),
    svix_timestamp: str = Header(None, alias="svix-timestamp"),
    svix_signature: str = Header(None, alias="svix-signature"),
):
    """Handle Clerk webhook events for user synchronization"""
    try:
        # Get the request body
        body = await request.body()
        
        # Verify the webhook signature
        wh = Webhook(CLERK_WEBHOOK_SECRET)
        try:
            payload = wh.verify(body, {
                "svix-id": svix_id,
                "svix-timestamp": svix_timestamp,
                "svix-signature": svix_signature,
            })
        except Exception as e:
            logger.error(f"Webhook verification failed: {str(e)}")
            raise HTTPException(status_code=400, detail="Webhook verification failed")
        
        # Parse the payload
        event_type = payload.get("type")
        data = payload.get("data", {})
        
        logger.info(f"Received Clerk webhook: {event_type} for user {data.get('id', 'unknown')}")
        
        if event_type == "user.created":
            await handle_user_created(data)
        elif event_type == "user.updated":
            await handle_user_updated(data)
        elif event_type == "user.deleted":
            await handle_user_deleted(data)
        else:
            logger.info(f"Unhandled webhook event type: {event_type}")
        
        return {"status": "success"}
        
    except Exception as e:
        # Return 200 so Svix does not retry on application errors.
        logger.error(f"Webhook processing error: {str(e)}")
        return {"status": "error_handled"}

async def handle_user_created(data: dict):
    """Handle user.created webhook event"""
    try:
        clerk_user_id = data.get("id")
        email_addresses = data.get("email_addresses", [])
        
        # Get primary email
        primary_email = None
        for email in email_addresses:
            if email.get("id") == data.get("primary_email_address_id"):
                primary_email = email.get("email_address")
                break
        
        if not primary_email and email_addresses:
            primary_email = email_addresses[0].get("email_address")
        
        if not clerk_user_id or not primary_email:
            logger.error("Missing required user data in webhook payload")
            return
        
        # Extract user metadata
        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip() or primary_email.split("@")[0]
        
        # Get role from public metadata, default to USER if not set
        public_metadata = data.get("public_metadata", {})
        role = public_metadata.get("role", "USER")
        
        # Validate role
        try:
            user_role = UserRoleEnum(role)
        except ValueError:
            logger.warning(f"Invalid role '{role}' for user {clerk_user_id}, defaulting to USER")
            user_role = UserRoleEnum.USER
        
        logger.info(f"Creating user {primary_email} with role: {user_role.value}")
        
        # Check if user already exists
        existing_user = await User.filter(
            Q(clerk_user_id=clerk_user_id) | Q(email=primary_email)
        ).first()
        
        if existing_user:
            # Update existing user with Clerk ID if missing
            if not existing_user.clerk_user_id:
                existing_user.clerk_user_id = clerk_user_id
                await existing_user.save()
                logger.info(f"Updated existing user {primary_email} with Clerk ID")
            elif existing_user.clerk_user_id != clerk_user_id:
                logger.error(
                    f"Clerk ID mismatch for {primary_email}: "
                    f"existing DB user (ID={existing_user.id}) has a different Clerk account. "
                    f"User record NOT updated. Manually resolve this conflict."
                )
                return

            # Self-heal role drift: the frontend middleware routes on Clerk
            # public_metadata.role, so if our authoritative DB role
            # disagrees with what Clerk holds (e.g. a franchisee signed up
            # without an invitation, or an invitation's metadata got
            # stripped), push the DB role back to Clerk. USER is the
            # default and safe to skip to avoid needless API calls.
            db_role = existing_user.role.value if hasattr(existing_user.role, "value") else str(existing_user.role)
            clerk_role = public_metadata.get("role")
            if db_role != "USER" and db_role != clerk_role:
                from services.clerk_invitation_service import push_role_to_clerk
                try:
                    await push_role_to_clerk(clerk_user_id, db_role)
                except Exception:
                    logger.exception(
                        "Role sync to Clerk failed for %s — will retry on next login.",
                        primary_email,
                    )
            return
        
        # Generate unique RFID/ID tag for OCPP
        import uuid
        rfid_card_id = str(uuid.uuid4()).replace('-', '')[:20]  # 20 char limit for OCPP
        
        # Create new user
        user = await User.create(
            clerk_user_id=clerk_user_id,
            email=primary_email,
            full_name=full_name,
            phone_number=data.get("phone_numbers", [{}])[0].get("phone_number") if data.get("phone_numbers") else None,
            role=user_role,
            is_email_verified=True,  # Clerk handles verification
            auth_provider="CLERK",
            is_active=True,
            preferred_language="en",
            notification_preferences="{}",
            rfid_card_id=rfid_card_id
        )
        
        # Create wallet for user
        await Wallet.create(user=user, balance=0.00)
        
        logger.info(f"Created new user {primary_email} from Clerk webhook")

        await log_webhook_event(
            source=WebhookSourceEnum.CLERK,
            event_type="user.created",
            event_id=clerk_user_id,
            payload=data,
            status="processed",
        )

    except Exception as e:
        logger.error(f"Error handling user.created webhook: {str(e)}")
        await log_webhook_event(
            source=WebhookSourceEnum.CLERK,
            event_type="user.created",
            event_id=data.get("id"),
            payload=data,
            status="failed",
            error_message=str(e),
        )
        raise

async def handle_user_updated(data: dict):
    """Handle user.updated webhook event"""
    try:
        clerk_user_id = data.get("id")
        if not clerk_user_id:
            logger.error("Missing user ID in webhook payload")
            return
        
        user = await User.filter(clerk_user_id=clerk_user_id).first()
        if not user:
            logger.warning(f"User with Clerk ID {clerk_user_id} not found for update")
            return
        
        # Update user data
        email_addresses = data.get("email_addresses", [])
        if email_addresses:
            for email in email_addresses:
                if email.get("id") == data.get("primary_email_address_id"):
                    user.email = email.get("email_address")
                    break
        
        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        if first_name or last_name:
            user.full_name = f"{first_name} {last_name}".strip()
        
        phone_numbers = data.get("phone_numbers", [])
        if phone_numbers:
            user.phone_number = phone_numbers[0].get("phone_number")
        
        # Update role from public metadata
        public_metadata = data.get("public_metadata", {})
        if "role" in public_metadata:
            role = public_metadata.get("role", "USER")
            try:
                user_role = UserRoleEnum(role)
                user.role = user_role
                logger.info(f"Updated role for user {user.email} to {role}")
            except ValueError:
                logger.warning(f"Invalid role '{role}' for user {clerk_user_id}, keeping current role")
        
        await user.save()
        logger.info(f"Updated user {user.email} from Clerk webhook")

        await log_webhook_event(
            source=WebhookSourceEnum.CLERK,
            event_type="user.updated",
            event_id=clerk_user_id,
            payload=data,
            status="processed",
        )

    except Exception as e:
        logger.error(f"Error handling user.updated webhook: {str(e)}")
        await log_webhook_event(
            source=WebhookSourceEnum.CLERK,
            event_type="user.updated",
            event_id=data.get("id"),
            payload=data,
            status="failed",
            error_message=str(e),
        )
        raise

async def handle_user_deleted(data: dict):
    """Handle user.deleted webhook event"""
    try:
        clerk_user_id = data.get("id")
        if not clerk_user_id:
            logger.error("Missing user ID in webhook payload")
            return

        user = await User.filter(clerk_user_id=clerk_user_id).first()
        if not user:
            logger.warning(f"User with Clerk ID {clerk_user_id} not found for deletion")
            return

        # Soft delete: deactivate user instead of hard delete
        user.is_active = False
        await user.save()

        logger.info(f"Deactivated user {user.email} from Clerk webhook")

        await log_webhook_event(
            source=WebhookSourceEnum.CLERK,
            event_type="user.deleted",
            event_id=clerk_user_id,
            payload=data,
            status="processed",
        )

    except Exception as e:
        logger.error(f"Error handling user.deleted webhook: {str(e)}")
        await log_webhook_event(
            source=WebhookSourceEnum.CLERK,
            event_type="user.deleted",
            event_id=data.get("id"),
            payload=data,
            status="failed",
            error_message=str(e),
        )
        raise


@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature")
):
    """
    Handle Razorpay webhook events for payment confirmations

    This is the PRIMARY source of truth for payment completion.
    Even if the frontend callback fails, this webhook ensures wallet is credited.
    """
    try:
        # Get raw request body for signature verification
        body = await request.body()

        # Verify webhook signature
        if not x_razorpay_signature:
            logger.error("Missing X-Razorpay-Signature header in webhook")
            raise HTTPException(status_code=400, detail="Missing signature header")

        is_valid = razorpay_service.verify_webhook_signature(body, x_razorpay_signature)
        if not is_valid:
            logger.error("Invalid Razorpay webhook signature")
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

        # Parse webhook payload
        try:
            payload = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse webhook payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        event_type = payload.get("event")
        event_data = payload.get("payload", {})

        logger.info(f"Received Razorpay webhook: {event_type}")

        # Handle payment.captured event (when payment is successful)
        if event_type == "payment.captured":
            await handle_payment_captured(event_data)

        # Handle payment.failed event
        elif event_type == "payment.failed":
            await handle_payment_failed(event_data)

        # Handle order.paid event (alternative to payment.captured)
        elif event_type == "order.paid":
            await handle_order_paid(event_data)

        # Handle QR code credited event (appless charging payment)
        elif event_type == "qr_code.credited":
            await handle_qr_code_credited(event_data)

        # Razorpay Route: account lifecycle
        elif event_type.startswith("account."):
            await handle_account_event(event_type, event_data)

        # Razorpay Route: transfer lifecycle
        elif event_type.startswith("transfer."):
            await handle_transfer_event(event_type, event_data)

        else:
            logger.info(f"Unhandled Razorpay webhook event: {event_type}")

        return {"status": "success"}

    except HTTPException:
        raise
    except Exception as e:
        # Return 200 so Razorpay does not retry on application errors.
        # Real infrastructure failures (DB/Redis down) still surface via HTTPException.
        logger.error(f"Razorpay webhook processing error: {e}", exc_info=True)
        return {"status": "error_handled"}


async def handle_payment_captured(event_data: dict):
    """Handle payment.captured webhook event"""
    try:
        payment = event_data.get("payment", {}).get("entity", {})
        order_id = payment.get("order_id")
        payment_id = payment.get("id")
        amount_in_paise = payment.get("amount")
        status = payment.get("status")

        logger.info(
            f"Processing payment.captured: "
            f"Order {order_id}, Payment {payment_id}, "
            f"Amount {amount_in_paise} paise, Status {status}"
        )

        if not order_id:
            logger.info(f"Payment {payment_id} has no order_id (likely a QR payment), skipping payment.captured handler")
            return
        if not payment_id:
            raise ValueError("Missing payment_id in webhook payload")

        # Find the wallet transaction by indexed order_id
        wallet_txn = await _find_txn_by_order_id(order_id)

        if not wallet_txn:
            logger.warning(f"Wallet transaction not found for order {order_id} — skipping (may belong to another environment)")
            return

        # Check if already completed (idempotency)
        current_status = wallet_txn.payment_metadata.get("status")
        if current_status == PaymentStatusEnum.COMPLETED.value:
            logger.info(
                f"Payment already processed for order {order_id}, "
                f"transaction {wallet_txn.id}"
            )
            return

        # Process the wallet top-up
        # Note: We don't have signature in webhook, so we pass empty string
        # The webhook signature verification is sufficient
        success, message, new_balance = await WalletService.process_wallet_topup(
            wallet_transaction_id=wallet_txn.id,
            razorpay_payment_id=payment_id,
            razorpay_signature=None  # Signature not available in webhook
        )

        if success:
            # Store Razorpay fee breakdown for GST compliance
            fee_data = extract_fee_from_payment(payment)
            if fee_data:
                total_fee, tax = fee_data
                txn = await WalletTransaction.get(id=wallet_txn.id)
                meta = txn.payment_metadata or {}
                meta.update({
                    "razorpay_fee": float(total_fee),
                    "razorpay_tax": float(tax),
                    "razorpay_commission": float(total_fee - tax),
                    "fee_source": "webhook",
                })
                txn.payment_metadata = meta
                await txn.save()

            logger.info(
                f"✅ Webhook: Successfully processed payment for order {order_id}, "
                f"Amount ₹{wallet_txn.amount}, New balance ₹{new_balance}"
            )
            await log_webhook_event(
                source=WebhookSourceEnum.RAZORPAY,
                event_type="payment.captured",
                event_id=payment_id,
                payload=event_data,
                status="processed",
            )
        else:
            logger.error(
                f"❌ Webhook: Failed to process payment for order {order_id}: {message}"
            )
            await log_webhook_event(
                source=WebhookSourceEnum.RAZORPAY,
                event_type="payment.captured",
                event_id=payment_id,
                payload=event_data,
                status="failed",
                error_message=message,
            )

    except Exception as e:
        # Log but do not re-raise; outer handler returns 200 to prevent Razorpay retries
        logger.error(f"Error handling payment.captured webhook: {e}", exc_info=True)


async def handle_payment_failed(event_data: dict):
    """Handle payment.failed webhook event"""
    try:
        payment = event_data.get("payment", {}).get("entity", {})
        order_id = payment.get("order_id")
        payment_id = payment.get("id")
        error_description = payment.get("error_description")

        logger.warning(
            f"Payment failed: Order {order_id}, Payment {payment_id}, "
            f"Reason: {error_description}"
        )

        if not order_id:
            logger.warning("Missing order_id in payment.failed webhook — skipping")
            return

        # Find the wallet transaction
        wallet_txn = await _find_txn_by_order_id(order_id)

        if not wallet_txn:
            logger.warning(f"Wallet transaction not found for failed order {order_id} — skipping (may belong to another environment)")
            return

        # Mark as failed
        updated_metadata = wallet_txn.payment_metadata or {}
        updated_metadata.update({
            "status": PaymentStatusEnum.FAILED.value,
            "razorpay_payment_id": payment_id,
            "error_description": error_description,
            "failed_at": int(time.time())
        })

        await WalletTransaction.filter(id=wallet_txn.id).update(
            description=f"Wallet recharge - ₹{wallet_txn.amount} (Payment Failed)",
            payment_metadata=updated_metadata
        )

        logger.info(f"Marked transaction {wallet_txn.id} as FAILED for order {order_id}")

        await log_webhook_event(
            source=WebhookSourceEnum.RAZORPAY,
            event_type="payment.failed",
            event_id=payment_id,
            payload=event_data,
            status="processed",
        )

    except Exception as e:
        logger.error(f"Error handling payment.failed webhook: {e}", exc_info=True)


async def handle_order_paid(event_data: dict):
    """Handle order.paid webhook event (alternative to payment.captured)"""
    try:
        order = event_data.get("order", {}).get("entity", {})
        order_id = order.get("id")
        amount_in_paise = order.get("amount_paid")

        logger.info(
            f"Processing order.paid: Order {order_id}, "
            f"Amount {amount_in_paise} paise"
        )

        if not order_id:
            logger.warning("Missing order_id in order.paid webhook — skipping")
            return

        # Find the wallet transaction
        wallet_txn = await _find_txn_by_order_id(order_id)

        if not wallet_txn:
            logger.warning(f"Wallet transaction not found for order {order_id} — skipping (may belong to another environment)")
            return

        # Check if already completed
        current_status = wallet_txn.payment_metadata.get("status")
        if current_status == PaymentStatusEnum.COMPLETED.value:
            logger.info(f"Order {order_id} already processed")
            return

        # Get payment details from Razorpay to find payment_id
        payment_id = None
        try:
            order_details = razorpay_service.fetch_order(order_id)
            if order_details:
                # Get payments for this order
                # Note: This is a simplified version, you might need to fetch payments separately
                payment_id = wallet_txn.payment_metadata.get("razorpay_payment_id", "from_webhook")
        except Exception as e:
            logger.warning(f"Could not fetch payment_id for order {order_id}: {e}")
            payment_id = "webhook_order_paid"

        # Process the wallet top-up
        success, message, new_balance = await WalletService.process_wallet_topup(
            wallet_transaction_id=wallet_txn.id,
            razorpay_payment_id=payment_id,
            razorpay_signature=None
        )

        if success:
            logger.info(
                f"✅ Webhook (order.paid): Successfully processed order {order_id}, "
                f"New balance ₹{new_balance}"
            )
            await log_webhook_event(
                source=WebhookSourceEnum.RAZORPAY,
                event_type="order.paid",
                event_id=order_id,
                payload=event_data,
                status="processed",
            )
        else:
            await log_webhook_event(
                source=WebhookSourceEnum.RAZORPAY,
                event_type="order.paid",
                event_id=order_id,
                payload=event_data,
                status="failed",
                error_message=message,
            )

    except Exception as e:
        logger.error(f"Error handling order.paid webhook: {e}", exc_info=True)


async def handle_qr_code_credited(event_data: dict):
    """Handle qr_code.credited webhook event for appless QR charging"""
    try:
        from services.qr_payment_service import QRPaymentService

        payment = event_data.get("payment", {}).get("entity", {})
        qr_code = event_data.get("qr_code", {}).get("entity", {})
        payment_id = payment.get("id")
        qr_code_id = qr_code.get("id")

        logger.info(
            f"Processing qr_code.credited: "
            f"Payment {payment_id}, QR {qr_code_id}, "
            f"Amount {payment.get('amount')} paise"
        )

        result = await QRPaymentService.handle_qr_payment(event_data)

        await log_webhook_event(
            source=WebhookSourceEnum.RAZORPAY,
            event_type="qr_code.credited",
            event_id=payment_id,
            payload=event_data,
            status="processed" if result.get("status") != "error" else "failed",
            error_message=result.get("reason"),
        )

        logger.info(f"QR code credited result: {result}")

    except Exception as e:
        logger.error(f"Error handling qr_code.credited webhook: {e}", exc_info=True)
        await log_webhook_event(
            source=WebhookSourceEnum.RAZORPAY,
            event_type="qr_code.credited",
            event_id=event_data.get("payment", {}).get("entity", {}).get("id"),
            payload=event_data,
            status="failed",
            error_message=str(e),
        )


async def handle_account_event(event_type: str, event_data: dict):
    """Handle Razorpay Route account lifecycle webhooks."""
    try:
        account_data = event_data.get("account", {}).get("entity", {})
        if not account_data:
            logger.warning("No account entity in %s webhook", event_type)
            return

        from services.franchisee_onboarding_service import FranchiseeOnboardingService
        await FranchiseeOnboardingService.handle_account_webhook(
            event_type, account_data
        )

        await log_webhook_event(
            source=WebhookSourceEnum.RAZORPAY,
            event_type=event_type,
            event_id=account_data.get("id"),
            payload=event_data,
            status="processed",
        )
    except Exception as e:
        logger.error("Error handling %s webhook: %s", event_type, e, exc_info=True)
        await log_webhook_event(
            source=WebhookSourceEnum.RAZORPAY,
            event_type=event_type,
            event_id=event_data.get("account", {}).get("entity", {}).get("id"),
            payload=event_data,
            status="failed",
            error_message=str(e),
        )


async def handle_transfer_event(event_type: str, event_data: dict):
    """Handle Razorpay Route transfer lifecycle webhooks."""
    try:
        transfer_data = event_data.get("transfer", {}).get("entity", {})
        if not transfer_data:
            logger.warning("No transfer entity in %s webhook", event_type)
            return

        from services.franchisee_settlement_service import FranchiseeSettlementService
        await FranchiseeSettlementService.handle_transfer_webhook(
            event_type, transfer_data
        )

        await log_webhook_event(
            source=WebhookSourceEnum.RAZORPAY,
            event_type=event_type,
            event_id=transfer_data.get("id"),
            payload=event_data,
            status="processed",
        )
    except Exception as e:
        logger.error("Error handling %s webhook: %s", event_type, e, exc_info=True)
        await log_webhook_event(
            source=WebhookSourceEnum.RAZORPAY,
            event_type=event_type,
            event_id=event_data.get("transfer", {}).get("entity", {}).get("id"),
            payload=event_data,
            status="failed",
            error_message=str(e),
        )