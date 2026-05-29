import os
import json
import asyncio
import uuid
import time
from app.execution.engines.base import BaseExecutionEngine

class PySparkEngine(BaseExecutionEngine):
    async def run(self, code: str, problem_id: str, conn, datasets: dict) -> dict:
        container_name = f"spark_run_{uuid.uuid4().hex[:8]}"
        start_time = time.perf_counter()
        
        # Prepare environment variables for forwarding
        env = os.environ.copy()
        env["CODE"] = code
        env["DATA"] = json.dumps(datasets)
        
        cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--hostname", "localhost",
            "-e", "CODE",
            "-e", "DATA",
            "-e", "SPARK_LOCAL_IP=127.0.0.1",
            "--network", "none",
            "--memory", "1024m",  # Spark needs slightly more memory (1024MB recommended)
            "--cpus", "0.75",
            "dailysql-pyspark-runner:latest"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        
        try:
            # Spark needs a slightly longer timeout for JVM startup (100s limit)
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=100.0)
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
                    "error": "No output returned from PySpark execution environment."
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
                "execution_time_ms": 100000,
                "error": "Execution Timed Out (exceeded 100s PySpark JVM limit)"
            }
