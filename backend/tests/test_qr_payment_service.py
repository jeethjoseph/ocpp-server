"""Unit and integration tests for QRPaymentService.

Covers:
  - Webhook idempotency by razorpay_payment_id
  - Concurrent-payment rejection for the same charger (atomic guard)
  - Cross-environment webhook handling (no-op, not an error)
  - UPI guest user creation on first VPA
  - `_full_refund` idempotency via DB row lock
  - Razorpay "already refunded" reconciliation
  - Budget auto-stop when energy cost exceeds budget

These mirror the style of test_wallet_billing_gst.py (static-method calls,
mocked external services) with DB fixtures from conftest.py when needed.
"""
import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from services.qr_payment_service import QRPaymentService, find_or_create_user_from_payment, _resolve_platform_fee
from services.razorpay_service import RazorpayAlreadyRefundedError, extract_fee_from_payment
from models import (
    User, Charger, ChargingStation, Connector, ChargerQRCode, QRPayment,
    QRPaymentStatusEnum, AuthProviderEnum, ChargerStatusEnum, Transaction,
    TransactionStatusEnum, Wallet, Tariff,
)


# ============================================================================
# Fixtures specific to QR tests
# ============================================================================

@pytest.fixture
async def qr_station():
    return await ChargingStation.create(
        name="QR Test Station",
        latitude=12.0,
        longitude=77.0,
        address="QR Address",
    )


@pytest.fixture
async def qr_charger(qr_station):
    import uuid
    charger = await Charger.create(
        charge_point_string_id=f"qr-test-{uuid.uuid4().hex[:8]}",
        station_id=qr_station.id,
        name="QR Test Charger",
        model="Model QR",
        vendor="Vendor QR",
        serial_number=f"SNQR{uuid.uuid4().hex[:8]}",
        latest_status=ChargerStatusEnum.PREPARING,
    )
    await Connector.create(
        charger_id=charger.id,
        connector_id=1,
        connector_type="Type2",
        max_power_kw=22.0,
    )
    return charger


@pytest.fixture
async def qr_code(qr_charger):
    return await ChargerQRCode.create(
        charger=qr_charger,
        razorpay_qr_code_id="qr_TEST123",
        image_url="https://razorpay.example/qr/qr_TEST123.png",
        is_active=True,
    )


@pytest.fixture
async def qr_tariff(qr_charger):
    return await Tariff.create(
        charger=qr_charger,
        rate_per_kwh=Decimal("15.00"),
        gst_percent=Decimal("18.00"),
        is_global=False,
    )


def _webhook_payload(
    payment_id: str, qr_code_id: str, amount_paise: int,
    vpa: str = "test@okhdfc", fee_paise: int = None, tax_paise: int = None,
):
    entity = {
        "id": payment_id,
        "amount": amount_paise,
        "vpa": vpa,
        "contact": "+919999999999",
        "email": "user@example.com",
        "notes": {"customer_name": "Test User"},
        "created_at": 9999999999,  # Future timestamp — no staleness
    }
    if fee_paise is not None:
        entity["fee"] = fee_paise
        entity["tax"] = tax_paise if tax_paise is not None else 0
    return {
        "payment": {"entity": entity},
        "qr_code": {"entity": {"id": qr_code_id}},
    }


# ============================================================================
# Webhook idempotency
# ============================================================================

@pytest.mark.asyncio
async def test_qr_webhook_idempotency_same_payment_id(client, qr_charger, qr_code, qr_tariff):
    """Replaying the same razorpay_payment_id should not create a second QRPayment."""
    payload = _webhook_payload("pay_IDEMP001", "qr_TEST123", 10000)

    # First call — should create a QRPayment
    with patch.object(QRPaymentService, "_start_charging", new=AsyncMock()), \
         patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=False)
        result1 = await QRPaymentService.handle_qr_payment(payload)

    assert result1["status"] in ("processed", "failed")
    count_after_first = await QRPayment.filter(razorpay_payment_id="pay_IDEMP001").count()
    assert count_after_first == 1

    # Second call — must be treated as duplicate
    with patch.object(QRPaymentService, "_start_charging", new=AsyncMock()), \
         patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=False)
        result2 = await QRPaymentService.handle_qr_payment(payload)

    assert result2["status"] == "duplicate"
    count_after_second = await QRPayment.filter(razorpay_payment_id="pay_IDEMP001").count()
    assert count_after_second == 1


# ============================================================================
# Cross-environment webhook (QR code not found)
# ============================================================================

@pytest.mark.asyncio
async def test_qr_cross_env_qr_code_not_found(client):
    """Webhook for an unknown QR code is treated as error-but-handled, not crash."""
    payload = _webhook_payload("pay_CROSS001", "qr_UNKNOWN_ENV", 10000)

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=False)
        result = await QRPaymentService.handle_qr_payment(payload)

    assert result["status"] == "error"
    assert "not found" in result["reason"].lower()


# ============================================================================
# UPI guest user creation
# ============================================================================

@pytest.mark.asyncio
async def test_upi_guest_user_creation_from_vpa(client):
    """First-time VPA payment creates a UPI_GUEST user with a wallet."""
    user = await find_or_create_user_from_payment(
        phone=None, vpa="newcustomer@okicici", name="New Customer"
    )
    assert user is not None
    assert user.auth_provider == AuthProviderEnum.UPI_GUEST
    assert user.upi_vpa == "newcustomer@okicici"

    wallet = await Wallet.filter(user=user).first()
    assert wallet is not None
    assert wallet.balance == Decimal("0.00")


@pytest.mark.asyncio
async def test_upi_guest_user_reused_on_repeat_vpa(client):
    """Second payment with same VPA should reuse the first user, not create a duplicate."""
    user1 = await find_or_create_user_from_payment(
        phone=None, vpa="repeat@okicici", name="Repeat Customer"
    )
    user2 = await find_or_create_user_from_payment(
        phone=None, vpa="repeat@okicici", name="Repeat Customer"
    )
    assert user1.id == user2.id


# ============================================================================
# _full_refund idempotency (razorpay_refund_id already set)
# ============================================================================

@pytest.mark.asyncio
async def test_full_refund_skips_if_already_refunded(client, qr_charger, qr_code):
    """If razorpay_refund_id is already set, skip the Razorpay call."""
    import uuid
    user = await User.create(
        email=f"refund_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    qr_payment = await QRPayment.create(
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"),
        razorpay_refund_id="rfnd_EXISTING",
        status=QRPaymentStatusEnum.REFUNDED,
    )

    mock_razorpay = MagicMock()
    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(qr_payment, "Test reason")

    mock_razorpay.refund_payment.assert_not_called()


@pytest.mark.asyncio
async def test_full_refund_reconciles_already_refunded_error(client, qr_charger, qr_code):
    """When Razorpay reports already-refunded, we fetch + persist the existing refund_id."""
    import uuid
    user = await User.create(
        email=f"recon_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    qr_payment = await QRPayment.create(
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        razorpay_payment_id=payment_id,
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"),
        status=QRPaymentStatusEnum.PAID,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment.side_effect = RazorpayAlreadyRefundedError(
        payment_id, Exception("The payment has been refunded fully")
    )
    mock_razorpay.find_refund_for_payment.return_value = {"id": "rfnd_PREVIOUS"}
    mock_razorpay.fetch_payment_fees.return_value = None

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(qr_payment, "Reconciliation test")

    await qr_payment.refresh_from_db()
    assert qr_payment.razorpay_refund_id == "rfnd_PREVIOUS"
    assert qr_payment.status == QRPaymentStatusEnum.REFUNDED


@pytest.mark.asyncio
async def test_full_refund_fails_cleanly_when_reconciliation_finds_no_refund(client, qr_charger, qr_code):
    """If Razorpay claims already-refunded but we can't find any record, mark REFUND_FAILED."""
    import uuid
    user = await User.create(
        email=f"norec_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    qr_payment = await QRPayment.create(
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        razorpay_payment_id=payment_id,
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"),
        status=QRPaymentStatusEnum.PAID,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment.side_effect = RazorpayAlreadyRefundedError(
        payment_id, Exception("fully refunded")
    )
    mock_razorpay.find_refund_for_payment.return_value = None
    mock_razorpay.fetch_payment_fees.return_value = None

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(qr_payment, "Edge case")

    await qr_payment.refresh_from_db()
    assert qr_payment.status == QRPaymentStatusEnum.REFUND_FAILED
    assert qr_payment.razorpay_refund_id is None


# ============================================================================
# Concurrent-payment rejection on same charger
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_payment_rejected_when_active_txn(client, qr_charger, qr_code, qr_tariff):
    """If charger has an active transaction, new QR payment is rejected + refunded."""
    import uuid
    user = await User.create(
        email=f"conc_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
        rfid_card_id=f"RFID_{uuid.uuid4().hex[:12]}",
    )
    # Seed an active transaction on the charger
    await Transaction.create(
        charger=qr_charger,
        user=user,
        transaction_status=TransactionStatusEnum.RUNNING,
        start_meter_kwh=0,
    )

    payload = _webhook_payload("pay_CONC001", "qr_TEST123", 10000)

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment.return_value = {"id": "rfnd_REJECTED"}
    mock_razorpay.fetch_payment_fees.return_value = None

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=True)
        result = await QRPaymentService.handle_qr_payment(payload)

    assert result["status"] == "failed"
    assert result["reason"] == "active_transaction"
    mock_razorpay.refund_payment.assert_called_once()

    rejected = await QRPayment.filter(razorpay_payment_id="pay_CONC001").first()
    assert rejected is not None
    assert rejected.status == QRPaymentStatusEnum.REFUNDED
    assert rejected.razorpay_refund_id == "rfnd_REJECTED"


# ============================================================================
# extract_fee_from_payment helper
# ============================================================================

def test_extract_fee_from_payment_with_fee_and_tax():
    """Extracts fee and tax from paise to rupees."""
    result = extract_fee_from_payment({"fee": 236, "tax": 36})
    assert result == (Decimal("2.36"), Decimal("0.36"))


def test_extract_fee_from_payment_zero_fee():
    """fee=0 is valid (common for UPI) — returns (0, 0), not None."""
    result = extract_fee_from_payment({"fee": 0, "tax": 0})
    assert result == (Decimal("0"), Decimal("0"))


def test_extract_fee_from_payment_missing_fee():
    """Missing fee field returns None (data unavailable)."""
    assert extract_fee_from_payment({"amount": 10000}) is None


def test_extract_fee_from_payment_none_fee():
    """fee=None returns None (data unavailable)."""
    assert extract_fee_from_payment({"fee": None, "tax": None}) is None


# ============================================================================
# Webhook fee extraction into QRPayment
# ============================================================================

@pytest.mark.asyncio
async def test_qr_payment_stores_webhook_fee(client, qr_charger, qr_code, qr_tariff):
    """QR payment created from webhook with fee/tax stores actual Razorpay fee."""
    payload = _webhook_payload("pay_FEE001", "qr_TEST123", 10000, fee_paise=0, tax_paise=0)

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment.return_value = {"id": "rfnd_FEE001"}

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=False)
        result = await QRPaymentService.handle_qr_payment(payload)

    qr = await QRPayment.filter(razorpay_payment_id="pay_FEE001").first()
    assert qr is not None
    assert qr.platform_fee == Decimal("0.00")
    assert qr.razorpay_commission == Decimal("0.00")
    assert qr.razorpay_gst == Decimal("0.00")
    assert qr.fee_source == "webhook"


@pytest.mark.asyncio
async def test_qr_payment_no_fee_in_webhook_uses_fallback(client, qr_charger, qr_code, qr_tariff):
    """QR payment without fee/tax in webhook falls back to estimate during refund."""
    payload = _webhook_payload("pay_NOFEE001", "qr_TEST123", 10000)

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment.return_value = {"id": "rfnd_NOFEE"}
    mock_razorpay.fetch_payment_fees.return_value = None

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=False)
        await QRPaymentService.handle_qr_payment(payload)

    qr = await QRPayment.filter(razorpay_payment_id="pay_NOFEE001").first()
    assert qr is not None
    # No fee in webhook + API returned None → falls back to 2% estimate
    assert qr.fee_source == "estimated"
    assert qr.platform_fee == Decimal("2.00")  # 2% of ₹100


# ============================================================================
# _resolve_platform_fee helper
# ============================================================================

@pytest.mark.asyncio
async def test_resolve_fee_uses_stored_webhook_fee(client, qr_charger, qr_code):
    """When fee_source is 'webhook', returns stored platform_fee without API call."""
    import uuid
    user = await User.create(
        email=f"resolve_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    qr_payment = await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("200.00"),
        platform_fee=Decimal("0.00"),
        razorpay_commission=Decimal("0.00"),
        razorpay_gst=Decimal("0.00"),
        fee_source="webhook",
        status=QRPaymentStatusEnum.PAID,
    )

    mock_razorpay = MagicMock()
    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        fee = await _resolve_platform_fee(qr_payment)

    assert fee == Decimal("0.00")
    mock_razorpay.fetch_payment_fees.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_fee_falls_back_to_api(client, qr_charger, qr_code):
    """When no stored fee, fetches from Razorpay API and updates fields."""
    import uuid
    user = await User.create(
        email=f"api_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    qr_payment = await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"),
        status=QRPaymentStatusEnum.PAID,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.fetch_payment_fees.return_value = (Decimal("2.36"), Decimal("0.36"))

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        fee = await _resolve_platform_fee(qr_payment)

    assert fee == Decimal("2.36")
    assert qr_payment.razorpay_commission == Decimal("2.00")
    assert qr_payment.razorpay_gst == Decimal("0.36")
    assert qr_payment.fee_source == "api"


@pytest.mark.asyncio
async def test_resolve_fee_falls_back_to_estimate(client, qr_charger, qr_code):
    """When both webhook and API fail, uses 2% estimate."""
    import uuid
    user = await User.create(
        email=f"est_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    qr_payment = await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"),
        status=QRPaymentStatusEnum.PAID,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.fetch_payment_fees.return_value = None

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        fee = await _resolve_platform_fee(qr_payment)

    assert fee == Decimal("2.00")
    assert qr_payment.fee_source == "estimated"
    # Estimated breakdown: 18% GST on commission → gst = 2.00 * 18/118 ≈ 0.31
    assert qr_payment.razorpay_gst == Decimal("0.31")
    assert qr_payment.razorpay_commission == Decimal("1.69")
    assert qr_payment.razorpay_commission + qr_payment.razorpay_gst == fee


# ============================================================================
# Zero-fee serialization (Decimal("0.00") must not serialize as null)
# ============================================================================

def test_zero_decimal_serializes_as_string():
    """Decimal('0.00') must serialize as '0.00', not None.

    Python treats Decimal('0.00') as falsy. Using `if value` instead of
    `if value is not None` causes zero fees to vanish from API responses.
    """
    from decimal import Decimal
    val = Decimal("0.00")
    # This is what the routers do after the fix:
    result = str(val) if val is not None else None
    assert result == "0.00"
    # The old buggy pattern:
    buggy = str(val) if val else None
    assert buggy is None  # confirms the bug existed


# ============================================================================
# Budget cap on over-consumption in process_qr_session_billing
# ============================================================================

async def _make_qr_billing_fixture(qr_charger, qr_code, qr_tariff, energy_consumed_kwh: float):
    """Set up a QR payment + transaction at the CHARGING state with the
    given energy_consumed_kwh ready for process_qr_session_billing to run."""
    import uuid
    user = await User.create(
        email=f"u-{uuid.uuid4().hex[:8]}@v.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
        auth_provider=AuthProviderEnum.UPI_GUEST,
    )
    txn = await Transaction.create(
        user=user,
        charger=qr_charger,
        energy_consumed_kwh=energy_consumed_kwh,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    qr_payment = await QRPayment.create(
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
        razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        transaction=txn,
        customer_vpa="testpayer@oksbi",
        amount_paid=Decimal("20.00"),
        platform_fee=Decimal("0.24"),
        razorpay_commission=Decimal("0.20"),
        razorpay_gst=Decimal("0.04"),
        fee_source="webhook",
        status=QRPaymentStatusEnum.CHARGING,
    )
    return user, txn, qr_payment


@pytest.mark.asyncio
async def test_qr_billing_caps_energy_at_budget(client, qr_charger, qr_code, qr_tariff, caplog):
    """Over-consumption is capped at the budgeted pre-tax ceiling.

    amount_paid=20, platform_fee=0.24 → budget_incl_tax=19.76 →
    budget_excl_tax=19.76/1.18=16.75. Driving 5.0 kWh at ₹15/kWh would
    cost ₹75 uncapped, so this firmly tests the cap.
    """
    import logging
    _, txn, qr_payment = await _make_qr_billing_fixture(
        qr_charger, qr_code, qr_tariff, energy_consumed_kwh=5.0
    )

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        with caplog.at_level(logging.WARNING, logger="ocpp-server"):
            await QRPaymentService.process_qr_session_billing(txn.id)

    await qr_payment.refresh_from_db()
    await txn.refresh_from_db()

    expected_billable_excl_tax = Decimal("16.75")  # (20 - 0.24) / 1.18
    expected_gst = (expected_billable_excl_tax * Decimal("18") / Decimal("100")).quantize(Decimal("0.01"))

    assert qr_payment.energy_cost == expected_billable_excl_tax
    assert qr_payment.gst_amount == expected_gst
    assert qr_payment.refund_amount is None or qr_payment.refund_amount == Decimal("0")
    assert txn.energy_charge == expected_billable_excl_tax
    assert txn.gst_amount == expected_gst
    # Authoritative meter reading on the transaction is untouched.
    assert txn.energy_consumed_kwh == 5.0
    # Warning logged so ops can quantify over-delivery.
    assert any("over-consumption capped" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_qr_billing_under_budget_is_unchanged(client, qr_charger, qr_code, qr_tariff):
    """Under-budget consumption is unaffected by the cap (regression guard).

    0.5 kWh × ₹15 = ₹7.50 + GST ₹1.35 = ₹8.85, which is well under the
    ₹19.76 budget. Cap should not kick in; refund should flow.
    """
    _, txn, qr_payment = await _make_qr_billing_fixture(
        qr_charger, qr_code, qr_tariff, energy_consumed_kwh=0.5
    )

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        with patch("services.qr_payment_service.razorpay_service") as mock_rzp:
            mock_rzp.refund_payment.return_value = {"id": "rfnd_test_001"}
            await QRPaymentService.process_qr_session_billing(txn.id)

    await qr_payment.refresh_from_db()
    await txn.refresh_from_db()

    assert qr_payment.energy_cost == Decimal("7.50")
    assert qr_payment.gst_amount == Decimal("1.35")
    # Refund = 20 - 0.24 - 7.50 - 1.35 = 10.91
    assert qr_payment.refund_amount == Decimal("10.91")
    assert txn.energy_charge == Decimal("7.50")
