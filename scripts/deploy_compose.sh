#!/usr/bin/env bash
set -euo pipefail

NO_CACHE="${1:-false}"
APP_DATA_DIR="${APP_DATA_DIR:-/srv/apps_data/pod_accounting}"
COMPOSE_FILE="docker-compose.deploy.yml"
PROJECT_NAME="pod_accounting"
SERVICE_NAME="pod-accounting"
ROLLBACK_TAG="podaccounting:rollback"
TARGET_IMAGE="podaccounting:local"
HEALTH_URL="http://127.0.0.1:5004/healthz"

export APP_DATA_DIR

if [[ ! -f ".env" ]]; then
  echo "Missing env file in workspace: .env" >&2
  exit 1
fi

docker run --rm -v "${APP_DATA_DIR}:/data" alpine sh -lc 'mkdir -p /data /data/expense_invoices'

# Clean up legacy container name from older compose service config.
docker rm -f pod_accounting-web-1 >/dev/null 2>&1 || true

# Fail early if the host port is owned by another container/process.
CURRENT_SERVICE_CID="$(docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" ps -q "${SERVICE_NAME}" || true)"
mapfile -t PORT_5004_CIDS < <(docker ps --filter "publish=5004" --format '{{.ID}}')
if (( ${#PORT_5004_CIDS[@]} > 0 )); then
  for CID in "${PORT_5004_CIDS[@]}"; do
    if [[ -n "${CURRENT_SERVICE_CID}" && "${CID}" == "${CURRENT_SERVICE_CID}" ]]; then
      continue
    fi
    echo "Port 5004 is already allocated by another running container:" >&2
    docker ps --filter "id=${CID}" --format '  - {{.Names}} ({{.Image}} | {{.Ports}})' >&2
    echo "Stop/remove that container (or change this app port) and re-run deploy." >&2
    exit 1
  done
fi

HAS_ROLLBACK_IMAGE=false
CURRENT_CONTAINER_ID="$(docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" ps -q "${SERVICE_NAME}" || true)"
if [[ -n "${CURRENT_CONTAINER_ID}" ]]; then
  CURRENT_IMAGE_ID="$(docker inspect -f '{{.Image}}' "${CURRENT_CONTAINER_ID}")"
  if [[ -n "${CURRENT_IMAGE_ID}" ]]; then
    docker image tag "${CURRENT_IMAGE_ID}" "${ROLLBACK_TAG}"
    HAS_ROLLBACK_IMAGE=true
    echo "Captured rollback image (${CURRENT_IMAGE_ID})."
  fi
fi

if [[ "${NO_CACHE}" == "true" ]]; then
  docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" build --pull --no-cache
else
  docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" build --pull
fi

docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" up -d --remove-orphans

for attempt in $(seq 1 30); do
  if curl -fsS "${HEALTH_URL}" >/dev/null; then
    echo "Deploy healthy."
    exit 0
  fi
  sleep 2
done

echo "Health check failed after deploy. Showing logs:" >&2
docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" logs --tail=150 "${SERVICE_NAME}" >&2

if [[ "${HAS_ROLLBACK_IMAGE}" == "true" ]]; then
  echo "Attempting rollback to previous image..." >&2
  docker image tag "${ROLLBACK_TAG}" "${TARGET_IMAGE}"
  docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" up -d --no-build --remove-orphans "${SERVICE_NAME}"
  for attempt in $(seq 1 30); do
    if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
      echo "Rollback completed and service is healthy." >&2
      exit 1
    fi
    sleep 2
  done
  echo "Rollback attempted but health check is still failing." >&2
else
  echo "No previous running container found. Rollback unavailable." >&2
fi

exit 1
