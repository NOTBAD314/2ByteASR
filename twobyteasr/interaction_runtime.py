"""Low-overhead interaction latency and zero-spawn evidence for Studio."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .processes import child_process_start_count, process_action_scope


def _visible_qt_windows(app: QApplication | None) -> list[tuple[str, str, str]]:
    if app is None:
        return []
    return sorted(
        (type(widget).__name__, widget.objectName(), widget.windowTitle())
        for widget in app.topLevelWidgets()
        if widget.isVisible()
    )


class InteractionRuntimeAudit:
    """Collect measurements in memory; JSON output is deferred off the action path."""

    def __init__(self, owner=None):
        self.owner = owner
        self.records: list[dict[str, object]] = []
        self._depth = 0
        self._flush_pending = False
        self._components: dict[str, float] | None = None

    def add_component(self, name: str, elapsed_ms: float) -> None:
        """Attach a measured sub-phase to the active user interaction."""
        if self._components is None:
            return
        key = str(name)
        self._components[key] = self._components.get(key, 0.0) + max(0.0, float(elapsed_ms))

    @contextmanager
    def measure(self, action: str, *, allow_new_top_levels: bool = False):
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self._depth = 1
        self._components = {
            "model_update_ms": 0.0,
            "timeline_update_ms": 0.0,
            "mpv_ipc_ms": 0.0,
            "preview_request_ms": 0.0,
        }
        app = QApplication.instance()
        started = time.perf_counter()
        child_before = child_process_start_count()
        windows_before = _visible_qt_windows(app)
        try:
            with process_action_scope(action):
                yield
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            child_after = child_process_start_count()
            windows_after = _visible_qt_windows(app)
            components = {
                key: round(float(value), 3)
                for key, value in (self._components or {}).items()
            }
            new_top_levels = [item for item in windows_after if item not in windows_before]
            self.records.append({
                "action": str(action),
                "timestamp": round(time.time(), 3),
                "total_ms": elapsed_ms,
                "model_ui_ms": elapsed_ms,
                **components,
                "child_process_starts": child_after - child_before,
                "new_qt_top_levels": new_top_levels,
                "expected_qt_popup": bool(allow_new_top_levels),
                "target_ms": 50,
                "extreme_target_ms": 100,
                "passed": elapsed_ms < 100 and child_after == child_before and (
                    allow_new_top_levels or not new_top_levels
                ),
            })
            self._components = None
            self._depth = 0
            self._defer_flush()

    def _defer_flush(self) -> None:
        target = str(os.environ.get("TWOBYTEASR_INTERACTION_LATENCY_PATH") or "").strip()
        if not target or self._flush_pending:
            return
        self._flush_pending = True
        QTimer.singleShot(0, lambda value=target: self.flush(value))

    def flush(self, target: str | os.PathLike[str]) -> Path:
        self._flush_pending = False
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "2byteasr.interaction-latency.v1",
            "process_id": os.getpid(),
            "records": list(self.records),
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        return path


__all__ = ["InteractionRuntimeAudit"]
