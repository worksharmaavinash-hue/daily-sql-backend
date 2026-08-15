import os
import gc
import json
import traceback
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pyspark.sql import SparkSession
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

MAX_RESULT_ROWS = 1000

app = FastAPI(title="DailySQL PySpark Runner Service")

class ExecuteRequest(BaseModel):
    code: str
    data: dict

def _create_spark():
    """Create a new SparkSession with memory-safe settings."""
    # In local[1] mode, executor runs inside the driver JVM — executor.memory is ignored.
    # Only driver.memory matters for total JVM heap.
    return SparkSession.builder \
        .master("local[1]") \
        .appName("DailySQLSparkSandbox") \
        .config("spark.ui.enabled", "false") \
        .config("spark.driver.host", "127.0.0.1") \
        .config("spark.driver.bindAddress", "127.0.0.1") \
        .config("spark.driver.memory", "512m") \
        .config("spark.sql.shuffle.partitions", "1") \
        .config("spark.sql.execution.arrow.pyspark.enabled", "false") \
        .config("spark.driver.extraJavaOptions",
                "-XX:+UseG1GC "
                "-XX:MaxMetaspaceSize=256m "
                "-XX:+ClassUnloadingWithConcurrentMark "
                "-XX:MetaspaceSize=64m") \
        .getOrCreate()

# Initialize warm SparkSession globally on startup
spark = _create_spark()

def get_spark():
    """Return the live SparkSession, recreating it if the JVM has crashed."""
    global spark
    try:
        # Quick health check — will throw if the JVM is unreachable
        spark.sql("SELECT 1")
        return spark
    except Exception:
        # Fully tear down the broken session + JVM gateway before recreating
        try:
            spark.stop()
        except Exception:
            pass
        try:
            from pyspark import SparkContext
            SparkContext._gateway = None
            SparkContext._jvm = None
        except Exception:
            pass
        # Clear the singleton so builder creates a truly new session
        SparkSession._instantiatedSession = None
        spark = _create_spark()
        return spark

def cleanup_spark(spark_session):
    """Free JVM + Python memory after each execution."""
    try:
        # Drop all temp views so the JVM catalog releases references
        for t in spark_session.catalog.listTables():
            if t.isTemporary:
                spark_session.catalog.dropTempView(t.name)
    except Exception:
        pass
    try:
        # Clear any cached DataFrames
        spark_session.catalog.clearCache()
    except Exception:
        pass
    try:
        # Trigger JVM garbage collection to free heap
        spark_session._jvm.System.gc()
    except Exception:
        pass
    # Trigger Python garbage collection to release Py4J proxy references
    gc.collect()

executor = ThreadPoolExecutor(max_workers=2)

SAFE_BUILTINS = {
    # Math & types
    'abs', 'round', 'min', 'max', 'sum', 'len', 'sorted', 'reversed',
    'int', 'float', 'str', 'bool', 'list', 'dict', 'tuple', 'set', 'frozenset',
    'complex', 'bytes', 'bytearray', 'memoryview',
    # Iteration & functional
    'range', 'enumerate', 'zip', 'map', 'filter', 'any', 'all',
    'iter', 'next', 'slice',
    # String & formatting
    'format', 'repr', 'chr', 'ord', 'ascii', 'bin', 'hex', 'oct',
    # Type checking
    'isinstance', 'issubclass', 'type', 'callable', 'hasattr',
    'id', 'hash', 'dir', 'vars',
    # Object construction
    'object', 'super', 'property', 'staticmethod', 'classmethod',
    # Exceptions
    'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError',
    'AttributeError', 'RuntimeError', 'StopIteration', 'ZeroDivisionError',
    'NotImplementedError', 'OverflowError', 'ArithmeticError',
    # I/O
    'print',
    # Misc
    'pow', 'divmod',
}

import builtins
safe_builtins_dict = {name: getattr(builtins, name) for name in SAFE_BUILTINS if hasattr(builtins, name)}
# We add __import__ to builtins for internal dependencies, but it is blocked at AST level in validator.py
safe_builtins_dict['__import__'] = builtins.__import__

def serialize_val(val):
    try:
        if val is None:
            return None
        if isinstance(val, float) and pd.isna(val):
            return None
        if hasattr(val, "isoformat"):
            return val.isoformat()
        if hasattr(val, "to_eng_string"):
            return float(val)
        return val
    except (ValueError, TypeError):
        return str(val)

def run_code_in_thread(code: str, data_payload: dict):
    # Get a healthy SparkSession (auto-recovers if JVM died)
    spark_session = get_spark()

    global_namespace = {"spark": spark_session, "__builtins__": safe_builtins_dict}
    try:
        # 1. Reconstruct DataFrames & Views
        for table_name, table_data in data_payload.items():
            if isinstance(table_data, str):
                table_data = json.loads(table_data)
            
            cols = [c["name"] for c in table_data["columns"]]
            rows = table_data["rows"]
            
            pdf = pd.DataFrame(rows, columns=cols)
            df = spark_session.createDataFrame(pdf)
            
            global_namespace[f"{table_name}_df"] = df
            global_namespace[table_name] = df
            df.createOrReplaceTempView(table_name)

        # 2. Run user code
        exec(code, global_namespace)
        
        if "result" not in global_namespace:
            return {"error": "Missing 'result' variable. Please assign your final DataFrame to 'result'."}
            
        result_df = global_namespace["result"]
        # Allow either PySpark DataFrame or Pandas DataFrame
        if hasattr(result_df, "toPandas"):  # PySpark DataFrame
            # Cap rows before toPandas() to prevent memory spikes
            pdf_result = result_df.limit(MAX_RESULT_ROWS).toPandas()
        elif isinstance(result_df, pd.DataFrame):
            pdf_result = result_df.head(MAX_RESULT_ROWS)
        else:
            return {"error": "The 'result' variable must be a Spark or Pandas DataFrame."}
            
        # 3. Serialize output
        columns = list(pdf_result.columns)
        rows = pdf_result.values.tolist()
        rows = [[serialize_val(cell) for cell in row] for row in rows]
        
        return {
            "columns": columns,
            "rows": rows,
            "error": None
        }
        
    except Exception as e:
        return {
            "error": f"Runtime Error: {str(e)}\n{traceback.format_exc()}"
        }
    finally:
        # Always clean up JVM + Python memory after each request
        global_namespace.clear()
        cleanup_spark(spark_session)

@app.post("/execute")
async def execute_code(payload: ExecuteRequest):
    loop = asyncio.get_running_loop()
    try:
        # Run in thread executor with a 30 second timeout limit
        result = await asyncio.wait_for(
            loop.run_in_executor(executor, run_code_in_thread, payload.code, payload.data),
            timeout=30.0
        )
        return result
    except asyncio.TimeoutError:
        return {
            "error": "Execution Timeout: Code took too long to execute (limit: 30 seconds)."
        }
    except Exception as e:
        return {
            "error": f"Internal runner error: {str(e)}\n{traceback.format_exc()}"
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5002)
