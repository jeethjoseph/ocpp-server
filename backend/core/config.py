"""Project-level configuration constants.

Single home for env-var-driven values that are read across multiple domains
(routers, services, startup validation). Domain-specific configuration stays
in the relevant service module — e.g. `QR_PAYMENT_PENDING_TIMEOUT` lives in
`services/qr_payment_service.py` because only QR payment code reads it.
"""
import logging
import os
from decimal import Decimal


# Synthetic platform-fee rate (%) — authoritative, drives every customer-facing
# calculation: budget cap, over-payment refund, invoice gateway-charges line,
# admin-form back-derivation. NOT a fallback; the actual Razorpay fee captured
# from the webhook is for ops/reconciliation only. See ADR 0001.
RAZORPAY_PLATFORM_FEE_PERCENT = Decimal(os.getenv("RAZORPAY_PLATFORM_FEE_PERCENT", "2.0"))


# Wallet charging gate — see ADR 0011. When false, NEW wallet sessions and
# top-ups are blocked: the two remote-start endpoints and the recharge endpoint
# return 403, so no unsettleable franchisee liability accrues while pooled
# multi-franchisee settlement is unbuilt. The backend flag is the source of
# truth (the frontend flag is cosmetic). Read at call time so a container
# restart toggles it with no rebuild. Default true so dev/existing envs are
# unaffected; only staging/prod set it false.
def wallet_charging_enabled() -> bool:
    """Whether new wallet sessions and top-ups are permitted. See ADR 0011."""
    return os.getenv("WALLET_CHARGING_ENABLED", "true").lower() == "true"


# Sanity bounds for RAZORPAY_PLATFORM_FEE_PERCENT (issue 03 / L2).
#
# Real-world Razorpay rates are 0–2% for UPI and up to ~3% for cards. Values
# above SOFT_CEILING are legitimate-but-suspicious; values above HARD_CEILING
# are almost certainly a misconfiguration (off-by-decimal-point — someone
# typed "20" intending "2.0").
PLATFORM_FEE_HARD_CEILING = Decimal("10")
PLATFORM_FEE_SOFT_CEILING = Decimal("5")


def validate_platform_fee_percent(
    value: Decimal,
    logger: logging.Logger,
) -> Decimal:
    """Validate `RAZORPAY_PLATFORM_FEE_PERCENT` at startup.

    Behaviour by band:
      - value ≤ 0          → RuntimeError (would zero out all customer-facing math)
      - 0 < value ≤ 5      → info log, normal startup
      - 5 < value ≤ 10     → ERROR log, startup proceeds (legitimately high; ops should review)
      - value > 10         → RuntimeError (almost certainly a fat-finger config error)

    Returns `value` unchanged on success so callers can use the return value
    in a chain if they want. Intended to be called once per process from the
    FastAPI startup event.
    """
    if value <= 0:
        raise RuntimeError(
            f"RAZORPAY_PLATFORM_FEE_PERCENT must be > 0 (got {value}). "
            f"This value drives all QR customer-facing math — see ADR 0001."
        )
    if value > PLATFORM_FEE_HARD_CEILING:
        raise RuntimeError(
            f"RAZORPAY_PLATFORM_FEE_PERCENT={value} exceeds the hard ceiling "
            f"of {PLATFORM_FEE_HARD_CEILING}% — this is almost certainly a "
            f"misconfiguration (off-by-decimal-point?). If you genuinely need "
            f"a rate this high, raise the ceiling deliberately."
        )
    if value > PLATFORM_FEE_SOFT_CEILING:
        logger.error(
            "RAZORPAY_PLATFORM_FEE_PERCENT=%s is above the soft ceiling of "
            "%s%%. Startup proceeds, but please confirm this is intentional "
            "— real Razorpay rates are typically 0–3%%.",
            value, PLATFORM_FEE_SOFT_CEILING,
        )
    else:
        logger.info(
            "Synthetic platform fee configured: %s%% of amount_paid "
            "(applies to QR budget cap, invoice gateway charges, over-payment refund)",
            value,
        )
    return value
