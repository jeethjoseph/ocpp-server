"""Franchisee settlement engine.

After each charging session completes billing, this service:
1. Resolves the franchisee (charger -> station -> franchisee)
2. Calculates the settlement split (commission, TDS, transfer fee)
3. Creates a CommissionLedgerEntry
4. Optionally initiates a Razorpay Route transfer (if enabled)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict

from tortoise.transactions import atomic

from models import (
    Transaction,
    Charger,
    ChargingStation,
    Franchisee,
    FranchiseeStatusEnum,
    CommissionLedgerEntry,
    SettlementStatusEnum,
    QRPayment,
    WalletTransaction,
    TransactionTypeEnum,
)

logger = logging.getLogger("ocpp-server")

TWO_DP = Decimal("0.01")


def transfer_fee_rupees(transfer: dict) -> Optional[Decimal]:
    """Razorpay's actual Route charge for one transfer, in rupees.

    ``fees`` and ``tax`` are top-level integer paise on the Transfer entity,
    present from ``transfer.processed`` onward. None when the entity carries
    no ``fees`` at all, so a caller can leave an existing value untouched.
    This is VoltLync's own cost, debited from the platform — it is NOT the
    customer-borne Gateway fee and must never be netted against the
    franchisee payout.
    """
    fees = transfer.get("fees")
    if fees is None:
        return None
    total = Decimal(str(fees)) + Decimal(str(transfer.get("tax") or 0))
    return (total / Decimal("100")).quantize(TWO_DP, ROUND_HALF_UP)


def settled_at_from(recipient_settlement: Optional[dict]) -> datetime:
    """When the linked-account settlement actually ran.

    Taken from the nested settlement's ``created_at`` when the caller has it,
    so a backfill of rows that settled in June records June, not the day the
    sweep finally noticed. Falls back to now when the caller only has the
    transfer list, which carries no nested settlement.
    """
    epoch = (recipient_settlement or {}).get("created_at")
    if epoch:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    return datetime.now(timezone.utc)


# How long the settlement.processed lookup waits after the webhook is acked.
# Not a courtesy — insurance against read-after-write lag on Razorpay's side,
# where the transfers may not yet be indexed under the settlement id at the
# instant the event fires. Read at call time (not bound as a default) so tests
# can shrink it.
SETTLEMENT_LOOKUP_DELAY_SECONDS = 60


async def settlement_lookup_after_delay(event_type: str, settlement_data: dict) -> None:
    """Run the settlement lookup off the webhook's response path.

    The router acks Razorpay first and schedules this. Before that change the
    lookup ran inline while Razorpay waited on our 200 — and a slow Razorpay
    API at the moment their webhook fires (the two correlate) exceeded their
    timeout, triggered a redelivery, and ran again. Idempotent, so nothing
    corrupted; but a retry storm waiting for a degraded afternoon.

    In-process, so a restart in the window loses it. Deliberately accepted:
    the reconciliation sweep is the guarantee, this is the fast path.
    """
    import asyncio
    await asyncio.sleep(SETTLEMENT_LOOKUP_DELAY_SECONDS)
    try:
        await FranchiseeSettlementService.handle_settlement_webhook(
            event_type, settlement_data
        )
    except Exception as exc:
        logger.error(
            "Deferred settlement lookup failed for %s: %s",
            settlement_data.get("id"), exc, exc_info=True,
        )
FOUR_DP = Decimal("0.0001")
MIN_TRANSFER_AMOUNT = Decimal(
    os.getenv("MINIMUM_TRANSFER_AMOUNT", "1.00")
)
MAX_TRANSFER_RETRIES = int(os.getenv("MAX_TRANSFER_RETRIES", "3"))
# Wallet-funded charging sessions have no per-session Razorpay payment_id, so
# settling them to a franchisee requires the standalone POST /v1/transfers
# endpoint (Razorpay-side "Direct Transfer" feature). Until that feature is
# activated on the merchant account, leave this flag off — wallet-session
# ledger entries are parked in ON_HOLD with failure_reason
# ``wallet_settlement_not_activated`` and the retry loop skips them. When the
# feature is activated, flip to "true" and the existing retry sweep picks
# them up. QR (UPI) settlements are unaffected by this flag.
WALLET_SETTLEMENT_ENABLED = os.getenv("WALLET_SETTLEMENT_ENABLED", "false").lower() == "true"
WALLET_HOLD_REASON = "wallet_settlement_not_activated"
# Tolerance for the gross == sum-of-components sanity check. A 2-paisa
# window absorbs DECIMAL rounding across six successive quantize() calls
# in calculate_settlement. Tighten to 0.01 once we confirm in production.
SUM_TOLERANCE = Decimal("0.02")
# settlement_status values for which a transfer attempt is allowed.
_TRANSFERABLE_STATUSES = {
    SettlementStatusEnum.PENDING,
    SettlementStatusEnum.ON_HOLD,
    SettlementStatusEnum.FAILED,
}


class FranchiseeSettlementService:

    @staticmethod
    async def resolve_franchisee(charger_id: int) -> Optional[Franchisee]:
        """Resolve charger -> station -> franchisee. Returns None if
        the station is VoltLync-owned (no franchisee)."""
        charger = await Charger.filter(id=charger_id).first()
        if not charger:
            return None
        station = await ChargingStation.filter(
            id=charger.station_id
        ).first()
        if not station or not station.franchisee_id:
            return None
        return await Franchisee.filter(id=station.franchisee_id).first()

    @staticmethod
    def calculate_settlement(
        gross_amount: Decimal,
        refund_amount: Decimal,
        pg_fee_amount: Decimal,
        gst_collected: Decimal,
        commission_pct: Decimal,
        tds_pct: Decimal,
    ) -> Dict[str, Decimal]:
        """Pure calculation -- no side effects.

        ``transfer_fee`` is populated after-the-fact from the
        ``settlement.processed`` webhook (the actual fee Razorpay charges
        for the Route transfer). It is NOT deducted from
        ``franchisee_payout`` at calc time.
        """
        net_amount = (gross_amount - refund_amount - pg_fee_amount).quantize(
            TWO_DP, ROUND_HALF_UP
        )
        net_excl_gst = (net_amount - gst_collected).quantize(
            TWO_DP, ROUND_HALF_UP
        )
        platform_commission = (
            net_excl_gst * commission_pct / Decimal("100")
        ).quantize(TWO_DP, ROUND_HALF_UP)
        # TDS is withheld from the franchisee's earning (post-commission),
        # not from the pre-commission net. Withholding on a base that
        # includes the platform's own commission would over-deduct from
        # the franchisee on every settlement.
        franchisee_earning = (
            net_excl_gst - platform_commission
        ).quantize(TWO_DP, ROUND_HALF_UP)
        tds_amount = (
            franchisee_earning * tds_pct / Decimal("100")
        ).quantize(TWO_DP, ROUND_HALF_UP)
        franchisee_payout = (
            franchisee_earning - tds_amount
        ).quantize(TWO_DP, ROUND_HALF_UP)

        return {
            "net_amount": net_amount,
            "gst_collected": gst_collected,
            "net_excl_gst": net_excl_gst,
            "platform_commission": platform_commission,
            "tds_amount": tds_amount,
            "transfer_fee": Decimal("0.00"),  # filled post-settlement
            "franchisee_payout": franchisee_payout,
        }

    @staticmethod
    @atomic()
    async def process_settlement(
        transaction_id: int,
    ) -> Optional[CommissionLedgerEntry]:
        """Main entry point. Called after billing completes."""

        transaction = await Transaction.filter(id=transaction_id).first()
        if not transaction:
            logger.warning("Settlement: transaction %s not found", transaction_id)
            return None

        # Resolve franchisee
        franchisee = await FranchiseeSettlementService.resolve_franchisee(
            transaction.charger_id
        )
        if not franchisee:
            return None  # VoltLync-owned station

        # Idempotency: check if ledger entry already exists
        idempotency_key = f"txn_{transaction_id}"
        existing = await CommissionLedgerEntry.filter(
            idempotency_key=idempotency_key
        ).first()
        if existing:
            logger.info("Settlement already exists for txn %s", transaction_id)
            return existing

        # Skip zero-energy sessions
        energy = transaction.energy_consumed_kwh or 0
        if energy <= 0:
            logger.info("Zero energy for txn %s, skipping settlement", transaction_id)
            return None

        # Determine payment method and gather amounts
        qr_payment = await QRPayment.filter(
            transaction_id=transaction_id
        ).first()

        if qr_payment:
            payment_method = "QR_UPI"
            gross_amount = qr_payment.amount_paid
            refund_amount = qr_payment.refund_amount or Decimal("0")
            # Ledger uses the ACTUAL gateway fee (ADR 0026), the same value on
            # the customer's invoice gateway line and deducted from the refund.
            # Because the gateway is added to the bill and subtracted here, it
            # cancels out of the franchisee payout — net_excl_gst equals the
            # invoice energy_taxable line (= energy_kWh × base_rate). Reverses
            # ADR 0001's synthetic-ledger amendment (safe: fee now cancels).
            pg_fee = (qr_payment.platform_fee or Decimal("0"))
            gst_collected = qr_payment.gst_amount or Decimal("0")
            razorpay_payment_id = qr_payment.razorpay_payment_id
            # Reporting snapshot only — payout is driven by net_excl_gst, not this
            # rate. In the rare over-consumption-capped case `energy` is the full
            # metered kWh while `energy_cost` is the capped charge, so this rate
            # reads slightly below the tariff base rate and disagrees with the
            # invoice's billable-kWh rate. Accepted (ADR 0026 residual #4).
            tariff_rate = qr_payment.energy_cost / Decimal(str(energy)) if qr_payment.energy_cost and energy else Decimal("0")
        else:
            payment_method = "WALLET"
            gross_amount = transaction.total_billed or Decimal("0")
            refund_amount = Decimal("0")
            pg_fee = Decimal("0")  # PG fee absorbed during wallet top-up
            gst_collected = transaction.gst_amount or Decimal("0")
            razorpay_payment_id = None
            tariff_rate = (
                transaction.energy_charge / Decimal(str(energy))
                if transaction.energy_charge and energy
                else Decimal("0")
            )

        if gross_amount <= 0:
            logger.info("Zero gross for txn %s, skipping settlement", transaction_id)
            return None

        # Freeze commission and TDS rates at transaction time
        commission_pct = franchisee.commission_percent
        tds_pct = franchisee.tds_rate_percent

        # Calculate split
        calc = FranchiseeSettlementService.calculate_settlement(
            gross_amount=gross_amount,
            refund_amount=refund_amount,
            pg_fee_amount=pg_fee,
            gst_collected=gst_collected,
            commission_pct=commission_pct,
            tds_pct=tds_pct,
        )

        # Resolve optional wallet transaction link
        wallet_txn = None
        if payment_method == "WALLET":
            wallet_txn = await WalletTransaction.filter(
                charging_transaction_id=transaction_id,
                type=TransactionTypeEnum.CHARGE_DEDUCT,
            ).first()

        # Create ledger entry
        entry = await CommissionLedgerEntry.create(
            transaction=transaction,
            franchisee=franchisee,
            qr_payment=qr_payment,
            wallet_transaction=wallet_txn,
            gross_amount=gross_amount,
            payment_method=payment_method,
            razorpay_payment_id=razorpay_payment_id,
            refund_amount=refund_amount,
            pg_fee_amount=pg_fee,
            net_amount=calc["net_amount"],
            gst_collected=calc["gst_collected"],
            net_excl_gst=calc["net_excl_gst"],
            commission_percent=commission_pct,
            platform_commission=calc["platform_commission"],
            tds_rate_percent=tds_pct,
            tds_amount=calc["tds_amount"],
            transfer_fee=calc["transfer_fee"],
            franchisee_payout=calc["franchisee_payout"],
            energy_consumed_kwh=energy,
            tariff_rate_per_kwh=tariff_rate.quantize(FOUR_DP, ROUND_HALF_UP),
            idempotency_key=idempotency_key,
        )

        logger.info(
            "Settlement created: txn=%s franchisee=%s payout=%.2f method=%s",
            transaction_id, franchisee.id, calc["franchisee_payout"],
            payment_method,
        )

        # Sub-floor payouts never transfer: mark terminal so the retry
        # sweep doesn't pick them up and PENDING keeps its "awaiting
        # transfer attempt" meaning.
        if calc["franchisee_payout"] < MIN_TRANSFER_AMOUNT:
            await CommissionLedgerEntry.filter(id=entry.id).update(
                settlement_status=SettlementStatusEnum.BELOW_THRESHOLD,
            )
        elif (
            franchisee.status == FranchiseeStatusEnum.ACTIVE
            and franchisee.razorpay_account_id
        ):
            await FranchiseeSettlementService.initiate_transfer(entry)

        return entry

    @staticmethod
    async def _validate_ledger_for_transfer(
        entry: CommissionLedgerEntry,
        franchisee: Franchisee,
    ) -> Optional[str]:
        """Foolproof pre-flight checks before any money moves.

        Returns ``None`` when the entry is safe to transfer, or a
        ``failure_reason`` string when a check fails. Callers should
        mark the entry FAILED with this reason and NOT increment
        ``retry_count`` — math/state failures require admin
        investigation, not blind retry.
        """
        if entry.franchisee_payout <= Decimal("0"):
            return "validation_payout_not_positive"

        if entry.franchisee_payout > entry.gross_amount - entry.refund_amount:
            return "validation_payout_exceeds_net_paid"

        components_sum = (
            entry.franchisee_payout
            + entry.platform_commission
            + entry.tds_amount
            + entry.gst_collected
            + entry.pg_fee_amount
            + entry.refund_amount
        )
        if abs(components_sum - entry.gross_amount) > SUM_TOLERANCE:
            return "validation_components_do_not_sum_to_gross"

        if entry.settlement_status not in _TRANSFERABLE_STATUSES:
            return f"validation_terminal_status_{entry.settlement_status.value}"

        if (
            not franchisee.razorpay_account_id
            or franchisee.id != entry.franchisee_id
        ):
            return "validation_franchisee_account_mismatch"

        if entry.razorpay_payment_id:
            collision = await CommissionLedgerEntry.filter(
                razorpay_payment_id=entry.razorpay_payment_id,
                razorpay_transfer_id__not_isnull=True,
            ).exclude(id=entry.id).first()
            if collision:
                return "validation_payment_id_already_transferred"

        return None

    @staticmethod
    async def initiate_transfer(
        entry: CommissionLedgerEntry,
    ) -> bool:
        """Attempt Razorpay Route transfer. Returns True on success.

        Skips (and marks ON_HOLD) when the franchisee has
        ``funds_on_hold=True`` or ``transfers_enabled=False`` — both flags
        are driven by ``account.*`` webhooks. A later
        ``account.funds_unhold`` / ``account.activated`` will trigger a
        retry via ``retry_failed_transfers``.
        """
        from services.razorpay_service import razorpay_service

        if not razorpay_service.is_route_enabled():
            logger.info(
                "Route disabled, skipping transfer for entry %s", entry.id
            )
            return False

        franchisee = await Franchisee.filter(id=entry.franchisee_id).first()
        if not franchisee or not franchisee.razorpay_account_id:
            return False

        if franchisee.funds_on_hold or not franchisee.transfers_enabled:
            await CommissionLedgerEntry.filter(id=entry.id).update(
                settlement_status=SettlementStatusEnum.ON_HOLD,
                failure_reason=(
                    "funds_on_hold" if franchisee.funds_on_hold
                    else "transfers_disabled"
                ),
            )
            logger.info(
                "Transfer for entry %s held: funds_on_hold=%s transfers_enabled=%s",
                entry.id, franchisee.funds_on_hold, franchisee.transfers_enabled,
            )
            return False

        # Wallet-session gate. Wallet entries have no razorpay_payment_id and
        # require POST /v1/transfers, which is a separately-activated Razorpay
        # feature. Park ON_HOLD until WALLET_SETTLEMENT_ENABLED is flipped on;
        # `retry_failed_transfers` filters these out so the loop doesn't churn.
        if entry.razorpay_payment_id is None and not WALLET_SETTLEMENT_ENABLED:
            await CommissionLedgerEntry.filter(id=entry.id).update(
                settlement_status=SettlementStatusEnum.ON_HOLD,
                failure_reason=WALLET_HOLD_REASON,
            )
            logger.info(
                "Transfer for entry %s held: wallet settlement disabled by env flag",
                entry.id,
            )
            return False

        # Razorpay enforces a 24-hour cooling period after a linked account
        # is activated before transfers can be initiated. Park as ON_HOLD
        # so retry_failed_transfers picks it up after the window closes.
        if franchisee.activated_at:
            cooling_until = franchisee.activated_at + timedelta(hours=24)
            if datetime.now(timezone.utc) < cooling_until:
                await CommissionLedgerEntry.filter(id=entry.id).update(
                    settlement_status=SettlementStatusEnum.ON_HOLD,
                    failure_reason="cooling_period",
                )
                logger.info(
                    "Transfer for entry %s held: 24h cooling period until %s",
                    entry.id, cooling_until,
                )
                return False

        # Foolproof commission-math + state checks. Math/state failures
        # are NOT retried — they require admin investigation.
        validation_failure = (
            await FranchiseeSettlementService._validate_ledger_for_transfer(
                entry, franchisee
            )
        )
        if validation_failure:
            # Saturate retry_count so the retry sweep
            # (settlement_status=FAILED AND retry_count<MAX_TRANSFER_RETRIES)
            # stops re-picking the entry. The validator's contract is
            # "admin must investigate"; without this the entry cycles
            # through the sweep every interval and the Sentry log fires
            # on every tick. Stuck-payout detector still surfaces these
            # via its FAILED+retry_count>=max branch.
            await CommissionLedgerEntry.filter(id=entry.id).update(
                settlement_status=SettlementStatusEnum.FAILED,
                failure_reason=validation_failure,
                retry_count=MAX_TRANSFER_RETRIES,
            )
            logger.warning(
                "Transfer rejected for entry %s by validator: %s",
                entry.id, validation_failure,
            )
            return False

        amount_paise = int(entry.franchisee_payout * 100)
        if amount_paise < 100:  # Razorpay minimum Rs.1
            return False

        notes = {
            "transaction_id": str(entry.transaction_id),
            "ledger_entry_id": str(entry.id),
            "franchisee_id": str(franchisee.id),
            "voltlync_payment_id": entry.razorpay_payment_id or "wallet",
            "idempotency_key": entry.idempotency_key,
        }

        # Atomic claim: flip status to TRANSFER_INITIATED conditional on the
        # row still being in a transferable state. Closes the read-then-write
        # race a concurrent webhook or sweep could exploit between
        # ``_validate_ledger_for_transfer`` and the Razorpay call. If 0 rows
        # update, another worker won — bail without contacting Razorpay.
        claim_time = datetime.now(timezone.utc)
        claimed = await CommissionLedgerEntry.filter(
            id=entry.id,
            settlement_status__in=list(_TRANSFERABLE_STATUSES),
        ).update(
            settlement_status=SettlementStatusEnum.TRANSFER_INITIATED,
            transfer_initiated_at=claim_time,
            # Clear any stale failure from a previous attempt — a successful
            # retry shouldn't leave the old error visible.
            failure_reason=None,
        )
        if not claimed:
            logger.info(
                "Entry %s: atomic claim lost (status changed mid-flight) — skipping transfer.",
                entry.id,
            )
            return False

        try:
            if entry.razorpay_payment_id:
                # QR session — payment-based transfer (no on-demand activation
                # needed, captured-amount is the only Razorpay-side gate).
                # idempotency_key guards against double-transfer when an
                # earlier POST timed out before we recorded the transfer id:
                # Razorpay returns the original response on key collision.
                result = await razorpay_service.create_payment_transfer(
                    payment_id=entry.razorpay_payment_id,
                    account_id=franchisee.razorpay_account_id,
                    amount_paise=amount_paise,
                    notes=notes,
                    franchisee_id=franchisee.id,
                    idempotency_key=entry.idempotency_key,
                )
            else:
                # Wallet session — direct transfer from platform balance.
                # Requires Razorpay support to activate ``POST /v1/transfers``.
                result = await razorpay_service.create_transfer(
                    account_id=franchisee.razorpay_account_id,
                    amount_paise=amount_paise,
                    notes=notes,
                    idempotency_key=entry.idempotency_key,
                )

            # Status + transfer_initiated_at were set by the atomic claim;
            # just record the Razorpay-side artefacts.
            updates = {"razorpay_transfer_id": result.get("id")}
            # Capture fees from the synchronous POST response when present
            # (settlement.processed will overwrite later if Razorpay sends
            # an updated value, but bare-id settlement payloads can leave
            # this 0.00 forever, so prefer to grab it now).
            fee_paise = result.get("fees")
            tax_paise = result.get("tax") or 0
            if fee_paise is not None:
                total_paise = Decimal(str(fee_paise)) + Decimal(str(tax_paise))
                updates["transfer_fee"] = (total_paise / Decimal("100")).quantize(
                    TWO_DP, ROUND_HALF_UP
                )
            await CommissionLedgerEntry.filter(id=entry.id).update(**updates)
            logger.info(
                "Transfer initiated: entry=%s transfer=%s",
                entry.id, result.get("id"),
            )
            return True

        except Exception as e:
            logger.error(
                "Transfer failed for entry %s: %s", entry.id, e
            )
            # Revert the optimistic claim. We own the row's status during
            # this function (claim → Razorpay → revert/finalize), so an
            # unconditional flip back to FAILED is safe.
            await CommissionLedgerEntry.filter(id=entry.id).update(
                settlement_status=SettlementStatusEnum.FAILED,
                failure_reason=str(e)[:500],
                retry_count=entry.retry_count + 1,
            )
            return False

    @staticmethod
    async def handle_transfer_webhook(
        event_type: str, transfer_data: dict
    ):
        """Handle transfer.processed / transfer.failed.

        Razorpay does not emit ``transfer.settled`` (that's
        ``settlement.processed``, see ``handle_settlement_webhook``) or
        ``transfer.reversed`` (reversals are surfaced via the transfer
        entity's ``amount_reversed`` / ``status`` fields).
        """
        transfer_id = transfer_data.get("id")
        if not transfer_id:
            return

        entry = await CommissionLedgerEntry.filter(
            razorpay_transfer_id=transfer_id
        ).first()
        if not entry:
            logger.warning("No ledger entry for transfer %s", transfer_id)
            return

        if event_type == "transfer.processed":
            updates = {
                "settlement_status": SettlementStatusEnum.TRANSFER_PROCESSED,
                "transfer_processed_at": datetime.now(timezone.utc),
                "failure_reason": None,
            }
            # The per-transfer Route fee lives on the transfer entity and is
            # already populated here — it never depended on the settlement
            # path. Captured now so it does not wait on a webhook that, for
            # three months, was never able to deliver it.
            fee = transfer_fee_rupees(transfer_data)
            if fee is not None:
                updates["transfer_fee"] = fee
            await CommissionLedgerEntry.filter(id=entry.id).update(**updates)
            logger.info("Transfer processed: %s fee=%s", transfer_id, fee)

        elif event_type == "transfer.failed":
            reason = transfer_data.get("error", {}).get(
                "description", "Unknown"
            )
            await CommissionLedgerEntry.filter(id=entry.id).update(
                settlement_status=SettlementStatusEnum.FAILED,
                failure_reason=reason[:500],
            )
            logger.error("Transfer failed: %s - %s", transfer_id, reason)

    @staticmethod
    async def handle_settlement_webhook(
        event_type: str, settlement_data: dict
    ):
        """Handle settlement.processed for linked-account settlements.

        The webhook is a TRIGGER, not a manifest. Its entity carries only the
        settlement's own ``id, amount, status, fees, tax, utr, created_at`` —
        verified against 202 production payloads and against Razorpay's
        documented sample — and never a list of the transfers it paid. The
        earlier version of this handler read a ``transfers`` array that does
        not exist, logged at INFO and returned, and so no ledger entry ever
        reached SETTLED between June and September 2026 (377 rows, ₹18,130).

        The documented second half is ``GET /v1/transfers?recipient_settlement_id=``,
        whose parameter Razorpay defines as "obtained from the
        settlement.processed webhook payload". Link direction is
        transfer → settlement; we ask the transfers which settlement paid them.

        An empty answer is NOT a failure. The platform receives its own bank
        settlements under this same event name, and those cover no Route
        transfers. Silence, at INFO, is the correct response to one of those.
        """
        if event_type != "settlement.processed":
            return
        settlement_id = settlement_data.get("id")
        if not settlement_id:
            logger.warning("settlement.processed without an id; ignoring")
            return

        from services.razorpay_service import razorpay_service
        transfers = await razorpay_service.list_transfers_for_settlement(settlement_id)
        if not transfers:
            logger.info(
                "settlement.processed %s covers no Route transfers — "
                "platform-own settlement, nothing to advance",
                settlement_id,
            )
            return

        # This settlement's own status is what the event announced; the
        # nested object is not returned by the list endpoint, so pass it in.
        processed = (settlement_data.get("status") or "processed") == "processed"
        settled = 0
        for transfer in transfers:
            if await FranchiseeSettlementService.settle_from_transfer(
                transfer, settlement_processed=processed
            ):
                settled += 1
        logger.info(
            "settlement.processed %s: %s transfer(s) listed, %s ledger row(s) settled",
            settlement_id, len(transfers), settled,
        )

    @staticmethod
    async def settle_from_transfer(
        transfer: dict, *, settlement_processed: Optional[bool] = None
    ) -> bool:
        """Advance one ledger row to SETTLED from a Transfer entity, if it is.

        Shared by the webhook path and the reconciliation sweep so the two can
        never disagree about what "settled" means. The predicate is strict on
        purpose: ``settlement_status == "settled"`` alone is not enough, because
        the settlement a transfer joined can itself have ``status: failed``.
        Money is recorded as landed only when the nested recipient settlement
        says ``processed`` — or, on the webhook path, when the event we are
        acting on already announced that for this settlement id.

        Returns True only when a row was actually moved. Idempotent: an
        already-SETTLED row is left untouched so ``settled_at`` and the fee are
        frozen at first observation, which is what makes Razorpay's webhook
        redelivery harmless.
        """
        transfer_id = transfer.get("id")
        if not transfer_id or transfer.get("settlement_status") != "settled":
            return False
        nested = transfer.get("recipient_settlement")
        if nested is not None:
            if nested.get("status") != "processed":
                return False
        elif not settlement_processed:
            return False

        entry = await CommissionLedgerEntry.filter(
            razorpay_transfer_id=transfer_id
        ).exclude(settlement_status=SettlementStatusEnum.SETTLED).first()
        if not entry:
            return False

        updates = {
            "settlement_status": SettlementStatusEnum.SETTLED,
            "settled_at": settled_at_from(nested),
            "failure_reason": None,
        }
        fee = transfer_fee_rupees(transfer)
        if fee is not None:
            updates["transfer_fee"] = fee
        await CommissionLedgerEntry.filter(id=entry.id).update(**updates)
        logger.info(
            "Settled: entry=%s transfer=%s settlement=%s fee=%s",
            entry.id, transfer_id,
            transfer.get("recipient_settlement_id") or "n/a", fee if fee is not None else "n/a",
        )
        return True

    @staticmethod
    async def retry_failed_transfers(franchisee_id: Optional[int] = None):
        """Retry FAILED and ON_HOLD entries that haven't exceeded max
        retries. ON_HOLD entries are picked up after a subsequent
        ``account.funds_unhold`` / ``account.activated`` webhook flips
        the gating flags back on.

        When ``WALLET_SETTLEMENT_ENABLED`` is false, wallet-session entries
        (no razorpay_payment_id) are excluded from the sweep so the loop
        doesn't churn against the same broken endpoint every cycle. When the
        flag is later flipped on, this filter disappears and those entries
        are picked up automatically by the next sweep.
        """
        query = CommissionLedgerEntry.filter(
            settlement_status__in=[
                SettlementStatusEnum.FAILED,
                SettlementStatusEnum.ON_HOLD,
            ],
            retry_count__lt=MAX_TRANSFER_RETRIES,
        )
        if franchisee_id:
            query = query.filter(franchisee_id=franchisee_id)
        if not WALLET_SETTLEMENT_ENABLED:
            query = query.filter(razorpay_payment_id__not_isnull=True)

        entries = await query.all()
        success_count = 0
        for entry in entries:
            if await FranchiseeSettlementService.initiate_transfer(entry):
                success_count += 1

        logger.info(
            "Retry complete: %d/%d transfers succeeded",
            success_count, len(entries),
        )
        return success_count, len(entries)
