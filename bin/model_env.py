#!/usr/bin/env python3
"""Load machine-local model defaults shared by the project entry points."""
import os
from pathlib import Path
import shlex
import sys


def load_model_environment():
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    path = Path(os.environ.get("LITEAGENT_MODEL_ENV", config_home / "liteagent/model.env")).expanduser()
    if not path.exists() and "LITEAGENT_MODEL_ENV" not in os.environ:
        return
    for number, line in enumerate(path.read_text().splitlines(), 1):
        fields = shlex.split(line, comments=True)
        if fields and fields[0] == "export":
            fields = fields[1:]
        if not fields:
            continue
        if len(fields) != 1 or "=" not in fields[0]:
            raise ValueError(f"{path}:{number}: expected KEY=value")
        key, value = fields[0].split("=", 1)
        if key not in {"QWEN_BASE_URL", "QWEN_MODEL", "QWEN_API_KEY"}:
            raise ValueError(f"{path}:{number}: unsupported model setting {key!r}")
        os.environ.setdefault(key, value)


if __name__ == "__main__":
    load_model_environment()
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
