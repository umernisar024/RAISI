"""
security_log.py — Append-only log of security-relevant events.

Events are written to data/security_log.jsonl (one JSON object per line).
Logged events: failed_login, successful_login, account_locked,
               admin_action, password_changed, user_created, user_deleted.

Keep this file simple — it must never raise an exception and must never
block the request that triggered the event.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

SECURITY_LOG_FILE = Path("./data/security_log.jsonl")


def log_event(
    event: str,
    username: str = "",
    detail: str = "",
    ip: str = "",
) -> None:
    """
    Append a security event to the log. Silently swallows any I/O errors
    so a logging failure never crashes the application.
    """
    try:
        SECURITY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            "username": username,
            "detail": detail,
            "ip": ip,
        }
        with SECURITY_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never let logging break the app


def load_security_log(limit: int = 200) -> list[dict]:
    """
    Load the most recent N security log entries, newest first.
    Pass limit=0 or a very large number to load all entries (e.g. for CSV export).
    """
    if not SECURITY_LOG_FILE.exists():
        return []
    try:
        lines = SECURITY_LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        reversed_entries = list(reversed(entries))
        return reversed_entries[:limit] if limit else reversed_entries
    except Exception:
        return []
