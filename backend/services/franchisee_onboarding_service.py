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


# For INDIVIDUAL / PROPRIETORSHIP there is no "director" of the business —
# the proprietor is just the executive (signatory). For PARTNERSHIP / LLP /
# PRIVATE_LIMITED the stakeholder typically holds both relationships. The
# defaults below keep the wire payload semantically correct; callers can
# still override via explicit args.
_RELATIONSHIP_DEFAULTS = {
    "INDIVIDUAL": (False, True),
    "PROPRIETORSHIP": (False, True),
    "PARTNERSHIP": (True, True),
    "PRIVATE_LIMITED": (True, True),
    "LLP": (True, True),
}


def _relationship_defaults(business_type) -> tuple[bool, bool]:
    """Return ``(director, executive)`` defaults for a business_type.

    Falls back to ``(True, True)`` with a warning for unmapped enum
    members so a future addition to ``FranchiseeBusinessTypeEnum``
    doesn't crash silently.
    """
    key = business_type.value if hasattr(business_type, "value") else str(
        business_type
    )
    defaults = _RELATIONSHIP_DEFAULTS.get(key)
    if defaults is None:
        logger.warning(
            "_relationship_defaults: unmapped business_type %r — "
            "defaulting to (True, True)", key,
        )
        return (True, True)
    return defaults


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
                    # Razorpay's `addresses` accepts both `registered` and
                    # `operational`. Mirroring the registered address as
                    # operational gives the review queue both touchpoints
                    # at once; updating operational separately later via
                    # account.edit is cheap if it ever diverges.
                    "registered": {
                        **_split_street(franchisee.address, franchisee.city),
                        "city": franchisee.city,
                        "state": (franchisee.state or "").upper(),
                        "postal_code": franchisee.pincode,
                        "country": "IN",
                    },
                    "operational": {
                        **_split_street(franchisee.address, franchisee.city),
                        "city": franchisee.city,
                        "state": (franchisee.state or "").upper(),
                        "postal_code": franchisee.pincode,
                        "country": "IN",
                    },
                },
            },
            "notes": {
                "voltlync_franchisee_id": str(franchisee.id),
            },
        }

        result = razorpay_service.create_linked_account(payload)

        # Razorpay sometimes silently downgrades the requested
        # ``business_type`` to ``not_yet_registered`` when its
        # internal classifier disagrees (we observed this on
        # acc_Sg73UwyOU3jziR). Surface the mismatch so the admin can
        # contact support before the account stalls in review.
        echoed = result.get("business_type")
        if echoed and echoed != business_type:
            logger.warning(
                "Razorpay echoed business_type=%r for franchisee %s "
                "(we sent %r) — review may stall; contact support if "
                "this is unexpected.",
                echoed, franchisee_id, business_type,
            )

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

        # Persist Razorpay's verification subtree when present. Razorpay
        # ships fields like ``bank_details_verification_status``,
        # ``poi_verification_status``, ``poa_verification_status`` (and
        # may add more) on under_review / needs_clarification / activated
        # webhook payloads. Storing the raw subtree as JSONB is forward-
        # compatible — admin UI can render whatever keys are present.
        verification = (
            account_data.get("verification")
            or account_data.get("verification_statuses")
        )
        if verification:
            update_fields["kyc_verifications"] = verification

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
            # `requirements` is a list of {field_reference, resolution_url,
            # reason_code, status} dicts (NOT a dict). Concatenate the
            # human-readable parts so admins can see what to fix without
            # opening the JSONB column.
            reason_parts = []
            requirements = account_data.get("requirements") or []
            if isinstance(requirements, list):
                for r in requirements:
                    if not isinstance(r, dict):
                        continue
                    field_ref = r.get("field_reference") or "?"
                    code = r.get("reason_code") or r.get("reason") or "?"
                    reason_parts.append(f"{field_ref}: {code}")
            top_reason = account_data.get("reason")
            if top_reason:
                reason_parts.insert(0, str(top_reason))
            if reason_parts:
                update_fields["status_reason"] = "; ".join(reason_parts)[:500]
            logger.info(
                "Franchisee %s KYC needs clarification: %s",
                franchisee.id, update_fields.get("status_reason", "(no reason)"),
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

        # account_type is optional in Razorpay's update-product-config
        # spec; send only when the franchisee row has it populated. The
        # update endpoint also accepts ``tnc_accepted`` and re-sending it
        # is documented as safe — including it ensures the consent stays
        # current even after a PATCH.
        settlements = {
            "account_number": franchisee.bank_account_number,
            "ifsc_code": franchisee.bank_ifsc_code,
            "beneficiary_name": franchisee.bank_account_name,
        }
        if franchisee.bank_account_type:
            settlements["account_type"] = franchisee.bank_account_type

        result = razorpay_service.edit_product_configuration(
            franchisee.razorpay_account_id,
            franchisee.razorpay_product_id,
            {
                "settlements": settlements,
                "tnc_accepted": True,
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
        ``phone_primary``, ``relationship_director`` /
        ``relationship_executive`` (defaults derived from the franchisee's
        ``business_type`` via ``_relationship_defaults`` — caller-provided
        values still win), ``pan_number``, ``residential`` (dict with
        ``street`` / ``city`` / ``state`` / ``postal_code`` / ``country``).
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

        default_director, default_executive = _relationship_defaults(
            franchisee.business_type
        )
        director = payload.get("relationship_director", default_director)
        executive = payload.get("relationship_executive", default_executive)
        phone = payload.get("phone_primary")
        pan = payload.get("pan_number")
        residential = payload.get("residential") or {}

        rzp_payload: Dict = {
            "name": name,
            "email": email,
            "relationship": {"director": director, "executive": executive},
        }
        if phone:
            rzp_payload["phone"] = {"primary": phone}
        if pan:
            rzp_payload["kyc"] = {"pan": pan}
        if residential.get("street"):
            rzp_payload["addresses"] = {
                "residential": {
                    "street": residential["street"],
                    "city": residential.get("city") or franchisee.city or "",
                    "state": (
                        residential.get("state") or franchisee.state or ""
                    ).upper(),
                    "postal_code": (
                        residential.get("postal_code")
                        or franchisee.pincode
                        or ""
                    ),
                    "country": residential.get("country") or "IN",
                }
            }

        result = razorpay_service.create_stakeholder(
            franchisee.razorpay_account_id, rzp_payload
        )
        stakeholder_id = result.get("id")

        try:
            row = await FranchiseeStakeholder.create(
                franchisee=franchisee,
                razorpay_stakeholder_id=stakeholder_id,
                name=name,
                email=email,
                phone_primary=phone,
                relationship_director=director,
                relationship_executive=executive,
                pan_number=pan,
                residential_street=residential.get("street"),
                residential_city=residential.get("city"),
                residential_state=residential.get("state"),
                residential_postal_code=residential.get("postal_code"),
                residential_country=residential.get("country") or "IN",
            )
        except Exception as e:
            # Razorpay create succeeded but local persistence failed —
            # don't silently duplicate-create on retry. Surface the
            # mismatch so the admin can reconcile via reconcile_razorpay.
            logger.error(
                "Stakeholder %s created on Razorpay for franchisee %s but "
                "local insert failed: %s — reconcile via "
                "POST /api/admin/franchisees/{id}/reconcile-razorpay",
                stakeholder_id, franchisee_id, e,
            )
            raise
        logger.info(
            "Stakeholder created for franchisee %s: %s",
            franchisee_id, stakeholder_id,
        )
        return row

    @staticmethod
    async def update_stakeholder(
        franchisee_id: int, stakeholder_id: int, payload: Dict
    ) -> FranchiseeStakeholder:
        """PATCH a stakeholder on Razorpay + persist locally.

        ``payload`` keys (all optional, only provided fields are sent /
        persisted): ``name``, ``email``, ``phone_primary``, ``pan_number``,
        ``relationship_director``, ``relationship_executive``,
        ``residential`` (dict with street / city / state / postal_code /
        country).
        """
        from services.razorpay_service import razorpay_service

        franchisee = await Franchisee.filter(id=franchisee_id).first()
        if not franchisee:
            raise ValueError(f"Franchisee {franchisee_id} not found")

        row = await FranchiseeStakeholder.filter(
            id=stakeholder_id, franchisee_id=franchisee_id
        ).first()
        if not row:
            raise ValueError(
                f"Stakeholder {stakeholder_id} not found for franchisee "
                f"{franchisee_id}"
            )
        if not row.razorpay_stakeholder_id:
            raise RuntimeError(
                "Stakeholder has no razorpay_stakeholder_id (not yet "
                "synced to Razorpay) — recreate via add_stakeholder."
            )

        # Build the Razorpay PATCH body — only include keys actually
        # provided (PATCH semantics; None must not overwrite existing
        # Razorpay-side values).
        rzp_payload: Dict = {}
        if payload.get("name"):
            rzp_payload["name"] = payload["name"].strip()
        if payload.get("email"):
            rzp_payload["email"] = payload["email"].strip()
        if payload.get("phone_primary"):
            rzp_payload["phone"] = {"primary": payload["phone_primary"]}
        if payload.get("pan_number"):
            rzp_payload["kyc"] = {"pan": payload["pan_number"]}
        relationship_keys = (
            "relationship_director", "relationship_executive",
        )
        if any(k in payload for k in relationship_keys):
            rzp_payload["relationship"] = {
                "director": payload.get(
                    "relationship_director", row.relationship_director
                ),
                "executive": payload.get(
                    "relationship_executive", row.relationship_executive
                ),
            }
        residential = payload.get("residential") or {}
        if residential.get("street"):
            rzp_payload["addresses"] = {
                "residential": {
                    "street": residential["street"],
                    "city": residential.get("city") or row.residential_city
                            or franchisee.city or "",
                    "state": (
                        residential.get("state")
                        or row.residential_state
                        or franchisee.state or ""
                    ).upper(),
                    "postal_code": (
                        residential.get("postal_code")
                        or row.residential_postal_code
                        or franchisee.pincode or ""
                    ),
                    "country": (
                        residential.get("country")
                        or row.residential_country or "IN"
                    ),
                }
            }

        if rzp_payload:
            razorpay_service.update_stakeholder(
                franchisee.razorpay_account_id,
                row.razorpay_stakeholder_id,
                rzp_payload,
            )

        # Persist locally — only fields the caller actually provided.
        local_updates: Dict = {}
        for key in (
            "name", "email", "phone_primary", "pan_number",
            "relationship_director", "relationship_executive",
        ):
            if key in payload and payload[key] is not None:
                local_updates[key] = payload[key]
        if residential:
            for k, col in (
                ("street", "residential_street"),
                ("city", "residential_city"),
                ("state", "residential_state"),
                ("postal_code", "residential_postal_code"),
                ("country", "residential_country"),
            ):
                if residential.get(k):
                    local_updates[col] = residential[k]

        if local_updates:
            await FranchiseeStakeholder.filter(id=stakeholder_id).update(
                **local_updates
            )

        logger.info(
            "Stakeholder %s updated for franchisee %s: keys=%s",
            stakeholder_id, franchisee_id, list(local_updates.keys()),
        )
        return await FranchiseeStakeholder.filter(id=stakeholder_id).first()

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
                remote = razorpay_service.fetch_stakeholder(
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
