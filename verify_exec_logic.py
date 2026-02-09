import urllib.request
import json

BASE_URL = "http://localhost:8000"

def test_execute(problem_id, query):
    url = f"{BASE_URL}/execute"
    data = {
        "problem_id": problem_id,
        "query": query
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"Status: {resp.status}")
            print(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code}")
        print(e.read().decode('utf-8'))
    except Exception as e:
        print(f"Error: {e}")

print("Test 1: Invalid ID")
test_execute("invalid-id", "SELECT 1")

print("\nTest 2: Valid ID (from previous step)")
# You need a valid UUID here. Ideally fetch one first.
# For now, let's try to fetch today's practice easy problem ID
try:
    with urllib.request.urlopen(f"{BASE_URL}/practice/today") as resp:
        today_data = json.loads(resp.read().decode('utf-8'))
        valid_id = today_data['easy']
        print(f"Using valid ID: {valid_id}")
        test_execute(valid_id, "SELECT * FROM transactions") # Assuming transactions table exists for this problem
except Exception as e:
    print(f"Could not fetch valid ID: {e}")
