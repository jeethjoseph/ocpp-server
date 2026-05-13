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
    # 20% commission on 410 = 82. TDS base is post-commission earning:
    # franchisee_earning = 410 - 82 = 328. TDS@10% = 32.80, payout = 295.20.
    assert result["platform_commission"] == Decimal("82.00")
    assert result["tds_amount"] == Decimal("32.80")
    assert result["franchisee_payout"] == Decimal("295.20")


def test_calculate_settlement_tds_on_post_commission_base():
    """TDS must be withheld from franchisee earning (net_excl_gst -
    platform_commission), not from the pre-commission net. Regression
    guard: switching the base back would over-deduct from the franchisee."""
    result = FranchiseeSettlementService.calculate_settlement(
        gross_amount=Decimal("100.00"),
        refund_amount=Decimal("25.00"),
        pg_fee_amount=Decimal("2.00"),
        gst_collected=Decimal("11.14"),
        commission_pct=Decimal("20.00"),
        tds_pct=Decimal("10.00"),
    )
    # net_excl_gst = 100 - 25 - 2 - 11.14 = 61.86
    # commission@20% = 12.37, earning = 49.49, tds@10% = 4.95, payout = 44.54
    assert result["net_excl_gst"] == Decimal("61.86")
    assert result["platform_commission"] == Decimal("12.37")
    assert result["tds_amount"] == Decimal("4.95")
    assert result["franchisee_payout"] == Decimal("44.54")
    # Components-sum invariant must still hold.
    components_sum = (
        result["franchisee_payout"]
        + result["platform_commission"]
        + result["tds_amount"]
        + result["gst_collected"]
        + Decimal("2.00")   # pg_fee_amount
        + Decimal("25.00")  # refund_amount
    )
    assert abs(components_sum - Decimal("100.00")) <= Decimal("0.02")


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


def _mock_httpx_response(json_body, status_code=200):
    """Build a MagicMock that mimics httpx.Response for AsyncClient.post."""
    resp = MagicMock()
    resp.json.return_value = json_body
    resp.status_code = status_code
    resp.is_error = status_code >= 400
    resp.text = str(json_body)
    return resp


def _patch_httpx_client(response):
    """Patch ``httpx.AsyncClient`` so the ``async with`` context yields a
    client whose ``.post`` is an AsyncMock returning ``response``.

    Returns ``(patch_context, mock_client)`` so the test can both enter
    the patch and assert on ``mock_client.post`` afterwards.
    """
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=response)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return patch(
        "services.razorpay_service.httpx.AsyncClient",
        return_value=mock_cm,
    ), mock_client


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

    httpx_patch, mock_client = _patch_httpx_client(
        _mock_httpx_response(response_body)
    )
    with httpx_patch, patch("models.RazorpayApiLog", fake_log_cls, create=True):
        result = await svc.create_payment_transfer(
            payment_id="pay_abc",
            account_id="acc_def",
            amount_paise=583,
            notes={"transaction_id": "90"},
            franchisee_id=2,
        )

    assert result["id"] == "trf_xyz"
    mock_client.post.assert_called_once()
    call = mock_client.post.call_args
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

    httpx_patch, _ = _patch_httpx_client(_mock_httpx_response(response_body))
    with httpx_patch, patch("models.RazorpayApiLog", fake_log_cls, create=True):
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

    httpx_patch, _ = _patch_httpx_client(
        _mock_httpx_response(error_body, status_code=400)
    )
    with httpx_patch, patch("models.RazorpayApiLog", fake_log_cls, create=True):
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
