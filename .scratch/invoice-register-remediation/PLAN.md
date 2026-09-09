# Invoice register remediation

Three independent defects in the GST Invoice register, found 6 August 2026 while preparing evidence for a chartered accountant meeting. All three stem from the same root: **a legal document was allowed to derive its identity from infrastructure artefacts** — a database primary key and an unvalidated environment variable.

## The defects

| # | Defect | Scope | Provision |
|---|---|---|---|
| 1 | Supplier GSTIN belongs to a different registered person | All 1,200 invoices | Rule 46 |
| 2 | Invoice numbers exceed the 16-character limit | All 1,200 (18–22 chars) | Rule 46(b) |
| 3 | Two invoice numbers issued twice under one GSTIN | 2 numbers, ₹50.93 | Rule 46(b) |

The GSTIN `32AAIFI0458G1ZN` printed on every invoice as `VOLTLYNC PRIVATE LIMITED` is registered to **IDOFTHINGS** — verified on the GST portal, 6 August 2026.

## Register scope

Production and staging share one GSTIN, one financial year and live Razorpay keys. Both have issued real tax invoices for real supplies; staging is **70% of the register by value** and is not a test system in any sense that matters to GST.

| | Invoices | Gross | Output GST | Franchisees |
|---|---|---|---|---|
| Production | 310 | ₹20,652.94 | ₹3,150.65 | 3 |
| Staging | 890 | ₹47,545.50 | ₹7,253.28 | 5 (2 with invoices) |
| **Combined** | **1,200** | **₹68,198.44** | **₹10,403.93** | **8** |

## Decisions taken

- **Two registers, not one.** Merging is a high-risk migration of financial records for no compliance benefit — Table 7 GSTR-1 filing is a consolidated rate-wise figure and never needs invoice numbers in one table. Rule 46(b) expressly permits "one or multiple series".
- **Never renumber an issued invoice.** The old format becomes a closed series; the new one starts at cutover. This includes the two duplicates — both copies of `VL/F2/QR/202627/00001` were rendered to PDF, so no clean renumbering exists.
- **Correct the GSTIN on all 1,200 rows** (CA opinion, 7 August 2026 — the printed bills may be corrected). An earlier draft proposed correcting only the 1,129 never-rendered rows and freezing the 71 already delivered; that split is superseded. The change is one `UPDATE` per register setting `supplier_gstin` and clearing `pdf_url`, plus explicit deletion of the 71 stored S3 objects — regeneration overwrites the same deterministic key, but only if that invoice is ever downloaded again, so stale documents would otherwise persist in the bucket.
- **The correct GSTIN is not yet known** and is the only hard blocker on issue 03.
- **Enforce partitioning in the database, not by agreement.** The previous arrangement relied on nobody creating a colliding franchisee, and failed silently for three months.

## Slices

| # | Slice | Type | Blocked by |
|---|---|---|---|
| 01 | Franchisee invoice code with partitioned allocation | AFK | — |
| 02 | New 16-character invoice number series | AFK | 01 |
| 03 | Supplier GSTIN correction — all 1,200 invoices | **HITL** | file note (CA confirmed 7 Aug) |
| 04 | Fail loudly on missing or mismatched supplier identity | AFK | deploy after 03 |
| 05 | Property-based invariant tests for invoice reconciliation | AFK | 02 (numbering half only) |

## Out of scope — needs its own feature

**Environment isolation.** Staging holds live Razorpay keys and has issued the majority of our tax invoices. That is the root cause behind the duplicate numbering and it is larger than this remediation: it means deciding whether staging is a second production environment or whether its chargers move to production, then rebuilding a genuinely isolated test environment with test credentials. Tracked separately.

Also deferred: the shared Razorpay linked account `Sum1WSDEGbyNL1`, mapped to R Shyam Shankar in production and Makara Tech in staging (no money has moved — staging franchisee 1 has zero settlements and the value is missing its `acc_` prefix), and ₹12.62 of customer refunds stuck below Razorpay's ₹1 floor across 46 payments.
