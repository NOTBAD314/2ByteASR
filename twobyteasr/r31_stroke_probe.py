"""P8C-R3.1 in-app stroke probe (env-gated audit machinery).

TWOBYTEASR_R31_STROKE_PROBE=1 runs a 100 ms × 10 s foreground-stroke sampler
inside the REAL application (source or packaged) on the currently open studio
project — the C2 evidence channel that cannot be faked by a fixture:

    TWOBYTEASR_R31_PROBE_OUTPUT   destination JSON (default tmp/r31-stroke-probe.json)
    TWOBYTEASR_R31_PROBE_QUIT=1   close the app after sampling completes

Records foreground owner, canonical/snapshot strokes, appearance generation
and actual foreground stroke-pixel counts (C5: pixels, not serialized values).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QTimer


class R31StrokeProbe:
    SAMPLE_MS = 100
    DURATION_MS = 10_000

    def __init__(self, page, output_path: str):
        self.page = page
        self.output_path = str(Path(output_path).resolve())
        self.rows: list[dict] = []
        self.timer = QTimer(page)
        self.timer.setInterval(self.SAMPLE_MS)
        self.timer.timeout.connect(self._sample)
        self._started_at = 0.0
        self._stroke_colors: list[str] = []

    def start(self) -> None:
        page = self.page
        session = getattr(page, "session", None)
        if session is None or not session.project or not session.project.cues:
            self._finish({"error": "no project/cue"})
            return
        cue = session.project.cues[0]
        page.select_cue(cue.id)
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        app.processEvents()
        # Apply with retries: the panel/selection may still be settling when
        # the audit hook fires inside the real application startup.
        self._apply_attempts = 0
        self._cue_id = cue.id
        self._apply_timer = QTimer(page)
        self._apply_timer.setInterval(700)
        self._apply_timer.timeout.connect(self._try_apply)
        self._try_apply()

    def _try_apply(self) -> None:
        page = self.page
        self._apply_attempts += 1
        try:
            page.style_outline_width.setValue(20.0)
            page._apply_style()
        except Exception as exc:  # noqa: BLE001 - audit must not crash the app
            self._apply_timer.stop()
            self._finish({"error": f"apply failed: {exc}"})
            return
        from .style_resolution import resolve_cue_visual

        canonical = 0.0
        try:
            cue = next(
                item
                for item in page.session.project.cues
                if item.id == page.session.selected_cue_id
            )
            canonical = float(resolve_cue_visual(page.session.project, cue).style.outline_width or 0)
        except StopIteration:
            canonical = -1
        if abs(canonical - 20.0) <= 0.01 or self._apply_attempts >= 8:
            self._apply_timer.stop()
            if abs(canonical - 20.0) > 0.01:
                self._finish({"error": f"apply never landed (canonical={canonical})"})
                return
            self._stroke_colors = self._current_stroke_colors()
            self._started_at = time.monotonic()
            self.timer.start()

    def _current_stroke_colors(self):
        from .style_resolution import resolve_cue_visual

        try:
            cue = self.page.session.project.cues[0]
            style = resolve_cue_visual(self.page.session.project, cue).style
            return [str(style.outline_color)]
        except Exception:
            return []

    def _sample(self) -> None:
        page = self.page
        elapsed_ms = round((time.monotonic() - self._started_at) * 1000)
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        app.processEvents()
        snapshot = getattr(page, "_advanced_preview_snapshot", None)
        from .studio_ui import _count_stroke_pixels
        from .style_resolution import resolve_cue_visual

        canonical = None
        try:
            cue = next(
                item
                for item in page.session.project.cues
                if item.id == getattr(self, "_cue_id", page.session.selected_cue_id)
            )
            canonical = float(resolve_cue_visual(page.session.project, cue).style.outline_width or 0)
        except (StopIteration, Exception):
            canonical = None
        foreground = getattr(page, "_advanced_cue_pixmap", None)
        colors = self._stroke_colors or [
            str(item.get("color"))
            for item in (getattr(snapshot, "strokes", ()) or [])
            if isinstance(item, dict) and item.get("color")
        ]
        try:
            pixels = _count_stroke_pixels(foreground, colors) if colors else -1
        except Exception:
            pixels = -1
        self.rows.append({
            "t_ms": elapsed_ms,
            "foreground_owner": getattr(page, "_advanced_canvas_source_kind", ""),
            "canonical_stroke": canonical,
            "appearance_generation": getattr(snapshot, "appearance_generation", None) if snapshot else None,
            "snapshot_strokes": [
                dict(item) for item in (getattr(snapshot, "strokes", ()) or [])
            ] if snapshot else [],
            "foreground_stroke_pixels": pixels,
        })
        if elapsed_ms >= self.DURATION_MS:
            self.timer.stop()
            self._finish()

    def _finish(self, payload: dict | None = None) -> None:
        result = dict(payload or {})
        baseline = max(
            (row["foreground_stroke_pixels"] for row in self.rows[:20] if row["foreground_stroke_pixels"] >= 0),
            default=0,
        )
        threshold = max(12, baseline * 0.2) if baseline > 0 else None
        collapse = None
        if threshold is not None:
            for row in self.rows:
                if (
                    row["t_ms"] > 800
                    and row["foreground_stroke_pixels"] >= 0
                    and row["foreground_stroke_pixels"] < threshold
                ):
                    collapse = row
                    break
        result.update({
            "stroke_colors": self._stroke_colors,
            "baseline_stroke_pixels": baseline,
            "collapse_threshold": threshold,
            "first_pixel_collapse": collapse,
            "owners_seen": sorted({row["foreground_owner"] for row in self.rows}),
            "final_row": self.rows[-1] if self.rows else None,
            "samples": self.rows,
        })
        try:
            destination = Path(self.output_path).resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("w", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=1)
        except OSError:
            pass
        if os.environ.get("TWOBYTEASR_R31_PROBE_QUIT", "") == "1":
            window = self.page.window()
            QTimer.singleShot(400, window.close)
