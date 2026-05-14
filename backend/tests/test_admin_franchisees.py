"""TestClient smoke for ``routers/franchisees.py`` and
``routers/admin_settlements.py``.

Goal is not exhaustive contract testing — that's the service-level test files.
This file proves the HTTP layer: routes registered, auth dependencies wired,
serialization works, role checks fire. One happy-path + one role-rejection per
endpoint group, plus the new audit-log side-effects on the commission edit.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from models import (
    CommissionAuditLog,
    CommissionLedgerEntry,
    Franchisee,
    SettlementStatusEnum,
    User,
    UserRoleEnum,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _mock_clerk_invitation():
    """Every franchisee-create path fires a Clerk invitation. The service
    method is wrapped in try/except in the router (non-fatal), but mocking
    it here keeps the tests offline + deterministic."""
    with patch(
        "services.clerk_invitation_service.send_invitation",
        new=AsyncMock(return_value={"id": "inv_test", "status": "pending"}),
    ):
        yield


# ───────────────────────── create ─────────────────────────


async def test_create_franchisee_happy_path(client_admin):
    """Admin can create a franchisee; response includes the new id and the
    franchisee row is persisted with a paired FRANCHISEE User row."""
    payload = {
        "business_name": "Test Owner Pvt Ltd",
        "contact_name": "Owner One",
        "contact_email": "owner1@franchisee.test",
        "contact_phone": "+919999000001",
        "commission_percent": "20.00",
        "tds_rate_percent": "10.00",
    }
    resp = await client_admin.post("/api/admin/franchisees", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["business_name"] == payload["business_name"]
    assert body["status"] == "DRAFT"

    franchisee = await Franchisee.filter(contact_email=payload["contact_email"]).first()
    assert franchisee is not None
    user = await User.filter(email=payload["contact_email"]).first()
    assert user is not None
    assert user.role == UserRoleEnum.FRANCHISEE


async def test_create_franchisee_writes_initial_commission_audit(client_admin):
    """Initial commission % must be captured in CommissionAuditLog."""
    payload = {
        "business_name": "Audit Trail Pvt Ltd",
        "contact_name": "Auditor",
        "contact_email": "audit@franchisee.test",
        "contact_phone": "+919999000002",
    }
    resp = await client_admin.post("/api/admin/franchisees", json=payload)
    assert resp.status_code == 200

    franchisee = await Franchisee.filter(contact_email=payload["contact_email"]).first()
    audit = await CommissionAuditLog.filter(franchisee=franchisee).first()
    assert audit is not None
    assert audit.new_percent == Decimal("20.00")
    assert audit.previous_percent is None


async def test_create_franchisee_rejects_duplicate_email(client_admin, test_franchisee):
    """Reusing an existing contact_email returns 409, not 500."""
    payload = {
        "business_name": "Duplicate",
        "contact_name": "Dup",
        "contact_email": test_franchisee.contact_email,
        "contact_phone": "+919999000099",
    }
    resp = await client_admin.post("/api/admin/franchisees", json=payload)
    assert resp.status_code == 409


async def test_create_franchisee_rejects_non_admin(client):
    """A request with no admin override should 401/403 the create."""
    payload = {
        "business_name": "Should Fail",
        "contact_name": "X",
        "contact_email": "should_fail@franchisee.test",
        "contact_phone": "+919999000003",
    }
    resp = await client.post("/api/admin/franchisees", json=payload)
    assert resp.status_code in (401, 403)


# ───────────────────────── list / get ─────────────────────────


async def test_list_franchisees_returns_existing(client_admin, test_franchisee):
    resp = await client_admin.get("/api/admin/franchisees")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body and isinstance(body["data"], list)
    ids = [row["id"] for row in body["data"]]
    assert test_franchisee.id in ids


async def test_list_franchisees_includes_zero_totals(client_admin, test_franchisee):
    """A franchisee with no invoices and no ledger entries reports both totals
    as zero rather than null — the UI relies on a numeric string."""
    resp = await client_admin.get("/api/admin/franchisees")
    assert resp.status_code == 200
    row = next(
        r for r in resp.json()["data"] if r["id"] == test_franchisee.id
    )
    assert Decimal(row["total_invoiced"]) == Decimal("0")
    assert Decimal(row["total_transferred"]) == Decimal("0")


async def test_get_franchisee_totals_filter_by_status(
    client_admin, test_commission_ledger_entry, test_franchisee
):
    """`total_transferred` must include only TRANSFER_PROCESSED + SETTLED
    rows. The PENDING fixture entry contributes zero."""
    from datetime import datetime, timezone
    from models import (
        CommissionLedgerEntry, SettlementStatusEnum, Transaction,
        TransactionStatusEnum,
    )
    # Add one SETTLED entry that SHOULD count.
    settled_txn = await Transaction.create(
        charger=test_commission_ledger_entry.transaction.charger,
        user=test_commission_ledger_entry.transaction.user,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    await CommissionLedgerEntry.create(
        transaction=settled_txn,
        franchisee=test_franchisee,
        gross_amount=Decimal("500.00"),
        payment_method="QR_UPI",
        razorpay_payment_id=f"pay_settled_{settled_txn.id}",
        refund_amount=Decimal("0.00"),
        pg_fee_amount=Decimal("0.00"),
        net_amount=Decimal("500.00"),
        gst_collected=Decimal("76.27"),
        net_excl_gst=Decimal("423.73"),
        commission_percent=Decimal("20.00"),
        platform_commission=Decimal("84.75"),
        tds_rate_percent=Decimal("10.00"),
        tds_amount=Decimal("33.90"),
        transfer_fee=Decimal("0.00"),
        franchisee_payout=Decimal("305.08"),
        energy_consumed_kwh=5.0,
        tariff_rate_per_kwh=Decimal("15.00"),
        settlement_status=SettlementStatusEnum.SETTLED,
        idempotency_key=f"txn_settled_{settled_txn.id}",
        transfer_processed_at=datetime.now(timezone.utc),
    )

    resp = await client_admin.get(f"/api/admin/franchisees/{test_franchisee.id}")
    assert resp.status_code == 200
    body = resp.json()
    # PENDING ledger (610.17) excluded; SETTLED (305.08) counted.
    assert Decimal(body["total_transferred"]) == Decimal("305.08")


async def test_get_franchisee_by_id(client_admin, test_franchisee):
    resp = await client_admin.get(f"/api/admin/franchisees/{test_franchisee.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == test_franchisee.id


async def test_get_franchisee_missing_returns_404(client_admin):
    resp = await client_admin.get("/api/admin/franchisees/9999999")
    assert resp.status_code == 404


# ───────────────────────── update ─────────────────────────


async def test_update_franchisee_basic_fields(client_admin, test_franchisee):
    resp = await client_admin.put(
        f"/api/admin/franchisees/{test_franchisee.id}",
        json={"contact_name": "Updated Name", "address": "12 New Address Rd"},
    )
    assert resp.status_code == 200, resp.text
    refreshed = await Franchisee.get(id=test_franchisee.id)
    assert refreshed.contact_name == "Updated Name"
    assert refreshed.address == "12 New Address Rd"


async def test_update_commission_writes_audit(client_admin, test_franchisee):
    """PUT /commission must persist the change AND a CommissionAuditLog row
    capturing previous & new percent + reason."""
    from datetime import date
    payload = {
        "new_percent": "25.00",
        "reason": "CONTRACT_RENEWAL",
        "effective_from": date.today().isoformat(),
        "notes": "test renewal",
    }
    resp = await client_admin.put(
        f"/api/admin/franchisees/{test_franchisee.id}/commission",
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    refreshed = await Franchisee.get(id=test_franchisee.id)
    assert refreshed.commission_percent == Decimal("25.00")

    audit = await CommissionAuditLog.filter(
        franchisee=test_franchisee, new_percent=Decimal("25.00")
    ).first()
    assert audit is not None
    assert audit.previous_percent == Decimal("20.00")


# ───────────────────────── settlements (admin views) ─────────────────────────


async def test_list_franchisee_settlements(
    client_admin, test_commission_ledger_entry, test_franchisee
):
    resp = await client_admin.get(
        f"/api/admin/franchisees/{test_franchisee.id}/settlements"
    )
    assert resp.status_code == 200
    body = resp.json()
    ids = [row["id"] for row in body["data"]]
    assert test_commission_ledger_entry.id in ids


async def test_hold_and_release_settlement(
    client_admin, test_commission_ledger_entry, test_franchisee
):
    """Admin manual hold flips PENDING → ON_HOLD; release flips back."""
    eid = test_commission_ledger_entry.id
    hold = await client_admin.post(
        f"/api/admin/franchisees/{test_franchisee.id}/settlements/{eid}/hold",
        json={"reason": "manual_review"},
    )
    assert hold.status_code == 200, hold.text
    refreshed = await CommissionLedgerEntry.get(id=eid)
    assert refreshed.settlement_status == SettlementStatusEnum.ON_HOLD

    release = await client_admin.post(
        f"/api/admin/franchisees/{test_franchisee.id}/settlements/{eid}/release"
    )
    assert release.status_code == 200, release.text
    refreshed = await CommissionLedgerEntry.get(id=eid)
    # Release transitions back to PENDING (or similar transferable state).
    assert refreshed.settlement_status != SettlementStatusEnum.ON_HOLD


# ───────────────────────── stations assign / unassign ─────────────────────────


async def test_assign_and_unassign_station(
    client_admin, test_franchisee, test_station
):
    """Admin can link a station to a franchisee then unlink it."""
    assign = await client_admin.post(
        f"/api/admin/franchisees/{test_franchisee.id}/stations",
        json={"station_ids": [test_station.id]},
    )
    assert assign.status_code in (200, 201), assign.text
    from models import ChargingStation
    refreshed = await ChargingStation.get(id=test_station.id)
    assert refreshed.franchisee_id == test_franchisee.id

    unassign = await client_admin.delete(
        f"/api/admin/franchisees/{test_franchisee.id}/stations/{test_station.id}"
    )
    assert unassign.status_code == 200, unassign.text
    refreshed = await ChargingStation.get(id=test_station.id)
    assert refreshed.franchisee_id is None


# ───────────────────────── admin_settlements router ─────────────────────────


async def test_list_stuck_settlements_empty(client_admin):
    """No stuck entries → 200 with empty data array."""
    resp = await client_admin.get("/api/admin/settlements/stuck")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert isinstance(body["data"], list)


async def test_list_stuck_settlements_rejects_non_admin(client):
    resp = await client.get("/api/admin/settlements/stuck")
    assert resp.status_code in (401, 403)
