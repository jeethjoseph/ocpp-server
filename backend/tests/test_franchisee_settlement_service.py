"""Unit tests for FranchiseeSettlementService.calculate_settlement
and the Razorpay idempotency header pass-through.

Pure-logic tests — no DB, no network. The SDK mock asserts the exact
headers Razorpay sees for transfer.create / payment.refund calls.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

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


def _build_razorpay_service():
    """Construct a RazorpayService with credentials but without invoking
    the real client constructor (which validates network connectivity)."""
    from services.razorpay_service import RazorpayService

    svc = RazorpayService.__new__(RazorpayService)
    svc.api_key = "rzp_test_key"
    svc.api_secret = "rzp_test_secret"
    svc.client = MagicMock()  # is_configured() checks client is not None
    return svc


def _mock_requests_post(json_body, status_code=200):
    """Build a MagicMock that mimics requests.Response for requests.post."""
    resp = MagicMock()
    resp.json.return_value = json_body
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.text = str(json_body)
    return resp


@pytest.mark.asyncio
async def test_create_payment_transfer_uses_payment_endpoint():
    """The HTTP request must go to /v1/payments/{id}/transfers with the
    correct body shape and HTTP basic auth credentials."""
    svc = _build_razorpay_service()

    response_body = {
        "entity": "collection",
        "count": 1,
        "items": [{
            "id": "trf_xyz",
            "source": "pay_abc",
            "recipient": "acc_def",
            "amount": 583,
            "currency": "INR",
            "fees": 2,
        }],
    }

    fake_log_cls = MagicMock()
    fake_log_cls.create = AsyncMock()

    with patch(
        "services.razorpay_service.requests.post",
        return_value=_mock_requests_post(response_body),
    ) as mock_post, patch(
        "models.RazorpayApiLog", fake_log_cls, create=True
    ):
        result = await svc.create_payment_transfer(
            payment_id="pay_abc",
            account_id="acc_def",
            amount_paise=583,
            notes={"transaction_id": "90"},
            franchisee_id=2,
        )

    assert result["id"] == "trf_xyz"
    mock_post.assert_called_once()
    call = mock_post.call_args
    assert call.args[0] == "https://api.razorpay.com/v1/payments/pay_abc/transfers"
    assert call.kwargs["json"] == {
        "transfers": [{
            "account": "acc_def",
            "amount": 583,
            "currency": "INR",
            "notes": {"transaction_id": "90"},
        }]
    }
    assert call.kwargs["auth"] == ("rzp_test_key", "rzp_test_secret")


@pytest.mark.asyncio
async def test_create_payment_transfer_writes_audit_log_on_success():
    """Successful 200 response must produce one RazorpayApiLog row with
    success=True and the response body recorded."""
    svc = _build_razorpay_service()

    response_body = {
        "entity": "collection",
        "items": [{"id": "trf_xyz", "amount": 583}],
    }
    captured_log = {}

    async def fake_create(**kw):
        captured_log.update(kw)
        return MagicMock()

    fake_log_cls = MagicMock()
    fake_log_cls.create = AsyncMock(side_effect=fake_create)

    with patch(
        "services.razorpay_service.requests.post",
        return_value=_mock_requests_post(response_body),
    ), patch("models.RazorpayApiLog", fake_log_cls, create=True):
        await svc.create_payment_transfer(
            payment_id="pay_abc",
            account_id="acc_def",
            amount_paise=583,
            franchisee_id=2,
        )

    fake_log_cls.create.assert_awaited_once()
    assert captured_log["method"] == "POST"
    assert captured_log["endpoint"] == "POST /v1/payments/pay_abc/transfers"
    assert captured_log["success"] is True
    assert captured_log["franchisee_id"] == 2
    assert captured_log["razorpay_account_id"] == "acc_def"


@pytest.mark.asyncio
async def test_create_payment_transfer_logs_failure_and_raises():
    """A 400 response must produce an audit row with success=False and
    re-raise so the settlement caller marks the ledger FAILED."""
    import razorpay
    svc = _build_razorpay_service()

    error_body = {
        "error": {
            "code": "BAD_REQUEST_ERROR",
            "description": "The sum of amount requested for transfer is greater than the captured amount",
        }
    }
    captured_log = {}

    async def fake_create(**kw):
        captured_log.update(kw)
        return MagicMock()

    fake_log_cls = MagicMock()
    fake_log_cls.create = AsyncMock(side_effect=fake_create)

    with patch(
        "services.razorpay_service.requests.post",
        return_value=_mock_requests_post(error_body, status_code=400),
    ), patch("models.RazorpayApiLog", fake_log_cls, create=True):
        with pytest.raises(razorpay.errors.BadRequestError):
            await svc.create_payment_transfer(
                payment_id="pay_abc",
                account_id="acc_def",
                amount_paise=999999,
            )

    fake_log_cls.create.assert_awaited_once()
    assert captured_log["success"] is False
    assert captured_log["response_status"] == 400
    assert "captured amount" in (captured_log["error_message"] or "")
