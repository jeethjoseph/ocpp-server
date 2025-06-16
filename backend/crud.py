import datetime
from typing import List, Optional, Tuple
from models import OCPPLog, Charger


###
### LOGS ###
###
async def log_message(
    charger_id: str, 
    direction: str, 
    message_type: str, 
    payload: dict, 
    status: str, 
    correlation_id: Optional[str] = None
) -> OCPPLog:
    """Create a new OCPP log entry"""
    log_entry = await OCPPLog.create(
        charge_point_id=charger_id,
        direction=direction,
        message_type=message_type,
        payload=payload,
        status=status,
        correlation_id=correlation_id,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    return log_entry

async def get_logs(limit: int = 100) -> List[OCPPLog]:
    """Get all OCPP logs ordered by timestamp descending"""
    return await OCPPLog.all().order_by('-timestamp').limit(limit)

async def get_logs_by_charge_point(charge_point_id: str, limit: int = 100) -> List[OCPPLog]:
    """Get OCPP logs for a specific charge point"""
    return await OCPPLog.filter(
        charge_point_id=charge_point_id
    ).order_by('-timestamp').limit(limit)

###
### CHARGER CONNECTIONS ###
###

async def validate_and_connect_charger(
    charge_point_id: str, 
    connected_charge_points: dict
) -> Tuple[bool, str]:
    """
    Validate if charger is registered and can connect.
    Returns (is_valid, message)
    """
    # Check if charger exists in database
    charger = await Charger.filter(
        charge_point_string_id=charge_point_id
    ).first()
    
    if not charger:
        return False, f"Charger {charge_point_id} not registered in system"
    
    # Check if already connected
    if charge_point_id in connected_charge_points:
        return False, f"Charger {charge_point_id} is already connected"
    
    return True, "Valid charger"

###
### ADDITIONAL HELPER FUNCTIONS ###
###

async def get_charger_by_id(charge_point_id: str) -> Optional[Charger]:
    """Get charger by charge point string ID"""
    return await Charger.filter(charge_point_string_id=charge_point_id).first()

async def update_charger_status(charge_point_id: str, status: str) -> bool:
    """Update charger status"""
    charger = await Charger.filter(charge_point_string_id=charge_point_id).first()
    if charger:
        charger.latest_status = status
        charger.last_heart_beat_time = datetime.datetime.now(datetime.timezone.utc)
        await charger.save()
        return True
    return False

async def get_all_chargers() -> List[Charger]:
    """Get all chargers with their station information"""
    return await Charger.all().prefetch_related('station')

async def create_charger(
    charge_point_string_id: str,
    station_id: int,
    name: str,
    model: str = None,
    vendor: str = None,
    serial_number: str = None
) -> Charger:
    """Create a new charger"""
    charger = await Charger.create(
        charge_point_string_id=charge_point_string_id,
        station_id=station_id,
        name=name,
        model=model,
        vendor=vendor,
        serial_number=serial_number,
        latest_status="UNAVAILABLE"
    )
    return charger