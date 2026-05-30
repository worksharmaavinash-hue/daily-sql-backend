import time
import httpx
from app.execution.engines.base import BaseExecutionEngine

class PythonEngine(BaseExecutionEngine):
    async def run(self, code: str, problem_id: str, conn, datasets: dict) -> dict:
        start_time = time.perf_counter()
        url = "http://python-runner:5001/execute"
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json={"code": code, "data": datasets})
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
                return {
                    "columns": result.get("columns", []),
                    "rows": result.get("rows", []),
                    "execution_time_ms": execution_time_ms,
                    "error": None
                }
        except httpx.RequestError as e:
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            return {
                "columns": [],
                "rows": [],
                "execution_time_ms": execution_time_ms,
                "error": f"Failed to communicate with Python runner service: {str(e)}"
            }
