from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials
from supabase_client import supabase
from schemas import SignUpRequest, SignInRequest, AuthResponse, UserResponse
from auth_middleware import get_current_user, security
import logging

logger = logging.getLogger("auth-router")
router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/signup")
async def sign_up(request: SignUpRequest):
    """Sign up a new user with email and password"""
    try:
        response = supabase.auth.sign_up({
            "email": request.email,
            "password": request.password,
            "options": {
                "data": request.user_metadata
            }
        })
        
        if response.user is None:
            raise HTTPException(status_code=400, detail="Sign up failed")
        
        logger.info(f"User signed up successfully: {response.user.email}")
        
        # Check if session exists (email confirmation may be required)
        if response.session is None:
            # Email confirmation required
            return {
                "message": "Sign up successful. Please check your email to confirm your account.",
                "user": {
                    "id": response.user.id,
                    "email": response.user.email,
                    "user_metadata": response.user.user_metadata or {},
                    "created_at": response.user.created_at
                },
                "email_confirmation_required": True
            }
        
        # Auto-confirmed user (session available)
        return AuthResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            user={
                "id": response.user.id,
                "email": response.user.email,
                "user_metadata": response.user.user_metadata or {},
                "created_at": response.user.created_at
            },
            expires_in=response.session.expires_in
        )
        
    except Exception as e:
        logger.error(f"Sign up error: {str(e)}")
        if "already registered" in str(e).lower():
            raise HTTPException(status_code=409, detail="User already exists")
        raise HTTPException(status_code=400, detail=f"Sign up failed: {str(e)}")

@router.post("/signin", response_model=AuthResponse)
async def sign_in(request: SignInRequest):
    """Sign in an existing user with email and password"""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password
        })
        
        if response.user is None or response.session is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        logger.info(f"User signed in successfully: {response.user.email}")
        
        return AuthResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            user={
                "id": response.user.id,
                "email": response.user.email,
                "user_metadata": response.user.user_metadata or {},
                "created_at": response.user.created_at
            },
            expires_in=response.session.expires_in
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sign in error: {str(e)}")
        if "invalid login credentials" in str(e).lower() or "invalid_credentials" in str(e).lower():
            raise HTTPException(status_code=401, detail="Invalid email or password")
        raise HTTPException(status_code=400, detail=f"Sign in failed: {str(e)}")

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user information"""
    return UserResponse(
        id=current_user["user_id"],
        email=current_user["email"],
        user_metadata=current_user["user_metadata"],
        created_at=str(current_user["created_at"])
    )

@router.post("/logout")
async def logout(_: HTTPAuthorizationCredentials = Depends(security)):
    """Logout current user by invalidating the session"""
    try:
        # Sign out - supabase.auth.sign_out() doesn't require token parameter
        # It invalidates the current session
        supabase.auth.sign_out()
        
        logger.info("User logged out successfully")
        return {"message": "Logged out successfully"}
        
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Logout failed: {str(e)}")

@router.post("/refresh")
async def refresh_token(refresh_token: str):
    """Refresh access token using refresh token"""
    try:
        response = supabase.auth.refresh_session(refresh_token)
        
        if response.session is None:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        
        return AuthResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            user={
                "id": response.user.id,
                "email": response.user.email,
                "user_metadata": response.user.user_metadata or {},
                "created_at": response.user.created_at
            },
            expires_in=response.session.expires_in
        )
        
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        raise HTTPException(status_code=401, detail="Token refresh failed")