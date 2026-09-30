"""
The one definition of "today" for the whole app.

Daily problem sets, attempts, streaks and the heat-map all run on India time, and the app's
"day" flips at 01:00 IST (matching how the daily set is published). Everything that needs the
current app-day must call app_today() so they can never disagree with each other, whatever
timezone the server itself runs in (Docker containers default to UTC).
"""
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:  # pragma: no cover - tz database missing
    import pytz
    IST = pytz.timezone("Asia/Kolkata")

DAY_FLIP_OFFSET = timedelta(hours=1)


def now_ist() -> datetime:
    return datetime.now(IST)


def app_today() -> date:
    """The current app-day (IST, flipping at 01:00)."""
    return (now_ist() - DAY_FLIP_OFFSET).date()
