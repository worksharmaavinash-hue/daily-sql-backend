import random
import uuid
from app.db import get_redis

async def create_otp_session(email: str) -> tuple[str, str]:
    """Generates a 6-digit OTP and stores it in Redis with a state_id."""
    redis = await get_redis()
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    state_id = str(uuid.uuid4())
    
    # Store OTP with state_id as key, and also store email
    # Expiry: 10 minutes (600 seconds)
    await redis.setex(f"otp:{state_id}", 600, f"{email}:{otp}")
    return state_id, otp

async def verify_otp_session(state_id: str, otp: str, email: str) -> bool:
    """Verifies the OTP for a given state_id and email."""
    redis = await get_redis()
    stored = await redis.get(f"otp:{state_id}")
    if not stored:
        return False
    
    try:
        stored_email, stored_otp = stored.split(":")
        if stored_email.lower().strip() == email.lower().strip() and stored_otp == otp:
            await redis.delete(f"otp:{state_id}")
            return True
    except ValueError:
        return False
        
    return False
