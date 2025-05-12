from tortoise import fields
from tortoise.models import Model
from enums import TransactionTypeEnum, ChargerStatusEnum, TransactionStatusEnum, MessageDirectionEnum


# --- Base Model ---
class BaseModel(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        abstract = True


# --- User ---
class User(BaseModel):
    email = fields.CharField(max_length=255)
    phone_number = fields.CharField(max_length=255, unique=True)
    password_hash = fields.CharField(max_length=255)
    full_name = fields.CharField(max_length=255)
    is_active = fields.BooleanField(default=True)

    wallet: fields.ReverseRelation['Wallet']
    vehicles: fields.ReverseRelation['VehicleProfile']


# --- Admin User ---
class AdminUser(BaseModel):
    email = fields.CharField(max_length=255)
    phone_number = fields.CharField(max_length=255, unique=True)
    password_hash = fields.CharField(max_length=255)
    full_name = fields.CharField(max_length=255)
    is_active = fields.BooleanField(default=True)


# --- Wallet ---
class Wallet(BaseModel):
    user = fields.OneToOneField('models.User', related_name='wallet')
    balance = fields.DecimalField(max_digits=10, decimal_places=2)


# --- Wallet Transaction ---

class WalletTransaction(Model):
    wallet = fields.ForeignKeyField("models.Wallet", related_name="transactions")
    amount = fields.DecimalField(max_digits=10, decimal_places=2)
    type = fields.CharEnumField(enum_type=TransactionTypeEnum)  # TOP_UP, CHARGE_DEDUCT
    description = fields.TextField(null=True)
    charging_transaction = fields.ForeignKeyField("models.Transaction", null=True, related_name="wallet_transactions")
    payment_metadata = fields.JSONField()


class PaymentGateway(BaseModel):
    name = fields.CharField(max_length=100)  # e.g., "Stripe", "PayPal", "Square"
    api_key = fields.CharField(max_length=255, null=True)  # encrypted
    webhook_secret = fields.CharField(max_length=255, null=True)
    status = fields.BooleanField(default=True)  # is active or not
    config = fields.JSONField(null=True)  # additional configuration parameters
    default_currency = fields.CharField(max_length=3, default="INR")


# --- Vehicle Profile ---
class VehicleProfile(BaseModel):
    user = fields.ForeignKeyField('models.User', related_name='vehicles')
    make = fields.CharField(max_length=100)
    model = fields.CharField(max_length=100)
    year = fields.IntField()


# --- Valid Vehicle Profile ---
class ValidVehicleProfile(BaseModel):
    make = fields.CharField(max_length=100)
    model = fields.CharField(max_length=100)
    year = fields.IntField()


# --- Charging Station ---
class ChargingStation(BaseModel):
    name = fields.CharField(max_length=255)
    latitude = fields.FloatField()
    longitude = fields.FloatField()
    address = fields.TextField()

    chargers: fields.ReverseRelation['Charger']


# --- Charger ---
class Charger(BaseModel):
    charge_point_string_id = fields.CharField(max_length=255, unique=True)
    station = fields.ForeignKeyField('models.ChargingStation', related_name='chargers')
    name = fields.CharField(max_length=255)
    model = fields.CharField(max_length=100)
    vendor = fields.CharField(max_length=100)
    serial_number = fields.CharField(max_length=100, unique=True)
    firmware_version = fields.CharField(max_length=100)
    iccid = fields.CharField(max_length=100, null=True)
    imsi = fields.CharField(max_length=100, null=True)
    meter_type = fields.CharField(max_length=100, null=True)
    meter_serial_number = fields.CharField(max_length=100, null=True)
    latest_status = fields.CharEnumField(enum_type=ChargerStatusEnum)
    last_heart_beat_time = fields.DatetimeField()
    connector_type = fields.CharField(max_length=255)
    max_power_kw = fields.FloatField()

    tariffs: fields.ReverseRelation['Tariff']


# --- Tariff ---
class Tariff(BaseModel):
    charger = fields.ForeignKeyField('models.Charger', related_name='tariffs', null=True)
    rate_per_kwh = fields.DecimalField(max_digits=5, decimal_places=2)
    is_global = fields.BooleanField(default=False)


# --- Transaction ---
class Transaction(BaseModel):
    user = fields.ForeignKeyField('models.User', related_name='transactions')
    charger = fields.ForeignKeyField('models.Charger', related_name='transactions')
    vehicle = fields.ForeignKeyField('models.VehicleProfile', related_name='transactions')
    start_meter_kwh = fields.FloatField()
    end_meter_kwh = fields.FloatField(null=True)
    energy_consumed_kwh = fields.FloatField(null=True)
    start_time = fields.DatetimeField(auto_now_add=True)
    end_time = fields.DatetimeField(null=True)
    stop_reason = fields.TextField(null=True)
    transaction_status = fields.CharEnumField(enum_type=TransactionStatusEnum)

    meter_values: fields.ReverseRelation['MeterValue']


# --- MeterValue ---
class MeterValue(BaseModel):
    transaction = fields.ForeignKeyField('models.Transaction', related_name='meter_values')
    reading_kwh = fields.FloatField()
    timestamp = fields.DatetimeField()
    current = fields.FloatField(null=True)
    voltage = fields.FloatField(null=True)
    power_kw = fields.FloatField(null=True)


# --- Log ---
class Log(BaseModel):
    charge_point_id = fields.CharField(max_length=100)
    message_type = fields.CharField(max_length=100)  # e.g., BootNotification, Heartbeat, etc.
    direction = fields.CharField(max_length=10)  # inbound or outbound
    payload = fields.JSONField()
    timestamp = fields.DatetimeField(auto_now_add=True)
