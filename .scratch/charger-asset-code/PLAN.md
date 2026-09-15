# Plan: Asset Code + Charger Purpose (ADR 0028)

Driver: jeethjoseph · Spec: `docs/adr/0028-customer-facing-charger-code.md`
Terms: **Asset Code**, **Charger Purpose** in `CONTEXT.md`

## Two independent things, deliberately

- **Asset Code** — identity. A system-allocated running number, `VOW0001` /
  `VOWS0001`, that replaces the `charge_point_string_id` UUID on every customer
  surface. Answers "which charger is this".
- **Charger Purpose** — serviceability. `PUBLIC` | `TEST` on `Charger.purpose`,
  defaulting `PUBLIC`. Answers "is this unit part of the customer-facing fleet".

The previous design fused them (`bay_number IS NULL` meant both "no code" and "not
serviceable"). Keeping them apart is what lets identity ship without a physical
survey, and lets the visibility and billing gates ship later on their own schedule.

`PRIVATE` (real hardware, real billing, not advertised) is a third value with no
instance in the fleet today. Tortoise renders a `CharEnumField` as a plain
`VARCHAR` with no DB enum type or CHECK (see migration 42 for `availability`), so
adding it later needs no migration. Do not add it speculatively.

## What each purpose does

| Surface | `PUBLIC` | `TEST` |
|---|---|---|
| `/stations`, station detail, no-auth map — all via `_fetch_stations_with_availability` (`routers/public_stations.py:98`) | listed, counts toward `total_chargers` | hidden |
| `StartTransaction` (`main.py:844`) | normal | non-`INTERNAL_ROLES` rejected `Blocked` |
| Wallet deduct / QR billing | normal | never billed |
| GST Invoice | issued | suppressed |
| OCPI feed (unimplemented, [[adr-0015-ocpi-identity-scheme]]) | published | excluded |
| Admin UI | normal | `TEST` badge beside the code |

Note `_filter_real_chargers` (`public_stations.py:164`) is a **liveness** predicate
(connected + recent heartbeat). Serviceability is a separate axis and gets a
separate filter rather than being folded into that one.

## Why the ordering is safe this time

`purpose` defaults to `PUBLIC`, so **the failure direction is fail-open**: a row
missed by any backfill keeps billing and stays visible. Contrast the bay design,
where `bay_number` was `NULL` for every row the moment the column landed, so
shipping the gate first blocked every customer and shipping the filter first
emptied the station map. Here the worst case of a missed row is the status quo —
the five production bench units stay visible on `/stations`, exactly as they are
today.

That removes the revenue-outage class, but not the ordering rule: **column and
backfill before gate and filter**, because a `TEST` flip is what those two read.

## The two open questions, resolved

### Bench units get a code — `NOT NULL`, same series (settled)

The alternative was a nullable `asset_code` with `CHECK (purpose = 'TEST' OR
asset_code IS NOT NULL)` and a mint-on-promotion path. Counting the call sites
settles it:

| Audience | Sites rendering charger identity |
|---|---|
| admin / franchisee (`chargers`, `franchisee_portal`, `firmware`, `qr_codes`) | **19** |
| customer-facing (`public_stations`, `public_qr_transactions`, `public_qr_active_sessions`) | **3** |

A nullable code puts a null-branch in the **19**, because admin surfaces are
exactly where bench units appear — and `routers/firmware.py:425,575` is the
firmware-deploy path, which targets bench hardware constantly. The 3 customer
sites would never exercise the branch at all once slices 06/07 land. So nullable
buys nothing and reintroduces the "three call-site families disagree on fallback"
problem catalogued in issue 03 of the old map, on the surfaces that matter most.

Promotion is also simpler this way: `TEST → PUBLIC` is a single field update with
no minting step. And units *do* move contexts — production holds rows named
`Staging_VOW0002` and `Staging_VOW0004`.

### Seeding — needs one verification pass first (new slice 00)

The seeded backfill assumes `Charger.name` faithfully records the sticker on the
unit. That assumption is weaker than it looked:

- **`name` has no write-side validation at all.** Not on `ChargerCreate`, not on
  `ChargerUpdate` — no trim, no format, no non-empty check. Any admin can change it
  to anything at any time.
- **It has demonstrably drifted.** Five of production's thirteen rows hold
  non-stencil text (`V3C_Test`, `Chargemode_1`, `Staging_VOW0002`…), and staging
  holds `"VOW0001 "` with a trailing space.
- **Nothing corroborates it.** Only one production row carries a `serial_number`.

So the risk isn't hypothetical drift, it is *unmeasured* drift on the eight rows
that matter. If a single one has drifted, seeding binds a wrong code to a unit
permanently — and that is the exact wrong-answer bug that made us reject pure
`id`-order allocation. Same failure, different cause.

Three options, and only one is drift-immune without a verification pass:

| Option | Aliasing risk | Physical work |
|---|---|---|
| pure `id`-order | **certain** — 6 of 8 shift | 12 units re-stencilled |
| seed from `name`, unverified | unknown, permanent if present | none |
| start production at `VOW1001` | none — a stale sticker resolves to nothing | 12 units re-stencilled |
| **seed from `name`, verified** | none | 4 staging units only |

The verification is far lighter than the bay survey that sank the previous design:
that needed a *judgement* about which spot is bay 1; this needs someone to read
eight labels and confirm they match. It is also **asynchronous** — it gates slice
03 and nothing before it.

If verification comes back dirty on any row, fall back to starting production at
`VOW1001` and re-stencil. Decide that on the evidence, not now.

## Slices

Tracer-bullet order. Each is independently deployable and independently revertible.

**Cut as tickets in `issues/`** — slice NN is `issues/NN-*.md`, and those files are the
working copy. This section stays as the rationale; the tickets carry the acceptance
criteria. Two additions the slice list did not have: `issues/09` covers the staging
re-stencil described under **Physical work** below, and `issues/08` is filed
`needs-triage` rather than ready, because it is deferred behind entry conditions.

### 00 — Confirm the eight production stencils  *(human, asynchronous; gates 04 only)*
Confirm that the label on each of production's eight fleet units matches
`Charger.name`, listed in `asset-code-assignments.csv`. Four sites: IDofThings
(`VOW0001`, `VOW0002`), Seleno Stones (`VOW0003`), SARADHY TOWERS (`VOW0006`,
`VOW0007`), SK EV Charging Station (`VOW0008`–`VOW0010`). Bench units need no check
— they carry no stencil and their codes are allocated, not seeded.

**The requirement is confirmation, not a particular medium.** The CSV cannot be its
own evidence: it is generated from `name`, so checking it against `name` is circular.
Anyone who knows the fleet can sign off the eight rows from memory; photographs are
only the fallback when nobody is confident, and then they are just the record.

**Gates slice 04, not slice 03.** The code becomes permanent when it starts landing
on GST Invoices, which is 04. Between 03 and 04 it lives only in the database and on
admin surfaces, where a wrong value is an `UPDATE`, not a scar. So 01, 02, 03 and 05
all proceed while this is outstanding — and **05 is the natural way to do it**: once
the admin UI shows the code, someone at a site compares the charger detail page to
the label in front of them, during normal work rather than as an errand.

All eight clean ⇒ seed stands, production is never re-stencilled. Any mismatch ⇒
correct that row before 04, or if the register turns out broadly untrustworthy,
restart production at `VOW1001` and re-stencil all twelve so no new code can alias an
old sticker.

**Prior probability is good.** Production holds 1, 2, 3, 6, 7, 8, 9, 10 and staging
holds 1, 2, 4, 5; the union covers 1–10 with only staging's two clones duplicated,
and the production gaps at 4 and 5 are explained by those units living at the staging
site. That is what a maintained register looks like. `name` is very likely accurate —
it is merely unvalidated, so "very likely" is the strongest claim available without
looking.

### 01 — Column, enum, constraints
Aerich migration adding `Charger.asset_code` (`VARCHAR(12)`, **nullable**, `UNIQUE`,
`CHECK (asset_code ~ '^VOWS?[0-9]{4,}$')` plus a series `CHECK` built in `upgrade()`
from `ENVIRONMENT`, following migration 50's pattern) and `Charger.purpose`
(`CharEnumField`, default `PUBLIC`, `NOT NULL`). `CHARGER_CODE_SERIES` +
`charger_code_series()` land in `backend/policy.py` beside `FRANCHISEE_CODE_BLOCKS`,
with the same fail-safe direction — unknown `ENVIRONMENT` resolves to `VOWS`, never
`VOW`. Nullable now; 03 makes it `NOT NULL`. No behaviour change.

### 02 — Allocation on create
`Charger.asset_code` assigned server-side at creation: `max + 1` within the
register, monotonic, gaps never backfilled, never reused. Not a field on
`ChargerCreate` (`routers/chargers.py:29`) and not editable via `ChargerUpdate` —
attempting to set it is a `422`, not a silent ignore. Concurrent creation is
resolved by the `UNIQUE` constraint with a bounded retry; creation is rare and
admin-driven. **Must land before 03**, or the `NOT NULL` flip breaks charger
creation.

### 03 — Backfill and `NOT NULL`
Applies an **explicit map**, not a derivation. `upgrade()` never reads
`Charger.name`; the map is generated offline from
`asset-code-assignments.csv` and baked into the migration as literal data, so what is
reviewed is exactly what executes. A derivation would re-read `name` at run time, and
`name` is freely editable — anyone touching it between review and deploy would
silently change the result.

**Keyed on `charge_point_string_id`**, never `Charger.id`. Row ids differ per register
(production 25–38, staging 1–10) and can be reused if a row is deleted and recreated;
the UUID is immutable and unique. Shape:

```python
ASSET_CODE_BACKFILL = {
    "production": {"7536bc02-…": ("VOW0001", "PUBLIC"), …},   # 13 rows
    "staging":    {"ffeadb01-…": ("VOWS0001", "PUBLIC"), …},  #  9 rows
}
```

Selected by `ENVIRONMENT` inside `upgrade()`, the same way migration 50 builds its
per-register CHECK from one shared file. **Development is not mapped** — a local DB
holds arbitrary chargers, so dev allocates sequentially instead of requiring a map,
or every dev box breaks on migrate.

Four guards, each raising rather than skipping quietly:

1. Every UUID in the map exists in the target register.
2. Every row with `asset_code IS NULL` is covered by the map — catches a charger
   created between CSV generation and deploy.
3. Only rows with `asset_code IS NULL` are written, so a re-run is idempotent.
4. Post-condition: zero `NULL` codes before the `NOT NULL` flip.

Also sets `purpose = TEST` on the ten bench units, from the same map. Then flips
`asset_code` to `NOT NULL`.

Because the map is literal and reviewable, this slice is fully deterministic — which
is what lets slice 00 gate 04 rather than gating this.

### 04 — Customer surfaces render the code   *(blocked by 00)*
One canonical serializer; no surface hand-formats. Replaces
`charge_point_string_id` on the QR landing page (`frontend/app/charge/[id]`), the
GST invoice PDF (`services/invoice_service.py:743`), `/my-charges`, `/my-sessions`,
and the Razorpay QR description (`routers/qr_codes.py:65-66` — which currently
falls back to a truncated UUID when `name` is null). Adds the three
`GSTInvoice` snapshot columns: `charger_id_str` keeps holding what was printed,
`charger_station_id` and `charger_ocpp_id` join it. Backfill `charger_id_str` only
`WHERE pdf_url IS NULL`, so no issued PDF changes.

### 05 — Support lookup
Admin/franchisee surfaces show the code and search on it, normalising by parsing
the integer part (`VOW0001`, `VOW00001`, `vow1` → one row; foreign series
rejected, not coerced). Touchpoints per issue 06 of the old map.

### 06 — Public visibility filter
`_fetch_stations_with_availability` filters `purpose != TEST`. Safe to ship any
time after 03; before 03 it is a no-op because everything defaults `PUBLIC`.
Fixes the five production bench units currently inflating `total_chargers`.

### 07 — StartTransaction gate
`main.py`, immediately after the `user.is_active` check (`:874`), same `Blocked`
idiom: a `TEST` charger rejects any user not in `INTERNAL_ROLES`
(`core/roles.py:19` — `{ADMIN, FRANCHISEE}`). Ship last, after 03 is verified in
each environment. Billing and invoice suppression ride along here.

### 08 — Drop `Charger.name`  *(deferred; entry conditions below)*
The contract half of an expand/contract, following the pattern and the reasoning of
`.scratch/diagnostic-bundle-headerless/issues/09`. Slice 04 stops `name` being
load-bearing; this removes it. **Deliberately separate and deliberately later** —
dropping it alongside 03 would destroy the only record of the fleet's painted
numbers, which is both the backfill's seed and slice 00's evidence, with no way back
if the code underperforms in the field. This effort has already been wrong twice
about what it could rely on. The column costs nothing to keep for a release.

Note this reverses a charter decision — the 2026-07-31 grilling explicitly chose
"keep `name` free-form for easy identification; add a NEW synthetic unique display
code for correctness". Reversing it is defensible once the code has proven it can
carry recognition on its own, but it is a reversal and should be recorded as one,
not slipped in.

**Entry conditions — do not start until all hold:**

1. Slices 04 and 05 live in **both** environments through at least one full billing
   cycle, with GST invoices issued carrying an Asset Code.
2. Support has resolved at least one customer-quoted code end to end.
3. No code references `Charger.name` outside migrations and ADRs — **19 backend
   render sites** (`chargers`, `franchisee_portal`, `firmware`, `qr_codes`,
   `public_stations`, `public_qr_*`) and **19 frontend files**.
4. Anything `name` legitimately carried has been moved first: `V3C_Test`,
   `V7C_Test`, `Chargemode_1` are hardware type and belong in `Charger.model` /
   `Charger.vendor`, which already exist. Capture before dropping; provenance notes
   like `Staging_VOW0004` are noise and are allowed to be lost.

Aerich-generated. **Never hand-edit a past migration to remove the column** — the
`aerich.content` snapshot stays poisoned and every future `aerich migrate` re-emits
the cleanup as an unrelated ALTER.

## Physical work

- **Production: none.** Seeding makes the register agree with the paint on day one.
- **Staging: four labels at IDT_Staging** (`VOW0004` → `VOWS0004`). Digits
  preserved so a re-stencilled unit reads back to its old sticker.
- **Bench units: none.** Nobody reads a code off a bench unit.

## Standing risk

`Charger.name` remains free-form, nullable and unvalidated through slices 00–07 — it
is just no longer load-bearing for identity after 04. Slice 03 is the last time
anything trusts it, and slice 08 removes it once the code has proven itself. Adding a
trim-and-non-empty validator in the meantime is cheap but buys little now that the
column is on a path out; skip it unless 08 slips.

## Out of scope

- **Deleting the production bench units** instead of flagging them. Evaluated
  2026-09-03 and rejected: charger 27 carries GST invoice `VL/QR/202627/00001` and
  the FK cascade would delete it, and chargers 27 and 29 hold live Razorpay QR codes
  that a row delete does not close. See `asset-code-assignments.md`.
- `Charger.name` uniqueness or validation beyond trim — it stays free-form and is
  no longer load-bearing for anything.
- `external_charger_id` cleanup.
- The unbounded `build_qr_description` business-name term, and the double space in
  `Franchisee.business_name` — real, but pre-existing and independent (see issue 04
  of `.scratch/charger-display-identity/`).
