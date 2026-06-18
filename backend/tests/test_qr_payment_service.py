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
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from services.qr_payment_service import (
    QRPaymentService, find_or_create_user_from_payment,
    _ensure_actual_fee_captured,
)
from services.tariff_utils import synthetic_platform_fee, synthetic_fee_split
from services.razorpay_service import (
    RazorpayAlreadyRefundedError,
    RazorpayRefundBelowMinimumError,
    extract_fee_from_payment,
)
from services.wallet_service import WalletService
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
        tariff_per_kwh_all_in=Decimal("17.7000"),  # 15 × 1.18
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
async def test_qr_cross_env_qr_code_not_found(client, caplog):
    """Webhook for an unknown QR code is treated as error-but-handled, not crash.

    Staging and prod share one Razorpay live account, so each gets the
    other's QR webhooks — the miss is expected and must NOT log at ERROR
    (Sentry's LoggingIntegration captures ERROR). Regression for
    OCPP-BACKEND-R (208 false alarms)."""
    payload = _webhook_payload("pay_CROSS001", "qr_UNKNOWN_ENV", 10000)

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=False)
        with caplog.at_level("INFO", logger="services.qr_payment_service"):
            result = await QRPaymentService.handle_qr_payment(payload)

    assert result["status"] == "error"
    assert "not found" in result["reason"].lower()

    qr_miss_errors = [
        r for r in caplog.records
        if r.levelname == "ERROR" and "No active ChargerQRCode" in r.message
    ]
    assert not qr_miss_errors, "cross-env QR miss must not log at ERROR"


@pytest.mark.asyncio
async def test_qr_payment_on_inactive_own_qr_logs_error(client, qr_charger, caplog):
    """A payment on a QR that IS ours but inactive (closed/regenerated) means a
    customer paid and gets no session — must stay visible at ERROR, NOT be
    silently folded into the cross-environment info downgrade."""
    await ChargerQRCode.create(
        charger=qr_charger,
        razorpay_qr_code_id="qr_OURS_BUT_CLOSED",
        image_url="https://razorpay.example/qr/closed.png",
        is_active=False,
    )
    payload = _webhook_payload("pay_ONCLOSED", "qr_OURS_BUT_CLOSED", 10000)

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=False)
        with caplog.at_level("INFO", logger="services.qr_payment_service"):
            result = await QRPaymentService.handle_qr_payment(payload)

    assert result["status"] == "error"
    inactive_errors = [
        r for r in caplog.records
        if r.levelname == "ERROR" and "INACTIVE ChargerQRCode" in r.message
    ]
    assert inactive_errors, "payment on our own inactive QR must log at ERROR"


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
    # Module C: derived balance, defaults to 0 with no transactions.
    assert await WalletService.get_balance(wallet.id) == Decimal("0.00")


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
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
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
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
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
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
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
# _full_refund amount semantics (ADR 0002 — zero-energy full refund)
# ============================================================================

@pytest.mark.asyncio
async def test_full_refund_returns_amount_paid_in_full(client, qr_charger, qr_code):
    """Zero-energy refund issues the full amount_paid; actual fee captured but ignored."""
    import uuid
    user = await User.create(
        email=f"full_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    qr_payment = await QRPayment.create(
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("500.00"),
        status=QRPaymentStatusEnum.PAID,
    )

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {"id": "rfnd_FULL"}
    # Razorpay actually charged 1.5% on this payment — should land on the row
    # for ops, but NOT be subtracted from the refund.
    mock_razorpay.fetch_payment_fees.return_value = (Decimal("7.50"), Decimal("1.14"))

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(qr_payment, "Zero energy")

    mock_razorpay.refund_payment.assert_called_once()
    call_kwargs = mock_razorpay.refund_payment.call_args.kwargs
    assert call_kwargs["amount"] == Decimal("500.00"), \
        "Razorpay refund must be the full amount_paid, not amount_paid - fee"

    await qr_payment.refresh_from_db()
    assert qr_payment.refund_amount == Decimal("500.00")
    assert qr_payment.status == QRPaymentStatusEnum.REFUNDED
    assert qr_payment.razorpay_refund_id == "rfnd_FULL"
    # Actual Razorpay fee still recorded on the row for reconciliation
    assert qr_payment.platform_fee == Decimal("7.50")
    assert qr_payment.razorpay_commission == Decimal("6.36")
    assert qr_payment.razorpay_gst == Decimal("1.14")


@pytest.mark.asyncio
async def test_handle_charging_failure_issues_full_refund(client, qr_charger, qr_code, monkeypatch):
    """End-to-end: zero-energy finalize → handle_charging_failure → full refund.

    Trigger 1 of 6 for ADR 0002 instant-refund coverage: zero-energy at
    StopTransaction. Asserts speed=optimum reaches Razorpay so a refactor
    that bypasses `_full_refund` on this path is caught.
    """
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")
    import uuid
    user = await User.create(
        email=f"chg_fail_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
        rfid_card_id=f"RFID_{uuid.uuid4().hex[:12]}",
    )
    txn = await Transaction.create(
        charger=qr_charger,
        user=user,
        transaction_status=TransactionStatusEnum.STOPPED,
        start_meter_kwh=Decimal("0.000"),
        end_meter_kwh=Decimal("0.000"),
        energy_consumed_kwh=Decimal("0.000"),
    )
    qr_payment = await QRPayment.create(
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        transaction=txn,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("250.00"),
        status=QRPaymentStatusEnum.CHARGING,
        platform_fee=Decimal("4.75"),
        razorpay_commission=Decimal("4.03"),
        razorpay_gst=Decimal("0.72"),
        fee_source="webhook",
    )

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {"id": "rfnd_CHG_FAIL"}

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        await QRPaymentService.handle_charging_failure(txn.id)

    call_kwargs = mock_razorpay.refund_payment.call_args.kwargs
    assert call_kwargs["amount"] == Decimal("250.00")
    assert call_kwargs["speed"] == "optimum"

    await qr_payment.refresh_from_db()
    assert qr_payment.refund_amount == Decimal("250.00")
    assert qr_payment.status == QRPaymentStatusEnum.REFUNDED
    # No GST invoice expected — verify by checking absence
    from models import GSTInvoice
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 0


@pytest.mark.asyncio
async def test_process_qr_session_billing_zero_energy_issues_full_refund(
    client, qr_charger, qr_code, qr_tariff, monkeypatch
):
    """ADR 0002: process_qr_session_billing must full-refund a zero-energy session.

    Regression for the 2026-05-27 bug where the function fell through to the
    over-payment formula `refund = amount_paid - energy_cost - gst - synth_fee`
    when energy_consumed_kwh was 0. With energy=0 the formula returned
    `amount_paid - synthetic_fee`, leaving the customer short by the synthetic
    platform fee (~2%) when ADR 0002 promises a full refund.

    Surfaced on payment id 96 (staging): ₹1500 paid, 0 kWh delivered, ₹1470
    refunded — should have been ₹1500. This test routes a clean StopTransaction
    with zero energy through process_qr_session_billing and asserts:
      - the full amount_paid is refunded (no synthetic fee deduction)
      - speed=optimum is requested (matches the _full_refund / ADR 0002 amendment)
      - QR payment ends REFUNDED
      - no GST invoice is issued (zero-energy = no taxable supply)
    """
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    _, txn, qr_payment = await _make_qr_billing_fixture(
        qr_charger, qr_code, qr_tariff, energy_consumed_kwh=0.0,
    )

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {
        "id": "rfnd_ZERO_ENERGY",
        "speed_processed": "instant",
    }

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        await QRPaymentService.process_qr_session_billing(txn.id)

    mock_razorpay.refund_payment.assert_called_once()
    call_kwargs = mock_razorpay.refund_payment.call_args.kwargs
    # Full refund — not amount_paid - synthetic_fee.
    assert call_kwargs["amount"] == Decimal("20.00")
    # Routed through _full_refund → instant speed per ADR 0002 amendment.
    assert call_kwargs["speed"] == "optimum"

    await qr_payment.refresh_from_db()
    assert qr_payment.refund_amount == Decimal("20.00")
    assert qr_payment.status == QRPaymentStatusEnum.REFUNDED
    # razorpay_refund_id populated proves _full_refund ran (not the over-payment path).
    assert qr_payment.razorpay_refund_id == "rfnd_ZERO_ENERGY"

    # No GST invoice for zero-energy sessions (ADR 0002 — no taxable supply).
    from models import GSTInvoice
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 0


# ============================================================================
# Razorpay instant refund speed wiring (ADR 0002)
# ============================================================================

@pytest.fixture
async def _refund_qr_payment(qr_charger, qr_code):
    """Minimal PAID QR payment ready for a full-refund call."""
    import uuid
    user = await User.create(
        email=f"speed_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    return await QRPayment.create(
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("300.00"),
        status=QRPaymentStatusEnum.PAID,
        platform_fee=Decimal("5.40"),
        razorpay_commission=Decimal("4.58"),
        razorpay_gst=Decimal("0.82"),
        fee_source="webhook",
    )


@pytest.mark.asyncio
async def test_full_refund_passes_speed_optimum_when_flag_enabled(
    client, _refund_qr_payment, monkeypatch
):
    """ADR 0002: full refunds request instant payout via speed=optimum.

    All six triggers flow through `_full_refund`. Per-trigger tests assert
    the speed param at each integration site so a refactor that bypasses
    `_full_refund` for one trigger is caught. Triggers covered:
      1. Zero-energy at StopTransaction → test_handle_charging_failure_issues_full_refund
      2. Stale payment → test_stale_payment_full_refund_passes_speed_optimum
      3. Concurrent rejection → test_concurrent_payment_rejected_when_active_txn
      4. Charger not connected → test_charger_not_connected_full_refund_passes_speed_optimum
      5. RemoteStart failed / 6. Plug-in timeout → covered only by this direct
         test; integration setup for those paths would require >30 lines of
         OCPP/asyncio mocking and the funnel is identical (see issue 02
         Comments section for the rationale).
    """
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {
        "id": "rfnd_INSTANT", "speed_processed": "instant",
    }

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(_refund_qr_payment, "Zero energy")

    mock_razorpay.refund_payment.assert_called_once()
    assert mock_razorpay.refund_payment.call_args.kwargs["speed"] == "optimum"

    await _refund_qr_payment.refresh_from_db()
    assert _refund_qr_payment.razorpay_refund_speed_processed == "instant"


@pytest.mark.asyncio
async def test_full_refund_persists_speed_processed_normal_on_fallback(
    client, _refund_qr_payment, monkeypatch
):
    """When Razorpay falls back to normal speed server-side, persist 'normal'
    on the QRPayment row so ops can see the fallback in the admin UI without
    grepping logs."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {
        "id": "rfnd_FB", "speed_processed": "normal",
    }

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(_refund_qr_payment, "Zero energy")

    await _refund_qr_payment.refresh_from_db()
    assert _refund_qr_payment.razorpay_refund_speed_processed == "normal"


@pytest.mark.asyncio
async def test_admin_qr_payments_endpoint_returns_refund_speed_processed(
    client_admin, qr_charger, qr_code
):
    """Admin QR payment list response includes razorpay_refund_speed_processed
    so the frontend can render the instant-vs-normal badge."""
    import uuid
    user = await User.create(
        email=f"endpoint_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    await QRPayment.create(
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"),
        refund_amount=Decimal("100.00"),
        razorpay_refund_id="rfnd_API",
        razorpay_refund_speed_processed="instant",
        status=QRPaymentStatusEnum.REFUNDED,
    )

    resp = await client_admin.get(f"/api/admin/qr-codes/{qr_code.id}/payments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["razorpay_refund_speed_processed"] == "instant"


@pytest.mark.asyncio
async def test_full_refund_persists_speed_processed_from_reconciliation(
    client, _refund_qr_payment, monkeypatch
):
    """`RazorpayAlreadyRefundedError` reconciliation persists speed_processed
    from the existing-refund dict when present."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.side_effect = RazorpayAlreadyRefundedError(
        _refund_qr_payment.razorpay_payment_id, Exception("dup")
    )
    mock_razorpay.find_refund_for_payment.return_value = {
        "id": "rfnd_RECON", "speed_processed": "instant",
    }

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(_refund_qr_payment, "Zero energy")

    await _refund_qr_payment.refresh_from_db()
    assert _refund_qr_payment.razorpay_refund_id == "rfnd_RECON"
    assert _refund_qr_payment.razorpay_refund_speed_processed == "instant"


@pytest.mark.asyncio
async def test_full_refund_emits_instant_succeeded_metric(
    client, _refund_qr_payment, monkeypatch
):
    """Razorpay returns speed_processed=instant → RefundInstantSucceeded
    counter increments, RefundInstantFallback does not."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {
        "id": "rfnd_M_OK", "speed_processed": "instant",
    }
    mock_razorpay.fetch_balance = AsyncMock(return_value={
        "balance": 422.68, "refund_credits": 0.0,
    })

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.OCPPMetrics.record_refund_speed",
               new_callable=AsyncMock) as mock_record:
        await QRPaymentService._full_refund(_refund_qr_payment, "Zero energy")

    mock_record.assert_awaited_once()
    assert mock_record.await_args.args[2] == "instant"
    # Funding pools snapshotted before the POST ride along to the NR event.
    assert mock_record.await_args.kwargs["balance_before"] == 422.68
    assert mock_record.await_args.kwargs["refund_credits_before"] == 0.0


@pytest.mark.asyncio
async def test_full_refund_emits_fallback_metric_when_response_is_normal(
    client, _refund_qr_payment, monkeypatch
):
    """`speed=optimum` requested but Razorpay fell back to normal →
    RefundInstantFallback counter increments via record_refund_speed.
    """
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {
        "id": "rfnd_M_FB", "speed_processed": "normal",
    }
    mock_razorpay.fetch_balance = AsyncMock(return_value={
        "balance": 422.68, "refund_credits": 0.0,
    })

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.OCPPMetrics.record_refund_speed",
               new_callable=AsyncMock) as mock_record:
        await QRPaymentService._full_refund(_refund_qr_payment, "Zero energy")

    mock_record.assert_awaited_once()
    assert mock_record.await_args.args[2] == "normal"


@pytest.mark.asyncio
async def test_full_refund_completes_when_balance_fetch_unavailable(
    client, _refund_qr_payment, monkeypatch
):
    """Best-effort guard: a failed balance read must not break the refund.
    The refund still completes and the QRRefundSpeed event still fires with
    balance_before=None. ADR 0002 (2026-06-18 amendment)."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {
        "id": "rfnd_M_NOBAL", "speed_processed": "normal",
    }
    # fetch_balance is best-effort and returns None when the read fails.
    mock_razorpay.fetch_balance = AsyncMock(return_value=None)

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.OCPPMetrics.record_refund_speed",
               new_callable=AsyncMock) as mock_record:
        await QRPaymentService._full_refund(_refund_qr_payment, "Zero energy")

    # Refund still issued despite the unavailable balance (re-fetch the row —
    # _full_refund mutates a freshly locked instance, not the passed-in object).
    updated = await QRPayment.get(id=_refund_qr_payment.id)
    assert updated.razorpay_refund_id == "rfnd_M_NOBAL"
    assert updated.status == QRPaymentStatusEnum.REFUNDED
    # Event still fires, with null funding pools.
    mock_record.assert_awaited_once()
    assert mock_record.await_args.kwargs["balance_before"] is None
    assert mock_record.await_args.kwargs["refund_credits_before"] is None


@pytest.mark.asyncio
async def test_full_refund_emits_no_metric_when_flag_disabled(
    client, _refund_qr_payment, monkeypatch
):
    """Kill-switch off → speed wasn't requested as optimum → neither counter
    fires. A normal-speed refund is intentional, not a fallback."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "false")

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {
        "id": "rfnd_M_OFF", "speed_processed": "normal",
    }

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.OCPPMetrics.record_refund_speed",
               new_callable=AsyncMock) as mock_record:
        await QRPaymentService._full_refund(_refund_qr_payment, "Zero energy")

    mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_full_refund_reconciliation_emits_metric_when_speed_present(
    client, _refund_qr_payment, monkeypatch
):
    """Reconciliation path also emits the metric when the existing-refund
    dict carries `speed_processed` (only when optimum was requested)."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.side_effect = RazorpayAlreadyRefundedError(
        _refund_qr_payment.razorpay_payment_id, Exception("dup")
    )
    mock_razorpay.find_refund_for_payment.return_value = {
        "id": "rfnd_M_RECON", "speed_processed": "instant",
    }
    mock_razorpay.fetch_balance = AsyncMock(return_value={
        "balance": 422.68, "refund_credits": 0.0,
    })

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.OCPPMetrics.record_refund_speed",
               new_callable=AsyncMock) as mock_record:
        await QRPaymentService._full_refund(_refund_qr_payment, "Zero energy")

    mock_record.assert_awaited_once()
    assert mock_record.await_args.args[2] == "instant"


@pytest.mark.asyncio
async def test_partial_refund_does_not_emit_speed_metric(
    client, qr_charger, qr_code, qr_tariff, monkeypatch
):
    """Partial refunds in process_qr_session_billing never touch the speed
    metric — they stay on normal speed and are not 'fallbacks'."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    _, txn, _qr_payment = await _make_qr_billing_fixture(
        qr_charger, qr_code, qr_tariff, energy_consumed_kwh=0.5,
    )

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        with patch("services.qr_payment_service.razorpay_service") as mock_rzp, \
             patch("services.qr_payment_service.OCPPMetrics.record_refund_speed",
                   new_callable=AsyncMock) as mock_record:
            mock_rzp.refund_payment = AsyncMock()
            mock_rzp.find_refund_for_payment = AsyncMock()
            mock_rzp.fetch_payment = AsyncMock()
            mock_rzp.fetch_payment_fees = AsyncMock()
            mock_rzp.fetch_order = AsyncMock()
            mock_rzp.create_transfer = AsyncMock()
            mock_rzp.refund_payment.return_value = {"id": "rfnd_partial_M"}
            await QRPaymentService.process_qr_session_billing(txn.id)

    mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_full_refund_passes_speed_none_when_flag_disabled(
    client, _refund_qr_payment, monkeypatch
):
    """Kill-switch: with RAZORPAY_INSTANT_REFUND_ENABLED=false, no speed is set."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "false")

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {
        "id": "rfnd_NORMAL", "speed_processed": "normal",
    }

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(_refund_qr_payment, "Zero energy")

    mock_razorpay.refund_payment.assert_called_once()
    assert mock_razorpay.refund_payment.call_args.kwargs["speed"] is None


@pytest.mark.asyncio
async def test_partial_refund_does_not_request_instant_speed(
    client, qr_charger, qr_code, qr_tariff, monkeypatch
):
    """Partial unused-credit refunds stay on normal speed even with the flag on
    (ADR 0002 — instant is scoped to full refunds where service was not rendered)."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    _, txn, qr_payment = await _make_qr_billing_fixture(
        qr_charger, qr_code, qr_tariff, energy_consumed_kwh=0.5,
    )

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        with patch("services.qr_payment_service.razorpay_service") as mock_rzp:
            mock_rzp.refund_payment = AsyncMock()
            mock_rzp.find_refund_for_payment = AsyncMock()
            mock_rzp.fetch_payment = AsyncMock()
            mock_rzp.fetch_payment_fees = AsyncMock()
            mock_rzp.fetch_order = AsyncMock()
            mock_rzp.create_transfer = AsyncMock()
            mock_rzp.refund_payment.return_value = {"id": "rfnd_partial"}
            await QRPaymentService.process_qr_session_billing(txn.id)

    mock_rzp.refund_payment.assert_called_once()
    # speed kwarg either absent entirely or None — both mean "normal".
    assert mock_rzp.refund_payment.call_args.kwargs.get("speed") is None


@pytest.mark.asyncio
async def test_partial_refund_below_razorpay_minimum_marks_failed_without_error_log(
    client, qr_charger, qr_code, qr_tariff, monkeypatch, caplog
):
    """When the unused-credit refund is below Razorpay's ₹1.00 minimum,
    refund_payment raises RazorpayRefundBelowMinimumError. The session
    must (a) not crash, (b) mark status=REFUND_FAILED with
    failure_reason='below_razorpay_minimum' so the billing-retry sweep
    excludes the entry, and (c) only log at INFO level so Sentry's
    LoggingIntegration (ERROR threshold by default) does not capture it.

    Regression for the 2026-05-26 staging Sentry noise from
    pay_SpuaKiPYNEFPL6 — a small-balance QR session retrying every
    interval with no possible resolution.
    """
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")

    _, txn, qr_payment = await _make_qr_billing_fixture(
        qr_charger, qr_code, qr_tariff, energy_consumed_kwh=0.5,
    )

    below_min_error = RazorpayRefundBelowMinimumError(
        qr_payment.razorpay_payment_id,
        Exception("The amount must be atleast INR 1.00"),
    )

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        with patch("services.qr_payment_service.razorpay_service") as mock_rzp:
            mock_rzp.refund_payment = AsyncMock()
            mock_rzp.find_refund_for_payment = AsyncMock()
            mock_rzp.fetch_payment = AsyncMock()
            mock_rzp.fetch_payment_fees = AsyncMock()
            mock_rzp.fetch_order = AsyncMock()
            mock_rzp.create_transfer = AsyncMock()
            mock_rzp.refund_payment.side_effect = below_min_error
            with caplog.at_level("INFO", logger="services.qr_payment_service"):
                await QRPaymentService.process_qr_session_billing(txn.id)

    await qr_payment.refresh_from_db()
    assert qr_payment.status == QRPaymentStatusEnum.REFUND_FAILED
    assert qr_payment.failure_reason == "below_razorpay_minimum"

    # No ERROR-level "Refund failed" log from this path — Sentry's
    # LoggingIntegration only captures ERROR by default.
    error_refund_logs = [
        r for r in caplog.records
        if r.levelname == "ERROR" and "Refund failed" in r.getMessage()
    ]
    assert not error_refund_logs, (
        f"unexpected ERROR-level refund log: "
        f"{[r.getMessage() for r in error_refund_logs]}"
    )


# ============================================================================
# Concurrent-payment rejection on same charger
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_payment_rejected_when_active_txn(client, qr_charger, qr_code, qr_tariff, monkeypatch):
    """If charger has an active transaction, new QR payment is rejected + refunded.

    Trigger 3 of 6 for ADR 0002 instant-refund coverage: concurrent payment
    rejected on busy charger. Asserts speed=optimum reaches Razorpay.
    """
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")
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
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {"id": "rfnd_REJECTED"}
    mock_razorpay.fetch_payment_fees.return_value = None

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=True)
        result = await QRPaymentService.handle_qr_payment(payload)

    assert result["status"] == "failed"
    assert result["reason"] == "active_transaction"
    mock_razorpay.refund_payment.assert_called_once()
    assert mock_razorpay.refund_payment.call_args.kwargs["speed"] == "optimum"

    rejected = await QRPayment.filter(razorpay_payment_id="pay_CONC001").first()
    assert rejected is not None
    assert rejected.status == QRPaymentStatusEnum.REFUNDED
    assert rejected.razorpay_refund_id == "rfnd_REJECTED"


@pytest.mark.asyncio
async def test_stale_payment_full_refund_passes_speed_optimum(
    client, qr_charger, qr_code, monkeypatch
):
    """Trigger 2 of 6: stale payment (webhook delayed past pending timeout)
    issues a full refund via `_full_refund` with speed=optimum.
    """
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")
    # Make the payment older than QR_PAYMENT_PENDING_TIMEOUT (300s default).
    stale_ts = int(datetime.now(timezone.utc).timestamp()) - 900
    payload = _webhook_payload("pay_STALE001", "qr_TEST123", 10000)
    payload["payment"]["entity"]["created_at"] = stale_ts

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {"id": "rfnd_STALE"}
    mock_razorpay.fetch_payment_fees.return_value = None

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        result = await QRPaymentService.handle_qr_payment(payload)

    assert result["status"] == "refunded_stale"
    mock_razorpay.refund_payment.assert_called_once()
    assert mock_razorpay.refund_payment.call_args.kwargs["speed"] == "optimum"


@pytest.mark.asyncio
async def test_charger_not_connected_full_refund_passes_speed_optimum(
    client, qr_charger, qr_code, monkeypatch
):
    """Trigger 4 of 6: charger not connected at payment time → full refund
    via `_full_refund` with speed=optimum.
    """
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")
    payload = _webhook_payload("pay_NOCONN001", "qr_TEST123", 10000)

    mock_razorpay = MagicMock()
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.refund_payment.return_value = {"id": "rfnd_NOCONN"}
    mock_razorpay.fetch_payment_fees.return_value = None

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay), \
         patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.is_charger_connected = AsyncMock(return_value=False)
        await QRPaymentService.handle_qr_payment(payload)

    mock_razorpay.refund_payment.assert_called_once()
    assert mock_razorpay.refund_payment.call_args.kwargs["speed"] == "optimum"


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
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
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
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
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
# Synthetic platform fee helpers (ADR 0001)
# ============================================================================

def test_synthetic_platform_fee_is_2_percent_of_amount_paid():
    """Synthetic fee = amount_paid × 2%, quantized to 2dp."""
    assert synthetic_platform_fee(Decimal("500.00")) == Decimal("10.00")
    assert synthetic_platform_fee(Decimal("100.00")) == Decimal("2.00")
    assert synthetic_platform_fee(Decimal("250.00")) == Decimal("5.00")
    # Odd amount that rounds
    assert synthetic_platform_fee(Decimal("99.99")) == Decimal("2.00")


def test_synthetic_fee_split_is_all_in_commission_plus_gst():
    """Synthetic fee is all-in: commission = total/1.18, GST = total − commission."""
    commission, gst = synthetic_fee_split(Decimal("500.00"))
    # 500 × 0.02 = 10.00 total → commission = 10/1.18 = 8.47, GST = 1.53
    assert commission == Decimal("8.47")
    assert gst == Decimal("1.53")
    assert commission + gst == synthetic_platform_fee(Decimal("500.00"))


def test_synthetic_fee_split_components_sum_to_total():
    """For a range of payment amounts the (commission, GST) pair must sum to total."""
    for amount in [Decimal("50"), Decimal("100"), Decimal("237.50"), Decimal("1000")]:
        total = synthetic_platform_fee(amount)
        commission, gst = synthetic_fee_split(amount)
        assert commission + gst == total, f"Mismatch at amount={amount}"


# ============================================================================
# _ensure_actual_fee_captured (writes Razorpay's real fee to the row)
# ============================================================================

@pytest.mark.asyncio
async def test_ensure_actual_fee_skips_when_webhook_value_already_stored(
    client, qr_charger, qr_code
):
    """If fee_source='webhook' and platform_fee set, do NOT call the Razorpay API."""
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
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await _ensure_actual_fee_captured(qr_payment)

    mock_razorpay.fetch_payment_fees.assert_not_called()
    assert qr_payment.platform_fee == Decimal("0.00")  # unchanged


@pytest.mark.asyncio
async def test_ensure_actual_fee_fetches_from_api_when_unset(client, qr_charger, qr_code):
    """When no stored fee, fetch from Razorpay API and write to row."""
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
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    # Razorpay actually charged ₹2.36 here (a real 2.36% rate, NOT 2%) — must
    # land on the row verbatim, not get coerced to the synthetic value.
    mock_razorpay.fetch_payment_fees.return_value = (Decimal("2.36"), Decimal("0.36"))

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await _ensure_actual_fee_captured(qr_payment)

    assert qr_payment.platform_fee == Decimal("2.36")
    assert qr_payment.razorpay_commission == Decimal("2.00")
    assert qr_payment.razorpay_gst == Decimal("0.36")
    assert qr_payment.fee_source == "api"


@pytest.mark.asyncio
async def test_ensure_actual_fee_falls_back_to_synthetic_when_api_silent(
    client, qr_charger, qr_code
):
    """When webhook + API both unavailable, fall back to the synthetic 2% split."""
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
    # Razorpay methods migrated to httpx.AsyncClient — mock as AsyncMock.
    mock_razorpay.refund_payment = AsyncMock()
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock()
    mock_razorpay.fetch_order = AsyncMock()
    mock_razorpay.create_transfer = AsyncMock()
    mock_razorpay.fetch_payment_fees.return_value = None

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await _ensure_actual_fee_captured(qr_payment)

    assert qr_payment.platform_fee == Decimal("2.00")
    assert qr_payment.fee_source == "estimated"
    # 2.00 all-in → commission = 2/1.18 ≈ 1.69, GST = 0.31
    assert qr_payment.razorpay_commission == Decimal("1.69")
    assert qr_payment.razorpay_gst == Decimal("0.31")
    assert qr_payment.razorpay_commission + qr_payment.razorpay_gst == qr_payment.platform_fee


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

    Synthetic fee (ADR 0001): amount_paid=20 → fee=20×2%=₹0.40 →
    budget_incl_tax=19.60 → budget_excl_tax=19.60/1.18=16.61. Driving 5.0 kWh
    at ₹15/kWh would cost ₹75 uncapped, so this firmly tests the cap.
    The fixture's actual platform_fee=0.24 is ignored — billing math uses
    synthetic.
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

    expected_billable_excl_tax = Decimal("16.61")  # (20 - 0.40) / 1.18 rounded
    expected_gst = (expected_billable_excl_tax * Decimal("18") / Decimal("100")).quantize(Decimal("0.01"))

    assert qr_payment.energy_cost == expected_billable_excl_tax
    assert qr_payment.gst_amount == expected_gst
    assert qr_payment.refund_amount is None or qr_payment.refund_amount == Decimal("0")
    assert txn.energy_charge == expected_billable_excl_tax
    assert txn.gst_amount == expected_gst
    # Authoritative meter reading on the transaction is untouched.
    assert txn.energy_consumed_kwh == 5.0
    # Actual platform_fee on the row remains the fixture's webhook value (0.24).
    assert qr_payment.platform_fee == Decimal("0.24")
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
            mock_rzp.refund_payment = AsyncMock()
            mock_rzp.find_refund_for_payment = AsyncMock()
            mock_rzp.fetch_payment = AsyncMock()
            mock_rzp.fetch_payment_fees = AsyncMock()
            mock_rzp.fetch_order = AsyncMock()
            mock_rzp.create_transfer = AsyncMock()
            mock_rzp.refund_payment.return_value = {"id": "rfnd_test_001"}
            await QRPaymentService.process_qr_session_billing(txn.id)

    await qr_payment.refresh_from_db()
    await txn.refresh_from_db()

    assert qr_payment.energy_cost == Decimal("7.50")
    assert qr_payment.gst_amount == Decimal("1.35")
    # Refund = 20 - synthetic_fee(0.40) - 7.50 - 1.35 = 10.75 (ADR 0001).
    # Every customer sees the same 2% deduction regardless of what Razorpay
    # actually charged on this payment (₹0.24 = 1.2% in this fixture). The
    # ₹0.16 delta vs. actual is platform P&L variance.
    assert qr_payment.refund_amount == Decimal("10.75")
    assert txn.energy_charge == Decimal("7.50")


@pytest.mark.asyncio
async def test_qr_billing_tiny_positive_balance_is_refunded(client, qr_charger, qr_code, qr_tariff):
    """Even sub-rupee positive balances are refunded — the historical
    MINIMUM_REFUND_AMOUNT threshold has been removed.

    Synthetic fee (ADR 0001): amount_paid=20 → fee=₹0.40 → budget=₹19.60.
    Driving 1.106 kWh × ₹15 = ₹16.59 + GST ₹2.99 = ₹19.58 leaves a ₹0.02
    positive balance — well below the old ₹1 threshold. The session must
    still issue a Razorpay refund.
    """
    _, txn, qr_payment = await _make_qr_billing_fixture(
        qr_charger, qr_code, qr_tariff, energy_consumed_kwh=1.106,
    )

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        with patch("services.qr_payment_service.razorpay_service") as mock_rzp:
            mock_rzp.refund_payment = AsyncMock()
            mock_rzp.find_refund_for_payment = AsyncMock()
            mock_rzp.fetch_payment = AsyncMock()
            mock_rzp.fetch_payment_fees = AsyncMock()
            mock_rzp.fetch_order = AsyncMock()
            mock_rzp.create_transfer = AsyncMock()
            mock_rzp.refund_payment.return_value = {"id": "rfnd_tiny_001"}
            await QRPaymentService.process_qr_session_billing(txn.id)

    await qr_payment.refresh_from_db()

    assert qr_payment.refund_amount is not None
    assert qr_payment.refund_amount > Decimal("0")
    assert qr_payment.refund_amount < Decimal("1.00")
    assert qr_payment.status == QRPaymentStatusEnum.REFUNDED
    assert qr_payment.razorpay_refund_id == "rfnd_tiny_001"
    mock_rzp.refund_payment.assert_called_once()
    call_kwargs = mock_rzp.refund_payment.call_args.kwargs
    assert call_kwargs["amount"] == qr_payment.refund_amount


# ============================================================================
# Synthetic-vs-actual end-to-end (ADR 0001 acceptance test)
# ============================================================================

@pytest.mark.asyncio
async def test_synthetic_drives_billing_and_invoice_while_actual_lands_on_row(
    client, qr_charger, qr_code, monkeypatch
):
    """End-to-end: a QR session where Razorpay actually charged 1.5% on a
    ₹500 payment, but the synthetic 2% drives budget + invoice gateway lines.

    Asserts:
      - QRPayment.platform_fee preserved as ₹7.50 (the actual 1.5% Razorpay fee)
      - Invoice gateway_charges = ₹8.47 (synthetic 2% commission split)
      - Invoice gateway_gst = ₹1.53 (synthetic 2% GST split)
      - Budget cap consistent with synthetic, NOT actual
    """
    import uuid
    from services import invoice_service as _svc
    from services.invoice_service import InvoiceService
    from models import GSTInvoice

    # Invoice generation requires VOLTLYNC_GSTIN; provide one for this test.
    monkeypatch.setattr(_svc, "VOLTLYNC_GSTIN", "32ABCDE1234F1Z5")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE_CODE", "32")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE", "Kerala")

    # Tariff at ₹20/kWh excl-tax
    await Tariff.create(
        charger=qr_charger,
        rate_per_kwh=Decimal("20.00"),
        tariff_per_kwh_all_in=Decimal("23.6000"),  # 20 × 1.18
        gst_percent=Decimal("18.00"),
        hsn_sac_code="996749",
        is_global=False,
    )
    user = await User.create(
        email=f"e2e_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
        rfid_card_id=f"RFID_{uuid.uuid4().hex[:12]}",
    )
    # Drive 10 kWh — well under budget. amount_paid=500, synthetic fee=₹10,
    # budget_incl_tax=₹490, budget_excl_tax=₹490/1.18=₹415.25, kWh_cap=20.76.
    txn = await Transaction.create(
        user=user, charger=qr_charger,
        energy_consumed_kwh=10.0,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    qr_payment = await QRPayment.create(
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:10]}",
        razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        transaction=txn,
        customer_vpa="end2end@oksbi",
        amount_paid=Decimal("500.00"),
        # Razorpay actually charged 1.5% (₹7.50). Source = webhook so
        # _ensure_actual_fee_captured leaves these alone.
        platform_fee=Decimal("7.50"),
        razorpay_commission=Decimal("6.36"),
        razorpay_gst=Decimal("1.14"),
        fee_source="webhook",
        status=QRPaymentStatusEnum.CHARGING,
    )

    mock_rzp = MagicMock()
    mock_rzp.refund_payment = AsyncMock()
    mock_rzp.find_refund_for_payment = AsyncMock()
    mock_rzp.fetch_payment = AsyncMock()
    mock_rzp.fetch_payment_fees = AsyncMock()
    mock_rzp.fetch_order = AsyncMock()
    mock_rzp.create_transfer = AsyncMock()
    mock_rzp.refund_payment.return_value = {"id": "rfnd_e2e"}

    with patch("services.qr_payment_service.redis_manager") as mock_redis, \
         patch("services.qr_payment_service.razorpay_service", mock_rzp):
        mock_redis.delete_qr_session = AsyncMock()
        await QRPaymentService.process_qr_session_billing(txn.id)

    await qr_payment.refresh_from_db()
    await txn.refresh_from_db()

    # Actual Razorpay fee preserved on the QRPayment row (truth column)
    assert qr_payment.platform_fee == Decimal("7.50")
    assert qr_payment.razorpay_commission == Decimal("6.36")
    assert qr_payment.razorpay_gst == Decimal("1.14")
    assert qr_payment.fee_source == "webhook"

    # Billing math used synthetic 2% (₹10), not actual ₹7.50.
    # energy_cost = 10 × 20 = ₹200, gst = 36, total energy_incl_tax = ₹236.
    # refund = 500 - 200 - 36 - 10(synthetic) = ₹254 (NOT 500-200-36-7.50=256.50)
    assert qr_payment.energy_cost == Decimal("200.00")
    assert qr_payment.gst_amount == Decimal("36.00")
    assert qr_payment.refund_amount == Decimal("254.00")

    # Invoice generation snapshots synthetic split on gateway lines.
    invoice = await InvoiceService.generate_invoice(txn.id)
    assert invoice is not None
    # Synthetic split of ₹500: total=₹10.00, commission=₹8.47, GST=₹1.53.
    assert invoice.gateway_charges == Decimal("8.47")
    assert invoice.gateway_gst == Decimal("1.53")
    # Total taxable = energy(₹200) + gateway_commission(₹8.47) = ₹208.47
    assert invoice.total_taxable_value == Decimal("208.47")
    # Total tax = energy_gst(₹36) + gateway_gst(₹1.53) = ₹37.53
    assert invoice.total_tax == Decimal("37.53")
    # The QRPayment row's actual razorpay_commission/_gst stay distinct from
    # the invoice's snapshotted synthetic values.
    assert qr_payment.razorpay_commission != invoice.gateway_charges
    assert qr_payment.razorpay_gst != invoice.gateway_gst


# ============================================================================
# Refund idempotency key + request-body determinism
# (cross-environment HTTP 409 collision fix)
# ============================================================================
#
# Root cause: the refund idempotency key was f"qr_payment_{qr_payment.id}" — a
# per-database PK. Staging and prod share ONE Razorpay LIVE account, so both
# envs eventually refund the same integer id with different bodies and Razorpay
# returns HTTP 409 "Different request with the same idempotency key has already
# been processed." The fix keys off the globally-unique razorpay_payment_id and
# makes the original + retry paths send a byte-identical body so a same-key
# call replays the original refund instead of 409ing.

from services.qr_payment_service import build_refund_call_kwargs
from services.billing_retry_service import BillingRetryService


@pytest.fixture
async def _refund_failed_qr_payment(qr_charger, qr_code):
    """A QR payment stuck in REFUND_FAILED with a 409 reason and a stored
    refund_amount — mirrors the staging rows the retry sweep must clear."""
    import uuid
    user = await User.create(
        email=f"rf_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    return await QRPayment.create(
        charger=qr_charger,
        charger_qr_code=qr_code,
        user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("150.00"),
        refund_amount=Decimal("60.81"),
        status=QRPaymentStatusEnum.REFUND_FAILED,
        failure_reason=(
            "HTTP 409: Different request with the same idempotency key "
            "has already been processed."
        ),
    )


def _make_payment(payment_id: str, qr_id: int, amount_paid: str):
    """Lightweight stand-in for a QRPayment row — build_refund_call_kwargs
    only reads .id, .razorpay_payment_id, and .amount_paid."""
    return MagicMock(
        id=qr_id,
        razorpay_payment_id=payment_id,
        amount_paid=Decimal(amount_paid),
    )


def test_refund_key_derives_from_razorpay_payment_id_not_pk(monkeypatch):
    """The idempotency key is keyed on the globally-unique razorpay_payment_id,
    never the per-database PK (which collides across the shared live account)."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")
    p = _make_payment("pay_GLOBALLYUNIQUE", qr_id=235, amount_paid="150.00")

    kwargs = build_refund_call_kwargs(p, Decimal("7.88"))

    assert kwargs["idempotency_key"] == "refund_pay_GLOBALLYUNIQUE"
    # The local PK must NOT appear in the key — that was the collision source.
    assert "235" not in kwargs["idempotency_key"]
    assert "qr_payment_235" != kwargs["idempotency_key"]


def test_refund_key_distinct_across_payments_same_pk(monkeypatch):
    """Two payments sharing the same integer PK (the staging-vs-prod scenario)
    but different razorpay_payment_id get distinct, non-colliding keys."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")
    staging = _make_payment("pay_STAGING235", qr_id=235, amount_paid="150.00")
    prod = _make_payment("pay_PROD235", qr_id=235, amount_paid="120.00")

    k_staging = build_refund_call_kwargs(staging, Decimal("7.88"))["idempotency_key"]
    k_prod = build_refund_call_kwargs(prod, Decimal("33.65"))["idempotency_key"]

    assert k_staging != k_prod


def test_refund_notes_are_deterministic_and_minimal(monkeypatch):
    """Notes carry only the qr_payment_id — no transaction reason, no "Retry:"
    prefix — so the original and retry bodies are byte-identical."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")
    p = _make_payment("pay_NOTES", qr_id=42, amount_paid="100.00")

    notes = build_refund_call_kwargs(p, Decimal("10.00"))["notes"]

    assert notes == {"qr_payment_id": "42"}


@pytest.mark.parametrize(
    "flag,refund,amount_paid,expected_speed",
    [
        ("true", "150.00", "150.00", "optimum"),   # full refund, flag on
        ("true", "60.81", "150.00", None),          # partial refund, flag on
        ("false", "150.00", "150.00", None),        # full refund, flag off (kill-switch)
    ],
)
def test_refund_speed_is_deterministic_from_amount_and_flag(
    monkeypatch, flag, refund, amount_paid, expected_speed
):
    """Speed is a pure function of (refund==amount_paid) and the kill-switch,
    so the retry path reproduces the original speed without extra state."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", flag)
    p = _make_payment("pay_SPEED", qr_id=1, amount_paid=amount_paid)

    assert build_refund_call_kwargs(p, Decimal(refund))["speed"] == expected_speed


def test_original_and_retry_produce_identical_request_for_same_payment(monkeypatch):
    """Same payment + same stored refund_amount → identical key, notes, amount,
    and speed across the original path and the retry path. This is what lets a
    same-key call replay (HTTP 200) instead of 409ing."""
    monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")
    p = _make_payment("pay_PARITY", qr_id=236, amount_paid="200.00")

    original = build_refund_call_kwargs(p, Decimal("144.22"))
    retry = build_refund_call_kwargs(p, p.amount_paid - Decimal("55.78"))

    assert original == retry


@pytest.mark.asyncio
async def test_retry_sweep_uses_globally_unique_key_and_clears_409_row(
    client, _refund_failed_qr_payment
):
    """End-to-end: BillingRetryService retries a 409-stuck row with the NEW
    razorpay_payment_id-based key (not the colliding qr_payment_{id} key) and,
    on success, marks it REFUNDED."""
    payment = _refund_failed_qr_payment

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment = AsyncMock(return_value={"id": "rfnd_RETRY_OK"})

    with patch("services.billing_retry_service.razorpay_service", mock_razorpay):
        await BillingRetryService()._process_failed_qr_refunds()

    mock_razorpay.refund_payment.assert_called_once()
    call = mock_razorpay.refund_payment.call_args
    # First positional arg is the payment id; the body kwargs carry the fix.
    assert call.args[0] == payment.razorpay_payment_id
    assert call.kwargs["idempotency_key"] == f"refund_{payment.razorpay_payment_id}"
    assert call.kwargs["notes"] == {"qr_payment_id": str(payment.id)}
    assert call.kwargs["amount"] == Decimal("60.81")

    await payment.refresh_from_db()
    assert payment.status == QRPaymentStatusEnum.REFUNDED
    assert payment.razorpay_refund_id == "rfnd_RETRY_OK"
    assert payment.failure_reason is None


# ============================================================================
# HTTP 409 idempotency-conflict handling (reconcile or mark non-retryable)
# ============================================================================

from services.qr_payment_service import IDEMPOTENCY_CONFLICT_NO_REFUND
from services.razorpay_service import (
    RazorpayIdempotencyConflictError,
    razorpay_service as _real_razorpay_service,
)

_CONFLICT_MSG = (
    "Different request with the same idempotency key has already been processed."
)


def _conflict_error(payment_id: str) -> RazorpayIdempotencyConflictError:
    return RazorpayIdempotencyConflictError(payment_id, Exception(_CONFLICT_MSG))


@pytest.mark.asyncio
async def test_full_refund_409_reconciles_to_existing_refund(client, qr_charger, qr_code):
    """A 409 means the key was already used; if a refund exists at Razorpay we
    persist it and mark REFUNDED rather than failing."""
    import uuid
    user = await User.create(
        email=f"c1_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    qr_payment = await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=payment_id, razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"), status=QRPaymentStatusEnum.PAID,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment = AsyncMock(side_effect=_conflict_error(payment_id))
    mock_razorpay.find_refund_for_payment = AsyncMock(
        return_value={"id": "rfnd_EXISTING", "speed_processed": "normal"}
    )
    mock_razorpay.fetch_payment_fees = AsyncMock(return_value=None)

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(qr_payment, "Conflict reconcile")

    await qr_payment.refresh_from_db()
    assert qr_payment.razorpay_refund_id == "rfnd_EXISTING"
    assert qr_payment.status == QRPaymentStatusEnum.REFUNDED


@pytest.mark.asyncio
async def test_full_refund_409_no_refund_marks_non_retryable(client, qr_charger, qr_code):
    """A 409 with no existing refund (the cross-env collision case) is terminal:
    REFUND_FAILED with the canonical non-retryable marker."""
    import uuid
    user = await User.create(
        email=f"c2_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    qr_payment = await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=payment_id, razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"), status=QRPaymentStatusEnum.PAID,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment = AsyncMock(side_effect=_conflict_error(payment_id))
    mock_razorpay.find_refund_for_payment = AsyncMock(return_value=None)
    mock_razorpay.fetch_payment_fees = AsyncMock(return_value=None)

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(qr_payment, "Conflict no-refund")

    await qr_payment.refresh_from_db()
    assert qr_payment.status == QRPaymentStatusEnum.REFUND_FAILED
    assert qr_payment.failure_reason == IDEMPOTENCY_CONFLICT_NO_REFUND
    assert qr_payment.razorpay_refund_id is None


@pytest.mark.asyncio
async def test_partial_refund_409_no_refund_marks_non_retryable(
    client, qr_charger, qr_code, qr_tariff
):
    """The unused-credit (partial) refund path also classifies a 409 as
    terminal-non-retryable when no refund exists."""
    _, txn, qr_payment = await _make_qr_billing_fixture(
        qr_charger, qr_code, qr_tariff, energy_consumed_kwh=0.5,
    )

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        with patch("services.qr_payment_service.razorpay_service") as mock_rzp:
            mock_rzp.refund_payment = AsyncMock(
                side_effect=_conflict_error(qr_payment.razorpay_payment_id)
            )
            mock_rzp.find_refund_for_payment = AsyncMock(return_value=None)
            mock_rzp.fetch_payment_fees = AsyncMock(return_value=None)
            await QRPaymentService.process_qr_session_billing(txn.id)

    await qr_payment.refresh_from_db()
    assert qr_payment.status == QRPaymentStatusEnum.REFUND_FAILED
    assert qr_payment.failure_reason == IDEMPOTENCY_CONFLICT_NO_REFUND


@pytest.mark.asyncio
async def test_partial_refund_409_reconciles_to_existing_refund(
    client, qr_charger, qr_code, qr_tariff
):
    """The partial path reconciles a 409 to an existing refund → REFUNDED."""
    _, txn, qr_payment = await _make_qr_billing_fixture(
        qr_charger, qr_code, qr_tariff, energy_consumed_kwh=0.5,
    )

    with patch("services.qr_payment_service.redis_manager") as mock_redis:
        mock_redis.delete_qr_session = AsyncMock()
        with patch("services.qr_payment_service.razorpay_service") as mock_rzp:
            mock_rzp.refund_payment = AsyncMock(
                side_effect=_conflict_error(qr_payment.razorpay_payment_id)
            )
            mock_rzp.find_refund_for_payment = AsyncMock(
                return_value={"id": "rfnd_PARTIAL_EXIST", "speed_processed": "normal"}
            )
            mock_rzp.fetch_payment_fees = AsyncMock(return_value=None)
            await QRPaymentService.process_qr_session_billing(txn.id)

    await qr_payment.refresh_from_db()
    assert qr_payment.status == QRPaymentStatusEnum.REFUNDED
    assert qr_payment.razorpay_refund_id == "rfnd_PARTIAL_EXIST"


@pytest.mark.asyncio
async def test_retry_sweep_excludes_non_retryable_conflict_rows(
    client, qr_charger, qr_code
):
    """A row marked IDEMPOTENCY_CONFLICT_NO_REFUND is never picked up by the
    retry sweep (no Razorpay call is made for it)."""
    import uuid
    user = await User.create(
        email=f"c3_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"), refund_amount=Decimal("40.00"),
        status=QRPaymentStatusEnum.REFUND_FAILED,
        failure_reason=IDEMPOTENCY_CONFLICT_NO_REFUND,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment = AsyncMock()

    with patch("services.billing_retry_service.razorpay_service", mock_razorpay):
        await BillingRetryService()._process_failed_qr_refunds()

    mock_razorpay.refund_payment.assert_not_called()


@pytest.mark.asyncio
async def test_retry_sweep_409_marks_row_non_retryable(client, qr_charger, qr_code):
    """If a retry itself hits a 409 with no existing refund, the row is marked
    non-retryable so the next sweep excludes it (stops the infinite loop)."""
    import uuid
    user = await User.create(
        email=f"c4_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    payment = await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=payment_id, razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("150.00"), refund_amount=Decimal("60.81"),
        status=QRPaymentStatusEnum.REFUND_FAILED,
        failure_reason="HTTP 409: " + _CONFLICT_MSG,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment = AsyncMock(side_effect=_conflict_error(payment_id))
    mock_razorpay.find_refund_for_payment = AsyncMock(return_value=None)

    with patch("services.billing_retry_service.razorpay_service", mock_razorpay):
        await BillingRetryService()._process_failed_qr_refunds()

    await payment.refresh_from_db()
    assert payment.status == QRPaymentStatusEnum.REFUND_FAILED
    assert payment.failure_reason == IDEMPOTENCY_CONFLICT_NO_REFUND


@pytest.mark.asyncio
async def test_refund_payment_maps_http_409_to_idempotency_conflict_error(monkeypatch):
    """razorpay_service.refund_payment maps a Razorpay HTTP 409 response to the
    dedicated RazorpayIdempotencyConflictError, not a generic Exception."""
    monkeypatch.setattr(_real_razorpay_service, "client", MagicMock())
    monkeypatch.setattr(_real_razorpay_service, "api_key", "rzp_test_key")
    monkeypatch.setattr(_real_razorpay_service, "api_secret", "test_secret")

    resp = MagicMock()
    resp.is_error = True
    resp.status_code = 409
    resp.json.return_value = {"error": {"description": _CONFLICT_MSG}}

    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=fake_client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("services.razorpay_service.httpx.AsyncClient", return_value=ctx):
        with pytest.raises(RazorpayIdempotencyConflictError):
            await _real_razorpay_service.refund_payment(
                "pay_CONFLICT", amount=Decimal("10.00"),
                idempotency_key="refund_pay_CONFLICT",
            )


# ============================================================================
# Retry exclusion robustness for below-minimum failures (canonical + legacy)
# ============================================================================

from services.qr_payment_service import (
    is_retryable_refund_failure, BELOW_MINIMUM_REASON,
)

_LEGACY_BELOW_MIN = (
    "Refund for pay_SpuaKiPYNEFPL6 below Razorpay minimum (₹1.00): "
    "The amount must be atleast INR 1.00"
)


@pytest.mark.parametrize(
    "reason,retryable",
    [
        (None, True),
        ("", True),
        ("Connection timeout", True),
        ("HTTP 500: Internal Server Error", True),
        (BELOW_MINIMUM_REASON, False),
        (_LEGACY_BELOW_MIN, False),
        ("refund for pay_x BELOW razorpay MINIMUM (₹1.00)", False),  # case-insensitive
        (IDEMPOTENCY_CONFLICT_NO_REFUND, False),
    ],
)
def test_is_retryable_refund_failure_predicate(reason, retryable):
    """Robust, substring-based classification — not an exact-string match on a
    single marker — so canonical AND legacy long-form below-minimum reasons
    (and the conflict marker) are all treated as terminal."""
    assert is_retryable_refund_failure(reason) is retryable


@pytest.mark.asyncio
async def test_retry_sweep_excludes_legacy_long_form_below_minimum(
    client, qr_charger, qr_code
):
    """Regression for staging row #46: a below-minimum row carrying the legacy
    long-form message (not the canonical marker) must NOT be retried."""
    import uuid
    user = await User.create(
        email=f"lm_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("40.00"), refund_amount=Decimal("0.23"),
        status=QRPaymentStatusEnum.REFUND_FAILED,
        failure_reason=_LEGACY_BELOW_MIN,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment = AsyncMock()

    with patch("services.billing_retry_service.razorpay_service", mock_razorpay):
        await BillingRetryService()._process_failed_qr_refunds()

    mock_razorpay.refund_payment.assert_not_called()


@pytest.mark.asyncio
async def test_retry_sweep_still_retries_transient_failures(client, qr_charger, qr_code):
    """A genuinely transient failure (e.g. insufficient balance) is still
    retried — the predicate only excludes permanently-stuck reasons."""
    import uuid
    user = await User.create(
        email=f"tr_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    payment = await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("100.00"), refund_amount=Decimal("40.00"),
        status=QRPaymentStatusEnum.REFUND_FAILED,
        failure_reason="HTTP 500: insufficient balance",
    )

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment = AsyncMock(return_value={"id": "rfnd_RECOVERED"})

    with patch("services.billing_retry_service.razorpay_service", mock_razorpay):
        await BillingRetryService()._process_failed_qr_refunds()

    mock_razorpay.refund_payment.assert_called_once()
    await payment.refresh_from_db()
    assert payment.status == QRPaymentStatusEnum.REFUNDED
    assert payment.razorpay_refund_id == "rfnd_RECOVERED"


@pytest.mark.asyncio
async def test_full_refund_below_minimum_sets_canonical_marker(client, qr_charger, qr_code):
    """A sub-₹1 full refund tags the canonical marker (not the long-form text),
    so the row is consistently classified non-retryable."""
    import uuid
    user = await User.create(
        email=f"fbm_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    qr_payment = await QRPayment.create(
        charger=qr_charger, charger_qr_code=qr_code, user=user,
        razorpay_payment_id=payment_id, razorpay_qr_code_id="qr_TEST123",
        amount_paid=Decimal("0.50"), status=QRPaymentStatusEnum.PAID,
    )

    mock_razorpay = MagicMock()
    mock_razorpay.refund_payment = AsyncMock(
        side_effect=RazorpayRefundBelowMinimumError(
            payment_id, Exception("The amount must be atleast INR 1.00")
        )
    )
    mock_razorpay.find_refund_for_payment = AsyncMock()
    mock_razorpay.fetch_payment_fees = AsyncMock(return_value=None)

    with patch("services.qr_payment_service.razorpay_service", mock_razorpay):
        await QRPaymentService._full_refund(qr_payment, "Sub-rupee full refund")

    await qr_payment.refresh_from_db()
    assert qr_payment.status == QRPaymentStatusEnum.REFUND_FAILED
    assert qr_payment.failure_reason == BELOW_MINIMUM_REASON


# ============================================================================
# Below-minimum classification (benign sub-₹1 forfeit, not a failure)
# ============================================================================

from services.qr_payment_service import is_below_minimum_reason


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("below_razorpay_minimum", True),
        ("BELOW_RAZORPAY_MINIMUM", True),
        (_LEGACY_BELOW_MIN, True),
        ("refund for pay_x BELOW razorpay MINIMUM (₹1.00)", True),
        (None, False),
        ("", False),
        ("HTTP 500: insufficient balance", False),
        (IDEMPOTENCY_CONFLICT_NO_REFUND, False),
    ],
)
def test_is_below_minimum_reason(reason, expected):
    assert is_below_minimum_reason(reason) is expected
