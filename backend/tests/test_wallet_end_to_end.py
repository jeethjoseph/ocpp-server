"""End-to-end integration test covering the full wallet path.

Top-up (PENDING → COMPLETED) → charging session → billing → GST invoice
→ derived balance. Verifies the whole chain interacts correctly across
Module A (positive amounts), Module B (in-session budget cap not tripped
under budget), Module C (derived balance from log), and Module A's
invoice generation (USER role → invoice issued).
"""
import uuid
from decimal import Decimal

import pytest

from models import (
    Charger,
    ChargingStation,
    Connector,
    GSTInvoice,
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
from services.invoice_service import InvoiceService
from services import invoice_service as _inv_mod


@pytest.fixture(autouse=True)
def _voltlync_supplier(monkeypatch):
    """Make GST invoice generation work without env vars (mirror of
    test_invoice_service.py's autouse fixture)."""
    monkeypatch.setattr(_inv_mod, "VOLTLYNC_GSTIN", "32ABCDE1234F1Z5")
    monkeypatch.setattr(_inv_mod, "VOLTLYNC_STATE_CODE", "32")
    monkeypatch.setattr(_inv_mod, "VOLTLYNC_STATE", "Kerala")


@pytest.fixture(autouse=True)
async def _redis_stub(monkeypatch):
    """Stub the wallet balance cache so the test asserts SQL-derived values."""
    from redis_manager import redis_manager

    async def _miss(*_a, **_k):
        return None

    async def _noop(*_a, **_k):
        return True

    monkeypatch.setattr(redis_manager, "get_wallet_balance", _miss)
    monkeypatch.setattr(redis_manager, "set_wallet_balance", _noop)
    monkeypatch.setattr(redis_manager, "invalidate_wallet_balance", _noop)


@pytest.mark.asyncio
async def test_full_path_topup_charge_invoice_balance(client):
    """The whole chain: pending recharge → completed → charge → bill →
    invoice issued → derived balance correct.

    Catches integration regressions across the three modules. Each unit
    test verifies one slice; this verifies the slices compose."""
    # ── Setup ─────────────────────────────────────────────────────────
    station = await ChargingStation.create(name="E2E Station", state_code="32")
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
        hsn_sac_code="996749",
    )
    user = await User.create(
        email=f"e2e-{uuid.uuid4().hex[:8]}@v.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    wallet = await Wallet.create(user=user)

    # ── Step 1: Top-up flow ───────────────────────────────────────────
    # Recharge-init creates a PENDING TOP_UP row.
    pending_topup = await WalletTransaction.create(
        wallet=wallet,
        amount=Decimal("100.00"),
        type=TransactionTypeEnum.TOP_UP,
        description="Recharge - ₹100 (Pending)",
        razorpay_order_id="order_test_e2e",
        payment_metadata={"status": PaymentStatusEnum.PENDING.value},
    )

    # PENDING must not credit the wallet.
    assert await WalletService.get_balance(wallet.id) == Decimal("0.00")

    # Razorpay webhook fires → process_wallet_topup flips to COMPLETED.
    success, msg, new_balance = await WalletService.process_wallet_topup(
        wallet_transaction_id=pending_topup.id,
        razorpay_payment_id="pay_test_e2e",
    )
    assert success is True
    assert new_balance == Decimal("100.00")
    assert await WalletService.get_balance(wallet.id) == Decimal("100.00")

    # ── Step 2: Charging session ──────────────────────────────────────
    txn = await Transaction.create(
        user=user,
        charger=charger,
        start_meter_kwh=Decimal("0.00"),
        end_meter_kwh=Decimal("3.00"),
        energy_consumed_kwh=3.0,
        transaction_status=TransactionStatusEnum.STOPPED,
    )

    # ── Step 3: Billing ───────────────────────────────────────────────
    # 3 kWh × ₹15 = ₹45 + 18% GST ₹8.10 = ₹53.10
    success, msg, amount = await WalletService.process_transaction_billing(txn.id)
    assert success is True
    assert amount == Decimal("53.10")

    # CHARGE_DEDUCT row was written with positive amount (Module A).
    deduct = await WalletTransaction.filter(
        wallet_id=wallet.id, type=TransactionTypeEnum.CHARGE_DEDUCT
    ).first()
    assert deduct is not None
    assert deduct.amount == Decimal("53.10")
    assert deduct.amount > 0  # explicit assertion of the sign convention

    # ── Step 4: Derived balance ───────────────────────────────────────
    # ₹100 TOP_UP (completed) minus ₹53.10 CHARGE_DEDUCT = ₹46.90
    assert await WalletService.get_balance(wallet.id) == Decimal("46.90")

    # ── Step 5: GST invoice ───────────────────────────────────────────
    invoice = await InvoiceService.generate_invoice(txn.id)
    assert invoice is not None
    assert invoice.energy_taxable_value == Decimal("45.00")
    assert invoice.total_tax == Decimal("8.10")
    assert invoice.total_amount == Decimal("53.10")
    # USER role → invoice IS issued (admin/franchisee skip from Module A
    # doesn't trigger here).
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 1
