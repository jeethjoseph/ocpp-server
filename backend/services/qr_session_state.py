"""Single source of truth for the customer-facing QR session sub-state.

Three places used to reason independently about "is this QR session active?":
    - QRPaymentService.process_qr_session_billing (status filter at finalize)
    - The stale-payment watchdog (status + age filter)
    - The /api/public/qr-active-sessions endpoint (display classifier)

This module centralizes the customer-facing sub-state machine so the next
person to add a state (e.g. for a new payment method) updates one place.

The customer-facing sub-states are deliberately a different abstraction from
the internal QRPaymentStatusEnum / TransactionStatusEnum: customers don't care
about RUNNING vs STARTED, but they do care about "charging vs paused".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from models import QRPayment, QRPaymentStatusEnum, Transaction, TransactionStatusEnum


# Customer sub-states surfaced on /my-charges.
WAITING = "waiting"
CHARGING = "charging"
PAUSED = "paused"
STOPPING = "stopping"

_IN_USE_TXN_STATES = {
    TransactionStatusEnum.STARTED,
    TransactionStatusEnum.RUNNING,
}

# Transaction states that still count as "active" for the purpose of carrying
# a customer view. Anything past these (STOPPED / COMPLETED / FAILED / etc.) is
# terminal and excluded from the active-session view.
ACTIVE_TXN_STATES = {
    TransactionStatusEnum.PENDING_START,
    TransactionStatusEnum.STARTED,
    TransactionStatusEnum.RUNNING,
    TransactionStatusEnum.SUSPENDED,
    TransactionStatusEnum.PENDING_STOP,
}


def customer_sub_state(
    qr_payment: QRPayment,
    transaction: Optional[Transaction],
    *,
    stale_threshold_seconds: int,
) -> Optional[str]:
    """Map (QRPayment, Transaction) to a customer-facing sub-state.

    Returns one of `WAITING` / `CHARGING` / `PAUSED` / `STOPPING`, or `None`
    if the session is not in any "active" state (caller filters None).

    The `stale_threshold_seconds` gate matches the watchdog's stale-payment
    timeout — a PAID payment older than this is on the auto-refund path and
    not "active" any more from the customer's perspective.
    """
    if qr_payment.status == QRPaymentStatusEnum.PAID:
        age = (datetime.now(timezone.utc) - qr_payment.created_at).total_seconds()
        if age > stale_threshold_seconds:
            return None
        if transaction is None or transaction.transaction_status == TransactionStatusEnum.PENDING_START:
            return WAITING
        return None

    if qr_payment.status != QRPaymentStatusEnum.CHARGING or transaction is None:
        return None

    if transaction.transaction_status in _IN_USE_TXN_STATES:
        return CHARGING
    if transaction.transaction_status == TransactionStatusEnum.SUSPENDED:
        return PAUSED
    if transaction.transaction_status == TransactionStatusEnum.PENDING_STOP:
        return STOPPING
    return None
