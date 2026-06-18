Status: done

# Wrap boto3 calls (s3_service + storage_service) in asyncio.to_thread

## Context

`backend/services/s3_service.py` and `backend/services/storage_service.py` expose only sync functions (`def`, not `async def`). They use `boto3` under the hood, which makes synchronous HTTP requests to AWS S3 via the `requests`-equivalent `botocore` HTTP client.

When called from async code (`async def` handler), these sync HTTP calls block the asyncio event loop for the full S3 round-trip — typically 50–500ms per call, but can spike to seconds under network pressure or large uploads.

Migrating boto3 to `aioboto3` is a larger lift (different API surface, dependency change, version compatibility checks). The simpler bridge: keep the sync `s3_service.*` / `storage_service.*` functions, but call them via `asyncio.to_thread(...)` from async contexts. That offloads the sync I/O to the default thread pool and frees the event loop.

## What to build

Identify every async call site that invokes a function from `backend/services/s3_service.py` or `backend/services/storage_service.py` that does network I/O or filesystem I/O. Wrap each call in `await asyncio.to_thread(func, *args, **kwargs)`.

The non-I/O helpers don't need wrapping:
- `s3_service._bucket`, `s3_service._client`, `s3_service._build_key`
- `storage_service._firmware_bucket`, `_s3_client`, `_presign_ttl`, `build_firmware_s3_key`, `get_firmware_download_url`, `get_firmware_download_url_for_file` (the latter constructs URLs; only does S3 calls when generating a presigned URL — check the implementation)
- `storage_service.calculate_checksum_from_bytes` (CPU-only on the in-memory bytes, fast)

The I/O-bound functions that DO need wrapping:
- `s3_service.upload_invoice_pdf(invoice, pdf_bytes) -> str` — boto3 PutObject
- `s3_service.generate_presigned_url(key, expires_in)` — boto3 generate_presigned_url
- `s3_service.download_pdf(key) -> Optional[bytes]` — boto3 GetObject
- `storage_service.upload_firmware_to_s3(s3_key, file_bytes, content_type)` — boto3 PutObject
- `storage_service.generate_firmware_presigned_url(s3_key, expires_in)` — boto3 presign
- `storage_service.delete_firmware_file(file_path)` — local filesystem unlink (cheap but still blocking)
- `storage_service.calculate_checksum(file_path)` — reads file from disk; can be large
- `storage_service.get_file_size(file_path)`, `storage_service.file_exists(file_path)` — sync filesystem stat

## What to change

Audit and update all async callers. From the initial grep:

- `backend/services/firmware_update_service.py:203` — `storage_service.get_firmware_download_url_for_file(...)` — confirm whether this hits S3 (if so, wrap).
- `backend/routers/firmware.py:158` — `storage_service.build_firmware_s3_key(version, safe_filename)` — pure key construction, no wrap needed.
- `backend/routers/firmware.py:159` — `storage_service.upload_firmware_to_s3(s3_key, file_content)` — **wrap**.
- `backend/routers/firmware.py:164` — `os.path.join(...)` — pure path construction, no wrap.
- `backend/routers/firmware.py:169` — `storage_service.calculate_checksum_from_bytes(file_content)` — in-memory, fast; skip unless file is huge.
- `backend/routers/firmware.py:364, 449, 800` — `storage_service.get_firmware_download_url_for_file(...)` — confirm if it makes an S3 call (presigning may not need a network call, but verify).
- `backend/routers/invoices.py:422, 446` — `s3_service.generate_presigned_url(...)` — **wrap**.
- `backend/routers/invoices.py:443` — `s3_service.upload_invoice_pdf(...)` — **wrap**.

Idiom to apply:

```python
# Before:
url = s3_service.generate_presigned_url(key)

# After:
url = await asyncio.to_thread(s3_service.generate_presigned_url, key)
```

Add `import asyncio` at the top of each file if not already imported.

## Acceptance criteria

- [ ] Every async caller of an I/O-bound `s3_service.*` / `storage_service.*` function uses `await asyncio.to_thread(...)`.
- [ ] Pure helpers (path construction, in-memory checksum) are left as-is.
- [ ] No regression in firmware upload, firmware download URL generation, invoice PDF upload, invoice presigned URL.
- [ ] Existing tests pass: `docker exec ocpp-backend pytest backend/tests/` (filter to firmware/invoice tests).
- [ ] Manual sanity: upload a small firmware file via the admin UI; confirm it lands in S3; confirm the chargers/4 page continues responding during the upload.
- [ ] Manual sanity for invoice: trigger a transaction finalization with energy > 0; the invoice should be created without the event loop visibly stalling (heartbeats keep flowing).

## Notes for the agent

Don't try to make `s3_service.*` itself `async def`. The bridge via `asyncio.to_thread` is intentional — it keeps the boto3-level API stable and avoids pulling in `aioboto3` as a new dependency. A future issue could migrate to `aioboto3` properly, but that's not this issue.

## Blocked by

None — can start immediately. Independent of all other issues.
