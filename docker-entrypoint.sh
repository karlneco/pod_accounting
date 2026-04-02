#!/usr/bin/env bash
set -euo pipefail

export FLASK_APP="${FLASK_APP:-pod_accounting.py}"
export FLASK_RUN_HOST="${FLASK_RUN_HOST:-0.0.0.0}"
export FLASK_RUN_PORT="${FLASK_RUN_PORT:-5004}"

flask db upgrade

flask ai-expense-worker --poll-interval "${AI_EXPENSE_WORKER_POLL_INTERVAL:-10}" &
worker_pid=$!

flask run --host="${FLASK_RUN_HOST}" --port="${FLASK_RUN_PORT}" &
web_pid=$!

shutdown() {
  kill "$worker_pid" "$web_pid" 2>/dev/null || true
  wait "$worker_pid" "$web_pid" 2>/dev/null || true
}

trap shutdown INT TERM

wait -n "$worker_pid" "$web_pid"
status=$?
shutdown
exit "$status"
