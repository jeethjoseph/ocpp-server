# Investigate Clerk webhook signature failures (stale secret vs probes)

Status: ready-for-human — **INVESTIGATED + code fix applied 2026-06-11; one optional human step remains (Clerk dashboard)**

## Investigation outcome (2026-06-11)

**Classification: benign cross-environment Clerk traffic — NOT a stale secret, NOT probes.**

Evidence:
1. **Genuine Svix sender.** Failing requests carry `User-Agent: Svix-Webhooks/1.84.0` with well-formed `Svix-Id`/`Svix-Timestamp`/`Svix-Signature` — real Clerk deliveries, not scanners. (Issues P and N share one `Svix-Id` → one request, two log sites; confirms single root cause.)
2. **Sporadic, not systematic.** 6 events = 3 messages (each Svix-retried ~4s apart) on 3 occasions across 2 weeks. A wrong secret would fail *every* delivery.
3. **The prod secret is correct (decisive).** Prod read-only DB check: `app_user` rows with role `USER` + a `clerk_user_id` can only be created by `handle_user_created`. Four such driver accounts were created *during* the failure window — id 100 (05-30), 104 (06-04), 109 (06-06), 110 (06-08). So legitimate prod webhooks verify and sync throughout. `CLERK_WEBHOOK_SECRET=whsec_jE98…` is the right secret.

Mechanism: staging and prod **share one Clerk app** (per CLAUDE.md). A message signed by the *other* endpoint's secret occasionally reaches the prod URL (duplicate/misconfigured webhook endpoint) and fails prod's verification — the exact analogue of the documented Razorpay cross-environment webhook pattern.

**Real-user impact: none.** Sign-ups sync fine. (`get_current_user_with_db` has no lazy creation — it 404s without a row — so a *real* secret break would be high-impact, but that is not what's happening.)

## Fix applied (code)

`routers/webhooks.py` `handle_clerk_webhook`: the signature-verification failure path now logs at **warning** (not error → no Sentry event) and returns `200 {"status":"verification_failed"}` directly, which also keeps it out of the generic outer error handler (that handler stays at `error` for genuine processing failures — DB/Redis). Removes both OCPP-BACKEND-P and -N. Test: `test_clerk_user_created_webhook.py::test_bad_signature_is_warning_not_error`. Passes.

**Monitoring trade-off (documented inline):** this downgrade would mask a *real* future `CLERK_WEBHOOK_SECRET` drift. Mitigation: the positive signal is "successful `Received Clerk webhook` log lines / new clerk-linked `app_user` rows." Suggested follow-up (not in this issue): a low-frequency health check that alerts if zero successful Clerk webhooks occur over N days while warnings continue.

## Optional human step (Clerk dashboard)

To stop the noise at source: in the shared Clerk app's **Webhooks** settings, find the endpoint(s) pointing at `app.voltlync.com/webhooks/clerk` and remove any duplicate / stale / staging endpoint that shouldn't deliver to prod. Not required for correctness — the code fix already silences the false alarms.

---


Sentry: OCPP-BACKEND-P (`Webhook verification failed: No matching signature found`) + OCPP-BACKEND-N (`Webhook processing error: 400: Webhook verification failed`) — 6 + 6 occurrences, production. Same root cause, two log sites (inner svix verify failure → outer handler catch).

## What to build

The Clerk webhook handler at `/webhooks/clerk` is rejecting requests with svix "No matching signature found". This has two very different possible causes that need to be distinguished before any fix:

- **Stale / cross-environment `CLERK_WEBHOOK_SECRET`** — real impact: legitimate Clerk `user.created/updated/deleted` events are being dropped, so users are not syncing. This is a production correctness bug.
- **Unauthenticated probes / scanners** hitting the public endpoint — benign noise; the fix is to downgrade the log so it stops generating Sentry errors.

Investigate first, then act:

1. Inspect the failing events' source (IPs, headers, whether `svix-id`/`svix-timestamp`/`svix-signature` are present and well-formed).
2. Confirm whether the deployed `CLERK_WEBHOOK_SECRET` matches the secret in the Clerk dashboard for this environment (note staging/prod share the same Clerk app).
3. Cross-check whether legitimate user syncs are succeeding in the same window.

Outcome branches:
- If stale/misconfigured secret → correct the env var (follow the env-var checklist: value in `.env.{env}` AND `backend.environment:` of the compose files) and verify syncs resume.
- If external probes → downgrade both log sites to warning so they no longer raise Sentry errors, while keeping the 400 response.

## Acceptance criteria

- [ ] Root cause classified: stale secret vs external probes (with evidence) — recorded in Comments.
- [ ] If secret issue: env var corrected per the env-var checklist and a real Clerk event verified to sync.
- [ ] If probe noise: both log sites downgraded so they no longer produce Sentry errors; the endpoint still returns 400 on bad signatures.
- [ ] No regression to legitimate `user.created/updated/deleted` handling.

## Blocked by

None - can start immediately.
