"""Payment callback handlers for Alipay and WeChat Pay.

This module provides the framework for payment gateway integration.
In production, replace stub verification with actual API calls.
"""
import hashlib
import hmac
import json
import logging
import datetime

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class AlipayCallback:
    """Alipay payment callback handler."""

    # In production, use Alipay public key for RSA verification
    ALIPAY_PUBLIC_KEY = None  # Set via environment variable

    @staticmethod
    def verify_signature(params: dict) -> bool:
        """Verify Alipay callback signature.

        In production:
        1. Extract sign and sign_type from params
        2. Sort remaining params alphabetically
        3. Concatenate as key=value&key=value
        4. Verify RSA2 signature with Alipay public key
        """
        sign = params.get("sign")
        if not sign:
            logger.warning("Alipay callback missing signature")
            return False

        # TODO: Implement RSA2 verification with Alipay public key
        # For now, log and accept (replace before production)
        logger.info(f"Alipay signature verification (STUB): {sign[:20]}...")
        return True

    @staticmethod
    def extract_order_info(params: dict) -> dict:
        """Extract order information from Alipay callback."""
        return {
            "order_id": params.get("out_trade_no", ""),
            "trade_no": params.get("trade_no", ""),  # Alipay transaction ID
            "amount": float(params.get("total_amount", 0)),
            "status": params.get("trade_status", ""),
            "buyer_id": params.get("buyer_id", ""),
            "paid_at": params.get("gmt_payment", ""),
        }

    @staticmethod
    def is_success(params: dict) -> bool:
        """Check if payment was successful."""
        return params.get("trade_status") in ("TRADE_SUCCESS", "TRADE_FINISHED")


class WechatPayCallback:
    """WeChat Pay callback handler."""

    # In production, use WeChat Pay API v3 key
    WECHAT_API_KEY = None  # Set via environment variable

    @staticmethod
    def verify_signature(headers: dict, body: str) -> bool:
        """Verify WeChat Pay callback signature.

        In production (API v3):
        1. Extract Wechatpay-Timestamp, Wechatpay-Nonce, Wechatpay-Signature from headers
        2. Construct message: timestamp\nnonce\nbody\n
        3. Verify signature with WeChat Pay platform certificate
        """
        signature = headers.get("wechatpay-signature", "")
        if not signature:
            logger.warning("WeChat callback missing signature header")
            return False

        # TODO: Implement API v3 signature verification
        logger.info(f"WeChat signature verification (STUB): {signature[:20]}...")
        return True

    @staticmethod
    def extract_order_info(body: dict) -> dict:
        """Extract order info from WeChat Pay callback body (API v3 format)."""
        resource = body.get("resource", {})
        # In production, decrypt resource with AEAD_AES_256_GCM
        return {
            "order_id": body.get("out_trade_no", ""),
            "transaction_id": body.get("transaction_id", ""),
            "amount": body.get("amount", {}).get("total", 0),
            "status": body.get("trade_state", ""),
            "openid": body.get("payer", {}).get("openid", ""),
            "paid_at": body.get("success_time", ""),
        }

    @staticmethod
    def is_success(body: dict) -> bool:
        """Check if payment was successful."""
        return body.get("trade_state") == "SUCCESS"


def process_alipay_callback(db: Session, params: dict) -> dict:
    """Process Alipay payment callback.

    Returns:
        dict with success status and order info
    """
    # 1. Verify signature
    if not AlipayCallback.verify_signature(params):
        return {"success": False, "error": "\u7b7e\u540d\u9a8c\u8bc1\u5931\u8d99"}

    # 2. Extract order info
    info = AlipayCallback.extract_order_info(params)
    logger.info(f"Alipay callback: order={info['order_id']} status={info['status']} amount={info['amount']}")

    # 3. Check payment status
    if not AlipayCallback.is_success(params):
        return {"success": False, "error": f"\u652f\u4ed8\u672a\u6210\u529f: {info['status']}"}

    # 4. Verify amount matches
    from app.models import Payment
    order = db.query(Payment).filter(Payment.order_id == info["order_id"]).first()
    if not order:
        return {"success": False, "error": "\u8ba2\u5355\u4e0d\u5b58\u5728"}

    if order.status == "completed":
        return {"success": True, "message": "\u8ba2\u5355\u5df2\u5904\u7406\u8fc7"}  # Idempotent

    if abs(order.amount - info["amount"]) > 0.01:
        logger.error(f"Amount mismatch: order={order.amount} callback={info['amount']}")
        return {"success": False, "error": "\u91d1\u989d\u4e0d\u5339\u914d"}

    # 5. Activate membership
    order.status = "completed"
    order.paid_at = datetime.datetime.utcnow()
    order.payment_proof = info["trade_no"]
    extra = order.extra_data or {}
    extra["alipay_trade_no"] = info["trade_no"]
    extra["buyer_id"] = info["buyer_id"]
    order.extra_data = extra

    from app.services.payment_service import activate_membership
    result = activate_membership(db, order.user_id, order.tier, extra.get("period", "yearly"))

    return {"success": True, "order_id": info["order_id"], "result": result}


def process_wechat_callback(db: Session, headers: dict, body: dict) -> dict:
    """Process WeChat Pay callback.

    Returns:
        dict with success status and order info
    """
    # 1. Verify signature
    if not WechatPayCallback.verify_signature(headers, json.dumps(body)):
        return {"success": False, "error": "\u7b7e\u540d\u9a8c\u8bc1\u5931\u8d99"}

    # 2. Extract order info
    info = WechatPayCallback.extract_order_info(body)
    logger.info(f"WeChat callback: order={info['order_id']} status={info['status']}")

    # 3. Check payment status
    if not WechatPayCallback.is_success(body):
        return {"success": False, "error": f"\u652f\u4ed8\u672a\u6210\u529f: {info['status']}"}

    # 4. Verify amount
    from app.models import Payment
    order = db.query(Payment).filter(Payment.order_id == info["order_id"]).first()
    if not order:
        return {"success": False, "error": "\u8ba2\u5355\u4e0d\u5b58\u5728"}

    if order.status == "completed":
        return {"success": True, "message": "\u8ba2\u5355\u5df2\u5904\u7406\u8fc7"}

    if order.amount != info["amount"]:
        logger.error(f"Amount mismatch: order={order.amount} callback={info['amount']}")
        return {"success": False, "error": "\u91d1\u989d\u4e0d\u5339\u914d"}

    # 5. Activate membership
    order.status = "completed"
    order.paid_at = datetime.datetime.utcnow()
    order.payment_proof = info["transaction_id"]
    extra = order.extra_data or {}
    extra["wechat_transaction_id"] = info["transaction_id"]
    extra["openid"] = info["openid"]
    order.extra_data = extra

    from app.services.payment_service import activate_membership
    result = activate_membership(db, order.user_id, order.tier, extra.get("period", "yearly"))

    return {"success": True, "order_id": info["order_id"], "result": result}
