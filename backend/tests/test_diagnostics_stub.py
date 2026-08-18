"""Tests for the Diagnostic Bundle upload stub (ADR 0029).

The stub touches no database, so these run against a minimal ASGI app holding
only the router — no Tortoise, no Redis, no event-loop sharing. That keeps them
outside the known cross-loop flake in the DB-backed suites.

What is worth asserting on a throwaway probe: that it stays invisible when
disabled, that it never echoes the Charger Auth Key, that an attacker-controlled
username cannot escape the dump directory, and that the diagnostics it reports
back are actually correct — because the firmware team will debug against them.
"""
from __future__ import annotations

import gzip

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from routers import diagnostics

pytestmark = pytest.mark.anyio

VALID_HEADER = "#VLTDIAG/1 boot=17 seq=42 first=100234 last=102301 overflow=0"
VALID_BODY = "\n".join([
    VALID_HEADER,
    "2026-08-18T03:12:44Z INFO  modem    registered on network, rssi=22",
    "2026-08-18T03:12:51Z INFO  ocpp     BootNotification accepted",
    "2026-08-18T14:31:02Z ERROR relay    contactor feedback mismatch",
])
CHARGER_ID = "8f14e45f-ceea-467a-9575-1f0f1a0f0a0b"
SECRET = "s3cr3t-charger-auth-key"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(diagnostics.router)
    return application


@pytest.fixture
async def client(app) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def stub_env(monkeypatch, tmp_path):
    """Enable the stub and point its dump directory at a tmp dir."""
    monkeypatch.setenv("DIAGNOSTIC_BUNDLE_STUB_ENABLED", "true")
    monkeypatch.setenv("DIAGNOSTIC_BUNDLE_DUMP_DIR", str(tmp_path))
    monkeypatch.setenv("DIAGNOSTIC_BUNDLE_MAX_BYTES", "4096")
    monkeypatch.setenv("DIAGNOSTIC_BUNDLE_KEEP", "3")
    return tmp_path


def _basic(user: str = CHARGER_ID, secret: str = SECRET) -> dict:
    import base64
    token = base64.b64encode(f"{user}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def test_disabled_stub_is_invisible(client, monkeypatch):
    """A disabled stub 404s rather than advertising itself — it must never be
    reachable on production, where it would be an unauthenticated write target."""
    monkeypatch.setenv("DIAGNOSTIC_BUNDLE_STUB_ENABLED", "false")
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY, headers=_basic())
    assert resp.status_code == 404


async def test_valid_bundle_is_accepted_and_parsed(client, stub_env):
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY, headers=_basic())
    assert resp.status_code == 200
    body = resp.json()

    assert body["ok"] is True
    assert body["received_bytes"] == len(VALID_BODY.encode())
    assert body["record_count"] == 3          # 4 lines minus the header line
    assert body["header_valid"] is True
    assert body["header"] == {
        "boot": 17, "seq": 42, "first": 100234, "last": 102301, "overflow": 0,
    }
    assert body["auth_username"] == CHARGER_ID
    assert body["warnings"] == []

    stored = list(stub_env.glob("*.txt"))
    assert len(stored) == 1
    assert stored[0].read_text() == VALID_BODY


async def test_auth_secret_is_never_echoed(client):
    """The password half is the Charger Auth Key. ADR 0029 requires it stay out
    of every response and log line."""
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY, headers=_basic())
    assert SECRET not in resp.text


async def test_username_cannot_escape_the_dump_directory(client, stub_env):
    """`username` is attacker-controlled; it must be slugged before it reaches
    the filesystem."""
    resp = await client.post(
        "/api/diagnostics/bundles",
        content=VALID_BODY,
        headers=_basic(user="../../../../etc/passwd"),
    )
    assert resp.status_code == 200
    stored = list(stub_env.glob("*.txt"))
    assert len(stored) == 1
    assert stored[0].parent == stub_env
    assert "/" not in stored[0].name


async def test_missing_auth_is_warned_not_rejected(client):
    """The stub authenticates nothing — but it must report a missing header, so
    we learn whether the firmware's HTTP client can set one at all."""
    resp = await client.post("/api/diagnostics/bundles", content=VALID_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_username"] is None
    assert any("no Authorization header" in w for w in body["warnings"])


async def test_malformed_header_is_reported(client):
    resp = await client.post(
        "/api/diagnostics/bundles",
        content="not a bundle header\nsome log line",
        headers=_basic(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["header_valid"] is False
    assert any("is not a #VLTDIAG/1 header" in w for w in body["warnings"])


async def test_header_with_non_integer_field_is_reported(client):
    bad = VALID_HEADER.replace("seq=42", "seq=abc")
    resp = await client.post("/api/diagnostics/bundles", content=bad, headers=_basic())
    body = resp.json()
    assert body["header_valid"] is False
    assert any("seq='abc' is not an integer" in w for w in body["warnings"])


async def test_gzip_body_is_decompressed(client, stub_env):
    """Compression is optional in the spec; if firmware uses it, the stub has to
    prove the round trip works."""
    packed = gzip.compress(VALID_BODY.encode())
    resp = await client.post(
        "/api/diagnostics/bundles",
        content=packed,
        headers={**_basic(), "Content-Encoding": "gzip"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["received_bytes"] == len(packed)
    assert body["decoded_bytes"] == len(VALID_BODY.encode())
    assert body["record_count"] == 3
    assert body["warnings"] == []
    assert list(stub_env.glob("*.txt"))[0].read_text() == VALID_BODY


async def test_body_over_limit_is_rejected(client):
    resp = await client.post(
        "/api/diagnostics/bundles",
        content="x" * 5000,          # limit is 4096 in the fixture
        headers=_basic(),
    )
    assert resp.status_code == 413


async def test_dump_directory_is_pruned(client, stub_env):
    """A test run must not be able to fill the staging disk."""
    for seq in range(6):
        await client.post(
            "/api/diagnostics/bundles",
            content=VALID_HEADER.replace("seq=42", f"seq={seq}") + "\nline",
            headers=_basic(),
        )
    assert len(list(stub_env.glob("*.txt"))) == 3   # DIAGNOSTIC_BUNDLE_KEEP=3


async def test_non_utf8_body_is_reported_not_fatal(client):
    resp = await client.post(
        "/api/diagnostics/bundles",
        content=b"\xff\xfe binary garbage",
        headers=_basic(),
    )
    assert resp.status_code == 200
    assert any("not valid UTF-8" in w for w in resp.json()["warnings"])


# ---------------------------------------------------------------------------
# S3 key construction (pure function — no AWS needed)
# ---------------------------------------------------------------------------

def test_s3_key_is_per_charger_and_date_partitioned():
    from datetime import datetime, timezone
    from services import storage_service

    key = storage_service.build_diagnostic_bundle_s3_key(
        CHARGER_ID, datetime(2026, 8, 18, 3, 12, 44, 123456, tzinfo=timezone.utc), 42
    )
    assert key.startswith(f"diagnostics/{CHARGER_ID}/2026/08/18/")
    assert key.endswith("-seq42.txt")


def test_s3_key_slugs_untrusted_charger_id():
    """charger_id comes from the Authorization header — it must never be able to
    inject extra path segments into the bucket layout."""
    from datetime import datetime, timezone
    from services import storage_service

    key = storage_service.build_diagnostic_bundle_s3_key(
        "../../etc/passwd", datetime(2026, 8, 18, tzinfo=timezone.utc), "1; DROP"
    )
    charger_segment = key.split("/")[1]
    assert ".." not in charger_segment
    assert key.count("/") == 5          # diagnostics/<charger>/YYYY/MM/DD/<file>


def test_s3_key_handles_missing_sequence():
    from datetime import datetime, timezone
    from services import storage_service

    key = storage_service.build_diagnostic_bundle_s3_key(
        CHARGER_ID, datetime(2026, 8, 18, tzinfo=timezone.utc), None
    )
    assert key.endswith("-seqna.txt")
