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

    def _state(self) -> dict:
        # Read once per store; this store's own writes keep it current.
        state = getattr(self, "_cached", None)
        if state is None:
            state = self._cached = self.load()
        return state

    def prefetch(self) -> None:
        """Read the file on a worker now, before the first should_show()."""
        _WRITER.submit(self._state)

    def should_show(self, key: str) -> bool:
        return str(key) in KNOWN_HINTS and str(key) not in self._state()["seen"]

    def mark_shown(self, key: str, *, background: bool = False) -> bool:
        """``background``: write on the ordered worker (the GUI thread must
        not wait for a file write and fsync; 2026-11-19)."""
        key = str(key)
        if key not in KNOWN_HINTS:
            return False
        payload = self._state()
        if key in payload["seen"]:
            return False
        payload["seen"][key] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        snapshot = {"schema_version": SCHEMA_VERSION, "seen": dict(payload["seen"])}
        if background:
            _WRITER.submit(self._save, snapshot)
        else:
            self._save(snapshot)
        return True

    def dismiss(self, key: str) -> None:
        if self.should_show(key):
            self.mark_shown(key)

    def reset(self) -> None:
        _WRITER.submit(lambda: None).result()  # earlier background writes land first
        self._cached = {"schema_version": SCHEMA_VERSION, "seen": {}}
        self._save({"schema_version": SCHEMA_VERSION, "seen": {}})


from concurrent.futures import ThreadPoolExecutor

#: One ordered writer for hint files, so a later reset is never overtaken.
_WRITER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="teach-hint-writer")
