"""TestClient coverage for the two terminal-resolution endpoints in
``routers/admin_settlements.py`` — ``mark-below-threshold`` and
``mark-settled``.

Validates per ADR 0007:
- Happy-path transitions write an ``audit_log`` row with the right action.
- Idempotency (re-clicking the target state) is a no-op: 200, no second
  audit row, ``settled_at`` not overwritten.
- Source-status whitelist enforced (409 for already-terminal statuses).
- ``mark-below-threshold`` enforces the payout-threshold check (422).
- ``mark-settled`` enforces the note ``min_length`` (422).
- Non-admin callers are rejected.
"""
from decimal import Decimal

import pytest

from models import (
    AuditLog,
    CommissionLedgerEntry,
    SettlementStatusEnum,
)


pytestmark = pytest.mark.asyncio


async def _set_payout(entry: CommissionLedgerEntry, payout: Decimal) -> None:
    """Helper: rewrite an existing fixture row's payout without re-deriving
    the rest of the commission math. The endpoints under test only inspect
    ``franchisee_payout`` and ``settlement_status``."""
    await CommissionLedgerEntry.filter(id=entry.id).update(
        franchisee_payout=payout,
    )


# ───────────────────────── mark-below-threshold ─────────────────────────


async def test_mark_below_threshold_happy_path(
    client_admin, test_commission_ledger_entry
):
    """PENDING + sub-floor payout → BELOW_THRESHOLD, audit row written."""
    entry = test_commission_ledger_entry
    await _set_payout(entry, Decimal("0.02"))

    resp = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-below-threshold"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settlement_status"] == "BELOW_THRESHOLD"

    refreshed = await CommissionLedgerEntry.get(id=entry.id)
    assert refreshed.settlement_status == SettlementStatusEnum.BELOW_THRESHOLD

    audit = await AuditLog.filter(
        action="settlement.mark_below_threshold",
        entity_id=str(entry.id),
    ).first()
    assert audit is not None
    assert audit.changes["previous_status"] == "PENDING"
    assert audit.changes["franchisee_payout"] == "0.02"


async def test_mark_below_threshold_idempotent(
    client_admin, test_commission_ledger_entry
):
    """Calling twice → second call returns 200 but writes no second audit row."""
    entry = test_commission_ledger_entry
    await _set_payout(entry, Decimal("0.02"))

    first = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-below-threshold"
    )
    assert first.status_code == 200
    second = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-below-threshold"
    )
    assert second.status_code == 200

    audit_count = await AuditLog.filter(
        action="settlement.mark_below_threshold",
        entity_id=str(entry.id),
    ).count()
    assert audit_count == 1


async def test_mark_below_threshold_rejects_above_threshold(
    client_admin, test_commission_ledger_entry
):
    """Payout >= MIN_TRANSFER_AMOUNT → 422, no state change."""
    entry = test_commission_ledger_entry
    # Default fixture payout is 610.17, well above threshold. Don't touch it.
    resp = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-below-threshold"
    )
    assert resp.status_code == 422
    refreshed = await CommissionLedgerEntry.get(id=entry.id)
    assert refreshed.settlement_status == SettlementStatusEnum.PENDING


async def test_mark_below_threshold_rejects_terminal_source(
    client_admin, test_commission_ledger_entry
):
    """SETTLED → 409 (not in allowed source set)."""
    entry = test_commission_ledger_entry
    await _set_payout(entry, Decimal("0.02"))
    await CommissionLedgerEntry.filter(id=entry.id).update(
        settlement_status=SettlementStatusEnum.SETTLED,
    )
    resp = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-below-threshold"
    )
    assert resp.status_code == 409


async def test_mark_below_threshold_not_found(client_admin):
    resp = await client_admin.post(
        "/api/admin/settlements/9999999/mark-below-threshold"
    )
    assert resp.status_code == 404


async def test_mark_below_threshold_rejects_non_admin(
    client, test_commission_ledger_entry
):
    entry = test_commission_ledger_entry
    resp = await client.post(
        f"/api/admin/settlements/{entry.id}/mark-below-threshold"
    )
    assert resp.status_code in (401, 403)


# ───────────────────────── mark-settled ─────────────────────────


async def test_mark_settled_happy_path(
    client_admin, test_commission_ledger_entry
):
    """FAILED → SETTLED, settled_at set, audit row carries the note."""
    entry = test_commission_ledger_entry
    await CommissionLedgerEntry.filter(id=entry.id).update(
        settlement_status=SettlementStatusEnum.FAILED,
        retry_count=3,
        failure_reason="balance shortfall",
    )
    resp = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-settled",
        json={"note": "Paid via bank transfer UTR ABC123"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settlement_status"] == "SETTLED"

    refreshed = await CommissionLedgerEntry.get(id=entry.id)
    assert refreshed.settlement_status == SettlementStatusEnum.SETTLED
    assert refreshed.settled_at is not None
    # Razorpay IDs untouched — manual = no Razorpay txn.
    assert refreshed.razorpay_transfer_id is None

    audit = await AuditLog.filter(
        action="settlement.manual_settle",
        entity_id=str(entry.id),
    ).first()
    assert audit is not None
    assert audit.changes["previous_status"] == "FAILED"
    assert audit.changes["note"] == "Paid via bank transfer UTR ABC123"


async def test_mark_settled_idempotent_preserves_settled_at(
    client_admin, test_commission_ledger_entry
):
    """Second call leaves ``settled_at`` unchanged and writes no second audit row."""
    entry = test_commission_ledger_entry
    await CommissionLedgerEntry.filter(id=entry.id).update(
        settlement_status=SettlementStatusEnum.FAILED,
    )

    first = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-settled",
        json={"note": "first call"},
    )
    assert first.status_code == 200
    after_first = await CommissionLedgerEntry.get(id=entry.id)
    original_settled_at = after_first.settled_at
    assert original_settled_at is not None

    second = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-settled",
        json={"note": "second call"},
    )
    assert second.status_code == 200
    after_second = await CommissionLedgerEntry.get(id=entry.id)
    assert after_second.settled_at == original_settled_at

    audit_count = await AuditLog.filter(
        action="settlement.manual_settle",
        entity_id=str(entry.id),
    ).count()
    assert audit_count == 1


async def test_mark_settled_rejects_empty_note(
    client_admin, test_commission_ledger_entry
):
    entry = test_commission_ledger_entry
    resp = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-settled",
        json={"note": ""},
    )
    assert resp.status_code == 422


async def test_mark_settled_rejects_short_note(
    client_admin, test_commission_ledger_entry
):
    entry = test_commission_ledger_entry
    resp = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-settled",
        json={"note": "ok"},
    )
    assert resp.status_code == 422


async def test_mark_settled_rejects_below_threshold_source(
    client_admin, test_commission_ledger_entry
):
    """BELOW_THRESHOLD is terminal → 409."""
    entry = test_commission_ledger_entry
    await CommissionLedgerEntry.filter(id=entry.id).update(
        settlement_status=SettlementStatusEnum.BELOW_THRESHOLD,
    )
    resp = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-settled",
        json={"note": "should not work"},
    )
    assert resp.status_code == 409


async def test_mark_settled_rejects_reversed_source(
    client_admin, test_commission_ledger_entry
):
    entry = test_commission_ledger_entry
    await CommissionLedgerEntry.filter(id=entry.id).update(
        settlement_status=SettlementStatusEnum.REVERSED,
    )
    resp = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-settled",
        json={"note": "should not work"},
    )
    assert resp.status_code == 409


async def test_mark_settled_accepts_transfer_initiated(
    client_admin, test_commission_ledger_entry
):
    """TRANSFER_INITIATED past threshold (webhook lost) is a primary use case."""
    entry = test_commission_ledger_entry
    await CommissionLedgerEntry.filter(id=entry.id).update(
        settlement_status=SettlementStatusEnum.TRANSFER_INITIATED,
    )
    resp = await client_admin.post(
        f"/api/admin/settlements/{entry.id}/mark-settled",
        json={"note": "Verified in Razorpay dashboard"},
    )
    assert resp.status_code == 200


async def test_mark_settled_not_found(client_admin):
    resp = await client_admin.post(
        "/api/admin/settlements/9999999/mark-settled",
        json={"note": "doesn't matter"},
    )
    assert resp.status_code == 404


async def test_mark_settled_rejects_non_admin(
    client, test_commission_ledger_entry
):
    entry = test_commission_ledger_entry
    resp = await client.post(
        f"/api/admin/settlements/{entry.id}/mark-settled",
        json={"note": "should not work"},
    )
    assert resp.status_code in (401, 403)
