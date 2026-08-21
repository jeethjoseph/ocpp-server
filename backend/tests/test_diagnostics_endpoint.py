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


def _bundle_row(epoch=0, overflow_delta=0, gap_records=0):
    return SimpleNamespace(epoch=epoch, overflow_delta=overflow_delta,
                           gap_records=gap_records)


@pytest.fixture
def authed():
    """Patch auth, S3 and the bundle index to succeed. Yields the S3 mock."""
    charger = SimpleNamespace(charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "find_duplicate",
                      AsyncMock(return_value=None)), \
         patch.object(diagnostics.diagnostic_bundle_service, "record_bundle",
                      AsyncMock(return_value=(_bundle_row(), True))), \
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
    assert key.endswith("-seq42.txt")
    assert resp.json()["stored_key"] == key


async def test_archive_failure_returns_503_not_200(client):
    """The single most important test here. A 2xx tells the charger it may let
    those records be overwritten — so if S3 failed, the response must not be 2xx,
    or the data is lost from both sides at once."""
    charger = SimpleNamespace(charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "find_duplicate",
                      AsyncMock(return_value=None)), \
         patch.object(diagnostics.storage_service, "upload_diagnostic_bundle_to_s3",
                      side_effect=RuntimeError("S3 down")):
        resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                 headers=_basic())
    assert resp.status_code == 503


# --------------------------------------------------------------------------
# Body handling
# --------------------------------------------------------------------------

async def test_header_is_parsed_and_lines_counted(client, authed):
    body = (await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                              headers=_basic())).json()
    assert body["header"] == {
        "boot": 17, "seq": 42, "first": 100234, "last": 102301, "overflow": 0}
    assert body["header_valid"] is True
    assert body["line_count"] == 2          # 3 lines minus the header line
    assert body["warnings"] == []


async def test_malformed_header_is_archived_anyway(client, authed):
    """A bundle we cannot parse is more useful stored than discarded."""
    resp = await client.post("/api/diagnostics/bundles",
                             content="not a header\nsome line", headers=_basic())
    assert resp.status_code == 200
    assert resp.json()["header_valid"] is False
    authed.assert_called_once()


async def test_gzip_body_is_decompressed_and_stored_decoded(client, authed):
    packed = gzip.compress(VALID_BODY.encode())
    resp = await client.post("/api/diagnostics/bundles", content=packed,
                             headers={**_basic(), "Content-Encoding": "gzip"})
    body = resp.json()
    assert body["received_bytes"] == len(packed)
    assert body["decoded_bytes"] == len(VALID_BODY.encode())
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
    charger = SimpleNamespace(charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "find_duplicate",
                      AsyncMock(return_value=None)), \
         patch.object(diagnostics.diagnostic_bundle_service, "record_bundle",
                      AsyncMock(return_value=(_bundle_row(), False))), \
         patch.object(diagnostics.storage_service, "upload_diagnostic_bundle_to_s3"):
        resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                 headers=_basic())
    assert resp.status_code == 200
    assert resp.json()["recorded"] is False


async def test_loss_counters_are_returned_to_the_charger(client):
    charger = SimpleNamespace(charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "find_duplicate",
                      AsyncMock(return_value=None)), \
         patch.object(diagnostics.diagnostic_bundle_service, "record_bundle",
                      AsyncMock(return_value=(_bundle_row(epoch=2, overflow_delta=500,
                                                          gap_records=39), True))), \
         patch.object(diagnostics.storage_service, "upload_diagnostic_bundle_to_s3"):
        body = (await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                  headers=_basic())).json()
    assert (body["epoch"], body["overflow_delta"], body["gap_records"]) == (2, 500, 39)
    # Fan-out is scheduled, never awaited — see the latency note in the router.
    assert body["fanout"] == "scheduled"


async def test_sensitive_content_is_redacted_before_it_reaches_s3(client, authed):
    """The archive keeps bundles for 90 days, so redaction must happen on the
    way in — not only on the search-index path."""
    dirty = VALID_HEADER + "\nI (11473) ATM90E26: Meter E: 12.34567 kWh"
    resp = await client.post("/api/diagnostics/bundles", content=dirty, headers=_basic())
    assert resp.status_code == 200
    stored = authed.call_args[0][1].decode()
    assert "12.34567" not in stored
    assert "[REDACTED]" in stored
    assert any("redaction applied" in w for w in resp.json()["warnings"])


async def test_a_resend_is_not_archived_a_second_time(client):
    """On a cellular link the common failure is a LOST RESPONSE, not a failed
    upload — the charger never sees the 2xx and re-sends. That retry must cost
    no second S3 object, and must return the key we already hold."""
    charger = SimpleNamespace(charge_point_string_id=CHARGER_ID, auth_key_hash="x" * 64)
    already = SimpleNamespace(bundle_seq=42, epoch=0, overflow_delta=0, gap_records=0,
                              s3_key="diagnostics/original/key.txt")
    with patch.object(diagnostics.charger_auth_service, "authenticate_charger",
                      AsyncMock(return_value=charger)), \
         patch.object(diagnostics.diagnostic_bundle_service, "find_duplicate",
                      AsyncMock(return_value=already)), \
         patch.object(diagnostics.storage_service, "upload_diagnostic_bundle_to_s3") as put:
        resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY,
                                 headers=_basic())

    assert resp.status_code == 200          # so the charger advances its marker
    body = resp.json()
    assert body["recorded"] is False
    assert body["stored_key"] == "diagnostics/original/key.txt"
    put.assert_not_called()                 # no redundant archive
