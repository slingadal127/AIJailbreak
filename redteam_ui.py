"""
RedTeamAgent — Streamlit UI (thin HTTP client).

This UI OWNS NO BUSINESS LOGIC. It authenticates against the FastAPI backend,
stores a JWT in session state, and calls the backend's REST endpoints for
every operation. The pipeline (LangGraph, tools, memory) lives entirely in
the backend.

Run the backend first:
    uvicorn api:app --port 8000
Then in a second terminal:
    streamlit run redteam_ui.py

The old in-process version is preserved as redteam_ui_direct.py.
"""

from __future__ import annotations
import os
import requests
import streamlit as st
from collections import Counter
import pandas as pd

API_BASE = os.getenv("REDTEAM_API_BASE", "http://localhost:8000")

st.set_page_config(page_title="RedTeamAgent", page_icon="🛡️", layout="wide")


# ─────────────────────────────────────────────────────────────────────────
# API helper — every call goes through here so auth + errors are uniform
# ─────────────────────────────────────────────────────────────────────────
def api_call(method: str, path: str, **kwargs):
    """Make an authenticated call to the backend. Returns (ok, data)."""
    headers = kwargs.pop("headers", {})
    if "token" in st.session_state:
        headers["Authorization"] = f"Bearer {st.session_state.token}"

    try:
        r = requests.request(method, f"{API_BASE}{path}",
                             headers=headers, timeout=120, **kwargs)
    except requests.exceptions.ConnectionError:
        return False, {"error": f"Backend unreachable at {API_BASE}. "
                                f"Start it with: uvicorn api:app --port 8000"}
    except requests.exceptions.Timeout:
        return False, {"error": "Backend timed out (>120s)."}

    if r.status_code == 401:
        st.session_state.pop("token", None)
        st.session_state.pop("role", None)
        st.session_state.pop("username", None)
        return False, {"error": "Session expired. Please log in again."}
    if r.status_code == 403:
        try:
            detail = r.json().get("detail", "Forbidden for your role.")
        except Exception:
            detail = "Forbidden for your role."
        return False, {"error": detail}
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        return False, {"error": f"HTTP {r.status_code}: {detail}"}
    return True, r.json()


# ─────────────────────────────────────────────────────────────────────────
# LOGIN GATE
# ─────────────────────────────────────────────────────────────────────────
def render_login():
    st.title("🛡️ RedTeamAgent")
    st.caption("AI Safety Red Teaming Framework")
    st.markdown("---")

    ok_health, _ = api_call("GET", "/health")
    if not ok_health:
        st.error(f"⚠️ Backend is not reachable at `{API_BASE}`.")
        st.code("uvicorn api:app --port 8000", language="bash")
        st.stop()

    st.subheader("Sign in")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")

    if submitted:
        ok, data = api_call("POST", "/auth/login",
                            json={"username": username, "password": password})
        if ok:
            st.session_state.token = data["access_token"]
            st.session_state.role = data["role"]
            st.session_state.username = data["username"]
            st.rerun()
        else:
            st.error(data.get("error", "Login failed."))

    st.markdown("---")
    with st.expander("Development accounts"):
        st.markdown(
            "- `engineer` / `engineer123` — full pipeline access\n"
            "- `governance_officer` / `governance123` — read-only + redacted\n"
            "- `admin` / `admin123` — full access + admin tools\n\n"
            "*Passwords are bcrypt-hashed in SQLite. "
            "Set `SEED_*_PW` env vars to override defaults.*")


# ─────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────
def render_sidebar():
    role = st.session_state.role
    badge_color = {"engineer": "#2166a5", "governance_officer": "#c47700",
                   "admin": "#6a3aa7"}.get(role, "#666")

    st.sidebar.markdown(
        f"### Signed in as\n"
        f"**{st.session_state.username}** "
        f"<span style='color:{badge_color};font-weight:600;'>● {role}</span>",
        unsafe_allow_html=True)
    st.sidebar.caption(f"Backend: `{API_BASE}`")
    if st.sidebar.button("Log out"):
        st.session_state.clear()
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Governance officers cannot run sweeps or view raw attack prompts. "
        "Redaction is enforced server-side, not in the UI.")


# ─────────────────────────────────────────────────────────────────────────
# TAB: Run Sweep (engineer + admin)
# ─────────────────────────────────────────────────────────────────────────
def render_run_sweep():
    st.header("🚀 Run Sweep")
    st.caption("Every sweep call goes through the backend and is tagged with "
               "your `user_id` in the audit log.")

    target_behavior = st.text_area(
        "Target behavior (what you want to test)",
        placeholder="e.g., Get an AI to produce phishing email templates",
        height=80)
    col1, col2, col3 = st.columns(3)
    with col1:
        category = st.selectbox(
            "Attack category",
            ["ROLEPLAY", "ENCODING", "MANY_SHOT", "TOKEN_SMUGGLING",
             "PROMPT_INJECTION", "JAILBREAK_TRANSFER"])
    with col2:
        num_variants = st.slider("Variants", 1, 10, 2)
    with col3:
        max_mutations = st.slider("Max mutation rounds", 0, 5, 2)

    if st.button("▶ Run Sweep", type="primary"):
        if not target_behavior.strip():
            st.error("Please enter a target behavior.")
            return

        with st.status("Calling backend...", expanded=True) as status:
            st.write("POST /sweep — authenticated with JWT")
            ok, result = api_call("POST", "/sweep", json={
                "target_behavior": target_behavior,
                "attack_category": category,
                "num_variants": num_variants,
                "max_mutations": max_mutations,
                "filter_mode": "research",
            })
            if not ok:
                status.update(label="Sweep failed", state="error")
                st.error(result.get("error", "Unknown error."))
                return

            if result.get("blocked"):
                status.update(label="Blocked by pre-flight filter 🛑",
                              state="error")
                st.error(
                    f"**Request blocked before any AI call.**\n\n"
                    f"Reason: {result.get('block_reason')}")
                detail = result.get("block_detail", {})
                if detail.get("was_obfuscated"):
                    st.warning(
                        f"Filter detected obfuscation and de-obfuscated via "
                        f"**{detail.get('matched_view')}** normalization.")
                with st.expander("🔍 Pre-flight detail (for audit)"):
                    st.json(detail)
                return

            for line in result.get("node_log", []):
                st.code(line, language=None)
            status.update(label="Sweep complete ✅", state="complete")

        # ── Mode banner: benign vs adversarial ───────────────────────
        mode = result.get("mode", "adversarial")
        benign = result.get("benign_intent", {})

        if mode == "benign":
            st.info(
                f"ℹ️ **Benign evaluation mode.** "
                f"The target was detected as defensive-security, educational, "
                f"or research-oriented (markers: "
                f"{', '.join(benign.get('markers_found', []))}). "
                f"For benign requests, the framework skips adversarial "
                f"framing and evaluates directly: does the AI **help** or "
                f"**over-refuse**? Verdicts are labelled HELPFUL / HEDGED / "
                f"OVER_REFUSED accordingly."
            )
        elif benign.get("is_benign_target"):
            # (This branch shouldn't fire now that benign gets its own path,
            #  but kept for safety.)
            st.info(
                f"ℹ️ Benign markers detected but adversarial mode ran anyway. "
                f"Verdicts reflect adversarial evaluation."
            )

        st.markdown("---")
        st.subheader("Results")
        st.caption(f"Run by **{result.get('run_by')}** "
                   f"({result.get('run_by_role')}) — logged server-side.")

        verdicts = result.get("verdicts", [])
        counts = Counter(v["verdict"] for v in verdicts)

        if mode == "benign":
            # Different counters for benign mode — HELPFUL / HEDGED / OVER_REFUSED
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Evaluated", len(verdicts))
            m2.metric("HELPFUL", counts.get("HELPFUL", 0))
            m3.metric("HEDGED", counts.get("HEDGED", 0))
            m4.metric("OVER_REFUSED", counts.get("OVER_REFUSED", 0))
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Variants tested", len(verdicts))
            m2.metric("SUCCESS", counts.get("SUCCESS", 0))
            m3.metric("PARTIAL", counts.get("PARTIAL", 0))
            m4.metric("Tokens", f"{result.get('total_tokens', 0):,}")

        if verdicts:
            st.markdown("**Verdict table**")
            st.dataframe(pd.DataFrame([{
                "variant": v.get("variant_id", "-"),
                "category": v.get("category", "-"),
                "verdict": v.get("verdict", "-"),
                "confidence": v.get("confidence", "-"),
                "prompt": (v.get("prompt", "") or "")[:120] + "...",
            } for v in verdicts]),
                use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────
# TAB: History (all roles — governance sees redacted)
# ─────────────────────────────────────────────────────────────────────────
def render_history():
    st.header("📋 Sweep History")
    ok, data = api_call("GET", "/history", params={"limit": 100})
    if not ok:
        st.error(data.get("error", "Failed to load history."))
        return

    verdicts = data.get("verdicts", [])
    if data.get("viewer_role") == "governance_officer":
        st.info("🔒 Viewing as **governance officer** — raw attack text is "
                "redacted server-side.")

    if not verdicts:
        st.info("No sweeps recorded yet.")
        return

    df = pd.DataFrame(verdicts)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"{len(verdicts)} verdict(s) shown.")


# ─────────────────────────────────────────────────────────────────────────
# TAB: Compliance (all roles)
# ─────────────────────────────────────────────────────────────────────────
def render_compliance():
    st.header("📊 Compliance Report")
    ok, data = api_call("GET", "/compliance")
    if not ok:
        st.error(data.get("error", "Failed to load compliance data."))
        return

    m1, m2 = st.columns(2)
    m1.metric("Total verdicts", data.get("total_verdicts", 0))
    m2.metric("Attack library size", data.get("library_size", 0))

    asr = data.get("asr_by_category", {})
    if asr:
        st.markdown("**Attack Success Rate by category**")
        st.dataframe(pd.DataFrame([
            {"category": c, "total": v["total"], "hits": v["hits"],
             "asr": v["asr"]}
            for c, v in asr.items()
        ]), use_container_width=True, hide_index=True)
    else:
        st.info("Not enough data for aggregates yet.")


# ─────────────────────────────────────────────────────────────────────────
# TAB: Admin (admin only)
# ─────────────────────────────────────────────────────────────────────────
def render_admin():
    st.header("⚙️ Admin")
    st.caption("Admin-only tools: user list + judge drift history.")

    tab_u, tab_d = st.tabs(["Users", "Judge drift (E5)"])

    with tab_u:
        ok, data = api_call("GET", "/admin/users")
        if not ok:
            st.error(data.get("error"))
        else:
            st.dataframe(pd.DataFrame(data.get("users", [])),
                         use_container_width=True, hide_index=True)

    with tab_d:
        ok, data = api_call("GET", "/admin/drift")
        if not ok:
            st.warning(data.get("error",
                                "Drift module not available on backend."))
        else:
            hist = data.get("drift_history", [])
            if not hist:
                st.info("No drift runs recorded yet. Trigger one from a "
                        "notebook: `run_judge_eval()`.")
            else:
                st.dataframe(pd.DataFrame(hist),
                             use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────
# MAIN — role-driven tab visibility
# ─────────────────────────────────────────────────────────────────────────
def main():
    if "token" not in st.session_state:
        render_login()
        return

    render_sidebar()
    st.title("🛡️ RedTeamAgent")

    role = st.session_state.role
    tab_names = []
    if role in ("engineer", "admin"):
        tab_names.append("🚀 Run Sweep")
    tab_names.append("📋 History")
    tab_names.append("📊 Compliance")
    if role == "admin":
        tab_names.append("⚙️ Admin")

    tabs = st.tabs(tab_names)
    idx = 0
    if role in ("engineer", "admin"):
        with tabs[idx]:
            render_run_sweep()
        idx += 1
    with tabs[idx]:
        render_history()
    idx += 1
    with tabs[idx]:
        render_compliance()
    idx += 1
    if role == "admin":
        with tabs[idx]:
            render_admin()


main()