"""Franchisee Razorpay Route onboarding service.

Handles creating linked accounts and processing KYC webhook events
from Razorpay's hosted onboarding flow.
"""

import logging
from datetime import datetime
from typing import Dict, Optional

from models import (
    Franchisee,
    FranchiseeStakeholder,
    FranchiseeStatusEnum,
)

logger = logging.getLogger("ocpp-server")


def _split_street(address: str, fallback: str) -> Dict[str, str]:
    """Split a freeform address into Razorpay Route's street1 + street2.

    Razorpay requires both to be non-empty. If ``address`` contains a
    comma or newline, use the parts either side. Otherwise use the full
    address as street1 and ``fallback`` (the city) as street2 so
    Razorpay's validator accepts the payload. Both values are truncated
    to 100 chars per Razorpay's documented limit.
    """
    raw = (address or "").replace("\n", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2:
        return {"street1": parts[0][:100], "street2": ", ".join(parts[1:])[:100]}
    return {
        "street1": (parts[0] if parts else address or "")[:100],
        "street2": (fallback or "NA")[:100],
    }


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
            # Razorpay Route requires BOTH street1 and street2 to be
            # non-empty even though the docs mark street2 optional (live
            # API validation drift, 2026-04). Split the freeform
            # `address` on comma / newline when the admin provided a
            # multi-part string; otherwise fall back to `city` so
            # street2 is never empty.
            # Razorpay's category/subcategory enum does not have a
            # dedicated EV-charging code. `services/service_stations`
            # maps to the MCC globally used for fuel/EV stations and is
            # the closest accepted pair. If Razorpay ever adds a
            # dedicated EV code we should switch.
            "profile": {
                "category": "services",
                "subcategory": "service_stations",
                "addresses": {
                    "registered": {
                        **_split_street(franchisee.address, franchisee.city),
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

    # ─── Post-create KYC submission chain ──────────────────────────────
    # After ``create_linked_account`` returns an ``acc_xxx`` in status
    # ``created``, the account still needs (1) a product config, (2) bank
    # settlement details, and (3) at least one stakeholder before Razorpay
    # will accept the account into their review queue. The methods below
    # drive that chain without requiring the admin to touch Razorpay's
    # dashboard.

    @staticmethod
    async def ensure_product_config(franchisee_id: int) -> str:
        """Return the franchisee's Route product_id, creating the product
        config on Razorpay if one doesn't exist yet. Idempotent: safe to
        call multiple times."""
        from services.razorpay_service import razorpay_service

        franchisee = await Franchisee.filter(id=franchisee_id).first()
        if not franchisee:
            raise ValueError(f"Franchisee {franchisee_id} not found")
        if not franchisee.razorpay_account_id:
            raise RuntimeError(
                "Franchisee has no Razorpay account. Run onboarding first."
            )
        if franchisee.razorpay_product_id:
            return franchisee.razorpay_product_id

        result = razorpay_service.request_product_configuration(
            franchisee.razorpay_account_id,
            {"product_name": "route", "tnc_accepted": True},
        )
        product_id = result.get("id")
        if not product_id:
            raise RuntimeError(
                "Razorpay product creation returned no id: %s" % result
            )
        await Franchisee.filter(id=franchisee_id).update(
            razorpay_product_id=product_id,
        )
        logger.info(
            "Product config created for franchisee %s: %s",
            franchisee_id, product_id,
        )
        return product_id

    @staticmethod
    async def submit_bank_details(franchisee_id: int) -> Dict:
        """PATCH the product config with the franchisee's bank account.
        Requires bank fields to be populated on the Franchisee record."""
        from services.razorpay_service import razorpay_service

        franchisee = await Franchisee.filter(id=franchisee_id).first()
        if not franchisee:
            raise ValueError(f"Franchisee {franchisee_id} not found")
        if not franchisee.razorpay_product_id:
            raise RuntimeError(
                "No product config. Call ensure_product_config first."
            )

        missing = [
            f for f in ("bank_ifsc_code", "bank_account_number", "bank_account_name")
            if not getattr(franchisee, f)
        ]
        if missing:
            raise RuntimeError(
                "Franchisee is missing bank fields: " + ", ".join(missing)
            )

        result = razorpay_service.edit_product_configuration(
            franchisee.razorpay_account_id,
            franchisee.razorpay_product_id,
            {
                "settlements": {
                    "account_number": franchisee.bank_account_number,
                    "ifsc_code": franchisee.bank_ifsc_code,
                    "beneficiary_name": franchisee.bank_account_name,
                }
            },
        )
        logger.info(
            "Bank details submitted for franchisee %s: activation_status=%s",
            franchisee_id, result.get("activation_status"),
        )
        return result

    @staticmethod
    async def add_stakeholder(
        franchisee_id: int, payload: Dict
    ) -> FranchiseeStakeholder:
        """Create a stakeholder on Razorpay + persist locally.

        ``payload`` must contain at least ``name`` and ``email``. Optional:
        ``phone_primary``, ``relationship_director`` (default True),
        ``relationship_executive`` (default True), ``pan_number``.
        """
        from services.razorpay_service import razorpay_service

        franchisee = await Franchisee.filter(id=franchisee_id).first()
        if not franchisee:
            raise ValueError(f"Franchisee {franchisee_id} not found")
        if not franchisee.razorpay_account_id:
            raise RuntimeError(
                "Franchisee has no Razorpay account. Run onboarding first."
            )

        name = (payload.get("name") or "").strip()
        email = (payload.get("email") or "").strip()
        if not name or not email:
            raise RuntimeError("Stakeholder name and email are required")

        director = payload.get("relationship_director", True)
        executive = payload.get("relationship_executive", True)
        phone = payload.get("phone_primary")

        rzp_payload: Dict = {
            "name": name,
            "email": email,
            "relationship": {"director": director, "executive": executive},
        }
        if phone:
            rzp_payload["phone"] = {"primary": phone}

        result = razorpay_service.create_stakeholder(
            franchisee.razorpay_account_id, rzp_payload
        )
        stakeholder_id = result.get("id")

        row = await FranchiseeStakeholder.create(
            franchisee=franchisee,
            razorpay_stakeholder_id=stakeholder_id,
            name=name,
            email=email,
            phone_primary=phone,
            relationship_director=director,
            relationship_executive=executive,
            pan_number=payload.get("pan_number"),
        )
        logger.info(
            "Stakeholder created for franchisee %s: %s",
            franchisee_id, stakeholder_id,
        )
        return row

    @staticmethod
    async def submit_kyc(franchisee_id: int) -> Dict:
        """Orchestrate: ensure product config → submit bank → re-fetch.
        Returns a summary dict with ``activation_status`` and
        ``requirements`` for the admin UI toast.
        """
        from services.razorpay_service import razorpay_service

        franchisee = await Franchisee.filter(id=franchisee_id).first()
        if not franchisee:
            raise ValueError(f"Franchisee {franchisee_id} not found")
        if not franchisee.razorpay_account_id:
            raise RuntimeError(
                "Franchisee has no Razorpay account. Run onboarding first."
            )

        stakeholder_count = await FranchiseeStakeholder.filter(
            franchisee_id=franchisee_id
        ).count()
        if stakeholder_count == 0:
            raise RuntimeError(
                "Razorpay requires at least one stakeholder before KYC "
                "submission. Add a stakeholder first."
            )

        product_id = await FranchiseeOnboardingService.ensure_product_config(
            franchisee_id
        )
        await FranchiseeOnboardingService.submit_bank_details(franchisee_id)
        final = razorpay_service.fetch_product_configuration(
            franchisee.razorpay_account_id, product_id
        )

        return {
            "product_id": product_id,
            "activation_status": final.get("activation_status"),
            "requirements": final.get("requirements") or [],
            "stakeholder_count": stakeholder_count,
        }

    @staticmethod
    async def reconcile_razorpay(
        franchisee_id: int,
        razorpay_product_id: Optional[str] = None,
        razorpay_stakeholder_ids: Optional[list] = None,
    ) -> Dict:
        """Back-reconcile an account that was pushed to Razorpay outside
        the normal flow (e.g. via a one-off script or the Razorpay
        dashboard). Stores product_id + creates stakeholder rows that
        point at existing Razorpay stakeholders without re-creating them.
        """
        franchisee = await Franchisee.filter(id=franchisee_id).first()
        if not franchisee:
            raise ValueError(f"Franchisee {franchisee_id} not found")

        updates: Dict = {}
        if razorpay_product_id and not franchisee.razorpay_product_id:
            updates["razorpay_product_id"] = razorpay_product_id
        if updates:
            await Franchisee.filter(id=franchisee_id).update(**updates)

        created = 0
        for sid in razorpay_stakeholder_ids or []:
            existing = await FranchiseeStakeholder.filter(
                razorpay_stakeholder_id=sid
            ).first()
            if existing:
                continue
            # Fetch details from Razorpay so we can populate the local row
            # faithfully. Cheap GET; skip on failure.
            from services.razorpay_service import razorpay_service
            try:
                remote = razorpay_service.client.stakeholder.fetch(
                    franchisee.razorpay_account_id, sid
                )
            except Exception as e:
                logger.warning(
                    "reconcile: could not fetch stakeholder %s: %s", sid, e
                )
                continue
            rel = remote.get("relationship") or {}
            phone = (remote.get("phone") or {}).get("primary")
            await FranchiseeStakeholder.create(
                franchisee=franchisee,
                razorpay_stakeholder_id=sid,
                name=remote.get("name") or "Unknown",
                email=remote.get("email") or "",
                phone_primary=phone,
                relationship_director=rel.get("director", True),
                relationship_executive=rel.get("executive", True),
            )
            created += 1

        return {
            "franchisee_id": franchisee_id,
            "razorpay_product_id": franchisee.razorpay_product_id or razorpay_product_id,
            "stakeholders_reconciled": created,
        }
