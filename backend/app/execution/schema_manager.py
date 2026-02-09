import uuid

def generate_schema_name() -> str:
    return f"run_{uuid.uuid4().hex[:8]}"

async def setup_execution_schema(conn, problem_id: str):
    """
    1. Create isolated schema
    2. Set search_path
    3. Load tables & data
    """
    schema_name = generate_schema_name()

    # Create schema
    await conn.execute(f'CREATE SCHEMA "{schema_name}"')

    # Force queries to only see this schema
    await conn.execute(f'SET search_path TO "{schema_name}"')

    # Load datasets for the problem
    datasets = await conn.fetch(
        """
        SELECT table_name, schema_sql, seed_sql
        FROM core.problem_datasets
        WHERE problem_id = $1
        """,
        problem_id,
    )

    if not datasets:
        raise RuntimeError("No datasets defined for this problem")

    for ds in datasets:
        # Create table
        await conn.execute(ds["schema_sql"])
        # Seed data
        await conn.execute(ds["seed_sql"])

    return schema_name

async def teardown_execution_schema(conn, schema_name: str):
    await conn.execute(f'DROP SCHEMA "{schema_name}" CASCADE')



async def apply_execution_limits(conn):
    await conn.execute("SET statement_timeout = '1000ms'")
    await conn.execute("SET work_mem = '16MB'")
    await conn.execute("SET idle_in_transaction_session_timeout = '1000ms'")
    await conn.execute("SET max_parallel_workers_per_gather = 0")
