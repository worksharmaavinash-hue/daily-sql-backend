from app.execution.engines.base import BaseExecutionEngine
from app.execution.schema_manager import (
    setup_execution_schema,
    teardown_execution_schema,
    apply_execution_limits
)
from app.execution.runner import execute_user_query, QueryExecutionError

class PostgresEngine(BaseExecutionEngine):
    async def run(self, code: str, problem_id: str, conn, datasets: dict = None) -> dict:
        schema_name = None
        try:
            # 1. Setup isolated PG schema
            schema_name = await setup_execution_schema(conn, problem_id)
            
            # 2. Apply resource limits to the PG transaction
            await apply_execution_limits(conn)
            
            # 3. Execute the SQL query
            result = await execute_user_query(conn, code)
            result["error"] = None
            return result
        except QueryExecutionError as e:
            return {
                "columns": [],
                "rows": [],
                "execution_time_ms": 0,
                "error": str(e)
            }
        except Exception as e:
            return {
                "columns": [],
                "rows": [],
                "execution_time_ms": 0,
                "error": f"Postgres Execution Error: {str(e)}"
            }
        finally:
            if schema_name:
                try:
                    await teardown_execution_schema(conn, schema_name)
                except Exception as e:
                    print(f"Teardown error: {e}")
