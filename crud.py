import datetime
from sqlalchemy.orm import Session
from models import OCPPLog, Charger


###
### LOGS ###
###
def log_message(db: Session, charger_id, direction, message_type, payload, status, correlation_id=None):
    log_entry = OCPPLog(
        charge_point_id=charger_id,
        direction=direction,
        message_type=message_type,
        payload=payload,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
        status=status,
        correlation_id=correlation_id
    )
    db.add(log_entry)
    db.commit()

def get_logs(db: Session, limit=100):
    return db.query(OCPPLog).order_by(OCPPLog.timestamp.desc()).limit(limit).all()

def get_logs_by_charge_point(db: Session, charge_point_id: str, limit=100):
    return db.query(OCPPLog).filter(
        OCPPLog.charger_id == charge_point_id
    ).order_by(OCPPLog.timestamp.desc()).limit(limit).all()

###
### CHARGER CONNECTIONS ###
###

async def validate_and_connect_charger(charge_point_id: str, db: Session, connected_charge_points: dict) -> tuple[bool, str]:
    """
    Validate if charger is registered and can connect.
    Returns (is_valid, message)
    """
    charger = db.query(Charger).filter(
        Charger.charge_point_string_id == charge_point_id
    ).first()
    
    if not charger:
        return False, f"Charger {charge_point_id} not registered in system"
    
    # Check if already connected
    if charge_point_id in connected_charge_points:
        return False, f"Charger {charge_point_id} is already connected"
    
    return True, "Valid charger"




