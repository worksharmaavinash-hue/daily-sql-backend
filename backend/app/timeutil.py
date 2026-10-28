"""
The one definition of "today" for the whole app.

Daily problem sets, attempts, streaks and the heat-map all run on UTC time, and the app's
"day" flips at 00:00 UTC (12:00 AM UTC). Everything that needs the current app-day must call
app_today() so they can never disagree with each other, whatever timezone the server itself
runs in.
"""
from datetime import date, datetime, timezone

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:  # pragma: no cover - tz database missing
    import pytz
    IST = pytz.timezone("Asia/Kolkata")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ist() -> datetime:
    return datetime.now(IST)


def app_today() -> date:
    """The current app-day (UTC, flipping at 00:00 UTC / 12:00 AM UTC)."""
    return now_utc().date()

