import os
import json
import pandas as pd

def run_sandbox():
    user_code = os.getenv("CODE", "")
    data_payload = json.loads(os.getenv("DATA", "{}"))
    
    # 1. Reconstruct DataFrames
    global_namespace = {}
    for table_name, table_data in data_payload.items():
        if isinstance(table_data, str):
            table_data = json.loads(table_data)
        # table_data contains { "columns": [{"name": "col_a"}], "rows": [[val]] } or simple structure
        cols = [c["name"] for c in table_data["columns"]]
        rows = table_data["rows"]
        df = pd.DataFrame(rows, columns=cols)
        
        # Inject standard variable names like "employees_df"
        global_namespace[f"{table_name}_df"] = df

    # 2. Run user code
    try:
        # Prevent accessing dangerous builtins inside the execution scope
        exec(user_code, global_namespace)
        
        if "result" not in global_namespace:
            print(json.dumps({"error": "Missing 'result' variable. Please assign your final DataFrame to 'result'."}))
            return
            
        result_df = global_namespace["result"]
        if not isinstance(result_df, pd.DataFrame):
            print(json.dumps({"error": "The 'result' variable must be a Pandas DataFrame."}))
            return
            
        # 3. Serialize output
        columns = list(result_df.columns)
        rows = result_df.values.tolist()
        
        # Convert any non-serializable types (like datetime, decimal, etc) to string/floats
        def serialize_val(val):
            if hasattr(val, "isoformat"):
                return val.isoformat()
            if hasattr(val, "to_eng_string"):
                return float(val)
            return val

        rows = [[serialize_val(cell) for cell in row] for row in rows]
        
        print(json.dumps({
            "columns": columns,
            "rows": rows,
            "error": None
        }))
        
    except Exception as e:
        print(json.dumps({
            "error": f"Runtime Error: {str(e)}"
        }))

if __name__ == "__main__":
    run_sandbox()
