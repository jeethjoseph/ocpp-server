# main.py
import os
import asyncio
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
    update_charger_status,
    update_charger_heartbeat
)
from models import OCPPLog
from redis_manager import redis_manager

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16 import call, call_result
from ocpp.routing import on
from starlette.websockets import WebSocketState

import logging
import json

# Import routers
from routers import stations, chargers, transactions, auth, webhooks, users, public_stations, logs

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Back to INFO level after debugging
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ocpp-server")

# FastAPI app
app = FastAPI(
    title="OCPP Central System API", 
    version="0.1.0",
    description="EV Charging Station Management System with OCPP 1.6 support"
)

# Configure CORS - Allow frontend domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",           # Local development
        "http://127.0.0.1:3000",           # Local development
        "https://powerlync.com",            # Production frontend
        "https://www.powerlync.com",        # Production frontend (www)
        "https://ocpp-frontend-mu.vercel.app",  # Legacy Vercel frontend
        "https://lyncpower.com",            # Backend domain (for testing)
        "https://www.lyncpower.com"         # Backend domain (www)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware to handle OPTIONS (CORS preflight) requests
# This ensures OPTIONS requests don't hit authentication middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class OptionsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Handle OPTIONS requests immediately with proper CORS headers
        if request.method == "OPTIONS":
            # Get origin from request
            origin = request.headers.get("origin", "*")

            # Check if origin is allowed (optional security check)
            allowed_origins = [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "https://powerlync.com",
                "https://www.powerlync.com",
                "https://ocpp-frontend-mu.vercel.app",
                "https://lyncpower.com",
                "https://www.lyncpower.com"
            ]

            # If origin is in allowed list, use it; otherwise use first allowed origin
            if origin not in allowed_origins:
                origin = allowed_origins[0] if allowed_origins else "*"

            headers = {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
                "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, Origin, User-Agent",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Max-Age": "3600",  # Cache preflight for 1 hour
            }

            return Response(status_code=200, headers=headers)

        # For non-OPTIONS requests, continue normally
        response = await call_next(request)
        return response

app.add_middleware(OptionsMiddleware)

# Store connected charge points with metadata (now moved to Redis)
# Keep this for backward compatibility but will be deprecated
connected_charge_points: Dict[str, Dict] = {}

# Helper to determine if a WebSocket is currently in CONNECTED state (avoids magic numbers)
def _is_ws_connected(ws: WebSocket) -> bool:
    try:
        return ws is not None and ws.client_state == WebSocketState.CONNECTED
    except Exception:
        return False

# Global cleanup task
cleanup_task = None

# Define a ChargePoint class using python-ocpp
class ChargePoint(OcppChargePoint):
    @on('BootNotification')
    async def on_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
        logger.info(f"BootNotification from {self.id}: vendor={charge_point_vendor}, model={charge_point_model}")
        
        # Don't automatically fail transactions on reboot - let StatusNotification handle actual status
        # The charger will send StatusNotification after boot which will determine if transactions should fail
        
        # Don't assume status - wait for StatusNotification from charge point
        
        return call_result.BootNotification(
            current_time=datetime.datetime.utcnow().isoformat() + "Z",
            interval=300,
            status="Accepted"
        )

    @on('Heartbeat')
    async def on_heartbeat(self, **kwargs):
        # Update last heartbeat timestamp for this charge point
        current_time = datetime.datetime.now(datetime.timezone.utc)
        if self.id in connected_charge_points:
            connected_charge_points[self.id]["last_heartbeat"] = current_time
        logger.info(f"Received OCPP Heartbeat from {self.id}")
        # Only update heartbeat time, don't assume status - wait for StatusNotification
        await update_charger_heartbeat(self.id)
        
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
            
            # Check if status indicates not charging and fail ongoing transactions
            # Charging states: Charging, Preparing, SuspendedEVSE, SuspendedEV, Finishing
            charging_states = {"Charging", "Preparing", "SuspendedEVSE", "SuspendedEV", "Finishing"}
            
            if status not in charging_states:
                from models import Transaction, TransactionStatusEnum, MeterValue
                try:
                    ongoing_transactions = await Transaction.filter(
                        charger__charge_point_string_id=self.id,
                        transaction_status__in=[
                            TransactionStatusEnum.RUNNING,
                            TransactionStatusEnum.STARTED,
                            TransactionStatusEnum.PENDING_START,
                            TransactionStatusEnum.PENDING_STOP
                        ]
                    ).all()
                    
                    if ongoing_transactions:
                        logger.info(f"Status {status} indicates not charging - found {len(ongoing_transactions)} ongoing transactions for charger {self.id} - marking as FAILED")
                        from services.wallet_service import WalletService
                        
                        for transaction in ongoing_transactions:
                            # Calculate energy consumption from latest meter value if not already set
                            if transaction.end_meter_kwh is None:
                                latest_meter_value = await MeterValue.filter(
                                    transaction_id=transaction.id
                                ).order_by("-created_at").first()
                                
                                if latest_meter_value:
                                    transaction.end_meter_kwh = latest_meter_value.reading_kwh
                                    transaction.energy_consumed_kwh = transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
                                    logger.info(f"Calculated energy consumption for failed transaction {transaction.id}: {transaction.energy_consumed_kwh} kWh (from latest meter value: {latest_meter_value.reading_kwh} kWh)")
                                else:
                                    logger.warning(f"No meter values found for failed transaction {transaction.id} - cannot calculate energy consumption")
                            
                            transaction.transaction_status = TransactionStatusEnum.FAILED
                            transaction.stop_reason = f"STATUS_CHANGE_TO_{status}"
                            transaction.end_time = datetime.datetime.now(datetime.timezone.utc)
                            await transaction.save()
                            logger.info(f"Marked transaction {transaction.id} as FAILED due to status change to {status}")
                            
                            # Process billing if we have energy consumption data
                            if transaction.energy_consumed_kwh is not None and transaction.energy_consumed_kwh > 0:
                                try:
                                    success, message, billing_amount = await WalletService.process_transaction_billing(transaction.id)
                                    if success:
                                        if billing_amount and billing_amount > 0:
                                            logger.info(f"💰 Billing successful for failed transaction {transaction.id}: ${billing_amount}")
                                        else:
                                            logger.info(f"💰 {message} for failed transaction {transaction.id}")
                                    else:
                                        logger.warning(f"💰 Billing failed for failed transaction {transaction.id}: {message}")
                                except Exception as billing_error:
                                    logger.error(f"💰 Unexpected error in billing for failed transaction {transaction.id}: {billing_error}", exc_info=True)
                                    await Transaction.filter(id=transaction.id).update(
                                        transaction_status=TransactionStatusEnum.BILLING_FAILED
                                    )
                            else:
                                logger.warning(f"💰 Cannot bill failed transaction {transaction.id} - no energy consumed (energy: {transaction.energy_consumed_kwh} kWh)")
                    else:
                        logger.debug(f"Status {status} indicates not charging but no ongoing transactions found for charger {self.id}")
                        
                except Exception as e:
                    logger.error(f"Error checking ongoing transactions for {self.id} on status change to {status}: {e}", exc_info=True)
            
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
            
            # Look up user by RFID card ID
            user = await User.filter(rfid_card_id=id_tag).first()
            
            if not user:
                logger.error(f"OCPP StartTransaction: No user found with rfid_card_id '{id_tag}', rejecting transaction")
                return call_result.StartTransaction(
                    transaction_id=0,
                    id_tag_info={"status": "Invalid"}
                )
            
            logger.info(f"OCPP StartTransaction: Found user by rfid_card_id '{id_tag}': {user.email}")
            
            if not user.is_active:
                logger.error(f"OCPP StartTransaction: User {user.email} is deactivated")
                return call_result.StartTransaction(
                    transaction_id=0,
                    id_tag_info={"status": "Blocked"}
                )
            
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
                transaction_status=TransactionStatusEnum.RUNNING  # Changed from STARTED to RUNNING
            )
            
            logger.info(f"🔋 Created transaction {transaction.id} for charger {self.id} with status RUNNING")
            
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
        logger.info(f"🛑 StopTransaction from {self.id}: transaction_id={transaction_id}, meter_stop={meter_stop}")
        
        from models import Transaction, TransactionStatusEnum
        from services.wallet_service import WalletService
        import datetime
        
        try:
            # Get transaction from database
            transaction = await Transaction.filter(id=transaction_id).first()
            if not transaction:
                logger.error(f"🛑 ❌ Transaction {transaction_id} not found")
                return call_result.StopTransaction(
                    id_tag_info={"status": "Invalid"}
                )
            
            logger.info(f"🛑 Transaction {transaction_id} status before stop: {transaction.transaction_status}")
            
            # Update transaction with end values
            transaction.end_meter_kwh = float(meter_stop) / 1000  # Convert Wh to kWh
            transaction.energy_consumed_kwh = transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
            transaction.end_time = datetime.datetime.now(datetime.timezone.utc)
            transaction.transaction_status = TransactionStatusEnum.COMPLETED
            transaction.stop_reason = kwargs.get('reason', 'Remote')
            
            await transaction.save()
            
            logger.info(f"🛑 ✅ Transaction stopped {transaction_id}: {transaction.energy_consumed_kwh} kWh consumed")
            
            # Process wallet billing asynchronously
            try:
                success, message, billing_amount = await WalletService.process_transaction_billing(transaction_id)
                if success:
                    if billing_amount and billing_amount > 0:
                        logger.info(f"💰 Billing successful for transaction {transaction_id}: ₹{billing_amount}")
                    else:
                        logger.info(f"💰 {message} for transaction {transaction_id}")
                else:
                    logger.warning(f"💰 Billing failed for transaction {transaction_id}: {message}")
            except Exception as billing_error:
                logger.error(f"💰 Unexpected error in billing for transaction {transaction_id}: {billing_error}", exc_info=True)
                # Mark transaction as billing failed
                await Transaction.filter(id=transaction_id).update(
                    transaction_status=TransactionStatusEnum.BILLING_FAILED
                )
            
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
        logger.info(f"🔋 MeterValues from {self.id}: connector_id={connector_id}, transaction_id={transaction_id}")
        logger.debug(f"🔋 Raw meter_value data: {meter_value}")
        
        from models import Transaction, MeterValue
        
        try:
            if not transaction_id:
                logger.warning(f"🔋 ❌ No transaction_id provided for meter values from {self.id} - DISCARDING")
                return call_result.MeterValues()
                
            # Get transaction from database
            logger.debug(f"🔋 Looking up transaction {transaction_id} in database...")
            transaction = await Transaction.filter(id=transaction_id).prefetch_related('charger').first()
            if not transaction:
                logger.error(f"🔋 ❌ Transaction {transaction_id} not found in database for meter values from {self.id}")
                # Let's also check what transactions exist
                all_transactions = await Transaction.all().values('id', 'transaction_status')
                logger.error(f"🔋 Available transactions: {all_transactions}")
                return call_result.MeterValues()
                
            logger.debug(f"🔋 ✅ Found transaction {transaction_id} for charger {transaction.charger.charge_point_string_id}")
            
            # Process meter values - group all measurands by timestamp
            meter_records_created = 0
            for i, meter_reading in enumerate(meter_value):
                timestamp = meter_reading.get('timestamp')
                # Handle both camelCase and snake_case for OCPP compatibility
                sampled_values = meter_reading.get('sampledValue', meter_reading.get('sampled_value', []))
                logger.debug(f"🔋 Processing meter reading {i+1}: timestamp={timestamp}, samples={len(sampled_values)}")
                
                # Collect all measurand values for this timestamp
                meter_data = {
                    'reading_kwh': None,
                    'current': None,
                    'voltage': None,
                    'power_kw': None
                }
                
                for j, sample in enumerate(sampled_values):
                    value = sample.get('value')
                    measurand = sample.get('measurand', 'Energy.Active.Import.Register')
                    unit = sample.get('unit', 'Wh')
                    logger.debug(f"🔋   Sample {j+1}: {measurand}={value} {unit}")
                    
                    if not value:
                        logger.warning(f"🔋   ⚠️ Empty value for {measurand} - skipping")
                        continue
                        
                    try:
                        if measurand == 'Energy.Active.Import.Register':
                            # Store energy reading
                            reading_kwh = float(value)
                            if unit == 'Wh':
                                reading_kwh = reading_kwh / 1000  # Convert Wh to kWh
                            meter_data['reading_kwh'] = reading_kwh
                            logger.debug(f"🔋   ✅ Energy: {reading_kwh} kWh")
                            
                        elif measurand == 'Current.Import':
                            # Store current reading
                            current = float(value)
                            if unit == 'mA':
                                current = current / 1000  # Convert mA to A
                            meter_data['current'] = current
                            logger.debug(f"🔋   ✅ Current: {current} A")
                            
                        elif measurand == 'Voltage':
                            # Store voltage reading
                            voltage = float(value)
                            if unit == 'mV':
                                voltage = voltage / 1000  # Convert mV to V
                            meter_data['voltage'] = voltage
                            logger.debug(f"🔋   ✅ Voltage: {voltage} V")
                            
                        elif measurand == 'Power.Active.Import':
                            # Store power reading
                            power_kw = float(value)
                            if unit == 'W':
                                power_kw = power_kw / 1000  # Convert W to kW
                            meter_data['power_kw'] = power_kw
                            logger.debug(f"🔋   ✅ Power: {power_kw} kW")
                        else:
                            logger.debug(f"🔋   ⚠️ Unknown measurand: {measurand} - ignoring")
                            
                    except (ValueError, TypeError) as e:
                        logger.error(f"🔋   ❌ Error parsing {measurand} value '{value}': {e}")
                        continue
                
                # Only create meter value record if we have at least energy reading
                if meter_data['reading_kwh'] is not None:
                    try:
                        logger.debug(f"🔋 💾 Creating MeterValue record in database...")
                        meter_record = await MeterValue.create(
                            transaction=transaction,
                            reading_kwh=meter_data['reading_kwh'],
                            current=meter_data['current'],
                            voltage=meter_data['voltage'],
                            power_kw=meter_data['power_kw']
                        )
                        meter_records_created += 1
                        
                        logger.info(f"🔋 ✅ STORED meter value ID={meter_record.id} for transaction {transaction_id}: "
                                  f"Energy={meter_data['reading_kwh']} kWh, "
                                  f"Current={meter_data['current']} A, "
                                  f"Voltage={meter_data['voltage']} V, "
                                  f"Power={meter_data['power_kw']} kW")
                    except Exception as db_error:
                        logger.error(f"🔋 ❌ DATABASE ERROR creating meter value: {db_error}", exc_info=True)
                        # Continue processing other readings even if one fails
                        
                else:
                    logger.warning(f"🔋 ⚠️ No energy reading found in meter data - skipping record")
                    logger.debug(f"🔋 Meter data was: {meter_data}")
            
            logger.info(f"🔋 📊 Summary: Created {meter_records_created} meter value records for transaction {transaction_id}")
            return call_result.MeterValues()
            
        except Exception as e:
            logger.error(f"🔋 ❌ FATAL ERROR processing meter values for {self.id}: {e}", exc_info=True)
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
        
        # Ghost session detection - check if this charge point is in our connected list
        if self.charge_point_id not in connected_charge_points:
            logger.warning(f"[DISCONNECT] Ghost session detected for {self.charge_point_id} - message received but not in connected list")
            
            # Force close the ghost connection
            try:
                await self.websocket.close(code=1008, reason="Ghost session cleanup")
                logger.info(f"[DISCONNECT] Closed ghost session WebSocket for {self.charge_point_id}")
            except Exception as e:
                logger.warning(f"[DISCONNECT] Error closing ghost session WebSocket for {self.charge_point_id}: {e}")
            
            # Don't process the message or log it - use WebSocketDisconnect to follow existing except path
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect(code=1008)
        
        # Update last_seen for ANY incoming message from valid connections
        connected_charge_points[self.charge_point_id]["last_seen"] = datetime.datetime.now(datetime.timezone.utc)
        
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
    
    # Validate WebSocket connection is still alive (enum-based, no magic number)
    try:
        if not _is_ws_connected(websocket):
            state_name = getattr(websocket.client_state, "name", str(getattr(websocket, "client_state", "unknown")))
            logger.warning(f"WebSocket not connected for {charge_point_id} (state={state_name})")
            await force_disconnect(charge_point_id, f"WebSocket not connected (state={state_name})")
            return False, "Connection lost"
    except Exception as e:
        logger.warning(f"WebSocket validation failed for {charge_point_id}: {e}")
        await force_disconnect(charge_point_id, f"WebSocket validation failed: {e}")
        return False, "Connection lost"

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

# ============ Connection Management ============

# Cleanup coordination locks to prevent race conditions
cleanup_locks = {}  # Dict[str, asyncio.Lock]

# Recently disconnected tombstone to prevent immediate reconnection races
recently_disconnected = {}  # Dict[str, datetime]

async def force_disconnect(charge_point_id: str, reason: str):
    """Force complete disconnection of a charge point with proper cleanup"""
    
    # Ensure only one cleanup per charger at a time
    if charge_point_id not in cleanup_locks:
        cleanup_locks[charge_point_id] = asyncio.Lock()
        
    async with cleanup_locks[charge_point_id]:
        logger.info(f"[DISCONNECT] Starting force disconnect for {charge_point_id}: {reason}")
        
        connection_data = connected_charge_points.get(charge_point_id)
        if connection_data:
            # 1. Cancel heartbeat task
            heartbeat_task = connection_data.get("heartbeat_task")
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
                logger.info(f"[DISCONNECT] Cancelled heartbeat task for {charge_point_id}")
                
            # 2. Close WebSocket with proper code (if not already closed)
            websocket = connection_data.get("websocket")
            if websocket:
                try:
                    if _is_ws_connected(websocket):
                        await websocket.close(code=1001, reason=f"Server cleanup: {reason}")
                        logger.info(f"[DISCONNECT] Sent WebSocket close frame to {charge_point_id}: {reason}")
                    else:
                        state_name = getattr(websocket.client_state, "name", str(getattr(websocket, "client_state", "unknown")))
                        logger.info(f"[DISCONNECT] WebSocket for {charge_point_id} already closed (state={state_name})")
                except Exception as e:
                    logger.warning(f"[DISCONNECT] Error closing WebSocket for {charge_point_id}: {e}")
                    if hasattr(websocket, '_transport') and websocket._transport:
                        websocket._transport.close()
                        logger.info(f"[DISCONNECT] Forced TCP closure for {charge_point_id}")
                        
        # 3. Atomic state cleanup
        if charge_point_id in connected_charge_points:
            del connected_charge_points[charge_point_id]
        await redis_manager.remove_connected_charger(charge_point_id)
        
        # 4. Add tombstone to prevent immediate reconnection races
        from datetime import timedelta
        recently_disconnected[charge_point_id] = datetime.datetime.now(datetime.timezone.utc) + timedelta(milliseconds=100)
        
        # 5. Clean up old tombstones
        current_time = datetime.datetime.now(datetime.timezone.utc)
        expired_tombstones = [cp_id for cp_id, expire_time in recently_disconnected.items() if current_time > expire_time]
        for cp_id in expired_tombstones:
            del recently_disconnected[cp_id]
        
        # 6. Clean up the lock for this connection to prevent memory leak
        cleanup_locks.pop(charge_point_id, None)
        
        logger.warning(f"[DISCONNECT] Force disconnected {charge_point_id}: {reason}")

async def cleanup_dead_connection(charge_point_id: str):
    """Legacy cleanup function - redirects to force_disconnect"""
    await force_disconnect(charge_point_id, "Dead connection detected")

async def heartbeat_monitor(charge_point_id: str, websocket: WebSocket):
    """Monitor OCPP Heartbeat message to check device liveness."""
    HEARTBEAT_TIMEOUT = 90  # seconds - disconnect if no heartbeat for 90 seconds

    try:
        while True:
            await asyncio.sleep(15)  # Check every 15 seconds
            try:
                now = datetime.datetime.now(datetime.timezone.utc)
                last_heartbeat = None
                if charge_point_id in connected_charge_points:
                    last_heartbeat = connected_charge_points[charge_point_id].get("last_heartbeat")
                if last_heartbeat is None:
                    # No heartbeat received yet, use last_seen or connected_at
                    last_heartbeat = connected_charge_points[charge_point_id].get("last_seen") or connected_charge_points[charge_point_id].get("connected_at")
                if last_heartbeat is None or (now - last_heartbeat).total_seconds() > HEARTBEAT_TIMEOUT:
                    logger.warning(f"No OCPP Heartbeat from {charge_point_id} in {HEARTBEAT_TIMEOUT} seconds. Cleaning up.")
                    await force_disconnect(charge_point_id, f"Heartbeat timeout ({HEARTBEAT_TIMEOUT}s)")
                    break
                logger.info(f"Heartbeat monitor: {charge_point_id} last heartbeat {(now - last_heartbeat).total_seconds():.1f}s ago")
            except Exception as e:
                logger.warning(f"Heartbeat monitor error for {charge_point_id}: {e}")
                await force_disconnect(charge_point_id, f"Heartbeat monitor error: {e}")
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
            most_recent_times = {}  # Store per-connection most_recent for proper reason message
            
            # Find connections that haven't been seen for more than 5 minutes (300 seconds)
            # This should be longer than heartbeat timeout (90s) to avoid false positives
            for charge_point_id, connection_data in connected_charge_points.items():
                last_seen = connection_data.get("last_seen")
                last_heartbeat = connection_data.get("last_heartbeat")
                
                # Use the most recent of last_seen or last_heartbeat
                most_recent = max(
                    last_seen or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
                    last_heartbeat or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
                )
                most_recent_times[charge_point_id] = most_recent
                
                # Only mark as stale if no activity for 90 seconds (consistent with heartbeat timeout)
                if (current_time - most_recent).total_seconds() > 90:

                    stale_connections.append(charge_point_id)
                    logger.warning(f"Connection {charge_point_id} stale: last activity {(current_time - most_recent).total_seconds():.1f}s ago")
            
            # Clean up stale connections with proper reason message
            for charge_point_id in stale_connections:
                most_recent = most_recent_times[charge_point_id]
                inactive_seconds = (current_time - most_recent).total_seconds()
                logger.warning(f"Cleaning up stale connection: {charge_point_id}")
                await force_disconnect(charge_point_id, f"Stale connection (inactive for {inactive_seconds:.1f}s)")
                
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")

# ============ Include Routers ============
app.include_router(stations.router)
app.include_router(chargers.router)
app.include_router(transactions.router)
app.include_router(auth.router)
app.include_router(webhooks.router)
app.include_router(users.router)
app.include_router(public_stations.router)
app.include_router(logs.router)

# ============ OCPP WebSocket Endpoint ============
@app.websocket("/ocpp/{charge_point_id}")
async def ocpp_websocket(websocket: WebSocket, charge_point_id: str):
    """OCPP WebSocket endpoint for charge points"""
    logger.info(f"[CONNECTION ATTEMPT] {charge_point_id} attempting WebSocket connection")

    try:
        await websocket.accept()
        logger.info(f"[CONNECTION ATTEMPT] {charge_point_id} WebSocket handshake successful")
    except Exception as e:
        logger.error(f"[CONNECTION ATTEMPT] {charge_point_id} WebSocket handshake failed: {e}")
        return

    # Check for recent disconnection tombstone to prevent reconnection races
    current_time = datetime.datetime.now(datetime.timezone.utc)
    if charge_point_id in recently_disconnected:
        expire_time = recently_disconnected[charge_point_id]
        if current_time < expire_time:
            remaining_ms = (expire_time - current_time).total_seconds() * 1000
            logger.warning(f"[CONNECTION ATTEMPT] Rejecting immediate reconnection for {charge_point_id} - tombstone expires in {remaining_ms:.1f}ms")
            await websocket.close(code=1013, reason="Too soon after disconnect")
            return
        else:
            # Tombstone expired, remove it
            logger.info(f"[CONNECTION ATTEMPT] {charge_point_id} tombstone expired, allowing reconnection")
            del recently_disconnected[charge_point_id]

    # Validate charger before connecting
    is_valid, message = await validate_and_connect_charger(charge_point_id, connected_charge_points)
    if not is_valid:
        logger.warning(f"[CONNECTION ATTEMPT] Validation failed for {charge_point_id}: {message}")
        await websocket.close(code=1008, reason=message)
        return

    logger.info(f"[CONNECTION ATTEMPT] {charge_point_id} validation successful - establishing OCPP connection")

    ws_adapter = LoggingWebSocketAdapter(websocket, charge_point_id)
    cp = ChargePoint(charge_point_id, ws_adapter)
    
    # Start heartbeat monitor task
    heartbeat_task = asyncio.create_task(heartbeat_monitor(charge_point_id, websocket))
    
    # Store connection data with heartbeat task handle for proper cleanup
    connection_data = {
        "websocket": websocket,
        "cp": cp,
        "heartbeat_task": heartbeat_task,  # Store for cleanup
        "connected_at": datetime.datetime.now(datetime.timezone.utc),
        "last_seen": datetime.datetime.now(datetime.timezone.utc)
    }
    connected_charge_points[charge_point_id] = connection_data
    
    # Add to Redis
    await redis_manager.add_connected_charger(charge_point_id, connection_data)

    logger.info(f"[CONNECTION ATTEMPT] {charge_point_id} connection established successfully - starting OCPP message handling")

    try:
        await cp.start()
    except WebSocketDisconnect as e:
        logger.error(f"[DISCONNECT] Charge point {charge_point_id} disconnected naturally - WebSocket code: {getattr(e, 'code', 'unknown')}, reason: {getattr(e, 'reason', 'none')}")
        logger.error(f"[DISCONNECT] WebSocket state at disconnect: {getattr(websocket, 'client_state', 'unknown')}")
        logger.error(f"[DISCONNECT] Last seen: {connection_data.get('last_seen', 'never') if charge_point_id in connected_charge_points else 'connection not found'}")
        # Apply tombstone on natural disconnect and let finally handle cleanup
        await force_disconnect(charge_point_id, "Natural WebSocket disconnect")
        return  # Avoid double cleanup in finally
    except Exception as e:
        logger.error(f"[DISCONNECT] WebSocket error for {charge_point_id}: {e}", exc_info=True)
        logger.error(f"[DISCONNECT] WebSocket state at error: {getattr(websocket, 'client_state', 'unknown')}")
        logger.error(f"[DISCONNECT] Connection data at error: {connection_data if charge_point_id in connected_charge_points else 'connection not found'}")
    finally:
        # Use force_disconnect for proper cleanup if still connected
        if charge_point_id in connected_charge_points:
            await force_disconnect(charge_point_id, "WebSocket session ended")

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
    
    # Start billing retry service
    from services.billing_retry_service import start_billing_retry_service
    await start_billing_retry_service()
    
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
    
    # Stop billing retry service
    from services.billing_retry_service import stop_billing_retry_service
    await stop_billing_retry_service()
    
    await close_db()
    await redis_manager.disconnect()
    logger.info("Database and Redis connections closed")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)