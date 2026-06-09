import os
import json
import multiprocessing
import traceback
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="DailySQL Python Runner Service")

class ExecuteRequest(BaseModel):
    code: str
    data: dict

def serialize_val(val):
    if pd.isna(val):
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "to_eng_string"):
        return float(val)
    return val

def execution_worker(code: str, data_payload: dict, pipe_conn):
    try:
        # 1. Reconstruct DataFrames
        global_namespace = {}
        for table_name, table_data in data_payload.items():
            if isinstance(table_data, str):
                table_data = json.loads(table_data)
            
            cols = [c["name"] for c in table_data["columns"]]
            rows = table_data["rows"]
            df = pd.DataFrame(rows, columns=cols)
            
            # Inject standard variable names like "employees_df"
            global_namespace[f"{table_name}_df"] = df

        # 2. Run user code
        exec(code, global_namespace)
        
        if "result" not in global_namespace:
            pipe_conn.send({"error": "Missing 'result' variable. Please assign your final DataFrame to 'result'."})
            return
            
        result_df = global_namespace["result"]
        if not isinstance(result_df, pd.DataFrame):
            pipe_conn.send({"error": "The 'result' variable must be a Pandas DataFrame."})
            return
            
        # 3. Serialize output
        columns = list(result_df.columns)
        rows = result_df.values.tolist()
        rows = [[serialize_val(cell) for cell in row] for row in rows]
        
        pipe_conn.send({
            "columns": columns,
            "rows": rows,
            "error": None
        })
        
    except Exception as e:
        pipe_conn.send({
            "error": f"Runtime Error: {str(e)}\n{traceback.format_exc()}"
        })

@app.post("/execute")
async def execute_code(payload: ExecuteRequest):
    parent_conn, child_conn = multiprocessing.Pipe()
    process = multiprocessing.Process(
        target=execution_worker,
        args=(payload.code, payload.data, child_conn)
    )
    
    process.start()
    
    # Wait for completion with a 5 second timeout limit
    timeout = 5.0
    if parent_conn.poll(timeout):
        result = parent_conn.recv()
        process.join()
        return result
    else:
        process.terminate()
        process.join()
        return {
            "error": "Execution Timeout: Code took too long to execute (limit: 5 seconds)."
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)
