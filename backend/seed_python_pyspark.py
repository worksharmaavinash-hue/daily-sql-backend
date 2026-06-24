import asyncio
import os
import json
import uuid
import asyncpg
import httpx

DATABASE_URL = "postgres://postgres:postgres@localhost:5432/dailysql"

async def seed_challenges():
    print("Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)
    print("Connected.")

    # 1. Insert Python problem
    py_problem_id = str(uuid.uuid4())
    print(f"Creating Python problem: {py_problem_id}")
    
    await conn.execute("""
        INSERT INTO core.problems (id, title, difficulty, description, estimated_time_minutes, is_active, challenge_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, py_problem_id, "Python Salary Bonus", "easy", 
       "Calculate the bonus for each employee. The bonus is 10% of the salary if the employee belongs to department 'Sales', and 5% otherwise. Return columns `id`, `name`, and `bonus`.", 
       10, True, "python")

    # Insert dataset JSON
    py_dataset_id = str(uuid.uuid4())
    employees_data = {
        "columns": [
            {"name": "id", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "salary", "type": "integer"},
            {"name": "department", "type": "text"}
        ],
        "rows": [
            [1, "Alice", 90000, "Sales"],
            [2, "Bob", 70000, "Engineering"],
            [3, "Charlie", 80000, "Sales"],
            [4, "David", 60000, "Engineering"]
        ]
    }
    py_sample_rows = [
        {"id": 1, "name": "Alice", "salary": 90000, "department": "Sales"},
        {"id": 2, "name": "Bob", "salary": 70000, "department": "Engineering"},
        {"id": 3, "name": "Charlie", "salary": 80000, "department": "Sales"},
        {"id": 4, "name": "David", "salary": 60000, "department": "Engineering"}
    ]
    
    await conn.execute("""
        INSERT INTO core.problem_datasets (id, problem_id, table_name, schema_sql, seed_sql, sample_rows, column_types, seed_data_json)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """, py_dataset_id, py_problem_id, "employees", "", "", json.dumps(py_sample_rows), "{}", json.dumps(employees_data))
    
    print("Inserted Python dataset.")

    # 2. Insert PySpark problem
    spark_problem_id = str(uuid.uuid4())
    print(f"Creating PySpark problem: {spark_problem_id}")
    
    await conn.execute("""
        INSERT INTO core.problems (id, title, difficulty, description, estimated_time_minutes, is_active, challenge_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, spark_problem_id, "PySpark High Salary Count", "medium", 
       "Group employees by department and count the number of employees earning more than 75000. Return columns `department` and `high_earner_count`.", 
       15, True, "pyspark")

    # Insert dataset JSON for spark (using the same structure)
    spark_dataset_id = str(uuid.uuid4())
    await conn.execute("""
        INSERT INTO core.problem_datasets (id, problem_id, table_name, schema_sql, seed_sql, sample_rows, column_types, seed_data_json)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """, spark_dataset_id, spark_problem_id, "employees", "", "", json.dumps(py_sample_rows), "{}", json.dumps(employees_data))
    
    print("Inserted PySpark dataset.")

    # 3. Create Solutions via admin POST API to trigger auto-compute and verification
    print("\nRegistering solutions via Admin API...")
    async with httpx.AsyncClient() as client:
        # Python solution
        py_sol_resp = await client.post(
            f"http://localhost:8000/admin/problems/{py_problem_id}/solution",
            headers={"X-Admin-Secret": "admin_secret"},
            json={
                "reference_code": "result = employees_df.copy()\nresult['bonus'] = result.apply(lambda r: r['salary'] * 0.10 if r['department'] == 'Sales' else r['salary'] * 0.05, axis=1)\nresult = result[['id', 'name', 'bonus']]",
                "order_sensitive": False,
                "notes": "Pandas conditional bonus"
            }
        )
        print("Python solution save status:", py_sol_resp.status_code)
        if py_sol_resp.status_code != 200:
            print("Python solution error:", py_sol_resp.text)

        # PySpark solution
        spark_sol_resp = await client.post(
            f"http://localhost:8000/admin/problems/{spark_problem_id}/solution",
            headers={"X-Admin-Secret": "admin_secret"},
            json={
                "reference_code": "filtered = employees_df.filter(employees_df['salary'] > 75000)\nresult = filtered.groupBy('department').count().withColumnRenamed('count', 'high_earner_count')",
                "order_sensitive": False,
                "notes": "PySpark grouping and renaming"
            }
        )
        print("PySpark solution save status:", spark_sol_resp.status_code)
        if spark_sol_resp.status_code != 200:
            print("PySpark solution error:", spark_sol_resp.text)

    await conn.close()
    print("\nSeed script completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed_challenges())
