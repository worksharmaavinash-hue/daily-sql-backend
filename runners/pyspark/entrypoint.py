import os
import json
from pyspark.sql import SparkSession
import pandas as pd

def run_spark_sandbox():
    user_code = os.getenv("CODE", "")
    data_payload = json.loads(os.getenv("DATA", "{}"))
    
    # 1. Initialize SparkSession in local mode
    spark = SparkSession.builder \
        .master("local[1]") \
        .appName("DailySQLSparkSandbox") \
        .config("spark.ui.enabled", "false") \
        .config("spark.driver.host", "127.0.0.1") \
        .config("spark.driver.bindAddress", "127.0.0.1") \
        .config("spark.driver.memory", "512m") \
        .getOrCreate()

    global_namespace = {"spark": spark}
    
    try:
        # 2. Reconstruct Spark DataFrames
        for table_name, table_data in data_payload.items():
            if isinstance(table_data, str):
                table_data = json.loads(table_data)
            cols = [c["name"] for c in table_data["columns"]]
            rows = table_data["rows"]
            
            # Use Pandas as transition format to respect type definitions
            pdf = pd.DataFrame(rows, columns=cols)
            df = spark.createDataFrame(pdf)
            
            # Inject "employees_df" and register as Spark temp view so they can write spark.sql("...")
            global_namespace[f"{table_name}_df"] = df
            df.createOrReplaceTempView(table_name)
            
        # 3. Execute code
        exec(user_code, global_namespace)
        
        if "result" not in global_namespace:
            print(json.dumps({"error": "Missing 'result' variable. Please assign your final DataFrame to 'result'."}))
            return
            
        result_df = global_namespace["result"]
        # Allow either PySpark DataFrame or Pandas DataFrame
        if hasattr(result_df, "toPandas"):  # PySpark DataFrame
            pdf_result = result_df.toPandas()
        elif isinstance(result_df, pd.DataFrame):
            pdf_result = result_df
        else:
            print(json.dumps({"error": "The 'result' variable must be a Spark or Pandas DataFrame."}))
            return
            
        columns = list(pdf_result.columns)
        rows = pdf_result.values.tolist()
        
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
    finally:
        spark.stop()

if __name__ == "__main__":
    run_spark_sandbox()
