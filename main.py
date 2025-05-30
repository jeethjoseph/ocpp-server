import os
import json
import uuid
import datetime
from typing import Union, Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, JSON, DateTime, desc
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Database setup
DB_URL = os.environ.get("DATABASE_URL")
print("db_url", DB_URL)
engine = create_engine(DB_URL)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

# FastAPI app
app = FastAPI(title="OCPP Central System API", version="1.0.0")

# Pydantic models for FastAPI

class OCPPCommand(BaseModel):
    charge_point_id: str
    action: str
    payload: Dict = {}

class OCPPResponse(BaseModel):
    success: bool
    message: str
    correlation_id: Optional[str] = None

class MessageLogResponse(BaseModel):
    id: str
    charger_id: str
    direction: str
    message_type: str
    payload: Union[Dict, List]  # Allow both Dict and List for OCPP message formats currently it is stored as list we will change it later
    timestamp: datetime.datetime
    status: str
    correlation_id: Optional[str]

class ChargePointStatus(BaseModel):
    charge_point_id: str
    connected: bool
    last_seen: Optional[datetime.datetime]

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

# Store connected charge points with metadata
connected_charge_points: Dict[str, Dict] = {}

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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

# Function to send OCPP requests from central system to charge point
async def send_ocpp_request(charge_point_id: str, action: str, payload: Dict = None):
    if charge_point_id not in connected_charge_points:
        print(f"Charge point {charge_point_id} not connected")
        return False, f"Charge point {charge_point_id} not connected"

    websocket = connected_charge_points[charge_point_id]["websocket"]
    unique_id = str(uuid.uuid4())

    # Default empty payload if none provided
    if payload is None:
        payload = {}

    # OCPP request format: [MessageTypeId, UniqueId, Action, Payload]
    # MessageTypeId 2 = Call
    request = [2, unique_id, action, payload]
    request_json = json.dumps(request)

    try:
        await websocket.send_text(request_json)

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
        return True, unique_id
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

        return False, str(e)

# ============ REST API ENDPOINTS ============

@app.get("/")
def read_root():
    return {"message": "OCPP Central System API", "version": "0.0.1"}

@app.get("/api/")
def read_api_root():
    return {"Hello": "World"}


# OCPP Management Endpoints
@app.get("/api/charge-points", response_model=List[ChargePointStatus])
def get_connected_charge_points():
    """Get list of all connected charge points"""
    charge_points = []
    for cp_id, cp_data in connected_charge_points.items():
        charge_points.append(ChargePointStatus(
            charge_point_id=cp_id,
            connected=True,
            last_seen=cp_data.get("last_seen")
        ))
    return charge_points

@app.post("/api/ocpp/command", response_model=OCPPResponse)
async def send_ocpp_command(command: OCPPCommand):
    """Send OCPP command to a charge point"""
    success, result = await send_ocpp_request(
        command.charge_point_id, 
        command.action, 
        command.payload
    )
    
    if success:
        return OCPPResponse(
            success=True,
            message="Command sent successfully",
            correlation_id=result
        )
    else:
        raise HTTPException(status_code=400, detail=result)

@app.get("/api/ocpp/logs/{charge_point_id}")
def get_charge_point_logs(
    charge_point_id: str, 
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get OCPP message logs for a specific charge point"""
    logs = db.query(OcppMessageLog).filter(
        OcppMessageLog.charger_id == charge_point_id
    ).order_by(desc(OcppMessageLog.timestamp)).limit(limit).all()
    
    return [
        MessageLogResponse(
            id=str(log.id),
            charger_id=log.charger_id,
            direction=log.direction,
            message_type=log.message_type,
            payload=log.payload,
            timestamp=log.timestamp,
            status=log.status,
            correlation_id=log.correlation_id
        ) for log in logs
    ]

@app.get("/api/ocpp/logs")
def get_all_logs(
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all OCPP message logs"""
    logs = db.query(OcppMessageLog).order_by(
        desc(OcppMessageLog.timestamp)
    ).limit(limit).all()
    
    return [
        MessageLogResponse(
            id=str(log.id),
            charger_id=log.charger_id,
            direction=log.direction,
            message_type=log.message_type,
            payload=log.payload,
            timestamp=log.timestamp,
            status=log.status,
            correlation_id=log.correlation_id
        ) for log in logs
    ]

# ============ WEBSOCKET ENDPOINTS (OCPP) ============

@app.websocket("/ocpp/{charge_point_id}")
async def ocpp_websocket_endpoint(websocket: WebSocket, charge_point_id: str):
    """OCPP WebSocket endpoint for charge points"""
    await websocket.accept()
    print(f"Charge point {charge_point_id} connected")

    # Store websocket connection with metadata
    connected_charge_points[charge_point_id] = {
        "websocket": websocket,
        "connected_at": datetime.datetime.now(datetime.timezone.utc),
        "last_seen": datetime.datetime.now(datetime.timezone.utc)
    }

    try:
        while True:
            # Receive message from charge point
            message = await websocket.receive_text()
            print(f"Received from {charge_point_id}: {message}")

            # Update last seen timestamp
            connected_charge_points[charge_point_id]["last_seen"] = datetime.datetime.now(datetime.timezone.utc)

            try:
                # Parse the OCPP message
                ocpp_message = json.loads(message)

                # OCPP 1.6 message format: [MessageTypeId, UniqueId, Action, Payload]
                if len(ocpp_message) < 3:
                    print("Invalid OCPP message format")
                    continue

                message_type_id = ocpp_message[0]
                unique_id = ocpp_message[1]

                # Handle incoming messages
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

                    # Handle specific OCPP actions
                    await handle_ocpp_call(websocket, charge_point_id, action, payload, unique_id)

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
                    print(f"Received CallResult from {charge_point_id}: {ocpp_message}")

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
                    print(f"Received CallError from {charge_point_id}: {ocpp_message}")

            except json.JSONDecodeError:
                print("Invalid JSON message")
            except Exception as e:
                print(f"Error processing message: {e}")

    except WebSocketDisconnect:
        print(f"Charge point {charge_point_id} disconnected")
    except Exception as e:
        print(f"WebSocket error for {charge_point_id}: {e}")
    finally:
        # Remove charge point on disconnect
        if charge_point_id in connected_charge_points:
            del connected_charge_points[charge_point_id]
        print(f"Charge point {charge_point_id} removed from connected list")

async def handle_ocpp_call(websocket: WebSocket, charge_point_id: str, action: str, payload: Dict, unique_id: str):
    """Handle OCPP Call messages from charge points"""
    
    if action == "BootNotification":
        print(f"Boot Notification from {charge_point_id}:")
        print(f"  Vendor: {payload.get('chargePointVendor')}")
        print(f"  Model: {payload.get('chargePointModel')}")

        # Respond to BootNotification
        response_payload = {
            "status": "Accepted",
            "currentTime": datetime.datetime.utcnow().isoformat() + "Z",
            "interval": 300  # Heartbeat interval in seconds
        }

        await send_ocpp_response(websocket, charge_point_id, unique_id, response_payload, "BootNotificationResponse")

    elif action == "Heartbeat":
        print(f"Heartbeat from {charge_point_id}")

        response_payload = {
            "currentTime": datetime.datetime.utcnow().isoformat() + "Z"
        }

        await send_ocpp_response(websocket, charge_point_id, unique_id, response_payload, "HeartbeatResponse")

    elif action == "StatusNotification":
        print(f"Status Notification from {charge_point_id}: {payload}")

        response_payload = {}
        await send_ocpp_response(websocket, charge_point_id, unique_id, response_payload, "StatusNotificationResponse")

    elif action == "MeterValues":
        print(f"Meter Values from {charge_point_id}: {payload}")

        response_payload = {}
        await send_ocpp_response(websocket, charge_point_id, unique_id, response_payload, "MeterValuesResponse")

    elif action == "StartTransaction":
        print(f"Start Transaction from {charge_point_id}: {payload}")

        response_payload = {
            "transactionId": int(unique_id.replace("-", "")[:8], 16),  # Simple transaction ID generation
            "idTagInfo": {
                "status": "Accepted"
            }
        }

        await send_ocpp_response(websocket, charge_point_id, unique_id, response_payload, "StartTransactionResponse")

    elif action == "StopTransaction":
        print(f"Stop Transaction from {charge_point_id}: {payload}")

        response_payload = {
            "idTagInfo": {
                "status": "Accepted"
            }
        }

        await send_ocpp_response(websocket, charge_point_id, unique_id, response_payload, "StopTransactionResponse")

    else:
        print(f"Unhandled OCPP action: {action}")
        # Send generic response
        response_payload = {}
        await send_ocpp_response(websocket, charge_point_id, unique_id, response_payload, f"{action}Response")

async def send_ocpp_response(websocket: WebSocket, charge_point_id: str, unique_id: str, payload: Dict, message_type: str):
    """Send OCPP CallResult response"""
    # OCPP response format: [MessageTypeId, UniqueId, Payload]
    # MessageTypeId 3 = CallResult
    response = [3, unique_id, payload]
    response_json = json.dumps(response)
    
    try:
        await websocket.send_text(response_json)

        # Log outgoing message
        log_message(
            charger_id=charge_point_id,
            direction="OUT",
            message_type=message_type,
            payload=response,
            status="Sent",
            correlation_id=unique_id
        )

        print(f"Sent {message_type} to {charge_point_id}")
    except Exception as e:
        print(f"Error sending response to {charge_point_id}: {e}")

# ============ STARTUP EVENT ============

@app.on_event("startup")
async def startup_event():
    """Initialize database tables on startup"""
    Base.metadata.create_all(engine)
    print("Database tables created/verified")
    print("OCPP Central System API started")
    print("REST API available at: /api/")
    print("OCPP WebSocket available at: /ocpp/{charge_point_id}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)