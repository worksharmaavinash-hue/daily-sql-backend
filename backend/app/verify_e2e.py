import asyncio
import os
import json
import uuid
import asyncpg
import httpx

DATABASE_URL = "postgres://postgres:postgres@postgres:5432/dailysql"

async def test_challenge(challenge_type: str):
    print(f"\n==========================================")
    print(f" TESTING {challenge_type.upper()} CHALLENGE")
    print(f"==========================================")
    
    conn = await asyncpg.connect(DATABASE_URL)
    problem_id = str(uuid.uuid4())
    print(f"Creating mock {challenge_type} problem with ID: {problem_id}")
    
    # 1. Insert problem
    await conn.execute("""
        INSERT INTO core.problems (id, title, difficulty, description, estimated_time_minutes, is_active, challenge_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, problem_id, f"Filter Salaries ({challenge_type})", "easy", "Filter employees with salary > 80000", 10, True, challenge_type)

    # 2. Insert dataset JSON
    dataset_id = str(uuid.uuid4())
    seed_data = {
        "columns": [
            {"name": "id", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "salary", "type": "integer"}
        ],
        "rows": [
            [1, "Alice", 90000],
            [2, "Bob", 75000],
            [3, "Charlie", 85000]
        ]
    }
    sample_rows = [
        {"id": 1, "name": "Alice", "salary": 90000},
        {"id": 2, "name": "Bob", "salary": 75000},
        {"id": 3, "name": "Charlie", "salary": 85000}
    ]
    
    await conn.execute("""
        INSERT INTO core.problem_datasets (id, problem_id, table_name, schema_sql, seed_sql, sample_rows, column_types, seed_data_json)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """, dataset_id, problem_id, "employees", "", "", json.dumps(sample_rows), "{}", json.dumps(seed_data))
    print("Inserted mock dataset.")

    async with httpx.AsyncClient(timeout=120.0) as client:
        # 3. Create Solution (via admin POST API to trigger auto-compute)
        print("Registering solution via Admin API to trigger auto-compute...")
        
        # PySpark and Pandas have slightly different syntax
        if challenge_type == "pyspark":
            ref_code = "result = employees_df.filter(employees_df.salary > 80000)"
            correct_code = "result = employees_df.filter(employees_df['salary'] > 80000)"
            incorrect_code = "result = employees_df.filter(employees_df['salary'] > 85000)"
        else:
            ref_code = "result = employees_df[employees_df['salary'] > 80000]"
            correct_code = "result = employees_df[employees_df['salary'] > 80000]"
            incorrect_code = "result = employees_df[employees_df['salary'] > 85000]"

        sol_response = await client.post(
            f"http://localhost:8000/admin/problems/{problem_id}/solution",
            headers={"X-Admin-Secret": "admin_secret"},
            json={
                "reference_code": ref_code,
                "order_sensitive": False,
                "notes": f"{challenge_type} filtering test"
            }
        )
        print("Admin solution save response:", sol_response.status_code, sol_response.text)
        
        # Verify cached output is in the DB
        output = await conn.fetchval("SELECT reference_output FROM core.problem_solutions WHERE problem_id = $1", problem_id)
        print("Pre-computed reference output in DB:", output)

        # 4. User Submission (Correct)
        print(f"\n--- Submitting CORRECT solution ---")
        correct_response = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": problem_id,
                "query": correct_code
            }
        )
        print("Correct submission response:", correct_response.status_code)
        correct_json = correct_response.json()
        print("Status:", correct_json.get("status"))
        print("User data:", correct_json.get("user"))
        print("Expected data:", correct_json.get("expected"))

        # 5. User Submission (Incorrect)
        print(f"\n--- Submitting INCORRECT solution ---")
        incorrect_response = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": problem_id,
                "query": incorrect_code
            }
        )
        print("Incorrect submission response:", incorrect_response.status_code)
        incorrect_json = incorrect_response.json()
        print("Status:", incorrect_json.get("status"))
        print("Diff Reason:", incorrect_json.get("diff_reason"))

        # 6. User Submission (Security blocked - forbidden import)
        print(f"\n--- Submitting FORBIDDEN import (AST validation) ---")
        blocked_response = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": problem_id,
                "query": "import subprocess\nresult = employees_df"
            }
        )
        print("Blocked submission response (AST):", blocked_response.status_code, blocked_response.text)

    # Cleanup
    print("\nCleaning up test data...")
    await conn.execute("DELETE FROM core.problem_solutions WHERE problem_id = $1", problem_id)
    await conn.execute("DELETE FROM core.problem_datasets WHERE problem_id = $1", problem_id)
    await conn.execute("DELETE FROM core.problems WHERE id = $1", problem_id)
    await conn.close()
    print(f"FINISHED testing {challenge_type.upper()}")

async def main():
    # Test Python
    await test_challenge("python")
    # Test PySpark
    await test_challenge("pyspark")

if __name__ == "__main__":
    asyncio.run(main())
