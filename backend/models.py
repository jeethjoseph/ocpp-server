# Tortoise ORM Models
import enum
from datetime import date
from tortoise.models import Model
from tortoise import fields
from tortoise.signals import pre_save
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

class ChargerAvailabilityEnum(str, enum.Enum):
    OPERATIVE = "Operative"
    INOPERATIVE = "Inoperative"

class ChargerPurposeEnum(str, enum.Enum):
    """What a charger is FOR — serviceability, not state and not identity.

    Deliberately one enum rather than two booleans: every TEST unit is
    non-public, so is_test + is_public would admit a bench unit advertised as
    bookable, and the behaviours do not decompose anyway (TEST gates billing,
    PRIVATE would gate only visibility).

    PRIVATE (real hardware, real billing, not advertised) is in ADR 0028 but has
    no instance in the fleet, so it is deliberately NOT declared here. Tortoise
    renders a CharEnumField as a plain VARCHAR with no DB enum type or CHECK
    (see migration 42 for `availability`), so declaring PRIVATE later needs no
    data migration. Do not add it speculatively.
    """

    PUBLIC = "PUBLIC"
    TEST = "TEST"

class ConnectorTypeEnum(str, enum.Enum):
    """Canonical connector types. Physical behavior (start gate, suspend
    window) is declared per-type in services.charger_type_service.CONNECTOR_TRAITS
    — every member here MUST have a traits row there (test-enforced)."""
    TYPE2 = "Type2"
    TYPE1 = "Type1"
    SOCKET = "Socket"
    CCS = "CCS"
    CHADEMO = "CHAdeMO"
    GBT = "GB/T"
    DOMESTIC = "domestic"


# Name and SQL for the DB-level guard on `connector.connector_type`, in one
# place so the migration that installs it and the test harness that recreates it
# cannot drift from the enum above — the same doctrine migration 58 applies to
# the Asset Code patterns.
#
# Tortoise models a CharEnumField as a plain VARCHAR, so without this the enum
# exists only in Python: migration 49 retyped the column but added no
# constraint, and `CharEnumFieldInstance.to_python_value` raises ValueError on
# any value that is not byte-exactly a member. One bad row would therefore break
# every path that loads a Connector — suspend-window selection on disconnect,
# remote start, QR start, the admin charger list, the public stations feed.
CONNECTOR_TYPE_CHECK = "connector_type_canonical"


def connector_type_check_sql() -> str:
    """`ALTER TABLE ... ADD CONSTRAINT` for the canonical-connector-type CHECK."""
    allowed = ", ".join(f"'{m.value}'" for m in ConnectorTypeEnum)
    return (
        f'ALTER TABLE "connector" ADD CONSTRAINT "{CONNECTOR_TYPE_CHECK}" '
        f'CHECK ("connector_type" IN ({allowed}));'
    )

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


# The states in which a Transaction still OCCUPIES its charger — i.e. a second
# session must not be opened alongside it. Two call sites need exactly this set
# and must not drift apart: the StartTransaction reconcile guard
# (`main._reconcile_existing_open_transaction`) and the QR double-payment guard
# (`QRPaymentService._create_qr_payment_locked`).
#
# SUSPENDED is included. It is not a terminal state — it means the charger went
# quiet mid-session and we are holding the session open for a reconnect. Firmware
# that keeps the contactor closed through a CSMS outage makes this the state a
# genuinely-charging session sits in, so treating it as "free" lets a second
# payment start a parallel session on a charger that is physically busy.
#
# PENDING_STOP is deliberately EXCLUDED. A txn mid-normal-stop is already being
# finalized by the StopTransaction path: superseding it races that path into a
# double-finalize (the finalizer's idempotency guard only short-circuits on
# TERMINAL states), and per ADR 0021 the session-end seam is not "busy" — a
# payment arriving there should fall through to the normal new-session flow
# rather than be rejected. A genuinely stuck PENDING_STOP is caught by the
# disconnect / stale-suspended sweeps.
OPEN_TRANSACTION_STATES = [
    TransactionStatusEnum.STARTED,
    TransactionStatusEnum.PENDING_START,
    TransactionStatusEnum.RUNNING,
    TransactionStatusEnum.SUSPENDED,
]


class MessageDirectionEnum(str, enum.Enum):
    INBOUND = "IN"
    OUTBOUND = "OUT"

class FirmwareUpdateStatusEnum(str, enum.Enum):
    PENDING = "PENDING"        # active: scheduled, in-flight, or waiting for next retry
    INSTALLED = "INSTALLED"    # terminal success (confirmed via BootNotification or admin)
    FAILED = "FAILED"          # terminal failure (retry budget exhausted or admin marked)
    CANCELLED = "CANCELLED"    # terminal admin cancel before any attempt

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
    # Refund decided + amount committed, but the Razorpay outcome is not yet
    # confirmed — the window between the claim (T1) and the persist (T2) where
    # the network call runs WITHOUT a row lock. A crash here strands the row in
    # this state; BillingRetryService resumes it idempotently. See ADR 0018.
    REFUND_IN_PROGRESS = "REFUND_IN_PROGRESS"

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
    BELOW_THRESHOLD = "BELOW_THRESHOLD"

class CommissionChangeReasonEnum(str, enum.Enum):
    INITIAL_SETUP = "INITIAL_SETUP"
    CONTRACT_RENEWAL = "CONTRACT_RENEWAL"
    PERFORMANCE_ADJUSTMENT = "PERFORMANCE_ADJUSTMENT"
    PROMOTION = "PROMOTION"
    ADMIN_OVERRIDE = "ADMIN_OVERRIDE"

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
    """User wallet. Balance is derived from `WalletTransaction` rows via
    `WalletService.get_balance`; there is no stored balance column post
    migration 33. The wallet row exists to anchor FKs and to be locked
    via `SELECT FOR UPDATE` during billing/top-up flows.
    """
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    user = fields.OneToOneField("models.User", related_name="wallet")

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

    async def save(self, *args, **kwargs):
        """Reject negative amounts.

        NOTE: Tortoise's `bulk_create()` does not call `save()` per row,
        so it bypasses this validator. The DB CHECK constraint
        `wallet_transaction_amount_non_negative` (added by migration 32,
        validated by migration 33) is the backstop for that path — a
        negative `bulk_create` row will raise `IntegrityError` from
        Postgres rather than `ValueError` from here.
        """
        if self.amount is not None and self.amount < 0:
            raise ValueError(
                f"wallet_transaction.amount must be >= 0, got {self.amount}"
            )
        await super().save(*args, **kwargs)

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
    # Admin-set availability intent — orthogonal to latest_status which
    # reflects what the charger reports. The toggle in the admin UI reads
    # THIS field, not latest_status. See ADR 0008.
    availability = fields.CharEnumField(
        ChargerAvailabilityEnum,
        default=ChargerAvailabilityEnum.OPERATIVE,
    )

    # The Asset Code — the customer-facing identifier (ADR 0028). An
    # environment series plus a zero-padded integer: VOW0001 production,
    # VOWS0001 staging/development.
    #
    # System-allocated at creation, never typed, never reused, gaps never
    # backfilled. It names the PHYSICAL UNIT, not a position, so it survives a
    # station re-parent and a replacement unit brings its own rather than
    # inheriting the dead one's. Bears no relationship to `name`.
    #
    # NOT NULL: every charger has a code, bench units included. Nothing about
    # the code says what a unit is for — that is `purpose`. The rejected
    # alternative (nullable for TEST, with a two-column CHECK and a
    # mint-on-promotion path) lost on call-site count: 19 admin/franchisee
    # surfaces render charger identity against 3 customer-facing ones, and
    # admin surfaces are exactly where bench units appear, so a nullable code
    # puts a null-branch everywhere it would actually be hit.
    #
    # Do not write to it directly — allocation goes through
    # services.charger_code_service, and a code is immutable once assigned.
    asset_code = fields.CharField(max_length=12, unique=True)

    # Serviceability — orthogonal to BOTH `latest_status` (what the charger
    # reports) and `availability` (what an admin commanded on serviceable
    # hardware). Marking a bench unit Inoperative would conflate "temporarily
    # withdrawn" with "not fleet hardware at all". See ADR 0008 and ADR 0028.
    #
    # The PUBLIC default is load-bearing: it makes every gate that reads this
    # column FAIL OPEN, so a row missed by any backfill keeps billing and stays
    # visible rather than silently going dark.
    purpose = fields.CharEnumField(
        ChargerPurposeEnum,
        # Explicit, and wider than the longest declared member. Tortoise
        # otherwise sizes the VARCHAR to the longest value it can see (6, for
        # PUBLIC), which would make declaring ADR 0028's PRIVATE later an
        # ALTER rather than the free change the ADR claims it is. Seven
        # characters buys that promise for nothing.
        max_length=7,
        default=ChargerPurposeEnum.PUBLIC,
    )

    last_heart_beat_time = fields.DatetimeField(null=True)

    # SHA-256 of the Charger Auth Key — the per-unit machine credential from
    # ADR 0020. Plaintext is revealed exactly once at provisioning and never
    # stored; a lost key is rotated, never recovered. SHA-256 rather than
    # bcrypt is deliberate: a high-entropy 20-byte machine secret checked on
    # every reconnect wants a fast hash.
    #
    # Nullable, and null is load-bearing per environment:
    #   - Diagnostic Bundle upload (ADR 0029) REJECTS a null-hash charger —
    #     there is no installed base on that endpoint, so it is enforced from
    #     day one.
    #   - The OCPP WebSocket handshake does NOT yet consult this column;
    #     ADR 0020 remains PROPOSED and chargers still connect unauthenticated.
    auth_key_hash = fields.CharField(max_length=64, null=True)

    # Relationships
    tariffs: fields.ReverseRelation["Tariff"]
    connectors: fields.ReverseRelation["Connector"]

    class Meta:
        table = "charger"

@pre_save(Charger)
async def allocate_asset_code(sender, instance: Charger, using_db, update_fields):
    """Give every charger an Asset Code at insert time (ADR 0028).

    Lives here rather than in the create endpoint so the invariant is
    structural: no creation path — the admin API, a seed script, a future bulk
    import or OCPI onboarding — can produce a charger without a code. That is
    the same reasoning that makes the code system-allocated in the first place;
    an invariant enforced only at one call site is an invariant with a
    deadline.

    Allocation comes from a Postgres sequence, so concurrent creates cannot
    collide and there is no retry to get wrong. See migration 60.

    Cheap on the hot path: chargers are saved constantly by the heartbeat and
    StatusNotification handlers, and every one of those already has a code, so
    this costs a single attribute check and returns.
    """
    if instance.asset_code:
        return
    from services.charger_code_service import next_asset_code

    instance.asset_code = await next_asset_code(using_db=using_db)


class Connector(Model):
    id = fields.IntField(pk=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="connectors")
    connector_id = fields.IntField()
    # max_length kept at 255 so the column definition is unchanged from the
    # free-text era (no data migration needed; live data is already canonical).
    connector_type = fields.CharEnumField(ConnectorTypeEnum, max_length=255)
    max_power_kw = fields.FloatField(null=True)
    
    class Meta:
        table = "connector"
        unique_together = [("charger", "connector_id")]

class Tariff(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    # At most one charger-specific tariff per charger (the domain invariant —
    # get_applicable_tariffs_for_chargers resolves a single charger tariff then
    # falls back to global). Enforced via the unique_together in Meta below;
    # Postgres treats NULLs as distinct, so global tariffs (charger_id IS NULL,
    # is_global=True) may coexist. See upsert-race-hardening issue 01.
    charger = fields.ForeignKeyField("models.Charger", related_name="tariffs", null=True)
    # Back-calculated base rate (GST- and gateway-exclusive), used by line-item
    # billing math and shown as the Energy-line "Rate" on the itemised invoice.
    # Equals `rate_gst_included / (1 + gst_pct/100)`. See ADR 0026.
    rate_per_kwh = fields.DecimalField(max_digits=8, decimal_places=4)
    # Operator-typed, customer-displayed GST-inclusive, GATEWAY-EXCLUSIVE energy
    # price. Source of truth for the customer-facing tariff display. The gateway
    # is a separate actual line, never folded in. See ADR 0026 (renamed from
    # tariff_per_kwh_all_in, which baked in a synthetic 2% gateway).
    rate_gst_included = fields.DecimalField(max_digits=10, decimal_places=4)
    gst_percent = fields.DecimalField(max_digits=5, decimal_places=2, default=18.00)
    hsn_sac_code = fields.CharField(max_length=10, null=True)
    is_global = fields.BooleanField(default=False)

    class Meta:
        table = "tariff"
        unique_together = [("charger",)]

class Transaction(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    user = fields.ForeignKeyField("models.User", related_name="transactions")
    charger = fields.ForeignKeyField("models.Charger", related_name="transactions")
    vehicle = fields.ForeignKeyField("models.VehicleProfile", related_name="transactions", null=True)
    start_meter_kwh = fields.DecimalField(max_digits=12, decimal_places=3, null=True)
    end_meter_kwh = fields.DecimalField(max_digits=12, decimal_places=3, null=True)
    energy_consumed_kwh = fields.DecimalField(max_digits=12, decimal_places=3, null=True)
    start_time = fields.DatetimeField(auto_now_add=True)
    end_time = fields.DatetimeField(null=True)
    # Charger-reported session boundaries, as carried on the StartTransaction /
    # StopTransaction frames. Distinct from start_time / end_time, which are
    # SERVER RECEIPT times and remain the basis of billing and the GST Invoice.
    # Under offline continuity a StopTransaction can arrive hours after the
    # session actually ended, so reported_end_time is the only record of when
    # the charge really stopped. NULL when absent or rejected by the clock
    # plausibility guard in utils.parse_ocpp_timestamp — never silently
    # substituted with receipt time. See ADR 0031.
    reported_start_time = fields.DatetimeField(null=True)
    reported_end_time = fields.DatetimeField(null=True)
    stop_reason = fields.TextField(null=True)
    transaction_status = fields.CharEnumField(TransactionStatusEnum)
    suspended_at = fields.DatetimeField(null=True)
    resumed_at = fields.DatetimeField(null=True)
    resume_count = fields.IntField(default=0)

    # Billing fields (populated after StopTransaction)
    energy_charge = fields.DecimalField(max_digits=10, decimal_places=2, null=True)  # Pre-GST energy cost
    gst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)     # GST on energy_charge
    gst_rate_percent = fields.DecimalField(max_digits=5, decimal_places=2, default=18.00)  # GST rate snapshot at billing
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
    # When the CHARGER says it took this reading, from the OCPP frame's own
    # `timestamp`. `created_at` is when WE received it — the two diverge by the
    # length of an outage once queued frames are replayed on reconnect, which
    # is exactly when the distinction matters. NULL when the frame carried no
    # timestamp or the clock guard rejected it; readers fall back to created_at
    # (see services.meter_readings.latest_meter_value). ADR 0031.
    #
    # Deliberately NOT indexed. Reads order by COALESCE(measured_at, created_at),
    # and a btree index on measured_at alone CANNOT serve that expression —
    # verified on a 20k-row probe with enable_seqscan=off, where the planner
    # still chose a full scan + top-N heapsort over using it. An index here
    # would cost write amplification on the highest-write table in the system
    # (one row per MeterValues frame per charger) and return nothing. Every
    # reader narrows by transaction_id first, which the FK index already serves,
    # and none of them sit on a per-frame path. If profiling ever disagrees, the
    # index that would actually work is the matching expression index:
    #   (transaction_id, COALESCE(measured_at, created_at) DESC, id DESC)
    measured_at = fields.DatetimeField(null=True)
    transaction = fields.ForeignKeyField("models.Transaction", related_name="meter_values")
    reading_kwh = fields.DecimalField(max_digits=12, decimal_places=3)
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
    timestamp = fields.DatetimeField(auto_now_add=True, index=True)

    class Meta:
        table = "log"
        # Logs Console query surface — see ADR 0014. The standalone `timestamp`
        # index (above) backs the default all-chargers/all-actions date window
        # and the retention cleanup's `timestamp`-keyed deletes; the composites
        # back charger- and action-filtered queries.
        indexes = [
            ("charge_point_id", "timestamp"),
            ("message_type", "timestamp"),
        ]

class FirmwareFile(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    version = fields.CharField(max_length=50, unique=True, index=True)
    filename = fields.CharField(max_length=255)
    file_path = fields.CharField(max_length=500)  # legacy local-filesystem path; null for S3-only uploads
    s3_key = fields.CharField(max_length=500, null=True)  # null on rows uploaded before S3 migration
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
    download_url = fields.TextField()
    started_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)
    error_message = fields.TextField(null=True)
    attempt_count = fields.IntField(default=0)  # number of UpdateFirmware sends so far
    last_attempt_at = fields.DatetimeField(null=True)  # when the last attempt was sent
    next_retry_at = fields.DatetimeField(null=True, index=True)  # scheduler wakes up rows whose retry is due

    class Meta:
        table = "firmware_update"
        unique_together = [("charger", "firmware_file")]

class SignalQuality(Model):
    """
    Stores cellular signal quality + modem telemetry from charge points.
    Data received via OCPP DataTransfer messages (vendorId=VoltLync,
    messageId=SignalQuality). The "signal_quality" table name is a
    historical misnomer — see ADR 0009 — the row also carries modem
    board temperature.
    """
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)
    updated_at = fields.DatetimeField(auto_now=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="signal_quality_data", index=True)
    rssi = fields.IntField()  # Received Signal Strength Indicator (0-31 typical for GSM, 99=unknown)
    ber = fields.IntField()   # Bit Error Rate (0-7 for GSM, 99=unknown/not detectable)
    temperature_celsius = fields.FloatField(null=True)  # Modem board temperature; optional — older firmware omits it
    timestamp = fields.CharField(max_length=50)  # Timestamp from charger

    class Meta:
        table = "signal_quality"


class DiagnosticBundle(Model):
    """One Diagnostic Bundle upload — the index over the S3 archive (ADR 0029).

    The row exists to answer *"did we receive everything from this charger?"*.
    The trace content itself lives in S3; this table holds only what is needed
    to detect loss, which the bundle body cannot tell us on its own.

    Loss is signalled two ways, and they are NOT the pair ADR 0029 described:
      * a **silence window** — the span between the previous bundle's
        ``last_utc`` and this one's ``first_utc`` — means records are missing.
        Derived at read time, never stored, because a delayed bundle can arrive
        later and fill the hole.
      * ``ring_wrap_events`` > 0 means the charger's buffer overwrote records
        before it could deliver them.

    The cumulative "how many records were destroyed in total" figure that
    ``overflow_delta`` carried is **gone and not approximated**. It required a
    monotonic counter held separately from the data it describes, and the
    charger cannot persist one across a reboot. See ADR 0030.
    """
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)
    charger = fields.ForeignKeyField("models.Charger", related_name="diagnostic_bundles", index=True)

    # When this bundle's records were actually written, reconstructed from the
    # in-band TIME_SYNC anchors (ADR 0030). Null when nothing in the body
    # anchored — a real state, not an error. `time_approximate` marks a window
    # that fell back to receipt time, or one derived from only some segments;
    # such a window must never be read as evidence of a loss gap.
    first_utc = fields.DatetimeField(null=True)
    last_utc = fields.DatetimeField(null=True)
    time_approximate = fields.BooleanField(default=False)

    # Count of in-band `ring wrapped mid-upload` lines. A RECENCY signal — the
    # buffer is destroying undelivered records right now — never a running
    # total. Cumulative overwrite accounting needs a counter in storage separate
    # from the data it describes, which this hardware cannot keep (ADR 0030).
    ring_wrap_events = fields.IntField(default=0)

    # SHA-256 of the raw body with any legacy `#VLTDIAG/` line stripped — the
    # bundle's identity (ADR 0030). Nullable only because rows written before
    # the digest existed have none; Postgres treats NULLs as distinct, so those
    # rows do not collide under the unique constraint. Every row written since
    # has one.
    content_sha256 = fields.CharField(max_length=64, null=True)

    s3_key = fields.CharField(max_length=512)

    # Set only once the S3 object is confirmed durable (ADR 0030, issue 06).
    #
    # The row is written BEFORE the object, so a failed upload can never strand
    # an object no row points at — the ordering that produced 195 orphans in one
    # morning. That inverts the risk: a row can now outlive a missing object.
    # `archived_at` is what keeps that from becoming a durability lie. A row
    # with it NULL is a *reservation*, not a delivery: it is invisible to the
    # duplicate check, so a charger retrying is told to re-send rather than
    # being falsely assured we hold its records.
    archived_at = fields.DatetimeField(null=True)

    size_bytes = fields.IntField()
    line_count = fields.IntField(default=0)

    class Meta:
        table = "diagnostic_bundle"
        # Idempotency key. A charger that retries after a lost response re-sends
        # the same bundle; the retry must be a no-op, not a duplicate archive.
        # Keyed on content rather than sequence: the firmware reuses sequence
        # numbers across genuinely different bundles, so a sequence key made
        # every retry look like a reflash (ADR 0030).
        # Content is the arbiter now; the sequence constraint is dropped because
        # the firmware reuses sequence numbers across different bundles.
        unique_together = (("charger", "content_sha256"),)


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


class RazorpayApiLog(Model):
    """Outbound audit trail for mutating Razorpay onboarding-chain calls.

    Counterpart of ``WebhookEvent`` (which logs inbound). Captures the
    request body we sent + the response/error we got back, with sensitive
    fields (PAN, account_number, IFSC, etc.) masked via
    ``RazorpayService._mask_sensitive``. Read-only fetches and high-volume
    calls (transfers / refunds / payments / QR) are intentionally NOT
    logged here — only the onboarding-chain endpoints.
    """

    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)
    method = fields.CharField(max_length=10)            # POST | PATCH | DELETE
    endpoint = fields.CharField(max_length=255)         # e.g. "POST /v2/accounts"
    request_body = fields.JSONField(null=True)          # masked
    response_status = fields.IntField(null=True)        # HTTP status; NULL on transport error
    response_body = fields.JSONField(null=True)         # masked
    success = fields.BooleanField()
    error_message = fields.TextField(null=True)
    # FK with SET NULL so logs survive franchisee deletion but stay joinable.
    franchisee = fields.ForeignKeyField(
        "models.Franchisee",
        related_name="razorpay_api_logs",
        null=True,
        on_delete=fields.SET_NULL,
    )
    razorpay_account_id = fields.CharField(max_length=50, null=True, index=True)

    class Meta:
        table = "razorpay_api_log"


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
    fee_source = fields.CharField(max_length=20, null=True)                                 # 'webhook', 'api', or 'unavailable' (ADR 0026; was 'estimated')
    refund_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)
    razorpay_refund_id = fields.CharField(max_length=255, null=True, index=True)
    razorpay_refund_speed_processed = fields.CharField(max_length=20, null=True)
    refund_processed_at = fields.DatetimeField(null=True)
    refund_failure_reason = fields.TextField(null=True)
    # Post-refund terminal status to restore at T2 (REFUNDED, or EXPIRED for
    # orphan/stale payments) — carried across the claim→call→persist gap because
    # T1 overwrites `status` with REFUND_IN_PROGRESS. NULL when no claim is open.
    # See ADR 0018.
    refund_terminal_status = fields.CharField(max_length=20, null=True)
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

    # Stable, globally-unique identifier embedded in the customer-facing GST
    # Invoice number (`F0001/Q/26/00001`). Deliberately NOT the primary key:
    # PKs are per-database autoincrements, and production and staging share one
    # GSTIN, so PK-derived numbers collided across registers. Allocated once at
    # onboarding from this environment's block (policy.FRANCHISEE_CODE_BLOCKS)
    # and never reused. `F0000` is reserved for VoltLync-owned stations.
    # Nullable only so the Aerich migration can add-then-backfill.
    invoice_code = fields.CharField(max_length=5, unique=True, null=True)

    # Tax/Legal (populated during KYC or by admin)
    pan_number = fields.CharField(max_length=10, unique=True, null=True)
    gstin = fields.CharField(max_length=15, unique=True, null=True)
    tan_number = fields.CharField(max_length=10, null=True)

    # Location (for GST place-of-supply on invoices + Razorpay Route
    # `profile.addresses.registered` payload)
    city = fields.CharField(max_length=100, null=True)
    state = fields.CharField(max_length=100, null=True)
    state_code = fields.CharField(max_length=5, null=True)
    pincode = fields.CharField(max_length=10, null=True)

    # Bank details (reference copy; Razorpay holds canonical)
    bank_account_name = fields.CharField(max_length=255, null=True)
    bank_account_number = fields.CharField(max_length=30, null=True)
    bank_ifsc_code = fields.CharField(max_length=11, null=True)
    bank_account_type = fields.CharField(max_length=10, null=True)

    # Razorpay Route integration
    razorpay_account_id = fields.CharField(
        max_length=50, unique=True, null=True
    )
    razorpay_account_status = fields.CharField(max_length=50, null=True)
    # Product configuration id returned by POST /v2/accounts/{id}/products.
    # Persisted so subsequent PATCH/GET on the product don't need a lookup.
    razorpay_product_id = fields.CharField(max_length=50, null=True)
    razorpay_onboarding_url = fields.CharField(max_length=500, null=True)
    kyc_submitted_at = fields.DatetimeField(null=True)
    kyc_verified_at = fields.DatetimeField(null=True)
    kyc_verifications = fields.JSONField(null=True)
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
    stakeholders: fields.ReverseRelation["FranchiseeStakeholder"]

    class Meta:
        table = "franchisee"


class FranchiseeStakeholder(Model):
    """Stakeholder (director / proprietor / beneficial owner) linked to a
    franchisee's Razorpay Route account. Razorpay requires at least one
    stakeholder to complete KYC submission for any non-individual
    business_type (proprietorship maps to `not_yet_registered`, which
    also requires one). One franchisee can have many stakeholders (e.g.
    multiple directors for a private limited company).
    """

    id = fields.IntField(pk=True)
    franchisee = fields.ForeignKeyField(
        "models.Franchisee", related_name="stakeholders",
        on_delete=fields.CASCADE,
    )
    # Razorpay id (sth_XXX). Null until POST /v2/accounts/{a}/stakeholders
    # succeeds — a row exists briefly in draft state before the API call.
    razorpay_stakeholder_id = fields.CharField(
        max_length=50, unique=True, null=True
    )
    name = fields.CharField(max_length=255)
    email = fields.CharField(max_length=255)
    phone_primary = fields.CharField(max_length=20, null=True)
    relationship_director = fields.BooleanField(default=True)
    relationship_executive = fields.BooleanField(default=True)
    pan_number = fields.CharField(max_length=10, null=True)
    residential_street = fields.CharField(max_length=255, null=True)
    residential_city = fields.CharField(max_length=100, null=True)
    residential_state = fields.CharField(max_length=100, null=True)
    residential_postal_code = fields.CharField(max_length=10, null=True)
    residential_country = fields.CharField(max_length=2, default="IN")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "franchisee_stakeholder"


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
    energy_consumed_kwh = fields.DecimalField(max_digits=12, decimal_places=3)
    tariff_rate_per_kwh = fields.DecimalField(max_digits=8, decimal_places=4)

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
        indexes = [("settlement_status", "retry_count")]


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

    VoltLync is the GST supplier on every invoice, but each franchisee
    operates as a substore with its own running sequence so the customer-facing
    invoice number identifies the franchisee. NULL franchisee = VoltLync-owned.
    NULL-aware partial unique index is in raw SQL via the migration since
    Postgres treats NULL as distinct in regular UNIQUE indexes.
    """
    id = fields.IntField(pk=True)
    franchisee = fields.ForeignKeyField(
        "models.Franchisee", related_name="invoice_counters", null=True
    )
    series = fields.CharField(max_length=10)  # WAL or QR
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
    invoice_number = fields.CharField(max_length=50)
    series = fields.CharField(max_length=10, default="WAL")  # WAL or QR
    financial_year = fields.CharField(max_length=10)  # e.g. 2026-27
    invoice_date = fields.DatetimeField(auto_now_add=True)

    # Links
    transaction = fields.OneToOneField(
        "models.Transaction", related_name="gst_invoice"
    )
    # Reporting metadata + substore identity on the bill. VoltLync remains
    # the GST supplier (see supplier_* fields); the franchisee_* snapshot
    # below is rendered on the PDF as "Operated by:" per Razorpay's
    # linked-account disclosure rule.
    franchisee = fields.ForeignKeyField(
        "models.Franchisee", related_name="gst_invoices", null=True
    )
    user = fields.ForeignKeyField(
        "models.User", related_name="gst_invoices", null=True
    )

    # Supplier snapshot — always VoltLync (merchant-of-record under Razorpay Route)
    supplier_name = fields.CharField(max_length=255)
    supplier_gstin = fields.CharField(max_length=20, null=True)
    supplier_address = fields.TextField(null=True)
    supplier_state = fields.CharField(max_length=100, null=True)
    supplier_state_code = fields.CharField(max_length=5, null=True)

    # Franchisee operator snapshot — rendered as the "Operated by" block on
    # the PDF. NULL for VoltLync-owned stations (block is omitted entirely).
    franchisee_business_name = fields.CharField(max_length=255, null=True)
    franchisee_gstin = fields.CharField(max_length=20, null=True)
    franchisee_address = fields.TextField(null=True)
    franchisee_state = fields.CharField(max_length=100, null=True)
    franchisee_state_code = fields.CharField(max_length=5, null=True)

    # Customer snapshot
    customer_name = fields.CharField(max_length=255, null=True)
    customer_identifier = fields.CharField(max_length=255, null=True)  # UPI ID, email, phone
    customer_address = fields.TextField(null=True)

    # Station/Charger snapshot (place-of-supply state code frozen at issue)
    station_name = fields.CharField(max_length=255, null=True)
    station_location = fields.CharField(max_length=500, null=True)
    place_of_supply_state_code = fields.CharField(max_length=5, null=True)
    # What was PRINTED on this invoice as the charger identifier: an Asset Code
    # for invoices issued after the ADR 0028 cutover, a legacy
    # charge_point_string_id UUID before it. The two eras are separable by
    # ^VOWS?\d{4,}$.
    #
    # Keeps its name despite the Asset Code avoid-list, deliberately: it is a
    # column header in the GST filings CSV export (routers/invoices.py) that
    # feeds an accountant's spreadsheet, and renaming it would silently break
    # saved import mappings on a compliance surface.
    charger_id_str = fields.CharField(max_length=255, null=True)

    # Two internal siblings, NEVER printed and never exported to the GST
    # filings CSV. Prefer either of these, or the `transaction` FK, when
    # joining an invoice back to hardware: an Asset Code does name a specific
    # unit, but an admin can correct a charger's code and this snapshot cannot
    # be corrected.
    #
    # `charger_ocpp_id` is what preserves the audit link to the physical unit
    # across the cutover, when charger_id_str stopped holding the UUID.
    charger_station_id = fields.IntField(null=True)
    charger_ocpp_id = fields.CharField(max_length=255, null=True)
    connector_type = fields.CharField(max_length=50, null=True)

    # Charging details
    energy_consumed_kwh = fields.DecimalField(max_digits=12, decimal_places=3)
    # GST-only-effective per-kWh rate, derived from (energy_taxable + energy_tax) / billable_kwh.
    # Used by line-item reconciliation on the PDF for legacy invoices.
    tariff_rate_incl_tax = fields.DecimalField(max_digits=10, decimal_places=2)
    # Snapshot of the operator-set, customer-displayed GST-inclusive per-kWh
    # tariff (Tariff.rate_gst_included) at the moment of issuance. Mirrors what
    # the customer saw on the QR / stations screen when they paid. Nullable for
    # backwards compat with pre-2026-05-19 invoices; the PDF falls back to
    # `tariff_rate_incl_tax` when NULL. Renamed from tariff_per_kwh_all_in
    # (ADR 0026); pre-2026-07 rows hold the old gateway-inclusive value, which
    # is fine — invoices are immutable and each PDF re-renders from its own
    # stored component fields.
    rate_gst_included = fields.DecimalField(max_digits=10, decimal_places=4, null=True)
    charged_on = fields.DatetimeField(null=True)
    duration_seconds = fields.IntField(null=True)
    hsn_sac_code = fields.CharField(max_length=10, default="996749")
    gst_rate_percent = fields.DecimalField(max_digits=5, decimal_places=2, default=18.00)

    # Line items (pre-tax)
    energy_taxable_value = fields.DecimalField(max_digits=10, decimal_places=2)
    gateway_charges = fields.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    # Razorpay's GST on its commission — sourced verbatim from the webhook
    # (qr_payment.razorpay_gst). Snapshotted here so the per-invoice gateway
    # tax is queryable without joining qr_payment, and the monthly ITC claim
    # has a single source of truth. NULL for wallet sessions (no gateway).
    gateway_gst = fields.DecimalField(
        max_digits=10, decimal_places=2, null=True
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
    # Sub-rupee reconciling residual. CGST/SGST are each computed independently
    # from the taxable value (so they're equal and pass GSTR-1 portal
    # recomputation), which can differ by a paisa from the billing tax that
    # total_amount must reconcile to (= amount_paid − refund for QR). That
    # residual is carried here as an explicit Round Off line rather than as an
    # asymmetric SGST. 0 for inter-state (single IGST component). See ADR 0017.
    round_off = fields.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = fields.DecimalField(max_digits=10, decimal_places=2)
    amount_in_words = fields.CharField(max_length=500, null=True)

    # Payment info — `transaction_amount` is the GROSS UPI payment for QR
    # sessions (= qr_payment.amount_paid). `refund_amount` is what was
    # refunded back to the customer (NULL/0 for wallet or full-use QR).
    payment_method = fields.CharField(max_length=20, null=True)  # UPI, WALLET
    transaction_amount = fields.DecimalField(
        max_digits=10, decimal_places=2, null=True
    )
    refund_amount = fields.DecimalField(
        max_digits=10, decimal_places=2, null=True
    )

    # PDF (S3 key once uploaded; served via presigned URL)
    pdf_url = fields.CharField(max_length=500, null=True)

    class Meta:
        table = "gst_invoice"
        unique_together = [("franchisee", "series", "financial_year", "invoice_number")]


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
