"""
feedback.py — Save and retrieve user feedback on chatbot responses.

Feedback is stored as JSONL (one JSON object per line) in data/feedback_log.jsonl.
Each entry records: timestamp, username, role, question, answer, rating, comment.
"""

import json
from datetime import datetime
from pathlib import Path

FEEDBACK_FILE = Path("./data/feedback_log.jsonl")


def save_feedback(
    username: str,
    user_role: str,
    persona: str,
    question: str,
    answer: str,
    rating: str,          # "👍 Helpful" | "👎 Not helpful"
    comment: str = "",
) -> None:
    """Append a feedback entry to the log file."""
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "username": username,
        "user_role": user_role,
        "persona": persona,
        "question": question,
        "answer": answer[:500],   # truncate for storage
        "rating": rating,
        "comment": comment.strip(),
    }
    with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def load_feedback(limit: int = 100) -> list[dict]:
    """Load the most recent N feedback entries, newest first."""
    if not FEEDBACK_FILE.exists():
        return []
    lines = FEEDBACK_FILE.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(entries))[:limit]


def feedback_summary() -> dict:
    """Return a simple summary: total, helpful count, not helpful count."""
    entries = load_feedback(limit=0) if FEEDBACK_FILE.exists() else []
    # reload without limit
    if FEEDBACK_FILE.exists():
        lines = FEEDBACK_FILE.read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(l) for l in lines if l]
    total = len(entries)
    helpful = sum(1 for e in entries if "👍" in e.get("rating", ""))
    return {
        "total": total,
        "helpful": helpful,
        "not_helpful": total - helpful,
        "pct_helpful": round(helpful / total * 100) if total else 0,
    }
