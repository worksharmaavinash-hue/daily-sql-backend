"""
Sandboxed execution entrypoint.
Reads JSON payload from stdin, runs user code in a restricted namespace, writes JSON result to stdout.
This runs as a fresh subprocess for every execution request (no forking, no event loop corruption).

Modes:
  - "dataframe": existing Pandas mode — expects result = pd.DataFrame
  - "dsa":       new DSA mode — calls user-defined function against test cases
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


def run_dataframe(code, data_payload):
    """Existing Pandas/DataFrame mode — unchanged."""
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


def run_dsa(code, test_cases, function_name):
    """
    DSA mode: exec the user's code, then call function_name(*args) for each test case.
    Returns {"mode": "dsa", "results": [...]} or {"error": "..."}.
    """
    import collections
    import heapq
    import bisect
    import functools
    import math
    import itertools

    # Build a namespace with safe builtins + DSA-standard algorithmic modules
    # These are pure-computation modules with no I/O or OS access
    dsa_namespace = {
        "__builtins__": safe_builtins_dict,
        "collections": collections,
        "heapq": heapq,
        "bisect": bisect,
        "functools": functools,
        "math": math,
        "itertools": itertools,
    }

    try:
        exec(code, dsa_namespace)
    except Exception as e:
        json.dump({"error": f"Runtime Error: {str(e)}\n{traceback.format_exc()}"}, sys.stdout)
        return

    if function_name not in dsa_namespace:
        json.dump({
            "error": f"Missing function '{function_name}'. Please define your solution as 'def {function_name}(...)'."
        }, sys.stdout)
        return

    fn = dsa_namespace[function_name]
    results = []
    for tc in test_cases:
        args = tc.get("input_data", {}).get("args", [])
        expected = tc.get("expected")
        try:
            got = fn(*args)
            # Normalize comparison: lists vs tuples, etc.
            passed = (got == expected)
            results.append({
                "passed": passed,
                "got": got,
                "expected": expected,
                "label": tc.get("label"),
                "is_hidden": tc.get("is_hidden", False),
            })
        except BaseException as e:
            # Catch ALL errors (including RecursionError, MemoryError, etc.)
            # per-case so that a crash on one test never stops the remaining tests.
            results.append({
                "passed": False,
                "error": str(e),
                "got": None,
                "expected": expected,
                "label": tc.get("label"),
                "is_hidden": tc.get("is_hidden", False),
            })

    json.dump({"mode": "dsa", "results": results, "error": None}, sys.stdout)


def main():
    try:
        payload = json.load(sys.stdin)
        code = payload["code"]
        mode = payload.get("mode", "dataframe")
    except Exception as e:
        json.dump({"error": f"Invalid input: {e}"}, sys.stdout)
        sys.exit(0)

    if mode == "dsa":
        run_dsa(
            code,
            payload.get("test_cases", []),
            payload.get("function_name", "solve"),
        )
    else:
        run_dataframe(code, payload.get("data", {}))


if __name__ == "__main__":
    main()
