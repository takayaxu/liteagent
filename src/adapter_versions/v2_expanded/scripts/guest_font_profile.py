"""Apply an explicitly configured, temporary guest rendering environment."""
from __future__ import annotations

import hashlib
import json
import uuid
import xml.etree.ElementTree as ET
from typing import Any


class GuestFontProfile:
    def __init__(self, controller: Any, config: Any):
        self.controller = controller
        self.receipt: dict[str, Any] | None = None
        self.config = config
        self.filename = f"99-liteagent-{uuid.uuid4().hex}.conf"
        if config is None:
            self.xml = None
            return
        if not isinstance(config, dict) or set(config) != {"reject_families", "expected_matches"}:
            raise ValueError("fontconfig requires reject_families and expected_matches")
        families, expected = config["reject_families"], config["expected_matches"]
        if not isinstance(families, list) or not families or not all(
            isinstance(value, str) and value.strip() for value in families
        ):
            raise ValueError("reject_families must be a nonempty list of font families")
        if not isinstance(expected, dict) or not expected or not all(
            isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()
            for key, value in expected.items()
        ):
            raise ValueError("expected_matches must map family queries to expected families")
        root = ET.Element("fontconfig")
        reject = ET.SubElement(ET.SubElement(root, "selectfont"), "rejectfont")
        for family in families:
            pattern = ET.SubElement(reject, "pattern")
            field = ET.SubElement(pattern, "patelt", name="family")
            ET.SubElement(field, "string").text = family
        self.xml = ET.tostring(root, encoding="unicode") + "\n"

    def _execute(self, operation: str) -> dict[str, Any]:
        payload = json.dumps({
            "operation": operation, "filename": self.filename,
            "xml": self.xml, "expected_matches": self.config["expected_matches"],
        })
        code = '''
import hashlib,json,os,pathlib,subprocess
p=json.loads(PAYLOAD)
root=pathlib.Path(os.environ.get('XDG_CONFIG_HOME',str(pathlib.Path.home()/'.config')))
path=root/'fontconfig'/'conf.d'/p['filename']
content=p['xml'].encode()
def matches():
    result={}
    for family in p['expected_matches']:
        q=subprocess.run(['fc-match','--format','%{family}\\n',family],capture_output=True,text=True,timeout=15,check=True)
        result[family]=q.stdout.strip()
    return result
before=matches()
if path.exists() and path.read_bytes()!=content:
    raise RuntimeError('refuse to overwrite or remove a foreign font configuration')
if p['operation']=='apply':
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(content)
else:
    path.unlink(missing_ok=True)
after=matches()
if p['operation']=='apply':
    for family,expected in p['expected_matches'].items():
        if expected not in [s.strip() for s in after[family].split(',')]:
            path.unlink(missing_ok=True)
            raise RuntimeError('font profile match mismatch: '+repr(after))
print(json.dumps({'operation':p['operation'],'path':str(path),'sha256':hashlib.sha256(content).hexdigest(),'matches_before':before,'matches_after':after,'present':path.exists()}))
'''.replace("PAYLOAD", repr(payload))
        response = self.controller.execute_python_command(code)
        if not isinstance(response, dict) or response.get("returncode", 0) != 0:
            raise RuntimeError(f"guest font profile failed: {response}")
        try:
            receipt = json.loads(response.get("output", "").strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid guest font receipt: {response}") from exc
        expected_hash = hashlib.sha256(self.xml.encode()).hexdigest()
        if receipt.get("sha256") != expected_hash or receipt.get("operation") != operation:
            raise RuntimeError(f"guest font receipt mismatch: {receipt}")
        return receipt

    def apply(self) -> dict[str, Any] | None:
        if self.xml is None:
            return None
        receipt = self._execute("apply")
        if self.receipt is None:
            self.receipt = receipt
        return receipt

    def restore(self) -> dict[str, Any] | None:
        if self.xml is None or self.receipt is None:
            return None
        return self._execute("restore")
