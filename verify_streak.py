import urllib.request
import json
import time

BASE_URL = "http://localhost:8000"

def get_json(url):
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"GET {url} failed: {e.code} {e.read().decode('utf-8')}")
        return None

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
    data = {"problem_id": problem_id, "query": query}
    try:
        req = urllib.request.Request(
            url, 
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
         print(f"EXECUTE failed: {e.code} {e.read().decode('utf-8')}")
         return None

def main():
    try:
        print("Checking initial streak...")
        streak = get_json(f"{BASE_URL}/me/streak")
        print(f"Initial Streak: {streak}")
        
        # 1. Setup Problem
        print("\nSetting up problem...")
        p_resp = post_json(f"{BASE_URL}/admin/problems", {
            "title": "Streak Test Problem",
            "difficulty": "easy",
            "description": "Streak test",
            "estimated_time_minutes": 5
        })
        problem_id = p_resp["problem_id"]
        
        post_json(f"{BASE_URL}/admin/problems/{problem_id}/datasets", {
            "table_name": "items",
            "schema_sql": "CREATE TABLE items (id INT);",
            "seed_sql": "INSERT INTO items VALUES (1);",
            "sample_rows": [{"id": 1}]
        })
        
        post_json(f"{BASE_URL}/admin/problems/{problem_id}/solution", {
            "reference_query": "SELECT * FROM items;",
            "order_sensitive": False,
            "notes": "Simple select"
        })
        
        # 2. Correct Submission
        print("\nSubmitting CORRECT Query...")
        res = execute_query(problem_id, "SELECT * FROM items;")
        print(f"Result Status: {res.get('status')}")
        
        # 3. Check Streak
        streak = get_json(f"{BASE_URL}/me/streak")
        print(f"Streak after correct: {streak}")
        
        # 4. Check Attempts
        attempts = get_json(f"{BASE_URL}/me/attempts/today")
        print(f"Attempts today: {len(attempts)}")
        if attempts:
            print(f"Latest attempt: {attempts[0]['status']} on {attempts[0]['problem_id']}")
            
        # 5. Incorrect Submission
        print("\nSubmitting INCORRECT Query...")
        execute_query(problem_id, "SELECT * FROM items WHERE id=999;")
        
        # 6. Check Attempts again
        attempts = get_json(f"{BASE_URL}/me/attempts/today")
        print(f"Attempts today: {len(attempts)}")
        # Note: UPSERT logic means one attempt per problem per day replaces the status?
        # Let's check the service.py:
        # ON CONFLICT (user_id, problem_id, attempt_date) DO UPDATE SET status = EXCLUDED.status
        # Yes! It overwrites. So if I submit incorrect after correct, it might show incorrect?
        # If so, does streak revert? Streak table is separate.
        # Streak only increments. It doesn't decrement on incorrect (unless date missed).
        # But core.attempts will show the LATEST status.
        
        streak = get_json(f"{BASE_URL}/me/streak")
        print(f"Streak after incorrect: {streak}")

    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    main()
