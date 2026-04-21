"""Unit tests for FranchiseeSettlementService.calculate_settlement
and the Razorpay idempotency header pass-through.

Pure-logic tests — no DB, no network. The SDK mock asserts the exact
headers Razorpay sees for transfer.create / payment.refund calls.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from services.franchisee_settlement_service import FranchiseeSettlementService


def test_calculate_settlement_does_not_deduct_transfer_fee():
    """transfer_fee must be 0 at calc time and franchisee_payout must
    equal net_excl_gst - platform_commission - tds_amount (no hidden
    platform-side transfer fee deduction)."""
    result = FranchiseeSettlementService.calculate_settlement(
        gross_amount=Decimal("1000.00"),
        refund_amount=Decimal("0.00"),
        pg_fee_amount=Decimal("0.00"),
        gst_collected=Decimal("152.54"),
        commission_pct=Decimal("20.00"),
        tds_pct=Decimal("10.00"),
    )

    assert result["transfer_fee"] == Decimal("0.00")
    expected_payout = (
        result["net_excl_gst"]
        - result["platform_commission"]
        - result["tds_amount"]
    )
    assert result["franchisee_payout"] == expected_payout


def test_calculate_settlement_subtracts_refund_and_pg_fee():
    """Basic sanity: refund + pg_fee reduce net, and GST is excluded from payout basis."""
    result = FranchiseeSettlementService.calculate_settlement(
        gross_amount=Decimal("500.00"),
        refund_amount=Decimal("50.00"),
        pg_fee_amount=Decimal("10.00"),
        gst_collected=Decimal("30.00"),
        commission_pct=Decimal("20.00"),
        tds_pct=Decimal("10.00"),
    )
    assert result["net_amount"] == Decimal("440.00")
    assert result["net_excl_gst"] == Decimal("410.00")
    # 20% commission on 410 = 82, 10% TDS = 41, payout = 287
    assert result["platform_commission"] == Decimal("82.00")
    assert result["tds_amount"] == Decimal("41.00")
    assert result["franchisee_payout"] == Decimal("287.00")


def test_create_transfer_passes_idempotency_header():
    """Regression test for the bug where X-Transfer-Idempotency was
    built but dropped before the SDK call."""
    from services.razorpay_service import RazorpayService

    svc = RazorpayService.__new__(RazorpayService)  # bypass __init__
    svc.client = MagicMock()
    svc.client.transfer.create.return_value = {"id": "trf_test"}

    svc.create_transfer(
        account_id="acc_test",
        amount_paise=12345,
        notes={"x": "y"},
        idempotency_key="idem-abc-123",
    )

    call = svc.client.transfer.create.call_args
    assert call.kwargs["data"]["account"] == "acc_test"
    assert call.kwargs["data"]["amount"] == 12345
    assert call.kwargs["headers"] == {"X-Transfer-Idempotency": "idem-abc-123"}


def test_create_transfer_omits_headers_when_no_idempotency_key():
    from services.razorpay_service import RazorpayService

    svc = RazorpayService.__new__(RazorpayService)
    svc.client = MagicMock()
    svc.client.transfer.create.return_value = {"id": "trf_test"}

    svc.create_transfer(
        account_id="acc_test",
        amount_paise=100,
    )
    call = svc.client.transfer.create.call_args
    assert "headers" not in call.kwargs


def test_refund_payment_passes_idempotency_header():
    """Regression: X-Refund-Idempotency must reach Razorpay."""
    from services.razorpay_service import RazorpayService

    svc = RazorpayService.__new__(RazorpayService)
    svc.client = MagicMock()
    svc.client.payment.refund.return_value = {"id": "rfnd_test"}

    svc.refund_payment(
        payment_id="pay_test",
        amount=Decimal("100.00"),
        idempotency_key="qr_payment_42",
    )

    call = svc.client.payment.refund.call_args
    # Positional args: (payment_id, data)
    assert call.args[0] == "pay_test"
    assert call.args[1]["amount"] == 10000  # rupees → paise
    assert call.kwargs["headers"] == {"X-Refund-Idempotency": "qr_payment_42"}
