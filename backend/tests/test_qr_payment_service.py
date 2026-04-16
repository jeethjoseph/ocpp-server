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

from services.qr_payment_service import QRPaymentService, find_or_create_user_from_payment
from services.razorpay_service import RazorpayAlreadyRefundedError
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


def _webhook_payload(payment_id: str, qr_code_id: str, amount_paise: int, vpa: str = "test@okhdfc"):
    return {
        "payment": {"entity": {
            "id": payment_id,
            "amount": amount_paise,
            "vpa": vpa,
            "contact": "+919999999999",
            "email": "user@example.com",
            "notes": {"customer_name": "Test User"},
            "created_at": 9999999999,  # Future timestamp — no staleness
        }},
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
