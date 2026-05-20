"""Tests for the Clerk `user.created` webhook handler — specifically the
ADR-0004 role gate that prevents wallet creation for internal-role users.

We exercise `handle_user_created` directly rather than going through the
HTTP endpoint to avoid Svix signature plumbing in tests; the signature
verification lives at the router boundary and is unrelated to the role
gate we're guarding here.
"""
import pytest

from models import User, UserRoleEnum, Wallet
from routers.webhooks import handle_user_created


def _payload(email: str, clerk_id: str, role: str | None) -> dict:
    """Build a minimal Clerk user.created data payload."""
    return {
        "id": clerk_id,
        "email_addresses": [{"id": "em_1", "email_address": email}],
        "primary_email_address_id": "em_1",
        "first_name": "T",
        "last_name": "User",
        "phone_numbers": [],
        "public_metadata": {"role": role} if role else {},
    }


@pytest.mark.asyncio
async def test_user_role_gets_wallet(client):
    """Regression guard: USER-role onboarding still creates a wallet."""
    await handle_user_created(
        _payload("user@v.test", "user_clerk_user", role="USER")
    )

    created = await User.filter(email="user@v.test").first()
    assert created is not None
    assert created.role == UserRoleEnum.USER

    wallet = await Wallet.filter(user_id=created.id).first()
    assert wallet is not None, "USER must still get a wallet at signup"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role_str,role_enum",
    [
        ("ADMIN", UserRoleEnum.ADMIN),
        ("FRANCHISEE", UserRoleEnum.FRANCHISEE),
    ],
)
async def test_internal_role_skips_wallet_creation(client, role_str, role_enum):
    """ADMIN/FRANCHISEE onboarding must NOT create a wallet (ADR 0004)."""
    email = f"{role_str.lower()}@v.test"
    clerk_id = f"user_clerk_{role_str.lower()}"
    await handle_user_created(_payload(email, clerk_id, role=role_str))

    created = await User.filter(email=email).first()
    assert created is not None
    assert created.role == role_enum

    wallet = await Wallet.filter(user_id=created.id).first()
    assert wallet is None, (
        f"{role_str} must not get a wallet at signup — see ADR 0004. "
        "The internal-role runtime skip in WalletService is a defense; the "
        "creation gate is the prevention."
    )


@pytest.mark.asyncio
async def test_missing_role_defaults_to_user_and_gets_wallet(client):
    """Webhook payloads without `public_metadata.role` default to USER →
    wallet is created. Guards against an accidental skip caused by the
    role-string parsing path."""
    await handle_user_created(
        _payload("noroleneeded@v.test", "user_clerk_default", role=None)
    )

    created = await User.filter(email="noroleneeded@v.test").first()
    assert created is not None
    assert created.role == UserRoleEnum.USER
    wallet = await Wallet.filter(user_id=created.id).first()
    assert wallet is not None
