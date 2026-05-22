"""Tests for WalletSessionService — wallet budget cap + RemoteStop auto-stop.

Module B mirrors QRPaymentService.check_budget_and_auto_stop. These tests
verify the snapshot/tick/stop pattern, idempotency, and the DB-fallback
rebuild path used after a Redis cache miss.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from models import (
    Charger,
    ChargingStation,
    Connector,
    Tariff,
    Transaction,
    TransactionStatusEnum,
    TransactionTypeEnum,
    User,
    UserRoleEnum,
    Wallet,
    WalletTransaction,
)
from services.wallet_session_service import WalletSessionService


@pytest.fixture(autouse=True)
async def _redis_stub(monkeypatch):
    """Stub the wallet-balance cache layer used by WalletService.get_balance.

    The Redis session cache itself is mocked per-test (we assert against
    set/get/delete calls). The balance cache just needs to miss so reads
    fall through to the SQL aggregate.
    """
    from redis_manager import redis_manager

    async def _miss(*_a, **_k):
        return None

    async def _noop(*_a, **_k):
        return True

    monkeypatch.setattr(redis_manager, "get_wallet_balance", _miss)
    monkeypatch.setattr(redis_manager, "set_wallet_balance", _noop)
    monkeypatch.setattr(redis_manager, "invalidate_wallet_balance", _noop)


async def _make_wallet_session_fixture(initial_balance: Decimal = Decimal("50.00")):
    """Build a charging session for a wallet user with the given balance."""
    import uuid
    station = await ChargingStation.create(name="Station", state_code="32")
    charger = await Charger.create(
        charge_point_string_id=f"chg-{uuid.uuid4().hex[:8]}",
        station=station,
        latest_status="Charging",
    )
    await Connector.create(charger=charger, connector_id=1, connector_type="Type2")
    tariff = await Tariff.create(
        charger=charger,
        rate_per_kwh=Decimal("15.0000"),
        tariff_per_kwh_all_in=Decimal("17.7000"),  # 15 × 1.18
        gst_percent=Decimal("18.00"),
    )
    user = await User.create(
        email=f"u-{uuid.uuid4().hex[:8]}@v.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    wallet = await Wallet.create(user=user)
    if initial_balance > 0:
        await WalletTransaction.create(
            wallet=wallet,
            amount=initial_balance,
            type=TransactionTypeEnum.TOP_UP,
            description="seed",
            payment_metadata={"status": "COMPLETED"},
        )
    txn = await Transaction.create(
        user=user,
        charger=charger,
        start_meter_kwh=Decimal("0.0"),
        transaction_status=TransactionStatusEnum.RUNNING,
    )
    return wallet, charger, tariff, txn


@pytest.mark.asyncio
async def test_cache_session_on_start_writes_paise_int_payload(client):
    """Budget snapshot is stored as integer paise, not float rupees."""
    wallet, charger, tariff, txn = await _make_wallet_session_fixture(
        initial_balance=Decimal("50.00")
    )

    with patch("services.wallet_session_service.redis_manager") as mock_redis:
        mock_redis.set_wallet_session = AsyncMock(return_value=True)

        result = await WalletSessionService.cache_session_on_start(
            txn.id, wallet, tariff, start_meter_kwh=0.0, charger_id=charger.id
        )

    assert result is True
    mock_redis.set_wallet_session.assert_awaited_once()
    args, _ = mock_redis.set_wallet_session.call_args
    cached_txn_id, payload = args
    assert cached_txn_id == txn.id
    assert payload["wallet_id"] == wallet.id
    assert payload["budget_limit_paise"] == 5000  # ₹50.00
    assert payload["tariff_rate"] == 15.0
    assert payload["gst_percent"] == 18.0
    assert "auto_stop_scheduled" not in payload  # flag-less; at-least-once dispatch


@pytest.mark.asyncio
async def test_auto_stop_fires_when_cost_crosses_budget(client):
    """Cost ≥ budget triggers a RemoteStopTransaction schedule."""
    _, charger, _, txn = await _make_wallet_session_fixture()

    session_data = {
        "wallet_id": 1,
        "budget_limit_paise": 5000,  # ₹50
        "tariff_rate": 15.0,
        "gst_percent": 18.0,
        "start_meter_kwh": 0.0,
        "charger_id": charger.id,
    }
    # 3 kWh × ₹15 × 1.18 = ₹53.10 → exceeds ₹50 budget
    reading_kwh = 3.0

    with patch("services.wallet_session_service.redis_manager") as mock_redis, \
         patch("services.wallet_session_service.safe_create_task") as mock_task:
        mock_redis.get_wallet_session = AsyncMock(return_value=session_data)

        await WalletSessionService.check_balance_and_auto_stop(txn.id, reading_kwh)

    # No flag persisted (at-least-once pattern). One dispatch.
    mock_redis.set_wallet_session.assert_not_called()
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_late_tick_after_dispatch_fires_again(client):
    """At-least-once dispatch: a second MeterValues frame past the budget
    dispatches again. Duplicate RemoteStops are harmless — the charger
    handles them idempotently — and this self-healing property is exactly
    what protects us if a previous dispatch was lost (crash, network).
    Mirrors the QR pattern at qr_payment_service.py:561-576."""
    _, charger, _, txn = await _make_wallet_session_fixture()

    session_data = {
        "wallet_id": 1,
        "budget_limit_paise": 5000,
        "tariff_rate": 15.0,
        "gst_percent": 18.0,
        "start_meter_kwh": 0.0,
        "charger_id": charger.id,
    }

    with patch("services.wallet_session_service.redis_manager") as mock_redis, \
         patch("services.wallet_session_service.safe_create_task") as mock_task:
        mock_redis.get_wallet_session = AsyncMock(return_value=session_data)

        # Two frames past the budget — both should dispatch.
        await WalletSessionService.check_balance_and_auto_stop(txn.id, 3.0)
        await WalletSessionService.check_balance_and_auto_stop(txn.id, 4.0)

    assert mock_task.call_count == 2


@pytest.mark.asyncio
async def test_under_budget_does_not_fire_stop(client):
    """Cost below budget: only the log line, no stop scheduled."""
    _, charger, _, txn = await _make_wallet_session_fixture()

    session_data = {
        "wallet_id": 1,
        "budget_limit_paise": 5000,  # ₹50
        "tariff_rate": 15.0,
        "gst_percent": 18.0,
        "start_meter_kwh": 0.0,
        "charger_id": charger.id,
    }
    # 1 kWh × ₹15 × 1.18 = ₹17.70 — well under ₹50
    with patch("services.wallet_session_service.redis_manager") as mock_redis, \
         patch("services.wallet_session_service.safe_create_task") as mock_task:
        mock_redis.get_wallet_session = AsyncMock(return_value=session_data)
        mock_redis.set_wallet_session = AsyncMock(return_value=True)

        await WalletSessionService.check_balance_and_auto_stop(txn.id, 1.0)

    mock_task.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_rebuilds_from_db(client):
    """After a server restart, the cache is gone but the DB still has the
    wallet + tariff + transaction. The rebuild path re-creates the session
    payload so the cap still fires."""
    _, charger, _, txn = await _make_wallet_session_fixture(
        initial_balance=Decimal("10.00")  # very small budget
    )

    with patch("services.wallet_session_service.redis_manager") as mock_redis, \
         patch("services.wallet_session_service.safe_create_task") as mock_task:
        mock_redis.get_wallet_session = AsyncMock(return_value=None)  # cache miss
        mock_redis.set_wallet_session = AsyncMock(return_value=True)

        # 1 kWh × ₹15 × 1.18 = ₹17.70 — exceeds the ₹10 budget
        await WalletSessionService.check_balance_and_auto_stop(txn.id, 1.0)

    # Rebuild wrote the cache exactly once (the budget-exceed branch no
    # longer touches Redis under the flag-less pattern). Dispatch fired.
    assert mock_redis.set_wallet_session.await_count == 1
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_qr_session_skipped_by_rebuild(client):
    """QR sessions must not be rebuilt as wallet sessions — they have their
    own budget cap. _rebuild_session_from_db returns None when a QRPayment
    is linked to the transaction, so the check is a no-op."""
    import uuid
    from models import QRPayment, QRPaymentStatusEnum, ChargerQRCode
    _, charger, _, txn = await _make_wallet_session_fixture()
    qr_code = await ChargerQRCode.create(
        charger=charger,
        razorpay_qr_code_id=f"qr_{uuid.uuid4().hex[:8]}",
        image_url=f"https://r/{uuid.uuid4().hex[:6]}.png",
        is_active=True,
    )
    await QRPayment.create(
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
        razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
        charger=charger,
        charger_qr_code=qr_code,
        transaction=txn,
        amount_paid=Decimal("20.00"),
        status=QRPaymentStatusEnum.CHARGING,
    )

    with patch("services.wallet_session_service.redis_manager") as mock_redis, \
         patch("services.wallet_session_service.safe_create_task") as mock_task:
        mock_redis.get_wallet_session = AsyncMock(return_value=None)
        mock_redis.set_wallet_session = AsyncMock(return_value=True)

        await WalletSessionService.check_balance_and_auto_stop(txn.id, 5.0)

    mock_task.assert_not_called()
    mock_redis.set_wallet_session.assert_not_awaited()


# ============================================================================
# Internal-role skip (ADR 0004) — admin/franchisee sessions skip budget cap
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRoleEnum.ADMIN, UserRoleEnum.FRANCHISEE])
async def test_cache_session_on_start_skips_internal_role(client, role):
    """ADMIN/FRANCHISEE sessions must not snapshot a budget into Redis.

    The MeterValues budget check naturally short-circuits because no
    `wallet_session:{txn_id}` row exists — but we assert the skip explicitly
    at the entry point so an accidentally-cached row can't sneak past us
    if a future refactor changes the order of checks. See ADR 0004.
    """
    wallet, charger, tariff, txn = await _make_wallet_session_fixture()
    # Promote the wallet's owner to an internal role.
    user = await User.get(id=wallet.user_id)
    user.role = role
    await user.save()

    with patch("services.wallet_session_service.redis_manager") as mock_redis, \
         patch(
             "services.wallet_session_service.MetricsCollector.increment_counter"
         ) as mock_metric:
        mock_redis.set_wallet_session = AsyncMock(return_value=True)

        result = await WalletSessionService.cache_session_on_start(
            txn.id, wallet, tariff, start_meter_kwh=0.0, charger_id=charger.id
        )

    assert result is False, "Internal-role session must return False (no snapshot)"
    mock_redis.set_wallet_session.assert_not_awaited(), (
        "Internal-role session must not write a Redis snapshot"
    )
    metric_calls = [c.args[0] for c in mock_metric.call_args_list]
    assert "Custom/WalletSession/InternalRoleSkipped" in metric_calls
