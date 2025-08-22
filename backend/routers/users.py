from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from tortoise.exceptions import DoesNotExist
from decimal import Decimal

from auth_middleware import require_admin, require_user_or_admin, require_user
from models import User, Transaction, WalletTransaction, Wallet, UserRoleEnum
from schemas import BaseModel
import logging

logger = logging.getLogger("users-router")
router = APIRouter(prefix="/api/users", tags=["User Management"])

# Response Models
class UserListItem(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: str
    auth_provider: str
    is_active: bool
    is_email_verified: bool
    rfid_card_id: Optional[str] = None
    created_at: str
    updated_at: str
    last_login: Optional[str] = None
    
    # Computed fields
    display_name: str
    wallet_balance: Optional[float] = None
    total_transactions: int = 0
    total_wallet_transactions: int = 0

class UserDetail(UserListItem):
    clerk_user_id: Optional[str] = None
    avatar_url: Optional[str] = None
    terms_accepted_at: Optional[str] = None
    preferred_language: str
    notification_preferences: dict

class UserListResponse(BaseModel):
    data: List[UserListItem]
    total: int
    page: int
    limit: int
    total_pages: int

class UserSoftDeleteResponse(BaseModel):
    message: str
    user_id: int
    deactivated_at: str

class UserTransactionSummary(BaseModel):
    charging_transactions: int
    wallet_transactions: int
    total_energy_consumed: float
    total_amount_spent: float
    last_transaction_date: Optional[str] = None

@router.get("/my-sessions", response_model=dict)
async def get_my_sessions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_user())
):
    """Get current user's charging sessions and wallet transactions

    Note: This route must appear before dynamic '/{user_id}' routes to avoid
    path-matching conflicts that could incorrectly enforce ADMIN access.
    """
    try:
        offset = (page - 1) * limit
        
        # Get all transactions (charging + standalone wallet transactions)
        # First, get charging transactions with their related wallet transactions
        charging_transactions = await Transaction.filter(user=current_user).prefetch_related(
            'charger__station', 'wallet_transactions'
        ).order_by('-created_at')
        
        # Get wallet transaction IDs that are already linked to charging transactions
        linked_wallet_transaction_ids = set()
        for ct in charging_transactions:
            for wt in ct.wallet_transactions:
                linked_wallet_transaction_ids.add(wt.id)
        
        # Get standalone wallet transactions (topups and charges not linked to charging sessions)
        standalone_wallet_transactions = await WalletTransaction.filter(
            wallet__user=current_user
        ).exclude(id__in=linked_wallet_transaction_ids).order_by('-created_at')
        
        # Combine all transactions by date
        all_transactions = []
        
        # Add charging transactions with their wallet transactions grouped
        for ct in charging_transactions:
            charging_amount = abs(sum(float(wt.amount) for wt in ct.wallet_transactions if wt.type.value in ["CHARGE", "CHARGE_DEDUCT"]))
            
            transaction_data = {
                "id": ct.id,
                "type": "charging",
                "station_name": ct.charger.station.name if ct.charger.station else "Unknown Station",
                "charger_name": ct.charger.name or f"Charger {ct.charger.id}",
                "energy_consumed_kwh": ct.energy_consumed_kwh,
                "start_time": ct.start_time.isoformat() if ct.start_time else None,
                "end_time": ct.end_time.isoformat() if ct.end_time else None,
                "status": ct.transaction_status.value,
                "amount": charging_amount if charging_amount > 0 else None,
                "created_at": ct.created_at.isoformat(),
                # Include linked wallet transaction details
                "wallet_transactions": [
                    {
                        "id": wt.id,
                        "amount": float(wt.amount),
                        "type": wt.type.value,
                        "description": wt.description,
                        "created_at": wt.created_at.isoformat()
                    } for wt in ct.wallet_transactions
                ]
            }
            all_transactions.append(transaction_data)
        
        # Add standalone wallet transactions (topups, refunds, etc.)
        for wt in standalone_wallet_transactions:
            all_transactions.append({
                "id": wt.id,
                "type": "wallet",
                "transaction_type": wt.type.value,
                "amount": float(wt.amount),
                "description": wt.description,
                "payment_metadata": wt.payment_metadata,
                "created_at": wt.created_at.isoformat()
            })
        
        # Sort by created_at descending
        all_transactions.sort(key=lambda x: x['created_at'], reverse=True)
        
        # Apply pagination after sorting
        paginated_transactions = all_transactions[offset:offset + limit]
        
        # Get totals (charging transactions + standalone wallet transactions only)
        total_charging = await Transaction.filter(user=current_user).count()
        total_standalone_wallet = await WalletTransaction.filter(
            wallet__user=current_user
        ).exclude(id__in=linked_wallet_transaction_ids).count()
        total = total_charging + total_standalone_wallet
        
        return {
            "data": paginated_transactions,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit
        }
        
    except Exception as e:
        logger.error(f"Error getting user sessions for {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve sessions")

@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by name, email, or phone"),
    admin_user: User = Depends(require_admin())
):
    """Get paginated list of USER role users only (admin only)"""
    try:
        # Build query - only show users with role USER (not ADMINs)
        query = User.filter(role=UserRoleEnum.USER)
        
        # Apply filters
        if is_active is not None:
            query = query.filter(is_active=is_active)
            
        if search:
            # Use OR conditions for search
            from tortoise.expressions import Q
            query = query.filter(
                Q(full_name__icontains=search) | 
                Q(email__icontains=search) | 
                Q(phone_number__icontains=search)
            )
        
        # Get total count
        total = await query.count()
        total_pages = (total + limit - 1) // limit
        
        # Apply pagination and ordering
        offset = (page - 1) * limit
        users = await query.offset(offset).limit(limit).order_by('-created_at')
        
        # Prepare response data with computed fields
        user_data = []
        for user in users:
            # Get wallet balance
            wallet = await Wallet.filter(user=user).first()
            wallet_balance = float(wallet.balance) if wallet and wallet.balance else 0.0
            
            # Get transaction counts
            total_transactions = await Transaction.filter(user=user).count()
            total_wallet_transactions = await WalletTransaction.filter(wallet__user=user).count()
            
            user_data.append(UserListItem(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                phone_number=user.phone_number,
                role=user.role.value,
                auth_provider=user.auth_provider.value,
                is_active=user.is_active,
                is_email_verified=user.is_email_verified,
                rfid_card_id=user.rfid_card_id,
                created_at=user.created_at.isoformat(),
                updated_at=user.updated_at.isoformat(),
                last_login=user.last_login.isoformat() if user.last_login else None,
                display_name=user.display_name,
                wallet_balance=wallet_balance,
                total_transactions=total_transactions,
                total_wallet_transactions=total_wallet_transactions
            ))
        
        return UserListResponse(
            data=user_data,
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages
        )
        
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve users")

@router.get("/{user_id:int}", response_model=UserDetail)
async def get_user(
    user_id: int,
    admin_user: User = Depends(require_admin())
):
    """Get detailed user information (admin only) - only USER role users"""
    try:
        user = await User.get(id=user_id, role=UserRoleEnum.USER)
        
        # Get wallet balance
        wallet = await Wallet.filter(user=user).first()
        wallet_balance = float(wallet.balance) if wallet and wallet.balance else 0.0
        
        # Get transaction counts
        total_transactions = await Transaction.filter(user=user).count()
        total_wallet_transactions = await WalletTransaction.filter(wallet__user=user).count()
        
        return UserDetail(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            phone_number=user.phone_number,
            role=user.role.value,
            auth_provider=user.auth_provider.value,
            is_active=user.is_active,
            is_email_verified=user.is_email_verified,
            rfid_card_id=user.rfid_card_id,
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat(),
            last_login=user.last_login.isoformat() if user.last_login else None,
            display_name=user.display_name,
            wallet_balance=wallet_balance,
            total_transactions=total_transactions,
            total_wallet_transactions=total_wallet_transactions,
            clerk_user_id=user.clerk_user_id,
            avatar_url=user.avatar_url,
            terms_accepted_at=user.terms_accepted_at.isoformat() if user.terms_accepted_at else None,
            preferred_language=user.preferred_language,
            notification_preferences=user.notification_preferences
        )
        
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve user")

@router.put("/{user_id:int}/deactivate", response_model=UserSoftDeleteResponse)
async def soft_delete_user(
    user_id: int,
    admin_user: User = Depends(require_admin())
):
    """Soft delete user by setting is_active to False (admin only) - only USER role users"""
    try:
        user = await User.get(id=user_id, role=UserRoleEnum.USER)
        
        # Soft delete
        user.is_active = False
        await user.save()
        
        logger.info(f"User {user_id} ({user.email}) deactivated by admin {admin_user.email}")
        
        return UserSoftDeleteResponse(
            message=f"User {user.display_name} has been deactivated",
            user_id=user_id,
            deactivated_at=user.updated_at.isoformat()
        )
        
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found or is not a regular user")
    except Exception as e:
        logger.error(f"Error deactivating user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to deactivate user")

@router.put("/{user_id:int}/reactivate", response_model=dict)
async def reactivate_user(
    user_id: int,
    admin_user: User = Depends(require_admin())
):
    """Reactivate a deactivated user (admin only) - only USER role users"""
    try:
        user = await User.get(id=user_id, role=UserRoleEnum.USER)
        
        if user.is_active:
            raise HTTPException(status_code=400, detail="User is already active")
        
        user.is_active = True
        await user.save()
        
        logger.info(f"User {user_id} ({user.email}) reactivated by admin {admin_user.email}")
        
        return {
            "message": f"User {user.display_name} has been reactivated",
            "user_id": user_id,
            "reactivated_at": user.updated_at.isoformat()
        }
        
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found or is not a regular user")
    except Exception as e:
        logger.error(f"Error reactivating user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to reactivate user")

@router.get("/{user_id:int}/transactions-summary", response_model=UserTransactionSummary)
async def get_user_transaction_summary(
    user_id: int,
    admin_user: User = Depends(require_admin())
):
    """Get user's transaction summary (admin only) - only USER role users"""
    try:
        user = await User.get(id=user_id, role=UserRoleEnum.USER)
        
        # Get charging transactions
        charging_transactions = await Transaction.filter(user=user)
        charging_count = len(charging_transactions)
        
        # Calculate total energy consumed
        total_energy = sum(
            t.energy_consumed_kwh for t in charging_transactions 
            if t.energy_consumed_kwh is not None
        )
        
        # Get wallet transactions
        wallet_transactions = await WalletTransaction.filter(wallet__user=user)
        wallet_count = len(wallet_transactions)
        
        # Calculate total amount spent (only deductions)
        total_spent = sum(
            abs(float(wt.amount)) for wt in wallet_transactions 
            if wt.amount < 0
        )
        
        # Get last transaction date
        last_transaction_date = None
        if charging_transactions:
            latest_charging = max(charging_transactions, key=lambda t: t.created_at)
            last_transaction_date = latest_charging.created_at.isoformat()
        
        return UserTransactionSummary(
            charging_transactions=charging_count,
            wallet_transactions=wallet_count,
            total_energy_consumed=round(total_energy, 2),
            total_amount_spent=round(total_spent, 2),
            last_transaction_date=last_transaction_date
        )
        
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found or is not a regular user")
    except Exception as e:
        logger.error(f"Error getting user transaction summary {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve transaction summary")

# Additional endpoints for user transaction details
@router.get("/{user_id:int}/transactions", response_model=dict)
async def get_user_charging_transactions(
    user_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin_user: User = Depends(require_admin())
):
    """Get user's charging transactions (admin only)"""
    try:
        user = await User.get(id=user_id, role=UserRoleEnum.USER)
        
        # Get charging transactions with pagination
        offset = (page - 1) * limit
        transactions = await Transaction.filter(user=user).offset(offset).limit(limit).order_by('-created_at').prefetch_related('charger')
        total = await Transaction.filter(user=user).count()
        
        transaction_data = []
        for transaction in transactions:
            charger = await transaction.charger
            transaction_data.append({
                "id": transaction.id,
                "charger_name": charger.name,
                "charger_id": charger.charge_point_string_id,
                "energy_consumed_kwh": transaction.energy_consumed_kwh,
                "start_time": transaction.start_time.isoformat(),
                "end_time": transaction.end_time.isoformat() if transaction.end_time else None,
                "status": transaction.transaction_status.value,
                "stop_reason": transaction.stop_reason
            })
        
        return {
            "data": transaction_data,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit
        }
        
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found or is not a regular user")
    except Exception as e:
        logger.error(f"Error getting user transactions {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve user transactions")

@router.get("/{user_id:int}/wallet-transactions", response_model=dict)
async def get_user_wallet_transactions(
    user_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin_user: User = Depends(require_admin())
):
    """Get user's wallet transactions (admin only)"""
    try:
        user = await User.get(id=user_id, role=UserRoleEnum.USER)
        
        # Get wallet transactions with pagination
        offset = (page - 1) * limit
        wallet_transactions = await WalletTransaction.filter(wallet__user=user).offset(offset).limit(limit).order_by('-created_at')
        total = await WalletTransaction.filter(wallet__user=user).count()
        
        transaction_data = []
        for wt in wallet_transactions:
            transaction_data.append({
                "id": wt.id,
                "amount": float(wt.amount),
                "type": wt.type.value,
                "description": wt.description,
                "payment_metadata": wt.payment_metadata,
                "created_at": wt.created_at.isoformat()
            })
        
        return {
            "data": transaction_data,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit
        }
        
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="User not found or is not a regular user")
    except Exception as e:
        logger.error(f"Error getting user wallet transactions {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve user wallet transactions")

@router.get("/transaction/{transaction_id}", response_model=dict)
async def get_user_transaction_details(
    transaction_id: int,
    current_user: User = Depends(require_user_or_admin())
):
    """Get transaction details for the current user's own transactions"""
    from models import Transaction, MeterValue, WalletTransaction, Charger
    
    try:
        # Get transaction and verify it belongs to the current user (or admin can access any)
        from models import UserRoleEnum
        if current_user.role == UserRoleEnum.ADMIN:
            transaction = await Transaction.filter(id=transaction_id).first()
        else:
            transaction = await Transaction.filter(id=transaction_id, user_id=current_user.id).first()
            
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found or access denied")
        
        # Get related data
        charger = await Charger.filter(id=transaction.charger_id).first()
        meter_values = await MeterValue.filter(transaction_id=transaction_id).order_by("created_at")
        wallet_transactions = await WalletTransaction.filter(charging_transaction_id=transaction_id).all()
        
        if not charger:
            raise HTTPException(status_code=500, detail="Related charger data not found")
        
        return {
            "transaction": {
                "id": transaction.id,
                "user_id": transaction.user_id,
                "charger_id": transaction.charger_id,
                "start_meter_kwh": transaction.start_meter_kwh,
                "end_meter_kwh": transaction.end_meter_kwh,
                "energy_consumed_kwh": transaction.energy_consumed_kwh,
                "start_time": transaction.start_time.isoformat() if transaction.start_time else None,
                "end_time": transaction.end_time.isoformat() if transaction.end_time else None,
                "stop_reason": transaction.stop_reason,
                "transaction_status": transaction.transaction_status.value,
                "created_at": transaction.created_at.isoformat(),
                "updated_at": transaction.updated_at.isoformat()
            },
            "user": {
                "id": current_user.id,
                "full_name": current_user.full_name,
                "email": current_user.email,
                "phone_number": current_user.phone_number
            },
            "charger": {
                "id": charger.id,
                "name": charger.name,
                "charge_point_string_id": charger.charge_point_string_id
            },
            "meter_values": [
                {
                    "id": mv.id,
                    "reading_kwh": mv.reading_kwh,
                    "current": mv.current,
                    "voltage": mv.voltage,
                    "power_kw": mv.power_kw,
                    "created_at": mv.created_at.isoformat()
                } for mv in meter_values
            ],
            "wallet_transactions": [
                {
                    "id": wt.id,
                    "amount": float(wt.amount),
                    "type": wt.type.value,
                    "description": wt.description,
                    "created_at": wt.created_at.isoformat()
                } for wt in wallet_transactions
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user transaction details {transaction_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve transaction details")

@router.get("/transaction/{transaction_id}/meter-values", response_model=dict)
async def get_user_transaction_meter_values(
    transaction_id: int,
    current_user: User = Depends(require_user_or_admin())
):
    """Get meter values for the current user's own transaction"""
    from models import Transaction, MeterValue, UserRoleEnum
    
    try:
        # Get transaction and verify it belongs to the current user (or admin can access any)
        if current_user.role == UserRoleEnum.ADMIN:
            transaction = await Transaction.filter(id=transaction_id).first()
        else:
            transaction = await Transaction.filter(id=transaction_id, user_id=current_user.id).first()
            
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found or access denied")
        
        meter_values = await MeterValue.filter(transaction_id=transaction_id).order_by("created_at")
        
        # Build energy chart data for frontend visualization
        energy_chart_data = {
            "labels": [mv.created_at.isoformat() for mv in meter_values],
            "energy_data": [mv.reading_kwh for mv in meter_values],
            "power_data": [mv.power_kw or 0 for mv in meter_values]
        }
        
        return {
            "meter_values": [
                {
                    "id": mv.id,
                    "reading_kwh": mv.reading_kwh,
                    "current": mv.current,
                    "voltage": mv.voltage,
                    "power_kw": mv.power_kw,
                    "created_at": mv.created_at.isoformat()
                } for mv in meter_values
            ],
            "energy_chart_data": energy_chart_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user transaction meter values {transaction_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve meter values")