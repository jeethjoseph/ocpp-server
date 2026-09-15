"""`safe_create_task` must not inherit the caller's database context.

A fire-and-forget task spawned inside a transaction used to inherit that
transaction's pinned Tortoise connection. Because it runs *later*, the parent
had normally committed and handed the connection back to the pool, so the child
issued its query against a connection another coroutine already owned:

    asyncpg.InterfaceError: cannot perform operation: another operation is in
    progress

The task simply died. Nothing awaited it, so the only trace was an error log —
which is how ~80 audit rows vanished in one dev session while every request
returned 200. Audit rows going missing silently is the failure this repo can
least afford: the Reset guard exists precisely because a *false* audit record is
worse than a misleading message, and an absent one is the same problem inverted.
"""
from __future__ import annotations

import asyncio

import pytest
from tortoise import connections
from tortoise.transactions import in_transaction

from models import AuditLog
from utils import safe_create_task

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# `client` is requested purely to initialise the test DB — these tests never
# make an HTTP call. It is the conftest fixture that calls Tortoise.init.


async def _write_audit(entity_id: str) -> None:
    await AuditLog.create(
        actor_type="system",
        action="charger.auth_provisioned",
        entity_type="charger",
        entity_id=entity_id,
    )


async def _churn() -> None:
    """Keep the pool busy so a stale connection handle actually collides."""
    for _ in range(6):
        await connections.get("default").execute_query("SELECT 1")


async def test_task_spawned_inside_a_transaction_survives_the_commit(client):
    """The regression. The task is created while a transaction holds a pinned
    connection, and only runs after that transaction has committed and released
    it — the exact ordering that used to lose the write."""
    entity = "bg-ctx-committed"

    async with in_transaction():
        task = safe_create_task(_write_audit(entity))
        # Touch the DB so the transaction genuinely owns its connection.
        await AuditLog.filter(entity_id="does-not-exist").count()

    await asyncio.gather(task, _churn())

    assert await AuditLog.filter(entity_id=entity).count() == 1, (
        "the audit row was lost — safe_create_task is inheriting the caller's "
        "DB context again"
    )
    await AuditLog.filter(entity_id=entity).delete()


async def test_the_task_does_not_join_the_callers_transaction(client):
    """A rolled-back caller must not take the fire-and-forget write with it.

    This is the semantic that makes the fix correct rather than merely working:
    work nobody can await must not be enrolled in a transaction whose outcome it
    cannot observe.
    """
    entity = "bg-ctx-rollback"

    class Rollback(Exception):
        pass

    with pytest.raises(Rollback):
        async with in_transaction():
            task = safe_create_task(_write_audit(entity))
            await AuditLog.filter(entity_id="does-not-exist").count()
            raise Rollback

    await task

    assert await AuditLog.filter(entity_id=entity).count() == 1, (
        "the audit row was rolled back with the caller's transaction"
    )
    await AuditLog.filter(entity_id=entity).delete()
