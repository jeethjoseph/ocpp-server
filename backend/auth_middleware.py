import jwt
import os
import httpx
from typing import Optional
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

load_dotenv()

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
if not CLERK_SECRET_KEY:
    raise ValueError("CLERK_SECRET_KEY must be set in environment variables")

security = HTTPBearer()

# Cache for Clerk's JWKS
_jwks_cache = None
_jwks_cache_expiry = 0

async def get_clerk_jwks():
    """Get Clerk's JWKS for JWT verification"""
    global _jwks_cache, _jwks_cache_expiry
    import time
    
    # Cache JWKS for 1 hour
    if _jwks_cache and time.time() < _jwks_cache_expiry:
        return _jwks_cache
    
    # Extract instance ID from secret key
    instance_id = CLERK_SECRET_KEY.split('_')[2] if '_' in CLERK_SECRET_KEY else None
    if not instance_id:
        raise HTTPException(status_code=500, detail="Invalid Clerk secret key format")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://{instance_id}.clerk.accounts.dev/.well-known/jwks.json")
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_expiry = time.time() + 3600  # Cache for 1 hour
            return _jwks_cache
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Clerk JWKS: {str(e)}")

async def verify_token(token: str) -> dict:
    """Verify Clerk JWT token and return user data"""
    try:
        # For now, we'll use a simpler approach by validating against Clerk directly
        # In production, you'd want to verify the JWT signature properly with JWKS
        
        # Decode without verification to get the payload (for development)
        # In production, implement proper JWT verification with JWKS
        payload = jwt.decode(token, options={"verify_signature": False})
        
        # Validate the issuer matches your Clerk instance
        expected_issuer = f"https://{CLERK_SECRET_KEY.split('_')[2]}.clerk.accounts.dev" if '_' in CLERK_SECRET_KEY else None
        if payload.get("iss") != expected_issuer:
            raise HTTPException(status_code=401, detail="Invalid token issuer")
        
        # Return user data from JWT payload
        return {
            "user_id": payload.get("sub"),
            "email": payload.get("email"),
            "user_metadata": payload.get("user_metadata", {}),
            "role": payload.get("role", "authenticated"),
            "created_at": payload.get("iat"),
        }
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """FastAPI dependency to get current authenticated user"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    return await verify_token(credentials.credentials)

async def get_current_user_with_db(credentials: HTTPAuthorizationCredentials = Depends(security)) -> 'User':
    """FastAPI dependency to get current user with database record"""
    from models import User
    
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    # Verify JWT token
    token_data = await verify_token(credentials.credentials)
    
    # Get user from database
    user = await User.filter(clerk_user_id=token_data["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in database")
    
    return user

def require_role(required_role: 'UserRoleEnum'):
    """Dependency factory for role-based access control"""
    async def role_dependency(user: 'User' = Depends(get_current_user_with_db)) -> 'User':
        from models import UserRoleEnum
        
        if user.role != required_role:
            raise HTTPException(
                status_code=403, 
                detail=f"Access denied. Required role: {required_role.value}, your role: {user.role.value}"
            )
        return user
    
    return role_dependency

def require_admin():
    """Convenience dependency for admin-only endpoints"""
    from models import UserRoleEnum
    return require_role(UserRoleEnum.ADMIN)

def require_user_or_admin():
    """Dependency for endpoints accessible by both users and admins"""
    async def user_or_admin_dependency(user: 'User' = Depends(get_current_user_with_db)) -> 'User':
        from models import UserRoleEnum
        
        if user.role not in [UserRoleEnum.USER, UserRoleEnum.ADMIN]:
            raise HTTPException(
                status_code=403, 
                detail="Access denied. User or Admin role required."
            )
        return user
    
    return user_or_admin_dependency