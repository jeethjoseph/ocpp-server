"""HTTP-layer tests for the ``GET /api/admin/transactions/{id}`` response
augmentations:

* ``live_energy_kwh`` — derived per-request from the latest ``MeterValue``,
  decoupled from the stored ``Transaction.energy_consumed_kwh`` column which
  is only populated at StopTransaction (and would otherwise read as 0 during
  an active session).
* ``funding_source`` — ``"WALLET"`` | ``"QR"`` | ``"NONE"`` discriminator
  driven by the presence of a ``QRPayment`` row and the user's role
  (per ``core.roles.INTERNAL_ROLES`` / ADR 0004).
* ``qr_session`` — live ``{budget_limit, cost_so_far, remaining}`` snapshot
  populated when ``funding_source == "QR"``, sourced via the pure
  ``QRPaymentService.compute_budget_snapshot`` helper.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from models import (
    ChargerQRCode,
    MeterValue,
    QRPayment,
    QRPaymentStatusEnum,
    Transaction,
    UserRoleEnum,
)
from services.qr_payment_service import BudgetSnapshot, QRPaymentService


pytestmark = pytest.mark.asyncio


async def _make_transaction(test_charger, test_user, start_meter_kwh):
    return await Transaction.create(
        user=test_user,
        charger=test_charger,
        start_meter_kwh=start_meter_kwh,
        transaction_status="RUNNING",
    )


async def _make_qr_payment(test_charger, test_user, transaction):
    import uuid
    qr_code = await ChargerQRCode.create(
        charger=test_charger,
        razorpay_qr_code_id=f"qr_{uuid.uuid4().hex[:10]}",
        image_url="https://razorpay.example/qr.png",
        is_active=True,
    )
    return await QRPayment.create(
        charger=test_charger,
        charger_qr_code=qr_code,
        user=test_user,
        transaction=transaction,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
        amount_paid=Decimal("500.00"),
        status=QRPaymentStatusEnum.CHARGING,
    )


async def test_live_energy_kwh_null_when_start_meter_missing(
    client_admin, test_charger, test_user
):
    """Legacy rows where StartTransaction never wrote start_meter_kwh must
    not crash the endpoint — the field is reported as null."""
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=None)
    await MeterValue.create(transaction=txn, reading_kwh=Decimal("10.500"))

    resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["live_energy_kwh"] is None


async def test_live_energy_kwh_null_when_no_meter_values(
    client_admin, test_charger, test_user
):
    """A transaction that has started but not yet emitted MeterValues
    reports live_energy_kwh=null rather than 0 (avoids confusion with a
    real 0 kWh reading)."""
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("100.000"))

    resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["live_energy_kwh"] is None


async def test_live_energy_kwh_derives_from_latest_meter_value(
    client_admin, test_charger, test_user
):
    """During an active session, live_energy_kwh = latest_reading - start."""
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("100.000"))
    await MeterValue.create(transaction=txn, reading_kwh=Decimal("100.500"))
    await MeterValue.create(transaction=txn, reading_kwh=Decimal("101.250"))

    resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["live_energy_kwh"] == pytest.approx(1.250)


async def test_live_energy_kwh_uses_meter_values_for_finalised_transaction(
    client_admin, test_charger, test_user
):
    """Even after StopTransaction has populated energy_consumed_kwh on the
    row, the derived live_energy_kwh still computes from the last MeterValue.
    This keeps the field's contract uniform across session lifecycle states
    (the column and the derived figure may differ slightly when the cap
    truncates billable energy)."""
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("100.000"))
    await MeterValue.create(transaction=txn, reading_kwh=Decimal("102.000"))
    txn.transaction_status = "COMPLETED"
    txn.energy_consumed_kwh = Decimal("1.500")  # capped billable, not raw meter delta
    await txn.save()

    resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["live_energy_kwh"] == pytest.approx(2.000)


async def test_live_energy_kwh_does_not_write_energy_consumed_kwh(
    client_admin, test_charger, test_user
):
    """The derived field is read-only: hitting the endpoint must never
    mutate Transaction.energy_consumed_kwh. Guards against an accidental
    refactor that persists the live figure and races with StopTransaction."""
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("50.000"))
    await MeterValue.create(transaction=txn, reading_kwh=Decimal("52.000"))

    resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")
    assert resp.status_code == 200, resp.text

    reloaded = await Transaction.get(id=txn.id)
    assert reloaded.energy_consumed_kwh is None


# ---------------------------------------------------------------------------
# funding_source classification
# ---------------------------------------------------------------------------


async def test_funding_source_wallet_for_regular_user_without_qr_payment(
    client_admin, test_charger, test_user
):
    """A regular USER role with no QRPayment row defaults to WALLET. The
    qr_session block is omitted (rendered as null over the wire)."""
    test_user.role = UserRoleEnum.USER
    await test_user.save()
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0.000"))

    resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["funding_source"] == "WALLET"
    assert body["qr_session"] is None


async def test_funding_source_none_for_internal_role_user(
    client_admin, test_charger, test_user
):
    """ADMIN/FRANCHISEE-initiated sessions are Internal-role Sessions per
    ADR 0004 — no funding pool. The response uses the NONE sentinel and
    omits the qr_session block."""
    test_user.role = UserRoleEnum.ADMIN
    await test_user.save()
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0.000"))

    resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["funding_source"] == "NONE"
    assert body["qr_session"] is None


async def test_funding_source_qr_carries_live_budget_snapshot(
    client_admin, test_charger, test_user
):
    """A transaction with a CHARGING QRPayment row is classified QR and the
    response carries a qr_session block populated from the pure budget
    helper. Numbers are Decimal-encoded strings to preserve precision."""
    test_user.role = UserRoleEnum.USER
    await test_user.save()
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("100.000"))
    await _make_qr_payment(test_charger, test_user, txn)

    snapshot = BudgetSnapshot(
        budget_limit=Decimal("490.00"),
        cost_so_far=Decimal("12.34"),
        remaining=Decimal("477.66"),
    )
    with patch.object(
        QRPaymentService, "compute_budget_snapshot",
        AsyncMock(return_value=snapshot),
    ):
        resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["funding_source"] == "QR"
    assert body["qr_session"] == {
        "budget_limit": "490.00",
        "cost_so_far": "12.34",
        "remaining": "477.66",
    }


async def test_funding_source_qr_with_unresolvable_budget_omits_block(
    client_admin, test_charger, test_user
):
    """If the helper returns None (e.g. tariff misconfigured), funding_source
    still classifies as QR but the qr_session block is omitted. Guards the
    UI against a half-populated card."""
    test_user.role = UserRoleEnum.USER
    await test_user.save()
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("100.000"))
    await _make_qr_payment(test_charger, test_user, txn)

    with patch.object(
        QRPaymentService, "compute_budget_snapshot",
        AsyncMock(return_value=None),
    ):
        resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["funding_source"] == "QR"
    assert body["qr_session"] is None


# ---------------------------------------------------------------------------
# compute_budget_snapshot purity
# ---------------------------------------------------------------------------


async def test_compute_budget_snapshot_does_not_stamp_meter_or_dispatch(
    test_charger, test_user
):
    """The helper must not write latest_reading_kwh / latest_power_kw /
    latest_meter_at into the qr_session row (that's the auto-stop path's
    job) and must not dispatch RemoteStop. Regression guard against an
    accidental merge of side effects into the read helper."""
    from redis_manager import redis_manager

    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("100.000"))
    await _make_qr_payment(test_charger, test_user, txn)

    # Prime the cache with a complete session row so the helper's load
    # path doesn't fall through to rebuild (which DOES write to Redis on
    # purpose). We want to assert about steady-state behavior.
    session = {
        "qr_payment_id": 1,
        "amount_paid": "500.00",
        "platform_fee": "10.00",
        "budget_limit_paise": 49000,
        "tariff_rate": "15.00",
        "gst_percent": "18.00",
        "start_meter_kwh": "100.000",
        "charger_id": test_charger.id,
    }
    with patch.object(redis_manager, "get_qr_session", AsyncMock(return_value=session)), \
         patch.object(redis_manager, "set_qr_session", AsyncMock(return_value=True)) as set_mock, \
         patch("services.qr_payment_service.safe_create_task") as safe_task:
        snapshot = await QRPaymentService.compute_budget_snapshot(txn.id)

    assert snapshot is not None
    set_mock.assert_not_called()
    safe_task.assert_not_called()


# ============================================================================
# Transactions Console — list enrichment + filters (slice 2.2) and detail
# drill-down fields (slice 2.3). CONTEXT.md "Transactions Console".
# ============================================================================

def _row_by_id(payload, txn_id):
    return next((r for r in payload["data"] if r["id"] == txn_id), None)


async def test_list_enriches_qr_session_funding_and_native_payment_status(
    client_admin, test_charger, test_user
):
    """A QR session reports funding_source=QR and the verbatim native
    QRPaymentStatusEnum value as payment_status."""
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0"))
    await _make_qr_payment(test_charger, test_user, txn)  # status CHARGING

    resp = await client_admin.get(f"/api/admin/transactions?user_id={test_user.id}")
    assert resp.status_code == 200, resp.text
    row = _row_by_id(resp.json(), txn.id)
    assert row["funding_source"] == "QR"
    assert row["payment_status"] == "CHARGING"


async def test_list_wallet_session_has_blank_payment_status(
    client_admin, test_charger, test_user
):
    """A wallet session shows funding_source=WALLET and a null payment_status
    — wallet CHARGE_DEDUCT carries no native status, and we do NOT derive one."""
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0"))

    resp = await client_admin.get(f"/api/admin/transactions?user_id={test_user.id}")
    assert resp.status_code == 200, resp.text
    row = _row_by_id(resp.json(), txn.id)
    assert row["funding_source"] == "WALLET"
    assert row["payment_status"] is None


async def test_list_filter_by_funding_source_qr_only(
    client_admin, test_charger, test_user
):
    """funding_source=QR returns only QR sessions; the wallet session is excluded."""
    qr_txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0"))
    await _make_qr_payment(test_charger, test_user, qr_txn)
    wallet_txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0"))

    resp = await client_admin.get(
        f"/api/admin/transactions?user_id={test_user.id}&funding_source=QR"
    )
    assert resp.status_code == 200, resp.text
    ids = {r["id"] for r in resp.json()["data"]}
    assert qr_txn.id in ids
    assert wallet_txn.id not in ids


async def test_list_filter_by_payment_status(
    client_admin, test_charger, test_user
):
    """payment_status=REFUND_FAILED returns only the matching QR session."""
    stuck = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0"))
    stuck_qr = await _make_qr_payment(test_charger, test_user, stuck)
    stuck_qr.status = QRPaymentStatusEnum.REFUND_FAILED
    await stuck_qr.save()
    ok = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0"))
    await _make_qr_payment(test_charger, test_user, ok)  # CHARGING

    resp = await client_admin.get(
        f"/api/admin/transactions?user_id={test_user.id}&payment_status=REFUND_FAILED"
    )
    assert resp.status_code == 200, resp.text
    ids = {r["id"] for r in resp.json()["data"]}
    assert ids == {stuck.id}


async def test_detail_exposes_payment_and_settlement_status(
    client_admin, test_charger, test_user
):
    """Detail drill-down surfaces verbatim payment_status (QR) and a
    settlement_status key (None when no CommissionLedgerEntry exists)."""
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0"))
    qrp = await _make_qr_payment(test_charger, test_user, txn)
    qrp.status = QRPaymentStatusEnum.REFUNDED
    await qrp.save()

    resp = await client_admin.get(f"/api/admin/transactions/{txn.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["payment_status"] == "REFUNDED"
    assert body["settlement_status"] is None


async def test_transactions_endpoints_require_admin(client, test_charger, test_user):
    """Every /api/admin/transactions route is admin-gated at the router level.
    Unauthenticated access must be rejected — these expose customer VPAs,
    refund amounts, and franchisee settlement economics. Regression guard for
    the auth gap found in the production-readiness review."""
    txn = await _make_transaction(test_charger, test_user, start_meter_kwh=Decimal("0"))
    for path in (
        "/api/admin/transactions",
        f"/api/admin/transactions/{txn.id}",
        f"/api/admin/transactions/{txn.id}/meter-values",
    ):
        resp = await client.get(path)  # `client` = no admin override
        assert resp.status_code in (401, 403), f"{path} not gated: {resp.status_code}"
