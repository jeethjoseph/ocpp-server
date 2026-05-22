"""Unit tests for FranchiseeOnboardingService payload correctness and
the regression patterns identified during the acc_Sg73UwyOU3jziR audit.

Pure-logic tests — no DB, no network. Razorpay SDK calls and model
queries are mocked so the assertions describe the wire payloads we send.
"""
import logging
from datetime import datetime, timedelta, timezone
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
async def test_create_linked_account_payload_keeps_type_route_and_only_registered_address():
    """`type: 'route'` is documented and required. Only `addresses.registered`
    is sent — Razorpay 400s with "operational is/are not required and should
    not be sent" if we include `operational` (verified against live API
    2026-04-29; see `razorpay_api_log` row from that date)."""
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

    def capture_create(payload, **kwargs):
        captured["payload"] = payload
        return {"id": "acc_test", "status": "created", "business_type": "individual"}

    rzp = MagicMock()
    rzp.is_route_enabled.return_value = True
    rzp.create_linked_account = AsyncMock(side_effect=capture_create)

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
    # Razorpay rejects `operational` — must NOT be sent.
    assert "operational" not in addresses
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
    rzp.create_linked_account = AsyncMock(return_value={
        "id": "acc_x", "status": "created",
        "business_type": "not_yet_registered",  # <-- mismatch
    })

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
async def test_submit_bank_details_includes_tnc_and_excludes_account_type():
    """PATCH must always include `tnc_accepted: true`. `account_type`
    must NEVER be sent — Razorpay 400s with "account_type is/are not
    required and should not be sent" (verified 2026-04-29 via the
    audit log). The franchisee.bank_account_type column stays locally
    for invoicing / reconciliation but is omitted from the Razorpay
    payload regardless of whether it's set."""
    franchisee = MagicMock()
    franchisee.razorpay_account_id = "acc_x"
    franchisee.razorpay_product_id = "acc_prd_x"
    franchisee.bank_account_number = "12345"
    franchisee.bank_ifsc_code = "SBIN0001"
    franchisee.bank_account_name = "Jane Doe"
    # Even when bank_account_type IS populated locally, we must not send it.
    franchisee.bank_account_type = "savings"

    rzp = MagicMock()
    rzp.edit_product_configuration = AsyncMock(return_value={
        "activation_status": "under_review"
    })

    with patch("services.razorpay_service.razorpay_service", rzp), patch(
        "models.Franchisee.filter"
    ) as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=franchisee)
        await FranchiseeOnboardingService.submit_bank_details(1)

    args, _kwargs = rzp.edit_product_configuration.call_args
    body = args[2]
    assert body["tnc_accepted"] is True
    assert body["settlements"]["account_number"] == "12345"
    assert body["settlements"]["ifsc_code"] == "SBIN0001"
    assert body["settlements"]["beneficiary_name"] == "Jane Doe"
    # Razorpay rejects account_type — it must never appear.
    assert "account_type" not in body["settlements"]


@pytest.mark.asyncio
async def test_submit_bank_details_omits_account_type_when_unset_too():
    """Sanity: with bank_account_type=None, account_type still must not
    appear in the payload (same as when it's set)."""
    franchisee = MagicMock()
    franchisee.razorpay_account_id = "acc_x"
    franchisee.razorpay_product_id = "acc_prd_x"
    franchisee.bank_account_number = "12345"
    franchisee.bank_ifsc_code = "SBIN0001"
    franchisee.bank_account_name = "Jane Doe"
    franchisee.bank_account_type = None

    rzp = MagicMock()
    rzp.edit_product_configuration = AsyncMock(return_value={})

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

    async def capture_update(**kwargs):
        captured_updates.update(kwargs)

    with patch("models.Franchisee.filter") as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=franchisee)
        mock_filter.return_value.update = AsyncMock(side_effect=capture_update)
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
    franchisee.activated_at = datetime.now(timezone.utc) - timedelta(hours=2)

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


# ─── Audit log writes from the wrappers ─────────────────────────────────

@pytest.mark.asyncio
async def test_create_linked_account_writes_audit_log_on_success():
    """Successful SDK call must produce one RazorpayApiLog row with
    success=True, the masked request body, and the response body."""
    from services.razorpay_service import RazorpayService

    svc = RazorpayService.__new__(RazorpayService)
    svc.client = MagicMock()
    svc.client.account.create.return_value = {"id": "acc_test"}

    captured_log = {}

    async def fake_create(**kw):
        captured_log.update(kw)
        return MagicMock()

    fake_log_cls = MagicMock()
    fake_log_cls.create = AsyncMock(side_effect=fake_create)

    with patch.dict("sys.modules", {}), patch(
        "models.RazorpayApiLog", fake_log_cls, create=True
    ):
        result = await svc.create_linked_account(
            {"legal_info": {"pan": "BFIPJ6239L"}}, franchisee_id=42
        )

    assert result == {"id": "acc_test"}
    fake_log_cls.create.assert_awaited_once()
    assert captured_log["method"] == "POST"
    assert captured_log["endpoint"] == "/v2/accounts"
    assert captured_log["success"] is True
    assert captured_log["franchisee_id"] == 42
    # PAN must be masked.
    assert captured_log["request_body"]["legal_info"]["pan"] == "***239L"


@pytest.mark.asyncio
async def test_create_linked_account_writes_audit_log_on_failure():
    """SDK exception still writes a row (success=False) and re-raises."""
    import razorpay
    from services.razorpay_service import RazorpayService

    svc = RazorpayService.__new__(RazorpayService)
    svc.client = MagicMock()
    svc.client.account.create.side_effect = razorpay.errors.BadRequestError(
        "invalid pan"
    )

    captured_log = {}
    fake_log_cls = MagicMock()

    async def fake_create(**kw):
        captured_log.update(kw)
        return MagicMock()

    fake_log_cls.create = AsyncMock(side_effect=fake_create)

    with patch("models.RazorpayApiLog", fake_log_cls, create=True):
        with pytest.raises(razorpay.errors.BadRequestError):
            await svc.create_linked_account({"legal_info": {"pan": "X"}})

    fake_log_cls.create.assert_awaited_once()
    assert captured_log["success"] is False
    assert captured_log["response_status"] == 400
    assert "invalid pan" in (captured_log["error_message"] or "")


@pytest.mark.asyncio
async def test_audit_call_swallows_audit_write_failure():
    """If RazorpayApiLog.create itself raises, the SDK return value
    must still propagate (audit-log failure does not break the SDK call)."""
    from services.razorpay_service import RazorpayService

    svc = RazorpayService.__new__(RazorpayService)
    svc.client = MagicMock()
    svc.client.account.create.return_value = {"id": "acc_ok"}

    fake_log_cls = MagicMock()
    fake_log_cls.create = AsyncMock(side_effect=RuntimeError("db down"))

    with patch("models.RazorpayApiLog", fake_log_cls, create=True):
        result = await svc.create_linked_account({"x": "y"})

    assert result == {"id": "acc_ok"}


# ─── delete_linked_account orchestration ────────────────────────────────

@pytest.mark.asyncio
async def test_delete_linked_account_returns_already_clear_when_no_account():
    franchisee = MagicMock()
    franchisee.razorpay_account_id = None

    with patch("models.Franchisee.filter") as mock_filter:
        mock_filter.return_value.first = AsyncMock(return_value=franchisee)
        result = await FranchiseeOnboardingService.delete_linked_account(7)

    assert result["status"] == "already_clear"


@pytest.mark.asyncio
async def test_delete_linked_account_refuses_when_settlements_exist():
    franchisee = MagicMock()
    franchisee.razorpay_account_id = "acc_x"

    with patch("models.Franchisee.filter") as mock_franchisee_filter, patch(
        "models.CommissionLedgerEntry.filter"
    ) as mock_entry_filter:
        mock_franchisee_filter.return_value.first = AsyncMock(
            return_value=franchisee
        )
        mock_entry_filter.return_value.count = AsyncMock(return_value=3)

        with pytest.raises(RuntimeError, match="commission_ledger_entry"):
            await FranchiseeOnboardingService.delete_linked_account(7)


@pytest.mark.asyncio
async def test_delete_linked_account_clears_local_state_on_success():
    franchisee = MagicMock()
    franchisee.razorpay_account_id = "acc_x"

    rzp = MagicMock()
    rzp.delete_linked_account = AsyncMock(return_value={"deleted": True})

    captured_updates = {}
    stakeholders_deleted = AsyncMock(return_value=2)

    with patch(
        "services.razorpay_service.razorpay_service", rzp
    ), patch("models.Franchisee.filter") as mock_franchisee_filter, patch(
        "models.CommissionLedgerEntry.filter"
    ) as mock_entry_filter, patch(
        "models.FranchiseeStakeholder.filter"
    ) as mock_stakeholder_filter, patch(
        "tortoise.transactions.in_transaction"
    ) as mock_txn:
        mock_franchisee_filter.return_value.first = AsyncMock(
            return_value=franchisee
        )
        mock_franchisee_filter.return_value.update = AsyncMock(
            side_effect=lambda **kw: captured_updates.update(kw) or None
        )
        mock_entry_filter.return_value.count = AsyncMock(return_value=0)
        mock_stakeholder_filter.return_value.delete = stakeholders_deleted
        mock_txn.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_txn.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await FranchiseeOnboardingService.delete_linked_account(7)

    rzp.delete_linked_account.assert_awaited_once_with(
        "acc_x", franchisee_id=7
    )
    assert result["status"] == "deleted"
    assert result["razorpay_account_id"] == "acc_x"
    assert result["stakeholders_removed"] == 2
    # Local fields cleared.
    assert captured_updates["razorpay_account_id"] is None
    assert captured_updates["razorpay_product_id"] is None
    assert captured_updates["kyc_verifications"] is None
    assert captured_updates["activated_at"] is None


@pytest.mark.asyncio
async def test_delete_linked_account_tolerates_razorpay_404():
    """If Razorpay says 'not found' (account already gone upstream),
    proceed with local cleanup instead of erroring."""
    franchisee = MagicMock()
    franchisee.razorpay_account_id = "acc_x"

    rzp = MagicMock()
    rzp.delete_linked_account = AsyncMock(
        side_effect=Exception("The account does not exist")
    )

    with patch(
        "services.razorpay_service.razorpay_service", rzp
    ), patch("models.Franchisee.filter") as mock_franchisee_filter, patch(
        "models.CommissionLedgerEntry.filter"
    ) as mock_entry_filter, patch(
        "models.FranchiseeStakeholder.filter"
    ) as mock_stakeholder_filter, patch(
        "tortoise.transactions.in_transaction"
    ) as mock_txn:
        mock_franchisee_filter.return_value.first = AsyncMock(
            return_value=franchisee
        )
        mock_franchisee_filter.return_value.update = AsyncMock(return_value=None)
        mock_entry_filter.return_value.count = AsyncMock(return_value=0)
        mock_stakeholder_filter.return_value.delete = AsyncMock(return_value=0)
        mock_txn.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_txn.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await FranchiseeOnboardingService.delete_linked_account(7)

    assert result["status"] == "deleted"
