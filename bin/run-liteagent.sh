#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x /var/lib/liteagent-shared/python-env/bin/python ]]; then
    PYTHON=/var/lib/liteagent-shared/python-env/bin/python
  else
    PYTHON=python3
  fi
fi
cd "$ROOT"
export PYTHONPATH="$ROOT/src/adapter_versions/v2_expanded:$ROOT/src/third_party/OSWorld:$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PROXY_CONFIG_FILE="${PROXY_CONFIG_FILE:-$ROOT/src/third_party/OSWorld/evaluation_examples/settings/proxy/dataimpulse.json}"

args=("$@")
has_qcow2=false
for arg in "${args[@]}"; do
  case "$arg" in
    --qcow2 | --qcow2=*) has_qcow2=true ;;
  esac
done
if [[ "$has_qcow2" == false ]]; then
  args+=(
    --qcow2
    "${OSWORLD_QCOW2:-$ROOT/src/third_party/OSWorld/docker_vm_data/Ubuntu.qcow2}"
  )
fi

exec "$PYTHON" "$ROOT/bin/model_env.py" \
  "$ROOT/src/adapter_versions/v2_expanded/scripts/run_lite_agent_pilot.py" "${args[@]}"
