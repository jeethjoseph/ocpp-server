# Lock the display-code format string

**Superseded 2026-08-27 by ADR 0028.** The resolution below is NOT the shipping
format. The per-station sequence and the hyphens are gone; the code is a system-allocated
running number, `VOW0001` (production) / `VOWS0001` (staging + dev), regex `^VOWS?\d{4,}$`,
minimum width four and widening by itself. What survived: the `VOW` literal — for exactly
the reason recorded below, that it is already on the fleet — and *one canonical
serializer, no surface hand-formats the code*. A 2026-08-24 draft in between derived the code from a bay
number; see ADR 0028's Considered options for why that was dropped.

Status: closed
Labels: wayfinder:grilling
Assignee: jeethjoseph (session 2026-07-31)
Blocked-by: (none)

## Question

Pin the exact format of the station-prefixed display code so every later surface
and migration renders it identically. Decide:

- Padding widths: `S01-C04` implies 2-digit fields — what happens when station id
  passes 99 or a station's charger sequence passes 99? (Fixed width that widens,
  e.g. `S100-C04`, vs wider padding up front, e.g. `S001-C004`.)
- Literal prefix letters: `S`/`C` as charted, or a brand prefix (`VLT-S01-C04`)?
  Note the UPI payee line has a ~17-char budget (see
  [04](04-upi-payee-with-code.md)) — longer formats eat into it.
- Separator and charset: hyphen, uppercase-only — confirm so validation/regex is
  writable.
- Canonical serialization: one function/property is the single source of truth;
  no surface hand-formats it.

Output: the format spec (regex + examples at boundary values) recorded in the
resolution comment.

## Comments

**Resolution (grilling, 2026-07-31):** format locked as **`VOW-S{station_id}-C{seq}`**,
both numbers zero-padded to 2 digits and widening naturally past 99.

- Examples: `VOW-S01-C04` (station 1, charger 4) · `VOW-S12-C09` · `VOW-S100-C04`
  (station 100 widens) · `VOW-S01-C112` (charger 112 widens)
- Regex: `^VOW-S\d{2,}-C\d{2,}$` — uppercase only, hyphen separators, no other
  charset. Typical length **11 chars**.
- Prefix literal is **VOW**, continuing the convention already stenciled on the
  fleet (`VOW0001`…), chosen over `VLT`/Voltlync branding. (2-digit pad chosen
  over 3-digit and no-pad; brand prefix chosen over bare `S01-C04` for
  self-identification out of context.)
- Canonical serialization: ONE function/property is the single source of truth
  (placement decided in [03](03-name-hygiene-and-fallback.md)); no surface may
  hand-format the code.
- Consequence flagged to [04](04-upi-payee-with-code.md): 11 of the UPI line's
  ~17-char charger budget goes to the code, leaving ~6 chars for any name part.
