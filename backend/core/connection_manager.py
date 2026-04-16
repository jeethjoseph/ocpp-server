"""
Connection management for OCPP charge points.

Manages WebSocket connections, heartbeat monitoring, cleanup of stale
connections, and provides the send_ocpp_request interface used by routers.
"""
import asyncio
import datetime
import json
import logging
import os
from datetime import timedelta
from typing import Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ocpp.v16 import call
from redis_manager import redis_manager
from crud import log_message, log_audit_event
from services.monitoring_service import OCPPMetrics, SentryHelper
from utils import safe_create_task

logger = logging.getLogger("ocpp-server")

OCPP_TIMEOUT = int(os.environ.get("OCPP_TIMEOUT", "120"))


class ConnectionManager:
    """
    Singleton that owns all charge point connection state.

    Follows the same pattern as RedisConnectionManager in redis_manager.py:
    instantiated at module level, imported by consumers as
    ``from core.connection_manager import connection_manager``.
    """

    def __init__(self):
        self.connected_charge_points: Dict[str, Dict] = {}
        self._cleanup_locks: Dict[str, asyncio.Lock] = {}
        self._recently_disconnected: Dict[str, datetime.datetime] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._on_disconnect_callbacks: list = []

    def register_on_disconnect(self, callback):
        """Register an async callback to fire on charger disconnect.

        Callback signature: async def callback(charge_point_id: str) -> None
        """
        self._on_disconnect_callbacks.append(callback)

    # --- helpers ---

    @staticmethod
    def is_ws_connected(ws: WebSocket) -> bool:
        """Check if a WebSocket is currently in CONNECTED state."""
        try:
            return ws is not None and ws.client_state == WebSocketState.CONNECTED
        except Exception:
            return False

    def check_tombstone(self, charge_point_id: str) -> Optional[float]:
        """Return remaining ms if a tombstone is active, else None (cleans up expired)."""
        if charge_point_id not in self._recently_disconnected:
            return None
        current_time = datetime.datetime.now(datetime.timezone.utc)
        expire_time = self._recently_disconnected[charge_point_id]
        if current_time < expire_time:
            return (expire_time - current_time).total_seconds() * 1000
        else:
            del self._recently_disconnected[charge_point_id]
            return None

    # --- core lifecycle ---

    async def force_disconnect(self, charge_point_id: str, reason: str):
        """Force complete disconnection of a charge point with proper cleanup."""
        if charge_point_id not in self._cleanup_locks:
            self._cleanup_locks[charge_point_id] = asyncio.Lock()

        async with self._cleanup_locks[charge_point_id]:
            logger.info(f"[DISCONNECT] Starting force disconnect for {charge_point_id}: {reason}")

            connection_data = self.connected_charge_points.get(charge_point_id)
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
                        if self.is_ws_connected(websocket):
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
            if charge_point_id in self.connected_charge_points:
                del self.connected_charge_points[charge_point_id]
            await redis_manager.remove_connected_charger(charge_point_id)

            # 4. Add tombstone to prevent immediate reconnection races
            self._recently_disconnected[charge_point_id] = (
                datetime.datetime.now(datetime.timezone.utc) + timedelta(milliseconds=100)
            )

            # 5. Clean up old tombstones
            current_time = datetime.datetime.now(datetime.timezone.utc)
            expired = [cp_id for cp_id, exp in self._recently_disconnected.items() if current_time > exp]
            for cp_id in expired:
                del self._recently_disconnected[cp_id]

            # 6. Clean up the lock for this connection to prevent memory leak
            self._cleanup_locks.pop(charge_point_id, None)

            logger.warning(f"[DISCONNECT] Force disconnected {charge_point_id}: {reason}")

            # 7. Fire disconnect callbacks (e.g. suspend active transactions)
            for cb in self._on_disconnect_callbacks:
                safe_create_task(cb(charge_point_id))

            safe_create_task(log_audit_event(
                action="charger.disconnected",
                entity_type="charger",
                entity_id=charge_point_id,
                actor_type="system",
                changes={"reason": reason},
            ))

            await OCPPMetrics.record_active_connections(len(self.connected_charge_points))

    async def cleanup_dead_connection(self, charge_point_id: str):
        """Legacy cleanup function - redirects to force_disconnect."""
        await self.force_disconnect(charge_point_id, "Dead connection detected")

    # --- heartbeat & periodic cleanup ---

    async def heartbeat_monitor(self, charge_point_id: str, websocket: WebSocket):
        """Monitor OCPP activity to check device liveness."""

        try:
            while True:
                await asyncio.sleep(15)
                try:
                    now = datetime.datetime.now(datetime.timezone.utc)
                    last_activity = None
                    if charge_point_id in self.connected_charge_points:
                        last_activity = (
                            self.connected_charge_points[charge_point_id].get("last_seen")
                            or self.connected_charge_points[charge_point_id].get("connected_at")
                        )
                    if last_activity is None or (now - last_activity).total_seconds() > OCPP_TIMEOUT:
                        idle_seconds = (now - last_activity).total_seconds() if last_activity else OCPP_TIMEOUT
                        logger.warning(f"No OCPP messages received from {charge_point_id} for {idle_seconds:.0f}s. Cleaning up.")

                        await OCPPMetrics.record_heartbeat_timeout(charge_point_id)
                        SentryHelper.add_breadcrumb(
                            category="ocpp.heartbeat",
                            message=f"OCPP activity timeout for {charge_point_id}",
                            level="warning"
                        )

                        await self.force_disconnect(charge_point_id, f"OCPP activity timeout ({OCPP_TIMEOUT}s)")
                        break
                    logger.info(f"Heartbeat monitor: {charge_point_id} last OCPP message {(now - last_activity).total_seconds():.1f}s ago")
                except Exception as e:
                    logger.warning(f"Heartbeat monitor error for {charge_point_id}: {e}")
                    await self.force_disconnect(charge_point_id, f"Heartbeat monitor error: {e}")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Heartbeat monitor error for {charge_point_id}: {e}")

    async def periodic_cleanup(self):
        """Periodic cleanup of stale connections every 5 minutes."""
        while True:
            try:
                await asyncio.sleep(300)
                logger.info("Running periodic cleanup of stale connections")

                current_time = datetime.datetime.now(datetime.timezone.utc)
                stale_connections = []
                most_recent_times = {}

                for charge_point_id, connection_data in self.connected_charge_points.items():
                    last_seen = connection_data.get("last_seen")
                    last_heartbeat = connection_data.get("last_heartbeat")

                    most_recent = max(
                        last_seen or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
                        last_heartbeat or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
                    )
                    most_recent_times[charge_point_id] = most_recent

                    if (current_time - most_recent).total_seconds() > OCPP_TIMEOUT:
                        stale_connections.append(charge_point_id)
                        logger.warning(f"Connection {charge_point_id} stale: last activity {(current_time - most_recent).total_seconds():.1f}s ago")

                for charge_point_id in stale_connections:
                    most_recent = most_recent_times[charge_point_id]
                    inactive_seconds = (current_time - most_recent).total_seconds()
                    logger.warning(f"Cleaning up stale connection: {charge_point_id}")
                    await self.force_disconnect(charge_point_id, f"Stale connection (inactive for {inactive_seconds:.1f}s)")

                # Prune cleanup locks for charge points no longer connected
                stale_locks = [cp_id for cp_id in self._cleanup_locks if cp_id not in self.connected_charge_points]
                for cp_id in stale_locks:
                    del self._cleanup_locks[cp_id]

                # Prune expired tombstones
                expired_tombstones = [cp_id for cp_id, exp in self._recently_disconnected.items() if current_time > exp]
                for cp_id in expired_tombstones:
                    del self._recently_disconnected[cp_id]

            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")

    # --- cleanup task lifecycle ---

    def start_cleanup_task(self):
        """Start the periodic cleanup background task. Call from app startup."""
        self._cleanup_task = safe_create_task(self.periodic_cleanup())

    async def stop_cleanup_task(self):
        """Stop the periodic cleanup background task. Call from app shutdown."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    # --- OCPP request dispatch ---

    async def send_ocpp_request(self, charge_point_id: str, action: str, payload: Dict = None):
        """Send an OCPP request from central system to a connected charge point."""
        is_connected = await redis_manager.is_charger_connected(charge_point_id)
        if not is_connected:
            logger.warning(f"Charge point {charge_point_id} not connected (not in Redis)")
            return False, f"Charge point {charge_point_id} not connected"

        connection_data = self.connected_charge_points.get(charge_point_id)
        if not connection_data:
            logger.warning(f"ChargePoint instance for {charge_point_id} not found in memory but found in Redis (stale entry after server restart)")
            logger.warning(f"Connected chargers in memory: {list(self.connected_charge_points.keys())}")
            await redis_manager.remove_connected_charger(charge_point_id)
            return False, "Charger connection lost. Please wait for charger to reconnect (usually within 60 seconds)"

        cp = connection_data.get("cp")
        websocket = connection_data.get("websocket")

        if not cp or not websocket:
            logger.warning(f"Invalid connection data for {charge_point_id}")
            return False, f"Invalid connection data for {charge_point_id}"

        try:
            if not self.is_ws_connected(websocket):
                state_name = getattr(websocket.client_state, "name", str(getattr(websocket, "client_state", "unknown")))
                logger.warning(f"WebSocket not connected for {charge_point_id} (state={state_name})")
                await self.force_disconnect(charge_point_id, f"WebSocket not connected (state={state_name})")
                return False, "Connection lost"
        except Exception as e:
            logger.warning(f"WebSocket validation failed for {charge_point_id}: {e}")
            await self.force_disconnect(charge_point_id, f"WebSocket validation failed: {e}")
            return False, "Connection lost"

        try:
            if action == "RemoteStartTransaction":
                req = call.RemoteStartTransaction(**(payload or {}))
            elif action == "RemoteStopTransaction":
                req = call.RemoteStopTransaction(**(payload or {}))
            elif action == "ChangeAvailability":
                req = call.ChangeAvailability(**(payload or {}))
            elif action == "UpdateFirmware":
                req = call.UpdateFirmware(**(payload or {}))
            elif action == "Reset":
                req = call.Reset(**(payload or {}))
            elif action == "DataTransfer":
                req = call.DataTransfer(**(payload or {}))
            else:
                logger.warning(f"Action {action} not implemented in send_ocpp_request")
                return False, f"Action {action} not implemented"

            response = await asyncio.wait_for(cp.call(req), timeout=30)
            logger.info(f"Sent {action} request to {charge_point_id}")
            return True, response
        except asyncio.TimeoutError:
            logger.warning(f"OCPP timeout (30s) sending {action} to {charge_point_id}")
            return False, f"OCPP timeout: {action}"
        except Exception as e:
            logger.error(f"Error sending request to {charge_point_id}: {e}", exc_info=True)
            return False, str(e)


# ============ WebSocket Adapters ============

class FastAPIWebSocketAdapter:
    """Adapter to make FastAPI's WebSocket compatible with python-ocpp."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def recv(self):
        return await self.websocket.receive_text()

    async def send(self, data):
        await self.websocket.send_text(data)


class LoggingWebSocketAdapter(FastAPIWebSocketAdapter):
    """Logging adapter to persist all OCPP messages to DB with validation."""

    def __init__(self, websocket: WebSocket, charge_point_id: str):
        super().__init__(websocket)
        self.charge_point_id = charge_point_id
        self._at_command_skip_count = 0  # Count of AT commands seen in the current window
        self._at_command_window_start: Optional[datetime.datetime] = None  # Start of rolling window

    async def recv(self):
        while True:
            msg = await super().recv()

            # Ghost session detection - check if this charge point is in our connected list
            if self.charge_point_id not in connection_manager.connected_charge_points:
                logger.warning(f"[DISCONNECT] Ghost session detected for {self.charge_point_id} - message received but not in connected list")

                # Force close the ghost connection
                try:
                    await self.websocket.close(code=1008, reason="Ghost session cleanup")
                    logger.info(f"[DISCONNECT] Closed ghost session WebSocket for {self.charge_point_id}")
                except Exception as e:
                    logger.warning(f"[DISCONNECT] Error closing ghost session WebSocket for {self.charge_point_id}: {e}")

                raise WebSocketDisconnect(code=1008)

            # Update last_seen for ANY incoming message from valid connections
            connection_manager.connected_charge_points[self.charge_point_id]["last_seen"] = datetime.datetime.now(datetime.timezone.utc)

            # Filter out AT commands (firmware bug where charger sends raw modem commands)
            # Counter uses a rolling 1-hour window to distinguish transient AT leaks
            # from sustained firmware malfunction.
            msg_stripped = msg.strip()
            if msg_stripped.startswith("AT+") or msg_stripped.startswith("AT ") or msg_stripped.startswith("at+") or msg_stripped.startswith("at "):
                now = datetime.datetime.now(datetime.timezone.utc)
                if self._at_command_window_start is None or (now - self._at_command_window_start).total_seconds() > 3600:
                    self._at_command_window_start = now
                    self._at_command_skip_count = 0
                self._at_command_skip_count += 1

                if self._at_command_skip_count > 50:
                    logger.error(
                        f"[FIRMWARE BUG] {self.charge_point_id} sent {self._at_command_skip_count} AT commands "
                        f"in the last hour - possible firmware malfunction. Disconnecting for safety."
                    )
                    raise WebSocketDisconnect(code=1008)

                logger.warning(f"[FIRMWARE BUG] {self.charge_point_id} sent AT modem command over OCPP websocket: '{msg_stripped}' - ignoring (skip count: {self._at_command_skip_count})")
                continue

            # Valid message received — keep the window but do not reset the count.
            # The window itself expires after 1 hour of no AT commands.

            # Validate OCPP message format before processing
            correlation_id = None
            try:
                parsed = json.loads(msg)

                # OCPP messages must be JSON arrays
                if not isinstance(parsed, list):
                    logger.error(f"[OCPP VALIDATION] {self.charge_point_id} sent non-array message: {msg}")
                    await self._send_protocol_error("RPC message must be a JSON array")
                    safe_create_task(log_message(
                        charger_id=self.charge_point_id,
                        direction="IN",
                        message_type="OCPP",
                        payload=msg,
                        status="error",
                        correlation_id="invalid"
                    ))
                    continue

                # Validate OCPP message structure
                # CALL: [2, "messageId", "action", {payload}]
                # CALLRESULT: [3, "messageId", {payload}]
                # CALLERROR: [4, "messageId", "errorCode", "errorDescription", {errorDetails}]
                message_type_id = parsed[0] if len(parsed) > 0 else None

                if message_type_id not in [2, 3, 4]:
                    logger.error(f"[OCPP VALIDATION] {self.charge_point_id} sent invalid message type ID {message_type_id}: {msg}")
                    await self._send_protocol_error(f"Invalid OCPP message type ID: {message_type_id}")
                    safe_create_task(log_message(
                        charger_id=self.charge_point_id,
                        direction="IN",
                        message_type="OCPP",
                        payload=msg,
                        status="error",
                        correlation_id="invalid"
                    ))
                    continue

                # Extract correlation ID (message ID)
                if len(parsed) > 1:
                    correlation_id = str(parsed[1])
                else:
                    logger.error(f"[OCPP VALIDATION] {self.charge_point_id} sent message without message ID: {msg}")
                    await self._send_protocol_error("OCPP message missing message ID")
                    safe_create_task(log_message(
                        charger_id=self.charge_point_id,
                        direction="IN",
                        message_type="OCPP",
                        payload=msg,
                        status="error",
                        correlation_id="missing"
                    ))
                    continue

                # Validate CALL message structure (most common from charge points)
                if message_type_id == 2:
                    if len(parsed) < 4:
                        logger.error(f"[OCPP VALIDATION] {self.charge_point_id} sent incomplete CALL message: {msg}")
                        await self._send_call_error(correlation_id, "ProtocolError", "CALL message must have [messageType, messageId, action, payload]")
                        safe_create_task(log_message(
                            charger_id=self.charge_point_id,
                            direction="IN",
                            message_type="OCPP",
                            payload=msg,
                            status="error",
                            correlation_id=correlation_id
                        ))
                        continue

                    action = parsed[2]
                    payload = parsed[3]

                    if not isinstance(action, str):
                        logger.error(f"[OCPP VALIDATION] {self.charge_point_id} sent CALL with non-string action: {msg}")
                        await self._send_call_error(correlation_id, "ProtocolError", "Action must be a string")
                        safe_create_task(log_message(
                            charger_id=self.charge_point_id,
                            direction="IN",
                            message_type="OCPP",
                            payload=msg,
                            status="error",
                            correlation_id=correlation_id
                        ))
                        continue

                    if not isinstance(payload, dict):
                        logger.error(f"[OCPP VALIDATION] {self.charge_point_id} sent CALL with non-object payload: {msg}")
                        await self._send_call_error(correlation_id, "ProtocolError", "Payload must be a JSON object")
                        safe_create_task(log_message(
                            charger_id=self.charge_point_id,
                            direction="IN",
                            message_type="OCPP",
                            payload=msg,
                            status="error",
                            correlation_id=correlation_id
                        ))
                        continue

            except json.JSONDecodeError as e:
                logger.error(f"[OCPP VALIDATION] {self.charge_point_id} sent invalid JSON: {msg} - Error: {e}")
                await self._send_protocol_error(f"Invalid JSON: {str(e)}")
                safe_create_task(log_message(
                    charger_id=self.charge_point_id,
                    direction="IN",
                    message_type="OCPP",
                    payload=msg,
                    status="error",
                    correlation_id="invalid_json"
                ))
                continue
            except Exception as e:
                logger.error(f"[OCPP VALIDATION] {self.charge_point_id} message validation error: {msg} - Error: {e}", exc_info=True)
                await self._send_protocol_error(f"Message validation failed: {str(e)}")
                safe_create_task(log_message(
                    charger_id=self.charge_point_id,
                    direction="IN",
                    message_type="OCPP",
                    payload=msg,
                    status="error",
                    correlation_id="validation_error"
                ))
                continue

            # Message is valid - log it and return
            safe_create_task(log_message(
                charger_id=self.charge_point_id,
                direction="IN",
                message_type="OCPP",
                payload=msg,
                status="received",
                correlation_id=correlation_id
            ))
            logger.debug(f"[OCPP][IN] {msg}")
            return msg

    async def _send_protocol_error(self, error_description: str):
        """Send a protocol error when message can't be parsed (no message ID available)"""
        try:
            logger.warning(f"[OCPP ERROR] Sending protocol error to {self.charge_point_id}: {error_description}")
        except Exception as e:
            logger.error(f"[OCPP ERROR] Failed to handle protocol error for {self.charge_point_id}: {e}")

    async def _send_call_error(self, message_id: str, error_code: str, error_description: str):
        """Send an OCPP CALLERROR response for validation failures"""
        try:
            # CALLERROR format: [4, "messageId", "errorCode", "errorDescription", {}]
            error_message = [4, message_id, error_code, error_description, {}]
            error_json = json.dumps(error_message)

            logger.warning(f"[OCPP ERROR] Sending CALLERROR to {self.charge_point_id}: {error_json}")

            # Log outgoing error
            await log_message(
                charger_id=self.charge_point_id,
                direction="OUT",
                message_type="OCPP",
                payload=error_json,
                status="sent",
                correlation_id=message_id
            )

            # Send error response
            await super().send(error_json)
        except Exception as e:
            logger.error(f"[OCPP ERROR] Failed to send CALLERROR to {self.charge_point_id}: {e}", exc_info=True)

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
        logger.debug(f"[OCPP][OUT] {data}")
        await super().send(data)


# Module-level singleton
connection_manager = ConnectionManager()
