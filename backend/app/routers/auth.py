"""Authentication API router with 4B-1 security enhancements."""
import logging
import datetime
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.auth import (
    register_user, authenticate_user, create_access_token,
    get_user_by_id, hash_password, verify_password, is_valid_email,
    activate_user_trial,
)
from app.services.middleware import get_current_user

# Captcha imports (Tencent 天御验证码)
from app.services.captcha import verify_captcha
from app.services.email_verify import (
    generate_verification_token, send_verification_email,
    check_resend_cooldown, is_token_expired,
)
from app.services.rate_limiter import record_login_failure, check_login_blocked

import os
import secrets
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

TENCENT_CAPTCHA_APP_ID = os.getenv("TENCENT_CAPTCHA_APP_ID", "")

# Redis for password reset tokens (persistent across restarts)
REDIS_URL = "redis://huidao_redis:6379/0"
RESET_TOKEN_EXPIRY_MINUTES = 30


def _get_redis():
    """Get async redis connection."""
    import redis.asyncio as aioredis
    return aioredis.from_url(REDIS_URL, decode_responses=True)


# --- Request/Response Schemas ---

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""
    captcha_ticket: Optional[str] = None
    captcha_randstr: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    membership_tier: str
    is_active: bool
    created_at: str
    membership_expires_at: Optional[str] = None
    email_verified: bool = True


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ResendVerificationRequest(BaseModel):
    email: str


# --- Endpoints ---

@router.post("/register", response_model=TokenResponse)
async def api_register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Register a new user account."""
    # Input validation
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少需要6位")
    if not is_valid_email(req.email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    # Tencent Captcha verification
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.client.host if request.client else "")
    rc = await verify_captcha(req.captcha_ticket or "", req.captcha_randstr or "", user_ip=client_ip)
    if not rc["success"]:
        logger.warning(f"Captcha blocked {req.email}: {rc['error']}")
        raise HTTPException(status_code=403, detail="人机验证未通过，请重试")

    user, error = register_user(db, req.email, req.password, req.display_name)
    if error:
        raise HTTPException(status_code=400, detail=error)

    # Generate verification token and send email
    vtoken = generate_verification_token()
    user.verification_token = vtoken
    user.verification_sent_at = datetime.datetime.now(datetime.timezone.utc)
    user.email_verified = False
    db.commit()

    email_result = await send_verification_email(
        to_email=user.email, token=vtoken, display_name=user.display_name,
    )
    if not email_result["success"]:
        logger.error(f"Verification email failed for {user.email}: {email_result['error']}")

    token = create_access_token({"sub": str(user.id), "email": user.email})
    logger.info(f"User registered: {user.email} (recaptcha={rc.get('score', 'N/A')}, tier=free pending verify)")
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def api_login(req: LoginRequest, db: Session = Depends(get_db)):
    """Login with email and password."""
    # Check if account is locked
    if await check_login_blocked(req.email):
        raise HTTPException(status_code=429, detail="登录失败次数过多，请5分钟后再试")

    user = authenticate_user(db, req.email, req.password)
    if not user:
        await record_login_failure(req.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    token = create_access_token({"sub": str(user.id), "email": user.email})
    logger.info(f"User logged in: {user.email}")
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def api_get_me(user=Depends(get_current_user)):
    """Get current user profile."""
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        membership_tier=user.membership_tier,
        is_active=user.is_active,
        created_at=str(user.created_at) if user.created_at else None,
        membership_expires_at=str(user.membership_expires_at) if user.membership_expires_at else None,
        email_verified=getattr(user, "email_verified", True),
    )


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None

@router.patch("/me")
async def api_update_profile(
    req: UpdateProfileRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current user profile."""
    if req.display_name is not None:
        if len(req.display_name) > 50:
            raise HTTPException(status_code=400, detail="昵称过长")
        user.display_name = req.display_name
    db.commit()
    db.refresh(user)
    logger.info(f"Profile updated: {user.email}")
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "membership_tier": user.membership_tier,
        "is_active": user.is_active,
        "created_at": str(user.created_at) if user.created_at else None,
        "membership_expires_at": str(user.membership_expires_at) if user.membership_expires_at else None,
        "email_verified": getattr(user, "email_verified", True),
    }

@router.post("/change-password")
async def api_change_password(
    req: ChangePasswordRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change current user's password."""
    if not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少需要6位")
    user.hashed_password = hash_password(req.new_password)
    db.commit()
    return {"message": "密码已更新"}


@router.post("/refresh", response_model=TokenResponse)
async def api_refresh_token(user=Depends(get_current_user)):
    """Refresh the JWT token."""
    token = create_access_token({"sub": str(user.id), "email": user.email})
    return TokenResponse(access_token=token)


# --- 4B-1 Email Verification Endpoints ---

@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email(token: str, db: Session = Depends(get_db)):
    """Email verification endpoint. Activates Pro trial upon success."""
    from app.models import User
    user = db.query(User).filter(User.verification_token == token).first()

    if not user:
        return _verify_page("验证失败", "验证链接无效或已被使用。", "error")

    if is_token_expired(user.verification_sent_at):
        return _verify_page("链接已过期", "验证链接已过期（24小时有效）。请登录后重新发送。", "expired")

    if user.email_verified:
        return _verify_page("已验证", "你的邮箱已验证过，无需重复操作。", "success")

    # Mark as verified
    user.email_verified = True
    user.verification_token = None
    user.verification_sent_at = None
    db.commit()

    # Activate 7-day Pro trial after verification
    activate_user_trial(user, db)

    logger.info(f"Email verified + trial activated: {user.email}")
    return _verify_page("验证成功", f"邮箱 {user.email} 已成功验证！已为你激活 7 天 Pro 会员试用。", "success")


@router.post("/resend-verification")
async def resend_verification(req: ResendVerificationRequest, db: Session = Depends(get_db)):
    """Resend verification email (60s cooldown)."""
    from app.models import User
    user = db.query(User).filter(User.email == req.email).first()

    if not user:
        return {"message": "如果该邮箱已注册，验证邮件已重新发送。"}
    if user.email_verified:
        return {"message": "该邮箱已验证，无需重复操作。"}

    can_resend, wait = check_resend_cooldown(user.verification_sent_at)
    if not can_resend:
        raise HTTPException(status_code=429, detail=f"请等待 {wait} 秒后再试")

    new_token = generate_verification_token()
    user.verification_token = new_token
    user.verification_sent_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()

    result = await send_verification_email(to_email=user.email, token=new_token, display_name=user.display_name)
    if result["success"]:
        return {"message": "验证邮件已重新发送，请查收。"}
    else:
        raise HTTPException(status_code=500, detail="邮件发送失败，请稍后重试")


# === Password Reset (Redis-backed tokens) ===

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@router.post("/forgot-password")
async def api_forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Send password reset email with token link."""
    from app.models import User
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        return {"message": "如果该邮箱已注册，重置密码链接已发送"}

    # Generate token and store in Redis with TTL
    token = secrets.token_urlsafe(32)
    try:
        r = _get_redis()
        await r.setex(
            f"reset_token:{token}",
            RESET_TOKEN_EXPIRY_MINUTES * 60,
            req.email,
        )
        await r.aclose()
    except Exception as e:
        logger.error(f"Redis error storing reset token: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")

    # Build reset link
    reset_url = f"https://huidao.cc/static/index.html?reset_token={token}"

    # Send email
    try:
        from app.services.email_verify import send_reset_password_email
        await send_reset_password_email(req.email, reset_url, user.display_name or req.email)
    except Exception as e:
        logger.error(f"Failed to send reset email: {e}")

    logger.info(f"Password reset requested for: {req.email}")
    return {"message": "如果该邮箱已注册，重置密码链接已发送"}

@router.post("/reset-password")
async def api_reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using token from email link."""
    from app.models import User

    # Look up token in Redis
    try:
        r = _get_redis()
        email = await r.get(f"reset_token:{req.token}")
        if not email:
            await r.aclose()
            raise HTTPException(status_code=400, detail="重置链接无效或已过期")

        if len(req.new_password) < 6:
            await r.aclose()
            raise HTTPException(status_code=400, detail="密码至少需要6位")

        user = db.query(User).filter(User.email == email).first()
        if not user:
            await r.aclose()
            raise HTTPException(status_code=400, detail="用户不存在")

        user.hashed_password = hash_password(req.new_password)
        db.commit()

        # Delete token (single use)
        await r.delete(f"reset_token:{req.token}")
        await r.aclose()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")

    logger.info(f"Password reset completed for: {user.email}")
    return {"message": "密码重置成功，请使用新密码登录"}


@router.get("/captcha-config")
async def get_captcha_config():
    """Return Tencent Captcha AppID (public, no secret)."""
    return {"app_id": TENCENT_CAPTCHA_APP_ID}


# --- Admin Bootstrap ---

class AdminBootstrapRequest(BaseModel):
    email: str
    password: str
    display_name: str = "Admin"
    secret_key: str


@router.post("/bootstrap-admin")
async def api_bootstrap_admin(req: AdminBootstrapRequest, db: Session = Depends(get_db)):
    """Bootstrap the first admin user. Protected by secret_key."""
    from app.config import JWT_SECRET_KEY
    from app.models import User, Membership

    if req.secret_key != JWT_SECRET_KEY:
        raise HTTPException(status_code=403, detail="无效的密钥")

    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        existing.is_admin = True
        existing.membership_tier = "max"
        existing.email_verified = True
        db.commit()
        return {"message": f"用户 {req.email} 已升级为管理员+旗舰会员", "id": existing.id}

    user = User(
        email=req.email,
        hashed_password=hash_password(req.password),
        display_name=req.display_name,
        membership_tier="max",
        is_active=True,
        is_admin=True,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    membership = Membership(
        user_id=user.id, tier="max", status="active",
        started_at=datetime.datetime.utcnow(),
    )
    db.add(membership)
    db.commit()

    token = create_access_token({"sub": str(user.id), "email": user.email})
    return {"message": f"管理员 {req.email} 创建成功", "id": user.id, "access_token": token}


# --- Verification HTML ---

def _verify_page(title: str, message: str, status_type: str) -> str:
    colors = {"success": "#22c55e", "error": "#ef4444", "expired": "#f59e0b"}
    icons = {"success": "&#10003;", "error": "&#10007;", "expired": "&#9203;"}
    c = colors.get(status_type, "#64748b")
    i = icons.get(status_type, "&#8226;")
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - huidao.cc</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#e2e8f0;padding:20px}}
.card{{background:#1e293b;border-radius:16px;padding:48px 40px;max-width:440px;width:100%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,.3)}}
.icon{{width:64px;height:64px;border-radius:50%;background:{c}20;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:28px;color:{c};border:2px solid {c}40}}
h1{{font-size:22px;margin-bottom:12px;color:#f1f5f9}}p{{font-size:15px;line-height:1.6;color:#94a3b8;margin-bottom:28px}}
.brand{{color:#60a5fa;font-size:20px;font-weight:700;margin-bottom:32px}}
.btn{{display:inline-block;padding:12px 32px;background:#3b82f6;color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:500}}</style>
</head><body><div class="card"><div class="brand">huidao.cc</div><div class="icon">{i}</div>
<h1>{title}</h1><p>{message}</p><a href="/" class="btn">返回首页</a></div></body></html>"""
