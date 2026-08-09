import time
import uuid

from app.execution.engines.base import BaseExecutionEngine
from app.db import get_mysql_pool


class QueryExecutionError(Exception):
    pass


async def _run_mysql_stmt(conn, sql: str):
    """Execute a single statement that doesn't return rows (e.g. CREATE, INSERT, USE, SET)."""
    async with conn.cursor() as cur:
        await cur.execute(sql)


async def _execute_mysql_query(conn, query: str) -> dict:
    """Execute a SELECT query on a MySQL connection and return {columns, rows, execution_time_ms}."""
    start = time.perf_counter()
    try:
        async with conn.cursor() as cur:
            await cur.execute(query)
            rows_raw = await cur.fetchall()
            columns = [d[0] for d in cur.description] if cur.description else []
    except Exception as e:
        error_msg = str(e)
        raise QueryExecutionError(error_msg)

    execution_time_ms = int((time.perf_counter() - start) * 1000)

    # Convert any non-serializable types (Decimal, datetime, etc.) to Python primitives
    rows = []
    for row in rows_raw:
        rows.append([_coerce(v) for v in row])

    return {
        "columns": columns,
        "rows": rows,
        "execution_time_ms": execution_time_ms,
    }


def _coerce(value):
    """Convert MySQL-specific types to JSON-serializable Python primitives."""
    import decimal, datetime
    if value is None:
        return None
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class MySQLEngine(BaseExecutionEngine):
    """
    Executes SQL queries against a temporary MySQL database using the stored
    mysql_schema_sql and mysql_seed_sql directly.
    """

    async def run(
        self,
        code: str,
        problem_id: str,
        conn,          # asyncpg PG connection (for fetching datasets metadata)
        datasets: dict = None,
    ) -> dict:
        pool = await get_mysql_pool()
        db_name = f"run_{uuid.uuid4().hex[:8]}"

        async with pool.acquire() as my_conn:
            try:
                # 1. Create isolated temp database
                await _run_mysql_stmt(my_conn, f"CREATE DATABASE `{db_name}`")
                await _run_mysql_stmt(my_conn, f"USE `{db_name}`")

                # 2. Enforce execution time limit (1 second)
                await _run_mysql_stmt(my_conn, "SET SESSION max_execution_time = 1000")

                # 3. Fetch dataset descriptors from Postgres
                ds_rows = await conn.fetch(
                    """
                    SELECT table_name, mysql_schema_sql, mysql_seed_sql, seed_data_json
                    FROM core.problem_datasets
                    WHERE problem_id = $1
                    """,
                    problem_id,
                )


                if not ds_rows:
                    return {
                        "columns": [], "rows": [], "execution_time_ms": 0,
                        "error": "No datasets defined for this problem"
                    }

                # 4. Load MySQL DDL and DML — prefer stored SQL, regenerate from JSON if absent
                for ds in ds_rows:
                    mysql_schema = ds["mysql_schema_sql"]
                    mysql_seed = ds["mysql_seed_sql"]

                    if not mysql_schema:
                        # Regenerate from seed_data_json using SqlDialectGenerator
                        raw_json = ds["seed_data_json"]
                        if raw_json:
                            import json as _json
                            from app.execution.sql_dialect_generator import SqlDialectGenerator
                            _gen = SqlDialectGenerator()
                            descriptor = _json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                            if _gen.has_schema_metadata(descriptor):
                                mysql_schema, mysql_seed = _gen.generate(
                                    descriptor, ds["table_name"], "mysql"
                                )
                            else:
                                return {
                                    "columns": [], "rows": [], "execution_time_ms": 0,
                                    "error": "This problem does not support MySQL dialect (no MySQL DDL or JSON descriptor with schema metadata found)"
                                }
                        else:
                            return {
                                "columns": [], "rows": [], "execution_time_ms": 0,
                                "error": "This problem does not support MySQL dialect (MySQL DDL schema not defined)"
                            }

                    await _run_mysql_stmt(my_conn, mysql_schema)
                    if mysql_seed:
                        await _run_mysql_stmt(my_conn, mysql_seed)


                # 5. Execute user query
                result = await _execute_mysql_query(my_conn, code)
                result["error"] = None
                return result

            except QueryExecutionError as e:
                return {
                    "columns": [], "rows": [], "execution_time_ms": 0,
                    "error": str(e)
                }
            except Exception as e:
                return {
                    "columns": [], "rows": [], "execution_time_ms": 0,
                    "error": f"MySQL Execution Error: {str(e)}"
                }
            finally:
                # 6. Always clean up the temp database
                try:
                    await _run_mysql_stmt(my_conn, f"DROP DATABASE IF EXISTS `{db_name}`")
                except Exception as cleanup_err:
                    print(f"MySQL teardown error for {db_name}: {cleanup_err}")
