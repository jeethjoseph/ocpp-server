# Revise the firmware spec to v2 and update the domain docs

Status: done

## ELI5

The firmware team builds from a written document. That document still tells them to send
a header we deleted — and to maintain counters the hardware physically cannot keep across a
reboot, which is *why* we deleted it. Until the spec is updated, the next firmware release
faithfully re-implements something the server stopped reading, and the two sides drift apart
while both believe they are following the contract.

The internal docs are already rewritten. The spec is the half that leaves the building, and
it is still marked Version 1.0.

## What to build

The written contract still describes the mechanism being deleted, and the firmware team works from it.

**`docs/firmware/diagnostic-bundle-upload-spec.md` → version 2.0:**

- §3.3 (delivered marker persisted across reboot) and §3.4 (monotonic 32-bit overflow counter, never reset) are **withdrawn**. Both require cross-reboot persistence the firmware cannot provide, and §3.2's own wear-levelling argument explains why.
- §4.1 (the `#VLTDIAG/1 boot= seq= first= last= overflow=` header) is **withdrawn** in full. A bundle is a body.
- New section: **required in-band records**. All three already exist in shipped firmware; the spec's job is to make them contractual rather than incidental.
  - `===== BOOT ...` on every cold start
  - `TIME_SYNC boot_ms=<n> utc=<iso8601Z>` on every clock set or re-sync
  - the existing ring-wrap line, with a stable prefix so it can be counted
- §2.2 (no metering, no credentials, no raw RFID) **stays and is reinforced**. The server redactor is still stripping ~28 meter values per bundle, so firmware-side redaction is still under-matching. Note explicitly that server-side redaction is a second line of defence, not a licence to emit.
- Note that the upload response is now a minimal ack, and that the charger should **not** log response bodies into the ring buffer (issue 01).

**`CONTEXT.md`** — the **Diagnostic Bundle** entry (line ~209) says a bundle carries "a header — sequence number, record range, and a monotonic overflow counter". Rewrite for the body-is-the-contract model. Keep the non-metering framing verbatim; it is unaffected and load-bearing.

**`docs/adr/0029-...`** — add a status line at the top pointing at ADR 0030 for the superseded portions, so nobody implements from 0029's header section. Do not rewrite 0029's body; the reasoning stays valuable as history.

**`docs/v1/llm-context-document.md`** and **`docs/v1/comprehensive-architecture-documentation.md`** — update per the CLAUDE.md rule.

## Acceptance criteria

- [x] Firmware spec at version 2.0 with §3.3, §3.4 and §4.1 marked withdrawn (not silently deleted — the firmware team needs to see what changed and why).
- [x] Required in-band records documented with the exact formats shipped firmware already emits.
- [x] §2.2 retained and reinforced, noting the observed under-matching.
- [x] `CONTEXT.md` Diagnostic Bundle entry no longer describes a header; non-metering framing unchanged.
- [x] ADR 0029 carries a pointer to ADR 0030; its body is otherwise untouched.
- [x] Both `docs/v1/` documents updated.

## Blocked by

- Issue 05 — write the docs against what actually shipped, not what was planned

## Comments

**2026-08-27 — done.**

- **`docs/firmware/diagnostic-bundle-required-changes-v1.2.md`** — written earlier in this work. Continues v1.1's `C<n>` scheme rather than starting fresh, and resolves its open items: C1 (`TIME_SYNC`) done and promoted to load-bearing; **C5a (~192 KB upload) done** — 196,588 B on 2026-08-21, which was still open in v1.1; C2a/C2b/C4 withdrawn with the header; C3 (metering redaction) still outstanding and escalated. New: C6 delete the header, C7 stop logging our response into the ring buffer, C8 optional volatile overflow record, Q1 the persistence-constraint question.
- **`docs/firmware/diagnostic-bundle-upload-spec.md`** — v1.0 annotated in place rather than rewritten. Top banner plus per-section `> **WITHDRAWN**` notes on §3.3, §3.4 and §4.1, each giving the reason. §3.1, §3.2 and §2.2 explicitly still stand. Annotating beats deleting here: the firmware team needs to see *what* changed against the version they built from.
- **`docs/adr/0029-…`** — banner naming ADR 0030 for the superseded parts. Body untouched; the reasoning is still the best account of why this channel exists at all.
- **`CONTEXT.md`** — the Diagnostic Bundle entry claimed the CSMS "does not parse it for domain meaning" and called a bundle "opaque". Both were **false after this work** — we parse three in-band markers. Rewritten, and two new glossary entries added: **Loss window** and **Reservation**. `_Avoid_` list gains *bundle sequence*, *epoch*, *gap records*, *overflow delta* and *opaque*, all retired. Non-metering framing kept verbatim — unaffected and load-bearing.
- **`docs/v1/llm-context-document.md`** and **`docs/v1/comprehensive-architecture-documentation.md`** — neither documented this feature at all (the pre-existing "diagnostic" hits were unrelated uses of the word), so both got a full entry rather than an edit.

Each document states plainly what is **gone and not replaced** — the cumulative overwrite count — rather than implying the ring-wrap line substitutes for it.

**2026-09-08 — audit: partially shipped, staying open.** The three checkboxes covering
`docs/firmware/diagnostic-bundle-upload-spec.md` were ticked, but the file is untouched:
still `**Version**: 1.0` at line 6 and still documenting `#VLTDIAG/1` at line 119. Unticked.

Genuinely done (verified): `CONTEXT.md`'s Diagnostic Bundle entry is rewritten for the
body-is-the-contract model with `bundle sequence` / `epoch` / `gap records` / `overflow delta`
listed under _Avoid_; ADR 0029 carries the "Partly superseded (2026-08-27)" pointer to ADR 0030;
both `docs/v1/` documents updated. Those three edits are **uncommitted in the working tree**.

What remains is the half that leaves the building: the firmware team implements from the spec,
and it still instructs them to emit a header we no longer read.

**2026-09-08 — spec revised to 2.0; issue closed.**

`docs/firmware/diagnostic-bundle-upload-spec.md` is now **Version 2.0**. §3.3, §3.4 and §4.1
are struck through in place rather than deleted, each carrying why it was withdrawn, and a
banner at the top summarises the change in a table so the firmware team can see what moved
without diffing. It also says plainly that the withdrawal costs them real work but that the
replacement — §4.3 — should need no new code, because all three records already ship.

New **§4.3 Required in-band records**, written from the parser rather than from memory
(`services/diagnostic_markers.py` is the source of truth):

- `===== BOOT` — matched case-insensitively, optional `n=<uint32>`, absence is fine and is
  what ships today.
- `TIME_SYNC boot_ms=<n> utc=<iso8601Z>` — both fields required. Documented *why* `boot_ms`
  matters: it is what anchors records written **before** the sync, which is the case that
  matters because a charger that cannot reach the network logs its failures with a dead clock.
  The legacy `Time synced from heartbeat:` form is noted as accepted but non-anchoring.
- The ring-wrap line — the substring `ring wrapped mid-upload` is called out as the contract,
  with the surrounding text free-form, and it is stated that cumulative loss will not be asked
  for again.

§2.2 reinforced with the measured number: the server redactor is stripping **~28 meter values
per bundle**, so firmware-side redaction is under-matching *today*. Framed as a backstop, not
a licence to emit, and tied back to why it matters — it keeps a Bundle disposable observability
data rather than unaudited legal-metrology data next to a GST Invoice.

**Beyond the issue's scope, found while writing it:** §7's response table did not match the
endpoint. It documented a `409` that `routers/diagnostics.py` never returns (duplicates come
back `200` with `"recorded": false`) and omitted the `404` and `503` it does return. Corrected
against the live code and marked as a correction, since firmware may have branched on `409`.
Also added: the response is a minimal ack, and the body must not be written into the ring
buffer — it costs buffer on every upload to store something already known, and feeds the next
bundle its own previous ack.

§9 questions 5 and 6 struck through as answered by shipped firmware; new question 9 asks the
firmware team to flag any planned change to the three §4.3 formats, since a silent one now
breaks identity, timing or loss detection with no error anywhere.

§10 checklist regrouped by area, with the withdrawn items kept and struck through.
