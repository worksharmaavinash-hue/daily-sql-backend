import os
import json
import asyncio
import uuid
import time
from app.execution.engines.base import BaseExecutionEngine

class PythonEngine(BaseExecutionEngine):
    async def run(self, code: str, problem_id: str, conn, datasets: dict) -> dict:
        container_name = f"py_run_{uuid.uuid4().hex[:8]}"
        start_time = time.perf_counter()
        
        # Prepare environment variables for forwarding
        env = os.environ.copy()
        env["CODE"] = code
        env["DATA"] = json.dumps(datasets)
        
        cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "-e", "CODE",
            "-e", "DATA",
            "--network", "none",
            "--memory", "256m",
            "--cpus", "0.5",
            "dailysql-python-runner:latest"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        
        try:
            # Wait for execution with 10-second timeout
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            
            if process.returncode != 0:
                err_msg = stderr.decode().strip() or stdout.decode().strip() or f"Process exited with code {process.returncode}"
                return {
                    "columns": [],
                    "rows": [],
                    "execution_time_ms": execution_time_ms,
                    "error": f"Execution failed: {err_msg}"
                }
                
            output_str = stdout.decode().strip()
            if not output_str:
                return {
                    "columns": [],
                    "rows": [],
                    "execution_time_ms": execution_time_ms,
                    "error": "No output returned from execution environment."
                }
                
            try:
                result = json.loads(output_str)
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
            except json.JSONDecodeError:
                return {
                    "columns": [],
                    "rows": [],
                    "execution_time_ms": execution_time_ms,
                    "error": f"Invalid runner output: {output_str}"
                }
                
        except asyncio.TimeoutError:
            # Force kill the docker container
            kill_proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await kill_proc.wait()
            return {
                "columns": [],
                "rows": [],
                "execution_time_ms": 10000,
                "error": "Execution Timed Out (exceeded 10s limit)"
            }
