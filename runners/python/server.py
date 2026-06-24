import json
import asyncio
import traceback
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="DailySQL Python Runner Service")

class ExecuteRequest(BaseModel):
    code: str
    data: dict

TIMEOUT_SECONDS = 10.0

@app.post("/execute")
async def execute_code(payload: ExecuteRequest):
    """
    Spawn a fresh subprocess for each execution request.
    This avoids fork()/event-loop corruption from multiprocessing.
    """
    input_payload = json.dumps({"code": payload.code, "data": payload.data})

    try:
        process = await asyncio.create_subprocess_exec(
            "python", "/entrypoint.py",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=input_payload.encode()),
                timeout=TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {"error": f"Execution Timeout: Code took too long to execute (limit: {TIMEOUT_SECONDS}s)."}

        if process.returncode != 0:
            err_text = stderr.decode(errors="replace").strip()
            return {"error": f"Runner process error: {err_text or 'Unknown error'}"}

        result = json.loads(stdout.decode())
        return result

    except Exception as e:
        return {"error": f"Failed to execute code: {str(e)}\n{traceback.format_exc()}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)
