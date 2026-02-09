import urllib.request
import json
import uuid

BASE_URL = "http://localhost:8000"

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def execute_query(problem_id, query):
    url = f"{BASE_URL}/execute"
    data = {
        "problem_id": problem_id,
        "query": query
    }
    try:
        req = urllib.request.Request(
            url, 
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"Error executing query: {e}")
        return None

def main():
    try:
        # 1. Create a problem
        print("Creating problem (Validation Test)...")
        problem_payload = {
            "title": "Validation Problem",
            "difficulty": "easy",
            "description": "Validation test",
            "estimated_time_minutes": 5
        }
        p_resp = post_json(f"{BASE_URL}/admin/problems", problem_payload)
        problem_id = p_resp["problem_id"]
        print(f"Problem ID: {problem_id}")

        # 2. Add Dataset
        dataset_payload = {
            "table_name": "employees",
            "schema_sql": "CREATE TABLE employees (id INT, name TEXT);",
            "seed_sql": "INSERT INTO employees VALUES (1, 'Alice'), (2, 'Bob');",
            "sample_rows": [{"id": 1, "name": "Alice"}]
        }
        post_json(f"{BASE_URL}/admin/problems/{problem_id}/datasets", dataset_payload)
        
        # 3. Add Solution (CRITICAL)
        sol_payload = {
            "reference_query": "SELECT * FROM employees ORDER BY id;",
            "order_sensitive": False,
            "notes": "Simple select"
        }
        post_json(f"{BASE_URL}/admin/problems/{problem_id}/solution", sol_payload)
        print("Dataset and solution added.")

        # 4. Test Correct
        print("\nTest 1: Correct Query")
        res1 = execute_query(problem_id, "SELECT * FROM employees ORDER BY id;")
        print(f"Status: {res1.get('status')}")
        if res1.get('status') != 'correct':
             print(json.dumps(res1, indent=2))

        # 5. Test Incorrect (Different Data)
        print("\nTest 2: Incorrect Query")
        res2 = execute_query(problem_id, "SELECT * FROM employees WHERE id = 1;")
        print(f"Status: {res2.get('status')}")
        print(f"Diff Reason: {res2.get('diff_reason')}")
        
        # 6. Test Error
        print("\nTest 3: Syntax Error")
        res3 = execute_query(problem_id, "SELECT * FROM nothing;")
        print(f"Status: {res3.get('status')}")
        print(f"Error: {res3.get('error')}")

    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    main()
