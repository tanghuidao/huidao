"""Membership management API router."""
import logging
import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.middleware import get_current_user, require_tier
from app.services.auth import get_tier_limits

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/membership", tags=["membership"])


# --- Schemas ---

class PlanInfo(BaseModel):
    tier: str
    name: str
    price_monthly: int  # CNY per month
    price_quarterly: int  # CNY per quarter
    price_yearly: int  # CNY per year, 0 for free
    features: list[str]
    limits: dict


class SubscribeRequest(BaseModel):
    tier: str  # "pro" or "max"
    payment_method: str = "alipay"  # alipay, wechat, stripe


class PaymentVerifyRequest(BaseModel):
    order_id: str
    payment_proof: str = ""  # transaction ID or proof


class MembershipStatusResponse(BaseModel):
    tier: str
    tier_name: str
    status: str
    started_at: Optional[str] = None
    expires_at: Optional[str] = None
    limits: dict


# --- Plan Definitions ---

PLANS = {
    "free": {
        "tier": "free",
        "name": "免费版",
        "price_monthly": 0,
        "price_quarterly": 0,
        "price_yearly": 0,
        "features": [
            "每日5篇文章浏览",
            "基础统计信息",
            "延迟1天AI简报",
            "7天历史数据",
        ],
        "limits": get_tier_limits("free"),
    },
    "basic": {
        "tier": "basic",
        "name": "基础版",
        "price_monthly": 19,
        "price_quarterly": 49,
        "price_yearly": 188,
        "features": [
            "全部文章阅读",
            "AI 分类 / 标签",
            "趋势图表",
            "关注列表",
        ],
        "limits": get_tier_limits("basic"),
    },
    "pro": {
        "tier": "pro",
        "name": "专业版",
        "price_monthly": 49,
        "price_quarterly": 125,
        "price_yearly": 468,
        "features": [
            "基础版全部功能",
            "AI 实时简报",
            "叙事强度指数",
            "风险预警推送",
            "周报推送",
            "Agent任务（最多5个）",
        ],
        "limits": get_tier_limits("pro"),
    },
    "max": {
        "tier": "max",
        "name": "旗舰版",
        "price_monthly": 129,
        "price_quarterly": 329,
        "price_yearly": 1228,
        "features": [
            "专业版全部功能",
            "深度研究报告",
            "API 接口（1000次/月）",
            "数据导出 CSV/PDF",
            "无限关注列表",
            "无限Agent任务",
            "会员专属社群",
            "专属客服支持",
        ],
        "limits": get_tier_limits("max"),
    },
}

TIER_NAMES = {"free": "免费版", "basic": "基础版", "pro": "专业版", "max": "旗舰版"}


# --- Endpoints ---

@router.get("/plans", response_model=list[PlanInfo])
async def api_list_plans():
    """List all available membership plans."""
    return list(PLANS.values())


@router.get("/status")
async def api_membership_status(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current membership status with trial info."""
    from app.services.trial import get_trial_status
    from app.models import Membership
    membership = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.status.in_(["active", "trial"]),
    ).first()

    tier_name = TIER_NAMES.get(user.membership_tier, "免费版")
    limits = get_tier_limits(user.membership_tier)

    trial_info = get_trial_status(user)

    return {
        "tier": user.membership_tier,
        "tier_name": tier_name,
        "status": membership.status if membership else "inactive",
        "started_at": str(membership.started_at) if membership and membership.started_at else None,
        "expires_at": str(membership.expires_at) if membership and membership.expires_at else None,
        "limits": limits,
        "trial": trial_info,
    }


@router.post("/subscribe")
async def api_subscribe(
    req: SubscribeRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Initiate a subscription upgrade.

    In production, this would integrate with a payment gateway.
    Currently creates a pending payment order.
    """
    if req.tier not in ("basic", "pro", "max"):
        raise HTTPException(status_code=400, detail="无效的会员等级")

    plan = PLANS[req.tier]

    # Check if already at this tier or higher
    tier_levels = {"free": 0, "basic": 1, "pro": 2, "max": 3}
    if tier_levels.get(user.membership_tier, 0) >= tier_levels[req.tier]:
        raise HTTPException(status_code=400, detail="当前已是该等级或更高级别")

    # Create payment order
    from app.models import Payment
    import uuid

    order_id = "PAY-" + uuid.uuid4().hex[:12].upper()
    payment = Payment(
        user_id=user.id,
        order_id=order_id,
        tier=req.tier,
        amount=plan["price_yearly"],  # annual subscription
        payment_method=req.payment_method,
        status="pending",
    )
    db.add(payment)
    db.commit()

    logger.info(f"Subscription order created: {order_id} for user {user.id}, tier={req.tier}")

    return {
        "order_id": order_id,
        "amount": plan["price_yearly"],
        "tier": req.tier,
        "tier_name": plan["name"],
        "payment_method": req.payment_method,
        "message": "订单已创建。请使用{}支付 {} 元。支付完成后请联系管理员确认或使用支付验证接口。".format(
            "支付宝" if req.payment_method == "alipay" else "微信",
            plan["price_yearly"],
        ),
    }


@router.post("/verify-payment")
async def api_verify_payment(
    req: PaymentVerifyRequest,
    db: Session = Depends(get_db),
):
    """Verify a payment and activate membership.

    In production, this would verify with the payment gateway.
    Currently supports admin verification flow.
    """
    from app.models import Payment

    payment = db.query(Payment).filter(Payment.order_id == req.order_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="订单不存在")

    if payment.status == "completed":
        raise HTTPException(status_code=400, detail="该订单已完成")

    if payment.status == "cancelled":
        raise HTTPException(status_code=400, detail="该订单已取消")

    # Mark payment as completed
    payment.status = "completed"
    payment.paid_at = datetime.datetime.utcnow()
    payment.payment_proof = req.payment_proof or "manual_verification"

    # Activate membership
    from app.models import User, Membership
    user = db.query(User).filter(User.id == payment.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # Deactivate old membership
    old_memberships = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.status.in_(["active", "trial"]),
    ).all()
    for m in old_memberships:
        m.status = "upgraded"

    # Create new membership
    now = datetime.datetime.utcnow()
    membership = Membership(
        user_id=user.id,
        tier=payment.tier,
        status="active",
        started_at=now,
        expires_at=now + datetime.timedelta(days=365),
    )
    db.add(membership)

    # Update user tier
    user.membership_tier = payment.tier
    user.membership_expires_at = now + datetime.timedelta(days=365)

    db.commit()

    tier_name = TIER_NAMES.get(payment.tier, payment.tier)
    logger.info(f"Membership activated: user={user.id}, tier={payment.tier}")

    return {
        "message": "会员已激活成功！",
        "tier": payment.tier,
        "tier_name": tier_name,
        "expires_at": str(membership.expires_at),
    }


@router.post("/admin/activate")
async def api_admin_activate(
    user_id: int,
    tier: str,
    days: int = 365,
    admin=Depends(require_tier("max")),
    db: Session = Depends(get_db),
):
    """Admin endpoint to activate membership for a user.

    Only Max tier users (admin) can use this.
    """
    if tier not in ("basic", "pro", "max"):
        raise HTTPException(status_code=400, detail="无效的会员等级")

    from app.models import User, Membership

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    # Deactivate old memberships
    old = db.query(Membership).filter(
        Membership.user_id == user_id,
        Membership.status.in_(["active", "trial"]),
    ).all()
    for m in old:
        m.status = "upgraded"

    now = datetime.datetime.utcnow()
    membership = Membership(
        user_id=user_id,
        tier=tier,
        status="active",
        started_at=now,
        expires_at=now + datetime.timedelta(days=days),
    )
    db.add(membership)

    target_user.membership_tier = tier
    target_user.membership_expires_at = now + datetime.timedelta(days=days)
    db.commit()

    tier_name = TIER_NAMES.get(tier, tier)
    return {
        "message": "用户 {} 已升级为 {}".format(target_user.email, tier_name),
        "user_id": user_id,
        "tier": tier,
        "expires_at": str(membership.expires_at),
    }
