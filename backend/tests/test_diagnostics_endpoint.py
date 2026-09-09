"""Tests for the authenticated Diagnostic Bundle upload endpoint (ADR 0029).

Auth and S3 are patched so these run against a minimal ASGI app with no DB and
no AWS — keeping them outside the known cross-loop flake in the DB-backed suites.

The two behaviours most worth protecting are the ones whose failure is silent:
a 2xx must never be sent unless the object is durably in S3, and the Charger
Auth Key must never appear in a response.
"""
from __future__ import annotations

import base64
import gzip
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from routers import diagnostics

pytestmark = pytest.mark.anyio

CHARGER_ID = "8f14e45f-ceea-467a-9575-1f0f1a0f0a0b"
SECRET = "s3cr3t-charger-auth-key"
VALID_HEADER = "#VLTDIAG/1 boot=17 seq=42 first=100234 last=102301 overflow=0"
VALID_BODY = "\n".join([
    VALID_HEADER,
    "2026-08-18T03:12:44Z INFO  modem    registered on network, rssi=22",
    "2026-08-18T14:31:02Z ERROR relay    contactor feedback mismatch",
])


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(diagnostics.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    diagnostics._rate_limit_store.clear()
    yield
    diagnostics._rate_limit_store.clear()


def _bundle_row(s3_key="diagnostics/reserved/key.txt", archived_at=None):
    return SimpleNamespace(id=1, s3_key=s3_key, archived_at=archived_at,
                           ring_wrap_events=0, time_approximate=False,
                           first_utc=None, last_utc=None)


def _reserve(archived=False, key=None):
    """Stub `reserve_bundle`, echoing back the key the router computed.

    Echoing matters: the router archives to `bundle.s3_key`, so a stub with a
    fixed key would silently make every key assertion test the stub instead of
    the code.
    """
    async def _inner(**kw):
        return _bundle_row(s3_key=key or kw["s3_key"]), archived
    return AsyncMock(side_effect=_inner)


@pytest.fixture
def authed():
    """Patch auth, S3 and the bundle index to succeed. Yields the S3 mock."""
    charger = SimpleNamespace(id=3, charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "mark_archived", AsyncMock()), \
         patch.object(diagnostics.diagnostic_bundle_service, "reserve_bundle", _reserve()), \
         patch.object(diagnostics.storage_service, "upload_diagnostic_bundle_to_s3") as put:
        yield put


@pytest.fixture
def unauthed():
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=None)):
        yield


def _basic(user: str = CHARGER_ID, secret: str = SECRET) -> dict:
    token = base64.b64encode(f"{user}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

async def test_missing_credentials_are_rejected(client, unauthed):
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY)
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate", "").startswith("Basic")


async def test_bad_credentials_are_rejected(client, unauthed):
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY, headers=_basic())
    assert resp.status_code == 401


async def test_rejection_does_not_reveal_why(client, unauthed):
    """One uniform message, so the endpoint cannot be used to enumerate charger
    ids or distinguish 'unknown charger' from 'wrong key'."""
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY, headers=_basic())
    assert resp.json()["detail"] == "Invalid charger credentials"


async def test_auth_secret_never_appears_in_the_response(client, authed):
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY, headers=_basic())
    assert resp.status_code == 200
    assert SECRET not in resp.text


# --------------------------------------------------------------------------
# Durability — the 2xx contract
# --------------------------------------------------------------------------

async def test_successful_upload_is_archived_before_responding(client, authed):
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY, headers=_basic())
    assert resp.status_code == 200
    authed.assert_called_once()
    key, uploaded = authed.call_args[0]
    assert uploaded == VALID_BODY.encode()
    assert key.startswith(f"diagnostics/{CHARGER_ID}/")
    # Keyed on the content digest, not the header sequence: the firmware reuses
    # sequence numbers, so `-seq42` named several different objects at once.
    from services.diagnostic_markers import content_digest
    assert key.endswith(f"-{content_digest(VALID_BODY)[:8]}.txt")
    assert resp.json()["stored_key"] == key


async def test_archive_failure_returns_503_not_200(client):
    """The single most important test here. A 2xx tells the charger it may let
    those records be overwritten — so if S3 failed, the response must not be 2xx,
    or the data is lost from both sides at once."""
    charger = SimpleNamespace(id=3, charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "reserve_bundle", _reserve()), \
         patch.object(diagnostics.diagnostic_bundle_service, "mark_archived", AsyncMock()) as marked, \
         patch.object(diagnostics.storage_service, "upload_diagnostic_bundle_to_s3",
                      side_effect=RuntimeError("S3 down")):
        resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                 headers=_basic())
    assert resp.status_code == 503
    # The reservation row is left unarchived on purpose: invisible to the
    # duplicate check, so the charger re-sends rather than being told we hold
    # records that reached nowhere.
    marked.assert_not_called()


# --------------------------------------------------------------------------
# Body handling
# --------------------------------------------------------------------------

async def test_response_is_a_minimal_ack(client, authed):
    """The charger logs our response into its own ring buffer, which is then
    uploaded, producing another response that is logged again. Anything we put
    here consumes the exact resource this feature exists to conserve, so the
    response carries only what the charger needs to advance its delivered
    marker. Detail belongs in the server log — see ADR 0030."""
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                             headers=_basic())
    body = resp.json()
    assert set(body) == {"ok", "recorded", "stored_key"}
    assert body["ok"] is True
    assert len(resp.content) < 150          # was 659-711 bytes in the field


async def test_malformed_header_is_archived_anyway(client, authed):
    """A bundle we cannot parse is more useful stored than discarded."""
    resp = await client.post("/api/diagnostics/bundles",
                             content="not a header\nsome line", headers=_basic())
    assert resp.status_code == 200
    # The observable that matters: it reached S3 regardless of how it parsed.
    authed.assert_called_once()
    assert authed.call_args[0][1] == b"not a header\nsome line"


async def test_gzip_body_is_decompressed_and_stored_decoded(client, authed):
    packed = gzip.compress(VALID_BODY.encode())
    resp = await client.post("/api/diagnostics/bundles", content=packed,
                             headers={**_basic(), "Content-Encoding": "gzip"})
    assert resp.status_code == 200
    # The archive holds the decoded text, not the compressed bytes.
    assert authed.call_args[0][1] == VALID_BODY.encode()


async def test_oversize_body_is_rejected_before_archiving(client, authed, monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_BUNDLE_MAX_BYTES", "512")
    resp = await client.post("/api/diagnostics/bundles", content="x" * 900, headers=_basic())
    assert resp.status_code == 413
    authed.assert_not_called()


# --------------------------------------------------------------------------
# Rate limiting and the kill switch
# --------------------------------------------------------------------------

async def test_rate_limit_bounds_a_runaway_charger(client, authed):
    for _ in range(diagnostics._rate_limit_max()):
        assert (await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                  headers=_basic())).status_code == 200
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY, headers=_basic())
    assert resp.status_code == 429


async def test_disabled_endpoint_is_invisible(client, authed, monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_BUNDLE_ENABLED", "false")
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY, headers=_basic())
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# Loss accounting and redaction surfaced on the response
# --------------------------------------------------------------------------

async def test_duplicate_upload_is_reported_as_already_recorded(client):
    """A charger retrying after a lost response must get a success, so it can
    safely advance its delivered marker — not a second archive."""
    charger = SimpleNamespace(id=3, charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "mark_archived", AsyncMock()), \
         patch.object(diagnostics.diagnostic_bundle_service, "reserve_bundle",
                      _reserve(archived=True, key="diagnostics/original/key.txt")), \
         patch.object(diagnostics.storage_service, "upload_diagnostic_bundle_to_s3"):
        resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                 headers=_basic())
    assert resp.status_code == 200
    assert resp.json()["recorded"] is False


async def test_loss_counters_are_not_returned_to_the_charger(client):
    """Loss accounting is an operator concern, not a charger one.

    The charger cannot act on `overflow_delta` or `gap_records` — its only
    decision is whether to advance its delivered marker, which `recorded`
    answers. Sending them cost ring-buffer space for no behaviour (ADR 0030).
    """
    charger = SimpleNamespace(id=3, charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "mark_archived", AsyncMock()), \
         patch.object(diagnostics.diagnostic_bundle_service, "reserve_bundle", _reserve()), \
         patch.object(diagnostics.storage_service, "upload_diagnostic_bundle_to_s3"):
        body = (await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                  headers=_basic())).json()
    assert set(body) == {"ok", "recorded", "stored_key"}
    assert body["recorded"] is True


async def test_sensitive_content_is_redacted_before_it_reaches_s3(client, authed):
    """The archive keeps bundles for 90 days, so redaction must happen on the
    way in — not only on the search-index path."""
    dirty = VALID_HEADER + "\nI (11473) ATM90E26: Meter E: 12.34567 kWh"
    resp = await client.post("/api/diagnostics/bundles", content=dirty, headers=_basic())
    assert resp.status_code == 200
    stored = authed.call_args[0][1].decode()
    assert "12.34567" not in stored
    assert "[REDACTED]" in stored


async def test_a_resend_is_not_archived_a_second_time(client):
    """On a cellular link the common failure is a LOST RESPONSE, not a failed
    upload — the charger never sees the 2xx and re-sends. That retry must cost
    no second S3 object, and must return the key we already hold."""
    charger = SimpleNamespace(id=3, charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "reserve_bundle",
                      _reserve(archived=True, key="diagnostics/original/key.txt")), \
         patch.object(diagnostics.diagnostic_bundle_service, "mark_archived", AsyncMock()) as marked, \
         patch.object(diagnostics.storage_service, "upload_diagnostic_bundle_to_s3") as put:
        resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                 headers=_basic())

    assert resp.status_code == 200          # so the charger advances its marker
    body = resp.json()
    assert body["recorded"] is False
    assert body["stored_key"] == "diagnostics/original/key.txt"
    put.assert_not_called()                 # no redundant archive
    marked.assert_not_called()              # nothing to re-confirm


# --------------------------------------------------------------------------
# Content-hash identity (ADR 0030)
# --------------------------------------------------------------------------

async def test_duplicate_check_is_keyed_on_content_not_the_header(client, authed):
    """Pins the wiring the review caught.

    `reserve_bundle` must receive the digest of the *records*. Passing the
    parsed header instead reintroduces sequence-keyed identity, which the
    firmware defeats by reusing a sequence number across different bundles.
    """
    from services.diagnostic_markers import content_digest

    seen = {}
    async def spy(**kw):
        seen.update(kw)
        return _bundle_row(s3_key=kw["s3_key"]), False
    with patch.object(diagnostics.diagnostic_bundle_service, "mark_archived", AsyncMock()), \
         patch.object(diagnostics.diagnostic_bundle_service, "reserve_bundle",
                      AsyncMock(side_effect=spy)):
        resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                 headers=_basic())
    assert resp.status_code == 200
    assert seen["content_sha256"] == content_digest(VALID_BODY)
    assert len(seen["content_sha256"]) == 64


async def test_a_moving_header_does_not_make_a_retry_look_new(client, authed):
    """Two uploads whose records are identical but whose header `last=` moved —
    the exact shape of the three real staging retries — must present the same
    identity to the duplicate check."""
    from services.diagnostic_markers import content_digest

    body_a = "#VLTDIAG/1 boot=55 seq=2 first=15207 last=15381 overflow=0\nI (1) a: rec"
    body_b = "#VLTDIAG/1 boot=55 seq=2 first=15207 last=15433 overflow=0\nI (1) a: rec"

    seen = []
    async def spy(**kw):
        seen.append(kw["content_sha256"])
        return _bundle_row(s3_key=kw["s3_key"]), False
    with patch.object(diagnostics.diagnostic_bundle_service, "mark_archived", AsyncMock()), \
         patch.object(diagnostics.diagnostic_bundle_service, "reserve_bundle",
                      AsyncMock(side_effect=spy)):
        for body in (body_a, body_b):
            diagnostics._rate_limit_store.clear()
            await client.post("/api/diagnostics/bundles", content=body, headers=_basic())

    assert body_a != body_b
    assert len(set(seen)) == 1
    assert seen[0] == content_digest(body_a)


async def test_the_stored_digest_is_taken_before_redaction(client, authed):
    """Identity must not move when our redaction policy moves."""
    from services.diagnostic_markers import content_digest

    dirty = VALID_HEADER + "\nI (11473) ATM90E26: Meter E: 12.34567 kWh"
    recorded = _reserve()
    with patch.object(diagnostics.diagnostic_bundle_service, "mark_archived", AsyncMock()), \
         patch.object(diagnostics.diagnostic_bundle_service, "reserve_bundle", recorded):
        await client.post("/api/diagnostics/bundles", content=dirty, headers=_basic())

    # What reached S3 is redacted...
    assert "12.34567" not in authed.call_args[0][1].decode()
    # ...but the identity is of what the charger actually sent.
    assert recorded.call_args.kwargs["content_sha256"] == content_digest(dirty)
