# Suspend windows are per-connector-type, live in git-tracked policy, and connector_type is an enum

A mid-session charger disconnect suspends the transaction and waits for reconnect. That wait is now **keyed to the connector's physical latching**: a latched connector (Type2/Type1/CCS/CHAdeMO/GB-T — the cable locks into the vehicle inlet) holds the session **12 hours**; an unlatched socket (Socket/domestic — a plug anyone can pull) holds **45 minutes**. The same window applies on **both** suspension paths — the disconnect timer and the post-boot timer armed by BootNotification — retiring the 300s post-boot timer that silently shortened the promised grace window. The window values live in the git-tracked `backend/policy.py`, not env vars, and `connector_type` is promoted from free text to an enum.

## Context

### The ask

Long overnight AC sessions on Type2 chargers were being force-finalized ~32 minutes after a connectivity loss (120s liveness + 1800s disconnect window). The operator's intent: hold a Type2 session up to 12h, because the cable is physically locked into the car — nobody can steal the cable or occupy the charger, and the customer expects their session to survive a power cut. A bare socket gives no such physical guarantee, so it keeps a short window.

The discriminator is **cable latching, not power class**. `max_power_kw` was considered and rejected: the causal story ("is it safe to hold the session against an unattended cable?") is about the lock, not the kW.

### The collision with the existing taxonomy

`connector_type` already drove one behavior: the start gate. `SOCKET_CONNECTOR_TYPES = {socket, type1, type2, domestic}` — connectors with no Control Pilot signal that idle in `Available` and must be remote-startable from `Available`. The new axis needs the **opposite grouping for Type2**:

| connector_type | Has CP? (start gate) | Latches? (suspend window) |
|---|---|---|
| Type2, Type1 | No → start from Available | **Yes → 12h** |
| Socket, domestic | No → start from Available | **No → 45min** |
| CCS, CHAdeMO, GB/T | Yes → wait for Preparing | Yes → 12h |

One column, two orthogonal physical properties, with Type2 split across them. So this is a **second predicate over the same column**, not a change to the first — expressed as a single declarative `CONNECTOR_TRAITS` table in `charger_type_service.py` with two booleans per type (`starts_from_available`, `latching`). `is_socket_connector_type` became a wrapper over the first axis (behavior-identical; three start-paths depend on it); `is_latching_connector_type` reads the second. The previously hand-rolled `{Preparing, Available}` sets at three call sites (`routers/chargers.py` remote start, `qr_payment_service._dispatch_charging`, `qr_payment_service.handle_payment_without_plug`) consolidated onto a shared `startable_statuses` helper. Unknown types resolve to the safe side of **each axis independently**: Preparing-only start, short window.

### The post-boot bug (txn 999) — why the reboot path is included

`_handle_ongoing_transaction_on_boot` rewrote `suspended_at` (disarming the in-flight 1800s disconnect timer via its CAS check) and armed a fresh timer with `SUSPEND_TIMEOUT_SECONDS` = **300s**. A charger that *rebooted* — evidence of recovery — got a 6× shorter grace window than one whose socket merely dropped. Fleet evidence: **9 sessions killed at gap ≈ 300s across prod+staging** (7 of them Type2; prod txns 999, 818, 77 — the last with 2.776 kWh already delivered), and a 90-day reconnect correlation showed **41% of all prod reconnects arrive via BootNotification** (per-charger habits range 0%–80%, fixed per firmware). Without fixing this path, the 12h window would be silently revoked at the exact moment most outages end (power restored → charger boots → car re-negotiates slower than 5 minutes). Rule adopted: **the post-boot window equals the connector type's window** — a reboot never shortens the grace the disconnect path promised.

### Why the values moved out of env vars

Every incident in this area came from env-var invisibility: `MAX_RESUME_GAP_SECONDS=900` silently inverted against the 1800s disconnect window (txn 870, ADR 0022), and the compose fallback for `DISCONNECT_SUSPEND_TIMEOUT_SECONDS` sat at `180` while prod ran `1800` — a 10× drift across 5 definition sites that nothing flagged. These numbers are **policy** — identical in every environment, encoding business decisions — not deployment wiring. They now live in `backend/policy.py`: one file, one reviewed diff, `git blame` answers "who changed the window and why". `DISCONNECT_SUSPEND_TIMEOUT_SECONDS` and `SUSPEND_TIMEOUT_SECONDS` are deleted from all env examples and compose `environment:` blocks; there is deliberately **no env override** — "tunable without review" was the failure mode, not a feature. The env-var checklist in CLAUDE.md no longer applies to policy values. Secrets, hosts, and mid-rollout feature flags stay in env.

### Why connector_type became an enum (and not a lookup table)

The column now carries two load-bearing meanings; a typo at charger creation would silently degrade both (wrong start gate AND wrong window), invisibly. The creation path validated nothing. Now: `ConnectorTypeEnum` (the 7 canonical values), Tortoise `CharEnumField` (column stays VARCHAR(255) — migration 49 is a comment-only no-op; live data was verified clean: exactly `Socket`/`Type2` across all 22 connectors in both envs), and both API paths validate + canonicalize through `canonical_connector_type` (case/space/`_`/`-`/`/`-insensitive; real-world aliases `CCS1`/`CCS2` map onto `CCS`). A test enforces enum↔traits bijection, so a new type cannot be added without declaring both physical properties.

A DB lookup table for the traits was rejected: whether Type2 latches is physics+policy that should change via reviewed git diff, not a runtime-editable row invisible to `git blame` — and a new row is inert until code understands the type anyway.

## Decision

1. **`backend/policy.py`**: `SUSPEND_WINDOW_LATCHED_SECONDS = 43200`, `SUSPEND_WINDOW_UNLATCHED_SECONDS = 2700`, `STALE_SUSPENDED_BUFFER_SECONDS = 60`. Git-tracked, no env override.
2. **`CONNECTOR_TRAITS`** in `charger_type_service.py` — one row per enum member, two booleans; shared `startable_statuses` start-gate helper; `is_latching_connector_type` window predicate.
3. **Both suspension paths resolve the window per charger**: `disconnect_handler.suspend_window_seconds_for_charge_point` feeds the disconnect timer AND the post-boot timer (`main.py` BootNotification handler). The 300s post-boot timer is retired.
4. **Derived cutoffs go per-transaction**: sweep + staleness guard use `stale_suspended_cutoff_seconds_for(txn)` = own window + buffer. The sweep pre-filters at the shortest cutoff then checks each row against its own. The ADR 0022 invariant (guard/sweep fire strictly after the primary timer) holds per-row by construction.
5. **Customer visibility**: `SUSPENDED` added to `/api/users/active-session` — a session deliberately held 12h must not vanish from the customer's app while the public QR endpoint shows it `PAUSED`.

## Accepted trade-offs

- **45min captures only ~13% of observed socket reconnects** (12h captures ~95% of Type2's). Deliberate: cable security outweighs resume convenience on unlatched plugs.
- **QR money can be held up to 12h** on a suspended Type2 session with no refund until finalize. Mitigated by the active-session visibility fix; the orphaned-QR sweep only touches terminal transactions, unchanged.
- **Flap-guard ceiling becomes 36h** (3 zero-progress resets × 12h). A hard session-age ceiling is a possible follow-up.
- **Window resolution reads the charger's first connector** — correct under the 1:1 charger:connector invariant; revisit with multi-connector support (deferred).
- **A policy change now requires a rebuild+deploy** instead of an env edit + restart. Accepted: these values should change rarely and with review.

## Consequences

- A Type2 overnight session survives a power cut of up to 12h on either recovery path (WS reconnect or reboot); txn-999-shaped kills (300s post-boot) become impossible.
- Sockets keep today's ~45min behavior; the compose-fallback 180s drift is gone (the number no longer exists outside policy.py).
- Migration 49 (`connector_type_enum`) is schema-neutral; invalid connector-type writes now fail at the API boundary with 400.
- Follow-up candidates: migrate the remaining policy-shaped env vars (`ZERO_ENERGY_*`, `QR_PAYMENT_PENDING_TIMEOUT`, payout thresholds, retention, `OCPP_TIMEOUT`, `VOLTLYNC_*` identity) into policy.py; hard session-age ceiling; frontend rendering for `SUSPENDED` in the customer app's session card.
