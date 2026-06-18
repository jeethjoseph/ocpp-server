# GST invoice date, financial year, and numbering are derived in IST (issue-time basis)

Status: accepted

A **GST Invoice**'s date, **Financial Year**, and serial number are all derived from the **issue instant** (when the `GSTInvoice` row is generated, ≈ session finalize / StopTransaction) **expressed in IST** — not UTC, and not the session-start instant. The database keeps storing instants in UTC; IST is applied only at derivation (FY, numbering) and presentation (PDF, admin filings view, GSTR-1 CSV). The session-*start* instant is shown separately as `charged_on` ("Charging date/time") and is informational only.

## Why

GST is an Indian statutory regime: the invoice "date of issue," the Apr–Mar financial year, and GSTR-1 monthly return periods are all IST concepts — the GST portal and the filing CA work in IST, and UTC has no meaning in compliance. Before this decision everything was computed from `datetime.utcnow()` (`invoice_service.py` FY derivation; `invoice_date` via `auto_now_add`; PDF and the GSTR-1 CSV rendered the raw UTC instant). For any invoice timestamped in the ~5.5h after IST midnight (still the previous day in UTC), this produced the wrong printed date, and — worse — the wrong **monthly filing period** (~66h/year of timestamps) and, at the Apr-1 boundary, the wrong **financial year and serial sequence**. The CSV the CA reconciles against is the most compliance-critical surface and was UTC.

## Considered options

- **Issue-time basis in IST (chosen).** Orthodox GST "date of issue." Because serial numbers are also allocated at issue, number order and date order always agree — no wobble. `invoice_date` already stores the finalize instant, so nothing about what we store changes.
- **Session-start basis in IST (rejected).** Customer-friendlier ("the day I plugged in"), but non-standard for a tax invoice, and it desynchronises number order from date order on sessions that straddle midnight (numbers are issued at finalize, dates at start). The customer still sees the plug-in time via `charged_on`, so the UX benefit is largely preserved without making it the legal date.
- **Store `invoice_date` as an IST `DATE` column + backfill (rejected).** Would make every read timezone-free, but requires a schema migration and a historical backfill, and breaks the project's "DB datetimes are UTC" convention ([[project-admin-ui-ist-server-utc]]). Not worth it given the conversion is confined to a few read sites behind one helper.

## Consequences

- No schema migration and no model change. The only writes that change are the FY computation at row creation (`to_ist(now)` instead of `utcnow()`).
- A single `to_ist()` helper (fixed +5:30 — India observes no DST) is the one conversion point, used at exactly three read sites: PDF render (`invoice_date` + `charged_on`), the admin filings date-range filter (translate the IST bounds to UTC for the indexed query), and the GSTR-1 CSV/JSON (emit the IST date). Any new surface that shows an invoice date MUST route through it.
- Forward-only. No historical correction: invoice PDFs are generated lazily and frozen in S3 on first download, so documents customers already hold are unchanged; only the admin filings view/CSV reinterpret old rows in IST, which is accepted.
- See `CONTEXT.md` → **Invoice Date** / **Financial Year (FY)** for the glossary definitions this ADR backs.
