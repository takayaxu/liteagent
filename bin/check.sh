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
export PROXY_CONFIG_FILE="$ROOT/src/third_party/OSWorld/evaluation_examples/settings/proxy/dataimpulse.json"
"$PYTHON" -m compileall -q "$ROOT/src/adapter_versions/v2_expanded/integrations/lite_agent" \
  "$ROOT/src/adapter_versions/v2_expanded/integrations/openapa_osworld" \
  "$ROOT/src/adapter_versions/v2_expanded/scripts"
"$PYTHON" - <<'PY'
from integrations.lite_agent.runtime import LiteAgent, LiteAgentConfig
from integrations.lite_agent.tool_catalog import public_actions
from integrations.openapa_osworld import provider
from desktop_env.desktop_env import DesktopEnv
from desktop_env.providers.docker.provider import DockerProvider
assert LiteAgent is not None and LiteAgentConfig is not None
assert callable(public_actions) and callable(provider.install_provider_patch)
assert DesktopEnv is not None and DockerProvider is not None
print('LiteAgent source/import check: OK')
PY
