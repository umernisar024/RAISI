"""
auth.py — User management for SIAgent.

Users are stored in data/users.json.
Passwords are hashed with PBKDF2-HMAC-SHA256 + random salt (600,000 iterations).

Old SHA-256-only hashes (no salt, from earlier versions) are detected and
automatically upgraded to PBKDF2 on the next successful login.

Roles:
    admin     — full access: chat, user management, system prompt, feedback log,
                security log, KB review
    reviewer  — chat + KB review (can approve/reject submitted documents)
    user      — chat + feedback only
"""

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

USERS_FILE = Path("./data/users.json")

# PBKDF2 parameters — increase ITERATIONS over time as hardware gets faster.
_ITERATIONS = 600_000
_HASH_NAME = "sha256"
_PREFIX = "pbkdf2"          # stored hash format: pbkdf2:<salt_hex>:<hash_hex>
_OLD_HASH_LEN = 64          # plain SHA-256 hex digest is always 64 chars


# ── Internal helpers ──────────────────────────────────────────────────────────

def _pbkdf2(password: str, salt: bytes) -> str:
    """Return a hex-encoded PBKDF2-HMAC-SHA256 digest."""
    dk = hashlib.pbkdf2_hmac(_HASH_NAME, password.encode("utf-8"), salt, _ITERATIONS)
    return dk.hex()


def _hash_password(password: str) -> str:
    """Hash a new password. Returns 'pbkdf2:<salt_hex>:<hash_hex>'."""
    salt = secrets.token_bytes(32)
    return f"{_PREFIX}:{salt.hex()}:{_pbkdf2(password, salt)}"


def _verify_password(password: str, stored: str) -> bool:
    """
    Verify a password against a stored hash.
    Handles both legacy plain-SHA-256 hashes and current PBKDF2 hashes.
    """
    if stored.startswith(f"{_PREFIX}:"):
        # Current format: pbkdf2:<salt_hex>:<hash_hex>
        try:
            _, salt_hex, expected_hex = stored.split(":", 2)
            salt = bytes.fromhex(salt_hex)
            actual = _pbkdf2(password, salt)
            # Constant-time compare to prevent timing attacks
            return hmac.compare_digest(actual, expected_hex)
        except ValueError:
            return False
    elif len(stored) == _OLD_HASH_LEN:
        # Legacy format: plain SHA-256 hex (no salt)
        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, stored)
    return False


def _load() -> dict:
    if not USERS_FILE.exists():
        _init()
    return json.loads(USERS_FILE.read_text(encoding="utf-8"))


def _save(users: dict) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def _init() -> None:
    """Create the default admin account on first run."""
    _save({
        "admin": {
            "password": _hash_password("SSCP@123"),
            "role": "admin",
            "name": "Administrator",
        }
    })


# ── Public API ────────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> dict | None:
    """
    Validate credentials. Returns user dict on success, None on failure.
    Automatically upgrades legacy SHA-256 hashes to PBKDF2 on success.
    Returned dict: { username, role, name }
    """
    users = _load()
    user = users.get(username.strip())
    if not user:
        return None

    stored = user["password"]
    if not _verify_password(password, stored):
        return None

    # Upgrade legacy hash to PBKDF2 transparently
    if not stored.startswith(f"{_PREFIX}:"):
        users[username]["password"] = _hash_password(password)
        _save(users)

    return {
        "username": username.strip(),
        "role": user["role"],
        "name": user.get("name", username),
    }


def get_all_users() -> list[dict]:
    """Return list of all users (without password hashes)."""
    users = _load()
    return [
        {"username": u, "role": d["role"], "name": d.get("name", u)}
        for u, d in users.items()
    ]


def add_user(username: str, password: str, role: str = "user", name: str = "") -> tuple[bool, str]:
    """Add a new user. Returns (success, message)."""
    username = username.strip()
    if not username or not password:
        return False, "Username and password are required."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    users = _load()
    if username in users:
        return False, f"Username '{username}' already exists."
    users[username] = {
        "password": _hash_password(password),
        "role": role,
        "name": name.strip() or username,
    }
    _save(users)
    return True, f"User '{username}' created."


def delete_user(username: str) -> tuple[bool, str]:
    """Delete a user. Admin account cannot be deleted."""
    if username == "admin":
        return False, "The admin account cannot be deleted."
    users = _load()
    if username not in users:
        return False, f"User '{username}' not found."
    del users[username]
    _save(users)
    return True, f"User '{username}' deleted."


def change_password(username: str, new_password: str) -> tuple[bool, str]:
    """Change a user's password."""
    if not new_password:
        return False, "Password cannot be empty."
    if len(new_password) < 8:
        return False, "Password must be at least 8 characters."
    users = _load()
    if username not in users:
        return False, f"User '{username}' not found."
    users[username]["password"] = _hash_password(new_password)
    _save(users)
    return True, "Password updated."
