import requests
import datetime
from uuid import UUID

BASE_URL = "http://localhost:8000"

def create_problem(title, difficulty, minutes):
    resp = requests.post(f"{BASE_URL}/admin/problems", json={
        "title": title,
        "difficulty": difficulty,
        "description": f"Description for {title}",
        "estimated_time_minutes": minutes
    })
    resp.raise_for_status()
    print(f"Created {title}: {resp.json()}")
    return resp.json()["problem_id"]

def schedule_practice(easy_id, medium_id, advanced_id):
    today = datetime.date.today().isoformat()
    resp = requests.post(f"{BASE_URL}/admin/daily-practice", json={
        "date": today,
        "easy_problem_id": easy_id,
        "medium_problem_id": medium_id,
        "advanced_problem_id": advanced_id
    })
    print(f"Schedule response: {resp.text}")
    resp.raise_for_status()

def main():
    try:
        e_id = create_problem("Easy Problem", "easy", 5)
        m_id = create_problem("Medium Problem", "medium", 10)
        a_id = create_problem("Advanced Problem", "advanced", 15)
        
        schedule_practice(e_id, m_id, a_id)
        
        # Verify user API
        resp = requests.get(f"{BASE_URL}/practice/today")
        resp.raise_for_status()
        print(f"User API Practice Today: {resp.json()}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
