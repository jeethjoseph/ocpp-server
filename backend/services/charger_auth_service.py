"""Charger Auth Key — the per-unit machine credential from ADR 0020.

The server generates a 20-byte key, stores only its SHA-256, and reveals the
plaintext exactly once. A lost key is rotated, never recovered.

SHA-256 rather than bcrypt/argon2 is deliberate and documented in ADR 0020: the
secret is high-entropy machine-generated, not a human password, so a fast hash
is both sufficient against brute force and cheap enough to check on every
reconnect across a fleet of flaky-modem chargers.

**Consumers.** Diagnostic Bundle upload (ADR 0029) is the first and currently
only consumer. The OCPP WebSocket handshake does NOT use this yet — ADR 0020
remains PROPOSED and chargers still connect unauthenticated. This module is
deliberately transport-agnostic so the handshake can adopt it unchanged.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import secrets
from typing import Optional

logger = logging.getLogger(__name__)

KEY_BYTES = 20


def generate_auth_key() -> str:
    """Mint a new plaintext Charger Auth Key. Returned once, never stored."""
    return secrets.token_urlsafe(KEY_BYTES)


def hash_auth_key(plaintext: str) -> str:
    """SHA-256 hex digest — what actually goes in `Charger.auth_key_hash`."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def verify_auth_key(plaintext: str, stored_hash: Optional[str]) -> bool:
    """Constant-time comparison of a presented key against a stored hash.

    `hmac.compare_digest` rather than `==` so comparison time cannot leak how
    much of the hash matched. A null stored hash always fails: an unprovisioned
    charger is rejected, never waved through.
    """
    if not stored_hash or not plaintext:
        return False
    return hmac.compare_digest(hash_auth_key(plaintext), stored_hash)


def parse_basic_auth(header: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split an HTTP Basic `Authorization` header into (username, secret).

    Returns `(None, None)` for anything malformed rather than raising, so the
    caller answers with one uniform rejection and cannot leak, through differing
    error responses, whether a username exists.
    """
    if not header or not header.startswith("Basic "):
        return None, None
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None, None
    username, sep, secret = decoded.partition(":")
    if not sep or not username or not secret:
        return None, None
    return username, secret


async def authenticate_charger(header: Optional[str]):
    """Resolve an `Authorization` header to a `Charger`, or None.

    The username MUST equal the charger's `charge_point_string_id`, matching the
    rule ADR 0020 sets for the WSS handshake, so one credential works unchanged
    across both transports.

    Never logs the secret — only the claimed identity and the outcome.
    """
    from models import Charger

    username, secret = parse_basic_auth(header)
    if not username:
        return None

    charger = await Charger.filter(charge_point_string_id=username).first()
    if charger is None:
        logger.warning("🔑 Auth failed: no charger with id %s", username)
        return None
    if not charger.auth_key_hash:
        logger.warning("🔑 Auth failed: charger %s has no auth key provisioned", username)
        return None
    if not verify_auth_key(secret, charger.auth_key_hash):
        logger.warning("🔑 Auth failed: bad key for charger %s", username)
        return None
    return charger
