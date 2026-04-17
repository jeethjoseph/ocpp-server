"""Franchisee Razorpay Route onboarding service.

Handles creating linked accounts and processing KYC webhook events
from Razorpay's hosted onboarding flow.
"""

import logging
from datetime import datetime
from typing import Dict, Optional

from models import (
    Franchisee,
    FranchiseeStatusEnum,
)

logger = logging.getLogger("ocpp-server")


class FranchiseeOnboardingService:

    @staticmethod
    async def create_linked_account(franchisee_id: int) -> Dict:
        """Create a minimal Razorpay Route linked account for the
        franchisee. The franchisee then completes KYC via Razorpay's
        hosted onboarding URL."""
        from services.razorpay_service import razorpay_service

        franchisee = await Franchisee.filter(id=franchisee_id).first()
        if not franchisee:
            raise ValueError(f"Franchisee {franchisee_id} not found")

        if franchisee.razorpay_account_id:
            return {
                "account_id": franchisee.razorpay_account_id,
                "status": franchisee.razorpay_account_status,
                "message": "Already has a linked account",
            }

        if not razorpay_service.is_route_enabled():
            raise RuntimeError("Razorpay Route is not enabled")

        payload = {
            "email": franchisee.contact_email,
            "phone": franchisee.contact_phone,
            "type": "route",
            "legal_business_name": franchisee.business_name,
            "notes": {
                "voltlync_franchisee_id": str(franchisee.id),
            },
        }

        result = razorpay_service.create_linked_account(payload)

        account_id = result.get("id")
        # Razorpay's hosted onboarding URL is returned under slightly
        # different keys depending on whether the merchant has Hosted
        # Onboarding enabled on their Partner dashboard. Check known
        # variants and fall back to None — if unavailable, Razorpay emails
        # the account holder a link directly.
        onboarding_url = (
            result.get("hosted_onboarding_url")
            or result.get("onboarding_url")
            or (result.get("onboarding") or {}).get("url")
        )

        update_fields = {
            "razorpay_account_id": account_id,
            "razorpay_account_status": result.get("status", "created"),
            "status": FranchiseeStatusEnum.KYC_SUBMITTED,
            "kyc_submitted_at": datetime.utcnow(),
        }
        if onboarding_url:
            update_fields["razorpay_onboarding_url"] = onboarding_url

        await Franchisee.filter(id=franchisee_id).update(**update_fields)

        logger.info(
            "Linked account created for franchisee %s: %s",
            franchisee_id, account_id,
        )
        return result

    @staticmethod
    async def handle_account_webhook(
        event_type: str, account_data: dict
    ):
        """Process Razorpay account lifecycle webhooks."""
        account_id = account_data.get("id")
        if not account_id:
            return

        franchisee = await Franchisee.filter(
            razorpay_account_id=account_id
        ).first()
        if not franchisee:
            # Check notes for our internal ID
            notes = account_data.get("notes", {})
            fid = notes.get("voltlync_franchisee_id")
            if fid:
                franchisee = await Franchisee.filter(id=int(fid)).first()
            if not franchisee:
                logger.warning(
                    "No franchisee for Razorpay account %s", account_id
                )
                return

        update_fields: Dict = {
            "razorpay_account_status": account_data.get("status"),
        }

        if event_type == "account.activated":
            update_fields["status"] = FranchiseeStatusEnum.ACTIVE
            update_fields["kyc_verified_at"] = datetime.utcnow()
            if not franchisee.activated_at:
                update_fields["activated_at"] = datetime.utcnow()
            logger.info("Franchisee %s KYC approved", franchisee.id)

        elif event_type == "account.under_review":
            update_fields["status"] = FranchiseeStatusEnum.KYC_UNDER_REVIEW
            logger.info("Franchisee %s KYC under review", franchisee.id)

        elif event_type == "account.needs_clarification":
            update_fields["status"] = FranchiseeStatusEnum.KYC_NEEDS_CLARIFICATION
            reason = account_data.get("reason") or account_data.get(
                "requirements", {}
            ).get("reason", "")
            if reason:
                update_fields["status_reason"] = str(reason)[:500]
            logger.info(
                "Franchisee %s KYC needs clarification", franchisee.id
            )

        elif event_type == "account.suspended":
            update_fields["status"] = FranchiseeStatusEnum.SUSPENDED
            update_fields["status_reason"] = account_data.get("reason", "Suspended by Razorpay")
            logger.warning("Franchisee %s suspended", franchisee.id)

        elif event_type == "account.rejected":
            update_fields["status"] = FranchiseeStatusEnum.DRAFT
            update_fields["status_reason"] = account_data.get("reason", "KYC rejected")
            logger.warning("Franchisee %s KYC rejected", franchisee.id)

        else:
            logger.info(
                "Unhandled account event %s for franchisee %s",
                event_type, franchisee.id,
            )
            return

        # Ensure razorpay_account_id is stored (in case it wasn't set before)
        if not franchisee.razorpay_account_id:
            update_fields["razorpay_account_id"] = account_id

        await Franchisee.filter(id=franchisee.id).update(**update_fields)

    @staticmethod
    async def refresh_kyc_status(franchisee_id: int) -> Dict:
        """Poll Razorpay for latest KYC status."""
        from services.razorpay_service import razorpay_service

        franchisee = await Franchisee.filter(id=franchisee_id).first()
        if not franchisee or not franchisee.razorpay_account_id:
            raise ValueError("No Razorpay account linked")

        account = razorpay_service.fetch_linked_account(
            franchisee.razorpay_account_id
        )

        await Franchisee.filter(id=franchisee_id).update(
            razorpay_account_status=account.get("status"),
        )

        return account
