import uuid

def generate_schema_name() -> str:
    return f"run_{uuid.uuid4().hex[:8]}"


async def setup_execution_schema(conn, problem_id: str):
    """
    1. Create isolated Postgres schema
    2. Set search_path
    3. Load tables & data — prefers stored schema_sql/seed_sql; regenerates
       from seed_data_json via SqlDialectGenerator when schema_sql is absent
       (new datasets created via the unified JSON descriptor flow).
    """
    schema_name = generate_schema_name()

    # Create schema
    await conn.execute(f'CREATE SCHEMA "{schema_name}"')

    # Force queries to only see this schema
    await conn.execute(f'SET search_path TO "{schema_name}"')

    # Load datasets for the problem
    datasets = await conn.fetch(
        """
        SELECT table_name, schema_sql, seed_sql, seed_data_json
        FROM core.problem_datasets
        WHERE problem_id = $1
        """,
        problem_id,
    )

    if not datasets:
        raise RuntimeError("No datasets defined for this problem")

    for ds in datasets:
        schema_sql = ds["schema_sql"]
        seed_sql = ds["seed_sql"]

        if not schema_sql:
            # Regenerate from seed_data_json using SqlDialectGenerator
            raw_json = ds["seed_data_json"]
            if raw_json:
                import json as _json
                from app.execution.sql_dialect_generator import SqlDialectGenerator
                _gen = SqlDialectGenerator()
                descriptor = _json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                if _gen.has_schema_metadata(descriptor):
                    schema_sql, seed_sql = _gen.generate(
                        descriptor, ds["table_name"], "postgresql"
                    )
                else:
                    raise RuntimeError(
                        f"Dataset '{ds['table_name']}' has no schema_sql and no JSON descriptor with schema metadata."
                    )
            else:
                raise RuntimeError(
                    f"Dataset '{ds['table_name']}' has no schema_sql and no seed_data_json to regenerate from."
                )

        await conn.execute(schema_sql)
        if seed_sql:
            await conn.execute(seed_sql)

    return schema_name



async def teardown_execution_schema(conn, schema_name: str):
    await conn.execute(f'DROP SCHEMA "{schema_name}" CASCADE')


async def apply_execution_limits(conn):
    await conn.execute("SET statement_timeout = '1000ms'")
    await conn.execute("SET work_mem = '16MB'")
    await conn.execute("SET idle_in_transaction_session_timeout = '1000ms'")
    await conn.execute("SET max_parallel_workers_per_gather = 0")
