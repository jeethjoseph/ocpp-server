# Charger availability is separate from latest_status

`Charger.availability` (admin-set intent: `Operative` / `Inoperative`) and `Charger.latest_status` (OCPP-reported state: `Available` / `Preparing` / `Charging` / `Faulted` / `Unavailable` / etc.) are two independent fields. Do not unify them. The toggle in the admin UI reads `availability`. The status pill, OCPP routing, billing math, and every other consumer of charger state reads `latest_status`.

Surfaced as a bug on 2026-05-27 against charger `ffeadb01-78bc-4b6e-b5cd-1ff657cbedbc` on staging: admin clicked the toggle twice in quick succession, both `ChangeAvailability:Operative` calls were Accepted at the OCPP layer, but `latest_status` stayed `Unavailable` and the toggle never flipped. Root cause: the schema had no place to record admin intent independent of charger-reported state, and the UI was reading the wrong field as a proxy for both.

## Considered alternatives

- **Optimistic update of `latest_status` on `ChangeAvailability:Accepted`** (set "Operative" → `Available`, "Inoperative" → `Unavailable` in the endpoint handler). Rejected: would override what the charger actually reports and conflict with the next legitimate `StatusNotification`. Specifically would mask `Faulted` states (a Faulted charger that admin commands Operative would appear Available even though the hardware is broken) and `Charging` states (would prematurely overwrite mid-session).

- **Send `TriggerMessage:StatusNotification` after Accepted** to force the charger to re-report its state. Rejected: only works for cooperative chargers. Real-world OCPP firmware sometimes Accepts ChangeAvailability without transitioning state — TriggerMessage doesn't help that case. Also adds OCPP message volume for marginal benefit on cooperative chargers (they would have sent the StatusNotification anyway).

- **Single `latest_status` field, derive admin intent from `audit_log`** when the UI needs it. Rejected: every consumer of `latest_status` would need to learn the new derivation. Joins on `audit_log` are slower than reading a column. The audit log is the right place for "who changed what when," but using it as a source of truth for "what's the current admin-set state" is a misuse.

- **Boolean column `is_operative` instead of an enum.** Rejected: the existing admin endpoint already takes `?type=Operative|Inoperative` (OCPP vocabulary). Converting between bool ↔ enum at the boundary adds friction without simplifying anything downstream.

## Consequences

- The admin UI toggle is permanently decoupled from charger-reported state. Admins see their last command reflected regardless of whether the charger acknowledged with a follow-up `StatusNotification`.
- A future contributor looking at the `charger` schema will see two seemingly-similar state fields. This ADR is the answer to "why two?" Do not unify them without revisiting this decision and updating this ADR.
- The persistence happens on OCPP `Accepted` and `Scheduled` responses, not `Rejected`. `Scheduled` counts because the charger committed to the change — it's just deferred until the current transaction ends. `Rejected` means the charger refused, so admin intent did not take effect.
- For a "command pending vs applied" indicator, future UIs can join the two fields:
  - `availability=Inoperative AND latest_status=Unavailable` → applied
  - `availability=Inoperative AND latest_status in (Charging, Preparing, ...)` → Scheduled, will apply when session ends
  - `availability=Inoperative AND latest_status in (Available, Faulted, ...)` for an extended period → charger ignored the command (firmware-side issue)

  That indicator is a future enhancement; it is not built yet, and this ADR intentionally does not block on it.

- Both the admin endpoint (`routers/chargers.change_charger_availability`) and the franchisee endpoint (`routers/franchisee_portal.change_availability`) write to `availability`. Their UX vocabularies remain different (admins use OCPP `?type=Operative|Inoperative&connector_id=0`; franchisees use boolean `?available=true|false`) — this divergence is intentional and pre-dates this ADR. The persisted column is the same; only the request shape differs.

- If business requirements ever need per-connector availability (currently `connector_id` is fixed to 0 in the admin endpoint by an explicit 422 check), the column needs to move from `Charger` to `Connector` or be supplemented with a `ConnectorAvailability` table. That is a separate ADR if and when it happens.

- `latest_status` semantics are untouched. The `StatusNotification` handler in `main.py` continues to be the sole writer of `latest_status`. No reader of `latest_status` needs to learn about the new field.
