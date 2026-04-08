#!/usr/bin/env python3
"""
OCPP 1.6 Simulator for Disconnect/Power Failure Testing

Tests the server's disconnect handler which suspends active transactions
and auto-stops them after a timeout if the charger doesn't reconnect.

Test modes:

  --test-no-reconnect     Disconnect mid-charge, never reconnect. Expect:
                          transaction SUSPENDED -> STOPPED after 180s

  --test-reconnect        Disconnect mid-charge, reconnect after N seconds.
                          Expect: SUSPENDED -> timeout reset on BootNotification
                          -> PostBootState -> resume

  --test-no-transaction   Disconnect with no active transaction.
                          Expect: clean disconnect, no transaction changes

Usage:
    # Never reconnect (transaction should auto-stop after 180s)
    python ocpp_simulator_disconnect.py --charger-id <id> --test-no-reconnect

    # Reconnect after 60s (within 180s window)
    python ocpp_simulator_disconnect.py --charger-id <id> --test-reconnect --reconnect-delay 60

    # Reconnect after 200s (outside 180s window - transaction already stopped)
    python ocpp_simulator_disconnect.py --charger-id <id> --test-reconnect --reconnect-delay 200

    # Disconnect with no active transaction
    python ocpp_simulator_disconnect.py --charger-id <id> --test-no-transaction

    # Against production
    python ocpp_simulator_disconnect.py --charger-id <id> --server wss://app.voltlync.com --test-no-reconnect
"""

import json
import time
import argparse
import sys
import websocket
from datetime import datetime, timezone
from typing import Optional


class DisconnectSimulator:
    """Simulates charger power failure to test disconnect handler."""

    def __init__(self, charge_point_id: str, server_url: str = "ws://localhost:8000"):
        self.charge_point_id = charge_point_id
        self.server_url = server_url
        self.ws = None
        self.message_id_counter = 1
        self.transaction_id = None
        self.meter_wh = 10000
        self._pending_server_calls = []

    def _get_next_message_id(self) -> str:
        msg_id = str(self.message_id_counter)
        self.message_id_counter += 1
        return msg_id

    def _send_message(self, action: str, payload: dict) -> dict:
        """Send OCPP CALL and wait for CALLRESULT."""
        message_id = self._get_next_message_id()
        message = [2, message_id, action, payload]
        print(f"  [{self.charge_point_id}] Sending {action}: {json.dumps(payload)}")
        self.ws.send(json.dumps(message))

        self.ws.settimeout(15.0)
        try:
            while True:
                response_raw = self.ws.recv()
                response = json.loads(response_raw)

                if response[0] == 2:
                    self._pending_server_calls.append(response)
                    print(f"  [{self.charge_point_id}] Queued server CALL: {response[2]}")
                elif response[0] == 3 and response[1] == message_id:
                    print(f"  [{self.charge_point_id}] Response: {action} -> {json.dumps(response[2])}")
                    return response[2]
                elif response[0] == 4 and response[1] == message_id:
                    raise Exception(f"OCPP Error: {response[2]} - {response[3]}")
        except websocket.WebSocketTimeoutException:
            raise Exception(f"{action} timed out")

    def _send_call_result(self, message_id: str, payload: dict):
        """Send CALLRESULT response to a server CALL."""
        response = [3, message_id, payload]
        print(f"  [{self.charge_point_id}] Response: {json.dumps(payload)}")
        self.ws.send(json.dumps(response))

    def _wait_for_server_call(self, timeout: float = 20.0) -> Optional[dict]:
        """Wait for an incoming server CALL."""
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
                else:
                    print(f"  [{self.charge_point_id}] Ignored non-CALL: {raw}")
        except websocket.WebSocketTimeoutException:
            return None

    def _process_queued_calls(self):
        """Process any queued server calls (DataTransfer, etc.)."""
        while self._pending_server_calls:
            msg = self._pending_server_calls.pop(0)
            call = {"message_id": msg[1], "action": msg[2], "payload": msg[3]}
            self._handle_server_call(call)

    def _handle_server_call(self, call: dict) -> Optional[dict]:
        """Handle a server-initiated CALL. Returns parsed data for DataTransfer."""
        action = call["action"]
        print(f"  [{self.charge_point_id}] Received {action}: {json.dumps(call['payload'])}")

        if action == "DataTransfer":
            data = call["payload"].get("data", "{}")
            parsed_data = json.loads(data) if isinstance(data, str) else data
            print(f"  [{self.charge_point_id}] DataTransfer content: {json.dumps(parsed_data, indent=2)}")
            self._send_call_result(call["message_id"], {"status": "Accepted"})
            return parsed_data
        elif action == "RemoteStartTransaction":
            self._send_call_result(call["message_id"], {"status": "Accepted"})
        elif action == "RemoteStopTransaction":
            self._send_call_result(call["message_id"], {"status": "Accepted"})
        else:
            self._send_call_result(call["message_id"], {"status": "Accepted"})
        return None

    # --- Connection ---

    def connect(self):
        url = f"{self.server_url}/ocpp/{self.charge_point_id}"
        print(f"\n  [{self.charge_point_id}] Connecting to {url}")
        self.ws = websocket.create_connection(url)
        print(f"  [{self.charge_point_id}] Connected")

    def disconnect_hard(self):
        """Simulate power failure: close TCP without WebSocket close frame."""
        if self.ws and self.ws.sock:
            self.ws.sock.close()
            print(f"  [{self.charge_point_id}] TCP connection killed (simulating power failure)")
        self.ws = None

    def disconnect_clean(self):
        """Normal WebSocket close."""
        if self.ws:
            self.ws.close()
            print(f"  [{self.charge_point_id}] WebSocket closed cleanly")
        self.ws = None

    # --- OCPP Messages ---

    def send_boot_notification(self, firmware_version: str = "1.0.0") -> dict:
        payload = {
            "chargePointModel": "DisconnectTestModel",
            "chargePointVendor": "SimulatorVendor",
            "firmwareVersion": firmware_version,
        }
        response = self._send_message("BootNotification", payload)
        print(f"  [{self.charge_point_id}] Boot: status={response.get('status')}")
        return response

    def send_heartbeat(self) -> dict:
        return self._send_message("Heartbeat", {})

    def send_status_notification(self, status: str, connector_id: int = 1) -> dict:
        payload = {
            "connectorId": connector_id,
            "status": status,
            "errorCode": "NoError",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._send_message("StatusNotification", payload)
        print(f"  [{self.charge_point_id}] Status: {status}")
        return payload

    def send_start_transaction(self, id_tag: str = "simulator_user") -> dict:
        payload = {
            "connectorId": 1,
            "idTag": id_tag,
            "meterStart": self.meter_wh,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        response = self._send_message("StartTransaction", payload)
        self.transaction_id = response.get("transactionId")
        print(f"  [{self.charge_point_id}] Transaction started: ID={self.transaction_id}")
        return response

    def send_meter_values(self, energy_wh: int) -> dict:
        self.meter_wh += energy_wh
        payload = {
            "connectorId": 1,
            "transactionId": self.transaction_id,
            "meterValue": [{
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sampledValue": [{
                    "value": str(self.meter_wh),
                    "measurand": "Energy.Active.Import.Register",
                    "unit": "Wh",
                }],
            }],
        }
        self._send_message("MeterValues", payload)
        print(f"  [{self.charge_point_id}] MeterValue: {self.meter_wh} Wh (+{energy_wh})")
        return payload

    def send_stop_transaction(self, reason: str = "PowerLoss") -> dict:
        payload = {
            "transactionId": self.transaction_id,
            "meterStop": self.meter_wh,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reason": reason,
        }
        response = self._send_message("StopTransaction", payload)
        print(f"  [{self.charge_point_id}] Transaction stopped: reason={reason}")
        self.transaction_id = None
        return response

    # --- Test Scenarios ---

    def _charging_session(self, duration_seconds: int = 30, meter_interval: int = 10):
        """Run a charging session for a given duration."""
        print(f"\n--- Charging for {duration_seconds}s (meter every {meter_interval}s) ---")
        elapsed = 0
        while elapsed < duration_seconds:
            time.sleep(meter_interval)
            elapsed += meter_interval
            self.send_meter_values(energy_wh=500)
            self.send_heartbeat()

    def _wait_for_remote_start(self, timeout: float = 300.0) -> bool:
        """Wait for RemoteStartTransaction from server, sending heartbeats while waiting."""
        print(f"\n  [{self.charge_point_id}] Waiting for RemoteStartTransaction from server...")
        print(f"  [{self.charge_point_id}] (Trigger a start from the admin panel or API)")
        start_time = time.time()
        heartbeat_interval = 10
        last_heartbeat = time.time()

        while time.time() - start_time < timeout:
            # Send periodic heartbeats
            if time.time() - last_heartbeat >= heartbeat_interval:
                self.send_heartbeat()
                last_heartbeat = time.time()

            # Check for incoming server calls
            call = self._wait_for_server_call(timeout=1.0)
            if call:
                if call["action"] == "RemoteStartTransaction":
                    payload = call["payload"]
                    id_tag = payload.get("idTag", "remote_user")
                    print(f"  [{self.charge_point_id}] RemoteStartTransaction received (idTag={id_tag})")
                    self._send_call_result(call["message_id"], {"status": "Accepted"})
                    self.send_start_transaction(id_tag=id_tag)
                    self._process_queued_calls()
                    self.send_status_notification("Charging")
                    return True
                else:
                    self._handle_server_call(call)

        print(f"  [{self.charge_point_id}] Timed out waiting for RemoteStartTransaction")
        return False

    def test_no_reconnect(self):
        """Test: disconnect mid-charge, never reconnect."""
        print(f"\n{'='*70}")
        print(f"TEST: No Reconnect (power failure, charger stays off)")
        print(f"Expected: transaction SUSPENDED -> STOPPED after ~180s")
        print(f"{'='*70}")

        self.connect()
        self.send_boot_notification()
        self._process_queued_calls()
        self.send_status_notification("Available")
        self.send_heartbeat()

        # Wait for server to initiate charging
        self.send_status_notification("Preparing")
        if not self._wait_for_remote_start():
            print(f"  [{self.charge_point_id}] No RemoteStartTransaction received. Aborting.")
            self.disconnect_clean()
            return

        # Charge for 30 seconds
        self._charging_session(duration_seconds=30, meter_interval=10)

        # Simulate power failure
        print(f"\n{'='*70}")
        print(f"SIMULATING POWER FAILURE (killing TCP connection)")
        print(f"Server should detect silence in ~120s, suspend transaction,")
        print(f"then auto-stop after another ~180s")
        print(f"{'='*70}")
        self.disconnect_hard()

        print(f"\n  Charger is OFF. Not reconnecting.")
        print(f"  Monitor server logs or check transaction status via API.")
        print(f"  Transaction {self.transaction_id} should become:")
        print(f"    -> SUSPENDED  (after ~120s heartbeat timeout)")
        print(f"    -> STOPPED    (after another ~180s disconnect timeout)")
        print(f"\n  Total time from power loss to STOPPED: ~300s (5 min)")

    def test_reconnect(self, reconnect_delay: int = 60):
        """Test: disconnect mid-charge, reconnect after delay."""
        print(f"\n{'='*70}")
        print(f"TEST: Reconnect after {reconnect_delay}s")
        within_window = reconnect_delay < 300  # 120s detect + 180s timeout
        if within_window:
            print(f"Expected: SUSPENDED -> BootNotification resets timeout -> resume")
        else:
            print(f"Expected: SUSPENDED -> STOPPED (reconnect too late)")
        print(f"{'='*70}")

        self.connect()
        self.send_boot_notification()
        self._process_queued_calls()
        self.send_status_notification("Available")
        self.send_heartbeat()

        # Wait for server to initiate charging
        self.send_status_notification("Preparing")
        if not self._wait_for_remote_start():
            print(f"  [{self.charge_point_id}] No RemoteStartTransaction received. Aborting.")
            self.disconnect_clean()
            return

        # Charge for 30 seconds
        self._charging_session(duration_seconds=30, meter_interval=10)
        saved_transaction_id = self.transaction_id

        # Simulate power failure
        print(f"\n{'='*70}")
        print(f"SIMULATING POWER FAILURE (killing TCP connection)")
        print(f"Will reconnect in {reconnect_delay}s...")
        print(f"{'='*70}")
        self.disconnect_hard()

        # Wait, then reconnect
        print(f"\n  Waiting {reconnect_delay}s before reconnect...")
        for i in range(reconnect_delay):
            time.sleep(1)
            remaining = reconnect_delay - i - 1
            if remaining > 0 and remaining % 30 == 0:
                print(f"  ... {remaining}s until reconnect")

        # Reconnect
        print(f"\n{'='*70}")
        print(f"RECONNECTING (simulating power restored)")
        print(f"{'='*70}")
        self._pending_server_calls = []
        self.message_id_counter = 1

        try:
            self.connect()
        except Exception as e:
            print(f"  Failed to reconnect: {e}")
            return

        # Boot notification (charger always sends this on power-up)
        response = self.send_boot_notification()
        if response.get("status") != "Accepted":
            print(f"  BootNotification rejected: {response}")
            self.disconnect_clean()
            return

        # Process PostBootState DataTransfer
        print(f"\n  Waiting for PostBootState from server...")
        post_boot_data = None
        server_call = self._wait_for_server_call(timeout=10)
        if server_call:
            post_boot_data = self._handle_server_call(server_call)

        # Also process any other queued calls
        while self._pending_server_calls:
            msg = self._pending_server_calls.pop(0)
            call = {"message_id": msg[1], "action": msg[2], "payload": msg[3]}
            result = self._handle_server_call(call)
            if result and not post_boot_data:
                post_boot_data = result

        # Check if server says there's a pending transaction to resume
        has_pending = post_boot_data and post_boot_data.get("hasPendingTransaction")

        if has_pending:
            pending_txn_id = post_boot_data.get("transactionId")
            last_meter = post_boot_data.get("lastMeterValueWh", self.meter_wh)
            self.transaction_id = pending_txn_id
            self.meter_wh = last_meter

            print(f"\n{'='*70}")
            print(f"RESUMING transaction {pending_txn_id} (last meter: {last_meter} Wh)")
            print(f"{'='*70}")

            # Resume charging: go Preparing -> Charging
            self.send_status_notification("Preparing")
            self.send_status_notification("Charging")

            # Continue charging for 30 more seconds
            self._charging_session(duration_seconds=30, meter_interval=10)

            # Stop transaction normally
            self.send_stop_transaction(reason="Local")
            self.send_status_notification("Available")
        else:
            print(f"\n  No pending transaction to resume.")
            if post_boot_data:
                print(f"  PostBootState: {json.dumps(post_boot_data)}")
            self.send_status_notification("Available")
            self.send_heartbeat()

        print(f"\n  Test complete. Check transaction {saved_transaction_id} status via API.")
        self.disconnect_clean()

    def test_no_transaction(self):
        """Test: disconnect with no active transaction."""
        print(f"\n{'='*70}")
        print(f"TEST: Disconnect with no active transaction")
        print(f"Expected: clean disconnect, no transaction changes")
        print(f"{'='*70}")

        self.connect()
        self.send_boot_notification()
        self._process_queued_calls()
        self.send_status_notification("Available")

        # Send a few heartbeats
        for _ in range(3):
            self.send_heartbeat()
            time.sleep(5)

        # Simulate power failure
        print(f"\n  Simulating power failure with no active transaction...")
        self.disconnect_hard()

        print(f"\n  Charger is OFF. No transaction was active.")
        print(f"  Server should detect disconnect in ~120s but take no transaction action.")


def main():
    parser = argparse.ArgumentParser(
        description="OCPP 1.6 Simulator - Disconnect/Power Failure Testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Never reconnect (test full timeout flow)
  python ocpp_simulator_disconnect.py --charger-id <id> --test-no-reconnect

  # Reconnect within timeout window (60s)
  python ocpp_simulator_disconnect.py --charger-id <id> --test-reconnect --reconnect-delay 60

  # Reconnect after timeout expires (200s > 180s disconnect timeout)
  python ocpp_simulator_disconnect.py --charger-id <id> --test-reconnect --reconnect-delay 200

  # No active transaction
  python ocpp_simulator_disconnect.py --charger-id <id> --test-no-transaction

  # Against production
  python ocpp_simulator_disconnect.py --charger-id <id> --server wss://app.voltlync.com --test-reconnect
        """,
    )

    parser.add_argument("--charger-id", required=True, help="Charge point ID")
    parser.add_argument(
        "--server", default="ws://localhost:8000", help="OCPP server URL"
    )

    test_group = parser.add_mutually_exclusive_group(required=True)
    test_group.add_argument(
        "--test-no-reconnect",
        action="store_true",
        help="Disconnect mid-charge, never reconnect",
    )
    test_group.add_argument(
        "--test-reconnect",
        action="store_true",
        help="Disconnect mid-charge, reconnect after delay",
    )
    test_group.add_argument(
        "--test-no-transaction",
        action="store_true",
        help="Disconnect with no active transaction",
    )

    parser.add_argument(
        "--reconnect-delay",
        type=int,
        default=60,
        help="Seconds to wait before reconnecting (default: 60)",
    )

    args = parser.parse_args()

    sim = DisconnectSimulator(args.charger_id, args.server)

    try:
        if args.test_no_reconnect:
            sim.test_no_reconnect()
        elif args.test_reconnect:
            sim.test_reconnect(reconnect_delay=args.reconnect_delay)
        elif args.test_no_transaction:
            sim.test_no_transaction()
    except KeyboardInterrupt:
        print(f"\n  Simulator stopped by user")
    except Exception as e:
        print(f"\n  Simulator error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
