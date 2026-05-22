"""Concurrent-write correctness tests for the wallet ledger.

Drives multiple `process_transaction_billing` and `process_wallet_topup`
calls in parallel via `asyncio.gather` to verify:

  - `SELECT FOR UPDATE` on the wallet row serialises writers.
  - The idempotency check (existing CHARGE_DEDUCT lookup keyed on
    `charging_transaction_id`) prevents double-billing under races.
  - Cache invalidation runs once per actual write (the post-commit
    invalidation pattern from Fix #1).
  - Derived balance is exact under concurrent activity.

These tests run against the real Postgres test DB, not mocks, so they
exercise the actual locking and isolation semantics.
"""
import asyncio
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from models import (
    Charger,
    ChargingStation,
    Connector,
    PaymentStatusEnum,
    Tariff,
    Transaction,
    TransactionStatusEnum,
    TransactionTypeEnum,
    User,
    Wallet,
    WalletTransaction,
)
from services.wallet_service import WalletService


@pytest.fixture(autouse=True)
async def _redis_stub(monkeypatch):
    """Make every get_balance hit SQL — the test asserts ledger truth, not
    cache behavior. Tracks invalidation calls so we can count them."""
    from redis_manager import redis_manager

    invalidation_count = {"n": 0}

    async def _miss(*_a, **_k):
        return None

    async def _noop(*_a, **_k):
        return True

    async def _invalidate(*_a, **_k):
        invalidation_count["n"] += 1
        return True

    monkeypatch.setattr(redis_manager, "get_wallet_balance", _miss)
    monkeypatch.setattr(redis_manager, "set_wallet_balance", _noop)
    monkeypatch.setattr(redis_manager, "invalidate_wallet_balance", _invalidate)
    yield invalidation_count


async def _make_wallet_with_balance(initial: Decimal) -> Wallet:
    user = await User.create(
        email=f"conc-{uuid.uuid4().hex[:8]}@v.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    wallet = await Wallet.create(user=user)
    await WalletTransaction.create(
        wallet=wallet,
        amount=initial,
        type=TransactionTypeEnum.TOP_UP,
        description="Seed",
        payment_metadata={"status": "COMPLETED"},
    )
    return wallet


async def _make_charger_with_tariff() -> Charger:
    station = await ChargingStation.create(name="C-Station", state_code="32")
    charger = await Charger.create(
        charge_point_string_id=f"chg-{uuid.uuid4().hex[:8]}",
        station=station,
        latest_status="Charging",
    )
    await Connector.create(charger=charger, connector_id=1, connector_type="Type2")
    await Tariff.create(
        charger=charger,
        rate_per_kwh=Decimal("15.00"),
        tariff_per_kwh_all_in=Decimal("17.7000"),  # 15 × 1.18
        gst_percent=Decimal("18.00"),
    )
    return charger


@pytest.mark.asyncio
async def test_double_billing_call_is_idempotent_under_race(client, _redis_stub):
    """Two concurrent process_transaction_billing calls on the SAME
    transaction must result in exactly one CHARGE_DEDUCT row. The
    idempotency check (existing-CHARGE_DEDUCT lookup) is what guarantees
    this — if SELECT FOR UPDATE somehow let both pass the check, the DB
    would end up with two deductions."""
    wallet = await _make_wallet_with_balance(Decimal("500.00"))
    user = await wallet.user
    charger = await _make_charger_with_tariff()

    txn = await Transaction.create(
        user=user, charger=charger,
        start_meter_kwh=Decimal("0.00"),
        end_meter_kwh=Decimal("2.00"),
        energy_consumed_kwh=2.0,
        transaction_status=TransactionStatusEnum.STOPPED,
    )

    # Both callers target the same transaction_id.
    results = await asyncio.gather(
        WalletService.process_transaction_billing(txn.id),
        WalletService.process_transaction_billing(txn.id),
    )

    # Both succeed (one bills, one early-returns on the idempotency check).
    assert all(r[0] is True for r in results)

    # Exactly one CHARGE_DEDUCT row exists.
    deduct_count = await WalletTransaction.filter(
        charging_transaction_id=txn.id,
        type=TransactionTypeEnum.CHARGE_DEDUCT,
    ).count()
    assert deduct_count == 1

    # Derived balance reflects exactly one deduction (2 kWh × ₹15 × 1.18 = ₹35.40).
    assert await WalletService.get_balance(wallet.id) == Decimal("500.00") - Decimal("35.40")


@pytest.mark.asyncio
async def test_parallel_billings_for_different_transactions_all_apply(client, _redis_stub):
    """N concurrent billings on DIFFERENT transactions for the same wallet
    must all succeed and the final derived balance must equal
    initial - N × billing_amount. Verifies SELECT FOR UPDATE serialises
    without deadlocking and that every successful write invalidates the
    cache once."""
    wallet = await _make_wallet_with_balance(Decimal("1000.00"))
    user = await wallet.user
    charger = await _make_charger_with_tariff()

    n = 5
    txns = []
    for i in range(n):
        t = await Transaction.create(
            user=user, charger=charger,
            start_meter_kwh=Decimal("0.00"),
            end_meter_kwh=Decimal("1.00"),
            energy_consumed_kwh=1.0,
            transaction_status=TransactionStatusEnum.STOPPED,
        )
        txns.append(t)

    invalidations_before = _redis_stub["n"]
    results = await asyncio.gather(*[
        WalletService.process_transaction_billing(t.id) for t in txns
    ])
    invalidations_after = _redis_stub["n"]

    assert all(r[0] is True for r in results)

    # Each successful billing invalidates exactly once (post-commit hook).
    assert invalidations_after - invalidations_before == n

    # Final balance = 1000 - 5 × (1 × 15 × 1.18) = 1000 - 88.50 = 911.50
    per_charge = Decimal("17.70")
    expected = Decimal("1000.00") - (n * per_charge)
    assert await WalletService.get_balance(wallet.id) == expected


@pytest.mark.asyncio
async def test_concurrent_topup_completes_serialise_correctly(client, _redis_stub):
    """N concurrent process_wallet_topup calls on N different PENDING rows
    for the same wallet must all complete and the derived balance must
    sum correctly. Verifies the wallet-row lock serialises top-ups too."""
    wallet = await _make_wallet_with_balance(Decimal("0.00"))

    # Pre-create N PENDING TOP_UP rows.
    n = 4
    per_topup = Decimal("100.00")
    pending_rows = []
    for i in range(n):
        row = await WalletTransaction.create(
            wallet=wallet,
            amount=per_topup,
            type=TransactionTypeEnum.TOP_UP,
            description=f"Pending #{i}",
            razorpay_order_id=f"order_conc_{i}",
            payment_metadata={"status": PaymentStatusEnum.PENDING.value},
        )
        pending_rows.append(row)

    # Complete all of them concurrently.
    results = await asyncio.gather(*[
        WalletService.process_wallet_topup(
            wallet_transaction_id=row.id,
            razorpay_payment_id=f"pay_conc_{row.id}",
        )
        for row in pending_rows
    ])

    assert all(r[0] is True for r in results)
    # 0 (seed) + N × 100 — note seed is 0.00 because we explicitly built a
    # zero-seeded wallet via _make_wallet_with_balance(0).
    # Actually _make_wallet_with_balance creates a TOP_UP=initial row; with
    # initial=0 nothing is contributed.
    assert await WalletService.get_balance(wallet.id) == n * per_topup
