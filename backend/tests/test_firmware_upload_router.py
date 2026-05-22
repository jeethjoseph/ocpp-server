"""Unit tests for the firmware upload endpoint's storage-backend branching.

Covers the two branches added in `.scratch/firmware-update-hardening/issues/01-…`:
  - AWS_S3_FIRMWARE_BUCKET set → S3 path, s3_key populated, file_path="".
  - AWS_S3_FIRMWARE_BUCKET unset/empty → local-disk path, s3_key=NULL, file_path set.

These tests call `upload_firmware` directly as a coroutine and mock the storage
helpers + FirmwareFile.create + audit log so we don't need DB or HTTP plumbing.
"""
from __future__ import annotations

import io
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from routers import firmware as firmware_router


def _make_upload(filename: str = "fw.bin", content: bytes = b"\x01\x02\x03\x04") -> UploadFile:
    """Build a FastAPI UploadFile around in-memory bytes."""
    return UploadFile(filename=filename, file=io.BytesIO(content))


def _admin_user() -> SimpleNamespace:
    return SimpleNamespace(id=42, email="admin@voltlync.test")


@pytest.fixture
def patched_storage(tmp_path):
    """Patch storage_service + FirmwareFile.create + audit log.

    Returns a SimpleNamespace exposing the mocks so tests can assert on them.
    Redirects FIRMWARE_DIR to a tmp_path so the local-mode branch can actually
    write bytes without touching the real container filesystem.
    """
    created = {}

    async def fake_create(**kwargs):
        created.update(kwargs)
        # Return a SimpleNamespace shaped like FirmwareFile (for response model)
        return SimpleNamespace(
            id=1,
            **kwargs,
            created_at=None,
            updated_at=None,
        )

    fake_storage = MagicMock()
    fake_storage.FIRMWARE_DIR = str(tmp_path)
    fake_storage.build_firmware_s3_key = MagicMock(return_value="firmware/v/safe_fw.bin")
    fake_storage.upload_firmware_to_s3 = MagicMock(return_value=None)
    fake_storage.calculate_checksum_from_bytes = MagicMock(return_value="deadbeef")

    with patch.object(firmware_router, "storage_service", fake_storage), \
         patch.object(firmware_router.FirmwareFile, "create", new=AsyncMock(side_effect=fake_create)), \
         patch.object(firmware_router.FirmwareFile, "filter", new=MagicMock(return_value=MagicMock(first=AsyncMock(return_value=None)))), \
         patch.object(firmware_router, "log_audit_event", new=AsyncMock()), \
         patch.object(firmware_router.FirmwareFileResponse, "from_orm", new=MagicMock(side_effect=lambda x: x)):
        yield SimpleNamespace(
            storage=fake_storage,
            created=created,
            audit=firmware_router.log_audit_event,
        )


@pytest.mark.asyncio
async def test_upload_routes_to_s3_when_bucket_env_is_set(monkeypatch, patched_storage):
    """With AWS_S3_FIRMWARE_BUCKET set, upload_firmware_to_s3 is called and the
    row carries s3_key + empty file_path. Existing behavior preserved."""
    monkeypatch.setenv("AWS_S3_FIRMWARE_BUCKET", "voltlync-firmware-test")

    await firmware_router.upload_firmware(
        file=_make_upload("continuous_read.bin", b"firmwarebytes"),
        version="1.4.2",
        description="ADR test",
        user=_admin_user(),
    )

    patched_storage.storage.upload_firmware_to_s3.assert_called_once()
    assert patched_storage.created["s3_key"] == "firmware/v/safe_fw.bin"
    assert patched_storage.created["file_path"] == ""
    # Audit must record storage_backend=s3
    audit_kwargs = patched_storage.audit.call_args.kwargs
    assert audit_kwargs["changes"]["storage_backend"] == "s3"
    assert audit_kwargs["changes"]["s3_key"] == "firmware/v/safe_fw.bin"
    assert audit_kwargs["changes"]["file_path"] is None


@pytest.mark.asyncio
async def test_upload_routes_to_local_disk_when_bucket_env_is_empty(monkeypatch, patched_storage, tmp_path):
    """With AWS_S3_FIRMWARE_BUCKET empty, the file lands on the filesystem and
    s3_key is NULL on the new row — exactly the stopgap configuration."""
    monkeypatch.setenv("AWS_S3_FIRMWARE_BUCKET", "")

    content = b"firmware-bytes-on-disk"
    await firmware_router.upload_firmware(
        file=_make_upload("continuous_read.bin", content),
        version="1.4.2",
        description=None,
        user=_admin_user(),
    )

    # S3 upload must NOT be called in local mode
    patched_storage.storage.upload_firmware_to_s3.assert_not_called()

    # Row carries s3_key=None and file_path under FIRMWARE_DIR
    assert patched_storage.created["s3_key"] is None
    expected_file = os.path.join(str(tmp_path), "1.4.2_continuous_read.bin")
    assert patched_storage.created["file_path"] == expected_file

    # File actually got written with the bytes we sent
    with open(expected_file, "rb") as f:
        assert f.read() == content

    # Audit must record storage_backend=local
    audit_kwargs = patched_storage.audit.call_args.kwargs
    assert audit_kwargs["changes"]["storage_backend"] == "local"
    assert audit_kwargs["changes"]["s3_key"] is None
    assert audit_kwargs["changes"]["file_path"] == expected_file


@pytest.mark.asyncio
async def test_upload_routes_to_local_disk_when_bucket_env_is_unset(monkeypatch, patched_storage, tmp_path):
    """Same as empty-string case: a fully missing env var also routes to local."""
    monkeypatch.delenv("AWS_S3_FIRMWARE_BUCKET", raising=False)

    await firmware_router.upload_firmware(
        file=_make_upload("continuous_read.bin", b"xyz"),
        version="1.4.3",
        description=None,
        user=_admin_user(),
    )

    patched_storage.storage.upload_firmware_to_s3.assert_not_called()
    assert patched_storage.created["s3_key"] is None
    assert patched_storage.created["file_path"].startswith(str(tmp_path))


@pytest.mark.asyncio
async def test_url_generation_picks_local_path_when_s3_key_null():
    """get_firmware_download_url_for_file already routes per-row based on
    s3_key. Regression guard — must keep working for the rows the new local
    branch produces."""
    from services import storage_service

    firmware_with_s3 = SimpleNamespace(s3_key="firmware/1.4.2/fw.bin", filename="fw.bin")
    firmware_no_s3 = SimpleNamespace(s3_key=None, filename="1.4.2_fw.bin")

    # When s3_key is set, presign helper must be called.
    with patch.object(storage_service, "generate_firmware_presigned_url", return_value="https://signed.example/x") as gen:
        url = storage_service.get_firmware_download_url_for_file(firmware_with_s3)
        gen.assert_called_once_with("firmware/1.4.2/fw.bin")
        assert url == "https://signed.example/x"

    # When s3_key is None, legacy URL is composed from FIRMWARE_PUBLIC_BASE_URL.
    with patch.dict(os.environ, {"FIRMWARE_PUBLIC_BASE_URL": "https://staging.voltlync.com"}):
        url = storage_service.get_firmware_download_url_for_file(firmware_no_s3)
        assert url == "https://staging.voltlync.com/firmware/1.4.2_fw.bin"
        assert len(url) < 100  # the whole point: short URL for charger ingestion
