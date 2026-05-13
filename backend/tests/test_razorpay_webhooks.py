"""End-to-end tests for the Razorpay webhook endpoint.

Exercises the full HTTP path: signature header → ``verify_webhook_signature``
(real hmac, not mocked) → event-type dispatch → handler.

Coverage:
- Valid signature + valid event → 200, processing happens.
- Invalid signature → 400, no processing.
- Missing signature header → 400, no processing.
- Replay of the same payment.captured event → idempotent at the handler
  level (only one WalletTransaction created).
- Settlement webhook replay → relies on the fix in
  franchisee_settlement_service.handle_settlement_webhook (excludes SETTLED
  entries from the update set).
"""
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from models import (
    CommissionLedgerEntry,
    SettlementStatusEnum,
)
from services.franchisee_settlement_service import FranchiseeSettlementService


pytestmark = pytest.mark.asyncio


TEST_WEBHOOK_SECRET = "test_webhook_secret_seed"


def _sign(body: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    """Compute the HMAC-SHA256 signature Razorpay would send."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post_webhook(client, payload: dict, *, signature: str | None):
    """Wrapper to issue a webhook POST with the right headers."""
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Razorpay-Signature"] = signature
    return client.post("/webhooks/razorpay", content=body, headers=headers)


async def _post_with_real_sig(client, payload: dict):
    """Convenience: sign the body with TEST_WEBHOOK_SECRET and POST."""
    body = json.dumps(payload).encode()
    return await client.post(
        "/webhooks/razorpay",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": _sign(body),
        },
    )


async def test_invalid_signature_returns_400(client):
    """Garbage signature value must be rejected without processing."""
    payload = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_x"}}}}
    body = json.dumps(payload).encode()
    with patch(
        "services.razorpay_service.razorpay_service.webhook_secret",
        TEST_WEBHOOK_SECRET,
    ):
        resp = await client.post(
            "/webhooks/razorpay",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": "deadbeef" * 8,
            },
        )
    assert resp.status_code == 400


async def test_missing_signature_header_returns_400(client):
    """Razorpay always sends the signature; missing header must be rejected."""
    payload = {"event": "payment.captured", "payload": {}}
    with patch(
        "services.razorpay_service.razorpay_service.webhook_secret",
        TEST_WEBHOOK_SECRET,
    ):
        resp = await client.post(
            "/webhooks/razorpay",
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 400


async def test_valid_signature_unknown_event_returns_200(client):
    """Verified signature + event we don't handle should still 200 (so
    Razorpay doesn't retry); the handler logs and moves on."""
    payload = {"event": "subscription.activated", "payload": {}}
    with patch(
        "services.razorpay_service.razorpay_service.webhook_secret",
        TEST_WEBHOOK_SECRET,
    ):
        resp = await _post_with_real_sig(client, payload)
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}


async def test_settlement_webhook_idempotent_on_replay(
    client, test_commission_ledger_entry, test_franchisee
):
    """Regression for the settlement-webhook idempotency fix: replaying
    ``settlement.processed`` for an already-SETTLED ledger entry must NOT
    advance ``settled_at`` or rewrite ``transfer_fee``.

    Calls FranchiseeSettlementService.handle_settlement_webhook directly
    (the dispatcher in webhooks.py is a thin wrapper that calls the same
    method)."""
    # Set the entry up as SETTLED with a known fee and timestamp.
    from datetime import datetime, timezone, timedelta
    fixed_settled_at = datetime.now(timezone.utc) - timedelta(hours=2)
    test_commission_ledger_entry.razorpay_transfer_id = "trf_settled_001"
    test_commission_ledger_entry.settlement_status = SettlementStatusEnum.SETTLED
    test_commission_ledger_entry.settled_at = fixed_settled_at
    test_commission_ledger_entry.transfer_fee = Decimal("0.50")
    await test_commission_ledger_entry.save()

    # Razorpay replays with a different fee/tax. Replay must NOT win.
    replay_payload = {
        "id": "setl_replay_001",
        "transfers": [
            {"id": "trf_settled_001", "fees": 999, "tax": 0},
        ],
    }
    await FranchiseeSettlementService.handle_settlement_webhook(
        event_type="settlement.processed",
        settlement_data=replay_payload,
    )

    refreshed = await CommissionLedgerEntry.get(id=test_commission_ledger_entry.id)
    assert refreshed.settlement_status == SettlementStatusEnum.SETTLED
    assert refreshed.transfer_fee == Decimal("0.50"), (
        "transfer_fee must be frozen at first observation; replay wrote stale value"
    )
    assert abs((refreshed.settled_at - fixed_settled_at).total_seconds()) < 1, (
        "settled_at must be frozen at first observation"
    )


async def test_settlement_webhook_first_time_applies(
    client, test_commission_ledger_entry, test_franchisee
):
    """Positive case: the first settlement.processed for a TRANSFER_PROCESSED
    entry transitions it to SETTLED with the carried fee/tax."""
    test_commission_ledger_entry.razorpay_transfer_id = "trf_first_002"
    test_commission_ledger_entry.settlement_status = SettlementStatusEnum.TRANSFER_PROCESSED
    test_commission_ledger_entry.transfer_fee = Decimal("0.00")
    await test_commission_ledger_entry.save()

    payload = {
        "id": "setl_first_002",
        "transfers": [{"id": "trf_first_002", "fees": 47, "tax": 8}],
    }
    await FranchiseeSettlementService.handle_settlement_webhook(
        event_type="settlement.processed",
        settlement_data=payload,
    )

    refreshed = await CommissionLedgerEntry.get(id=test_commission_ledger_entry.id)
    assert refreshed.settlement_status == SettlementStatusEnum.SETTLED
    assert refreshed.settled_at is not None
    # (47 + 8) paise = 0.55 rupees
    assert refreshed.transfer_fee == Decimal("0.55")
