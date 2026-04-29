"""Franchisee settlement engine.

After each charging session completes billing, this service:
1. Resolves the franchisee (charger -> station -> franchisee)
2. Calculates the settlement split (commission, TDS, transfer fee)
3. Creates a CommissionLedgerEntry
4. Optionally initiates a Razorpay Route transfer (if enabled)
"""

import logging
import os
from datetime import datetime, timedelta
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
MIN_TRANSFER_AMOUNT = Decimal(
    os.getenv("MINIMUM_TRANSFER_AMOUNT", "1.00")
)
MAX_TRANSFER_RETRIES = int(os.getenv("MAX_TRANSFER_RETRIES", "3"))


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
        tds_amount = (
            net_excl_gst * tds_pct / Decimal("100")
        ).quantize(TWO_DP, ROUND_HALF_UP)
        franchisee_payout = (
            net_excl_gst - platform_commission - tds_amount
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
            pg_fee = (
                (qr_payment.razorpay_commission or Decimal("0"))
                + (qr_payment.razorpay_gst or Decimal("0"))
            )
            gst_collected = qr_payment.gst_amount or Decimal("0")
            razorpay_payment_id = qr_payment.razorpay_payment_id
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
            tariff_rate_per_kwh=tariff_rate.quantize(TWO_DP, ROUND_HALF_UP),
            idempotency_key=idempotency_key,
        )

        logger.info(
            "Settlement created: txn=%s franchisee=%s payout=%.2f method=%s",
            transaction_id, franchisee.id, calc["franchisee_payout"],
            payment_method,
        )

        # Attempt transfer if Route is enabled and franchisee is active
        if (
            franchisee.status == FranchiseeStatusEnum.ACTIVE
            and franchisee.razorpay_account_id
            and calc["franchisee_payout"] >= MIN_TRANSFER_AMOUNT
        ):
            await FranchiseeSettlementService.initiate_transfer(entry)

        return entry

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

        # Razorpay enforces a 24-hour cooling period after a linked account
        # is activated before transfers can be initiated. Park as ON_HOLD
        # so retry_failed_transfers picks it up after the window closes.
        if franchisee.activated_at:
            cooling_until = franchisee.activated_at + timedelta(hours=24)
            if datetime.utcnow() < cooling_until.replace(tzinfo=None):
                await CommissionLedgerEntry.filter(id=entry.id).update(
                    settlement_status=SettlementStatusEnum.ON_HOLD,
                    failure_reason="cooling_period",
                )
                logger.info(
                    "Transfer for entry %s held: 24h cooling period until %s",
                    entry.id, cooling_until,
                )
                return False

        amount_paise = int(entry.franchisee_payout * 100)
        if amount_paise < 100:  # Razorpay minimum Rs.1
            return False

        try:
            result = razorpay_service.create_transfer(
                account_id=franchisee.razorpay_account_id,
                amount_paise=amount_paise,
                notes={
                    "transaction_id": str(entry.transaction_id),
                    "franchisee_id": str(franchisee.id),
                    "idempotency_key": entry.idempotency_key,
                },
                idempotency_key=entry.idempotency_key,
            )

            await CommissionLedgerEntry.filter(id=entry.id).update(
                settlement_status=SettlementStatusEnum.TRANSFER_INITIATED,
                razorpay_transfer_id=result.get("id"),
                transfer_initiated_at=datetime.utcnow(),
            )
            logger.info(
                "Transfer initiated: entry=%s transfer=%s",
                entry.id, result.get("id"),
            )
            return True

        except Exception as e:
            logger.error(
                "Transfer failed for entry %s: %s", entry.id, e
            )
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
            await CommissionLedgerEntry.filter(id=entry.id).update(
                settlement_status=SettlementStatusEnum.TRANSFER_PROCESSED,
                transfer_processed_at=datetime.utcnow(),
            )
            logger.info("Transfer processed: %s", transfer_id)

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

        A single settlement can cover multiple transfers. We advance every
        ledger entry whose ``razorpay_transfer_id`` is listed in the
        settlement entity, and capture the per-transfer fee (Razorpay's
        actual transfer charge) when provided.
        """
        if event_type != "settlement.processed":
            return

        transfer_ids = []
        # Known Razorpay shapes: a list of transfer ids, or a list of
        # {id, fees, tax} dicts. Handle both defensively.
        raw_transfers = settlement_data.get("transfers") or []
        for t in raw_transfers:
            if isinstance(t, str):
                transfer_ids.append(t)
            elif isinstance(t, dict) and t.get("id"):
                transfer_ids.append(t["id"])

        if not transfer_ids:
            logger.info(
                "settlement.processed with no transfers listed: %s",
                settlement_data.get("id"),
            )
            return

        # Build a map transfer_id -> (fees_rupees, tax_rupees) when available
        fee_by_transfer: Dict[str, Decimal] = {}
        for t in raw_transfers:
            if isinstance(t, dict) and t.get("id"):
                fee_paise = t.get("fees")
                tax_paise = t.get("tax") or 0
                if fee_paise is not None:
                    total = Decimal(str(fee_paise)) + Decimal(str(tax_paise))
                    fee_by_transfer[t["id"]] = (total / Decimal("100")).quantize(
                        TWO_DP, ROUND_HALF_UP
                    )

        entries = await CommissionLedgerEntry.filter(
            razorpay_transfer_id__in=transfer_ids
        ).all()
        now = datetime.utcnow()
        for entry in entries:
            updates = {
                "settlement_status": SettlementStatusEnum.SETTLED,
                "settled_at": now,
            }
            fee = fee_by_transfer.get(entry.razorpay_transfer_id)
            if fee is not None:
                updates["transfer_fee"] = fee
            await CommissionLedgerEntry.filter(id=entry.id).update(**updates)
            logger.info(
                "Settlement processed: entry=%s transfer=%s fee=%s",
                entry.id, entry.razorpay_transfer_id, fee or "n/a",
            )

    @staticmethod
    async def retry_failed_transfers(franchisee_id: Optional[int] = None):
        """Retry FAILED and ON_HOLD entries that haven't exceeded max
        retries. ON_HOLD entries are picked up after a subsequent
        ``account.funds_unhold`` / ``account.activated`` webhook flips
        the gating flags back on."""
        query = CommissionLedgerEntry.filter(
            settlement_status__in=[
                SettlementStatusEnum.FAILED,
                SettlementStatusEnum.ON_HOLD,
            ],
            retry_count__lt=MAX_TRANSFER_RETRIES,
        )
        if franchisee_id:
            query = query.filter(franchisee_id=franchisee_id)

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
