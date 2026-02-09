async def ensure_problem_exists(conn, problem_id: str):
    try:
        row = await conn.fetchrow(
            """
            SELECT id
            FROM core.problems
            WHERE id = $1 AND is_active = true
            """,
            problem_id,
        )
    except Exception:
        # Catch explicit invalid UUID format error
        raise ValueError("Invalid format for problem_id")

    if not row:
        raise ValueError("Invalid or inactive problem_id")
