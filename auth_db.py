"""
RedTeamAgent — Auth DB layer.

SQLite-backed user store with bcrypt-hashed passwords and roles.
This is the identity source of truth for the FastAPI backend.

Roles: engineer | governance_officer | admin

Security notes:
  - Passwords are NEVER stored in plaintext — only bcrypt hashes.
  - bcrypt automatically salts each hash (no separate salt column needed).
  - This module does no auth decisions itself; it only stores and verifies
    credentials. Token issuance + role checks live in auth.py / api.py.
"""

from __future__ import annotations
import sqlite3
import os
from datetime import datetime
from typing import Optional

import bcrypt

AUTH_DB_PATH = os.getenv("AUTH_DB_PATH", "redteam_auth.db")

VALID_ROLES = {"engineer", "governance_officer", "admin"}


# ─────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────
def init_auth_db(path: str = AUTH_DB_PATH) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id       TEXT PRIMARY KEY,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        last_login    TEXT,
        is_active     INTEGER NOT NULL DEFAULT 1,
        failed_attempts INTEGER NOT NULL DEFAULT 0
    )""")
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────────────────
def hash_password(plaintext: str) -> str:
    """bcrypt hash (includes salt). Returns a str for DB storage."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def verify_password(plaintext: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"),
                              password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ─────────────────────────────────────────────────────────────────────────
# User CRUD
# ─────────────────────────────────────────────────────────────────────────
def create_user(username: str, password: str, role: str,
                path: str = AUTH_DB_PATH) -> dict:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role '{role}'; must be one of {VALID_ROLES}")

    init_auth_db(path)
    user_id = f"u_{username}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    pwd_hash = hash_password(password)

    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, role, created_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, username, pwd_hash, role, datetime.now().isoformat()))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"username '{username}' already exists")
    conn.close()
    return {"user_id": user_id, "username": username, "role": role}


def get_user(username: str, path: str = AUTH_DB_PATH) -> Optional[dict]:
    init_auth_db(path)
    conn = sqlite3.connect(path)
    row = conn.execute(
        "SELECT user_id, username, password_hash, role, is_active, failed_attempts "
        "FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "user_id": row[0], "username": row[1], "password_hash": row[2],
        "role": row[3], "is_active": bool(row[4]), "failed_attempts": row[5],
    }


def authenticate(username: str, password: str,
                 path: str = AUTH_DB_PATH,
                 max_failed: int = 5) -> Optional[dict]:
    """
    Verify credentials. Returns user dict (without hash) on success, None on
    failure. Tracks failed attempts and locks the account after max_failed.
    """
    user = get_user(username, path)
    if not user:
        return None
    if not user["is_active"]:
        return None
    # Account lockout
    if user["failed_attempts"] >= max_failed:
        return None

    if verify_password(password, user["password_hash"]):
        _reset_failed(username, path)
        _touch_login(username, path)
        return {"user_id": user["user_id"], "username": user["username"],
                "role": user["role"]}
    else:
        _increment_failed(username, path)
        return None


def _increment_failed(username: str, path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("UPDATE users SET failed_attempts = failed_attempts + 1 "
                 "WHERE username=?", (username,))
    conn.commit()
    conn.close()


def _reset_failed(username: str, path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("UPDATE users SET failed_attempts = 0 WHERE username=?",
                 (username,))
    conn.commit()
    conn.close()


def _touch_login(username: str, path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("UPDATE users SET last_login=? WHERE username=?",
                 (datetime.now().isoformat(), username))
    conn.commit()
    conn.close()


def list_users(path: str = AUTH_DB_PATH) -> list:
    init_auth_db(path)
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT username, role, created_at, last_login, is_active, failed_attempts "
        "FROM users ORDER BY created_at").fetchall()
    conn.close()
    return [{"username": r[0], "role": r[1], "created_at": r[2],
             "last_login": r[3], "is_active": bool(r[4]),
             "failed_attempts": r[5]} for r in rows]


def seed_default_users(path: str = AUTH_DB_PATH,
                       reset: bool = False) -> list:
    """
    Create the 3 default accounts. Passwords come from env vars if set,
    otherwise fall back to documented defaults (CHANGE THESE in production).
    """
    if reset and os.path.exists(path):
        os.remove(path)
    init_auth_db(path)

    defaults = [
        ("engineer",           os.getenv("SEED_ENGINEER_PW", "engineer123"),  "engineer"),
        ("governance_officer", os.getenv("SEED_GOV_PW", "governance123"),      "governance_officer"),
        ("admin",              os.getenv("SEED_ADMIN_PW", "admin123"),         "admin"),
    ]
    created = []
    for username, pw, role in defaults:
        if get_user(username, path) is None:
            create_user(username, pw, role, path)
            created.append({"username": username, "role": role})
    return created


# ─────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 64)
    print("AUTH DB — SELF TEST")
    print("=" * 64)

    TEST_DB = "test_auth.db"
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    print("\n1. Seed default users")
    created = seed_default_users(TEST_DB)
    for c in created:
        print(f"   created {c['username']} ({c['role']})")

    print("\n2. Correct password authenticates")
    u = authenticate("engineer", "engineer123", TEST_DB)
    print(f"   engineer/engineer123 -> {u}")
    assert u and u["role"] == "engineer"

    print("\n3. Wrong password rejected")
    u = authenticate("engineer", "wrongpass", TEST_DB)
    print(f"   engineer/wrongpass   -> {u}")
    assert u is None

    print("\n4. Password is hashed, not plaintext")
    raw = get_user("admin", TEST_DB)
    print(f"   stored hash starts with: {raw['password_hash'][:20]}...")
    assert raw["password_hash"] != "admin123"
    assert raw["password_hash"].startswith("$2b$")

    print("\n5. Account lockout after 5 failed attempts")
    for i in range(5):
        authenticate("governance_officer", "bad", TEST_DB)
    locked = authenticate("governance_officer", "governance123", TEST_DB)
    print(f"   after 5 fails, correct pw -> {locked} (should be None = locked)")
    assert locked is None

    print("\n6. Duplicate username rejected")
    try:
        create_user("admin", "x", "admin", TEST_DB)
        print("   ERROR: duplicate allowed")
    except ValueError as e:
        print(f"   correctly rejected: {e}")

    print("\n7. Invalid role rejected")
    try:
        create_user("newbie", "x", "superuser", TEST_DB)
        print("   ERROR: invalid role allowed")
    except ValueError as e:
        print(f"   correctly rejected: {e}")

    os.remove(TEST_DB)
    print("\n" + "=" * 64)
    print("✅ AUTH DB self-test passed")
    print("=" * 64)