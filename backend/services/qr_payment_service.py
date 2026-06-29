"""QR Payment Service - Core business logic for appless EV charging via Razorpay UPI QR"""
import os
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import NamedTuple, Optional, Tuple, Dict

from tortoise.transactions import in_transaction

from core.config import RAZORPAY_PLATFORM_FEE_PERCENT  # noqa: F401  (re-exported for backwards compat)
from models import (
    User, Wallet, Charger, Transaction, QRPayment, ChargerQRCode, MeterValue,
    QRPaymentStatusEnum, AuthProviderEnum, ChargerStatusEnum,
    TransactionStatusEnum, UserRoleEnum
)


class BudgetSnapshot(NamedTuple):
    """Pure-read budget figures for a QR session, in ₹ (Decimal).

    Returned by ``QRPaymentService.compute_budget_snapshot`` for both the
    auto-stop dispatch path and the admin transaction-detail response.
    """
    budget_limit: Decimal
    cost_so_far: Decimal
    remaining: Decimal


class ParsedQRWebhook(NamedTuple):
    """Fields lifted out of a ``qr_code.credited`` webhook payload, used to
    build the QRPayment row regardless of which branch (stale / rejected /
    accepted) handles it."""
    payment_id: Optional[str]
    amount_paid: Decimal
    vpa: Optional[str]
    contact: Optional[str]
    customer_name: Optional[str]
    qr_code_id: str
    fee_fields: Dict
from services.razorpay_service import (
    razorpay_service,
    RazorpayAlreadyRefundedError,
    RazorpayRefundBelowMinimumError,
    RazorpayIdempotencyConflictError,
    extract_fee_from_payment,
)
from services.tariff_utils import synthetic_platform_fee, synthetic_fee_split
from services.wallet_service import WalletService
from services.billing_rules import (
    MIN_BILLABLE_ENERGY_KWH,
    is_zero_energy,
    is_fault_refund,
)
from services.monitoring_service import MetricsCollector
from redis_manager import redis_manager
from core.connection_manager import connection_manager
from crud import log_audit_event
from utils import safe_create_task, mask_vpa, mask_phone, mask_payment_id, mask_email

logger = logging.getLogger(__name__)

# QR-specific configuration. The project-level RAZORPAY_PLATFORM_FEE_PERCENT
# lives in core.config; see the import above.
QR_PAYMENT_PENDING_TIMEOUT = int(os.getenv("QR_PAYMENT_PENDING_TIMEOUT", "300"))

SYSTEM_GUEST_EMAIL = "guest@system.powerlync.com"

# Canonical, non-retryable failure_reason for a refund that hit a Razorpay
# idempotency conflict (HTTP 409) AND had no existing refund to reconcile to.
# The BillingRetryService sweep excludes this marker — a same-key retry can
# never clear the conflict, so hammering it just generates noise.
IDEMPOTENCY_CONFLICT_NO_REFUND = "idempotency_conflict_no_refund"

# Canonical failure_reason for a refund below Razorpay's ₹1.00 floor. Permanent
# (the floor will not change). Older rows predate this marker and carry the
# long-form RazorpayRefundBelowMinimumError text instead — both are matched by
# is_retryable_refund_failure() so neither is ever retried.
BELOW_MINIMUM_REASON = "below_razorpay_minimum"


def is_below_minimum_reason(failure_reason: Optional[str]) -> bool:
    """True if a failure_reason marks Razorpay's sub-₹1 floor — the canonical
    marker OR the legacy long-form text ("... below Razorpay minimum (₹1.00) ...").
    This is a *benign* terminal state (the customer consumed all but a sub-rupee
    remainder Razorpay cannot refund), NOT an operational failure. Substring-
    based, not exact-match, so legacy/variant wording is still caught."""
    if not failure_reason:
        return False
    fr = failure_reason.lower()
    return fr == BELOW_MINIMUM_REASON or "below razorpay minimum" in fr


def is_retryable_refund_failure(failure_reason: Optional[str]) -> bool:
    """Whether a REFUND_FAILED row is worth another BillingRetryService attempt.

    Permanently-stuck reasons return False so the sweep stops hammering them:
      - below Razorpay's ₹1 floor (see is_below_minimum_reason)
      - an idempotency conflict with no existing refund to reconcile to
    Everything else (transient API/network errors, empty reason) is retryable.
    """
    if not failure_reason:
        return True
    if failure_reason.lower() == IDEMPOTENCY_CONFLICT_NO_REFUND:
        return False
    if is_below_minimum_reason(failure_reason):
        return False
    return True


def build_refund_call_kwargs(qr_payment: QRPayment, refund_amount: Decimal) -> Dict:
    """Deterministic Razorpay refund-request kwargs for a QR payment.

    Idempotency: staging and prod share ONE Razorpay LIVE account (QR needs
    live mode). A key derived from the per-database PK (``qr_payment_{id}``)
    collides across environments — both envs eventually refund the same
    integer id with different bodies, so Razorpay returns HTTP 409 "Different
    request with the same idempotency key has already been processed."
    ``razorpay_payment_id`` is globally unique across the account, so a key
    built from it never collides.

    The body (amount + notes + speed) is built purely from the row so the
    original attempt and every BillingRetryService retry send a byte-identical
    request for the same payment: a same-key, same-body call replays the
    original refund (HTTP 200) instead of returning 409. Notes are kept minimal
    and deterministic for the same reason — variable text (transaction reason,
    "Retry:" prefix) would change the body and re-trigger 409.

    Speed: full refunds (service not rendered) request instant payout per
    ADR 0002; partial unused-credit refunds use normal speed. Derived from the
    amount so the retry path reproduces the original speed without extra state.
    """
    instant_enabled = os.getenv(
        "RAZORPAY_INSTANT_REFUND_ENABLED", "true"
    ).lower() == "true"
    is_full_refund = refund_amount >= qr_payment.amount_paid
    return {
        "amount": refund_amount,
        "notes": {"qr_payment_id": str(qr_payment.id)},
        "idempotency_key": f"refund_{qr_payment.razorpay_payment_id}",
        "speed": "optimum" if (instant_enabled and is_full_refund) else None,
    }


_REFUND_MAX_CONCURRENCY = int(os.getenv("REFUND_MAX_CONCURRENCY", "3"))
_refund_sem = None
_refund_sem_loop = None


def _refund_semaphore() -> asyncio.Semaphore:
    """Bound the number of in-flight Razorpay refund calls (defense-in-depth: a
    provider latency spike can't pile up unbounded outbound requests). Created
    lazily per running event loop so the test suite's per-test loops don't trip
    'bound to a different event loop'. See ADR 0018."""
    global _refund_sem, _refund_sem_loop
    loop = asyncio.get_running_loop()
    if _refund_sem is None or _refund_sem_loop is not loop:
        _refund_sem = asyncio.Semaphore(_REFUND_MAX_CONCURRENCY)
        _refund_sem_loop = loop
    return _refund_sem


async def _ensure_actual_fee_captured(qr_payment: QRPayment) -> None:
    """Side-effect writer: ensure the actual Razorpay fee lives on the row.

    Priority for sourcing the actual fee: existing stored value (webhook/api) >
    Razorpay API fetch > 2% estimate fallback. Updates `qr_payment.platform_fee`,
    `razorpay_commission`, `razorpay_gst`, and `fee_source` in place; caller must
    save. Used only for ops/reconciliation. NEVER drives customer-facing math —
    see ADR 0001.
    """
    if qr_payment.fee_source in ("webhook", "api") and qr_payment.platform_fee is not None:
        return

    fee_data = await razorpay_service.fetch_payment_fees(qr_payment.razorpay_payment_id)
    if fee_data:
        total_fee, tax = fee_data
        qr_payment.platform_fee = total_fee
        qr_payment.razorpay_commission = total_fee - tax
        qr_payment.razorpay_gst = tax
        qr_payment.fee_source = "api"
        return

    # Fallback when Razorpay neither delivered the fee in the webhook nor
    # exposes it via the payment-fetch API — estimate using the same synthetic
    # split so the row stays internally consistent.
    estimated = synthetic_platform_fee(qr_payment.amount_paid)
    commission, gst_on_fee = synthetic_fee_split(qr_payment.amount_paid)
    qr_payment.platform_fee = estimated
    qr_payment.razorpay_commission = commission
    qr_payment.razorpay_gst = gst_on_fee
    qr_payment.fee_source = "estimated"


async def ensure_guest_user():
    """Create or find the system guest user for fallback scenarios"""
    guest = await User.filter(email=SYSTEM_GUEST_EMAIL).first()
    if not guest:
        rfid_card_id = str(uuid.uuid4()).replace('-', '')[:20]
        guest = await User.create(
            email=SYSTEM_GUEST_EMAIL,
            full_name="Guest User",
            role=UserRoleEnum.USER,
            auth_provider=AuthProviderEnum.UPI_GUEST,
            is_active=True,
            rfid_card_id=rfid_card_id,
            preferred_language="en",
            notification_preferences="{}",
        )
        await Wallet.create(user=guest)
        logger.info("System guest user created")
    else:
        logger.info("System guest user already exists")
    return guest


async def find_or_create_user_from_payment(
    phone: Optional[str],
    vpa: Optional[str],
    name: Optional[str]
) -> User:
    """
    Find or create a user from QR payment webhook data.
    Priority: phone match -> VPA match -> create new UPI_GUEST -> system guest
    """
    # 1. Try phone lookup (existing app user)
    if phone:
        user = await User.filter(phone_number=phone, is_active=True).first()
        if user:
            # Update VPA on existing user if not set
            if vpa and not user.upi_vpa:
                user.upi_vpa = vpa
                await user.save()
            logger.info(f"Found existing user by phone: {mask_email(user.email)} (id={user.id})")
            return user

    # 2. Try VPA lookup (repeat QR customer)
    if vpa:
        user = await User.filter(upi_vpa=vpa, is_active=True).first()
        if user:
            # Update phone if now available
            if phone and not user.phone_number:
                user.phone_number = phone
                await user.save()
            logger.info(f"Found existing user by VPA: {mask_email(user.email)} (id={user.id})")
            return user

    # 3. Create new UPI_GUEST user
    if vpa or phone:
        email = f"upi_{vpa or phone}@guest.powerlync.com"
        # Check if email already exists (shouldn't, but be safe)
        existing = await User.filter(email=email).first()
        if existing:
            return existing

        rfid_card_id = str(uuid.uuid4()).replace('-', '')[:20]
        user = await User.create(
            email=email,
            full_name=name or (vpa or phone),
            phone_number=phone,
            upi_vpa=vpa,
            role=UserRoleEnum.USER,
            auth_provider=AuthProviderEnum.UPI_GUEST,
            is_active=True,
            rfid_card_id=rfid_card_id,
            preferred_language="en",
            notification_preferences="{}",
        )
        await Wallet.create(user=user)
        logger.info(f"Created UPI_GUEST user: {mask_email(email)} (id={user.id})")
        return user

    # 4. Fallback to system guest
    guest = await User.filter(email=SYSTEM_GUEST_EMAIL).first()
    if not guest:
        guest = await ensure_guest_user()
    logger.info("Using system guest user (no phone or VPA)")
    return guest


class QRPaymentService:
    """Service for handling QR-based appless charging payments"""

    @staticmethod
    def _parse_qr_webhook(webhook_data: Dict) -> ParsedQRWebhook:
        """Lift the QR-payment fields out of the raw ``qr_code.credited``
        webhook payload (payment id, amount, customer identity, qr code id and
        the actual-fee fields). Pure parsing — no DB or network."""
        payment_entity = webhook_data.get("payment", {}).get("entity", {})
        qr_code_entity = webhook_data.get("qr_code", {}).get("entity", {})

        amount_paid = Decimal(str(payment_entity.get("amount", 0))) / 100
        notes = payment_entity.get("notes", {})
        if not isinstance(notes, dict):
            notes = {}
        customer_name = notes.get("customer_name") or payment_entity.get("email")
        qr_code_id = qr_code_entity.get("id") or payment_entity.get(
            "description", ""
        ).split("|")[-1].strip()

        fee_fields = {}
        fee_data = extract_fee_from_payment(payment_entity)
        if fee_data:
            total_fee, tax = fee_data
            fee_fields = {
                "platform_fee": total_fee,
                "razorpay_commission": total_fee - tax,
                "razorpay_gst": tax,
                "fee_source": "webhook",
            }

        return ParsedQRWebhook(
            payment_id=payment_entity.get("id"),
            amount_paid=amount_paid,
            vpa=payment_entity.get("vpa"),
            contact=payment_entity.get("contact"),
            customer_name=customer_name,
            qr_code_id=qr_code_id,
            fee_fields=fee_fields,
        )

    @staticmethod
    def _qr_payment_create_kwargs(
        parsed: ParsedQRWebhook, charger_qr: ChargerQRCode, user: User,
        charger: Charger, webhook_data: Dict, **overrides,
    ) -> Dict:
        """Shared kwargs for ``QRPayment.create`` across the stale, rejected and
        accepted branches. ``overrides`` supplies the branch-specific status /
        failure_reason."""
        return {
            "charger": charger,
            "charger_qr_code": charger_qr,
            "user": user,
            "razorpay_payment_id": parsed.payment_id,
            "razorpay_qr_code_id": parsed.qr_code_id,
            "amount_paid": parsed.amount_paid,
            "customer_vpa": parsed.vpa,
            "customer_name": parsed.customer_name,
            "customer_contact": parsed.contact,
            "metadata": webhook_data,
            **parsed.fee_fields,
            **overrides,
        }

    @staticmethod
    async def _handle_stale_payment(
        parsed: ParsedQRWebhook, webhook_data: Dict, payment_created_at,
    ) -> Optional[Dict]:
        """If the payment is older than the pending timeout the customer has
        long gone — record + immediately refund. Returns a status dict when the
        stale path handled it, or None to fall through to normal processing."""
        if not payment_created_at:
            return None
        payment_time = datetime.fromtimestamp(payment_created_at, tz=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - payment_time).total_seconds()
        if age_seconds <= QR_PAYMENT_PENDING_TIMEOUT:
            return None

        logger.warning(
            "Stale QR payment %s: %.0fs old (threshold %ss), refunding",
            mask_payment_id(parsed.payment_id), age_seconds, QR_PAYMENT_PENDING_TIMEOUT,
        )
        # Still need to look up charger for the record
        charger_qr = await ChargerQRCode.filter(
            razorpay_qr_code_id=parsed.qr_code_id
        ).prefetch_related("charger").first()
        if not charger_qr:
            logger.error(f"No ChargerQRCode for stale payment {mask_payment_id(parsed.payment_id)}")
            return {"status": "error", "reason": "QR code not found"}

        user = await find_or_create_user_from_payment(
            parsed.contact, parsed.vpa, parsed.customer_name
        )
        qr_payment = await QRPayment.create(
            **QRPaymentService._qr_payment_create_kwargs(
                parsed, charger_qr, user, charger_qr.charger, webhook_data,
                status=QRPaymentStatusEnum.EXPIRED,
                failure_reason=f"Stale webhook: payment was {age_seconds:.0f}s old",
            )
        )
        await QRPaymentService._full_refund(qr_payment, "Stale payment - webhook delayed")
        return {"status": "refunded_stale", "qr_payment_id": qr_payment.id}

    @staticmethod
    async def _resolve_active_charger_qr(qr_code_id: str) -> Optional[ChargerQRCode]:
        """Look up the active ChargerQRCode for a qr_code_id, logging the two
        distinct miss causes (cross-env noise vs a customer paying on an
        inactive/closed QR). Returns None on any miss."""
        charger_qr = await ChargerQRCode.filter(
            razorpay_qr_code_id=qr_code_id, is_active=True
        ).prefetch_related("charger").first()
        if charger_qr:
            return charger_qr

        # Two very different causes. If NO row exists for this qr_code_id,
        # it's the other environment's QR (staging and prod share one
        # Razorpay live account) — expected noise, log at info. But if a
        # row DOES exist and is merely inactive, the QR is OURS (closed or
        # regenerated) and a customer just paid on a dead QR → they get no
        # session. That is real and customer-impacting: keep it at error.
        exists_inactive = await ChargerQRCode.filter(
            razorpay_qr_code_id=qr_code_id
        ).exists()
        if exists_inactive:
            logger.error(f"Payment on INACTIVE ChargerQRCode qr_code_id={qr_code_id} — customer paid on a closed/regenerated QR, no session created")
        else:
            logger.info(f"No ChargerQRCode for qr_code_id={qr_code_id} (likely cross-environment webhook)")
        return None

    @staticmethod
    async def _create_qr_payment_locked(
        parsed: ParsedQRWebhook, charger_qr: ChargerQRCode, charger: Charger,
        user: User, webhook_data: Dict,
    ) -> Tuple[Optional[QRPayment], Optional[int]]:
        """Atomic double-payment guard: lock the Charger row and either create
        an accepted PAID QRPayment or, if the charger is busy, a rejected FAILED
        one. Returns ``(qr_payment, None)`` on accept or ``(None, rejected_id)``
        on rejection. The rejected payment is refunded by the caller outside the
        lock (the Razorpay call is slow)."""
        async with in_transaction():
            locked_charger = await Charger.select_for_update().get(id=charger.id)

            active_txn = await Transaction.filter(
                charger=locked_charger,
                transaction_status__in=[
                    TransactionStatusEnum.RUNNING,
                    TransactionStatusEnum.STARTED,
                    TransactionStatusEnum.PENDING_START,
                ]
            ).first()
            pending_qr = await QRPayment.filter(
                charger=locked_charger,
                status=QRPaymentStatusEnum.PAID,
                transaction_id__isnull=True,
            ).first()

            if active_txn or pending_qr:
                reason = (
                    f"Active transaction {active_txn.id}"
                    if active_txn
                    else f"Pending QR payment {pending_qr.id} already waiting"
                )
                logger.warning(
                    "qr_payment_rejected reason=charger_busy charger_id=%s payment_id=%s detail=%s",
                    locked_charger.id, mask_payment_id(parsed.payment_id), reason,
                )
                rejected = await QRPayment.create(
                    **QRPaymentService._qr_payment_create_kwargs(
                        parsed, charger_qr, user, locked_charger, webhook_data,
                        status=QRPaymentStatusEnum.FAILED,
                        failure_reason="Concurrent payment rejected — charger busy",
                    )
                )
                return None, rejected.id

            qr_payment = await QRPayment.create(
                **QRPaymentService._qr_payment_create_kwargs(
                    parsed, charger_qr, user, locked_charger, webhook_data,
                    status=QRPaymentStatusEnum.PAID,
                )
            )
            return qr_payment, None

    @staticmethod
    async def _dispatch_charging(
        charger: Charger, user: User, qr_payment: QRPayment,
    ) -> None:
        """Decide what to do with an accepted PAID payment: start now, wait for
        plug-in, or refund if the charger is offline."""
        # Socket chargers may remain Available (no CP signal for Preparing)
        from services.charger_type_service import is_socket_charger as _is_socket
        is_connected = await redis_manager.is_charger_connected(charger.charge_point_string_id)
        start_statuses = {ChargerStatusEnum.PREPARING}
        if await _is_socket(charger.charge_point_string_id):
            start_statuses.add(ChargerStatusEnum.AVAILABLE)

        if charger.latest_status in start_statuses and is_connected:
            # Start charging immediately
            await QRPaymentService._start_charging(charger, user, qr_payment)
        elif is_connected:
            # Charger connected but not Preparing - wait for plug
            logger.info(f"Charger {charger.id} status is {charger.latest_status}, waiting for Preparing")
            safe_create_task(QRPaymentService.handle_payment_without_plug(charger.id, qr_payment.id))
        else:
            # Charger not connected
            logger.warning(f"Charger {charger.id} not connected, refunding")
            qr_payment.status = QRPaymentStatusEnum.FAILED
            qr_payment.failure_reason = "Charger not connected"
            await qr_payment.save()
            await QRPaymentService._full_refund(qr_payment, "Charger not connected")

    @staticmethod
    async def handle_qr_payment(webhook_data: Dict) -> Dict:
        """
        Handle qr_code.credited webhook: validate, find user, start charging.
        Returns a status dict for logging.
        """
        parsed = QRPaymentService._parse_qr_webhook(webhook_data)

        logger.info(
            "QR payment received: payment_id=%s amount=₹%s qr_code=%s vpa=%s",
            mask_payment_id(parsed.payment_id), parsed.amount_paid,
            parsed.qr_code_id, mask_vpa(parsed.vpa),
        )

        # Idempotency check
        existing = await QRPayment.filter(razorpay_payment_id=parsed.payment_id).first()
        if existing:
            logger.info(f"Duplicate webhook for payment {mask_payment_id(parsed.payment_id)}, skipping")
            return {"status": "duplicate", "qr_payment_id": existing.id}

        # Staleness check — if payment is older than the pending timeout,
        # the user has long gone. Create record and refund immediately.
        stale_result = await QRPaymentService._handle_stale_payment(
            parsed, webhook_data,
            webhook_data.get("payment", {}).get("entity", {}).get("created_at"),
        )
        if stale_result is not None:
            return stale_result

        # Look up ChargerQRCode
        charger_qr = await QRPaymentService._resolve_active_charger_qr(parsed.qr_code_id)
        if not charger_qr:
            return {"status": "error", "reason": "QR code not found or inactive"}

        charger = charger_qr.charger

        # Find or create user
        user = await find_or_create_user_from_payment(
            parsed.contact, parsed.vpa, parsed.customer_name
        )

        qr_payment, rejection_qr_payment_id = await QRPaymentService._create_qr_payment_locked(
            parsed, charger_qr, charger, user, webhook_data,
        )

        # Refund rejected payment outside the lock (Razorpay call is slow)
        if rejection_qr_payment_id is not None:
            rejected = await QRPayment.get(id=rejection_qr_payment_id)
            await QRPaymentService._full_refund(rejected, "Concurrent payment rejected — charger busy")
            return {"status": "failed", "reason": "active_transaction", "qr_payment_id": rejection_qr_payment_id}

        await QRPaymentService._dispatch_charging(charger, user, qr_payment)
        return {"status": "processed", "qr_payment_id": qr_payment.id}

    MAX_START_RETRIES = 2
    START_RETRY_DELAY = 5  # seconds

    @staticmethod
    async def _start_charging(charger: Charger, user: User, qr_payment: QRPayment):
        """Send RemoteStartTransaction to charger with retry on communication failure"""
        # Guard against concurrent calls (e.g. handle_payment_without_plug + direct path)
        if qr_payment.status != QRPaymentStatusEnum.PAID:
            logger.warning(f"QR payment {qr_payment.id} status is {qr_payment.status.value}, skipping _start_charging")
            return

        try:
            id_tag = user.rfid_card_id
            if not id_tag:
                id_tag = str(uuid.uuid4()).replace('-', '')[:20]
                user.rfid_card_id = id_tag
                await user.save()

            result = None
            for attempt in range(1, QRPaymentService.MAX_START_RETRIES + 1):
                logger.info(f"Sending RemoteStartTransaction to {charger.charge_point_string_id} (attempt {attempt}/{QRPaymentService.MAX_START_RETRIES})")

                success, result = await connection_manager.send_ocpp_request(
                    charger.charge_point_string_id,
                    "RemoteStartTransaction",
                    {"id_tag": id_tag, "connector_id": 1}
                )

                if success:
                    status_value = str(getattr(result, 'status', '')).lower()
                    if status_value == "accepted":
                        logger.info(f"RemoteStartTransaction accepted for charger {charger.id}")
                        return  # Success — done
                    else:
                        # Charger explicitly rejected — no point retrying
                        logger.warning(f"RemoteStartTransaction rejected: {result}")
                        break

                # Communication failure — retry if attempts remain
                if attempt < QRPaymentService.MAX_START_RETRIES:
                    logger.warning(f"RemoteStart attempt {attempt} failed: {result}, retrying in {QRPaymentService.START_RETRY_DELAY}s")
                    await asyncio.sleep(QRPaymentService.START_RETRY_DELAY)

                    # Check if transaction already started despite the timeout
                    # (e.g. AT command corrupted the response but charger started anyway)
                    await qr_payment.refresh_from_db()
                    if qr_payment.status == QRPaymentStatusEnum.CHARGING:
                        logger.info(f"QR payment {qr_payment.id} already linked to transaction (status=CHARGING), skipping retry")
                        return
                else:
                    logger.error(f"RemoteStart failed after {QRPaymentService.MAX_START_RETRIES} attempts: {result}")

            # All attempts failed or rejected — refund
            qr_payment.status = QRPaymentStatusEnum.FAILED
            qr_payment.failure_reason = f"RemoteStart failed: {result}"
            await qr_payment.save()
            await QRPaymentService._full_refund(qr_payment, "RemoteStart failed")

        except Exception as e:
            logger.error(f"Error starting charging for QR payment {qr_payment.id}: {e}", exc_info=True)
            qr_payment.status = QRPaymentStatusEnum.FAILED
            qr_payment.failure_reason = str(e)
            await qr_payment.save()
            await QRPaymentService._full_refund(qr_payment, f"Start error: {e}")

    @staticmethod
    async def handle_payment_without_plug(charger_id: int, qr_payment_id: int):
        """Wait for charger to enter a startable state, then start. Timeout -> refund."""
        from services.charger_type_service import is_socket_charger as _is_socket
        timeout = QR_PAYMENT_PENDING_TIMEOUT
        poll_interval = 10
        elapsed = 0

        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            charger = await Charger.filter(id=charger_id).first()
            qr_payment = await QRPayment.filter(id=qr_payment_id).first()

            if not charger or not qr_payment:
                return
            if qr_payment.status != QRPaymentStatusEnum.PAID:
                return  # Already handled

            # Socket chargers may stay Available (no CP signal for Preparing)
            start_statuses = {ChargerStatusEnum.PREPARING}
            if await _is_socket(charger.charge_point_string_id):
                start_statuses.add(ChargerStatusEnum.AVAILABLE)

            if charger.latest_status in start_statuses:
                user = await User.filter(id=qr_payment.user_id).first()
                if user:
                    await QRPaymentService._start_charging(charger, user, qr_payment)
                return

        # Timeout - refund
        qr_payment = await QRPayment.filter(id=qr_payment_id).first()
        if qr_payment and qr_payment.status == QRPaymentStatusEnum.PAID:
            logger.info(f"QR payment {qr_payment_id} timed out waiting for plug-in, refunding")
            qr_payment.status = QRPaymentStatusEnum.EXPIRED
            qr_payment.failure_reason = "Charger not in startable state within timeout"
            await qr_payment.save()
            await QRPaymentService._full_refund(qr_payment, "Plug-in timeout")

    @staticmethod
    async def link_transaction_to_qr_payment(transaction_id: int, charger_id: int, user_id: int):
        """Called from on_start_transaction to link a QR payment to the new transaction."""
        qr_payment = await QRPayment.filter(
            charger_id=charger_id,
            user_id=user_id,
            status=QRPaymentStatusEnum.PAID,
            transaction_id=None,
        ).order_by("-created_at").first()

        if not qr_payment:
            return None

        qr_payment.transaction_id = transaction_id
        qr_payment.status = QRPaymentStatusEnum.CHARGING

        # Cache session data in Redis for MeterValues budget check
        tariff = await WalletService.get_applicable_tariff(charger_id)
        tariff_rate = tariff.rate_per_kwh if tariff else Decimal('0')
        gst_percent = tariff.gst_percent if tariff else Decimal('18')
        # Budget cap uses the synthetic platform fee, not the actual Razorpay
        # fee — see ADR 0001. Customers get a predictable contract regardless
        # of Razorpay's pricing of the moment.
        platform_fee = synthetic_platform_fee(qr_payment.amount_paid)
        await _ensure_actual_fee_captured(qr_payment)
        # Store budget as an integer paise value — Decimal money should
        # never round-trip through float in Redis. Consumers read this
        # back as Decimal via ``Decimal(...) / Decimal("100")``.
        budget_limit_paise = int(
            ((qr_payment.amount_paid - platform_fee) * Decimal("100"))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        await qr_payment.save()

        transaction = await Transaction.filter(id=transaction_id).first()

        # Decimal fields are serialized as strings (not float) so reads round-trip
        # without precision loss. Readers parse via `Decimal(value)`. Legacy
        # in-flight cache rows (pre-2026-05-21) wrote floats — readers continue
        # to accept those via `Decimal(str(value))` for one TTL window.
        session_data = {
            "qr_payment_id": qr_payment.id,
            "amount_paid": str(qr_payment.amount_paid),
            "platform_fee": str(platform_fee),
            "budget_limit_paise": budget_limit_paise,
            "tariff_rate": str(tariff_rate),
            "gst_percent": str(gst_percent),
            "start_meter_kwh": str(transaction.start_meter_kwh) if transaction and transaction.start_meter_kwh else "0",
            "charger_id": charger_id,
        }
        await redis_manager.set_qr_session(transaction_id, session_data)

        budget_rupees = Decimal(budget_limit_paise) / Decimal("100")
        logger.info(f"Linked QR payment {qr_payment.id} to transaction {transaction_id}, budget_limit=₹{budget_rupees}")
        return qr_payment

    @staticmethod
    async def _load_or_rebuild_qr_session(transaction_id: int) -> Optional[Dict]:
        """Return the Redis ``qr_session:{txn}`` row, rebuilding from DB on
        cache miss. Returns None when the transaction has no associated
        ``CHARGING`` ``QRPayment`` row (i.e. not a QR session).

        Extracted so both the auto-stop dispatch path and the read-only admin
        snapshot share the same cache-miss recovery without duplicating it.
        """
        session = await redis_manager.get_qr_session(transaction_id)
        if session:
            return session

        # DB fallback for cache miss (e.g., server restart). Log so ops can
        # detect Redis blips / TTL exhaustion / operator-edits-mid-session.
        logger.warning(
            "qr_session cache miss for txn %s — rebuilding from DB. "
            "If frequent, indicates Redis instability or TTL exhaustion.",
            transaction_id,
        )
        MetricsCollector.increment_counter("Custom/QrSession/BudgetCheckCacheMiss")

        qr_payment = await QRPayment.filter(
            transaction_id=transaction_id,
            status=QRPaymentStatusEnum.CHARGING,
        ).first()
        if not qr_payment:
            return None

        tariff = await WalletService.get_applicable_tariff(qr_payment.charger_id)
        tariff_rate = tariff.rate_per_kwh if tariff else Decimal('0')
        gst_percent = tariff.gst_percent if tariff else Decimal('18')
        platform_fee = synthetic_platform_fee(qr_payment.amount_paid)
        await _ensure_actual_fee_captured(qr_payment)
        await qr_payment.save()
        budget_limit_paise = int(
            ((qr_payment.amount_paid - platform_fee) * Decimal("100"))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

        transaction = await Transaction.filter(id=transaction_id).first()
        session = {
            "qr_payment_id": qr_payment.id,
            "amount_paid": str(qr_payment.amount_paid),
            "platform_fee": str(platform_fee),
            "budget_limit_paise": budget_limit_paise,
            "tariff_rate": str(tariff_rate),
            "gst_percent": str(gst_percent),
            "start_meter_kwh": str(transaction.start_meter_kwh) if transaction and transaction.start_meter_kwh else "0",
            "charger_id": qr_payment.charger_id,
        }
        await redis_manager.set_qr_session(transaction_id, session)
        return session

    @staticmethod
    async def compute_budget_snapshot(
        transaction_id: int,
        reading_kwh: Optional[Decimal] = None,
    ) -> Optional[BudgetSnapshot]:
        """Pure-read budget figures for a QR session.

        Returns None when the transaction is not a QR session (no CHARGING
        QRPayment row) or when the tariff rate is non-positive (config bug —
        the auto-stop path bails on the same condition).

        ``reading_kwh`` is the meter reading to compute cost against. If None,
        the latest ``MeterValue`` row for the transaction is used; if no
        MeterValue exists yet, cost is zero and ``remaining == budget_limit``.

        Pure: no Redis writes, no RemoteStop dispatch. Safe to call from any
        read path (e.g., the admin transaction-detail endpoint).
        """
        session = await QRPaymentService._load_or_rebuild_qr_session(transaction_id)
        if not session:
            return None

        if "budget_limit_paise" in session:
            budget_limit = Decimal(session["budget_limit_paise"]) / Decimal("100")
        else:
            # Legacy float key — drains within one TTL window post-2026-05-21.
            budget_limit = Decimal(str(session["budget_limit"]))
        tariff_rate = Decimal(str(session["tariff_rate"]))
        gst_percent = Decimal(str(session.get("gst_percent", 18.0)))
        start_meter = Decimal(str(session["start_meter_kwh"]))

        if tariff_rate <= 0:
            return None

        if reading_kwh is None:
            latest = await MeterValue.filter(
                transaction_id=transaction_id
            ).order_by("-id").first()
            reading_dec = Decimal(latest.reading_kwh) if latest else start_meter
        else:
            reading_dec = Decimal(str(reading_kwh))

        energy_consumed = reading_dec - start_meter
        gst_multiplier = Decimal("1") + (gst_percent / Decimal("100"))
        cost = (energy_consumed * tariff_rate * gst_multiplier).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        remaining = budget_limit - cost
        return BudgetSnapshot(
            budget_limit=budget_limit, cost_so_far=cost, remaining=remaining,
        )

    @staticmethod
    async def check_budget_and_auto_stop(
        transaction_id: int, reading_kwh: float, power_kw: Optional[float] = None,
    ):
        """Check if QR session has exceeded budget and auto-stop if needed.

        Also stamps the latest meter snapshot (`latest_reading_kwh`,
        `latest_power_kw`, `latest_meter_at`) into the qr_session Redis row so
        the `/api/public/qr-active-sessions` endpoint can serve live KPIs
        without an extra MeterValue DB lookup per session (review item #4,
        2026-05-22). `power_kw` is optional — older callers that don't pass it
        leave the previous snapshot's value in place.
        """
        snapshot = await QRPaymentService.compute_budget_snapshot(
            transaction_id, reading_kwh=Decimal(str(reading_kwh)),
        )
        if snapshot is None:
            return

        # Re-read the session row that the helper just populated/loaded.
        # We need the dict to stamp the latest-meter snapshot below; the
        # helper intentionally doesn't return it (purity over convenience).
        session = await redis_manager.get_qr_session(transaction_id)
        if not session:
            return

        # Stamp the latest snapshot into the cache so the active-sessions
        # endpoint can render live KPIs without a per-row MeterValue lookup.
        session["latest_reading_kwh"] = str(Decimal(str(reading_kwh)))
        if power_kw is not None:
            session["latest_power_kw"] = float(power_kw)
        session["latest_meter_at"] = datetime.now(timezone.utc).isoformat()
        await redis_manager.set_qr_session(transaction_id, session)

        cost = snapshot.cost_so_far
        budget_limit = snapshot.budget_limit
        remaining = snapshot.remaining
        gst_percent = Decimal(str(session.get("gst_percent", 18.0)))
        start_meter = Decimal(str(session["start_meter_kwh"]))
        energy_consumed = Decimal(str(reading_kwh)) - start_meter
        logger.info(
            f"QR budget check txn {transaction_id}: "
            f"energy={energy_consumed:.3f}kWh, cost=₹{cost:.2f} (incl GST {gst_percent}%), "
            f"budget=₹{budget_limit:.2f}, remaining=₹{remaining:.2f}"
        )

        if cost >= budget_limit:
            logger.info(
                f"QR session budget exceeded for txn {transaction_id}: "
                f"cost=₹{cost:.2f} >= budget=₹{budget_limit:.2f}, scheduling RemoteStopTransaction"
            )

            transaction = await Transaction.filter(id=transaction_id).prefetch_related("charger").first()
            if transaction:
                # Schedule as background task — do NOT await here.
                # This runs inside the MeterValues handler; awaiting would deadlock
                # because the CALLRESULT hasn't been sent yet. Use ``safe_create_task``
                # so a failing auto-stop is logged rather than dropped silently
                # (the budget-exceeded session would otherwise keep charging).
                safe_create_task(
                    QRPaymentService._send_remote_stop(transaction, transaction_id)
                )

    @staticmethod
    async def _send_remote_stop(transaction, transaction_id: int):
        """Send RemoteStopTransaction as a background task (avoids MeterValues deadlock)."""
        try:
            success, result = await connection_manager.send_ocpp_request(
                transaction.charger.charge_point_string_id,
                "RemoteStopTransaction",
                {"transaction_id": transaction_id}
            )
            if success:
                logger.info(f"Auto-stop sent for QR session txn {transaction_id}")
            else:
                logger.error(f"Failed to auto-stop QR session txn {transaction_id}: {result}")
        except Exception as e:
            logger.error(f"Error sending auto-stop for QR session txn {transaction_id}: {e}")

    @staticmethod
    async def _refund_if_non_billable(
        qr_payment: QRPayment, transaction: Transaction, energy_kwh,
    ) -> bool:
        """Route the two non-billable bands to a full refund. Returns True when
        a full refund was issued (caller must stop), False to keep billing.

        Non-billable bands (full refund, no GST invoice / settlement). The
        over-payment formula in the billing path is correct only when a billable
        service was delivered, so route these to _full_refund (handles audit +
        instant speed=optimum). Per ADR 0013 (amended 2026-06-24), only TWO
        bands are non-billable — a COMPLETED session that delivered any energy
        now bills from the first Wh (customer got the service; franchisee earns
        it):
          energy <= 0                         -> no taxable supply (ADR 0002)
          FAILED and 0 < energy < 0.5 kWh     -> faulted after a trivial
                                                 delivery (ADR 0013 amendment)
        """
        if is_zero_energy(transaction):
            await QRPaymentService._full_refund(qr_payment, "Zero energy delivered")
            return True
        if is_fault_refund(transaction):
            energy_dec = Decimal(str(energy_kwh))
            await QRPaymentService._full_refund(
                qr_payment,
                f"Faulted after {energy_dec:.3f} kWh (< {MIN_BILLABLE_ENERGY_KWH} kWh) — full refund",
            )
            return True
        return False

    @staticmethod
    def _compute_qr_energy_cost(
        transaction_id: int, amount_paid: Decimal, energy_kwh,
        tariff_rate: Decimal, gst_percent: Decimal,
    ) -> Tuple[Decimal, Decimal]:
        """Compute ``(energy_cost, gst_amount)`` for a billable QR session,
        capping billable energy at the budgeted pre-tax ceiling. Returns
        ``(0, 0)`` when there is no tariff rate. Pure (apart from over-cap
        metric/log emission)."""
        if not tariff_rate:
            return Decimal('0.00'), Decimal('0.00')

        uncapped_energy_cost = (Decimal(str(energy_kwh)) * tariff_rate).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        # Cap billable energy at the budgeted pre-tax ceiling. The budget
        # enforced in Redis is `amount_paid - platform_fee` (tax-inclusive).
        # The charger keeps delivering for a few seconds after we send
        # RemoteStopTransaction, so the metered kWh can overshoot the
        # budget. Without this cap, the customer would be billed for
        # energy they never paid for and the refund would clamp to zero,
        # silently shifting the GST liability onto VoltLync.
        platform_fee = synthetic_platform_fee(amount_paid)
        budget_incl_tax = amount_paid - platform_fee
        gst_multiplier = Decimal('1') + (gst_percent / Decimal('100'))
        budget_excl_tax = (budget_incl_tax / gst_multiplier).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        energy_cost = min(uncapped_energy_cost, budget_excl_tax)
        if uncapped_energy_cost > budget_excl_tax:
            over_kwh = float(
                Decimal(str(energy_kwh)) - (budget_excl_tax / tariff_rate)
            )
            logger.warning(
                "QR over-consumption capped for txn %s: "
                "delivered=%.3fkWh, billable=%.3fkWh, over_delivery=%.3fkWh, "
                "uncapped_cost=₹%s, capped_cost=₹%s",
                transaction_id, energy_kwh,
                float(budget_excl_tax / tariff_rate), over_kwh,
                uncapped_energy_cost, energy_cost,
            )
            # Emit metrics so ops can quantify how much electricity is
            # being absorbed past the budget. A non-zero rate here is a
            # signal to tighten the auto-stop reaction time.
            MetricsCollector.increment_counter("Custom/QR/OverConsumptionCapped")
            MetricsCollector.record_metric("Custom/QR/OverDeliveryKwh", over_kwh)
        gst_amount = (energy_cost * gst_percent / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        return energy_cost, gst_amount

    @staticmethod
    async def process_qr_session_billing(transaction_id: int):
        """
        Called after StopTransaction. Calculate energy cost, platform fee, and issue refund.
        """
        qr_payment = await QRPayment.filter(
            transaction_id=transaction_id,
            status__in=[QRPaymentStatusEnum.CHARGING, QRPaymentStatusEnum.PAID]
        ).first()

        if not qr_payment:
            return  # Not a QR session

        transaction = await Transaction.filter(id=transaction_id).first()
        if not transaction:
            return

        energy_kwh = transaction.energy_consumed_kwh or 0

        if await QRPaymentService._refund_if_non_billable(qr_payment, transaction, energy_kwh):
            return

        tariff = await WalletService.get_applicable_tariff(qr_payment.charger_id)
        tariff_rate = tariff.rate_per_kwh if tariff else Decimal('0')
        gst_percent = tariff.gst_percent if tariff else Decimal('18')
        # Final billing uses the synthetic platform fee for budget cap AND
        # over-payment refund — same rule as the budget side, so the customer
        # never feels the variance with Razorpay's actual fee. See ADR 0001.
        platform_fee = synthetic_platform_fee(qr_payment.amount_paid)
        await _ensure_actual_fee_captured(qr_payment)

        energy_cost, gst_amount = QRPaymentService._compute_qr_energy_cost(
            transaction_id, qr_payment.amount_paid, energy_kwh, tariff_rate, gst_percent,
        )

        refund = max(Decimal('0'), qr_payment.amount_paid - energy_cost - gst_amount - platform_fee)
        await QRPaymentService._finalize_qr_billing(
            transaction_id, qr_payment, energy_cost, gst_amount, gst_percent,
            platform_fee, refund,
        )

    @staticmethod
    async def _finalize_qr_billing(
        transaction_id: int, qr_payment: QRPayment, energy_cost: Decimal,
        gst_amount: Decimal, gst_percent: Decimal, platform_fee: Decimal,
        refund: Decimal,
    ) -> None:
        """Persist the billing breakdown, issue any positive unused-credit
        refund, clear the Redis session, and emit the billing-completed audit
        event. ``platform_fee`` here is the *synthetic* fee used for the refund
        math + log/audit — it is NOT written to ``qr_payment.platform_fee``
        (that holds the actual Razorpay fee, ADR 0001).

        Claim-marker (ADR 0018): T1 persists the billing breakdown and, when a
        refund is due, CLAIMS it (status -> REFUND_IN_PROGRESS) atomically under
        the row lock. The Razorpay call then runs in _execute_claimed_refund with
        NO lock held. StopTransaction, the finalizer, and the orphan sweep can
        all reach this concurrently; the T1 lock + status re-check makes the
        finalize at-most-once, and the idempotency key makes the payout single."""
        # T1 — billing + claim, atomic, lock held only for this fast write.
        async with in_transaction():
            locked = await QRPayment.select_for_update().get(id=qr_payment.id)
            if locked.status not in (
                QRPaymentStatusEnum.CHARGING, QRPaymentStatusEnum.PAID,
            ):
                logger.info(
                    "QR billing for txn %s already finalized (status=%s) — "
                    "skipping duplicate finalize", transaction_id, locked.status,
                )
                return

            # Carry the actual-fee capture made on the pre-lock object
            # (_ensure_actual_fee_captured mutates in place and does NOT save,
            # so the freshly-locked row doesn't have it yet). ADR 0001 — actual
            # fee, never the synthetic platform_fee.
            locked.platform_fee = qr_payment.platform_fee
            locked.razorpay_commission = qr_payment.razorpay_commission
            locked.razorpay_gst = qr_payment.razorpay_gst
            locked.fee_source = qr_payment.fee_source

            locked.energy_cost = energy_cost
            locked.gst_amount = gst_amount

            claimed = refund > 0
            if claimed:
                # Claim the unused-credit refund; the Razorpay call happens after
                # this commits (no lock). Prepaid policy: every unused paisa back.
                locked.refund_amount = refund
                locked.refund_terminal_status = QRPaymentStatusEnum.REFUNDED.value
                locked.status = QRPaymentStatusEnum.REFUND_IN_PROGRESS
            else:
                locked.status = QRPaymentStatusEnum.COMPLETED

            # Store billing breakdown on transaction
            await Transaction.filter(id=transaction_id).update(
                energy_charge=energy_cost,
                gst_amount=gst_amount,
                gst_rate_percent=gst_percent,
                total_billed=energy_cost + gst_amount,
            )

            logger.info(
                f"QR billing for txn {transaction_id}: "
                f"paid=₹{locked.amount_paid}, energy_cost=₹{energy_cost}, "
                f"GST({gst_percent}%)=₹{gst_amount}, platform_fee=₹{platform_fee}, refund=₹{refund}"
            )

            await locked.save()

        # call → persist (T2) for the claimed refund — NO lock across the network.
        if claimed:
            await QRPaymentService._execute_claimed_refund(
                qr_payment.id, "Unused charging credit refund",
            )

        # Post-commit (outside any lock): cache invalidation + audit.
        await redis_manager.delete_qr_session(transaction_id)

        final = await QRPayment.get(id=qr_payment.id)
        safe_create_task(log_audit_event(
            action="qr_payment.billing_completed",
            entity_type="qr_payment",
            entity_id=final.id,
            actor_type="system",
            changes={
                "energy_cost": float(energy_cost),
                "gst_amount": float(gst_amount),
                "platform_fee": float(platform_fee),
                "refund_amount": float(final.refund_amount or 0),
                "status": final.status.value,
            },
        ))

    @staticmethod
    async def handle_charging_failure(transaction_id: int):
        """Full refund on charging failure"""
        qr_payment = await QRPayment.filter(
            transaction_id=transaction_id,
            status__in=[QRPaymentStatusEnum.CHARGING, QRPaymentStatusEnum.PAID]
        ).first()
        if not qr_payment:
            return
        qr_payment.status = QRPaymentStatusEnum.FAILED
        qr_payment.failure_reason = "Charging session failed"
        await qr_payment.save()
        await QRPaymentService._full_refund(qr_payment, "Charging failure")
        await redis_manager.delete_qr_session(transaction_id)

    @staticmethod
    async def _claim_refund(
        payment_id: int,
        refund_amount: Decimal,
        terminal_status: QRPaymentStatusEnum,
        fee_source: Optional[QRPayment] = None,
    ) -> bool:
        """T1 — atomically CLAIM a refund under the row lock: persist
        ``refund_amount`` + the post-refund terminal intent and flip status to
        REFUND_IN_PROGRESS. Returns True iff THIS caller won the claim (must
        proceed to execute), False if the row was already claimed/refunded (back
        off). The lock is held only for this fast write — never across the
        Razorpay call. ``fee_source`` carries the in-place actual-fee capture
        (``_ensure_actual_fee_captured`` mutates without saving). See ADR 0018."""
        async with in_transaction():
            locked = await QRPayment.select_for_update().get(id=payment_id)
            if locked.razorpay_refund_id or locked.status in (
                QRPaymentStatusEnum.REFUNDED, QRPaymentStatusEnum.REFUND_IN_PROGRESS,
            ):
                return False
            if fee_source is not None:
                locked.platform_fee = fee_source.platform_fee
                locked.razorpay_commission = fee_source.razorpay_commission
                locked.razorpay_gst = fee_source.razorpay_gst
                locked.fee_source = fee_source.fee_source
            locked.refund_amount = refund_amount
            locked.refund_terminal_status = terminal_status.value
            locked.status = QRPaymentStatusEnum.REFUND_IN_PROGRESS
            await locked.save()
            return True

    @staticmethod
    async def _execute_claimed_refund(payment_id: int, reason: str) -> None:
        """call → persist (T2) for a row already CLAIMED (REFUND_IN_PROGRESS).

        Holds NO row lock during the Razorpay call (bounded by the refund
        semaphore); re-locks only to persist the outcome. Idempotency-safe and
        resumable: running it twice for the same row issues at most one payout
        (the idempotency key) and the status / refund_id re-checks make the
        second run a no-op — this is exactly what the sweep relies on to recover
        a claim stranded by a crash between T1 and T2. See ADR 0018. The one
        bounded lookup still under the T2 lock is the rare AlreadyRefunded /
        idempotency-conflict reconcile (via the shared classifier)."""
        row = await QRPayment.get(id=payment_id)
        if row.status != QRPaymentStatusEnum.REFUND_IN_PROGRESS:
            return  # already persisted by a concurrent run, or never claimed
        refund_amount = row.refund_amount
        terminal = QRPaymentStatusEnum(
            row.refund_terminal_status or QRPaymentStatusEnum.REFUNDED.value
        )
        refund_kwargs = build_refund_call_kwargs(row, refund_amount)

        # NETWORK — no lock, no open transaction, bounded outbound concurrency.
        result, call_exc = None, None
        try:
            async with _refund_semaphore():
                result = await razorpay_service.refund_payment(
                    row.razorpay_payment_id, **refund_kwargs,
                )
        except Exception as exc:
            call_exc = exc

        # T2 — re-lock and persist the outcome (fast, no refund call).
        async with in_transaction():
            locked = await QRPayment.select_for_update().get(id=payment_id)
            if locked.razorpay_refund_id:
                return  # webhook/sweep already finalized this refund
            if call_exc is None:
                locked.razorpay_refund_id = result.get("id")
                locked.razorpay_refund_speed_processed = result.get("speed_processed")
                locked.status = terminal
                locked.failure_reason = None
                logger.info(
                    "Refund ₹%s issued for QR payment %s: %s",
                    refund_amount, locked.id, reason,
                )
            else:
                # Restore the intended terminal status so _reconcile_conflict's
                # EXPIRED-preservation works, then classify the failure.
                locked.status = terminal
                await QRPaymentService._classify_refund_exception(
                    locked, call_exc,
                    refund_speed=refund_kwargs["speed"],
                    reason=reason,
                    below_minimum_log=(
                        "QR payment %s refund below Razorpay minimum; not refunded"
                        % locked.id
                    ),
                    generic_error_log="Refund error for QR payment %s: %s",
                )
            locked.refund_terminal_status = None
            await locked.save()

    @staticmethod
    async def _classify_refund_exception(
        payment: QRPayment,
        exc: Exception,
        *,
        refund_speed,
        reason: str,
        below_minimum_log: str,
        generic_error_log: str,
    ) -> None:
        """Single source of truth for mapping a Razorpay refund exception onto
        the QRPayment row. Used by BOTH the full-refund and partial (unused
        credit) refund paths so their failure handling can never drift.

        Branches (union of both historical paths):
          - RazorpayAlreadyRefundedError -> reconcile via find_refund_for_payment;
            REFUND_FAILED with an explanatory reason if no refund exists.
          - RazorpayIdempotencyConflictError -> reconcile; REFUND_FAILED with the
            non-retryable IDEMPOTENCY_CONFLICT_NO_REFUND marker if none exists.
          - RazorpayRefundBelowMinimumError -> REFUND_FAILED, BELOW_MINIMUM_REASON
            (benign sub-₹1 remainder); logs ``below_minimum_log`` at info.
          - anything else -> REFUND_FAILED with str(exc), logged at error.

        Does NOT save the row — the caller persists.
        """
        if isinstance(exc, RazorpayAlreadyRefundedError):
            await QRPaymentService._reconcile_conflict(
                payment, refund_speed, reason,
                f"Razorpay reports already refunded but no refund record found: {exc}",
            )
        elif isinstance(exc, RazorpayIdempotencyConflictError):
            await QRPaymentService._reconcile_conflict(
                payment, refund_speed, reason, IDEMPOTENCY_CONFLICT_NO_REFUND,
            )
        elif isinstance(exc, RazorpayRefundBelowMinimumError):
            payment.status = QRPaymentStatusEnum.REFUND_FAILED
            payment.failure_reason = BELOW_MINIMUM_REASON
            logger.info(below_minimum_log)
        else:
            logger.error(generic_error_log, payment.id, exc, exc_info=True)
            payment.status = QRPaymentStatusEnum.REFUND_FAILED
            payment.failure_reason = str(exc)

    @staticmethod
    async def _reconcile_conflict(
        payment: QRPayment, refund_speed, reason: str, no_refund_failure_reason: str,
    ) -> None:
        """Resolve a refund that Razorpay rejected as already-handled (an
        'already refunded' reply or an idempotency-key conflict). A refund may
        already exist on the payment; fetch it. If found, persist its id/speed
        and mark REFUNDED. If not, mark REFUND_FAILED with the supplied
        (non-retryable) reason. The caller persists the row.
        """
        existing = await razorpay_service.find_refund_for_payment(payment.razorpay_payment_id)
        if existing and existing.get("id"):
            payment.razorpay_refund_id = existing["id"]
            existing_speed = existing.get("speed_processed")
            payment.razorpay_refund_speed_processed = existing_speed
            if payment.status != QRPaymentStatusEnum.EXPIRED:
                payment.status = QRPaymentStatusEnum.REFUNDED
            # Clear any prior failure_reason — the row is REFUNDED now, so a
            # lingering reason would falsely read as a failed row in ops/sweep
            # predicates that key on failure_reason presence.
            payment.failure_reason = None
            logger.warning(
                "refund_reconciled=true qr_payment=%s existing_refund=%s reason=%s",
                payment.id, existing["id"], reason,
            )
        else:
            payment.status = QRPaymentStatusEnum.REFUND_FAILED
            payment.failure_reason = no_refund_failure_reason
            logger.error(
                "Could not reconcile refund for payment %s: no refund record found",
                payment.razorpay_payment_id,
            )

    @staticmethod
    async def _full_refund(qr_payment: QRPayment, reason: str):
        """Issue a full refund via the claim-marker pattern (ADR 0018): a short
        locked CLAIM (T1), the Razorpay call with NO lock held, then a short
        locked PERSIST (T2). Serialized (single claim), idempotent (single payout
        via the key), and crash-resumable (a stranded REFUND_IN_PROGRESS is
        recovered by the sweep).

        CONTRACT (unchanged): a caller needing a terminal status preserved (e.g.
        EXPIRED for an orphaned / stale payment) MUST ``save()`` that status
        BEFORE calling — it is read here to record the post-refund terminal
        intent, which T2 restores."""
        # Fast path: already refunded → nothing to do, and skip the fee fetch.
        # (Authoritative re-check happens under the lock in _claim_refund; a stale
        # object that misses here just wastes a fee fetch, never double-refunds.)
        if qr_payment.razorpay_refund_id:
            logger.info(
                "QR payment %s already refunded (%s), skipping",
                qr_payment.id, qr_payment.razorpay_refund_id,
            )
            return
        # Pre-claim, NO lock: capture the actual Razorpay fee (may hit Razorpay's
        # fetch-fees API). Ops/reconciliation only; never subtracted from the
        # refund — zero-energy = no service rendered, customer made whole, fee
        # absorbed as P&L (ADR 0002).
        await _ensure_actual_fee_captured(qr_payment)
        refund_amount = qr_payment.amount_paid
        terminal = (
            QRPaymentStatusEnum.EXPIRED
            if qr_payment.status == QRPaymentStatusEnum.EXPIRED
            else QRPaymentStatusEnum.REFUNDED
        )

        if refund_amount <= 0:
            # Nothing to refund — persist the captured fee under a short lock.
            async with in_transaction():
                locked = await QRPayment.select_for_update().get(id=qr_payment.id)
                if locked.razorpay_refund_id:
                    return
                locked.platform_fee = qr_payment.platform_fee
                locked.razorpay_commission = qr_payment.razorpay_commission
                locked.razorpay_gst = qr_payment.razorpay_gst
                locked.fee_source = qr_payment.fee_source
                await locked.save()
            logger.info("Refund amount ₹%s is zero/negative, skipping", refund_amount)
            return

        # T1 claim (carries the captured fee), then call + persist with no lock
        # across the network. build_refund_call_kwargs derives speed=optimum for
        # full refunds (ADR 0002) deterministically from the amount.
        if await QRPaymentService._claim_refund(
            qr_payment.id, refund_amount, terminal, fee_source=qr_payment,
        ):
            await QRPaymentService._execute_claimed_refund(qr_payment.id, reason)
