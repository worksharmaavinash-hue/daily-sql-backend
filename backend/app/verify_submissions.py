import asyncio
import json
import asyncpg
import httpx

DATABASE_URL = "postgres://postgres:postgres@postgres:5432/dailysql"

async def verify_submissions():
    print("Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)
    print("Connected.")

    # 1. Retrieve the newly seeded Python and PySpark problem IDs
    py_problem = await conn.fetchrow(
        "SELECT id FROM core.problems WHERE title = 'Python Salary Bonus'"
    )
    spark_problem = await conn.fetchrow(
        "SELECT id FROM core.problems WHERE title = 'PySpark High Salary Count'"
    )

    if not py_problem or not spark_problem:
        print("Error: Could not find seeded challenges in the database!")
        await conn.close()
        return

    py_id = str(py_problem["id"])
    spark_id = str(spark_problem["id"])
    print(f"Found Python problem ID: {py_id}")
    print(f"Found PySpark problem ID: {spark_id}")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # --- Python Verification ---
        print("\n--- Submitting CORRECT Pandas code ---")
        py_correct_resp = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": py_id,
                "query": "result = employees_df.copy()\nresult['bonus'] = result.apply(lambda r: r['salary'] * 0.10 if r['department'] == 'Sales' else r['salary'] * 0.05, axis=1)\nresult = result[['id', 'name', 'bonus']]"
            }
        )
        print("Status:", py_correct_resp.status_code)
        py_correct_json = py_correct_resp.json()
        print("Grading Result:", py_correct_json.get("status"))
        print("Columns Returned:", py_correct_json.get("user", {}).get("columns"))
        print("Rows Returned:", py_correct_json.get("user", {}).get("rows"))

        print("\n--- Submitting INCORRECT Pandas code ---")
        py_incorrect_resp = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": py_id,
                "query": "result = employees_df.copy()\nresult['bonus'] = 5000\nresult = result[['id', 'name', 'bonus']]"
            }
        )
        py_incorrect_json = py_incorrect_resp.json()
        print("Grading Result:", py_incorrect_json.get("status"))
        print("Diff Reason:", py_incorrect_json.get("diff_reason"))

        # --- PySpark Verification ---
        print("\n--- Submitting CORRECT PySpark DataFrame API code ---")
        spark_correct_resp = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": spark_id,
                "query": "filtered = employees_df.filter(employees_df['salary'] > 75000)\nresult = filtered.groupBy('department').count().withColumnRenamed('count', 'high_earner_count')"
            }
        )
        print("Status:", spark_correct_resp.status_code)
        spark_correct_json = spark_correct_resp.json()
        print("Grading Result:", spark_correct_json.get("status"))
        print("Columns Returned:", spark_correct_json.get("user", {}).get("columns"))
        print("Rows Returned:", spark_correct_json.get("user", {}).get("rows"))

        print("\n--- Submitting CORRECT PySpark SparkSQL query ---")
        spark_sql_resp = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": spark_id,
                "query": "result = spark.sql('SELECT department, COUNT(*) as high_earner_count FROM employees WHERE salary > 75000 GROUP BY department')"
            }
        )
        print("Status:", spark_sql_resp.status_code)
        spark_sql_json = spark_sql_resp.json()
        print("Grading Result:", spark_sql_json.get("status"))
        print("Columns Returned:", spark_sql_json.get("user", {}).get("columns"))
        print("Rows Returned:", spark_sql_json.get("user", {}).get("rows"))

    await conn.close()
    print("\nVerification completed successfully!")

if __name__ == "__main__":
    asyncio.run(verify_submissions())
