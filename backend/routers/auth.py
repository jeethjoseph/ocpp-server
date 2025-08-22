from fastapi import APIRouter, HTTPException, Depends
from schemas import UserResponse
from auth_middleware import get_current_user
from models import User
import logging

logger = logging.getLogger("auth-router")
router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user information"""
    # Find user in local database by Clerk user ID
    user = await User.filter(clerk_user_id=current_user["user_id"]).first()
    
    if not user:
        # User not found in local database - this shouldn't happen if webhooks are working
        logger.warning(f"User {current_user['user_id']} not found in local database")
        raise HTTPException(status_code=404, detail="User not found in local database")
    
    return UserResponse(
        id=str(user.id),
        email=current_user["email"],
        user_metadata=current_user.get("user_metadata", {}),
        created_at=str(current_user.get("created_at", ""))
    )

