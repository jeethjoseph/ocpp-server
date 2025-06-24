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