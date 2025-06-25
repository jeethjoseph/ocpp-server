# main.py
import os
import asyncio
import datetime
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from websockets.exceptions import ConnectionClosed

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
from redis_manager import redis_manager

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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000","https://ocpp-frontend-mu.vercel.app" ],  # Frontend origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store connected charge points with metadata (now moved to Redis)
# Keep this for backward compatibility but will be deprecated
connected_charge_points: Dict[str, Dict] = {}

# Global cleanup task
cleanup_task = None

# Define a ChargePoint class using python-ocpp
class ChargePoint(OcppChargePoint):
    @on('BootNotification')
    async def on_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
        logger.info(f"BootNotification from {self.id}: vendor={charge_point_vendor}, model={charge_point_model}")
        # Update charger status in database
        await update_charger_status(self.id, "Available")
        
        return call_result.BootNotification(
            current_time=datetime.datetime.utcnow().isoformat() + "Z",
            interval=300,
            status="Accepted"
        )

    @on('Heartbeat')
    async def on_heartbeat(self, **kwargs):
        logger.info(f"Heartbeat from {self.id}")
        # Update charger status and heartbeat time in database
        await update_charger_status(self.id, "Available")
        
        return call_result.Heartbeat(
            current_time=datetime.datetime.utcnow().isoformat() + "Z"
        )
    
    @on('StatusNotification')
    async def on_status_notification(self, connector_id, status, error_code=None, info=None, **kwargs):
        logger.info(f"StatusNotification from {self.id}: connector_id={connector_id}, status={status}, error_code={error_code}, info={info}")
        
        try:
            # Update charger status in database
            result = await update_charger_status(self.id, status)
            if not result:
                logger.warning(f"Failed to update status for charger {self.id} - charger not found in database")
            else:
                logger.info(f"Successfully updated charger {self.id} status to {status}")
            
            return call_result.StatusNotification()
            
        except Exception as e:
            logger.error(f"Error handling StatusNotification for {self.id}: {e}", exc_info=True)
            # Return success anyway to avoid blocking the charger
            return call_result.StatusNotification()

    @on('StartTransaction')
    async def on_start_transaction(self, connector_id, id_tag, meter_start, timestamp, **kwargs):
        logger.info(f"StartTransaction from {self.id}: connector_id={connector_id}, id_tag={id_tag}, meter_start={meter_start}")
        
        from models import Transaction, User, VehicleProfile, Charger, TransactionStatusEnum
        
        try:
            # Get charger from database
            charger = await Charger.filter(charge_point_string_id=self.id).first()
            if not charger:
                logger.error(f"Charger {self.id} not found in database")
                return call_result.StartTransaction(
                    transaction_id=0,
                    id_tag_info={"status": "Invalid"}
                )
            
            # For now, create a test user if id_tag doesn't exist
            # In production, you'd lookup user by id_tag
            user, _ = await User.get_or_create(phone_number=f"user_{id_tag}")
            
            # Get or create a vehicle profile for the user
            vehicle, _ = await VehicleProfile.get_or_create(
                user=user,
                defaults={"make": "Unknown", "model": "Unknown"}
            )
            
            # Create transaction record
            transaction = await Transaction.create(
                user=user,
                charger=charger,
                vehicle=vehicle,
                start_meter_kwh=float(meter_start) / 1000,  # Convert Wh to kWh
                transaction_status=TransactionStatusEnum.STARTED
            )
            
            logger.info(f"Created transaction {transaction.id} for charger {self.id}")
            
            return call_result.StartTransaction(
                transaction_id=transaction.id,
                id_tag_info={"status": "Accepted"}
            )
            
        except Exception as e:
            logger.error(f"Error creating transaction for {self.id}: {e}", exc_info=True)
            return call_result.StartTransaction(
                transaction_id=0,
                id_tag_info={"status": "Invalid"}
            )

    @on('StopTransaction')
    async def on_stop_transaction(self, transaction_id, meter_stop, timestamp, **kwargs):
        logger.info(f"StopTransaction from {self.id}: transaction_id={transaction_id}, meter_stop={meter_stop}")
        
        from models import Transaction, TransactionStatusEnum
        import datetime
        
        try:
            # Get transaction from database
            transaction = await Transaction.filter(id=transaction_id).first()
            if not transaction:
                logger.error(f"Transaction {transaction_id} not found")
                return call_result.StopTransaction(
                    id_tag_info={"status": "Invalid"}
                )
            
            # Update transaction with end values
            transaction.end_meter_kwh = float(meter_stop) / 1000  # Convert Wh to kWh
            transaction.energy_consumed_kwh = transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
            transaction.end_time = datetime.datetime.now(datetime.timezone.utc)
            transaction.transaction_status = TransactionStatusEnum.COMPLETED
            transaction.stop_reason = kwargs.get('reason', 'Remote')
            
            await transaction.save()
            
            logger.info(f"Completed transaction {transaction_id}: {transaction.energy_consumed_kwh} kWh consumed")
            
            return call_result.StopTransaction(
                id_tag_info={"status": "Accepted"}
            )
            
        except Exception as e:
            logger.error(f"Error stopping transaction {transaction_id}: {e}", exc_info=True)
            return call_result.StopTransaction(
                id_tag_info={"status": "Invalid"}
            )

    @on('MeterValues')
    async def on_meter_values(self, connector_id, meter_value, transaction_id=None, **kwargs):
        logger.info(f"MeterValues from {self.id}: connector_id={connector_id}, transaction_id={transaction_id}")
        
        from models import Transaction, MeterValue
        
        try:
            if transaction_id:
                # Get transaction from database
                transaction = await Transaction.filter(id=transaction_id).first()
                if not transaction:
                    logger.warning(f"Transaction {transaction_id} not found for meter values")
                    return call_result.MeterValues()
                
                # Process meter values
                for meter_reading in meter_value:
                    timestamp = meter_reading.get('timestamp')
                    sampled_values = meter_reading.get('sampledValue', [])
                    
                    for sample in sampled_values:
                        value = sample.get('value')
                        measurand = sample.get('measurand', 'Energy.Active.Import.Register')
                        unit = sample.get('unit', 'Wh')
                        
                        if measurand == 'Energy.Active.Import.Register' and value:
                            # Store energy reading
                            reading_kwh = float(value)
                            if unit == 'Wh':
                                reading_kwh = reading_kwh / 1000  # Convert Wh to kWh
                            
                            await MeterValue.create(
                                transaction=transaction,
                                reading_kwh=reading_kwh
                            )
                            
                            logger.info(f"Stored meter value: {reading_kwh} kWh for transaction {transaction_id}")
                        
                        elif measurand == 'Current.Import' and value:
                            # Update current reading (could store in separate field or latest meter value)
                            pass
                        
                        elif measurand == 'Voltage' and value:
                            # Update voltage reading
                            pass
                        
                        elif measurand == 'Power.Active.Import' and value:
                            # Update power reading
                            power_kw = float(value)
                            if unit == 'W':
                                power_kw = power_kw / 1000  # Convert W to kW
                            
                            # Store power in the latest meter value (you could enhance this)
                            latest_meter = await MeterValue.filter(transaction=transaction).order_by('-created_at').first()
                            if latest_meter:
                                latest_meter.power_kw = power_kw
                                await latest_meter.save()
            
            return call_result.MeterValues()
            
        except Exception as e:
            logger.error(f"Error processing meter values for {self.id}: {e}", exc_info=True)
            return call_result.MeterValues()

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
    # Check Redis for connection status
    is_connected = await redis_manager.is_charger_connected(charge_point_id)
    if not is_connected:
        logger.warning(f"Charge point {charge_point_id} not connected")
        return False, f"Charge point {charge_point_id} not connected"

    # Get connection data from in-memory dict
    connection_data = connected_charge_points.get(charge_point_id)
    if not connection_data:
        logger.warning(f"ChargePoint instance for {charge_point_id} not found")
        return False, f"ChargePoint instance for {charge_point_id} not found"
    
    cp = connection_data.get("cp")
    websocket = connection_data.get("websocket")
    
    if not cp or not websocket:
        logger.warning(f"Invalid connection data for {charge_point_id}")
        return False, f"Invalid connection data for {charge_point_id}"
    
    # Validate WebSocket connection is still alive
    try:
        if websocket.client_state.value != 1:  # 1 = CONNECTED
            logger.warning(f"WebSocket not connected for {charge_point_id}")
            await cleanup_dead_connection(charge_point_id)
            return False, f"Connection lost for {charge_point_id}"
    except Exception as e:
        logger.warning(f"WebSocket validation failed for {charge_point_id}: {e}")
        await cleanup_dead_connection(charge_point_id)
        return False, f"Connection lost for {charge_point_id}"

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

# ============ Heartbeat Monitor ============
async def cleanup_dead_connection(charge_point_id: str):
    """Clean up a dead connection from both memory and Redis"""
    if charge_point_id in connected_charge_points:
        del connected_charge_points[charge_point_id]
    await redis_manager.remove_connected_charger(charge_point_id)
    logger.warning(f"Dead connection cleaned up for charge point {charge_point_id}")

async def heartbeat_monitor(charge_point_id: str, websocket: WebSocket):
    """Monitor WebSocket connection health by checking client state"""
    try:
        while True:
            await asyncio.sleep(30)  # Check every 30 seconds
            try:
                # Check if WebSocket is still connected
                logger.debug(f"Checking heartbeat for {charge_point_id}")
                if websocket.client_state.value != 1:  # 1 = CONNECTED
                    logger.warning(f"WebSocket disconnected for {charge_point_id}")
                    await cleanup_dead_connection(charge_point_id)
                    break
                
                # Update last seen timestamp
                if charge_point_id in connected_charge_points:
                    connected_charge_points[charge_point_id]["last_seen"] = datetime.datetime.now(datetime.timezone.utc)
                logger.info(f"Heartbeat successful for {charge_point_id}")    
            except Exception as e:
                logger.warning(f"Heartbeat failed for {charge_point_id}: {e}")
                await cleanup_dead_connection(charge_point_id)
                break
                
    except asyncio.CancelledError:
        # Task was cancelled, normal shutdown
        pass
    except Exception as e:
        logger.error(f"Heartbeat monitor error for {charge_point_id}: {e}")

async def periodic_cleanup():
    """Periodic cleanup of stale connections every 5 minutes"""
    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes
            logger.info("Running periodic cleanup of stale connections")
            
            current_time = datetime.datetime.now(datetime.timezone.utc)
            stale_connections = []
            
            # Find connections that haven't been seen for more than 2 minutes
            for charge_point_id, connection_data in connected_charge_points.items():
                last_seen = connection_data.get("last_seen")
                if last_seen and (current_time - last_seen).total_seconds() > 120:
                    stale_connections.append(charge_point_id)
            
            # Clean up stale connections
            for charge_point_id in stale_connections:
                logger.warning(f"Cleaning up stale connection: {charge_point_id}")
                await cleanup_dead_connection(charge_point_id)
                
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")

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
    
    # Store connection data in both places during transition
    connection_data = {
        "websocket": websocket,
        "cp": cp,
        "connected_at": datetime.datetime.now(datetime.timezone.utc),
        "last_seen": datetime.datetime.now(datetime.timezone.utc)
    }
    connected_charge_points[charge_point_id] = connection_data
    
    # Add to Redis
    await redis_manager.add_connected_charger(charge_point_id, connection_data)

    # Start heartbeat monitor
    heartbeat_task = asyncio.create_task(heartbeat_monitor(charge_point_id, websocket))
    
    try:
        await cp.start()
    except WebSocketDisconnect:
        logger.error(f"Charge point {charge_point_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error for {charge_point_id}: {e}", exc_info=True)
    finally:
        # Cancel heartbeat monitor
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
            
        # Remove from both in-memory and Redis
        if charge_point_id in connected_charge_points:
            del connected_charge_points[charge_point_id]
        await redis_manager.remove_connected_charger(charge_point_id)
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
async def get_connected_charge_points():
    """Get list of all connected charge points"""  
    from models import Charger
    charge_points = []
    # Get from Redis
    connected_charger_ids = await redis_manager.get_all_connected_chargers()
    
    for cp_id in connected_charger_ids:
        connected_at = await redis_manager.get_charger_connected_at(cp_id)
        # Get heartbeat info from database
        charger = await Charger.filter(charge_point_string_id=cp_id).first()
        
        if connected_at and charger:
            charge_points.append(ChargePointStatus(
                charge_point_id=cp_id,
                connected_at=connected_at,
                last_seen=charger.last_heart_beat_time or connected_at,
                connected=True  # If it's in Redis, it's connected
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
    """Initialize database and Redis on startup"""
    global cleanup_task
    await init_db()
    await redis_manager.connect()
    
    # Start periodic cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    logger.info("Database initialized with Tortoise ORM")
    logger.info("Redis connection established")
    logger.info("Periodic cleanup task started")
    logger.info("OCPP Central System API started")
    logger.info("REST API available at: /api/")
    logger.info("API Documentation available at: /docs")
    logger.info("OCPP WebSocket available at: /ocpp/{charge_point_id}")

@app.on_event("shutdown")
async def shutdown_event():
    """Close database and Redis connections on shutdown"""
    global cleanup_task
    
    # Cancel cleanup task
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
    
    await close_db()
    await redis_manager.disconnect()
    logger.info("Database and Redis connections closed")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)