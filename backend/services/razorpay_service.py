# Razorpay service for payment integration
import os
import razorpay
import hmac
import hashlib
import logging
from typing import Dict, Optional, Tuple
from decimal import Decimal

logger = logging.getLogger(__name__)


class RazorpayAlreadyRefundedError(Exception):
    """Raised when Razorpay indicates a payment is already (fully) refunded."""

    def __init__(self, payment_id: str, original_error: Exception):
        self.payment_id = payment_id
        self.original_error = original_error
        super().__init__(f"Payment {payment_id} is already refunded: {original_error}")


def extract_fee_from_payment(payment_data: dict) -> Optional[Tuple[Decimal, Decimal]]:
    """Extract actual Razorpay fee and tax from a payment object.

    Args:
        payment_data: Razorpay payment entity dict (from webhook or API).

    Returns:
        (total_fee_rupees, tax_rupees) or None if fee data is unavailable.
        fee=0 is valid (common for UPI) and returns (Decimal('0'), Decimal('0')).
    """
    fee_paise = payment_data.get("fee")
    tax_paise = payment_data.get("tax")
    if fee_paise is None:
        return None
    total_fee = Decimal(str(fee_paise)) / 100
    tax = Decimal(str(tax_paise or 0)) / 100
    return (total_fee, tax)


def _is_already_refunded_error(err: Exception) -> bool:
    """Detect Razorpay 'already refunded' / 'fully refunded' responses."""
    msg = str(err).lower()
    return any(token in msg for token in ("already refund", "fully refund", "refunded fully"))


# Razorpay caps the QR `name` field at ~50 chars; truncate business + charger
# so the whole string fits even when the business name is long.
_QR_NAME_MAX = 50
_QR_BUSINESS_MAX = 30
_QR_CHARGER_MAX = 17


def build_qr_payee_name(business_name: Optional[str], charger_name: str) -> str:
    """Compose the Razorpay QR ``name`` metadata field.

    Format: ``"{business_name} - {charger_name}"``. When no franchisee is
    linked, falls back to ``"VoltLync"`` as the business_name. The result
    is truncated to fit Razorpay's 50-char cap on the QR name.
    """
    business = (business_name or "VoltLync").strip()[:_QR_BUSINESS_MAX]
    charger = (charger_name or "").strip()[:_QR_CHARGER_MAX]
    combined = f"{business} - {charger}" if charger else business
    return combined[:_QR_NAME_MAX]


def build_qr_description(business_name: Optional[str], charger_name: str) -> str:
    """Compose the rendered descriptor line on the Razorpay QR image."""
    business = (business_name or "VoltLync").strip()
    charger = (charger_name or "").strip()
    return f"{business} - Pay for EV charging at {charger}" if charger else f"{business} - Pay for EV charging"


class RazorpayService:
    """Service for handling Razorpay payment operations"""

    def __init__(self):
        """Initialize Razorpay client with API credentials from environment"""
        self.api_key = os.getenv("RAZORPAY_KEY_ID")
        self.api_secret = os.getenv("RAZORPAY_KEY_SECRET")
        self.webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")

        if not self.api_key or not self.api_secret:
            logger.warning("Razorpay credentials not configured. Payment features will be disabled.")
            self.client = None
        else:
            self.client = razorpay.Client(auth=(self.api_key, self.api_secret))
            self.client.set_app_details({"title": "OCPP CSMS", "version": "2.1"})
            logger.info("Razorpay client initialized successfully")

    def is_configured(self) -> bool:
        """Check if Razorpay is properly configured"""
        return self.client is not None

    def create_order(
        self,
        amount: Decimal,
        currency: str = "INR",
        receipt: Optional[str] = None,
        notes: Optional[Dict] = None
    ) -> Dict:
        """
        Create a Razorpay order for wallet recharge

        Args:
            amount: Amount in rupees (will be converted to paise)
            currency: Currency code (default: INR)
            receipt: Receipt ID for tracking
            notes: Additional metadata

        Returns:
            Order details from Razorpay

        Raises:
            Exception: If Razorpay is not configured or order creation fails
        """
        if not self.is_configured():
            raise Exception("Razorpay is not configured. Please set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET")

        try:
            # Convert amount to paise (1 rupee = 100 paise)
            amount_in_paise = int(amount * 100)

            order_data = {
                "amount": amount_in_paise,
                "currency": currency,
                "payment_capture": 1  # Auto-capture payment
            }

            if receipt:
                order_data["receipt"] = receipt

            if notes:
                order_data["notes"] = notes

            logger.info(f"Creating Razorpay order: ₹{amount} ({amount_in_paise} paise)")
            order = self.client.order.create(data=order_data)
            logger.info(f"Razorpay order created: {order['id']}")

            return order

        except Exception as e:
            logger.error(f"Failed to create Razorpay order: {e}", exc_info=True)
            raise Exception(f"Failed to create payment order: {str(e)}")

    def verify_payment_signature(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str
    ) -> bool:
        """
        Verify payment signature to ensure authenticity

        Args:
            razorpay_order_id: Order ID from Razorpay
            razorpay_payment_id: Payment ID from Razorpay
            razorpay_signature: Signature from Razorpay

        Returns:
            True if signature is valid, False otherwise
        """
        if not self.is_configured():
            logger.error("Cannot verify payment signature - Razorpay not configured")
            return False

        try:
            # Verify using Razorpay SDK
            params_dict = {
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            }

            self.client.utility.verify_payment_signature(params_dict)
            logger.info(f"Payment signature verified successfully for order {razorpay_order_id}")
            return True

        except razorpay.errors.SignatureVerificationError as e:
            logger.error(f"Payment signature verification failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Error verifying payment signature: {e}", exc_info=True)
            return False

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify webhook signature from Razorpay

        Args:
            payload: Raw webhook payload (bytes)
            signature: X-Razorpay-Signature header value

        Returns:
            True if signature is valid, False otherwise
        """
        if not self.webhook_secret:
            logger.error("Cannot verify webhook signature - RAZORPAY_WEBHOOK_SECRET not configured")
            return False

        try:
            # Generate expected signature
            expected_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()

            # Compare signatures (constant time comparison)
            is_valid = hmac.compare_digest(expected_signature, signature)

            if is_valid:
                logger.info("Webhook signature verified successfully")
            else:
                logger.warning("Webhook signature verification failed")

            return is_valid

        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}", exc_info=True)
            return False

    def fetch_payment(self, payment_id: str) -> Optional[Dict]:
        """
        Fetch payment details from Razorpay

        Args:
            payment_id: Razorpay payment ID

        Returns:
            Payment details or None if not found
        """
        if not self.is_configured():
            logger.error("Cannot fetch payment - Razorpay not configured")
            return None

        try:
            payment = self.client.payment.fetch(payment_id)
            logger.info(f"Fetched payment details for {payment_id}")
            return payment

        except Exception as e:
            logger.error(f"Failed to fetch payment {payment_id}: {e}")
            return None

    def fetch_payment_fees(self, payment_id: str) -> Optional[Tuple[Decimal, Decimal]]:
        """Fetch payment from Razorpay and extract fee/tax.

        Returns:
            (total_fee_rupees, tax_rupees) or None if unavailable.
        """
        payment = self.fetch_payment(payment_id)
        if payment:
            return extract_fee_from_payment(payment)
        return None

    def fetch_order(self, order_id: str) -> Optional[Dict]:
        """
        Fetch order details from Razorpay

        Args:
            order_id: Razorpay order ID

        Returns:
            Order details or None if not found
        """
        if not self.is_configured():
            logger.error("Cannot fetch order - Razorpay not configured")
            return None

        try:
            order = self.client.order.fetch(order_id)
            logger.info(f"Fetched order details for {order_id}")
            return order

        except Exception as e:
            logger.error(f"Failed to fetch order {order_id}: {e}")
            return None

    def create_qr_code(
        self,
        payee_name: str,
        description: str,
        account_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Create a Razorpay QR code for a charger (static, variable amount).

        Args:
            payee_name: metadata label stored on the QR object in Razorpay's
                dashboard. Does not rewrite the rendered big-label on the
                returned image — that comes from the owning merchant's KYC.
            description: shorter descriptor rendered on the returned QR image.
            account_id: when provided, scopes the QR to a linked account via
                the ``X-Razorpay-Account`` header. The rendered image will
                then show the linked account's registered business name
                instead of the platform's. Required for RBI Route
                payer-payee transparency when the charger belongs to a
                franchisee whose linked account is ACTIVE.
        """
        if not self.is_configured():
            raise Exception("Razorpay is not configured")
        try:
            qr_data = {
                "type": "upi_qr",
                "name": payee_name,
                "usage": "multiple_use",
                "fixed_amount": False,
                "description": description,
            }
            options = {}
            if account_id:
                options["headers"] = {"X-Razorpay-Account": account_id}
            qr_code = self.client.qrcode.create(data=qr_data, **options)
            logger.info(
                "Razorpay QR code created: %s payee=%s account=%s",
                qr_code.get("id"), payee_name, account_id or "platform",
            )
            return qr_code
        except Exception as e:
            logger.error(f"Failed to create Razorpay QR code: {e}", exc_info=True)
            raise Exception(f"Failed to create QR code: {str(e)}")

    def close_qr_code(
        self, qr_code_id: str, account_id: Optional[str] = None
    ) -> Optional[Dict]:
        """Close a Razorpay QR code. Pass ``account_id`` if the QR was
        created under a linked account so the close call is authorised
        against the same context."""
        if not self.is_configured():
            raise Exception("Razorpay is not configured")
        try:
            options = {}
            if account_id:
                options["headers"] = {"X-Razorpay-Account": account_id}
            result = self.client.qrcode.close(qr_code_id, **options)
            logger.info(
                "Razorpay QR code closed: %s account=%s",
                qr_code_id, account_id or "platform",
            )
            return result
        except Exception as e:
            logger.error(f"Failed to close Razorpay QR code {qr_code_id}: {e}")
            return None

    def fetch_qr_code(
        self, qr_code_id: str, account_id: Optional[str] = None
    ) -> Optional[Dict]:
        """Fetch QR code details from Razorpay."""
        if not self.is_configured():
            return None
        try:
            options = {}
            if account_id:
                options["headers"] = {"X-Razorpay-Account": account_id}
            return self.client.qrcode.fetch(qr_code_id, **options)
        except Exception as e:
            logger.error(f"Failed to fetch QR code {qr_code_id}: {e}")
            return None

    def fetch_qr_payments(self, qr_code_id: str, options: Optional[Dict] = None) -> Optional[Dict]:
        """Fetch payments for a QR code"""
        if not self.is_configured():
            return None
        try:
            return self.client.qrcode.fetch_all_payments(qr_code_id, options or {})
        except Exception as e:
            logger.error(f"Failed to fetch payments for QR code {qr_code_id}: {e}")
            return None

    def validate_vpa(self, vpa: str) -> Optional[Dict]:
        """Validate a UPI VPA and return account holder name."""
        if not self.is_configured():
            logger.error("Cannot validate VPA - Razorpay not configured")
            return None
        try:
            result = self.client.payment.validateVpa({"vpa": vpa})
            logger.info(f"VPA validation for {vpa}: success={result.get('success')}")
            return result
        except Exception as e:
            logger.error(f"Failed to validate VPA {vpa}: {e}")
            return None

    def refund_payment(
        self,
        payment_id: str,
        amount: Optional[Decimal] = None,
        notes: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Create a refund for a payment

        Args:
            payment_id: Razorpay payment ID
            amount: Amount to refund in rupees (None for full refund)
            notes: Additional metadata

        Returns:
            Refund details or None if failed
        """
        if not self.is_configured():
            logger.error("Cannot create refund - Razorpay not configured")
            return None

        try:
            refund_data = {}

            if amount is not None:
                # Convert to paise
                refund_data["amount"] = int(amount * 100)

            if notes:
                refund_data["notes"] = notes

            refund = self.client.payment.refund(payment_id, refund_data)
            logger.info(f"Refund created: {refund['id']} for payment {payment_id}")
            return refund

        except Exception as e:
            if _is_already_refunded_error(e):
                raise RazorpayAlreadyRefundedError(payment_id, e)
            logger.error(f"Failed to create refund for payment {payment_id}: {e}")
            raise

    def find_refund_for_payment(self, payment_id: str) -> Optional[Dict]:
        """Fetch existing refund(s) for a payment. Returns the first refund dict or None."""
        if not self.is_configured():
            return None
        try:
            payment = self.client.payment.fetch(payment_id)
            # SDK may expose `refunds` as list directly or via a subresource call
            refunds = payment.get("refunds") if isinstance(payment, dict) else None
            if not refunds:
                refunds_response = self.client.payment.refunds(payment_id)
                if isinstance(refunds_response, dict):
                    refunds = refunds_response.get("items") or []
                else:
                    refunds = refunds_response or []
            if refunds:
                return refunds[0]
        except Exception as e:
            logger.error(f"Failed to fetch refunds for payment {payment_id}: {e}")
        return None


    # ─── Razorpay Route (Linked Accounts & Transfers) ──────────────

    def is_route_enabled(self) -> bool:
        return self.is_configured() and os.getenv(
            "RAZORPAY_ROUTE_ENABLED", "false"
        ).lower() in ("true", "1", "yes")

    def create_linked_account(self, payload: Dict) -> Dict:
        """Create a Razorpay Route linked account (POST /v2/accounts)."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            result = self.client.account.create(data=payload)
            logger.info("Linked account created: %s", result.get("id"))
            return result
        except Exception as e:
            logger.error("Failed to create linked account: %s", e)
            raise

    def fetch_linked_account(self, account_id: str) -> Dict:
        """Fetch linked account details (GET /v2/accounts/{id})."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            return self.client.account.fetch(account_id)
        except Exception as e:
            logger.error("Failed to fetch account %s: %s", account_id, e)
            raise

    def create_transfer(
        self,
        account_id: str,
        amount_paise: int,
        notes: Optional[Dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict:
        """Create a Route transfer to a linked account."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            data = {
                "account": account_id,
                "amount": amount_paise,
                "currency": "INR",
            }
            if notes:
                data["notes"] = notes

            headers = {}
            if idempotency_key:
                headers["X-Transfer-Idempotency"] = idempotency_key

            result = self.client.transfer.create(data=data)
            logger.info(
                "Transfer created: %s -> %s (%d paise)",
                result.get("id"), account_id, amount_paise,
            )
            return result
        except Exception as e:
            logger.error(
                "Transfer failed to %s (%d paise): %s",
                account_id, amount_paise, e,
            )
            raise

    def fetch_transfer(self, transfer_id: str) -> Dict:
        """Fetch transfer status."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            return self.client.transfer.fetch(transfer_id)
        except Exception as e:
            logger.error("Failed to fetch transfer %s: %s", transfer_id, e)
            raise

    def reverse_transfer(
        self, transfer_id: str, amount_paise: Optional[int] = None
    ) -> Dict:
        """Reverse a transfer (full or partial)."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            data = {}
            if amount_paise is not None:
                data["amount"] = amount_paise
            result = self.client.transfer.reverse(transfer_id, data=data)
            logger.info("Transfer %s reversed", transfer_id)
            return result
        except Exception as e:
            logger.error("Failed to reverse transfer %s: %s", transfer_id, e)
            raise


# Singleton instance
razorpay_service = RazorpayService()
