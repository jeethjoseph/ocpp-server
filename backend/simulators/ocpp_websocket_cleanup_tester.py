#!/usr/bin/env python3
"""
OCPP WebSocket Cleanup and Ghost Session Tester

This simulator specifically tests the WebSocket cleanup fixes:
1. Normal disconnection scenarios
2. Ghost session detection
3. Heartbeat timeout testing
4. Rapid reconnect cycles
5. Network interruption simulation
6. Tombstone functionality

Usage:
    python ocpp_websocket_cleanup_tester.py --test normal --charger-id TEST_NORMAL_01
    python ocpp_websocket_cleanup_tester.py --test ghost --charger-id TEST_GHOST_01
    python ocpp_websocket_cleanup_tester.py --test timeout --charger-id TEST_TIMEOUT_01
    python ocpp_websocket_cleanup_tester.py --test rapid --charger-id TEST_RAPID_01
    python ocpp_websocket_cleanup_tester.py --test all --charger-id TEST_ALL_01
"""

import asyncio
import time
import json
import websocket
import argparse
import signal
import sys
import random
import threading
from datetime import datetime
from typing import Optional


class WebSocketCleanupTester:
    """WebSocket cleanup and ghost session testing simulator"""
    
    def __init__(self, charge_point_id: str, server_url: str = "ws://localhost:8000"):
        self.charge_point_id = charge_point_id
        self.server_url = server_url
        self.ws = None
        self.message_id_counter = 1
        self.server_time = None
        self.is_connected = False
        self.running = False
        
        # Test-specific settings
        self.heartbeat_interval = 10
        self.test_mode = "normal"
        
        # Background tasks
        self.heartbeat_task = None
        
        # Statistics
        self.statistics = {
            "messages_sent": 0,
            "messages_received": 0,
            "connections": 0,
            "disconnections": 0,
            "ghost_sessions": 0,
            "start_time": None
        }
        
    def _get_next_message_id(self) -> str:
        """Generate next unique message ID"""
        msg_id = f"{self.charge_point_id}_{self.message_id_counter}_{int(time.time())}"
        self.message_id_counter += 1
        return msg_id
    
    def _send_message(self, action: str, payload: dict, expect_response: bool = True) -> Optional[dict]:
        """Send OCPP message and optionally wait for response"""
        if not self.ws:
            print(f"❌ [{self.charge_point_id}] Cannot send {action} - not connected")
            return None
            
        message_id = self._get_next_message_id()
        message = [2, message_id, action, payload]
        
        print(f"📤 [{self.charge_point_id}] Sending {action}")
        
        try:
            self.ws.send(json.dumps(message))
            self.statistics["messages_sent"] += 1
            
            if not expect_response:
                return {"status": "sent"}
            
            # Set timeout for response
            self.ws.settimeout(10.0)
            response_raw = self.ws.recv()
            response = json.loads(response_raw)
            self.statistics["messages_received"] += 1
            
            if response[0] == 3:  # CALLRESULT
                print(f"📥 [{self.charge_point_id}] Response: {action} OK")
                return response[2]  # Return payload
            elif response[0] == 4:  # CALLERROR
                print(f"❌ [{self.charge_point_id}] OCPP Error: {response[2]} - {response[3]}")
                return {"error": response[2], "description": response[3]}
            else:
                print(f"⚠️ [{self.charge_point_id}] Unknown response type: {response[0]}")
                return {"unknown_response": response}
                
        except websocket.WebSocketTimeoutException:
            print(f"⏰ [{self.charge_point_id}] {action} timed out")
            return {"error": "timeout"}
        except Exception as e:
            print(f"❌ [{self.charge_point_id}] Error sending {action}: {e}")
            return {"error": str(e)}
    
    def _handle_incoming_message(self, message: str) -> Optional[dict]:
        """Handle incoming CALL message from server"""
        try:
            parsed = json.loads(message)
            if parsed[0] == 2:  # CALL
                message_id = parsed[1]
                action = parsed[2]
                payload = parsed[3]
                print(f"📥 [{self.charge_point_id}] Received {action}")
                return {"message_id": message_id, "action": action, "payload": payload}
        except Exception as e:
            print(f"⚠️ [{self.charge_point_id}] Error parsing message: {e}")
        return None
    
    def _send_call_result(self, message_id: str, payload: dict):
        """Send CALLRESULT response"""
        response = [3, message_id, payload]
        try:
            self.ws.send(json.dumps(response))
            print(f"📤 [{self.charge_point_id}] Sent response")
        except Exception as e:
            print(f"❌ [{self.charge_point_id}] Error sending response: {e}")
    
    def connect(self) -> bool:
        """Connect to OCPP server"""
        try:
            print(f"🔌 [{self.charge_point_id}] Connecting to {self.server_url}/ocpp/{self.charge_point_id}")
            self.ws = websocket.create_connection(f"{self.server_url}/ocpp/{self.charge_point_id}")
            self.is_connected = True
            self.running = True
            self.statistics["connections"] += 1
            print(f"✅ [{self.charge_point_id}] Connected successfully")
            return True
        except Exception as e:
            print(f"❌ [{self.charge_point_id}] Connection failed: {e}")
            return False
    
    def disconnect(self, clean: bool = True):
        """Disconnect from server"""
        self.running = False
        self.statistics["disconnections"] += 1
        
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            
        if self.ws and clean:
            try:
                self.ws.close()
                print(f"🔌 [{self.charge_point_id}] Clean disconnect")
            except Exception as e:
                print(f"⚠️ [{self.charge_point_id}] Error during clean disconnect: {e}")
        else:
            print(f"🔌 [{self.charge_point_id}] Abrupt disconnect (no close frame)")
            
        self.is_connected = False
    
    def send_boot_notification(self) -> Optional[dict]:
        """Send BootNotification"""
        # Ensure serial number fits OCPP 1.6 limit of 25 characters
        serial_suffix = self.charge_point_id[-15:] if len(self.charge_point_id) > 15 else self.charge_point_id
        payload = {
            "chargePointModel": f"Cleanup-{self.test_mode}",  # Shorter model name
            "chargePointVendor": "TestVendor",
            "chargePointSerialNumber": f"SN_{serial_suffix}",  # Max 25 chars
            "firmwareVersion": "1.0.0"  # Shorter version
        }
        
        response = self._send_message("BootNotification", payload)
        
        if response and "currentTime" in response:
            self.server_time = response["currentTime"]
            print(f"🕐 [{self.charge_point_id}] Server time: {self.server_time}")
        
        return response
    
    def send_heartbeat(self, expect_response: bool = True) -> Optional[dict]:
        """Send Heartbeat message"""
        return self._send_message("Heartbeat", {}, expect_response)
    
    def send_status_notification(self, status: str = "Available") -> Optional[dict]:
        """Send StatusNotification message"""
        payload = {
            "connectorId": 1,
            "status": status,
            "errorCode": "NoError",
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        }
        
        return self._send_message("StatusNotification", payload)
    
    def process_incoming_messages(self, timeout: float = 0.1):
        """Process any incoming messages from server"""
        try:
            self.ws.settimeout(timeout)
            message_raw = self.ws.recv()
            message = self._handle_incoming_message(message_raw)
            
            if message:
                action = message["action"]
                if action in ["Reset", "ChangeAvailability", "RemoteStartTransaction", "RemoteStopTransaction"]:
                    # Send generic acceptance response
                    self._send_call_result(message["message_id"], {"status": "Accepted"})
                    
        except websocket.WebSocketTimeoutException:
            pass
        except Exception as e:
            if self.running:
                print(f"❌ [{self.charge_point_id}] Error processing message: {e}")
    
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
                print(f"💔 [{self.charge_point_id}] Heartbeat error: {e}")
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
        print(f"\n📊 [{self.charge_point_id}] TEST STATISTICS")
        print(f"   ⏱️  Test Mode: {self.test_mode}")
        print(f"   ⏱️  Uptime: {uptime:.1f}s")
        print(f"   📤 Messages sent: {self.statistics['messages_sent']}")
        print(f"   📥 Messages received: {self.statistics['messages_received']}")
        print(f"   🔌 Connections: {self.statistics['connections']}")
        print(f"   ❌ Disconnections: {self.statistics['disconnections']}")
        print(f"   👻 Ghost sessions: {self.statistics['ghost_sessions']}")
        print(f"   🌐 Currently connected: {self.is_connected}")
        print("")
    
    async def test_normal_flow(self, duration: int = 120):
        """Test normal connection, operation, and clean disconnection"""
        self.test_mode = "normal"
        print(f"\n🧪 [{self.charge_point_id}] NORMAL FLOW TEST - {duration}s")
        print("   Testing proper connection, heartbeats, and clean disconnect")
        
        if not self.connect():
            return False
        
        # Send boot notification
        boot_response = self.send_boot_notification()
        if not boot_response or boot_response.get("status") != "Accepted":
            print(f"❌ [{self.charge_point_id}] Boot notification failed")
            return False
        
        # Send initial status
        self.send_status_notification("Available")
        
        # Start heartbeat task
        self.start_heartbeat_task()
        
        # Run for specified duration with message processing
        start_time = time.time()
        while time.time() - start_time < duration and self.running:
            self.process_incoming_messages(timeout=0.1)
            await asyncio.sleep(0.1)
        
        # Clean disconnect
        self.disconnect(clean=True)
        
        print(f"✅ [{self.charge_point_id}] NORMAL FLOW TEST completed")
        return True
    
    async def test_ghost_session(self):
        """Test ghost session detection"""
        self.test_mode = "ghost"
        print(f"\n👻 [{self.charge_point_id}] GHOST SESSION TEST")
        print("   Testing server detection of ghost sessions after cleanup")
        
        if not self.connect():
            return False
        
        # Normal startup
        self.send_boot_notification()
        self.send_status_notification("Available")
        
        # Send a few normal heartbeats
        for i in range(3):
            print(f"👻 [{self.charge_point_id}] Normal heartbeat #{i+1}")
            self.send_heartbeat()
            await asyncio.sleep(5)
        
        # Simulate becoming a ghost by stopping heartbeats but keeping connection
        print(f"👻 [{self.charge_point_id}] Simulating ghost session - stopped heartbeats")
        await asyncio.sleep(60)  # Wait for server to think we're disconnected
        
        # Try to send messages as a ghost - server should detect this
        print(f"👻 [{self.charge_point_id}] Sending messages as ghost session...")
        self.statistics["ghost_sessions"] += 1
        
        for i in range(5):
            print(f"👻 [{self.charge_point_id}] Ghost message #{i+1}")
            result = self.send_heartbeat(expect_response=False)
            await asyncio.sleep(2)
            
            # Check if connection was closed by server
            try:
                self.ws.settimeout(0.1)
                self.ws.recv()  # This should fail if connection was closed
            except:
                print(f"👻 [{self.charge_point_id}] Connection closed by server (ghost detected)")
                break
        
        self.disconnect(clean=False)
        
        print(f"✅ [{self.charge_point_id}] GHOST SESSION TEST completed")
        return True
    
    async def test_heartbeat_timeout(self):
        """Test heartbeat timeout scenario"""
        self.test_mode = "timeout"
        print(f"\n💔 [{self.charge_point_id}] HEARTBEAT TIMEOUT TEST")
        print("   Testing server cleanup after heartbeat timeout")
        
        if not self.connect():
            return False
        
        # Normal startup
        self.send_boot_notification()
        self.send_status_notification("Available")
        
        # Send initial heartbeats
        for i in range(3):
            print(f"💔 [{self.charge_point_id}] Initial heartbeat #{i+1}")
            self.send_heartbeat()
            await asyncio.sleep(20)
        
        # Stop heartbeats and wait for timeout
        print(f"💔 [{self.charge_point_id}] Stopping heartbeats - waiting for server timeout")
        
        # Wait for heartbeat timeout (should be ~90 seconds)
        await asyncio.sleep(100)
        
        # Try to send a message - should fail if server cleaned us up
        print(f"💔 [{self.charge_point_id}] Testing connection after timeout")
        result = self.send_heartbeat()
        if result and "error" in result:
            print(f"💔 [{self.charge_point_id}] Connection properly cleaned up by server")
        
        self.disconnect(clean=False)
        
        print(f"✅ [{self.charge_point_id}] HEARTBEAT TIMEOUT TEST completed")
        return True
    
    async def test_rapid_reconnect(self, cycles: int = 5):
        """Test rapid disconnect/reconnect cycles"""
        self.test_mode = "rapid"
        print(f"\n🔄 [{self.charge_point_id}] RAPID RECONNECT TEST - {cycles} cycles")
        print("   Testing tombstone functionality and reconnection races")
        
        for cycle in range(cycles):
            print(f"🔄 [{self.charge_point_id}] Cycle {cycle + 1}/{cycles}")
            
            # Connect
            if not self.connect():
                continue
            
            # Quick startup
            self.send_boot_notification()
            self.send_heartbeat()
            
            # Random connection duration
            connection_time = random.uniform(2, 8)
            await asyncio.sleep(connection_time)
            
            # Disconnect (random clean/abrupt)
            clean = random.choice([True, False])
            disconnect_type = "clean" if clean else "abrupt"
            print(f"🔄 [{self.charge_point_id}] {disconnect_type} disconnect after {connection_time:.1f}s")
            self.disconnect(clean=clean)
            
            # Wait before reconnecting (test tombstone)
            wait_time = random.uniform(1, 6)
            print(f"🔄 [{self.charge_point_id}] Waiting {wait_time:.1f}s before reconnect")
            await asyncio.sleep(wait_time)
        
        print(f"✅ [{self.charge_point_id}] RAPID RECONNECT TEST completed")
        return True
    
    async def test_network_interruption(self):
        """Test network interruption simulation"""
        self.test_mode = "network"
        print(f"\n📡 [{self.charge_point_id}] NETWORK INTERRUPTION TEST")
        print("   Testing cleanup after abrupt network loss")
        
        if not self.connect():
            return False
        
        # Normal startup
        self.send_boot_notification()
        self.send_status_notification("Available")
        
        # Send heartbeats for a while
        for i in range(5):
            print(f"📡 [{self.charge_point_id}] Heartbeat #{i+1} before interruption")
            self.send_heartbeat()
            await asyncio.sleep(15)
        
        # Simulate network interruption by closing socket without proper close frame
        print(f"📡 [{self.charge_point_id}] Simulating network interruption...")
        if self.ws and hasattr(self.ws, 'sock') and self.ws.sock:
            try:
                self.ws.sock.close()  # Force close the underlying socket
                print(f"📡 [{self.charge_point_id}] Forced socket closure")
            except Exception as e:
                print(f"📡 [{self.charge_point_id}] Socket already closed or error: {e}")
        else:
            print(f"📡 [{self.charge_point_id}] WebSocket or socket not available for interruption")
        
        self.disconnect(clean=False)
        
        print(f"✅ [{self.charge_point_id}] NETWORK INTERRUPTION TEST completed")
        return True
    
    async def run_all_tests(self):
        """Run all test scenarios"""
        print(f"\n🎯 [{self.charge_point_id}] RUNNING ALL CLEANUP TESTS")
        
        test_scenarios = [
            ("Normal Flow", self.test_normal_flow, [60]),
            ("Ghost Session", self.test_ghost_session, []),
            ("Heartbeat Timeout", self.test_heartbeat_timeout, []),
            ("Rapid Reconnect", self.test_rapid_reconnect, [3]),
            ("Network Interruption", self.test_network_interruption, [])
        ]
        
        for test_name, test_func, args in test_scenarios:
            try:
                print(f"\n{'='*60}")
                print(f"🧪 Starting: {test_name}")
                print(f"{'='*60}")
                
                await test_func(*args)
                
                # Brief pause between tests
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"❌ Test {test_name} failed: {e}")
        
        print(f"\n🎯 [{self.charge_point_id}] ALL TESTS COMPLETED")
    
    async def run_test(self, test_type: str):
        """Run specific test type"""
        try:
            self.statistics["start_time"] = time.time()
            
            print(f"\n{'='*80}")
            print(f"🧪 WEBSOCKET CLEANUP TESTER")
            print(f"📍 Charger ID: {self.charge_point_id}")
            print(f"🌐 Server: {self.server_url}")
            print(f"🎯 Test Type: {test_type}")
            print(f"{'='*80}")
            
            if test_type == "normal":
                await self.test_normal_flow(120)
            elif test_type == "ghost":
                await self.test_ghost_session()
            elif test_type == "timeout":
                await self.test_heartbeat_timeout()
            elif test_type == "rapid":
                await self.test_rapid_reconnect(5)
            elif test_type == "network":
                await self.test_network_interruption()
            elif test_type == "all":
                await self.run_all_tests()
            else:
                print(f"❌ Unknown test type: {test_type}")
                return
                
        except KeyboardInterrupt:
            print(f"\n🛑 [{self.charge_point_id}] Test interrupted by user")
        except Exception as e:
            print(f"❌ [{self.charge_point_id}] Test error: {e}")
        finally:
            if self.running:
                self.disconnect(clean=False)
            self.print_statistics()


def signal_handler(_signum, _frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Stopping tester...")
    sys.exit(0)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="OCPP WebSocket Cleanup and Ghost Session Tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test Types:
  normal    - Normal connection, heartbeats, clean disconnect
  ghost     - Ghost session detection after server cleanup
  timeout   - Heartbeat timeout and server cleanup
  rapid     - Rapid disconnect/reconnect cycles (tombstone test)
  network   - Network interruption simulation
  all       - Run all test scenarios

Examples:
  python ocpp_websocket_cleanup_tester.py --test normal --charger-id TEST_NORMAL_01
  python ocpp_websocket_cleanup_tester.py --test ghost --charger-id TEST_GHOST_01
  python ocpp_websocket_cleanup_tester.py --test all --charger-id TEST_ALL_01
        """
    )
    
    # Required arguments
    parser.add_argument("--test", required=True, 
                       choices=["normal", "ghost", "timeout", "rapid", "network", "all"],
                       help="Test scenario to run")
    parser.add_argument("--charger-id", required=True, 
                       help="Charge point ID for testing")
    
    # Connection settings
    parser.add_argument("--server", default="ws://localhost:8000", 
                       help="OCPP server URL (default: ws://localhost:8000)")
    
    args = parser.parse_args()
    
    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    # Create and run tester
    tester = WebSocketCleanupTester(args.charger_id, args.server)
    await tester.run_test(args.test)


if __name__ == "__main__":
    asyncio.run(main())