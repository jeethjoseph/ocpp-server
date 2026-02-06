#!/usr/bin/env python3
"""
OCPP 1.6 Vendor Error Code Simulator

This simulator tests the vendor error code feature:
1. Connects to OCPP server
2. Sends StatusNotification with standard error codes
3. Sends StatusNotification with vendor-specific error codes
4. Sends "NoError" to resolve errors
5. Demonstrates the complete error lifecycle

Usage:
    python ocpp_simulator_vendor_errors.py --charger-id <charger-id>
    python ocpp_simulator_vendor_errors.py --charger-id <charger-id> --server ws://localhost:8000
"""

import time
import json
import websocket
import argparse
import sys
from typing import Optional


class VendorErrorSimulator:
    """OCPP 1.6 Simulator for testing vendor error codes"""

    def __init__(self, charge_point_id: str, server_url: str = "ws://localhost:8000"):
        self.charge_point_id = charge_point_id
        self.server_url = server_url
        self.ws = None
        self.message_id_counter = 1
        self.is_connected = False

    def _get_next_message_id(self) -> str:
        """Generate next unique message ID"""
        msg_id = str(self.message_id_counter)
        self.message_id_counter += 1
        return msg_id

    def _send_message(self, action: str, payload: dict) -> dict:
        """Send OCPP message and wait for response"""
        message_id = self._get_next_message_id()
        message = [2, message_id, action, payload]

        print(f"\n{'='*60}")
        print(f">>> Sending {action}")
        print(f"    Payload: {json.dumps(payload, indent=4)}")

        self.ws.send(json.dumps(message))

        self.ws.settimeout(10.0)
        try:
            response_raw = self.ws.recv()
            response = json.loads(response_raw)

            if response[0] == 3:  # CALLRESULT
                print(f"<<< Response: OK")
                return response[2]
            elif response[0] == 4:  # CALLERROR
                print(f"<<< Error: {response[2]} - {response[3]}")
                raise Exception(f"OCPP Error: {response[2]}")
            else:
                raise Exception(f"Unknown response type: {response[0]}")
        except websocket.WebSocketTimeoutException:
            print(f"<<< Timeout!")
            raise

    def connect(self):
        """Connect to OCPP server"""
        url = f"{self.server_url}/ocpp/{self.charge_point_id}"
        print(f"\nConnecting to {url}")
        self.ws = websocket.create_connection(url)
        self.is_connected = True
        print("Connected!")

    def disconnect(self):
        """Disconnect from server"""
        if self.ws:
            self.ws.close()
            self.is_connected = False
            print("\nDisconnected from server")

    def send_boot_notification(self) -> dict:
        """Send BootNotification"""
        payload = {
            "chargePointModel": "ErrorTestModel",
            "chargePointVendor": "JET_EV1",
            "firmwareVersion": "1.0.0-test"
        }
        return self._send_message("BootNotification", payload)

    def send_heartbeat(self) -> dict:
        """Send Heartbeat"""
        return self._send_message("Heartbeat", {})

    def send_status_notification(
        self,
        status: str,
        error_code: str = "NoError",
        vendor_error_code: Optional[str] = None,
        vendor_id: Optional[str] = None,
        info: Optional[str] = None,
        connector_id: int = 1
    ) -> dict:
        """
        Send StatusNotification with optional vendor error fields

        OCPP 1.6 Error Codes:
        - NoError, ConnectorLockFailure, EVCommunicationError, GroundFailure
        - HighTemperature, InternalError, LocalListConflict, OtherError
        - OverCurrentFailure, OverVoltage, PowerMeterFailure, PowerSwitchFailure
        - ReaderFailure, ResetFailure, UnderVoltage, WeakSignal
        """
        payload = {
            "connectorId": connector_id,
            "status": status,
            "errorCode": error_code,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        }

        # Add optional vendor error fields
        if vendor_error_code:
            payload["vendorErrorCode"] = vendor_error_code
        if vendor_id:
            payload["vendorId"] = vendor_id
        if info:
            payload["info"] = info

        return self._send_message("StatusNotification", payload)

    def run_error_test_sequence(self):
        """Run a complete error test sequence"""

        print("\n" + "="*60)
        print("VENDOR ERROR CODE TEST SEQUENCE")
        print("="*60)

        # 1. Boot and become available
        print("\n[STEP 1] Boot Notification")
        self.send_boot_notification()
        time.sleep(1)

        print("\n[STEP 2] Initial Available Status (NoError)")
        self.send_status_notification(
            status="Available",
            error_code="NoError"
        )
        time.sleep(2)

        # 2. Simulate standard OCPP error
        print("\n[STEP 3] Simulate Standard OCPP Error (GroundFailure)")
        self.send_status_notification(
            status="Faulted",
            error_code="GroundFailure",
            info="Ground fault detected on connector 1"
        )
        time.sleep(3)

        # 3. Resolve the error
        print("\n[STEP 4] Resolve GroundFailure (send NoError)")
        self.send_status_notification(
            status="Available",
            error_code="NoError"
        )
        time.sleep(2)

        # 4. Simulate vendor-specific error (OtherError with vendorErrorCode)
        print("\n[STEP 5] Simulate Vendor Error (OtherError + vendorErrorCode)")
        self.send_status_notification(
            status="Faulted",
            error_code="OtherError",
            vendor_error_code="GF001",
            vendor_id="JET_EV1",
            info="Vendor-specific ground fault code GF001"
        )
        time.sleep(3)

        # 5. Send another vendor error without resolving first
        print("\n[STEP 6] Another Vendor Error (HighTemperature + vendorErrorCode)")
        self.send_status_notification(
            status="Faulted",
            error_code="HighTemperature",
            vendor_error_code="TEMP_CRIT_01",
            vendor_id="JET_EV1",
            info="Temperature exceeded 85C on power module"
        )
        time.sleep(3)

        # 6. Resolve all errors
        print("\n[STEP 7] Resolve All Errors (send NoError)")
        self.send_status_notification(
            status="Available",
            error_code="NoError"
        )
        time.sleep(2)

        # 7. Simulate WeakSignal with vendor code
        print("\n[STEP 8] Simulate WeakSignal with Vendor Details")
        self.send_status_notification(
            status="Available",  # Can still be available with weak signal
            error_code="WeakSignal",
            vendor_error_code="GSM_LOW_RSSI",
            vendor_id="JET_EV1",
            info="GSM signal strength below threshold (RSSI=3)"
        )
        time.sleep(3)

        # 8. Signal recovered
        print("\n[STEP 9] Signal Recovered")
        self.send_status_notification(
            status="Available",
            error_code="NoError"
        )
        time.sleep(1)

        # Final heartbeat
        print("\n[STEP 10] Final Heartbeat")
        self.send_heartbeat()

        print("\n" + "="*60)
        print("TEST SEQUENCE COMPLETE")
        print("="*60)
        print("\nCheck the frontend at /admin/chargers to see:")
        print("  - Error column in charger list")
        print("  - Error details in charger detail page")
        print("  - Error history at GET /api/admin/chargers/{id}/errors")


def main():
    parser = argparse.ArgumentParser(description="OCPP Vendor Error Code Simulator")
    parser.add_argument(
        "--charger-id",
        required=True,
        help="Charge point ID (must exist in database)"
    )
    parser.add_argument(
        "--server",
        default="ws://localhost:8000",
        help="OCPP server URL (default: ws://localhost:8000)"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive mode to send custom errors"
    )

    args = parser.parse_args()

    simulator = VendorErrorSimulator(
        charge_point_id=args.charger_id,
        server_url=args.server
    )

    try:
        simulator.connect()

        if args.interactive:
            # Interactive mode
            print("\nInteractive Mode - Commands:")
            print("  boot     - Send boot notification")
            print("  hb       - Send heartbeat")
            print("  ok       - Send Available + NoError")
            print("  fault    - Send Faulted + OtherError with vendor code")
            print("  ground   - Send Faulted + GroundFailure")
            print("  temp     - Send Faulted + HighTemperature")
            print("  weak     - Send Available + WeakSignal")
            print("  custom   - Send custom error")
            print("  quit     - Exit")

            while True:
                try:
                    cmd = input("\n> ").strip().lower()

                    if cmd == "quit":
                        break
                    elif cmd == "boot":
                        simulator.send_boot_notification()
                    elif cmd == "hb":
                        simulator.send_heartbeat()
                    elif cmd == "ok":
                        simulator.send_status_notification("Available", "NoError")
                    elif cmd == "fault":
                        vendor_code = input("  Vendor error code: ").strip()
                        info = input("  Info message: ").strip()
                        simulator.send_status_notification(
                            "Faulted", "OtherError",
                            vendor_error_code=vendor_code or "VE001",
                            vendor_id="JET_EV1",
                            info=info or None
                        )
                    elif cmd == "ground":
                        simulator.send_status_notification(
                            "Faulted", "GroundFailure",
                            info="Ground fault detected"
                        )
                    elif cmd == "temp":
                        simulator.send_status_notification(
                            "Faulted", "HighTemperature",
                            vendor_error_code="TEMP_HIGH",
                            vendor_id="JET_EV1",
                            info="Temperature exceeded safe limit"
                        )
                    elif cmd == "weak":
                        simulator.send_status_notification(
                            "Available", "WeakSignal",
                            vendor_error_code="GSM_LOW",
                            vendor_id="JET_EV1",
                            info="Weak cellular signal"
                        )
                    elif cmd == "custom":
                        status = input("  Status (Available/Faulted/etc): ").strip()
                        error_code = input("  Error code: ").strip()
                        vendor_code = input("  Vendor error code (optional): ").strip()
                        info = input("  Info (optional): ").strip()
                        simulator.send_status_notification(
                            status or "Faulted",
                            error_code or "OtherError",
                            vendor_error_code=vendor_code or None,
                            vendor_id="JET_EV1" if vendor_code else None,
                            info=info or None
                        )
                    else:
                        print("Unknown command")

                except KeyboardInterrupt:
                    break
        else:
            # Run automated test sequence
            simulator.run_error_test_sequence()

    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
    finally:
        simulator.disconnect()


if __name__ == "__main__":
    main()
