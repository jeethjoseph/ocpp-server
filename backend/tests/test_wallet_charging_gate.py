"""Tests for the wallet-charging gate (ADR 0011).

When WALLET_CHARGING_ENABLED is false, the two remote-start endpoints and the
wallet recharge endpoint must return 403 *before* any charger/wallet work, so no
new unsettleable wallet session or top-up can be created. When unset/true, the
gate is open (endpoints proceed past the flag check).
"""
import pytest

from main import app
from auth_middleware import get_current_user_with_db
from core.config import wallet_charging_enabled


@pytest.fixture
async def client_user(client, test_user):
    """HTTP test client authenticated as a regular USER.

    Overrides the DB-bound auth dependency, mirroring `client_admin`.
    """
    app.dependency_overrides[get_current_user_with_db] = lambda: test_user
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user_with_db, None)


# --- unit: the shared accessor -------------------------------------------------

def test_accessor_defaults_true_when_unset(monkeypatch):
    monkeypatch.delenv("WALLET_CHARGING_ENABLED", raising=False)
    assert wallet_charging_enabled() is True


@pytest.mark.parametrize(
    "value,expected",
    [("true", True), ("True", True), ("false", False), ("FALSE", False), ("", False)],
)
def test_accessor_parses_env(monkeypatch, value, expected):
    monkeypatch.setenv("WALLET_CHARGING_ENABLED", value)
    assert wallet_charging_enabled() is expected


# --- endpoint guards: flag OFF -> 403 -----------------------------------------

async def test_remote_start_by_string_id_blocked_when_disabled(monkeypatch, client_user):
    monkeypatch.setenv("WALLET_CHARGING_ENABLED", "false")
    resp = await client_user.post("/api/users/charger/CP_DOES_NOT_EXIST/remote-start")
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


async def test_recharge_blocked_when_disabled(monkeypatch, client_user):
    monkeypatch.setenv("WALLET_CHARGING_ENABLED", "false")
    resp = await client_user.post("/api/wallet/create-recharge", json={"amount": 100})
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


# --- endpoint guards: flag ON -> gate open (NOT 403) --------------------------

async def test_remote_start_gate_open_when_enabled(monkeypatch, client_user):
    monkeypatch.setenv("WALLET_CHARGING_ENABLED", "true")
    # Charger doesn't exist -> 404, proving we got past the gate (not 403).
    resp = await client_user.post("/api/users/charger/CP_DOES_NOT_EXIST/remote-start")
    assert resp.status_code != 403


async def test_recharge_gate_open_when_enabled(monkeypatch, client_user):
    monkeypatch.setenv("WALLET_CHARGING_ENABLED", "true")
    # Proceeds past the gate; may 503 (razorpay unconfigured) or succeed,
    # but must not be the gate's 403.
    resp = await client_user.post("/api/wallet/create-recharge", json={"amount": 100})
    assert resp.status_code != 403


# --- internal-role (ADR 0004): ADMIN/FRANCHISEE sessions are NOT wallet-gated --
# Internal-role sessions are operational and decoupled from wallets (no debit,
# no budget cap, no invoice — see core/roles.py, CONTEXT.md). The gate must not
# block them even when wallet charging is disabled.

async def test_admin_remote_start_not_gated_when_disabled(monkeypatch, client_admin):
    monkeypatch.setenv("WALLET_CHARGING_ENABLED", "false")
    # Charger 999999 doesn't exist -> expect 404 (past the gate), never the 403.
    resp = await client_admin.post("/api/admin/chargers/999999/remote-start")
    assert resp.status_code != 403, (
        f"admin remote-start must not be wallet-gated (ADR 0004); got {resp.status_code}"
    )


async def test_user_remote_start_charging_still_gated_when_disabled(monkeypatch, client_user):
    # A regular USER on the same endpoint IS wallet-funded -> still gated.
    # Confirms the internal-role carve-out doesn't open the gate for customers.
    monkeypatch.setenv("WALLET_CHARGING_ENABLED", "false")
    resp = await client_user.post("/api/admin/chargers/999999/remote-start")
    assert resp.status_code == 403
