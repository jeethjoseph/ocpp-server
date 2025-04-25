import os
import asyncio
import json
import uuid
import websockets
import datetime
from sqlalchemy import create_engine, Column, String, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Database setup
DB_URL = os.environ.get("DATABASE_URL")
engine = create_engine(DB_URL)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)


# Define the OCPP message log model
class OcppMessageLog(Base):
    __tablename__ = "ocpp_message_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    charger_id = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # 'IN' or 'OUT'
    message_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False)
    correlation_id = Column(String, nullable=True)


# Store connected charge points
connected_charge_points = {}


# Log OCPP message to database
def log_message(charger_id, direction, message_type, payload, status, correlation_id=None):
    try:
        session = SessionLocal()
        log_entry = OcppMessageLog(
            charger_id=charger_id,
            direction=direction,
            message_type=message_type,
            payload=payload,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            status=status,
            correlation_id=correlation_id
        )
        session.add(log_entry)
        session.commit()
    except Exception as e:
        print(f"Error logging message: {e}")
    finally:
        session.close()


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

                # Log incoming message
                if message_type_id == 2:  # Call
                    action = ocpp_message[2]
                    payload = ocpp_message[3] if len(ocpp_message) > 3 else {}

                    # Log incoming message
                    log_message(
                        charger_id=charge_point_id,
                        direction="IN",
                        message_type=action,
                        payload=ocpp_message,
                        status="Received",
                        correlation_id=unique_id
                    )

                    # Handle Call messages (from charge point to central system)
                    if action == "BootNotification":
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
                        response_json = json.dumps(response)
                        await websocket.send(response_json)

                        # Log outgoing message
                        log_message(
                            charger_id=charge_point_id,
                            direction="OUT",
                            message_type="BootNotificationResponse",
                            payload=response,
                            status="Sent",
                            correlation_id=unique_id
                        )

                        print(f"Sent BootNotification response to {charge_point_id}")

                elif message_type_id == 3:  # CallResult
                    # Log response
                    log_message(
                        charger_id=charge_point_id,
                        direction="IN",
                        message_type="CallResult",
                        payload=ocpp_message,
                        status="Received",
                        correlation_id=unique_id
                    )

                elif message_type_id == 4:  # CallError
                    # Log error
                    log_message(
                        charger_id=charge_point_id,
                        direction="IN",
                        message_type="CallError",
                        payload=ocpp_message,
                        status="Error",
                        correlation_id=unique_id
                    )

            except json.JSONDecodeError:
                print("Invalid JSON message")
            except Exception as e:
                print(f"Error processing message: {e}")

    finally:
        # Remove charge point on disconnect
        if charge_point_id in connected_charge_points:
            del connected_charge_points[charge_point_id]
        print(f"Charge point {charge_point_id} disconnected")


# Function to send OCPP requests from central system to charge point
async def send_request(charge_point_id, action, payload=None):
    if charge_point_id not in connected_charge_points:
        print(f"Charge point {charge_point_id} not connected")
        return False

    websocket = connected_charge_points[charge_point_id]
    unique_id = str(uuid.uuid4())

    # Default empty payload if none provided
    if payload is None:
        payload = {}

    # OCPP request format: [MessageTypeId, UniqueId, Action, Payload]
    # MessageTypeId 2 = Call
    request = [2, unique_id, action, payload]
    request_json = json.dumps(request)

    try:
        await websocket.send(request_json)

        # Log outgoing message
        log_message(
            charger_id=charge_point_id,
            direction="OUT",
            message_type=action,
            payload=request,
            status="Sent",
            correlation_id=unique_id
        )

        print(f"Sent {action} request to {charge_point_id}")
        return True
    except Exception as e:
        print(f"Error sending request to {charge_point_id}: {e}")

        # Log failed message
        log_message(
            charger_id=charge_point_id,
            direction="OUT",
            message_type=action,
            payload=request,
            status="Failed",
            correlation_id=unique_id
        )

        return False


async def main():
    # Create database tables
    Base.metadata.create_all(engine)
    print("Database tables created")

    # Start WebSocket server
    port = int(os.environ.get("PORT", 9000))
    async with websockets.serve(ocpp_handler, "0.0.0.0", port):
        print(f"OCPP Central System running at ws://0.0.0.0:{port}/ocpp/CP001")
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())