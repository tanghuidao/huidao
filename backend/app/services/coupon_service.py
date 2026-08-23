"""Coupon management service."""
import datetime
import logging
import string
import random

from sqlalchemy.orm import Session
from app.models import Coupon

logger = logging.getLogger(__name__)


def generate_code(length=8):
    """Generate a random coupon code."""
    chars = string.ascii_uppercase + string.digits
    prefix = random.choice(["HD", "SV", "VIP", "PRO", "MAX", "NEW"])
    suffix = "".join(random.choices(chars, k=length))
    return f"{prefix}-{suffix}"


def create_coupon(db, name, discount_type, discount_value,
                  description="", applicable_tiers=None, max_uses=None,
                  expires_days=None, code=None, created_by=None):
    """Create a new coupon."""
    coupon_code = (code or generate_code()).upper()

    existing = db.query(Coupon).filter(Coupon.code == coupon_code).first()
    if existing:
        return {"error": f"Coupon code {coupon_code} already exists"}

    expires_at = None
    if expires_days:
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=expires_days)

    coupon = Coupon(
        code=coupon_code,
        name=name,
        description=description,
        discount_type=discount_type,
        discount_value=discount_value,
        applicable_tiers=applicable_tiers,
        max_uses=max_uses,
        expires_at=expires_at,
        created_by=created_by,
    )
    db.add(coupon)
    db.commit()
    logger.info(f"Coupon created: {coupon_code} ({discount_type}={discount_value})")
    return _coupon_to_dict(coupon)


def get_coupon(db, code):
    """Get coupon by code."""
    coupon = db.query(Coupon).filter(Coupon.code == code.upper()).first()
    return _coupon_to_dict(coupon) if coupon else None


def list_coupons(db, active_only=False, limit=50):
    """List all coupons."""
    q = db.query(Coupon)
    if active_only:
        q = q.filter(Coupon.is_active == True)
    coupons = q.order_by(Coupon.created_at.desc()).limit(limit).all()
    return [_coupon_to_dict(c) for c in coupons]


def update_coupon(db, code, **kwargs):
    """Update coupon fields."""
    coupon = db.query(Coupon).filter(Coupon.code == code.upper()).first()
    if not coupon:
        return {"error": "Coupon not found"}
    for key, value in kwargs.items():
        if hasattr(coupon, key) and key not in ("id", "code", "created_at"):
            setattr(coupon, key, value)
    db.commit()
    return _coupon_to_dict(coupon)


def deactivate_coupon(db, code):
    """Deactivate a coupon."""
    return update_coupon(db, code, is_active=False)


def delete_coupon(db, code):
    """Delete a coupon permanently."""
    coupon = db.query(Coupon).filter(Coupon.code == code.upper()).first()
    if not coupon:
        return {"error": "Coupon not found"}
    db.delete(coupon)
    db.commit()
    return {"success": True, "code": code}


def batch_create_coupons(db, count, prefix, discount_type, discount_value,
                         applicable_tiers=None, max_uses=None, expires_days=None):
    """Batch create coupons with a common prefix."""
    created = []
    for i in range(count):
        code = f"{prefix}{i+1:03d}"
        result = create_coupon(
            db, name=f"Batch {prefix} #{i+1}",
            discount_type=discount_type,
            discount_value=discount_value,
            applicable_tiers=applicable_tiers,
            max_uses=max_uses,
            expires_days=expires_days,
            code=code,
        )
        if "error" not in result:
            created.append(result)
    return {"created": len(created), "coupons": created}


def validate_coupon(db, code, tier=None):
    """Validate a coupon for use."""
    coupon = db.query(Coupon).filter(Coupon.code == code.upper()).first()
    if not coupon:
        return {"valid": False, "error": "\u65e0\u6548\u7684\u4f18\u60e0\u7801"}

    if not coupon.is_active:
        return {"valid": False, "error": "\u4f18\u60e0\u7801\u5df2\u505c\u7528"}

    now = datetime.datetime.utcnow()
    if coupon.expires_at and coupon.expires_at < now:
        return {"valid": False, "error": "\u4f18\u60e0\u7801\u5df2\u8fc7\u671f"}

    if coupon.max_uses and coupon.used_count >= coupon.max_uses:
        return {"valid": False, "error": "\u4f18\u60e0\u7801\u5df2\u7528\u5b8c"}

    if tier and coupon.applicable_tiers and tier not in coupon.applicable_tiers:
        tier_names = {"basic": "\u57fa\u7840\u7248", "pro": "\u4e13\u4e1a\u7248", "max": "\u65d7\u8230\u7248"}
        allowed = ", ".join(tier_names.get(t, t) for t in coupon.applicable_tiers)
        return {"valid": False, "error": f"\u4f18\u60e0\u7801\u4ec5\u9002\u7528\u4e8e: {allowed}"}

    return {
        "valid": True,
        "code": coupon.code,
        "name": coupon.name,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
    }


def _coupon_to_dict(coupon):
    """Convert Coupon ORM object to dict."""
    return {
        "id": coupon.id,
        "code": coupon.code,
        "name": coupon.name,
        "description": coupon.description,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "applicable_tiers": coupon.applicable_tiers,
        "max_uses": coupon.max_uses,
        "used_count": coupon.used_count,
        "is_active": coupon.is_active,
        "created_at": coupon.created_at.isoformat() if coupon.created_at else None,
        "expires_at": coupon.expires_at.isoformat() if coupon.expires_at else None,
    }
