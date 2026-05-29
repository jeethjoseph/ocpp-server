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


# ───────────────────────────────────────────────────────────────────────────
# ADR 0001 amendment (2026-05-29) — settlement ledger uses synthetic pg_fee.
# Tests below guard:
#   • ledger.pg_fee_amount == synthetic 2%, regardless of actual Razorpay fee
#   • ledger.net_excl_gst == invoice.energy_taxable_value (the motivation)
#   • behaviour holds whether actual > synthetic or actual < synthetic
#   • wallet path unchanged (pg_fee stays 0)
# ───────────────────────────────────────────────────────────────────────────


@pytest.fixture
def _voltlync_supplier(monkeypatch):
    """Stub VoltLync GSTIN constants so InvoiceService.generate_invoice can
    proceed in tests that exercise the invoice ↔ ledger agreement."""
    from services import invoice_service as _svc
    monkeypatch.setattr(_svc, "VOLTLYNC_GSTIN", "32ABCDE1234F1Z5")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE_CODE", "32")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE", "Kerala")


async def _build_qr_session(
    franchisee, station, charger, user,
    *,
    amount_paid: Decimal,
    energy_kwh: Decimal,
    energy_cost: Decimal,
    gst_amount: Decimal,
    actual_commission: Decimal,
    actual_gst: Decimal,
    station_state_code: str = "32",
):
    """Inline helper: link station→franchisee and create a completed QR
    txn + payment for one of the assertions below. Keeps each test's body
    focused on the assertion, not the fixture wiring.
    """
    from models import (
        Transaction, TransactionStatusEnum, QRPayment, QRPaymentStatusEnum,
        ChargerQRCode,
    )
    import uuid as _uuid

    station.franchisee = franchisee
    station.state_code = station_state_code
    station.state = "Kerala"
    await station.save()

    qr_code = await ChargerQRCode.create(
        charger=charger,
        razorpay_qr_code_id=f"qr_{_uuid.uuid4().hex[:8]}",
        image_url=f"https://example.test/qr-{_uuid.uuid4().hex[:6]}.png",
    )

    txn = await Transaction.create(
        charger=charger,
        user=user,
        start_meter_kwh=Decimal("0"),
        end_meter_kwh=energy_kwh,
        energy_consumed_kwh=energy_kwh,
        energy_charge=energy_cost,
        gst_amount=gst_amount,
        gst_rate_percent=Decimal("18.00"),
        total_billed=energy_cost + gst_amount,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    await QRPayment.create(
        transaction=txn,
        charger=charger,
        charger_qr_code=qr_code,
        razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
        razorpay_payment_id=f"pay_{_uuid.uuid4().hex[:10]}",
        amount_paid=amount_paid,
        energy_cost=energy_cost,
        gst_amount=gst_amount,
        razorpay_commission=actual_commission,
        razorpay_gst=actual_gst,
        status=QRPaymentStatusEnum.COMPLETED,
    )
    return txn


@pytest.mark.asyncio
async def test_process_settlement_qr_uses_synthetic_pg_fee(
    client, test_franchisee, test_charger, test_user, test_tariff, test_station,
):
    """ADR 0001 amendment regression guard (actual > synthetic case).

    ₹45 QR session where Razorpay actually charged ₹1.09 (~2.42%). The
    ledger must still record the synthetic ₹0.90, and net_excl_gst must
    match the invoice's energy_taxable_value (₹37.37) — not the
    actual-fee-derived ₹37.18 that the pre-amendment code would have
    produced.
    """
    from services.franchisee_settlement_service import FranchiseeSettlementService

    txn = await _build_qr_session(
        test_franchisee, test_station, test_charger, test_user,
        amount_paid=Decimal("45.00"),
        energy_kwh=Decimal("2.250"),
        energy_cost=Decimal("37.37"),
        gst_amount=Decimal("6.73"),
        actual_commission=Decimal("0.92"),
        actual_gst=Decimal("0.17"),  # actual total ₹1.09 vs synthetic ₹0.90
    )

    entry = await FranchiseeSettlementService.process_settlement(txn.id)

    assert entry is not None
    # 2% of 45 = 0.90, regardless of the 1.09 actual sitting on QRPayment.
    assert entry.pg_fee_amount == Decimal("0.90"), (
        f"expected synthetic 0.90, got {entry.pg_fee_amount}"
    )
    # net_excl_gst now matches the invoice's energy_taxable_value exactly.
    assert entry.net_excl_gst == Decimal("37.37")


@pytest.mark.asyncio
async def test_process_settlement_qr_synthetic_when_actual_below_2pct(
    client, test_franchisee, test_charger, test_user, test_tariff, test_station,
):
    """ADR 0001 amendment regression guard (actual < synthetic case).

    ~57% of staging txns fall here. Pre-amendment, when Razorpay charged
    less than 2%, the splittable pool grew and franchisee got a bonus.
    Post-amendment, VoltLync pockets the surplus; the franchisee's pool
    is locked to synthetic 2% regardless. The ledger must record
    synthetic 0.90 even though actual is only ₹0.30.
    """
    from services.franchisee_settlement_service import FranchiseeSettlementService

    txn = await _build_qr_session(
        test_franchisee, test_station, test_charger, test_user,
        amount_paid=Decimal("45.00"),
        energy_kwh=Decimal("2.250"),
        energy_cost=Decimal("37.37"),
        gst_amount=Decimal("6.73"),
        actual_commission=Decimal("0.25"),
        actual_gst=Decimal("0.05"),  # actual ₹0.30 vs synthetic ₹0.90
    )

    entry = await FranchiseeSettlementService.process_settlement(txn.id)

    assert entry is not None
    assert entry.pg_fee_amount == Decimal("0.90"), (
        f"expected synthetic 0.90 even when actual is lower, "
        f"got {entry.pg_fee_amount}"
    )
    assert entry.net_excl_gst == Decimal("37.37")
    # Franchisee payout is identical to the actual > synthetic case — that's
    # the whole point of the policy: a stable per-session payout regardless
    # of Razorpay's instantaneous fee.
    # 37.37 × 0.80 (commission@20% from test_franchisee) = 29.90 (earning)
    # 29.90 × 0.10 (tds) = 2.99 → payout = 26.91
    assert entry.franchisee_payout == Decimal("26.91")


@pytest.mark.asyncio
async def test_qr_ledger_agrees_with_invoice_revenue_pool(
    client, _voltlync_supplier,
    test_franchisee, test_charger, test_user, test_tariff, test_station,
):
    """The motivating test: invoice gateway-charges line and ledger
    pg_fee_amount must be the same number, and invoice energy_taxable_value
    must equal ledger net_excl_gst. This was the stated reason for the
    ADR 0001 amendment — if this ever fails, the amendment is broken.

    Explicit GSTInvoice + GSTInvoiceCounter cleanup at the end because the
    project-wide conftest cleanup list omits both (every other test that
    generates an invoice has the same gap; this test trips a downstream
    flake without the teardown).
    """
    from models import GSTInvoice, GSTInvoiceCounter
    from services.franchisee_settlement_service import FranchiseeSettlementService
    from services.invoice_service import InvoiceService

    # The project conftest cleanup omits qr_session:* Redis keys, GSTInvoice,
    # and GSTInvoiceCounter rows. This test exercises both invoice generation
    # AND a downstream Redis-cached endpoint surface — be defensive at the
    # boundary so we don't leave residue for the next test in the file.
    import redis as _sync_redis
    import os as _os
    try:
        _r = _sync_redis.from_url(_os.environ.get("REDIS_URL", "redis://redis:6379/0"))
        for _k in _r.scan_iter("qr_session:*"):
            _r.delete(_k)
        _r.close()
    except Exception:
        pass

    txn = await _build_qr_session(
        test_franchisee, test_station, test_charger, test_user,
        amount_paid=Decimal("45.00"),
        energy_kwh=Decimal("2.250"),
        energy_cost=Decimal("37.37"),
        gst_amount=Decimal("6.73"),
        actual_commission=Decimal("0.92"),
        actual_gst=Decimal("0.17"),
    )

    try:
        entry = await FranchiseeSettlementService.process_settlement(txn.id)
        invoice = await InvoiceService.generate_invoice(txn.id)

        assert entry is not None
        assert invoice is not None

        # Gateway line: invoice's gateway_charges + gateway_gst equals the
        # ledger's pg_fee_amount, both being the synthetic 2% of ₹45 = ₹0.90.
        invoice_gateway_total = (
            invoice.gateway_charges + (invoice.gateway_gst or Decimal("0"))
        )
        assert invoice_gateway_total == entry.pg_fee_amount == Decimal("0.90"), (
            f"invoice gateway total {invoice_gateway_total} != "
            f"ledger pg_fee {entry.pg_fee_amount}"
        )

        # Revenue pool: invoice's energy_taxable_value equals the ledger's
        # net_excl_gst. This is the line that pre-amendment disagreed by the
        # actual-vs-synthetic variance.
        assert invoice.energy_taxable_value == entry.net_excl_gst, (
            f"invoice energy_taxable {invoice.energy_taxable_value} != "
            f"ledger net_excl_gst {entry.net_excl_gst}"
        )
    finally:
        await GSTInvoice.all().delete()
        await GSTInvoiceCounter.all().delete()


@pytest.mark.asyncio
async def test_process_settlement_qr_honours_non_default_synthetic_percent(
    client, monkeypatch,
    test_franchisee, test_charger, test_user, test_tariff, test_station,
):
    """Regression guard: the policy is NOT hard-coded to 2%.

    `synthetic_platform_fee` reads `RAZORPAY_PLATFORM_FEE_PERCENT` at import
    time as a module-level constant; if ops bumps it (e.g. to 3% after
    Razorpay re-rates UPI), the settlement ledger must follow without code
    changes. Patches the module constant and re-verifies pg_fee_amount.
    """
    from decimal import Decimal as _D
    from services import tariff_utils as _tu
    from services.franchisee_settlement_service import FranchiseeSettlementService

    monkeypatch.setattr(_tu, "RAZORPAY_PLATFORM_FEE_PERCENT", _D("3.0"))

    txn = await _build_qr_session(
        test_franchisee, test_station, test_charger, test_user,
        amount_paid=Decimal("100.00"),
        energy_kwh=Decimal("4.000"),
        energy_cost=Decimal("82.20"),
        gst_amount=Decimal("14.80"),
        actual_commission=Decimal("0.85"),
        actual_gst=Decimal("0.15"),  # actual ₹1.00 — irrelevant; we want 3% synthetic
    )

    entry = await FranchiseeSettlementService.process_settlement(txn.id)

    assert entry is not None
    # 3% of ₹100 = ₹3.00, not the ₹2.00 the default would have produced.
    assert entry.pg_fee_amount == Decimal("3.00"), (
        f"expected synthetic 3.00 after monkey-patching the percent, "
        f"got {entry.pg_fee_amount}"
    )


@pytest.mark.asyncio
async def test_process_settlement_wallet_pg_fee_unchanged(
    client, test_franchisee, test_charger, test_user, test_tariff, test_station,
):
    """Wallet sessions must NOT pick up the synthetic policy — they have
    no per-session Razorpay payment fee (absorbed at top-up time, ADR 0002).
    Regression guard against accidentally applying the QR synthetic to wallet.
    """
    from models import Transaction, TransactionStatusEnum
    from services.franchisee_settlement_service import FranchiseeSettlementService

    test_station.franchisee = test_franchisee
    await test_station.save()

    txn = await Transaction.create(
        charger=test_charger,
        user=test_user,
        start_meter_kwh=Decimal("0"),
        end_meter_kwh=Decimal("2.250"),
        energy_consumed_kwh=Decimal("2.250"),
        energy_charge=Decimal("33.90"),
        gst_amount=Decimal("6.10"),
        gst_rate_percent=Decimal("18.00"),
        total_billed=Decimal("40.00"),
        transaction_status=TransactionStatusEnum.COMPLETED,
    )

    entry = await FranchiseeSettlementService.process_settlement(txn.id)

    assert entry is not None
    assert entry.payment_method == "WALLET"
    assert entry.pg_fee_amount == Decimal("0.00"), (
        f"wallet pg_fee must remain 0 (ADR 0002), got {entry.pg_fee_amount}"
    )


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
