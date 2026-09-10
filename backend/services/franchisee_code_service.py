"""Allocation of `Franchisee.invoice_code`.

The customer-facing GST Invoice number embeds this code (`F0001/Q/26/00001`).
It replaces `Franchisee.id`, which is a per-database autoincrement and therefore
collided between the production and staging registers — both share one GSTIN and
one financial year, so a duplicate code is a duplicate invoice number and a
Rule 46(b) breach.

Each environment allocates only from its own block (see `policy`), so two
databases cannot mint the same code without coordinating. The database CHECK
constraint is the hard guard; this module is the allocator that respects it.
"""

import logging
import os
import re

from tortoise.transactions import in_transaction

from models import Franchisee
from policy import VOLTLYNC_OWNED_INVOICE_CODE, franchisee_code_block

logger = logging.getLogger(__name__)

INVOICE_CODE_PATTERN = re.compile(r"^F\d{4}$")


def format_invoice_code(number: int) -> str:
    """`1` -> `F0001`. Four digits, so the invoice serial stays inside the
    sixteen characters Rule 46(b) allows."""
    if not 0 <= number <= 9999:
        raise ValueError(f"invoice code number out of range: {number}")
    return f"F{number:04d}"


def current_block() -> tuple[int, int]:
    return franchisee_code_block(os.getenv("ENVIRONMENT", "development"))


# Advisory-lock key for invoice-code allocation. An arbitrary constant, chosen
# once and never reused for another lock: Postgres advisory locks share one
# namespace per database, so two features picking the same number would block
# each other for no reason.
_INVOICE_CODE_LOCK_KEY = 8_471_205


async def allocate_invoice_code() -> str:
    """Next free code in this environment's block.

    Scans the block rather than trusting a counter, so a code freed by a
    deleted franchisee is reusable and a manually-inserted code is respected.
    At fewer than 9,000 rows per block the scan is trivial, and it removes a
    counter row that could itself drift between registers.

    Raises RuntimeError when the block is exhausted — never silently falls back
    to another block, because that is precisely the cross-register collision
    this exists to prevent.
    """
    low, high = current_block()
    async with in_transaction() as conn:
        # Serialise allocation across concurrent creates. A plain SELECT takes
        # no lock, so under READ COMMITTED two callers read the same snapshot of
        # taken codes, pick the same gap, and one dies on the unique index —
        # surfacing to the caller as a misleading duplicate-email/PAN error.
        # Being "inside a transaction" confers nothing here; the lock does.
        # Transaction-scoped, so it releases on commit or rollback without a
        # matching unlock, and it is keyed on a constant because allocation is
        # global to the block, not per-row.
        await conn.execute_query(
            "SELECT pg_advisory_xact_lock($1)", [_INVOICE_CODE_LOCK_KEY]
        )
        taken = set(
            await Franchisee.filter(invoice_code__not_isnull=True)
            .values_list("invoice_code", flat=True)
        )
        for n in range(low, high + 1):
            code = format_invoice_code(n)
            if code not in taken:
                return code
    raise RuntimeError(
        f"franchisee invoice-code block {format_invoice_code(low)}-"
        f"{format_invoice_code(high)} is exhausted; widen the block in policy.py "
        f"rather than borrowing from another environment's range"
    )


def invoice_code_for(franchisee) -> str:
    """Code to embed in an invoice number. VoltLync-owned stations (no
    franchisee) use the reserved `F0000`."""
    if franchisee is None:
        return VOLTLYNC_OWNED_INVOICE_CODE
    code = getattr(franchisee, "invoice_code", None)
    if not code:
        raise ValueError(
            f"franchisee {getattr(franchisee, 'id', '?')} has no invoice_code; "
            f"it cannot be billed until one is allocated"
        )
    return code
