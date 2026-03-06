"""OCPP WebSocket endpoint for charge point connections."""
import asyncio
import datetime
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.connection_manager import connection_manager, LoggingWebSocketAdapter
from crud import validate_and_connect_charger, log_audit_event
from redis_manager import redis_manager
from services.monitoring_service import OCPPMetrics, SentryHelper

logger = logging.getLogger("ocpp-server")

router = APIRouter()


@router.websocket("/ocpp/{charge_point_id}")
async def ocpp_websocket(websocket: WebSocket, charge_point_id: str):
    """OCPP WebSocket endpoint for charge points"""
    logger.info(f"[CONNECTION ATTEMPT] {charge_point_id} attempting WebSocket connection")

    # Add Sentry breadcrumb
    SentryHelper.add_breadcrumb(
        category="ocpp.connection",
        message=f"WebSocket connection attempt: {charge_point_id}",
        level="info"
    )

    try:
        await websocket.accept()
        logger.info(f"[CONNECTION ATTEMPT] {charge_point_id} WebSocket handshake successful")
    except Exception as e:
        logger.error(f"[CONNECTION ATTEMPT] {charge_point_id} WebSocket handshake failed: {e}")
        await OCPPMetrics.record_websocket_connection(charge_point_id, success=False)
        SentryHelper.capture_exception(e, extra={"charger_id": charge_point_id})
        return

    # Check for recent disconnection tombstone to prevent reconnection races
    remaining_ms = connection_manager.check_tombstone(charge_point_id)
    if remaining_ms is not None:
        logger.warning(f"[CONNECTION ATTEMPT] Rejecting immediate reconnection for {charge_point_id} - tombstone expires in {remaining_ms:.1f}ms")
        asyncio.create_task(log_audit_event(
            action="charger.connection_rejected",
            entity_type="charger",
            entity_id=charge_point_id,
            actor_type="ocpp",
            changes={"reason": "tombstone_active", "close_code": 1013},
        ))
        await websocket.close(code=1013, reason="Too soon after disconnect")
        return

    # If charger already connected, force disconnect old connection (handles reconnection after reboot)
    if charge_point_id in connection_manager.connected_charge_points:
        logger.warning(f"[CONNECTION ATTEMPT] {charge_point_id} already connected - forcing disconnect of stale connection")
        await connection_manager.force_disconnect(charge_point_id, "New connection attempt - replacing stale connection")

    # Validate charger before connecting
    is_valid, message = await validate_and_connect_charger(charge_point_id, connection_manager.connected_charge_points)
    if not is_valid:
        logger.warning(f"[CONNECTION ATTEMPT] Validation failed for {charge_point_id}: {message}")
        asyncio.create_task(log_audit_event(
            action="charger.connection_rejected",
            entity_type="charger",
            entity_id=charge_point_id,
            actor_type="ocpp",
            changes={"reason": "validation_failed", "close_code": 1008},
        ))
        await websocket.close(code=1008, reason=message)
        return

    logger.info(f"[CONNECTION ATTEMPT] {charge_point_id} validation successful - establishing OCPP connection")

    # Deferred import to avoid circular dependency (ChargePoint is defined in main.py)
    from main import ChargePoint

    ws_adapter = LoggingWebSocketAdapter(websocket, charge_point_id)
    cp = ChargePoint(charge_point_id, ws_adapter)

    # Start heartbeat monitor task
    heartbeat_task = asyncio.create_task(connection_manager.heartbeat_monitor(charge_point_id, websocket))

    # Store connection data with heartbeat task handle for proper cleanup
    connection_data = {
        "websocket": websocket,
        "cp": cp,
        "heartbeat_task": heartbeat_task,  # Store for cleanup
        "connected_at": datetime.datetime.now(datetime.timezone.utc),
        "last_seen": datetime.datetime.now(datetime.timezone.utc)
    }
    connection_manager.connected_charge_points[charge_point_id] = connection_data

    # Add to Redis
    await redis_manager.add_connected_charger(charge_point_id, connection_data)

    logger.info(f"[CONNECTION ATTEMPT] {charge_point_id} connection established successfully - starting OCPP message handling")

    asyncio.create_task(log_audit_event(
        action="charger.connected",
        entity_type="charger",
        entity_id=charge_point_id,
        actor_type="system",
        changes={"source": "websocket"},
    ))

    # Record successful WebSocket connection
    await OCPPMetrics.record_websocket_connection(charge_point_id, success=True)

    # Update active connections metric
    active_connections = len(connection_manager.connected_charge_points)
    await OCPPMetrics.record_active_connections(active_connections)

    try:
        await cp.start()
    except WebSocketDisconnect as e:
        logger.error(f"[DISCONNECT] Charge point {charge_point_id} disconnected naturally - WebSocket code: {getattr(e, 'code', 'unknown')}, reason: {getattr(e, 'reason', 'none')}")
        logger.error(f"[DISCONNECT] WebSocket state at disconnect: {getattr(websocket, 'client_state', 'unknown')}")
        logger.error(f"[DISCONNECT] Last seen: {connection_data.get('last_seen', 'never') if charge_point_id in connection_manager.connected_charge_points else 'connection not found'}")
        # Apply tombstone on natural disconnect and let finally handle cleanup
        await connection_manager.force_disconnect(charge_point_id, "Natural WebSocket disconnect")
        return  # Avoid double cleanup in finally
    except Exception as e:
        logger.error(f"[DISCONNECT] WebSocket error for {charge_point_id}: {e}", exc_info=True)
        logger.error(f"[DISCONNECT] WebSocket state at error: {getattr(websocket, 'client_state', 'unknown')}")
        logger.error(f"[DISCONNECT] Connection data at error: {connection_data if charge_point_id in connection_manager.connected_charge_points else 'connection not found'}")
    finally:
        # Use force_disconnect for proper cleanup if still connected
        if charge_point_id in connection_manager.connected_charge_points:
            await connection_manager.force_disconnect(charge_point_id, "WebSocket session ended")
