"""Reading meter values back, with one ordering rule per question.

A `MeterValue` row carries two times that mean different things:

- ``created_at`` — when the SERVER received the frame.
- ``measured_at`` — when the CHARGER says it took the reading (from the OCPP
  frame's own ``timestamp``), or NULL when absent or rejected by the clock
  plausibility guard.

They are identical to within milliseconds on a healthy link, and diverge by the
length of an outage the moment a charger replays queued frames on reconnect.

**The billing baseline orders by RECEIPT, not by measured time.** A first cut
ordered by ``COALESCE(measured_at, created_at)`` and it regressed: the clock
guard deliberately admits a charger running up to 300 s fast, so a frame stamped
+4 min followed — after an NTP correction — by a later frame stamped +1 min put
the earlier, LOWER reading on top. Reproduced on the dev DB (A id=321 1.0 kWh
measured +4m; B id=322 9.0 kWh measured +1m; latest returned A). Receipt order is
monotonic by construction, which is the property a billing baseline needs; and
OCPP 1.6 requires transaction-related messages be delivered chronologically, so
whenever the charger behaves the two orderings agree anyway. Where they differ,
receipt order is the one that cannot go backwards.

``measured_at`` keeps the job it was actually retained for — the delivery curve,
audit, forensics — via ``meter_series``. A backwards *reading* (as opposed to a
backwards clock) is the monotonicity observation's concern, not this module's.

Deliberately NOT used by the resume-staleness guard: that measures *silence* —
time since we last heard anything about the transaction — which is a receipt-time
question, and a replay legitimately resets it. See ADR 0031 decisions 3 and 8.
"""
from __future__ import annotations

from typing import Optional

from tortoise.expressions import RawSQL

from models import MeterValue

# Tortoise's own Coalesce() takes a literal as its fallback, not a column — both
# a bare "measured_at" string and an F("created_at") are passed to asyncpg as a
# query parameter and rejected as a bad datetime. RawSQL is the way to express a
# two-column COALESCE here. Column names are fixed literals, not user input.
_MEASURED_TIME = 'COALESCE("measured_at", "created_at")'


async def latest_meter_value(transaction_id: int) -> Optional[MeterValue]:
    """The most recent reading for a transaction, by RECEIPT order.

    Single source of truth for "what did the meter last say", shared by the
    finalizer's energy calculation, the post-boot/resume baselines and the
    live-energy read-outs, so those cannot drift apart.

    Receipt order (``created_at``, then ``id``) is monotonic: a later frame can
    never sort below an earlier one. Measured order cannot promise that — see
    the module docstring for the clock-step regression that proved it. The
    ``id`` tiebreak covers a replayed burst whose rows share a ``created_at``
    at the clock's resolution.
    """
    return await (
        MeterValue.filter(transaction_id=transaction_id)
        .order_by("-created_at", "-id")
        .first()
    )


async def meter_series(transaction_id: int) -> list[MeterValue]:
    """All readings for a transaction, oldest first, by MEASURED time.

    This is the delivery curve — what the retained timestamp is for. Ordering
    by when the charger says each reading was taken is what makes a replayed
    outage render as hours of charging rather than a burst at one instant.
    Falls back to receipt time for rows with no usable ``measured_at``.
    """
    return await (
        MeterValue.filter(transaction_id=transaction_id)
        .annotate(measured_time=RawSQL(_MEASURED_TIME))
        .order_by("measured_time", "id")
    )
