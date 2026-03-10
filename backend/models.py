# Tortoise ORM Models
import enum
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
    charger = fields.OneToOneField("models.Charger", related_name="qr_code")
    razorpay_qr_code_id = fields.CharField(max_length=255, unique=True, index=True)
    image_url = fields.CharField(max_length=500)
    short_url = fields.CharField(max_length=500, null=True)
    is_active = fields.BooleanField(default=True)
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
    customer_vpa = fields.CharField(max_length=255, null=True)
    customer_name = fields.CharField(max_length=255, null=True)
    customer_contact = fields.CharField(max_length=255, null=True)
    energy_cost = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    platform_fee = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    refund_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    razorpay_refund_id = fields.CharField(max_length=255, null=True)
    status = fields.CharEnumField(QRPaymentStatusEnum)
    failure_reason = fields.TextField(null=True)
    metadata = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "qr_payment"

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
