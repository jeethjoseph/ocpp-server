"""
Firmware Storage Service

Primary storage is S3 with presigned GET URLs (TTL spans the firmware retry
window). Legacy fallback: rows with no s3_key still resolve via the local
filesystem mount at /firmware. The historical-file migration script moves
those into S3 and clears the fallback.
"""

import logging
import os
import hashlib
import re
from functools import lru_cache
from typing import BinaryIO, Optional

import boto3
from botocore.config import Config
from fastapi import UploadFile

logger = logging.getLogger("ocpp-server")

# Get the base directory for firmware storage (legacy local path)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE_DIR = os.path.join(BASE_DIR, "firmware_files")

# Ensure firmware directory exists (legacy fallback only — new uploads go to S3)
os.makedirs(FIRMWARE_DIR, exist_ok=True)


# ============ S3 storage ============

def _firmware_bucket() -> str:
    bucket = os.getenv("AWS_S3_FIRMWARE_BUCKET")
    if not bucket:
        raise RuntimeError("AWS_S3_FIRMWARE_BUCKET is not configured")
    return bucket


@lru_cache(maxsize=1)
def _s3_client():
    region = os.getenv("AWS_REGION", "ap-south-1")
    profile = os.getenv("AWS_PROFILE")
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client(
        "s3",
        region_name=region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def _presign_ttl() -> int:
    """Presigned URL TTL — must span the retry window so a URL handed out at
    attempt 1 is still valid when attempt 5 fires hours later."""
    base_floor = 24 * 3600  # 24h floor
    margin = 3600           # +1h margin
    try:
        max_elapsed = int(os.getenv("FIRMWARE_MAX_ELAPSED_SECONDS", "21600"))
    except ValueError:
        max_elapsed = 21600
    return max(max_elapsed, base_floor) + margin


def upload_firmware_to_s3(s3_key: str, file_bytes: bytes, content_type: str = "application/octet-stream") -> None:
    """Upload firmware bytes to S3 at the given key."""
    _s3_client().put_object(
        Bucket=_firmware_bucket(),
        Key=s3_key,
        Body=file_bytes,
        ContentType=content_type,
        ServerSideEncryption="AES256",
    )
    logger.info("📦 Uploaded firmware to s3://%s/%s (%d bytes)", _firmware_bucket(), s3_key, len(file_bytes))


def generate_firmware_presigned_url(s3_key: str, expires_in: Optional[int] = None) -> str:
    """Generate a presigned GET URL for a firmware blob in S3."""
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _firmware_bucket(), "Key": s3_key},
        ExpiresIn=expires_in or _presign_ttl(),
    )


def build_firmware_s3_key(version: str, filename: str) -> str:
    """S3 key for a firmware blob: firmware/{version}/{filename}."""
    safe_version = "".join(c if c.isalnum() or c in "._-" else "_" for c in version)
    safe_filename = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
    return f"firmware/{safe_version}/{safe_filename}"


# ============ Diagnostic Bundles (ADR 0029) ============
#
# A separate bucket from firmware, deliberately: Bundles carry a 90-day
# lifecycle rule where firmware images are kept indefinitely, and they may
# contain charger-side PII, so they warrant their own access policy.


def diagnostics_bucket() -> Optional[str]:
    """Configured Diagnostic Bundle bucket, or None when S3 is not wired up.

    Returns None rather than raising so callers can fall back to local disk,
    matching the firmware uploader's S3-or-disk branching.
    """
    return os.getenv("AWS_S3_DIAGNOSTICS_BUCKET") or None


def build_diagnostic_bundle_s3_key(charger_id: str, received_at, bundle_seq) -> str:
    """S3 key for a Bundle: diagnostics/{charger}/{YYYY}/{MM}/{DD}/{stamp}-seq{n}.txt

    Per-charger, date-partitioned, as specified in ADR 0029. `charger_id` is
    slugged because it originates in an untrusted request header.
    """
    safe_charger = "".join(c if c.isalnum() or c in "._-" else "_" for c in (charger_id or "unknown"))[:64]
    # Collapse dot runs so a hostile charger_id can never yield a ".." segment.
    # Harmless in S3 (keys are flat strings) but not once a key is used as a
    # local filename on download — see ADR 0029 on not trusting charger input.
    safe_charger = re.sub(r"\.{2,}", "_", safe_charger).strip(".") or "unknown"
    safe_seq = "".join(c if c.isalnum() else "_" for c in str(bundle_seq if bundle_seq is not None else "na"))[:16]
    stamp = received_at.strftime("%Y%m%dT%H%M%S%fZ")
    return (
        f"diagnostics/{safe_charger or 'unknown'}/{received_at:%Y/%m/%d}/"
        f"{stamp}-seq{safe_seq}.txt"
    )


def upload_diagnostic_bundle_to_s3(s3_key: str, body: bytes) -> None:
    """Upload a Diagnostic Bundle body to the diagnostics bucket."""
    bucket = diagnostics_bucket()
    if not bucket:
        raise RuntimeError("AWS_S3_DIAGNOSTICS_BUCKET is not configured")
    _s3_client().put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=body,
        ContentType="text/plain; charset=utf-8",
        ServerSideEncryption="AES256",
    )
    logger.info("📟 Uploaded diagnostic bundle to s3://%s/%s (%d bytes)", bucket, s3_key, len(body))


# ============ Checksums ============


def calculate_checksum(file_path: str) -> str:
    """
    Calculate MD5 checksum of a file

    Args:
        file_path: Path to the file

    Returns:
        MD5 checksum as hex string
    """
    md5_hash = hashlib.md5()

    with open(file_path, "rb") as f:
        # Read file in chunks to handle large files
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)

    return md5_hash.hexdigest()


def calculate_checksum_from_bytes(file_content: bytes) -> str:
    """
    Calculate MD5 checksum from bytes

    Args:
        file_content: File content as bytes

    Returns:
        MD5 checksum as hex string
    """
    md5_hash = hashlib.md5()
    md5_hash.update(file_content)
    return md5_hash.hexdigest()


async def save_firmware_file(file: UploadFile, version: str) -> dict:
    """
    Save uploaded firmware file to local storage

    Args:
        file: Uploaded file from FastAPI
        version: Firmware version string

    Returns:
        dict with file_path, file_size, checksum, filename
    """
    # Create safe filename: version_originalname
    safe_filename = f"{version}_{file.filename}"
    file_path = os.path.join(FIRMWARE_DIR, safe_filename)

    # Read file content
    file_content = await file.read()

    # Write to disk
    with open(file_path, "wb") as f:
        f.write(file_content)

    # Calculate checksum and size
    file_size = len(file_content)
    checksum = calculate_checksum_from_bytes(file_content)

    return {
        "file_path": file_path,
        "filename": safe_filename,
        "file_size": file_size,
        "checksum": checksum
    }


def delete_firmware_file(file_path: str) -> bool:
    """
    Delete firmware file from filesystem

    Args:
        file_path: Path to the file

    Returns:
        True if deleted, False if file doesn't exist
    """
    if os.path.exists(file_path):
        os.remove(file_path)
        return True
    return False


def get_firmware_download_url(filename: str, base_url: str) -> str:
    """Legacy: build the local-mount URL for a firmware filename.

    Only used for FirmwareFile rows with no s3_key (pre-migration uploads).
    New code paths should call get_firmware_download_url_for_file() instead,
    which prefers S3 presigned URLs.
    """
    base_url = base_url.rstrip('/')
    return f"{base_url}/firmware/{filename}"


def get_firmware_download_url_for_file(firmware_file, base_url: Optional[str] = None) -> str:
    """Return the download URL for a FirmwareFile, preferring S3.

    - If the row has an s3_key, returns a presigned S3 URL (TTL spans retry window).
    - Otherwise falls back to the legacy local-mount URL. base_url is only needed
      for the fallback path.
    """
    if getattr(firmware_file, "s3_key", None):
        return generate_firmware_presigned_url(firmware_file.s3_key)
    if base_url is None:
        # No S3 + no caller-supplied base_url. Best-effort: use FIRMWARE_PUBLIC_BASE_URL
        # if configured, else a relative path the charger can resolve against its CSMS host.
        base_url = os.getenv("FIRMWARE_PUBLIC_BASE_URL", "")
    return get_firmware_download_url(firmware_file.filename, base_url or "")


def get_file_size(file_path: str) -> int:
    """
    Get size of file in bytes

    Args:
        file_path: Path to the file

    Returns:
        File size in bytes
    """
    return os.path.getsize(file_path)


def file_exists(file_path: str) -> bool:
    """
    Check if file exists

    Args:
        file_path: Path to the file

    Returns:
        True if exists, False otherwise
    """
    return os.path.exists(file_path)
