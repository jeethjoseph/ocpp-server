# Data Models
import uuid
import enum
import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, DECIMAL, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ENUM as PG_ENUM
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# Enums
class TransactionTypeEnum(str, enum.Enum):
    TOP_UP = "TOP_UP"
    CHARGE_DEDUCT = "CHARGE_DEDUCT"

class ChargerStatusEnum(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    PREPARING = "PREPARING"
    CHARGING = "CHARGING"
    SUSPENDED_EVSE = "SUSPENDED_EVSE"
    SUSPENDED_EV = "SUSPENDED_EV"
    FINISHING = "FINISHING"
    RESERVED = "RESERVED"
    UNAVAILABLE = "UNAVAILABLE"
    FAULTED = "FAULTED"

class TransactionStatusEnum(str, enum.Enum):
    STARTED = "STARTED"
    PENDING_START = "PENDING_START"
    RUNNING = "RUNNING"
    PENDING_STOP = "PENDING_STOP"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

class MessageDirectionEnum(str, enum.Enum):
    INBOUND = "IN"
    OUTBOUND = "OUT"

# User Table
class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    email = Column(String(255))
    phone_number = Column(String(255), unique=True)
    password_hash = Column(String(255))
    full_name = Column(String(255))
    is_active = Column(Boolean, default=True)
    wallet = relationship("Wallet", uselist=False, back_populates="user")
    vehicles = relationship("VehicleProfile", back_populates="user")

class AdminUser(Base):
    __tablename__ = "admin_user"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    email = Column(String(255))
    phone_number = Column(String(255), unique=True)
    password_hash = Column(String(255))
    full_name = Column(String(255))
    is_active = Column(Boolean, default=True)

class Wallet(Base):
    __tablename__ = "wallet"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    user_id = Column(Integer, ForeignKey("user.id"), unique=True)
    balance = Column(DECIMAL(10,2))
    user = relationship("User", back_populates="wallet")
    transactions = relationship("WalletTransaction", back_populates="wallet")

class WalletTransaction(Base):
    __tablename__ = "wallet_transaction"
    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_id = Column(Integer, ForeignKey("wallet.id"))
    amount = Column(DECIMAL(10,2))
    type = Column(PG_ENUM(TransactionTypeEnum, name="transactiontypeenum"), nullable=False)
    description = Column(Text, nullable=True)
    charging_transaction_id = Column(Integer, ForeignKey("transaction.id"), nullable=True)
    payment_metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    wallet = relationship("Wallet", back_populates="transactions")
    charging_transaction = relationship("Transaction", back_populates="wallet_transactions")

class PaymentGateway(Base):
    __tablename__ = "payment_gateway"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    name = Column(String(100))
    api_key = Column(String(255), nullable=True)
    webhook_secret = Column(String(255), nullable=True)
    status = Column(Boolean, default=True)
    config = Column(JSON, nullable=True)
    default_currency = Column(String(3), default="INR")

class VehicleProfile(Base):
    __tablename__ = "vehicle_profile"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    user_id = Column(Integer, ForeignKey("user.id"))
    make = Column(String(100))
    model = Column(String(100))
    year = Column(Integer)
    user = relationship("User", back_populates="vehicles")

class ValidVehicleProfile(Base):
    __tablename__ = "valid_vehicle_profile"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    make = Column(String(100))
    model = Column(String(100))
    year = Column(Integer)

class ChargingStation(Base):
    __tablename__ = "charging_station"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    name = Column(String(255))
    latitude = Column(Float)
    longitude = Column(Float)
    address = Column(Text)
    chargers = relationship("Charger", back_populates="station")

class Charger(Base):
    __tablename__ = "charger"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    charge_point_string_id = Column(String(255), unique=True)
    station_id = Column(Integer, ForeignKey("charging_station.id"))
    name = Column(String(255))
    model = Column(String(100))
    vendor = Column(String(100))
    serial_number = Column(String(100), unique=True)
    firmware_version = Column(String(100))
    iccid = Column(String(100), nullable=True)
    imsi = Column(String(100), nullable=True)
    meter_type = Column(String(100), nullable=True)
    meter_serial_number = Column(String(100), nullable=True)
    latest_status = Column(PG_ENUM(ChargerStatusEnum, name="chargerstatusenum"), nullable=False)
    last_heart_beat_time = Column(DateTime)
    station = relationship("ChargingStation", back_populates="chargers")
    tariffs = relationship("Tariff", back_populates="charger")
    connectors = relationship("Connector", back_populates="charger", cascade="all, delete-orphan")

class Connector(Base):
    __tablename__ = "connector"
    id = Column(Integer, primary_key=True, autoincrement=True)
    charger_id = Column(Integer, ForeignKey("charger.id"), nullable=False)
    connector_id = Column(Integer, nullable=False)  # starts from 1, unique per charger
    connector_type = Column(String(255), nullable=False)
    max_power_kw = Column(Float, nullable=True)
    charger = relationship("Charger", back_populates="connectors")
    __table_args__ = (
        # Ensure (charger_id, connector_id) is unique
        {'sqlite_autoincrement': True},
    )

class Tariff(Base):
    __tablename__ = "tariff"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    charger_id = Column(Integer, ForeignKey("charger.id"), nullable=True)
    rate_per_kwh = Column(DECIMAL(5,2))
    is_global = Column(Boolean, default=False)
    charger = relationship("Charger", back_populates="tariffs")

class Transaction(Base):
    __tablename__ = "transaction"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    user_id = Column(Integer, ForeignKey("user.id"))
    charger_id = Column(Integer, ForeignKey("charger.id"))
    vehicle_id = Column(Integer, ForeignKey("vehicle_profile.id"))
    start_meter_kwh = Column(Float)
    end_meter_kwh = Column(Float, nullable=True)
    energy_consumed_kwh = Column(Float, nullable=True)
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    stop_reason = Column(Text, nullable=True)
    transaction_status = Column(PG_ENUM(TransactionStatusEnum, name="transactionstatusenum"), nullable=False)
    wallet_transactions = relationship("WalletTransaction", back_populates="charging_transaction")
    meter_values = relationship("MeterValue", back_populates="transaction")

class MeterValue(Base):
    __tablename__ = "meter_value"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    transaction_id = Column(Integer, ForeignKey("transaction.id"))
    reading_kwh = Column(Float)
    timestamp = Column(DateTime)
    current = Column(Float, nullable=True)
    voltage = Column(Float, nullable=True)
    power_kw = Column(Float, nullable=True)
    transaction = relationship("Transaction", back_populates="meter_values")

class OCPPLog(Base):
    __tablename__ = "log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    charge_point_id = Column(String(100))
    message_type = Column(String(100))
    direction = Column(PG_ENUM(MessageDirectionEnum, name="messagedirectionenum"), nullable=False)
    payload = Column(JSON)
    status = Column(String(50), nullable=True)
    correlation_id = Column(String(100), nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


