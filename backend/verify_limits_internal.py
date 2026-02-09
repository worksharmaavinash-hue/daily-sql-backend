import requests
import jwt
import datetime
import time

JWT_SECRET = "your_supabase_jwt_secret"
BASE_URL = "http://127.0.0.1:8000"

def create_token(user_id):
    payload = {"sub": user_id, "aud": "authenticated", "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def main():
    print("Testing Rate Limit internally...")
    user_id = "blocked_user"
    token = create_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}
    
    for i in range(25):
        try:
            resp = requests.post(
                f"{BASE_URL}/execute", 
                json={"problem_id": "invalid-id", "query": "SELECT 1"},
                headers=headers
            )
            print(f"Req {i+1}: {resp.status_code}")
            if resp.status_code == 429:
                print("BLOCKED!")
                return
        except Exception as e:
            print(f"Error: {e}")

    print("Rate limit NOT hit.")

if __name__ == "__main__":
    main()
