import asyncio
import os
import json
import uuid
import asyncpg
import httpx

DATABASE_URL = "postgres://postgres:postgres@postgres:5432/dailysql"

async def test_e2e():
    print("Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)
    print("Connected.")

    problem_id = str(uuid.uuid4())
    print(f"Creating mock Python problem with ID: {problem_id}")
    
    # 1. Insert Python problem
    await conn.execute("""
        INSERT INTO core.problems (id, title, difficulty, description, estimated_time_minutes, is_active, challenge_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, problem_id, "Filter Salaries", "easy", "Filter employees with salary > 80000", 10, True, "python")

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

    # 3. Create Solution (via admin POST API to trigger auto-compute)
    print("Registering solution via Admin API to trigger auto-compute...")
    async with httpx.AsyncClient() as client:
        # Create solution
        sol_response = await client.post(
            f"http://localhost:8000/admin/problems/{problem_id}/solution",
            headers={"X-Admin-Secret": "admin_secret"},
            json={
                "reference_code": "result = employees_df[employees_df['salary'] > 80000]",
                "order_sensitive": False,
                "notes": "Pandas filtering test"
            }
        )
        print("Admin solution save response:", sol_response.status_code, sol_response.text)
        
        # Verify cached output is in the DB
        output = await conn.fetchval("SELECT reference_output FROM core.problem_solutions WHERE problem_id = $1", problem_id)
        print("Pre-computed reference output in DB:", output)

        # 4. User Submission (Correct)
        print("\n--- Submitting CORRECT solution ---")
        correct_response = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": problem_id,
                "query": "result = employees_df[employees_df['salary'] > 80000]"
            }
        )
        print("Correct submission response:", correct_response.status_code)
        correct_json = correct_response.json()
        print("Status:", correct_json.get("status"))
        print("User data:", correct_json.get("user"))
        print("Expected data:", correct_json.get("expected"))

        # 5. User Submission (Incorrect)
        print("\n--- Submitting INCORRECT solution ---")
        incorrect_response = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": problem_id,
                "query": "result = employees_df[employees_df['salary'] > 85000]"
            }
        )
        print("Incorrect submission response:", incorrect_response.status_code)
        incorrect_json = incorrect_response.json()
        print("Status:", incorrect_json.get("status"))
        print("Diff Reason:", incorrect_json.get("diff_reason"))

        # 6. User Submission (Security blocked - forbidden import)
        print("\n--- Submitting FORBIDDEN import (AST validation) ---")
        blocked_response = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": problem_id,
                "query": "import os\nresult = employees_df"
            }
        )
        print("Blocked submission response (AST):", blocked_response.status_code, blocked_response.text)

        # 7. User Submission (Timeout limit)
        print("\n--- Submitting TIMEOUT code (Docker limit) ---")
        timeout_response = await client.post(
            "http://localhost:8000/execute",
            json={
                "problem_id": problem_id,
                "query": "import time\nwhile True:\n    time.sleep(1)\nresult = employees_df"
            }
        )
        print("Timeout submission response (Docker):", timeout_response.status_code, timeout_response.text)

    # Cleanup
    print("\nCleaning up test data...")
    await conn.execute("DELETE FROM core.problem_solutions WHERE problem_id = $1", problem_id)
    await conn.execute("DELETE FROM core.problem_datasets WHERE problem_id = $1", problem_id)
    await conn.execute("DELETE FROM core.problems WHERE id = $1", problem_id)
    await conn.close()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(test_e2e())
