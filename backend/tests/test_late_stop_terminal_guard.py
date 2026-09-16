"""A late StopTransaction records the truth without moving the money.

ADR 0031 decision 5 / offline-continuity issue 01. Once a transaction is in
TERMINAL_TRANSACTION_STATES its billed figures are frozen: the refund, the
Settlement Entry and the GST Invoice were computed from them and there is no
credit note to correct an issued invoice. A charger replaying its queue after
a write-off — StopTransaction or MeterValues — lands in the reported_* fields
and nowhere else. The open-transaction paths are unchanged.
"""
import datetime
import types
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import (
    AuditLog, MeterValue, Transaction, TransactionStatusEnum,
    TERMINAL_TRANSACTION_STATES,
)
from utils import get_utc_now

pytestmark = pytest.mark.asyncio

BILLED_FIELDS = ("end_meter_kwh", "energy_consumed_kwh", "end_time", "total_billed",
                 "transaction_status", "stop_reason")
BILLING_PATCHES = (
    "services.wallet_service.WalletService.process_transaction_billing",
    "services.qr_payment_service.QRPaymentService.process_qr_session_billing",
    "services.franchisee_settlement_service.FranchiseeSettlementService.process_settlement",
    "services.invoice_service.InvoiceService.generate_invoice",
)
BUDGET_PATCHES = (
    "services.qr_payment_service.QRPaymentService.check_budget_and_auto_stop",
    "services.wallet_session_service.WalletSessionService.check_balance_and_auto_stop",
)


def _fake_cp(charger):
    """A ChargePoint stand-in with the real late-stop helpers bound to it."""
    from main import ChargePoint
    cp = MagicMock(spec=ChargePoint)
    cp.id = charger.charge_point_string_id
    for name in ("_record_late_stop", "_emit_late_stop_signals", "_record_replayed_reading"):
        setattr(cp, name, types.MethodType(getattr(ChargePoint, name), cp))
    return cp


async def _written_off_txn(charger, user, status=TransactionStatusEnum.STOPPED):
    """A session finalized on server-available data: 0.4 kWh billed."""
    started = get_utc_now() - datetime.timedelta(hours=50)
    txn = await Transaction.create(
        charger=charger, user=user, transaction_status=status,
        start_meter_kwh=Decimal("11.000"), end_meter_kwh=Decimal("11.400"),
        energy_consumed_kwh=Decimal("0.400"), total_billed=Decimal("8.00"),
        stop_reason="SUSPENDED_TIMEOUT",
        end_time=get_utc_now() - datetime.timedelta(hours=2),
    )
    await Transaction.filter(id=txn.id).update(start_time=started)
    return await Transaction.get(id=txn.id)


def _billed_snapshot(txn):
    return {f: getattr(txn, f) for f in BILLED_FIELDS}


async def _stop(cp, txn, meter_stop_wh, ts=None):
    from main import ChargePoint
    ts = ts or get_utc_now().isoformat().replace("+00:00", "Z")
    return await ChargePoint.on_stop_transaction(
        cp, transaction_id=txn.id, meter_stop=meter_stop_wh, timestamp=ts, reason="Local",
    )


async def _meter(cp, txn, wh):
    from main import ChargePoint
    return await ChargePoint.on_meter_values(
        cp, connector_id=1, transaction_id=txn.id,
        meter_value=[{
            "timestamp": get_utc_now().isoformat().replace("+00:00", "Z"),
            "sampledValue": [{"value": str(wh), "unit": "Wh",
                              "measurand": "Energy.Active.Import.Register"}],
        }],
    )


def _patch_all(names):
    mocks = {}
    ctxs = []
    for n in names:
        m = AsyncMock(return_value=(True, "ok", Decimal(0)))
        ctxs.append(patch(n, new=m))
        mocks[n.rsplit(".", 1)[1]] = m
    return ctxs, mocks


# ------------------------------------------------------- StopTransaction --

@pytest.mark.parametrize("status", sorted(TERMINAL_TRANSACTION_STATES, key=str))
async def test_late_stop_leaves_billed_fields_untouched(client, test_charger, test_user, status):
    """The charger says 22 kWh; the books say 0.4 kWh and stay that way."""
    txn = await _written_off_txn(test_charger, test_user, status)
    before = _billed_snapshot(txn)
    ctxs, mocks = _patch_all(BILLING_PATCHES)
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3]:
        response = await _stop(_fake_cp(test_charger), txn, meter_stop_wh=33000)

    assert response.id_tag_info == {"status": "Accepted"}
    fresh = await Transaction.get(id=txn.id)
    assert _billed_snapshot(fresh) == before
    assert fresh.reported_end_meter_kwh == Decimal("33.000")
    assert fresh.reported_energy_kwh == Decimal("22.000")
    assert fresh.reported_end_time is not None
    for name, m in mocks.items():
        assert not m.called, f"{name} must not run for a terminal transaction"


async def test_late_stop_emits_audit_and_alert_with_gap(client, test_charger, test_user):
    txn = await _written_off_txn(test_charger, test_user)
    with patch("services.monitoring_service.OCPPMetrics.record_late_stop_recorded",
               new=AsyncMock()) as alert:
        await _stop(_fake_cp(test_charger), txn, meter_stop_wh=33000)

    row = await AuditLog.filter(
        action="transaction.late_stop_recorded", entity_id=str(txn.id)
    ).first()
    assert row is not None
    assert row.changes["billed_energy_kwh"] == 0.4
    assert row.changes["reported_energy_kwh"] == 22.0
    assert row.changes["gap_kwh"] == pytest.approx(21.6)
    alert.assert_awaited_once()
    args = alert.await_args.args
    assert args[1] == txn.id and args[5] == pytest.approx(21.6)


async def test_normal_stop_unchanged_and_reported_equals_billed(client, test_charger, test_user):
    """The open path behaves exactly as today, and now also stamps reported_*."""
    txn = await Transaction.create(
        charger=test_charger, user=test_user,
        transaction_status=TransactionStatusEnum.RUNNING,
        start_meter_kwh=Decimal("11.000"),
    )
    ctxs, mocks = _patch_all(BILLING_PATCHES)
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3]:
        response = await _stop(_fake_cp(test_charger), txn, meter_stop_wh=14200)

    assert response.id_tag_info == {"status": "Accepted"}
    fresh = await Transaction.get(id=txn.id)
    assert fresh.transaction_status == TransactionStatusEnum.COMPLETED
    assert fresh.end_meter_kwh == Decimal("14.200")
    assert fresh.energy_consumed_kwh == Decimal("3.200")
    assert fresh.reported_end_meter_kwh == fresh.end_meter_kwh
    assert fresh.reported_energy_kwh == fresh.energy_consumed_kwh
    assert mocks["process_transaction_billing"].called
    assert await AuditLog.filter(
        action="transaction.late_stop_recorded", entity_id=str(txn.id)
    ).count() == 0


# ----------------------------------------------------------- MeterValues --

async def test_replayed_meter_values_stored_but_never_billed_or_resumed(
    client, test_charger, test_user
):
    txn = await _written_off_txn(test_charger, test_user)
    before = _billed_snapshot(txn)
    ctxs, mocks = _patch_all(BUDGET_PATCHES)
    with ctxs[0], ctxs[1]:
        await _meter(_fake_cp(test_charger), txn, wh=20000)
        await _meter(_fake_cp(test_charger), txn, wh=33000)

    fresh = await Transaction.get(id=txn.id)
    assert _billed_snapshot(fresh) == before
    assert fresh.resume_count == 0
    assert await MeterValue.filter(transaction_id=txn.id).count() == 2
    assert fresh.reported_end_meter_kwh == Decimal("33.000")
    assert fresh.reported_energy_kwh == Decimal("22.000")
    for name, m in mocks.items():
        assert not m.called, f"{name} must not run for a terminal transaction"


async def test_replayed_reading_never_lowers_reported_figure(client, test_charger, test_user):
    """A retried frame after a late stop must not walk the reported figure back."""
    txn = await _written_off_txn(test_charger, test_user)
    cp = _fake_cp(test_charger)
    await _stop(cp, txn, meter_stop_wh=33000)
    await _meter(cp, txn, wh=20000)

    fresh = await Transaction.get(id=txn.id)
    assert fresh.reported_end_meter_kwh == Decimal("33.000")


async def test_suspended_meter_values_still_resume(client, test_charger, test_user):
    txn = await Transaction.create(
        charger=test_charger, user=test_user,
        transaction_status=TransactionStatusEnum.SUSPENDED,
        start_meter_kwh=Decimal("11.000"), suspended_at=get_utc_now(),
    )
    ctxs, _ = _patch_all(BUDGET_PATCHES)
    with ctxs[0], ctxs[1]:
        await _meter(_fake_cp(test_charger), txn, wh=12000)

    fresh = await Transaction.get(id=txn.id)
    assert fresh.transaction_status == TransactionStatusEnum.RUNNING
    assert fresh.resume_count == 1


async def test_running_meter_values_still_budget_checked(client, test_charger, test_user):
    txn = await Transaction.create(
        charger=test_charger, user=test_user,
        transaction_status=TransactionStatusEnum.RUNNING,
        start_meter_kwh=Decimal("11.000"),
    )
    ctxs, mocks = _patch_all(BUDGET_PATCHES)
    with ctxs[0], ctxs[1]:
        await _meter(_fake_cp(test_charger), txn, wh=12000)

    mocks["check_budget_and_auto_stop"].assert_awaited_once()
    mocks["check_balance_and_auto_stop"].assert_awaited_once()
