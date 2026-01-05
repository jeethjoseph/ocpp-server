#!/usr/bin/env python3
"""
Simple OCPP 1.6 Test Simulator for External Servers

Usage:
    python ocpp_test_external.py ws://tgs.console.chargemod.com:8180/ocpp/css/JETEV010
    python ocpp_test_external.py wss://server.com/ocpp/CHARGER_ID --debug
"""

import asyncio
import json
import time
import argparse
import signal
import sys
import websocket


class SimpleOCPPTester:
    """Simple OCPP 1.6 tester for external servers"""

    def __init__(self, full_url: str, debug: bool = False):
        self.full_url = full_url
        self.debug = debug
        self.ws = None
        self.message_id = 1
        self.running = False

    def _next_id(self) -> str:
        msg_id = str(self.message_id)
        self.message_id += 1
        return msg_id

    def _send(self, action: str, payload: dict) -> dict:
        """Send OCPP CALL and wait for response"""
        msg_id = self._next_id()
        message = [2, msg_id, action, payload]

        print(f"📤 Sending {action}")
        if self.debug:
            print(f"   Payload: {json.dumps(payload, indent=2)}")

        self.ws.send(json.dumps(message))

        self.ws.settimeout(10.0)
        try:
            response_raw = self.ws.recv()
            response = json.loads(response_raw)

            if response[0] == 3:  # CALLRESULT
                print(f"📥 Response: {action} OK")
                if self.debug:
                    print(f"   Result: {json.dumps(response[2], indent=2)}")
                return response[2]
            elif response[0] == 4:  # CALLERROR
                print(f"❌ Error: {response[2]} - {response[3]}")
                return None
            else:
                print(f"❓ Unknown response type: {response[0]}")
                return None
        except websocket.WebSocketTimeoutException:
            print(f"⏰ Timeout waiting for {action} response")
            return None
        except Exception as e:
            print(f"❌ Error: {e}")
            return None

    def _handle_incoming(self, message: str):
        """Handle incoming CALL from server"""
        try:
            parsed = json.loads(message)
            if parsed[0] == 2:  # CALL
                msg_id, action, payload = parsed[1], parsed[2], parsed[3]
                print(f"📥 Server request: {action}")
                if self.debug:
                    print(f"   Payload: {json.dumps(payload, indent=2)}")

                # Auto-respond with Accepted for common actions
                if action in ["RemoteStartTransaction", "RemoteStopTransaction", "Reset",
                              "ChangeConfiguration", "GetConfiguration", "TriggerMessage"]:
                    response = [3, msg_id, {"status": "Accepted"}]
                    self.ws.send(json.dumps(response))
                    print(f"📤 Responded: Accepted")
                else:
                    print(f"⚠️  Unknown action, not responding")
        except Exception as e:
            if self.debug:
                print(f"❌ Parse error: {e}")

    def connect(self) -> bool:
        """Connect to OCPP server"""
        print(f"\n{'='*60}")
        print(f"🔌 Connecting to: {self.full_url}")
        print(f"{'='*60}\n")

        try:
            self.ws = websocket.create_connection(
                self.full_url,
                subprotocols=["ocpp1.6"],
                timeout=10
            )
            print(f"✅ WebSocket connected!")
            self.running = True
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from server"""
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
            print(f"🔌 Disconnected")

    def boot(self) -> bool:
        """Send BootNotification"""
        print("\n--- Boot Notification ---")
        result = self._send("BootNotification", {
            "chargePointModel": "TestSimulator",
            "chargePointVendor": "MakaraTech",
            "firmwareVersion": "1.0.0",
            "chargePointSerialNumber": "TEST001"
        })

        if result and result.get("status") == "Accepted":
            print(f"🚀 Boot accepted! Server time: {result.get('currentTime', 'N/A')}")
            return True
        else:
            print(f"⚠️  Boot status: {result.get('status', 'Unknown') if result else 'No response'}")
            return False

    def heartbeat(self) -> bool:
        """Send Heartbeat"""
        result = self._send("Heartbeat", {})
        if result:
            print(f"💓 Heartbeat OK - Server time: {result.get('currentTime', 'N/A')}")
            return True
        return False

    def status(self, status: str = "Available", connector: int = 1):
        """Send StatusNotification"""
        print(f"\n--- Status: {status} ---")
        self._send("StatusNotification", {
            "connectorId": connector,
            "status": status,
            "errorCode": "NoError",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        })

    def listen_for_messages(self, timeout: float = 0.5):
        """Check for incoming server messages"""
        try:
            self.ws.settimeout(timeout)
            message = self.ws.recv()
            self._handle_incoming(message)
        except websocket.WebSocketTimeoutException:
            pass
        except Exception as e:
            if self.running and self.debug:
                print(f"❌ Listen error: {e}")

    def start_transaction(self, id_tag: str = "TEST_USER", connector: int = 1) -> int:
        """Send StartTransaction"""
        print(f"\n--- Starting Transaction ---")
        result = self._send("StartTransaction", {
            "connectorId": connector,
            "idTag": id_tag,
            "meterStart": 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        })

        if result and "transactionId" in result:
            txn_id = result["transactionId"]
            print(f"🔋 Transaction started! ID: {txn_id}")
            return txn_id
        else:
            print(f"⚠️  StartTransaction failed")
            return None

    def stop_transaction(self, transaction_id: int, meter_stop: int, reason: str = "Local") -> bool:
        """Send StopTransaction"""
        print(f"\n--- Stopping Transaction {transaction_id} ---")
        result = self._send("StopTransaction", {
            "transactionId": transaction_id,
            "meterStop": meter_stop,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "reason": reason
        })

        if result is not None:
            print(f"🛑 Transaction {transaction_id} stopped! Final energy: {meter_stop} Wh ({meter_stop/1000:.2f} kWh)")
            return True
        return False

    def send_meter_values(self, connector: int, transaction_id: int, energy_wh: int, power_w: int = 7400):
        """Send MeterValues"""
        import random

        # Add realistic variation
        current_a = (power_w / 230) * random.uniform(0.95, 1.05)
        voltage_v = 230 * random.uniform(0.98, 1.02)

        self._send("MeterValues", {
            "connectorId": connector,
            "transactionId": transaction_id,
            "meterValue": [{
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "sampledValue": [
                    {"value": str(energy_wh), "measurand": "Energy.Active.Import.Register", "unit": "Wh"},
                    {"value": str(int(power_w)), "measurand": "Power.Active.Import", "unit": "W"},
                    {"value": f"{current_a:.1f}", "measurand": "Current.Import", "unit": "A"},
                    {"value": f"{voltage_v:.1f}", "measurand": "Voltage", "unit": "V"}
                ]
            }]
        })
        print(f"⚡ Meter: {energy_wh} Wh ({energy_wh/1000:.2f} kWh), {power_w/1000:.1f} kW")

    async def run_with_transaction(self, start_delay: int = 60, charge_duration: int = 300,
                                    heartbeat_interval: int = 10, meter_interval: int = 30):
        """Run test with a timed transaction"""
        if not self.connect():
            return

        try:
            # Boot sequence
            if not self.boot():
                print("⚠️  Boot not accepted, continuing anyway...")

            # Initial status
            self.status("Available")

            print(f"\n{'='*60}")
            print(f"📋 Test Plan:")
            print(f"   1. Wait {start_delay}s before starting transaction")
            print(f"   2. Charge for {charge_duration}s ({charge_duration/60:.1f} minutes)")
            print(f"   3. Stop transaction and finish")
            print(f"   Heartbeat: every {heartbeat_interval}s")
            print(f"   Meter values: every {meter_interval}s during charging")
            print(f"   Press Ctrl+C to stop")
            print(f"{'='*60}\n")

            transaction_id = None
            transaction_start_time = None
            charging_power_w = 7400  # 7.4 kW

            start_time = time.time()
            last_heartbeat = start_time
            last_meter = start_time

            while self.running:
                current_time = time.time()
                elapsed = current_time - start_time

                # Phase 1: Wait before starting transaction
                if transaction_id is None and elapsed >= start_delay:
                    self.status("Preparing")
                    await asyncio.sleep(1)
                    self.status("Charging")
                    transaction_id = self.start_transaction()
                    transaction_start_time = current_time
                    last_meter = current_time

                # Phase 2: During transaction - send meter values
                if transaction_id and transaction_start_time:
                    charge_elapsed = current_time - transaction_start_time

                    # Send meter values periodically
                    if current_time - last_meter >= meter_interval:
                        energy_wh = int((charging_power_w * charge_elapsed) / 3600)
                        self.send_meter_values(1, transaction_id, energy_wh, charging_power_w)
                        last_meter = current_time

                    # Phase 3: Stop transaction after charge duration
                    if charge_elapsed >= charge_duration:
                        final_energy = int((charging_power_w * charge_elapsed) / 3600)
                        self.status("Finishing")
                        await asyncio.sleep(1)
                        self.stop_transaction(transaction_id, final_energy)
                        self.status("Available")
                        print(f"\n✅ Test completed successfully!")
                        break

                # Send heartbeat periodically
                if current_time - last_heartbeat >= heartbeat_interval:
                    self.heartbeat()
                    last_heartbeat = current_time

                # Listen for server messages
                self.listen_for_messages(timeout=0.5)

                # Progress indicator
                if transaction_id and transaction_start_time:
                    remaining = charge_duration - (current_time - transaction_start_time)
                    if int(remaining) % 30 == 0 and int(remaining) > 0:
                        print(f"⏱️  Charging... {int(remaining)}s remaining")

                await asyncio.sleep(0.1)

        except KeyboardInterrupt:
            print(f"\n🛑 Stopped by user")
            if transaction_id:
                charge_elapsed = time.time() - transaction_start_time
                final_energy = int((charging_power_w * charge_elapsed) / 3600)
                self.stop_transaction(transaction_id, final_energy, reason="Local")
        finally:
            self.disconnect()

    async def run(self, duration: int = 60, heartbeat_interval: int = 10):
        """Run the test simulation"""
        if not self.connect():
            return

        try:
            # Boot sequence
            if not self.boot():
                print("⚠️  Boot not accepted, continuing anyway...")

            # Initial status
            self.status("Available")

            print(f"\n{'='*60}")
            print(f"🔄 Running for {duration}s (heartbeat every {heartbeat_interval}s)")
            print(f"   Waiting for server commands...")
            print(f"   Press Ctrl+C to stop")
            print(f"{'='*60}\n")

            start_time = time.time()
            last_heartbeat = start_time

            while self.running and (time.time() - start_time) < duration:
                # Send heartbeat periodically
                if time.time() - last_heartbeat >= heartbeat_interval:
                    self.heartbeat()
                    last_heartbeat = time.time()

                # Listen for server messages
                self.listen_for_messages(timeout=0.5)

                await asyncio.sleep(0.1)

            print(f"\n✅ Test completed after {int(time.time() - start_time)}s")

        except KeyboardInterrupt:
            print(f"\n🛑 Stopped by user")
        finally:
            self.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Simple OCPP 1.6 External Server Tester")
    parser.add_argument("url", help="Full WebSocket URL (e.g., ws://server:8180/ocpp/css/CHARGER)")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug output")
    parser.add_argument("--duration", "-t", type=int, default=120, help="Test duration in seconds (default: 120)")
    parser.add_argument("--heartbeat", "-hb", type=int, default=10, help="Heartbeat interval (default: 10s)")

    # Transaction mode (default)
    parser.add_argument("--no-transaction", action="store_true", help="Skip transaction test, just heartbeats")
    parser.add_argument("--start-delay", type=int, default=60, help="Seconds before starting transaction (default: 60)")
    parser.add_argument("--charge-duration", type=int, default=300, help="Charging duration in seconds (default: 300 = 5 min)")
    parser.add_argument("--meter-interval", type=int, default=30, help="Meter value interval during charging (default: 30s)")

    args = parser.parse_args()

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    tester = SimpleOCPPTester(args.url, debug=args.debug)

    if args.no_transaction:
        asyncio.run(tester.run(duration=args.duration, heartbeat_interval=args.heartbeat))
    else:
        # Default: run with transaction
        asyncio.run(tester.run_with_transaction(
            start_delay=args.start_delay,
            charge_duration=args.charge_duration,
            heartbeat_interval=args.heartbeat,
            meter_interval=args.meter_interval
        ))


if __name__ == "__main__":
    main()
