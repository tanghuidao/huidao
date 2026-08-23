"""Google reCAPTCHA v3 verification service."""
import httpx
import os
import logging

logger = logging.getLogger(__name__)

RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "")
RECAPTCHA_SCORE_THRESHOLD = float(os.getenv("RECAPTCHA_SCORE_THRESHOLD", "0.5"))


async def verify_recaptcha(token: str, action: str = "register") -> dict:
    """
    Verify reCAPTCHA v3 token.
    Returns: {"success": bool, "score": float, "error": str|None}

    Policy:
    - No secret key configured -> skip (dev mode)
    - Empty token -> allow (frontend not yet integrated), but flag for email verification
    - Token provided + verification fails -> REJECT
    - Token provided + low score -> REJECT
    - Timeout/network error -> allow (graceful degradation)
    """
    if not RECAPTCHA_SECRET_KEY:
        logger.warning("RECAPTCHA_SECRET_KEY not configured, skipping verification")
        return {"success": True, "score": 1.0, "error": None}

    if not token:
        # Frontend does not yet integrate reCAPTCHA - allow but flag
        # Once frontend sends tokens, change this to reject
        logger.info(f"reCAPTCHA token empty (action={action}) - allowing, requires email verification")
        return {"success": True, "score": 0.0, "error": "no_token_needs_verify"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(RECAPTCHA_VERIFY_URL, data={
                "secret": RECAPTCHA_SECRET_KEY,
                "response": token,
            })
            resp.raise_for_status()
            result = resp.json()

        success = result.get("success", False)
        score = result.get("score", 0.0)
        resp_action = result.get("action", "")
        error_codes = result.get("error-codes", [])

        if not success:
            logger.warning(f"reCAPTCHA verification failed: {error_codes}")
            return {"success": False, "score": score, "error": error_codes[0] if error_codes else "failed"}

        if resp_action != action:
            logger.warning(f"reCAPTCHA action mismatch: expected={action}, got={resp_action}")
            return {"success": False, "score": score, "error": "action_mismatch"}

        if score < RECAPTCHA_SCORE_THRESHOLD:
            logger.warning(f"reCAPTCHA score too low: {score} < {RECAPTCHA_SCORE_THRESHOLD} - REJECTING")
            return {"success": False, "score": score, "error": "low_score"}

        logger.info(f"reCAPTCHA passed: score={score}")
        return {"success": True, "score": score, "error": None}

    except httpx.TimeoutException:
        logger.error("reCAPTCHA verification timeout - allowing (network issue)")
        return {"success": True, "score": 0.5, "error": "timeout_passthrough"}
    except Exception as e:
        logger.error(f"reCAPTCHA error: {e} - allowing (graceful degradation)")
        return {"success": True, "score": 0.5, "error": f"error_passthrough: {e}"}
