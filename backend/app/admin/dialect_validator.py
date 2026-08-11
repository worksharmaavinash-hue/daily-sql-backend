"""
dialect_validator.py
====================
Per-dialect SQL validation functions for admin dataset creation.

Each validator receives the resolved (schema_sql, seed_sql) strings for its
dialect and validates them against a live database instance, raising
HTTPException on failure.

Registry
--------
DIALECT_VALIDATORS maps dialect name → validator coroutine.
To add a new dialect, write an async validate_<dialect>_dataset() function
and add it to DIALECT_VALIDATORS — no other file needs changing.
"""

from __future__ import annotations

import uuid as _uuid
from fastapi import HTTPException
from app.execution.schema_manager import generate_schema_name, teardown_execution_schema


# ──────────────────────────────────────────────────────────────────────────────
# PostgreSQL validator
# ──────────────────────────────────────────────────────────────────────────────

async def validate_postgres_dataset(
    conn,
    schema_sql: str,
    seed_sql: str,
    existing_datasets: list[dict],
    table_name: str,
) -> list[dict]:
    """
    Validates DDL+DML against a live PostgreSQL instance using an isolated
    temporary schema. Returns sample_rows (up to 10) on success.
    Raises HTTPException(400) on failure.
    """
    schema_name = generate_schema_name()
    try:
        await conn.execute(f'CREATE SCHEMA "{schema_name}"')
        await conn.execute(f'SET search_path TO "{schema_name}"')

        # Load existing sibling tables first (foreign key resolution)
        for ds in existing_datasets:
            await conn.execute(ds["schema_sql"])
            if ds["seed_sql"]:
                await conn.execute(ds["seed_sql"])

        # Load the new table
        await conn.execute(schema_sql)
        if seed_sql:
            await conn.execute(seed_sql)

        records = await conn.fetch(f"SELECT * FROM {table_name} LIMIT 10")
        return [dict(r) for r in records]

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"PostgreSQL validation failed: {exc}",
        )
    finally:
        await teardown_execution_schema(conn, schema_name)
        await conn.execute("SET search_path TO public")


# ──────────────────────────────────────────────────────────────────────────────
# MySQL validator
# ──────────────────────────────────────────────────────────────────────────────

async def validate_mysql_dataset(
    conn,  # unused but kept for consistent signature
    schema_sql: str,
    seed_sql: str,
    existing_datasets: list[dict],
    table_name: str,
) -> None:
    """
    Validates DDL+DML against a live MySQL instance using an isolated
    temporary database. Returns None on success.
    Raises HTTPException(400) on failure.
    """
    from app.db import get_mysql_pool

    my_pool = await get_mysql_pool()
    test_db = f"validate_{_uuid.uuid4().hex[:8]}"

    async with my_pool.acquire() as my_conn:
        try:
            async with my_conn.cursor() as cur:
                await cur.execute(f"CREATE DATABASE `{test_db}`")
                await cur.execute(f"USE `{test_db}`")

                # Load existing sibling tables first
                for ds in existing_datasets:
                    ex_schema = ds.get("mysql_schema_sql") or ds["schema_sql"]
                    ex_seed = ds.get("mysql_seed_sql") or ds["seed_sql"]
                    await cur.execute(ex_schema)
                    if ex_seed:
                        await cur.execute(ex_seed)

                # Load the new table
                await cur.execute(schema_sql)
                if seed_sql:
                    await cur.execute(seed_sql)

        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"MySQL validation failed: {exc}",
            )
        finally:
            try:
                async with my_conn.cursor() as cur:
                    await cur.execute(f"DROP DATABASE IF EXISTS `{test_db}`")
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────────

# Maps dialect name → validation coroutine.
# To add a new dialect (e.g. "sqlite"), write validate_sqlite_dataset() above
# and add it here. Nothing else needs changing.
DIALECT_VALIDATORS: dict = {
    "postgresql": validate_postgres_dataset,
    "mysql": validate_mysql_dataset,
}
