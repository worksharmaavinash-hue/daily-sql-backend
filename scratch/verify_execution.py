import urllib.request
import json

BASE_URL = "http://localhost:8001"
PROBLEM_ID = "ae04d618-b923-4fb2-b3a1-271f7ff6fc50" # Created dual-dialect problem ID

def execute_query(query, dialect):
    url = f"{BASE_URL}/execute"
    payload = {
        "problem_id": PROBLEM_ID,
        "query": query,
        "mode": "submit",
        "sql_dialect": dialect
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"Error executing for {dialect}: {e}")
        if hasattr(e, 'read'):
            try:
                print("Response:", e.read().decode('utf-8'))
            except:
                pass
        return None

def main():
    print(f"🧪 Testing execution for dual-dialect problem: {PROBLEM_ID}...\n")
    
    # 1. Test PostgreSQL execution
    print("🐘 Testing PostgreSQL execution...")
    pg_res = execute_query("SELECT * FROM users_test ORDER BY id ASC;", "postgresql")
    if pg_res:
        print(f"Status: {pg_res.get('status')}")
        print(f"Columns: {pg_res.get('user', {}).get('columns')}")
        print(f"Rows: {pg_res.get('user', {}).get('rows')}")
        print(f"Error: {pg_res.get('error')}")
    else:
        print("PG Execution Failed")
        
    print("\n" + "-"*40 + "\n")
        
    # 2. Test MySQL execution
    print("🐬 Testing MySQL execution...")
    my_res = execute_query("SELECT * FROM users_test ORDER BY id ASC;", "mysql")
    if my_res:
        print(f"Status: {my_res.get('status')}")
        print(f"Columns: {my_res.get('user', {}).get('columns')}")
        print(f"Rows: {my_res.get('user', {}).get('rows')}")
        print(f"Error: {my_res.get('error')}")
    else:
        print("MySQL Execution Failed")

if __name__ == "__main__":
    main()
