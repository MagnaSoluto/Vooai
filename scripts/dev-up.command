#!/bin/bash
# Sobe API + Vite no Terminal.app (fora do Cursor).
# Duplo-clique neste arquivo ou: open scripts/dev-up.command
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

osascript <<EOF
tell application "Terminal"
  activate
  do script "cd '$ROOT/apps/api' && set -a && source .env && set +a && echo '=== VooAI API :8000 ===' && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
  delay 0.8
  do script "cd '$ROOT/apps/web' && echo '=== VooAI Web :5173 ===' && npm run dev -- --host 127.0.0.1 --port 5173"
end tell
EOF
