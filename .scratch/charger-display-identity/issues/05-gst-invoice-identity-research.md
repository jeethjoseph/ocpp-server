# Research: GST invoice equipment-identity requirements

**Note 2026-08-24:** no findings file was ever written to `research/` — the
subagent output is missing, so treat this as unanswered. ADR 0028 proceeded on the
assumption the charger line is informational, and kept `GSTInvoice.charger_id_str`
as an internal snapshot either way. Worth closing out before the invoice PDF
change ships.

Status: ready-for-agent
Labels: wayfinder:research
Assignee: research-subagent (fired 2026-07-31)
Blocked-by: (none)

## Question

The charter decision replaces the printed "CHARGER ID: {uuid}" on the GST invoice
PDF with charger name + display code, keeping the UUID only as an internal
snapshot. Before the spec locks: does Indian GST law/rules (CGST Rules invoice
particulars, e-invoicing schema if applicable) impose ANY requirement on
identifying the supplying equipment/charging point on a tax invoice — format,
uniqueness, or presence at all? Or is the charger line purely informational, in
which case we have full freedom?

Also: any EV-charging-specific guidance (Ministry of Power charging
infrastructure guidelines) that references charger identification on customer
receipts.

Output: findings file at `research/gst-invoice-equipment-identity.md` in this
feature directory, with sources; resolution comment summarizing whether any
constraint binds the invoice rendering.
