Status: ready-for-agent

# Widen `FirmwareUpdate.download_url` to fit presigned URLs with STS tokens

## What to build

The admin "trigger firmware update" endpoint (`POST /api/admin/firmware/chargers/{id}/update`) returns 500 on staging and prod because the presigned S3 download URL exceeds the `download_url` column's 500-char limit.

On EC2 the backend authenticates to S3 via the instance's IAM role. Role-assumed credentials presigns carry an `X-Amz-Security-Token` query parameter (the STS session token, ~1.3 KB), which inflates the URL to ~1824 chars. Local dev and any environment using a static IAM-user access key never hit this — the URL stays under 500 chars, which is why the regression only shows up in staging/prod.

Observed in staging logs (2026-05-20):

```
tortoise.exceptions.ValidationError: download_url: Length of '<presigned URL>' 1824 > 500
  File "/app/routers/firmware.py", line 369, in update_charger_firmware
    firmware_update = await FirmwareUpdate.create(...)
INFO:     "POST /api/admin/firmware/chargers/5/update HTTP/1.1" 500 Internal Server Error
```

Fix: widen the column. Presigned URLs are not user-input, are never indexed or queried by substring, and STS-token length is outside our control, so an unbounded `TextField` is the correct shape rather than a larger `CharField`.

Touchpoints:

- `backend/models.py` — `FirmwareUpdate.download_url`: change from `fields.CharField(max_length=500)` to `fields.TextField()`.
- Generate the schema change with Aerich (`aerich migrate --name widen_firmware_update_download_url`). Do NOT hand-write the migration; if Aerich refuses, that's a stale-local-DB signal — run `aerich upgrade` first and retry.
- No router/service code changes required. The two callsites that write the field (`routers/firmware.py:374` create and `:453` re-trigger update) already pass the full string through.

## Acceptance criteria

- [ ] `FirmwareUpdate.download_url` is `TextField` in `models.py`
- [ ] Aerich-generated migration committed under `backend/migrations/models/`
- [ ] Migration applies cleanly on a fresh DB (verify with `docker exec ocpp-backend aerich upgrade` on a clean container)
- [ ] On staging post-deploy, `POST /api/admin/firmware/chargers/{id}/update` returns 200 and creates a `firmware_update` row when the presigned URL is >500 chars (verify via SSM: `docker exec ocpp-backend-staging psql ... -c "select length(download_url) from firmware_update order by id desc limit 1;"`)
- [ ] No 500s with `tortoise.exceptions.ValidationError: download_url` in `docker logs ocpp-backend-staging` for 1 hour after deploy
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` updated if either documents the firmware-update schema

## Blocked by

None — can start immediately.
