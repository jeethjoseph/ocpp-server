"""Staging stub for Diagnostic Bundle upload — see ADR 0029.

This is deliberately NOT the real endpoint. It authenticates nothing and indexes
nothing. Its only job is to prove, before we build the real thing, that the
charger's HTTP client can reach us over TLS and send what the firmware spec says
it will send.

It answers five questions per upload:
  1. Did the POST arrive at all, over the production Let's Encrypt chain?
  2. Can the firmware's HTTP client set an Authorization header?
  3. Did the body survive intact (byte count, UTF-8, line count)?
  4. Is the `#VLTDIAG/1` header line well-formed?
  5. What exactly arrived — the body is stored so it can be diffed against
     what firmware believes it sent.

And — read from the OCPP side rather than here — whether the WSS connection
dropped during the upload, which is how we determine the modem class without
anyone reading a datasheet.

Disabled unless DIAGNOSTIC_BUNDLE_STUB_ENABLED=true, so it can never be reachable
on production. Delete this module when the real endpoint lands.
"""
import asyncio
import base64
import gzip
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from services import storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics Stub"])

BUNDLE_MAGIC = "#VLTDIAG/1"
_HEADER_INT_FIELDS = ("boot", "seq", "first", "last", "overflow")
_BODY_PREVIEW_CHARS = 200
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]")

# Local-disk fallback, used only when no diagnostics bucket is configured (dev,
# or a staging box without AWS creds). S3 is the real destination.
_DEFAULT_DUMP_DIR = "/tmp/diag_bundles"


def _stub_enabled() -> bool:
    return os.getenv("DIAGNOSTIC_BUNDLE_STUB_ENABLED", "false").strip().lower() == "true"


def _max_bytes() -> int:
    return int(os.getenv("DIAGNOSTIC_BUNDLE_MAX_BYTES", str(2 * 1024 * 1024)))


def _dump_dir() -> str:
    return os.getenv("DIAGNOSTIC_BUNDLE_DUMP_DIR", _DEFAULT_DUMP_DIR).strip()


def _keep_count() -> int:
    return int(os.getenv("DIAGNOSTIC_BUNDLE_KEEP", "200"))


def _safe_slug(value: Optional[str], fallback: str = "unknown") -> str:
    """Sanitise an untrusted header value for use in a filename.

    `username` arrives in the Authorization header and is entirely attacker-
    controlled, so it never reaches the filesystem unfiltered — same rule the
    real endpoint applies to charger-reported filenames.
    """
    if not value:
        return fallback
    return (_SLUG_RE.sub("_", value)[:48]) or fallback


def _prune(directory: Path, keep: int) -> None:
    """Keep only the newest `keep` dumps so a test run cannot fill the disk."""
    dumps = sorted(directory.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in dumps[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def _persist_to_disk(body: bytes, username: Optional[str], header: dict) -> tuple[Optional[str], list[str]]:
    """Local-disk fallback for when no diagnostics bucket is configured."""
    target = _dump_dir()
    if not target:
        return None, []
    try:
        directory = Path(target)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"{stamp}-{_safe_slug(username, 'noauth')}-seq{_safe_slug(str(header.get('seq')), 'na')}.txt"
        path = directory / name
        path.write_bytes(body)
        _prune(directory, _keep_count())
        return str(path), []
    except Exception as exc:
        return None, [f"could not persist bundle to disk ({exc})"]


async def _persist_bundle(body: bytes, username: Optional[str], header: dict) -> tuple[Optional[str], list[str]]:
    """Persist the decoded body so it can be diffed against what firmware sent.

    S3 when a diagnostics bucket is configured, local disk otherwise — the same
    S3-or-disk branching the firmware uploader uses. A persistence failure is
    reported as a warning and never as an upload failure: a storage problem here
    must not look to the charger like a transport problem, which is the one thing
    this probe exists to measure.
    """
    bucket = storage_service.diagnostics_bucket()
    if not bucket:
        return _persist_to_disk(body, username, header)
    try:
        key = storage_service.build_diagnostic_bundle_s3_key(
            username, datetime.now(timezone.utc), header.get("seq")
        )
        # boto3 is synchronous — off the event loop, as firmware.py does.
        await asyncio.to_thread(storage_service.upload_diagnostic_bundle_to_s3, key, body)
        return f"s3://{bucket}/{key}", []
    except Exception as exc:
        path, disk_warnings = _persist_to_disk(body, username, header)
        return path, [f"S3 upload failed ({exc}) — fell back to local disk"] + disk_warnings


def _describe_auth(header: Optional[str]) -> tuple[Optional[str], list[str]]:
    """Return (username, warnings). NEVER returns or logs the secret.

    The password half is the Charger Auth Key. ADR 0029 requires it stay out of
    logs entirely, so it is decoded only far enough to confirm it is non-empty
    and then discarded.
    """
    if not header:
        return None, ["no Authorization header — firmware must send HTTP Basic"]
    if not header.startswith("Basic "):
        return None, [f"Authorization is not Basic (got {header.split(' ', 1)[0]!r})"]
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except Exception:
        return None, ["Authorization header is not valid base64/UTF-8"]
    username, sep, secret = decoded.partition(":")
    warnings = []
    if not sep:
        warnings.append("Authorization has no ':' separator")
    elif not secret:
        warnings.append("Authorization carries an empty password")
    return username or None, warnings


def _parse_bundle_header(first_line: str) -> tuple[dict, list[str]]:
    """Parse the `#VLTDIAG/1 boot=.. seq=..` line. Returns (fields, warnings)."""
    tokens = first_line.split()
    if not tokens or tokens[0] != BUNDLE_MAGIC:
        got = tokens[0] if tokens else "<empty>"
        return {}, [f"first line is not a {BUNDLE_MAGIC} header (got {got!r})"]

    fields: dict = {}
    warnings: list[str] = []
    for token in tokens[1:]:
        key, sep, value = token.partition("=")
        if not sep:
            warnings.append(f"malformed header token {token!r}")
            continue
        fields[key] = value

    for name in _HEADER_INT_FIELDS:
        if name not in fields:
            warnings.append(f"header is missing {name}=")
            continue
        try:
            fields[name] = int(fields[name])
        except ValueError:
            warnings.append(f"header field {name}={fields[name]!r} is not an integer")
    return fields, warnings


def _decode_body(raw: bytes, content_encoding: Optional[str]) -> tuple[bytes, list[str]]:
    """Gunzip if the charger declared gzip. Returns (decoded, warnings)."""
    if (content_encoding or "").strip().lower() != "gzip":
        return raw, []
    try:
        return gzip.decompress(raw), []
    except Exception as exc:
        return raw, [f"Content-Encoding: gzip declared but body did not decompress ({exc})"]


@router.post("/bundles")
async def receive_bundle(request: Request):
    """Accept a Diagnostic Bundle and report back exactly what arrived."""
    if not _stub_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    limit = _max_bytes()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail=f"Body exceeds {limit} bytes")

    raw = await request.body()
    if len(raw) > limit:
        raise HTTPException(status_code=413, detail=f"Body exceeds {limit} bytes")

    username, warnings = _describe_auth(request.headers.get("authorization"))
    body, decode_warnings = _decode_body(raw, request.headers.get("content-encoding"))
    warnings += decode_warnings

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")
        warnings.append("body is not valid UTF-8 — decoded with replacement characters")

    lines = text.splitlines()
    header, header_warnings = _parse_bundle_header(lines[0] if lines else "")
    warnings += header_warnings

    stored_path, store_warnings = await _persist_bundle(body, username, header)
    warnings += store_warnings

    result = {
        "ok": True,
        "received_bytes": len(raw),
        "decoded_bytes": len(body),
        "content_encoding": request.headers.get("content-encoding"),
        "content_type": request.headers.get("content-type"),
        "user_agent": request.headers.get("user-agent"),
        "client_ip": request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else None
        ),
        "auth_username": username,
        "record_count": max(len(lines) - 1, 0),
        "header": header,
        "header_valid": not header_warnings,
        "body_preview": text[:_BODY_PREVIEW_CHARS],
        "stored_path": stored_path,
        "warnings": warnings,
    }

    # This line is the durable record of the attempt: staging backend logs are
    # already forwarded to New Relic, so every upload is queryable there without
    # shelling onto the box.
    logger.info(
        "📟 Diagnostic Bundle stub: charger=%s bytes=%s decoded=%s records=%s "
        "header=%s stored=%s warnings=%s",
        username, len(raw), len(body), result["record_count"],
        header or "<none>", stored_path or "<none>", warnings or "none",
    )
    return result
