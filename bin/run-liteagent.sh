#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=${PYTHON:-python3}
cd "$ROOT"
export PYTHONPATH="$ROOT/src/adapter_versions/v2_expanded:$ROOT/src/third_party/OSWorld:$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PROXY_CONFIG_FILE="${PROXY_CONFIG_FILE:-$ROOT/src/third_party/OSWorld/evaluation_examples/settings/proxy/dataimpulse.json}"
exec "$PYTHON" "$ROOT/src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py" "$@"
