"""Single source of truth for audit-log action strings.

Every `action=` passed to `crud.log_audit_event` MUST be registered here.
`tests/test_audit_actions.py` enforces the contract in both directions:
  • no emitted action is missing from this registry (catches new, unregistered
    actions the moment they're added), and
  • no registered action is dead (never emitted), and
  • the admin charger-timeline dropdown (`frontend/components/ChargerAuditLog.tsx`)
    exactly mirrors `charger_timeline_actions()`.

This replaces the previously hand-maintained frontend dropdown list, which had
drifted from the real vocabulary (missing `transaction.finalized`, offering
renamed-away `transaction.suspended_timeout` / `charger.*` options). See the
audit-log-action-filters investigation.
"""
from __future__ import annotations

# Grouped by entity namespace purely for readability; the flat frozenset below
# is the contract. Keep each list alphabetically sorted.
_CHARGER = [
    "charger.auth_provisioned",
    "charger.auth_rotated",
    "charger.availability_changed",
    "charger.connected",
    "charger.connection_rejected",
    "charger.create_failed",
    "charger.created",
    "charger.deleted",
    "charger.disconnected",
    "charger.reset",
    "charger.updated",
]
_TRANSACTION = [
    "transaction.finalized",
    "transaction.force_stopped",
    "transaction.resume_blocked",
    "transaction.resumed",
    "transaction.status_changed",
    "transaction.suspended",
]
_FIRMWARE = [
    "firmware.bulk_update_initiated",
    "firmware.deleted",
    "firmware.marked_failed",
    "firmware.marked_installed",
    "firmware.update_initiated",
    "firmware.uploaded",
]
_FRANCHISEE = [
    "franchisee.commission_updated",
    "franchisee.created",
    "franchisee.invitation_resent",
    "franchisee.kyc_submitted",
    "franchisee.qr_code_closed",
    "franchisee.qr_code_created",
    "franchisee.qr_code_regenerated",
    "franchisee.razorpay_account_deleted",
    "franchisee.razorpay_onboarded",
    "franchisee.razorpay_reconciled",
    "franchisee.retry_settlements",
    "franchisee.stakeholder_created",
    "franchisee.stakeholder_updated",
    "franchisee.station_unassigned",
    "franchisee.stations_assigned",
    "franchisee.status_updated",
    "franchisee.tds_updated",
    "franchisee.updated",
]
_SETTLEMENT = [
    "settlement.hold",
    "settlement.manual_settle",
    "settlement.mark_below_threshold",
    "settlement.release",
]
_STATION = [
    "station.created",
    "station.deleted",
    "station.updated",
]
_QR_PAYMENT = [
    "qr_payment.billing_completed",
]

AUDIT_ACTIONS: frozenset[str] = frozenset(
    _CHARGER + _TRANSACTION + _FIRMWARE + _FRANCHISEE + _SETTLEMENT + _STATION + _QR_PAYMENT
)


def charger_timeline_actions() -> list[str]:
    """Actions surfaced by the `/audit/charger-timeline` endpoint — charger
    events plus transaction events for the charger's transactions. Sorted;
    the authoritative source for the admin ChargerAuditLog action dropdown."""
    return sorted(a for a in AUDIT_ACTIONS if a.startswith(("charger.", "transaction.")))
