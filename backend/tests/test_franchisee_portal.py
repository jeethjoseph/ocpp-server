"""TestClient smoke + cross-tenant IDOR coverage for
``routers/franchisee_portal.py``.

The portal is the highest-risk router for IDOR because every URL path takes
an id (station_id, charger_id, transaction_id, qr_id) that maps to a resource
which MUST be franchisee-scoped. We test the happy path for each endpoint group
and — critically — that franchisee A cannot retrieve franchisee B's resources.

The cross-tenant tests use 404 (not 403) on miss to avoid leaking existence;
this matches the codebase's pattern: ``ChargingStation.filter(id=…, franchisee_id=me)
.first()`` then ``404 if None``.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from models import (
    Charger,
    ChargerStatusEnum,
    ChargingStation,
    Franchisee,
    FranchiseeStatusEnum,
    Transaction,
    TransactionStatusEnum,
    User,
    UserRoleEnum,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def franchisee_a_station(test_franchisee):
    """A station owned by the fixtured franchisee."""
    return await ChargingStation.create(
        name="Franchisee A Station",
        franchisee=test_franchisee,
        state="Karnataka", state_code="29", pincode="560001",
    )


@pytest.fixture
async def franchisee_a_charger(franchisee_a_station):
    return await Charger.create(
        charge_point_string_id="FRANCHISEE_A_CP_01",
        station=franchisee_a_station,
        latest_status=ChargerStatusEnum.AVAILABLE,
    )


@pytest.fixture
async def franchisee_b_setup():
    """Independent franchisee + user + station + charger. Used as the
    'other tenant' in cross-franchisee IDOR tests."""
    import random
    suffix = random.randint(100000000, 999999999)
    other = await Franchisee.create(
        business_name=f"Other Franchisee {suffix}",
        contact_name="Other Contact",
        contact_email=f"other_{suffix}@franchisee.test",
        contact_phone=f"9{suffix}",
        commission_percent=Decimal("20.00"),
        tds_rate_percent=Decimal("10.00"),
        status=FranchiseeStatusEnum.ACTIVE,
        razorpay_account_id=f"acc_other_{suffix}",
        transfers_enabled=True,
    )
    user = await User.create(
        email=f"other_user_{suffix}@franchisee.test",
        role=UserRoleEnum.FRANCHISEE,
    )
    other.user = user
    await other.save()
    station = await ChargingStation.create(
        name=f"Other Station {suffix}",
        franchisee=other,
        state="Karnataka", state_code="29", pincode="560002",
    )
    charger = await Charger.create(
        charge_point_string_id=f"OTHER_CP_{suffix}",
        station=station,
        latest_status=ChargerStatusEnum.AVAILABLE,
    )
    return {
        "franchisee": other,
        "user": user,
        "station": station,
        "charger": charger,
    }


# ───────────────────────── dashboard ─────────────────────────


async def test_dashboard_returns_franchisee_scoped_counts(
    client_franchisee, test_franchisee, franchisee_a_station, franchisee_a_charger
):
    resp = await client_franchisee.get("/api/franchisee/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["station_count"] == 1
    assert body["charger_count"] == 1


async def test_dashboard_rejects_non_franchisee(client):
    resp = await client.get("/api/franchisee/dashboard")
    assert resp.status_code in (401, 403)


async def test_dashboard_rejects_admin(client_admin):
    """Admin has no Franchisee profile — portal must reject."""
    resp = await client_admin.get("/api/franchisee/dashboard")
    assert resp.status_code in (403, 404)


# ───────────────────────── stations ─────────────────────────


async def test_list_stations_returns_only_own(
    client_franchisee,
    franchisee_a_station,
    franchisee_b_setup,
):
    resp = await client_franchisee.get("/api/franchisee/stations")
    assert resp.status_code == 200
    rows = resp.json()
    ids = [s["id"] for s in rows]
    assert franchisee_a_station.id in ids
    assert franchisee_b_setup["station"].id not in ids


async def test_get_own_station_returns_200(
    client_franchisee, franchisee_a_station
):
    resp = await client_franchisee.get(
        f"/api/franchisee/stations/{franchisee_a_station.id}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["station"]["id"] == franchisee_a_station.id


async def test_get_other_franchisees_station_returns_404(
    client_franchisee, franchisee_b_setup
):
    """Critical IDOR guard: passing a station id owned by another franchisee
    must return 404 (not the row, not 403 — 404 keeps existence private)."""
    resp = await client_franchisee.get(
        f"/api/franchisee/stations/{franchisee_b_setup['station'].id}"
    )
    assert resp.status_code == 404


# ───────────────────────── chargers ─────────────────────────


async def test_get_own_charger_returns_200(
    client_franchisee, franchisee_a_charger
):
    resp = await client_franchisee.get(
        f"/api/franchisee/chargers/{franchisee_a_charger.id}"
    )
    assert resp.status_code == 200


async def test_get_other_franchisees_charger_blocked(
    client_franchisee, franchisee_b_setup
):
    """Cross-tenant charger fetch must not succeed. Helper
    ``_verify_charger_ownership`` returns 403 on franchisee mismatch and 404
    on missing — accept either as long as access is denied."""
    resp = await client_franchisee.get(
        f"/api/franchisee/chargers/{franchisee_b_setup['charger'].id}"
    )
    assert resp.status_code in (403, 404)


# ───────────────────────── settlements ─────────────────────────


async def test_list_settlements_scoped(
    client_franchisee, test_franchisee, test_commission_ledger_entry,
    franchisee_b_setup,
):
    """Franchisee only sees their own ledger entries (the fixture entry is
    tied to test_franchisee)."""
    resp = await client_franchisee.get("/api/franchisee/settlements")
    assert resp.status_code == 200
    body = resp.json()
    rows = body.get("data") if isinstance(body, dict) else body
    ids = [r["id"] for r in rows]
    assert test_commission_ledger_entry.id in ids
    # The other franchisee has none, but if anything leaks it'd show here.
    # Sanity: no row's franchisee_id matches the other franchisee.
    for r in rows:
        if "franchisee_id" in r:
            assert r["franchisee_id"] != franchisee_b_setup["franchisee"].id


async def _make_settlement(franchisee, charger, user, *, status, payout,
                            gross="100.00", tds="10.00", created_at=None):
    """Create a Settlement Entry with a given status/amounts, optionally
    backdating created_at (the earnings date the filter keys on)."""
    from models import CommissionLedgerEntry, SettlementStatusEnum
    txn = await Transaction.create(
        charger=charger, user=user,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    entry = await CommissionLedgerEntry.create(
        transaction=txn, franchisee=franchisee,
        gross_amount=Decimal(gross), payment_method="QR_UPI",
        razorpay_payment_id=f"pay_{txn.id}", refund_amount=Decimal("0.00"),
        pg_fee_amount=Decimal("0.00"), net_amount=Decimal(gross),
        gst_collected=Decimal("0.00"), net_excl_gst=Decimal(gross),
        commission_percent=Decimal("20.00"), platform_commission=Decimal("0.00"),
        tds_rate_percent=Decimal("10.00"), tds_amount=Decimal(tds),
        transfer_fee=Decimal("0.00"), franchisee_payout=Decimal(payout),
        energy_consumed_kwh=1.0, tariff_rate_per_kwh=Decimal("15.00"),
        settlement_status=getattr(SettlementStatusEnum, status),
        idempotency_key=f"txn_{txn.id}",
    )
    if created_at is not None:
        await CommissionLedgerEntry.filter(id=entry.id).update(created_at=created_at)
    return entry


async def test_settlements_summary_buckets(
    client_franchisee, test_franchisee, test_charger, test_user,
):
    """Payout splits settled vs pending; FAILED counts as pending (+ surfaced
    via failed_count); REVERSED is excluded from every money total."""
    await _make_settlement(test_franchisee, test_charger, test_user, status="SETTLED", payout="100.00", gross="200.00", tds="5.00")
    await _make_settlement(test_franchisee, test_charger, test_user, status="TRANSFER_PROCESSED", payout="50.00", gross="100.00", tds="5.00")
    await _make_settlement(test_franchisee, test_charger, test_user, status="PENDING", payout="30.00", gross="60.00", tds="3.00")
    await _make_settlement(test_franchisee, test_charger, test_user, status="FAILED", payout="20.00", gross="40.00", tds="2.00")
    await _make_settlement(test_franchisee, test_charger, test_user, status="REVERSED", payout="999.00", gross="999.00", tds="99.00")

    resp = await client_franchisee.get("/api/franchisee/settlements")
    assert resp.status_code == 200
    s = resp.json()["summary"]

    assert s["payout_settled"] == "150.00"          # 100 + 50
    assert s["payout_pending"] == "50.00"           # 30 + 20 (FAILED)
    assert s["total_payout"] == "200.00"            # REVERSED's 999 excluded
    assert s["failed_count"] == 1
    assert s["total_gross"] == "400.00"             # 200+100+60+40, REVERSED's 999 excluded
    assert s["total_tds"] == "15.00"                # 5+5+3+2, REVERSED's 99 excluded


async def test_settlements_date_filter_is_ist_on_created_at(
    client_franchisee, test_franchisee, test_charger, test_user,
):
    """from/to are inclusive IST dates on created_at. An entry at
    2026-06-30 20:30 UTC == 2026-07-01 02:00 IST belongs to July, not June."""
    boundary = datetime(2026, 6, 30, 20, 30, tzinfo=timezone.utc)  # 2026-07-01 02:00 IST
    entry = await _make_settlement(
        test_franchisee, test_charger, test_user,
        status="SETTLED", payout="77.00", created_at=boundary,
    )

    june = await client_franchisee.get(
        "/api/franchisee/settlements?from_date=2026-06-01&to_date=2026-06-30"
    )
    july = await client_franchisee.get(
        "/api/franchisee/settlements?from_date=2026-07-01&to_date=2026-07-31"
    )
    june_ids = [r["id"] for r in june.json()["data"]]
    july_ids = [r["id"] for r in july.json()["data"]]

    assert entry.id not in june_ids
    assert june.json()["summary"]["total_payout"] == "0.00"
    assert entry.id in july_ids
    assert july.json()["summary"]["payout_settled"] == "77.00"


async def test_settlements_rejects_bad_date(client_franchisee, test_franchisee):
    resp = await client_franchisee.get("/api/franchisee/settlements?from_date=06-2026")
    assert resp.status_code == 400


# ───────────────────────── profile ─────────────────────────


async def test_get_profile_returns_own(
    client_franchisee, test_franchisee
):
    resp = await client_franchisee.get("/api/franchisee/profile")
    assert resp.status_code == 200
    assert resp.json()["id"] == test_franchisee.id


# ───────────────────────── soft-delete gate ─────────────────────────


async def test_suspended_franchisee_blocked_from_portal(
    client_franchisee, test_franchisee
):
    """The auth_middleware soft-delete fix must reject a SUSPENDED franchisee
    even with a valid JWT/session override."""
    test_franchisee.status = FranchiseeStatusEnum.SUSPENDED
    await test_franchisee.save()
    resp = await client_franchisee.get("/api/franchisee/dashboard")
    assert resp.status_code == 403


async def test_deactivated_franchisee_blocked_from_portal(
    client_franchisee, test_franchisee
):
    test_franchisee.status = FranchiseeStatusEnum.DEACTIVATED
    await test_franchisee.save()
    resp = await client_franchisee.get("/api/franchisee/dashboard")
    assert resp.status_code == 403


async def test_active_franchisee_allowed(
    client_franchisee, test_franchisee
):
    """Sanity: default ACTIVE fixture must pass the gate. Belt-and-suspenders
    so a future bug that returns 403 for all statuses doesn't go undetected."""
    test_franchisee.status = FranchiseeStatusEnum.ACTIVE
    await test_franchisee.save()
    resp = await client_franchisee.get("/api/franchisee/dashboard")
    assert resp.status_code == 200
