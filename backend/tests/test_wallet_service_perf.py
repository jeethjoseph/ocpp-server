"""Performance benchmark for WalletService.get_balance.

Verifies the SUM query stays cheap as the wallet_transaction log grows.
The cache is stubbed out so every call exercises the SQL path.

Run with `-s` to see the timings:
    docker exec ocpp-backend pytest tests/test_wallet_service_perf.py -v -s
"""
import time
import uuid
from decimal import Decimal

import pytest

from models import (
    User,
    Wallet,
    WalletTransaction,
    TransactionTypeEnum,
)
from services.wallet_service import WalletService


# Ceiling per row count. Numbers are generous — real prod numbers should
# come in well under these — but they catch a serious regression
# (e.g. someone drops the wallet_id index).
TIMING_CEILINGS_MS = {
    200: 50,
    1000: 100,
    5000: 250,
}


@pytest.fixture(autouse=True)
async def _disable_cache(monkeypatch):
    """Disable Redis cache so every get_balance call exercises the SQL."""
    from redis_manager import redis_manager

    async def _miss(*_a, **_k):
        return None

    async def _noop(*_a, **_k):
        return True

    monkeypatch.setattr(redis_manager, "get_wallet_balance", _miss)
    monkeypatch.setattr(redis_manager, "set_wallet_balance", _noop)


async def _seed_wallet_with_history(n_rows: int) -> int:
    """Seed a fresh wallet with ~80% CHARGE_DEDUCT and ~20% COMPLETED TOP_UP."""
    user = await User.create(
        email=f"perf-{uuid.uuid4().hex[:8]}@v.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    wallet = await Wallet.create(user=user)

    rows = []
    for i in range(n_rows):
        if i % 5 == 0:
            rows.append(WalletTransaction(
                wallet_id=wallet.id,
                amount=Decimal("100.00"),
                type=TransactionTypeEnum.TOP_UP,
                payment_metadata={"status": "COMPLETED"},
            ))
        else:
            rows.append(WalletTransaction(
                wallet_id=wallet.id,
                amount=Decimal("5.00"),
                type=TransactionTypeEnum.CHARGE_DEDUCT,
                payment_metadata={},
            ))
    # bulk_create bypasses the model validator, but every amount is
    # positive here so the DB CHECK doesn't trip either.
    await WalletTransaction.bulk_create(rows, batch_size=500)
    return wallet.id


@pytest.mark.asyncio
@pytest.mark.parametrize("n_rows", [200, 1000, 5000])
async def test_get_balance_timing(client, n_rows, capsys):
    wallet_id = await _seed_wallet_with_history(n_rows)

    # Warm: one read to populate any caches, plan, etc.
    await WalletService.get_balance(wallet_id)

    # Measured: average over 5 calls.
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        await WalletService.get_balance(wallet_id)
        samples.append((time.perf_counter() - start) * 1000)
    avg_ms = sum(samples) / len(samples)
    p95_ms = sorted(samples)[-1]

    ceiling = TIMING_CEILINGS_MS[n_rows]
    with capsys.disabled():
        print(
            f"\n  get_balance @ N={n_rows:>5}: "
            f"avg={avg_ms:6.2f}ms  p95={p95_ms:6.2f}ms  "
            f"(ceiling {ceiling}ms)"
        )
    assert avg_ms < ceiling, (
        f"get_balance for N={n_rows} averaged {avg_ms:.1f}ms, "
        f"exceeds ceiling {ceiling}ms"
    )
