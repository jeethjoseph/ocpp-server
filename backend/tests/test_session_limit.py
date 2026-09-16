"""SessionLimit: the Budget cap pushed to the charger that enforces it.

ADR 0031 decision 2 / offline-continuity issue 04. The number comes from the
same Redis session rows the server-side checks read; the Wh conversion rounds
DOWN; the push is keyed on transactionId, idempotent, re-sendable, and its
outcome never fails the session. StopDetail is the charger's follow-up that
says WHY it stopped.
"""
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.connection_manager import connection_manager
from models import Transaction, TransactionStatusEnum
from redis_manager import redis_manager
from services.session_limit_service import (
    budget_to_wh, build_payload, compute_session_limit_wh, push_session_limit,
)

pytestmark = pytest.mark.asyncio


def _response(status):
    r = MagicMock(); r.status = status; return r


def _register_fake_cp(charger, response="Accepted"):
    cp = MagicMock(); cp.id = charger.charge_point_string_id
    cp.call = AsyncMock(return_value=_response(response) if response else None)
    connection_manager.connected_charge_points[charger.charge_point_string_id] = {"cp": cp}
    return cp


@pytest.fixture(autouse=True)
def _clean_connection_registry():
    yield
    connection_manager.connected_charge_points.clear()


@pytest.fixture(autouse=True)
def _in_memory_session_cache():
    """Back the four Redis session accessors with a dict — the test process
    has no Redis client, and the service must read the SAME rows the
    server-side budget checks read, so we stub at that boundary."""
    store = {}

    def _set(prefix):
        async def f(txn_id, data, ttl=86400):
            store[f"{prefix}{txn_id}"] = dict(data); return True
        return f

    def _get(prefix):
        async def f(txn_id):
            return store.get(f"{prefix}{txn_id}")
        return f

    with patch.object(redis_manager, "set_qr_session", side_effect=_set("qr:")), \
         patch.object(redis_manager, "get_qr_session", side_effect=_get("qr:")), \
         patch.object(redis_manager, "set_wallet_session", side_effect=_set("wallet:")), \
         patch.object(redis_manager, "get_wallet_session", side_effect=_get("wallet:")):
        yield store


async def _running_txn(charger, user, start_kwh="10.000"):
    return await Transaction.create(
        charger=charger, user=user, transaction_status=TransactionStatusEnum.RUNNING,
        start_meter_kwh=Decimal(start_kwh),
    )


async def _qr_session(txn, budget_paise, rate="10.0000", gst="18"):
    await redis_manager.set_qr_session(txn.id, {
        "qr_payment_id": 1, "budget_limit_paise": budget_paise,
        "tariff_rate": rate, "gst_percent": gst,
        "start_meter_kwh": str(txn.start_meter_kwh), "charger_id": txn.charger_id,
    })


async def _wallet_session(txn, budget_paise, rate="10.0000", gst="18"):
    await redis_manager.set_wallet_session(txn.id, {
        "wallet_id": 1, "budget_limit_paise": budget_paise,
        "tariff_rate": float(rate), "gst_percent": float(gst),
        "start_meter_kwh": float(txn.start_meter_kwh), "charger_id": txn.charger_id,
    })


# ------------------------------------------------------------- the number --

def test_wh_conversion_rounds_down():
    """₹100 at ₹10/kWh + 18% GST buys 8.4745… kWh → 8474 Wh, never 8475."""
    assert budget_to_wh(Decimal("100"), Decimal("10"), Decimal("18")) == 8474


def test_wh_conversion_exact_case_and_guards():
    assert budget_to_wh(Decimal("11.8"), Decimal("10"), Decimal("18")) == 1000
    assert budget_to_wh(Decimal("100"), Decimal("0"), Decimal("18")) is None
    assert budget_to_wh(Decimal("-1"), Decimal("10"), Decimal("18")) is None


def test_payload_mirrors_transaction_limit_shape():
    data = json.loads(build_payload(42, 8474))
    assert data == {"transactionId": 42, "maxEnergy": 8474, "maxCost": None, "maxTime": None}


async def test_limit_from_qr_session(client, test_charger, test_user):
    txn = await _running_txn(test_charger, test_user)
    await _qr_session(txn, budget_paise=10000)
    assert await compute_session_limit_wh(txn.id) == 8474


async def test_limit_from_wallet_session(client, test_charger, test_user):
    txn = await _running_txn(test_charger, test_user)
    await _wallet_session(txn, budget_paise=5000)
    assert await compute_session_limit_wh(txn.id) == 4237


async def test_no_limit_without_a_budgeted_session(client, test_charger, test_admin_user):
    """Internal-role sessions never get a session row cached (ADR 0004) → no cap."""
    txn = await _running_txn(test_charger, test_admin_user)
    assert await compute_session_limit_wh(txn.id) is None
    cp = _register_fake_cp(test_charger)
    assert await push_session_limit(test_charger.charge_point_string_id, txn.id, "start") is None
    cp.call.assert_not_called()


# --------------------------------------------------------------- the push --

async def test_push_sends_datatransfer_keyed_on_transaction_id(client, test_charger, test_user):
    txn = await _running_txn(test_charger, test_user)
    await _qr_session(txn, budget_paise=10000)
    cp = _register_fake_cp(test_charger)

    outcome = await push_session_limit(test_charger.charge_point_string_id, txn.id, "start")

    assert outcome == "accepted"
    req = cp.call.call_args[0][0]
    assert req.vendor_id == "VOLTLYNC" and req.message_id == "SessionLimit"
    assert json.loads(req.data)["transactionId"] == txn.id
    assert json.loads(req.data)["maxEnergy"] == 8474


@pytest.mark.parametrize("response,expected", [
    ("Rejected", "rejected"), ("UnknownMessageId", "unknown_message_id"),
    ("UnknownVendorId", "unknown_vendor_id"), (None, "no_response"),
])
async def test_every_charger_answer_is_classified_not_raised(client, test_charger, test_user, response, expected):
    txn = await _running_txn(test_charger, test_user)
    await _qr_session(txn, budget_paise=10000)
    _register_fake_cp(test_charger, response=response)
    import asyncio
    with patch("services.monitoring_service.OCPPMetrics.record_session_limit_push", new=AsyncMock()) as m:
        assert await push_session_limit(test_charger.charge_point_string_id, txn.id, "start") == expected
        await asyncio.sleep(0.01)   # the metric is a fire-and-forget task
    assert m.await_args.args[4] == expected


async def test_timeout_and_disconnected_are_outcomes(client, test_charger, test_user):
    import asyncio
    txn = await _running_txn(test_charger, test_user)
    await _qr_session(txn, budget_paise=10000)
    assert await push_session_limit(test_charger.charge_point_string_id, txn.id, "start") == "not_connected"
    cp = _register_fake_cp(test_charger)
    cp.call = AsyncMock(side_effect=asyncio.TimeoutError())
    assert await push_session_limit(test_charger.charge_point_string_id, txn.id, "start") == "timeout"


async def test_budget_change_repushes_new_absolute_value_and_repeat_is_identical(client, test_charger, test_user):
    txn = await _running_txn(test_charger, test_user)
    await _qr_session(txn, budget_paise=10000)
    cp = _register_fake_cp(test_charger)
    cp_id = test_charger.charge_point_string_id

    await push_session_limit(cp_id, txn.id, "start")
    await _qr_session(txn, budget_paise=20000)          # a same-payer top-up (ADR 0021)
    await push_session_limit(cp_id, txn.id, "budget_change")
    await push_session_limit(cp_id, txn.id, "budget_change")

    sent = [json.loads(c.args[0].data)["maxEnergy"] for c in cp.call.call_args_list]
    assert sent == [8474, 16949, 16949]


# ------------------------------------------------------------- the hooks --

async def test_after_start_transaction_pushes_once_and_clears(client, test_charger, test_user):
    from main import ChargePoint
    txn = await _running_txn(test_charger, test_user)
    cp = MagicMock(spec=ChargePoint); cp.id = test_charger.charge_point_string_id
    cp._pending_session_limit_txn = txn.id
    with patch("services.session_limit_service.push_session_limit", new=AsyncMock()) as push:
        await ChargePoint.after_start_transaction(cp)
        await ChargePoint.after_start_transaction(cp)     # nothing pending → no second push
    push.assert_awaited_once_with(cp.id, txn.id, trigger="start")


async def test_reconnect_reasserts_open_transactions_only(client, test_charger, test_user):
    from main import ChargePoint
    running = await _running_txn(test_charger, test_user)
    suspended = await Transaction.create(
        charger=test_charger, user=test_user, transaction_status=TransactionStatusEnum.SUSPENDED,
        start_meter_kwh=Decimal("1"),
    )
    await Transaction.create(
        charger=test_charger, user=test_user, transaction_status=TransactionStatusEnum.COMPLETED,
        start_meter_kwh=Decimal("1"),
    )
    cp = MagicMock(spec=ChargePoint); cp.id = test_charger.charge_point_string_id
    with patch("services.session_limit_service.push_session_limit", new=AsyncMock()) as push:
        await ChargePoint.reassert_session_limits(cp)
    pushed = sorted(c.args[1] for c in push.await_args_list)
    assert pushed == sorted([running.id, suspended.id])
    assert all(c.kwargs["trigger"] == "reconnect" for c in push.await_args_list)


# ------------------------------------------------------------- StopDetail --

async def _stop_detail(charger, data):
    from main import ChargePoint
    cp = MagicMock(spec=ChargePoint); cp.id = charger.charge_point_string_id
    cp._handle_stop_detail = ChargePoint._handle_stop_detail.__get__(cp)
    return await ChargePoint.on_data_transfer(cp, vendor_id="VOLTLYNC", message_id="StopDetail", data=data)


async def test_stop_detail_records_reason_beside_stop_reason(client, test_charger, test_user):
    txn = await _running_txn(test_charger, test_user)
    await Transaction.filter(id=txn.id).update(stop_reason="Local")

    resp = await _stop_detail(test_charger, json.dumps({"transactionId": txn.id, "reason": "SessionLimit"}))

    assert resp.status == "Accepted"
    fresh = await Transaction.get(id=txn.id)
    assert fresh.stop_detail_reason == "SessionLimit"
    assert fresh.stop_reason == "Local"


@pytest.mark.parametrize("data", [
    json.dumps({"transactionId": 999999, "reason": "SessionLimit"}),
    json.dumps({"transactionId": 1}),
    "not json", None,
])
async def test_stop_detail_rejects_unknown_or_malformed_without_raising(client, test_charger, data):
    resp = await _stop_detail(test_charger, data)
    assert resp.status == "Rejected"
