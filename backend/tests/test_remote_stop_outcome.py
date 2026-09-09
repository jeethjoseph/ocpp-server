"""A refused RemoteStop must never read as success.

The dangerous asymmetry: a failed *start* is self-revealing — nothing plugs in
and the operator tries again. A failed *stop* is invisible. The session keeps
running, keeps drawing power and keeps billing, while the UI says it ended.

See CONTEXT.md -> Remote commands, and
.scratch/ocpp-command-outcome/issues/03-remote-stop-honours-rejection.md
"""
import random
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from httpx import AsyncClient
from ocpp.v16 import call_result

from auth_middleware import get_current_user_with_db
from core.connection_manager import CommandOutcome
from main import app, connected_charge_points
from models import Transaction, User, VehicleProfile

REFUSED = CommandOutcome(True, call_result.RemoteStopTransaction(status="Rejected"))
UNANSWERED = CommandOutcome(False, "OCPP timeout: RemoteStopTransaction")


@pytest.fixture
async def client_user(client, test_user):
    """HTTP client authenticated as a regular USER, mirroring `client_admin`."""
    app.dependency_overrides[get_current_user_with_db] = lambda: test_user
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user_with_db, None)


async def _running_transaction(charger, user=None):
    if user is None:
        suffix = random.randint(100000000, 999999999)
        user = await User.create(
            email=f"stop_{suffix}@voltlync.test", phone_number=f"9{suffix}"
        )
    vehicle = await VehicleProfile.create(user=user)
    return await Transaction.create(
        user_id=user.id,
        charger_id=charger.id,
        vehicle_id=vehicle.id,
        transaction_status="RUNNING",
    )


def _mark_connected(charger):
    connected_charge_points[charger.charge_point_string_id] = {
        "cp": MagicMock(),
        "websocket": MagicMock(),
    }


class TestAdminStop:
    @pytest.mark.asyncio
    @patch("main.send_ocpp_request")
    async def test_refused_stop_is_not_reported_as_success(
        self, mock_send, client_admin: AsyncClient, test_charger
    ):
        txn = await _running_transaction(test_charger)
        _mark_connected(test_charger)
        mock_send.return_value = REFUSED

        resp = await client_admin.post(
            f"/api/admin/chargers/{test_charger.id}/remote-stop",
            json={"reason": "Operator request"},
        )

        assert resp.status_code == status.HTTP_409_CONFLICT
        detail = resp.json()["detail"].lower()
        assert "declined" in detail
        # The operator must be told the session did NOT end.
        assert "still running" in detail
        assert txn.id  # session deliberately left untouched

    @pytest.mark.asyncio
    @patch("main.send_ocpp_request")
    async def test_refused_stop_leaves_the_session_running(
        self, mock_send, client_admin: AsyncClient, test_charger
    ):
        """The transaction must not be marked stopped on a refusal — that is the
        divergence that would let the books disagree with the hardware."""
        txn = await _running_transaction(test_charger)
        _mark_connected(test_charger)
        mock_send.return_value = REFUSED

        await client_admin.post(
            f"/api/admin/chargers/{test_charger.id}/remote-stop",
            json={"reason": "Operator request"},
        )

        await txn.refresh_from_db()
        assert txn.transaction_status == "RUNNING"

    @pytest.mark.asyncio
    @patch("main.send_ocpp_request")
    async def test_unanswered_stop_is_504_not_409(
        self, mock_send, client_admin: AsyncClient, test_charger
    ):
        """Refused and unanswered must be distinguishable by status code, not
        by sniffing message text."""
        await _running_transaction(test_charger)
        _mark_connected(test_charger)
        mock_send.return_value = UNANSWERED

        resp = await client_admin.post(
            f"/api/admin/chargers/{test_charger.id}/remote-stop",
            json={"reason": "Operator request"},
        )

        assert resp.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        assert "did not respond" in resp.json()["detail"].lower()


class TestCustomerAppStop:
    """This path checks connectivity via Redis rather than the in-memory map,
    so it needs its own patch."""

    @pytest.mark.asyncio
    @patch("redis_manager.redis_manager.get_all_connected_chargers")
    @patch("main.send_ocpp_request")
    async def test_refused_stop_tells_the_driver_the_session_continues(
        self, mock_send, mock_connected, client_user: AsyncClient, test_charger, test_user
    ):
        await _running_transaction(test_charger, user=test_user)
        mock_connected.return_value = [test_charger.charge_point_string_id]
        mock_send.return_value = REFUSED

        resp = await client_user.post(
            f"/api/users/charger/{test_charger.charge_point_string_id}/remote-stop"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT
        detail = resp.json()["detail"].lower()
        assert "declined" in detail
        assert "still running" in detail

    @pytest.mark.asyncio
    @patch("redis_manager.redis_manager.get_all_connected_chargers")
    @patch("main.send_ocpp_request")
    async def test_unanswered_stop_is_504(
        self, mock_send, mock_connected, client_user: AsyncClient, test_charger, test_user
    ):
        await _running_transaction(test_charger, user=test_user)
        mock_connected.return_value = [test_charger.charge_point_string_id]
        mock_send.return_value = UNANSWERED

        resp = await client_user.post(
            f"/api/users/charger/{test_charger.charge_point_string_id}/remote-stop"
        )

        assert resp.status_code == status.HTTP_504_GATEWAY_TIMEOUT
