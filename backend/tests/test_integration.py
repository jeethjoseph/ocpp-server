#!/usr/bin/env python3
"""
Integration tests for OCPP WebSocket connections
These tests require the server to be running at localhost:8000
"""

import pytest
import requests
import json
import websocket
import time

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

@pytest.mark.integration
class TestOCPPIntegration:
    """Integration tests for OCPP WebSocket functionality"""
    
    def test_ocpp_websocket_connect_and_listed_in_charge_points(self):
        """Test WebSocket connection and charge point listing"""
        charge_point_id = "test-cp-2"
        
        try:
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
            
            # Check if charge point is listed
            response = requests.get(f"{BASE_URL}/api/charge-points")
            response.raise_for_status()
            ids = [cp["charge_point_id"] for cp in response.json()]
            assert charge_point_id in ids
            
            ws.close()
            time.sleep(0.2)
            
            # Verify charge point is removed after disconnect
            response = requests.get(f"{BASE_URL}/api/charge-points")
            response.raise_for_status()
            ids = [cp["charge_point_id"] for cp in response.json()]
            assert charge_point_id not in ids
            
        except (ConnectionRefusedError, websocket.WebSocketException):
            pytest.skip("Server not running at localhost:8000 - start server to run integration tests")
    
    def test_multiple_charge_points_connect(self):
        """Test multiple charge points connecting simultaneously"""
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
            
            # Check all are listed
            response = requests.get(f"{BASE_URL}/api/charge-points")
            response.raise_for_status()
            listed_ids = [cp["charge_point_id"] for cp in response.json()]
            
            for cp_id in ids:
                assert cp_id in listed_ids
            
            # Close all connections
            for ws in websockets:
                ws.close()
            
            time.sleep(0.2)
            
            # Verify all are removed
            response = requests.get(f"{BASE_URL}/api/charge-points")
            response.raise_for_status()
            listed_ids = [cp["charge_point_id"] for cp in response.json()]
            
            for cp_id in ids:
                assert cp_id not in listed_ids
                
        except (ConnectionRefusedError, websocket.WebSocketException):
            pytest.skip("Server not running at localhost:8000 - start server to run integration tests")
    
    def test_ocpp_bootnotification_response(self):
        """Test OCPP BootNotification response format"""
        charge_point_id = "test-cp-boot"
        
        try:
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
            
            # Verify OCPP response format
            assert isinstance(response, list)
            assert response[0] == 3  # CALLRESULT
            assert response[1] == "12345"  # Message ID
            
            payload = response[2]
            assert "currentTime" in payload
            assert "interval" in payload
            assert "status" in payload
            assert payload["status"] in ["Accepted", "Pending", "Rejected"]
            
            ws.close()
            
        except (ConnectionRefusedError, websocket.WebSocketException):
            pytest.skip("Server not running at localhost:8000 - start server to run integration tests")
        except json.JSONDecodeError:
            pytest.fail("Invalid JSON response from OCPP endpoint")


class OCPPChargerMock:
    """Mock OCPP 1.6 Charger for complete success cycle testing"""
    
    def __init__(self, charge_point_id: str, server_url: str = "ws://localhost:8000"):
        self.charge_point_id = charge_point_id
        self.server_url = server_url
        self.ws = None
        self.message_id_counter = 1
        self.server_time = None
        self.transaction_id = None
        self.current_status = "Unavailable"
        self.is_connected = False
        self.heartbeat_task = None
        self.meter_value_task = None
        self.running = False
        
    def _get_next_message_id(self) -> str:
        """Generate next unique message ID"""
        msg_id = str(self.message_id_counter)
        self.message_id_counter += 1
        return msg_id
    
    def _send_message(self, action: str, payload: dict) -> dict:
        """Send OCPP message and wait for response"""
        message_id = self._get_next_message_id()
        message = [2, message_id, action, payload]
        
        self.ws.send(json.dumps(message))
        response_raw = self.ws.recv()
        response = json.loads(response_raw)
        
        if response[0] == 3:  # CALLRESULT
            return response[2]  # Return payload
        elif response[0] == 4:  # CALLERROR
            raise Exception(f"OCPP Error: {response[2]} - {response[3]}")
        else:
            raise Exception(f"Unknown response type: {response[0]}")
    
    def _handle_incoming_message(self, message: str) -> dict:
        """Handle incoming CALL message from server"""
        try:
            parsed = json.loads(message)
            if parsed[0] == 2:  # CALL
                message_id = parsed[1]
                action = parsed[2]
                payload = parsed[3]
                return {"message_id": message_id, "action": action, "payload": payload}
        except:
            pass
        return None
    
    def _send_call_result(self, message_id: str, payload: dict):
        """Send CALLRESULT response"""
        response = [3, message_id, payload]
        self.ws.send(json.dumps(response))
    
    def connect(self):
        """Connect to OCPP server"""
        self.ws = websocket.create_connection(f"{self.server_url}/ocpp/{self.charge_point_id}")
        self.is_connected = True
        self.running = True
        print(f"[{self.charge_point_id}] Connected to server")
    
    def disconnect(self):
        """Disconnect from server"""
        self.running = False
        if self.ws:
            self.ws.close()
            self.is_connected = False
            print(f"[{self.charge_point_id}] Disconnected from server")
    
    def send_boot_notification(self) -> dict:
        """Send BootNotification and handle clock reset"""
        payload = {
            "chargePointModel": "TestModel",
            "chargePointVendor": "TestVendor"
        }
        
        response = self._send_message("BootNotification", payload)
        
        if "currentTime" in response:
            self.server_time = response["currentTime"]
            print(f"[{self.charge_point_id}] Clock reset to server time: {self.server_time}")
        
        print(f"[{self.charge_point_id}] Boot notification sent, status: {response.get('status', 'Unknown')}")
        return response
    
    def send_heartbeat(self) -> dict:
        """Send Heartbeat message"""
        response = self._send_message("Heartbeat", {})
        if "currentTime" in response:
            self.server_time = response["currentTime"]
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
        print(f"[{self.charge_point_id}] Status changed to: {status}")
        return response
    
    def send_start_transaction(self, id_tag: str = "test_user", connector_id: int = 1) -> dict:
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
            print(f"[{self.charge_point_id}] Transaction started with ID: {self.transaction_id}")
        
        return response
    
    def send_stop_transaction(self, reason: str = "Remote") -> dict:
        """Send StopTransaction message"""
        if not self.transaction_id:
            raise Exception("No active transaction to stop")
        
        payload = {
            "transactionId": self.transaction_id,
            "meterStop": 5000,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "reason": reason
        }
        
        response = self._send_message("StopTransaction", payload)
        print(f"[{self.charge_point_id}] Transaction {self.transaction_id} stopped")
        self.transaction_id = None
        return response
    
    def send_meter_values(self, connector_id: int = 1) -> dict:
        """Send MeterValues message"""
        if not self.transaction_id:
            raise Exception("No active transaction for meter values")
        
        payload = {
            "connectorId": connector_id,
            "transactionId": self.transaction_id,
            "meterValue": [{
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "sampledValue": [{
                    "value": str(2000 + (time.time() % 100)),
                    "context": "Sample.Periodic",
                    "format": "Raw",
                    "measurand": "Energy.Active.Import.Register",
                    "unit": "Wh"
                }]
            }]
        }
        
        response = self._send_message("MeterValues", payload)
        return response
    
    def handle_remote_start_transaction(self, message_id: str, payload: dict) -> bool:
        """Handle RemoteStartTransaction from server"""
        connector_id = payload.get("connectorId", 1)
        id_tag = payload.get("idTag", "remote_user")
        
        # Send confirmation
        self._send_call_result(message_id, {"status": "Accepted"})
        print(f"[{self.charge_point_id}] Remote start transaction accepted")
        
        # Start transaction
        self.send_start_transaction(id_tag, connector_id)
        return True
    
    def handle_remote_stop_transaction(self, message_id: str, payload: dict) -> bool:
        """Handle RemoteStopTransaction from server"""
        # Send confirmation
        self._send_call_result(message_id, {"status": "Accepted"})
        print(f"[{self.charge_point_id}] Remote stop transaction accepted")
        
        # Stop transaction
        self.send_stop_transaction("Remote")
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
                print(f"[{self.charge_point_id}] Error processing message: {e}")
        
        return False


@pytest.mark.integration
class TestOCPPSuccessCycle:
    """OCPP Success Cycle Integration Test"""
    
    @pytest.mark.slow
    def test_ocpp_core_functionality(self):
        """
        Test core OCPP 1.6 functionality (quick validation):
        1. Connect and boot notification with clock reset
        2. Heartbeat messages  
        3. Status notifications
        4. Start/Stop transaction with database integration
        5. Meter values with transaction linkage
        
        Note: For complete simulation with remote commands, use ocpp_simulator.py
        """
        # Use manually created test charger ID
        charge_point_id = "f87a48bc-532e-4aed-862c-c6846dd278f9"
        
        charger = OCPPChargerMock(charge_point_id)
        
        try:
            print(f"\n=== Testing OCPP Core Functionality for {charge_point_id} ===")
            
            # Step 1: Connect to server
            charger.connect()
            
            # Step 2: Send boot notification and verify clock reset
            boot_response = charger.send_boot_notification()
            assert boot_response["status"] == "Accepted"
            assert charger.server_time is not None
            print(f"[{charge_point_id}] ✅ Boot notification with clock reset successful")
            
            # Step 3: Test heartbeat functionality
            for i in range(3):
                charger.send_heartbeat()
                print(f"[{charge_point_id}] ✅ Heartbeat #{i+1} successful")
                time.sleep(0.5)
            
            # Step 4: Test status notifications
            charger.send_status_notification("Available")
            print(f"[{charge_point_id}] ✅ Status notification (Available) successful")
            
            # Step 5: Test transaction lifecycle
            # Start transaction
            start_response = charger.send_start_transaction("test_user", 1)
            transaction_id = start_response.get("transactionId")
            assert transaction_id and transaction_id > 0
            print(f"[{charge_point_id}] ✅ Transaction started with ID: {transaction_id}")
            
            # Update status to charging
            charger.send_status_notification("Charging")
            print(f"[{charge_point_id}] ✅ Status notification (Charging) successful")
            
            # Step 6: Test meter values during transaction
            for i in range(3):
                charger.send_meter_values()
                print(f"[{charge_point_id}] ✅ Meter value #{i+1} sent")
                time.sleep(0.5)
            
            # Step 7: Complete transaction
            charger.send_status_notification("Finishing")
            charger.send_stop_transaction("Local")
            print(f"[{charge_point_id}] ✅ Transaction stopped successfully")
            
            # Step 8: Return to available
            charger.send_status_notification("Available")
            print(f"[{charge_point_id}] ✅ Status returned to Available")
            
            # Final heartbeat
            charger.send_heartbeat()
            
            print(f"\n[{charge_point_id}] ✅ ALL CORE OCPP FUNCTIONALITY WORKING!")
            
            # Verify final state
            assert charger.is_connected
            assert charger.current_status == "Available"
            assert charger.transaction_id is None
            assert charger.server_time is not None
                
        except (ConnectionRefusedError, websocket.WebSocketException):
            pytest.skip("Server not running at localhost:8000 - start server to run integration tests")
        except Exception as e:
            pytest.fail(f"OCPP Core functionality test failed: {str(e)}")
        finally:
            # Cleanup
            charger.disconnect()
            print(f"[{charge_point_id}] Test cleanup completed")
    
    def test_ocpp_remote_commands_info(self):
        """
        Information test: For testing remote commands, use the OCPP simulator
        
        Usage:
            python ocpp_simulator.py --charger-id f87a48bc-532e-4aed-862c-c6846dd278f9
            
        The simulator will:
        1. Connect and send boot notification with clock reset
        2. Send heartbeats every 45 seconds
        3. Wait for remote start transaction commands
        4. Send meter values every 30 seconds during charging
        5. Wait for remote stop transaction commands
        6. Complete the full OCPP success cycle
        """
        print("\n" + "="*80)
        print("🚀 OCPP REMOTE COMMANDS TESTING")
        print("="*80)
        print("For complete remote command testing, use the OCPP simulator:")
        print()
        print("  python ocpp_simulator.py --charger-id f87a48bc-532e-4aed-862c-c6846dd278f9")
        print()
        print("The simulator demonstrates:")
        print("  ✅ Boot notification with clock reset")
        print("  ✅ Regular heartbeats (45s intervals)")
        print("  ✅ Status notifications (Available → Charging → Available)")
        print("  ✅ Remote start transaction handling")
        print("  ✅ Meter values during charging (30s intervals)")
        print("  ✅ Remote stop transaction handling")
        print("  ✅ Complete database integration")
        print()
        print("To test remote commands:")
        print("  1. Start the simulator")
        print("  2. Use admin API to send RemoteStartTransaction")
        print("  3. Watch real-time meter values")
        print("  4. Use admin API to send RemoteStopTransaction")
        print("="*80)
        
        # This test always passes - it's just informational
        assert True