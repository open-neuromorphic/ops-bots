import pytz
from datetime import datetime

COMMON_TIMEZONES = {
    'PST': 'America/Los_Angeles',
    'PDT': 'America/Los_Angeles',
    'MST': 'America/Denver',
    'MDT': 'America/Denver',
    'CST': 'America/Chicago',
    'CDT': 'America/Chicago',
    'EST': 'America/New_York',
    'EDT': 'America/New_York',
    'CET': 'Europe/Berlin',
    'CEST': 'Europe/Berlin',
    'BST': 'Europe/London',
    'GMT': 'UTC',
    'UTC': 'UTC',
    'IST': 'Asia/Kolkata',
    'JST': 'Asia/Tokyo',
    'AEST': 'Australia/Sydney',
    'AEDT': 'Australia/Sydney'
}


def parse_event_datetime(date_str: str, time_str: str, tz_str: str) -> datetime:
    """Parses human-friendly date, time, and timezone strings into a timezone-aware datetime object."""
    tz_name = COMMON_TIMEZONES.get(tz_str.upper().strip(), tz_str.strip())
    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        raise ValueError(
            f"Unknown timezone: `{tz_str}`. Use abbreviations like EST, CEST, or IANA names like Europe/Berlin.")

    try:
        dt_date = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format: `{date_str}`. Please use YYYY-MM-DD.")

    time_str = time_str.strip().upper()
    dt_time = None
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%H:%M:%S"):
        try:
            dt_time = datetime.strptime(time_str, fmt).time()
            break
        except ValueError:
            continue

    if not dt_time:
        raise ValueError(
            f"Invalid time format: `{time_str}`. Please use HH:MM (e.g., 14:00) or 12-hour (e.g., 2:00 PM).")

    naive_dt = datetime.combine(dt_date, dt_time)

    # Use localize to correctly handle DST transitions
    aware_dt = tz.localize(naive_dt)
    return aware_dt