#!/usr/bin/env python3
"""
OCPP 1.6 Charger Simulator for Real-World Testing

This simulator acts like a real charging station:
1. Connects to OCPP server
2. Sends boot notification with clock reset
3. Sends regular heartbeats every 10 seconds  
4. Waits for remote start transaction commands
5. Sends meter values every 30 seconds during charging
6. Waits for remote stop transaction commands
7. Demonstrates complete OCPP success cycle

Usage:
    python ocpp_simulator.py --charger-id f87a48bc-532e-4aed-862c-c6846dd278f9
    python ocpp_simulator.py --charger-id f87a48bc-532e-4aed-862c-c6846dd278f9 --server ws://localhost:8000
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


class OCPPChargerSimulator:
    """Real OCPP 1.6 Charger Simulator for end-to-end testing"""
    
    def __init__(self, charge_point_id: str, server_url: str = "ws://localhost:8000"):
        self.charge_point_id = charge_point_id
        self.server_url = server_url
        self.ws = None
        self.message_id_counter = 1
        self.server_time = None
        self.transaction_id = None
        self.current_status = "Unavailable"
        self.is_connected = False
        self.running = False
        
        # Timing intervals (in seconds)
        self.heartbeat_interval = 10
        self.meter_value_interval = 30
        
        # Background tasks
        self.heartbeat_task = None
        self.meter_value_task = None
        
        # Development features
        self.auto_start = False
        self.auto_stop_after = None
        self.debug_mode = False
        self.statistics = {
            "messages_sent": 0,
            "messages_received": 0,
            "transactions": 0,
            "meter_values": 0,
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
        
        # Set timeout for response to avoid infinite blocking
        self.ws.settimeout(10.0)  # 10 second timeout
        try:
            response_raw = self.ws.recv()
            response = json.loads(response_raw)
            self.statistics["messages_received"] += 1
            
            if response[0] == 3:  # CALLRESULT
                if self.debug_mode:
                    print(f"📥 [{self.charge_point_id}] Received response: {json.dumps(response[2], indent=2)}")
                else:
                    print(f"📥 [{self.charge_point_id}] Response: {action} OK")
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
                print(f"📥 [{self.charge_point_id}] Received {action}: {payload}")
                return {"message_id": message_id, "action": action, "payload": payload}
        except:
            pass
        return None
    
    def _send_call_result(self, message_id: str, payload: dict):
        """Send CALLRESULT response"""
        response = [3, message_id, payload]
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
        if self.meter_value_task:
            self.meter_value_task.cancel()
        if self.ws:
            self.ws.close()
            self.is_connected = False
            print(f"🔌 [{self.charge_point_id}] Disconnected from server")
    
    def send_boot_notification(self) -> dict:
        """Send BootNotification and handle clock reset"""
        payload = {
            "chargePointModel": "SimulatorModel",
            "chargePointVendor": "SimulatorVendor"
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
    
    def send_start_transaction(self, id_tag: str = "simulator_user", connector_id: int = 1) -> dict:
        """Send StartTransaction message"""
        payload = {
            "connectorId": connector_id,
            "idTag": id_tag,
            "meterStart": 1000,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        }
        
        response = self._send_message("StartTransaction", payload)
        if "transactionId" in response:
            self.transaction_id = response["transactionId"]
            self.statistics["transactions"] += 1
            print(f"🔋 [{self.charge_point_id}] ⭐ TRANSACTION STARTED with ID: {self.transaction_id} ⭐")
            
            # Start meter values automatically when transaction starts
            self.start_meter_value_task()
            print(f"⚡ [{self.charge_point_id}] Meter values started")
        
        return response
    
    def send_stop_transaction(self, reason: str = "Remote") -> dict:
        """Send StopTransaction message"""
        if not self.transaction_id:
            raise Exception("No active transaction to stop")
        
        # Stop meter values automatically when transaction stops
        if self.meter_value_task:
            self.meter_value_task.cancel()
            self.meter_value_task = None
            print(f"⚡ [{self.charge_point_id}] Meter values stopped")
        
        payload = {
            "transactionId": self.transaction_id,
            "meterStop": 5000,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "reason": reason
        }
        
        response = self._send_message("StopTransaction", payload)
        print(f"🛑 [{self.charge_point_id}] ⭐ TRANSACTION {self.transaction_id} STOPPED ⭐")
        self.transaction_id = None
        return response
    
    def send_meter_values(self, connector_id: int = 1) -> dict:
        """Send comprehensive MeterValues message with all measurands"""
        if not self.transaction_id:
            return {}
        
        # Simulate realistic charging values
        time_elapsed = time.time() % 1000
        current_energy = 2000 + time_elapsed  # Increasing energy consumption
        
        # Simulate realistic electrical values during charging
        import random
        base_current = 32.0  # 32A typical for AC charging
        base_voltage = 230.0  # 230V typical for AC charging
        base_power = 7.4  # 7.4kW typical for AC charging
        
        # Add some realistic variation
        current_variation = random.uniform(0.9, 1.1)
        voltage_variation = random.uniform(0.98, 1.02)
        power_variation = random.uniform(0.9, 1.1)
        
        current_amps = base_current * current_variation
        voltage_volts = base_voltage * voltage_variation  
        power_watts = base_power * power_variation * 1000  # Convert kW to W
        
        payload = {
            "connectorId": connector_id,
            "transactionId": self.transaction_id,
            "meterValue": [{
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "sampledValue": [
                    {
                        "value": str(int(current_energy)),
                        "context": "Sample.Periodic",
                        "format": "Raw",
                        "measurand": "Energy.Active.Import.Register",
                        "unit": "Wh"
                    },
                    {
                        "value": str(round(current_amps, 2)),
                        "context": "Sample.Periodic", 
                        "format": "Raw",
                        "measurand": "Current.Import",
                        "unit": "A"
                    },
                    {
                        "value": str(round(voltage_volts, 1)),
                        "context": "Sample.Periodic",
                        "format": "Raw", 
                        "measurand": "Voltage",
                        "unit": "V"
                    },
                    {
                        "value": str(int(power_watts)),
                        "context": "Sample.Periodic",
                        "format": "Raw",
                        "measurand": "Power.Active.Import", 
                        "unit": "W"
                    }
                ]
            }]
        }
        
        response = self._send_message("MeterValues", payload)
        self.statistics["meter_values"] += 1
        print(f"⚡ [{self.charge_point_id}] Meter values sent: "
              f"{int(current_energy)} Wh, {current_amps:.1f}A, {voltage_volts:.1f}V, {power_watts/1000:.1f}kW")
        return response
    
    def handle_remote_start_transaction(self, message_id: str, payload: dict) -> bool:
        """Handle RemoteStartTransaction from server"""
        connector_id = payload.get("connectorId", 1)
        id_tag = payload.get("idTag", "remote_user")
        
        # Send confirmation
        self._send_call_result(message_id, {"status": "Accepted"})
        print(f"✅ [{self.charge_point_id}] ⭐ REMOTE START TRANSACTION ACCEPTED ⭐")
        
        # Start transaction (meter values will start automatically)
        self.send_start_transaction(id_tag, connector_id)
        
        # Change status to charging
        self.send_status_notification("Charging")
        
        return True
    
    def handle_remote_stop_transaction(self, message_id: str, payload: dict) -> bool:
        """Handle RemoteStopTransaction from server"""
        # Send confirmation
        self._send_call_result(message_id, {"status": "Accepted"})
        print(f"✅ [{self.charge_point_id}] ⭐ REMOTE STOP TRANSACTION ACCEPTED ⭐")
        
        # Change status to finishing
        self.send_status_notification("Finishing")
        
        # Stop transaction (meter values will stop automatically)
        self.send_stop_transaction("Remote")
        
        # Return to available briefly, then back to preparing for next cycle
        self.send_status_notification("Available")
        
        # After a short delay, go back to preparing state for next transaction
        import time
        time.sleep(2)
        self.send_status_notification("Preparing")
        print(f"🔄 [{self.charge_point_id}] Ready for next transaction cycle")
        
        return True
    
    def process_incoming_messages(self, timeout: float = 0.1):
        """Process any incoming messages from server"""
        try:
            self.ws.settimeout(timeout)
            message_raw = self.ws.recv()
            message = self._handle_incoming_message(message_raw)
            
            if message:
                action = message["action"]
                if action == "RemoteStartTransaction":
                    return self.handle_remote_start_transaction(message["message_id"], message["payload"])
                elif action == "RemoteStopTransaction":
                    return self.handle_remote_stop_transaction(message["message_id"], message["payload"])
                    
        except websocket.WebSocketTimeoutException:
            pass
        except Exception as e:
            if self.running:
                print(f"❌ [{self.charge_point_id}] Error processing message: {e}")
        
        return False
    
    async def heartbeat_loop(self):
        """Send heartbeats every 10 seconds"""
        while self.running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if self.running:
                    self.send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ [{self.charge_point_id}] Heartbeat error: {e}")
                # Continue running instead of crashing on heartbeat errors
                await asyncio.sleep(5)  # Wait 5 seconds before trying again
    
    async def meter_value_loop(self):
        """Send meter values every 30 seconds during transaction"""
        while self.running and self.transaction_id:
            try:
                await asyncio.sleep(self.meter_value_interval)
                if self.running and self.transaction_id:
                    self.send_meter_values()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ [{self.charge_point_id}] Meter value error: {e}")
    
    def start_heartbeat_task(self):
        """Start heartbeat background task"""
        if not self.heartbeat_task:
            self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
    
    def start_meter_value_task(self):
        """Start meter value background task"""
        if not self.meter_value_task:
            self.meter_value_task = asyncio.create_task(self.meter_value_loop())
    
    def print_statistics(self):
        """Print current statistics"""
        if not self.statistics["start_time"]:
            return
            
        uptime = time.time() - self.statistics["start_time"]
        print(f"\n📊 [{self.charge_point_id}] STATISTICS")
        print(f"   ⏱️  Uptime: {uptime:.1f}s")
        print(f"   📤 Messages sent: {self.statistics['messages_sent']}")
        print(f"   📥 Messages received: {self.statistics['messages_received']}")
        print(f"   🔋 Transactions: {self.statistics['transactions']}")
        print(f"   ⚡ Meter values: {self.statistics['meter_values']}")
        print(f"   📊 Status: {self.current_status}")
        print(f"   🔌 Connected: {self.is_connected}")
        if self.transaction_id:
            print(f"   🏃 Active transaction: {self.transaction_id}")
        print("")
    
    async def post_boot_initialization(self):
        """Handle post-boot initialization sequence"""
        print(f"⏰ [{self.charge_point_id}] Post-boot initialization in 60 seconds...")
        await asyncio.sleep(60)
        
        if self.running and not self.transaction_id:
            print(f"🔧 [{self.charge_point_id}] Entering PREPARING state - Ready for remote commands")
            self.send_status_notification("Preparing")

    async def auto_transaction_demo(self):
        """Auto-start a transaction for demo purposes"""
        if not self.auto_start:
            return
            
        print(f"🤖 [{self.charge_point_id}] Auto-demo mode: starting transaction in 10 seconds...")
        await asyncio.sleep(10)
        
        if not self.transaction_id and self.running:
            print(f"🤖 [{self.charge_point_id}] Auto-starting transaction...")
            self.send_start_transaction("auto_demo_user")  # Meter values start automatically
            self.send_status_notification("Charging") 
            
            # Auto stop after specified time
            if self.auto_stop_after:
                print(f"🤖 [{self.charge_point_id}] Will auto-stop in {self.auto_stop_after} seconds...")
                await asyncio.sleep(self.auto_stop_after)
                if self.transaction_id and self.running:
                    print(f"🤖 [{self.charge_point_id}] Auto-stopping transaction...")
                    self.send_status_notification("Finishing")
                    await asyncio.sleep(1)
                    self.send_stop_transaction("AutoDemo")  # Meter values stop automatically
                    self.send_status_notification("Available")
    
    async def run_simulation(self):
        """Run the complete OCPP simulation"""
        try:
            print(f"\n{'='*80}")
            print(f"🚀 STARTING OCPP 1.6 CHARGER SIMULATOR")
            print(f"📍 Charger ID: {self.charge_point_id}")
            print(f"🌐 Server: {self.server_url}")
            if self.debug_mode:
                print(f"🐛 Debug mode: ON")
            if self.auto_start:
                print(f"🤖 Auto-demo mode: ON (stop after {self.auto_stop_after}s)")
            print(f"{'='*80}\n")
            
            # Initialize statistics
            self.statistics["start_time"] = time.time()
            
            # Step 1: Connect to server
            self.connect()
            
            # Step 2: Send boot notification with clock reset
            boot_response = self.send_boot_notification()
            assert boot_response["status"] == "Accepted"
            
            # Step 3: Start heartbeat loop immediately after boot notification
            self.start_heartbeat_task()
            
            # Step 4: Send initial status notification
            self.send_status_notification("Available")
            
            # Step 5: Start post-boot initialization (1 min delay to PREPARING)
            asyncio.create_task(self.post_boot_initialization())
            
            # Step 6: Start auto demo if enabled
            if self.auto_start:
                asyncio.create_task(self.auto_transaction_demo())
            
            print(f"\n🔄 [{self.charge_point_id}] Ready for remote commands...")
            print(f"💡 To test the simulator:")
            print(f"   1. Send RemoteStartTransaction via API or admin panel")
            print(f"   2. Watch the charging simulation with meter values")
            print(f"   3. Send RemoteStopTransaction to complete the cycle")
            print(f"   4. Press 's' + Enter to show statistics")
            print(f"   5. Press Ctrl+C to stop the simulator")
            print(f"\n⏰ Heartbeats every {self.heartbeat_interval}s, Meter values every {self.meter_value_interval}s")
            print(f"{'='*80}\n")
            
            # Main loop - process incoming messages and handle user input
            last_stats_time = time.time()
            while self.running:
                self.process_incoming_messages(timeout=0.1)
                
                # Show periodic statistics in debug mode
                if self.debug_mode and time.time() - last_stats_time > 30:
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


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Stopping simulator...")
    sys.exit(0)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="OCPP 1.6 Charger Simulator - Enhanced for Development",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Development Examples:
  # Basic simulation
  python ocpp_simulator.py --charger-id f87a48bc-532e-4aed-862c-c6846dd278f9
  
  # Fast development mode (quick intervals)
  python ocpp_simulator.py --charger-id test-dev --heartbeat-interval 10 --meter-interval 5 --debug
  
  # Auto-demo mode (starts transaction automatically)
  python ocpp_simulator.py --charger-id test-auto --auto-start --auto-stop 30
  
  # Production-like simulation
  python ocpp_simulator.py --charger-id prod-test --heartbeat-interval 45 --meter-interval 30
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
    parser.add_argument("--meter-interval", type=int, default=30, 
                       help="Meter value interval in seconds (default: 30)")
    
    # Development features
    parser.add_argument("--debug", action="store_true", 
                       help="Enable debug mode with detailed message logging")
    parser.add_argument("--auto-start", action="store_true", 
                       help="Automatically start a transaction after 10 seconds")
    parser.add_argument("--auto-stop", type=int, metavar="SECONDS",
                       help="Auto-stop transaction after specified seconds (requires --auto-start)")
    
    # Quick presets
    parser.add_argument("--dev-mode", action="store_true",
                       help="Development preset: --heartbeat-interval 10 --meter-interval 5 --debug")
    parser.add_argument("--demo-mode", action="store_true", 
                       help="Demo preset: --auto-start --auto-stop 60 --heartbeat-interval 15")
    
    args = parser.parse_args()
    
    # Apply presets
    if args.dev_mode:
        args.heartbeat_interval = 10
        args.meter_interval = 5
        args.debug = True
        print("🚀 Development mode enabled: Fast intervals + Debug logging")
        
    if args.demo_mode:
        args.auto_start = True
        args.auto_stop = 60
        args.heartbeat_interval = 15
        args.meter_interval = 10
        print("🎭 Demo mode enabled: Auto transaction cycle")
    
    # Validation
    if args.auto_stop and not args.auto_start:
        parser.error("--auto-stop requires --auto-start")
    
    # Setup signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Create and configure simulator
    simulator = OCPPChargerSimulator(args.charger_id, args.server)
    simulator.heartbeat_interval = args.heartbeat_interval
    simulator.meter_value_interval = args.meter_interval
    simulator.debug_mode = args.debug
    simulator.auto_start = args.auto_start
    simulator.auto_stop_after = args.auto_stop
    
    await simulator.run_simulation()


if __name__ == "__main__":
    asyncio.run(main())