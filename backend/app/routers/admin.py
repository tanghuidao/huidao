"""Admin panel API router."""
import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import get_db
from app.services.middleware import get_current_user
from app.models import User, Membership, Payment, Article, Source, Briefing, Alert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(user=Depends(get_current_user)):
    """Require admin or max tier user."""
    if not user.is_admin and user.membership_tier != "max":
        raise HTTPException(status_code=403, detail="\u65e0\u6743\u8bbf\u95ee\u7ba1\u7406\u540e\u53f0")
    return user


# --- Dashboard Overview ---

@router.get("/overview")
def admin_overview(admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Get admin dashboard overview stats."""
    now = datetime.datetime.utcnow()
    today_start = datetime.datetime.combine(now.date(), datetime.time.min)
    week_start = today_start - datetime.timedelta(days=7)
    month_start = today_start - datetime.timedelta(days=30)

    # User stats
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()
    new_users_today = db.query(User).filter(User.created_at >= today_start).count()
    new_users_week = db.query(User).filter(User.created_at >= week_start).count()
    new_users_month = db.query(User).filter(User.created_at >= month_start).count()

    # Tier distribution
    tier_dist = db.query(
        User.membership_tier, func.count(User.id)
    ).group_by(User.membership_tier).all()
    tier_distribution = {tier: count for tier, count in tier_dist}

    # Trial users
    trial_users = db.query(User).filter(
        User.membership_tier == "pro",
        User.membership_expires_at.isnot(None),
        User.membership_expires_at > now,
    ).count()

    # Content stats
    total_articles = db.query(Article).count()
    articles_today = db.query(Article).filter(Article.fetched_at >= today_start).count()
    total_sources = db.query(Source).count()
    healthy_sources = db.query(Source).filter(Source.health_status == "healthy").count()
    total_briefings = db.query(Briefing).count()

    # Revenue stats
    total_revenue = db.query(func.sum(Payment.amount)).filter(
        Payment.status == "completed"
    ).scalar() or 0
    completed_orders = db.query(Payment).filter(Payment.status == "completed").count()
    pending_orders = db.query(Payment).filter(Payment.status == "pending").count()

    # Alert stats
    active_alerts = db.query(Alert).filter(Alert.status == "active").count()

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "new_today": new_users_today,
            "new_week": new_users_week,
            "new_month": new_users_month,
            "tier_distribution": tier_distribution,
            "on_trial": trial_users,
        },
        "content": {
            "total_articles": total_articles,
            "articles_today": articles_today,
            "total_sources": total_sources,
            "healthy_sources": healthy_sources,
            "total_briefings": total_briefings,
        },
        "revenue": {
            "total_revenue": total_revenue,
            "completed_orders": completed_orders,
            "pending_orders": pending_orders,
        },
        "alerts": {
            "active": active_alerts,
        },
    }


# --- User Management ---

@router.get("/users")
def admin_list_users(
    page: int = 1, per_page: int = 20, search: str = "",
    tier: str = "", admin=Depends(require_admin), db: Session = Depends(get_db),
):
    """List all users with pagination and filtering."""
    q = db.query(User)
    if search:
        q = q.filter(
            (User.email.ilike(f"%{search}%")) | (User.display_name.ilike(f"%{search}%"))
        )
    if tier:
        q = q.filter(User.membership_tier == tier)

    total = q.count()
    users = q.order_by(desc(User.created_at)).offset((page-1)*per_page).limit(per_page).all()

    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "membership_tier": u.membership_tier,
                "is_active": u.is_active,
                "is_admin": u.is_admin,
                "email_verified": u.email_verified,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                "membership_expires_at": u.membership_expires_at.isoformat() if u.membership_expires_at else None,
                "trial_info": _get_trial_info(u),
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/users/{user_id}")
def admin_get_user(user_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Get detailed user info."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="\u7528\u6237\u4e0d\u5b58\u5728")

    # Get membership history
    memberships = db.query(Membership).filter(
        Membership.user_id == user_id
    ).order_by(desc(Membership.created_at)).all()

    # Get payment history
    payments = db.query(Payment).filter(
        Payment.user_id == user_id
    ).order_by(desc(Payment.created_at)).all()

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "membership_tier": user.membership_tier,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "email_verified": user.email_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "membership_expires_at": user.membership_expires_at.isoformat() if user.membership_expires_at else None,
            "extra_data": user.extra_data,
            "trial_info": _get_trial_info(user),
        },
        "memberships": [
            {
                "id": m.id, "tier": m.tier, "status": m.status,
                "started_at": str(m.started_at), "expires_at": str(m.expires_at) if m.expires_at else None,
            }
            for m in memberships
        ],
        "payments": [
            {
                "id": p.id, "order_id": p.order_id, "tier": p.tier,
                "amount": p.amount, "status": p.status, "payment_method": p.payment_method,
                "paid_at": str(p.paid_at) if p.paid_at else None,
                "created_at": str(p.created_at) if p.created_at else None,
            }
            for p in payments
        ],
    }


@router.post("/users/{user_id}/toggle-active")
def admin_toggle_user(user_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Toggle user active status."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="\u7528\u6237\u4e0d\u5b58\u5728")
    user.is_active = not user.is_active
    db.commit()
    return {"success": True, "user_id": user_id, "is_active": user.is_active}


@router.post("/users/{user_id}/set-tier")
def admin_set_tier(
    user_id: int, tier: str, days: int = 365,
    admin=Depends(require_admin), db: Session = Depends(get_db),
):
    """Set user's membership tier."""
    if tier not in ("free", "basic", "pro", "max"):
        raise HTTPException(status_code=400, detail="\u65e0\u6548\u7684\u4f1a\u5458\u7b49\u7ea7")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="\u7528\u6237\u4e0d\u5b58\u5728")

    now = datetime.datetime.utcnow()
    expires = now + datetime.timedelta(days=days) if tier != "free" else None

    # Deactivate old memberships
    old = db.query(Membership).filter(
        Membership.user_id == user_id,
        Membership.status.in_(["active", "trial"]),
    ).all()
    for m in old:
        m.status = "upgraded"

    # Create new membership
    membership = Membership(
        user_id=user_id, tier=tier, status="active",
        started_at=now, expires_at=expires,
    )
    db.add(membership)
    user.membership_tier = tier
    user.membership_expires_at = expires
    db.commit()

    return {"success": True, "user_id": user_id, "tier": tier, "expires_at": str(expires) if expires else None}


# --- Order Management ---

@router.get("/orders")
def admin_list_orders(
    page: int = 1, per_page: int = 20, status: str = "",
    admin=Depends(require_admin), db: Session = Depends(get_db),
):
    """List all orders."""
    q = db.query(Payment).join(User, Payment.user_id == User.id)
    if status:
        q = q.filter(Payment.status == status)

    total = q.count()
    orders = q.order_by(desc(Payment.created_at)).offset((page-1)*per_page).limit(per_page).all()

    return {
        "orders": [
            {
                "id": o.id,
                "order_id": o.order_id,
                "user_id": o.user_id,
                "user_email": o.user.email if o.user else "unknown",
                "tier": o.tier,
                "amount": o.amount,
                "payment_method": o.payment_method,
                "status": o.status,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/orders/{order_id}/complete")
def admin_complete_order(
    order_id: str, admin=Depends(require_admin), db: Session = Depends(get_db),
):
    """Manually complete an order and activate membership."""
    order = db.query(Payment).filter(Payment.order_id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="\u8ba2\u5355\u4e0d\u5b58\u5728")
    if order.status == "completed":
        raise HTTPException(status_code=400, detail="\u8ba2\u5355\u5df2\u5b8c\u6210")

    order.status = "completed"
    order.paid_at = datetime.datetime.utcnow()
    order.payment_proof = "admin_manual"

    from app.services.payment_service import activate_membership
    extra = order.extra_data or {}
    result = activate_membership(db, order.user_id, order.tier, extra.get("period", "yearly"))

    return {"success": True, "order_id": order_id, "result": result}


@router.post("/orders/{order_id}/cancel")
def admin_cancel_order(
    order_id: str, admin=Depends(require_admin), db: Session = Depends(get_db),
):
    """Cancel an order."""
    order = db.query(Payment).filter(Payment.order_id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="\u8ba2\u5355\u4e0d\u5b58\u5728")
    order.status = "cancelled"
    db.commit()
    return {"success": True, "order_id": order_id, "status": "cancelled"}


def _get_trial_info(user):
    """Extract trial info from user extra_data."""
    extra = user.extra_data or {}
    if not extra.get("trial_used"):
        return {"used": False}
    return {
        "used": True,
        "started_at": extra.get("trial_started_at"),
        "ends_at": extra.get("trial_ends_at"),
        "downgraded": bool(extra.get("trial_downgraded_at")),
        "converted": bool(extra.get("upgraded_from_trial")),
    }
