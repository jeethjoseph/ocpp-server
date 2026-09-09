"""Tests for the Charger Auth Key primitives (ADR 0020).

These are the pure functions — no DB, no HTTP. `authenticate_charger` is
exercised through the endpoint tests instead, where the DB interaction matters.
"""
from __future__ import annotations

import base64
import hashlib

from services import charger_auth_service as svc


def test_generated_keys_are_unique_and_high_entropy():
    keys = {svc.generate_auth_key() for _ in range(50)}
    assert len(keys) == 50
    # 20 random bytes, urlsafe-base64 encoded — always comfortably over 20 chars.
    assert all(len(k) >= 20 for k in keys)


def test_hash_is_plain_sha256_hex():
    """The hash format is load-bearing: the column is CHAR(64) and ADR 0020
    commits to SHA-256, so a change here is a schema and migration concern."""
    assert svc.hash_auth_key("hunter2") == hashlib.sha256(b"hunter2").hexdigest()
    assert len(svc.hash_auth_key("x")) == 64


def test_verify_accepts_the_right_key_and_rejects_others():
    key = svc.generate_auth_key()
    stored = svc.hash_auth_key(key)
    assert svc.verify_auth_key(key, stored) is True
    assert svc.verify_auth_key(key + "x", stored) is False
    assert svc.verify_auth_key("", stored) is False


def test_verify_fails_closed_on_an_unprovisioned_charger():
    """A null hash must never be treated as 'no key required'."""
    assert svc.verify_auth_key("anything", None) is False
    assert svc.verify_auth_key("anything", "") is False


def _basic(raw: str) -> str:
    return "Basic " + base64.b64encode(raw.encode()).decode()


def test_parse_basic_auth_happy_path():
    assert svc.parse_basic_auth(_basic("charger-1:secret")) == ("charger-1", "secret")


def test_parse_basic_auth_returns_none_for_every_malformed_shape():
    """Malformed input yields (None, None) rather than raising, so the caller
    answers with one uniform 401 and cannot leak which part was wrong."""
    for header in [
        None,
        "",
        "Bearer abc",                       # wrong scheme
        "Basic !!!not-base64!!!",
        _basic("no-colon-here"),            # missing separator
        _basic(":secret-only"),             # empty username
        _basic("user-only:"),               # empty secret
    ]:
        assert svc.parse_basic_auth(header) == (None, None), header


def test_password_containing_a_colon_survives_parsing():
    """`partition` splits on the FIRST colon — a key containing one must not be
    silently truncated."""
    user, secret = svc.parse_basic_auth(_basic("charger-1:se:cr:et"))
    assert (user, secret) == ("charger-1", "se:cr:et")
