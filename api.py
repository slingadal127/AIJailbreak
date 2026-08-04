"""
RedTeamAgent — FastAPI backend.

The single backend that owns all business logic. Streamlit is a thin client
that talks to these endpoints over HTTP with a JWT bearer token.

Endpoints:
  POST /auth/login          -> issue JWT           (public)
  GET  /auth/me             -> current user info   (any authenticated)
  POST /sweep               -> run a sweep         (engineer, admin)
  GET  /history             -> past verdicts       (all roles; redacted for gov)
  GET  /compliance          -> aggregate ASR       (all roles)
  GET  /admin/drift         -> judge drift status  (admin only)
  GET  /admin/users         -> list users          (admin only)

Role enforcement is applied on EVERY protected endpoint via require_role,
not just login — this is what makes the auth real rather than cosmetic.

Run:
    uvicorn api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations
import os
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth_db import authenticate, seed_default_users, list_users
from auth import create_access_token, get_current_user, require_role

# Pipeline logic — the backend imports redteam_core, the frontend never does.
from redteam_core import (
    run_sweep, get_all_verdicts, ATTACK_LIBRARY,
)

app = FastAPI(title="RedTeamAgent API", version="1.0")

# CORS — allow the Streamlit origin. Tighten this in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:8501").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# On startup, ensure the 3 default users exist.
@app.on_event("startup")
def _startup():
    created = seed_default_users()
    if created:
        print(f"[startup] seeded users: {[c['username'] for c in created]}")


# ── Request/response models ──────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class SweepRequest(BaseModel):
    target_behavior: str
    attack_category: str = "ROLEPLAY"
    num_variants: int = 2
    max_mutations: int = 2
    filter_mode: str = "research"


# ── Public: login ────────────────────────────────────────────────────────
@app.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest):
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials or account locked")
    token = create_access_token(user["user_id"], user["username"], user["role"])
    return LoginResponse(access_token=token, role=user["role"],
                         username=user["username"])


# ── Any authenticated user: who am I ─────────────────────────────────────
@app.get("/auth/me")
def me(user: dict = Depends(get_current_user)):
    return user


# ── Engineer + admin: run a sweep ────────────────────────────────────────
@app.post("/sweep")
def sweep(req: SweepRequest,
          user: dict = Depends(require_role("engineer", "admin"))):
    """Run a red-team sweep. Guarded — governance officers get 403."""
    result = run_sweep(
        target_behavior=req.target_behavior,
        attack_category=req.attack_category,
        num_variants=req.num_variants,
        max_mutations=req.max_mutations,
        filter_mode=req.filter_mode,
    )
    # Drop the non-serializable session object if present
    result.pop("session", None)
    # Tag the audit trail with who ran it
    result["run_by"] = user["username"]
    result["run_by_role"] = user["role"]
    return result


# ── All roles: history (redacted for governance officers) ────────────────
@app.get("/history")
def history(limit: int = 100, user: dict = Depends(get_current_user)):
    verdicts = get_all_verdicts(limit=limit)

    # Server-side redaction: governance officers never receive raw attack text.
    # (The current schema stores target_behavior, not raw prompts, but we apply
    #  the redaction pattern so it's correct as the schema grows.)
    if user["role"] == "governance_officer":
        for v in verdicts:
            if "target_behavior" in v:
                v["target_behavior"] = "[redacted — governance role]"
    return {"verdicts": verdicts, "viewer_role": user["role"]}


# ── All roles: compliance aggregates ─────────────────────────────────────
@app.get("/compliance")
def compliance(user: dict = Depends(get_current_user)):
    verdicts = get_all_verdicts(limit=500)
    # Aggregate ASR by category (no raw text exposed to anyone here)
    from collections import Counter
    by_cat_total = Counter()
    by_cat_hits = Counter()
    for v in verdicts:
        cat = v.get("category", "UNKNOWN")
        by_cat_total[cat] += 1
        if v.get("verdict") in ("SUCCESS", "PARTIAL"):
            by_cat_hits[cat] += 1
    asr_by_cat = {
        cat: {"total": by_cat_total[cat], "hits": by_cat_hits[cat],
              "asr": round(by_cat_hits[cat] / by_cat_total[cat], 3) if by_cat_total[cat] else 0.0}
        for cat in by_cat_total
    }
    return {
        "asr_by_category": asr_by_cat,
        "total_verdicts": len(verdicts),
        "library_size": len(ATTACK_LIBRARY),
        "viewer_role": user["role"],
    }


# ── Admin only: judge drift ──────────────────────────────────────────────
@app.get("/admin/drift")
def admin_drift(user: dict = Depends(require_role("admin"))):
    try:
        from redteam_drift import get_drift_history
        history = get_drift_history(limit=10)
        return {"drift_history": history}
    except ImportError:
        raise HTTPException(status_code=503,
                            detail="drift module (E5) not available")


# ── Admin only: list users ───────────────────────────────────────────────
@app.get("/admin/users")
def admin_users(user: dict = Depends(require_role("admin"))):
    return {"users": list_users()}


# ── Health check (public) ────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "redteam-api"}