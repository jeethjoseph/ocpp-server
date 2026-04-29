"""Unit tests for FranchiseeOnboardingService payload correctness and
the regression patterns identified during the acc_Sg73UwyOU3jziR audit.

Pure-logic tests — no DB, no network. Razorpay SDK calls and model
queries are mocked so the assertions describe the wire payloads we send.
"""
import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.franchisee_onboarding_service import (
    FranchiseeOnboardingService,
    _relationship_defaults,
)


@pytest.fixture
def ocpp_caplog(caplog):
    """The "ocpp-server" logger is configured with propagate=False in
    main.py to avoid duplicate handlers in production. caplog hooks the
    root logger, so we need to flip propagation back on for the test."""
    svc_logger = logging.getLogger("ocpp-server")
    prev = svc_logger.propagate
    svc_logger.propagate = True
    caplog.set_level(logging.WARNING, logger="ocpp-server")
    yield caplog
    svc_logger.propagate = prev


# ─── _relationship_defaults ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "business_type,expected",
    [
        ("INDIVIDUAL", (False, True)),
        ("PROPRIETORSHIP", (False, True)),
        ("PARTNERSHIP", (True, True)),
        ("PRIVATE_LIMITED", (True, True)),
        ("LLP", (True, True)),
    ],
)
def test_relationship_defaults_known_business_types(business_type, expected):
    """Every member of FranchiseeBusinessTypeEnum must produce a defined
    (director, executive) tuple — INDIVIDUAL/PROPRIETORSHIP especially
    must NOT default director=True (the regression pattern observed for
    acc_Sg73UwyOU3jziR)."""
    assert _relationship_defaults(business_type) == expected


def test_relationship_defaults_unknown_falls_back_with_warning(ocpp_caplog):
    result = _relationship_defaults("SOMETHING_NEW_RAZORPAY_INVENTED")
    assert result == (True, True)
    assert any(
        "unmapped business_type" in r.getMessage()
        for r in ocpp_caplog.records
    )


def test_relationship_defaults_handles_enum_member_with_value_attr():
    """Tortoise CharEnumField passes a real enum member, not a string —
    helper must read .value."""
    enum_like = MagicMock()
    enum_like.value = "INDIVIDUAL"
    assert _relationship_defaults(enum_like) == (False, True)


# ─── create_linked_account payload shape ────────────────────────────────

@pytest.mark.asyncio
async def test_create_linked_account_payload_keeps_type_route_and_mirrors_addresses():
    """`type: 'route'` is documented and required. `addresses.operational`
    must mirror `addresses.registered` so Razorpay's review has both."""
    franchisee = MagicMock()
    franchisee.id = 42
    franchisee.razorpay_account_id = None
    franchisee.business_type = MagicMock()
    franchisee.business_type.value = "INDIVIDUAL"
    franchisee.business_name = "Acme"
    franchisee.contact_name = "Jane Doe"
    franchisee.contact_email = "jane@example.com"
    franchisee.contact_phone = "9999999999"
    franchisee.address = "1, Main St, Bangalore"
    franchisee.city = "Bengaluru"
    franchisee.state = "karnataka"
    franchisee.pincode = "560001"

    captured = {}

    def capture_create(payload):
        captured["payload"] = payload
        return {"id": "acc_test", "status": "created", "business_type": "individual"}

    rzp = MagicMock()
    rzp.is_route_enabled.return_value = True
    rzp.create_linked_account.side_effect = capture_create

    with patch(
        "services.razorpay_service.razorpay_service", rzp
    ), patch.object(
        type(franchisee), "filter", create=True,
    ), patch(
        "models.Franchisee.filter"
    ) as mock_filter:
        # First filter: fetch by id; chain to .first()
        first = AsyncMock(return_value=franchisee)
        update = AsyncMock(return_value=None)
        mock_filter.return_value.first = first
        mock_filter.return_value.update = update

        await FranchiseeOnboardingService.create_linked_account(42)

    assert captured["payload"]["type"] == "route"
    assert captured["payload"]["business_type"] == "individual"
    addresses = captured["payload"]["profile"]["addresses"]
    assert "registered" in addresses
    assert "operational" in addresses
    assert addresses["registered"] == addresses["operational"]
    assert addresses["registered"]["country"] == "IN"


@pytest.mark.asyncio
async def test_create_linked_account_warns_on_business_type_mismatch(ocpp_caplog):
    """If Razorpay echoes a different business_type than we sent, surface
    a WARNING — this is the silent downgrade pattern we observed."""
    franchisee = MagicMock()
    franchisee.id = 1
    franchisee.razorpay_account_id = None
    franchisee.business_type = MagicMock()
    franchisee.business_type.value = "INDIVIDUAL"
    franchisee.business_name = "Acme"
    franchisee.contact_name = "Jane"
    franchisee.contact_email = "j@example.com"
    franchisee.contact_phone = "9"
    franchisee.address = "1, x"
    franchisee.city = "Bengaluru"
    franchisee.state = "ka"
    franchisee.pincode = "1"

    rzp = MagicMock()
    rzp.is_route_enabled.return_value = True
    rzp.create_linked_account.return_value = {
        "id": "acc_x", "status": "created",
        "business_type": "not_yet_registered",  # <-- mismatch
    }

    with patch(
        "services.razorpay_service.razorpay_service", rzp
    ), patch("models.Franchisee.filter") as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=franchisee)
        mock_filter.return_value.update = AsyncMock(return_value=None)
        await FranchiseeOnboardingService.create_linked_account(1)

    msgs = "\n".join(r.getMessage() for r in ocpp_caplog.records)
    assert "not_yet_registered" in msgs
    assert "individual" in msgs


# ─── submit_bank_details payload shape ──────────────────────────────────

@pytest.mark.asyncio
async def test_submit_bank_details_includes_tnc_and_optional_account_type():
    """PATCH must always include `tnc_accepted: true`; `account_type` is
    only sent when the franchisee row has bank_account_type set."""
    franchisee = MagicMock()
    franchisee.razorpay_account_id = "acc_x"
    franchisee.razorpay_product_id = "acc_prd_x"
    franchisee.bank_account_number = "12345"
    franchisee.bank_ifsc_code = "SBIN0001"
    franchisee.bank_account_name = "Jane Doe"
    franchisee.bank_account_type = "savings"

    rzp = MagicMock()
    rzp.edit_product_configuration.return_value = {
        "activation_status": "under_review"
    }

    with patch("services.razorpay_service.razorpay_service", rzp), patch(
        "models.Franchisee.filter"
    ) as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=franchisee)
        await FranchiseeOnboardingService.submit_bank_details(1)

    args, _kwargs = rzp.edit_product_configuration.call_args
    body = args[2]
    assert body["tnc_accepted"] is True
    assert body["settlements"]["account_type"] == "savings"
    assert body["settlements"]["account_number"] == "12345"


@pytest.mark.asyncio
async def test_submit_bank_details_omits_account_type_when_unset():
    franchisee = MagicMock()
    franchisee.razorpay_account_id = "acc_x"
    franchisee.razorpay_product_id = "acc_prd_x"
    franchisee.bank_account_number = "12345"
    franchisee.bank_ifsc_code = "SBIN0001"
    franchisee.bank_account_name = "Jane Doe"
    franchisee.bank_account_type = None

    rzp = MagicMock()
    rzp.edit_product_configuration.return_value = {}

    with patch("services.razorpay_service.razorpay_service", rzp), patch(
        "models.Franchisee.filter"
    ) as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=franchisee)
        await FranchiseeOnboardingService.submit_bank_details(1)

    body = rzp.edit_product_configuration.call_args[0][2]
    assert "account_type" not in body["settlements"]
    assert body["tnc_accepted"] is True


# ─── handle_account_webhook ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_account_webhook_parses_requirements_as_list():
    """Regression for franchisee_onboarding_service.py:222 — requirements
    is a LIST of dicts, not a dict."""
    franchisee = MagicMock()
    franchisee.id = 7
    franchisee.razorpay_account_id = "acc_x"
    franchisee.activated_at = None

    captured_updates = {}

    def capture_update(**kwargs):
        captured_updates.update(kwargs)
        return AsyncMock(return_value=None)()

    with patch("models.Franchisee.filter") as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=franchisee)
        mock_filter.return_value.update = AsyncMock(
            side_effect=lambda **kw: capture_update(**kw)
        )
        await FranchiseeOnboardingService.handle_account_webhook(
            "account.needs_clarification",
            {
                "id": "acc_x",
                "status": "needs_clarification",
                "requirements": [
                    {
                        "field_reference": "stakeholder.kyc.pan",
                        "resolution_url": "https://...",
                        "reason_code": "field_missing",
                        "status": "open",
                    },
                    {
                        "field_reference": "settlements.account_type",
                        "reason_code": "field_invalid",
                    },
                ],
            },
        )

    reason = captured_updates.get("status_reason", "")
    assert "stakeholder.kyc.pan" in reason
    assert "settlements.account_type" in reason


@pytest.mark.asyncio
async def test_handle_account_webhook_persists_kyc_verifications():
    franchisee = MagicMock()
    franchisee.id = 7
    franchisee.razorpay_account_id = "acc_x"
    franchisee.activated_at = None

    captured_updates = {}

    with patch("models.Franchisee.filter") as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=franchisee)
        mock_filter.return_value.update = AsyncMock(
            side_effect=lambda **kw: captured_updates.update(kw) or None
        )
        await FranchiseeOnboardingService.handle_account_webhook(
            "account.under_review",
            {
                "id": "acc_x",
                "status": "under_review",
                "verification": {
                    "bank_details_verification_status": "initiated",
                    "poi_verification_status": "verified",
                },
            },
        )

    verifications = captured_updates.get("kyc_verifications")
    assert verifications is not None
    assert verifications["bank_details_verification_status"] == "initiated"
    assert verifications["poi_verification_status"] == "verified"


# ─── initiate_transfer cooling-period guard ─────────────────────────────

@pytest.mark.asyncio
async def test_initiate_transfer_holds_within_24h_of_activation():
    """Razorpay enforces a 24h cooling period after activation. Park
    transfers as ON_HOLD with failure_reason='cooling_period' so
    retry_failed_transfers picks them up later."""
    from services.franchisee_settlement_service import (
        FranchiseeSettlementService,
    )
    from models import SettlementStatusEnum

    entry = MagicMock()
    entry.id = 1
    entry.franchisee_id = 1
    from decimal import Decimal
    entry.franchisee_payout = Decimal("256.00")
    entry.idempotency_key = "txn_1"
    entry.transaction_id = 1
    entry.retry_count = 0

    franchisee = MagicMock()
    franchisee.id = 1
    franchisee.razorpay_account_id = "acc_x"
    franchisee.funds_on_hold = False
    franchisee.transfers_enabled = True
    franchisee.activated_at = datetime.utcnow() - timedelta(hours=2)

    rzp = MagicMock()
    rzp.is_route_enabled.return_value = True

    captured = {}

    with patch(
        "services.razorpay_service.razorpay_service", rzp
    ), patch("models.Franchisee.filter") as mock_franchisee_filter, patch(
        "models.CommissionLedgerEntry.filter"
    ) as mock_entry_filter:
        mock_franchisee_filter.return_value.first = AsyncMock(
            return_value=franchisee
        )
        mock_entry_filter.return_value.update = AsyncMock(
            side_effect=lambda **kw: captured.update(kw) or None
        )
        result = await FranchiseeSettlementService.initiate_transfer(entry)

    assert result is False
    assert captured["settlement_status"] == SettlementStatusEnum.ON_HOLD
    assert captured["failure_reason"] == "cooling_period"
    rzp.create_transfer.assert_not_called()
