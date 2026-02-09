from datetime import date, timedelta

async def update_streak(conn, user_id: str, was_correct: bool):
    today = date.today()

    row = await conn.fetchrow(
        """
        SELECT current_streak, last_active_date
        FROM core.streaks
        WHERE user_id = $1
        """,
        user_id,
    )

    if not was_correct:
        return  # incorrect attempts do not affect streak

    if not row:
        # First-ever streak
        await conn.execute(
            """
            INSERT INTO core.streaks (user_id, current_streak, last_active_date)
            VALUES ($1, 1, $2)
            """,
            user_id,
            today,
        )
        return

    last_date = row["last_active_date"]
    current_streak = row["current_streak"]

    if last_date == today:
        return  # already counted today

    if last_date == today - timedelta(days=1):
        # Continue streak
        await conn.execute(
            """
            UPDATE core.streaks
            SET current_streak = current_streak + 1,
                last_active_date = $2
            WHERE user_id = $1
            """,
            user_id,
            today,
        )
    else:
        # Streak broken → reset
        await conn.execute(
            """
            UPDATE core.streaks
            SET current_streak = 1,
                last_active_date = $2
            WHERE user_id = $1
            """,
            user_id,
            today,
        )
