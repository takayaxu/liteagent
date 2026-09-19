#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE="$ROOT/docker/shared-endpoints.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi
name=${OSWORLD_CONTAINER_NAME:-liteagent-shared-osworld}
if ! docker inspect "$name" >/dev/null 2>&1; then
  echo "container $name is not present" >&2
  exit 1
fi
docker inspect --format 'container={{.Name}} status={{.State.Status}} image={{.Config.Image}}' "$name"
status_png="/tmp/liteagent-guest-status-${USER:-user}.png"
curl --fail --silent --show-error --max-time 10 \
  "http://127.0.0.1:${OSWORLD_CONTROL_PORT:-5020}/screenshot" \
  -o "$status_png"
file "$status_png"
for pair in \
  "os:${OSWORLD_OS_PORT:-8909}" \
  "calc:${OSWORLD_CALC_PORT:-8905}" \
  "writer:${OSWORLD_WRITER_PORT:-8910}"; do
  label=${pair%%:*}; port=${pair##*:}
  health_json="/tmp/liteagent-health-${USER:-user}.json"
  code=$(curl --silent --output "$health_json" --write-out '%{http_code}' \
    --max-time 10 "http://127.0.0.1:${port}/health" || true)
  printf '%s health_http=%s ' "$label" "$code"
  head -c 180 "$health_json" 2>/dev/null || true
  printf '\n'
done
