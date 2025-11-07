# Razorpay service for payment integration
import os
import razorpay
import hmac
import hashlib
import logging
from typing import Dict, Optional, Tuple
from decimal import Decimal

logger = logging.getLogger(__name__)

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
            logger.error(f"Failed to create refund for payment {payment_id}: {e}")
            return None


# Singleton instance
razorpay_service = RazorpayService()
