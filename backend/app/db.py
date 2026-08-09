import asyncpg
import aiomysql
import os
import redis.asyncio as redis

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# MySQL connection settings (individual env vars, no URL parsing needed)
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "mysql")

_pool = None
_redis = None
_mysql_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool

async def get_redis():
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis

async def get_mysql_pool():
    """
    Returns a lazy-initialized aiomysql connection pool.
    Used exclusively by MySQLEngine for dual-dialect SQL problem execution.
    Each execution creates and drops its own temporary database for isolation.
    """
    global _mysql_pool
    if _mysql_pool is None:
        _mysql_pool = await aiomysql.create_pool(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            autocommit=True,
            minsize=2,
            maxsize=10,
            connect_timeout=10,
        )
    return _mysql_pool
