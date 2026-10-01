"""
One-time fix: protect streaks that would otherwise break because of the maintenance outage.

Scope — deliberately NOT "every user": only accounts whose last real solve was close enough to
when maintenance started that they were still on a live streak (not someone who had already gone
quiet before the outage). For those accounts, mark the day before today as covered, so their next
real solve reads as a continuation instead of a reset. Nothing else changes: current_streak is
never touched, and no fake attempt/solve is recorded anywhere.

Usage (on the VPS, from the repo root after `git pull` — this file isn't baked into the Docker
image, so it still needs copying into the running container, which already has DATABASE_URL set):
    docker cp backend/fix_maintenance_streaks.py dailysql_api_prod:/app/fix_maintenance_streaks.py
    docker exec -it dailysql_api_prod python fix_maintenance_streaks.py            # preview only
    docker exec -it dailysql_api_prod python fix_maintenance_streaks.py --apply    # actually writes

Adjust MAINTENANCE_START below if maintenance actually began on a different date.
"""
import asyncio
import os
import sys
from datetime import date, timedelta

import asyncpg

MAINTENANCE_START = date(2026, 9, 30)   # <-- change this if it's wrong
CUTOFF_START = MAINTENANCE_START - timedelta(days=1)   # still "alive" (1-day grace) as of maintenance start
COVER_DATE = date.today() - timedelta(days=1)          # "yesterday" — run this the day you actually restore


async def main():
    apply = "--apply" in sys.argv
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        rows = await conn.fetch(
            """
            SELECT s.user_id, u.email, s.current_streak, s.last_active_date
            FROM core.streaks s
            JOIN core.users u ON u.user_id = s.user_id
            WHERE s.last_active_date >= $1 AND s.last_active_date < $2
            ORDER BY s.current_streak DESC
            """,
            CUTOFF_START, COVER_DATE,
        )
        print(f"Maintenance assumed to start: {MAINTENANCE_START}  (cutoff: last active >= {CUTOFF_START})")
        print(f"Will mark covered through:    {COVER_DATE}")
        print(f"\n{len(rows)} account(s) would be protected:")
        for r in rows[:25]:
            print(f"  {r['email']:<35} streak={r['current_streak']:<4} last_active={r['last_active_date']}")
        if len(rows) > 25:
            print(f"  ... and {len(rows) - 25} more")

        if not apply:
            print("\nPreview only — nothing written. Re-run with --apply to actually update these rows.")
            return

        result = await conn.execute(
            """
            UPDATE core.streaks
            SET last_active_date = $2
            WHERE last_active_date >= $1 AND last_active_date < $2
            """,
            CUTOFF_START, COVER_DATE,
        )
        print(f"\nDone: {result}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
