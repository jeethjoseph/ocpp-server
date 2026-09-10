"""Guards on the two ways an invoice number could be minted wrongly.

Both protect the same thing: an issued **GST Invoice** number is permanent, and
there is no credit-note mechanism to correct one. A failed invoice is
recoverable; a duplicated number under a shared GSTIN is not.
"""
import pytest
from tortoise import Tortoise

from models import Connector, Franchisee
from policy import VOLTLYNC_OWNED_INVOICE_CODE
from services.franchisee_code_service import (
    allocate_invoice_code,
    invoice_code_for,
)


# ---------------------------------------------------------------------------
# A missing franchisee must not be numbered as VoltLync-owned
# ---------------------------------------------------------------------------

def test_invoice_code_for_none_still_means_voltlync_owned():
    """Unchanged, and the reason the caller cannot rely on it: this helper reads
    None as 'this invoice has no franchisee', which is not the same fact as
    'the franchisee could not be loaded'."""
    assert invoice_code_for(None) == VOLTLYNC_OWNED_INVOICE_CODE


@pytest.mark.asyncio
async def test_a_missing_franchisee_never_mints_a_voltlync_number(client):
    """With a franchisee_id set but no row, the numbering path used to fall
    through to invoice_code_for(None) -> F0000 while still drawing the sequence
    from that franchisee's own counter -- able to duplicate a genuine
    VoltLync-owned number under the same GSTIN.

    TWO guards now stand in the way, and this asserts the outcome rather than
    which one fires: the FK on gst_invoice_counter.franchisee_id rejects the
    counter row first, and the explicit not-found check in the numbering path
    catches the case where that FK is ever relaxed. Either way the call raises
    instead of returning a number.
    """
    from tortoise.exceptions import IntegrityError
    from services.invoice_service import InvoiceService

    with pytest.raises((ValueError, IntegrityError)):
        await InvoiceService.get_next_invoice_number(
            franchisee_id=987_654_321, series="QR", financial_year="2026-27"
        )


@pytest.mark.asyncio
async def test_numbering_still_works_for_a_real_franchisee(client, test_franchisee):
    from services.invoice_service import InvoiceService

    number = await InvoiceService.get_next_invoice_number(
        franchisee_id=test_franchisee.id, series="QR", financial_year="2026-27"
    )
    assert test_franchisee.invoice_code in number
    assert VOLTLYNC_OWNED_INVOICE_CODE not in number


# ---------------------------------------------------------------------------
# Code allocation is serialised
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_allocation_takes_the_advisory_lock(client):
    """A plain SELECT takes no lock, so under READ COMMITTED two concurrent
    creates read the same snapshot, pick the same gap, and one dies on the
    unique index -- surfacing to the caller as a misleading duplicate-email
    error. Being inside a transaction confers nothing; the advisory lock does.

    Asserted by spying on the transaction's own connection rather than by racing
    two callers: Postgres advisory locks are per-SESSION and re-entrant, and the
    test harness runs everything on one connection, so a second acquisition here
    would never block no matter how the code behaved.
    """
    from contextlib import asynccontextmanager
    from services import franchisee_code_service as svc

    executed: list[str] = []
    real_in_transaction = svc.in_transaction

    @asynccontextmanager
    async def spying_in_transaction(*a, **kw):
        async with real_in_transaction(*a, **kw) as conn:
            original = conn.execute_query

            async def spy(query, values=None):
                executed.append(query)
                return await original(query, values)

            conn.execute_query = spy
            try:
                yield conn
            finally:
                conn.execute_query = original

    svc.in_transaction = spying_in_transaction
    try:
        code = await svc.allocate_invoice_code()
    finally:
        svc.in_transaction = real_in_transaction

    assert code.startswith("F")
    assert any("pg_advisory_xact_lock" in q for q in executed), (
        f"allocation did not take the advisory lock; queries were {executed}"
    )


@pytest.mark.asyncio
async def test_allocation_skips_a_code_already_held(client, test_franchisee):
    """The fixture's franchisee already holds a code; the next allocation must
    not hand out the same one."""
    assert test_franchisee.invoice_code
    assert await allocate_invoice_code() != test_franchisee.invoice_code


# ---------------------------------------------------------------------------
# connector_type is constrained in the database, not only in Python
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_database_rejects_a_non_canonical_connector_type(client, test_charger):
    """Migration 49 retyped the column to an enum field but added no constraint,
    and Tortoise raises ValueError on any value that is not byte-exactly a
    member -- which would fire on every path that loads a Connector: suspend
    windows, remote start, QR start, the admin list, the public stations feed.
    The data is clean today by audit; this makes it clean by construction."""
    from tortoise.exceptions import IntegrityError, OperationalError

    conn = Tortoise.get_connection("default")
    with pytest.raises((IntegrityError, OperationalError)):
        await conn.execute_query(
            'INSERT INTO connector (charger_id, connector_id, connector_type, max_power_kw) '
            'VALUES ($1, 99, $2, 7.4)',
            [test_charger.id, "TYPE2"],   # right type, wrong casing
        )


@pytest.mark.asyncio
async def test_database_accepts_every_canonical_connector_type(client, test_charger):
    """The constraint is built from the enum, so the two cannot drift. If a
    member is added without widening the CHECK, this fails."""
    from models import ConnectorTypeEnum

    for i, member in enumerate(ConnectorTypeEnum, start=50):
        row = await Connector.create(
            charger=test_charger, connector_id=i,
            connector_type=member.value, max_power_kw=7.4,
        )
        assert row.id is not None
