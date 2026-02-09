import asyncio
from app.rate_limit.limiter import redis

async def main():
    print("Testing Redis...")
    try:
        val = await redis.incr("test_key")
        print(f"Redis incr: {val}")
    except Exception as e:
        print(f"Redis Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
