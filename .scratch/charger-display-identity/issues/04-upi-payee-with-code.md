# UPI payee/description composition with the code

**Re-scoped 2026-08-27 by ADR 0028, and the premise below is wrong.** Two corrections.
(1) `build_qr_payee_name`'s 17-char cap is on Razorpay's QR **`name` metadata** field,
not the UPI payee — the QR is platform-owned (`account_id=None`), so a customer's app
shows VoltLync's registered merchant name and nothing we compose per-charger reaches it.
(2) The customer-visible string is `build_qr_description`, rendered on the QR image
(confirmed against a live staging QR: "Arunraj  R - Pay for EV charging at VOW0002"),
and it truncates **nothing** — neither business name nor charger.

Razorpay documents no max length for `name` or `description` on the Create QR Code API;
the repo's "~50 chars" comment is unverified. The real limit is rendering, and it is
empirical — 43 chars already wraps to two lines.

The **Asset Code** (`VOW0001` / `VOWS0001`, 7-8 chars) is not the term that drives that
line: the fixed text " - Pay for EV charging at " is 26 chars and the business name is
unbounded, so today's worst case is production's `S K Consultancy Services - Pay for EV
charging at VOW0006` (57). Still open: the composition and truncation rule, a guard on
the unbounded business name, and whether `Franchisee.business_name` gets the same
trim-at-the-boundary treatment (staging's reads "Arunraj  R", double space).

Status: ready-for-human
Labels: wayfinder:grilling
Assignee:
Blocked-by: (none — 01-lock-code-format.md closed 2026-07-31; code is
`VOW-S##-C##`, 11 chars typical, vs the ~17-char UPI charger budget)

## Question

`build_qr_payee_name()` / `build_qr_description()` (razorpay_service.py:142-159)
compose `"{business} - {charger}"` and truncate the charger part to **17 chars**;
callers currently pass `charger.name or charge_point_string_id`, so a null name
puts a truncated UUID on the customer's UPI payment screen.

With the display code available, decide what the UPI line shows:

- Name only, code only, or `"{name} {code}"` squeezed into the 17-char budget?
  (Code format length from [01](01-lock-code-format.md) determines what fits.)
- Truncation rule when name is long: hard cut (current) vs prefer dropping the
  name and keeping the code intact?
- RBI/Razorpay constraint check: payee-name rules from the existing compliance
  memory (platform-collects-first model) — confirm nothing here changes the
  disclosure posture.

Output: the exact composition + truncation rule for both payee and description.
