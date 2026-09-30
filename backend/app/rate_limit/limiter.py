import time
try:
    import redis.asyncio as aioredis
except ImportError:
    import aioredis
from fastapi import HTTPException

import os

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

redis = aioredis.from_url(REDIS_URL, decode_responses=True)

# Track consecutive Redis failures — fail-open for a brief outage, then protect
_redis_failure_count = 0
_REDIS_FAIL_THRESHOLD = 3  # After this many consecutive failures, block all requests

async def rate_limit(user_id: str, limit: int = 20, window: int = 60):
    global _redis_failure_count
    key = f"rate:{user_id}"
    try:
        current = await redis.incr(key)

        if current == 1:
            await redis.expire(key, window)

        _redis_failure_count = 0  # Reset on success

        if current > limit:
            raise HTTPException(
                status_code=429,
                detail="Too many executions. Please slow down.",
            )
    except HTTPException:
        raise
    except Exception as e:
        _redis_failure_count += 1
        if _redis_failure_count >= _REDIS_FAIL_THRESHOLD:
            # Fail closed after repeated Redis failures to prevent abuse during outages
            raise HTTPException(
                status_code=503,
                detail="Rate limiter temporarily unavailable. Please retry shortly.",
            )
        # First few failures: fail open (allow request)


async def rate_limit_auth(key: str, limit: int = 10, window: int = 300):
    """
    Rate limiter for sensitive auth endpoints (login, OTP requests).
    Key should be email or IP address.
    Defaults: 10 attempts per 5 minutes.
    """
    global _redis_failure_count
    redis_key = f"auth_rate:{key}"
    try:
        current = await redis.incr(redis_key)
        if current == 1:
            await redis.expire(redis_key, window)
        _redis_failure_count = 0
        if current > limit:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait a few minutes and try again.",
            )
    except HTTPException:
        raise
    except Exception:
        _redis_failure_count += 1
        # Auth endpoints: fail closed to protect against abuse
        if _redis_failure_count >= _REDIS_FAIL_THRESHOLD:
            raise HTTPException(
                status_code=503,
                detail="Service temporarily unavailable. Please retry shortly.",
            )
