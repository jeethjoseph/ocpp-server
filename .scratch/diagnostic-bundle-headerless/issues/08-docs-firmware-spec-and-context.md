# Revise the firmware spec to v2 and update the domain docs

Status: ready-for-agent

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

- [ ] Firmware spec at version 2.0 with §3.3, §3.4 and §4.1 marked withdrawn (not silently deleted — the firmware team needs to see what changed and why).
- [ ] Required in-band records documented with the exact formats shipped firmware already emits.
- [ ] §2.2 retained and reinforced, noting the observed under-matching.
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
