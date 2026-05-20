"""Canonical user-role groupings shared across services.

Lives in `core/` rather than any single service module because the same set
is consulted by:
  - `services/invoice_service` (skip GST invoice generation)
  - `services/wallet_service` (skip wallet billing — ADR 0004)
  - `services/wallet_session_service` (skip budget cap — ADR 0004)
  - `routers/webhooks` (skip wallet creation for new internal-role users)

A service-level home (e.g. `invoice_service.INTERNAL_ROLES`) would force the
webhook handler to import from a service it has no other business with.
"""
from models import UserRoleEnum


# Roles whose charging sessions are purely operational, not customer-facing.
# See ADR 0004 (`docs/adr/0004-internal-role-sessions-are-operational.md`)
# and CONTEXT.md "Internal-role User" / "Internal-role Session".
INTERNAL_ROLES = {UserRoleEnum.ADMIN, UserRoleEnum.FRANCHISEE}
