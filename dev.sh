#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# dev.sh — Start the Flask dev server with environment variables set.
# -----------------------------------------------------------------------------

# Load .env if it exists (ignoring comments and blank lines)
if [ -f .env ]; then
  echo "Loading environment from .env"
  export $(grep -v '^\s*#' .env | xargs)
fi

# Required exports
export FLASK_APP=pod_accounting
export FLASK_ENV=development

# Optional—but recommended—overrides
export SECRET_KEY=${SECRET_KEY:-"dev-secret-key"}
export DATABASE_URL=${DATABASE_URL:-"sqlite:///$(pwd)/data/pod_accounting.db"}

echo "FLASK_APP=$FLASK_APP"
echo "FLASK_ENV=$FLASK_ENV"
echo "Using SECRET_KEY=${SECRET_KEY}"
echo "Using DATABASE_URL=${DATABASE_URL}"

# Launch!
exec python pod_accounting.py