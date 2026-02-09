import urllib.request
import json

url = "http://localhost:8000/execute"
data = {
    "problem_id": "test",
    "query": "SELECT * FROM users"
}

req = urllib.request.Request(
    url, 
    data=json.dumps(data).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

try:
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode('utf-8'))
except Exception as e:
    print(e)
