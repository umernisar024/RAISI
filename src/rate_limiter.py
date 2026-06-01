"""
rate_limiter.py — Per-user daily question limit.

Tracks how many questions each user has asked today and enforces
a configurable daily cap. Counts reset automatically at midnight.

Config (in .env):
    DAILY_QUESTION_LIMIT=50   # max questions per user per day (0 = unlimited)

Storage:
    data/daily_usage.json — lightweight JSON, one entry per user per day.
    Old dates are pruned automatically to keep the file small.

Admin users are always exempt from the limit.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

USAGE_FILE = Path("data/daily_usage.json")


def _get_limit() -> int:
    """Return the daily question limit. 0 means unlimited."""
    return int(os.getenv("DAILY_QUESTION_LIMIT", "50"))


def _load() -> dict:
    """Load usage data from disk. Returns empty dict if file missing."""
    if not USAGE_FILE.exists():
        return {}
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    """Write usage data to disk atomically."""
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _today() -> str:
    """Return today's date string in the configured timezone (default: Australia/Sydney)."""
    tz_name = os.getenv("RATE_LIMIT_TIMEZONE", "Australia/Sydney")
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).strftime("%Y-%m-%d")


def _prune(data: dict) -> dict:
    """Remove all entries older than today to keep the file small."""
    today = _today()
    return {
        username: {d: count for d, count in days.items() if d >= today}
        for username, days in data.items()
    }


def get_usage_today(username: str) -> int:
    """Return how many questions this user has asked today."""
    data = _load()
    return data.get(username, {}).get(_today(), 0)


def get_limit() -> int:
    """Public accessor for the configured limit."""
    return _get_limit()


def check_limit(username: str, role: str) -> tuple[bool, int, int]:
    """
    Check whether the user is allowed to ask another question.

    Returns:
        allowed  (bool) — True if the user can proceed
        used     (int)  — questions asked today
        limit    (int)  — daily cap (0 = unlimited)

    Admin users are always allowed regardless of limit.
    """
    limit = _get_limit()

    # Admins and unlimited mode are always allowed
    if role == "admin" or limit == 0:
        return True, get_usage_today(username), limit

    used = get_usage_today(username)
    allowed = used < limit
    return allowed, used, limit


def record_question(username: str) -> int:
    """
    Increment today's question count for this user.
    Returns the updated count.
    """
    data = _load()
    data = _prune(data)

    today = _today()
    if username not in data:
        data[username] = {}
    data[username][today] = data[username].get(today, 0) + 1

    _save(data)
    return data[username][today]


def get_all_usage_today() -> dict[str, int]:
    """
    Return today's question count for every user.
    Used by the admin panel to show usage across all accounts.
    """
    data = _load()
    today = _today()
    return {username: days.get(today, 0) for username, days in data.items()}


def reset_user_today(username: str) -> None:
    """
    Reset today's count for a specific user (admin action).
    Useful if a test user hits their limit and needs more questions.
    """
    data = _load()
    if username in data and _today() in data[username]:
        data[username][_today()] = 0
        _save(data)
