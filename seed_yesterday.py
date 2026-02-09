import urllib.request
import json
import datetime
from datetime import timedelta

BASE_URL = "http://localhost:8000"

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def main():
    try:
        # We need PROBLEM IDs. 
        # Since I don't have them easily, I'll just CREATE NEW ones for "Yesterday's Set"
        # Ideally we'd query them, but the admin API doesn't have a 'list problems' endpoint exposed easily here.
        # So I'll just create new identical ones. It's fine for dev.

        e_resp = post_json(f"{BASE_URL}/admin/problems", {
            "title": "Easy Problem (Timezone Fix)", "difficulty": "easy", 
            "description": "Fixing Timezone Gap", "estimated_time_minutes": 5
        })
        m_resp = post_json(f"{BASE_URL}/admin/problems", {
            "title": "Medium Problem (Timezone Fix)", "difficulty": "medium", 
            "description": "Fixing Timezone Gap", "estimated_time_minutes": 10
        })
        a_resp = post_json(f"{BASE_URL}/admin/problems", {
            "title": "Adv Problem (Timezone Fix)", "difficulty": "advanced", 
            "description": "Fixing Timezone Gap", "estimated_time_minutes": 15
        })

        # Seed for YESTERDAY (Jan 30 if today is Jan 31)
        yesterday = (datetime.date.today() - timedelta(days=1)).isoformat()
        
        print(f"Seeding for yesterday: {yesterday}")

        sched_resp = post_json(f"{BASE_URL}/admin/daily-practice", {
            "date": yesterday,
            "easy_problem_id": e_resp["problem_id"],
            "medium_problem_id": m_resp["problem_id"],
            "advanced_problem_id": a_resp["problem_id"]
        })
        print(f"Schedule: {sched_resp}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
