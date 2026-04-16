# utils.py
"""
Utility functions for OCPP server.
Add logging, ID generation, and other helpers here.
"""
import asyncio
import datetime
import logging
import uuid

logger = logging.getLogger("ocpp-server")

def get_utc_now():
    """Return current UTC time with timezone info."""
    return datetime.datetime.now(datetime.timezone.utc)

def generate_uuid():
    """Generate a new UUID4 as string."""
    return str(uuid.uuid4())


def safe_create_task(coro, *, name: str = None) -> asyncio.Task:
    """Wrap asyncio.create_task with exception logging for fire-and-forget tasks."""
    task = asyncio.create_task(coro, name=name)

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
