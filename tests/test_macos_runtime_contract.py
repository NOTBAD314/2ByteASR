"""The macOS CPU runtime installs every package the shared main-runtime contract checks (2026-10-13)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pins(*names):
    pins = {}
    for name in names:
        for line in (ROOT / "packaging/macos" / name).read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([A-Za-z0-9_.\-]+)==(\S+)", line.strip())
            if match:
                pins[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = match.group(2)
    return pins


def test_mac_requirements_pin_every_main_runtime_contract_package():
    contract = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))["environments"]["main"]
    pins = _pins("requirements-cpu.txt", "requirements-gui.txt")
    wanted = {re.sub(r"[-_.]+", "-", name).lower(): str(version) for name, version in contract["packages"].items()}
    assert {name: pins.get(name) for name in wanted} == wanted
    assert pins.get("torch") == contract["torch"] and pins.get("torchaudio") == contract["torchaudio"]
