import os
import datetime
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from schemas import OCPPCommand, OCPPResponse, MessageLogResponse, ChargePointStatus
from crud import log_message, get_logs, get_logs_by_charge_point

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16 import call, call_result
from ocpp.routing import on

import logging


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ocpp-server")

# FastAPI app
app = FastAPI(title="OCPP Central System API", version="1.0.0")

# Store connected charge points with metadata
connected_charge_points: Dict[str, Dict] = {}

# Define a ChargePoint class using python-ocpp
class ChargePoint(OcppChargePoint):
    @on('BootNotification')
    async def on_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
        logger.info(f"BootNotification from {self.id}: vendor={charge_point_vendor}, model={charge_point_model}")
        return call_result.BootNotification(
            current_time=datetime.datetime.utcnow().isoformat() + "Z",
            interval=300,
            status="Accepted"
        )

    @on('Heartbeat')
    async def on_heartbeat(self, **kwargs):
        logger.info(f"Heartbeat from {self.id}")
        return call_result.HeartbeatPayload(
            current_time=datetime.datetime.utcnow().isoformat() + "Z"
        )

# Adapter to make FastAPI's WebSocket compatible with python-ocpp
class FastAPIWebSocketAdapter:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def recv(self):
        return await self.websocket.receive_text()

    async def send(self, data):
        await self.websocket.send_text(data)

# Logging adapter to persist all OCPP messages to DB
class LoggingWebSocketAdapter(FastAPIWebSocketAdapter):
    def __init__(self, websocket: WebSocket, charge_point_id: str, db: Session):
        super().__init__(websocket)
        self.charge_point_id = charge_point_id
        self.db = db

    async def recv(self):
        msg = await super().recv()
        correlation_id = None
        try:
            import json
            parsed = json.loads(msg)
            if isinstance(parsed, list) and len(parsed) > 1:
                correlation_id = str(parsed[1])
        except Exception:
            logger.error(f"Failed to parse OCPP message in the logging adapter: {msg}", exc_info=True)
        log_message(
            db=self.db,
            charger_id=self.charge_point_id,
            direction="IN",
            message_type="OCPP",
            payload=msg,
            status="received",
            correlation_id=correlation_id
        )
        logger.info(f"[OCPP][IN] {msg}")
        return msg

    async def send(self, data):
        correlation_id = None
        try:
            import json
            parsed = json.loads(data)
            if isinstance(parsed, list) and len(parsed) > 1:
                correlation_id = str(parsed[1])
        except Exception:
            logger.error(f"Failed to parse OCPP message in the logging adapter: {data}", exc_info=True)
        log_message(
            db=self.db,
            charger_id=self.charge_point_id,
            direction="OUT",
            message_type="OCPP",
            payload=data,
            status="sent",
            correlation_id=correlation_id
        )
        logger.info(f"[OCPP][OUT] {data}")
        await super().send(data)

# Function to send OCPP requests from central system to charge point. In this particualar use case we use the API to send a message
async def send_ocpp_request(charge_point_id: str, action: str, payload: Dict = None, db: Session = Depends(get_db)):
    if charge_point_id not in connected_charge_points:
        logger.warning(f"Charge point {charge_point_id} not connected")
        return False, f"Charge point {charge_point_id} not connected"

    cp = connected_charge_points[charge_point_id].get("cp")
    if not cp:
        logger.warning(f"ChargePoint instance for {charge_point_id} not found")
        return False, f"ChargePoint instance for {charge_point_id} not found"

    try:
        # Example: only RemoteStartTransaction is implemented here
        if action == "RemoteStartTransaction":
            req = call.RemoteStartTransactionPayload(**(payload or {}))
            response = await cp.call(req)
            logger.info(f"Sent {action} request to {charge_point_id}")
            return True, response
        else:
            logger.warning(f"Action {action} not implemented in send_ocpp_request")
            return False, f"Action {action} not implemented"
    except Exception as e:
        logger.error(f"Error sending request to {charge_point_id}: {e}", exc_info=True)
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
    logs = get_logs_by_charge_point(db, charge_point_id, limit)
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
    logs = get_logs(db, limit)
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
async def ocpp_websocket_endpoint(websocket: WebSocket, charge_point_id: str, db: Session = Depends(get_db)):
    """OCPP WebSocket endpoint for charge points"""
    await websocket.accept()
    logger.info(f"Charge point {charge_point_id} connected")

    ws_adapter = LoggingWebSocketAdapter(websocket, charge_point_id, db)
    cp = ChargePoint(charge_point_id, ws_adapter)
    connected_charge_points[charge_point_id] = {
        "websocket": websocket,
        "cp": cp,
        "connected_at": datetime.datetime.now(datetime.timezone.utc),
        "last_seen": datetime.datetime.now(datetime.timezone.utc)
    }

    try:
        await cp.start()
    except WebSocketDisconnect:
        logger.error(f"Charge point {charge_point_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error for {charge_point_id}: {e}", exc_info=True)
    finally:
        if charge_point_id in connected_charge_points:
            del connected_charge_points[charge_point_id]
        logger.info(f"Charge point {charge_point_id} removed from connected list")

# ============ STARTUP EVENT ============

@app.on_event("startup")
async def startup_event():
    """Initialize database tables on startup"""
    from database import engine
    from models import Base
    Base.metadata.create_all(engine)
    logger.info("Database tables created/verified")
    logger.info("OCPP Central System API started")
    logger.info("REST API available at: /api/")
    logger.info("OCPP WebSocket available at: /ocpp/{charge_point_id}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)