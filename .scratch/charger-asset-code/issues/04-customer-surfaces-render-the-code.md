# Customer surfaces render the Asset Code

Status: ready-for-agent

## What to build

Stop showing customers a UUID. This is the slice the whole effort exists for.

Two customer surfaces currently print `charge_point_string_id`: the QR landing page and
the `CHARGER ID:` line on the GST invoice PDF. That value is a UUID4 that also serves as
the OCPP WSS path segment and the HTTP Basic Auth **username**, so printing it on a PDF
that lands in a stranger's inbox publishes half a credential pair. A third surface,
`/my-charges`, shows `Charger.name` — nullable free text with no uniqueness, so
"Charger 3" can name four different units. The Razorpay QR description currently falls
back to a **truncated UUID** when `name` is null, which is the worst of both.

Replace all of them with the Asset Code, rendered as `CHARGER: VOW0001`.

**One canonical serializer. No surface hand-formats.** That rule is the entire point —
the disagreeing-fallback problem across three call-site families is what ADR 0028 exists
to end, and it comes straight back the moment two surfaces each build the string
themselves.

`charge_point_string_id` stays visible on admin and franchisee surfaces, where ops needs
it for log correlation and firmware deploys. It is scrubbed from customer surfaces only.

The GST Invoice also gains three snapshot columns. `charger_id_str` keeps holding exactly
what was **printed** — a UUID before the cutover, an Asset Code after, the two eras
separable by `^VOWS?\d{4,}$`. It keeps its name despite the avoid-list, because it is a
header in the GST filings CSV that feeds an accountant's spreadsheet and renaming it
would silently break saved import mappings on a compliance surface. Two internal columns
join it, never printed and never exported: `charger_station_id` (the station as of
issuance, so a compliance query never parses a string) and `charger_ocpp_id` (the
`charge_point_string_id`, the audit link to the physical unit across the cutover).

**Backfill `charger_id_str` only `WHERE pdf_url IS NULL`.** Issued invoices are frozen tax
documents and stay byte-identical. This was ruled out in the charter and is not
negotiable.

## Acceptance criteria

- [ ] One serializer produces the rendered code; the QR landing page, GST invoice PDF, `/my-charges`, `/my-sessions` and the Razorpay QR description all call it.
- [ ] No customer-facing surface renders `charge_point_string_id`, in full or truncated. Grep proves it.
- [ ] Admin and franchisee surfaces still show `charge_point_string_id`.
- [ ] The Razorpay QR description no longer has a UUID fallback path.
- [ ] `GSTInvoice` gains `charger_station_id` and `charger_ocpp_id`; neither appears in the GST filings CSV export.
- [ ] The `charger_id_str` backfill touches only rows with `pdf_url IS NULL`. A test asserts an issued invoice is unchanged.
- [ ] A newly issued invoice carries an Asset Code in `charger_id_str` and the OCPP UUID in `charger_ocpp_id`.
- [ ] Aerich-generated migration.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.
- [ ] `cd frontend && npm run build` **and** `npm run lint` both pass.

## Blocked by

- [03 — Backfill every charger from the explicit map, then flip to NOT NULL](03-backfill-and-not-null.md)
- [00 — Confirm the eight production stencils](00-confirm-production-stencils.md) — **do not deploy this to production until 00 is signed off.** This is the slice where the code becomes permanent, because it starts landing on GST Invoices. Before it, a wrong code is an `UPDATE`; after it, it is on an issued tax document that cannot be retro-edited.
