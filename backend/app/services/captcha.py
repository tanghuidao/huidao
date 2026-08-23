"""Tencent Captcha (腾讯天御验证码) server-side verification service."""
import os
import logging
import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)

TENCENT_CAPTCHA_APP_ID = os.getenv("TENCENT_CAPTCHA_APP_ID", "")
TENCENT_CAPTCHA_SECRET_KEY = os.getenv("TENCENT_CAPTCHA_SECRET_KEY", "")
TENCENT_VERIFY_URL = "https://ssl.captcha.qq.com/ticket/verify"


async def verify_captcha(ticket: str, randstr: str, user_ip: str = "") -> dict:
    """
    Verify Tencent Captcha ticket server-side.
    Returns: {"success": bool, "error": str|None}

    Policy:
    - No keys configured -> skip (dev mode)
    - Empty ticket -> reject
    - Verification fails -> reject
    - Network error -> allow (graceful degradation)
    """
    if not TENCENT_CAPTCHA_APP_ID or not TENCENT_CAPTCHA_SECRET_KEY:
        logger.warning("Tencent Captcha keys not configured, skipping verification")
        return {"success": True, "error": None}

    if not ticket or not randstr:
        logger.warning("Captcha ticket/randstr empty - REJECTING")
        return {"success": False, "error": "missing_ticket"}

    # DEBUG: log exact received values
    logger.warning(f"CAPTCHA DEBUG: ticket_len={len(ticket)} ticket_head={ticket[:15]!r} ticket_tail={ticket[-15:]!r} randstr={randstr!r} user_ip={user_ip!r}")

    params = urllib.parse.urlencode({
        "aid": TENCENT_CAPTCHA_APP_ID,
        "AppSecretKey": TENCENT_CAPTCHA_SECRET_KEY,
        "Ticket": ticket,
        "Randstr": randstr,
        "UserIP": user_ip,
    })

    try:
        url = f"{TENCENT_VERIFY_URL}?{params}"
        logger.warning(f"CAPTCHA DEBUG: verify url={url}")
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
        logger.warning(f"CAPTCHA DEBUG: raw response={raw}")
        data = json.loads(raw)

        # response: 1 = pass, 0 = fail
        if str(data.get("response")) == "1":
            logger.info(f"Tencent Captcha passed (evil_level={data.get('evil_level', 'N/A')})")
            return {"success": True, "error": None}
        else:
            logger.warning(f"Tencent Captcha FAILED: {data}")
            return {"success": False, "error": f"verification_failed (code={data.get('response', '?')})"}

    except Exception as e:
        # Graceful degradation: don't block users if Tencent API is unreachable
        logger.error(f"Tencent Captcha verification error: {e} - allowing")
        return {"success": True, "error": f"error_passthrough: {e}"}
