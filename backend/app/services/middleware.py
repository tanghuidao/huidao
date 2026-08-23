"""Authentication dependency and middleware for FastAPI."""
import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.auth import decode_access_token, get_user_by_id, check_membership_permission

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
):
    """Extract and validate the current user from JWT token.

    Returns the user object if authenticated, raises 401 otherwise.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌载荷",
        )

    user = get_user_by_id(db, int(user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用",
        )

    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
):
    """Extract user from JWT if present, but don't require it.

    Returns user object or None. Useful for endpoints that work
    differently for authenticated vs anonymous users.
    """
    if credentials is None:
        return None

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        return None

    user_id = payload.get("sub")
    if user_id is None:
        return None

    user = get_user_by_id(db, int(user_id))
    if user and not user.is_active:
        return None
    return user


def require_tier(min_tier: str):
    """Create a dependency that requires a minimum membership tier.

    Usage:
        @router.get("/api/pro-feature")
        async def pro_feature(user=Depends(require_tier("pro"))):
            ...
    """
    def _check(user=Depends(get_current_user)):
        if not check_membership_permission(user.membership_tier, min_tier):
            tier_names = {"free": "免费版", "basic": "基础版", "pro": "专业版", "max": "旗舰版"}
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要 {} 或更高级别会员".format(tier_names.get(min_tier, min_tier)),
            )
        return user
    return _check
