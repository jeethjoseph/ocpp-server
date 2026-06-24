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
from services.razorpay_service import (
    razorpay_service,
    RazorpayAlreadyRefundedError,
    RazorpayRefundBelowMinimumError,
    RazorpayIdempotencyConflictError,
    extract_fee_from_payment,
)
from services.tariff_utils import synthetic_platform_fee, synthetic_fee_split
from services.wallet_service import WalletService, MIN_BILLABLE_ENERGY_KWH
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
    async def handle_qr_payment(webhook_data: Dict) -> Dict:
        """
        Handle qr_code.credited webhook: validate, find user, start charging.
        Returns a status dict for logging.
        """
        payment_entity = webhook_data.get("payment", {}).get("entity", {})
        qr_code_entity = webhook_data.get("qr_code", {}).get("entity", {})

        payment_id = payment_entity.get("id")
        amount_paise = payment_entity.get("amount", 0)
        amount_paid = Decimal(str(amount_paise)) / 100
        vpa = payment_entity.get("vpa")
        contact = payment_entity.get("contact")
        notes = payment_entity.get("notes", {})
        if not isinstance(notes, dict):
            notes = {}
        customer_name = notes.get("customer_name") or payment_entity.get("email")
        qr_code_id = qr_code_entity.get("id") or payment_entity.get("description", "").split("|")[-1].strip()

        # Extract actual Razorpay fee from webhook payload
        fee_data = extract_fee_from_payment(payment_entity)
        fee_fields = {}
        if fee_data:
            total_fee, tax = fee_data
            fee_fields = {
                "platform_fee": total_fee,
                "razorpay_commission": total_fee - tax,
                "razorpay_gst": tax,
                "fee_source": "webhook",
            }

        logger.info(
            "QR payment received: payment_id=%s amount=₹%s qr_code=%s vpa=%s",
            mask_payment_id(payment_id), amount_paid, qr_code_id, mask_vpa(vpa),
        )

        # Idempotency check
        existing = await QRPayment.filter(razorpay_payment_id=payment_id).first()
        if existing:
            logger.info(f"Duplicate webhook for payment {mask_payment_id(payment_id)}, skipping")
            return {"status": "duplicate", "qr_payment_id": existing.id}

        # Staleness check — if payment is older than the pending timeout,
        # the user has long gone. Create record and refund immediately.
        payment_created_at = payment_entity.get("created_at")
        if payment_created_at:
            payment_time = datetime.fromtimestamp(payment_created_at, tz=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - payment_time).total_seconds()
            if age_seconds > QR_PAYMENT_PENDING_TIMEOUT:
                logger.warning(
                    "Stale QR payment %s: %.0fs old (threshold %ss), refunding",
                    mask_payment_id(payment_id), age_seconds, QR_PAYMENT_PENDING_TIMEOUT,
                )
                # Still need to look up charger for the record
                charger_qr = await ChargerQRCode.filter(
                    razorpay_qr_code_id=qr_code_id
                ).prefetch_related("charger").first()
                if not charger_qr:
                    logger.error(f"No ChargerQRCode for stale payment {mask_payment_id(payment_id)}")
                    return {"status": "error", "reason": "QR code not found"}

                user = await find_or_create_user_from_payment(contact, vpa, customer_name)
                qr_payment = await QRPayment.create(
                    charger=charger_qr.charger,
                    charger_qr_code=charger_qr,
                    user=user,
                    razorpay_payment_id=payment_id,
                    razorpay_qr_code_id=qr_code_id,
                    amount_paid=amount_paid,
                    customer_vpa=vpa,
                    customer_name=customer_name,
                    customer_contact=contact,
                    status=QRPaymentStatusEnum.EXPIRED,
                    failure_reason=f"Stale webhook: payment was {age_seconds:.0f}s old",
                    metadata=webhook_data,
                    **fee_fields,
                )
                await QRPaymentService._full_refund(qr_payment, "Stale payment - webhook delayed")
                return {"status": "refunded_stale", "qr_payment_id": qr_payment.id}

        # Look up ChargerQRCode
        charger_qr = await ChargerQRCode.filter(
            razorpay_qr_code_id=qr_code_id, is_active=True
        ).prefetch_related("charger").first()
        if not charger_qr:
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
            return {"status": "error", "reason": "QR code not found or inactive"}

        charger = charger_qr.charger

        # Find or create user
        user = await find_or_create_user_from_payment(contact, vpa, customer_name)

        # Atomic double-payment guard: serialize concurrent QR webhooks for the
        # same charger by locking the Charger row. Only one payment can win the
        # "first slot"; any concurrent payment sees the active txn / pending QR
        # and is rejected + refunded.
        rejection_qr_payment_id = None
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
                    locked_charger.id, mask_payment_id(payment_id), reason,
                )
                rejected = await QRPayment.create(
                    charger=locked_charger,
                    charger_qr_code=charger_qr,
                    user=user,
                    razorpay_payment_id=payment_id,
                    razorpay_qr_code_id=qr_code_id,
                    amount_paid=amount_paid,
                    customer_vpa=vpa,
                    customer_name=customer_name,
                    customer_contact=contact,
                    status=QRPaymentStatusEnum.FAILED,
                    failure_reason="Concurrent payment rejected — charger busy",
                    metadata=webhook_data,
                    **fee_fields,
                )
                rejection_qr_payment_id = rejected.id
            else:
                qr_payment = await QRPayment.create(
                    charger=locked_charger,
                    charger_qr_code=charger_qr,
                    user=user,
                    razorpay_payment_id=payment_id,
                    razorpay_qr_code_id=qr_code_id,
                    amount_paid=amount_paid,
                    customer_vpa=vpa,
                    customer_name=customer_name,
                    customer_contact=contact,
                    status=QRPaymentStatusEnum.PAID,
                    metadata=webhook_data,
                    **fee_fields,
                )

        # Refund rejected payment outside the lock (Razorpay call is slow)
        if rejection_qr_payment_id is not None:
            rejected = await QRPayment.get(id=rejection_qr_payment_id)
            await QRPaymentService._full_refund(rejected, "Concurrent payment rejected — charger busy")
            return {"status": "failed", "reason": "active_transaction", "qr_payment_id": rejection_qr_payment_id}

        # Check if charger is in a suitable state and connected
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

        # Non-billable bands (full refund, no GST invoice / settlement). The
        # over-payment formula below is correct only when a billable service was
        # delivered, so route these to _full_refund (handles audit + instant
        # speed=optimum). Per ADR 0013 (amended 2026-06-24), only TWO bands are
        # non-billable — a COMPLETED session that delivered any energy now bills
        # from the first Wh (customer got the service; franchisee earns it):
        #   energy <= 0                         -> no taxable supply (ADR 0002)
        #   FAILED and 0 < energy < 0.5 kWh     -> faulted after a trivial
        #                                          delivery (ADR 0013 amendment)
        energy_dec = Decimal(str(energy_kwh))
        if energy_dec <= 0:
            await QRPaymentService._full_refund(qr_payment, "Zero energy delivered")
            return
        if (transaction.transaction_status == TransactionStatusEnum.FAILED
                and energy_dec < MIN_BILLABLE_ENERGY_KWH):
            await QRPaymentService._full_refund(
                qr_payment,
                f"Faulted after {energy_dec:.3f} kWh (< {MIN_BILLABLE_ENERGY_KWH} kWh) — full refund",
            )
            return

        tariff = await WalletService.get_applicable_tariff(qr_payment.charger_id)
        tariff_rate = tariff.rate_per_kwh if tariff else Decimal('0')
        gst_percent = tariff.gst_percent if tariff else Decimal('18')
        # Final billing uses the synthetic platform fee for budget cap AND
        # over-payment refund — same rule as the budget side, so the customer
        # never feels the variance with Razorpay's actual fee. See ADR 0001.
        platform_fee = synthetic_platform_fee(qr_payment.amount_paid)
        await _ensure_actual_fee_captured(qr_payment)

        if tariff_rate:
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
            budget_incl_tax = qr_payment.amount_paid - platform_fee
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
                MetricsCollector.record_metric(
                    "Custom/QR/OverDeliveryKwh", over_kwh
                )
            gst_amount = (energy_cost * gst_percent / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        else:
            energy_cost = Decimal('0.00')
            gst_amount = Decimal('0.00')

        refund = max(Decimal('0'), qr_payment.amount_paid - energy_cost - gst_amount - platform_fee)

        qr_payment.energy_cost = energy_cost
        qr_payment.gst_amount = gst_amount
        # NB: qr_payment.platform_fee already holds the actual Razorpay fee
        # (populated above by _ensure_actual_fee_captured) — do not overwrite
        # with the synthetic value. ADR 0001.
        qr_payment.status = QRPaymentStatusEnum.COMPLETED

        # Store billing breakdown on transaction
        await Transaction.filter(id=transaction_id).update(
            energy_charge=energy_cost,
            gst_amount=gst_amount,
            gst_rate_percent=gst_percent,
            total_billed=energy_cost + gst_amount,
        )

        logger.info(
            f"QR billing for txn {transaction_id}: "
            f"paid=₹{qr_payment.amount_paid}, energy_cost=₹{energy_cost}, "
            f"GST({gst_percent}%)=₹{gst_amount}, platform_fee=₹{platform_fee}, refund=₹{refund}"
        )

        # Always refund any positive balance (no minimum-refund threshold).
        # Prepaid policy: customer gets every paisa back if they didn't use it.
        # Negative balance (over-consumption past budget) is absorbed as
        # operator loss — handled separately in the cap logic above.
        if refund > 0:
            qr_payment.refund_amount = refund
            try:
                refund_result = await razorpay_service.refund_payment(
                    qr_payment.razorpay_payment_id,
                    **build_refund_call_kwargs(qr_payment, refund),
                )
                qr_payment.razorpay_refund_id = refund_result.get("id")
                qr_payment.status = QRPaymentStatusEnum.REFUNDED
                logger.info(f"Refund of ₹{refund} issued for QR payment {qr_payment.id}")
            except RazorpayRefundBelowMinimumError:
                # Razorpay rejects refunds < ₹1.00. Customer effectively
                # forfeits the sub-rupee remainder; not a real failure.
                # Tag with a specific reason so admin/billing-retry can
                # disambiguate from genuine refund errors.
                qr_payment.status = QRPaymentStatusEnum.REFUND_FAILED
                qr_payment.failure_reason = BELOW_MINIMUM_REASON
                logger.info(
                    "QR payment %s refund ₹%s below Razorpay minimum; not refunded",
                    qr_payment.id, refund,
                )
            except RazorpayIdempotencyConflictError:
                # HTTP 409 on the unused-credit refund (cross-env key collision
                # or lost-response retry). Reconcile to any existing refund; if
                # none, mark non-retryable. Partial refunds never request
                # instant speed, so pass refund_speed=None.
                await QRPaymentService._reconcile_conflict(
                    qr_payment, None, "Unused charging credit refund",
                    IDEMPOTENCY_CONFLICT_NO_REFUND,
                )
            except Exception as e:
                qr_payment.status = QRPaymentStatusEnum.REFUND_FAILED
                qr_payment.failure_reason = str(e)
                logger.error(f"Refund failed for QR payment {qr_payment.id}: {e}", exc_info=True)

        await qr_payment.save()

        # Clean up Redis cache
        await redis_manager.delete_qr_session(transaction_id)

        safe_create_task(log_audit_event(
            action="qr_payment.billing_completed",
            entity_type="qr_payment",
            entity_id=qr_payment.id,
            actor_type="system",
            changes={
                "energy_cost": float(energy_cost),
                "gst_amount": float(gst_amount),
                "platform_fee": float(platform_fee),
                "refund_amount": float(qr_payment.refund_amount or 0),
                "status": qr_payment.status.value,
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
        """Issue a full refund for a QR payment, guarded by a row lock.

        The entire check-decide-write flow runs inside a single DB transaction
        with SELECT FOR UPDATE on the QRPayment row. This serializes concurrent
        callers (webhook retries, watchdogs, billing) so only one refund is ever
        issued. Razorpay "already refunded" responses are reconciled by
        fetching the existing refund and persisting its ID.
        """
        async with in_transaction():
            locked = await QRPayment.select_for_update().get(id=qr_payment.id)

            if locked.razorpay_refund_id:
                logger.info(
                    "QR payment %s already refunded (%s), skipping",
                    locked.id, locked.razorpay_refund_id,
                )
                return

            # Capture the actual Razorpay fee onto the row for ops/reconciliation,
            # but don't subtract it from the refund — zero-energy = no service
            # rendered, customer is made whole, VoltLync absorbs the fee as P&L.
            # See ADR 0002.
            await _ensure_actual_fee_captured(locked)
            refund_amount = locked.amount_paid

            if refund_amount <= 0:
                await locked.save()  # Persist fee data even if refund is skipped
                logger.info(f"Refund amount ₹{refund_amount} is zero/negative, skipping")
                return

            locked.refund_amount = refund_amount

            # ADR 0002: request instant refund (speed=optimum) on full-refund
            # flows so customers see the money back in minutes, not days.
            # Razorpay falls back to normal speed server-side when rails or
            # payment method don't support instant. VoltLync absorbs the
            # per-refund instant fee. The speed decision + kill-switch
            # (RAZORPAY_INSTANT_REFUND_ENABLED, default true) live in
            # build_refund_call_kwargs so the retry path reproduces it exactly.
            refund_kwargs = build_refund_call_kwargs(locked, refund_amount)
            refund_speed = refund_kwargs["speed"]

            try:
                refund_result = await razorpay_service.refund_payment(
                    locked.razorpay_payment_id,
                    **refund_kwargs,
                )
                locked.razorpay_refund_id = refund_result.get("id")
                speed_processed = refund_result.get("speed_processed")
                locked.razorpay_refund_speed_processed = speed_processed
                if locked.status != QRPaymentStatusEnum.EXPIRED:
                    locked.status = QRPaymentStatusEnum.REFUNDED
                await locked.save()
                logger.info(
                    "Full refund ₹%s issued for QR payment %s: %s",
                    refund_amount, locked.id, reason,
                )
            except RazorpayAlreadyRefundedError as e:
                await QRPaymentService._reconcile_conflict(
                    locked, refund_speed, reason,
                    f"Razorpay reports already refunded but no refund record found: {e}",
                )
                await locked.save()
            except RazorpayIdempotencyConflictError:
                # HTTP 409: the key was already used (cross-env collision or a
                # lost-response retry). Reconcile to any existing refund; if
                # none, mark non-retryable so the sweep stops hammering it.
                await QRPaymentService._reconcile_conflict(
                    locked, refund_speed, reason, IDEMPOTENCY_CONFLICT_NO_REFUND,
                )
                await locked.save()
            except RazorpayRefundBelowMinimumError:
                # Sub-₹1 full refund (rare — amount_paid is normally ≥₹1).
                # Tag with the canonical marker so the sweep excludes it,
                # matching the partial-refund path.
                locked.status = QRPaymentStatusEnum.REFUND_FAILED
                locked.failure_reason = BELOW_MINIMUM_REASON
                await locked.save()
                logger.info(
                    "QR payment %s full refund below Razorpay minimum; not refunded",
                    locked.id,
                )
            except Exception as e:
                logger.error(
                    "Full refund error for QR payment %s: %s", locked.id, e, exc_info=True,
                )
                locked.status = QRPaymentStatusEnum.REFUND_FAILED
                locked.failure_reason = str(e)
                await locked.save()
