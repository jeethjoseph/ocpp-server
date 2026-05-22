"""WalletSessionService — budget cap + auto-stop for wallet-paid sessions.

Mirror of `QRPaymentService.check_budget_and_auto_stop`. When a wallet user
starts a charging session, we snapshot their available balance into Redis
(`wallet_session:{transaction_id}`). On every MeterValues frame, we
recompute the session's accumulated cost from kWh + tariff and compare it
to the snapshot. When cost >= snapshot, we schedule a RemoteStopTransaction
via `safe_create_task` so the charger stops *before* the wallet ledger
goes negative.

Why `safe_create_task` and not `await`: this runs inside the MeterValues
OCPP handler, which has not yet sent its CALLRESULT. Awaiting an outbound
RemoteStopTransaction here would deadlock the OCPP session. Scheduling
the stop as a background task lets the MeterValues CALLRESULT return
immediately while the stop is dispatched asynchronously.

At-least-once dispatch: if a MeterValues frame past the budget fires a
stop and the stop is lost (process crash, network failure, charger
unreachable), the next MeterValues frame re-evaluates the same condition
and re-dispatches. Energy consumed is monotonic so once cost ≥ budget the
condition stays true. RemoteStop is idempotent at the charger; duplicate
dispatches are harmless. The Redis key is deleted on StopTransaction.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from core.roles import INTERNAL_ROLES
from models import Transaction, User, Wallet
from services.wallet_service import WalletService
from services.monitoring_service import MetricsCollector
from redis_manager import redis_manager
from core.connection_manager import connection_manager
from utils import safe_create_task

logger = logging.getLogger(__name__)


class WalletSessionService:
    """Mirror of QRPaymentService's budget-check pattern, for wallet sessions."""

    @staticmethod
    async def cache_session_on_start(
        transaction_id: int,
        wallet: Wallet,
        tariff,
        start_meter_kwh: float,
        charger_id: int,
    ) -> bool:
        """Snapshot the wallet's available balance into Redis at session start.

        Called from the StartTransaction handler when the id_tag resolves
        to a wallet user (not QR, not internal-role admin/franchisee).
        Failure to cache is non-fatal — the session continues; only the
        in-session budget cap is forfeited.
        """
        if not tariff or not tariff.rate_per_kwh:
            logger.warning(
                f"Wallet session cache skipped for txn {transaction_id}: no tariff"
            )
            return False

        # Internal-role skip — ADR 0004. Sessions initiated by ADMIN or
        # FRANCHISEE users are purely operational, no budget cap. The
        # MeterValues budget check naturally short-circuits because no
        # `wallet_session:{txn_id}` cache row exists. See CONTEXT.md
        # "Internal-role Session."
        user = await User.filter(id=wallet.user_id).first()
        if user and user.role in INTERNAL_ROLES:
            MetricsCollector.increment_counter("Custom/WalletSession/InternalRoleSkipped")
            logger.info(
                f"Wallet session cache skipped for txn {transaction_id}: "
                f"internal-role ({user.role.value}) session per policy"
            )
            return False

        balance = await WalletService.get_balance(wallet.id)
        budget_limit_paise = int(
            (balance * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

        session_data = {
            "wallet_id": wallet.id,
            "budget_limit_paise": budget_limit_paise,
            "tariff_rate": float(tariff.rate_per_kwh),
            "gst_percent": float(tariff.gst_percent),
            "start_meter_kwh": float(start_meter_kwh) if start_meter_kwh else 0.0,
            "charger_id": charger_id,
        }
        success = await redis_manager.set_wallet_session(transaction_id, session_data)
        if success:
            logger.info(
                f"Cached wallet session for txn {transaction_id}, "
                f"budget=₹{balance:.2f} (wallet_id={wallet.id})"
            )
            MetricsCollector.increment_counter("Custom/Wallet/SessionBudgetCached")
        return success

    @staticmethod
    async def check_balance_and_auto_stop(transaction_id: int, reading_kwh: float):
        """Recompute session cost and schedule RemoteStopTransaction if budget hit.

        Mirror of `QRPaymentService.check_budget_and_auto_stop`. Includes a
        DB-fallback rebuild path so a server restart mid-session doesn't
        forfeit the budget cap (the wallet user is resolved from the
        transaction, balance is re-read via the ledger, payload re-cached).
        """
        session = await redis_manager.get_wallet_session(transaction_id)

        if not session:
            # Cache miss — likely a server restart. Rebuild from the DB.
            session = await WalletSessionService._rebuild_session_from_db(transaction_id)
            if not session:
                return  # Not a wallet session (probably QR or internal-role)

        budget_limit = Decimal(session["budget_limit_paise"]) / Decimal("100")
        tariff_rate = Decimal(str(session["tariff_rate"]))
        gst_percent = Decimal(str(session.get("gst_percent", 18.0)))
        start_meter = Decimal(str(session["start_meter_kwh"]))

        if tariff_rate <= 0:
            return

        energy_consumed = Decimal(str(reading_kwh)) - start_meter
        gst_multiplier = Decimal("1") + (gst_percent / Decimal("100"))
        cost = (energy_consumed * tariff_rate * gst_multiplier).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        remaining = budget_limit - cost

        logger.info(
            f"Wallet budget check txn {transaction_id}: "
            f"energy={energy_consumed:.3f}kWh, cost=₹{cost:.2f} (incl GST {gst_percent}%), "
            f"budget=₹{budget_limit:.2f}, remaining=₹{remaining:.2f}"
        )

        if cost >= budget_limit:
            logger.info(
                f"Wallet session budget exceeded for txn {transaction_id}: "
                f"cost=₹{cost:.2f} >= budget=₹{budget_limit:.2f}, "
                "scheduling RemoteStopTransaction"
            )
            MetricsCollector.increment_counter("Custom/Wallet/SessionBudgetExceeded")

            transaction = await Transaction.filter(
                id=transaction_id
            ).prefetch_related("charger").first()
            if transaction:
                # Flag-less, at-least-once dispatch. Matches QRPaymentService
                # at qr_payment_service.py:561-576. Energy consumed is
                # monotonic so once cost ≥ budget the condition stays true
                # on every subsequent MeterValues frame — any lost stop
                # self-heals on the next tick. RemoteStop is idempotent at
                # the charger; duplicate dispatches are harmless.
                safe_create_task(
                    WalletSessionService._send_remote_stop(transaction, transaction_id)
                )

    @staticmethod
    async def _rebuild_session_from_db(transaction_id: int):
        """Reconstruct the session payload after a Redis cache miss.

        Only returns a session dict if the transaction belongs to a wallet
        user (has a wallet, not a QR-payment-linked session). Internal-role
        users (ADMIN/FRANCHISEE) are still cached — the budget check just
        prevents them from charging past their own wallet balance, which
        is desirable.
        """
        transaction = await Transaction.filter(
            id=transaction_id
        ).prefetch_related("charger").first()
        if not transaction:
            return None

        # Skip if this is a QR session (the QR cache will handle it)
        from models import QRPayment
        qr = await QRPayment.filter(transaction_id=transaction_id).first()
        if qr:
            return None

        wallet = await Wallet.filter(user_id=transaction.user_id).first()
        if not wallet:
            return None

        tariff = await WalletService.get_applicable_tariff(transaction.charger_id)
        if not tariff:
            return None

        balance = await WalletService.get_balance(wallet.id)
        budget_limit_paise = int(
            (balance * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        session = {
            "wallet_id": wallet.id,
            "budget_limit_paise": budget_limit_paise,
            "tariff_rate": float(tariff.rate_per_kwh),
            "gst_percent": float(tariff.gst_percent),
            "start_meter_kwh": float(transaction.start_meter_kwh) if transaction.start_meter_kwh else 0.0,
            "charger_id": transaction.charger_id,
        }
        await redis_manager.set_wallet_session(transaction_id, session)
        logger.info(
            f"Rebuilt wallet session cache for txn {transaction_id} after miss"
        )
        MetricsCollector.increment_counter("Custom/Wallet/SessionRebuildFromDB")
        return session

    @staticmethod
    async def _send_remote_stop(transaction, transaction_id: int):
        """Send RemoteStopTransaction as a background task (avoids MeterValues deadlock)."""
        try:
            success, result = await connection_manager.send_ocpp_request(
                transaction.charger.charge_point_string_id,
                "RemoteStopTransaction",
                {"transaction_id": transaction_id},
            )
            if success:
                logger.info(f"Auto-stop sent for wallet session txn {transaction_id}")
                MetricsCollector.increment_counter("Custom/Wallet/SessionAutoStopDispatched")
            else:
                logger.error(
                    f"Failed to auto-stop wallet session txn {transaction_id}: {result}"
                )
                MetricsCollector.increment_counter("Custom/Wallet/SessionAutoStopFailed")
        except Exception as e:
            logger.error(
                f"Error sending auto-stop for wallet session txn {transaction_id}: {e}"
            )
            MetricsCollector.increment_counter("Custom/Wallet/SessionAutoStopFailed")
