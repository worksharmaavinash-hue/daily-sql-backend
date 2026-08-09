import urllib.request
import json

BASE_URL = "http://localhost:8000"
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
    print("🚀 Seeding a dual-SQL script problem on local dev...")
    
    # 1. Create problem
    problem_data = {
        "title": "Dual SQL Local Test",
        "difficulty": "easy",
        "description": "Select all rows from users_local.",
        "estimated_time_minutes": 10
    }
    prob_res = post_json(f"{BASE_URL}/admin/problems", problem_data)
    if not prob_res:
        print("Failed to create problem")
        return
    
    problem_id = prob_res["problem_id"]
    print(f"✅ Created problem: {problem_id}")
    
    # 2. Add dual-SQL datasets
    dataset_data = {
        "table_name": "users_local",
        "schema_sql": """CREATE TABLE users_local (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        );""",
        "seed_sql": """INSERT INTO users_local (name) VALUES ('Alice'), ('Bob');""",
        "mysql_schema_sql": """CREATE TABLE users_local (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        );""",
        "mysql_seed_sql": """INSERT INTO users_local (name) VALUES ('Alice'), ('Bob');""",
        "column_types": {"id": "int", "name": "varchar"},
    }
    ds_res = post_json(f"{BASE_URL}/admin/problems/{problem_id}/datasets", dataset_data)
    if not ds_res:
        print("Failed to add dataset")
        return
    print("✅ Created dual-SQL datasets")
    
    # 3. Add solution
    sol_data = {
        "reference_query": "SELECT * FROM users_local ORDER BY id ASC;",
        "mysql_reference_query": None,
        "order_sensitive": True,
        "notes": "Simple select test"
    }
    sol_res = post_json(f"{BASE_URL}/admin/problems/{problem_id}/solution", sol_data)
    if not sol_res:
        print("Failed to save solution")
        return
    print("✅ Saved solution")
    
    print("\n🎉 Seeding complete. Problem ID:", problem_id)

if __name__ == "__main__":
    main()
