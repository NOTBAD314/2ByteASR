"""Render the 2ByteASR settings page in zh / en / ja for design review.

Usage: .venv-main\\Scripts\\python.exe scripts\\screenshot_ui.py
Output: dist\\ui-shots\\{zh,en,ja}.png (offscreen, no window flashes).
The ui.language setting is backed up and restored afterwards.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "2byteasr_settings.json"
OUT_DIR = ROOT / "dist" / "ui-shots"
PYTHON = ROOT / ".venv-main" / "Scripts" / "python.exe"
UI_ENTRY = ROOT / "twobyteasr" / "ui.py"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(SETTINGS.read_text(encoding="utf-8"))
    backup = json.loads(SETTINGS.read_text(encoding="utf-8"))
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    for language in ("zh", "en", "ja"):
        payload.setdefault("ui", {})["language"] = language
        SETTINGS.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        target = OUT_DIR / f"{language}.png"
        subprocess.run(
            [str(PYTHON), "-m", "twobyteasr.ui", "--screenshot", str(target), "settings"],
            cwd=str(ROOT), env=env, check=False,
        )
        print(f"rendered {target.name}")
    SETTINGS.write_text(
        json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    print("settings restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
