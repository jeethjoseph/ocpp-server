"""Reading meter values back, with one ordering rule.

A `MeterValue` row carries two times that mean different things:

- ``created_at`` — when the SERVER received the frame.
- ``measured_at`` — when the CHARGER says it took the reading (from the OCPP
  frame's own ``timestamp``), or NULL when absent or rejected by the clock
  plausibility guard.

They are identical to within milliseconds on a healthy link, and diverge by the
length of an outage the moment a charger replays queued frames on reconnect.
OCPP 1.6 requires transaction-related messages be delivered in chronological
order, so ordering by receipt usually still lands on the right row — but
"usually" is doing real work in that sentence, and the row picked here becomes
the meter baseline for billing. Order by what was measured, fall back to what
was received.

Deliberately NOT used by the resume-staleness guard: that measures *silence* —
time since we last heard anything about the transaction — which is a receipt-time
question, and a replay legitimately resets it. See ADR 0031 decisions 3 and 8.
"""
from __future__ import annotations

from typing import Optional

from tortoise.expressions import RawSQL

from models import MeterValue

# Tortoise's own Coalesce() takes a literal as its fallback, not a column — both
# a bare "created_at" string and an F("created_at") are passed to asyncpg as a
# query parameter and rejected as a bad datetime. RawSQL is the way to express a
# two-column COALESCE here. Column names are fixed literals, not user input.
_READING_TIME = 'COALESCE("measured_at", "created_at")'


def _ordered(queryset, *, newest_first: bool):
    """Apply the canonical ordering: measured time, falling back to receipt.

    The ``id`` tiebreak matters for a replayed burst — several frames can share
    a timestamp at the source's resolution, and without it the row returned is
    whatever the planner happened to emit.
    """
    return queryset.annotate(reading_time=RawSQL(_READING_TIME)).order_by(
        f"{'-' if newest_first else ''}reading_time",
        f"{'-' if newest_first else ''}id",
    )


async def latest_meter_value(transaction_id: int) -> Optional[MeterValue]:
    """The most recent reading for a transaction, by measured time.

    Single source of truth for "what did the meter last say", shared by the
    finalizer's energy calculation, the post-boot/resume baselines and the
    live-energy read-outs, so those cannot drift apart.
    """
    return await _ordered(
        MeterValue.filter(transaction_id=transaction_id), newest_first=True
    ).first()


async def meter_series(transaction_id: int) -> list[MeterValue]:
    """All readings for a transaction, oldest first, by measured time."""
    return await _ordered(
        MeterValue.filter(transaction_id=transaction_id), newest_first=False
    )
