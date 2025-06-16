import requests
import json
import websocket
import time

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"


def test_ocpp_websocket_connect_and_listed_in_charge_points():
    charge_point_id = "test-cp-2"
    ws = websocket.create_connection(f"{WS_URL}/ocpp/{charge_point_id}")
    # Send BootNotification to complete OCPP handshake
    boot_notification = [
        2,
        "12345",
        "BootNotification",
        {
            "chargePointModel": "ModelX",
            "chargePointVendor": "VendorY"
        }
    ]
    ws.send(json.dumps(boot_notification))
    ws.recv()  # Wait for BootNotification response
    time.sleep(0.2)
    response = requests.get(f"{BASE_URL}/api/charge-points")
    ids = [cp["charge_point_id"] for cp in response.json()]
    assert charge_point_id in ids
    ws.close()
    time.sleep(0.2)
    response = requests.get(f"{BASE_URL}/api/charge-points")
    ids = [cp["charge_point_id"] for cp in response.json()]
    assert charge_point_id not in ids


def test_multiple_charge_points_connect():
    ids = ["cp-1", "cp-2", "cp-3"]
    websockets = []
    try:
        for cp_id in ids:
            ws = websocket.create_connection(f"{WS_URL}/ocpp/{cp_id}")
            # Send BootNotification for each connection
            boot_notification = [
                2,
                f"boot-{cp_id}",
                "BootNotification",
                {
                    "chargePointModel": "ModelX",
                    "chargePointVendor": "VendorY"
                }
            ]
            ws.send(json.dumps(boot_notification))
            ws.recv()  # Wait for BootNotification response
            websockets.append(ws)
        time.sleep(0.2)
        response = requests.get(f"{BASE_URL}/api/charge-points")
        listed_ids = [cp["charge_point_id"] for cp in response.json()]
        for cp_id in ids:
            assert cp_id in listed_ids
    finally:
        for ws in websockets:
            ws.close()
    time.sleep(0.2)
    response = requests.get(f"{BASE_URL}/api/charge-points")
    listed_ids = [cp["charge_point_id"] for cp in response.json()]
    for cp_id in ids:
        assert cp_id not in listed_ids


def test_ocpp_bootnotification_response():
    charge_point_id = "test-cp-boot"
    ws = websocket.create_connection(f"{WS_URL}/ocpp/{charge_point_id}")
    boot_notification = [
        2,
        "12345",
        "BootNotification",
        {
            "chargePointModel": "ModelX",
            "chargePointVendor": "VendorY"
        }
    ]
    ws.send(json.dumps(boot_notification))
    response_raw = ws.recv()
    response = json.loads(response_raw)
    assert isinstance(response, list)
    assert response[0] == 3
    assert response[1] == "12345"
    payload = response[2]
    assert "currentTime" in payload
    assert "interval" in payload
    assert "status" in payload
    assert payload["status"] in ["Accepted", "Pending", "Rejected"]
    ws.close()
