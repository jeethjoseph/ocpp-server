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

    # Razorpay `business_type` values (lowercased, snake_case). Our enum uses
    # UPPERCASE; this maps between the two.
    _BUSINESS_TYPE_MAP = {
        "INDIVIDUAL": "individual",
        "PROPRIETORSHIP": "proprietorship",
        "PARTNERSHIP": "partnership",
        "PRIVATE_LIMITED": "private_limited",
        "LLP": "llp",
    }

    @staticmethod
    async def create_linked_account(franchisee_id: int) -> Dict:
        """Create a Razorpay Route linked account for the franchisee.

        Razorpay's default Route flow emails the franchisee a KYC invite
        link automatically once the account is created; we don't host a
        KYC form ourselves. The create response may or may not include a
        ``hosted_onboarding_url`` depending on Partner dashboard config —
        treat its absence as expected, not an error.
        """
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

        if not franchisee.business_type:
            raise RuntimeError(
                "business_type must be set on the franchisee before Razorpay "
                "onboarding (update via PUT /api/admin/franchisees/{id})."
            )

        business_type = FranchiseeOnboardingService._BUSINESS_TYPE_MAP.get(
            franchisee.business_type.value
            if hasattr(franchisee.business_type, "value")
            else str(franchisee.business_type)
        )
        if not business_type:
            raise RuntimeError(
                f"Unsupported business_type {franchisee.business_type}"
            )

        # Razorpay Route requires profile.addresses.registered with all
        # subfields populated. Fail early with a clear message so the
        # admin knows which field to fill in the edit dialog.
        missing = [
            f for f in ("address", "city", "state", "pincode")
            if not getattr(franchisee, f)
        ]
        if missing:
            raise RuntimeError(
                "Franchisee is missing required address fields for Razorpay: "
                + ", ".join(missing)
            )

        payload = {
            "email": franchisee.contact_email,
            "phone": franchisee.contact_phone,
            "type": "route",
            "reference_id": f"franchisee_{franchisee.id}",
            "legal_business_name": franchisee.business_name,
            "customer_facing_business_name": franchisee.business_name,
            "business_type": business_type,
            "contact_name": franchisee.contact_name,
            "profile": {
                "category": "utilities",
                "subcategory": "electric_vehicle_charging",
                "addresses": {
                    "registered": {
                        "street1": franchisee.address[:100],
                        "street2": "",
                        "city": franchisee.city,
                        "state": (franchisee.state or "").upper(),
                        "postal_code": franchisee.pincode,
                        "country": "IN",
                    }
                },
            },
            "notes": {
                "voltlync_franchisee_id": str(franchisee.id),
            },
        }

        result = razorpay_service.create_linked_account(payload)

        account_id = result.get("id")
        # Hosted onboarding URL is best-effort: Razorpay returns it only
        # when the Partner dashboard has Hosted Onboarding enabled. When
        # absent, Razorpay emails the franchisee a KYC invite directly.
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

        if event_type in ("account.activated", "account.instantly_activated"):
            update_fields["status"] = FranchiseeStatusEnum.ACTIVE
            update_fields["kyc_verified_at"] = datetime.utcnow()
            update_fields["transfers_enabled"] = True
            if not franchisee.activated_at:
                update_fields["activated_at"] = datetime.utcnow()
            logger.info("Franchisee %s KYC approved (%s)", franchisee.id, event_type)

        elif event_type == "account.activated_kyc_pending":
            # Account can accept payments but cannot yet receive transfers.
            update_fields["status"] = FranchiseeStatusEnum.KYC_UNDER_REVIEW
            update_fields["transfers_enabled"] = False
            logger.info(
                "Franchisee %s activated with KYC pending — transfers disabled",
                franchisee.id,
            )

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

        elif event_type == "account.rejected":
            update_fields["status"] = FranchiseeStatusEnum.DRAFT
            update_fields["transfers_enabled"] = False
            update_fields["status_reason"] = account_data.get("reason", "KYC rejected")
            logger.warning("Franchisee %s KYC rejected", franchisee.id)

        elif event_type == "account.updated":
            # Generic catch-all. Razorpay fires this for any account-entity
            # change (bank details, contact info, status updates that aren't
            # covered by a specific lifecycle event). We already refresh
            # razorpay_account_status from the payload above — nothing else
            # to do unless we decide to sync bank details into our table.
            logger.info(
                "Franchisee %s account updated (status=%s)",
                franchisee.id, account_data.get("status"),
            )

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
