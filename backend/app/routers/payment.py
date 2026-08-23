"""Payment API router - order management and payment callbacks."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment", tags=["payment"])


class CreateOrderRequest(BaseModel):
    tier: str  # basic, pro, max
    period: str = "yearly"  # monthly, quarterly, yearly
    payment_method: str = "alipay"  # alipay, wechat, stripe
    coupon_code: Optional[str] = None


class CancelOrderRequest(BaseModel):
    order_id: str


# --- Order Management ---

@router.post("/orders")
async def create_order(
    req: CreateOrderRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new payment order."""
    from app.services.payment_service import create_order as _create

    result = _create(
        db, user,
        tier=req.tier,
        period=req.period,
        payment_method=req.payment_method,
        coupon_code=req.coupon_code,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Generate payment instructions based on method
    if req.payment_method == "alipay":
        result["payment_url"] = f"https://huidao.cc/pay/alipay?order_id={result['order_id']}"
        result["instructions"] = "\u8bf7\u4f7f\u7528\u652f\u4ed8\u5b9d\u626b\u63cf\u4e8c\u7ef4\u7801\u6216\u70b9\u51fb\u94fe\u63a5\u5b8c\u6210\u652f\u4ed8"
    elif req.payment_method == "wechat":
        result["payment_url"] = f"https://huidao.cc/pay/wechat?order_id={result['order_id']}"
        result["instructions"] = "\u8bf7\u4f7f\u7528\u5fae\u4fe1\u626b\u4e00\u626b\u5b8c\u6210\u652f\u4ed8"
    else:
        result["payment_url"] = f"https://huidao.cc/pay/stripe?order_id={result['order_id']}"
        result["instructions"] = "Please complete payment via the link"

    return result


@router.get("/orders")
async def list_orders(
    limit: int = 20,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List user's payment orders."""
    from app.services.payment_service import get_user_orders
    orders = get_user_orders(db, user.id, limit=limit)
    return {"orders": orders, "count": len(orders)}


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get order detail."""
    from app.services.payment_service import get_order_detail
    order = get_order_detail(db, order_id, user.id)
    if not order:
        raise HTTPException(status_code=404, detail="\u8ba2\u5355\u4e0d\u5b58\u5728")
    return order


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending order."""
    from app.services.payment_service import cancel_order as _cancel
    result = _cancel(db, order_id, user.id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# --- Payment Callbacks ---

@router.post("/callback/alipay")
async def alipay_callback(request: Request, db: Session = Depends(get_db)):
    """Alipay payment callback endpoint."""
    form = await request.form()
    params = dict(form)

    logger.info(f"Alipay callback received: order={params.get('out_trade_no')}")

    from app.services.payment_callbacks import process_alipay_callback
    result = process_alipay_callback(db, params)

    if result.get("success"):
        return "success"  # Alipay expects plain "success" string
    else:
        logger.error(f"Alipay callback failed: {result}")
        return "fail"


@router.post("/callback/wechat")
async def wechat_callback(request: Request, db: Session = Depends(get_db)):
    """WeChat Pay callback endpoint."""
    body = await request.json()
    headers = dict(request.headers)

    logger.info(f"WeChat callback received: order={body.get('out_trade_no')}")

    from app.services.payment_callbacks import process_wechat_callback
    result = process_wechat_callback(db, headers, body)

    if result.get("success"):
        return {"code": "SUCCESS", "message": "\u6210\u529f"}
    else:
        logger.error(f"WeChat callback failed: {result}")
        return {"code": "FAIL", "message": result.get("error", "\u5931\u8d25")}


# --- Payment Status Check (for frontend polling) ---

@router.get("/status/{order_id}")
async def check_payment_status(
    order_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check payment status (for frontend polling)."""
    from app.services.payment_service import get_order_detail
    order = get_order_detail(db, order_id, user.id)
    if not order:
        raise HTTPException(status_code=404, detail="\u8ba2\u5355\u4e0d\u5b58\u5728")
    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "amount": order["amount"],
        "tier": order["tier"],
    }


# --- Coupon Management ---

class ValidateCouponRequest(BaseModel):
    code: str
    tier: Optional[str] = None


class CreateCouponRequest(BaseModel):
    name: str
    discount_type: str  # percent, fixed
    discount_value: float
    description: str = ""
    applicable_tiers: Optional[list] = None
    max_uses: Optional[int] = None
    expires_days: Optional[int] = None
    code: Optional[str] = None


class BatchCouponRequest(BaseModel):
    count: int
    prefix: str
    discount_type: str
    discount_value: float
    applicable_tiers: Optional[list] = None
    max_uses: Optional[int] = None
    expires_days: Optional[int] = None


@router.post("/coupon/validate")
async def validate_coupon_api(
    req: ValidateCouponRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate a coupon code before checkout."""
    from app.services.coupon_service import validate_coupon as _validate
    return _validate(db, req.code, tier=req.tier)


@router.post("/admin/coupons")
async def admin_create_coupon(
    req: CreateCouponRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new coupon (admin only)."""
    if not user.is_admin and user.membership_tier != "max":
        raise HTTPException(status_code=403, detail="\u65e0\u6743\u64cd\u4f5c")

    from app.services.coupon_service import create_coupon
    result = create_coupon(
        db, name=req.name, discount_type=req.discount_type,
        discount_value=req.discount_value, description=req.description,
        applicable_tiers=req.applicable_tiers, max_uses=req.max_uses,
        expires_days=req.expires_days, code=req.code, created_by=user.id,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/admin/coupons")
async def admin_list_coupons(
    active_only: bool = False, limit: int = 50,
    user=Depends(get_current_user), db: Session = Depends(get_db),
):
    """List all coupons (admin only)."""
    if not user.is_admin and user.membership_tier != "max":
        raise HTTPException(status_code=403, detail="\u65e0\u6743\u64cd\u4f5c")
    from app.services.coupon_service import list_coupons
    coupons = list_coupons(db, active_only=active_only, limit=limit)
    return {"coupons": coupons, "count": len(coupons)}


@router.post("/admin/coupons/batch")
async def admin_batch_create(
    req: BatchCouponRequest,
    user=Depends(get_current_user), db: Session = Depends(get_db),
):
    """Batch create coupons (admin only)."""
    if not user.is_admin and user.membership_tier != "max":
        raise HTTPException(status_code=403, detail="\u65e0\u6743\u64cd\u4f5c")
    from app.services.coupon_service import batch_create_coupons
    return batch_create_coupons(
        db, count=req.count, prefix=req.prefix,
        discount_type=req.discount_type, discount_value=req.discount_value,
        applicable_tiers=req.applicable_tiers, max_uses=req.max_uses,
        expires_days=req.expires_days,
    )


@router.delete("/admin/coupons/{code}")
async def admin_delete_coupon(
    code: str, user=Depends(get_current_user), db: Session = Depends(get_db),
):
    """Delete a coupon (admin only)."""
    if not user.is_admin and user.membership_tier != "max":
        raise HTTPException(status_code=403, detail="\u65e0\u6743\u64cd\u4f5c")
    from app.services.coupon_service import delete_coupon
    result = delete_coupon(db, code)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.patch("/admin/coupons/{code}/deactivate")
async def admin_deactivate_coupon(
    code: str, user=Depends(get_current_user), db: Session = Depends(get_db),
):
    """Deactivate a coupon (admin only)."""
    if not user.is_admin and user.membership_tier != "max":
        raise HTTPException(status_code=403, detail="\u65e0\u6743\u64cd\u4f5c")
    from app.services.coupon_service import deactivate_coupon
    result = deactivate_coupon(db, code)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# --- Data Export (Max tier) ---

@router.get("/export/profile")
async def export_profile(
    format: str = "json",
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export user profile data (Max tier only)."""
    from app.services.data_export import export_user_data
    data = export_user_data(db, user.id)
    if "error" in data:
        raise HTTPException(status_code=403, detail=data["error"])

    if format == "json":
        from fastapi.responses import JSONResponse
        return JSONResponse(content=data, headers={
            "Content-Disposition": f"attachment; filename=huidao_profile_{user.id}.json"
        })
    return data


@router.get("/export/articles")
async def export_articles(
    format: str = "csv",
    days: int = 30,
    limit: int = 1000,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export articles data (Max tier only)."""
    if user.membership_tier != "max":
        raise HTTPException(status_code=403, detail="\u4ec5\u65d7\u8230\u7248\u4f1a\u5458\u53ef\u5bfc\u51fa\u6570\u636e")

    from app.services.data_export import export_articles_csv, export_articles_json
    from fastapi.responses import Response

    if format == "json":
        data = export_articles_json(db, days=days, limit=limit)
        return Response(
            content=data,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=huidao_articles_{days}d.json"}
        )
    else:
        data = export_articles_csv(db, days=days, limit=limit)
        return Response(
            content=data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=huidao_articles_{days}d.csv"}
        )
