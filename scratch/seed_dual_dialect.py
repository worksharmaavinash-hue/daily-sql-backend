import urllib.request
import json

BASE_URL = "http://localhost:8001"
ADMIN_SECRET = "admin_secret"

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'X-Admin-Secret': ADMIN_SECRET
        }
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"Error: {e}")
        if hasattr(e, 'read'):
            try:
                print("Response detail:", e.read().decode('utf-8'))
            except:
                pass
        return None

def main():
    print("🚀 Seeding a dual-dialect SQL problem...")
    
    # 1. Create problem
    problem_data = {
        "title": "Dual Dialect Users Test",
        "difficulty": "easy",
        "description": "Write a SQL query to select all records from users_test table.",
        "estimated_time_minutes": 10
    }
    prob_res = post_json(f"{BASE_URL}/admin/problems", problem_data)
    if not prob_res:
        print("Failed to create problem")
        return
    
    problem_id = prob_res["problem_id"]
    print(f"✅ Created problem: {problem_id}")
    
    # 2. Add dual-dialect dataset
    dataset_data = {
        "table_name": "users_test",
        "schema_sql": "",
        "seed_sql": "",
        "column_types": {"id": "int", "name": "varchar"},
        "seed_data_json": {
            "columns": [
                { "name": "id", "type": "integer", "primary_key": True, "auto_increment": True },
                { "name": "name", "type": "varchar", "length": 100, "nullable": False }
            ],
            "rows": [
                [1, "Alice"],
                [2, "Bob"]
            ]
        }
    }
    ds_res = post_json(f"{BASE_URL}/admin/problems/{problem_id}/datasets", dataset_data)
    if not ds_res:
        print("Failed to add dataset")
        return
    print("✅ Created dual-dialect dataset")
    
    # 3. Add solution
    sol_data = {
        "reference_query": "SELECT * FROM users_test ORDER BY id ASC;",
        "mysql_reference_query": None, # falls back to reference_query
        "order_sensitive": True,
        "notes": "Simple select"
    }
    sol_res = post_json(f"{BASE_URL}/admin/problems/{problem_id}/solution", sol_data)
    if not sol_res:
        print("Failed to save solution")
        return
    print("✅ Saved solution")
    
    # 4. Schedule practice for today
    sched_data = {
        "date": "2026-08-01",
        "easy_problem_id": problem_id,
        "medium_problem_id": problem_id,
        "advanced_problem_id": problem_id
    }
    post_json(f"{BASE_URL}/admin/daily-practice", sched_data)
    print("✅ Scheduled practice")
    
    print("\n🎉 Seeding complete. Problem ID:", problem_id)

if __name__ == "__main__":
    main()
