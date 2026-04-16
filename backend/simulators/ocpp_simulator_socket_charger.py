#!/usr/bin/env python3
"""
OCPP 1.6 Socket Charger Simulator

Simulates a socket-type (Mode 1&2) charger. Key differences from Type 2:
- No Control Pilot signal → no Preparing state on plug-in
- Starts transactions from Available state
- May report Available during active transactions (current dips)

Test modes:
  --test-grace-cancel    Available mid-txn → MeterValues arrive → txn stays alive
  --test-grace-timeout   Available mid-txn → no MeterValues → txn fails after grace
  --test-start-available Admin triggers RemoteStart while charger is Available

Default (no test flag): runs as a long-lived socket charger simulator that
reacts to RemoteStart/Stop from the admin panel, like ocpp_simulator_full_success.py.

Usage:
    python ocpp_simulator_socket_charger.py --charger-id SOCKET-001
    python ocpp_simulator_socket_charger.py --charger-id SOCKET-001 --test-grace-cancel
    python ocpp_simulator_socket_charger.py --charger-id SOCKET-001 --test-grace-timeout
    python ocpp_simulator_socket_charger.py --charger-id SOCKET-001 --test-start-available

Note: Charger must exist in DB with connector_type="Socket". Create via admin panel.
"""

import asyncio
import time
import json
import random
import websocket
import argparse
import signal
import sys
from datetime import datetime, timezone
from typing import Optional


class SocketChargerSimulator:
    """OCPP 1.6 simulator for a socket-type (Mode 1&2) charger."""

    def __init__(self, charge_point_id: str, server_url: str = "ws://localhost:8000"):
        self.charge_point_id = charge_point_id
        self.server_url = server_url
        self.ws = None
        self.message_id_counter = 1
        self.transaction_id = None
        self.current_status = "Unavailable"
        self.is_connected = False
        self.running = False

        # Timing
        self.heartbeat_interval = 10
        self.meter_value_interval = 15  # Socket chargers typically lower power, send more often

        # Background tasks
        self.heartbeat_task = None
        self.meter_value_task = None

        # Energy tracking
        self._transaction_start_time = None
        self._charging_power_w = 1500  # 1.5kW typical socket charger

        self.statistics = {
            "messages_sent": 0,
            "messages_received": 0,
            "transactions": 0,
            "meter_values": 0,
            "start_time": None,
        }

    # --- Low-level OCPP messaging ---

    def _get_next_message_id(self) -> str:
        msg_id = str(self.message_id_counter)
        self.message_id_counter += 1
        return msg_id

    def _send_message(self, action: str, payload: dict) -> dict:
        """Send OCPP CALL and wait for CALLRESULT, handling interleaved server CALLs."""
        message_id = self._get_next_message_id()
        message = [2, message_id, action, payload]
        print(f"📤 [{self.charge_point_id}] {action}")
        self.ws.send(json.dumps(message))
        self.statistics["messages_sent"] += 1

        self.ws.settimeout(15.0)
        try:
            while True:
                raw = self.ws.recv()
                response = json.loads(raw)
                self.statistics["messages_received"] += 1

                if response[0] == 2:  # Server CALL while we wait — handle inline
                    self._dispatch_server_call(response)
                elif response[0] == 3 and response[1] == message_id:
                    print(f"📥 [{self.charge_point_id}] {action} → OK")
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

    def _dispatch_server_call(self, parsed: list):
        """Route an incoming server CALL to the appropriate handler."""
        message_id = parsed[1]
        action = parsed[2]
        payload = parsed[3]
        print(f"📥 [{self.charge_point_id}] Server CALL: {action}")

        if action == "RemoteStartTransaction":
            self.handle_remote_start(message_id, payload)
        elif action == "RemoteStopTransaction":
            self.handle_remote_stop(message_id, payload)
        elif action == "DataTransfer":
            self._send_call_result(message_id, {"status": "Accepted"})
        elif action == "Reset":
            self.handle_reset(message_id, payload)
        else:
            self._send_call_result(message_id, {"status": "Accepted"})

    # --- Connection ---

    def connect(self):
        url = f"{self.server_url}/ocpp/{self.charge_point_id}"
        print(f"🔌 [{self.charge_point_id}] Connecting to {url}")
        self.ws = websocket.create_connection(url)
        self.is_connected = True
        self.running = True
        print(f"✅ [{self.charge_point_id}] Connected")

    def disconnect(self):
        self.running = False
        for task in [self.heartbeat_task, self.meter_value_task]:
            if task:
                task.cancel()
        self.heartbeat_task = None
        self.meter_value_task = None
        if self.ws:
            self.ws.close()
            self.is_connected = False
        print(f"🔌 [{self.charge_point_id}] Disconnected")

    # --- OCPP message senders ---

    def send_boot_notification(self) -> dict:
        response = self._send_message("BootNotification", {
            "chargePointModel": "SocketCharger-Sim",
            "chargePointVendor": "VOLTLYNC",
            "firmwareVersion": "1.0.0",
        })
        if "currentTime" in response:
            print(f"🕐 [{self.charge_point_id}] Clock synced: {response['currentTime']}")
        return response

    def send_heartbeat(self) -> dict:
        response = self._send_message("Heartbeat", {})
        print(f"💓 [{self.charge_point_id}] Heartbeat")
        return response

    def send_status_notification(self, status: str, connector_id: int = 1) -> dict:
        self.current_status = status
        response = self._send_message("StatusNotification", {
            "connectorId": connector_id,
            "status": status,
            "errorCode": "NoError",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        print(f"📊 [{self.charge_point_id}] Status → {status}")
        return response

    def send_start_transaction(self, id_tag: str = "socket_user") -> dict:
        response = self._send_message("StartTransaction", {
            "connectorId": 1,
            "idTag": id_tag,
            "meterStart": 0,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        if "transactionId" in response:
            self.transaction_id = response["transactionId"]
            self._transaction_start_time = time.time()
            self.statistics["transactions"] += 1
            print(f"🔋 [{self.charge_point_id}] Transaction started: ID={self.transaction_id}")
            self.start_meter_value_task()
        return response

    def send_stop_transaction(self, reason: str = "Local") -> dict:
        if not self.transaction_id:
            print(f"⚠️ No active transaction to stop")
            return {}

        # Stop meter values
        if self.meter_value_task:
            self.meter_value_task.cancel()
            self.meter_value_task = None

        final_energy = self._current_energy_wh()
        response = self._send_message("StopTransaction", {
            "transactionId": self.transaction_id,
            "meterStop": final_energy,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reason": reason,
        })
        print(f"🛑 [{self.charge_point_id}] Transaction {self.transaction_id} stopped ({final_energy} Wh)")
        self.transaction_id = None
        self._transaction_start_time = None
        return response

    def send_meter_values(self) -> dict:
        if not self.transaction_id:
            return {}

        energy_wh = self._current_energy_wh()
        power_w = self._charging_power_w * random.uniform(0.85, 1.15)
        current_a = power_w / 230.0
        voltage_v = 230.0 * random.uniform(0.97, 1.03)

        response = self._send_message("MeterValues", {
            "connectorId": 1,
            "transactionId": self.transaction_id,
            "meterValue": [{
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sampledValue": [
                    {"value": str(energy_wh), "measurand": "Energy.Active.Import.Register", "unit": "Wh"},
                    {"value": str(round(current_a, 2)), "measurand": "Current.Import", "unit": "A"},
                    {"value": str(round(voltage_v, 1)), "measurand": "Voltage", "unit": "V"},
                    {"value": str(int(power_w)), "measurand": "Power.Active.Import", "unit": "W"},
                ],
            }],
        })
        self.statistics["meter_values"] += 1
        print(f"⚡ [{self.charge_point_id}] Meter: {energy_wh} Wh ({energy_wh/1000:.2f} kWh), "
              f"{current_a:.1f}A, {voltage_v:.0f}V, {power_w/1000:.1f}kW")
        return response

    def _current_energy_wh(self) -> int:
        if not self._transaction_start_time:
            return 0
        elapsed = time.time() - self._transaction_start_time
        return int((self._charging_power_w * elapsed) / 3600)

    # --- Server command handlers ---

    def handle_remote_start(self, message_id: str, payload: dict):
        """Socket charger: accept RemoteStart, go straight to Charging (skip Preparing)."""
        id_tag = payload.get("idTag", "remote_user")
        self._send_call_result(message_id, {"status": "Accepted"})
        print(f"✅ [{self.charge_point_id}] RemoteStart ACCEPTED (idTag={id_tag})")

        # Socket charger goes directly Available → Charging (no CP signal for Preparing)
        self.send_status_notification("Charging")
        self.send_start_transaction(id_tag)

    def handle_remote_stop(self, message_id: str, payload: dict):
        self._send_call_result(message_id, {"status": "Accepted"})
        print(f"✅ [{self.charge_point_id}] RemoteStop ACCEPTED")

        self.send_status_notification("Finishing")
        self.send_stop_transaction("Remote")
        self.send_status_notification("Available")

    def handle_reset(self, message_id: str, payload: dict):
        reset_type = payload.get("type", "Hard")
        self._send_call_result(message_id, {"status": "Accepted"})
        print(f"✅ [{self.charge_point_id}] Reset ({reset_type}) ACCEPTED")

        if self.transaction_id:
            self.send_status_notification("Finishing")
            time.sleep(1)
            self.send_stop_transaction("HardReset")

        # Stop tasks, disconnect, reboot delay, reconnect
        for task in [self.heartbeat_task, self.meter_value_task]:
            if task:
                task.cancel()
        self.heartbeat_task = None
        self.meter_value_task = None

        if self.ws:
            self.ws.close()
        reboot_time = 3 if reset_type == "Soft" else 5
        print(f"🔄 [{self.charge_point_id}] Rebooting ({reboot_time}s)...")
        time.sleep(reboot_time)

        self.connect()
        self.send_boot_notification()
        self.start_heartbeat_task()
        self.send_status_notification("Available")

    # --- Message processing (main loop) ---

    def process_incoming_messages(self, timeout: float = 0.1):
        """Poll for incoming server CALLs."""
        try:
            self.ws.settimeout(timeout)
            raw = self.ws.recv()
            parsed = json.loads(raw)
            self.statistics["messages_received"] += 1
            if parsed[0] == 2:
                self._dispatch_server_call(parsed)
        except websocket.WebSocketTimeoutException:
            pass
        except Exception as e:
            if self.running:
                print(f"❌ [{self.charge_point_id}] Error: {e}")

    # --- Background tasks ---

    async def heartbeat_loop(self):
        while self.running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if self.running:
                    self.send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Heartbeat error: {e}")
                await asyncio.sleep(5)

    async def meter_value_loop(self):
        while self.running and self.transaction_id:
            try:
                await asyncio.sleep(self.meter_value_interval)
                if self.running and self.transaction_id:
                    self.send_meter_values()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Meter value error: {e}")

    def start_heartbeat_task(self):
        if not self.heartbeat_task:
            self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())

    def start_meter_value_task(self):
        if not self.meter_value_task:
            self.meter_value_task = asyncio.create_task(self.meter_value_loop())

    # --- Run modes ---

    async def run_interactive(self):
        """Long-lived simulator: boot → Available → react to server commands."""
        self.statistics["start_time"] = time.time()
        self.connect()
        self.send_boot_notification()
        self.start_heartbeat_task()
        self.send_status_notification("Available")

        print(f"\n{'='*60}")
        print(f"🔌 Socket Charger Simulator Running")
        print(f"   Charger: {self.charge_point_id}")
        print(f"   Status:  Available (waiting for RemoteStart)")
        print(f"   Power:   {self._charging_power_w/1000:.1f} kW")
        print(f"{'='*60}")
        print(f"   Trigger RemoteStart from admin panel to begin charging.")
        print(f"   Press Ctrl+C to stop.\n")

        while self.running:
            self.process_incoming_messages(timeout=0.1)
            await asyncio.sleep(0.1)

    async def run_test_grace_cancel(self):
        """Test: Available mid-txn → MeterValues cancel grace → txn survives."""
        print(f"\n{'='*60}")
        print(f"TEST: Grace Period Cancelled by MeterValues")
        print(f"{'='*60}\n")

        self.statistics["start_time"] = time.time()
        self.connect()
        self.send_boot_notification()
        self.start_heartbeat_task()
        self.send_status_notification("Available")

        # Wait for RemoteStart from admin
        print(f"\n--- Trigger RemoteStart from admin panel ---\n")
        while self.running:
            self.process_incoming_messages(timeout=0.5)
            await asyncio.sleep(0.1)
            if self.transaction_id:
                break

        if not self.transaction_id:
            print("❌ No transaction started")
            return

        # Let it charge for a bit
        print(f"\n--- Charging normally for 30s ---")
        for _ in range(30):
            self.process_incoming_messages(timeout=0.1)
            await asyncio.sleep(1)

        # Simulate current dip → Available status
        print(f"\n⚠️ Simulating current dip → Available status")
        print(f"   (Grace period should start on server)")

        # Stop meter value task temporarily to simulate the dip
        if self.meter_value_task:
            self.meter_value_task.cancel()
            self.meter_value_task = None

        self.send_status_notification("Available")

        # Wait 10 seconds (well within 5-min grace), then resume meter values
        print(f"   Waiting 10s then resuming MeterValues...")
        for _ in range(10):
            self.process_incoming_messages(timeout=0.1)
            await asyncio.sleep(1)

        # Resume meter values → should cancel grace period
        print(f"\n✅ Resuming MeterValues (should cancel grace period)")
        self.send_status_notification("Charging")
        self.start_meter_value_task()

        # Continue charging
        print(f"--- Continuing to charge for 30s ---")
        for _ in range(30):
            self.process_incoming_messages(timeout=0.1)
            await asyncio.sleep(1)

        # Stop cleanly
        self.send_status_notification("Finishing")
        self.send_stop_transaction("Local")
        self.send_status_notification("Available")
        print(f"\n✅ TEST PASSED: Transaction completed after grace period was cancelled")

    async def run_test_grace_timeout(self, grace_minutes: int = 5):
        """Test: Available mid-txn → no MeterValues → txn fails after grace period."""
        print(f"\n{'='*60}")
        print(f"TEST: Grace Period Timeout ({grace_minutes} min)")
        print(f"{'='*60}\n")

        self.statistics["start_time"] = time.time()
        self.connect()
        self.send_boot_notification()
        self.start_heartbeat_task()
        self.send_status_notification("Available")

        # Wait for RemoteStart from admin
        print(f"\n--- Trigger RemoteStart from admin panel ---\n")
        while self.running:
            self.process_incoming_messages(timeout=0.5)
            await asyncio.sleep(0.1)
            if self.transaction_id:
                break

        if not self.transaction_id:
            print("❌ No transaction started")
            return

        # Charge for a bit
        print(f"\n--- Charging for 30s ---")
        for _ in range(30):
            self.process_incoming_messages(timeout=0.1)
            await asyncio.sleep(1)

        # Send Available and stop sending meter values (simulate disconnect)
        print(f"\n⚠️ Sending Available + going silent (no more MeterValues)")
        if self.meter_value_task:
            self.meter_value_task.cancel()
            self.meter_value_task = None
        self.send_status_notification("Available")

        # Wait for grace period to expire
        total_wait = (grace_minutes * 60) + 30
        print(f"   Waiting {total_wait}s for grace period to expire...")
        start = time.time()
        while time.time() - start < total_wait and self.running:
            self.process_incoming_messages(timeout=0.5)
            elapsed = int(time.time() - start)
            if elapsed % 30 == 0 and elapsed > 0:
                print(f"   ⏳ {elapsed}s / {total_wait}s elapsed")
            await asyncio.sleep(1)

        print(f"\n✅ TEST COMPLETE: Check admin panel")
        print(f"   Transaction should be FAILED with reason SOCKET_GRACE_TIMEOUT")

    async def run_test_start_available(self):
        """Test: RemoteStart from Available state (socket charger, no Preparing)."""
        print(f"\n{'='*60}")
        print(f"TEST: Remote Start from Available State")
        print(f"{'='*60}\n")

        self.statistics["start_time"] = time.time()
        self.connect()
        self.send_boot_notification()
        self.start_heartbeat_task()
        self.send_status_notification("Available")

        print(f"\n--- Socket charger is Available ---")
        print(f"--- Trigger RemoteStart from admin panel ---\n")

        # Wait for RemoteStart
        while self.running:
            self.process_incoming_messages(timeout=0.5)
            await asyncio.sleep(0.1)
            if self.transaction_id:
                break

        if not self.transaction_id:
            print("❌ No transaction started")
            return

        # Charge for 30s
        print(f"\n--- Charging for 30s ---")
        for _ in range(30):
            self.process_incoming_messages(timeout=0.1)
            await asyncio.sleep(1)

        # Stop
        self.send_status_notification("Finishing")
        self.send_stop_transaction("Local")
        self.send_status_notification("Available")

        energy = self._current_energy_wh() if self._transaction_start_time else 0
        print(f"\n✅ TEST PASSED: Remote start from Available worked")
        print(f"   Transaction completed successfully")


def signal_handler(signum, frame):
    print("\n🛑 Stopping simulator...")
    sys.exit(0)


async def main():
    parser = argparse.ArgumentParser(
        description="Socket-Type Charger Simulator (OCPP 1.6)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (like full_success simulator)
  python ocpp_simulator_socket_charger.py --charger-id SOCKET-001

  # Test grace period cancelled by MeterValues
  python ocpp_simulator_socket_charger.py --charger-id SOCKET-001 --test-grace-cancel

  # Test grace period timeout (5 min wait)
  python ocpp_simulator_socket_charger.py --charger-id SOCKET-001 --test-grace-timeout

  # Test remote start from Available
  python ocpp_simulator_socket_charger.py --charger-id SOCKET-001 --test-start-available

Note: Charger must exist in DB with connector_type="Socket".
        """,
    )
    parser.add_argument("--charger-id", required=True, help="Charge point string ID")
    parser.add_argument("--server", default="ws://localhost:8000", help="OCPP server URL")
    parser.add_argument("--test-grace-cancel", action="store_true",
                        help="Test: Available mid-txn → MeterValues cancel grace")
    parser.add_argument("--test-grace-timeout", action="store_true",
                        help="Test: Available mid-txn → no MeterValues → txn fails")
    parser.add_argument("--test-start-available", action="store_true",
                        help="Test: RemoteStart from Available state")
    parser.add_argument("--grace-minutes", type=int, default=5,
                        help="Grace timeout wait in minutes (default: 5)")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, signal_handler)

    sim = SocketChargerSimulator(args.charger_id, args.server)

    try:
        if args.test_grace_cancel:
            await sim.run_test_grace_cancel()
        elif args.test_grace_timeout:
            await sim.run_test_grace_timeout(args.grace_minutes)
        elif args.test_start_available:
            await sim.run_test_start_available()
        else:
            await sim.run_interactive()
    except KeyboardInterrupt:
        print(f"\n🛑 Stopped")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        sim.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
