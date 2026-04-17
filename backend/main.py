# main.py
import os
import asyncio
import datetime
from typing import Dict, List
from fastapi import Depends, FastAPI, HTTPException, Query
from auth_middleware import require_admin
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import init_db, close_db
from schemas import OCPPCommand, OCPPResponse, MessageLogResponse, ChargePointStatus
from crud import (
    get_logs,
    get_logs_by_charge_point,
    update_charger_status,
    update_charger_heartbeat,
    log_audit_event,
)
from models import OCPPLog, Transaction, TransactionStatusEnum, MeterValue
from services.wallet_service import WalletService
from redis_manager import redis_manager
from core.connection_manager import connection_manager
from utils import safe_create_task, mask_id_tag, mask_email

from ocpp.v16 import ChargePoint as OcppChargePoint
from ocpp.v16 import call, call_result
from ocpp.routing import on, after
import logging
import json

# Transaction resume constants
SUSPEND_TIMEOUT_SECONDS = int(os.environ.get("SUSPEND_TIMEOUT_SECONDS", "300"))

# Socket charger grace period (seconds) before failing txn on Available status
SOCKET_GRACE_PERIOD_SECONDS = int(os.environ.get("SOCKET_GRACE_PERIOD_SECONDS", "300"))

# Import routers
from routers import stations, chargers, transactions, auth, webhooks, users, public_stations, logs, wallet_payments, firmware

# Import monitoring service
from services.monitoring_service import (
    initialize_monitoring,
    MetricsCollector,
    OCPPMetrics,
    SentryHelper,
    trace_transaction,
    trace_function
)

# Initialize monitoring BEFORE creating FastAPI app
# This must happen before app = FastAPI() for proper instrumentation
initialize_monitoring()

# Configure root logger with timestamps, preserving any existing handlers (e.g. New Relic)
root = logging.getLogger()
root.setLevel(logging.INFO)
if not root.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(handler)
else:
    # Preserve existing handlers, but add our formatter to any without one
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    for h in root.handlers:
        if not h.formatter:
            h.setFormatter(fmt)

# App-specific logger with custom formatter (propagate=False to avoid
# duplicate output through root's handler)
logger = logging.getLogger("ocpp-server")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

# FastAPI app
app = FastAPI(
    title="OCPP Central System API", 
    version="0.1.0",
    description="EV Charging Station Management System with OCPP 1.6 support"
)

# Allowed CORS origins — env-driven, single source of truth for CORSMiddleware and OptionsMiddleware
_cors_env = os.getenv("CORS_ORIGINS", "").strip()
if _cors_env:
    ALLOWED_ORIGINS = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    # Dev default when CORS_ORIGINS not set
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://frontend:3000",
        "http://ocpp-frontend:3000",
    ]
logger.info("CORS allowed origins: %s", ALLOWED_ORIGINS)

# Configure CORS - Allow frontend domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# Configure Sentry middleware for error tracking
if os.getenv("SENTRY_ENABLED", "false").lower() == "true":
    try:
        import sentry_sdk
        from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
        app.add_middleware(SentryAsgiMiddleware)
        logger.info("✅ Sentry ASGI middleware added")
    except ImportError:
        logger.warning("⚠️ Sentry SDK not available, middleware not added")

# Middleware to handle OPTIONS (CORS preflight) requests
# This ensures OPTIONS requests don't hit authentication middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class OptionsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Handle OPTIONS requests immediately with proper CORS headers
        if request.method == "OPTIONS":
            origin = request.headers.get("origin", "")

            # Only set CORS headers if origin is allowed
            if origin not in ALLOWED_ORIGINS:
                return Response(status_code=403)

            headers = {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
                "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Max-Age": "3600",
            }

            return Response(status_code=200, headers=headers)

        # For non-OPTIONS requests, continue normally
        response = await call_next(request)
        return response

app.add_middleware(OptionsMiddleware)

# Mount firmware files as static files
FIRMWARE_DIR = os.path.join(os.path.dirname(__file__), "firmware_files")
os.makedirs(FIRMWARE_DIR, exist_ok=True)
app.mount("/firmware", StaticFiles(directory=FIRMWARE_DIR), name="firmware")

# Backward-compatible alias: same dict object by reference, so all existing
# reads/writes (including `from main import connected_charge_points`) work unchanged.
connected_charge_points = connection_manager.connected_charge_points

# Valid OCPP 1.6 StopTransaction reason values
VALID_STOP_REASONS = {
    "EmergencyStop", "EVDisconnected", "HardReset", "Local", "Other",
    "PowerLoss", "Reboot", "Remote", "SoftReset", "UnlockCommand", "DeAuthorized",
}

# Define a ChargePoint class using python-ocpp
class ChargePoint(OcppChargePoint):

    async def route_message(self, raw_msg):
        """Override to sanitize invalid StopTransaction reason values before validation."""
        try:
            parsed = json.loads(raw_msg)
            # Call messages: [2, uniqueId, action, payload]
            if isinstance(parsed, list) and len(parsed) == 4 and parsed[0] == 2:
                action = parsed[2]
                payload = parsed[3]
                if action == "StopTransaction" and "reason" in payload:
                    if payload["reason"] not in VALID_STOP_REASONS:
                        original = payload["reason"]
                        payload["reason"] = "Other"
                        raw_msg = json.dumps(parsed)
                        logger.warning(
                            f"Sanitized invalid StopTransaction reason '{original}' → 'Other' "
                            f"from {self.id}"
                        )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Let the parent handle malformed messages

        await super().route_message(raw_msg)

    @on('BootNotification')
    @trace_transaction(name="OCPP/BootNotification", group="OCPP/Messages")
    async def on_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
        # Record metric
        await OCPPMetrics.record_message("BootNotification", "IN")

        # Add Sentry breadcrumb
        SentryHelper.add_breadcrumb(
            category="ocpp.message",
            message=f"BootNotification from {self.id}",
            level="info",
            data={"vendor": charge_point_vendor, "model": charge_point_model}
        )

        # Extract optional fields from kwargs
        firmware_version = kwargs.get('firmware_version')
        charge_point_serial_number = kwargs.get('charge_point_serial_number')
        iccid = kwargs.get('iccid')
        imsi = kwargs.get('imsi')
        meter_type = kwargs.get('meter_type')
        meter_serial_number = kwargs.get('meter_serial_number')

        logger.info(f"BootNotification from {self.id}: vendor={charge_point_vendor}, model={charge_point_model}, firmware={firmware_version}")

        # Update charger information in database
        from models import Charger
        try:
            charger = await Charger.get(charge_point_string_id=self.id)

            # Update charger fields if provided
            if charge_point_vendor:
                charger.vendor = charge_point_vendor
            if charge_point_model:
                charger.model = charge_point_model
            if firmware_version:
                charger.firmware_version = firmware_version
                logger.info(f"📦 Recorded firmware version for {self.id}: {firmware_version}")
            if charge_point_serial_number:
                charger.serial_number = charge_point_serial_number
            if iccid:
                charger.iccid = iccid
            if imsi:
                charger.imsi = imsi
            if meter_type:
                charger.meter_type = meter_type
            if meter_serial_number:
                charger.meter_serial_number = meter_serial_number

            await charger.save()

            # Cache connector type for socket-aware StatusNotification handling
            from models import Connector
            connector = await Connector.filter(charger=charger).first()
            if connector and self.id in connected_charge_points:
                connected_charge_points[self.id]["connector_type"] = connector.connector_type
        except Exception as e:
            logger.error(f"❌ Error updating charger info from BootNotification: {e}", exc_info=True)

        # A BootNotification means the charger rebooted. Handle ongoing transactions:
        # - Already SUSPENDED (from disconnect): reset suspended_at to extend window
        # - Still RUNNING/STARTED/etc (edge case): suspend them
        # In both cases, start a SUSPEND_TIMEOUT_SECONDS timeout for resume.
        try:
            ongoing_transactions = await Transaction.filter(
                charger__charge_point_string_id=self.id,
                transaction_status__in=[
                    TransactionStatusEnum.RUNNING,
                    TransactionStatusEnum.STARTED,
                    TransactionStatusEnum.PENDING_START,
                    TransactionStatusEnum.PENDING_STOP,
                    TransactionStatusEnum.SUSPENDED,
                ]
            ).all()

            if ongoing_transactions:
                now = datetime.datetime.now(datetime.timezone.utc)
                logger.warning(f"⚠️ BootNotification from {self.id} — handling {len(ongoing_transactions)} ongoing transaction(s)")

                for transaction in ongoing_transactions:
                    await self._handle_ongoing_transaction_on_boot(transaction, now)
        except Exception as e:
            logger.error(f"Error handling transactions on BootNotification for {self.id}: {e}", exc_info=True)

        return call_result.BootNotification(
            current_time=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
            interval=30,
            status="Accepted"
        )

    @after('BootNotification')
    async def after_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
        """Push post-boot state (meter value + pending transaction) to charger after BootNotification response."""
        from models import Transaction, TransactionStatusEnum
        try:
            suspended_txns = await Transaction.filter(
                charger__charge_point_string_id=self.id,
                transaction_status=TransactionStatusEnum.SUSPENDED,
            ).all()

            if suspended_txns:
                logger.info(f"📡 Pushing PostBootState for {len(suspended_txns)} suspended transaction(s) to {self.id}")
                for txn in suspended_txns:
                    await self._push_post_boot_state(transaction=txn)
            else:
                logger.info(f"📡 Pushing PostBootState (meter restore only) to {self.id}")
                await self._push_post_boot_state(transaction=None)

        except Exception as e:
            logger.error(f"Error in after_boot_notification for {self.id}: {e}", exc_info=True)

    async def _push_post_boot_state(self, transaction=None):
        """Send PostBootState DataTransfer to charger with meter value and optional transaction info."""
        from models import Transaction, TransactionStatusEnum, MeterValue
        try:
            if transaction:
                latest_mv = await MeterValue.filter(
                    transaction_id=transaction.id
                ).order_by("-created_at").first()

                start_kwh = transaction.start_meter_kwh or 0
                last_kwh = latest_mv.reading_kwh if latest_mv else start_kwh
                energy_kwh = last_kwh - start_kwh

                payload_data = json.dumps({
                    "hasPendingTransaction": True,
                    "transactionId": transaction.id,
                    "startMeterValueWh": int(round(start_kwh * 1000)),
                    "lastMeterValueWh": int(round(last_kwh * 1000)),
                    "energyConsumedWh": int(round(energy_kwh * 1000)),
                })
            else:
                last_meter_wh = await self._get_charger_last_meter_wh()
                payload_data = json.dumps({
                    "hasPendingTransaction": False,
                    "lastMeterValueWh": last_meter_wh,
                })

            req = call.DataTransfer(
                vendor_id="VOLTLYNC",
                message_id="PostBootState",
                data=payload_data,
            )
            response = await asyncio.wait_for(self.call(req), timeout=15)

            logger.info(f"📡 PostBootState push to {self.id}: status={response.status}, data={payload_data}")
            if response.status != "Accepted":
                logger.warning(f"📡 Charger {self.id} did not accept PostBootState: status={response.status}")

        except asyncio.TimeoutError:
            logger.warning(f"📡 PostBootState push timed out for {self.id}")
        except Exception as e:
            logger.error(f"📡 Error pushing PostBootState to {self.id}: {e}", exc_info=True)

    async def _get_charger_last_meter_wh(self):
        """Get the last known meter value (Wh) for this charger from the most recent transaction with end meter data."""
        from models import Transaction
        last_txn = await Transaction.filter(
            charger__charge_point_string_id=self.id,
            end_meter_kwh__isnull=False,
        ).order_by("-end_time").first()

        if last_txn and last_txn.end_meter_kwh:
            return int(round(last_txn.end_meter_kwh * 1000))
        return 0

    async def _handle_ongoing_transaction_on_boot(self, transaction, now: datetime.datetime) -> None:
        """
        Process a single ongoing transaction during BootNotification.

        Decides between:
        - Refuse + finalize (gap is too stale — defense-in-depth guard)
        - Reset suspended_at (already-SUSPENDED, normal flap)
        - Skip without action (already-SUSPENDED, pathological flap)
        - Suspend a still-running txn (edge case: disconnect handler missed it)

        Then audit-logs and schedules the suspend timer when applicable.
        Extracted from on_boot_notification for testability.
        """
        from services.transaction_finalizer import (
            is_resume_too_stale,
            finalize_stopped_transaction,
        )
        from services.disconnect_handler import (
            _disconnect_reset_count,
            MAX_RESETS_WITHOUT_PROGRESS,
        )

        previous_status = transaction.transaction_status

        # Staleness guard — applies to both branches below. Catches the case
        # where suspend_transactions_on_disconnect failed to run, OR where its
        # _disconnect_suspend_timeout task died (process restart) before firing.
        is_stale, gap = await is_resume_too_stale(transaction)
        if is_stale:
            logger.warning(
                f"⏰ Refusing to resume stale transaction {transaction.id} on "
                f"BootNotification (was {previous_status}) — gap={gap:.0f}s"
            )
            safe_create_task(log_audit_event(
                action="transaction.resume_blocked",
                entity_type="transaction",
                entity_id=transaction.id,
                actor_type="system",
                changes={
                    "previous_status": str(previous_status),
                    "trigger": "BootNotification",
                    "gap_seconds": gap,
                    "reason": "STALE_RECONNECT",
                },
            ))
            await finalize_stopped_transaction(transaction, "STALE_RECONNECT")
            _disconnect_reset_count.pop(transaction.id, None)
            return

        if previous_status == TransactionStatusEnum.SUSPENDED:
            # Already suspended from disconnect — would normally reset
            # timeout window. Pathological-flap guard (W5): if we've
            # already reset this txn's suspended_at
            # MAX_RESETS_WITHOUT_PROGRESS times without any energy
            # progress in between, do NOT reset — let the existing
            # timer fire and finalize the transaction.
            count = _disconnect_reset_count.get(transaction.id, 0)
            if count >= MAX_RESETS_WITHOUT_PROGRESS:
                logger.warning(
                    f"Transaction {transaction.id}: {count} consecutive "
                    f"BootNotification resets without energy progress — "
                    f"letting existing timer fire"
                )
                return
            transaction.suspended_at = now
            await transaction.save()
            _disconnect_reset_count[transaction.id] = count + 1
            logger.info(
                f"⏸️ Transaction {transaction.id} already SUSPENDED — "
                f"resetting timeout for resume (reset count={count + 1})"
            )
        else:
            # Edge case: still active when BootNotification arrives
            transaction.transaction_status = TransactionStatusEnum.SUSPENDED
            transaction.suspended_at = now
            await transaction.save()
            logger.info(f"⏸️ Suspended transaction {transaction.id} (was {previous_status}) due to charger reboot")

        safe_create_task(log_audit_event(
            action="transaction.suspended",
            entity_type="transaction",
            entity_id=transaction.id,
            actor_type="system",
            changes={
                "previous_status": str(previous_status),
                "new_status": "SUSPENDED",
                "trigger": "BootNotification",
            },
        ))

        # Start resume timeout — will auto-stop if charger doesn't resume
        safe_create_task(self._suspend_timeout(transaction.id, now, SUSPEND_TIMEOUT_SECONDS))

    async def _suspend_timeout(self, transaction_id: int, original_suspended_at, timeout_seconds: int = 300):
        """Auto-stop a SUSPENDED transaction if the charger doesn't resume it in time."""
        try:
            await asyncio.sleep(timeout_seconds)

            transaction = await Transaction.filter(id=transaction_id).first()
            if not transaction:
                return

            # Only act if still SUSPENDED with the same suspended_at (handles double-boot race)
            if (
                transaction.transaction_status != TransactionStatusEnum.SUSPENDED
                or transaction.suspended_at != original_suspended_at
            ):
                logger.info(f"⏸️ Suspend timeout for transaction {transaction_id} — status already changed, skipping")
                return

            from services.transaction_finalizer import finalize_stopped_transaction
            await finalize_stopped_transaction(transaction, "SUSPENDED_TIMEOUT")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in suspend timeout for transaction {transaction_id}: {e}", exc_info=True)

    async def _start_socket_grace_period(self, transactions):
        """Start a grace period for socket charger reporting Available during active transactions."""
        # Check if grace period already active to avoid duplicates
        existing = await redis_manager.get_socket_grace_period(self.id)
        if existing:
            logger.info(f"Socket grace period already active for {self.id}, skipping duplicate")
            return

        txn_ids = [t.id for t in transactions]
        grace_started = datetime.datetime.now(datetime.timezone.utc)
        await redis_manager.set_socket_grace_period(self.id, txn_ids, ttl=SOCKET_GRACE_PERIOD_SECONDS)
        logger.info(
            f"Socket charger {self.id}: Available during active transactions {txn_ids} "
            f"— starting {SOCKET_GRACE_PERIOD_SECONDS}s grace period"
        )

        for transaction in transactions:
            safe_create_task(
                self._socket_grace_timeout(transaction.id, grace_started, SOCKET_GRACE_PERIOD_SECONDS)
            )

    async def _socket_grace_timeout(self, transaction_id, grace_started_at, timeout_seconds=300):
        """After grace period, fail the transaction if no MeterValues arrived."""
        try:
            await asyncio.sleep(timeout_seconds)

            transaction = await Transaction.filter(id=transaction_id).first()
            if not transaction:
                return

            # CAS guard: only act if transaction is still in an active state
            active_statuses = {
                TransactionStatusEnum.RUNNING, TransactionStatusEnum.STARTED,
                TransactionStatusEnum.PENDING_START, TransactionStatusEnum.PENDING_STOP,
                TransactionStatusEnum.SUSPENDED,
            }
            if transaction.transaction_status not in active_statuses:
                logger.info(f"Socket grace timeout for txn {transaction_id} — status already {transaction.transaction_status}, skipping")
                return

            # Check if MeterValues arrived since grace period started
            recent_mv = await MeterValue.filter(
                transaction_id=transaction_id,
                created_at__gte=grace_started_at,
            ).first()
            if recent_mv:
                logger.info(f"Socket grace timeout for txn {transaction_id} — MeterValues arrived, keeping alive")
                return

            logger.info(f"Socket grace timeout expired for txn {transaction_id} — no MeterValues, failing")
            await self._fail_transaction_with_billing(transaction, "SOCKET_GRACE_TIMEOUT")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in socket grace timeout for txn {transaction_id}: {e}", exc_info=True)

    async def _fail_transaction_with_billing(self, transaction, stop_reason):
        """Fail a transaction, process billing and QR refunds."""
        previous_status = transaction.transaction_status.value

        # Calculate energy from latest meter value if not already set
        if transaction.end_meter_kwh is None:
            latest_mv = await MeterValue.filter(
                transaction_id=transaction.id
            ).order_by("-created_at").first()
            if latest_mv:
                transaction.end_meter_kwh = latest_mv.reading_kwh
                transaction.energy_consumed_kwh = transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
                logger.info(f"Calculated energy for failed txn {transaction.id}: {transaction.energy_consumed_kwh} kWh")
            else:
                logger.warning(f"No meter values for failed txn {transaction.id}")

        transaction.transaction_status = TransactionStatusEnum.FAILED
        transaction.stop_reason = stop_reason
        transaction.end_time = datetime.datetime.now(datetime.timezone.utc)
        await transaction.save()
        logger.info(f"Marked transaction {transaction.id} as FAILED: {stop_reason}")

        safe_create_task(log_audit_event(
            action="transaction.status_changed",
            entity_type="transaction",
            entity_id=transaction.id,
            actor_type="system",
            changes={"previous_status": previous_status, "new_status": "FAILED", "trigger": stop_reason},
        ))

        await self._process_failure_billing(transaction)

    async def _process_failure_billing(self, transaction):
        """Process wallet billing and QR refunds for a failed transaction."""
        if transaction.energy_consumed_kwh is not None and transaction.energy_consumed_kwh > 0:
            try:
                success, message, billing_amount = await WalletService.process_transaction_billing(transaction.id)
                if success:
                    logger.info(f"Billed failed txn {transaction.id}: {billing_amount}")
                else:
                    logger.warning(f"Billing failed for txn {transaction.id}: {message}")
            except Exception as billing_error:
                logger.error(f"Billing error for txn {transaction.id}: {billing_error}", exc_info=True)
                await Transaction.filter(id=transaction.id).update(
                    transaction_status=TransactionStatusEnum.BILLING_FAILED
                )
        else:
            logger.warning(f"Cannot bill txn {transaction.id} - no energy consumed")

        try:
            from services.qr_payment_service import QRPaymentService
            if transaction.energy_consumed_kwh is not None and transaction.energy_consumed_kwh > 0:
                await QRPaymentService.process_qr_session_billing(transaction.id)
            else:
                await QRPaymentService.handle_charging_failure(transaction.id)
        except Exception as qr_err:
            logger.warning(f"QR payment handling error (non-fatal): {qr_err}")

        # Franchisee settlement
        try:
            from services.franchisee_settlement_service import FranchiseeSettlementService
            safe_create_task(
                FranchiseeSettlementService.process_settlement(transaction.id),
                name=f"settlement-txn-{transaction.id}",
            )
        except Exception as settle_err:
            logger.error("Settlement trigger error for txn %s: %s", transaction.id, settle_err)

        # GST invoice generation
        try:
            from services.invoice_service import InvoiceService
            safe_create_task(
                InvoiceService.generate_invoice(transaction.id),
                name=f"invoice-txn-{transaction.id}",
            )
        except Exception as inv_err:
            logger.error("Invoice trigger error for txn %s: %s", transaction.id, inv_err)

    @on('Heartbeat')
    async def on_heartbeat(self, **kwargs):
        # Record heartbeat metric (lightweight, don't trace entire transaction)
        await OCPPMetrics.record_message("Heartbeat", "IN")

        # Update last heartbeat timestamp for this charge point
        current_time = datetime.datetime.now(datetime.timezone.utc)
        if self.id in connected_charge_points:
            connected_charge_points[self.id]["last_heartbeat"] = current_time
        logger.info(f"Received OCPP Heartbeat from {self.id}")
        # Only update heartbeat time, don't assume status - wait for StatusNotification
        await update_charger_heartbeat(self.id)
        
        return call_result.Heartbeat(
            current_time=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        )
    
    @on('StatusNotification')
    async def on_status_notification(self, connector_id, status, error_code=None, info=None,
                                      vendor_error_code=None, vendor_id=None, timestamp=None, **kwargs):
        # Record metric
        await OCPPMetrics.record_message("StatusNotification", "IN")

        # Extract vendor error code fields (OCPP 1.6 uses camelCase in messages)
        vendor_error_code = vendor_error_code or kwargs.get('vendorErrorCode')
        vendor_id = vendor_id or kwargs.get('vendorId')

        logger.info(f"StatusNotification from {self.id}: connector_id={connector_id}, status={status}, "
                   f"error_code={error_code}, info={info}, vendor_error_code={vendor_error_code}, vendor_id={vendor_id}")

        try:
            # Update charger status in database
            result = await update_charger_status(self.id, status)
            if not result:
                logger.warning(f"Failed to update status for charger {self.id} - charger not found in database")
            else:
                logger.info(f"Successfully updated charger {self.id} status to {status}")

            # Store error information in ChargerError table
            from models import ChargerError, Charger
            try:
                charger = await Charger.filter(charge_point_string_id=self.id).first()
                if charger:
                    if error_code and error_code != "NoError":
                        # Parse timestamp if provided
                        error_ts = None
                        if timestamp:
                            try:
                                error_ts = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            except (ValueError, AttributeError) as e:
                                logger.debug(f"Could not parse StatusNotification timestamp '{timestamp}': {e}")

                        # Create error record
                        await ChargerError.create(
                            charger=charger,
                            connector_id=connector_id,
                            status=status,
                            error_code=error_code,
                            vendor_error_code=vendor_error_code,
                            vendor_id=vendor_id,
                            info=info[:255] if info else None,  # Truncate to max length
                            error_timestamp=error_ts
                        )
                        logger.info(f"Stored error for charger {self.id}: error_code={error_code}, "
                                   f"vendor_error_code={vendor_error_code}, vendor_id={vendor_id}")
                    elif error_code == "NoError":
                        # Mark unresolved errors for this connector as resolved
                        resolved_count = await ChargerError.filter(
                            charger=charger,
                            connector_id=connector_id,
                            is_resolved=False
                        ).update(
                            is_resolved=True,
                            resolved_at=datetime.datetime.now(datetime.timezone.utc)
                        )
                        if resolved_count > 0:
                            logger.info(f"Resolved {resolved_count} errors for charger {self.id} connector {connector_id}")
            except Exception as error_tracking_error:
                logger.error(f"Error tracking charger error: {error_tracking_error}", exc_info=True)

            # Check if status indicates not charging and fail ongoing transactions
            # Charging states: Charging, Preparing, SuspendedEVSE, SuspendedEV, Finishing
            charging_states = {"Charging", "Preparing", "SuspendedEVSE", "SuspendedEV", "Finishing"}

            if status not in charging_states:
                from models import Transaction, TransactionStatusEnum, MeterValue
                from services.charger_type_service import is_socket_charger_cached, should_use_grace_period
                try:
                    ongoing_transactions = await Transaction.filter(
                        charger__charge_point_string_id=self.id,
                        transaction_status__in=[
                            TransactionStatusEnum.RUNNING,
                            TransactionStatusEnum.STARTED,
                            TransactionStatusEnum.PENDING_START,
                            TransactionStatusEnum.PENDING_STOP,
                            TransactionStatusEnum.SUSPENDED,
                        ]
                    ).all()

                    if ongoing_transactions:
                        is_socket = await is_socket_charger_cached(self.id, connected_charge_points)

                        if is_socket and should_use_grace_period(status):
                            await self._start_socket_grace_period(ongoing_transactions)
                        else:
                            logger.info(f"Status {status} indicates not charging - found {len(ongoing_transactions)} ongoing transactions for charger {self.id} - marking as FAILED")
                            for transaction in ongoing_transactions:
                                await self._fail_transaction_with_billing(
                                    transaction, f"STATUS_CHANGE_TO_{status}"
                                )
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
    @trace_transaction(name="OCPP/StartTransaction", group="OCPP/Messages")
    async def on_start_transaction(self, connector_id, id_tag, meter_start, timestamp, **kwargs):
        # Record metric
        await OCPPMetrics.record_message("StartTransaction", "IN")

        logger.info(f"StartTransaction from {self.id}: connector_id={connector_id}, id_tag={mask_id_tag(id_tag)}, meter_start={meter_start}")
        
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
                logger.error(f"OCPP StartTransaction: No user found with rfid_card_id '{mask_id_tag(id_tag)}', rejecting transaction")
                return call_result.StartTransaction(
                    transaction_id=0,
                    id_tag_info={"status": "Invalid"}
                )
            
            logger.info(f"OCPP StartTransaction: Found user by rfid_card_id '{mask_id_tag(id_tag)}': {mask_email(user.email)}")
            
            if not user.is_active:
                logger.error(f"OCPP StartTransaction: User {mask_email(user.email)} is deactivated")
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

            safe_create_task(log_audit_event(
                action="transaction.status_changed",
                entity_type="transaction",
                entity_id=transaction.id,
                actor_type="ocpp",
                changes={"new_status": "RUNNING", "trigger": "StartTransaction"},
            ))

            # Link QR payment to transaction if applicable
            try:
                from services.qr_payment_service import QRPaymentService
                await QRPaymentService.link_transaction_to_qr_payment(
                    transaction.id, charger.id, user.id
                )
            except Exception as qr_err:
                logger.warning(f"QR payment link check failed (non-fatal): {qr_err}")

            # Record transaction started event
            await OCPPMetrics.record_transaction_started(self.id, user.id)
            SentryHelper.set_transaction_context(transaction.id, self.id, user.id)

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
    @trace_transaction(name="OCPP/StopTransaction", group="OCPP/Messages")
    async def on_stop_transaction(self, transaction_id, meter_stop, timestamp, **kwargs):
        # Record metric
        await OCPPMetrics.record_message("StopTransaction", "IN")

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

            if transaction.transaction_status == TransactionStatusEnum.SUSPENDED:
                logger.info(f"🛑 Stopping SUSPENDED transaction {transaction_id} — charger chose to end rather than resume")

            # Update transaction with end values
            transaction.end_meter_kwh = float(meter_stop) / 1000  # Convert Wh to kWh
            transaction.energy_consumed_kwh = transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
            transaction.end_time = datetime.datetime.now(datetime.timezone.utc)
            transaction.transaction_status = TransactionStatusEnum.COMPLETED
            transaction.stop_reason = kwargs.get('reason', 'Remote')
            
            await transaction.save()

            logger.info(f"🛑 ✅ Transaction stopped {transaction_id}: {transaction.energy_consumed_kwh} kWh consumed")

            # Cancel any active socket grace period for this charger
            try:
                if await redis_manager.get_socket_grace_period(self.id):
                    await redis_manager.delete_socket_grace_period(self.id)
                    logger.info(f"Cancelled socket grace period for {self.id} on StopTransaction")
            except Exception as e:
                logger.debug(f"Grace period cleanup error (non-fatal): {e}")

            # Clean up zero-energy watchdog tracking
            try:
                from services.zero_energy_watchdog import clear_zero_energy_tracking
                await clear_zero_energy_tracking(transaction_id)
            except Exception as e:
                logger.debug(f"Zero-energy cleanup error (non-fatal): {e}")

            safe_create_task(log_audit_event(
                action="transaction.status_changed",
                entity_type="transaction",
                entity_id=transaction_id,
                actor_type="ocpp",
                changes={"previous_status": "RUNNING", "new_status": "COMPLETED", "trigger": "StopTransaction"},
            ))

            # Record transaction completed event
            duration_minutes = (transaction.end_time - transaction.start_time).total_seconds() / 60 if transaction.start_time and transaction.end_time else 0
            await OCPPMetrics.record_transaction_completed(transaction_id, transaction.energy_consumed_kwh, duration_minutes)
            
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

            # Process QR payment billing (refund unused amount)
            try:
                from services.qr_payment_service import QRPaymentService
                await QRPaymentService.process_qr_session_billing(transaction_id)
            except Exception as qr_err:
                logger.error(f"QR billing error for transaction {transaction_id}: {qr_err}", exc_info=True)

            # Franchisee settlement
            try:
                from services.franchisee_settlement_service import FranchiseeSettlementService
                safe_create_task(
                    FranchiseeSettlementService.process_settlement(transaction_id),
                    name=f"settlement-txn-{transaction_id}",
                )
            except Exception as settle_err:
                logger.error("Settlement trigger error for txn %s: %s", transaction_id, settle_err)

            # GST invoice generation
            try:
                from services.invoice_service import InvoiceService
                safe_create_task(
                    InvoiceService.generate_invoice(transaction_id),
                    name=f"invoice-txn-{transaction_id}",
                )
            except Exception as inv_err:
                logger.error("Invoice trigger error for txn %s: %s", transaction_id, inv_err)

            return call_result.StopTransaction(
                id_tag_info={"status": "Accepted"}
            )

        except Exception as e:
            logger.error(f"Error stopping transaction {transaction_id}: {e}", exc_info=True)
            return call_result.StopTransaction(
                id_tag_info={"status": "Invalid"}
            )

    @on('MeterValues')
    @trace_transaction(name="OCPP/MeterValues", group="OCPP/Messages")
    async def on_meter_values(self, connector_id, meter_value, transaction_id=None, **kwargs):
        # Record metric
        await OCPPMetrics.record_message("MeterValues", "IN")

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
                return call_result.MeterValues()
                
            logger.debug(f"🔋 ✅ Found transaction {transaction_id} for charger {transaction.charger.charge_point_string_id}")

            # Auto-resume SUSPENDED transactions on MeterValues receipt
            if transaction.transaction_status == TransactionStatusEnum.SUSPENDED:
                from services.transaction_finalizer import (
                    is_resume_too_stale,
                    finalize_stopped_transaction,
                )
                is_stale, gap = await is_resume_too_stale(transaction)
                if is_stale:
                    logger.warning(
                        f"⏰ Refusing to resume stale transaction {transaction_id} "
                        f"via MeterValues — gap={gap:.0f}s exceeds MAX_RESUME_GAP_SECONDS"
                    )
                    safe_create_task(log_audit_event(
                        action="transaction.resume_blocked",
                        entity_type="transaction",
                        entity_id=transaction_id,
                        actor_type="system",
                        changes={
                            "trigger": "MeterValues",
                            "gap_seconds": gap,
                            "reason": "STALE_RECONNECT",
                        },
                    ))
                    await finalize_stopped_transaction(transaction, "STALE_RECONNECT")
                    return call_result.MeterValues()

                now = datetime.datetime.now(datetime.timezone.utc)
                transaction.transaction_status = TransactionStatusEnum.RUNNING
                transaction.resumed_at = now
                transaction.resume_count = (transaction.resume_count or 0) + 1
                await transaction.save()
                logger.info(f"▶️ Auto-resumed transaction {transaction_id} via MeterValues (resume_count={transaction.resume_count})")
                safe_create_task(log_audit_event(
                    action="transaction.resumed",
                    entity_type="transaction",
                    entity_id=transaction_id,
                    actor_type="ocpp",
                    changes={
                        "previous_status": "SUSPENDED",
                        "new_status": "RUNNING",
                        "trigger": "MeterValues",
                        "resume_count": transaction.resume_count,
                    },
                ))

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
                        logger.error(f"🔋   ❌ Error parsing {measurand} value '{value}': {e}", exc_info=True)
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

            # Check QR session budget and auto-stop if needed
            if meter_records_created > 0 and meter_data.get('reading_kwh') is not None:
                try:
                    from services.qr_payment_service import QRPaymentService
                    await QRPaymentService.check_budget_and_auto_stop(transaction_id, meter_data['reading_kwh'])
                except Exception as qr_err:
                    logger.warning(f"QR budget check failed (non-fatal): {qr_err}")

            # Check zero-energy watchdog (stalled charging detection)
            if meter_records_created > 0 and meter_data.get('reading_kwh') is not None:
                try:
                    from services.zero_energy_watchdog import check_zero_energy
                    await check_zero_energy(transaction_id, meter_data['reading_kwh'], transaction.start_time)
                except Exception as ze_err:
                    logger.warning(f"Zero-energy check failed (non-fatal): {ze_err}")

            # Cancel socket grace period if MeterValues arrived (charger is alive)
            try:
                grace_data = await redis_manager.get_socket_grace_period(self.id)
                if grace_data:
                    logger.info(f"MeterValues received during socket grace period for {self.id} — cancelling")
                    await redis_manager.delete_socket_grace_period(self.id)
            except Exception as e:
                logger.debug(f"Grace period check error (non-fatal): {e}")

            return call_result.MeterValues()
            
        except Exception as e:
            logger.error(f"🔋 ❌ FATAL ERROR processing meter values for {self.id}: {e}", exc_info=True)
            return call_result.MeterValues()

    @on('FirmwareStatusNotification')
    async def on_firmware_status_notification(self, status: str, **kwargs):
        """
        OCPP 1.6 FirmwareStatusNotification handler
        Charger sends this to report firmware update progress
        """
        # Record metric
        await OCPPMetrics.record_message("FirmwareStatusNotification", "IN")

        logger.info(f"📦 FirmwareStatusNotification from {self.id}: status={status}")

        from models import Charger, FirmwareUpdate, FirmwareFile

        try:
            # Get charger from database
            charger = await Charger.get(charge_point_string_id=self.id)

            # Find the most recent active update for this charger
            # Note: With new schema, each charger+firmware combo has one row
            # Only one should be "active" (in progress) at a time per charger
            firmware_update = await FirmwareUpdate.filter(
                charger_id=charger.id,
                status__in=["PENDING", "DOWNLOADING", "DOWNLOADED", "INSTALLING"]
            ).order_by('-started_at', '-initiated_at').first()

            if not firmware_update:
                logger.warning(
                    f"📦 No active firmware update found for {self.id}, "
                    f"but received FirmwareStatusNotification: {status}"
                )
                return call_result.FirmwareStatusNotification()

            # Map OCPP status to our database status
            status_mapping = {
                "Idle": "PENDING",
                "Downloading": "DOWNLOADING",
                "Downloaded": "DOWNLOADED",
                "Installing": "INSTALLING",
                "Installed": "INSTALLED",
                "DownloadFailed": "DOWNLOAD_FAILED",
                "InstallationFailed": "INSTALLATION_FAILED",
                "InstallVerificationFailed": "INSTALLATION_FAILED"
            }

            new_status = status_mapping.get(status, status)
            firmware_update.status = new_status

            # Track timestamps
            if status == "Downloading" and not firmware_update.started_at:
                firmware_update.started_at = datetime.datetime.now(datetime.timezone.utc)
                logger.info(f"📦 ✅ Firmware download started for {self.id}")

            elif status in ["Installed", "DownloadFailed", "InstallationFailed", "InstallVerificationFailed"]:
                firmware_update.completed_at = datetime.datetime.now(datetime.timezone.utc)

                if status == "Installed":
                    # Update success - update charger's firmware version
                    firmware_file = await firmware_update.firmware_file
                    charger.firmware_version = firmware_file.version
                    await charger.save()
                    logger.info(f"📦 ✅ Firmware update completed for {self.id} - new version: {firmware_file.version}")
                else:
                    # Update failed
                    firmware_update.error_message = f"Firmware update failed with status: {status}"
                    logger.error(f"📦 ❌ Firmware update failed for {self.id} with status: {status}")

            await firmware_update.save()

            # Log to OCPP logs for audit trail
            await OCPPLog.create(
                charge_point_id=self.id,
                message_type="FirmwareStatusNotification",
                direction="IN",
                payload={"status": status},
                status="SUCCESS",
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )

            logger.info(f"📦 Updated firmware_update ID={firmware_update.id} to status={new_status}")

        except Exception as e:
            logger.error(f"📦 ❌ Error processing FirmwareStatusNotification from {self.id}: {e}", exc_info=True)

        return call_result.FirmwareStatusNotification()

    @on('DataTransfer')
    async def on_data_transfer(self, vendor_id: str, message_id: str = None, data: str = None, **kwargs):
        """
        OCPP 1.6 DataTransfer handler
        Handles vendor-specific data messages from chargers
        Currently supports: JET_EV1 Signal Quality data
        """
        # Record metric
        await OCPPMetrics.record_message("DataTransfer", "IN")

        logger.info(f"📡 DataTransfer from {self.id}: vendorId={vendor_id}, messageId={message_id}")

        from models import Charger, SignalQuality, OCPPLog
        import json

        try:
            # Route by messageId (vendor-agnostic)
            if message_id == "SignalQuality":
                return await self._handle_signal_quality(data)
            elif message_id == "GetLastMeterValue":
                return await self._handle_get_last_meter_value(data)
            else:
                logger.warning(f"📡 Unhandled DataTransfer from {self.id}: vendorId={vendor_id}, messageId={message_id}")
                return call_result.DataTransfer(status="UnknownMessageId")

        except Exception as e:
            logger.error(f"📡 ❌ Error processing DataTransfer from {self.id}: {e}", exc_info=True)
            return call_result.DataTransfer(status="Rejected")

    async def _handle_signal_quality(self, data: str):
        """
        Handle SignalQuality DataTransfer messages (vendor-agnostic)
        Data format: {"rssi":22,"ber":99,"timestamp":"86"}
        """
        from models import Charger, SignalQuality
        import json

        try:
            # Parse JSON data
            if not data:
                logger.error(f"📡 ❌ No data provided in SignalQuality message from {self.id}")
                return call_result.DataTransfer(status="Rejected")

            payload = json.loads(data)
            rssi = payload.get("rssi")
            ber = payload.get("ber")
            timestamp = payload.get("timestamp")

            # Validate required fields
            if rssi is None or ber is None:
                logger.error(f"📡 ❌ Missing required fields (rssi/ber) in SignalQuality data from {self.id}")
                return call_result.DataTransfer(status="Rejected")

            # Validate RSSI range (0-31 for GSM, 99 for unknown)
            if not (0 <= rssi <= 31 or rssi == 99):
                logger.warning(f"📡 ⚠️  RSSI value {rssi} out of typical range for {self.id}")

            # Validate BER range (0-7 for GSM, 99 for unknown/not detectable)
            if not (0 <= ber <= 7 or ber == 99):
                logger.warning(f"📡 ⚠️  BER value {ber} out of typical range for {self.id}")

            # Get charger
            charger = await Charger.get(charge_point_string_id=self.id)

            # Store signal quality data
            await SignalQuality.create(
                charger=charger,
                rssi=rssi,
                ber=ber,
                timestamp=str(timestamp) if timestamp is not None else ""
            )

            # Log success
            signal_strength = "Good" if rssi >= 10 else "Fair" if rssi >= 5 else "Poor" if rssi > 0 else "Unknown"
            logger.info(f"📶 Stored signal quality for {self.id}: RSSI={rssi} ({signal_strength}), BER={ber}")

            return call_result.DataTransfer(status="Accepted")

        except json.JSONDecodeError as e:
            logger.error(f"📡 ❌ Invalid JSON in SignalQuality data from {self.id}: {e}", exc_info=True)
            return call_result.DataTransfer(status="Rejected")
        except Exception as e:
            logger.error(f"📡 ❌ Error storing SignalQuality for {self.id}: {e}", exc_info=True)
            return call_result.DataTransfer(status="Rejected")

    async def _handle_get_last_meter_value(self, data: str):
        """
        Handle GetLastMeterValue DataTransfer — allows charger to resume a transaction
        after power loss by retrieving the server's last known meter reading.

        Request data: {"transactionId": 42}
        Response data: {"transactionId":42,"startMeterValueWh":10000,"lastMeterValueWh":15340,"energyConsumedWh":5340}
        """
        from models import Charger, Transaction, TransactionStatusEnum, MeterValue

        try:
            if not data:
                logger.error(f"📡 ❌ No data in GetLastMeterValue from {self.id}")
                return call_result.DataTransfer(
                    status="Rejected",
                    data=json.dumps({"error": "No data provided"})
                )

            payload = json.loads(data)
            transaction_id = payload.get("transactionId")

            if transaction_id is None:
                logger.error(f"📡 ❌ Missing transactionId in GetLastMeterValue from {self.id}")
                return call_result.DataTransfer(
                    status="Rejected",
                    data=json.dumps({"error": "Missing transactionId"})
                )

            # Look up transaction
            transaction = await Transaction.filter(id=transaction_id).prefetch_related("charger").first()

            if not transaction:
                logger.error(f"📡 ❌ Transaction {transaction_id} not found for GetLastMeterValue from {self.id}")
                return call_result.DataTransfer(
                    status="Rejected",
                    data=json.dumps({"error": "Transaction not found"})
                )

            # Validate ownership — transaction must belong to this charger
            if transaction.charger.charge_point_string_id != self.id:
                logger.error(f"📡 ❌ Transaction {transaction_id} belongs to {transaction.charger.charge_point_string_id}, not {self.id}")
                return call_result.DataTransfer(
                    status="Rejected",
                    data=json.dumps({"error": "Transaction does not belong to this charger"})
                )

            # Must be in SUSPENDED state
            if transaction.transaction_status != TransactionStatusEnum.SUSPENDED:
                logger.error(f"📡 ❌ Transaction {transaction_id} is {transaction.transaction_status}, not SUSPENDED")
                return call_result.DataTransfer(
                    status="Rejected",
                    data=json.dumps({"error": f"Transaction is {transaction.transaction_status}, not SUSPENDED"})
                )

            # Staleness guard — refuse resume if last activity is too old
            from services.transaction_finalizer import (
                is_resume_too_stale,
                finalize_stopped_transaction,
            )
            is_stale, gap = await is_resume_too_stale(transaction)
            if is_stale:
                logger.warning(
                    f"⏰ Refusing to resume stale transaction {transaction_id} via "
                    f"GetLastMeterValue — gap={gap:.0f}s"
                )
                safe_create_task(log_audit_event(
                    action="transaction.resume_blocked",
                    entity_type="transaction",
                    entity_id=transaction_id,
                    actor_type="system",
                    changes={
                        "trigger": "GetLastMeterValue",
                        "gap_seconds": gap,
                        "reason": "STALE_RECONNECT",
                    },
                ))
                await finalize_stopped_transaction(transaction, "STALE_RECONNECT")
                return call_result.DataTransfer(
                    status="Rejected",
                    data=json.dumps({"error": "Transaction expired due to long disconnect"})
                )

            # Get last meter value (fall back to start_meter_kwh)
            latest_meter_value = await MeterValue.filter(
                transaction_id=transaction_id
            ).order_by("-created_at").first()

            start_meter_kwh = transaction.start_meter_kwh or 0
            last_meter_kwh = latest_meter_value.reading_kwh if latest_meter_value else start_meter_kwh
            energy_consumed_kwh = last_meter_kwh - start_meter_kwh

            # Convert to Wh (integers) for charger
            start_meter_wh = int(round(start_meter_kwh * 1000))
            last_meter_wh = int(round(last_meter_kwh * 1000))
            energy_consumed_wh = int(round(energy_consumed_kwh * 1000))

            # Resume: SUSPENDED → RUNNING
            now = datetime.datetime.now(datetime.timezone.utc)
            transaction.transaction_status = TransactionStatusEnum.RUNNING
            transaction.resumed_at = now
            transaction.resume_count = (transaction.resume_count or 0) + 1
            await transaction.save()

            logger.info(
                f"▶️ Resumed transaction {transaction_id} via GetLastMeterValue: "
                f"startWh={start_meter_wh}, lastWh={last_meter_wh}, energyWh={energy_consumed_wh}, "
                f"resume_count={transaction.resume_count}"
            )

            safe_create_task(log_audit_event(
                action="transaction.resumed",
                entity_type="transaction",
                entity_id=transaction_id,
                actor_type="ocpp",
                changes={
                    "previous_status": "SUSPENDED",
                    "new_status": "RUNNING",
                    "trigger": "GetLastMeterValue",
                    "resume_count": transaction.resume_count,
                },
            ))

            response_data = json.dumps({
                "transactionId": transaction_id,
                "startMeterValueWh": start_meter_wh,
                "lastMeterValueWh": last_meter_wh,
                "energyConsumedWh": energy_consumed_wh,
            })

            return call_result.DataTransfer(status="Accepted", data=response_data)

        except json.JSONDecodeError as e:
            logger.error(f"📡 ❌ Invalid JSON in GetLastMeterValue from {self.id}: {e}", exc_info=True)
            return call_result.DataTransfer(
                status="Rejected",
                data=json.dumps({"error": "Invalid JSON"})
            )
        except Exception as e:
            logger.error(f"📡 ❌ Error handling GetLastMeterValue from {self.id}: {e}", exc_info=True)
            return call_result.DataTransfer(status="Rejected")

# Backward-compatible shim: routers do `from main import send_ocpp_request`
async def send_ocpp_request(charge_point_id: str, action: str, payload: Dict = None):
    return await connection_manager.send_ocpp_request(charge_point_id, action, payload)

# ============ Health Check Endpoint ============
@app.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring systems
    Checks database and Redis connectivity
    """
    import time
    from starlette.responses import Response
    start_time = time.time()

    health_status = {
        "status": "healthy",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "checks": {}
    }

    # Check database
    try:
        from models import Charger
        await Charger.all().limit(1)
        health_status["checks"]["database"] = {
            "status": "healthy",
            "message": "Database connection OK"
        }
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "message": f"Database error: {str(e)}"
        }

    # Check Redis
    try:
        await redis_manager.redis_client.ping()
        health_status["checks"]["redis"] = {
            "status": "healthy",
            "message": "Redis connection OK"
        }
    except Exception as e:
        health_status["checks"]["redis"] = {
            "status": "degraded",
            "message": f"Redis error: {str(e)} (non-critical)"
        }

    # Add response time
    health_status["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

    # Return appropriate status code
    if health_status["status"] == "unhealthy":
        return Response(
            content=json.dumps(health_status),
            status_code=503,
            media_type="application/json"
        )

    return health_status

# ============ Include Routers ============
app.include_router(stations.router)
app.include_router(chargers.router)
app.include_router(transactions.router)
app.include_router(auth.router)
app.include_router(webhooks.router)
app.include_router(wallet_payments.router)
app.include_router(users.router)
# Map router must be registered before public_stations so
# /api/public/stations/map matches before /{station_id} catch-all
from routers import public_station_map
app.include_router(public_station_map.router)
app.include_router(public_stations.router)
app.include_router(logs.router)
app.include_router(firmware.router)
app.include_router(firmware.public_router)

from routers import qr_codes, public_qr_transactions
app.include_router(qr_codes.router)
app.include_router(public_qr_transactions.router)

from routers import franchisees, franchisee_portal, invoices
app.include_router(franchisees.router)
app.include_router(franchisee_portal.router)
app.include_router(invoices.router)

# OCPP WebSocket endpoint (connection management + message handling)
from routers import ocpp_ws
app.include_router(ocpp_ws.router)

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
async def get_connected_charge_points(admin_user=Depends(require_admin())):
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
async def send_command_to_charge_point(charge_point_id: str, command: OCPPCommand, admin_user=Depends(require_admin())):
    """Send OCPP command to a specific charge point"""
    success, result = await connection_manager.send_ocpp_request(charge_point_id, command.action, command.payload)
    
    if success:
        return OCPPResponse(
            success=True,
            message=f"Command {command.action} sent successfully",
            data=result.dict() if hasattr(result, 'dict') else str(result)
        )
    else:
        raise HTTPException(status_code=400, detail=result)

@app.get("/api/logs", response_model=List[MessageLogResponse])
async def get_message_logs(limit: int = Query(100, ge=1, le=10000), admin_user=Depends(require_admin())):
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
async def get_charge_point_logs(charge_point_id: str, limit: int = Query(100, ge=1, le=10000), admin_user=Depends(require_admin())):
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
    await init_db()
    await redis_manager.connect()

    # Ensure system guest user exists for QR payment fallback
    from services.qr_payment_service import ensure_guest_user
    try:
        await ensure_guest_user()
    except Exception as e:
        logger.warning(f"Failed to ensure guest user (non-fatal): {e}")

    logger.info("Admin panel available at /admin")

    # Start periodic cleanup task for stale connections
    connection_manager.start_cleanup_task()

    # Start billing retry service
    from services.billing_retry_service import start_billing_retry_service
    await start_billing_retry_service()

    # Start firmware update service (process pending firmware updates)
    from services.firmware_update_service import start_firmware_update_service
    await start_firmware_update_service()

    # Register disconnect handler (suspend transactions when charger disconnects)
    from services.disconnect_handler import (
        suspend_transactions_on_disconnect,
        sweep_stale_suspended_transactions,
    )
    connection_manager.register_on_disconnect(suspend_transactions_on_disconnect)
    await sweep_stale_suspended_transactions()

    # Start data retention service (cleanup old signal quality data & OCPP logs)
    from services.data_retention_service import start_data_retention_service
    retention_days = int(os.environ.get("RETENTION_DAYS", "90"))
    cleanup_interval_hours = int(os.environ.get("CLEANUP_INTERVAL_HOURS", "24"))
    await start_data_retention_service(retention_days=retention_days, cleanup_interval_hours=cleanup_interval_hours)

    logger.info("Database initialized with Tortoise ORM")
    logger.info("Redis connection established")
    logger.info("Periodic cleanup task started")
    logger.info("OCPP Central System API started")
    logger.info("REST API available at: /api/")
    logger.info("API Documentation available at: /docs")
    logger.info("OCPP WebSocket available at: /ocpp/{charge_point_id}")

    # Record initial metrics
    await OCPPMetrics.record_active_connections(0)

    # Log monitoring status
    if os.getenv("NEW_RELIC_MONITOR_MODE", "false").lower() == "true":
        logger.info("✅ New Relic APM: ENABLED")
    else:
        logger.info("ℹ️ New Relic APM: DISABLED")

    if os.getenv("SENTRY_ENABLED", "false").lower() == "true":
        logger.info("✅ Sentry Error Tracking: ENABLED")
    else:
        logger.info("ℹ️ Sentry Error Tracking: DISABLED")

@app.on_event("shutdown")
async def shutdown_event():
    """Close database and Redis connections on shutdown"""
    # Cancel cleanup task
    await connection_manager.stop_cleanup_task()
    
    # Stop billing retry service
    from services.billing_retry_service import stop_billing_retry_service
    await stop_billing_retry_service()

    # Stop firmware update service
    from services.firmware_update_service import stop_firmware_update_service
    await stop_firmware_update_service()

    # Stop data retention service
    from services.data_retention_service import stop_data_retention_service
    await stop_data_retention_service()

    await close_db()
    await redis_manager.disconnect()
    logger.info("Database and Redis connections closed")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=debug)