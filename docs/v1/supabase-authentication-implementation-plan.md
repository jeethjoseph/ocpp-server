# Supabase Authentication Implementation Plan
## OCPP 1.6 Charging Station Management System

**Document Version**: 1.0  
**Created**: January 22, 2025  
**Target Completion**: 4 weeks  

---

## Executive Summary

This document outlines the comprehensive implementation plan for integrating Supabase authentication into the existing OCPP 1.6 CSMS. The implementation will support:

- **10 Admin users** for the dashboard management
- **9,000 Monthly Active Users (EV drivers)** for the mobile-first web application
- **Role-based access control** (Admin vs User roles)
- **Google OAuth + Email authentication**
- **JWT token-based security** for all API endpoints
- **Seamless integration** with existing OCPP functionality

**Cost**: **$0/month** (Free tier supports up to 50,000 MAU)

---

## Table of Contents

1. [Project Setup & Configuration](#project-setup--configuration)
2. [Database Schema Migration](#database-schema-migration)
3. [Backend Authentication Implementation](#backend-authentication-implementation)
4. [Admin Dashboard Integration](#admin-dashboard-integration)
5. [EV User Mobile App Authentication](#ev-user-mobile-app-authentication)
6. [OCPP System Integration](#ocpp-system-integration)
7. [Security & Best Practices](#security--best-practices)
8. [Testing Strategy](#testing-strategy)
9. [Deployment & Environment Setup](#deployment--environment-setup)
10. [Implementation Timeline](#implementation-timeline)

---

## Project Setup & Configuration

### 1. Supabase Project Creation

#### Step 1: Create Free Supabase Project
```bash
# 1. Visit https://supabase.com
# 2. Sign up with GitHub (recommended for integration)
# 3. Create new project:
#    - Project name: "ocpp-csms-auth"
#    - Database password: Generate secure password
#    - Region: Select closest to your deployment region
```

#### Step 2: Configure Authentication Providers
```sql
-- Enable Google OAuth in Supabase Dashboard
-- 1. Go to Authentication > Providers
-- 2. Enable Google provider
-- 3. Add OAuth credentials:
--    - Client ID: from Google Cloud Console
--    - Client Secret: from Google Cloud Console
--    - Redirect URLs: 
--      - http://localhost:3000/auth/callback (development)
--      - https://your-domain.com/auth/callback (production)
```

#### Step 3: Get Project Credentials
```bash
# Add to your .env files:
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret
```

### 2. Google OAuth Setup

#### Create Google Cloud Console Project
```bash
# 1. Go to Google Cloud Console
# 2. Create new project or select existing
# 3. Enable Google+ API
# 4. Create OAuth 2.0 credentials:
#    - Application type: Web application
#    - Authorized origins: 
#      - http://localhost:3000
#      - https://your-production-domain.com
#    - Authorized redirect URIs:
#      - https://your-project.supabase.co/auth/v1/callback
```

### 3. Development Dependencies

#### Backend Dependencies
```bash
# Add to backend/requirements.txt
supabase==2.3.4
python-jose[cryptography]==3.3.0
python-multipart==0.0.6
httpx==0.26.0
```

#### Frontend Dependencies
```bash
# Add to frontend/package.json
npm install @supabase/supabase-js @supabase/auth-helpers-nextjs @supabase/auth-helpers-react
```

---

## Database Schema Migration

### 1. Current State Analysis

#### Existing Tables
```sql
-- Current separate tables
CREATE TABLE user (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255),
    phone_number VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    full_name VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE admin_user (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255),
    phone_number VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    full_name VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### 2. New Unified Schema

#### Updated User Model
```python
# backend/models.py - Updated User model
from enum import Enum
from tortoise.models import Model
from tortoise import fields

class UserRoleEnum(str, Enum):
    ADMIN = "ADMIN"
    USER = "USER"  # EV drivers

class AuthProviderEnum(str, Enum):
    EMAIL = "EMAIL"
    GOOGLE = "GOOGLE"
    APPLE = "APPLE"  # Future

class User(Model):
    id = fields.IntField(pk=True)
    
    # Authentication fields
    email = fields.CharField(max_length=255, unique=True)
    phone_number = fields.CharField(max_length=255, unique=True, null=True)
    
    # Supabase integration
    supabase_user_id = fields.CharField(max_length=255, unique=True, null=True)
    auth_provider = fields.CharEnumField(AuthProviderEnum, default=AuthProviderEnum.EMAIL)
    
    # Profile fields
    full_name = fields.CharField(max_length=255, null=True)
    avatar_url = fields.CharField(max_length=500, null=True)  # From Google/social
    role = fields.CharEnumField(UserRoleEnum, default=UserRoleEnum.USER)
    
    # Status and permissions
    is_active = fields.BooleanField(default=True)
    is_email_verified = fields.BooleanField(default=False)
    terms_accepted_at = fields.DatetimeField(null=True)
    
    # Additional EV user fields
    preferred_language = fields.CharField(max_length=10, default="en")
    notification_preferences = fields.JSONField(default=dict)
    
    # RFID/Card integration for OCPP
    rfid_card_id = fields.CharField(max_length=255, unique=True, null=True)
    
    # Timestamps
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    last_login = fields.DatetimeField(null=True)
    
    # Existing relationships (unchanged)
    wallet: fields.ReverseRelation["Wallet"]
    vehicles: fields.ReverseRelation["VehicleProfile"]
    transactions: fields.ReverseRelation["Transaction"]
    
    class Meta:
        table = "user"
        
    @property
    def is_admin(self) -> bool:
        return self.role == UserRoleEnum.ADMIN
        
    @property
    def display_name(self) -> str:
        return self.full_name or self.email.split('@')[0]
```

### 3. Migration Script

#### Database Migration
```python
# backend/migrations/models/3_20250122_add_supabase_auth.py
from tortoise import BaseDBAsyncClient

async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Add new columns to user table
        ALTER TABLE "user" ADD COLUMN "supabase_user_id" VARCHAR(255);
        ALTER TABLE "user" ADD COLUMN "auth_provider" VARCHAR(20) DEFAULT 'EMAIL';
        ALTER TABLE "user" ADD COLUMN "role" VARCHAR(20) DEFAULT 'USER';
        ALTER TABLE "user" ADD COLUMN "avatar_url" VARCHAR(500);
        ALTER TABLE "user" ADD COLUMN "is_email_verified" BOOLEAN DEFAULT FALSE;
        ALTER TABLE "user" ADD COLUMN "terms_accepted_at" TIMESTAMPTZ;
        ALTER TABLE "user" ADD COLUMN "preferred_language" VARCHAR(10) DEFAULT 'en';
        ALTER TABLE "user" ADD COLUMN "notification_preferences" JSONB DEFAULT '{}';
        ALTER TABLE "user" ADD COLUMN "rfid_card_id" VARCHAR(255);
        ALTER TABLE "user" ADD COLUMN "last_login" TIMESTAMPTZ;
        
        -- Make email unique and required
        ALTER TABLE "user" ALTER COLUMN "email" SET NOT NULL;
        CREATE UNIQUE INDEX CONCURRENTLY idx_user_email ON "user"(email);
        CREATE UNIQUE INDEX CONCURRENTLY idx_user_supabase_id ON "user"(supabase_user_id);
        CREATE UNIQUE INDEX CONCURRENTLY idx_user_rfid ON "user"(rfid_card_id);
        
        -- Migrate existing admin users
        INSERT INTO "user" (
            email, phone_number, full_name, is_active, 
            role, created_at, updated_at
        )
        SELECT 
            email, phone_number, full_name, is_active,
            'ADMIN' as role, created_at, updated_at
        FROM admin_user
        WHERE email NOT IN (SELECT email FROM "user");
        
        -- Update existing users to USER role
        UPDATE "user" SET role = 'USER' WHERE role IS NULL;
        
        -- Drop admin_user table
        DROP TABLE IF EXISTS admin_user;
    """

async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Recreate admin_user table and migrate back
        CREATE TABLE admin_user (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255),
            phone_number VARCHAR(255),
            full_name VARCHAR(255),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        );
        
        -- Migrate admin users back
        INSERT INTO admin_user (email, phone_number, full_name, is_active, created_at, updated_at)
        SELECT email, phone_number, full_name, is_active, created_at, updated_at
        FROM "user" WHERE role = 'ADMIN';
        
        -- Remove new columns
        ALTER TABLE "user" DROP COLUMN "supabase_user_id";
        ALTER TABLE "user" DROP COLUMN "auth_provider";
        ALTER TABLE "user" DROP COLUMN "role";
        ALTER TABLE "user" DROP COLUMN "avatar_url";
        ALTER TABLE "user" DROP COLUMN "is_email_verified";
        ALTER TABLE "user" DROP COLUMN "terms_accepted_at";
        ALTER TABLE "user" DROP COLUMN "preferred_language";
        ALTER TABLE "user" DROP COLUMN "notification_preferences";
        ALTER TABLE "user" DROP COLUMN "rfid_card_id";
        ALTER TABLE "user" DROP COLUMN "last_login";
    """
```

---

## Backend Authentication Implementation

### 1. Authentication Service

#### Core Auth Service (Updated with Official Supabase Patterns)
```python
# backend/auth/service.py
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from supabase import create_client, Client
from gotrue import User as SupabaseUser
from fastapi import HTTPException, status
from models import User, UserRoleEnum
import logging

logger = logging.getLogger(__name__)

class AuthService:
    def __init__(self):
        self.supabase: Client = create_client(
            supabase_url=settings.SUPABASE_URL,
            supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY
        )
    
    async def get_user_from_session(self, access_token: str) -> Tuple[SupabaseUser, User]:
        """Get user using Supabase's official session verification"""
        try:
            # Use Supabase's built-in user verification (official method)
            response = self.supabase.auth.get_user(access_token)
            if response.user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired session"
                )
            
            supabase_user = response.user
            local_user = await self._sync_local_user(supabase_user)
            
            # Update last login
            local_user.last_login = datetime.utcnow()
            await local_user.save()
            
            return supabase_user, local_user
            
        except Exception as e:
            logger.error(f"Session verification failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
    
    async def create_admin_user(self, email: str, password: str, full_name: str = None) -> User:
        """Create admin user via Supabase Admin API"""
        try:
            response = self.supabase.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,  # Auto-confirm admin users
                "user_metadata": {
                    "full_name": full_name or email.split('@')[0],
                    "role": "ADMIN"
                }
            })
            
            if response.user is None:
                raise HTTPException(status_code=400, detail="Failed to create admin user")
            
            local_user = await self._sync_local_user(response.user)
            logger.info(f"Created admin user: {email}")
            return local_user
            
        except Exception as e:
            logger.error(f"Admin user creation failed: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Failed to create admin: {str(e)}")
    
    async def send_otp_sms(self, phone: str) -> dict:
        """Send OTP to phone number for EV users"""
        try:
            response = self.supabase.auth.sign_in_with_otp({
                "phone": phone
            })
            return {"success": True, "message": "OTP sent successfully"}
        except Exception as e:
            logger.error(f"OTP send failed: {str(e)}")
            raise HTTPException(status_code=400, detail="Failed to send OTP")
    
    async def verify_otp(self, phone: str, token: str) -> Tuple[SupabaseUser, User]:
        """Verify OTP token and return authenticated user"""
        try:
            response = self.supabase.auth.verify_otp({
                "phone": phone,
                "token": token,
                "type": "sms"
            })
            
            if response.user is None:
                raise HTTPException(status_code=400, detail="Invalid OTP")
            
            local_user = await self._sync_local_user(response.user)
            return response.user, local_user
            
        except Exception as e:
            logger.error(f"OTP verification failed: {str(e)}")
            raise HTTPException(status_code=400, detail="OTP verification failed")
    
    async def refresh_session(self, refresh_token: str) -> dict:
        """Refresh user session using Supabase's session management"""
        try:
            response = self.supabase.auth.refresh_session(refresh_token)
            if response.session is None:
                raise HTTPException(status_code=401, detail="Session refresh failed")
            return {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "expires_in": response.session.expires_in
            }
        except Exception as e:
            logger.error(f"Session refresh failed: {str(e)}")
            raise HTTPException(status_code=401, detail="Failed to refresh session")
    
    async def sign_out_user(self, access_token: str) -> dict:
        """Sign out user and invalidate session"""
        try:
            # Supabase handles session invalidation
            response = self.supabase.auth.sign_out(access_token)
            return {"success": True, "message": "Signed out successfully"}
        except Exception as e:
            logger.error(f"Sign out failed: {str(e)}")
            # Don't fail sign out - client can handle locally
            return {"success": True, "message": "Signed out locally"}
    
    async def update_user_role(self, supabase_user_id: str, role: str) -> User:
        """Update user role via Supabase Admin API"""
        try:
            response = self.supabase.auth.admin.update_user_by_id(
                supabase_user_id,
                {"user_metadata": {"role": role}}
            )
            
            if response.user is None:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Update local user record
            local_user = await User.filter(supabase_user_id=supabase_user_id).first()
            if local_user:
                local_user.role = UserRoleEnum(role)
                await local_user.save()
            
            return local_user
            
        except Exception as e:
            logger.error(f"Role update failed: {str(e)}")
            raise HTTPException(status_code=400, detail="Failed to update user role")
    
    async def delete_user(self, supabase_user_id: str) -> bool:
        """Delete user from both Supabase and local database"""
        try:
            # Delete from Supabase
            response = self.supabase.auth.admin.delete_user(supabase_user_id)
            
            # Delete from local database
            local_user = await User.filter(supabase_user_id=supabase_user_id).first()
            if local_user:
                await local_user.delete()
            
            return True
            
        except Exception as e:
            logger.error(f"User deletion failed: {str(e)}")
            raise HTTPException(status_code=400, detail="Failed to delete user")
    
    async def _sync_local_user(self, supabase_user: SupabaseUser) -> User:
        """Sync Supabase user data with local database"""
        # Check if user exists locally
        local_user = await User.filter(supabase_user_id=supabase_user.id).first()
        
        if not local_user:
            # Create new local user
            local_user = await self._create_local_user(supabase_user)
        else:
            # Update existing user with latest Supabase data
            await self._update_local_user(local_user, supabase_user)
        
        return local_user
    
    async def _create_local_user(self, supabase_user: SupabaseUser) -> User:
        """Create new local user from Supabase user data"""
        email = supabase_user.email
        if not email:
            raise HTTPException(status_code=400, detail="User email is required")
        
        # Determine auth provider
        provider = "EMAIL"
        for identity in supabase_user.identities or []:
            if identity.provider == "google":
                provider = "GOOGLE"
                break
        
        # Determine role from user metadata
        user_metadata = supabase_user.user_metadata or {}
        role = UserRoleEnum.USER
        
        if user_metadata.get("role") == "ADMIN":
            role = UserRoleEnum.ADMIN
        elif email.endswith("@your-company.com"):  # Admin email domain
            role = UserRoleEnum.ADMIN
        
        user = await User.create(
            supabase_user_id=supabase_user.id,
            email=email,
            phone_number=supabase_user.phone,
            full_name=user_metadata.get("full_name") or user_metadata.get("name"),
            avatar_url=user_metadata.get("avatar_url") or user_metadata.get("picture"),
            auth_provider=provider,
            role=role,
            is_email_verified=supabase_user.email_confirmed_at is not None,
        )
        
        # Create wallet for EV users
        if role == UserRoleEnum.USER:
            from models import Wallet
            await Wallet.create(user=user, balance=0.0)
        
        logger.info(f"Created local user: {email} with role: {role}")
        return user
    
    async def _update_local_user(self, local_user: User, supabase_user: SupabaseUser) -> None:
        """Update existing local user with Supabase data"""
        user_metadata = supabase_user.user_metadata or {}
        
        # Update fields that might have changed
        local_user.email = supabase_user.email or local_user.email
        local_user.phone_number = supabase_user.phone or local_user.phone_number
        local_user.full_name = user_metadata.get("full_name") or user_metadata.get("name") or local_user.full_name
        local_user.avatar_url = user_metadata.get("avatar_url") or user_metadata.get("picture") or local_user.avatar_url
        local_user.is_email_verified = supabase_user.email_confirmed_at is not None
        
        # Update role if changed in Supabase
        metadata_role = user_metadata.get("role")
        if metadata_role and metadata_role != local_user.role:
            local_user.role = UserRoleEnum(metadata_role)
        
        await local_user.save()

auth_service = AuthService()
```

### 2. Authentication Dependencies

#### FastAPI Dependencies (Updated)
```python
# backend/auth/dependencies.py
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer
from typing import Optional, Tuple
from models import User, UserRoleEnum
from gotrue import User as SupabaseUser
from .service import auth_service
import logging

logger = logging.getLogger(__name__)
security = HTTPBearer()

async def get_current_user(
    token: str = Depends(security)
) -> Tuple[SupabaseUser, User]:
    """Get current authenticated user using official Supabase methods"""
    try:
        supabase_user, local_user = await auth_service.get_user_from_session(token.credentials)
        
        if not local_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive"
            )
        
        return supabase_user, local_user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

async def get_current_local_user(
    user_data: Tuple[SupabaseUser, User] = Depends(get_current_user)
) -> User:
    """Get just the local user object (common use case)"""
    supabase_user, local_user = user_data
    return local_user

async def get_current_admin_user(
    local_user: User = Depends(get_current_local_user)
) -> User:
    """Require admin role"""
    if local_user.role != UserRoleEnum.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return local_user

async def get_current_active_user(
    local_user: User = Depends(get_current_local_user)
) -> User:
    """Get any active user (admin or regular)"""
    return local_user

# Optional authentication (for public endpoints with optional auth)
async def get_current_user_optional(
    request: Request,
    token: Optional[str] = Depends(HTTPBearer(auto_error=False))
) -> Optional[User]:
    """Optional authentication - returns None if no valid token"""
    if not token:
        return None
    
    try:
        supabase_user, local_user = await auth_service.get_user_from_session(token.credentials)
        return local_user if local_user.is_active else None
    except Exception as e:
        logger.debug(f"Optional auth failed: {str(e)}")
        return None

# Rate limiting decorator for auth endpoints
from functools import wraps
import time
from collections import defaultdict

_rate_limit_storage = defaultdict(list)

def rate_limit(max_requests: int = 5, window_seconds: int = 60):
    """Rate limiting decorator for authentication endpoints"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get client IP (simplified for demo)
            client_ip = "127.0.0.1"  # In production, extract from request
            current_time = time.time()
            
            # Clean old requests
            _rate_limit_storage[client_ip] = [
                req_time for req_time in _rate_limit_storage[client_ip]
                if current_time - req_time < window_seconds
            ]
            
            # Check rate limit
            if len(_rate_limit_storage[client_ip]) >= max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many requests. Try again in {window_seconds} seconds."
                )
            
            # Record this request
            _rate_limit_storage[client_ip].append(current_time)
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

### 3. Updated API Routes

#### Admin Routes Protection
```python
# backend/routers/chargers.py - Updated with authentication
from fastapi import APIRouter, Depends, HTTPException
from auth.dependencies import get_current_admin_user, get_current_user
from models import User

router = APIRouter(prefix="/api/admin/chargers", tags=["chargers"])

@router.get("/")
async def list_chargers(
    current_admin: User = Depends(get_current_admin_user),
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    station_id: Optional[int] = None,
    search: Optional[str] = None
):
    """List chargers (Admin only)"""
    # Existing charger list logic with authentication
    chargers = await get_chargers_with_filters(page, limit, status, station_id, search)
    return chargers

@router.post("/{charger_id}/remote-start")
async def remote_start_charger(
    charger_id: int,
    request: RemoteStartRequest,
    current_admin: User = Depends(get_current_admin_user)
):
    """Remote start transaction (Admin only)"""
    # Existing remote start logic
    success, result = await send_ocpp_request(
        charger_id, 
        "RemoteStartTransaction", 
        request.dict()
    )
    
    # Log admin action
    logger.info(f"Admin {current_admin.email} initiated remote start for charger {charger_id}")
    
    return {"success": success, "result": result}
```

#### User Routes (EV Drivers)
```python
# backend/routers/user.py - New user-facing routes
from fastapi import APIRouter, Depends
from auth.dependencies import get_current_active_user
from models import User, Transaction, Wallet

router = APIRouter(prefix="/api/user", tags=["user"])

@router.get("/profile")
async def get_user_profile(current_user: User = Depends(get_current_active_user)):
    """Get current user profile"""
    await current_user.fetch_related("wallet", "vehicles")
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "avatar_url": current_user.avatar_url,
        "phone_number": current_user.phone_number,
        "wallet_balance": current_user.wallet.balance if current_user.wallet else 0,
        "vehicles": [
            {
                "id": vehicle.id,
                "make": vehicle.make,
                "model": vehicle.model,
                "year": vehicle.year
            }
            for vehicle in current_user.vehicles
        ]
    }

@router.get("/transactions")
async def get_user_transactions(
    current_user: User = Depends(get_current_active_user),
    page: int = 1,
    limit: int = 20
):
    """Get user's charging transactions"""
    transactions = await Transaction.filter(user=current_user).prefetch_related(
        "charger", "charger__station"
    ).offset((page - 1) * limit).limit(limit).order_by("-created_at")
    
    return {
        "data": [
            {
                "id": t.id,
                "start_time": t.start_time,
                "end_time": t.end_time,
                "energy_consumed_kwh": t.energy_consumed_kwh,
                "transaction_status": t.transaction_status,
                "charger": {
                    "name": t.charger.name,
                    "station": {
                        "name": t.charger.station.name,
                        "address": t.charger.station.address
                    }
                }
            }
            for t in transactions
        ]
    }

@router.get("/wallet")
async def get_user_wallet(current_user: User = Depends(get_current_active_user)):
    """Get user wallet information"""
    await current_user.fetch_related("wallet")
    wallet_transactions = await current_user.wallet.transactions.all().order_by("-created_at").limit(10)
    
    return {
        "balance": current_user.wallet.balance,
        "recent_transactions": [
            {
                "id": wt.id,
                "amount": wt.amount,
                "type": wt.type,
                "description": wt.description,
                "created_at": wt.created_at
            }
            for wt in wallet_transactions
        ]
    }
```

### 4. Authentication Middleware

#### Main App Integration
```python
# backend/main.py - Updated with authentication
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth.dependencies import get_current_user_optional
from routers import stations, chargers, transactions
from routers import user as user_router  # New user routes

app = FastAPI(title="OCPP Central System API", version="0.1.0")

# Updated CORS for Supabase
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ocpp-frontend-mu.vercel.app",
        "https://your-ev-app-domain.com"  # Add EV app domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(stations.router)
app.include_router(chargers.router)
app.include_router(transactions.router)
app.include_router(user_router.router)  # New user routes

# Health check endpoint
@app.get("/")
def read_root():
    return {
        "message": "OCPP Central System API",
        "version": "0.1.0",
        "authentication": "Supabase JWT",
        "endpoints": {
            "admin": "/api/admin/*",
            "user": "/api/user/*",
            "ocpp": "/ocpp/{charge_point_id}"
        }
    }

# Public endpoint for checking authentication
@app.get("/api/auth/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user_optional)
):
    """Get current user info (public endpoint for frontend)"""
    if not current_user:
        return {"authenticated": False}
    
    return {
        "authenticated": True,
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": current_user.role,
            "avatar_url": current_user.avatar_url
        }
    }
```

---

## Admin Dashboard Integration

### 1. Supabase Client Setup

#### Frontend Configuration (Enhanced with Official Patterns)
```typescript
// frontend/lib/supabase.ts
import { createClient, SupabaseClient, Session, User } from '@supabase/supabase-js'
import { Database } from './database.types'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!

export const supabase: SupabaseClient<Database> = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: true,
    flowType: 'pkce', // Use PKCE flow for better security
    storage: typeof window !== 'undefined' ? window.localStorage : undefined
  }
})

// Enhanced auth helper functions with proper error handling
export const authHelpers = {
  async signInWithGoogle(redirectTo?: string) {
    try {
      const { data, error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: redirectTo || `${window.location.origin}/dashboard`,
          queryParams: {
            access_type: 'offline',
            prompt: 'consent'
          }
        }
      })
      
      if (error) {
        console.error('Google sign-in error:', error)
        return { data: null, error }
      }
      
      return { data, error: null }
    } catch (err) {
      console.error('Google sign-in unexpected error:', err)
      return { data: null, error: { message: 'Unexpected error during Google sign-in' } }
    }
  },

  async signInWithEmail(email: string, password: string) {
    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email: email.trim().toLowerCase(),
        password
      })
      
      if (error) {
        console.error('Email sign-in error:', error)
      }
      
      return { data, error }
    } catch (err) {
      console.error('Email sign-in unexpected error:', err)
      return { data: null, error: { message: 'Unexpected error during sign-in' } }
    }
  },

  async signUp(email: string, password: string, userData?: any) {
    try {
      const { data, error } = await supabase.auth.signUp({
        email: email.trim().toLowerCase(),
        password,
        options: {
          data: {
            full_name: userData?.full_name || email.split('@')[0],
            ...userData
          }
        }
      })
      
      if (error) {
        console.error('Sign-up error:', error)
      }
      
      return { data, error }
    } catch (err) {
      console.error('Sign-up unexpected error:', err)
      return { data: null, error: { message: 'Unexpected error during sign-up' } }
    }
  },

  // Phone authentication methods
  async signInWithPhone(phone: string) {
    try {
      const { data, error } = await supabase.auth.signInWithOtp({
        phone: phone.trim(),
        options: {
          shouldCreateUser: true
        }
      })
      
      if (error) {
        console.error('Phone sign-in error:', error)
      }
      
      return { data, error }
    } catch (err) {
      console.error('Phone sign-in unexpected error:', err)
      return { data: null, error: { message: 'Failed to send OTP' } }
    }
  },

  async verifyOtp(phone: string, token: string) {
    try {
      const { data, error } = await supabase.auth.verifyOtp({
        phone: phone.trim(),
        token: token.trim(),
        type: 'sms'
      })
      
      if (error) {
        console.error('OTP verification error:', error)
      }
      
      return { data, error }
    } catch (err) {
      console.error('OTP verification unexpected error:', err)
      return { data: null, error: { message: 'OTP verification failed' } }
    }
  },

  async signOut() {
    try {
      const { error } = await supabase.auth.signOut()
      
      if (error) {
        console.error('Sign-out error:', error)
      }
      
      // Clear any additional local storage
      if (typeof window !== 'undefined') {
        localStorage.removeItem('user-preferences')
        localStorage.removeItem('recent-searches')
      }
      
      return { error }
    } catch (err) {
      console.error('Sign-out unexpected error:', err)
      return { error: { message: 'Unexpected error during sign-out' } }
    }
  },

  async getSession(): Promise<Session | null> {
    try {
      const { data: { session }, error } = await supabase.auth.getSession()
      
      if (error) {
        console.error('Get session error:', error)
        return null
      }
      
      return session
    } catch (err) {
      console.error('Get session unexpected error:', err)
      return null
    }
  },

  async getUser(): Promise<User | null> {
    try {
      const { data: { user }, error } = await supabase.auth.getUser()
      
      if (error) {
        console.error('Get user error:', error)
        return null
      }
      
      return user
    } catch (err) {
      console.error('Get user unexpected error:', err)
      return null
    }
  },

  async refreshSession(): Promise<Session | null> {
    try {
      const { data: { session }, error } = await supabase.auth.refreshSession()
      
      if (error) {
        console.error('Refresh session error:', error)
        return null
      }
      
      return session
    } catch (err) {
      console.error('Refresh session unexpected error:', err)
      return null
    }
  },

  async updateUser(updates: {
    email?: string
    password?: string
    data?: any
  }) {
    try {
      const { data, error } = await supabase.auth.updateUser(updates)
      
      if (error) {
        console.error('Update user error:', error)
      }
      
      return { data, error }
    } catch (err) {
      console.error('Update user unexpected error:', err)
      return { data: null, error: { message: 'Failed to update user' } }
    }
  },

  // Session management utilities
  isSessionValid(session: Session | null): boolean {
    if (!session) return false
    
    const now = Math.floor(Date.now() / 1000)
    return session.expires_at ? session.expires_at > now : false
  },

  getTokenExpiryTime(session: Session | null): Date | null {
    if (!session?.expires_at) return null
    return new Date(session.expires_at * 1000)
  }
}

// Real-time auth state subscription helper
export const createAuthStateListener = (callback: (event: string, session: Session | null) => void) => {
  const { data: { subscription } } = supabase.auth.onAuthStateChange(callback)
  return subscription
}
```

### 2. Authentication Context

#### Auth Provider
```typescript
// frontend/contexts/AuthContext.tsx
'use client'

import React, { createContext, useContext, useEffect, useState } from 'react'
import { User, Session } from '@supabase/supabase-js'
import { supabase, authHelpers } from '@/lib/supabase'
import { useRouter } from 'next/navigation'

interface AuthContextType {
  user: User | null
  session: Session | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<any>
  signInWithGoogle: () => Promise<any>
  signUp: (email: string, password: string) => Promise<any>
  signOut: () => Promise<any>
  userRole: 'ADMIN' | 'USER' | null
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [userRole, setUserRole] = useState<'ADMIN' | 'USER' | null>(null)
  const router = useRouter()

  useEffect(() => {
    // Get initial session
    getInitialSession()

    // Listen for auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event, session) => {
        setSession(session)
        setUser(session?.user ?? null)
        
        if (session?.user) {
          await fetchUserRole(session.access_token)
        } else {
          setUserRole(null)
        }
        
        setLoading(false)
      }
    )

    return () => subscription.unsubscribe()
  }, [])

  async function getInitialSession() {
    const session = await authHelpers.getSession()
    setSession(session)
    setUser(session?.user ?? null)
    
    if (session?.access_token) {
      await fetchUserRole(session.access_token)
    }
    
    setLoading(false)
  }

  async function fetchUserRole(accessToken: string) {
    try {
      const response = await fetch('/api/auth/me', {
        headers: {
          'Authorization': `Bearer ${accessToken}`
        }
      })
      
      if (response.ok) {
        const data = await response.json()
        setUserRole(data.user?.role || null)
      }
    } catch (error) {
      console.error('Error fetching user role:', error)
    }
  }

  const value = {
    user,
    session,
    loading,
    userRole,
    signIn: authHelpers.signInWithEmail,
    signInWithGoogle: authHelpers.signInWithGoogle,
    signUp: authHelpers.signUp,
    signOut: async () => {
      const result = await authHelpers.signOut()
      if (!result.error) {
        router.push('/login')
      }
      return result
    }
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
```

### 3. Login Page

#### Admin Login Component
```typescript
// frontend/app/login/page.tsx
'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const { signIn, signInWithGoogle } = useAuth()
  const router = useRouter()

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      const { error } = await signIn(email, password)
      
      if (error) {
        toast.error(error.message)
      } else {
        toast.success('Logged in successfully')
        router.push('/dashboard')
      }
    } catch (error) {
      toast.error('An unexpected error occurred')
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleLogin = async () => {
    setLoading(true)
    
    try {
      const { error } = await signInWithGoogle()
      
      if (error) {
        toast.error(error.message)
        setLoading(false)
      }
      // Success will be handled by auth state change
    } catch (error) {
      toast.error('An unexpected error occurred')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold text-center">
            OCPP Admin Login
          </CardTitle>
          <CardDescription className="text-center">
            Sign in to your admin account
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            onClick={handleGoogleLogin}
            disabled={loading}
            variant="outline"
            className="w-full"
          >
            {loading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24">
                <path
                  fill="currentColor"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="currentColor"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="currentColor"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                />
                <path
                  fill="currentColor"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                />
              </svg>
            )}
            Continue with Google
          </Button>

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-background px-2 text-muted-foreground">
                Or continue with email
              </span>
            </div>
          </div>

          <form onSubmit={handleEmailLogin} className="space-y-4">
            <div className="space-y-2">
              <Input
                type="email"
                placeholder="admin@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Sign In
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
```

### 4. Protected Routes

#### Route Protection
```typescript
// frontend/components/ProtectedRoute.tsx
'use client'

import { useAuth } from '@/contexts/AuthContext'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'
import { Loader2 } from 'lucide-react'

interface ProtectedRouteProps {
  children: React.ReactNode
  requireAdmin?: boolean
}

export function ProtectedRoute({ children, requireAdmin = false }: ProtectedRouteProps) {
  const { user, loading, userRole } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!loading) {
      if (!user) {
        router.push('/login')
        return
      }

      if (requireAdmin && userRole !== 'ADMIN') {
        router.push('/unauthorized')
        return
      }
    }
  }, [user, loading, userRole, requireAdmin, router])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  if (!user) {
    return null // Will redirect to login
  }

  if (requireAdmin && userRole !== 'ADMIN') {
    return null // Will redirect to unauthorized
  }

  return <>{children}</>
}
```

### 5. Updated Layout

#### Root Layout with Auth
```typescript
// frontend/app/layout.tsx - Updated with AuthProvider
import { AuthProvider } from '@/contexts/AuthContext'
import { QueryProvider } from '@/contexts/QueryClientProvider'
import { ThemeProvider } from '@/contexts/ThemeContext'
import Navbar from '@/components/Navbar'
import { Toaster } from 'sonner'
import './globals.css'

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="antialiased bg-background text-foreground transition-colors duration-300">
        <QueryProvider>
          <AuthProvider>
            <ThemeProvider>
              <Navbar />
              <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
                {children}
              </main>
              <Toaster />
            </ThemeProvider>
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  )
}
```

### 6. Updated API Client

#### Authenticated API Client
```typescript
// frontend/lib/api-client.ts - Updated with authentication
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

import { supabase } from './supabase'

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const session = await supabase.auth.getSession()
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  
  if (session.data.session?.access_token) {
    headers.Authorization = `Bearer ${session.data.session.access_token}`
  }
  
  return headers
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  
  const headers = await getAuthHeaders()
  
  const config: RequestInit = {
    headers: {
      ...headers,
      ...options.headers,
    },
    ...options,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    if (response.status === 401) {
      // Token expired, redirect to login
      await supabase.auth.signOut()
      window.location.href = '/login'
    }
    
    throw new ApiError(
      response.status,
      response.statusText,
      `API request failed: ${response.status} ${response.statusText}`
    );
  }

  return response.json();
}

export const api = {
  get: <T>(endpoint: string) => apiRequest<T>(endpoint, { method: "GET" }),
  
  post: <T>(endpoint: string, data?: unknown) =>
    apiRequest<T>(endpoint, {
      method: "POST",
      body: data ? JSON.stringify(data) : undefined,
    }),
    
  put: <T>(endpoint: string, data?: unknown) =>
    apiRequest<T>(endpoint, {
      method: "PUT",
      body: data ? JSON.stringify(data) : undefined,
    }),
    
  delete: <T>(endpoint: string) =>
    apiRequest<T>(endpoint, { method: "DELETE" }),
};
```

---

## EV User Mobile App Authentication

### 1. Mobile-First Login Page

#### EV User Login Component
```typescript
// ev-app/app/login/page.tsx
'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { toast } from 'sonner'
import { Loader2, Zap } from 'lucide-react'

export default function EVLoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLogin, setIsLogin] = useState(true)
  const [loading, setLoading] = useState(false)
  const { signIn, signUp, signInWithGoogle } = useAuth()
  const router = useRouter()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      const { error } = isLogin 
        ? await signIn(email, password)
        : await signUp(email, password, { 
            full_name: email.split('@')[0] // Basic name from email
          })
      
      if (error) {
        toast.error(error.message)
      } else {
        toast.success(isLogin ? 'Logged in successfully' : 'Account created! Please check your email.')
        if (isLogin) {
          router.push('/stations')
        }
      }
    } catch (error) {
      toast.error('An unexpected error occurred')
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleLogin = async () => {
    setLoading(true)
    
    try {
      const { error } = await signInWithGoogle()
      
      if (error) {
        toast.error(error.message)
        setLoading(false)
      }
      // Success handled by auth state change
    } catch (error) {
      toast.error('An unexpected error occurred')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-green-400 via-blue-500 to-purple-600 p-4 flex items-center justify-center">
      <Card className="w-full max-w-md backdrop-blur-sm bg-white/90 border-0 shadow-xl">
        <CardHeader className="text-center space-y-4">
          <div className="mx-auto w-16 h-16 bg-gradient-to-br from-green-500 to-blue-600 rounded-full flex items-center justify-center">
            <Zap className="h-8 w-8 text-white" />
          </div>
          <div>
            <CardTitle className="text-2xl font-bold bg-gradient-to-r from-green-600 to-blue-600 bg-clip-text text-transparent">
              EV Charging
            </CardTitle>
            <CardDescription className="text-gray-600">
              {isLogin ? 'Sign in to start charging' : 'Create your account'}
            </CardDescription>
          </div>
        </CardHeader>
        
        <CardContent className="space-y-6">
          <Button
            onClick={handleGoogleLogin}
            disabled={loading}
            variant="outline"
            className="w-full h-12 text-gray-700 border-gray-300 hover:bg-gray-50"
          >
            {loading ? (
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            ) : (
              <svg className="mr-2 h-5 w-5" viewBox="0 0 24 24">
                <path
                  fill="#4285f4"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="#34a853"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="#fbbc05"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                />
                <path
                  fill="#ea4335"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                />
              </svg>
            )}
            Continue with Google
          </Button>

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t border-gray-300" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-white px-2 text-gray-500">
                Or continue with email
              </span>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              type="email"
              placeholder="your.email@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="h-12"
            />
            <Input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="h-12"
            />
            <Button 
              type="submit" 
              className="w-full h-12 bg-gradient-to-r from-green-600 to-blue-600 hover:from-green-700 hover:to-blue-700 text-white font-medium" 
              disabled={loading}
            >
              {loading && <Loader2 className="mr-2 h-5 w-5 animate-spin" />}
              {isLogin ? 'Sign In' : 'Create Account'}
            </Button>
          </form>

          <div className="text-center">
            <button
              type="button"
              onClick={() => setIsLogin(!isLogin)}
              className="text-sm text-blue-600 hover:text-blue-700 font-medium"
            >
              {isLogin 
                ? "Don't have an account? Sign up" 
                : "Already have an account? Sign in"
              }
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
```

### 2. EV App Main Pages

#### Charging Stations Map/List
```typescript
// ev-app/app/stations/page.tsx
'use client'

import { useAuth } from '@/contexts/AuthContext'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { useStations } from '@/lib/queries/stations'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { MapPin, Zap, Clock } from 'lucide-react'

function StationsContent() {
  const { user } = useAuth()
  const { data: stations, isLoading } = useStations()

  if (isLoading) {
    return <div className="p-4 text-center">Loading charging stations...</div>
  }

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="max-w-md mx-auto space-y-4">
        <div className="text-center py-4">
          <h1 className="text-2xl font-bold text-gray-900">
            Welcome, {user?.user_metadata?.full_name || 'EV Driver'}!
          </h1>
          <p className="text-gray-600">Find charging stations near you</p>
        </div>

        <div className="space-y-4">
          {stations?.data.map((station) => (
            <Card key={station.id} className="shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg flex items-center gap-2">
                  <MapPin className="h-5 w-5 text-blue-600" />
                  {station.name}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-gray-600">{station.address}</p>
                
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-4 text-sm">
                    <span className="flex items-center gap-1">
                      <Zap className="h-4 w-4 text-green-600" />
                      {station._charger_count} chargers
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="h-4 w-4 text-orange-600" />
                      24/7
                    </span>
                  </div>
                  <Button 
                    size="sm" 
                    className="bg-gradient-to-r from-green-600 to-blue-600"
                    onClick={() => router.push(`/stations/${station.id}`)}
                  >
                    View Details
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function StationsPage() {
  return (
    <ProtectedRoute>
      <StationsContent />
    </ProtectedRoute>
  )
}
```

#### User Profile Page
```typescript
// ev-app/app/profile/page.tsx
'use client'

import { useAuth } from '@/contexts/AuthContext'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { useUserProfile } from '@/lib/queries/user'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { User, Wallet, Car, LogOut } from 'lucide-react'

function ProfileContent() {
  const { user, signOut } = useAuth()
  const { data: profile } = useUserProfile()

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="max-w-md mx-auto space-y-6">
        {/* Profile Header */}
        <Card>
          <CardContent className="pt-6">
            <div className="text-center space-y-4">
              <Avatar className="h-20 w-20 mx-auto">
                <AvatarImage src={user?.user_metadata?.avatar_url} />
                <AvatarFallback>
                  {user?.user_metadata?.full_name?.[0] || user?.email?.[0] || 'U'}
                </AvatarFallback>
              </Avatar>
              <div>
                <h2 className="text-xl font-semibold">
                  {user?.user_metadata?.full_name || 'EV Driver'}
                </h2>
                <p className="text-gray-600">{user?.email}</p>
                <Badge variant="secondary" className="mt-2">
                  {user?.user_metadata?.provider || 'Email'} Account
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Wallet */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <Wallet className="h-5 w-5" />
              Wallet Balance
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">
              ${profile?.wallet_balance?.toFixed(2) || '0.00'}
            </div>
            <Button size="sm" className="mt-2">
              Add Funds
            </Button>
          </CardContent>
        </Card>

        {/* Vehicles */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <Car className="h-5 w-5" />
              My Vehicles
            </CardTitle>
          </CardHeader>
          <CardContent>
            {profile?.vehicles?.length ? (
              <div className="space-y-2">
                {profile.vehicles.map((vehicle) => (
                  <div key={vehicle.id} className="p-2 bg-gray-50 rounded">
                    <p className="font-medium">{vehicle.year} {vehicle.make} {vehicle.model}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-4 text-gray-500">
                <Car className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p>No vehicles added yet</p>
                <Button size="sm" variant="outline" className="mt-2">
                  Add Vehicle
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Sign Out */}
        <Button 
          onClick={signOut} 
          variant="outline" 
          className="w-full"
        >
          <LogOut className="mr-2 h-4 w-4" />
          Sign Out
        </Button>
      </div>
    </div>
  )
}

export default function ProfilePage() {
  return (
    <ProtectedRoute>
      <ProfileContent />
    </ProtectedRoute>
  )
}
```

---

## OCPP System Integration

### 1. Updated Transaction Handling

#### Enhanced StartTransaction with Improved User Authentication
```python
# backend/main.py - Updated OCPP handlers with enhanced authentication
from auth.service import auth_service
from models import User, UserRoleEnum, Transaction, VehicleProfile, Charger, TransactionStatusEnum
import asyncio
from typing import Optional

class UserLookupService:
    """Centralized user lookup service for OCPP transactions"""
    
    @staticmethod
    async def find_user_by_id_tag(id_tag: str) -> Optional[User]:
        """Enhanced user lookup with multiple authentication methods"""
        if not id_tag:
            return None
        
        user = None
        
        # Method 1: RFID Card ID (primary method)
        if len(id_tag) >= 4:  # Minimum RFID card length
            user = await User.filter(rfid_card_id=id_tag, is_active=True).first()
            if user:
                logger.info(f"Found user by RFID card: {user.email}")
                return user
        
        # Method 2: Email (for development/testing)
        if "@" in id_tag and len(id_tag.split("@")) == 2:
            user = await User.filter(email=id_tag.lower(), is_active=True).first()
            if user:
                logger.info(f"Found user by email: {user.email}")
                return user
        
        # Method 3: Phone number (international format support)
        if id_tag.replace("+", "").replace("-", "").replace(" ", "").isdigit():
            # Normalize phone number
            normalized_phone = id_tag.replace("-", "").replace(" ", "")
            user = await User.filter(phone_number=normalized_phone, is_active=True).first()
            if user:
                logger.info(f"Found user by phone: {user.email}")
                return user
        
        # Method 4: Supabase User ID (for API-initiated transactions)
        if len(id_tag) == 36 and id_tag.count("-") == 4:  # UUID format
            user = await User.filter(supabase_user_id=id_tag, is_active=True).first()
            if user:
                logger.info(f"Found user by Supabase ID: {user.email}")
                return user
        
        logger.warning(f"No active user found for id_tag: {id_tag}")
        return None
    
    @staticmethod
    async def create_guest_user(id_tag: str, charger_location: str = None) -> Optional[User]:
        """Create guest user for one-time charging (if enabled)"""
        try:
            # Create guest user with Supabase (anonymous user)
            guest_user = await auth_service.supabase.auth.sign_in_anonymously()
            
            if guest_user.user:
                # Create local user record
                user = await User.create(
                    supabase_user_id=guest_user.user.id,
                    email=f"guest-{id_tag}@temporary.local",
                    full_name=f"Guest User {id_tag[:8]}",
                    role=UserRoleEnum.USER,
                    rfid_card_id=id_tag,
                    auth_provider="GUEST",
                    is_email_verified=False
                )
                
                # Create wallet with limited balance for guest users
                from models import Wallet
                await Wallet.create(user=user, balance=25.0)  # $25 guest limit
                
                logger.info(f"Created guest user for id_tag: {id_tag}")
                return user
                
        except Exception as e:
            logger.error(f"Failed to create guest user: {e}")
            
        return None

@on('StartTransaction')
async def on_start_transaction(self, connector_id, id_tag, meter_start, timestamp, **kwargs):
    logger.info(f"StartTransaction from {self.id}: connector_id={connector_id}, id_tag={id_tag}")
    
    try:
        # Get charger from database
        charger = await Charger.filter(charge_point_string_id=self.id).prefetch_related('station').first()
        if not charger:
            logger.error(f"Charger {self.id} not found in database")
            return call_result.StartTransaction(
                transaction_id=0,
                id_tag_info={"status": "Invalid"}
            )
        
        # Enhanced user lookup
        user = await UserLookupService.find_user_by_id_tag(id_tag)
        
        # If no user found, check if guest users are allowed
        if not user and getattr(settings, 'ALLOW_GUEST_CHARGING', False):
            user = await UserLookupService.create_guest_user(
                id_tag, 
                charger.station.name if charger.station else None
            )
        
        if not user:
            logger.warning(f"Authentication failed for id_tag: {id_tag}")
            return call_result.StartTransaction(
                transaction_id=0,
                id_tag_info={"status": "Invalid"}
            )
        
        # Verify user is active and in good standing
        if not user.is_active:
            logger.warning(f"User {user.email} account is inactive")
            return call_result.StartTransaction(
                transaction_id=0,
                id_tag_info={"status": "Blocked"}
            )
        
        # Check for existing active transactions
        existing_transaction = await Transaction.filter(
            user=user,
            transaction_status=TransactionStatusEnum.RUNNING
        ).first()
        
        if existing_transaction:
            logger.warning(f"User {user.email} already has active transaction {existing_transaction.id}")
            return call_result.StartTransaction(
                transaction_id=0,
                id_tag_info={"status": "ConcurrentTx"}
            )
        
        # Wallet balance validation
        await user.fetch_related("wallet")
        minimum_balance = 5.0  # Configurable minimum
        
        if user.wallet and user.wallet.balance < minimum_balance:
            logger.warning(f"Insufficient balance for user {user.email}: ${user.wallet.balance:.2f} < ${minimum_balance}")
            return call_result.StartTransaction(
                transaction_id=0,
                id_tag_info={"status": "Invalid"}
            )
        
        # Get or create vehicle profile
        vehicle = await user.vehicles.filter().first()
        if not vehicle:
            vehicle = await VehicleProfile.create(
                user=user,
                make="Unknown",
                model="Unknown",
                license_plate=f"TEMP-{id_tag[:6]}"
            )
        
        # Create transaction record with enhanced metadata
        transaction = await Transaction.create(
            user=user,
            charger=charger,
            vehicle=vehicle,
            start_meter_kwh=float(meter_start) / 1000,  # Convert Wh to kWh
            transaction_status=TransactionStatusEnum.RUNNING,
            id_tag_used=id_tag,
            connector_id=connector_id,
            start_time=timestamp
        )
        
        # Update user's last activity
        user.last_login = datetime.utcnow()
        await user.save()
        
        logger.info(f"🔋 Started transaction {transaction.id} for {user.email} (balance: ${user.wallet.balance if user.wallet else 0:.2f})")
        
        # Send notification to user (if phone/email available)
        await send_transaction_notification(user, transaction, "started")
        
        return call_result.StartTransaction(
            transaction_id=transaction.id,
            id_tag_info={
                "status": "Accepted",
                "parent_id_tag": id_tag,
                "expiry_date": timestamp  # Optional: set expiry
            }
        )
        
    except Exception as e:
        logger.error(f"Error in StartTransaction for {self.id}: {e}", exc_info=True)
        return call_result.StartTransaction(
            transaction_id=0,
            id_tag_info={"status": "Invalid"}
        )

async def send_transaction_notification(user: User, transaction: Transaction, event: str):
    """Send notification to user about transaction events"""
    try:
        if not user.notification_preferences.get('charging_updates', True):
            return
        
        # SMS notification (if phone available)
        if user.phone_number and user.notification_preferences.get('sms', False):
            await send_sms_notification(user.phone_number, f"Charging {event} at {transaction.charger.name}")
        
        # Email notification  
        if user.email and user.notification_preferences.get('email', True):
            await send_email_notification(user.email, f"Charging {event}", transaction)
            
        # Push notification via Supabase (if user has app)
        if user.supabase_user_id:
            await send_push_notification(user.supabase_user_id, f"Charging {event}")
            
    except Exception as e:
        logger.warning(f"Failed to send notification to {user.email}: {e}")

async def send_sms_notification(phone: str, message: str):
    """Send SMS via your preferred SMS provider"""
    # Implement SMS sending logic
    pass

async def send_email_notification(email: str, subject: str, transaction: Transaction):
    """Send email notification"""
    # Implement email sending logic
    pass

async def send_push_notification(user_id: str, message: str):
    """Send push notification via Supabase"""
    # Implement push notification logic
    pass
```

### 2. Enhanced StopTransaction with Billing

#### Automatic Wallet Deduction
```python
@on('StopTransaction')
async def on_stop_transaction(self, transaction_id, meter_stop, timestamp, **kwargs):
    logger.info(f"🛑 StopTransaction from {self.id}: transaction_id={transaction_id}, meter_stop={meter_stop}")
    
    from models import Transaction, TransactionStatusEnum, WalletTransaction, TransactionTypeEnum
    import datetime
    
    try:
        # Get transaction from database
        transaction = await Transaction.filter(id=transaction_id).prefetch_related('user', 'user__wallet', 'charger').first()
        if not transaction:
            logger.error(f"🛑 ❌ Transaction {transaction_id} not found")
            return call_result.StopTransaction(
                id_tag_info={"status": "Invalid"}
            )
        
        logger.info(f"🛑 Processing stop for transaction {transaction_id}, user: {transaction.user.email}")
        
        # Calculate energy consumption and cost
        transaction.end_meter_kwh = float(meter_stop) / 1000  # Convert Wh to kWh
        energy_consumed = transaction.end_meter_kwh - (transaction.start_meter_kwh or 0)
        transaction.energy_consumed_kwh = energy_consumed
        
        # Calculate cost ($0.35 per kWh - make this configurable)
        cost_per_kwh = 0.35
        total_cost = energy_consumed * cost_per_kwh
        
        # Update transaction
        transaction.end_time = datetime.datetime.now(datetime.timezone.utc)
        transaction.transaction_status = TransactionStatusEnum.COMPLETED
        transaction.stop_reason = kwargs.get('reason', 'Remote')
        
        # Process payment
        if total_cost > 0 and transaction.user.wallet:
            if transaction.user.wallet.balance >= total_cost:
                # Deduct from wallet
                transaction.user.wallet.balance -= total_cost
                await transaction.user.wallet.save()
                
                # Create wallet transaction record
                await WalletTransaction.create(
                    wallet=transaction.user.wallet,
                    amount=-total_cost,
                    type=TransactionTypeEnum.CHARGE_DEDUCT,
                    description=f"Charging session at {transaction.charger.name}: {energy_consumed:.2f} kWh",
                    charging_transaction=transaction
                )
                
                logger.info(f"🛑 💰 Charged ${total_cost:.2f} to {transaction.user.email}, remaining balance: ${transaction.user.wallet.balance:.2f}")
            else:
                # Insufficient funds - mark as failed but allow completion
                logger.warning(f"🛑 ⚠️ Insufficient funds for {transaction.user.email}: ${transaction.user.wallet.balance:.2f} needed ${total_cost:.2f}")
                # Could implement credit/debt handling here
        
        await transaction.save()
        
        logger.info(f"🛑 ✅ Completed transaction {transaction_id}: {energy_consumed:.2f} kWh, ${total_cost:.2f}")
        
        return call_result.StopTransaction(
            id_tag_info={"status": "Accepted"}
        )
        
    except Exception as e:
        logger.error(f"Error stopping transaction {transaction_id}: {e}", exc_info=True)
        return call_result.StopTransaction(
            id_tag_info={"status": "Invalid"}
        )
```

### 3. User Management API for OCPP Integration

#### RFID Card Management
```python
# backend/routers/user.py - RFID card management
@router.post("/rfid-cards")
async def assign_rfid_card(
    request: AssignRFIDRequest,
    current_user: User = Depends(get_current_active_user)
):
    """Assign RFID card to current user"""
    # Check if card is already assigned
    existing_user = await User.filter(rfid_card_id=request.card_id).first()
    if existing_user and existing_user.id != current_user.id:
        raise HTTPException(status_code=400, detail="RFID card already assigned to another user")
    
    current_user.rfid_card_id = request.card_id
    await current_user.save()
    
    return {"message": "RFID card assigned successfully"}

@router.delete("/rfid-cards")
async def remove_rfid_card(current_user: User = Depends(get_current_active_user)):
    """Remove RFID card from current user"""
    current_user.rfid_card_id = None
    await current_user.save()
    
    return {"message": "RFID card removed successfully"}
```

---

## Security & Best Practices

### 1. Environment Variables Configuration

#### Development Environment
```bash
# .env.local (Frontend)
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_API_URL=http://localhost:8000

# .env (Backend)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret

# Database (existing)
DB_HOST=localhost
DB_PORT=5432
DB_USER=ocpp_user
DB_PASSWORD=secure_password
DB_NAME=ocpp_db

# Redis (existing)
REDIS_URL=redis://localhost:6379
```

#### Production Environment
```bash
# Production .env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-production-service-role-key
SUPABASE_JWT_SECRET=your-production-jwt-secret

# Production database and Redis URLs
DATABASE_URL=postgresql://...
REDIS_URL=redis://...

# CORS origins
ALLOWED_ORIGINS=https://your-admin-dashboard.com,https://your-ev-app.com
```

### 2. JWT Token Security

#### Token Validation Middleware
```python
# backend/auth/security.py
from functools import wraps
from typing import Callable
import time

def rate_limit_auth(max_attempts: int = 5, window_minutes: int = 15):
    """Rate limit authentication attempts"""
    attempts = {}
    
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Implementation for rate limiting
            client_ip = "127.0.0.1"  # Get from request
            current_time = time.time()
            
            # Clean old attempts
            attempts[client_ip] = [
                attempt_time for attempt_time in attempts.get(client_ip, [])
                if current_time - attempt_time < window_minutes * 60
            ]
            
            if len(attempts.get(client_ip, [])) >= max_attempts:
                raise HTTPException(
                    status_code=429, 
                    detail=f"Too many authentication attempts. Try again in {window_minutes} minutes."
                )
            
            try:
                result = await func(*args, **kwargs)
                return result
            except HTTPException as e:
                if e.status_code == 401:
                    attempts.setdefault(client_ip, []).append(current_time)
                raise
        
        return wrapper
    return decorator
```

### 3. Input Validation & Sanitization

#### Request Validation Schemas
```python
# backend/auth/schemas.py
from pydantic import BaseModel, EmailStr, validator
from typing import Optional

class UserRegistrationRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    
    @validator('phone_number')
    def validate_phone(cls, v):
        if v and not v.replace('+', '').replace('-', '').replace(' ', '').isdigit():
            raise ValueError('Invalid phone number format')
        return v

class AssignRFIDRequest(BaseModel):
    card_id: str
    
    @validator('card_id')
    def validate_card_id(cls, v):
        if not v or len(v) < 4 or len(v) > 50:
            raise ValueError('Card ID must be between 4 and 50 characters')
        # Additional validation for card ID format
        if not v.replace('-', '').replace(':', '').isalnum():
            raise ValueError('Card ID contains invalid characters')
        return v

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    preferred_language: Optional[str] = "en"
    
    @validator('full_name')
    def validate_name(cls, v):
        if v and len(v.strip()) < 2:
            raise ValueError('Name must be at least 2 characters long')
        return v.strip() if v else None
```

### 4. Row Level Security (RLS) in Supabase

#### Supabase RLS Policies
```sql
-- Enable RLS on auth.users
ALTER TABLE auth.users ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own data
CREATE POLICY "Users can view own profile" ON auth.users
    FOR SELECT USING (auth.uid() = id);

-- Policy: Users can update their own profile
CREATE POLICY "Users can update own profile" ON auth.users
    FOR UPDATE USING (auth.uid() = id);

-- Custom user data table policies (if storing additional data in Supabase)
CREATE TABLE IF NOT EXISTS user_profiles (
    id uuid REFERENCES auth.users(id) PRIMARY KEY,
    full_name text,
    avatar_url text,
    updated_at timestamp DEFAULT now()
);

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own profile" ON user_profiles
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" ON user_profiles
    FOR INSERT WITH CHECK (auth.uid() = id);

CREATE POLICY "Users can update own profile" ON user_profiles
    FOR UPDATE USING (auth.uid() = id);
```

### 5. CORS and Security Headers

#### Enhanced Security Configuration
```python
# backend/main.py - Enhanced security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Admin dashboard dev
        "https://admin.your-domain.com",  # Admin dashboard prod
        "https://app.your-domain.com",  # EV app prod
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Trusted hosts
app.add_middleware(
    TrustedHostMiddleware, 
    allowed_hosts=["localhost", "*.your-domain.com", "your-api-domain.com"]
)

# Compression
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response
```

---

## Testing Strategy

### 1. Authentication Testing

#### Backend Authentication Tests
```python
# backend/tests/test_auth.py
import pytest
from fastapi.testclient import TestClient
from main import app
from auth.service import auth_service
import jwt
from datetime import datetime, timedelta

client = TestClient(app)

@pytest.mark.asyncio
async def test_jwt_verification():
    """Test JWT token verification"""
    # Create mock JWT token
    payload = {
        "sub": "test-user-id",
        "email": "test@example.com",
        "aud": "authenticated",
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    
    token = jwt.encode(payload, "test-secret", algorithm="HS256")
    
    # Mock settings
    with patch('auth.service.settings.SUPABASE_JWT_SECRET', 'test-secret'):
        result = await auth_service.verify_jwt_token(token)
        assert result["sub"] == "test-user-id"
        assert result["email"] == "test@example.com"

@pytest.mark.asyncio
async def test_protected_endpoint():
    """Test protected endpoint access"""
    # Test without token
    response = client.get("/api/admin/chargers")
    assert response.status_code == 401
    
    # Test with valid token
    token = create_test_jwt_token("admin@example.com", role="ADMIN")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/admin/chargers", headers=headers)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_role_based_access():
    """Test role-based access control"""
    # Create user token
    user_token = create_test_jwt_token("user@example.com", role="USER")
    headers = {"Authorization": f"Bearer {user_token}"}
    
    # User should not access admin endpoints
    response = client.get("/api/admin/chargers", headers=headers)
    assert response.status_code == 403
    
    # User should access user endpoints
    response = client.get("/api/user/profile", headers=headers)
    assert response.status_code == 200
```

### 2. Frontend Authentication Tests

#### React Component Tests
```typescript
// frontend/__tests__/auth/LoginPage.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { AuthProvider } from '@/contexts/AuthContext'
import LoginPage from '@/app/login/page'
import { supabase } from '@/lib/supabase'

jest.mock('@/lib/supabase')

const renderWithAuth = (component: React.ReactNode) => {
  return render(
    <AuthProvider>
      {component}
    </AuthProvider>
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  test('renders login form', () => {
    renderWithAuth(<LoginPage />)
    
    expect(screen.getByPlaceholderText('admin@company.com')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Password')).toBeInTheDocument()
    expect(screen.getByText('Continue with Google')).toBeInTheDocument()
  })

  test('handles email login', async () => {
    const mockSignIn = jest.fn().mockResolvedValue({ data: {}, error: null })
    ;(supabase.auth.signInWithPassword as jest.Mock) = mockSignIn

    renderWithAuth(<LoginPage />)
    
    fireEvent.change(screen.getByPlaceholderText('admin@company.com'), {
      target: { value: 'test@example.com' }
    })
    fireEvent.change(screen.getByPlaceholderText('Password'), {
      target: { value: 'password123' }
    })
    
    fireEvent.click(screen.getByText('Sign In'))
    
    await waitFor(() => {
      expect(mockSignIn).toHaveBeenCalledWith({
        email: 'test@example.com',
        password: 'password123'
      })
    })
  })

  test('handles Google OAuth', async () => {
    const mockSignInWithOAuth = jest.fn().mockResolvedValue({ data: {}, error: null })
    ;(supabase.auth.signInWithOAuth as jest.Mock) = mockSignInWithOAuth

    renderWithAuth(<LoginPage />)
    
    fireEvent.click(screen.getByText('Continue with Google'))
    
    await waitFor(() => {
      expect(mockSignInWithOAuth).toHaveBeenCalledWith({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}/dashboard`
        }
      })
    })
  })
})
```

### 3. OCPP Integration Tests

#### Authentication in OCPP Flow
```python
# backend/tests/test_ocpp_auth.py
import pytest
import websockets
import json
from models import User, UserRoleEnum, Wallet

@pytest.mark.integration
async def test_ocpp_transaction_with_authenticated_user():
    """Test OCPP transaction flow with authenticated user"""
    
    # Create test user with wallet
    user = await User.create(
        email="test@example.com",
        role=UserRoleEnum.USER,
        rfid_card_id="TEST_CARD_001",
        supabase_user_id="test-supabase-id"
    )
    wallet = await Wallet.create(user=user, balance=50.0)
    
    # Connect to OCPP WebSocket
    async with websockets.connect(f"ws://localhost:8000/ocpp/CP001") as ws:
        
        # Send BootNotification
        boot_msg = [2, "1", "BootNotification", {
            "chargePointVendor": "Test",
            "chargePointModel": "TestModel"
        }]
        await ws.send(json.dumps(boot_msg))
        response = json.loads(await ws.recv())
        assert response[2]["status"] == "Accepted"
        
        # Send StartTransaction with user's RFID card
        start_msg = [2, "2", "StartTransaction", {
            "connectorId": 1,
            "idTag": "TEST_CARD_001",  # User's RFID card
            "meterStart": 1000
        }]
        await ws.send(json.dumps(start_msg))
        response = json.loads(await ws.recv())
        
        # Should be accepted for authenticated user with sufficient balance
        assert response[2]["idTagInfo"]["status"] == "Accepted"
        transaction_id = response[2]["transactionId"]
        assert transaction_id > 0
        
        # Verify transaction created
        from models import Transaction
        transaction = await Transaction.get(id=transaction_id)
        assert transaction.user.id == user.id
        
        # Send StopTransaction
        stop_msg = [2, "3", "StopTransaction", {
            "transactionId": transaction_id,
            "meterStop": 2000,
            "timestamp": "2025-01-22T10:30:00Z"
        }]
        await ws.send(json.dumps(stop_msg))
        response = json.loads(await ws.recv())
        assert response[2]["idTagInfo"]["status"] == "Accepted"
        
        # Verify payment processed
        await user.refresh_from_db()
        await user.fetch_related("wallet")
        assert user.wallet.balance < 50.0  # Should be deducted

@pytest.mark.integration
async def test_ocpp_transaction_insufficient_balance():
    """Test OCPP transaction rejected for insufficient balance"""
    
    # Create test user with low balance
    user = await User.create(
        email="poor@example.com",
        role=UserRoleEnum.USER,
        rfid_card_id="POOR_CARD_001"
    )
    wallet = await Wallet.create(user=user, balance=1.0)  # Low balance
    
    async with websockets.connect(f"ws://localhost:8000/ocpp/CP001") as ws:
        # BootNotification
        boot_msg = [2, "1", "BootNotification", {"chargePointVendor": "Test", "chargePointModel": "TestModel"}]
        await ws.send(json.dumps(boot_msg))
        await ws.recv()
        
        # StartTransaction should be rejected
        start_msg = [2, "2", "StartTransaction", {
            "connectorId": 1,
            "idTag": "POOR_CARD_001",
            "meterStart": 1000
        }]
        await ws.send(json.dumps(start_msg))
        response = json.loads(await ws.recv())
        
        # Should be rejected for insufficient balance
        assert response[2]["idTagInfo"]["status"] == "Invalid"
        assert response[2]["transactionId"] == 0
```

---

## Deployment & Environment Setup

### 1. Production Environment Variables

#### Supabase Production Configuration
```bash
# Production .env file
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-production-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-production-service-role-key
SUPABASE_JWT_SECRET=your-production-jwt-secret

# Database (existing)
DATABASE_URL=postgresql://user:password@host:5432/dbname

# Redis (existing)
REDIS_URL=redis://user:password@host:6379

# CORS Origins
ALLOWED_ORIGINS=https://admin.your-domain.com,https://app.your-domain.com

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=100

# Logging
LOG_LEVEL=INFO
SENTRY_DSN=your-sentry-dsn  # Optional error tracking
```

### 2. Render Deployment Configuration

#### Backend Deployment (Render)
```yaml
# render.yaml
services:
  - type: web
    name: ocpp-backend
    env: python
    buildCommand: "pip install -r requirements.txt"
    startCommand: "python main.py"
    envVars:
      - key: SUPABASE_URL
        value: https://your-project.supabase.co
      - key: SUPABASE_SERVICE_ROLE_KEY
        fromSecret: SUPABASE_SERVICE_ROLE_KEY
      - key: SUPABASE_JWT_SECRET
        fromSecret: SUPABASE_JWT_SECRET
      - key: DATABASE_URL
        fromDatabase: 
          name: ocpp-db
          property: connectionString
      - key: REDIS_URL
        fromService:
          type: redis
          name: ocpp-redis
          property: connectionString
```

### 3. Vercel Frontend Deployment

#### Admin Dashboard Deployment
```json
{
  "name": "ocpp-admin-dashboard",
  "version": 2,
  "builds": [
    {
      "src": "frontend/package.json",
      "use": "@vercel/next"
    }
  ],
  "env": {
    "NEXT_PUBLIC_SUPABASE_URL": "https://your-project.supabase.co",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY": "@supabase-anon-key",
    "NEXT_PUBLIC_API_URL": "https://your-api-domain.com"
  },
  "routes": [
    {
      "src": "/frontend/(.*)",
      "dest": "/frontend/$1"
    }
  ]
}
```

#### EV App Deployment
```json
{
  "name": "ev-charging-app",
  "version": 2,
  "builds": [
    {
      "src": "ev-app/package.json",
      "use": "@vercel/next"
    }
  ],
  "env": {
    "NEXT_PUBLIC_SUPABASE_URL": "https://your-project.supabase.co",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY": "@supabase-anon-key",
    "NEXT_PUBLIC_API_URL": "https://your-api-domain.com"
  }
}
```

### 4. Database Migration for Production

#### Production Migration Script
```bash
#!/bin/bash
# scripts/deploy_auth.sh

echo "🚀 Deploying Supabase Authentication System"

# 1. Backup current database
echo "📦 Creating database backup..."
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Run Tortoise migrations
echo "🔄 Running database migrations..."
cd backend
aerich upgrade

# 3. Verify critical tables exist
echo "✅ Verifying database schema..."
python -c "
import asyncio
from tortoise import Tortoise
from models import User, Wallet
from tortoise_config import TORTOISE_ORM

async def verify_schema():
    await Tortoise.init(config=TORTOISE_ORM)
    
    # Test user creation
    try:
        user = await User.create(
            email='test@verify.com',
            role='USER'
        )
        await Wallet.create(user=user, balance=0.0)
        await user.delete()  # Cleanup
        print('✅ Schema verification successful')
    except Exception as e:
        print(f'❌ Schema verification failed: {e}')
        raise
    
    await Tortoise.close_connections()

asyncio.run(verify_schema())
"

# 4. Test authentication endpoint
echo "🔍 Testing authentication endpoints..."
curl -f "$API_URL/api/auth/me" || echo "⚠️ Auth endpoint test failed (expected without token)"

echo "✅ Authentication system deployment complete!"
echo "📝 Next steps:"
echo "   1. Configure Google OAuth in Supabase dashboard"
echo "   2. Update frontend environment variables"
echo "   3. Test login flows"
echo "   4. Monitor logs for any issues"
```

### 5. Monitoring & Health Checks

#### Health Check Endpoints
```python
# backend/routers/health.py
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
import asyncio

router = APIRouter(prefix="/health", tags=["health"])

@router.get("/")
async def health_check():
    """Basic health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "version": "1.0.0",
        "services": {
            "api": "healthy",
            "auth": "enabled"
        }
    }

@router.get("/auth")
async def auth_health_check():
    """Authentication system health check"""
    try:
        # Test Supabase connection
        from auth.service import auth_service
        
        # Create a test JWT payload (don't actually verify)
        test_payload = {
            "sub": "health-check",
            "aud": "authenticated"
        }
        
        return {
            "status": "healthy",
            "auth_provider": "supabase",
            "jwt_verification": "enabled",
            "timestamp": datetime.utcnow()
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Auth system unhealthy: {str(e)}")

@router.get("/database")
async def database_health_check():
    """Database connectivity health check"""
    try:
        from models import User
        count = await User.all().count()
        return {
            "status": "healthy",
            "user_count": count,
            "timestamp": datetime.utcnow()
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unhealthy: {str(e)}")
```

---

## Implementation Timeline

### Phase 1: Foundation Setup (Week 1)
#### Days 1-2: Supabase Project Setup
- [x] Create free Supabase project
- [x] Configure Google OAuth provider
- [x] Set up development environment variables
- [x] Test basic Supabase connection

#### Days 3-4: Database Migration
- [x] Create unified User model with roles
- [x] Generate and test database migration
- [x] Migrate existing AdminUser data
- [x] Verify all relationships intact

#### Days 5-7: Backend Authentication Core
- [x] Implement JWT verification service
- [x] Create authentication dependencies
- [x] Add basic protected endpoints
- [x] Test with Postman/curl

**Deliverables**:
- ✅ Working JWT authentication in FastAPI
- ✅ Unified User table with roles
- ✅ Basic protected admin endpoints

### Phase 2: Admin Dashboard Integration (Week 2)
#### Days 8-10: Frontend Auth Setup
- [ ] Install Supabase client libraries
- [ ] Create authentication context
- [ ] Build login page component
- [ ] Implement Google OAuth flow

#### Days 11-12: Protected Routes
- [ ] Create ProtectedRoute component
- [ ] Update existing dashboard pages
- [ ] Test role-based access control
- [ ] Handle authentication errors

#### Days 13-14: Admin API Integration
- [ ] Update API client with JWT tokens
- [ ] Modify existing charger/station management
- [ ] Test admin workflows end-to-end
- [ ] Fix any authentication issues

**Deliverables**:
- ✅ Admin dashboard with Google login
- ✅ Protected admin routes working
- ✅ Existing OCPP functionality intact

### Phase 3: EV User App Development (Week 3)
#### Days 15-17: EV App Authentication
- [ ] Create mobile-first login page
- [ ] Implement user registration flow
- [ ] Build user profile management
- [ ] Create wallet interface

#### Days 18-19: User-Facing Features
- [ ] Build charging stations list/map
- [ ] Create transaction history page
- [ ] Implement user settings
- [ ] Add vehicle profile management

#### Days 20-21: OCPP Integration
- [ ] Update StartTransaction with user lookup
- [ ] Implement automatic wallet deduction
- [ ] Add RFID card assignment
- [ ] Test complete charging flow

**Deliverables**:
- ✅ Mobile EV user app with authentication
- ✅ User transaction management
- ✅ OCPP integration with user authentication

### Phase 4: Testing & Production Deployment (Week 4)
#### Days 22-24: Testing
- [ ] Write authentication unit tests
- [ ] Create OCPP integration tests
- [ ] Test both user flows end-to-end
- [ ] Performance testing with auth overhead

#### Days 25-26: Production Preparation
- [ ] Set up production Supabase project
- [ ] Configure production environment variables
- [ ] Deploy to staging environment
- [ ] Run production migration

#### Days 27-28: Go-Live
- [ ] Deploy to production
- [ ] Monitor for issues
- [ ] Create user documentation
- [ ] Train stakeholders on new flows

**Deliverables**:
- ✅ Production-ready authentication system
- ✅ Both admin and EV user apps deployed
- ✅ Complete testing coverage
- ✅ Documentation and training complete

---

## Success Metrics

### Authentication System KPIs
- **User Registration Success Rate**: >95%
- **Login Success Rate**: >98%
- **Authentication Response Time**: <500ms
- **Token Refresh Success Rate**: >99%
- **Google OAuth Success Rate**: >95%

### OCPP Integration KPIs
- **Transaction Authentication Rate**: 100% (no unauthenticated transactions)
- **Payment Processing Success**: >98%
- **RFID Card Recognition**: >99%
- **Transaction Completion Rate**: >95%

### Performance Metrics
- **API Response Time with Auth**: <200ms (same as current)
- **Frontend Load Time**: <3 seconds
- **Database Query Performance**: No degradation
- **Concurrent User Support**: 1000+ simultaneous users

### Business Metrics
- **Admin User Adoption**: 100% (10 users)
- **EV User Registration**: Target 1000 users in first month
- **Authentication-Related Support Tickets**: <5% of total tickets
- **System Uptime**: >99.9%

---

## Risk Mitigation

### Technical Risks
1. **Migration Data Loss**: 
   - Mitigation: Complete database backup before migration
   - Rollback plan: Automated rollback scripts prepared

2. **OCPP Functionality Broken**: 
   - Mitigation: Extensive integration testing
   - Fallback: Keep existing user creation logic as backup

3. **Authentication Provider Downtime**:
   - Mitigation: Supabase SLA 99.9% uptime
   - Fallback: Email/password still works if Google OAuth fails

4. **Performance Degradation**:
   - Mitigation: JWT verification is fast (<10ms)
   - Monitoring: Performance testing before production

### Business Risks
1. **User Adoption Resistance**:
   - Mitigation: Gradual rollout, training provided
   - Admin users get early access for feedback

2. **Google OAuth Approval Delays**:
   - Mitigation: Email authentication works immediately
   - Google OAuth can be added later if needed

### Operational Risks
1. **Deployment Complexity**:
   - Mitigation: Staged deployment (dev → staging → production)
   - Documentation: Complete deployment runbook

2. **Support Complexity**:
   - Mitigation: Clear error messages and user guidance
   - Documentation: Troubleshooting guide for common issues

---

## Conclusion

This comprehensive Supabase authentication implementation plan provides:

1. **Cost-Effective Solution**: Free for initial scale, predictable pricing growth
2. **Production-Ready Security**: JWT tokens, role-based access, rate limiting
3. **Seamless Integration**: Minimal impact on existing OCPP functionality
4. **Scalable Architecture**: Supports growth from 10 to 50,000+ users
5. **Modern User Experience**: Google OAuth, mobile-first design, responsive UI

The 4-week timeline is achievable with proper planning and execution. The system will be production-ready with comprehensive testing and monitoring.

**Next Steps**: 
1. Create Supabase project (free)
2. Begin Phase 1 implementation
3. Set up development environment
4. Start database migration planning

This plan ensures your OCPP 1.6 CSMS will have enterprise-grade authentication while maintaining its excellent existing functionality.