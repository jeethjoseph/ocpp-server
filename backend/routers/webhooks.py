from fastapi import APIRouter, HTTPException, Request, Header
from svix import Webhook
from models import User, UserRoleEnum, Wallet
from tortoise.expressions import Q
import logging
import json
import os
from clerk_backend_api import Clerk

logger = logging.getLogger("webhooks")
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

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
        logger.error(f"Webhook processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")

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
            return
        
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
            notification_preferences="{}"
        )
        
        # Create wallet for user
        await Wallet.create(user=user, balance=0.00)
        
        logger.info(f"Created new user {primary_email} from Clerk webhook")
        
    except Exception as e:
        logger.error(f"Error handling user.created webhook: {str(e)}")
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
        
    except Exception as e:
        logger.error(f"Error handling user.updated webhook: {str(e)}")
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
        
    except Exception as e:
        logger.error(f"Error handling user.deleted webhook: {str(e)}")
        raise