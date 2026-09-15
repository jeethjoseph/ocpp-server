# utils.py
"""
Utility functions for OCPP server.
Add logging, ID generation, and other helpers here.
"""
import asyncio
import contextvars
import datetime
import logging
import uuid

logger = logging.getLogger("ocpp-server")

def get_utc_now():
    """Return current UTC time with timezone info."""
    return datetime.datetime.now(datetime.timezone.utc)

# India Standard Time. Fixed +5:30 offset — India observes no DST, so a fixed
# offset is correct and simpler than a zoneinfo lookup. This is the SINGLE
# conversion point for rendering/deriving Indian-local dates (GST invoice date,
# financial year, GSTR-1 period). See docs/adr/0012 and CONTEXT.md "Invoice Date".
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def to_ist(dt):
    """Convert a datetime to IST. Naive datetimes are assumed UTC (Tortoise
    runs use_tz=False, so DB timestamps come back as naive UTC). Returns a
    tz-aware IST datetime, or None if given None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(IST)

# How far ahead of our own clock a charger-reported timestamp may sit before we
# stop believing it. Small, because a charger running fast is reporting a time
# that has not happened yet — there is no legitimate reason for that beyond
# ordinary NTP drift.
OCPP_CLOCK_SKEW_SECONDS = 300


def parse_ocpp_timestamp(value, *, not_before=None, context: str = "") -> "datetime.datetime | None":
    """Parse a charger-reported OCPP timestamp into a tz-aware UTC datetime.

    Returns ``None`` when the value is missing, unparseable, or implausible —
    callers fall back to server receipt time (``created_at``), so a bad clock
    degrades to today's behaviour instead of poisoning the record.

    **Charger clocks in this fleet are not trustworthy.** ADR 0030 exists partly
    because of it: Diagnostic Bundle timestamps are reconstructed from in-band
    ``TIME_SYNC`` anchors rather than believed outright. So a reported time is
    accepted only inside a plausibility window — no further ahead than
    ``OCPP_CLOCK_SKEW_SECONDS``, and (where the caller knows one) no earlier than
    ``not_before``, which is normally the transaction's start.

    Naive inputs are assumed UTC, matching the rest of the codebase.
    """
    if not value:
        return None

    if isinstance(value, datetime.datetime):
        parsed = value
    else:
        try:
            parsed = datetime.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.warning("Unparseable OCPP timestamp %r%s", value, f" ({context})" if context else "")
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    parsed = parsed.astimezone(datetime.timezone.utc)

    skew = datetime.timedelta(seconds=OCPP_CLOCK_SKEW_SECONDS)
    if parsed > get_utc_now() + skew:
        logger.warning("Rejecting future OCPP timestamp %s%s", parsed, f" ({context})" if context else "")
        return None

    if not_before is not None:
        floor = not_before if not_before.tzinfo else not_before.replace(tzinfo=datetime.timezone.utc)
        if parsed < floor - skew:
            logger.warning(
                "Rejecting OCPP timestamp %s before floor %s%s",
                parsed, floor, f" ({context})" if context else "",
            )
            return None

    return parsed


def csv_safe_cell(value) -> str:
    """Neutralize CSV formula injection (OWASP). A spreadsheet treats a cell
    whose first character is ``= + - @`` (or a leading tab/CR) as a formula, so
    a malicious value like ``=cmd|'/c calc'!A1`` executes when the export is
    opened in Excel/Sheets. Prefix such cells with a single quote so they render
    as inert text. Apply to every user/charger-influenced TEXT cell in any CSV
    export (NOT numeric/date cells — a leading ``-`` on a number is not a
    formula and must stay numeric). Always returns a string."""
    s = "" if value is None else str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def generate_uuid():
    """Generate a new UUID4 as string."""
    return str(uuid.uuid4())


def safe_create_task(coro, *, name: str = None) -> asyncio.Task:
    """Fire-and-forget task with exception logging and a detached DB context.

    **The context is deliberately empty.** `asyncio.create_task` normally hands
    the child a copy of the caller's contextvars, and Tortoise keeps the current
    DB connection in one of those. A task spawned inside a transaction therefore
    inherits that transaction's pinned `TransactionWrapper` — and because it runs
    *later*, the parent has usually committed and returned the connection to the
    pool by then. The child then issues its query on a connection another
    coroutine already owns:

        asyncpg.InterfaceError: cannot perform operation: another operation is
        in progress

    which surfaced as ~80 silently-dropped audit rows in a single dev session.
    Silent, because the only trace is this function's own error log — the caller
    cannot await a fire-and-forget task to find out it failed.

    An empty context makes Tortoise resolve a fresh connection from the pool,
    which is the correct semantic anyway: work that cannot be awaited must not
    be enrolled in a transaction whose outcome it cannot observe. Note this also
    detaches Sentry/New Relic scope, so these tasks are reported as their own
    unit of work rather than as part of the request that spawned them. That is a
    deliberate trade — losing breadcrumb correlation is cheaper than losing the
    write. Exception reporting is unaffected: the done-callback below runs in the
    caller's context.
    """
    task = asyncio.create_task(coro, name=name, context=contextvars.Context())

    def _done_cb(t: asyncio.Task):
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error(
                "Unhandled exception in background task %s: %s",
                t.get_name(),
                exc,
                exc_info=exc,
            )

    task.add_done_callback(_done_cb)
    return task


def mask_id_tag(id_tag: str) -> str:
    """Mask an RFID tag to show only the last 4 characters."""
    if not id_tag or len(id_tag) <= 4:
        return id_tag or ""
    return "***" + id_tag[-4:]


def mask_email(email: str) -> str:
    """Mask an email to show first 2 chars + *** + @domain."""
    if not email or "@" not in email:
        return email or ""
    local, domain = email.rsplit("@", 1)
    if len(local) <= 2:
        return local + "***@" + domain
    return local[:2] + "***@" + domain


def mask_vpa(vpa: str) -> str:
    """Mask a UPI VPA to show ***<last2>@<provider>."""
    if not vpa or "@" not in vpa:
        return "***"
    local, provider = vpa.rsplit("@", 1)
    if len(local) <= 2:
        return f"***@{provider}"
    return f"***{local[-2:]}@{provider}"


def mask_phone(phone: str) -> str:
    """Mask a phone number to show only the last 4 digits."""
    if not phone or len(phone) < 4:
        return "***"
    return f"***{phone[-4:]}"


def mask_payment_id(payment_id: str) -> str:
    """Mask a Razorpay payment ID to show prefix + ***<last6>."""
    if not payment_id or len(payment_id) <= 10:
        return payment_id or ""
    return f"{payment_id[:4]}***{payment_id[-6:]}"
