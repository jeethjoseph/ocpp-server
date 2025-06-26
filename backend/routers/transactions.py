# routers/transactions.py
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime
import logging

from models import Transaction, MeterValue, User, Charger, WalletTransaction
from tortoise.exceptions import IntegrityError

logger = logging.getLogger(__name__)

# Pydantic schemas
class MeterValueResponse(BaseModel):
    id: int
    reading_kwh: float
    current: Optional[float]
    voltage: Optional[float]
    power_kw: Optional[float]
    created_at: datetime
    
    class Config:
        from_attributes = True

class TransactionResponse(BaseModel):
    id: int
    user_id: int
    charger_id: int
    start_meter_kwh: Optional[float]
    end_meter_kwh: Optional[float]
    energy_consumed_kwh: Optional[float]
    start_time: datetime
    end_time: Optional[datetime]
    stop_reason: Optional[str]
    transaction_status: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class UserBasicInfo(BaseModel):
    id: int
    full_name: Optional[str]
    email: Optional[str]
    phone_number: Optional[str]
    
    class Config:
        from_attributes = True

class ChargerBasicInfo(BaseModel):
    id: int
    name: str
    charge_point_string_id: str
    
    class Config:
        from_attributes = True

class WalletTransactionResponse(BaseModel):
    id: int
    amount: float
    type: str
    description: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

class TransactionListResponse(BaseModel):
    data: List[TransactionResponse]
    total: int
    page: int
    limit: int
    summary: Dict

class TransactionDetailResponse(BaseModel):
    transaction: TransactionResponse
    user: UserBasicInfo
    charger: ChargerBasicInfo
    meter_values: List[MeterValueResponse]
    wallet_transactions: List[WalletTransactionResponse]

class MeterValuesListResponse(BaseModel):
    meter_values: List[MeterValueResponse]
    energy_chart_data: Dict

class StopTransactionRequest(BaseModel):
    reason: str

# Create router
router = APIRouter(
    prefix="/api/admin/transactions",
    tags=["Transaction Management"]
)

@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    charger_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    sort: Optional[str] = Query("created_at", regex="^(created_at|updated_at|start_time|end_time)$")
):
    """List all transactions with filtering options"""
    
    query = Transaction.all()
    
    # Apply filters
    if status:
        query = query.filter(transaction_status=status)
    if user_id:
        query = query.filter(user_id=user_id)
    if charger_id:
        query = query.filter(charger_id=charger_id)
    if start_date:
        query = query.filter(start_time__gte=start_date)
    if end_date:
        query = query.filter(start_time__lte=end_date)
    
    # Get total count
    total = await query.count()
    
    # Apply sorting
    if sort.startswith("-"):
        query = query.order_by(f"-{sort[1:]}")
    else:
        query = query.order_by(sort)
    
    # Apply pagination
    offset = (page - 1) * limit
    transactions = await query.offset(offset).limit(limit)
    
    # Build summary statistics
    summary = {
        "total_energy_consumed": sum(t.energy_consumed_kwh or 0 for t in transactions),
        "active_sessions": await Transaction.filter(transaction_status__in=["STARTED", "RUNNING"]).count(),
        "completed_sessions": await Transaction.filter(transaction_status="COMPLETED").count()
    }
    
    transaction_responses = [TransactionResponse.model_validate(t, from_attributes=True) for t in transactions]
    
    return TransactionListResponse(
        data=transaction_responses,
        total=total,
        page=page,
        limit=limit,
        summary=summary
    )

@router.get("/{transaction_id}", response_model=TransactionDetailResponse)
async def get_transaction_details(transaction_id: int):
    """Get transaction details with related data"""
    
    transaction = await Transaction.filter(id=transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Get related data
    user = await User.filter(id=transaction.user_id).first()
    charger = await Charger.filter(id=transaction.charger_id).first()
    meter_values = await MeterValue.filter(transaction_id=transaction_id).order_by("created_at")
    wallet_transactions = await WalletTransaction.filter(charging_transaction_id=transaction_id).all()
    
    if not user or not charger:
        raise HTTPException(status_code=500, detail="Related data not found")
    
    return TransactionDetailResponse(
        transaction=TransactionResponse.model_validate(transaction, from_attributes=True),
        user=UserBasicInfo.model_validate(user, from_attributes=True),
        charger=ChargerBasicInfo.model_validate(charger, from_attributes=True),
        meter_values=[MeterValueResponse.model_validate(mv, from_attributes=True) for mv in meter_values],
        wallet_transactions=[WalletTransactionResponse.model_validate(wt, from_attributes=True) for wt in wallet_transactions]
    )

@router.post("/{transaction_id}/stop", response_model=dict)
async def force_stop_transaction(transaction_id: int, request: StopTransactionRequest):
    """Force stop a transaction (admin override)"""
    
    transaction = await Transaction.filter(id=transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    if transaction.transaction_status in ["STOPPED", "COMPLETED", "CANCELLED"]:
        raise HTTPException(status_code=409, detail="Transaction is already stopped")
    
    # Get charger for OCPP command
    charger = await Charger.filter(id=transaction.charger_id).first()
    if not charger:
        raise HTTPException(status_code=500, detail="Charger not found")
    
    # Import connection checking function
    def get_connected_charge_points():
        from main import connected_charge_points
        return connected_charge_points
    
    connected_cps = get_connected_charge_points()
    
    # Try to send OCPP stop command if charger is connected
    if charger.charge_point_string_id in connected_cps:
        from main import send_ocpp_request
        
        success, response = await send_ocpp_request(
            charger.charge_point_string_id,
            "RemoteStopTransaction",
            {"transactionId": transaction_id}
        )
        
        if not success:
            logger.warning(f"Failed to send OCPP stop command for transaction {transaction_id}: {response}")
    
    # Force stop the transaction in database
    transaction.transaction_status = "STOPPED"
    transaction.stop_reason = f"Force stopped by admin: {request.reason}"
    transaction.end_time = datetime.utcnow()
    await transaction.save()
    
    # Calculate final amount if needed
    final_amount = None
    if transaction.energy_consumed_kwh:
        # TODO: Calculate based on tariff
        final_amount = transaction.energy_consumed_kwh * 10  # Placeholder calculation
    
    return {
        "success": True,
        "message": "Transaction force stopped successfully",
        "final_amount": final_amount
    }

@router.get("/{transaction_id}/meter-values", response_model=MeterValuesListResponse)
async def get_transaction_meter_values(transaction_id: int):
    """Get meter values for a specific transaction"""
    
    transaction = await Transaction.filter(id=transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    meter_values = await MeterValue.filter(transaction_id=transaction_id).order_by("created_at")
    
    # Build energy chart data for frontend visualization
    energy_chart_data = {
        "labels": [mv.created_at.isoformat() for mv in meter_values],
        "energy_data": [mv.reading_kwh for mv in meter_values],
        "power_data": [mv.power_kw or 0 for mv in meter_values]
    }
    
    meter_value_responses = [MeterValueResponse.model_validate(mv, from_attributes=True) for mv in meter_values]
    
    return MeterValuesListResponse(
        meter_values=meter_value_responses,
        energy_chart_data=energy_chart_data
    )