from uuid import uuid4
from datetime import date

async def record_attempt(
    conn,
    user_id: str,
    problem_id: str,
    status: str,
    execution_time_ms: int | None,
    challenge_type: str = "sql"
):
    await conn.execute(
        """
        INSERT INTO core.attempts
        (id, user_id, problem_id, attempt_date, status, execution_time_ms, challenge_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        uuid4(),
        user_id,
        problem_id,
        date.today(),
        status,
        execution_time_ms,
        challenge_type,
    )
