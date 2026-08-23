"""Redis-based API rate limiter middleware."""
import time
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

REDIS_URL = "redis://huidao_redis:6379/0"

RATE_LIMIT_RULES = {
    "/api/auth/register": {"max": 10, "window": 3600, "msg": "注册请求过于频繁，请1小时后再试"},
    "/api/auth/login": {"max": 10, "window": 300, "msg": "登录尝试过于频繁，请5分钟后再试"},
    "/api/auth/resend-verification": {"max": 3, "window": 300, "msg": "验证邮件发送过于频繁，请稍后再试"},
    "/api/auth/forgot-password": {"max": 3, "window": 3600, "msg": "密码重置请求过于频繁，请1小时后再试"},
}


class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        rule = RATE_LIMIT_RULES.get(path)

        if rule is None or request.method != "POST":
            return await call_next(request)

        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.headers.get("X-Real-IP", "")
        if not client_ip and request.client:
            client_ip = request.client.host
        if not client_ip:
            client_ip = "unknown"

        blocked = await self._check(f"rl:{path}:{client_ip}", rule)
        if blocked:
            logger.warning(f"Rate limited: {client_ip} -> {path}")
            return JSONResponse(status_code=429, content={"detail": rule["msg"]},
                                headers={"Retry-After": str(blocked)})

        return await call_next(request)

    async def _check(self, key: str, rule: dict):
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(REDIS_URL, decode_responses=True)
            now = time.time()
            window = rule["window"]
            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zcard(key)
            pipe.zadd(key, {f"{now}:{id(pipe)}": now})
            pipe.expire(key, window + 10)
            results = await pipe.execute()
            count = results[1]
            await r.aclose()

            if count >= rule["max"]:
                return window  # retry after
            return None
        except Exception as e:
            logger.error(f"Rate limit check error: {e}")
            return None  # pass through on error


async def record_login_failure(email: str) -> bool:
    """Record a login failure, return True if account is locked."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        key = f"rl:login_fail:{email}"
        now = time.time()
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, now - 300)
        pipe.zcard(key)
        pipe.zadd(key, {f"{now}:{id(pipe)}": now})
        pipe.expire(key, 310)
        results = await pipe.execute()
        count = results[1]
        await r.aclose()
        return count >= 5
    except Exception as e:
        logger.error(f"Login failure record error: {e}")
        return False


async def check_login_blocked(email: str) -> bool:
    """Check if account is locked due to too many failed login attempts."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        key = f"rl:login_fail:{email}"
        now = time.time()
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, now - 300)
        pipe.zcard(key)
        results = await pipe.execute()
        count = results[1]
        await r.aclose()
        return count >= 5
    except Exception:
        return False
