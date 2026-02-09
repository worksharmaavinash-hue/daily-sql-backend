import urllib.request
import json
import datetime

BASE_URL = "http://localhost:8000"

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def get_json(url):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode('utf-8'))

def main():
    try:
        # Create problems
        e_resp = post_json(f"{BASE_URL}/admin/problems", {
            "title": "Easy Problem", "difficulty": "easy", 
            "description": "Desc", "estimated_time_minutes": 5
        })
        print(f"Easy: {e_resp}")
        
        m_resp = post_json(f"{BASE_URL}/admin/problems", {
            "title": "Medium Problem", "difficulty": "medium", 
            "description": "Desc", "estimated_time_minutes": 10
        })
        print(f"Medium: {m_resp}")

        a_resp = post_json(f"{BASE_URL}/admin/problems", {
            "title": "Advanced Problem", "difficulty": "advanced", 
            "description": "Desc", "estimated_time_minutes": 15
        })
        print(f"Advanced: {a_resp}")
        
        # Schedule
        today = datetime.date.today().isoformat()
        sched_resp = post_json(f"{BASE_URL}/admin/daily-practice", {
            "date": today,
            "easy_problem_id": e_resp["problem_id"],
            "medium_problem_id": m_resp["problem_id"],
            "advanced_problem_id": a_resp["problem_id"]
        })
        print(f"Schedule: {sched_resp}")
        
        # Verify
        user_resp = get_json(f"{BASE_URL}/practice/today")
        print(f"User API: {user_resp}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
