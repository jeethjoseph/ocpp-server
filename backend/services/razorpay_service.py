# Razorpay service for payment integration
import asyncio
import os
import razorpay
import httpx
import hmac
import hashlib
import logging
from typing import Dict, Optional, Tuple
from decimal import Decimal

from utils import mask_vpa

logger = logging.getLogger(__name__)


class RazorpayAlreadyRefundedError(Exception):
    """Raised when Razorpay indicates a payment is already (fully) refunded."""

    def __init__(self, payment_id: str, original_error: Exception):
        self.payment_id = payment_id
        self.original_error = original_error
        super().__init__(f"Payment {payment_id} is already refunded: {original_error}")


class RazorpayRefundBelowMinimumError(Exception):
    """Raised when Razorpay rejects a refund because the amount is below
    its ₹1.00 (100 paise) minimum. Common business edge case: a QR session
    bills almost the entire pre-paid amount, leaving a sub-rupee unused
    balance the customer is contractually owed but that Razorpay won't
    process. Callers should treat as 'no refund issued' rather than a
    fault — log at info, do not alert.
    """

    def __init__(self, payment_id: str, original_error: Exception):
        self.payment_id = payment_id
        self.original_error = original_error
        super().__init__(
            f"Refund for {payment_id} below Razorpay minimum (₹1.00): "
            f"{original_error}"
        )


class RazorpayIdempotencyConflictError(Exception):
    """Raised on Razorpay HTTP 409 'Different request with the same idempotency
    key has already been processed.' A prior request reused this key with a
    different body. The original refund may or may not have been created, so a
    same-key retry can never clear the conflict — callers must reconcile via
    find_refund_for_payment instead of blindly retrying.
    """

    def __init__(self, payment_id: str, original_error: Exception):
        self.payment_id = payment_id
        self.original_error = original_error
        super().__init__(
            f"Idempotency conflict refunding {payment_id}: {original_error}"
        )


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


def _is_amount_below_minimum_error(err: Exception) -> bool:
    """Detect Razorpay 'amount must be at least INR 1.00' rejections.
    Razorpay accepts both spellings ('at least' / 'atleast'). The check
    is intentionally narrow — only this exact rejection class — so other
    amount-related errors still escalate normally."""
    msg = str(err).lower()
    return ("amount must be atleast" in msg) or ("amount must be at least" in msg)


def _is_idempotency_conflict_error(err: Exception) -> bool:
    """Detect Razorpay's idempotency-key conflict response ('Different request
    with the same idempotency key has already been processed.'). Matched on the
    message as a fallback to the HTTP 409 status code."""
    return "idempotency key" in str(err).lower()


# Sensitive field names that get masked before being persisted to
# `razorpay_api_log`. Keys are matched case-insensitively against the
# JSON payload's keys (top-level and nested). Email/phone are NOT in
# this set — they're already stored cleartext on the franchisee row.
_SENSITIVE_KEYS = {
    "pan", "account_number", "ifsc_code", "ifsc",
    "aadhaar", "aadhar", "gst", "gstin", "tan",
    "card_number", "card_id",
}


def _mask_sensitive(value):
    """Recursively mask known sensitive fields in a JSON-serialisable
    structure. Returns a NEW structure — never mutates input.

    Masking rule: for any dict key in ``_SENSITIVE_KEYS`` (case-insensitive),
    replace the value with ``f"***{last4}"`` (preserving last-4 chars for
    diagnostic value) when the stringified value is at least 4 chars long,
    or with ``"***"`` for shorter values. Recurses into nested dicts and
    lists; leaves other scalars untouched.
    """
    if isinstance(value, dict):
        masked = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS and v is not None:
                sval = str(v)
                masked[k] = f"***{sval[-4:]}" if len(sval) >= 4 else "***"
            else:
                masked[k] = _mask_sensitive(v)
        return masked
    if isinstance(value, list):
        return [_mask_sensitive(v) for v in value]
    return value


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

    async def create_order(
        self,
        amount: Decimal,
        currency: str = "INR",
        receipt: Optional[str] = None,
        notes: Optional[Dict] = None
    ) -> Dict:
        """
        Create a Razorpay order for wallet recharge (non-blocking via httpx).

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

        amount_in_paise = int(amount * 100)
        order_data = {
            "amount": amount_in_paise,
            "currency": currency,
            "payment_capture": 1,
        }
        if receipt:
            order_data["receipt"] = receipt
        if notes:
            order_data["notes"] = notes

        try:
            logger.info(f"Creating Razorpay order: ₹{amount} ({amount_in_paise} paise)")
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.razorpay.com/v1/orders",
                    json=order_data,
                    auth=(self.api_key, self.api_secret),
                )
            try:
                parsed = resp.json()
            except Exception:
                parsed = {"raw": resp.text}
            if resp.is_error:
                description = ""
                if isinstance(parsed, dict):
                    description = parsed.get("error", {}).get("description") or ""
                description = description or f"HTTP {resp.status_code}"
                raise Exception(description)
            logger.info(f"Razorpay order created: {parsed.get('id')}")
            return parsed
        except httpx.HTTPError as e:
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

    async def fetch_payment(self, payment_id: str) -> Optional[Dict]:
        """
        Fetch payment details from Razorpay (non-blocking via httpx).

        Args:
            payment_id: Razorpay payment ID

        Returns:
            Payment details or None if not found / error.
        """
        if not self.is_configured():
            logger.error("Cannot fetch payment - Razorpay not configured")
            return None

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.razorpay.com/v1/payments/{payment_id}",
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                logger.error(
                    "Failed to fetch payment %s: HTTP %s",
                    payment_id, resp.status_code,
                )
                return None
            try:
                payment = resp.json()
            except Exception:
                payment = None
            if payment:
                logger.info(f"Fetched payment details for {payment_id}")
            return payment
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch payment {payment_id}: {e}")
            return None

    async def fetch_payment_fees(self, payment_id: str) -> Optional[Tuple[Decimal, Decimal]]:
        """Fetch payment from Razorpay and extract fee/tax.

        Returns:
            (total_fee_rupees, tax_rupees) or None if unavailable.
        """
        payment = await self.fetch_payment(payment_id)
        if payment:
            return extract_fee_from_payment(payment)
        return None

    async def fetch_order(self, order_id: str) -> Optional[Dict]:
        """
        Fetch order details from Razorpay (non-blocking via httpx).

        Args:
            order_id: Razorpay order ID

        Returns:
            Order details or None if not found / error.
        """
        if not self.is_configured():
            logger.error("Cannot fetch order - Razorpay not configured")
            return None

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.razorpay.com/v1/orders/{order_id}",
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                logger.error(
                    "Failed to fetch order %s: HTTP %s",
                    order_id, resp.status_code,
                )
                return None
            try:
                order = resp.json()
            except Exception:
                order = None
            if order:
                logger.info(f"Fetched order details for {order_id}")
            return order
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch order {order_id}: {e}")
            return None

    async def create_qr_code(
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
        qr_data = {
            "type": "upi_qr",
            "name": payee_name,
            "usage": "multiple_use",
            "fixed_amount": False,
            "description": description,
        }
        headers: Dict[str, str] = {}
        if account_id:
            headers["X-Razorpay-Account"] = account_id
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.razorpay.com/v1/payments/qr_codes",
                    json=qr_data,
                    headers=headers or None,
                    auth=(self.api_key, self.api_secret),
                )
            try:
                parsed = resp.json()
            except Exception:
                parsed = {"raw": resp.text}
            if resp.is_error:
                description_err = ""
                if isinstance(parsed, dict):
                    description_err = parsed.get("error", {}).get("description") or ""
                description_err = description_err or f"HTTP {resp.status_code}"
                raise Exception(description_err)
            logger.info(
                "Razorpay QR code created: %s payee=%s account=%s",
                parsed.get("id"), payee_name, account_id or "platform",
            )
            return parsed
        except httpx.HTTPError as e:
            logger.error(f"Failed to create Razorpay QR code: {e}", exc_info=True)
            raise Exception(f"Failed to create QR code: {str(e)}")

    async def close_qr_code(
        self, qr_code_id: str, account_id: Optional[str] = None
    ) -> Optional[Dict]:
        """Close a Razorpay QR code. Pass ``account_id`` if the QR was
        created under a linked account so the close call is authorised
        against the same context."""
        if not self.is_configured():
            raise Exception("Razorpay is not configured")
        headers: Dict[str, str] = {}
        if account_id:
            headers["X-Razorpay-Account"] = account_id
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"https://api.razorpay.com/v1/payments/qr_codes/{qr_code_id}/close",
                    headers=headers or None,
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                logger.error(
                    "Failed to close Razorpay QR code %s: HTTP %s",
                    qr_code_id, resp.status_code,
                )
                return None
            try:
                parsed = resp.json()
            except Exception:
                parsed = None
            logger.info(
                "Razorpay QR code closed: %s account=%s",
                qr_code_id, account_id or "platform",
            )
            return parsed
        except httpx.HTTPError as e:
            logger.error(f"Failed to close Razorpay QR code {qr_code_id}: {e}")
            return None

    async def fetch_qr_code(
        self, qr_code_id: str, account_id: Optional[str] = None
    ) -> Optional[Dict]:
        """Fetch QR code details from Razorpay."""
        if not self.is_configured():
            return None
        headers: Dict[str, str] = {}
        if account_id:
            headers["X-Razorpay-Account"] = account_id
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.razorpay.com/v1/payments/qr_codes/{qr_code_id}",
                    headers=headers or None,
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                return None
            try:
                return resp.json()
            except Exception:
                return None
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch QR code {qr_code_id}: {e}")
            return None

    async def fetch_qr_payments(self, qr_code_id: str, options: Optional[Dict] = None) -> Optional[Dict]:
        """Fetch payments for a QR code. ``options`` is treated as query params."""
        if not self.is_configured():
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.razorpay.com/v1/payments/qr_codes/{qr_code_id}/payments",
                    params=options or None,
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                return None
            try:
                return resp.json()
            except Exception:
                return None
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch payments for QR code {qr_code_id}: {e}")
            return None

    async def validate_vpa(self, vpa: str) -> Optional[Dict]:
        """Validate a UPI VPA and return account holder name."""
        if not self.is_configured():
            logger.error("Cannot validate VPA - Razorpay not configured")
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.razorpay.com/v1/payments/validate/vpa",
                    json={"vpa": vpa},
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                return None
            try:
                result = resp.json()
            except Exception:
                return None
            logger.info(f"VPA validation for {mask_vpa(vpa)}: success={result.get('success')}")
            return result
        except httpx.HTTPError as e:
            logger.error(f"Failed to validate VPA {mask_vpa(vpa)}: {e}")
            return None

    async def refund_payment(
        self,
        payment_id: str,
        amount: Optional[Decimal] = None,
        notes: Optional[Dict] = None,
        idempotency_key: Optional[str] = None,
        speed: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Create a refund for a payment.

        Uses ``httpx.AsyncClient`` directly (not the sync ``razorpay`` SDK)
        so the call doesn't block the asyncio event loop. Mirrors the
        migration done on ``create_payment_transfer``.

        Args:
            payment_id: Razorpay payment ID
            amount: Amount to refund in rupees (None for full refund)
            notes: Additional metadata
            idempotency_key: Stable key for safe retries. Sent as
                ``X-Refund-Idempotency`` header. Same key + same body replays
                the original refund; same key + different body returns 400.
            speed: Razorpay refund speed. ``"optimum"`` requests instant
                payout when the rails/payment method support it, falling
                back to ``"normal"`` server-side (Razorpay returns the
                actual speed in ``speed_processed``). ``None`` (default)
                lets Razorpay use ``normal`` (5–7 working days, no fee).
                See ADR 0002 for the policy.

        Returns:
            Refund details or None if not configured.
        """
        if not self.is_configured():
            logger.error("Cannot create refund - Razorpay not configured")
            return None

        url = f"https://api.razorpay.com/v1/payments/{payment_id}/refund"
        body: Dict = {}
        if amount is not None:
            # Convert to paise
            body["amount"] = int(amount * 100)
        if notes:
            body["notes"] = notes
        if speed:
            body["speed"] = speed

        headers: Dict[str, str] = {}
        if idempotency_key:
            headers["X-Refund-Idempotency"] = idempotency_key

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    json=body,
                    headers=headers or None,
                    auth=(self.api_key, self.api_secret),
                )
            try:
                parsed = resp.json()
            except Exception:
                parsed = {"raw": resp.text}

            if resp.is_error:
                description = ""
                if isinstance(parsed, dict):
                    description = parsed.get("error", {}).get("description") or ""
                description = description or f"HTTP {resp.status_code}"
                http_error = Exception(description)
                if _is_already_refunded_error(http_error):
                    raise RazorpayAlreadyRefundedError(payment_id, http_error)
                if _is_amount_below_minimum_error(http_error):
                    logger.info(
                        "Refund for %s skipped: amount below Razorpay ₹1.00 minimum",
                        payment_id,
                    )
                    raise RazorpayRefundBelowMinimumError(payment_id, http_error)
                if resp.status_code == 409 or _is_idempotency_conflict_error(http_error):
                    logger.warning(
                        "Refund for %s hit idempotency conflict (HTTP %s): %s",
                        payment_id, resp.status_code, description,
                    )
                    raise RazorpayIdempotencyConflictError(payment_id, http_error)
                logger.error(f"Failed to create refund for payment {payment_id}: {description}")
                if resp.status_code == 400:
                    raise razorpay.errors.BadRequestError(description)
                if resp.status_code in (502, 503, 504):
                    raise razorpay.errors.GatewayError(description)
                raise Exception(f"HTTP {resp.status_code}: {description}")

            logger.info(
                "Refund created: %s for payment %s idempotency_key=%s "
                "speed_requested=%s speed_processed=%s",
                parsed.get("id"), payment_id, idempotency_key or "none",
                speed or "default", parsed.get("speed_processed") or "unknown",
            )
            return parsed

        except (
            RazorpayAlreadyRefundedError,
            RazorpayRefundBelowMinimumError,
            RazorpayIdempotencyConflictError,
        ):
            raise
        except httpx.HTTPError as e:
            logger.error(f"Failed to create refund for payment {payment_id}: {e}")
            raise

    async def find_refund_for_payment(self, payment_id: str) -> Optional[Dict]:
        """Fetch existing refund(s) for a payment. Returns the first refund dict or None.

        Two requests: payment fetch (may include inline refunds), then refunds
        subresource as a fallback. Both run on ``httpx.AsyncClient`` so the
        call doesn't block the event loop.
        """
        if not self.is_configured():
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                pay_resp = await client.get(
                    f"https://api.razorpay.com/v1/payments/{payment_id}",
                    auth=(self.api_key, self.api_secret),
                )
                if pay_resp.is_error:
                    logger.error(
                        "Failed to fetch payment %s for refund lookup: HTTP %s",
                        payment_id, pay_resp.status_code,
                    )
                    return None
                try:
                    payment = pay_resp.json()
                except Exception:
                    payment = {}
                refunds = payment.get("refunds") if isinstance(payment, dict) else None

                if not refunds:
                    ref_resp = await client.get(
                        f"https://api.razorpay.com/v1/payments/{payment_id}/refunds",
                        auth=(self.api_key, self.api_secret),
                    )
                    if ref_resp.is_error:
                        return None
                    try:
                        refunds_response = ref_resp.json()
                    except Exception:
                        refunds_response = {}
                    if isinstance(refunds_response, dict):
                        refunds = refunds_response.get("items") or []
                    else:
                        refunds = refunds_response or []

            if refunds:
                return refunds[0]
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch refunds for payment {payment_id}: {e}")
        return None


    # ─── Razorpay Route (Linked Accounts & Transfers) ──────────────

    def is_route_enabled(self) -> bool:
        return self.is_configured() and os.getenv(
            "RAZORPAY_ROUTE_ENABLED", "false"
        ).lower() in ("true", "1", "yes")

    async def _audit_call(
        self,
        *,
        method: str,
        endpoint: str,
        request_body: Optional[Dict],
        sdk_call,
        franchisee_id: Optional[int] = None,
        account_id: Optional[str] = None,
        critical: bool = False,
    ) -> Dict:
        """Run a sync Razorpay SDK call and persist a single
        ``RazorpayApiLog`` row capturing request + response (PII masked).

        - SDK exceptions are re-raised AFTER the log row is written.
        - Audit-write failures are normally swallowed (logged at ERROR
          level for ops visibility) so SDK behaviour is preserved.
          When ``critical=True`` (money-moving calls), audit-write
          failures are re-raised AFTER the SDK result is captured —
          callers need to know that a real side effect happened without
          a trace so they can compensate / page on-call.
        - Used by onboarding-chain wrappers and ``create_payment_transfer``
          (Route payment-based transfers). Refunds, payment captures, and
          QR webhook ingestion remain unaudited here.
        """
        masked_request = _mask_sensitive(request_body) if request_body else None
        response_body = None
        response_status: Optional[int] = None
        error_message: Optional[str] = None
        success = False
        sdk_exc: Optional[BaseException] = None
        try:
            # Support both sync SDK calls (return value) and async callers
            # (coroutine). httpx-based callers need the async branch so the
            # event loop isn't blocked on the HTTP round-trip.
            response_body = sdk_call()
            if asyncio.iscoroutine(response_body):
                response_body = await response_body
            success = True
        except razorpay.errors.BadRequestError as e:
            response_status = 400
            error_message = str(e)
            sdk_exc = e
        except razorpay.errors.GatewayError as e:
            response_status = 502
            error_message = str(e)
            sdk_exc = e
        except Exception as e:
            error_message = str(e)
            sdk_exc = e

        # Always attempt to write the audit row, regardless of SDK outcome.
        try:
            from models import RazorpayApiLog
            await RazorpayApiLog.create(
                method=method,
                endpoint=endpoint,
                request_body=masked_request,
                response_status=response_status,
                response_body=(
                    _mask_sensitive(response_body)
                    if isinstance(response_body, (dict, list))
                    else None
                ),
                success=success,
                error_message=error_message,
                franchisee_id=franchisee_id,
                razorpay_account_id=account_id,
            )
        except Exception as audit_err:
            logger.error(
                "Failed to write razorpay_api_log row for %s %s: %s — "
                "audit write %s; SDK call %s.",
                method, endpoint, audit_err,
                "re-raised (critical=True)" if critical else "swallowed",
                "succeeded" if success else "failed",
            )
            if critical and sdk_exc is None:
                # SDK side-effect happened; caller MUST know we couldn't
                # record it. Don't mask SDK exceptions if the call also
                # failed — those take precedence below.
                raise

        if sdk_exc is not None:
            raise sdk_exc
        return response_body

    async def create_linked_account(
        self, payload: Dict, franchisee_id: Optional[int] = None
    ) -> Dict:
        """Create a Razorpay Route linked account (POST /v2/accounts)."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        result = await self._audit_call(
            method="POST",
            endpoint="/v2/accounts",
            request_body=payload,
            sdk_call=lambda: self.client.account.create(data=payload),
            franchisee_id=franchisee_id,
            account_id=None,
        )
        logger.info("Linked account created: %s", result.get("id"))
        return result

    async def fetch_linked_account(self, account_id: str) -> Dict:
        """Fetch linked account details (GET /v2/accounts/{id}) — non-blocking."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.razorpay.com/v2/accounts/{account_id}",
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                description = ""
                try:
                    description = resp.json().get("error", {}).get("description") or ""
                except Exception:
                    pass
                description = description or f"HTTP {resp.status_code}"
                raise Exception(description)
            return resp.json()
        except httpx.HTTPError as e:
            logger.error("Failed to fetch account %s: %s", account_id, e)
            raise

    async def update_linked_account(
        self,
        account_id: str,
        data: Dict,
        franchisee_id: Optional[int] = None,
    ) -> Dict:
        """PATCH /v2/accounts/{id} — amend account fields post-create.
        Some fields (notably ``business_type``) are locked by Razorpay
        once set; the SDK surfaces those as BadRequestError."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        result = await self._audit_call(
            method="PATCH",
            endpoint=f"/v2/accounts/{account_id}",
            request_body=data,
            sdk_call=lambda: self.client.account.edit(account_id, data),
            franchisee_id=franchisee_id,
            account_id=account_id,
        )
        logger.info("Linked account updated: %s", account_id)
        return result

    async def delete_linked_account(
        self, account_id: str, franchisee_id: Optional[int] = None
    ) -> Dict:
        """DELETE /v2/accounts/{id} — hard-delete a linked account.

        Irreversible on Razorpay's side. Used by the admin
        "Delete Razorpay Account" flow when the account is stuck or
        misconfigured and we'd rather start over.
        """
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        result = await self._audit_call(
            method="DELETE",
            endpoint=f"/v2/accounts/{account_id}",
            request_body=None,
            sdk_call=lambda: self.client.account.delete(account_id),
            franchisee_id=franchisee_id,
            account_id=account_id,
        )
        logger.info("Linked account deleted: %s", account_id)
        return result if isinstance(result, dict) else {"deleted": True}

    # ─── Route product configuration + stakeholders (KYC submission) ───

    async def request_product_configuration(
        self,
        account_id: str,
        data: Dict,
        franchisee_id: Optional[int] = None,
    ) -> Dict:
        """POST /v2/accounts/{id}/products — create a product config.
        Minimal body is ``{product_name, tnc_accepted, ip?}``; other config
        (settlements, payment_methods, refund, etc.) is PATCH-only."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        return await self._audit_call(
            method="POST",
            endpoint=f"/v2/accounts/{account_id}/products",
            request_body=data,
            sdk_call=lambda: self.client.product.requestProductConfiguration(
                account_id, data
            ),
            franchisee_id=franchisee_id,
            account_id=account_id,
        )

    async def edit_product_configuration(
        self,
        account_id: str,
        product_id: str,
        data: Dict,
        franchisee_id: Optional[int] = None,
    ) -> Dict:
        """PATCH /v2/accounts/{id}/products/{product_id} — update bank,
        payment_methods, refund, notifications, checkout, etc."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        return await self._audit_call(
            method="PATCH",
            endpoint=f"/v2/accounts/{account_id}/products/{product_id}",
            request_body=data,
            sdk_call=lambda: self.client.product.edit(
                account_id, product_id, data
            ),
            franchisee_id=franchisee_id,
            account_id=account_id,
        )

    async def fetch_product_configuration(
        self, account_id: str, product_id: str
    ) -> Dict:
        """GET /v2/accounts/{id}/products/{product_id} — read
        ``activation_status`` and outstanding ``requirements[]``. Non-blocking."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.razorpay.com/v2/accounts/{account_id}/products/{product_id}",
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                description = ""
                try:
                    description = resp.json().get("error", {}).get("description") or ""
                except Exception:
                    pass
                description = description or f"HTTP {resp.status_code}"
                raise Exception(description)
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(
                "Failed to fetch product %s for %s: %s",
                product_id, account_id, e,
            )
            raise

    async def create_stakeholder(
        self,
        account_id: str,
        data: Dict,
        franchisee_id: Optional[int] = None,
    ) -> Dict:
        """POST /v2/accounts/{id}/stakeholders — add a
        director/proprietor. Razorpay requires at least one stakeholder
        to clear the ``name`` requirement on product config."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        return await self._audit_call(
            method="POST",
            endpoint=f"/v2/accounts/{account_id}/stakeholders",
            request_body=data,
            sdk_call=lambda: self.client.stakeholder.create(account_id, data),
            franchisee_id=franchisee_id,
            account_id=account_id,
        )

    async def list_stakeholders(self, account_id: str) -> Dict:
        """GET /v2/accounts/{id}/stakeholders — list all. Non-blocking."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.razorpay.com/v2/accounts/{account_id}/stakeholders",
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                description = ""
                try:
                    description = resp.json().get("error", {}).get("description") or ""
                except Exception:
                    pass
                description = description or f"HTTP {resp.status_code}"
                raise Exception(description)
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(
                "Failed to list stakeholders on %s: %s", account_id, e
            )
            raise

    async def fetch_stakeholder(self, account_id: str, stakeholder_id: str) -> Dict:
        """GET /v2/accounts/{id}/stakeholders/{sid} — read single stakeholder. Non-blocking."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.razorpay.com/v2/accounts/{account_id}/stakeholders/{stakeholder_id}",
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                description = ""
                try:
                    description = resp.json().get("error", {}).get("description") or ""
                except Exception:
                    pass
                description = description or f"HTTP {resp.status_code}"
                raise Exception(description)
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(
                "Failed to fetch stakeholder %s on %s: %s",
                stakeholder_id, account_id, e,
            )
            raise

    async def update_stakeholder(
        self,
        account_id: str,
        stakeholder_id: str,
        data: Dict,
        franchisee_id: Optional[int] = None,
    ) -> Dict:
        """PATCH /v2/accounts/{id}/stakeholders/{sid} — amend stakeholder
        fields. Used to add ``kyc.pan`` / ``addresses.residential`` to a
        stakeholder created earlier without them."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        result = await self._audit_call(
            method="PATCH",
            endpoint=f"/v2/accounts/{account_id}/stakeholders/{stakeholder_id}",
            request_body=data,
            sdk_call=lambda: self.client.stakeholder.edit(
                account_id, stakeholder_id, data
            ),
            franchisee_id=franchisee_id,
            account_id=account_id,
        )
        logger.info(
            "Stakeholder updated: %s on %s", stakeholder_id, account_id
        )
        return result

    async def create_transfer(
        self,
        account_id: str,
        amount_paise: int,
        notes: Optional[Dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict:
        """Create a Route transfer to a linked account (non-blocking via httpx).

        When ``idempotency_key`` is set, Razorpay deduplicates retries via the
        ``X-Transfer-Idempotency`` header: same key + same body returns the
        original response; same key + different body returns 400.
        """
        if not self.is_configured():
            raise Exception("Razorpay not configured")

        data = {
            "account": account_id,
            "amount": amount_paise,
            "currency": "INR",
        }
        if notes:
            data["notes"] = notes

        headers: Dict[str, str] = {}
        if idempotency_key:
            headers["X-Transfer-Idempotency"] = idempotency_key

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.razorpay.com/v1/transfers",
                    json=data,
                    headers=headers or None,
                    auth=(self.api_key, self.api_secret),
                )
            try:
                parsed = resp.json()
            except Exception:
                parsed = {"raw": resp.text}
            if resp.is_error:
                description = ""
                if isinstance(parsed, dict):
                    description = parsed.get("error", {}).get("description") or ""
                description = description or f"HTTP {resp.status_code}"
                logger.error(
                    "Transfer failed to %s (%d paise): %s",
                    account_id, amount_paise, description,
                )
                if resp.status_code == 400:
                    raise razorpay.errors.BadRequestError(description)
                if resp.status_code in (502, 503, 504):
                    raise razorpay.errors.GatewayError(description)
                raise Exception(f"HTTP {resp.status_code}: {description}")
            logger.info(
                "Transfer created: %s -> %s (%d paise) idempotency_key=%s",
                parsed.get("id"), account_id, amount_paise,
                idempotency_key or "none",
            )
            return parsed
        except httpx.HTTPError as e:
            logger.error(
                "Transfer failed to %s (%d paise): %s",
                account_id, amount_paise, e,
            )
            raise

    async def create_payment_transfer(
        self,
        payment_id: str,
        account_id: str,
        amount_paise: int,
        notes: Optional[Dict] = None,
        franchisee_id: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict:
        """Create a Route transfer from a captured payment to a linked account.

        Calls ``POST /v1/payments/{payment_id}/transfers``. Unlike the
        standalone ``POST /v1/transfers`` (see ``create_transfer``), this
        endpoint requires no separate Razorpay-side feature activation —
        Route account + active linked account is sufficient.

        The only documented constraint is
        ``sum(transfers on payment) <= captured_amount`` (refunds reduce
        the effective transferable amount). Two layers of idempotency:

        1. App-level: ``_validate_ledger_for_transfer`` rejects duplicate
           transfers on the same ``razorpay_payment_id`` once the prior
           transfer has been recorded on the ledger entry.
        2. Network-level: ``idempotency_key`` (sent as ``X-Transfer-Idempotency``
           header) lets Razorpay deduplicate retries when the original POST
           timed out before we recorded the transfer id. Same key + same body
           returns the original response; same key + different body returns
           400. Callers should pass the ledger entry's stable ``idempotency_key``.

        Razorpay returns ``{"entity":"collection","items":[<transfer>]}``;
        this method unwraps and returns ``items[0]`` so callers can use
        ``result.get("id")`` interchangeably with ``create_transfer``.
        """
        if not self.is_configured():
            raise Exception("Razorpay not configured")

        url = f"https://api.razorpay.com/v1/payments/{payment_id}/transfers"
        transfer_obj: Dict = {
            "account": account_id,
            "amount": amount_paise,
            "currency": "INR",
        }
        if notes:
            transfer_obj["notes"] = notes
        body = {"transfers": [transfer_obj]}

        headers: Dict[str, str] = {}
        if idempotency_key:
            headers["X-Transfer-Idempotency"] = idempotency_key

        async def _do_call():
            # httpx.AsyncClient — non-blocking; the previous sync ``requests``
            # call stalled the event loop for the full Razorpay round-trip
            # (up to 30s), serialising every other concurrent task.
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    json=body,
                    headers=headers or None,
                    auth=(self.api_key, self.api_secret),
                )
            try:
                parsed = resp.json()
            except Exception:
                parsed = {"raw": resp.text}
            if resp.is_error:
                description = ""
                if isinstance(parsed, dict):
                    description = (
                        parsed.get("error", {}).get("description") or ""
                    )
                description = description or f"HTTP {resp.status_code}"
                if resp.status_code == 400:
                    raise razorpay.errors.BadRequestError(description)
                if resp.status_code in (502, 503, 504):
                    raise razorpay.errors.GatewayError(description)
                raise Exception(f"HTTP {resp.status_code}: {description}")
            return parsed

        response = await self._audit_call(
            method="POST",
            endpoint=f"POST /v1/payments/{payment_id}/transfers",
            request_body=body,
            sdk_call=_do_call,
            franchisee_id=franchisee_id,
            account_id=account_id,
            critical=True,
        )

        items = response.get("items") if isinstance(response, dict) else None
        if not items:
            raise Exception(
                f"Unexpected payment-transfer response shape: {response}"
            )
        transfer = items[0]
        logger.info(
            "Payment transfer created: %s on %s -> %s (%d paise)",
            transfer.get("id"), payment_id, account_id, amount_paise,
        )
        return transfer

    async def fetch_transfer(self, transfer_id: str) -> Dict:
        """Fetch transfer status. Non-blocking."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.razorpay.com/v1/transfers/{transfer_id}",
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                description = ""
                try:
                    description = resp.json().get("error", {}).get("description") or ""
                except Exception:
                    pass
                description = description or f"HTTP {resp.status_code}"
                raise Exception(description)
            return resp.json()
        except httpx.HTTPError as e:
            logger.error("Failed to fetch transfer %s: %s", transfer_id, e)
            raise

    async def reverse_transfer(
        self, transfer_id: str, amount_paise: Optional[int] = None
    ) -> Dict:
        """Reverse a transfer (full or partial). Non-blocking."""
        if not self.is_configured():
            raise Exception("Razorpay not configured")
        data = {}
        if amount_paise is not None:
            data["amount"] = amount_paise
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"https://api.razorpay.com/v1/transfers/{transfer_id}/reversals",
                    json=data,
                    auth=(self.api_key, self.api_secret),
                )
            if resp.is_error:
                description = ""
                try:
                    description = resp.json().get("error", {}).get("description") or ""
                except Exception:
                    pass
                description = description or f"HTTP {resp.status_code}"
                raise Exception(description)
            result = resp.json()
            logger.info("Transfer %s reversed", transfer_id)
            return result
        except httpx.HTTPError as e:
            logger.error("Failed to reverse transfer %s: %s", transfer_id, e)
            raise


# Singleton instance
razorpay_service = RazorpayService()
