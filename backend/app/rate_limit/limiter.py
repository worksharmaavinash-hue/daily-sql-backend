import time
try:
    import redis.asyncio as aioredis
except ImportError:
    import aioredis
from fastapi import HTTPException

REDIS_URL = "redis://redis:6379"

redis = aioredis.from_url(REDIS_URL, decode_responses=True)

async def rate_limit(user_id: str, limit: int = 20, window: int = 60):
    key = f"rate:{user_id}"
    try:
        current = await redis.incr(key)
        print(f"RateLimit: User {user_id} -> {current}/{limit}")
        
        if current == 1:
            await redis.expire(key, window)

        if current > limit:
            print(f"RateLimit: BLOCKING User {user_id}")
            raise HTTPException(
                status_code=429,
                detail="Too many executions. Please slow down."
            )
    except Exception as e:
        print(f"RateLimit ERROR: {e}")
        # Fail open or closed? Fail open for now to avoid blocking on redis error unless strict.
        # But we want to know if it fails.
        if isinstance(e, HTTPException):
            raise e
        # If redis fails, maybe pass?
        # raise e
