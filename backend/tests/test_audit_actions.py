"""Contract tests for the audit-action registry (core.audit_actions).

Keeps the single source of truth honest in three directions so the admin
ChargerAuditLog dropdown can never drift from the actions the backend emits:
  1. every emitted `action="x.y"` literal is registered,
  2. every registered action is actually emitted (no dead entries), and
  3. the frontend dropdown mirrors `charger_timeline_actions()` exactly.
"""
import re
from pathlib import Path

import pytest

from core.audit_actions import AUDIT_ACTIONS, charger_timeline_actions

_BACKEND = Path(__file__).resolve().parent.parent
# The frontend lives as a sibling of backend/ in a full checkout. Under the
# standard `docker exec ocpp-backend pytest` workflow only backend/ is mounted,
# so the FE/BE sync test skips there and runs in a full-repo checkout / CI.
_FRONTEND_DROPDOWN = _BACKEND.parent / "frontend" / "components" / "ChargerAuditLog.tsx"

# Matches a dotted audit action passed to log_audit_event, e.g. action="charger.created".
_ACTION_RE = re.compile(r"""action=["']([a-z_]+\.[a-z_]+)["']""")


def _emitted_actions() -> set[str]:
    """Scan backend source (excluding tests + migrations) for emitted action
    literals — the same literal form the runtime uses."""
    found: set[str] = set()
    for path in _BACKEND.rglob("*.py"):
        rel = path.relative_to(_BACKEND).as_posix()
        if rel.startswith(("tests/", "migrations/")):
            continue
        found.update(_ACTION_RE.findall(path.read_text(encoding="utf-8")))
    return found


def test_every_emitted_action_is_registered():
    unregistered = _emitted_actions() - AUDIT_ACTIONS
    assert not unregistered, (
        f"Audit actions emitted but not registered in core.audit_actions: "
        f"{sorted(unregistered)}"
    )


def test_no_dead_registered_actions():
    dead = AUDIT_ACTIONS - _emitted_actions()
    assert not dead, (
        f"Registered audit actions that are never emitted (remove them or the "
        f"code that should emit them regressed): {sorted(dead)}"
    )


def test_frontend_dropdown_matches_charger_timeline_registry():
    """The hardcoded ACTION_OPTIONS list in ChargerAuditLog.tsx must equal the
    charger-timeline subset (plus the leading '' = All actions)."""
    if not _FRONTEND_DROPDOWN.exists():
        pytest.skip("frontend/ not present (backend-only container); runs in full checkout / CI")
    src = _FRONTEND_DROPDOWN.read_text(encoding="utf-8")
    block = re.search(r"ACTION_OPTIONS\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert block, "Could not locate ACTION_OPTIONS in ChargerAuditLog.tsx"
    options = re.findall(r"""["']([a-z_.]*)["']""", block.group(1))
    dropdown = {o for o in options if o}  # drop the leading "" (All actions)
    assert dropdown == set(charger_timeline_actions()), (
        "Frontend audit dropdown drifted from core.audit_actions.charger_timeline_actions().\n"
        f"  missing from dropdown: {sorted(set(charger_timeline_actions()) - dropdown)}\n"
        f"  dead in dropdown:      {sorted(dropdown - set(charger_timeline_actions()))}"
    )
