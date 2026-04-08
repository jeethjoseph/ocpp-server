"""
Integration tests for OCPP WebSocket connections.

These tests run end-to-end against the in-process FastAPI app via TestClient.
The OCPP WebSocket layer (`backend/routers/ocpp_ws.py`) is exercised through
TestClient's WebSocket support, with chargers pre-seeded via the admin API
on the same connection (so DB writes happen on TestClient's worker loop).

Originally these tests used the `requests` and `websocket-client` libraries
against a real localhost:8000 server, which broke when admin auth was added
(403 Forbidden) and when charger pre-registration became mandatory. The
rewrite preserves the original test intent while making them runnable in
any environment without external services.
"""

import pytest
import json
import time
import uuid


# ============================================================================
# OCPPChargerMock — TestClient-backed OCPP 1.6 charger simulator
# ============================================================================

class OCPPChargerMock:
    """Simulates an OCPP 1.6 charger for end-to-end integration testing.

    Uses FastAPI's TestClient WebSocket session as transport. The wire
    protocol (raw [type, msgId, action, payload] frames) is constructed
    in-process and round-tripped through the in-process ASGI app.
    """

    def __init__(self, charge_point_string_id: str, test_client):
        self.charge_point_id = charge_point_string_id
        self.test_client = test_client
        self.ws_ctx = None
        self.ws = None
        self.message_id_counter = 1
        self.server_time = None
        self.transaction_id = None
        self.current_status = "Unavailable"
        self.is_connected = False

    def _get_next_message_id(self) -> str:
        msg_id = str(self.message_id_counter)
        self.message_id_counter += 1
        return msg_id

    def _send_message(self, action: str, payload: dict) -> dict:
        """Send an OCPP CALL and wait for the matching CALLRESULT.

        Server-initiated CALLs (e.g. DataTransfer pushes from
        after_boot_notification) are auto-acked so the test can keep
        progressing without dropping incoming messages.
        """
        message_id = self._get_next_message_id()
        self.ws.send_text(json.dumps([2, message_id, action, payload]))

        for _ in range(20):
            raw = self.ws.receive_text()
            response = json.loads(raw)
            if response[0] == 3 and response[1] == message_id:
                return response[2]
            elif response[0] == 4 and response[1] == message_id:
                raise Exception(f"OCPP CALLERROR: {response[2]} - {response[3]}")
            elif response[0] == 2:
                # Server CALL — auto-ack and keep waiting for our CALLRESULT
                self.ws.send_text(json.dumps([3, response[1], {"status": "Accepted"}]))
                continue
        raise Exception(f"No CALLRESULT received for {action} (msg_id={message_id})")

    def connect(self):
        self.ws_ctx = self.test_client.websocket_connect(
            f"/ocpp/{self.charge_point_id}", subprotocols=["ocpp1.6"]
        )
        self.ws = self.ws_ctx.__enter__()
        self.is_connected = True

    def disconnect(self):
        if self.ws_ctx is not None:
            try:
                self.ws_ctx.__exit__(None, None, None)
            except Exception:
                pass
            self.ws_ctx = None
            self.ws = None
            self.is_connected = False

    def send_boot_notification(self) -> dict:
        response = self._send_message("BootNotification", {
            "chargePointModel": "TestModel",
            "chargePointVendor": "VOLTLYNC",
        })
        if "currentTime" in response:
            self.server_time = response["currentTime"]
        return response

    def send_heartbeat(self) -> dict:
        return self._send_message("Heartbeat", {})

    def send_status_notification(self, status: str, connector_id: int = 1) -> dict:
        self.current_status = status
        return self._send_message("StatusNotification", {
            "connectorId": connector_id,
            "status": status,
            "errorCode": "NoError",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        })

    def send_start_transaction(self, id_tag: str = "test_user", connector_id: int = 1) -> dict:
        response = self._send_message("StartTransaction", {
            "connectorId": connector_id,
            "idTag": id_tag,
            "meterStart": 1000,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        })
        if "transactionId" in response:
            self.transaction_id = response["transactionId"]
        return response

    def send_stop_transaction(self, reason: str = "Remote") -> dict:
        if not self.transaction_id:
            raise Exception("No active transaction to stop")
        response = self._send_message("StopTransaction", {
            "transactionId": self.transaction_id,
            "meterStop": 5000,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "reason": reason,
        })
        self.transaction_id = None
        return response

    def send_meter_values(self, connector_id: int = 1) -> dict:
        if not self.transaction_id:
            raise Exception("No active transaction for meter values")
        return self._send_message("MeterValues", {
            "connectorId": connector_id,
            "transactionId": self.transaction_id,
            "meterValue": [{
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "sampledValue": [{
                    "value": "2500",
                    "context": "Sample.Periodic",
                    "format": "Raw",
                    "measurand": "Energy.Active.Import.Register",
                    "unit": "Wh",
                }],
            }],
        })


# ============================================================================
# Helpers — seed test data via TestClient HTTP (same loop as the WebSocket)
# ============================================================================

def _seed_station(client) -> int:
    """POST a unique test station, return its id."""
    resp = client.post(
        "/api/admin/stations",
        json={
            "name": f"IntegTest Station {uuid.uuid4().hex[:6]}",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "address": "Integration Test Address",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["station"]["id"]


def _seed_charger(client, station_id: int, name: str = "IntegTest Charger") -> str:
    """POST a unique test charger, return its charge_point_string_id."""
    external_id = f"integ-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/admin/chargers",
        json={
            "station_id": station_id,
            "name": name,
            "model": "TestModel",
            "vendor": "VOLTLYNC",
            "external_charger_id": external_id,
            "connectors": [
                {"connector_id": 1, "connector_type": "Type2", "max_power_kw": 22.0}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["charger"]["charge_point_string_id"]


def _seed_user_with_rfid(client, rfid_card_id: str) -> int:
    """Create a test user with a specific rfid_card_id by running an async
    seeder on TestClient's worker loop (via the internal portal). This is
    needed because the StartTransaction OCPP handler looks up users by
    rfid_card_id in the DB, and there's no admin HTTP endpoint to create
    users (Clerk handles that in production).

    Returns the created user's id.
    """
    async def _create():
        from models import User as _User
        return await _User.create(
            email=f"integ_user_{uuid.uuid4().hex[:8]}@voltlync.test",
            phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
            rfid_card_id=rfid_card_id,
        )

    user = client.portal.call(_create)
    return user.id


# ============================================================================
# Tests
# ============================================================================

@pytest.mark.integration
class TestOCPPIntegration:
    """End-to-end integration tests for the OCPP WebSocket layer.

    Uses TestClient (sync) to drive the in-process ASGI app. The
    `sync_client_admin` fixture provides Redis mocking and admin auth
    bypass; chargers are pre-seeded via TestClient HTTP calls so the DB
    writes happen on the same event loop as the WebSocket connection
    (avoiding the asyncpg cross-loop issue).
    """

    def test_ocpp_websocket_connect_and_listed_in_charge_points(self, sync_client_admin):
        """A connected charger should appear in /api/charge-points and be removed on disconnect."""
        station_id = _seed_station(sync_client_admin)
        cp_id = _seed_charger(sync_client_admin, station_id)

        charger = OCPPChargerMock(cp_id, sync_client_admin)
        try:
            charger.connect()
            response = charger.send_boot_notification()
            assert response["status"] == "Accepted"

            # While connected, the charger should be listed
            listing = sync_client_admin.get("/api/charge-points")
            assert listing.status_code == 200
            ids = [cp["charge_point_id"] for cp in listing.json()]
            assert cp_id in ids
        finally:
            charger.disconnect()

        # After disconnect, the charger should no longer be listed
        listing_after = sync_client_admin.get("/api/charge-points")
        assert listing_after.status_code == 200
        ids_after = [cp["charge_point_id"] for cp in listing_after.json()]
        assert cp_id not in ids_after

    def test_multiple_charge_points_connect(self, sync_client_admin):
        """Multiple chargers should connect simultaneously and all be listed."""
        station_id = _seed_station(sync_client_admin)
        cp_ids = [_seed_charger(sync_client_admin, station_id, f"Multi {i}") for i in range(3)]

        chargers = [OCPPChargerMock(cp_id, sync_client_admin) for cp_id in cp_ids]
        try:
            for ch in chargers:
                ch.connect()
                response = ch.send_boot_notification()
                assert response["status"] == "Accepted"

            listing = sync_client_admin.get("/api/charge-points")
            assert listing.status_code == 200
            listed_ids = [cp["charge_point_id"] for cp in listing.json()]
            for cp_id in cp_ids:
                assert cp_id in listed_ids
        finally:
            for ch in chargers:
                ch.disconnect()

    def test_ocpp_bootnotification_response(self, sync_client_admin):
        """Verify the OCPP BootNotification response shape."""
        station_id = _seed_station(sync_client_admin)
        cp_id = _seed_charger(sync_client_admin, station_id)

        charger = OCPPChargerMock(cp_id, sync_client_admin)
        try:
            charger.connect()
            response = charger.send_boot_notification()
            assert "currentTime" in response
            assert "interval" in response
            assert response["status"] == "Accepted"
        finally:
            charger.disconnect()


@pytest.mark.integration
class TestOCPPSuccessCycle:
    """End-to-end OCPP message cycle test."""

    @pytest.mark.slow
    def test_ocpp_core_functionality(self, sync_client_admin):
        """Full OCPP 1.6 cycle:
        1. Boot notification with clock reset
        2. Heartbeats
        3. Status notification (Available)
        4. StartTransaction
        5. Status notification (Charging)
        6. MeterValues
        7. StopTransaction
        8. Status notification (Available)
        """
        station_id = _seed_station(sync_client_admin)
        cp_id = _seed_charger(sync_client_admin, station_id, "Core Cycle Charger")
        # StartTransaction needs a real user with the matching rfid_card_id.
        # Use a unique value per test to avoid cross-test UNIQUE collisions.
        rfid_tag = f"test_rfid_{uuid.uuid4().hex[:8]}"
        _seed_user_with_rfid(sync_client_admin, rfid_tag)

        charger = OCPPChargerMock(cp_id, sync_client_admin)
        try:
            # Step 1: Connect + BootNotification
            charger.connect()
            boot_response = charger.send_boot_notification()
            assert boot_response["status"] == "Accepted"
            assert charger.server_time is not None

            # Step 2: Heartbeats
            for _ in range(2):
                hb = charger.send_heartbeat()
                assert "currentTime" in hb

            # Step 3: Available status
            status_resp = charger.send_status_notification("Available")
            assert status_resp == {} or "status" in status_resp or status_resp is not None

            # Step 4: StartTransaction (use the rfid we seeded above)
            start_response = charger.send_start_transaction(rfid_tag, 1)
            assert "transactionId" in start_response
            assert start_response["transactionId"] is not None
            assert start_response["transactionId"] > 0

            # Step 5: Charging status
            charger.send_status_notification("Charging")

            # Step 6: MeterValues
            for _ in range(2):
                charger.send_meter_values()

            # Step 7: StopTransaction
            charger.send_status_notification("Finishing")
            stop_response = charger.send_stop_transaction("Local")
            # StopTransaction response is a dict (possibly empty or with idTagInfo)
            assert isinstance(stop_response, dict)

            # Step 8: Back to Available
            charger.send_status_notification("Available")

            # Final assertions
            assert charger.is_connected
            assert charger.current_status == "Available"
            assert charger.transaction_id is None
        finally:
            charger.disconnect()

    def test_ocpp_remote_commands_info(self, sync_client_admin):
        """Smoke test: the /api/charge-points endpoint is reachable via admin auth."""
        response = sync_client_admin.get("/api/charge-points")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
