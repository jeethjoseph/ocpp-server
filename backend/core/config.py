"""Project-level configuration constants.

Single home for env-var-driven values that are read across multiple domains
(routers, services, startup validation). Domain-specific configuration stays
in the relevant service module — e.g. `QR_PAYMENT_PENDING_TIMEOUT` lives in
`services/qr_payment_service.py` because only QR payment code reads it.
"""
import os


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
