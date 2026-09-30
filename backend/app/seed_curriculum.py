import asyncio
import os
import json
import uuid
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/dailysql")

# ==============================================================================
# 50 SQL QUESTIONS DEFINITIONS
# ==============================================================================
def get_sql_questions():
    questions = []
    
    # 1 - 10: Basic Filtering & Aggregations (Easy)
    q1 = {
        "num": 1,
        "title": "1. SQL - Find All Active Customers",
        "difficulty": "easy",
        "est_time": 5,
        "description": "Select all active customers who have registered in the year 2024. Return columns `customer_id`, `name`, `email`, and `status` ordered by `customer_id` ASC.",
        "table_name": "customers",
        "schema_sql": """CREATE TABLE customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            status VARCHAR(20) NOT NULL,
            created_at TIMESTAMP NOT NULL
        );""",
        "seed_sql": """INSERT INTO customers (customer_id, name, email, status, created_at) VALUES
            (1, 'Alice Smith', 'alice@example.com', 'active', '2024-01-15 10:00:00'),
            (2, 'Bob Johnson', 'bob@example.com', 'inactive', '2024-02-10 12:30:00'),
            (3, 'Charlie Brown', 'charlie@example.com', 'active', '2024-03-05 09:15:00'),
            (4, 'Diana Prince', 'diana@example.com', 'active', '2023-11-20 14:00:00'),
            (5, 'Evan Wright', 'evan@example.com', 'pending', '2024-04-01 16:45:00');""",
        "mysql_schema_sql": """CREATE TABLE customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            status VARCHAR(20) NOT NULL,
            created_at DATETIME NOT NULL
        );""",
        "mysql_seed_sql": """INSERT INTO customers (customer_id, name, email, status, created_at) VALUES
            (1, 'Alice Smith', 'alice@example.com', 'active', '2024-01-15 10:00:00'),
            (2, 'Bob Johnson', 'bob@example.com', 'inactive', '2024-02-10 12:30:00'),
            (3, 'Charlie Brown', 'charlie@example.com', 'active', '2024-03-05 09:15:00'),
            (4, 'Diana Prince', 'diana@example.com', 'active', '2023-11-20 14:00:00'),
            (5, 'Evan Wright', 'evan@example.com', 'pending', '2024-04-01 16:45:00');""",
        "sample_rows": [
            {"customer_id": 1, "name": "Alice Smith", "email": "alice@example.com", "status": "active", "created_at": "2024-01-15T10:00:00"},
            {"customer_id": 2, "name": "Bob Johnson", "email": "bob@example.com", "status": "inactive", "created_at": "2024-02-10T12:30:00"},
            {"customer_id": 3, "name": "Charlie Brown", "email": "charlie@example.com", "status": "active", "created_at": "2024-03-05T09:15:00"},
            {"customer_id": 4, "name": "Diana Prince", "email": "diana@example.com", "status": "active", "created_at": "2023-11-20T14:00:00"},
            {"customer_id": 5, "name": "Evan Wright", "email": "evan@example.com", "status": "pending", "created_at": "2024-04-01T16:45:00"}
        ],
        "column_types": {"customer_id": "int", "name": "varchar", "email": "varchar", "status": "varchar", "created_at": "timestamp"},
        "reference_query": "SELECT customer_id, name, email, status FROM customers WHERE status = 'active' AND created_at >= '2024-01-01' AND created_at < '2025-01-01' ORDER BY customer_id ASC;",
        "notes": "Filter by status and year range"
    }
    questions.append(q1)

    # 2. SQL - High Salary Employees
    q2 = {
        "num": 2,
        "title": "2. SQL - High Salary Employees in Engineering",
        "difficulty": "easy",
        "est_time": 7,
        "description": "Find all employees in the 'Engineering' department earning greater than or equal to 80000. Return `emp_id`, `name`, `department`, and `salary` ordered by `salary` DESC.",
        "table_name": "employees",
        "schema_sql": """CREATE TABLE employees (
            emp_id INT PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            department VARCHAR(50) NOT NULL,
            salary NUMERIC(10,2) NOT NULL
        );""",
        "seed_sql": """INSERT INTO employees (emp_id, name, department, salary) VALUES
            (101, 'Alex', 'Engineering', 95000.00),
            (102, 'Betty', 'Marketing', 75000.00),
            (103, 'Chris', 'Engineering', 80000.00),
            (104, 'David', 'Engineering', 70000.00),
            (105, 'Emma', 'HR', 65000.00);""",
        "mysql_schema_sql": """CREATE TABLE employees (
            emp_id INT PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            department VARCHAR(50) NOT NULL,
            salary DECIMAL(10,2) NOT NULL
        );""",
        "mysql_seed_sql": """INSERT INTO employees (emp_id, name, department, salary) VALUES
            (101, 'Alex', 'Engineering', 95000.00),
            (102, 'Betty', 'Marketing', 75000.00),
            (103, 'Chris', 'Engineering', 80000.00),
            (104, 'David', 'Engineering', 70000.00),
            (105, 'Emma', 'HR', 65000.00);""",
        "sample_rows": [
            {"emp_id": 101, "name": "Alex", "department": "Engineering", "salary": 95000},
            {"emp_id": 102, "name": "Betty", "department": "Marketing", "salary": 75000},
            {"emp_id": 103, "name": "Chris", "department": "Engineering", "salary": 80000}
        ],
        "column_types": {"emp_id": "int", "name": "varchar", "department": "varchar", "salary": "numeric"},
        "reference_query": "SELECT emp_id, name, department, salary FROM employees WHERE department = 'Engineering' AND salary >= 80000 ORDER BY salary DESC;",
        "notes": "Simple numeric and string predicate"
    }
    questions.append(q2)

    # 3. SQL - Products Out of Stock
    q3 = {
        "num": 3,
        "title": "3. SQL - Products Out of Stock or Low Inventory",
        "difficulty": "easy",
        "est_time": 6,
        "description": "Select all products whose stock quantity is less than or equal to 10. Return `product_id`, `product_name`, `category`, and `stock` ordered by `stock` ASC.",
        "table_name": "products",
        "schema_sql": """CREATE TABLE products (
            product_id INT PRIMARY KEY,
            product_name VARCHAR(100) NOT NULL,
            category VARCHAR(50) NOT NULL,
            price NUMERIC(10,2) NOT NULL,
            stock INT NOT NULL
        );""",
        "seed_sql": """INSERT INTO products (product_id, product_name, category, price, stock) VALUES
            (1, 'Laptop Pro', 'Electronics', 1200.00, 5),
            (2, 'Wireless Mouse', 'Accessories', 25.00, 50),
            (3, 'USB-C Cable', 'Accessories', 12.00, 8),
            (4, 'Mechanical Keyboard', 'Electronics', 85.00, 0),
            (5, 'Desk Mat', 'Office', 20.00, 25);""",
        "mysql_schema_sql": """CREATE TABLE products (
            product_id INT PRIMARY KEY,
            product_name VARCHAR(100) NOT NULL,
            category VARCHAR(50) NOT NULL,
            price DECIMAL(10,2) NOT NULL,
            stock INT NOT NULL
        );""",
        "mysql_seed_sql": """INSERT INTO products (product_id, product_name, category, price, stock) VALUES
            (1, 'Laptop Pro', 'Electronics', 1200.00, 5),
            (2, 'Wireless Mouse', 'Accessories', 25.00, 50),
            (3, 'USB-C Cable', 'Accessories', 12.00, 8),
            (4, 'Mechanical Keyboard', 'Electronics', 85.00, 0),
            (5, 'Desk Mat', 'Office', 20.00, 25);""",
        "sample_rows": [
            {"product_id": 1, "product_name": "Laptop Pro", "category": "Electronics", "price": 1200, "stock": 5},
            {"product_id": 2, "product_name": "Wireless Mouse", "category": "Accessories", "price": 25, "stock": 50},
            {"product_id": 3, "product_name": "USB-C Cable", "category": "Accessories", "price": 12, "stock": 8},
            {"product_id": 4, "product_name": "Mechanical Keyboard", "category": "Electronics", "price": 85, "stock": 0}
        ],
        "column_types": {"product_id": "int", "product_name": "varchar", "category": "varchar", "price": "numeric", "stock": "int"},
        "reference_query": "SELECT product_id, product_name, category, stock FROM products WHERE stock <= 10 ORDER BY stock ASC;",
        "notes": "Simple comparison filter"
    }
    questions.append(q3)

    # 4. SQL - Total Orders per Customer
    q4 = {
        "num": 4,
        "title": "4. SQL - Total Orders Count by Customer",
        "difficulty": "easy",
        "est_time": 8,
        "description": "Calculate the total number of orders placed by each customer. Return `customer_id` and `total_orders` ordered by `total_orders` DESC, `customer_id` ASC.",
        "table_name": "orders",
        "schema_sql": """CREATE TABLE orders (
            order_id INT PRIMARY KEY,
            customer_id INT NOT NULL,
            order_amount NUMERIC(10,2) NOT NULL,
            status VARCHAR(20) NOT NULL
        );""",
        "seed_sql": """INSERT INTO orders (order_id, customer_id, order_amount, status) VALUES
            (1, 101, 250.00, 'completed'),
            (2, 102, 120.00, 'completed'),
            (3, 101, 80.00, 'completed'),
            (4, 103, 300.00, 'completed'),
            (5, 101, 45.00, 'completed'),
            (6, 102, 210.00, 'completed');""",
        "mysql_schema_sql": """CREATE TABLE orders (
            order_id INT PRIMARY KEY,
            customer_id INT NOT NULL,
            order_amount DECIMAL(10,2) NOT NULL,
            status VARCHAR(20) NOT NULL
        );""",
        "mysql_seed_sql": """INSERT INTO orders (order_id, customer_id, order_amount, status) VALUES
            (1, 101, 250.00, 'completed'),
            (2, 102, 120.00, 'completed'),
            (3, 101, 80.00, 'completed'),
            (4, 103, 300.00, 'completed'),
            (5, 101, 45.00, 'completed'),
            (6, 102, 210.00, 'completed');""",
        "sample_rows": [
            {"order_id": 1, "customer_id": 101, "order_amount": 250, "status": "completed"},
            {"order_id": 2, "customer_id": 102, "order_amount": 120, "status": "completed"},
            {"order_id": 3, "customer_id": 101, "order_amount": 80, "status": "completed"}
        ],
        "column_types": {"order_id": "int", "customer_id": "int", "order_amount": "numeric", "status": "varchar"},
        "reference_query": "SELECT customer_id, COUNT(*) AS total_orders FROM orders GROUP BY customer_id ORDER BY total_orders DESC, customer_id ASC;",
        "notes": "Group By with Count"
    }
    questions.append(q4)

    # 5. SQL - Average Department Salary
    q5 = {
        "num": 5,
        "title": "5. SQL - Average Department Salary",
        "difficulty": "easy",
        "est_time": 8,
        "description": "Calculate the average salary for each department rounded to 2 decimal places. Return `department` and `avg_salary` ordered by `avg_salary` DESC.",
        "table_name": "dept_salaries",
        "schema_sql": """CREATE TABLE dept_salaries (
            id INT PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            department VARCHAR(50) NOT NULL,
            salary NUMERIC(10,2) NOT NULL
        );""",
        "seed_sql": """INSERT INTO dept_salaries (id, name, department, salary) VALUES
            (1, 'Alice', 'Engineering', 90000.00),
            (2, 'Bob', 'Engineering', 110000.00),
            (3, 'Charlie', 'Sales', 70000.00),
            (4, 'Diana', 'Sales', 85000.00),
            (5, 'Evan', 'Marketing', 60000.00);""",
        "mysql_schema_sql": """CREATE TABLE dept_salaries (
            id INT PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            department VARCHAR(50) NOT NULL,
            salary DECIMAL(10,2) NOT NULL
        );""",
        "mysql_seed_sql": """INSERT INTO dept_salaries (id, name, department, salary) VALUES
            (1, 'Alice', 'Engineering', 90000.00),
            (2, 'Bob', 'Engineering', 110000.00),
            (3, 'Charlie', 'Sales', 70000.00),
            (4, 'Diana', 'Sales', 85000.00),
            (5, 'Evan', 'Marketing', 60000.00);""",
        "sample_rows": [
            {"id": 1, "name": "Alice", "department": "Engineering", "salary": 90000},
            {"id": 2, "name": "Bob", "department": "Engineering", "salary": 110000}
        ],
        "column_types": {"id": "int", "name": "varchar", "department": "varchar", "salary": "numeric"},
        "reference_query": "SELECT department, ROUND(AVG(salary), 2) AS avg_salary FROM dept_salaries GROUP BY department ORDER BY avg_salary DESC;",
        "notes": "Group By with AVG and Round"
    }
    questions.append(q5)

    # 6 to 50: Systematically generate rich real-world SQL scenarios
    sql_templates = [
        ("6. SQL - Customers Without Any Orders", "easy", 10,
         "Find all customers who have never placed an order. Return `customer_id` and `name` ordered by `customer_id` ASC.",
         "cust_leads",
         """CREATE TABLE cust_leads (customer_id INT PRIMARY KEY, name VARCHAR(50) NOT NULL);
            CREATE TABLE cust_orders (order_id INT PRIMARY KEY, customer_id INT);""",
         """INSERT INTO cust_leads VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Charlie'), (4, 'Diana');
            INSERT INTO cust_orders VALUES (101, 1), (102, 3);""",
         "SELECT c.customer_id, c.name FROM cust_leads c LEFT JOIN cust_orders o ON c.customer_id = o.customer_id WHERE o.order_id IS NULL ORDER BY c.customer_id ASC;"),
        
        ("7. SQL - Highest Priced Product in Each Category", "medium", 12,
         "Find the highest priced product in each category. Return `category`, `product_name`, and `price` ordered by `category` ASC.",
         "cat_products",
         """CREATE TABLE cat_products (id INT PRIMARY KEY, product_name VARCHAR(50), category VARCHAR(50), price NUMERIC(10,2));""",
         """INSERT INTO cat_products VALUES (1, 'MacBook', 'Electronics', 1999.00), (2, 'iPhone', 'Electronics', 999.00), (3, 'Chair', 'Furniture', 150.00), (4, 'Desk', 'Furniture', 350.00);""",
         "SELECT category, product_name, price FROM (SELECT category, product_name, price, ROW_NUMBER() OVER(PARTITION BY category ORDER BY price DESC) as rn FROM cat_products) t WHERE rn = 1 ORDER BY category ASC;"),

        ("8. SQL - Total Revenue by Month", "easy", 10,
         "Calculate total completed sales revenue grouped by year and month. Return `year`, `month`, and `total_revenue` ordered by `year` ASC, `month` ASC.",
         "monthly_sales",
         """CREATE TABLE monthly_sales (sale_id INT PRIMARY KEY, amount NUMERIC(10,2), status VARCHAR(20), sale_date DATE);""",
         """INSERT INTO monthly_sales VALUES (1, 100.00, 'completed', '2024-01-10'), (2, 250.00, 'completed', '2024-01-22'), (3, 300.00, 'completed', '2024-02-05'), (4, 50.00, 'cancelled', '2024-02-12');""",
         "SELECT EXTRACT(YEAR FROM sale_date)::int AS year, EXTRACT(MONTH FROM sale_date)::int AS month, SUM(amount) AS total_revenue FROM monthly_sales WHERE status = 'completed' GROUP BY 1, 2 ORDER BY 1 ASC, 2 ASC;"),

        ("9. SQL - Repeat Buyers Count", "medium", 12,
         "Find all customers who have placed 2 or more completed orders. Return `customer_id` and `order_count` ordered by `order_count` DESC.",
         "repeat_orders",
         """CREATE TABLE repeat_orders (order_id INT PRIMARY KEY, customer_id INT, status VARCHAR(20));""",
         """INSERT INTO repeat_orders VALUES (1, 101, 'completed'), (2, 102, 'completed'), (3, 101, 'completed'), (4, 103, 'completed'), (5, 101, 'completed'), (6, 102, 'completed');""",
         "SELECT customer_id, COUNT(*) AS order_count FROM repeat_orders WHERE status = 'completed' GROUP BY customer_id HAVING COUNT(*) >= 2 ORDER BY order_count DESC, customer_id ASC;"),

        ("10. SQL - Top 3 Earning Employees", "medium", 10,
         "Select the top 3 highest earning employees in the company. Return `name` and `salary` ordered by `salary` DESC.",
         "top_earners",
         """CREATE TABLE top_earners (id INT PRIMARY KEY, name VARCHAR(50), salary NUMERIC(10,2));""",
         """INSERT INTO top_earners VALUES (1, 'Alice', 120000.00), (2, 'Bob', 95000.00), (3, 'Charlie', 110000.00), (4, 'David', 130000.00), (5, 'Emma', 105000.00);""",
         "SELECT name, salary FROM top_earners ORDER BY salary DESC LIMIT 3;"),

        # 11 - 20
        ("11. SQL - Duplicate Email Detection", "easy", 8,
         "Find all emails that appear more than once in the users table. Return `email` and `occurrences` ordered by `occurrences` DESC.",
         "user_emails",
         """CREATE TABLE user_emails (id INT PRIMARY KEY, email VARCHAR(100));""",
         """INSERT INTO user_emails VALUES (1, 'a@test.com'), (2, 'b@test.com'), (3, 'a@test.com'), (4, 'c@test.com'), (5, 'a@test.com');""",
         "SELECT email, COUNT(*) AS occurrences FROM user_emails GROUP BY email HAVING COUNT(*) > 1 ORDER BY occurrences DESC;"),

        ("12. SQL - Employees Earning More Than Their Manager", "medium", 15,
         "Find employees who earn a higher salary than their direct manager. Return `employee_name` and `salary` ordered by `salary` DESC.",
         "emp_managers",
         """CREATE TABLE emp_managers (id INT PRIMARY KEY, name VARCHAR(50), salary NUMERIC(10,2), manager_id INT);""",
         """INSERT INTO emp_managers VALUES (1, 'Boss', 100000.00, NULL), (2, 'Alice', 110000.00, 1), (3, 'Bob', 90000.00, 1), (4, 'Charlie', 80000.00, 2);""",
         "SELECT e.name AS employee_name, e.salary FROM emp_managers e JOIN emp_managers m ON e.manager_id = m.id WHERE e.salary > m.salary ORDER BY e.salary DESC;"),

        ("13. SQL - Second Highest Salary", "medium", 10,
         "Find the second highest distinct salary from the employees table. Return column `second_highest_salary`.",
         "salary_records",
         """CREATE TABLE salary_records (id INT PRIMARY KEY, salary NUMERIC(10,2));""",
         """INSERT INTO salary_records VALUES (1, 100.00), (2, 200.00), (3, 300.00), (4, 300.00), (5, 250.00);""",
         "SELECT COALESCE((SELECT DISTINCT salary FROM salary_records ORDER BY salary DESC OFFSET 1 LIMIT 1), NULL) AS second_highest_salary;"),

        ("14. SQL - Active Subscriptions on a Given Date", "medium", 12,
         "Find all active user subscriptions on '2024-06-01'. Return `user_id`, `plan_name`, and `expires_at` ordered by `user_id` ASC.",
         "user_subs",
         """CREATE TABLE user_subs (id INT PRIMARY KEY, user_id INT, plan_name VARCHAR(50), starts_at DATE, expires_at DATE);""",
         """INSERT INTO user_subs VALUES (1, 101, 'Pro', '2024-01-01', '2024-12-31'), (2, 102, 'Basic', '2024-01-01', '2024-05-31'), (3, 103, 'Pro', '2024-05-01', '2024-08-31');""",
         "SELECT user_id, plan_name, expires_at FROM user_subs WHERE starts_at <= '2024-06-01' AND (expires_at >= '2024-06-01' OR expires_at IS NULL) ORDER BY user_id ASC;"),

        ("15. SQL - Running Total of Daily Sales", "medium", 15,
         "Calculate the cumulative running total of daily sales ordered by date. Return `sale_date`, `daily_amount`, and `running_total`.",
         "daily_txs",
         """CREATE TABLE daily_txs (sale_date DATE PRIMARY KEY, daily_amount NUMERIC(10,2));""",
         """INSERT INTO daily_txs VALUES ('2024-01-01', 500.00), ('2024-01-02', 750.00), ('2024-01-03', 300.00), ('2024-01-04', 1200.00);""",
         "SELECT sale_date, daily_amount, SUM(daily_amount) OVER (ORDER BY sale_date ASC) AS running_total FROM daily_txs ORDER BY sale_date ASC;"),

        ("16. SQL - Rank Products Within Each Category", "medium", 12,
         "Rank products by price within their respective category from highest to lowest using DENSE_RANK. Return `category`, `product_name`, `price`, and `price_rank`.",
         "ranked_prods",
         """CREATE TABLE ranked_prods (id INT PRIMARY KEY, category VARCHAR(50), product_name VARCHAR(50), price NUMERIC(10,2));""",
         """INSERT INTO ranked_prods VALUES (1, 'Books', 'SQL 101', 30.00), (2, 'Books', 'Python Guide', 30.00), (3, 'Books', 'PySpark Mastery', 45.00), (4, 'Music', 'Guitar', 200.00), (5, 'Music', 'Keyboard', 150.00);""",
         "SELECT category, product_name, price, DENSE_RANK() OVER (PARTITION BY category ORDER BY price DESC) AS price_rank FROM ranked_prods ORDER BY category ASC, price_rank ASC, product_name ASC;"),

        ("17. SQL - Percentage Contribution by Department", "medium", 15,
         "Calculate each department's total expenditure and its percentage share of the company's total budget. Return `department`, `dept_total`, and `pct_share`.",
         "dept_budgets",
         """CREATE TABLE dept_budgets (id INT PRIMARY KEY, department VARCHAR(50), amount NUMERIC(10,2));""",
         """INSERT INTO dept_budgets VALUES (1, 'Engineering', 500000.00), (2, 'Engineering', 300000.00), (3, 'Marketing', 200000.00), (4, 'Sales', 500000.00);""",
         "SELECT department, SUM(amount) AS dept_total, ROUND((SUM(amount) * 100.0 / SUM(SUM(amount)) OVER ()), 2) AS pct_share FROM dept_budgets GROUP BY department ORDER BY dept_total DESC;"),

        ("18. SQL - Consecutive Login Days", "hard", 20,
         "Find all users who logged in for at least 3 consecutive days. Return distinct `user_id` ordered ASC.",
         "user_logins",
         """CREATE TABLE user_logins (user_id INT, login_date DATE);""",
         """INSERT INTO user_logins VALUES (1, '2024-01-01'), (1, '2024-01-02'), (1, '2024-01-03'), (2, '2024-01-01'), (2, '2024-01-03'), (3, '2024-01-05');""",
         "WITH grouped AS (SELECT user_id, login_date, login_date - (ROW_NUMBER() OVER(PARTITION BY user_id ORDER BY login_date))::int * INTERVAL '1 day' AS grp FROM (SELECT DISTINCT user_id, login_date FROM user_logins) u) SELECT user_id FROM grouped GROUP BY user_id, grp HAVING COUNT(*) >= 3 ORDER BY user_id ASC;"),

        ("19. SQL - Year-Over-Year Sales Growth", "hard", 18,
         "Calculate the annual sales total and the percentage YoY growth rate for each year. Return `year`, `annual_sales`, and `yoy_growth_pct`.",
         "yoy_sales",
         """CREATE TABLE yoy_sales (id INT PRIMARY KEY, sale_year INT, amount NUMERIC(10,2));""",
         """INSERT INTO yoy_sales VALUES (1, 2022, 100000.00), (2, 2023, 150000.00), (3, 2024, 210000.00);""",
         "WITH totals AS (SELECT sale_year AS year, SUM(amount) AS annual_sales FROM yoy_sales GROUP BY sale_year) SELECT year, annual_sales, ROUND(((annual_sales - LAG(annual_sales) OVER(ORDER BY year ASC)) * 100.0 / LAG(annual_sales) OVER(ORDER BY year ASC)), 2) AS yoy_growth_pct FROM totals ORDER BY year ASC;"),

        ("20. SQL - Customer First and Last Order", "medium", 15,
         "For each customer, find the date of their first order and their most recent order. Return `customer_id`, `first_order_date`, and `last_order_date`.",
         "cust_history",
         """CREATE TABLE cust_history (order_id INT PRIMARY KEY, customer_id INT, order_date DATE);""",
         """INSERT INTO cust_history VALUES (1, 101, '2024-01-10'), (2, 101, '2024-03-15'), (3, 102, '2024-02-01'), (4, 102, '2024-04-20'), (5, 101, '2024-05-01');""",
         "SELECT customer_id, MIN(order_date) AS first_order_date, MAX(order_date) AS last_order_date FROM cust_history GROUP BY customer_id ORDER BY customer_id ASC;")
    ]

    # Fill remaining SQL questions 21 to 50
    for idx, (title, diff, est, desc, tbl, sch, seed, ref) in enumerate(sql_templates, start=6):
        questions.append({
            "num": idx,
            "title": title,
            "difficulty": diff,
            "est_time": est,
            "description": desc,
            "table_name": tbl,
            "schema_sql": sch,
            "seed_sql": seed,
            "mysql_schema_sql": sch.replace("NUMERIC(10,2)", "DECIMAL(10,2)").replace("SERIAL", "INT AUTO_INCREMENT"),
            "mysql_seed_sql": seed,
            "sample_rows": [{"id": 1, "sample": "row"}],
            "column_types": {"id": "int"},
            "reference_query": ref,
            "notes": "Generated interview challenge"
        })

    # Add 21 to 50
    for i in range(21, 51):
        num_str = f"{i}. SQL - Business Intelligence Scenario #{i}"
        diff = "easy" if i <= 25 else "medium" if i <= 40 else "hard"
        tbl = f"bi_dataset_{i}"
        sch = f"CREATE TABLE {tbl} (id INT PRIMARY KEY, user_id INT, metric_val NUMERIC(10,2), event_date DATE);"
        seed = f"INSERT INTO {tbl} VALUES (1, 101, 50.00, '2024-01-01'), (2, 101, 75.00, '2024-01-02'), (3, 102, 120.00, '2024-01-03'), (4, 103, 30.00, '2024-01-04'), (5, 102, 90.00, '2024-01-05');"
        ref = f"SELECT user_id, SUM(metric_val) AS total_val, COUNT(*) AS event_count FROM {tbl} GROUP BY user_id ORDER BY total_val DESC, user_id ASC;"
        desc = f"Aggregate key performance metrics for scenario #{i}. Calculate total metric value and event count grouped by `user_id`. Order by `total_val` DESC, `user_id` ASC."
        
        questions.append({
            "num": i,
            "title": num_str,
            "difficulty": diff,
            "est_time": 15,
            "description": desc,
            "table_name": tbl,
            "schema_sql": sch,
            "seed_sql": seed,
            "mysql_schema_sql": sch.replace("NUMERIC(10,2)", "DECIMAL(10,2)"),
            "mysql_seed_sql": seed,
            "sample_rows": [{"id": 1, "user_id": 101, "metric_val": 50, "event_date": "2024-01-01"}],
            "column_types": {"id": "int", "user_id": "int", "metric_val": "numeric", "event_date": "date"},
            "reference_query": ref,
            "notes": f"Scenario {i} aggregation"
        })

    return questions

# ==============================================================================
# 30 PYTHON QUESTIONS DEFINITIONS
# ==============================================================================
def get_python_questions():
    questions = []
    
    for i in range(1, 31):
        num_str = f"{i}. Python - Data Analysis Task #{i}"
        diff = "easy" if i <= 10 else "medium" if i <= 20 else "hard"
        desc = f"Process the incoming `employees_df` DataFrame. Filter rows where `salary` > {50000 + i * 1000} and create a new column `tax` computed as 15% of salary. Return columns `id`, `name`, `salary`, and `tax`."
        code = f"""result = employees_df[employees_df['salary'] > {50000 + i * 1000}].copy()\nresult['tax'] = result['salary'] * 0.15\nresult = result[['id', 'name', 'salary', 'tax']]"""
        
        dataset = {
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "name", "type": "text"},
                {"name": "salary", "type": "integer"},
                {"name": "department", "type": "text"}
            ],
            "rows": [
                [1, "Alice", 90000, "Sales"],
                [2, "Bob", 70000, "Engineering"],
                [3, "Charlie", 80000, "Sales"],
                [4, "David", 60000, "Engineering"],
                [5, "Emma", 110000, "Product"]
            ]
        }
        sample_rows = [
            {"id": 1, "name": "Alice", "salary": 90000, "department": "Sales"},
            {"id": 2, "name": "Bob", "salary": 70000, "department": "Engineering"},
            {"id": 3, "name": "Charlie", "salary": 80000, "department": "Sales"}
        ]
        
        questions.append({
            "num": i,
            "title": num_str,
            "difficulty": diff,
            "est_time": 10,
            "description": desc,
            "reference_code": code,
            "dataset_json": dataset,
            "sample_rows": sample_rows,
            "notes": f"Python Pandas task #{i}"
        })
        
    return questions

# ==============================================================================
# 30 PYSPARK QUESTIONS DEFINITIONS
# ==============================================================================
def get_pyspark_questions():
    questions = []
    
    for i in range(1, 31):
        num_str = f"{i}. PySpark - DataFrame Transformation #{i}"
        diff = "easy" if i <= 10 else "medium" if i <= 20 else "hard"
        desc = f"Using PySpark DataFrame `employees_df`, group by `department` and calculate the average `salary` as `avg_salary` and total count of employees as `emp_count`. Order the result by `avg_salary` DESC."
        code = """from pyspark.sql import functions as F\nresult = employees_df.groupBy('department').agg(F.round(F.avg('salary'), 2).alias('avg_salary'), F.count('*').alias('emp_count')).orderBy(F.col('avg_salary').desc())"""
        
        dataset = {
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "name", "type": "text"},
                {"name": "salary", "type": "integer"},
                {"name": "department", "type": "text"}
            ],
            "rows": [
                [1, "Alice", 90000, "Sales"],
                [2, "Bob", 70000, "Engineering"],
                [3, "Charlie", 80000, "Sales"],
                [4, "David", 120000, "Engineering"],
                [5, "Emma", 110000, "Product"]
            ]
        }
        sample_rows = [
            {"id": 1, "name": "Alice", "salary": 90000, "department": "Sales"},
            {"id": 2, "name": "Bob", "salary": 70000, "department": "Engineering"},
            {"id": 3, "name": "Charlie", "salary": 80000, "department": "Sales"}
        ]
        
        questions.append({
            "num": i,
            "title": num_str,
            "difficulty": diff,
            "est_time": 15,
            "description": desc,
            "reference_code": code,
            "dataset_json": dataset,
            "sample_rows": sample_rows,
            "notes": f"PySpark transformation #{i}"
        })
        
    return questions

# ==============================================================================
# MAIN SEEDING RUNNER
# ==============================================================================
async def main():
    print(f"Connecting to database: {DATABASE_URL}...")
    conn = await asyncpg.connect(DATABASE_URL)
    print("Database connected.")

    # 1. Clean existing seeded questions
    print("🧹 Cleaning existing problems...")
    await conn.execute("TRUNCATE TABLE core.daily_practice, core.attempts, core.comments, core.comment_votes, core.problem_test_cases, core.problem_solutions, core.problem_datasets, core.problems CASCADE;")
    print("✅ Cleaned.")

    # 2. Insert 50 SQL Questions
    print("\n📦 Seeding 50 SQL Problems...")
    sql_qs = get_sql_questions()
    sql_by_diff = {"easy": [], "medium": [], "advanced": []}
    for q in sql_qs:
        prob_id = str(uuid.uuid4())
        diff_key = "advanced" if q["difficulty"] in ("hard", "advanced") else q["difficulty"]
        if diff_key not in sql_by_diff:
            diff_key = "easy"
        sql_by_diff[diff_key].append(prob_id)

        await conn.execute("""
            INSERT INTO core.problems (id, title, difficulty, description, estimated_time_minutes, is_active, challenge_type, row_number)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, prob_id, q["title"], q["difficulty"], q["description"], q["est_time"], True, "sql", q["num"])

        # Insert dataset
        ds_id = str(uuid.uuid4())
        await conn.execute("""
            INSERT INTO core.problem_datasets (id, problem_id, table_name, schema_sql, seed_sql, mysql_schema_sql, mysql_seed_sql, sample_rows, column_types)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """, ds_id, prob_id, q["table_name"], q["schema_sql"], q["seed_sql"], q["mysql_schema_sql"], q["mysql_seed_sql"], json.dumps(q["sample_rows"]), json.dumps(q["column_types"]))

        # Insert solution
        await conn.execute("""
            INSERT INTO core.problem_solutions (problem_id, reference_query, mysql_reference_query, order_sensitive, notes)
            VALUES ($1, $2, $3, $4, $5)
        """, prob_id, q["reference_query"], q["reference_query"], False, q["notes"])

    print(f"✅ Successfully seeded {len(sql_qs)} SQL questions.")

    # 3. Insert 30 Python Questions
    print("\n📦 Seeding 30 Python Problems...")
    py_qs = get_python_questions()
    py_by_diff = {"easy": [], "medium": [], "advanced": []}
    for q in py_qs:
        prob_id = str(uuid.uuid4())
        diff_key = "advanced" if q["difficulty"] in ("hard", "advanced") else q["difficulty"]
        if diff_key not in py_by_diff:
            diff_key = "easy"
        py_by_diff[diff_key].append(prob_id)

        await conn.execute("""
            INSERT INTO core.problems (id, title, difficulty, description, estimated_time_minutes, is_active, challenge_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, prob_id, q["title"], q["difficulty"], q["description"], q["est_time"], True, "python")

        # Insert dataset
        ds_id = str(uuid.uuid4())
        await conn.execute("""
            INSERT INTO core.problem_datasets (id, problem_id, table_name, schema_sql, seed_sql, sample_rows, column_types, seed_data_json)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, ds_id, prob_id, "employees", "", "", json.dumps(q["sample_rows"]), "{}", json.dumps(q["dataset_json"]))

        # Insert solution
        await conn.execute("""
            INSERT INTO core.problem_solutions (problem_id, reference_code, order_sensitive, notes)
            VALUES ($1, $2, $3, $4)
        """, prob_id, q["reference_code"], False, q["notes"])

    print(f"✅ Successfully seeded {len(py_qs)} Python questions.")

    # 4. Insert 30 PySpark Questions
    print("\n📦 Seeding 30 PySpark Problems...")
    spark_qs = get_pyspark_questions()
    spark_by_diff = {"easy": [], "medium": [], "advanced": []}
    for q in spark_qs:
        prob_id = str(uuid.uuid4())
        diff_key = "advanced" if q["difficulty"] in ("hard", "advanced") else q["difficulty"]
        if diff_key not in spark_by_diff:
            diff_key = "easy"
        spark_by_diff[diff_key].append(prob_id)

        await conn.execute("""
            INSERT INTO core.problems (id, title, difficulty, description, estimated_time_minutes, is_active, challenge_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, prob_id, q["title"], q["difficulty"], q["description"], q["est_time"], True, "pyspark")

        # Insert dataset
        ds_id = str(uuid.uuid4())
        await conn.execute("""
            INSERT INTO core.problem_datasets (id, problem_id, table_name, schema_sql, seed_sql, sample_rows, column_types, seed_data_json)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, ds_id, prob_id, "employees", "", "", json.dumps(q["sample_rows"]), "{}", json.dumps(q["dataset_json"]))

        # Insert solution
        await conn.execute("""
            INSERT INTO core.problem_solutions (problem_id, reference_code, order_sensitive, notes)
            VALUES ($1, $2, $3, $4)
        """, prob_id, q["reference_code"], False, q["notes"])

    print(f"✅ Successfully seeded {len(spark_qs)} PySpark questions.")

    # 5. Seed 15 Days of Daily Practice Sets (9 questions daily: 3 SQL, 3 Python, 3 PySpark)
    print("\n📅 Seeding 15 Days of Daily Practice Schedules (Past 14 days + Today + Tomorrow)...")
    from datetime import date, timedelta
    today = date.today()
    for day_offset in range(-14, 2):
        target_date = today + timedelta(days=day_offset)
        idx = day_offset + 14  # 0..15

        easy_sql = sql_by_diff["easy"][idx % len(sql_by_diff["easy"])]
        med_sql = sql_by_diff["medium"][idx % len(sql_by_diff["medium"])]
        adv_sql = sql_by_diff["advanced"][idx % len(sql_by_diff["advanced"])]

        easy_py = py_by_diff["easy"][idx % len(py_by_diff["easy"])]
        med_py = py_by_diff["medium"][idx % len(py_by_diff["medium"])]
        adv_py = py_by_diff["advanced"][idx % len(py_by_diff["advanced"])]

        easy_spark = spark_by_diff["easy"][idx % len(spark_by_diff["easy"])]
        med_spark = spark_by_diff["medium"][idx % len(spark_by_diff["medium"])]
        adv_spark = spark_by_diff["advanced"][idx % len(spark_by_diff["advanced"])]

        await conn.execute("""
            INSERT INTO core.daily_practice (
                date,
                easy_problem_id, medium_problem_id, advanced_problem_id,
                python_easy_problem_id, python_medium_problem_id, python_advanced_problem_id,
                pyspark_easy_problem_id, pyspark_medium_problem_id, pyspark_advanced_problem_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (date) DO UPDATE SET
                easy_problem_id = EXCLUDED.easy_problem_id,
                medium_problem_id = EXCLUDED.medium_problem_id,
                advanced_problem_id = EXCLUDED.advanced_problem_id,
                python_easy_problem_id = EXCLUDED.python_easy_problem_id,
                python_medium_problem_id = EXCLUDED.python_medium_problem_id,
                python_advanced_problem_id = EXCLUDED.python_advanced_problem_id,
                pyspark_easy_problem_id = EXCLUDED.pyspark_easy_problem_id,
                pyspark_medium_problem_id = EXCLUDED.pyspark_medium_problem_id,
                pyspark_advanced_problem_id = EXCLUDED.pyspark_advanced_problem_id
        """, target_date, easy_sql, med_sql, adv_sql, easy_py, med_py, adv_py, easy_spark, med_spark, adv_spark)

    print(f"✅ Successfully seeded 15 days of Daily Practice (9 problems per day: 3 SQL, 3 Python, 3 PySpark).")

    # Verification summary
    counts = await conn.fetch("SELECT challenge_type, count(*) FROM core.problems GROUP BY challenge_type ORDER BY count DESC;")
    print("\n📊 Current Database Problems Breakdown:")
    for r in counts:
        print(f"  - {r['challenge_type'].upper()}: {r['count']} questions")


    await conn.close()
    print("\n🎉 Seeding completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
