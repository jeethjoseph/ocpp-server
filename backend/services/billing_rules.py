"""Shared, pure billing-classification rules for Charging Sessions.

Single source of truth for the ADR 0013 (amended 2026-06-24) non-billable
bands, imported by BOTH the wallet billing path (`wallet_service`) and the QR
billing path (`qr_payment_service`) so the predicate cannot drift between them.

CODE IS THE SOURCE OF TRUTH for the policy (ADR 0013 §Amendment). The bands,
keyed on `transaction_status` × `energy_consumed_kwh`:

    energy <= 0                          -> non-billable, ZERO-ENERGY (ADR 0002)
    FAILED and 0 < energy < 0.5 kWh      -> non-billable, FAULT-REFUND (ADR 0013)
    everything else (incl. COMPLETED and STOPPED sub-0.5)  -> BILLS

A STOPPED session (timeout / disconnect / sweep / force-stop via
`finalize_stopped_transaction`) is NEVER FAILED, so a STOPPED sub-0.5 kWh
session bills exactly like COMPLETED. Only the StatusNotification-driven
`_fail_transaction_with_billing` path produces FAILED and thus the fault-refund.

These helpers are intentionally tiny and side-effect-free. The DISTINCT reason
strings and the distinct actions (no-debit vs full-refund) stay at the call
sites; only the branching predicate is shared here.
"""
from decimal import Decimal

from models import Transaction, TransactionStatusEnum

# Minimum billable energy. Pre-amendment this was "minimum energy to bill";
# post-amendment (2026-06-24) it is the FAULT-REFUND CEILING — the maximum
# energy a FAILED session can have delivered and still be fully waived. A
# hardcoded policy constant on purpose (NOT an env var): changing it goes
# through code review + an ADR amendment, not a per-environment deploy edit.
# Strict `<` everywhere — exactly 0.5 kWh bills its TOTAL energy (a cliff, not
# an allowance). Single source of truth; re-exported from wallet_service for
# backwards compat with existing importers.
MIN_BILLABLE_ENERGY_KWH = Decimal("0.5")


def _energy_dec(transaction: Transaction) -> Decimal:
    """Normalize energy_consumed_kwh to Decimal, matching the historic call
    sites byte-for-byte: None/0 -> Decimal('0'), else Decimal(str(value))."""
    energy = transaction.energy_consumed_kwh
    return Decimal(str(energy)) if energy else Decimal("0")


def is_zero_energy(transaction: Transaction) -> bool:
    """True when no taxable supply occurred (energy <= 0). Full refund (QR) /
    no debit (wallet) under ADR 0002, regardless of status."""
    return _energy_dec(transaction) <= 0


def is_fault_refund(transaction: Transaction) -> bool:
    """True for the ADR 0013 fault-refund band: a FAILED session that delivered
    a trivial amount (0 < energy < MIN_BILLABLE_ENERGY_KWH). Keyed STRICTLY on
    transaction_status == FAILED — STOPPED/COMPLETED sub-0.5 sessions bill."""
    energy_dec = _energy_dec(transaction)
    return (
        transaction.transaction_status == TransactionStatusEnum.FAILED
        and 0 < energy_dec < MIN_BILLABLE_ENERGY_KWH
    )


def is_non_billable(transaction: Transaction) -> bool:
    """True when the session must NOT bill — either zero-energy (ADR 0002) or
    the fault-refund band (ADR 0013). Everything else bills from the first Wh."""
    return is_zero_energy(transaction) or is_fault_refund(transaction)
