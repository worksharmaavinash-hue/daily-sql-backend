"""
Sandboxed execution entrypoint.
Reads JSON payload from stdin, runs user code in a restricted namespace, writes JSON result to stdout.
This runs as a fresh subprocess for every execution request (no forking, no event loop corruption).
"""
import sys
import json
import traceback
import builtins
import pandas as pd

SAFE_BUILTINS = {
    'abs', 'round', 'min', 'max', 'sum', 'len', 'sorted', 'reversed',
    'int', 'float', 'str', 'bool', 'list', 'dict', 'tuple', 'set', 'frozenset',
    'complex', 'bytes', 'bytearray', 'memoryview',
    'range', 'enumerate', 'zip', 'map', 'filter', 'any', 'all',
    'iter', 'next', 'slice',
    'format', 'repr', 'chr', 'ord', 'ascii', 'bin', 'hex', 'oct',
    'isinstance', 'issubclass', 'type', 'callable', 'hasattr',
    'id', 'hash', 'dir', 'vars',
    'object', 'super', 'property', 'staticmethod', 'classmethod',
    'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError',
    'AttributeError', 'RuntimeError', 'StopIteration', 'ZeroDivisionError',
    'NotImplementedError', 'OverflowError', 'ArithmeticError',
    'print',
    'pow', 'divmod',
}

safe_builtins_dict = {name: getattr(builtins, name) for name in SAFE_BUILTINS if hasattr(builtins, name)}
safe_builtins_dict['__import__'] = builtins.__import__

def serialize_val(val):
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "to_eng_string"):
        return float(val)
    return val

def main():
    try:
        payload = json.load(sys.stdin)
        code = payload["code"]
        data_payload = payload["data"]
    except Exception as e:
        json.dump({"error": f"Invalid input: {e}"}, sys.stdout)
        sys.exit(0)

    global_namespace = {"__builtins__": safe_builtins_dict, "pd": pd}
    try:
        for table_name, table_data in data_payload.items():
            if isinstance(table_data, str):
                table_data = json.loads(table_data)
            cols = [c["name"] if isinstance(c, dict) else c for c in table_data["columns"]]
            rows = table_data["rows"]
            df = pd.DataFrame(rows, columns=cols)
            global_namespace[f"{table_name}_df"] = df
            global_namespace[table_name] = df

        exec(code, global_namespace)

        if "result" not in global_namespace:
            json.dump({"error": "Missing 'result' variable. Please assign your final DataFrame to 'result'."}, sys.stdout)
            sys.exit(0)

        result_df = global_namespace["result"]
        if not isinstance(result_df, pd.DataFrame):
            json.dump({"error": "The 'result' variable must be a Pandas DataFrame."}, sys.stdout)
            sys.exit(0)

        columns = list(result_df.columns)
        rows = [[serialize_val(cell) for cell in row] for row in result_df.values.tolist()]
        json.dump({"columns": columns, "rows": rows, "error": None}, sys.stdout)

    except Exception as e:
        json.dump({"error": f"Runtime Error: {str(e)}\n{traceback.format_exc()}"}, sys.stdout)

if __name__ == "__main__":
    main()
