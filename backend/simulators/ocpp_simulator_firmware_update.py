#!/usr/bin/env python3
"""
OCPP 1.6 Firmware Update Simulator

This simulator demonstrates the complete OTA (Over-The-Air) firmware update flow:
1. Connects to OCPP server
2. Sends boot notification
3. Waits for UpdateFirmware command from server
4. Simulates firmware download progress (with optional failure simulation)
5. Sends FirmwareStatusNotification messages at each stage
6. Simulates firmware installation
7. Reboots with new firmware version

Usage:
    # Normal firmware update simulation
    python ocpp_simulator_firmware_update.py --charger-id test-fw-001 --current-version 1.0.0

    # Simulate download failure
    python ocpp_simulator_firmware_update.py --charger-id test-fw-002 --current-version 1.0.0 --fail-download

    # Simulate installation failure
    python ocpp_simulator_firmware_update.py --charger-id test-fw-003 --current-version 1.0.0 --fail-install

    # Fast mode for quick testing
    python ocpp_simulator_firmware_update.py --charger-id test-fw-004 --current-version 1.0.0 --fast-mode
"""

import asyncio
import time
import json
import websocket
import argparse
import signal
import sys
from datetime import datetime
from typing import Optional
import random


class FirmwareUpdateSimulator:
    """OCPP 1.6 Firmware Update Simulator"""

    def __init__(self, charge_point_id: str, current_version: str, server_url: str = "ws://localhost:8000"):
        self.charge_point_id = charge_point_id
        self.current_version = current_version
        self.new_version = None
        self.server_url = server_url
        self.ws = None
        self.message_id_counter = 1
        self.is_connected = False
        self.running = False

        # Firmware update state
        self.update_in_progress = False
        self.download_url = None
        self.retrieve_date = None

        # Simulation settings
        self.download_duration = 20  # seconds to simulate download
        self.install_duration = 15   # seconds to simulate installation
        self.fail_download = False
        self.fail_install = False
        self.fast_mode = False
        self.debug_mode = False

        # Background tasks
        self.heartbeat_task = None
        self.heartbeat_interval = 10

        # Statistics
        self.statistics = {
            "messages_sent": 0,
            "messages_received": 0,
            "firmware_updates": 0,
            "start_time": None
        }

    def _get_next_message_id(self) -> str:
        """Generate next unique message ID"""
        msg_id = str(self.message_id_counter)
        self.message_id_counter += 1
        return msg_id

    def _send_message(self, action: str, payload: dict) -> dict:
        """Send OCPP message and wait for response"""
        message_id = self._get_next_message_id()
        message = [2, message_id, action, payload]

        if self.debug_mode:
            print(f"📤 [{self.charge_point_id}] Sending {action}: {json.dumps(payload, indent=2)}")
        else:
            print(f"📤 [{self.charge_point_id}] Sending {action}")

        self.ws.send(json.dumps(message))
        self.statistics["messages_sent"] += 1

        # Set timeout for response
        self.ws.settimeout(10.0)
        try:
            response_raw = self.ws.recv()
            response = json.loads(response_raw)
            self.statistics["messages_received"] += 1

            if response[0] == 3:  # CALLRESULT
                if self.debug_mode:
                    print(f"📥 [{self.charge_point_id}] Received response: {json.dumps(response[2], indent=2)}")
                else:
                    print(f"📥 [{self.charge_point_id}] Response: {action} OK")
                return response[2]
            elif response[0] == 4:  # CALLERROR
                print(f"❌ [{self.charge_point_id}] OCPP Error: {response[2]} - {response[3]}")
                raise Exception(f"OCPP Error: {response[2]} - {response[3]}")
        except websocket.WebSocketTimeoutException:
            print(f"❌ [{self.charge_point_id}] {action} error: timed out")
            raise Exception(f"{action} timed out")

    def _handle_incoming_message(self, message: str) -> Optional[dict]:
        """Handle incoming CALL message from server"""
        try:
            parsed = json.loads(message)
            if parsed[0] == 2:  # CALL
                message_id = parsed[1]
                action = parsed[2]
                payload = parsed[3]
                print(f"📥 [{self.charge_point_id}] Received {action}: {payload}")
                return {"message_id": message_id, "action": action, "payload": payload}
        except:
            pass
        return None

    def _send_call_result(self, message_id: str, payload: dict):
        """Send CALLRESULT response"""
        response = [3, message_id, payload]
        if self.debug_mode:
            print(f"📤 [{self.charge_point_id}] Sending response: {payload}")
        self.ws.send(json.dumps(response))

    def connect(self):
        """Connect to OCPP server"""
        print(f"🔌 [{self.charge_point_id}] Connecting to {self.server_url}/ocpp/{self.charge_point_id}")
        self.ws = websocket.create_connection(f"{self.server_url}/ocpp/{self.charge_point_id}")
        self.is_connected = True
        self.running = True
        print(f"✅ [{self.charge_point_id}] Connected to server")

    def disconnect(self):
        """Disconnect from server"""
        self.running = False
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.ws:
            self.ws.close()
            self.is_connected = False
            print(f"🔌 [{self.charge_point_id}] Disconnected from server")

    def send_boot_notification(self, firmware_version: str = None) -> dict:
        """Send BootNotification"""
        version = firmware_version or self.current_version
        payload = {
            "chargePointModel": "FirmwareTestModel",
            "chargePointVendor": "FirmwareTestVendor",
            "firmwareVersion": version
        }

        response = self._send_message("BootNotification", payload)
        print(f"🚀 [{self.charge_point_id}] Boot notification complete with firmware v{version}")
        return response

    def send_heartbeat(self) -> dict:
        """Send Heartbeat message"""
        response = self._send_message("Heartbeat", {})
        if self.debug_mode:
            print(f"💓 [{self.charge_point_id}] Heartbeat sent")
        return response

    def send_status_notification(self, status: str, connector_id: int = 1) -> dict:
        """Send StatusNotification message"""
        payload = {
            "connectorId": connector_id,
            "status": status,
            "errorCode": "NoError",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        }

        response = self._send_message("StatusNotification", payload)
        print(f"📊 [{self.charge_point_id}] Status: {status}")
        return response

    def send_firmware_status_notification(self, status: str) -> dict:
        """Send FirmwareStatusNotification message"""
        payload = {
            "status": status
        }

        response = self._send_message("FirmwareStatusNotification", payload)

        # Map status to emojis for better visibility
        status_emoji = {
            "Idle": "⏸️",
            "Downloading": "📥",
            "Downloaded": "✅",
            "Installing": "🔧",
            "Installed": "🎉",
            "DownloadFailed": "❌",
            "InstallationFailed": "⚠️"
        }

        emoji = status_emoji.get(status, "📦")
        print(f"{emoji} [{self.charge_point_id}] Firmware status: {status}")
        return response

    async def handle_update_firmware(self, message_id: str, payload: dict) -> bool:
        """Handle UpdateFirmware command from server"""
        self.download_url = payload.get("location")
        self.retrieve_date = payload.get("retrieve_date")
        retries = payload.get("retries", 3)
        retry_interval = payload.get("retry_interval", 300)

        print(f"\n{'='*80}")
        print(f"📦 [{self.charge_point_id}] UPDATE FIRMWARE COMMAND RECEIVED")
        print(f"   📍 Download URL: {self.download_url}")
        print(f"   📅 Retrieve Date: {self.retrieve_date}")
        print(f"   🔁 Retries: {retries}")
        print(f"   ⏱️  Retry Interval: {retry_interval}s")
        print(f"{'='*80}\n")

        # Send acceptance
        self._send_call_result(message_id, {})
        print(f"✅ [{self.charge_point_id}] UpdateFirmware command ACCEPTED")

        # Start firmware update process in background
        asyncio.create_task(self.firmware_update_process())

        return True

    async def firmware_update_process(self):
        """Simulate the complete firmware update process"""
        try:
            self.update_in_progress = True
            self.statistics["firmware_updates"] += 1

            # Apply fast mode timing if enabled
            if self.fast_mode:
                download_time = 3
                install_time = 2
            else:
                download_time = self.download_duration
                install_time = self.install_duration

            print(f"\n🔄 [{self.charge_point_id}] Starting firmware update process...")
            print(f"   Current version: {self.current_version}")
            print(f"   Download will take: {download_time}s")
            print(f"   Installation will take: {install_time}s\n")

            # Phase 1: Idle → Downloading
            await asyncio.sleep(2)
            self.send_firmware_status_notification("Downloading")

            # Phase 2: Simulate download with progress
            print(f"📥 [{self.charge_point_id}] Downloading firmware...")
            for i in range(5):
                if not self.running:
                    return
                await asyncio.sleep(download_time / 5)
                progress = (i + 1) * 20
                print(f"   📥 Download progress: {progress}%")

            # Check if download should fail
            if self.fail_download:
                print(f"\n❌ [{self.charge_point_id}] SIMULATING DOWNLOAD FAILURE")
                self.send_firmware_status_notification("DownloadFailed")
                self.update_in_progress = False
                print(f"💡 Update process ended. Charger remains on version {self.current_version}\n")
                return

            # Phase 3: Downloaded successfully
            self.send_firmware_status_notification("Downloaded")
            await asyncio.sleep(2)

            # Phase 4: Installing
            self.send_firmware_status_notification("Installing")
            print(f"🔧 [{self.charge_point_id}] Installing firmware...")
            for i in range(5):
                if not self.running:
                    return
                await asyncio.sleep(install_time / 5)
                progress = (i + 1) * 20
                print(f"   🔧 Installation progress: {progress}%")

            # Check if installation should fail
            if self.fail_install:
                print(f"\n⚠️ [{self.charge_point_id}] SIMULATING INSTALLATION FAILURE")
                self.send_firmware_status_notification("InstallationFailed")
                self.update_in_progress = False
                print(f"💡 Update process ended. Charger remains on version {self.current_version}\n")
                return

            # Phase 5: Installed successfully
            self.send_firmware_status_notification("Installed")

            # Extract version from download URL (e.g., /firmware/2.0.0_firmware.bin)
            # This is a simplified version extraction
            if self.download_url and '/' in self.download_url:
                filename = self.download_url.split('/')[-1]
                # Try to extract version (format: version_filename)
                if '_' in filename:
                    self.new_version = filename.split('_')[0]
                else:
                    # Fallback: increment version
                    major, minor, patch = self.current_version.split('.')
                    self.new_version = f"{major}.{int(minor)+1}.{patch}"
            else:
                # Default: increment version
                major, minor, patch = self.current_version.split('.')
                self.new_version = f"{major}.{int(minor)+1}.{patch}"

            print(f"\n🎉 [{self.charge_point_id}] FIRMWARE UPDATE SUCCESSFUL!")
            print(f"   Old version: {self.current_version}")
            print(f"   New version: {self.new_version}")
            print(f"\n🔄 [{self.charge_point_id}] Rebooting charger in 3 seconds...")
            await asyncio.sleep(3)

            # Phase 6: Reboot with new version
            print(f"🔌 [{self.charge_point_id}] Simulating reboot...")
            await asyncio.sleep(2)

            # Update current version and send new boot notification
            self.current_version = self.new_version
            self.send_boot_notification(self.new_version)
            self.send_status_notification("Available")

            print(f"\n✨ [{self.charge_point_id}] Charger successfully updated to v{self.new_version}!")
            print(f"💡 Ready for next update cycle\n")

            self.update_in_progress = False

        except Exception as e:
            print(f"❌ [{self.charge_point_id}] Error during firmware update: {e}")
            self.update_in_progress = False

    def process_incoming_messages(self, timeout: float = 0.1):
        """Process any incoming messages from server"""
        try:
            self.ws.settimeout(timeout)
            message_raw = self.ws.recv()
            message = self._handle_incoming_message(message_raw)

            if message:
                action = message["action"]
                if action == "UpdateFirmware":
                    asyncio.create_task(self.handle_update_firmware(message["message_id"], message["payload"]))
                elif action == "ChangeAvailability":
                    # Accept but ignore for now
                    self._send_call_result(message["message_id"], {"status": "Accepted"})

        except websocket.WebSocketTimeoutException:
            pass
        except Exception as e:
            if self.running:
                if self.debug_mode:
                    print(f"❌ [{self.charge_point_id}] Error processing message: {e}")

        return False

    async def heartbeat_loop(self):
        """Send heartbeats periodically"""
        while self.running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if self.running:
                    self.send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ [{self.charge_point_id}] Heartbeat error: {e}")
                await asyncio.sleep(5)

    def start_heartbeat_task(self):
        """Start heartbeat background task"""
        if not self.heartbeat_task:
            self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())

    def print_statistics(self):
        """Print current statistics"""
        if not self.statistics["start_time"]:
            return

        uptime = time.time() - self.statistics["start_time"]
        print(f"\n📊 [{self.charge_point_id}] STATISTICS")
        print(f"   ⏱️  Uptime: {uptime:.1f}s")
        print(f"   📤 Messages sent: {self.statistics['messages_sent']}")
        print(f"   📥 Messages received: {self.statistics['messages_received']}")
        print(f"   📦 Firmware updates completed: {self.statistics['firmware_updates']}")
        print(f"   🔌 Current firmware version: {self.current_version}")
        print(f"   📡 Connected: {self.is_connected}")
        if self.update_in_progress:
            print(f"   🔄 Update in progress: YES")
        print("")

    async def run_simulation(self):
        """Run the complete firmware update simulation"""
        try:
            print(f"\n{'='*80}")
            print(f"🚀 STARTING FIRMWARE UPDATE SIMULATOR")
            print(f"📍 Charger ID: {self.charge_point_id}")
            print(f"📦 Current Firmware: v{self.current_version}")
            print(f"🌐 Server: {self.server_url}")
            if self.fast_mode:
                print(f"⚡ Fast mode: ON")
            if self.fail_download:
                print(f"⚠️  Will simulate DOWNLOAD FAILURE")
            if self.fail_install:
                print(f"⚠️  Will simulate INSTALLATION FAILURE")
            if self.debug_mode:
                print(f"🐛 Debug mode: ON")
            print(f"{'='*80}\n")

            # Initialize statistics
            self.statistics["start_time"] = time.time()

            # Step 1: Connect
            self.connect()

            # Step 2: Send boot notification
            boot_response = self.send_boot_notification()
            assert boot_response["status"] == "Accepted"

            # Step 3: Start heartbeat
            self.start_heartbeat_task()

            # Step 4: Send initial status
            self.send_status_notification("Available")

            print(f"\n🔄 [{self.charge_point_id}] Ready for firmware update...")
            print(f"💡 To test the simulator:")
            print(f"   1. Go to Admin Firmware page")
            print(f"   2. Upload a firmware file (any .bin/.hex/.fw file)")
            print(f"   3. Go to Chargers page and trigger update for this charger")
            print(f"   4. Watch the simulator simulate the entire OTA update process")
            print(f"   5. Press Ctrl+C to stop the simulator")
            print(f"\n⏰ Heartbeats every {self.heartbeat_interval}s")
            print(f"{'='*80}\n")

            # Main loop
            while self.running:
                self.process_incoming_messages(timeout=0.1)
                await asyncio.sleep(0.1)

        except KeyboardInterrupt:
            print(f"\n🛑 [{self.charge_point_id}] Simulator stopped by user")
            self.print_statistics()
        except Exception as e:
            print(f"❌ [{self.charge_point_id}] Simulation error: {e}")
            import traceback
            traceback.print_exc()
            self.print_statistics()
        finally:
            self.disconnect()


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Stopping simulator...")
    sys.exit(0)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="OCPP 1.6 Firmware Update Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic firmware update simulation
  python ocpp_simulator_firmware_update.py --charger-id test-fw-001 --current-version 1.0.0

  # Fast mode for quick testing (3s download, 2s install)
  python ocpp_simulator_firmware_update.py --charger-id test-fw-002 --current-version 1.0.0 --fast-mode

  # Simulate download failure
  python ocpp_simulator_firmware_update.py --charger-id test-fw-003 --current-version 1.0.0 --fail-download

  # Simulate installation failure
  python ocpp_simulator_firmware_update.py --charger-id test-fw-004 --current-version 1.0.0 --fail-install

  # Custom server
  python ocpp_simulator_firmware_update.py --charger-id test-fw-005 --current-version 1.0.0 --server ws://production-server.com:8000
        """
    )

    # Required arguments
    parser.add_argument("--charger-id", required=True,
                       help="Charge point ID to simulate")
    parser.add_argument("--current-version", required=True,
                       help="Current firmware version (e.g., 1.0.0)")

    # Connection settings
    parser.add_argument("--server", default="ws://localhost:8000",
                       help="OCPP server URL (default: ws://localhost:8000)")

    # Timing settings
    parser.add_argument("--heartbeat-interval", type=int, default=10,
                       help="Heartbeat interval in seconds (default: 10)")
    parser.add_argument("--download-duration", type=int, default=20,
                       help="Simulated download duration in seconds (default: 20)")
    parser.add_argument("--install-duration", type=int, default=15,
                       help="Simulated installation duration in seconds (default: 15)")

    # Failure simulation
    parser.add_argument("--fail-download", action="store_true",
                       help="Simulate download failure")
    parser.add_argument("--fail-install", action="store_true",
                       help="Simulate installation failure")

    # Development features
    parser.add_argument("--fast-mode", action="store_true",
                       help="Fast mode: 3s download, 2s install (for quick testing)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug mode with detailed message logging")

    args = parser.parse_args()

    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)

    # Create and configure simulator
    simulator = FirmwareUpdateSimulator(args.charger_id, args.current_version, args.server)
    simulator.heartbeat_interval = args.heartbeat_interval
    simulator.download_duration = args.download_duration
    simulator.install_duration = args.install_duration
    simulator.fail_download = args.fail_download
    simulator.fail_install = args.fail_install
    simulator.fast_mode = args.fast_mode
    simulator.debug_mode = args.debug

    await simulator.run_simulation()


if __name__ == "__main__":
    asyncio.run(main())
