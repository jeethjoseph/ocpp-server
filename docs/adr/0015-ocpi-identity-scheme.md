# OCPI identity scheme: env-specific party ID, persisted-and-frozen public IDs, per-charger publish

**Status:** accepted (2026-06-24)

## Context

We expose a direct **OCPI 2.2.1** CPO feed (Versions + Credentials + Locations) so external consumers — primarily Google Maps via `EVCS-global@google.com`, plus any future aggregator/roaming hub — can pull static location data and real-time EVSE status. See [[adr-0008-charger-availability-separate-from-status]] for the two state fields the feed fuses.

OCPI requires a stable CPO **party identity** and stable IDs at the Location / EVSE / Connector levels. These IDs become the primary keys for every POI Google ingests. **Changing a public ID after ingestion orphans the Maps listing** — the old POI appears to vanish (losing reviews/history) and a new one appears. So the identity scheme must guarantee these IDs never churn for the life of a physical charging point, *independently of internal database row identity*.

## Decision

**Party identity (config constants, not data):**
- `country_code = IN` (ISO-3166).
- `party_id` — self-assigned (India has no mandatory national OCPI party registry) and **env-specific**: `VLT` on prod, `VLS` on staging. Held as a per-environment config constant (`OCPI_PARTY_ID`), not a per-row column. The env split is what makes it safe for **both** environments to publish to Google simultaneously — see Consequences.

**Public object IDs (persisted and frozen):**
- `Charger.ocpi_evse_id` — new nullable, **unique** column. eMI3 format `IN*VLT*E{Charger.id}`. Assigned once at charger creation from the derived default, then **never recomputed**.
- `ChargingStation.ocpi_location_id` — new nullable, **unique** column. `str(ChargingStation.id)`. Assigned once at station creation, then frozen.
- Existing rows backfilled with the derived value in the creating migration (Aerich-generated: two nullable columns + backfill).

**Derived (not persisted):**
- `EVSE.uid = Charger.charge_point_string_id` (internal handle, not the public Maps key).
- `Connector.id = "1"` — follows from the one-connector-per-charger invariant (see `CONTEXT.md`).

`evse_id` uses the integer `Charger.id`, not `charge_point_string_id`, because eMI3 permits only `A–Z 0–9 *` and string IDs may contain disallowed characters; the int PK is immutable and safe. Because `party_id` is part of the frozen `evse_id`, each environment's DB bakes its own party into the stored value at creation (prod rows → `IN*VLT*E{id}`, staging rows → `IN*VLS*E{id}`).

**Per-charger publish control:** `Charger.publish_to_google` (boolean, default `false`) gates feed inclusion — only flagged chargers are emitted; a Location is published iff it has ≥1 published EVSE. Flipping the flag to `true` is **completeness-gated** (hard block unless `ocpi_evse_id` assigned + station has coords/city/address + connector has `ocpi_standard`) and **audit-logged**, because it has irreversible external side effects (see Consequences).

## Considered options

- **Pure derivation (no columns), compute `evse_id` from `Charger.id` on every feed render.** Rejected: a hardware swap (dead unit replaced at the same bay → new `Charger` row → new `id`) silently changes the public `evse_id` and orphans the Maps POI — re-introducing exactly the failure the scheme exists to prevent.
- **Registered party_id via a roaming body.** Rejected for now: no mandatory India registry, no existing assigned code, and Google's direct path accepts a self-declared `party_id`. Revisit only if we join a roaming hub that requires a registered ID.

## Consequences

- **Hardware swaps preserve the POI:** ops copies the dead charger's `ocpi_evse_id` onto the replacement `Charger` row; Google keeps the listing. This is the operational procedure the persisted column enables — without it, every swap churns the Maps POI.
- The served contract is auditable (`SELECT ocpi_evse_id` shows exactly what Google has).
- **Both environments publish to Google, kept distinct by env-specific `party_id`.** Staging (`VLS`) serves a small set of real, Google-live chargers as a **deliberate canary** — a pre-rollout validation step before a charger goes live under prod (`VLT`). Without the per-env party split, staging `id=N` and prod `id=N` would collide on an identical `evse_id` (the same cross-environment hazard as the shared Razorpay/Clerk accounts); the split removes it, so `OCPI_ENABLED` is `true` on both envs rather than prod-only. (This supersedes the initial prod-only guardrail.)
- **Publishing is irreversible in identity, not in visibility.** Un-flagging `publish_to_google` drops the EVSE from the feed and Google removes the POI on its next pull — but the `evse_id` is permanently spent and must never be rebound to a different physical charger. Hence the completeness gate + audit log on the toggle: the risk being guarded against is publishing wrong/incomplete data or churning a spent identity, not the inability to unpublish.
