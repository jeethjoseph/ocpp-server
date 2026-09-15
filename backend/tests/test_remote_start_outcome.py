"""A refused RemoteStart must not be reported as success.

Less dangerous than a refused stop — nothing plugs in and nobody is billed, so
the failure is at least self-revealing — but the UI previously fired a green
"Waiting for charger to start charging..." toast, leaving the operator waiting
for a session that was never going to begin.

Also pins the asymmetry fix: the admin and customer-app endpoints disagreed on
the timeout, returning 504 and 500 for the identical condition.

See CONTEXT.md -> Remote commands, and
.scratch/ocpp-command-outcome/issues/02-remote-start-honours-rejection.md
"""
from unittest.mock import patch

import pytest
from fastapi import status
from httpx import AsyncClient
from ocpp.v16 import call_result

from auth_middleware import get_current_user_with_db
from core.connection_manager import CommandOutcome
from main import app

REFUSED = CommandOutcome(True, call_result.RemoteStartTransaction(status="Rejected"))
UNANSWERED = CommandOutcome(False, "OCPP timeout: RemoteStartTransaction")


@pytest.fixture
async def client_user(client, test_user):
    """HTTP client authenticated as a regular USER, mirroring `client_admin`."""
    app.dependency_overrides[get_current_user_with_db] = lambda: test_user
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user_with_db, None)


@pytest.fixture
async def user_with_rfid(test_user):
    """The customer-app start path requires an assigned RFID card id."""
    test_user.rfid_card_id = "RFID_TEST_0001"
    await test_user.save()
    return test_user


class TestCustomerAppStart:
    @pytest.mark.asyncio
    @patch("redis_manager.redis_manager.get_all_connected_chargers")
    @patch("main.send_ocpp_request")
    async def test_refused_start_is_409_not_success(
        self, mock_send, mock_connected, client_user: AsyncClient,
        test_charger, user_with_rfid
    ):
        mock_connected.return_value = [test_charger.charge_point_string_id]
        mock_send.return_value = REFUSED

        resp = await client_user.post(
            f"/api/users/charger/{test_charger.charge_point_string_id}/remote-start"
        )

        assert resp.status_code == status.HTTP_409_CONFLICT
        assert "declined" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    @patch("redis_manager.redis_manager.get_all_connected_chargers")
    @patch("main.send_ocpp_request")
    async def test_unanswered_start_is_504_not_500(
        self, mock_send, mock_connected, client_user: AsyncClient,
        test_charger, user_with_rfid
    ):
        """Was a 500, which reported an offline charger as a server fault and
        disagreed with the admin endpoint's 504 for the identical condition.
        A 500 also lands in Sentry, which 504 is deliberately excluded from."""
        mock_connected.return_value = [test_charger.charge_point_string_id]
        mock_send.return_value = UNANSWERED

        resp = await client_user.post(
            f"/api/users/charger/{test_charger.charge_point_string_id}/remote-start"
        )

        assert resp.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        assert "did not respond" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    @patch("redis_manager.redis_manager.get_all_connected_chargers")
    @patch("main.send_ocpp_request")
    async def test_accepted_start_still_succeeds(
        self, mock_send, mock_connected, client_user: AsyncClient,
        test_charger, user_with_rfid
    ):
        mock_connected.return_value = [test_charger.charge_point_string_id]
        mock_send.return_value = CommandOutcome(
            True, call_result.RemoteStartTransaction(status="Accepted")
        )

        resp = await client_user.post(
            f"/api/users/charger/{test_charger.charge_point_string_id}/remote-start"
        )

        assert resp.status_code == status.HTTP_200_OK
        assert "accepted by charger" in resp.json()["message"].lower()


class TestEndpointsAgree:
    @pytest.mark.asyncio
    @patch("routers.chargers.is_charger_connected")
    @patch("redis_manager.redis_manager.get_all_connected_chargers")
    @patch("main.send_ocpp_request")
    async def test_both_endpoints_return_504_on_no_answer(
        self, mock_send, mock_redis_connected, mock_connected,
        client_admin: AsyncClient, client_user: AsyncClient,
        test_charger, user_with_rfid
    ):
        """The two start endpoints must not disagree about the same condition."""
        from models import Charger, ChargerStatusEnum
        mock_connected.return_value = True
        mock_redis_connected.return_value = [test_charger.charge_point_string_id]
        await Charger.filter(id=test_charger.id).update(
            latest_status=ChargerStatusEnum.PREPARING
        )
        mock_send.return_value = UNANSWERED

        admin = await client_admin.post(
            f"/api/admin/chargers/{test_charger.id}/remote-start"
        )
        assert admin.status_code == status.HTTP_504_GATEWAY_TIMEOUT
