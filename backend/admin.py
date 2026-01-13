# FastAdmin Configuration
# Admin panel for managing OCPP server data

import os

# IMPORTANT: Set environment variables BEFORE importing fastadmin
os.environ["ADMIN_USER_MODEL"] = "Admin"
os.environ["ADMIN_USER_MODEL_USERNAME_FIELD"] = "username"
os.environ["ADMIN_SECRET_KEY"] = os.getenv("SECRET_KEY", "fastadmin-secret-key-change-me")

import bcrypt
from typing import Optional
from fastadmin import TortoiseModelAdmin, register, fastapi_app as admin_app
from tortoise import fields
from tortoise.models import Model

# Admin user model for FastAdmin authentication
class Admin(Model):
    """Admin user for FastAdmin panel authentication"""
    id = fields.IntField(pk=True)
    username = fields.CharField(max_length=255, unique=True)
    hash_password = fields.CharField(max_length=255)
    is_superuser = fields.BooleanField(default=False)
    is_active = fields.BooleanField(default=True)
    email = fields.CharField(max_length=255, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    last_login = fields.DatetimeField(null=True)

    class Meta:
        table = "admin_user"

    def __str__(self):
        return self.username


# Import models for admin registration
from models import (
    User, Wallet, WalletTransaction, ChargingStation, Charger,
    Connector, Tariff, Transaction, MeterValue, OCPPLog,
    FirmwareFile, FirmwareUpdate, SignalQuality, VehicleProfile,
    PaymentGateway
)


# ============ Admin Model Registrations ============

@register(Admin)
class AdminModelAdmin(TortoiseModelAdmin):
    list_display = ("id", "username", "email", "is_superuser", "is_active", "created_at")
    list_display_links = ("id", "username")
    search_fields = ("username", "email")
    list_filter = ("is_superuser", "is_active")
    exclude = ("hash_password",)

    async def authenticate(self, username: str, password: str) -> Optional[int]:
        """Authenticate admin user for FastAdmin login"""
        user = await Admin.filter(username=username, is_active=True).first()
        if not user:
            return None
        if not bcrypt.checkpw(password.encode(), user.hash_password.encode()):
            return None
        return user.id


@register(User)
class UserAdmin(TortoiseModelAdmin):
    list_display = ("id", "email", "full_name", "phone_number", "role", "clerk_user_id", "is_active", "created_at")
    list_display_links = ("id", "email")
    search_fields = ("email", "full_name", "phone_number", "clerk_user_id")
    list_filter = ("role", "is_active", "auth_provider")
    exclude = ("password_hash",)
    # Force clerk_user_id to appear as a raw input field
    raw_id_fields = ("clerk_user_id",)


@register(Wallet)
class WalletAdmin(TortoiseModelAdmin):
    list_display = ("id", "user_id", "balance", "created_at", "updated_at")
    list_display_links = ("id",)
    search_fields = ("user_id",)


@register(WalletTransaction)
class WalletTransactionAdmin(TortoiseModelAdmin):
    list_display = ("id", "wallet_id", "amount", "type", "created_at")
    list_display_links = ("id",)
    list_filter = ("type",)


@register(VehicleProfile)
class VehicleProfileAdmin(TortoiseModelAdmin):
    list_display = ("id", "user_id", "make", "model", "year", "created_at")
    list_display_links = ("id",)
    search_fields = ("make", "model")


@register(ChargingStation)
class ChargingStationAdmin(TortoiseModelAdmin):
    list_display = ("id", "name", "address", "latitude", "longitude", "created_at")
    list_display_links = ("id", "name")
    search_fields = ("name", "address")


@register(Charger)
class ChargerAdmin(TortoiseModelAdmin):
    list_display = ("id", "name", "charge_point_string_id", "station_id", "vendor", "model", "firmware_version", "latest_status")
    list_display_links = ("id", "name", "charge_point_string_id")
    search_fields = ("name", "charge_point_string_id", "serial_number", "vendor")
    list_filter = ("latest_status", "vendor")


@register(Connector)
class ConnectorAdmin(TortoiseModelAdmin):
    list_display = ("id", "charger_id", "connector_id", "connector_type", "max_power_kw")
    list_display_links = ("id",)
    list_filter = ("connector_type",)


@register(Tariff)
class TariffAdmin(TortoiseModelAdmin):
    list_display = ("id", "charger_id", "rate_per_kwh", "is_global", "created_at")
    list_display_links = ("id",)
    list_filter = ("is_global",)


@register(Transaction)
class TransactionAdmin(TortoiseModelAdmin):
    list_display = ("id", "user_id", "charger_id", "transaction_status", "energy_consumed_kwh", "start_time", "end_time")
    list_display_links = ("id",)
    search_fields = ("user_id", "charger_id")
    list_filter = ("transaction_status",)


@register(MeterValue)
class MeterValueAdmin(TortoiseModelAdmin):
    list_display = ("id", "transaction_id", "reading_kwh", "power_kw", "voltage", "current", "created_at")
    list_display_links = ("id",)


@register(FirmwareFile)
class FirmwareFileAdmin(TortoiseModelAdmin):
    list_display = ("id", "version", "filename", "file_size", "is_active", "created_at")
    list_display_links = ("id", "version")
    search_fields = ("version", "filename")
    list_filter = ("is_active",)


@register(FirmwareUpdate)
class FirmwareUpdateAdmin(TortoiseModelAdmin):
    list_display = ("id", "charger_id", "firmware_file_id", "status", "initiated_at", "completed_at")
    list_display_links = ("id",)
    list_filter = ("status",)


@register(OCPPLog)
class OCPPLogAdmin(TortoiseModelAdmin):
    list_display = ("id", "charge_point_id", "message_type", "direction", "status", "timestamp")
    list_display_links = ("id",)
    search_fields = ("charge_point_id", "message_type", "correlation_id")
    list_filter = ("direction", "message_type")


@register(SignalQuality)
class SignalQualityAdmin(TortoiseModelAdmin):
    list_display = ("id", "charger_id", "rssi", "ber", "timestamp", "created_at")
    list_display_links = ("id",)


@register(PaymentGateway)
class PaymentGatewayAdmin(TortoiseModelAdmin):
    list_display = ("id", "name", "status", "default_currency", "created_at")
    list_display_links = ("id", "name")
    list_filter = ("status",)
    exclude = ("api_key", "webhook_secret")  # Don't show secrets in admin
