import urllib.request
import json
import jwt
import time
import datetime
import sys

BASE_URL = "http://127.0.0.1:8000"
JWT_SECRET = "your_supabase_jwt_secret"

def create_token(user_id, email="test@example.com"):
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def call_api(endpoint, token=None, method="GET", data=None):
    url = f"{BASE_URL}{endpoint}"
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f"Bearer {token}"
    
    body = json.dumps(data).encode('utf-8') if data else None
    
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8'))
    except Exception as e:
        return 0, str(e)

def main():
    print("--- Auth & Rate Limit Verification (Updated) ---")
    sys.stdout.flush()
    
    try:
        # 1. No Token
        print("\n1. Test No Token")
        status, res = call_api("/execute", method="POST", data={"problem_id": "test", "query": "SELECT 1"})
        print(f"Status: {status} (Expected 403/401)") 
        sys.stdout.flush()

        # 2. Invalid Token
        print("\n2. Test Invalid Token")
        status, res = call_api("/execute", token="invalid.token.here", method="POST", data={"problem_id": "test", "query": "SELECT 1"})
        print(f"Status: {status} (Expected 401)")
        sys.stdout.flush()

        # 3. Valid Token
        print("\n3. Test Valid Token")
        user_id = "11111111-1111-1111-1111-111111111111"
        token = create_token(user_id)
        status, res = call_api("/execute", token=token, method="POST", data={"problem_id": "invalid-id", "query": "SELECT 1"})
        print(f"Status: {status} (Expected 404/400 not 401)")
        sys.stdout.flush()

        # 4. Rate Limit
        print("\n4. Test Rate Limit (20 reqs)")
        print(f"Using Token: {token[:10]}...")
        start = time.time()
        blocked = False
        for i in range(25):
            status, res = call_api("/execute", token=token, method="POST", data={"problem_id": "invalid-id", "query": "SELECT 1"})
            print(f"Req {i+2}: Status {status}")
            if status == 429:
                print("Rate limit hit successfully!")
                blocked = True
                break
        
        if not blocked:
            print("❌ Rate limit NOT hit - check Redis config/logs")
    except Exception as e:
        print(f"CRITICAL FAILURE: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
