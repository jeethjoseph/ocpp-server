# fastapi.testclient creates a test instance of your FastAPI app and handles requests internally without needing to run a separate server process.
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_ocpp_websocket_connect_and_listed_in_charge_points():
    charge_point_id = "test-cp-2"
    with client.websocket_connect(f"/ocpp/{charge_point_id}") as websocket:
        # Connection should be successful
        assert websocket is not None

        # Now check if the charge point appears in the connected list
        response = client.get("/api/charge-points")
        assert response.status_code == 200
        charge_points = response.json()
        ids = [cp["charge_point_id"] for cp in charge_points]
        assert charge_point_id in ids

    # After disconnect, it should be removed from the list
    response = client.get("/api/charge-points")
    assert response.status_code == 200
    charge_points = response.json()
    ids = [cp["charge_point_id"] for cp in charge_points]
    assert charge_point_id not in ids


def test_multiple_charge_points_connect():
    ids = ["cp-1", "cp-2", "cp-3"]
    from contextlib import ExitStack
    with ExitStack() as stack:
        websockets = [
            stack.enter_context(client.websocket_connect(f"/ocpp/{cp_id}"))
            for cp_id in ids
        ]
        # All should be connected
        response = client.get("/api/charge-points")
        assert response.status_code == 200
        charge_points = response.json()
        listed_ids = [cp["charge_point_id"] for cp in charge_points]
        for cp_id in ids:
            assert cp_id in listed_ids
    # After disconnect, none should be listed
    response = client.get("/api/charge-points")
    listed_ids = [cp["charge_point_id"] for cp in response.json()]
    for cp_id in ids:
        assert cp_id not in listed_ids


def test_get_connected_charge_points_empty():
    # Should be empty if no websocket is connected
    response = client.get("/api/charge-points")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) == 0


def test_ocpp_bootnotification_response():
    charge_point_id = "test-cp-boot"
    with client.websocket_connect(f"/ocpp/{charge_point_id}") as websocket:
        # Send BootNotification message (OCPP 1.6 format)
        boot_notification = [
            2,  # CALL
            "12345",
            "BootNotification",
            {
                "chargePointModel": "ModelX",
                "chargePointVendor": "VendorY"
            }
        ]
        import json
        websocket.send_text(json.dumps(boot_notification))
        response = websocket.receive_json()
        # OCPP response should be a CALLRESULT with required fields
        assert isinstance(response, list)
        assert response[0] == 3  # CALLRESULT
        assert response[1] == "12345"  # uniqueId matches
        payload = response[2]
        assert "currentTime" in payload
        assert "interval" in payload
        assert "status" in payload
        assert payload["status"] in ["Accepted", "Pending", "Rejected"]
