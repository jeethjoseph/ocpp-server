#!/usr/bin/env python3
"""
OCPP 1.6 Simulator for PostBootState DataTransfer Testing

Tests the server's ability to push meter values and pending transaction
state to the charger after BootNotification. Three test modes:

  --test-resume   Reboot mid-transaction, receive PostBootState, resume via MeterValues
  --test-stop     Reboot mid-transaction, receive PostBootState, send StopTransaction
  --test-no-txn   Reboot with no active transaction, receive meter-only PostBootState

Usage:
    python ocpp_simulator_post_boot_state.py --charger-id <id> --test-resume
    python ocpp_simulator_post_boot_state.py --charger-id <id> --server wss://app.voltlync.com --test-no-txn
"""

import json
import time
import argparse
import websocket
from datetime import datetime, timezone
from typing import Optional


class PostBootStateSimulator:
    """Simulates charger reboot scenarios to test PostBootState DataTransfer."""

    def __init__(self, charge_point_id: str, server_url: str = "ws://localhost:8000"):
        self.charge_point_id = charge_point_id
        self.server_url = server_url
        self.ws = None
        self.message_id_counter = 1
        self.transaction_id = None
        self.meter_wh = 10000  # Starting meter value
        self._pending_server_calls = []

    def _get_next_message_id(self) -> str:
        msg_id = str(self.message_id_counter)
        self.message_id_counter += 1
        return msg_id

    def _send_message(self, action: str, payload: dict) -> dict:
        """Send OCPP CALL and wait for CALLRESULT, queuing interleaved server CALLs."""
        message_id = self._get_next_message_id()
        message = [2, message_id, action, payload]
        print(f"📤 [{self.charge_point_id}] Sending {action}: {json.dumps(payload)}")
        self.ws.send(json.dumps(message))

        self.ws.settimeout(15.0)
        try:
            while True:
                response_raw = self.ws.recv()
                response = json.loads(response_raw)

                if response[0] == 2:  # Server CALL — queue for later
                    self._pending_server_calls.append(response)
                    print(f"📥 [{self.charge_point_id}] Queued server CALL: {response[2]}")
                elif response[0] == 3 and response[1] == message_id:
                    print(f"📥 [{self.charge_point_id}] Response: {action} → {json.dumps(response[2])}")
                    return response[2]
                elif response[0] == 4 and response[1] == message_id:
                    raise Exception(f"OCPP Error: {response[2]} - {response[3]}")
        except websocket.WebSocketTimeoutException:
            raise Exception(f"{action} timed out")

    def _send_call_result(self, message_id: str, payload: dict):
        """Send CALLRESULT response to a server CALL."""
        response = [3, message_id, payload]
        print(f"📤 [{self.charge_point_id}] Response: {json.dumps(payload)}")
        self.ws.send(json.dumps(response))

    def _wait_for_server_call(self, timeout: float = 20.0) -> Optional[dict]:
        """Wait for an incoming server CALL (e.g., DataTransfer, RemoteStart)."""
        # Check queued calls first
        if self._pending_server_calls:
            msg = self._pending_server_calls.pop(0)
            return {"message_id": msg[1], "action": msg[2], "payload": msg[3]}

        self.ws.settimeout(timeout)
        try:
            while True:
                raw = self.ws.recv()
                parsed = json.loads(raw)
                if parsed[0] == 2:
                    return {"message_id": parsed[1], "action": parsed[2], "payload": parsed[3]}
                print(f"⚠️ Unexpected message: {parsed}")
        except websocket.WebSocketTimeoutException:
            return None

    def connect(self):
        url = f"{self.server_url}/ocpp/{self.charge_point_id}"
        print(f"🔌 Connecting to {url}")
        self.ws = websocket.create_connection(url)
        self._pending_server_calls = []
        print(f"✅ Connected")

    def disconnect(self):
        if self.ws:
            self.ws.close()
            self.ws = None
        print(f"🔌 Disconnected")

    def send_boot_notification(self):
        return self._send_message("BootNotification", {
            "chargePointModel": "PostBootTest",
            "chargePointVendor": "VOLTLYNC",
        })

    def send_status(self, status: str, connector_id: int = 1):
        return self._send_message("StatusNotification", {
            "connectorId": connector_id,
            "status": status,
            "errorCode": "NoError",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        })

    def send_start_transaction(self, id_tag: str = "test_user"):
        response = self._send_message("StartTransaction", {
            "connectorId": 1,
            "idTag": id_tag,
            "meterStart": self.meter_wh,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        })
        self.transaction_id = response.get("transactionId")
        print(f"🔋 Transaction started: ID={self.transaction_id}")
        return response

    def send_meter_values(self, reading_wh: int = None):
        if reading_wh is not None:
            self.meter_wh = reading_wh
        return self._send_message("MeterValues", {
            "connectorId": 1,
            "transactionId": self.transaction_id,
            "meterValue": [{
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                "sampledValue": [
                    {"value": str(self.meter_wh), "measurand": "Energy.Active.Import.Register", "unit": "Wh"},
                    {"value": "3500", "measurand": "Power.Active.Import", "unit": "W"},
                ],
            }],
        })

    def send_stop_transaction(self, meter_stop_wh: int, reason: str = "EVDisconnected"):
        return self._send_message("StopTransaction", {
            "transactionId": self.transaction_id,
            "meterStop": meter_stop_wh,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
            "reason": reason,
        })

    def handle_post_boot_state(self, message: dict) -> dict:
        """Handle incoming PostBootState DataTransfer from server."""
        payload = message["payload"]
        data = json.loads(payload.get("data", "{}"))

        print(f"\n{'='*60}")
        print(f"📡 RECEIVED PostBootState from server:")
        print(f"   hasPendingTransaction: {data.get('hasPendingTransaction')}")
        print(f"   lastMeterValueWh:      {data.get('lastMeterValueWh')}")
        if data.get("hasPendingTransaction"):
            print(f"   transactionId:         {data.get('transactionId')}")
            print(f"   startMeterValueWh:     {data.get('startMeterValueWh')}")
            print(f"   energyConsumedWh:      {data.get('energyConsumedWh')}")
        print(f"{'='*60}\n")

        # Accept the message
        self._send_call_result(message["message_id"], {"status": "Accepted"})

        # Update internal meter
        self.meter_wh = data.get("lastMeterValueWh", 0)
        if data.get("transactionId"):
            self.transaction_id = data["transactionId"]

        return data

    def handle_remote_start(self, message: dict):
        """Accept RemoteStartTransaction and start a transaction."""
        self._send_call_result(message["message_id"], {"status": "Accepted"})
        id_tag = message["payload"].get("idTag", "remote_user")
        print(f"⚡ Accepted RemoteStart (idTag={id_tag})")
        self.send_status("Preparing")
        time.sleep(1)
        self.send_status("Charging")
        self.send_start_transaction(id_tag)

    def wait_and_handle_server_calls(self, timeout: float = 20.0):
        """Wait for and dispatch server calls. Returns PostBootState data if received."""
        msg = self._wait_for_server_call(timeout)
        if not msg:
            print(f"⏰ No server call received within {timeout}s")
            return None

        action = msg["action"]
        if action == "DataTransfer":
            vendor_id = msg["payload"].get("vendorId", "")
            message_id = msg["payload"].get("messageId", "")
            if vendor_id == "VOLTLYNC" and message_id == "PostBootState":
                return self.handle_post_boot_state(msg)
            else:
                print(f"⚠️ Unknown DataTransfer: vendorId={vendor_id}, messageId={message_id}")
                self._send_call_result(msg["message_id"], {"status": "UnknownMessageId"})
        elif action == "RemoteStartTransaction":
            self.handle_remote_start(msg)
        elif action == "RemoteStopTransaction":
            self._send_call_result(msg["message_id"], {"status": "Accepted"})
        else:
            print(f"⚠️ Unhandled server call: {action}")
            self._send_call_result(msg["message_id"], {"status": "Rejected"})

        return None


def test_resume(sim: PostBootStateSimulator):
    """Test: Reboot mid-transaction, receive PostBootState, resume via MeterValues."""
    print("\n" + "=" * 60)
    print("TEST: Reboot mid-transaction → Resume")
    print("=" * 60)

    # Phase 1: Start a charging session
    sim.connect()
    sim.send_boot_notification()
    # Drain any PostBootState from initial boot
    sim.wait_and_handle_server_calls(timeout=5)
    sim.send_status("Available")

    # Transition to Preparing (like full success simulator)
    print(f"\n⏰ Waiting 5 seconds before entering Preparing state...")
    time.sleep(5)
    sim.send_status("Preparing")

    print("\n--- Waiting for RemoteStartTransaction (send via admin panel) ---")
    while True:
        msg = sim._wait_for_server_call(timeout=30)
        if msg and msg["action"] == "RemoteStartTransaction":
            sim.handle_remote_start(msg)
            break
        elif msg and msg["action"] == "DataTransfer":
            sim.handle_post_boot_state(msg)

    # Send some meter values
    for i in range(3):
        time.sleep(2)
        sim.meter_wh += 500
        sim.send_meter_values()

    print(f"\n⚡ Current meter: {sim.meter_wh} Wh")

    # Phase 2: Simulate reboot
    print("\n🔄 SIMULATING REBOOT...")
    sim.disconnect()
    time.sleep(3)

    # Phase 3: Reconnect and receive PostBootState
    sim.connect()
    sim.send_boot_notification()

    data = sim.wait_and_handle_server_calls(timeout=20)
    if data and data.get("hasPendingTransaction"):
        print(f"✅ Received pending transaction! Resuming from {data['lastMeterValueWh']} Wh")

        # Resume: send MeterValues (server auto-resumes SUSPENDED→RUNNING)
        sim.meter_wh = data["lastMeterValueWh"] + 200
        sim.send_status("Charging")
        sim.send_meter_values()
        print(f"✅ Resumed! Sent MeterValues at {sim.meter_wh} Wh")

        # Send a few more
        for i in range(2):
            time.sleep(2)
            sim.meter_wh += 300
            sim.send_meter_values()

        print(f"\n✅ TEST PASSED: Transaction resumed successfully")
    else:
        print("❌ TEST FAILED: Did not receive PostBootState with pending transaction")

    sim.disconnect()


def test_stop(sim: PostBootStateSimulator):
    """Test: Reboot mid-transaction, receive PostBootState, send StopTransaction."""
    print("\n" + "=" * 60)
    print("TEST: Reboot mid-transaction → Can't resume → StopTransaction")
    print("=" * 60)

    # Phase 1: Start a charging session
    sim.connect()
    sim.send_boot_notification()
    sim.wait_and_handle_server_calls(timeout=5)
    sim.send_status("Available")

    # Transition to Preparing (like full success simulator)
    print(f"\n⏰ Waiting 5 seconds before entering Preparing state...")
    time.sleep(5)
    sim.send_status("Preparing")

    print("\n--- Waiting for RemoteStartTransaction (send via admin panel) ---")
    while True:
        msg = sim._wait_for_server_call(timeout=30)
        if msg and msg["action"] == "RemoteStartTransaction":
            sim.handle_remote_start(msg)
            break
        elif msg and msg["action"] == "DataTransfer":
            sim.handle_post_boot_state(msg)

    # Send some meter values
    for i in range(3):
        time.sleep(2)
        sim.meter_wh += 500
        sim.send_meter_values()

    # Phase 2: Simulate reboot
    print("\n🔄 SIMULATING REBOOT (EV will be 'unplugged')...")
    sim.disconnect()
    time.sleep(3)

    # Phase 3: Reconnect and receive PostBootState
    sim.connect()
    sim.send_boot_notification()

    data = sim.wait_and_handle_server_calls(timeout=20)
    if data and data.get("hasPendingTransaction"):
        print(f"✅ Received pending transaction. EV not plugged in → sending StopTransaction")

        sim.send_stop_transaction(
            meter_stop_wh=data["lastMeterValueWh"],
            reason="EVDisconnected"
        )
        print(f"✅ TEST PASSED: StopTransaction sent with meterStop={data['lastMeterValueWh']}")
    else:
        print("❌ TEST FAILED: Did not receive PostBootState with pending transaction")

    sim.disconnect()


def test_no_transaction(sim: PostBootStateSimulator):
    """Test: Boot with no active transaction, receive meter-only PostBootState."""
    print("\n" + "=" * 60)
    print("TEST: Boot with no active transaction → Meter restore only")
    print("=" * 60)

    sim.connect()
    sim.send_boot_notification()

    data = sim.wait_and_handle_server_calls(timeout=20)
    if data is not None:
        if not data.get("hasPendingTransaction"):
            print(f"✅ TEST PASSED: Meter restored to {data['lastMeterValueWh']} Wh (no pending transaction)")
        else:
            print(f"⚠️ Unexpected: received pending transaction (txn={data.get('transactionId')})")
    else:
        print("❌ TEST FAILED: No PostBootState received")

    sim.send_status("Available")
    sim.disconnect()


def main():
    parser = argparse.ArgumentParser(description="PostBootState DataTransfer Simulator")
    parser.add_argument("--charger-id", required=True, help="Charge point string ID")
    parser.add_argument("--server", default="ws://localhost:8000", help="OCPP server URL")
    parser.add_argument("--test-resume", action="store_true", help="Test: reboot mid-txn → resume")
    parser.add_argument("--test-stop", action="store_true", help="Test: reboot mid-txn → StopTransaction")
    parser.add_argument("--test-no-txn", action="store_true", help="Test: boot with no active transaction")
    args = parser.parse_args()

    if not any([args.test_resume, args.test_stop, args.test_no_txn]):
        print("Error: specify at least one test mode (--test-resume, --test-stop, --test-no-txn)")
        return

    sim = PostBootStateSimulator(args.charger_id, args.server)

    try:
        if args.test_no_txn:
            test_no_transaction(sim)
        if args.test_resume:
            test_resume(sim)
        if args.test_stop:
            test_stop(sim)
    except KeyboardInterrupt:
        print("\n👋 Interrupted")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        sim.disconnect()


if __name__ == "__main__":
    main()
