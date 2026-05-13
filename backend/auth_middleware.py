import jwt
import os
import logging
from typing import Optional, Tuple
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ocpp-server")

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
if not CLERK_SECRET_KEY:
    raise ValueError("CLERK_SECRET_KEY must be set in environment variables")

CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL")
CLERK_ISSUER = os.getenv("CLERK_ISSUER")

if not CLERK_JWKS_URL:
    # Derive from secret key for dev convenience; production must set explicitly
    if "_" in CLERK_SECRET_KEY:
        parts = CLERK_SECRET_KEY.split("_")
        if len(parts) >= 3:
            instance_id = parts[2][:10]
            CLERK_JWKS_URL = f"https://{instance_id}.clerk.accounts.dev/.well-known/jwks.json"
            if not CLERK_ISSUER:
                CLERK_ISSUER = f"https://{instance_id}.clerk.accounts.dev"
            logger.warning(
                "CLERK_JWKS_URL not set; derived from secret key as %s. "
                "Set CLERK_JWKS_URL and CLERK_ISSUER explicitly in production.",
                CLERK_JWKS_URL,
            )
        else:
            raise ValueError("Cannot derive CLERK_JWKS_URL: invalid CLERK_SECRET_KEY format")
    else:
        raise ValueError("CLERK_JWKS_URL must be set when CLERK_SECRET_KEY has no underscore")

if not CLERK_ISSUER:
    raise ValueError("CLERK_ISSUER must be set when CLERK_JWKS_URL is set explicitly")

security = HTTPBearer()

# Module-level JWKS client — caches keys across requests, auto-refreshes on kid miss
_jwks_client = jwt.PyJWKClient(CLERK_JWKS_URL, cache_keys=True, lifespan=3600)


async def verify_token(token: str) -> dict:
    """Verify Clerk JWT token signature + issuer, return user data."""
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER,
            options={"verify_aud": False},
        )

        from models import User as UserModel
        user_in_db = await UserModel.filter(clerk_user_id=payload.get("sub")).first()

        role = "USER"
        if user_in_db:
            role = user_in_db.role.value if hasattr(user_in_db.role, "value") else str(user_in_db.role)

        return {
            "user_id": payload.get("sub"),
            "email": payload.get("email"),
            "user_metadata": payload.get("user_metadata", {}),
            "public_metadata": payload.get("public_metadata", {}),
            "role": role,
            "created_at": payload.get("iat"),
        }

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Invalid token issuer")
    except jwt.InvalidSignatureError:
        raise HTTPException(status_code=401, detail="Invalid token signature")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Authentication error")
        raise HTTPException(status_code=401, detail="Authentication failed")


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """FastAPI dependency to get current authenticated user"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required")

    return await verify_token(credentials.credentials)


async def get_current_user_with_db(credentials: HTTPAuthorizationCredentials = Depends(security)) -> "User":
    """FastAPI dependency to get current user with database record"""
    from models import User

    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token_data = await verify_token(credentials.credentials)

    user = await User.filter(clerk_user_id=token_data["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in database")

    return user


def require_role(required_role: "UserRoleEnum"):
    """Dependency factory for role-based access control"""
    async def role_dependency(user: "User" = Depends(get_current_user_with_db)) -> "User":
        from models import UserRoleEnum

        if user.role != required_role:
            logger.warning(
                "Role mismatch — required=%s user=%s user_id=%s",
                required_role.value, user.role.value, user.id,
            )
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


def require_user():
    """Convenience dependency for user-only endpoints"""
    from models import UserRoleEnum
    return require_role(UserRoleEnum.USER)


def require_user_or_admin():
    """Dependency for endpoints accessible by both users and admins"""
    async def user_or_admin_dependency(user: "User" = Depends(get_current_user_with_db)) -> "User":
        from models import UserRoleEnum

        if user.role not in [UserRoleEnum.USER, UserRoleEnum.ADMIN]:
            raise HTTPException(
                status_code=403,
                detail="Access denied. User or Admin role required."
            )
        return user

    return user_or_admin_dependency


def require_franchisee():
    """Dependency for franchisee-only endpoints. Returns (User, Franchisee) tuple.

    Rejects SUSPENDED / DEACTIVATED franchisees: a valid Clerk JWT alone is
    not enough — admin status changes must take effect within one request,
    not at the next JWT refresh. DRAFT and KYC_* statuses remain allowed so
    franchisees can complete onboarding from the portal.
    """
    async def franchisee_dependency(
        user: "User" = Depends(get_current_user_with_db),
    ):
        from models import UserRoleEnum, Franchisee, FranchiseeStatusEnum

        if user.role != UserRoleEnum.FRANCHISEE:
            raise HTTPException(
                status_code=403,
                detail="Access denied. Franchisee role required.",
            )
        franchisee = await Franchisee.filter(user=user).first()
        if not franchisee:
            raise HTTPException(
                status_code=404,
                detail="No franchisee profile linked to this user.",
            )
        if franchisee.status in (
            FranchiseeStatusEnum.SUSPENDED,
            FranchiseeStatusEnum.DEACTIVATED,
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Franchisee account is suspended."
                    if franchisee.status == FranchiseeStatusEnum.SUSPENDED
                    else "Franchisee account is deactivated."
                ),
            )
        return user, franchisee

    return franchisee_dependency


def require_admin_or_franchisee():
    """Dependency for endpoints accessible by admin or franchisee.
    Returns (User, Optional[Franchisee]) -- Franchisee is None for admins.

    Admins bypass the franchisee status check (they may need to view a
    suspended/deactivated franchisee for audit). For franchisee callers,
    rejects SUSPENDED / DEACTIVATED — same rule as ``require_franchisee``.
    """
    async def admin_or_franchisee_dependency(
        user: "User" = Depends(get_current_user_with_db),
    ):
        from models import UserRoleEnum, Franchisee, FranchiseeStatusEnum

        if user.role == UserRoleEnum.ADMIN:
            return user, None
        if user.role == UserRoleEnum.FRANCHISEE:
            franchisee = await Franchisee.filter(user=user).first()
            if not franchisee:
                raise HTTPException(
                    status_code=404,
                    detail="No franchisee profile linked to this user.",
                )
            if franchisee.status in (
                FranchiseeStatusEnum.SUSPENDED,
                FranchiseeStatusEnum.DEACTIVATED,
            ):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Franchisee account is suspended."
                        if franchisee.status == FranchiseeStatusEnum.SUSPENDED
                        else "Franchisee account is deactivated."
                    ),
                )
            return user, franchisee
        raise HTTPException(
            status_code=403,
            detail="Access denied. Admin or Franchisee role required.",
        )

    return admin_or_franchisee_dependency
