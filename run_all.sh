#!/bin/bash
# Launch RedTeamAgent — FastAPI backend + Streamlit frontend together.
#
# Usage:
#   source .venv/bin/activate
#   ./run_all.sh
#
# Ctrl-C stops both processes.

set -e

# Activate venv if it exists and isn't already active
if [ -z "$VIRTUAL_ENV" ] && [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "──────────────────────────────────────────────────────────────"
echo "  Starting RedTeamAgent (backend + frontend)"
echo "──────────────────────────────────────────────────────────────"
echo "  Backend  → http://localhost:8000"
echo "  Frontend → http://localhost:8501"
echo "  Press Ctrl-C to stop both."
echo "──────────────────────────────────────────────────────────────"

# Ensure both processes die together on Ctrl-C
trap 'echo; echo "Shutting down..."; kill 0' SIGINT SIGTERM EXIT

# Backend (background)
uvicorn api:app --host 0.0.0.0 --port 8000 --log-level info &
BACKEND_PID=$!

# Give the backend a moment to bind
sleep 1.5

# Frontend (foreground)
python3 -m streamlit run redteam_ui.py --server.port 8501

# Wait on the backend if streamlit exits
wait $BACKEND_PID