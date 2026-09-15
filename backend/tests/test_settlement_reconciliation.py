"""Settlement detection for Route transfers: webhook path, sweep path, and the
two corrections the research surfaced.

Background. ``settlement.processed`` carries only the settlement's own
``{id, amount, status, fees, tax, utr, created_at}`` — verified against 202
production payloads and Razorpay's documented sample. The previous handler read
a ``transfers`` array that does not exist, so between June and September 2026
no ledger row ever reached SETTLED. The documented link runs the other way:
``GET /v1/transfers?recipient_settlement_id=`` answers which transfers a
settlement paid, and the Transfer entity carries ``settlement_status`` plus a
nested ``recipient_settlement``.

The real eight-key payload is the fixture throughout.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from models import (
    CommissionLedgerEntry,
    SettlementStatusEnum,
    Transaction,
    TransactionStatusEnum,
)
from services import razorpay_service as rp_module
from services.franchisee_settlement_service import (
    FranchiseeSettlementService,
    settled_at_from,
    transfer_fee_rupees,
)
from services.settlement_reconciler import reconcile_processed_transfers

UTC = timezone.utc

# The real shape, from production. No `transfers`, no `recipient_settlement_id`.
SETTLEMENT_EVENT = {
    "id": "setl_TaFlWiRqn0kQmk",
    "entity": "settlement",
    "amount": 1880,
    "status": "processed",
    "fees": 0,
    "tax": 0,
    "utr": "AXISCN1463261184",
    "created_at": 1789025679,
}


def _transfer(transfer_id, *, settlement_status="settled", nested=None,
              fees=296, tax=46, settlement_id="setl_TaFlWiRqn0kQmk"):
    """A Transfer entity as the API returns it."""
    return {
        "id": transfer_id,
        "entity": "transfer",
        "status": "processed",
        "settlement_status": settlement_status,
        "recipient_settlement_id": settlement_id if settlement_status == "settled" else None,
        "recipient_settlement": nested,
        "fees": fees,
        "tax": tax,
        "on_hold": settlement_status == "on_hold",
    }


NESTED_PROCESSED = {
    "id": "setl_TaFlWiRqn0kQmk", "entity": "settlement", "status": "processed",
    "amount": 1880, "fees": 0, "tax": 0, "utr": "AXISCN1463261184",
    "created_at": 1749772800,  # 2025-06-13T00:00:00Z — a June row
}
NESTED_FAILED = {**NESTED_PROCESSED, "status": "failed", "utr": None}


async def _entry(franchisee, charger, user, *, transfer_id, status, processed_at=None):
    txn = await Transaction.create(
        charger=charger, user=user, start_meter_kwh=0, end_meter_kwh=1,
        energy_consumed_kwh=1, transaction_status=TransactionStatusEnum.COMPLETED,
    )
    return await CommissionLedgerEntry.create(
        transaction=txn, franchisee=franchisee,
        gross_amount=Decimal("20.00"), payment_method="QR_UPI",
        net_amount=Decimal("20.00"), gst_collected=Decimal("3.05"),
        net_excl_gst=Decimal("16.95"), commission_percent=Decimal("10.00"),
        platform_commission=Decimal("1.70"), franchisee_payout=Decimal("15.25"),
        energy_consumed_kwh=Decimal("1.000"), tariff_rate_per_kwh=Decimal("16.9500"),
        settlement_status=status, razorpay_transfer_id=transfer_id,
        transfer_processed_at=processed_at,
        idempotency_key=f"test-{uuid.uuid4().hex}",
    )


# ------------------------------------------------------------ helpers -----

def test_fee_is_fees_plus_tax_in_rupees():
    assert transfer_fee_rupees({"fees": 296, "tax": 46}) == Decimal("3.42")
    assert transfer_fee_rupees({"fees": 0}) == Decimal("0.00")
    assert transfer_fee_rupees({}) is None


def test_settled_at_prefers_the_settlement_timestamp():
    assert settled_at_from(NESTED_PROCESSED) == datetime(2025, 6, 13, tzinfo=UTC)
    assert abs((settled_at_from(None) - datetime.now(UTC)).total_seconds()) < 5


# ------------------------------------------------------ transfer.processed --

@pytest.mark.asyncio
async def test_transfer_processed_captures_the_fee(client, test_franchisee, test_charger, test_user):
    """The fee lives on the transfer entity at this point — it never needed
    the settlement path."""
    e = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_fee01", status=SettlementStatusEnum.TRANSFER_INITIATED)
    await FranchiseeSettlementService.handle_transfer_webhook(
        "transfer.processed", _transfer("trf_fee01", settlement_status=None)
    )
    e = await CommissionLedgerEntry.get(id=e.id)
    assert e.settlement_status == SettlementStatusEnum.TRANSFER_PROCESSED
    assert e.transfer_fee == Decimal("3.42")
    assert e.transfer_processed_at is not None


# ----------------------------------------------------- settlement.processed --

@pytest.mark.asyncio
async def test_settlement_webhook_looks_up_and_advances_transfers(
    client, test_franchisee, test_charger, test_user
):
    a = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_a", status=SettlementStatusEnum.TRANSFER_PROCESSED)
    b = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_b", status=SettlementStatusEnum.TRANSFER_PROCESSED)
    listing = AsyncMock(return_value=[_transfer("trf_a"), _transfer("trf_b", fees=100, tax=0)])

    with patch.object(rp_module.razorpay_service, "list_transfers_for_settlement", listing):
        await FranchiseeSettlementService.handle_settlement_webhook(
            "settlement.processed", SETTLEMENT_EVENT
        )

    listing.assert_awaited_once_with("setl_TaFlWiRqn0kQmk")
    a, b = await CommissionLedgerEntry.get(id=a.id), await CommissionLedgerEntry.get(id=b.id)
    assert a.settlement_status == b.settlement_status == SettlementStatusEnum.SETTLED
    assert a.transfer_fee == Decimal("3.42") and b.transfer_fee == Decimal("1.00")
    assert a.settled_at is not None


@pytest.mark.asyncio
async def test_platform_own_settlement_is_a_quiet_noop(
    client, test_franchisee, test_charger, test_user
):
    """Correction 1. The platform receives its OWN bank settlements under the
    same event name; those cover no Route transfers. Not an error."""
    e = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_untouched", status=SettlementStatusEnum.TRANSFER_PROCESSED)
    with patch.object(rp_module.razorpay_service, "list_transfers_for_settlement",
                      AsyncMock(return_value=[])):
        await FranchiseeSettlementService.handle_settlement_webhook(
            "settlement.processed", SETTLEMENT_EVENT
        )
    e = await CommissionLedgerEntry.get(id=e.id)
    assert e.settlement_status == SettlementStatusEnum.TRANSFER_PROCESSED
    assert e.settled_at is None


@pytest.mark.asyncio
async def test_redelivery_freezes_settled_at_and_fee(
    client, test_franchisee, test_charger, test_user
):
    e = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_replay", status=SettlementStatusEnum.TRANSFER_PROCESSED)
    first = AsyncMock(return_value=[_transfer("trf_replay", fees=296, tax=46)])
    replay = AsyncMock(return_value=[_transfer("trf_replay", fees=999, tax=0)])

    with patch.object(rp_module.razorpay_service, "list_transfers_for_settlement", first):
        await FranchiseeSettlementService.handle_settlement_webhook("settlement.processed", SETTLEMENT_EVENT)
    once = await CommissionLedgerEntry.get(id=e.id)
    with patch.object(rp_module.razorpay_service, "list_transfers_for_settlement", replay):
        await FranchiseeSettlementService.handle_settlement_webhook("settlement.processed", SETTLEMENT_EVENT)
    twice = await CommissionLedgerEntry.get(id=e.id)

    assert twice.settled_at == once.settled_at
    assert twice.transfer_fee == once.transfer_fee == Decimal("3.42")


@pytest.mark.asyncio
async def test_other_events_are_ignored(client):
    with patch.object(rp_module.razorpay_service, "list_transfers_for_settlement",
                      AsyncMock()) as listing:
        await FranchiseeSettlementService.handle_settlement_webhook("settlement.failed", SETTLEMENT_EVENT)
    listing.assert_not_awaited()


# -------------------------------------------------------- strict predicate --

@pytest.mark.asyncio
async def test_failed_recipient_settlement_stays_unsettled(
    client, test_franchisee, test_charger, test_user
):
    """Correction 2. `settlement_status == settled` is not enough: the settlement
    the transfer joined can itself have failed."""
    e = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_failed", status=SettlementStatusEnum.TRANSFER_PROCESSED)
    moved = await FranchiseeSettlementService.settle_from_transfer(
        _transfer("trf_failed", nested=NESTED_FAILED)
    )
    assert moved is False
    assert (await CommissionLedgerEntry.get(id=e.id)).settlement_status == SettlementStatusEnum.TRANSFER_PROCESSED


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "on_hold", None])
async def test_unsettled_statuses_do_not_advance(
    client, test_franchisee, test_charger, test_user, status
):
    e = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id=f"trf_{status}", status=SettlementStatusEnum.TRANSFER_PROCESSED)
    assert await FranchiseeSettlementService.settle_from_transfer(
        _transfer(f"trf_{status}", settlement_status=status)
    ) is False
    assert (await CommissionLedgerEntry.get(id=e.id)).settlement_status == SettlementStatusEnum.TRANSFER_PROCESSED


# ------------------------------------------------------------------ sweep --

@pytest.mark.asyncio
async def test_sweep_backfills_and_records_the_real_settlement_date(
    client, test_franchisee, test_charger, test_user
):
    """The 377-row case: a June row, polled today, settles with June's date."""
    june = datetime(2025, 6, 10, tzinfo=UTC)
    e = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_june", status=SettlementStatusEnum.TRANSFER_PROCESSED,
                     processed_at=june)
    with patch.object(rp_module.razorpay_service, "fetch_transfer",
                      AsyncMock(return_value=_transfer("trf_june", nested=NESTED_PROCESSED))):
        counts = await reconcile_processed_transfers(age_floor_days=None)

    assert counts == {"examined": 1, "settled": 1, "unsettled": 0, "errors": 0}
    e = await CommissionLedgerEntry.get(id=e.id)
    assert e.settlement_status == SettlementStatusEnum.SETTLED
    assert e.settled_at == datetime(2025, 6, 13, tzinfo=UTC)
    assert e.transfer_fee == Decimal("3.42")


@pytest.mark.asyncio
async def test_sweep_respects_the_age_floor(client, test_franchisee, test_charger, test_user):
    """A row processed minutes ago is not worth a call yet — linked accounts
    settle on the parent's T+n schedule."""
    await _entry(test_franchisee, test_charger, test_user,
                 transfer_id="trf_fresh", status=SettlementStatusEnum.TRANSFER_PROCESSED,
                 processed_at=datetime.now(UTC))
    fetch = AsyncMock()
    with patch.object(rp_module.razorpay_service, "fetch_transfer", fetch):
        counts = await reconcile_processed_transfers()  # default 2-day floor
    assert counts["examined"] == 0
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_sweep_leaves_pending_rows_and_survives_a_fetch_error(
    client, test_franchisee, test_charger, test_user
):
    old = datetime.now(UTC) - timedelta(days=10)
    p = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_pending", status=SettlementStatusEnum.TRANSFER_PROCESSED,
                     processed_at=old)
    x = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_boom", status=SettlementStatusEnum.TRANSFER_PROCESSED,
                     processed_at=old)

    async def fetch(transfer_id, **_):
        if transfer_id == "trf_boom":
            raise Exception("HTTP 500")
        return _transfer(transfer_id, settlement_status="pending")

    with patch.object(rp_module.razorpay_service, "fetch_transfer",
                      AsyncMock(side_effect=fetch)):
        counts = await reconcile_processed_transfers()

    assert counts["examined"] == 2 and counts["unsettled"] == 1 and counts["errors"] == 1
    for e in (p, x):
        assert (await CommissionLedgerEntry.get(id=e.id)).settlement_status == SettlementStatusEnum.TRANSFER_PROCESSED


# ---------------------------------------------------- ack first, look up later --

@pytest.mark.asyncio
async def test_router_acks_before_the_lookup_runs(client, monkeypatch):
    """The webhook handler must return before the Razorpay lookup happens.
    Before this, the lookup ran inline while Razorpay waited on our 200."""
    import asyncio
    from services import franchisee_settlement_service as svc
    from routers.webhooks import handle_settlement_event

    monkeypatch.setattr(svc, "SETTLEMENT_LOOKUP_DELAY_SECONDS", 0)
    lookup = AsyncMock()
    with patch.object(svc.FranchiseeSettlementService, "handle_settlement_webhook", lookup), \
         patch("routers.webhooks.log_webhook_event", AsyncMock()):
        await handle_settlement_event(
            "settlement.processed", {"settlement": {"entity": SETTLEMENT_EVENT}}
        )
        # Returned. The lookup has been scheduled but has not run yet.
        assert not lookup.await_count
        await asyncio.sleep(0.05)
    lookup.assert_awaited_once_with("settlement.processed", SETTLEMENT_EVENT)


@pytest.mark.asyncio
async def test_deferred_lookup_swallows_its_own_errors(client, monkeypatch):
    """A failing lookup must not surface as an unhandled task exception —
    the sweep is the guarantee, this is only the fast path."""
    from services import franchisee_settlement_service as svc

    monkeypatch.setattr(svc, "SETTLEMENT_LOOKUP_DELAY_SECONDS", 0)
    with patch.object(svc.FranchiseeSettlementService, "handle_settlement_webhook",
                      AsyncMock(side_effect=Exception("razorpay down"))):
        await svc.settlement_lookup_after_delay("settlement.processed", SETTLEMENT_EVENT)


# ------------------------------------------------- review findings, pinned --

@pytest.mark.asyncio
async def test_transfer_processed_redelivery_does_not_regress_a_settled_row(
    client, test_franchisee, test_charger, test_user
):
    """Finding 1. Razorpay redelivers transfer.processed on any timeout and
    the router does not dedupe. Once a row is SETTLED, a late redelivery must
    not walk it back — that reset transfer_processed_at, held it under the
    sweep floor for two more days, and showed a paid payout as unpaid."""
    settled_at = datetime(2026, 7, 22, tzinfo=UTC)
    e = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_regress", status=SettlementStatusEnum.SETTLED,
                     processed_at=datetime(2026, 7, 20, tzinfo=UTC))
    await CommissionLedgerEntry.filter(id=e.id).update(settled_at=settled_at, transfer_fee=Decimal("0.11"))

    await FranchiseeSettlementService.handle_transfer_webhook(
        "transfer.processed", _transfer("trf_regress", settlement_status=None, fees=999)
    )

    e = await CommissionLedgerEntry.get(id=e.id)
    assert e.settlement_status == SettlementStatusEnum.SETTLED
    assert e.settled_at == settled_at
    assert e.transfer_fee == Decimal("0.11")
    assert e.transfer_processed_at == datetime(2026, 7, 20, tzinfo=UTC)


@pytest.mark.asyncio
async def test_webhook_path_stamps_the_settlement_date_not_now(
    client, test_franchisee, test_charger, test_user
):
    """Finding 2. The list endpoint returns no nested settlement, but the
    webhook IS the settlement: its created_at must become settled_at. A
    redelivery 12 hours late must not freeze the wrong day."""
    e = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_dated", status=SettlementStatusEnum.TRANSFER_PROCESSED)
    with patch.object(rp_module.razorpay_service, "list_transfers_for_settlement",
                      AsyncMock(return_value=[_transfer("trf_dated")])):
        await FranchiseeSettlementService.handle_settlement_webhook("settlement.processed", SETTLEMENT_EVENT)

    e = await CommissionLedgerEntry.get(id=e.id)
    assert e.settlement_status == SettlementStatusEnum.SETTLED
    assert e.settled_at == datetime.fromtimestamp(SETTLEMENT_EVENT["created_at"], tz=UTC)
    assert (datetime.now(UTC) - e.settled_at) > timedelta(hours=1)


@pytest.mark.asyncio
async def test_webhook_path_refuses_a_failed_settlement(
    client, test_franchisee, test_charger, test_user
):
    """The attached settlement carries the event's own status. A
    settlement.processed whose entity says anything but processed advances
    nothing — the shared predicate sees one input shape on both paths."""
    e = await _entry(test_franchisee, test_charger, test_user,
                     transfer_id="trf_evfailed", status=SettlementStatusEnum.TRANSFER_PROCESSED)
    with patch.object(rp_module.razorpay_service, "list_transfers_for_settlement",
                      AsyncMock(return_value=[_transfer("trf_evfailed")])):
        await FranchiseeSettlementService.handle_settlement_webhook(
            "settlement.processed", {**SETTLEMENT_EVENT, "status": "failed"}
        )
    assert (await CommissionLedgerEntry.get(id=e.id)).settlement_status == SettlementStatusEnum.TRANSFER_PROCESSED


@pytest.mark.asyncio
async def test_reconciler_start_is_gated_on_route(client):
    """Finding 3. Same gate as stuck_payout_detector: a dev box restored from
    a production dump must not poll api.razorpay.com every six hours."""
    from services import settlement_reconciler as rec
    rec._reconciler = None
    with patch.object(rp_module.razorpay_service, "is_route_enabled", return_value=False):
        await rec.start_settlement_reconciler()
    assert rec._reconciler is None


@pytest.mark.asyncio
async def test_sweep_examines_newest_first_so_stuck_rows_cannot_starve_it(
    client, test_franchisee, test_charger, test_user
):
    """Finding 4. With a budget of 1, the row examined must be the NEWEST
    eligible one; a permanently-unsettleable old row must not sit at the head
    of every pass and block it."""
    old = datetime.now(UTC) - timedelta(days=30)
    newer = datetime.now(UTC) - timedelta(days=5)
    await _entry(test_franchisee, test_charger, test_user,
                 transfer_id="trf_ancient", status=SettlementStatusEnum.TRANSFER_PROCESSED, processed_at=old)
    fresh = await _entry(test_franchisee, test_charger, test_user,
                         transfer_id="trf_recent", status=SettlementStatusEnum.TRANSFER_PROCESSED, processed_at=newer)
    fetched = []

    async def fetch(transfer_id, **_):
        fetched.append(transfer_id)
        return _transfer(transfer_id, nested=NESTED_PROCESSED)

    with patch.object(rp_module.razorpay_service, "fetch_transfer", AsyncMock(side_effect=fetch)):
        counts = await reconcile_processed_transfers(limit=1)

    assert fetched == ["trf_recent"]
    assert counts["examined"] == 1 and counts["settled"] == 1
    assert (await CommissionLedgerEntry.get(id=fresh.id)).settlement_status == SettlementStatusEnum.SETTLED


def test_settlement_tuning_is_ordered():
    """Finding 10. The alarm must sit strictly past the sweep floor, or every
    healthy row inside the floor pages the operator. Asserted at import in
    policy.py; pinned here so the assertion cannot be quietly removed."""
    from policy import SETTLEMENT_AGE_FLOOR_DAYS, STUCK_PROCESSED_DAYS
    from services.settlement_reconciler import AGE_FLOOR_DAYS
    from services.stuck_payout_detector import STUCK_PROCESSED_DAYS as detector_days
    assert AGE_FLOOR_DAYS == SETTLEMENT_AGE_FLOOR_DAYS < STUCK_PROCESSED_DAYS == detector_days
