"""Small persistent state for one-time contextual teaching hints."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
KNOWN_HINTS = {"studio", "razor", "priority_review"}


def teach_hints_path(base: str | os.PathLike[str] | None = None) -> Path:
    root = Path(base) if base is not None else Path(
        os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    ) / "2ByteASR" / "SubtitleStudioPreview"
    return root / "teach-hints.json"


class TeachHintStore:
    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path) if path is not None else teach_hints_path()

    def load(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            payload = {}
        seen = payload.get("seen", {}) if isinstance(payload, dict) else {}
        return {
            "schema_version": SCHEMA_VERSION,
            "seen": {str(key): str(value) for key, value in seen.items() if str(key)},
        }

    def _save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def should_show(self, key: str) -> bool:
        return str(key) in KNOWN_HINTS and str(key) not in self.load()["seen"]

    def mark_shown(self, key: str) -> bool:
        key = str(key)
        if key not in KNOWN_HINTS:
            return False
        payload = self.load()
        if key in payload["seen"]:
            return False
        payload["seen"][key] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._save(payload)
        return True

    def dismiss(self, key: str) -> None:
        if self.should_show(key):
            self.mark_shown(key)

    def reset(self) -> None:
        self._save({"schema_version": SCHEMA_VERSION, "seen": {}})
