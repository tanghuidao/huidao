"""API key authentication middleware for FastAPI.

The site is fully free and open (CC BY 4.0) — the user authentication and
membership system was removed. Only the admin API key check remains for
protecting source management write endpoints. User-scoped dependencies
below are kept as stubs so legacy monitoring endpoints stay locked (401).
"""
import logging
import os
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def require_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    """Protect administrative write endpoints with a shared API key.

    The key is configured via the ADMIN_API_KEY environment variable.
    If the variable is not set, all protected endpoints are denied (fail-closed).
    """
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected:
        logger.warning("ADMIN_API_KEY is not configured; rejecting admin API request")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理接口未配置密钥，已拒绝访问",
        )
    if not x_api_key or not secrets.compare_digest(str(x_api_key), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或缺少 X-API-Key 请求头",
        )
    return True


def _auth_disabled():
    """User authentication has been removed along with the membership system."""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="站点已免费开放，用户认证体系已停用",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """Legacy user dependency — always 401 (auth system removed)."""
    _auth_disabled()
