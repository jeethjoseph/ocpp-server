# Correct the supplier GSTIN on all GST Invoices

Status: ready-for-human

## What to build

Every **GST Invoice** issued across both registers — 1,200 of them, ₹68,198.44 gross, ₹10,403.93 output tax — carries GSTIN `32AAIFI0458G1ZN` under the supplier name `VOLTLYNC PRIVATE LIMITED`. That registration was verified on the GST portal on 6 August 2026 and belongs to **IDOFTHINGS**, a different registered person. **Rule 46 CGST** requires the name and GSTIN on a tax invoice to belong to the same registered person.

Cause: the supplier name is a hardcoded default in the invoice service and the GSTIN comes from an environment variable that defaults to empty. Neither was ever validated against the other, and a later migration retrospectively stamped the name across all pre-existing rows.

**The number is wrong, not the name.** VoltLync Private Limited is the operating entity and returns were filed manually under its own registration. Per CA opinion of 7 August 2026 the printed bills may be corrected, so this covers **all 1,200 invoices** in both registers — there is no rendered / never-rendered split.

### The correct GSTIN

**`32AALCV6461E1ZA`** — supplied 12 August 2026. Structural verification passed:

| Check | Value | Result |
|---|---|---|
| State code | `32` | Kerala — matches |
| PAN | `AALCV6461E` | |
| Entity type (PAN char 4) | `C` | **Company** — consistent with "PRIVATE LIMITED" |
| Name initial (PAN char 5) | `V` | consistent with VoltLync |
| Mod-36 check digit | `A` | **valid** |

For contrast, the GSTIN currently on every invoice (`32AAIFI0458G1ZN`) carries `F` (firm or LLP) and name initial `I` — the contradiction issue 04's startup guard is designed to catch.

**Still outstanding:** the structural check proves the number is well-formed and internally consistent. It does not prove the registration is live or that its legal name reads VOLTLYNC PRIVATE LIMITED. Confirm both via GST portal → Search Taxpayer before running the UPDATE, exactly as was done for the IDOFTHINGS number on 6 August.

### The change itself

Two columns, one statement per environment:

```sql
UPDATE gst_invoice
   SET supplier_gstin = '<correct GSTIN>',
       pdf_url        = NULL;
```

`pdf_url` is cleared so the PDF regenerates from the corrected row on next download. For the 1,129 rows where it is already NULL this is a no-op; for the 71 with a stored PDF it is what makes the correction visible at all — the download endpoint short-circuits on `pdf_url` and would otherwise keep serving the old object forever.

### The 71 stored PDFs must also be deleted from S3

Clearing `pdf_url` alone is not sufficient. The S3 key is deterministic (`invoices/{FY}/{owner}/{invoice_number}.pdf`), so regeneration overwrites the same object — **but only if and when someone downloads that invoice again.** The 71 with stored PDFs are precisely the ones already downloaded, and many will never be fetched again. Their objects would otherwise sit in the bucket carrying the wrong GSTIN indefinitely, and a bucket-level export taken for an audit would return the uncorrected document.

Delete all 71 objects explicitly as part of the correction. Presigned URLs expire after 15 minutes, so there is no meaningful window of stale links to worry about.

### Regenerated PDFs differ cosmetically

A re-rendered invoice reads "Tariff quoted (incl. GST)" where the original said "(all-inclusive)" — a wording change recorded in ADR 0026. **Every figure is identical**, because each PDF rebuilds from its own stored component fields. Note it in the file note and move on.

### Human prerequisite: the file note

Written, dated and committed **before** the UPDATE runs. GST provides no statutory mechanism to amend an issued tax invoice — revised invoices under Rule 53(2) cover only the pre-registration window, and s.34 credit notes cover value and tax, not identity fields. The correction therefore sits outside the statutory instruments, and the contemporaneous record is what carries the **s.126(5)** voluntary-disclosure mitigation. Its evidentiary weight comes from a responsible person in the company attesting to it on the date the defect was found, which is why this step is not delegable.

The note must record: what was wrong, when discovered, the cause, that all 1,200 rows were corrected on CA advice of 7 August 2026, the cosmetic PDF wording change, that no recipient could claim ITC (the schema has no recipient-GSTIN field, so every supply is B2C), and the two duplicate invoice numbers left in place under issue 02.

Export the original `supplier_gstin` for all 1,200 rows and commit it alongside the note. Archiving the 71 PDF files themselves is optional and low value — every figure on them is reproducible from the stored row, so the export is the meaningful record.

## Acceptance criteria

- [x] VoltLync Private Limited's correct GSTIN obtained and recorded — `32AALCV6461E1ZA`
- [x] GSTIN structurally verified: state code `32`, PAN entity type `C`, name initial `V`, check digit valid
- [x] GST portal confirms the registration is Active and its legal name reads VOLTLYNC PRIVATE LIMITED — verified 12 August 2026
- [x] `VOLTLYNC_GSTIN` corrected in `.env.prod` and `.env.staging`; both backends recreated and confirmed serving `32AALCV6461E1ZA` — 12 Aug 2026
- [x] Original `supplier_gstin` exported for all rows and committed (`docs/compliance/gstin-correction-original-values-{prod,staging}.csv`)
- [x] `supplier_gstin` corrected and `pdf_url` cleared — **338 production, 949 staging, 1,287 total**; zero rows remain on the old GSTIN
- [x] All 77 stored PDF objects deleted from S3 (25 prod, 52 staging); keys retained in `docs/compliance/s3-keys-{prod,staging}.txt`
- [x] Idempotent — the `WHERE supplier_gstin = <old>` filter means re-running reports zero changes
- [x] Reconciles: single distinct supplier pair in each register, no invoice number altered
- [ ] **File note completed, dated and attested** — draft at `docs/compliance/2026-08-gstin-correction-file-note.md`, figures updated, bracketed fields outstanding
- [x] Spot-check passed — text extracted from both regenerated PDFs shows `VOLTLYNC PRIVATE LIMITED` / `GSTIN: 32AALCV6461E1ZA`, with the old GSTIN absent:
  - `VL/F1/QR/202627/00070` (id 197) — had a stored PDF that was deleted, so this proves the delete-and-regenerate path
  - `VL/F3/QR/202627/00117` (id 348) — issued 15:22 IST on 12 Aug, 34 minutes after the container was recreated, so this was generated correctly from config with no correction applied
  - Note for anyone re-running this check: a raw byte search of the PDF finds neither GSTIN. DejaVu is embedded as a font subset and text is written as glyph indices, not ASCII. Use text extraction (e.g. PyMuPDF), not `grep`.

## Blocked by

- **The file note**, which must exist and be dated before execution. This is now the only remaining gate — the GSTIN is obtained, structurally verified, and confirmed Active on the portal under the correct legal name (12 August 2026). A draft is at `docs/compliance/2026-08-gstin-correction-file-note.md`, pending review and attestation.
- Ordering note: run this **before** issue 04's startup guard is enforced, or the corrected environment variable will fail validation while historical rows still disagree.
