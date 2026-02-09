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
        print("Creating problem...")
        problem_payload = {
            "title": "Runner Test Problem",
            "difficulty": "easy",
            "description": "Test runner",
            "estimated_time_minutes": 5
        }
        p_resp = post_json(f"{BASE_URL}/admin/problems", problem_payload)
        problem_id = p_resp["problem_id"]
        print(f"Problem ID: {problem_id}")

        # 2. Add Dataset
        print("Adding dataset...")
        dataset_payload = {
            "table_name": "users",
            "schema_sql": "CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT, age INT);",
            "seed_sql": "INSERT INTO users (name, age) VALUES ('Alice', 30), ('Bob', 25);",
            "sample_rows": [{"id": 1, "name": "Alice", "age": 30}]
        }
        post_json(f"{BASE_URL}/admin/problems/{problem_id}/datasets", dataset_payload)
        print("Dataset added.")

        # 3. Test Valid Query
        print("\nTest 1: Valid Query")
        res1 = execute_query(problem_id, "SELECT * FROM users ORDER BY id")
        print(json.dumps(res1, indent=2))
        
        # 4. Test SQL Error
        print("\nTest 2: SQL Error")
        res2 = execute_query(problem_id, "SELECT * FROM non_existent")
        print(json.dumps(res2, indent=2))

        # 5. Test Timeout (Recursive CTE to hang)
        print("\nTest 3: Timeout simulation")
        # Try a query that takes > 1s. Simple sleep might be easier if permitted, but let's try a cross join or recursive
        # Using pg_sleep if allowed, or cross join
        # Our validator only allows SELECT/WITH.
        # "SELECT pg_sleep(2)" should timeout if limit is 1000ms
        res3 = execute_query(problem_id, "SELECT pg_sleep(2)") 
        print(json.dumps(res3, indent=2))

    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    main()
