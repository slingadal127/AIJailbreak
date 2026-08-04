# RedTeamAgent

Automated AI safety red-teaming framework. Generates adversarial prompts to test AI guardrails, evaluates responses via LLM-as-judge, and mutates partial successes to probe further. INFO 7375 course project (Assignments 2–5) with post-graded enhancements (E1–E6).

## Architecture

Streamlit UI (thin HTTP client) → FastAPI backend (guarded endpoints) → redteam_core (LangGraph pipeline + tools + memory) → ChromaDB (25 attack library) + SQLite (auth users, verdicts, drift) + OpenAI API (gpt-4o).

## Quick start

```bash
# 1. venv + deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. environment
cp .env.example .env
# then edit .env — set OPENAI_API_KEY and generate a JWT_SECRET

# 3. run backend + frontend
chmod +x run_all.sh
./run_all.sh
```

Open http://localhost:8501 and log in.

## Default accounts

| Username | Password | Role |
|----------|----------|------|
| engineer | engineer123 | Full pipeline access |
| governance_officer | governance123 | Read-only, redacted view |
| admin | admin123 | Everything + admin tools |

Change these via env vars (SEED_ENGINEER_PW, SEED_GOV_PW, SEED_ADMIN_PW) for any non-local deployment.

## Enhancements (E1–E6, post-graded feedback)

- **E1** — Real JWT auth + role enforcement + server-side redaction
- **E2** — 3-layer obfuscation-resistant input filter
- **E3** — Adaptive strategy selection with epsilon-explore
- **E4** — Novelty, diversity, cost, calibration metrics
- **E5** — Judge drift monitoring (frozen 30-example eval set)
- **E6** — 12-framing bias testing with chi-square parity

See ENHANCEMENTS_CHANGELOG.md for details.

## Honest limitations

- Target is a deterministic simulator, not a live AI (documented future work)
- Auth uses local SQLite credential store — production would use managed IdP
- Bias evaluation catches gross disparities, not nuanced ones
- Keyword blocklist can never be complete; LLM classifier catches novel framings

## License

Course project. Do not use to attack systems you don't own or have written authorization to test.
