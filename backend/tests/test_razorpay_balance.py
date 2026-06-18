"""Tests for RazorpayService.fetch_balance and the refund-speed diagnostic
fields (ADR 0002, 2026-06-18 amendment).

fetch_balance is the best-effort funding-pool snapshot taken before an
optimum refund POST; it must convert paise->rupees on success and swallow all
failures to None so it can never break the refund.
"""
import httpx
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from services.razorpay_service import RazorpayService
from services.monitoring_service import OCPPMetrics


def _client_cm(resp):
    """An async-context-manager mock whose .get() returns `resp`."""
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _configured_service():
    svc = RazorpayService()
    svc.client = MagicMock()  # is_configured() keys off self.client
    svc.api_key = "rzp_test_key"
    svc.api_secret = "rzp_test_secret"
    return svc


@pytest.mark.asyncio
async def test_fetch_balance_converts_paise_to_rupees():
    resp = MagicMock()
    resp.is_error = False
    resp.json = MagicMock(return_value={"balance": 42268, "refund_credits": 1500})
    with patch("services.razorpay_service.httpx.AsyncClient",
               return_value=_client_cm(resp)):
        out = await _configured_service().fetch_balance()
    assert out == {"balance": 422.68, "refund_credits": 15.0}


@pytest.mark.asyncio
async def test_fetch_balance_defaults_missing_pools_to_zero():
    resp = MagicMock()
    resp.is_error = False
    resp.json = MagicMock(return_value={"balance": None})  # refund_credits absent
    with patch("services.razorpay_service.httpx.AsyncClient",
               return_value=_client_cm(resp)):
        out = await _configured_service().fetch_balance()
    assert out == {"balance": 0.0, "refund_credits": 0.0}


@pytest.mark.asyncio
async def test_fetch_balance_returns_none_on_http_error():
    resp = MagicMock()
    resp.is_error = True
    resp.status_code = 500
    with patch("services.razorpay_service.httpx.AsyncClient",
               return_value=_client_cm(resp)):
        out = await _configured_service().fetch_balance()
    assert out is None


@pytest.mark.asyncio
async def test_fetch_balance_returns_none_on_network_error():
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=httpx.HTTPError("timeout"))
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch("services.razorpay_service.httpx.AsyncClient", return_value=cm):
        out = await _configured_service().fetch_balance()
    assert out is None


@pytest.mark.asyncio
async def test_fetch_balance_returns_none_when_not_configured():
    svc = RazorpayService()
    svc.client = None
    out = await svc.fetch_balance()
    assert out is None


@pytest.mark.asyncio
async def test_record_refund_speed_emits_funding_pool_fields():
    with patch("services.monitoring_service.MetricsCollector.record_event") as rec, \
         patch("services.monitoring_service.MetricsCollector.increment_counter"):
        await OCPPMetrics.record_refund_speed(
            charger_id=1, qr_payment_id=2, speed_processed="normal",
            balance_before=422.68, refund_credits_before=0.0,
        )
    rec.assert_called_once()
    event_type, payload = rec.call_args.args
    assert event_type == "QRRefundSpeed"
    assert payload["balance_before"] == 422.68
    assert payload["refund_credits_before"] == 0.0
    assert payload["speed_processed"] == "normal"
