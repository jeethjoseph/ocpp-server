"""QR Payment Service - Core business logic for appless EV charging via Razorpay UPI QR"""
import os
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple, Dict

from tortoise.transactions import in_transaction

from models import (
    User, Wallet, Charger, Transaction, QRPayment, ChargerQRCode,
    QRPaymentStatusEnum, AuthProviderEnum, ChargerStatusEnum,
    TransactionStatusEnum, UserRoleEnum
)
from services.razorpay_service import razorpay_service, RazorpayAlreadyRefundedError
from services.wallet_service import WalletService
from redis_manager import redis_manager
from core.connection_manager import connection_manager
from crud import log_audit_event
from utils import safe_create_task, mask_vpa, mask_phone, mask_payment_id, mask_email

logger = logging.getLogger(__name__)

# Configuration from environment
RAZORPAY_PLATFORM_FEE_PERCENT = Decimal(os.getenv("RAZORPAY_PLATFORM_FEE_PERCENT", "2.0"))
MINIMUM_REFUND_AMOUNT = Decimal(os.getenv("MINIMUM_REFUND_AMOUNT", "1.0"))
QR_PAYMENT_PENDING_TIMEOUT = int(os.getenv("QR_PAYMENT_PENDING_TIMEOUT", "300"))

SYSTEM_GUEST_EMAIL = "guest@system.powerlync.com"


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
        await Wallet.create(user=guest, balance=Decimal("0.00"))
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
        await Wallet.create(user=user, balance=Decimal("0.00"))
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
                )
                await QRPaymentService._full_refund(qr_payment, "Stale payment - webhook delayed")
                return {"status": "refunded_stale", "qr_payment_id": qr_payment.id}

        # Look up ChargerQRCode
        charger_qr = await ChargerQRCode.filter(
            razorpay_qr_code_id=qr_code_id, is_active=True
        ).prefetch_related("charger").first()
        if not charger_qr:
            logger.error(f"No active ChargerQRCode found for qr_code_id={qr_code_id}")
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
        await qr_payment.save()

        # Cache session data in Redis for MeterValues budget check
        tariff = await WalletService.get_applicable_tariff(charger_id)
        tariff_rate = tariff.rate_per_kwh if tariff else Decimal('0')
        gst_percent = tariff.gst_percent if tariff else Decimal('18')
        platform_fee = (qr_payment.amount_paid * RAZORPAY_PLATFORM_FEE_PERCENT / 100).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        budget_limit = float(qr_payment.amount_paid - platform_fee)

        transaction = await Transaction.filter(id=transaction_id).first()

        session_data = {
            "qr_payment_id": qr_payment.id,
            "amount_paid": float(qr_payment.amount_paid),
            "platform_fee": float(platform_fee),
            "budget_limit": budget_limit,
            "tariff_rate": float(tariff_rate),
            "gst_percent": float(gst_percent),
            "start_meter_kwh": transaction.start_meter_kwh if transaction else 0,
            "charger_id": charger_id,
        }
        await redis_manager.set_qr_session(transaction_id, session_data)

        logger.info(f"Linked QR payment {qr_payment.id} to transaction {transaction_id}, budget_limit=₹{budget_limit}")
        return qr_payment

    @staticmethod
    async def check_budget_and_auto_stop(transaction_id: int, reading_kwh: float):
        """Check if QR session has exceeded budget and auto-stop if needed."""
        session = await redis_manager.get_qr_session(transaction_id)

        if not session:
            # DB fallback for cache miss (e.g., server restart)
            qr_payment = await QRPayment.filter(
                transaction_id=transaction_id,
                status=QRPaymentStatusEnum.CHARGING
            ).first()
            if not qr_payment:
                return  # Not a QR session

            # Rebuild cache
            tariff = await WalletService.get_applicable_tariff(qr_payment.charger_id)
            tariff_rate = tariff.rate_per_kwh if tariff else Decimal('0')
            gst_percent = tariff.gst_percent if tariff else Decimal('18')
            platform_fee = (qr_payment.amount_paid * RAZORPAY_PLATFORM_FEE_PERCENT / 100).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            budget_limit = float(qr_payment.amount_paid - platform_fee)

            transaction = await Transaction.filter(id=transaction_id).first()
            session = {
                "qr_payment_id": qr_payment.id,
                "amount_paid": float(qr_payment.amount_paid),
                "platform_fee": float(platform_fee),
                "budget_limit": budget_limit,
                "tariff_rate": float(tariff_rate),
                "gst_percent": float(gst_percent),
                "start_meter_kwh": transaction.start_meter_kwh if transaction else 0,
                "charger_id": qr_payment.charger_id,
            }
            await redis_manager.set_qr_session(transaction_id, session)

        budget_limit = Decimal(str(session["budget_limit"]))
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
                # because the CALLRESULT hasn't been sent yet.
                asyncio.create_task(
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
        tariff = await WalletService.get_applicable_tariff(qr_payment.charger_id)
        tariff_rate = tariff.rate_per_kwh if tariff else Decimal('0')
        gst_percent = tariff.gst_percent if tariff else Decimal('18')

        if tariff_rate:
            energy_cost = (Decimal(str(energy_kwh)) * tariff_rate).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            gst_amount = (energy_cost * gst_percent / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
        else:
            energy_cost = Decimal('0.00')
            gst_amount = Decimal('0.00')

        platform_fee = (qr_payment.amount_paid * RAZORPAY_PLATFORM_FEE_PERCENT / 100).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

        refund = max(Decimal('0'), qr_payment.amount_paid - energy_cost - gst_amount - platform_fee)

        qr_payment.energy_cost = energy_cost
        qr_payment.gst_amount = gst_amount
        qr_payment.platform_fee = platform_fee
        qr_payment.status = QRPaymentStatusEnum.COMPLETED

        # Store billing breakdown on transaction
        await Transaction.filter(id=transaction_id).update(
            energy_charge=energy_cost,
            gst_amount=gst_amount,
            total_billed=energy_cost + gst_amount,
        )

        logger.info(
            f"QR billing for txn {transaction_id}: "
            f"paid=₹{qr_payment.amount_paid}, energy_cost=₹{energy_cost}, "
            f"GST({gst_percent}%)=₹{gst_amount}, platform_fee=₹{platform_fee}, refund=₹{refund}"
        )

        if refund >= MINIMUM_REFUND_AMOUNT:
            qr_payment.refund_amount = refund
            try:
                refund_result = razorpay_service.refund_payment(
                    qr_payment.razorpay_payment_id,
                    amount=refund,
                    notes={"transaction_id": str(transaction_id), "reason": "Unused charging credit refund"}
                )
                qr_payment.razorpay_refund_id = refund_result.get("id")
                qr_payment.status = QRPaymentStatusEnum.REFUNDED
                logger.info(f"Refund of ₹{refund} issued for QR payment {qr_payment.id}")
            except Exception as e:
                qr_payment.status = QRPaymentStatusEnum.REFUND_FAILED
                qr_payment.failure_reason = str(e)
                logger.error(f"Refund failed for QR payment {qr_payment.id}: {e}", exc_info=True)
        else:
            logger.info(f"Refund ₹{refund} below minimum ₹{MINIMUM_REFUND_AMOUNT}, absorbed as operator credit")

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

            platform_fee = (locked.amount_paid * RAZORPAY_PLATFORM_FEE_PERCENT / 100).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            refund_amount = locked.amount_paid - platform_fee

            if refund_amount < MINIMUM_REFUND_AMOUNT:
                logger.info(f"Refund amount ₹{refund_amount} below minimum, skipping")
                return

            locked.platform_fee = platform_fee
            locked.refund_amount = refund_amount

            try:
                refund_result = razorpay_service.refund_payment(
                    locked.razorpay_payment_id,
                    amount=refund_amount,
                    notes={"reason": reason, "qr_payment_id": str(locked.id)},
                )
                locked.razorpay_refund_id = refund_result.get("id")
                if locked.status != QRPaymentStatusEnum.EXPIRED:
                    locked.status = QRPaymentStatusEnum.REFUNDED
                await locked.save()
                logger.info(
                    "Full refund ₹%s issued for QR payment %s: %s",
                    refund_amount, locked.id, reason,
                )
            except RazorpayAlreadyRefundedError as e:
                existing = razorpay_service.find_refund_for_payment(locked.razorpay_payment_id)
                if existing and existing.get("id"):
                    locked.razorpay_refund_id = existing["id"]
                    if locked.status != QRPaymentStatusEnum.EXPIRED:
                        locked.status = QRPaymentStatusEnum.REFUNDED
                    await locked.save()
                    logger.warning(
                        "refund_reconciled=true qr_payment=%s existing_refund=%s reason=%s",
                        locked.id, existing["id"], reason,
                    )
                else:
                    locked.status = QRPaymentStatusEnum.REFUND_FAILED
                    locked.failure_reason = f"Razorpay reports already refunded but no refund record found: {e}"
                    await locked.save()
                    logger.error(
                        "Could not reconcile already-refunded payment %s: no refund record found",
                        locked.razorpay_payment_id,
                    )
            except Exception as e:
                logger.error(
                    "Full refund error for QR payment %s: %s", locked.id, e, exc_info=True,
                )
                locked.status = QRPaymentStatusEnum.REFUND_FAILED
                locked.failure_reason = str(e)
                await locked.save()
