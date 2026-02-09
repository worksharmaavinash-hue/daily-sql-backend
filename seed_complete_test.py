"""
Complete Test Data Seeder for DailySQL
Creates 3 problems (Easy, Medium, Advanced) with full datasets and solutions
"""
import urllib.request
import json
from datetime import date

BASE_URL = "http://localhost:8000"
ADMIN_SECRET = "admin_secret"

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'X-Admin-Secret': ADMIN_SECRET
        }
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"Error: {e}")
        return None

# ============================================================
# PROBLEM 1: EASY - Basic SELECT with WHERE
# ============================================================
easy_problem = {
    "title": "Find Active Users",
    "difficulty": "easy",
    "description": """## Problem

You have a `users` table containing user information.

Write a SQL query to find all **active users** who joined in **2024 or later**.

### Expected Output Columns:
- `name` - User's name
- `email` - User's email
- `joined_date` - Date they joined

Order the results by `joined_date` in descending order (newest first).

### Hint
Use the `WHERE` clause to filter by `status` and `joined_date`.
""",
    "estimated_time_minutes": 5
}

easy_datasets = [
    {
        "table_name": "users",
        "schema_sql": """CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    joined_date DATE NOT NULL
);""",
        "seed_sql": """INSERT INTO users (name, email, status, joined_date) VALUES
('Alice Johnson', 'alice@email.com', 'active', '2024-03-15'),
('Bob Smith', 'bob@email.com', 'inactive', '2024-01-10'),
('Charlie Brown', 'charlie@email.com', 'active', '2023-12-01'),
('Diana Ross', 'diana@email.com', 'active', '2024-06-20'),
('Eve Wilson', 'eve@email.com', 'active', '2024-02-28'),
('Frank Miller', 'frank@email.com', 'suspended', '2024-04-05'),
('Grace Lee', 'grace@email.com', 'active', '2023-08-15');""",
        "sample_rows": [
            {"id": 1, "name": "Alice Johnson", "email": "alice@email.com", "status": "active", "joined_date": "2024-03-15"},
            {"id": 2, "name": "Bob Smith", "email": "bob@email.com", "status": "inactive", "joined_date": "2024-01-10"},
            {"id": 3, "name": "Charlie Brown", "email": "charlie@email.com", "status": "active", "joined_date": "2023-12-01"},
            {"id": 4, "name": "Diana Ross", "email": "diana@email.com", "status": "active", "joined_date": "2024-06-20"},
            {"id": 5, "name": "Eve Wilson", "email": "eve@email.com", "status": "active", "joined_date": "2024-02-28"}
        ]
    }
]

easy_solution = {
    "reference_query": """SELECT name, email, joined_date
FROM users
WHERE status = 'active' AND joined_date >= '2024-01-01'
ORDER BY joined_date DESC;""",
    "order_sensitive": True,
    "notes": "Expected 3 rows: Diana (2024-06-20), Alice (2024-03-15), Eve (2024-02-28)"
}


# ============================================================
# PROBLEM 2: MEDIUM - JOIN with Aggregation
# ============================================================
medium_problem = {
    "title": "Top Spending Customers",
    "difficulty": "medium",
    "description": """## Problem

You have two tables: `customers` and `orders`.

Write a SQL query to find the **top 3 customers** by total spending.

### Expected Output Columns:
- `customer_name` - Name of the customer
- `total_orders` - Number of orders placed
- `total_spent` - Sum of all order amounts

Only include customers who have placed **at least 2 orders**.
Order by `total_spent` in descending order.

### Hint
You'll need to use `JOIN`, `GROUP BY`, `HAVING`, and `ORDER BY` with `LIMIT`.
""",
    "estimated_time_minutes": 10
}

medium_datasets = [
    {
        "table_name": "customers",
        "schema_sql": """CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    city VARCHAR(100)
);""",
        "seed_sql": """INSERT INTO customers (name, email, city) VALUES
('John Doe', 'john@shop.com', 'New York'),
('Jane Smith', 'jane@shop.com', 'Los Angeles'),
('Mike Johnson', 'mike@shop.com', 'Chicago'),
('Sarah Williams', 'sarah@shop.com', 'Houston'),
('Tom Brown', 'tom@shop.com', 'Phoenix');""",
        "sample_rows": [
            {"id": 1, "name": "John Doe", "email": "john@shop.com", "city": "New York"},
            {"id": 2, "name": "Jane Smith", "email": "jane@shop.com", "city": "Los Angeles"},
            {"id": 3, "name": "Mike Johnson", "email": "mike@shop.com", "city": "Chicago"},
            {"id": 4, "name": "Sarah Williams", "email": "sarah@shop.com", "city": "Houston"},
            {"id": 5, "name": "Tom Brown", "email": "tom@shop.com", "city": "Phoenix"}
        ]
    },
    {
        "table_name": "orders",
        "schema_sql": """CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    amount DECIMAL(10,2) NOT NULL,
    order_date DATE NOT NULL
);""",
        "seed_sql": """INSERT INTO orders (customer_id, amount, order_date) VALUES
(1, 150.00, '2024-01-15'),
(1, 200.00, '2024-02-20'),
(1, 75.50, '2024-03-10'),
(2, 300.00, '2024-01-25'),
(2, 450.00, '2024-02-15'),
(3, 50.00, '2024-01-05'),
(4, 125.00, '2024-02-01'),
(4, 175.00, '2024-02-28'),
(4, 225.00, '2024-03-15'),
(5, 80.00, '2024-01-30');""",
        "sample_rows": [
            {"id": 1, "customer_id": 1, "amount": 150.00, "order_date": "2024-01-15"},
            {"id": 2, "customer_id": 1, "amount": 200.00, "order_date": "2024-02-20"},
            {"id": 3, "customer_id": 1, "amount": 75.50, "order_date": "2024-03-10"},
            {"id": 4, "customer_id": 2, "amount": 300.00, "order_date": "2024-01-25"},
            {"id": 5, "customer_id": 2, "amount": 450.00, "order_date": "2024-02-15"}
        ]
    }
]

medium_solution = {
    "reference_query": """SELECT 
    c.name AS customer_name,
    COUNT(o.id) AS total_orders,
    SUM(o.amount) AS total_spent
FROM customers c
JOIN orders o ON c.id = o.customer_id
GROUP BY c.id, c.name
HAVING COUNT(o.id) >= 2
ORDER BY total_spent DESC
LIMIT 3;""",
    "order_sensitive": True,
    "notes": "Expected: Jane Smith (750.00), Sarah Williams (525.00), John Doe (425.50)"
}


# ============================================================
# PROBLEM 3: ADVANCED - Window Functions & Subqueries
# ============================================================
advanced_problem = {
    "title": "Employee Salary Ranking by Department",
    "difficulty": "advanced",
    "description": """## Problem

You have an `employees` table with salary information.

Write a SQL query to rank employees within each department by their salary.

### Expected Output Columns:
- `department` - Department name
- `employee_name` - Name of the employee
- `salary` - Employee's salary
- `dept_rank` - Rank within department (1 = highest salary)
- `salary_diff_from_top` - Difference from highest salary in that department

Order by department (alphabetically), then by rank.

### Hint
Use `RANK()` or `ROW_NUMBER()` window functions with `PARTITION BY`.
For the salary difference, you can use `MAX() OVER (PARTITION BY ...)`.
""",
    "estimated_time_minutes": 15
}

advanced_datasets = [
    {
        "table_name": "employees",
        "schema_sql": """CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    department VARCHAR(50) NOT NULL,
    salary DECIMAL(10,2) NOT NULL,
    hire_date DATE NOT NULL
);""",
        "seed_sql": """INSERT INTO employees (name, department, salary, hire_date) VALUES
('Alice Chen', 'Engineering', 95000.00, '2022-03-15'),
('Bob Kumar', 'Engineering', 85000.00, '2023-01-10'),
('Carol White', 'Engineering', 110000.00, '2020-06-01'),
('David Lee', 'Engineering', 75000.00, '2023-08-20'),
('Emma Davis', 'Marketing', 72000.00, '2022-05-12'),
('Frank Miller', 'Marketing', 68000.00, '2023-02-28'),
('Grace Park', 'Marketing', 82000.00, '2021-09-15'),
('Henry Wilson', 'Sales', 65000.00, '2023-04-01'),
('Ivy Johnson', 'Sales', 78000.00, '2022-11-10'),
('Jack Brown', 'Sales', 71000.00, '2023-06-15');""",
        "sample_rows": [
            {"id": 1, "name": "Alice Chen", "department": "Engineering", "salary": 95000.00, "hire_date": "2022-03-15"},
            {"id": 2, "name": "Bob Kumar", "department": "Engineering", "salary": 85000.00, "hire_date": "2023-01-10"},
            {"id": 3, "name": "Carol White", "department": "Engineering", "salary": 110000.00, "hire_date": "2020-06-01"},
            {"id": 5, "name": "Emma Davis", "department": "Marketing", "salary": 72000.00, "hire_date": "2022-05-12"},
            {"id": 8, "name": "Henry Wilson", "department": "Sales", "salary": 65000.00, "hire_date": "2023-04-01"}
        ]
    }
]

advanced_solution = {
    "reference_query": """SELECT 
    department,
    name AS employee_name,
    salary,
    RANK() OVER (PARTITION BY department ORDER BY salary DESC) AS dept_rank,
    MAX(salary) OVER (PARTITION BY department) - salary AS salary_diff_from_top
FROM employees
ORDER BY department, dept_rank;""",
    "order_sensitive": True,
    "notes": "Uses RANK() and MAX() window functions. Engineering has 4 rows, Marketing has 3, Sales has 3."
}


# ============================================================
# MAIN SEEDER
# ============================================================
def create_full_problem(problem_data, datasets, solution):
    """Create a problem with all its datasets and solution"""
    print(f"\n📝 Creating: {problem_data['title']}")
    
    # 1. Create problem
    result = post_json(f"{BASE_URL}/admin/problems", problem_data)
    if not result:
        print("   ❌ Failed to create problem")
        return None
    
    problem_id = result['problem_id']
    print(f"   ✅ Problem ID: {problem_id[:8]}...")
    
    # 2. Add datasets
    for ds in datasets:
        ds_result = post_json(f"{BASE_URL}/admin/problems/{problem_id}/datasets", ds)
        if ds_result:
            print(f"   ✅ Dataset: {ds['table_name']}")
        else:
            print(f"   ❌ Failed: {ds['table_name']}")
    
    # 3. Add solution
    sol_result = post_json(f"{BASE_URL}/admin/problems/{problem_id}/solution", solution)
    if sol_result:
        print(f"   ✅ Solution saved")
    else:
        print(f"   ❌ Failed to save solution")
    
    return problem_id


def main():
    print("=" * 60)
    print("🚀 DailySQL Complete Test Data Seeder")
    print("=" * 60)
    
    # Create all problems
    easy_id = create_full_problem(easy_problem, easy_datasets, easy_solution)
    medium_id = create_full_problem(medium_problem, medium_datasets, medium_solution)
    advanced_id = create_full_problem(advanced_problem, advanced_datasets, advanced_solution)
    
    if easy_id and medium_id and advanced_id:
        # Schedule for today
        today = date.today().isoformat()
        schedule_data = {
            "date": today,
            "easy_problem_id": easy_id,
            "medium_problem_id": medium_id,
            "advanced_problem_id": advanced_id
        }
        
        result = post_json(f"{BASE_URL}/admin/daily-practice", schedule_data)
        if result:
            print(f"\n📅 Scheduled for {today}!")
        else:
            print("\n❌ Failed to schedule")
    
    print("\n" + "=" * 60)
    print("✅ DONE! Test data created successfully.")
    print("=" * 60)
    print(f"""
📋 PROBLEM SUMMARY:

1. EASY: Find Active Users
   - Filter users by status and date
   - Expected: 3 rows
   
2. MEDIUM: Top Spending Customers  
   - JOIN, GROUP BY, HAVING
   - Expected: 3 rows

3. ADVANCED: Employee Salary Ranking
   - Window functions (RANK, MAX OVER)
   - Expected: 10 rows

🧪 TEST SOLUTIONS:

EASY:
SELECT name, email, joined_date
FROM users
WHERE status = 'active' AND joined_date >= '2024-01-01'
ORDER BY joined_date DESC;

MEDIUM:
SELECT 
    c.name AS customer_name,
    COUNT(o.id) AS total_orders,
    SUM(o.amount) AS total_spent
FROM customers c
JOIN orders o ON c.id = o.customer_id
GROUP BY c.id, c.name
HAVING COUNT(o.id) >= 2
ORDER BY total_spent DESC
LIMIT 3;

ADVANCED:
SELECT 
    department,
    name AS employee_name,
    salary,
    RANK() OVER (PARTITION BY department ORDER BY salary DESC) AS dept_rank,
    MAX(salary) OVER (PARTITION BY department) - salary AS salary_diff_from_top
FROM employees
ORDER BY department, dept_rank;
""")


if __name__ == "__main__":
    main()
