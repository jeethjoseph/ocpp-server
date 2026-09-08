# The QR sticker URL still embeds the OCPP UUID

Status: needs-triage

## What to build

Nothing yet — this is the residue slice 04 could not remove, filed so it is a
decision rather than an oversight.

ADR 0028 opens by observing that `charge_point_string_id` is a UUID4 that
doubles as the OCPP WSS path segment **and** the HTTP Basic Auth **username**
under [[adr-0020-charger-websocket-basic-auth]], so publishing it hands out half
a credential pair. Slice 04 removed it from everything a customer *sees*.

It did not remove it from where a customer's browser *goes*. The QR landing page
lives at `/charge/{charge_point_string_id}`, that URL is generated in the admin
charger detail page, and **it is encoded in the QR codes already printed and
stuck to the fleet**. So the field:

- is still returned by the public `/stations` payload, because the frontend needs
  it to build the link;
- is still in the address bar of every QR session;
- is still in any browser history, referrer header, or shared link.

Nothing renders it any more, which was the ticket's acceptance criterion. But
"not rendered" is a weaker property than the ADR's framing implies, and the
difference is worth being explicit about rather than letting the closed ticket
suggest the exposure is gone.

## Why it was not fixed in slice 04

The route cannot change without invalidating every physical sticker on the
fleet. Fixing it properly means introducing a **second, public-facing handle**
for the landing page — one that is not the auth username — supporting both
schemes during a transition, and re-stickering the fleet. That is a larger piece
of work than the whole of slices 01-07 combined, and it is not what ADR 0028 was
scoped to decide.

## What to decide

1. Does the residual exposure actually matter, given ADR 0020 is still PROPOSED
   and the WebSocket handshake is **not yet authenticated**? Today the username
   half is not guarding anything. It will matter the moment ADR 0020 ships — so
   the honest framing is that this is a **prerequisite of ADR 0020**, not an
   independent bug.
2. If it matters: is the public handle a new random token, or the Asset Code
   itself? The Asset Code is already public by design and already unique per
   register, so `/charge/VOW0001` is the obvious candidate and needs no new
   column. It is guessable, but so is any short code, and the landing page is a
   read-only surface that starts nothing without payment.
3. Whichever is chosen, the transition has to accept both forms until the fleet
   is re-stickered, which folds naturally into [[09-restencil-staging-labels]].

## Acceptance criteria

- [ ] A decision recorded on whether this blocks [[adr-0020-charger-websocket-basic-auth]]. If it does, ADR 0020 gains an explicit dependency on this ticket.
- [ ] If proceeding: the landing page resolves by a handle that is **not** the Basic Auth username, and `/charge/{uuid}` keeps working until the fleet is re-stickered.
- [ ] `charge_point_string_id` disappears from the public `/stations` payload only once nothing needs it for routing.

## Blocked by

None to investigate. Any implementation is blocked by the decision in point 2.
