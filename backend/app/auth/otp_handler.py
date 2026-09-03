import secrets
import uuid
from app.db import get_redis

MAX_OTP_ATTEMPTS = 5

async def create_otp_session(email: str) -> tuple[str, str]:
    """Generates a cryptographically secure 6-digit OTP and stores it in Redis with a state_id."""
    redis = await get_redis()
    # Use secrets module (cryptographically secure) instead of random
    otp = f"{secrets.randbelow(1000000):06d}"
    state_id = str(uuid.uuid4())
    
    # Store OTP with state_id as key, and also store email
    # Expiry: 10 minutes (600 seconds)
    await redis.setex(f"otp:{state_id}", 600, f"{email}:{otp}")
    # Initialize attempt counter
    await redis.setex(f"otp_attempts:{state_id}", 600, "0")
    return state_id, otp

async def verify_otp_session(state_id: str, otp: str, email: str) -> bool:
    """Verifies the OTP for a given state_id and email with brute-force protection."""
    redis = await get_redis()

    # Brute-force protection: max MAX_OTP_ATTEMPTS attempts per session
    attempts_key = f"otp_attempts:{state_id}"
    attempts = await redis.get(attempts_key)
    if attempts is not None and int(attempts) >= MAX_OTP_ATTEMPTS:
        # Invalidate the session to prevent further guessing
        await redis.delete(f"otp:{state_id}")
        await redis.delete(attempts_key)
        return False

    stored = await redis.get(f"otp:{state_id}")
    if not stored:
        return False
    
    # Increment attempt counter before checking (fail-safe)
    await redis.incr(attempts_key)

    try:
        stored_email, stored_otp = stored.split(":", 1)
        if stored_email.lower().strip() == email.lower().strip() and stored_otp == otp:
            # Correct — delete both keys immediately (single-use OTP)
            await redis.delete(f"otp:{state_id}")
            await redis.delete(attempts_key)
            return True
    except ValueError:
        return False
        
    return False
