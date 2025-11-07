# Razorpay Payment Integration - Implementation Documentation

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Backend Implementation](#backend-implementation)
4. [Frontend Implementation](#frontend-implementation)
5. [Payment Flow](#payment-flow)
6. [Database Schema](#database-schema)
7. [API Endpoints](#api-endpoints)
8. [Security & Verification](#security--verification)
9. [Error Handling](#error-handling)
10. [Testing Guide](#testing-guide)
11. [Deployment Configuration](#deployment-configuration)

---

## Overview

### Purpose
The Razorpay integration enables secure wallet recharge functionality for users to add funds to their wallet, which is then used for charging session payments. The implementation follows industry best practices for payment security and reliability.

### Key Features
- Secure payment processing via Razorpay Payment Gateway
- Dual verification mechanism (frontend + webhook)
- Idempotent payment processing
- Real-time wallet balance updates
- Comprehensive transaction tracking
- Payment status monitoring
- Webhook signature verification for security
- Automatic retry mechanisms

### Technology Stack
- **Payment Gateway**: Razorpay (Test/Live modes)
- **Backend SDK**: razorpay==2.0.0 (Python)
- **Frontend SDK**: Razorpay Checkout.js (CDN)
- **Webhook Security**: HMAC SHA256 signature verification

---

## Architecture

### High-Level Architecture

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│              │         │              │         │              │
│   Frontend   │◄───────►│   Backend    │◄───────►│   Razorpay   │
│   (Next.js)  │         │   (FastAPI)  │         │   Gateway    │
│              │         │              │         │              │
└──────────────┘         └──────────────┘         └──────────────┘
       │                        │                         │
       │                        │                         │
       ▼                        ▼                         ▼
  Razorpay            PostgreSQL Database           Webhook Events
  Checkout UI         - Wallet                      - payment.captured
                      - WalletTransaction           - payment.failed
                      - PaymentMetadata             - order.paid
```

### Component Overview

1. **Frontend Component** (`WalletRechargeModal.tsx`)
   - User interface for amount input
   - Razorpay Checkout integration
   - Payment callback handling
   - Real-time balance updates

2. **Backend Services**
   - `razorpay_service.py`: Core Razorpay SDK wrapper
   - `wallet_service.py`: Wallet business logic
   - `wallet_payments.py`: API router for payment operations

3. **Webhook Handler** (`webhooks.py`)
   - Signature verification
   - Event processing (payment.captured, payment.failed, order.paid)
   - Idempotent transaction updates

4. **Database Layer** (`models.py`)
   - Wallet model for balance tracking
   - WalletTransaction model with payment metadata
   - PaymentStatusEnum for transaction states

---

## Backend Implementation

### 1. Razorpay Service (`backend/services/razorpay_service.py`)

#### Class: `RazorpayService`

**Purpose**: Encapsulates all Razorpay SDK interactions and provides a clean interface for payment operations.

**Key Methods**:

```python
class RazorpayService:
    def __init__(self):
        """Initialize Razorpay client with environment credentials"""
        self.api_key = os.getenv("RAZORPAY_KEY_ID")
        self.api_secret = os.getenv("RAZORPAY_KEY_SECRET")
        self.webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
        self.client = razorpay.Client(auth=(self.api_key, self.api_secret))
```

**Methods Overview**:

| Method | Purpose | Returns |
|--------|---------|---------|
| `is_configured()` | Check if Razorpay credentials are set | bool |
| `create_order()` | Create a Razorpay order for payment | Dict (order details) |
| `verify_payment_signature()` | Verify payment authenticity | bool |
| `verify_webhook_signature()` | Verify webhook events | bool |
| `fetch_payment()` | Get payment details from Razorpay | Optional[Dict] |
| `fetch_order()` | Get order details from Razorpay | Optional[Dict] |
| `refund_payment()` | Create a refund (future use) | Optional[Dict] |

**Implementation Details**:

```python
def create_order(self, amount: Decimal, currency: str = "INR",
                 receipt: Optional[str] = None,
                 notes: Optional[Dict] = None) -> Dict:
    """
    Create a Razorpay order for wallet recharge

    Args:
        amount: Amount in rupees (will be converted to paise)
        currency: Currency code (default: INR)
        receipt: Receipt ID for tracking
        notes: Additional metadata (user_id, email, etc.)

    Returns:
        Order details from Razorpay

    Key Features:
    - Automatic currency conversion (rupees → paise)
    - Auto-capture enabled for immediate fund capture
    - Comprehensive logging for debugging
    - Error handling with descriptive messages
    """
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

    order = self.client.order.create(data=order_data)
    logger.info(f"Razorpay order created: {order['id']}")
    return order
```

**Signature Verification**:

```python
def verify_payment_signature(self, razorpay_order_id: str,
                             razorpay_payment_id: str,
                             razorpay_signature: str) -> bool:
    """
    Verify payment signature to ensure authenticity

    Uses Razorpay SDK's built-in verification:
    - Generates expected signature using order_id + payment_id + secret
    - Compares with received signature using constant-time comparison
    - Prevents timing attacks
    """
    try:
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        self.client.utility.verify_payment_signature(params_dict)
        return True
    except razorpay.errors.SignatureVerificationError:
        logger.error(f"Payment signature verification failed")
        return False
```

**Webhook Signature Verification**:

```python
def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
    """
    Verify webhook signature from Razorpay

    Security Features:
    - HMAC SHA256 signature verification
    - Constant-time comparison to prevent timing attacks
    - Raw payload validation (bytes, not parsed JSON)
    """
    expected_signature = hmac.new(
        self.webhook_secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()

    # Constant time comparison
    is_valid = hmac.compare_digest(expected_signature, signature)
    return is_valid
```

### 2. Wallet Service (`backend/services/wallet_service.py`)

**Key Method**: `process_wallet_topup()`

```python
@staticmethod
@atomic()  # Database transaction for consistency
async def process_wallet_topup(
    wallet_transaction_id: int,
    razorpay_payment_id: str,
    razorpay_signature: str
) -> Tuple[bool, str, Optional[Decimal]]:
    """
    Process wallet top-up after payment verification

    Features:
    - Atomic database transactions (SELECT FOR UPDATE)
    - Idempotency check (prevents double-crediting)
    - Accurate balance calculation
    - Comprehensive metadata tracking
    - Error recovery

    Returns:
        (success: bool, message: str, new_balance: Optional[Decimal])
    """
    # Get wallet transaction with lock (prevents race conditions)
    wallet_txn = await WalletTransaction.filter(
        id=wallet_transaction_id
    ).select_for_update().first()

    # Idempotency: Check if already completed
    current_status = wallet_txn.payment_metadata.get("status")
    if current_status == PaymentStatusEnum.COMPLETED.value:
        wallet = await wallet_txn.wallet
        return True, "Payment already processed", wallet.balance

    # Get wallet with lock
    wallet = await Wallet.filter(
        id=wallet_txn.wallet_id
    ).select_for_update().first()

    # Calculate new balance
    current_balance = wallet.balance or Decimal('0.00')
    top_up_amount = wallet_txn.amount
    new_balance = current_balance + top_up_amount

    # Update wallet balance
    await Wallet.filter(id=wallet.id).update(balance=new_balance)

    # Update transaction metadata
    updated_metadata = wallet_txn.payment_metadata or {}
    updated_metadata.update({
        "status": PaymentStatusEnum.COMPLETED.value,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature,
        "completed_at": int(time.time()),
        "previous_balance": float(current_balance),
        "new_balance": float(new_balance)
    })

    await WalletTransaction.filter(id=wallet_transaction_id).update(
        description=f"Wallet recharge - ₹{top_up_amount} (Completed)",
        payment_metadata=updated_metadata
    )

    return True, f"Successfully added ₹{top_up_amount} to wallet", new_balance
```

### 3. Payment Router (`backend/routers/wallet_payments.py`)

**Endpoints**:

#### POST `/api/wallet/create-recharge`

```python
@router.post("/create-recharge", response_model=CreateRechargeResponse)
async def create_recharge_order(
    request: CreateRechargeRequest,
    current_user: User = Depends(require_user())
):
    """
    Create a Razorpay order for wallet recharge

    Flow:
    1. Validate user has a wallet (create if missing)
    2. Create Razorpay order with metadata
    3. Create pending wallet transaction
    4. Return order details for frontend

    Returns:
    {
        "order_id": "order_MkT6xGHq8gQp8B",
        "amount": 500.00,
        "currency": "INR",
        "key_id": "rzp_test_1234567890",
        "wallet_transaction_id": 123
    }
    """
```

**Implementation Details**:

1. **Wallet Validation**: Get or create user's wallet
2. **Receipt Generation**: Unique receipt ID for tracking
3. **Order Creation**: Call Razorpay API
4. **Transaction Recording**: Create pending WalletTransaction
5. **Response**: Return order details for checkout

#### POST `/api/wallet/verify-payment`

```python
@router.post("/verify-payment", response_model=VerifyPaymentResponse)
async def verify_payment(
    request: VerifyPaymentRequest,
    current_user: User = Depends(require_user())
):
    """
    Verify payment from frontend callback (secondary verification)

    Note: Webhook is primary source of truth.
    This provides immediate feedback to user.

    Flow:
    1. Verify payment signature
    2. Find wallet transaction by order_id
    3. Check idempotency (already completed?)
    4. Process wallet top-up via WalletService
    5. Return success with new balance
    """
```

**Security Features**:
- Signature verification using Razorpay SDK
- Idempotency checks to prevent double-crediting
- User ownership validation (wallet transaction belongs to user)

#### GET `/api/wallet/payment-status/{transaction_id}`

```python
@router.get("/payment-status/{transaction_id}",
            response_model=PaymentStatusResponse)
async def get_payment_status(
    transaction_id: int,
    current_user: User = Depends(require_user())
):
    """
    Get the status of a wallet recharge transaction

    Returns:
    {
        "transaction_id": 123,
        "amount": 500.00,
        "status": "COMPLETED",
        "razorpay_order_id": "order_MkT6xGHq8gQp8B",
        "razorpay_payment_id": "pay_MkT7FKhJuD9Z8Q",
        "created_at": "2025-01-15T10:30:00Z"
    }
    """
```

#### GET `/api/wallet/recharge-history`

```python
@router.get("/recharge-history", response_model=dict)
async def get_recharge_history(
    current_user: User = Depends(require_user())
):
    """
    Get user's wallet recharge history (TOP_UP transactions only)

    Returns:
    {
        "data": [
            {
                "id": 123,
                "amount": 500.00,
                "status": "COMPLETED",
                "razorpay_order_id": "order_MkT6xGHq8gQp8B",
                "razorpay_payment_id": "pay_MkT7FKhJuD9Z8Q",
                "description": "Wallet recharge - ₹500 (Completed)",
                "created_at": "2025-01-15T10:30:00Z"
            }
        ],
        "total": 1
    }
    """
```

### 4. Webhook Handler (`backend/routers/webhooks.py`)

**Endpoint**: POST `/webhooks/razorpay`

```python
@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature")
):
    """
    Handle Razorpay webhook events

    PRIMARY source of truth for payment completion.
    Even if frontend callback fails, webhook ensures wallet is credited.

    Supported Events:
    - payment.captured: Payment successful
    - payment.failed: Payment failed
    - order.paid: Alternative to payment.captured

    Security:
    - Webhook signature verification
    - Raw payload validation
    """
    # Get raw request body for signature verification
    body = await request.body()

    # Verify webhook signature
    is_valid = razorpay_service.verify_webhook_signature(
        body, x_razorpay_signature
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    # Parse webhook payload
    payload = json.loads(body.decode('utf-8'))
    event_type = payload.get("event")
    event_data = payload.get("payload", {})

    # Route to appropriate handler
    if event_type == "payment.captured":
        await handle_payment_captured(event_data)
    elif event_type == "payment.failed":
        await handle_payment_failed(event_data)
    elif event_type == "order.paid":
        await handle_order_paid(event_data)

    return {"status": "success"}
```

**Event Handlers**:

```python
async def handle_payment_captured(event_data: dict):
    """
    Handle payment.captured webhook event

    Flow:
    1. Extract payment details from event
    2. Find wallet transaction by order_id
    3. Check idempotency (already completed?)
    4. Process wallet top-up via WalletService
    5. Log success/failure
    """
    payment = event_data.get("payment", {}).get("entity", {})
    order_id = payment.get("order_id")
    payment_id = payment.get("id")

    # Find wallet transaction
    # Note: Can't filter JSON fields directly in Tortoise ORM
    all_transactions = await WalletTransaction.filter(
        type=TransactionTypeEnum.TOP_UP
    ).all()

    wallet_txn = None
    for txn in all_transactions:
        if txn.payment_metadata and \
           txn.payment_metadata.get("razorpay_order_id") == order_id:
            wallet_txn = txn
            break

    # Idempotency check
    current_status = wallet_txn.payment_metadata.get("status")
    if current_status == PaymentStatusEnum.COMPLETED.value:
        logger.info(f"Payment already processed for order {order_id}")
        return

    # Process top-up
    success, message, new_balance = await WalletService.process_wallet_topup(
        wallet_transaction_id=wallet_txn.id,
        razorpay_payment_id=payment_id,
        razorpay_signature=""  # Signature not available in webhook
    )
```

---

## Frontend Implementation

### 1. Wallet Recharge Modal (`frontend/components/WalletRechargeModal.tsx`)

**Component Structure**:

```typescript
interface WalletRechargeModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

export function WalletRechargeModal({
  open,
  onOpenChange,
  onSuccess,
}: WalletRechargeModalProps) {
  const [amount, setAmount] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  // ...
}
```

**Key Features**:

1. **Amount Input Validation**
   ```typescript
   const handleAmountChange = (e: React.ChangeEvent<HTMLInputElement>) => {
     const value = e.target.value;
     // Allow only numbers and decimal point
     if (value === "" || /^\d*\.?\d*$/.test(value)) {
       setAmount(value);
     }
   };
   ```

2. **Quick Amount Buttons**
   ```typescript
   const handleQuickAmount = (value: number) => {
     setAmount(value.toString());
   };

   // Quick amounts: ₹100, ₹200, ₹500, ₹1000
   ```

3. **Validation Rules**
   - Minimum: ₹1
   - Maximum: ₹1,00,000
   - Must be positive number
   - Decimal support

**Payment Flow Implementation**:

```typescript
const handleRecharge = async () => {
  const rechargeAmount = parseFloat(amount);

  // Validation
  if (!amount || rechargeAmount <= 0) {
    toast.error("Please enter a valid amount");
    return;
  }

  if (rechargeAmount < 1) {
    toast.error("Minimum recharge amount is ₹1");
    return;
  }

  if (rechargeAmount > 100000) {
    toast.error("Maximum recharge amount is ₹1,00,000");
    return;
  }

  setIsLoading(true);

  try {
    // Step 1: Create order on backend
    const orderResponse = await walletPaymentService.createRechargeOrder(
      rechargeAmount
    );

    // Step 2: Load Razorpay script if not already loaded
    if (!window.Razorpay) {
      const script = document.createElement("script");
      script.src = "https://checkout.razorpay.com/v1/checkout.js";
      script.async = true;
      document.body.appendChild(script);

      // Wait for script to load
      await new Promise<void>((resolve, reject) => {
        script.onload = () => resolve();
        script.onerror = () => reject(new Error("Failed to load Razorpay"));
      });
    }

    // Step 3: Open Razorpay checkout
    const options = {
      key: orderResponse.key_id,
      amount: orderResponse.amount * 100, // Amount in paise
      currency: orderResponse.currency,
      name: "OCPP CSMS",
      description: `Wallet Recharge - ₹${orderResponse.amount}`,
      order_id: orderResponse.order_id,
      handler: async function (response: any) {
        // Payment successful - verify on backend
        try {
          const verifyResponse = await walletPaymentService.verifyPayment({
            razorpay_order_id: response.razorpay_order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature: response.razorpay_signature,
          });

          if (verifyResponse.success) {
            toast.success(
              `₹${orderResponse.amount} added to wallet! ` +
              `New balance: ₹${verifyResponse.wallet_balance}`
            );
            setAmount("");
            onOpenChange(false);
            onSuccess?.();
          } else {
            toast.error("Payment verification failed. Please contact support.");
          }
        } catch (error: any) {
          console.error("Payment verification error:", error);
          toast.error(
            error.response?.data?.detail ||
            "Payment verification failed. Your wallet will be updated via webhook."
          );
          // Close modal anyway as webhook will handle it
          onOpenChange(false);
          onSuccess?.();
        } finally {
          setIsLoading(false);
        }
      },
      prefill: {
        name: "",
        email: "",
        contact: "",
      },
      theme: {
        color: "#3399cc",
      },
      modal: {
        ondismiss: function () {
          setIsLoading(false);
          toast.info("Payment cancelled");
        },
      },
    };

    const razorpay = new window.Razorpay(options);
    razorpay.open();
  } catch (error: any) {
    console.error("Recharge error:", error);
    toast.error(
      error.response?.data?.detail ||
      "Failed to initiate recharge. Please try again."
    );
    setIsLoading(false);
  }
};
```

### 2. API Service (`frontend/lib/api-services.ts`)

```typescript
export const walletPaymentService = {
  /**
   * Create a Razorpay order for wallet recharge
   */
  createRechargeOrder: (amount: number) =>
    api.post<CreateRechargeResponse>(
      "/api/wallet/create-recharge",
      { amount }
    ),

  /**
   * Verify payment after Razorpay checkout completion
   */
  verifyPayment: (paymentDetails: VerifyPaymentRequest) =>
    api.post<VerifyPaymentResponse>(
      "/api/wallet/verify-payment",
      paymentDetails
    ),

  /**
   * Get payment status by transaction ID
   */
  getPaymentStatus: (transactionId: number) =>
    api.get<PaymentStatusResponse>(
      `/api/wallet/payment-status/${transactionId}`
    ),

  /**
   * Get user's recharge history
   */
  getRechargeHistory: () =>
    api.get<RechargeHistoryResponse>(
      "/api/wallet/recharge-history"
    ),
};
```

### 3. TypeScript Types (`frontend/types/api.ts`)

```typescript
// Request/Response Types
export interface CreateRechargeRequest {
  amount: number;
}

export interface CreateRechargeResponse {
  order_id: string;
  amount: number;
  currency: string;
  key_id: string;
  wallet_transaction_id: number;
}

export interface VerifyPaymentRequest {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

export interface VerifyPaymentResponse {
  success: boolean;
  message: string;
  wallet_balance: number;
  transaction_id: number;
}

export interface PaymentStatusResponse {
  transaction_id: number;
  amount: number;
  status: string;
  razorpay_order_id?: string;
  razorpay_payment_id?: string;
  created_at: string;
}

export interface RechargeHistoryResponse {
  data: Array<{
    id: number;
    amount: number;
    status: string;
    razorpay_order_id?: string;
    razorpay_payment_id?: string;
    description?: string;
    created_at: string;
  }>;
  total: number;
}
```

---

## Payment Flow

### Complete Payment Journey

```
┌─────────────────────────────────────────────────────────────────┐
│                      PAYMENT FLOW DIAGRAM                       │
└─────────────────────────────────────────────────────────────────┘

1. User Action: Click "Recharge Wallet"
   ↓
2. Frontend: Display WalletRechargeModal
   ↓
3. User: Enter amount (e.g., ₹500)
   ↓
4. Frontend: Click "Recharge ₹500"
   │
   ├─► Validate amount (₹1 - ₹1,00,000)
   │
   └─► Call API: POST /api/wallet/create-recharge
       ↓
5. Backend: Create Razorpay Order
   │
   ├─► Generate receipt ID: wallet_recharge_{user_id}_{timestamp}
   ├─► Call Razorpay API: create_order()
   ├─► Create WalletTransaction (status: PENDING)
   │   └─► payment_metadata: {
   │         "status": "PENDING",
   │         "razorpay_order_id": "order_ABC123",
   │         "amount_in_paise": 50000,
   │         ...
   │       }
   └─► Return: order_id, amount, key_id
       ↓
6. Frontend: Load Razorpay Checkout.js
   ↓
7. Frontend: Open Razorpay Modal
   │
   ├─► Display: "Pay ₹500 to OCPP CSMS"
   └─► User selects payment method:
       │
       ├─► Card (Test: 4111 1111 1111 1111)
       ├─► UPI (Test: success@razorpay)
       ├─► Netbanking
       └─► Other methods
       ↓
8. Razorpay: Process Payment
   │
   ├─► Success Path ✅
   │   ↓
   │   Razorpay calls frontend handler with:
   │   {
   │     razorpay_order_id: "order_ABC123",
   │     razorpay_payment_id: "pay_XYZ789",
   │     razorpay_signature: "signature_hash"
   │   }
   │   ↓
   │   Frontend: Call POST /api/wallet/verify-payment
   │   ↓
   │   Backend: Verify Payment
   │   │
   │   ├─► Verify signature using Razorpay SDK
   │   ├─► Find WalletTransaction by order_id
   │   ├─► Check idempotency (already completed?)
   │   └─► Call WalletService.process_wallet_topup()
   │       │
   │       ├─► Lock wallet transaction (SELECT FOR UPDATE)
   │       ├─► Lock wallet (SELECT FOR UPDATE)
   │       ├─► Calculate: new_balance = current + top_up
   │       ├─► Update wallet.balance
   │       └─► Update transaction metadata:
   │           {
   │             "status": "COMPLETED",
   │             "razorpay_payment_id": "pay_XYZ789",
   │             "completed_at": timestamp,
   │             "previous_balance": 1000.00,
   │             "new_balance": 1500.00
   │           }
   │   ↓
   │   Frontend: Show success toast
   │   "₹500 added to wallet! New balance: ₹1500"
   │   ↓
   │   Frontend: Close modal, refresh balance
   │
   └─► Failure Path ❌
       ↓
       Razorpay calls modal.ondismiss()
       ↓
       Frontend: Show cancellation toast
       "Payment cancelled"

9. Razorpay: Send Webhook (Async, Parallel)
   │
   └─► POST /webhooks/razorpay
       Headers: X-Razorpay-Signature
       Body: {
         "event": "payment.captured",
         "payload": {
           "payment": {
             "entity": {
               "id": "pay_XYZ789",
               "order_id": "order_ABC123",
               "amount": 50000,
               "status": "captured"
             }
           }
         }
       }
       ↓
       Backend: Verify Webhook Signature
       │
       ├─► Calculate HMAC SHA256 of raw body
       ├─► Compare with X-Razorpay-Signature
       └─► If valid, process event
           ↓
           Backend: Handle payment.captured
           │
           ├─► Find WalletTransaction by order_id
           ├─► Check idempotency (already completed?)
           │   └─► If completed by frontend: Skip (log success)
           │   └─► If still pending: Process top-up
           └─► Call WalletService.process_wallet_topup()
               (Same flow as frontend verification)
       ↓
       Backend: Return 200 OK to Razorpay
       (Razorpay will retry if webhook fails)

┌─────────────────────────────────────────────────────────────────┐
│                    DUAL VERIFICATION BENEFIT                    │
├─────────────────────────────────────────────────────────────────┤
│ Frontend Verification: Immediate user feedback                  │
│ Webhook Verification: Reliability (works even if user closes)   │
│ Idempotency: Prevents double-crediting                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### Models Related to Razorpay Integration

#### 1. Wallet Model

```python
class Wallet(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    user = fields.OneToOneField("models.User", related_name="wallet")
    balance = fields.DecimalField(max_digits=10, decimal_places=2, null=True)

    # Relationships
    transactions: fields.ReverseRelation["WalletTransaction"]

    class Meta:
        table = "wallet"
```

**Key Points**:
- One-to-one relationship with User
- Balance stored as Decimal for precision
- Auto-created on user creation via Clerk webhook

#### 2. WalletTransaction Model

```python
class WalletTransaction(Model):
    id = fields.IntField(pk=True)
    wallet = fields.ForeignKeyField("models.Wallet", related_name="transactions")
    amount = fields.DecimalField(max_digits=10, decimal_places=2)
    type = fields.CharEnumField(TransactionTypeEnum)
    description = fields.TextField(null=True)
    charging_transaction = fields.ForeignKeyField(
        "models.Transaction",
        related_name="wallet_transactions",
        null=True
    )
    payment_metadata = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "wallet_transaction"
```

**Transaction Types**:
```python
class TransactionTypeEnum(str, enum.Enum):
    TOP_UP = "TOP_UP"              # Wallet recharge
    CHARGE_DEDUCT = "CHARGE_DEDUCT"  # Charging session payment
```

**Payment Metadata Structure** (for TOP_UP):
```json
{
  "status": "COMPLETED",
  "razorpay_order_id": "order_MkT6xGHq8gQp8B",
  "razorpay_payment_id": "pay_MkT7FKhJuD9Z8Q",
  "razorpay_receipt": "wallet_recharge_123_1737000000",
  "razorpay_signature": "a1b2c3d4e5f6g7h8i9j0...",
  "amount_in_paise": 50000,
  "currency": "INR",
  "created_at": 1737000000,
  "completed_at": 1737000060,
  "previous_balance": 1000.00,
  "new_balance": 1500.00
}
```

For FAILED payments:
```json
{
  "status": "FAILED",
  "razorpay_order_id": "order_MkT6xGHq8gQp8B",
  "razorpay_payment_id": "pay_Failed123",
  "error_description": "Payment failed due to insufficient funds",
  "failed_at": 1737000100
}
```

#### 3. PaymentStatusEnum

```python
class PaymentStatusEnum(str, enum.Enum):
    PENDING = "PENDING"      # Order created, payment not completed
    COMPLETED = "COMPLETED"  # Payment successful, wallet credited
    FAILED = "FAILED"        # Payment failed or declined
    REFUNDED = "REFUNDED"    # Payment refunded (future use)
```

### Database Schema Diagram

```sql
┌─────────────────────────┐
│        app_user         │
├─────────────────────────┤
│ id (PK)                 │
│ email                   │
│ full_name               │
│ clerk_user_id           │
│ role (ADMIN/USER)       │
│ ...                     │
└───────────┬─────────────┘
            │ 1:1
            ▼
┌─────────────────────────┐
│         wallet          │
├─────────────────────────┤
│ id (PK)                 │
│ user_id (FK)            │
│ balance (Decimal)       │
│ created_at              │
│ updated_at              │
└───────────┬─────────────┘
            │ 1:N
            ▼
┌─────────────────────────────────────────────┐
│          wallet_transaction                 │
├─────────────────────────────────────────────┤
│ id (PK)                                     │
│ wallet_id (FK)                              │
│ amount (Decimal)                            │
│ type (TOP_UP | CHARGE_DEDUCT)               │
│ description                                 │
│ charging_transaction_id (FK, nullable)      │
│ payment_metadata (JSONB)                    │
│   ├─ status                                 │
│   ├─ razorpay_order_id                      │
│   ├─ razorpay_payment_id                    │
│   ├─ razorpay_signature                     │
│   ├─ completed_at                           │
│   └─ previous_balance, new_balance          │
│ created_at                                  │
└─────────────────────────────────────────────┘
```

---

## API Endpoints

### Complete API Reference

#### 1. Create Recharge Order

**Endpoint**: `POST /api/wallet/create-recharge`

**Authentication**: Required (Bearer JWT token)

**Request Body**:
```json
{
  "amount": 500.00
}
```

**Response** (200 OK):
```json
{
  "order_id": "order_MkT6xGHq8gQp8B",
  "amount": 500.00,
  "currency": "INR",
  "key_id": "rzp_test_1234567890",
  "wallet_transaction_id": 123
}
```

**Error Responses**:
- `503 Service Unavailable`: Razorpay not configured
- `500 Internal Server Error`: Order creation failed

**Usage Example**:
```typescript
const orderResponse = await walletPaymentService.createRechargeOrder(500);
// Use orderResponse.order_id to open Razorpay checkout
```

#### 2. Verify Payment

**Endpoint**: `POST /api/wallet/verify-payment`

**Authentication**: Required (Bearer JWT token)

**Request Body**:
```json
{
  "razorpay_order_id": "order_MkT6xGHq8gQp8B",
  "razorpay_payment_id": "pay_MkT7FKhJuD9Z8Q",
  "razorpay_signature": "a1b2c3d4e5f6g7h8i9j0..."
}
```

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Payment verified and wallet recharged successfully",
  "wallet_balance": 1500.00,
  "transaction_id": 123
}
```

**Error Responses**:
- `400 Bad Request`: Invalid payment signature
- `404 Not Found`: Transaction not found
- `500 Internal Server Error`: Payment processing failed

**Usage Example**:
```typescript
// Called from Razorpay handler callback
const verifyResponse = await walletPaymentService.verifyPayment({
  razorpay_order_id: response.razorpay_order_id,
  razorpay_payment_id: response.razorpay_payment_id,
  razorpay_signature: response.razorpay_signature,
});
```

#### 3. Get Payment Status

**Endpoint**: `GET /api/wallet/payment-status/{transaction_id}`

**Authentication**: Required (Bearer JWT token)

**Response** (200 OK):
```json
{
  "transaction_id": 123,
  "amount": 500.00,
  "status": "COMPLETED",
  "razorpay_order_id": "order_MkT6xGHq8gQp8B",
  "razorpay_payment_id": "pay_MkT7FKhJuD9Z8Q",
  "created_at": "2025-01-15T10:30:00Z"
}
```

**Error Responses**:
- `404 Not Found`: Transaction not found or access denied

#### 4. Get Recharge History

**Endpoint**: `GET /api/wallet/recharge-history`

**Authentication**: Required (Bearer JWT token)

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": 123,
      "amount": 500.00,
      "status": "COMPLETED",
      "razorpay_order_id": "order_MkT6xGHq8gQp8B",
      "razorpay_payment_id": "pay_MkT7FKhJuD9Z8Q",
      "description": "Wallet recharge - ₹500 (Completed)",
      "created_at": "2025-01-15T10:30:00Z"
    },
    {
      "id": 122,
      "amount": 1000.00,
      "status": "COMPLETED",
      "razorpay_order_id": "order_PreviousOrder",
      "razorpay_payment_id": "pay_PreviousPayment",
      "description": "Wallet recharge - ₹1000 (Completed)",
      "created_at": "2025-01-10T15:20:00Z"
    }
  ],
  "total": 2
}
```

#### 5. Razorpay Webhook

**Endpoint**: `POST /webhooks/razorpay`

**Authentication**: Webhook signature verification

**Headers**:
```
X-Razorpay-Signature: abc123def456...
```

**Request Body** (payment.captured):
```json
{
  "event": "payment.captured",
  "payload": {
    "payment": {
      "entity": {
        "id": "pay_MkT7FKhJuD9Z8Q",
        "order_id": "order_MkT6xGHq8gQp8B",
        "amount": 50000,
        "currency": "INR",
        "status": "captured",
        "method": "card",
        "email": "user@example.com",
        "contact": "+919876543210",
        "created_at": 1737000000
      }
    }
  }
}
```

**Response** (200 OK):
```json
{
  "status": "success"
}
```

**Error Responses**:
- `400 Bad Request`: Missing or invalid signature
- `500 Internal Server Error`: Webhook processing failed

---

## Security & Verification

### 1. Payment Signature Verification

**Purpose**: Ensure payment data hasn't been tampered with

**Algorithm**: HMAC SHA256

**Frontend Verification Flow**:
```python
# Backend verifies signature using Razorpay SDK
def verify_payment_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str
) -> bool:
    # Razorpay SDK generates expected signature:
    # expected_sig = HMAC-SHA256(order_id + "|" + payment_id, secret_key)

    params_dict = {
        'razorpay_order_id': razorpay_order_id,
        'razorpay_payment_id': razorpay_payment_id,
        'razorpay_signature': razorpay_signature
    }

    try:
        self.client.utility.verify_payment_signature(params_dict)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
```

### 2. Webhook Signature Verification

**Purpose**: Verify webhook events are from Razorpay

**Security Features**:
- HMAC SHA256 signature
- Raw payload verification (before JSON parsing)
- Constant-time comparison (prevents timing attacks)

**Implementation**:
```python
def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
    # Calculate expected signature
    expected_signature = hmac.new(
        self.webhook_secret.encode('utf-8'),
        payload,  # Raw bytes, NOT parsed JSON
        hashlib.sha256
    ).hexdigest()

    # Constant-time comparison (prevents timing attacks)
    is_valid = hmac.compare_digest(expected_signature, signature)
    return is_valid
```

### 3. Idempotency Protection

**Purpose**: Prevent double-crediting of wallet

**Mechanism**:
```python
# Check payment status before processing
current_status = wallet_txn.payment_metadata.get("status")
if current_status == PaymentStatusEnum.COMPLETED.value:
    logger.info(f"Payment already processed")
    return True, "Payment already processed", wallet.balance
```

**Where Applied**:
- Frontend verification endpoint
- Webhook handlers (payment.captured, order.paid)

### 4. Database Locking

**Purpose**: Prevent race conditions

**Mechanism**:
```python
# Use SELECT FOR UPDATE to lock rows
wallet_txn = await WalletTransaction.filter(
    id=wallet_transaction_id
).select_for_update().first()

wallet = await Wallet.filter(
    id=wallet_txn.wallet_id
).select_for_update().first()
```

**Benefits**:
- Prevents concurrent updates to same wallet
- Ensures accurate balance calculations
- Prevents lost updates

### 5. User Ownership Validation

**Purpose**: Ensure users can only access their own transactions

**Implementation**:
```python
# Verify transaction belongs to user
wallet_transaction = await WalletTransaction.filter(
    id=transaction_id,
    wallet__user=current_user,  # Ownership check
    type=TransactionTypeEnum.TOP_UP
).first()

if not wallet_transaction:
    raise HTTPException(status_code=404, detail="Transaction not found or access denied")
```

### 6. Environment-Based Configuration

**Test Mode**:
```bash
RAZORPAY_KEY_ID=rzp_test_1234567890
RAZORPAY_KEY_SECRET=test_secret_key
RAZORPAY_WEBHOOK_SECRET=whsec_test_secret
```

**Production Mode**:
```bash
RAZORPAY_KEY_ID=rzp_live_XXXXXXXXXX
RAZORPAY_KEY_SECRET=live_secret_YYYYYYYY
RAZORPAY_WEBHOOK_SECRET=whsec_live_ZZZZZZZZ
```

### 7. Error Handling & Logging

**Comprehensive Logging**:
```python
logger.info(f"Creating Razorpay order: ₹{amount}")
logger.info(f"Razorpay order created: {order['id']}")
logger.info(f"Payment signature verified successfully")
logger.info(f"✅ Successfully processed wallet top-up")
logger.error(f"Payment signature verification failed")
logger.warning(f"Payment already processed - idempotency check")
```

**Graceful Error Handling**:
```python
try:
    order = razorpay_service.create_order(...)
except Exception as e:
    logger.error(f"Failed to create Razorpay order: {e}", exc_info=True)
    raise HTTPException(
        status_code=500,
        detail=f"Failed to create payment order: {str(e)}"
    )
```

---

## Error Handling

### Common Errors & Solutions

#### 1. "Payment service is currently unavailable"

**Cause**: Razorpay credentials not configured

**Solution**:
```bash
# Check .env file
RAZORPAY_KEY_ID=rzp_test_YOUR_KEY
RAZORPAY_KEY_SECRET=YOUR_SECRET
RAZORPAY_WEBHOOK_SECRET=whsec_YOUR_SECRET
```

**Code Check**:
```python
if not razorpay_service.is_configured():
    raise HTTPException(
        status_code=503,
        detail="Payment service is currently unavailable"
    )
```

#### 2. "Invalid payment signature"

**Cause**: Signature verification failed

**Possible Reasons**:
- Wrong secret key
- Tampered payment data
- Test/Live mode mismatch

**Debugging**:
```python
logger.error(
    f"Invalid payment signature from user {current_user.id}: "
    f"Order {request.razorpay_order_id}"
)
```

**Solution**:
- Verify `RAZORPAY_KEY_SECRET` matches dashboard
- Ensure using correct test/live keys
- Check for man-in-the-middle attacks

#### 3. "Transaction not found"

**Cause**: Order ID doesn't match any wallet transaction

**Possible Reasons**:
- Frontend sent wrong order_id
- Transaction was deleted
- Database inconsistency

**Solution**:
```python
# Enhanced logging
logger.error(
    f"Wallet transaction not found for order {razorpay_order_id}, "
    f"user {current_user.id}"
)
```

#### 4. "Payment already processed"

**Cause**: Idempotency check triggered

**Scenario**: Normal behavior when:
- Webhook and frontend both process same payment
- User refreshes payment confirmation page
- Retry mechanism kicks in

**Handling**:
```python
if current_status == PaymentStatusEnum.COMPLETED.value:
    logger.info(f"Payment already completed - returning success")
    return True, "Payment already processed", wallet.balance
```

#### 5. Webhook Signature Verification Failed

**Cause**: Invalid webhook signature

**Possible Reasons**:
- Wrong webhook secret
- Payload tampering
- Encoding issues

**Solution**:
```python
if not x_razorpay_signature:
    logger.error("Missing X-Razorpay-Signature header")
    raise HTTPException(status_code=400)

is_valid = razorpay_service.verify_webhook_signature(body, x_razorpay_signature)
if not is_valid:
    logger.error("Invalid Razorpay webhook signature")
    raise HTTPException(status_code=400)
```

#### 6. "Razorpay modal doesn't open"

**Frontend Issue**

**Possible Reasons**:
- Script not loaded
- Popup blocker
- JavaScript error
- Network issue

**Solution**:
```typescript
// Ensure script is loaded
if (!window.Razorpay) {
  const script = document.createElement("script");
  script.src = "https://checkout.razorpay.com/v1/checkout.js";
  script.async = true;
  document.body.appendChild(script);

  await new Promise<void>((resolve, reject) => {
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Razorpay"));
  });
}
```

**User Instructions**:
- Check browser console for errors
- Disable popup blocker for your domain
- Ensure internet connectivity

### Error Response Format

**Standard Error Response**:
```json
{
  "detail": "Payment verification failed. Please contact support."
}
```

**Detailed Error Response** (Development):
```json
{
  "detail": "Payment verification failed",
  "error_type": "SignatureVerificationError",
  "order_id": "order_MkT6xGHq8gQp8B",
  "timestamp": "2025-01-15T10:30:00Z"
}
```

---

## Testing Guide

### Quick Start Testing

**Prerequisites**:
1. Razorpay test account
2. Test API keys in `.env`
3. Backend and frontend servers running

**Test Flow**:
```bash
# 1. Navigate to application
http://localhost:3000

# 2. Login with test user

# 3. Go to "My Sessions" or wallet section

# 4. Click "Recharge Wallet"

# 5. Enter test amount: ₹100

# 6. Use test card:
# Card: 4111 1111 1111 1111
# Expiry: 12/25
# CVV: 123

# 7. Complete payment

# 8. Verify success message

# 9. Check wallet balance updated
```

### Razorpay Test Cards

#### Success Scenarios

**Domestic Card (Success)**:
```
Card Number: 4111 1111 1111 1111
Expiry: Any future date (12/25)
CVV: Any 3 digits (123)
Name: Any name
Result: Payment successful
```

**International Card (Success)**:
```
Card Number: 4012 0010 3714 1112
Expiry: 12/25
CVV: 123
Name: Test User
Result: Payment successful
```

#### Failure Scenarios

**Card Declined**:
```
Card Number: 4000 0000 0000 0002
Expiry: 12/25
CVV: 123
Result: Card declined by bank
```

**Insufficient Funds**:
```
Card Number: 4000 0000 0000 9995
Expiry: 12/25
CVV: 123
Result: Insufficient funds error
```

**Authentication Failed**:
```
Card Number: 4000 0025 0000 3155
Expiry: 12/25
CVV: 123
Result: 3D Secure authentication failed
```

#### UPI Testing

**Successful UPI Payment**:
```
UPI ID: success@razorpay
Result: Payment successful
```

**Failed UPI Payment**:
```
UPI ID: failure@razorpay
Result: Payment failed
```

### Backend Testing

**Test Endpoints with cURL**:

```bash
# 1. Create recharge order
curl -X POST http://localhost:8000/api/wallet/create-recharge \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount": 500}'

# Response:
# {
#   "order_id": "order_MkT6xGHq8gQp8B",
#   "amount": 500.0,
#   "currency": "INR",
#   "key_id": "rzp_test_1234567890",
#   "wallet_transaction_id": 123
# }

# 2. Check payment status
curl http://localhost:8000/api/wallet/payment-status/123 \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"

# 3. Get recharge history
curl http://localhost:8000/api/wallet/recharge-history \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Database Verification

```sql
-- Check wallet balance
SELECT u.email, w.balance
FROM wallet w
JOIN app_user u ON w.user_id = u.id
WHERE u.email = 'test@example.com';

-- Check recent transactions
SELECT
  id,
  amount,
  type,
  description,
  payment_metadata->>'status' as status,
  payment_metadata->>'razorpay_order_id' as order_id,
  created_at
FROM wallet_transaction
WHERE wallet_id = (
  SELECT id FROM wallet WHERE user_id = (
    SELECT id FROM app_user WHERE email = 'test@example.com'
  )
)
ORDER BY created_at DESC
LIMIT 5;

-- Check payment metadata details
SELECT
  id,
  amount,
  payment_metadata
FROM wallet_transaction
WHERE id = 123;
```

### Webhook Testing

#### Using ngrok for Local Testing

```bash
# 1. Start backend server
cd backend
source .venv/bin/activate
python main.py

# 2. Start ngrok (in another terminal)
ngrok http 8000

# Output:
# Forwarding https://abc123.ngrok.io -> http://localhost:8000

# 3. Configure webhook in Razorpay dashboard:
# URL: https://abc123.ngrok.io/webhooks/razorpay
# Events: payment.captured, payment.failed, order.paid

# 4. Copy webhook secret to .env
RAZORPAY_WEBHOOK_SECRET=whsec_abc123xyz...

# 5. Test webhook
# Complete a test payment and check backend logs
```

#### Manual Webhook Testing

**Using Razorpay Dashboard**:
1. Go to Settings → Webhooks
2. Click on your webhook
3. Click "Send Test Webhook"
4. Select `payment.captured` event
5. Check backend logs for processing

**Expected Log Output**:
```
INFO Received Razorpay webhook: payment.captured
INFO Webhook signature verified successfully
INFO Processing payment.captured: Order order_ABC123
INFO ✅ Webhook: Successfully processed payment for order order_ABC123
```

### Integration Testing

**Test Coverage**:
- ✅ Order creation
- ✅ Payment signature verification
- ✅ Wallet balance update
- ✅ Transaction metadata tracking
- ✅ Idempotency checks
- ✅ Webhook processing
- ✅ Error handling
- ✅ User authorization

### Performance Testing

**Load Test Scenarios**:
```python
# Test concurrent payments
import asyncio
import aiohttp

async def test_concurrent_payments(num_requests=10):
    async with aiohttp.ClientSession() as session:
        tasks = []
        for i in range(num_requests):
            task = session.post(
                'http://localhost:8000/api/wallet/create-recharge',
                headers={'Authorization': f'Bearer {token}'},
                json={'amount': 100}
            )
            tasks.append(task)

        responses = await asyncio.gather(*tasks)
        return responses

# Expected: All requests succeed, no race conditions
```

---

## Deployment Configuration

### Environment Variables

**Required Variables**:
```bash
# Razorpay Configuration
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXX        # Test: rzp_test_*, Live: rzp_live_*
RAZORPAY_KEY_SECRET=YOUR_SECRET_KEY        # Keep secure, never commit
RAZORPAY_WEBHOOK_SECRET=whsec_YYYYYYYY    # For webhook signature verification
```

**Optional Variables**:
```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Frontend URL (for CORS)
FRONTEND_URL=https://yourdomain.com

# Environment
ENV=production  # or development, staging
```

### Deployment Checklist

#### Backend Deployment

**Pre-deployment**:
- [ ] Add Razorpay credentials to environment variables
- [ ] Verify database migrations are up to date
- [ ] Test webhook endpoint is accessible publicly
- [ ] Configure CORS for production frontend URL
- [ ] Enable HTTPS (required for Razorpay)

**Deployment Steps**:
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run migrations
aerich upgrade

# 3. Start server
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Post-deployment**:
- [ ] Verify `/webhooks/razorpay` is accessible
- [ ] Test payment flow with test card
- [ ] Monitor logs for errors
- [ ] Configure Razorpay webhook URL in dashboard

#### Frontend Deployment

**Pre-deployment**:
- [ ] Update API base URL to production backend
- [ ] Verify Clerk authentication is configured
- [ ] Test Razorpay Checkout.js loads correctly

**Deployment Steps**:
```bash
# 1. Build production bundle
npm run build

# 2. Deploy to Vercel/Netlify
vercel deploy --prod
```

**Post-deployment**:
- [ ] Test wallet recharge flow
- [ ] Verify payment modal opens
- [ ] Check balance updates immediately
- [ ] Test error scenarios

### Razorpay Dashboard Configuration

#### 1. Create Webhook

**Steps**:
1. Login to Razorpay Dashboard
2. Go to **Settings** → **Webhooks**
3. Click **Create New Webhook**
4. Configure:
   ```
   URL: https://yourdomain.com/webhooks/razorpay
   Secret: <generated automatically>
   Active Events:
   ✅ payment.captured
   ✅ payment.failed
   ✅ order.paid
   ```
5. Click **Create Webhook**
6. Copy webhook secret to `.env`:
   ```bash
   RAZORPAY_WEBHOOK_SECRET=whsec_abc123xyz...
   ```

#### 2. API Keys

**Test Mode**:
- Dashboard → Settings → API Keys
- Generate Test Key
- Use `rzp_test_*` keys for development/staging

**Live Mode**:
- Complete KYC verification
- Activate account
- Generate Live Key
- Use `rzp_live_*` keys for production

#### 3. Payment Methods

**Enable**:
- Cards (Debit/Credit)
- UPI
- Net Banking
- Wallets (Paytm, PhonePe, etc.)
- EMI (optional)

**Configure**:
- Currency: INR
- Auto-capture: Enabled
- Payment timeout: 15 minutes

### Monitoring & Alerts

**Key Metrics to Monitor**:
- Payment success rate
- Webhook delivery success rate
- Average payment processing time
- Failed payment reasons
- Wallet balance discrepancies

**Logging**:
```python
# Production logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("razorpay.log"),
        logging.StreamHandler()
    ]
)
```

**Alert Conditions**:
- Webhook signature verification failures
- Payment processing errors
- Database transaction failures
- Razorpay API errors

### Security Best Practices

**Production Security**:
1. **Never commit secrets** to version control
   ```bash
   # Use .env file (gitignored)
   RAZORPAY_KEY_SECRET=keep_this_secret
   ```

2. **Enable HTTPS** (required by Razorpay)
   ```
   Production URL must use HTTPS
   Webhook URL must use HTTPS
   ```

3. **Validate webhook signatures**
   ```python
   # Always verify before processing
   if not verify_webhook_signature(payload, signature):
       raise HTTPException(status_code=400)
   ```

4. **Use environment-based keys**
   ```bash
   # Development
   RAZORPAY_KEY_ID=rzp_test_*

   # Production
   RAZORPAY_KEY_ID=rzp_live_*
   ```

5. **Implement rate limiting**
   ```python
   # Prevent abuse
   @app.middleware("http")
   async def rate_limit_middleware(request, call_next):
       # Implement rate limiting logic
   ```

6. **Audit logging**
   ```python
   # Log all payment activities
   logger.info(f"Payment attempt by user {user.id}")
   logger.info(f"Payment completed: {payment_id}")
   ```

### Backup & Recovery

**Database Backups**:
```bash
# Backup wallet transactions
pg_dump -t wallet_transaction -t wallet > wallet_backup.sql

# Restore if needed
psql < wallet_backup.sql
```

**Razorpay Data Recovery**:
- Razorpay dashboard maintains complete payment history
- Use `/fetch_payment` API to reconcile discrepancies
- Webhook logs available for 90 days

---

## Troubleshooting

### Common Issues

**Issue**: Payment succeeds but wallet not credited

**Solution**:
1. Check webhook logs in Razorpay dashboard
2. Verify webhook URL is correct
3. Check webhook signature verification
4. Manually trigger webhook resend from dashboard
5. Check backend logs for processing errors

---

**Issue**: Duplicate wallet credits

**Solution**:
- Idempotency checks should prevent this
- If occurred, check logs for race condition
- Verify `SELECT FOR UPDATE` is working
- Review transaction metadata for duplicate processing

---

**Issue**: Webhook signature verification fails

**Solution**:
1. Verify `RAZORPAY_WEBHOOK_SECRET` matches dashboard
2. Ensure using raw payload (bytes) for verification
3. Check for encoding issues
4. Test with Razorpay's test webhook feature

---

## Conclusion

This Razorpay integration provides a robust, secure, and reliable payment solution for wallet recharges in the OCPP CSMS. Key highlights:

✅ **Dual verification** (frontend + webhook) for reliability
✅ **Idempotency** prevents double-crediting
✅ **Comprehensive error handling** with detailed logging
✅ **Security-first approach** with signature verification
✅ **Production-ready** with proper testing and monitoring

For additional support, refer to:
- [Razorpay Documentation](https://razorpay.com/docs/)
- [Testing Guide](../docs/RAZORPAY_TESTING_GUIDE.md)
- Backend logs: `backend/logs/razorpay.log`
