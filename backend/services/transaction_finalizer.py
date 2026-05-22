"""
Transaction Finalizer Service

Single source of truth for stopping a transaction that timed out (rather than
being stopped by a normal StopTransaction OCPP message). Used by:

- ChargePoint._suspend_timeout (BootNotification suspend timeout)
- disconnect_handler._disconnect_suspend_timeout (charger disconnect timeout)
- disconnect_handler.sweep_stale_suspended_transactions (startup safety net)

Responsibilities (in order):
1. Calculate final energy from the latest MeterValue
2. Mark transaction STOPPED with end_time and stop_reason
3. Audit-log the transition
4. Process wallet billing (or skip if zero energy)
5. Process QR payment billing/refund (or full refund if zero energy)
6. Clean up zero-energy watchdog redis state
7. Clean up disconnect-flap counter

Idempotent against already-stopped transactions.
"""
import datetime
import logging
import os
from typing import Optional, Tuple

from models import Transaction, TransactionStatusEnum, MeterValue
from services.wallet_service import WalletService
from services.monitoring_service import OCPPMetrics
from crud import log_audit_event
from utils import safe_create_task

logger = logging.getLogger("ocpp-server")

# Defense-in-depth staleness threshold for transaction resume.
# If the gap between a txn's last activity and a resume attempt exceeds this,
# we finalize the txn (STALE_RECONNECT) instead of resuming. This only fires
# when the primary disconnect/suspend timer chain has failed — it must be
# larger than DISCONNECT_SUSPEND_TIMEOUT_SECONDS (180s) and SUSPEND_TIMEOUT_SECONDS
# (300s) to avoid racing with the existing finalize chain.
MAX_RESUME_GAP_SECONDS = int(os.environ.get("MAX_RESUME_GAP_SECONDS", "900"))


async def is_resume_too_stale(
    transaction: Transaction,
) -> Tuple[bool, Optional[float]]:
    """
    Decide whether a transaction's last activity is too stale to safely resume.

    Returns (is_stale, gap_seconds). gap_seconds is the age of the most recent
    activity signal we found, or None if we couldn't find any.

    Looks at the most recent of: suspended_at, latest MeterValue.created_at,
    falling back to start_time. Threshold is MAX_RESUME_GAP_SECONDS.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    candidates = []
    if transaction.suspended_at:
        candidates.append(transaction.suspended_at)
    latest_mv = await MeterValue.filter(
        transaction_id=transaction.id
    ).order_by("-created_at").first()
    if latest_mv:
        candidates.append(latest_mv.created_at)
    if not candidates and transaction.start_time:
        candidates.append(transaction.start_time)
    if not candidates:
        return False, None
    most_recent = max(candidates)
    gap = (now - most_recent).total_seconds()
    return gap > MAX_RESUME_GAP_SECONDS, gap


async def finalize_stopped_transaction(
    transaction: Transaction,
    stop_reason: str,
) -> None:
    """
    Finalize a transaction that was stopped by a timeout (not by a normal
    StopTransaction). Calculates energy, processes billing, cleans up state.

    Idempotent: if the transaction is already STOPPED/COMPLETED/BILLING_FAILED,
    this is a no-op.
    """
    # Idempotency guard — don't double-process
    terminal_states = {
        TransactionStatusEnum.STOPPED,
        TransactionStatusEnum.COMPLETED,
        TransactionStatusEnum.BILLING_FAILED,
        TransactionStatusEnum.FAILED,
    }
    if transaction.transaction_status in terminal_states:
        logger.info(
            f"finalize_stopped_transaction: txn {transaction.id} already "
            f"in terminal state {transaction.transaction_status}, skipping"
        )
        return

    previous_status = transaction.transaction_status

    # Step 1: calculate final energy from latest meter value
    await _calculate_final_energy(transaction)

    # Step 2: mark STOPPED
    transaction.transaction_status = TransactionStatusEnum.STOPPED
    transaction.stop_reason = stop_reason
    transaction.end_time = datetime.datetime.now(datetime.timezone.utc)
    await transaction.save()

    logger.info(
        f"🛑 Finalized transaction {transaction.id}: {stop_reason} "
        f"(was {previous_status}, energy={transaction.energy_consumed_kwh} kWh)"
    )

    # Step 3: audit log
    safe_create_task(log_audit_event(
        action="transaction.finalized",
        entity_type="transaction",
        entity_id=transaction.id,
        actor_type="system",
        changes={
            "previous_status": str(previous_status),
            "new_status": "STOPPED",
            "trigger": stop_reason,
            "energy_consumed_kwh": transaction.energy_consumed_kwh,
        },
    ))

    # Metric: record disconnect-driven stops separately for alerting
    if stop_reason == "DISCONNECT_TIMEOUT":
        try:
            charger_id = transaction.charger.charge_point_string_id if transaction.charger else "unknown"
        except Exception:
            charger_id = "unknown"
        safe_create_task(OCPPMetrics.record_disconnect_stopped(
            charger_id=charger_id,
            transaction_id=transaction.id,
            energy_kwh=float(transaction.energy_consumed_kwh or 0),
        ))

    # Step 4 + 5: process wallet billing and QR billing/refund
    await _process_billing(transaction)

    # Step 6: clean up zero-energy watchdog state
    try:
        from services.zero_energy_watchdog import clear_zero_energy_tracking
        await clear_zero_energy_tracking(transaction.id)
    except Exception as e:
        logger.debug(f"Zero-energy cleanup error (non-fatal) for txn {transaction.id}: {e}")

    # Step 7: clean up flap counter
    try:
        from services.disconnect_handler import _disconnect_reset_count
        _disconnect_reset_count.pop(transaction.id, None)
    except Exception as e:
        logger.debug(f"Flap counter cleanup error (non-fatal) for txn {transaction.id}: {e}")


async def _calculate_final_energy(transaction: Transaction) -> None:
    """
    Look up the latest MeterValue for this transaction and set
    end_meter_kwh + energy_consumed_kwh on the transaction object.
    Does NOT save — caller is responsible for that.
    """
    latest_meter_value = await MeterValue.filter(
        transaction_id=transaction.id
    ).order_by("-created_at").first()

    if latest_meter_value:
        transaction.end_meter_kwh = latest_meter_value.reading_kwh
        transaction.energy_consumed_kwh = (
            transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
        )
        logger.info(
            f"Calculated energy for txn {transaction.id}: "
            f"{transaction.energy_consumed_kwh} kWh "
            f"(start={transaction.start_meter_kwh}, end={transaction.end_meter_kwh})"
        )
    else:
        logger.warning(
            f"No meter values found for txn {transaction.id} — "
            f"energy_consumed_kwh will remain {transaction.energy_consumed_kwh}"
        )


async def _process_billing(transaction: Transaction) -> None:
    """
    Process wallet billing and QR refund for a finalized transaction.

    - Wallet billing: only if energy > 0. Failures move status to BILLING_FAILED.
    - QR billing: if energy > 0, run normal billing+refund. If energy = 0,
      run handle_charging_failure (full refund).
    """
    energy = transaction.energy_consumed_kwh

    # Wallet billing
    if energy is not None and energy > 0:
        try:
            success, message, billing_amount = await WalletService.process_transaction_billing(
                transaction.id
            )
            if success:
                logger.info(f"💰 Billed transaction {transaction.id}: ₹{billing_amount}")
            else:
                logger.warning(
                    f"💰 Billing failed for transaction {transaction.id}: {message}"
                )
        except Exception as e:
            logger.error(
                f"💰 Billing error for transaction {transaction.id}: {e}",
                exc_info=True,
            )
            await Transaction.filter(id=transaction.id).update(
                transaction_status=TransactionStatusEnum.BILLING_FAILED
            )
    else:
        logger.info(
            f"💰 No energy consumed for transaction {transaction.id} — skipping wallet billing"
        )

    # QR payment billing/refund
    try:
        from services.qr_payment_service import QRPaymentService
        if energy is not None and energy > 0:
            await QRPaymentService.process_qr_session_billing(transaction.id)
        else:
            await QRPaymentService.handle_charging_failure(transaction.id)
    except Exception as qr_err:
        logger.error(
            f"QR billing error for finalized transaction {transaction.id}: {qr_err}",
            exc_info=True,
        )

    # Franchisee settlement (fire-and-forget, non-blocking)
    try:
        from services.franchisee_settlement_service import FranchiseeSettlementService
        from utils import safe_create_task
        safe_create_task(
            FranchiseeSettlementService.process_settlement(transaction.id),
            name=f"settlement-txn-{transaction.id}",
        )
    except Exception as settle_err:
        logger.error(
            "Settlement trigger error for transaction %s: %s",
            transaction.id, settle_err,
        )

    # GST invoice generation (fire-and-forget)
    try:
        from services.invoice_service import InvoiceService
        from utils import safe_create_task
        safe_create_task(
            InvoiceService.generate_invoice(transaction.id),
            name=f"invoice-txn-{transaction.id}",
        )
    except Exception as inv_err:
        logger.error(
            "Invoice trigger error for transaction %s: %s",
            transaction.id, inv_err,
        )
