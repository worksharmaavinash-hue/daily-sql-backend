import urllib.request
import json
import datetime
from datetime import timedelta

BASE_URL = "http://localhost:8000"

def get_json(url):
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"GET {url} failed: {e}")
        return None

def post_json(url, data):
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"POST {url} failed: {e}")
        return None

def seed_datasets_for_problem(problem_id):
    if not problem_id: return
    
    # 1. Add Users Table
    post_json(f"{BASE_URL}/admin/problems/{problem_id}/datasets", {
        "table_name": "users",
        "schema_sql": "CREATE TABLE users (id INT, name TEXT, email TEXT);",
        "seed_sql": "INSERT INTO users VALUES (1, 'Alice', 'alice@example.com'), (2, 'Bob', 'bob@example.com');",
        "sample_rows": [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
            {"id": 2, "name": "Bob", "email": "bob@example.com"}
        ]
    })
    
    # 2. Add Orders Table
    post_json(f"{BASE_URL}/admin/problems/{problem_id}/datasets", {
        "table_name": "orders",
        "schema_sql": "CREATE TABLE orders (id INT, user_id INT, amount DECIMAL);",
        "seed_sql": "INSERT INTO orders VALUES (100, 1, 50.00), (101, 1, 20.00), (102, 2, 100.00);",
        "sample_rows": [
            {"id": 100, "user_id": 1, "amount": 50.00},
            {"id": 101, "user_id": 1, "amount": 20.00}
        ]
    })
    print(f"Seeded datasets for {problem_id}")

def main():
    # Attempt to get today's practice
    today_practice = get_json(f"{BASE_URL}/practice/today")
    
    if today_practice:
        print("Found practice for today, seeding datasets...")
        seed_datasets_for_problem(today_practice.get("easy"))
        seed_datasets_for_problem(today_practice.get("medium"))
        seed_datasets_for_problem(today_practice.get("advanced"))
    else:
        print("No practice found for today to attach datasets to.")

if __name__ == "__main__":
    main()
