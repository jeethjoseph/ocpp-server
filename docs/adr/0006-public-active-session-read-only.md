# Active-session view on `/my-charges` is read-only — no remote-stop button

The `/my-charges` page surfaces a customer's in-progress QR session as a **read-only** card. There is no remote-stop button, no session-modify affordance, no admin-style controls. The customer's "I want to stop now" path is to unplug the cable (the OCPP `Finishing` flow handles it) or to let the synthetic-fee-based budget cap auto-stop them when their prepaid balance is exhausted.

Rationale: the page authenticates only by the customer-typed UPI VPA (`QRPayment.customer_vpa`). A VPA is **not a credential** — it appears on UPI receipts, payment confirmations, and screenshots customers freely share. Exposing any state-mutating action behind a VPA check creates a grief-stop attack surface (anyone who sees the VPA can stop the session) that rate-limiting only paper-overs.

## Considered alternatives

- **VPA-gated stop button.** `POST /api/public/qr-active-sessions/{txn_id}/stop?vpa=X` with the VPA check + an aggressive per-VPA rate limit (e.g. 3 stops per 5 min). Rejected: VPAs leak through normal use and the rate limit only moves the bar — a single mis-keyed grief attempt still costs a real customer their session. Customer support cost of "someone stopped my charge" outweighs the convenience of a remote stop button.
- **Per-payment session token (browser cookie minted via Razorpay redirect).** Rejected: UPI QR payments don't reliably redirect back to the merchant's browser — the user pays in their UPI app, not in a webview. The user typically arrives at `/my-charges` cold via the QR sticker URL or a manual visit, with no prior browser context to anchor a token to.
- **Clerk-authenticated stop button (require login).** Rejected: defeats the appless flow's entire reason for existing. QR/UPI customers are explicitly the segment that doesn't want to install an app or create an account.

## Consequences

- A future contributor will reasonably look at the card and think "this is missing the obvious primary action — let me add a stop button." This ADR explains why the omission is deliberate. If you're tempted to add it, you must first solve the authentication problem (a real per-payment browser session token), not paper over it with a VPA check.
- Customers who decide to stop mid-session must walk back to the charger and unplug. This is the same physical action they were going to take anyway to retrieve their cable, so the UX regression is small.
- The budget cap (per ADR area on QR sessions) is the system's primary "stop early" mechanism for customer-initiated termination — it auto-stops when `spent_so_far ≥ budget_limit_paise`, capping the customer's loss at what they prepaid.
- If a real per-payment session token system is later built (e.g. via a Razorpay webhook → email/SMS magic link), revisit this ADR; the no-stop-button decision was about the public-VPA threat model, not about read-only being intrinsically better.
