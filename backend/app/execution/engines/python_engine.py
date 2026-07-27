import time
import os
import httpx
from app.execution.engines.base import BaseExecutionEngine

class PythonEngine(BaseExecutionEngine):
    async def run(
        self,
        code: str,
        problem_id: str,
        conn,
        datasets: dict,
        test_cases: list = None,
        function_name: str = "solve",
    ) -> dict:
        start_time = time.perf_counter()
        url = os.getenv("PYTHON_RUNNER_URL", "http://python-runner:5001/execute")

        if test_cases is not None:
            # DSA mode: pass test cases and function name, no dataset needed
            runner_payload = {
                "code": code,
                "data": {},
                "mode": "dsa",
                "test_cases": test_cases,
                "function_name": function_name,
            }
        else:
            # Existing DataFrame mode — unchanged
            runner_payload = {
                "code": code,
                "data": datasets,
                "mode": "dataframe",
            }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=runner_payload)
                execution_time_ms = int((time.perf_counter() - start_time) * 1000)

                if response.status_code != 200:
                    return {
                        "columns": [],
                        "rows": [],
                        "execution_time_ms": execution_time_ms,
                        "error": f"Execution failed with server status code: {response.status_code}"
                    }

                result = response.json()
                if result.get("error"):
                    return {
                        "columns": [],
                        "rows": [],
                        "execution_time_ms": execution_time_ms,
                        "error": result["error"]
                    }

                if test_cases is not None:
                    # DSA mode — return the raw results list alongside timing
                    return {
                        "mode": "dsa",
                        "results": result.get("results", []),
                        "execution_time_ms": execution_time_ms,
                        "error": None,
                    }

                # DataFrame mode — return columns/rows as before
                return {
                    "columns": result.get("columns", []),
                    "rows": result.get("rows", []),
                    "execution_time_ms": execution_time_ms,
                    "error": None
                }

        except httpx.RequestError as e:
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            base = {
                "execution_time_ms": execution_time_ms,
                "error": f"Failed to communicate with Python runner service: {str(e)}"
            }
            if test_cases is not None:
                return {"mode": "dsa", "results": [], **base}
            return {"columns": [], "rows": [], **base}
