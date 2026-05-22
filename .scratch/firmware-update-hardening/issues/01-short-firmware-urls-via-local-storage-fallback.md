Status: ready-for-agent

# Firmware upload: fall back to local disk when AWS_S3_FIRMWARE_BUCKET is unset

## What to build

Make the firmware upload endpoint route storage based on the `AWS_S3_FIRMWARE_BUCKET` env var:

- **bucket set (current behavior)** → upload bytes to S3, set `firmware_file.s3_key`, leave `file_path=""`. Download URL = ~1700-byte S3 presigned URL.
- **bucket empty/unset (new behavior)** → write bytes to `/app/firmware_files/{safe_filename}` on the backend container, leave `firmware_file.s3_key = NULL`, set `file_path` to the on-disk path. Download URL = ~62-byte legacy static-mount URL `https://<host>/firmware/{filename}`.

The existing `storage_service.get_firmware_download_url_for_file` already branches on whether `s3_key` is populated and routes to the correct URL — no change needed there. The FastAPI static mount at `main.py:158` and the nginx `/firmware/` proxy block already serve the legacy URL — confirmed working.

This is a **stopgap to unblock the firmware team**, whose charger-side URL parser cannot handle the 1.7KB S3 presigned URL that gets produced when the backend signs from an EC2 IAM role (the `X-Amz-Security-Token` alone is ~1.1KB). Falling back to local storage gives them a ~62-byte URL while the device firmware is patched to accept longer URLs.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| New `FIRMWARE_STORAGE_BACKEND=local\|s3` flag | More wiring (CLAUDE.md mandates 6 files per new env var). Reusing `AWS_S3_FIRMWARE_BUCKET` is self-documenting: "no bucket → no S3 mode." |
| Backend proxy endpoint with short token | Right long-term answer, but ~1 day of work + new column + migration. Doesn't unblock firmware team this week. |
| Static long-lived IAM keys (no STS session token) | Drops URL to ~350 bytes but introduces a security regression (long-lived creds) and may still exceed the firmware parser limit. |
| Manual SCP + DB INSERT per upload | Operationally painful. No code change but every firmware shipment becomes a bespoke procedure. |

## What to change

### Code change — `backend/routers/firmware.py` `upload_firmware` endpoint

Inside the existing `try:` block at lines 149-183, replace the unconditional S3 path with a branch:

```python
file_content = await file.read()
safe_filename = f"{version}_{file.filename}"

if os.getenv("AWS_S3_FIRMWARE_BUCKET"):
    s3_key = storage_service.build_firmware_s3_key(version, safe_filename)
    storage_service.upload_firmware_to_s3(s3_key, file_content)
    file_path = ""
else:
    s3_key = None
    file_path = os.path.join(storage_service.FIRMWARE_DIR, safe_filename)
    with open(file_path, "wb") as f:
        f.write(file_content)

checksum = storage_service.calculate_checksum_from_bytes(file_content)
firmware_file = await FirmwareFile.create(
    version=version,
    filename=safe_filename,
    file_path=file_path,
    s3_key=s3_key,
    file_size=len(file_content),
    checksum=checksum,
    description=description,
    uploaded_by_id=user.id,
    is_active=True,
)
```

Update the success log line to indicate which backend was used (`s3_key=…` vs `local file_path=…`). Update the audit-log `changes` dict accordingly.

### Migration of existing row 1.4.2 (data fix, not code)

After the code change ships to staging, repoint the existing in-flight firmware update at the local-disk file:

1. SSM to the staging EC2.
2. Inside `ocpp-backend-staging` container, verify the file already exists on disk:
   ```
   ls -la /app/firmware_files/1.4.2_continuous_read.bin
   ```
   If absent, re-upload via the admin UI (with bucket env now empty, this writes to disk).
3. Run SQL:
   ```sql
   UPDATE firmware_file
   SET s3_key = NULL,
       file_path = '/app/firmware_files/1.4.2_continuous_read.bin'
   WHERE id = 8;
   ```
4. Re-schedule firmware update for the affected charger from the admin UI.

### Compose / env wiring

Set `AWS_S3_FIRMWARE_BUCKET=""` (empty) in `.env.staging` so the new local-mode branch fires. **Do NOT** remove the var from `docker-compose.staging.yml` — keep the `- AWS_S3_FIRMWARE_BUCKET=${AWS_S3_FIRMWARE_BUCKET:-}` line so flipping back to S3 is a one-line env change. No changes to `.env.prod` — prod stays on S3.

## Acceptance criteria

- [ ] `POST /api/firmware/upload` with `AWS_S3_FIRMWARE_BUCKET=""` writes the file to `/app/firmware_files/` and creates a `FirmwareFile` row with `s3_key=NULL` and `file_path` pointing at the on-disk location.
- [ ] `POST /api/firmware/upload` with `AWS_S3_FIRMWARE_BUCKET=voltlync-firmware-staging` continues to behave exactly as today (S3 upload, `s3_key` set, `file_path=""`).
- [ ] `storage_service.get_firmware_download_url_for_file(firmware_file)` returns a `~62-byte` URL of the form `https://<host>/firmware/{filename}` when `s3_key IS NULL`, and an S3 presigned URL otherwise. No code change needed here — verify behavior via a unit test if not already covered.
- [ ] When `AWS_S3_FIRMWARE_BUCKET` is empty, `_try_trigger_update` dispatches `UpdateFirmware` with `location` < 100 bytes.
- [ ] The existing in-flight update on staging (row id=8, charger `ed2bd339-…`, target 1.4.2) is repointed at the local-disk file and successfully delivers the firmware to the charger on next attempt.
- [ ] No regression in prod (prod env stays on S3; behavior unchanged).
- [ ] One new test in `backend/tests/` covering both branches of the upload endpoint (S3 mode + local mode), mocking the S3 client and the on-disk write.
- [ ] Audit log records which backend was used (`storage_backend: "s3" | "local"`).

## Rollback

Flip `AWS_S3_FIRMWARE_BUCKET` back to the bucket name in `.env.staging`, redeploy the env-var change (no rebuild needed, just `docker compose up -d backend` to refresh env). New uploads go back to S3. Existing local-only rows continue to work via the legacy URL until manually re-uploaded.

## Known caveats to document in admin UI / runbook

- **Volume persistence:** `/app/firmware_files/` is backed by the `backend_firmware` named docker volume. Survives `docker compose restart`; lost on `docker compose down -v` or instance replacement.
- **No URL signature/TTL on legacy path:** anyone who can reach `https://staging.voltlync.com/firmware/{filename}` can download the firmware. Acceptable for staging; **must not enable this on prod** without adding a token-based proxy first (see follow-up issue).
- **Disk usage:** ~5-10MB per firmware version. Add to retention runbook if cadence is high.

## Follow-ups to file separately (NOT in scope here)

- Backend proxy endpoint with short opaque token (the proper long-term replacement for both S3 long-URLs and the legacy unauthenticated path).
- Premature auto-`INSTALLED` short-circuit in `firmware_update_service.py:189` — should require a fresh BootNotification within the boot-debounce window, otherwise the system marks INSTALLED based on stale `Charger.firmware_version` and silently swallows admin re-schedule intent.
- Re-schedule debounce — current UPSERT in `update_charger_firmware` wipes `last_attempt_at`, defeating the 5-min boot-debounce and allowing rapid re-fire of `UpdateFirmware` on a charger that's mid-download.

## Blocked by

None - can start immediately.

## Comments

### Files changed
- `backend/routers/firmware.py` — `upload_firmware` branches on `AWS_S3_FIRMWARE_BUCKET`; passes `storage_backend` into the audit log and chooses between S3 upload + `s3_key` and local-disk write + `file_path`.
- `backend/tests/test_firmware_upload_router.py` — new file; 4 unit tests covering S3 mode, local mode with empty env var, local mode with unset env var, and the per-row URL generation regression guard.
- `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` — updated to document the stopgap and its caveats.

### Test results
- `docker exec ocpp-backend pytest tests/test_firmware_upload_router.py tests/test_firmware_update_service.py` → 13 passed (4 new + 9 existing firmware service).

### Code change kept minimal
- No new env var introduced. Reuses `AWS_S3_FIRMWARE_BUCKET`: presence selects S3, absence selects local.
- No schema change. The `s3_key` and `file_path` columns on `FirmwareFile` already exist (legacy columns reused).
- No change to `storage_service.get_firmware_download_url_for_file` — it already branches on `s3_key`. The URL chooser is row-driven; the upload endpoint just decides what to write to the row.

### Operational steps to roll out on staging (NOT performed in this code change)
1. Set `AWS_S3_FIRMWARE_BUCKET=""` in `.env.staging`.
2. Deploy: `make staging-deploy` or `docker compose up -d backend` to refresh env.
3. Verify: `docker exec ocpp-backend-staging env | grep AWS_S3_FIRMWARE_BUCKET` should show empty.
4. Re-upload firmware 1.4.2 via the admin UI — new row will have `s3_key=NULL` and `file_path` populated.
5. EITHER point the in-flight `FirmwareUpdate.firmware_file_id` to the new row, OR run the SQL fix on row id=8 (null s3_key + set file_path) + place the existing 1.4.2 file on disk.
6. Re-schedule the firmware update from the admin UI.
7. Confirm via staging logs that the next `UpdateFirmware` OCPP dispatch carries the short URL.

### Rollback
- Set `AWS_S3_FIRMWARE_BUCKET=voltlync-firmware-staging` (or original value) in `.env.staging`, redeploy. Future uploads go back to S3. Existing local-only rows continue to serve via the legacy URL until manually re-uploaded.

### Judgment calls
- Tests are unit-level (direct coroutine call with mocked storage / DB), not integration-level via `TestClient`. The upload endpoint requires admin auth and a real DB connection; the branching logic under test does not need either. Future expansion to a full integration test could live alongside the existing `client` fixture pattern in `test_qr_payment_service.py`.
- `FirmwareFileResponse.from_orm` is patched in tests because the SimpleNamespace returned by the mocked `FirmwareFile.create` doesn't satisfy the pydantic `from_orm` shape. Acceptable for this scope.
- The legacy `save_firmware_file()` helper in `storage_service.py` remains untouched — it's dead code on the upload path (the endpoint no longer calls it), but it's still referenced by tests and may have indirect uses. Cleanup is a separate concern.
