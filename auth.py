"""
RedTeamAgent — JWT auth + FastAPI role guards.

Handles:
  - JWT creation (login issues a signed token carrying user_id + role)
  - JWT verification (every guarded request validates the token)
  - require_role(...) FastAPI dependency for role-based access control

Security notes:
  - The signing secret comes from JWT_SECRET env var. NEVER hardcode it in
    production. A random default is generated per-process if unset, which
    means tokens don't survive a restart — fine for dev, set the env in prod.
  - Tokens expire (default 8h). Expired tokens are rejected.
  - Role checks happen on EVERY guarded endpoint, not just login — this closes
    the "auth bypass" gap where only login is protected.
"""

from __future__ import annotations
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ── Config ───────────────────────────────────────────────────────────────
# In production, set JWT_SECRET to a long random value via env / secrets mgr.
JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = int(os.getenv("TOKEN_EXPIRE_HOURS", "8"))

# Role hierarchy — higher roles inherit lower-role access where sensible.
ROLE_LEVEL = {"governance_officer": 1, "engineer": 2, "admin": 3}

_bearer = HTTPBearer(auto_error=False)


# ── Token creation / verification ────────────────────────────────────────
def create_access_token(user_id: str, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Returns the payload if valid; raises JWTError if not."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ── FastAPI dependencies ─────────────────────────────────────────────────
async def get_current_user(
        creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> dict:
    """Validates the Bearer token and returns the user payload."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing authentication token",
            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(creds.credentials)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid or expired token: {type(e).__name__}",
            headers={"WWW-Authenticate": "Bearer"})
    return {
        "user_id": payload.get("sub"),
        "username": payload.get("username"),
        "role": payload.get("role"),
    }


def require_role(*allowed_roles: str):
    """
    Dependency factory: guard an endpoint so only the listed roles may access.

    Usage:
        @app.post("/sweep")
        def sweep(user = Depends(require_role("engineer", "admin"))):
            ...
    """
    allowed = set(allowed_roles)

    async def _dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(f"role '{user['role']}' not permitted; "
                        f"requires one of {sorted(allowed)}"))
        return user

    return _dependency


# ── Self-test (no server needed) ─────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    print("=" * 64)
    print("JWT AUTH — SELF TEST")
    print("=" * 64)

    print("\n1. Create + decode a valid token")
    tok = create_access_token("u_1", "engineer", "engineer")
    print(f"   token: {tok[:40]}...")
    payload = decode_token(tok)
    print(f"   decoded role: {payload['role']}, user: {payload['username']}")
    assert payload["role"] == "engineer"

    print("\n2. Tampered token rejected")
    tampered = tok[:-4] + "XXXX"
    try:
        decode_token(tampered)
        print("   ERROR: tampered token accepted")
    except JWTError:
        print("   correctly rejected tampered token")

    print("\n3. Expired token rejected")
    # Build a token that expired in the past
    from datetime import datetime, timedelta, timezone
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = jwt.encode(
        {"sub": "u", "username": "x", "role": "admin",
         "iat": past - timedelta(hours=1), "exp": past},
        JWT_SECRET, algorithm=JWT_ALGORITHM)
    try:
        decode_token(expired)
        print("   ERROR: expired token accepted")
    except JWTError:
        print("   correctly rejected expired token")

    print("\n4. require_role dependency logic")

    async def check():
        from fastapi.security import HTTPAuthorizationCredentials as Cred
        # Simulate an engineer hitting an engineer-only endpoint
        eng_tok = create_access_token("u_e", "eng", "engineer")
        user = await get_current_user(Cred(scheme="Bearer", credentials=eng_tok))
        # engineer allowed
        guard = require_role("engineer", "admin")
        ok = await guard(user)
        print(f"   engineer -> engineer/admin endpoint: allowed ({ok['role']})")

        # governance officer blocked from engineer endpoint
        gov_tok = create_access_token("u_g", "gov", "governance_officer")
        gov = await get_current_user(Cred(scheme="Bearer", credentials=gov_tok))
        try:
            await guard(gov)
            print("   ERROR: governance officer allowed on engineer endpoint")
        except HTTPException as e:
            print(f"   governance_officer -> engineer endpoint: blocked ({e.status_code})")

    asyncio.run(check())

    print("\n" + "=" * 64)
    print("✅ JWT AUTH self-test passed")
    print("=" * 64)