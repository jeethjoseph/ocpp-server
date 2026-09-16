"""Meter monotonicity: observe a backwards reading, never correct it.

ADR 0031 decision 7 / offline-continuity issue 05.
"""
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import AuditLog, MeterValue, Transaction, TransactionStatusEnum
from redis_manager import redis_manager
from services.meter_monotonicity import observe_reading

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _in_memory_high_water():
    store = {}

    async def _set(txn_id, value):
        store[txn_id] = value; return True

    async def _get(txn_id):
        return store.get(txn_id)

    with patch.object(redis_manager, "set_meter_high_water", side_effect=_set), \
         patch.object(redis_manager, "get_meter_high_water", side_effect=_get):
        yield store


async def _txn(charger, user, status=TransactionStatusEnum.RUNNING, start="11.000"):
    return await Transaction.create(
        charger=charger, user=user, transaction_status=status, start_meter_kwh=Decimal(start),
    )


async def _audits(txn):
    return await AuditLog.filter(action="transaction.meter_regression", entity_id=str(txn.id)).all()


async def test_advancing_readings_emit_nothing(client, test_charger, test_user):
    txn = await _txn(test_charger, test_user)
    cp = test_charger.charge_point_string_id
    for kwh in ("11.000", "12.500", "12.500", "14.200"):
        assert await observe_reading(txn, cp, Decimal(kwh)) is False
    assert await _audits(txn) == []


async def test_backwards_reading_is_reported_with_delta(client, test_charger, test_user):
    txn = await _txn(test_charger, test_user)
    cp = test_charger.charge_point_string_id
    await observe_reading(txn, cp, Decimal("14.200"))
    with patch("services.monitoring_service.OCPPMetrics.record_meter_regression", new=AsyncMock()) as m:
        assert await observe_reading(txn, cp, Decimal("0.900")) is True
        await asyncio.sleep(0.01)

    rows = await _audits(txn)
    assert len(rows) == 1
    assert rows[0].changes["previous_kwh"] == 14.2
    assert rows[0].changes["current_kwh"] == 0.9
    assert rows[0].changes["delta_kwh"] == pytest.approx(-13.3)
    assert rows[0].changes["charger_id"] == cp
    m.assert_awaited_once_with(cp, txn.id, 14.2, 0.9)


async def test_mark_holds_until_register_climbs_back(client, test_charger, test_user):
    """After a reset every frame below the old mark is a violation; once the
    register climbs past it, reporting stops."""
    txn = await _txn(test_charger, test_user)
    cp = test_charger.charge_point_string_id
    await observe_reading(txn, cp, Decimal("14.200"))
    assert await observe_reading(txn, cp, Decimal("0.900")) is True
    assert await observe_reading(txn, cp, Decimal("5.000")) is True
    assert await observe_reading(txn, cp, Decimal("14.300")) is False
    assert len(await _audits(txn)) == 2


async def test_cache_miss_seeds_from_meter_start_and_latest_row(client, test_charger, test_user):
    txn = await _txn(test_charger, test_user, start="11.000")
    cp = test_charger.charge_point_string_id
    # first reading below meterStart — caught with no prior frame at all
    assert await observe_reading(txn, cp, Decimal("0.500")) is True

    txn2 = await _txn(test_charger, test_user, start="11.000")
    await MeterValue.create(transaction=txn2, reading_kwh=Decimal("13.000"))
    assert await observe_reading(txn2, cp, Decimal("12.000")) is True
    assert await observe_reading(txn2, cp, Decimal("13.500")) is False


async def test_handler_stores_and_bills_the_backwards_reading(client, test_charger, test_user):
    """End to end through on_meter_values: the row lands, the budget check
    still runs on the reported figure, and the violation is audited."""
    from main import ChargePoint
    from utils import get_utc_now
    txn = await _txn(test_charger, test_user)
    cp = MagicMock(spec=ChargePoint); cp.id = test_charger.charge_point_string_id

    def frame(wh):
        return [{"timestamp": get_utc_now().isoformat().replace("+00:00", "Z"),
                 "sampledValue": [{"value": str(wh), "unit": "Wh",
                                   "measurand": "Energy.Active.Import.Register"}]}]

    with patch("services.qr_payment_service.QRPaymentService.check_budget_and_auto_stop", new=AsyncMock()) as qr, \
         patch("services.wallet_session_service.WalletSessionService.check_balance_and_auto_stop", new=AsyncMock()):
        await ChargePoint.on_meter_values(cp, connector_id=1, transaction_id=txn.id, meter_value=frame(14200))
        await ChargePoint.on_meter_values(cp, connector_id=1, transaction_id=txn.id, meter_value=frame(900))

    readings = sorted(float(r.reading_kwh) for r in await MeterValue.filter(transaction_id=txn.id))
    assert readings == [0.9, 14.2]
    assert qr.await_args.args[1] == Decimal("0.9")      # billed as reported
    assert len(await _audits(txn)) == 1


async def test_two_readings_in_one_frame_are_compared_in_order(client, test_charger, test_user):
    from main import ChargePoint
    from utils import get_utc_now
    txn = await _txn(test_charger, test_user)
    cp = MagicMock(spec=ChargePoint); cp.id = test_charger.charge_point_string_id
    ts = get_utc_now().isoformat().replace("+00:00", "Z")
    frame = [
        {"timestamp": ts, "sampledValue": [{"value": "14200", "unit": "Wh", "measurand": "Energy.Active.Import.Register"}]},
        {"timestamp": ts, "sampledValue": [{"value": "900", "unit": "Wh", "measurand": "Energy.Active.Import.Register"}]},
    ]
    with patch("services.qr_payment_service.QRPaymentService.check_budget_and_auto_stop", new=AsyncMock()), \
         patch("services.wallet_session_service.WalletSessionService.check_balance_and_auto_stop", new=AsyncMock()):
        await ChargePoint.on_meter_values(cp, connector_id=1, transaction_id=txn.id, meter_value=frame)
    assert len(await _audits(txn)) == 1


async def test_terminal_replay_is_observed_but_still_not_billed(client, test_charger, test_user):
    from main import ChargePoint
    from utils import get_utc_now
    txn = await _txn(test_charger, test_user, status=TransactionStatusEnum.STOPPED)
    await MeterValue.create(transaction=txn, reading_kwh=Decimal("14.200"))
    cp = MagicMock(spec=ChargePoint); cp.id = test_charger.charge_point_string_id
    cp._record_replayed_reading = AsyncMock()
    frame = [{"timestamp": get_utc_now().isoformat().replace("+00:00", "Z"),
              "sampledValue": [{"value": "900", "unit": "Wh", "measurand": "Energy.Active.Import.Register"}]}]
    with patch("services.qr_payment_service.QRPaymentService.check_budget_and_auto_stop", new=AsyncMock()) as qr:
        await ChargePoint.on_meter_values(cp, connector_id=1, transaction_id=txn.id, meter_value=frame)
    qr.assert_not_called()
    assert len(await _audits(txn)) == 1
