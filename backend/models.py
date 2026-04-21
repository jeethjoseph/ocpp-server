# Tortoise ORM Models
import enum
from datetime import date
from tortoise.models import Model
from tortoise import fields
from tortoise.contrib.pydantic import pydantic_model_creator

# Enums
class TransactionTypeEnum(str, enum.Enum):
    TOP_UP = "TOP_UP"
    CHARGE_DEDUCT = "CHARGE_DEDUCT"

class PaymentStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

class ChargerStatusEnum(str, enum.Enum):
    AVAILABLE = "Available"
    PREPARING = "Preparing"
    CHARGING = "Charging"
    SUSPENDED_EVSE = "SuspendedEVSE"
    SUSPENDED_EV = "SuspendedEV"
    FINISHING = "Finishing"
    RESERVED = "Reserved"
    UNAVAILABLE = "Unavailable"
    FAULTED = "Faulted"

class TransactionStatusEnum(str, enum.Enum):
    STARTED = "STARTED"
    PENDING_START = "PENDING_START"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    PENDING_STOP = "PENDING_STOP"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    BILLING_FAILED = "BILLING_FAILED"

class MessageDirectionEnum(str, enum.Enum):
    INBOUND = "IN"
    OUTBOUND = "OUT"

class FirmwareUpdateStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    INSTALLING = "INSTALLING"
    INSTALLED = "INSTALLED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    INSTALLATION_FAILED = "INSTALLATION_FAILED"
    CANCELLED = "CANCELLED"

# OCPP 1.6 Standard Error Codes
class OCPPErrorCodeEnum(str, enum.Enum):
    CONNECTOR_LOCK_FAILURE = "ConnectorLockFailure"
    EV_COMMUNICATION_ERROR = "EVCommunicationError"
    GROUND_FAILURE = "GroundFailure"
    HIGH_TEMPERATURE = "HighTemperature"
    INTERNAL_ERROR = "InternalError"
    LOCAL_LIST_CONFLICT = "LocalListConflict"
    NO_ERROR = "NoError"
    OTHER_ERROR = "OtherError"
    OVER_CURRENT_FAILURE = "OverCurrentFailure"
    OVER_VOLTAGE = "OverVoltage"
    POWER_METER_FAILURE = "PowerMeterFailure"
    POWER_SWITCH_FAILURE = "PowerSwitchFailure"
    READER_FAILURE = "ReaderFailure"
    RESET_FAILURE = "ResetFailure"
    UNDER_VOLTAGE = "UnderVoltage"
    WEAK_SIGNAL = "WeakSignal"

# Authentication enums
class UserRoleEnum(str, enum.Enum):
    ADMIN = "ADMIN"
    USER = "USER"  # EV drivers
    FRANCHISEE = "FRANCHISEE"  # Franchisee portal access

class AuthProviderEnum(str, enum.Enum):
    EMAIL = "EMAIL"
    GOOGLE = "GOOGLE"
    CLERK = "CLERK"
    UPI_GUEST = "UPI_GUEST"

class QRPaymentStatusEnum(str, enum.Enum):
    PAID = "PAID"
    CHARGING = "CHARGING"
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    REFUND_FAILED = "REFUND_FAILED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"

class WebhookSourceEnum(str, enum.Enum):
    CLERK = "CLERK"
    RAZORPAY = "RAZORPAY"

# Franchisee enums
class FranchiseeStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    KYC_SUBMITTED = "KYC_SUBMITTED"
    KYC_UNDER_REVIEW = "KYC_UNDER_REVIEW"
    KYC_NEEDS_CLARIFICATION = "KYC_NEEDS_CLARIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"

class FranchiseeBusinessTypeEnum(str, enum.Enum):
    INDIVIDUAL = "INDIVIDUAL"
    PROPRIETORSHIP = "PROPRIETORSHIP"
    PARTNERSHIP = "PARTNERSHIP"
    PRIVATE_LIMITED = "PRIVATE_LIMITED"
    LLP = "LLP"

class SettlementStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    TRANSFER_INITIATED = "TRANSFER_INITIATED"
    TRANSFER_PROCESSED = "TRANSFER_PROCESSED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    ON_HOLD = "ON_HOLD"

class CommissionChangeReasonEnum(str, enum.Enum):
    INITIAL_SETUP = "INITIAL_SETUP"
    CONTRACT_RENEWAL = "CONTRACT_RENEWAL"
    PERFORMANCE_ADJUSTMENT = "PERFORMANCE_ADJUSTMENT"
    PROMOTION = "PROMOTION"
    ADMIN_OVERRIDE = "ADMIN_OVERRIDE"

class GSTInvoiceStatusEnum(str, enum.Enum):
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"


# Models
class User(Model):
    id = fields.IntField(pk=True)
    
    # Authentication fields
    email = fields.CharField(max_length=255, unique=True)
    phone_number = fields.CharField(max_length=255, unique=True, null=True)
    
    # External authentication integration
    clerk_user_id = fields.CharField(max_length=255, unique=True, null=True)
    auth_provider = fields.CharEnumField(AuthProviderEnum, default=AuthProviderEnum.CLERK)
    
    # Profile fields
    full_name = fields.CharField(max_length=255, null=True)
    avatar_url = fields.CharField(max_length=500, null=True)  # From Google/social
    role = fields.CharEnumField(UserRoleEnum, default=UserRoleEnum.USER)
    
    # Status and permissions
    is_active = fields.BooleanField(default=True)
    is_email_verified = fields.BooleanField(default=False)
    terms_accepted_at = fields.DatetimeField(null=True)
    
    # Additional EV user fields
    preferred_language = fields.CharField(max_length=10, default="en")
    notification_preferences = fields.JSONField(default=dict)
    
    # RFID/Card integration for OCPP
    rfid_card_id = fields.CharField(max_length=255, unique=True, null=True)

    # UPI VPA for QR payment user lookup
    upi_vpa = fields.CharField(max_length=255, unique=True, null=True)
    
    # Legacy password support (will be deprecated)
    password_hash = fields.CharField(max_length=255, null=True)
    
    # Timestamps
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    last_login = fields.DatetimeField(null=True)
    
    # Existing relationships (unchanged)
    wallet: fields.ReverseRelation["Wallet"]
    vehicles: fields.ReverseRelation["VehicleProfile"]
    transactions: fields.ReverseRelation["Transaction"]
    
    class Meta:
        table = "app_user"
        
    @property
    def is_admin(self) -> bool:
        return self.role == UserRoleEnum.ADMIN
        
    @property
    def display_name(self) -> str:
        return self.full_name or self.email.split('@')[0]

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

class WalletTransaction(Model):
    id = fields.IntField(pk=True)
    wallet = fields.ForeignKeyField("models.Wallet", related_name="transactions")
    amount = fields.DecimalField(max_digits=10, decimal_places=2)
    type = fields.CharEnumField(TransactionTypeEnum)
    description = fields.TextField(null=True)
    charging_transaction = fields.ForeignKeyField("models.Transaction", related_name="wallet_transactions", null=True)
    payment_metadata = fields.JSONField(null=True)
    razorpay_order_id = fields.CharField(max_length=64, null=True, index=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "wallet_transaction"

class PaymentGateway(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    name = fields.CharField(max_length=100, null=True)
    api_key = fields.CharField(max_length=255, null=True)
    webhook_secret = fields.CharField(max_length=255, null=True)
    status = fields.BooleanField(default=True)
    config = fields.JSONField(null=True)
    default_currency = fields.CharField(max_length=3, default="INR")
    
    class Meta:
        table = "payment_gateway"

class VehicleProfile(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    user = fields.ForeignKeyField("models.User", related_name="vehicles")
    make = fields.CharField(max_length=100, null=True)
    model = fields.CharField(max_length=100, null=True)
    year = fields.IntField(null=True)
    
    class Meta:
        table = "vehicle_profile"

class ValidVehicleProfile(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    make = fields.CharField(max_length=100, null=True)
    model = fields.CharField(max_length=100, null=True)
    year = fields.IntField(null=True)
    
    class Meta:
        table = "valid_vehicle_profile"

class ChargingStation(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    name = fields.CharField(max_length=255, null=True)
    latitude = fields.FloatField(null=True)
    longitude = fields.FloatField(null=True)
    address = fields.TextField(null=True)

    # Franchisee ownership (NULL = VoltLync-owned)
    franchisee = fields.ForeignKeyField(
        "models.Franchisee", related_name="stations", null=True, on_delete=fields.SET_NULL
    )

    # Location details for GST place-of-supply
    state = fields.CharField(max_length=100, null=True)
    state_code = fields.CharField(max_length=5, null=True)
    pincode = fields.CharField(max_length=10, null=True)

    # Relationships
    chargers: fields.ReverseRelation["Charger"]

    class Meta:
        table = "charging_station"

class Charger(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    charge_point_string_id = fields.CharField(max_length=255, unique=True)
    external_charger_id = fields.CharField(max_length=255, unique=True, null=True)
    station = fields.ForeignKeyField("models.ChargingStation", related_name="chargers")
    name = fields.CharField(max_length=255, null=True)
    model = fields.CharField(max_length=100, null=True)
    vendor = fields.CharField(max_length=100, null=True)
    serial_number = fields.CharField(max_length=100, unique=True, null=True)
    firmware_version = fields.CharField(max_length=100, null=True)
    iccid = fields.CharField(max_length=100, null=True)
    imsi = fields.CharField(max_length=100, null=True)
    meter_type = fields.CharField(max_length=100, null=True)
    meter_serial_number = fields.CharField(max_length=100, null=True)
    latest_status = fields.CharEnumField(ChargerStatusEnum)
    last_heart_beat_time = fields.DatetimeField(null=True)
    
    # Relationships
    tariffs: fields.ReverseRelation["Tariff"]
    connectors: fields.ReverseRelation["Connector"]
    
    class Meta:
        table = "charger"

class Connector(Model):
    id = fields.IntField(pk=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="connectors")
    connector_id = fields.IntField()
    connector_type = fields.CharField(max_length=255)
    max_power_kw = fields.FloatField(null=True)
    
    class Meta:
        table = "connector"
        unique_together = [("charger", "connector_id")]

class Tariff(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="tariffs", null=True)
    rate_per_kwh = fields.DecimalField(max_digits=5, decimal_places=2)
    gst_percent = fields.DecimalField(max_digits=5, decimal_places=2, default=18.00)
    hsn_sac_code = fields.CharField(max_length=10, null=True)
    is_global = fields.BooleanField(default=False)

    class Meta:
        table = "tariff"

class Transaction(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    user = fields.ForeignKeyField("models.User", related_name="transactions")
    charger = fields.ForeignKeyField("models.Charger", related_name="transactions")
    vehicle = fields.ForeignKeyField("models.VehicleProfile", related_name="transactions", null=True)
    start_meter_kwh = fields.FloatField(null=True)
    end_meter_kwh = fields.FloatField(null=True)
    energy_consumed_kwh = fields.FloatField(null=True)
    start_time = fields.DatetimeField(auto_now_add=True)
    end_time = fields.DatetimeField(null=True)
    stop_reason = fields.TextField(null=True)
    transaction_status = fields.CharEnumField(TransactionStatusEnum)
    suspended_at = fields.DatetimeField(null=True)
    resumed_at = fields.DatetimeField(null=True)
    resume_count = fields.IntField(default=0)

    # Billing fields (populated after StopTransaction)
    energy_charge = fields.DecimalField(max_digits=10, decimal_places=2, null=True)  # Pre-GST energy cost
    gst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)     # GST on energy_charge
    total_billed = fields.DecimalField(max_digits=10, decimal_places=2, null=True)   # energy_charge + gst

    # Relationships
    wallet_transactions: fields.ReverseRelation["WalletTransaction"]
    meter_values: fields.ReverseRelation["MeterValue"]

    class Meta:
        table = "transaction"

class MeterValue(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    transaction = fields.ForeignKeyField("models.Transaction", related_name="meter_values")
    reading_kwh = fields.FloatField()
    current = fields.FloatField(null=True)
    voltage = fields.FloatField(null=True)
    power_kw = fields.FloatField(null=True)
    
    class Meta:
        table = "meter_value"

class OCPPLog(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    charge_point_id = fields.CharField(max_length=100, null=True)
    message_type = fields.CharField(max_length=100, null=True)
    direction = fields.CharEnumField(MessageDirectionEnum)
    payload = fields.JSONField(null=True)
    status = fields.CharField(max_length=50, null=True)
    correlation_id = fields.CharField(max_length=100, null=True)
    timestamp = fields.DatetimeField(auto_now_add=True)
    
    class Meta:
        table = "log"

class FirmwareFile(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    version = fields.CharField(max_length=50, unique=True, index=True)
    filename = fields.CharField(max_length=255)
    file_path = fields.CharField(max_length=500)
    file_size = fields.BigIntField()
    checksum = fields.CharField(max_length=64)
    description = fields.TextField(null=True)
    uploaded_by = fields.ForeignKeyField("models.User", related_name="uploaded_firmwares")
    is_active = fields.BooleanField(default=True)

    # Relationships
    firmware_updates: fields.ReverseRelation["FirmwareUpdate"]

    class Meta:
        table = "firmware_file"

class FirmwareUpdate(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="firmware_updates", index=True)
    firmware_file = fields.ForeignKeyField("models.FirmwareFile", related_name="firmware_updates")
    status = fields.CharEnumField(FirmwareUpdateStatusEnum, default=FirmwareUpdateStatusEnum.PENDING, index=True)
    initiated_by = fields.ForeignKeyField("models.User", related_name="initiated_updates")
    initiated_at = fields.DatetimeField(auto_now_add=True)
    download_url = fields.CharField(max_length=500)
    started_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)
    error_message = fields.TextField(null=True)
    retry_count = fields.IntField(default=0)

    class Meta:
        table = "firmware_update"
        unique_together = [("charger", "firmware_file")]

class SignalQuality(Model):
    """
    Stores cellular signal quality metrics from charge points.
    Data received via OCPP DataTransfer messages from JET_EV1 chargers.
    """
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)
    updated_at = fields.DatetimeField(auto_now=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="signal_quality_data", index=True)
    rssi = fields.IntField()  # Received Signal Strength Indicator (0-31 typical for GSM, 99=unknown)
    ber = fields.IntField()   # Bit Error Rate (0-7 for GSM, 99=unknown/not detectable)
    timestamp = fields.CharField(max_length=50)  # Timestamp from charger

    class Meta:
        table = "signal_quality"

class ChargerError(Model):
    """
    Stores error events from chargers received via OCPP StatusNotification.
    Captures both standard OCPP error codes and vendor-specific error codes.
    """
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="errors", index=True)
    connector_id = fields.IntField(index=True)
    status = fields.CharField(max_length=50)  # Charger status when error occurred
    error_code = fields.CharField(max_length=50, index=True)  # Standard OCPP error code
    vendor_error_code = fields.CharField(max_length=50, null=True, index=True)  # Vendor-specific error code
    vendor_id = fields.CharField(max_length=255, null=True)  # Vendor identifier
    info = fields.CharField(max_length=255, null=True)  # Additional error information
    error_timestamp = fields.DatetimeField(null=True)  # Timestamp from charger (if provided)
    is_resolved = fields.BooleanField(default=False, index=True)  # Track if error was resolved
    resolved_at = fields.DatetimeField(null=True)

    class Meta:
        table = "charger_error"

class AuditLog(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)
    # Actor
    actor_type = fields.CharField(max_length=20)       # "system", "admin", "user", "webhook", "ocpp"
    actor_id = fields.IntField(null=True)               # User.id when applicable
    actor_email = fields.CharField(max_length=255, null=True)
    # What happened
    action = fields.CharField(max_length=100, index=True)
    # Target entity
    entity_type = fields.CharField(max_length=50)
    entity_id = fields.CharField(max_length=255, index=True)
    # Context
    changes = fields.JSONField(null=True)

    class Meta:
        table = "audit_log"
        indexes = [("entity_type", "entity_id")]

class WebhookEvent(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)
    source = fields.CharEnumField(WebhookSourceEnum, index=True)
    event_type = fields.CharField(max_length=100, index=True)
    event_id = fields.CharField(max_length=255, null=True, index=True)
    payload = fields.JSONField(null=True)
    status = fields.CharField(max_length=20, default="processed")
    error_message = fields.TextField(null=True)

    class Meta:
        table = "webhook_event"

class ChargerQRCode(Model):
    id = fields.IntField(pk=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="qr_codes")
    razorpay_qr_code_id = fields.CharField(max_length=255, unique=True, index=True)
    image_url = fields.CharField(max_length=500)
    short_url = fields.CharField(max_length=500, null=True)
    is_active = fields.BooleanField(default=True)
    # Razorpay linked-account id this QR was created under. Null means the
    # QR is owned by the platform (VoltLync's merchant account). Stored at
    # creation time so later close/fetch calls can scope via the same
    # X-Razorpay-Account header even if the station is later reassigned.
    owner_razorpay_account_id = fields.CharField(max_length=50, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    # Relationships
    payments: fields.ReverseRelation["QRPayment"]

    class Meta:
        table = "charger_qr_code"

class QRPayment(Model):
    id = fields.IntField(pk=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="qr_payments")
    charger_qr_code = fields.ForeignKeyField("models.ChargerQRCode", related_name="payments")
    user = fields.ForeignKeyField("models.User", related_name="qr_payments", null=True)
    transaction = fields.ForeignKeyField("models.Transaction", related_name="qr_payment", null=True)
    razorpay_payment_id = fields.CharField(max_length=255, unique=True, index=True)
    razorpay_qr_code_id = fields.CharField(max_length=255, index=True)
    amount_paid = fields.DecimalField(max_digits=10, decimal_places=2)
    customer_vpa = fields.CharField(max_length=255, null=True, index=True)
    customer_name = fields.CharField(max_length=255, null=True)
    customer_contact = fields.CharField(max_length=255, null=True)
    energy_cost = fields.DecimalField(max_digits=10, decimal_places=2, null=True)   # Pre-GST energy charge
    gst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)    # GST on energy_cost
    platform_fee = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    razorpay_commission = fields.DecimalField(max_digits=10, decimal_places=2, null=True)  # Base Razorpay commission (fee - tax), rupees
    razorpay_gst = fields.DecimalField(max_digits=10, decimal_places=2, null=True)         # GST on Razorpay commission (tax), rupees
    fee_source = fields.CharField(max_length=20, null=True)                                 # 'webhook', 'api', or 'estimated'
    refund_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    razorpay_refund_id = fields.CharField(max_length=255, null=True, index=True)
    refund_processed_at = fields.DatetimeField(null=True)
    refund_failure_reason = fields.TextField(null=True)
    status = fields.CharEnumField(QRPaymentStatusEnum)
    failure_reason = fields.TextField(null=True)
    metadata = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "qr_payment"
        indexes = [("charger_id", "status", "transaction_id")]

# Franchisee Models

class Franchisee(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    # Identity (minimal at creation, rest filled during KYC)
    business_name = fields.CharField(max_length=255)
    business_type = fields.CharEnumField(
        FranchiseeBusinessTypeEnum, null=True
    )
    contact_name = fields.CharField(max_length=255)
    contact_email = fields.CharField(max_length=255, unique=True)
    contact_phone = fields.CharField(max_length=20)
    address = fields.TextField(null=True)

    # Tax/Legal (populated during KYC or by admin)
    pan_number = fields.CharField(max_length=10, unique=True, null=True)
    gstin = fields.CharField(max_length=15, unique=True, null=True)
    tan_number = fields.CharField(max_length=10, null=True)

    # Location (for GST place-of-supply on invoices)
    state = fields.CharField(max_length=100, null=True)
    state_code = fields.CharField(max_length=5, null=True)

    # Bank details (reference copy; Razorpay holds canonical)
    bank_account_name = fields.CharField(max_length=255, null=True)
    bank_account_number = fields.CharField(max_length=30, null=True)
    bank_ifsc_code = fields.CharField(max_length=11, null=True)

    # Razorpay Route integration
    razorpay_account_id = fields.CharField(
        max_length=50, unique=True, null=True
    )
    razorpay_account_status = fields.CharField(max_length=50, null=True)
    razorpay_onboarding_url = fields.CharField(max_length=500, null=True)
    kyc_submitted_at = fields.DatetimeField(null=True)
    kyc_verified_at = fields.DatetimeField(null=True)
    # Route transfer gates (driven by account.* webhooks)
    transfers_enabled = fields.BooleanField(default=True)
    funds_on_hold = fields.BooleanField(default=False)

    # Commission (VoltLync's platform cut, default 20%)
    commission_percent = fields.DecimalField(
        max_digits=5, decimal_places=2, default=20.00
    )
    commission_effective_from = fields.DateField(default=date.today)

    # TDS (configurable per franchisee, default 10%)
    tds_rate_percent = fields.DecimalField(
        max_digits=5, decimal_places=2, default=10.00
    )
    tds_pan_verified = fields.BooleanField(default=False)

    # Status
    status = fields.CharEnumField(
        FranchiseeStatusEnum, default=FranchiseeStatusEnum.DRAFT
    )
    status_reason = fields.TextField(null=True)
    activated_at = fields.DatetimeField(null=True)
    deactivated_at = fields.DatetimeField(null=True)

    # Admin
    onboarded_by = fields.ForeignKeyField(
        "models.User", related_name="onboarded_franchisees", null=True
    )
    notes = fields.TextField(null=True)

    # User account for portal access (1:1)
    user = fields.OneToOneField(
        "models.User", related_name="franchisee_profile", null=True
    )

    # Relationships
    stations: fields.ReverseRelation["ChargingStation"]
    ledger_entries: fields.ReverseRelation["CommissionLedgerEntry"]
    commission_audit_logs: fields.ReverseRelation["CommissionAuditLog"]

    class Meta:
        table = "franchisee"


class CommissionLedgerEntry(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    # Links
    transaction = fields.OneToOneField(
        "models.Transaction", related_name="settlement"
    )
    franchisee = fields.ForeignKeyField(
        "models.Franchisee", related_name="ledger_entries"
    )
    qr_payment = fields.ForeignKeyField(
        "models.QRPayment", related_name="settlement", null=True
    )
    wallet_transaction = fields.ForeignKeyField(
        "models.WalletTransaction", related_name="settlement", null=True
    )

    # Gross
    gross_amount = fields.DecimalField(max_digits=10, decimal_places=2)
    payment_method = fields.CharField(max_length=20)  # WALLET | QR_UPI
    razorpay_payment_id = fields.CharField(max_length=255, null=True)

    # Deductions
    refund_amount = fields.DecimalField(
        max_digits=10, decimal_places=2, default=0.00
    )
    pg_fee_amount = fields.DecimalField(
        max_digits=10, decimal_places=2, default=0.00
    )
    net_amount = fields.DecimalField(max_digits=10, decimal_places=2)

    # GST
    gst_collected = fields.DecimalField(max_digits=10, decimal_places=2)
    net_excl_gst = fields.DecimalField(max_digits=10, decimal_places=2)

    # Commission split (calculated on net_excl_gst)
    commission_percent = fields.DecimalField(max_digits=5, decimal_places=2)
    platform_commission = fields.DecimalField(max_digits=10, decimal_places=2)
    tds_rate_percent = fields.DecimalField(
        max_digits=5, decimal_places=2, default=0.00
    )
    tds_amount = fields.DecimalField(
        max_digits=10, decimal_places=2, default=0.00
    )
    transfer_fee = fields.DecimalField(
        max_digits=10, decimal_places=2, default=0.00
    )

    # Franchisee payout
    franchisee_payout = fields.DecimalField(max_digits=10, decimal_places=2)

    # Energy data (denormalized for reporting)
    energy_consumed_kwh = fields.FloatField()
    tariff_rate_per_kwh = fields.DecimalField(max_digits=5, decimal_places=2)

    # Transfer tracking
    settlement_status = fields.CharEnumField(
        SettlementStatusEnum, default=SettlementStatusEnum.PENDING
    )
    razorpay_transfer_id = fields.CharField(
        max_length=255, unique=True, null=True
    )
    transfer_initiated_at = fields.DatetimeField(null=True)
    transfer_processed_at = fields.DatetimeField(null=True)
    settled_at = fields.DatetimeField(null=True)
    failure_reason = fields.TextField(null=True)
    retry_count = fields.IntField(default=0)

    # Idempotency
    idempotency_key = fields.CharField(max_length=255, unique=True)

    class Meta:
        table = "commission_ledger_entry"


class CommissionAuditLog(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    franchisee = fields.ForeignKeyField(
        "models.Franchisee", related_name="commission_audit_logs"
    )
    previous_percent = fields.DecimalField(
        max_digits=5, decimal_places=2, null=True
    )
    new_percent = fields.DecimalField(max_digits=5, decimal_places=2)
    reason = fields.CharEnumField(CommissionChangeReasonEnum)
    effective_from = fields.DateField()
    changed_by = fields.ForeignKeyField(
        "models.User", related_name="commission_changes"
    )
    notes = fields.TextField(null=True)

    class Meta:
        table = "commission_audit_log"


# GST Invoice Models

class GSTInvoiceCounter(Model):
    """Sequential invoice numbering per (franchisee, series, FY).
    franchisee=NULL means VoltLync is the supplier."""
    id = fields.IntField(pk=True)
    franchisee = fields.ForeignKeyField(
        "models.Franchisee", related_name="invoice_counters", null=True
    )
    series = fields.CharField(max_length=10)  # WALLET, QR
    financial_year = fields.CharField(max_length=10)  # e.g. 2026-27
    last_number = fields.IntField(default=0)

    class Meta:
        table = "gst_invoice_counter"
        unique_together = [("franchisee", "series", "financial_year")]


class GSTInvoice(Model):
    """Per-session customer-facing GST tax invoice."""
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    # Identity
    invoice_number = fields.CharField(max_length=50, unique=True)
    status = fields.CharEnumField(
        GSTInvoiceStatusEnum, default=GSTInvoiceStatusEnum.ISSUED
    )
    invoice_date = fields.DatetimeField(auto_now_add=True)

    # Links
    transaction = fields.OneToOneField(
        "models.Transaction", related_name="gst_invoice"
    )
    franchisee = fields.ForeignKeyField(
        "models.Franchisee", related_name="gst_invoices", null=True
    )
    user = fields.ForeignKeyField(
        "models.User", related_name="gst_invoices", null=True
    )

    # Supplier snapshot (franchisee or VoltLync)
    supplier_name = fields.CharField(max_length=255)
    supplier_gstin = fields.CharField(max_length=20, null=True)
    supplier_address = fields.TextField(null=True)
    supplier_state = fields.CharField(max_length=100, null=True)
    supplier_state_code = fields.CharField(max_length=5, null=True)

    # Customer snapshot
    customer_name = fields.CharField(max_length=255, null=True)
    customer_identifier = fields.CharField(max_length=255, null=True)  # UPI ID, email, phone
    customer_address = fields.TextField(null=True)

    # Station/Charger snapshot
    station_name = fields.CharField(max_length=255, null=True)
    station_location = fields.CharField(max_length=500, null=True)
    charger_id_str = fields.CharField(max_length=255, null=True)
    connector_type = fields.CharField(max_length=50, null=True)

    # Charging details
    energy_consumed_kwh = fields.FloatField()
    tariff_rate_incl_tax = fields.DecimalField(max_digits=10, decimal_places=2)
    charged_on = fields.DatetimeField(null=True)
    duration_seconds = fields.IntField(null=True)
    hsn_sac_code = fields.CharField(max_length=10, default="998749")

    # Line items (pre-tax)
    energy_taxable_value = fields.DecimalField(max_digits=10, decimal_places=2)
    gateway_charges = fields.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    gateway_hsn_code = fields.CharField(max_length=10, default="997158")
    total_taxable_value = fields.DecimalField(max_digits=10, decimal_places=2)

    # Tax breakdown
    is_inter_state = fields.BooleanField(default=False)
    cgst_rate = fields.DecimalField(max_digits=5, decimal_places=2, null=True)
    cgst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    sgst_rate = fields.DecimalField(max_digits=5, decimal_places=2, null=True)
    sgst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    igst_rate = fields.DecimalField(max_digits=5, decimal_places=2, null=True)
    igst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)

    # Totals
    total_tax = fields.DecimalField(max_digits=10, decimal_places=2)
    total_amount = fields.DecimalField(max_digits=10, decimal_places=2)
    amount_in_words = fields.CharField(max_length=500, null=True)

    # Payment info (for QR sessions)
    payment_method = fields.CharField(max_length=20, null=True)  # UPI, WALLET
    transaction_amount = fields.DecimalField(
        max_digits=10, decimal_places=2, null=True
    )  # What customer paid (QR prepayment)
    refund_amount = fields.DecimalField(
        max_digits=10, decimal_places=2, null=True
    )

    # PDF
    pdf_url = fields.CharField(max_length=500, null=True)

    # Audit
    cancelled_at = fields.DatetimeField(null=True)
    cancellation_reason = fields.TextField(null=True)

    class Meta:
        table = "gst_invoice"


class GSTCreditNote(Model):
    """Credit note against a GST invoice (for refunds/corrections)."""
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    credit_note_number = fields.CharField(max_length=50, unique=True)
    original_invoice = fields.ForeignKeyField(
        "models.GSTInvoice", related_name="credit_notes"
    )
    franchisee = fields.ForeignKeyField(
        "models.Franchisee", related_name="credit_notes", null=True
    )

    reason = fields.CharField(max_length=255)
    credit_amount = fields.DecimalField(max_digits=10, decimal_places=2)

    # Tax mirror
    cgst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    sgst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    igst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)

    issue_date = fields.DatetimeField(auto_now_add=True)
    pdf_url = fields.CharField(max_length=500, null=True)

    class Meta:
        table = "gst_credit_note"


# Pydantic models for API serialization
User_Pydantic = pydantic_model_creator(User, name="User")
UserIn_Pydantic = pydantic_model_creator(User, name="UserIn", exclude_readonly=True)
Charger_Pydantic = pydantic_model_creator(Charger, name="Charger")
OCPPLog_Pydantic = pydantic_model_creator(OCPPLog, name="OCPPLog")
SignalQuality_Pydantic = pydantic_model_creator(SignalQuality, name="SignalQuality")
ChargerError_Pydantic = pydantic_model_creator(ChargerError, name="ChargerError")
AuditLog_Pydantic = pydantic_model_creator(AuditLog, name="AuditLog")
WebhookEvent_Pydantic = pydantic_model_creator(WebhookEvent, name="WebhookEvent")
ChargerQRCode_Pydantic = pydantic_model_creator(ChargerQRCode, name="ChargerQRCode")
QRPayment_Pydantic = pydantic_model_creator(QRPayment, name="QRPayment")
