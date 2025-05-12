from enum import Enum


class TransactionTypeEnum(str, Enum):
    TOP_UP = "TOP_UP"
    CHARGE_DEDUCT = "CHARGE_DEDUCT"


class ChargerStatusEnum(str, Enum):
    AVAILABLE = "Available"
    PREPARING = "Preparing"
    CHARGING = "Charging"
    SUSPENDED_EVSE = "SuspendedEVSE"
    SUSPENDED_EV = "SuspendedEV"
    FINISHING = "Finishing"
    RESERVED = "Reserved"
    UNAVAILABLE = "Unavailable"
    FAULTED = "Faulted"


class TransactionStatusEnum(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MessageDirectionEnum(str, Enum):
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"
