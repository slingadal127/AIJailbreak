# RedTeamAgent

> Stress-tests your AI's safety guardrails automatically — and produces evidence a regulator will accept.

RedTeamAgent is an automated safety-testing framework for AI-powered products. It generates realistic adversarial prompts against your AI, grades every response, systematically explores near-misses, and produces an auditable record of everything it tested — turning safety testing from a manual, one-off exercise into a repeatable engineering discipline.

## 🚀 Live demo

The framework is deployed as two Docker services on Railway. Try it in your browser:

**Live URL:** *replace this line with your actual Railway frontend URL, e.g. `https://aijailbreak-staging.up.railway.app/`*

Log in with the default accounts below. The first request after an idle period may take 20–30 seconds while the container warms up.

## Why this exists

Every AI-powered product ships with guardrails: refuse harmful requests, don't leak private data, don't be tricked into acting on injected instructions. But guardrails fail in ways that are hard to spot until someone posts a screenshot on Twitter.

Today, most teams test these guardrails by hand — an engineer sits down and tries a few tricky prompts. That approach is:

- **Slow** — a thorough manual sweep takes days
- **Inconsistent** — every tester probes differently, and a tired tester misses edge cases
- **Not auditable** — screenshots don't answer "how do we know our AI is safe?" when compliance asks
- **Expensive at scale** — dedicated red-teamers cost hundreds of dollars per hour

Meanwhile, regulators are catching up. The EU AI Act's Article 9 now legally requires documented red-teaming for high-risk AI, and equivalent requirements are appearing in NIST AI RMF and elsewhere.

**RedTeamAgent solves this by automating the systematic parts** — attack generation, grading, mutation, audit logging — so humans focus on interpretation and remediation rather than typing prompts by hand.

## Who this is for

- **AI safety engineers** shipping AI features who need systematic coverage before launch
- **Governance and compliance officers** who need auditable proof that safety testing was done, without ever seeing the raw jailbreak payload
- **Security researchers** exploring novel attack classes who want the framework to probe nearby prompt space automatically
- **Product leaders** who want to launch AI features without waking up to a viral screenshot

## What it does

Given a description of what your AI should *not* do (e.g., "should never help write phishing emails"), the framework:

1. **Generates** dozens of realistic adversarial variants across six attack categories: roleplay, encoding tricks, many-shot manipulation, token smuggling, prompt injection, and published jailbreak transfers
2. **Attacks** the target AI with each variant
3. **Evaluates** every response with a calibrated LLM-as-judge, returning FAIL / PARTIAL / SUCCESS with a confidence score and reasoning
4. **Mutates** near-misses — when a variant hedges instead of clearly refusing, the framework automatically generates refined variants targeting the weak point the judge named
5. **Reports** everything to an audit log with sweep ID, user, timestamp, verdicts, and reasoning — ready for compliance to query

A **dual-mode design** also detects legitimate defensive-security and educational requests (e.g., "explain phishing techniques so I can train employees") and evaluates whether the AI *helpfully complied* rather than treating it as an attack. Because an AI that refuses everything is safe but useless.

## Architecture

Streamlit UI (thin HTTP client) → FastAPI backend with JWT auth and role guards → LangGraph pipeline (memory check → RAG retrieval → dedup → generate → judge → conditional mutate → store) → ChromaDB attack library + SQLite audit log + OpenAI GPT-4o.

A **pre-flight safety filter** with a categorized keyword blocklist runs before any LLM call, catching high-severity attack targets and obfuscation attempts (leetspeak, homoglyphs, base64) before they reach the pipeline.

Three enforced roles — `engineer`, `governance_officer`, `admin` — each with different visibility. Governance officers see aggregated safety metrics and redacted history; raw attack prompts are stripped server-side before responses leave the API.

## Setup

Two ways to run locally: **native Python** for development, or **Docker Compose** for the same setup that ships to production.

### Option 1 — Native Python

```bash
# 1. Virtual environment + dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Environment configuration
cp .env.example .env
# Edit .env — set OPENAI_API_KEY and generate a JWT_SECRET:
#   python3 -c "import secrets; print(secrets.token_urlsafe(64))"

# 3. Run backend + frontend together
chmod +x run_all.sh
./run_all.sh
```

Open http://localhost:8501 and log in.

### Option 2 — Docker Compose

```bash
# Same two-service setup that runs in production
docker compose -f docker/docker-compose.yml up --build
```

Requires an `.env` file at the project root with `OPENAI_API_KEY` set. Open http://localhost:8501 once both containers are healthy.

## Default accounts

| Username | Password | Role |
|----------|----------|------|
| engineer | ******** | Full pipeline access |
| governance_officer | ******** | Read-only, redacted view |
| admin | ******** | Everything + admin tools |

Override these via `SEED_ENGINEER_PW`, `SEED_GOV_PW`, and `SEED_ADMIN_PW` environment variables for any non-local deployment.

## Deployment

Production deployment runs on Railway as two independent Docker services. Every push to `main` triggers an automatic rebuild.

- **Backend** — `docker/Dockerfile.backend`, FastAPI + LangGraph pipeline, listens on `$PORT` (falls back to 8000 locally)
- **Frontend** — `docker/Dockerfile.frontend`, Streamlit, listens on `$PORT` (falls back to 8501 locally)
- **Secrets** — `OPENAI_API_KEY`, `JWT_SECRET`, and `SEED_*_PW` are set via the Railway Variables UI, never committed
- **Data** — SQLite for auth and audit log (currently ephemeral — resets on redeploy; persistent volume support is roadmapped)

## Honest limitations

- The default target is a deterministic simulator, not a live AI. Pointing the framework at a real AI API endpoint is scoped as future work — the pipeline is target-agnostic, only the target adapter needs to change.
- Auth uses a local SQLite credential store. Production deployments would swap this for a managed IdP.
- Bias evaluation catches gross disparities across a small set of demographic framings, not nuanced ones. Standardized suites (BBQ, HolisticBias) are roadmapped.
- The keyword blocklist can never be complete on its own; novel adversarial framings need the LLM classifier layer that runs after it.
- Judge accuracy is measured against a frozen 30-example evaluation set. `PROMPT_INJECTION` is the reproducibly weakest category — verdicts in that category are gated on human review.

## License

Do not use this framework to attack systems you do not own or have written authorization to test. Intended for defensive security research, guardrail hardening, and compliance evidence generation only.