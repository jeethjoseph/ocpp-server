#for pydantic string typing
from typing import Union, Dict, List, Optional
import datetime
from pydantic import BaseModel

class OCPPCommand(BaseModel):
    charge_point_id: str
    action: str
    payload: Dict = {}

class OCPPResponse(BaseModel):
    success: bool
    message: str
    correlation_id: Optional[str] = None

class MessageLogResponse(BaseModel):
    id: str
    charger_id: str
    direction: str
    message_type: str
    payload: Union[Dict, List]
    timestamp: datetime.datetime
    status: str
    correlation_id: Optional[str]

class ChargePointStatus(BaseModel):
    charge_point_id: str
    connected: bool
    last_seen: Optional[datetime.datetime]
