#!/usr/bin/env bash
set -euo pipefail

payload_dir="${1:-/tmp/osworld-os-adapter-payload}"
install_dir="${HOME}/.local/share/osworld-os-adapter"
unit_dir="${HOME}/.config/systemd/user"
pymupdf_wheel="${payload_dir}/os_adapter/vendor/pymupdf-1.28.0-cp310-abi3-manylinux_2_28_x86_64.whl"

test -f "${payload_dir}/os_adapter/service.py"
test -f "${payload_dir}/os_adapter/actions.py"
test -f "${payload_dir}/os_adapter/vendor/pypdf-6.14.2-py3-none-any.whl"
test -f "${payload_dir}/os_adapter/vendor/typing_extensions-4.15.0-py3-none-any.whl"
test -f "${pymupdf_wheel}"
test -f "${payload_dir}/os_adapter/deploy/osworld-os-adapter.service"
for command in gio gsettings pactl timedatectl gnome-terminal gnome-screenshot wmctrl snap sudo useradd usermod openssl pdftocairo; do
  command -v "${command}"
done
/usr/bin/python3 -c 'import flask'

if ! command -v tesseract >/dev/null || ! tesseract --list-langs 2>/dev/null | grep -qx eng; then
  PYTHONPATH="${payload_dir}" /usr/bin/python3 - <<'PY'
import time

from os_adapter.command import CommandRunner
from os_adapter.errors import AdapterError

runner = CommandRunner()
for arguments, timeout in (
    (["apt-get", "update"], 45),
    (["apt-get", "install", "-y", "--no-install-recommends", "tesseract-ocr", "tesseract-ocr-eng"], 60),
):
    # Waiting for index locks must not consume the package installation's time.
    install_deadline = time.monotonic() + 90
    while True:
        remaining = install_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("OCR package stage exceeded its 90-second setup budget")
        try:
            result = runner.sudo(
                ["env", "DEBIAN_FRONTEND=noninteractive", *arguments],
                timeout=min(timeout, remaining),
            )
            break
        except AdapterError as error:
            print(error.details, flush=True)
            details = error.details if isinstance(error.details, dict) else {}
            remaining = install_deadline - time.monotonic()
            if (
                details.get("returncode") != 100
                or "could not get lock" not in str(details.get("stderr", "")).casefold()
                or remaining <= 0
            ):
                raise
            # PackageKit may still be updating the fresh guest. Leave its locks intact.
            time.sleep(min(3, remaining))
            if time.monotonic() >= install_deadline:
                raise
    print(result["stdout"], end="")
    print(result["stderr"], end="")
PY
fi

mkdir -p "${install_dir}" "${unit_dir}"
rm -rf "${install_dir}/os_adapter"
rm -rf "${install_dir}/pypdf" "${install_dir}"/pypdf-*.dist-info
rm -rf "${install_dir}/typing_extensions.py" "${install_dir}"/typing_extensions-*.dist-info
cp -a "${payload_dir}/os_adapter" "${install_dir}/os_adapter"
/usr/bin/python3 -m pip install \
  --disable-pip-version-check \
  --no-index \
  --no-deps \
  --upgrade \
  --target "${install_dir}" \
  "${payload_dir}/os_adapter/vendor/pypdf-6.14.2-py3-none-any.whl" \
  "${payload_dir}/os_adapter/vendor/typing_extensions-4.15.0-py3-none-any.whl" \
  "${pymupdf_wheel}"
install -m 0644 \
  "${payload_dir}/os_adapter/deploy/osworld-os-adapter.service" \
  "${unit_dir}/osworld-os-adapter.service"

systemctl --user daemon-reload
systemctl --user enable osworld-os-adapter.service
systemctl --user restart osworld-os-adapter.service
