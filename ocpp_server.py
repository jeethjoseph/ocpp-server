import os
import asyncio
import json
import websockets
import datetime

# Store connected charge points
connected_charge_points = {}


async def ocpp_handler(websocket, path):
    # Extract charge point ID from URL path (e.g., /ocpp/CP001)
    charge_point_id = path.strip("/").split("/")[-1]
    print(f"Charge point {charge_point_id} connected")

    # Store websocket connection with charge point ID
    connected_charge_points[charge_point_id] = websocket

    try:
        async for message in websocket:
            print(f"Received: {message}")

            try:
                # Parse the OCPP message
                ocpp_message = json.loads(message)

                # OCPP 1.6 message format: [MessageTypeId, UniqueId, Action, Payload]
                if len(ocpp_message) < 3:
                    print("Invalid OCPP message format")
                    continue

                message_type_id = ocpp_message[0]
                unique_id = ocpp_message[1]
                action = ocpp_message[2]

                # Handle Call messages (from charge point to central system)
                if message_type_id == 2:  # 2 = Call
                    if action == "BootNotification":
                        payload = ocpp_message[3]
                        print(f"Boot Notification from {charge_point_id}:")
                        print(f"  Vendor: {payload.get('chargePointVendor')}")
                        print(f"  Model: {payload.get('chargePointModel')}")

                        # Respond to BootNotification
                        response_payload = {
                            "status": "Accepted",
                            "currentTime": datetime.datetime.utcnow().isoformat(),
                            "interval": 300  # Heartbeat interval in seconds
                        }

                        # OCPP response format: [MessageTypeId, UniqueId, Payload]
                        # MessageTypeId 3 = CallResult
                        response = [3, unique_id, response_payload]
                        await websocket.send(json.dumps(response))
                        print(f"Sent BootNotification response to {charge_point_id}")

            except json.JSONDecodeError:
                print("Invalid JSON message")
            except Exception as e:
                print(f"Error processing message: {e}")

    finally:
        # Remove charge point on disconnect
        if charge_point_id in connected_charge_points:
            del connected_charge_points[charge_point_id]
        print(f"Charge point {charge_point_id} disconnected")


async def main():
    # Start WebSocket server
    port = int(os.environ.get("PORT", 9000))
    async with websockets.serve(ocpp_handler, "0.0.0.0", port):
        print(f"OCPP Central System running at ws://0.0.0.0:{port}/ocpp/CP001")
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())