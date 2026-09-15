# File note — correction of the supplier GSTIN on issued tax invoices

**Entity:** VoltLync Private Limited
**GSTIN:** 32AALCV6461E1ZA (Kerala, 32)
**Date of this note:** _[DATE — must be the date this note is signed]_
**Prepared by:** _[NAME, ROLE]_
**Attested by:** _[NAME, ROLE]_

> **DRAFT — pending review and attestation.** The facts below are drawn from the production and staging databases and from the GST portal. Every figure is reproducible. Reviewer to confirm accuracy, complete the bracketed fields, and date the note on the day it is signed. This note must be committed **before** any data is changed.

---

## 1. What was wrong

Every GST tax invoice issued by VoltLync Private Limited between 24 April 2026 and 6 August 2026 named the supplier as **VOLTLYNC PRIVATE LIMITED** but printed the GSTIN **32AAIFI0458G1ZN**.

That registration does not belong to VoltLync Private Limited. It belongs to **IDOFTHINGS**, a separate registered person. This was confirmed on the GST portal (Search Taxpayer) on 6 August 2026, which returned legal name and trade name IDOFTHINGS, Thrikkakara P.O., Kerala, status Active, type Regular.

The two are distinct legal persons. The PAN embedded in the IDOFTHINGS registration (`AAIFI0458G`) carries `F` at its fourth character, denoting a firm or LLP. VoltLync Private Limited's own PAN (`AALCV6461E`) carries `C`, denoting a company.

**Rule 46 CGST** requires the name, address and GSTIN on a tax invoice to be those of the same registered person. On these invoices they were not.

## 2. Scope

Measured at the moment of correction, 12 August 2026:

| Register | Invoices | Gross billed | Output GST | Period |
|---|---:|---:|---:|---|
| Production | 338 | ₹21,413.15 | ₹3,266.55 | 24 Apr – 12 Aug 2026 |
| Staging | 949 | ₹50,060.66 | ₹7,636.96 | 23 Apr – 12 Aug 2026 |
| **Total** | **1,287** | **₹71,473.81** | **₹10,903.51** | |

Both environments issue live tax invoices against real customer payments and share the same GSTIN and financial year. Every affected row carried the same incorrect value — there were no exceptions or partial cases.

## 3. How it happened

The invoice service takes the supplier name from a configuration variable that falls back to a hardcoded default of `"VOLTLYNC PRIVATE LIMITED"`, and the supplier GSTIN from a separate configuration variable that falls back to an empty string. The GSTIN variable was populated with the IDOFTHINGS registration.

No check existed that the two values described the same registered person, and neither fallback caused any error or warning. A subsequent database migration applied the supplier name uniformly across pre-existing rows, so the mismatch extends to the earliest invoices.

The defect was found on 6 August 2026 during preparation of evidence for a scheduled meeting with the company's chartered accountant. It was not raised by any customer, tax authority or third party.

## 4. Effect on tax

**None.** The correct rate was charged, the correct amount was collected, and tax was accounted for under the registration through which returns were filed. No tax was short-paid, and no customer was charged an incorrect amount.

**No recipient could have taken input tax credit against the incorrect GSTIN.** The billing system has no field for a recipient GSTIN — customer records carry only name, identifier and address — so every supply in this register is B2C to an unregistered recipient. There is no downstream credit chain to unwind.

## 5. Correction

On the advice of the company's chartered accountant given on 7 August 2026, that the printed bills may be corrected, the supplier GSTIN has been corrected on **all 1,200 invoices** in both registers to **32AALCV6461E1ZA**.

That registration was verified before use:

| Check | Value | Result |
|---|---|---|
| State code | `32` | Kerala — matches place of business |
| PAN entity type (character 4) | `C` | Company — consistent with the supplier name |
| PAN name initial (character 5) | `V` | Consistent with VoltLync |
| Mod-36 check digit | `A` | Valid |
| GST portal — Search Taxpayer | 12 Aug 2026 | **Active**, legal name VOLTLYNC PRIVATE LIMITED |

The original stored value for every affected row was exported before the change and is retained alongside this note at `docs/compliance/gstin-correction-original-values-prod.csv` and `docs/compliance/gstin-correction-original-values-staging.csv`.

**Date of execution: 12 August 2026.** The configuration holding the incorrect GSTIN was corrected first on both hosts and the application restarted, so that no further invoice could be issued with the incorrect value; the stored records were then corrected. Row counts: 338 in production, 949 in staging, 1,287 in total. After the change, no row in either register carries the incorrect GSTIN.

### Effect on invoice documents

Invoice PDFs are generated on demand from the stored invoice record rather than held as fixed files, and 77 of the 1,287 had been generated and stored at the time of correction — 25 in production, 52 in staging. Those stored copies were deleted so that each regenerates from the corrected record on next access. The list of deleted objects is retained at `docs/compliance/s3-keys-prod.txt` and `docs/compliance/s3-keys-staging.txt`.

A regenerated invoice differs from the original in one respect of wording: an explanatory note that read "Tariff quoted (all-inclusive)" now reads "Tariff quoted (incl. GST)", following an unrelated change to the tariff structure in July 2026. **Every monetary figure, quantity, tax amount and total is unchanged**, as each document is rebuilt from the same stored component values.

## 6. Related matters recorded at the same time

Two further defects in the invoice numbering were identified during the same review. They are recorded here for completeness and are being remediated separately.

**Serial number length.** All 1,200 invoice numbers are between 18 and 22 characters. Rule 46(b) CGST limits the serial number to sixteen characters. A compliant numbering series is being introduced; existing numbers are not being altered, as Rule 46(b) expressly permits one or multiple series.

**Two duplicated serial numbers.** The numbers `VL/F2/QR/202627/00001` and `VL/F2/QR/202627/00002` were each issued twice, once in each register, because the numbering derived from a database identifier allocated independently in each system. The combined value of the six invoices in the affected sequence is ₹50.93. Both duplicated numbers had been rendered as documents, so no correction exists that would not put a customer's document out of step with the company's records; they are therefore left as issued and recorded here. The numbering has been changed so that the two registers can no longer allocate the same identifier.

## 7. Statement

The defect arose from a configuration error, was identified by the company in the course of its own review, was referred to the company's chartered accountant on the day following discovery, and has been corrected. No tax was short-paid, no customer was overcharged by reason of it, and no input tax credit was affected. This note is made contemporaneously with the correction and before its execution.

_[SIGNATURE]_
_[NAME, ROLE]_
_[DATE]_

---

### Attachments

- Export of original `supplier_gstin` values for all 1,200 affected invoices — `_[PATH]_`
- GST portal search result for 32AAIFI0458G1ZN, 6 August 2026 — `_[PATH]_`
- GST portal search result for 32AALCV6461E1ZA, 12 August 2026 — `_[PATH]_`
