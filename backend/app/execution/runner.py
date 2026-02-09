import time
import asyncpg

class QueryExecutionError(Exception):
    pass

async def execute_user_query(conn, query: str):
    start_time = time.perf_counter()

    try:
        records = await conn.fetch(query)
    except asyncpg.exceptions.QueryCanceledError:
        raise QueryExecutionError("Query timed out")
    except asyncpg.PostgresError as e:
        raise QueryExecutionError(e.message)

    execution_time_ms = int((time.perf_counter() - start_time) * 1000)

    if not records:
        return {
            "columns": [],
            "rows": [],
            "execution_time_ms": execution_time_ms
        }

    columns = list(records[0].keys())
    rows = [list(record.values()) for record in records]

    return {
        "columns": columns,
        "rows": rows,
        "execution_time_ms": execution_time_ms
    }
