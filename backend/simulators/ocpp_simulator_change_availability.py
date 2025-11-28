#!/usr/bin/env python3
"""
OCPP 1.6 Change Availability Simulator

This simulator tests the Change Availability functionality:
1. Connects to OCPP server
2. Sends boot notification
3. Sends heartbeats periodically
4. Waits for ChangeAvailability commands from server
5. Responds with Accepted status for successful testing

Usage:
    python ocpp_simulator_change_availability.py --charger-id f87a48bc-532e-4aed-862c-c6846dd278f9
    python ocpp_simulator_change_availability.py --charger-id f87a48bc-532e-4aed-862c-c6846dd278f9 --server ws://localhost:8000
"""

import asyncio
import time
import json
import websocket
import argparse
import signal
import sys
from typing import Optional


class OCPPChangeAvailabilitySimulator:
    """OCPP 1.6 Change Availability Simulator for testing availability changes"""
    
    def __init__(self, charge_point_id: str, server_url: str = "ws://localhost:8000"):
        self.charge_point_id = charge_point_id
        self.server_url = server_url
        self.ws = None
        self.message_id_counter = 1
        self.server_time = None
        self.current_status = "Unavailable"
        self.current_availability = "Operative"  # Track current availability
        self.is_connected = False
        self.running = False
        
        # Timing intervals (in seconds)
        self.heartbeat_interval = 10
        
        # Background tasks
        self.heartbeat_task = None
        
        # Statistics
        self.statistics = {
            "messages_sent": 0,
            "messages_received": 0,
            "availability_changes": 0,
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
        
        print(f"📤 [{self.charge_point_id}] Sending {action}: {json.dumps(payload, indent=2)}")
            
        self.ws.send(json.dumps(message))
        self.statistics["messages_sent"] += 1
        
        # Set timeout for response
        self.ws.settimeout(10.0)
        try:
            response_raw = self.ws.recv()
            response = json.loads(response_raw)
            self.statistics["messages_received"] += 1
            
            if response[0] == 3:  # CALLRESULT
                print(f"📥 [{self.charge_point_id}] Response: {action} OK - {json.dumps(response[2], indent=2)}")
                return response[2]  # Return payload
            elif response[0] == 4:  # CALLERROR
                print(f"❌ [{self.charge_point_id}] OCPP Error: {response[2]} - {response[3]}")
                raise Exception(f"OCPP Error: {response[2]} - {response[3]}")
            else:
                raise Exception(f"Unknown response type: {response[0]}")
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
                print(f"📥 [{self.charge_point_id}] Received {action}: {json.dumps(payload, indent=2)}")
                return {"message_id": message_id, "action": action, "payload": payload}
        except:
            pass
        return None
    
    def _send_call_result(self, message_id: str, payload: dict):
        """Send CALLRESULT response"""
        response = [3, message_id, payload]
        print(f"📤 [{self.charge_point_id}] Sending response: {json.dumps(payload, indent=2)}")
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
    
    def send_boot_notification(self) -> dict:
        """Send BootNotification"""
        payload = {
            "chargePointModel": "AvailSimulator",
            "chargePointVendor": "TestVendor",
            "firmwareVersion": "1.0.0"
        }

        response = self._send_message("BootNotification", payload)
        
        if "currentTime" in response:
            self.server_time = response["currentTime"]
            print(f"🕐 [{self.charge_point_id}] ⭐ CLOCK RESET TO SERVER TIME: {self.server_time} ⭐")
        
        print(f"🚀 [{self.charge_point_id}] Boot notification complete, status: {response.get('status', 'Unknown')}")
        return response
    
    def send_heartbeat(self) -> dict:
        """Send Heartbeat message"""
        response = self._send_message("Heartbeat", {})
        if "currentTime" in response:
            self.server_time = response["currentTime"]
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
        
        self.current_status = status
        response = self._send_message("StatusNotification", payload)
        print(f"📊 [{self.charge_point_id}] Status changed to: {status}")
        return response
    
    def handle_change_availability(self, message_id: str, payload: dict) -> bool:
        """Handle ChangeAvailability from server - Always responds with Accepted"""
        connector_id = payload.get("connectorId", 1)
        availability_type = payload.get("type", "Operative")
        
        print(f"🔄 [{self.charge_point_id}] ⭐ CHANGE AVAILABILITY REQUEST ⭐")
        print(f"   Connector ID: {connector_id}")
        print(f"   Type: {availability_type}")
        print(f"   Previous availability: {self.current_availability}")
        
        # Send success response - this simulator always accepts
        self._send_call_result(message_id, {"status": "Accepted"})
        print(f"✅ [{self.charge_point_id}] ⭐ CHANGE AVAILABILITY ACCEPTED ⭐")
        
        # Update internal state
        self.current_availability = availability_type
        self.statistics["availability_changes"] += 1
        
        # Update status based on availability
        if availability_type == "Inoperative":
            # Send unavailable status when made inoperative
            self.send_status_notification("Unavailable", connector_id)
            print(f"📊 [{self.charge_point_id}] Connector {connector_id} is now INOPERATIVE")
        else:
            # Send available status when made operative
            self.send_status_notification("Available", connector_id)
            print(f"📊 [{self.charge_point_id}] Connector {connector_id} is now OPERATIVE")
        
        print(f"🎯 [{self.charge_point_id}] Availability change completed successfully!")
        return True
    
    def process_incoming_messages(self, timeout: float = 0.1):
        """Process any incoming messages from server"""
        try:
            self.ws.settimeout(timeout)
            message_raw = self.ws.recv()
            message = self._handle_incoming_message(message_raw)
            
            if message:
                action = message["action"]
                if action == "ChangeAvailability":
                    return self.handle_change_availability(message["message_id"], message["payload"])
                    
        except websocket.WebSocketTimeoutException:
            pass
        except Exception as e:
            if self.running:
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
        print(f"   🔄 Availability changes: {self.statistics['availability_changes']}")
        print(f"   📊 Current status: {self.current_status}")
        print(f"   🔌 Current availability: {self.current_availability}")
        print(f"   🌐 Connected: {self.is_connected}")
        print("")
    
    async def run_simulation(self):
        """Run the change availability simulation"""
        try:
            print(f"\n{'='*80}")
            print(f"🚀 STARTING OCPP 1.6 CHANGE AVAILABILITY SIMULATOR")
            print(f"📍 Charger ID: {self.charge_point_id}")
            print(f"🌐 Server: {self.server_url}")
            print(f"🎯 Purpose: Test Change Availability functionality")
            print(f"{'='*80}\n")
            
            # Initialize statistics
            self.statistics["start_time"] = time.time()
            
            # Step 1: Connect to server
            self.connect()
            
            # Step 2: Send boot notification
            boot_response = self.send_boot_notification()
            assert boot_response["status"] == "Accepted"
            
            # Step 3: Start heartbeat loop
            self.start_heartbeat_task()
            
            # Step 4: Send initial status notification
            self.send_status_notification("Available")
            
            print(f"\n🔄 [{self.charge_point_id}] Ready for Change Availability commands...")
            print(f"💡 To test the simulator:")
            print(f"   1. Use the admin API: POST /api/admin/chargers/{{charger_id}}/change-availability")
            print(f"   2. Set type=Inoperative or type=Operative")
            print(f"   3. Set connector_id=0 (for entire charger) or 1 (for specific connector)")
            print(f"   4. Watch the simulator respond with Accepted and update status")
            print(f"   5. Press Ctrl+C to stop the simulator")
            print(f"\n⏰ Heartbeats every {self.heartbeat_interval}s")
            print(f"🎯 This simulator ALWAYS responds with 'Accepted' for successful testing")
            print(f"{'='*80}\n")
            
            # Main loop - process incoming messages
            last_stats_time = time.time()
            while self.running:
                self.process_incoming_messages(timeout=0.1)
                
                # Show periodic statistics
                if time.time() - last_stats_time > 60:  # Every minute
                    self.print_statistics()
                    last_stats_time = time.time()
                    
                await asyncio.sleep(0.1)
                
        except KeyboardInterrupt:
            print(f"\n🛑 [{self.charge_point_id}] Simulator stopped by user")
            self.print_statistics()
        except Exception as e:
            print(f"❌ [{self.charge_point_id}] Simulation error: {e}")
            self.print_statistics()
        finally:
            self.disconnect()


def signal_handler(_signum, _frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Stopping simulator...")
    sys.exit(0)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="OCPP 1.6 Change Availability Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic simulation
  python ocpp_simulator_change_availability.py --charger-id f87a48bc-532e-4aed-862c-c6846dd278f9
  
  # With custom server
  python ocpp_simulator_change_availability.py --charger-id test-availability --server ws://localhost:8000
  
  # Fast heartbeats for testing
  python ocpp_simulator_change_availability.py --charger-id test-fast --heartbeat-interval 10
        """
    )
    
    # Required arguments
    parser.add_argument("--charger-id", required=True, 
                       help="Charge point ID to simulate")
    
    # Connection settings
    parser.add_argument("--server", default="ws://localhost:8000", 
                       help="OCPP server URL (default: ws://localhost:8000)")
    
    # Timing settings
    parser.add_argument("--heartbeat-interval", type=int, default=10,
                       help="Heartbeat interval in seconds (default: 10)")
    
    args = parser.parse_args()
    
    # Setup signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Create and configure simulator
    simulator = OCPPChangeAvailabilitySimulator(args.charger_id, args.server)
    simulator.heartbeat_interval = args.heartbeat_interval
    
    await simulator.run_simulation()


if __name__ == "__main__":
    asyncio.run(main())