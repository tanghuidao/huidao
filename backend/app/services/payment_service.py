"""Payment and order management service."""
import datetime
import logging
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models import User, Membership, Payment

logger = logging.getLogger(__name__)

# Order timeout: 30 minutes
ORDER_TIMEOUT_MINUTES = 30

# Pricing config (matches membership.py PLANS)
PRICING = {
    "basic": {"monthly": 19, "quarterly": 49, "yearly": 188},
    "pro": {"monthly": 49, "quarterly": 125, "yearly": 468},
    "max": {"monthly": 129, "quarterly": 329, "yearly": 1228},
}

TIER_NAMES = {"basic": "\u57fa\u7840\u7248", "pro": "\u4e13\u4e1a\u7248", "max": "\u65d7\u8230\u7248"}
PERIOD_DAYS = {"monthly": 30, "quarterly": 90, "yearly": 365}


def create_order(db, user, tier, period="yearly", payment_method="alipay", coupon_code=None):
    """Create a new payment order.

    Args:
        db: Database session
        user: User object
        tier: Target tier (basic/pro/max)
        period: Subscription period (monthly/quarterly/yearly)
        payment_method: alipay, wechat, or stripe
        coupon_code: Optional coupon code

    Returns:
        dict with order info or error
    """
    if tier not in PRICING:
        return {"error": "\u65e0\u6548\u7684\u4f1a\u5458\u7b49\u7ea7"}

    if period not in PRICING[tier]:
        return {"error": "\u65e0\u6548\u7684\u8ba2\u9605\u5468\u671f"}

    # Check if already at this tier or higher
    tier_levels = {"free": 0, "basic": 1, "pro": 2, "max": 3}
    if tier_levels.get(user.membership_tier, 0) >= tier_levels[tier]:
        return {"error": "\u5f53\u524d\u5df2\u662f\u8be5\u7b49\u7ea7\u6216\u66f4\u9ad8\u7ea7\u522b"}

    amount = PRICING[tier][period]
    discount_info = {}

    # Apply coupon if provided
    if coupon_code:
        coupon_result = _apply_coupon(db, coupon_code, tier, amount)
        if "error" in coupon_result:
            return {"error": coupon_result["error"]}
        amount = coupon_result["final_amount"]
        discount_info = coupon_result

    order_id = "PAY-" + uuid.uuid4().hex[:12].upper()
    now = datetime.datetime.utcnow()

    extra = {"period": period, "original_amount": PRICING[tier][period]}
    if discount_info:
        extra["coupon"] = discount_info

    payment = Payment(
        user_id=user.id,
        order_id=order_id,
        tier=tier,
        amount=amount,
        payment_method=payment_method,
        status="pending",
        extra_data=extra,
    )
    db.add(payment)
    db.commit()

    logger.info(f"Order created: {order_id} user={user.id} tier={tier} period={period} amount={amount}")

    return {
        "order_id": order_id,
        "tier": tier,
        "tier_name": TIER_NAMES.get(tier, tier),
        "period": period,
        "amount": amount,
        "payment_method": payment_method,
        "created_at": now.isoformat(),
        "expires_at": (now + datetime.timedelta(minutes=ORDER_TIMEOUT_MINUTES)).isoformat(),
        "discount": discount_info,
    }


def get_user_orders(db, user_id, limit=20):
    """Get user's order history."""
    orders = db.query(Payment).filter(
        Payment.user_id == user_id
    ).order_by(Payment.created_at.desc()).limit(limit).all()

    return [_order_to_dict(o) for o in orders]


def get_order_detail(db, order_id, user_id=None):
    """Get single order detail."""
    q = db.query(Payment).filter(Payment.order_id == order_id)
    if user_id:
        q = q.filter(Payment.user_id == user_id)
    order = q.first()
    if not order:
        return None
    return _order_to_dict(order)


def cancel_order(db, order_id, user_id):
    """Cancel a pending order."""
    order = db.query(Payment).filter(
        Payment.order_id == order_id,
        Payment.user_id == user_id,
        Payment.status == "pending",
    ).first()
    if not order:
        return {"error": "\u8ba2\u5355\u4e0d\u5b58\u5728\u6216\u5df2\u5904\u7406"}

    order.status = "cancelled"
    db.commit()
    logger.info(f"Order cancelled: {order_id} by user {user_id}")
    return {"success": True, "order_id": order_id, "status": "cancelled"}


def cancel_expired_orders(db):
    """Cancel orders that have been pending for too long. Called by scheduler."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=ORDER_TIMEOUT_MINUTES)

    expired = db.query(Payment).filter(
        Payment.status == "pending",
        Payment.created_at < cutoff,
    ).all()

    count = 0
    for order in expired:
        order.status = "cancelled"
        extra = order.extra_data or {}
        extra["cancelled_reason"] = "timeout"
        extra["cancelled_at"] = datetime.datetime.utcnow().isoformat()
        order.extra_data = extra
        count += 1

    db.commit()
    if count > 0:
        logger.info(f"Cancelled {count} expired orders")
    return count


def activate_membership(db, user_id, tier, period="yearly"):
    """Activate membership after successful payment."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"error": "\u7528\u6237\u4e0d\u5b58\u5728"}

    days = PERIOD_DAYS.get(period, 365)
    now = datetime.datetime.utcnow()

    # Deactivate old memberships
    old = db.query(Membership).filter(
        Membership.user_id == user_id,
        Membership.status.in_(["active", "trial"]),
    ).all()
    for m in old:
        m.status = "upgraded"

    # Create new membership
    membership = Membership(
        user_id=user_id,
        tier=tier,
        status="active",
        started_at=now,
        expires_at=now + datetime.timedelta(days=days),
    )
    db.add(membership)

    user.membership_tier = tier
    user.membership_expires_at = now + datetime.timedelta(days=days)

    # Clear trial data if upgrading from trial
    extra = user.extra_data or {}
    if extra.get("trial_used") and not extra.get("trial_downgraded_at"):
        extra["upgraded_from_trial"] = True
        extra["trial_converted_at"] = now.isoformat()
    user.extra_data = extra

    db.commit()
    logger.info(f"Membership activated: user={user_id} tier={tier} period={period} days={days}")
    return {"success": True, "tier": tier, "expires_at": str(membership.expires_at)}


def _apply_coupon(db, code, tier, amount):
    """Apply coupon code. Returns discount info or error."""
    # Check if coupon table exists (it will be created in coupon system)
    try:
        from app.models import Coupon
    except ImportError:
        return {"error": "\u4f18\u60e0\u5238\u7cfb\u7edf\u6682\u672a\u5f00\u653e"}

    coupon = db.query(Coupon).filter(
        Coupon.code == code.upper(),
        Coupon.is_active == True,
    ).first()

    if not coupon:
        return {"error": "\u65e0\u6548\u7684\u4f18\u60e0\u7801"}

    now = datetime.datetime.utcnow()
    if coupon.expires_at and coupon.expires_at < now:
        return {"error": "\u4f18\u60e0\u7801\u5df2\u8fc7\u671f"}

    if coupon.max_uses and coupon.used_count >= coupon.max_uses:
        return {"error": "\u4f18\u60e0\u7801\u5df2\u7528\u5b8c"}

    # Check tier restriction
    if coupon.applicable_tiers and tier not in coupon.applicable_tiers:
        return {"error": f"\u4f18\u60e0\u7801\u4e0d\u9002\u7528\u4e8e{TIER_NAMES.get(tier, tier)}"}

    # Calculate discount
    if coupon.discount_type == "percent":
        discount = int(amount * coupon.discount_value / 100)
    else:  # fixed
        discount = min(int(coupon.discount_value), amount)

    final = max(0, amount - discount)

    # Record usage
    coupon.used_count = (coupon.used_count or 0) + 1
    db.commit()

    return {
        "code": coupon.code,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "discount_amount": discount,
        "original_amount": amount,
        "final_amount": final,
    }


def _order_to_dict(order):
    """Convert Payment ORM object to dict."""
    return {
        "id": order.id,
        "order_id": order.order_id,
        "tier": order.tier,
        "tier_name": TIER_NAMES.get(order.tier, order.tier),
        "amount": order.amount,
        "payment_method": order.payment_method,
        "status": order.status,
        "period": (order.extra_data or {}).get("period", "yearly"),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }
