# services/monitoring_service.py
"""
Monitoring service for New Relic APM, Sentry, and custom metrics
Provides centralized monitoring initialization and metric tracking for OCPP server
"""
import os
import logging
from typing import Optional, Dict, Any
from functools import wraps
import asyncio

logger = logging.getLogger(__name__)

# Global flags
_monitoring_initialized = False
_newrelic_enabled = False
_sentry_enabled = False


def initialize_monitoring():
    """
    Initialize New Relic APM and Sentry error tracking
    Call this BEFORE creating the FastAPI app instance
    """
    global _monitoring_initialized, _newrelic_enabled, _sentry_enabled

    if _monitoring_initialized:
        logger.warning("Monitoring already initialized")
        return

    environment = os.getenv("ENVIRONMENT", "development")

    # ==================== NEW RELIC APM ====================
    newrelic_monitor_mode = os.getenv("NEW_RELIC_MONITOR_MODE", "false").lower() == "true"
    newrelic_license_key = os.getenv("NEW_RELIC_LICENSE_KEY")

    if newrelic_monitor_mode and newrelic_license_key:
        try:
            import newrelic.agent

            # Initialize with environment variables (no ini file needed)
            newrelic.agent.initialize()

            _newrelic_enabled = True
            logger.info(f"✅ New Relic APM initialized for {environment} environment")

        except ImportError:
            logger.warning("⚠️ New Relic package not installed. Install with: pip install newrelic")
        except Exception as e:
            logger.error(f"❌ Failed to initialize New Relic: {e}")
    else:
        logger.info(f"ℹ️ New Relic APM disabled (monitor_mode={newrelic_monitor_mode}, license_key={'set' if newrelic_license_key else 'not set'})")

    # ==================== SENTRY ERROR TRACKING ====================
    sentry_enabled = os.getenv("SENTRY_ENABLED", "false").lower() == "true"
    sentry_dsn = os.getenv("SENTRY_DSN")

    if sentry_enabled and sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration
            from sentry_sdk.integrations.asyncio import AsyncioIntegration
            from sentry_sdk.integrations.redis import RedisIntegration
            from sentry_sdk.integrations.logging import LoggingIntegration

            # Get configuration from environment
            sentry_environment = os.getenv("SENTRY_ENVIRONMENT", environment)
            traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
            profiles_sample_rate = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1"))

            sentry_sdk.init(
                dsn=sentry_dsn,
                environment=sentry_environment,

                # Integrations
                integrations=[
                    FastApiIntegration(transaction_style="endpoint"),
                    StarletteIntegration(transaction_style="endpoint"),
                    AsyncioIntegration(),
                    RedisIntegration(),
                    LoggingIntegration(
                        level=logging.INFO,  # Capture info and above
                        event_level=logging.ERROR  # Send errors to Sentry
                    ),
                ],

                # Performance monitoring
                traces_sample_rate=traces_sample_rate,
                profiles_sample_rate=profiles_sample_rate,

                # Error filtering
                ignore_errors=[
                    KeyboardInterrupt,
                    asyncio.CancelledError,
                ],

                # Release tracking (use git commit hash in production)
                release=os.getenv("GIT_COMMIT", "dev"),

                # Additional options
                attach_stacktrace=True,
                send_default_pii=False,  # Don't send PII automatically
                max_breadcrumbs=50,
            )

            _sentry_enabled = True
            logger.info(f"✅ Sentry initialized for {sentry_environment} environment (traces: {traces_sample_rate*100}%, profiles: {profiles_sample_rate*100}%)")

        except ImportError:
            logger.warning("⚠️ Sentry SDK not installed. Install with: pip install sentry-sdk")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Sentry: {e}")
    else:
        logger.info(f"ℹ️ Sentry disabled (enabled={sentry_enabled}, dsn={'set' if sentry_dsn else 'not set'})")

    _monitoring_initialized = True


# ==================== CUSTOM METRICS ====================

class MetricsCollector:
    """Collect and send custom metrics to New Relic"""

    @staticmethod
    def record_metric(name: str, value: float, tags: Optional[Dict[str, Any]] = None):
        """
        Record a custom metric to New Relic

        Args:
            name: Metric name (e.g., "Custom/OCPP/ActiveConnections")
            value: Metric value
            tags: Optional dictionary of tags/attributes
        """
        if not _newrelic_enabled:
            return

        try:
            import newrelic.agent
            newrelic.agent.record_custom_metric(name, value, application=newrelic.agent.application())
        except Exception as e:
            logger.debug(f"Failed to record metric {name}: {e}")

    @staticmethod
    def record_event(event_type: str, params: Dict[str, Any]):
        """
        Record a custom event to New Relic

        Args:
            event_type: Event type (e.g., "OCPPTransaction")
            params: Event parameters/attributes
        """
        if not _newrelic_enabled:
            return

        try:
            import newrelic.agent
            newrelic.agent.record_custom_event(event_type, params, application=newrelic.agent.application())
        except Exception as e:
            logger.debug(f"Failed to record event {event_type}: {e}")

    @staticmethod
    def increment_counter(name: str, value: int = 1, tags: Optional[Dict[str, Any]] = None):
        """
        Increment a counter metric

        Args:
            name: Counter name (e.g., "Custom/OCPP/Messages/Heartbeat")
            value: Increment amount (default: 1)
            tags: Optional tags
        """
        MetricsCollector.record_metric(name, value, tags)

    @staticmethod
    def record_gauge(name: str, value: float, tags: Optional[Dict[str, Any]] = None):
        """
        Record a gauge metric (point-in-time value)

        Args:
            name: Gauge name (e.g., "Custom/OCPP/ActiveTransactions")
            value: Current value
            tags: Optional tags
        """
        MetricsCollector.record_metric(name, value, tags)


# ==================== INSTRUMENTATION DECORATORS ====================

def trace_transaction(name: Optional[str] = None, group: str = "Python/OCPP"):
    """
    Decorator to trace a function/method as a New Relic transaction

    Usage:
        @trace_transaction(name="OCPP/StartTransaction")
        async def on_start_transaction(self, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not _newrelic_enabled:
                return await func(*args, **kwargs)

            try:
                import newrelic.agent
                transaction_name = name or f"{group}/{func.__name__}"

                with newrelic.agent.BackgroundTask(newrelic.agent.application(), transaction_name, group=group):
                    return await func(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Tracing failed for {func.__name__}: {e}")
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not _newrelic_enabled:
                return func(*args, **kwargs)

            try:
                import newrelic.agent
                transaction_name = name or f"{group}/{func.__name__}"

                with newrelic.agent.BackgroundTask(newrelic.agent.application(), transaction_name, group=group):
                    return func(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Tracing failed for {func.__name__}: {e}")
                return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def trace_function(name: Optional[str] = None):
    """
    Decorator to trace a function as a segment within a transaction

    Usage:
        @trace_function(name="calculate_billing")
        async def calculate_billing_amount(...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not _newrelic_enabled:
                return await func(*args, **kwargs)

            try:
                import newrelic.agent
                function_name = name or func.__name__

                with newrelic.agent.FunctionTrace(name=function_name):
                    return await func(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Function trace failed for {func.__name__}: {e}")
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not _newrelic_enabled:
                return func(*args, **kwargs)

            try:
                import newrelic.agent
                function_name = name or func.__name__

                with newrelic.agent.FunctionTrace(name=function_name):
                    return func(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Function trace failed for {func.__name__}: {e}")
                return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


# ==================== SENTRY HELPERS ====================

class SentryHelper:
    """Helper functions for Sentry error tracking"""

    @staticmethod
    def set_user_context(user_id: str, email: Optional[str] = None, clerk_user_id: Optional[str] = None):
        """
        Set user context for Sentry error tracking

        Args:
            user_id: User ID
            email: User email (optional)
            clerk_user_id: Clerk user ID (optional)
        """
        if not _sentry_enabled:
            return

        try:
            import sentry_sdk
            sentry_sdk.set_user({
                "id": user_id,
                "email": email,
                "clerk_user_id": clerk_user_id,
            })
        except Exception as e:
            logger.debug(f"Failed to set Sentry user context: {e}")

    @staticmethod
    def set_transaction_context(transaction_id: int, charger_id: str, user_id: Optional[int] = None):
        """
        Set OCPP transaction context for Sentry

        Args:
            transaction_id: Transaction ID
            charger_id: Charge point ID
            user_id: User ID (optional)
        """
        if not _sentry_enabled:
            return

        try:
            import sentry_sdk
            sentry_sdk.set_context("ocpp_transaction", {
                "transaction_id": transaction_id,
                "charger_id": charger_id,
                "user_id": user_id,
            })
        except Exception as e:
            logger.debug(f"Failed to set Sentry transaction context: {e}")

    @staticmethod
    def set_context(name: str, context: Dict[str, Any]):
        """
        Set custom context for Sentry

        Args:
            name: Context name
            context: Context data
        """
        if not _sentry_enabled:
            return

        try:
            import sentry_sdk
            sentry_sdk.set_context(name, context)
        except Exception as e:
            logger.debug(f"Failed to set Sentry context: {e}")

    @staticmethod
    def add_breadcrumb(category: str, message: str, level: str = "info", data: Optional[Dict] = None):
        """
        Add a breadcrumb for Sentry error context

        Args:
            category: Breadcrumb category (e.g., "ocpp.message")
            message: Breadcrumb message
            level: Level (debug, info, warning, error)
            data: Additional data
        """
        if not _sentry_enabled:
            return

        try:
            import sentry_sdk
            sentry_sdk.add_breadcrumb(
                category=category,
                message=message,
                level=level,
                data=data or {}
            )
        except Exception as e:
            logger.debug(f"Failed to add Sentry breadcrumb: {e}")

    @staticmethod
    def capture_exception(exception: Exception, extra: Optional[Dict] = None):
        """
        Manually capture an exception to Sentry

        Args:
            exception: Exception to capture
            extra: Extra context data
        """
        if not _sentry_enabled:
            return

        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                if extra:
                    for key, value in extra.items():
                        scope.set_extra(key, value)
                sentry_sdk.capture_exception(exception)
        except Exception as e:
            logger.debug(f"Failed to capture exception to Sentry: {e}")


# ==================== OCPP-SPECIFIC METRICS ====================

class OCPPMetrics:
    """OCPP-specific metrics collection"""

    @staticmethod
    async def record_active_connections(count: int):
        """Record active charger connection count"""
        MetricsCollector.record_gauge("Custom/OCPP/ActiveConnections", float(count))

    @staticmethod
    async def record_message(message_type: str, direction: str):
        """
        Record OCPP message

        Args:
            message_type: OCPP message type (e.g., "Heartbeat", "StartTransaction")
            direction: "IN" or "OUT"
        """
        metric_name = f"Custom/OCPP/Messages/{direction}/{message_type}"
        MetricsCollector.increment_counter(metric_name)

    @staticmethod
    async def record_transaction_started(charger_id: str, user_id: int):
        """Record transaction start event"""
        MetricsCollector.increment_counter("Custom/OCPP/Transactions/Started")
        MetricsCollector.record_event("OCPPTransactionStarted", {
            "charger_id": charger_id,
            "user_id": user_id,
        })

    @staticmethod
    async def record_transaction_completed(transaction_id: int, energy_kwh: float, duration_minutes: float):
        """Record transaction completion"""
        MetricsCollector.increment_counter("Custom/OCPP/Transactions/Completed")
        MetricsCollector.record_metric("Custom/OCPP/Energy/Consumed", energy_kwh)
        MetricsCollector.record_event("OCPPTransactionCompleted", {
            "transaction_id": transaction_id,
            "energy_kwh": energy_kwh,
            "duration_minutes": duration_minutes,
        })

    @staticmethod
    async def record_transaction_failed(transaction_id: int, reason: str):
        """Record transaction failure"""
        MetricsCollector.increment_counter("Custom/OCPP/Transactions/Failed")
        MetricsCollector.record_event("OCPPTransactionFailed", {
            "transaction_id": transaction_id,
            "reason": reason,
        })

    @staticmethod
    async def record_heartbeat_timeout(charger_id: str):
        """Record heartbeat timeout"""
        MetricsCollector.increment_counter("Custom/OCPP/Heartbeat/Timeouts")
        MetricsCollector.record_event("OCPPHeartbeatTimeout", {
            "charger_id": charger_id,
        })

    @staticmethod
    async def record_websocket_connection(charger_id: str, success: bool):
        """Record WebSocket connection attempt"""
        metric_name = "Custom/OCPP/WebSocket/Connected" if success else "Custom/OCPP/WebSocket/Rejected"
        MetricsCollector.increment_counter(metric_name)

    @staticmethod
    async def record_billing_amount(amount: float):
        """Record billing amount"""
        MetricsCollector.record_metric("Custom/OCPP/Billing/Amount", amount)
