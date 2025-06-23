# main.py
import os
import datetime
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, close_db
from schemas import OCPPCommand, OCPPResponse, MessageLogResponse, ChargePointStatus
from crud import (
    log_message, 
    get_logs, 
    get_logs_by_charge_point, 
    validate_and_connect_charger,
    update_charger_status
)
from models import OCPPLog

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16 import call, call_result
from ocpp.routing import on

import logging
import json

# Import routers
from routers import stations, chargers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ocpp-server")

# FastAPI app
app = FastAPI(
    title="OCPP Central System API", 
    version="0.1.0",
    description="EV Charging Station Management System with OCPP 1.6 support"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000","https://ocpp-frontend-mu.vercel.app/" ],  # Frontend origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store connected charge points with metadata
connected_charge_points: Dict[str, Dict] = {}

# Define a ChargePoint class using python-ocpp
class ChargePoint(OcppChargePoint):
    @on('BootNotification')
    async def on_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
        logger.info(f"BootNotification from {self.id}: vendor={charge_point_vendor}, model={charge_point_model}")
        # Update charger status in database
        await update_charger_status(self.id, "AVAILABLE")
        
        return call_result.BootNotification(
            current_time=datetime.datetime.utcnow().isoformat() + "Z",
            interval=300,
            status="Accepted"
        )

    @on('Heartbeat')
    async def on_heartbeat(self, **kwargs):
        logger.info(f"Heartbeat from {self.id}")
        # Update last heartbeat time
        await update_charger_status(self.id, "AVAILABLE")
        
        return call_result.Heartbeat(
            current_time=datetime.datetime.utcnow().isoformat() + "Z"
        )
    
    @on('StatusNotification')
    async def on_status_notification(self, connector_id, status, error_code=None, info=None, **kwargs):
        logger.info(f"StatusNotification from {self.id}: connector_id={connector_id}, status={status}, error_code={error_code}, info={info}")
        # Update charger status in database
        await update_charger_status(self.id, status)
        
        return call_result.StatusNotification()

    @on('StartTransaction')
    async def on_start_transaction(self, connector_id, id_tag, meter_start, timestamp, **kwargs):
        logger.info(f"StartTransaction from {self.id}: connector_id={connector_id}, id_tag={id_tag}, meter_start={meter_start}")
        # You can add transaction creation logic here
        # For now, just accept with a dummy transaction ID
        return call_result.StartTransaction(
            transaction_id=1,  # You should generate a real transaction ID
            id_tag_info={"status": "Accepted"}
        )

    @on('StopTransaction')
    async def on_stop_transaction(self, transaction_id, meter_stop, timestamp, **kwargs):
        logger.info(f"StopTransaction from {self.id}: transaction_id={transaction_id}, meter_stop={meter_stop}")
        # You can add transaction completion logic here
        return call_result.StopTransaction(
            id_tag_info={"status": "Accepted"}
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
    def __init__(self, websocket: WebSocket, charge_point_id: str):
        super().__init__(websocket)
        self.charge_point_id = charge_point_id

    async def recv(self):
        msg = await super().recv()
        correlation_id = None
        try:
            parsed = json.loads(msg)
            if isinstance(parsed, list) and len(parsed) > 1:
                correlation_id = str(parsed[1])
        except Exception:
            logger.error(f"Failed to parse OCPP message in the logging adapter: {msg}", exc_info=True)
        
        await log_message(
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
            parsed = json.loads(data)
            if isinstance(parsed, list) and len(parsed) > 1:
                correlation_id = str(parsed[1])
        except Exception:
            logger.error(f"Failed to parse OCPP message in the logging adapter: {data}", exc_info=True)
        
        await log_message(
            charger_id=self.charge_point_id,
            direction="OUT",
            message_type="OCPP",
            payload=data,
            status="sent",
            correlation_id=correlation_id
        )
        logger.info(f"[OCPP][OUT] {data}")
        await super().send(data)

# Function to send OCPP requests from central system to charge point
async def send_ocpp_request(charge_point_id: str, action: str, payload: Dict = None):
    if charge_point_id not in connected_charge_points:
        logger.warning(f"Charge point {charge_point_id} not connected")
        return False, f"Charge point {charge_point_id} not connected"

    cp = connected_charge_points[charge_point_id].get("cp")
    if not cp:
        logger.warning(f"ChargePoint instance for {charge_point_id} not found")
        return False, f"ChargePoint instance for {charge_point_id} not found"

    try:
        if action == "RemoteStartTransaction":
            req = call.RemoteStartTransaction(**(payload or {}))
            response = await cp.call(req)
            logger.info(f"Sent {action} request to {charge_point_id}")
            return True, response
        elif action == "RemoteStopTransaction":
            req = call.RemoteStopTransaction(**(payload or {}))
            response = await cp.call(req)
            logger.info(f"Sent {action} request to {charge_point_id}")
            return True, response
        elif action == "ChangeAvailability":
            req = call.ChangeAvailability(**(payload or {}))
            response = await cp.call(req)
            logger.info(f"Sent {action} request to {charge_point_id}")
            return True, response
        else:
            logger.warning(f"Action {action} not implemented in send_ocpp_request")
            return False, f"Action {action} not implemented"
    except Exception as e:
        logger.error(f"Error sending request to {charge_point_id}: {e}", exc_info=True)
        return False, str(e)

# ============ Include Routers ============
app.include_router(stations.router)
app.include_router(chargers.router)

# ============ OCPP WebSocket Endpoint ============
@app.websocket("/ocpp/{charge_point_id}")
async def ocpp_websocket(websocket: WebSocket, charge_point_id: str):
    """OCPP WebSocket endpoint for charge points"""
    await websocket.accept()
    logger.info(f"Charge point {charge_point_id} connected")

    # Validate charger before connecting
    is_valid, message = await validate_and_connect_charger(charge_point_id, connected_charge_points)
    if not is_valid:
        logger.warning(f"Validation failed for {charge_point_id}: {message}")
        await websocket.close(code=1008, reason=message)
        return

    ws_adapter = LoggingWebSocketAdapter(websocket, charge_point_id)
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

# ============ Basic API Endpoints ============

@app.get("/")
def read_root():
    return {
        "message": "OCPP Central System API",
        "version": "0.1.0",
        "docs": "/docs",
        "ocpp_endpoint": "/ocpp/{charge_point_id}"
    }

@app.get("/api/")
def read_api_root():
    return {
        "endpoints": {
            "stations": "/api/admin/stations",
            "chargers": "/api/admin/chargers",
            "charge_points": "/api/charge-points",
            "logs": "/api/logs"
        }
    }

# Legacy endpoints - these were in your original main.py
@app.get("/api/charge-points", response_model=List[ChargePointStatus])
def get_connected_charge_points():
    """Get list of all connected charge points"""
    charge_points = []
    for cp_id, cp_data in connected_charge_points.items():
        charge_points.append(ChargePointStatus(
            charge_point_id=cp_id,
            connected_at=cp_data["connected_at"],
            last_seen=cp_data["last_seen"],
            connected=True
        ))
    return charge_points

@app.post("/api/charge-points/{charge_point_id}/request")
async def send_command_to_charge_point(charge_point_id: str, command: OCPPCommand):
    """Send OCPP command to a specific charge point"""
    success, result = await send_ocpp_request(charge_point_id, command.action, command.payload)
    
    if success:
        return OCPPResponse(
            success=True,
            message=f"Command {command.action} sent successfully",
            data=result.dict() if hasattr(result, 'dict') else str(result)
        )
    else:
        raise HTTPException(status_code=400, detail=result)

@app.get("/api/logs", response_model=List[MessageLogResponse])
async def get_message_logs(limit: int = 100):
    """Get recent OCPP message logs"""
    logs = await get_logs(limit)
    return [
        MessageLogResponse(
            id=log.id,
            charge_point_id=log.charge_point_id,
            direction=log.direction,
            message_type=log.message_type,
            payload=log.payload,
            status=log.status,
            correlation_id=log.correlation_id,
            timestamp=log.timestamp
        ) for log in logs
    ]

@app.get("/api/logs/{charge_point_id}", response_model=List[MessageLogResponse])
async def get_charge_point_logs(charge_point_id: str, limit: int = 100):
    """Get OCPP message logs for a specific charge point"""
    logs = await get_logs_by_charge_point(charge_point_id, limit)
    return [
        MessageLogResponse(
            id=log.id,
            charge_point_id=log.charge_point_id,
            direction=log.direction,
            message_type=log.message_type,
            payload=log.payload,
            status=log.status,
            correlation_id=log.correlation_id,
            timestamp=log.timestamp
        ) for log in logs
    ]

# ============ STARTUP/SHUTDOWN EVENTS ============

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    await init_db()
    logger.info("Database initialized with Tortoise ORM")
    logger.info("OCPP Central System API started")
    logger.info("REST API available at: /api/")
    logger.info("API Documentation available at: /docs")
    logger.info("OCPP WebSocket available at: /ocpp/{charge_point_id}")

@app.on_event("shutdown")
async def shutdown_event():
    """Close database connections on shutdown"""
    await close_db()
    logger.info("Database connections closed")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)