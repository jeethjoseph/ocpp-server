"""Clerk invitation helpers.

Wraps the Clerk Python SDK so admin-facing flows can send magic-link
invitations pre-populated with role metadata. Used by the franchisee
onboarding flow: when an admin creates a franchisee, we email an
invitation whose public_metadata carries role=FRANCHISEE, so the user
lands in the right portal the moment they finish sign-up.
"""

import os
import logging
from typing import Optional

from clerk_backend_api import Clerk
from clerk_backend_api.models import ClerkErrors, SDKError

logger = logging.getLogger("ocpp-server")

_CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
if not _CLERK_SECRET_KEY:
    raise ValueError("CLERK_SECRET_KEY must be set for clerk_invitation_service")

_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")

_client = Clerk(bearer_auth=_CLERK_SECRET_KEY)


def _is_already_invited_or_registered(exc: Exception) -> bool:
    """Detect Clerk errors that mean "this email is already in play".

    Clerk returns 422 with codes `duplicate_record` or
    `form_identifier_exists` in these cases. We treat them as success
    from the caller's perspective (invitation flow is idempotent).
    """
    if not isinstance(exc, ClerkErrors):
        return False
    for err in getattr(exc, "errors", []) or []:
        code = getattr(err, "code", "") or ""
        if code in {"duplicate_record", "form_identifier_exists"}:
            return True
    return False


async def send_invitation(
    email: str,
    role: str,
    redirect_path: str = "/",
) -> Optional[str]:
    """Send a Clerk invitation email seeded with role metadata.

    Returns the invitation id on success, None if the email is already
    invited or already registered (idempotent no-op), and re-raises on
    unexpected Clerk / transport failures so the caller can decide
    whether to surface the failure.
    """
    redirect_url = f"{_FRONTEND_URL}{redirect_path}"
    try:
        invitation = await _client.invitations.create_async(
            request={
                "email_address": email,
                "public_metadata": {"role": role},
                "redirect_url": redirect_url,
                "notify": True,
            }
        )
    except ClerkErrors as exc:
        if _is_already_invited_or_registered(exc):
            logger.info(
                "Clerk invitation skipped (already invited/registered): %s",
                email,
            )
            return None
        logger.exception("Clerk invitation failed for %s", email)
        raise
    except SDKError:
        logger.exception("Clerk transport error sending invitation to %s", email)
        raise

    invitation_id = getattr(invitation, "id", None) if invitation else None
    logger.info(
        "Clerk invitation sent: email=%s role=%s invitation_id=%s",
        email, role, invitation_id,
    )
    return invitation_id


async def revoke_pending_invitation(email: str) -> bool:
    """Revoke any pending invitation for the given email.

    Useful when an admin wants to resend with fresh metadata, or when a
    franchisee is deleted before signing up. Returns True if something
    was revoked, False if no pending invitation existed.
    """
    try:
        result = await _client.invitations.list_async(status="pending", query=email)
    except (ClerkErrors, SDKError):
        logger.exception("Clerk invitation list failed for %s", email)
        raise

    invitations = result or []
    revoked = False
    for inv in invitations:
        inv_email = getattr(inv, "email_address", None)
        inv_id = getattr(inv, "id", None)
        if inv_email == email and inv_id:
            try:
                await _client.invitations.revoke_async(invitation_id=inv_id)
                revoked = True
                logger.info("Revoked pending Clerk invitation %s (%s)", inv_id, email)
            except (ClerkErrors, SDKError):
                logger.exception("Failed revoking Clerk invitation %s", inv_id)
    return revoked


async def push_role_to_clerk(clerk_user_id: str, role: str) -> None:
    """Ensure an existing Clerk user's public_metadata.role matches ours.

    Called from the user.created webhook handler to self-heal any drift
    between the authoritative DB role and what Clerk holds — so frontend
    routing (which trusts Clerk publicMetadata) reflects reality.
    """
    try:
        await _client.users.update_metadata_async(
            user_id=clerk_user_id,
            public_metadata={"role": role},
        )
        logger.info(
            "Clerk role synced: clerk_user_id=%s role=%s", clerk_user_id, role
        )
    except (ClerkErrors, SDKError):
        logger.exception(
            "Failed syncing Clerk role for %s", clerk_user_id
        )
