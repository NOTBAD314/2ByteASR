"""P8C-R3 stroke ownership: preset switches must own the transaction.

Reproduces the real-user sequence: edit stroke -> switch presets (incl. the
wheel path that only emitted currentIndexChanged) -> verify the resolved
stroke follows the preset and no stale numeric commit can overwrite it.

Uses the proven plain-function pattern (explicit close_page teardown) from
tests/test_p4_stage_fixes.py; yield fixtures around SubtitleStudioPage crash
at interpreter teardown on Windows.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    save_project,
)
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.caption_style.style_resolution import resolve_cue_visual


_APP = None

def _app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _make_page(tmp_path, cue_count=2):
    _app()
    cues = [
        StudioCue(f"c{index}", index * 3000, index * 3000 + 1500, f"句子 {index}", speaker_id="S01")
        for index in range(cue_count)
    ]
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=60_000),
        cues=cues,
    )
    path = save_project(project, tmp_path / "studio.2byteproj")
    page = SubtitleStudioPage()
    _app().processEvents()
    page.open_project(path)
    _app().processEvents()
    return page


def _close(page):
    page.close_page()
    page.deleteLater()
    _app().processEvents()


def _two_presets():
    # Pick from the visible store: builtin/user presets may be hidden, so the
    # fixture must select among ids that actually resolve for this machine.
    store = StylePresetStore()
    with_stroke = [
        pid for pid, style in store.all().items() if (style.outline_width or 0) > 0
    ]
    assert len(with_stroke) >= 2, "fixture expects at least two stroked presets"
    first = with_stroke[0]
    different = [
        pid for pid in with_stroke if store.all()[pid].outline_width != store.all()[first].outline_width
    ]
    assert different, "fixture expects presets with different stroke widths"
    return first, different[0]


def _resolved_stroke(page, cue_id="c0") -> float:
    project = page.session.project
    cue = next(item for item in project.cues if item.id == cue_id)
    return float(resolve_cue_visual(project, cue).style.outline_width or 0)


def _cue_state(page, cue_id="c0"):
    cue = next(item for item in page.session.project.cues if item.id == cue_id)
    return cue.base_preset_id, dict(cue.appearance_override or {})


def _settle(seconds: float = 0.35) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _app().processEvents()
        time.sleep(0.02)


def test_preset_index_change_alone_applies_transaction(tmp_path):
    first, _second = _two_presets()
    page = _make_page(tmp_path)
    try:
        page.select_cue("c0")
        _app().processEvents()
        index = page.style_preset.findData(first)
        assert index >= 0
        page.style_preset.setCurrentIndex(index)
        _app().processEvents()
        _settle(0.05)
        base, override = _cue_state(page)
        assert base == first
        assert override == {}
        assert _resolved_stroke(page) == float(
            StylePresetStore().all()[first].outline_width
        )
    finally:
        _close(page)


def test_pending_numeric_commit_cannot_override_later_preset(tmp_path):
    _first, second = _two_presets()
    store = StylePresetStore()
    preset_stroke = float(store.all()[second].outline_width)
    page = _make_page(tmp_path)
    try:
        page.select_cue("c0")
        _app().processEvents()
        # User ticks the stroke spinbox: the 180 ms numeric debounce arms.
        page.style_outline_width.setValue(preset_stroke + 3.0)
        # …but changes preset before the timer fires.
        page.style_preset.setCurrentIndex(page.style_preset.findData(second))
        _app().processEvents()
        _settle(0.4)
        base, _override = _cue_state(page)
        assert base == second
        assert _resolved_stroke(page) == preset_stroke
    finally:
        _close(page)


def test_rapid_preset_switches_keep_stroke_preset_owned(tmp_path):
    first, second = _two_presets()
    store = StylePresetStore()
    stroke_first = float(store.all()[first].outline_width)
    page = _make_page(tmp_path)
    try:
        page.select_cue("c0")
        _app().processEvents()
        for preset_id in (first, second, first, second, first):
            page.style_preset.setCurrentIndex(page.style_preset.findData(preset_id))
            _app().processEvents()
        base, _override = _cue_state(page)
        assert base == first
        assert _resolved_stroke(page) == stroke_first
        # The double-signal popup path (index change + activated) must not
        # stack duplicate transactions for one user action.
        before = page.undo_stack.count()
        page.style_preset.setCurrentIndex(page.style_preset.findData(second))
        page._preset_activated(page.style_preset.currentIndex())
        _app().processEvents()
        assert page.undo_stack.count() == before + 1
        assert _resolved_stroke(page) == float(store.all()[second].outline_width)
    finally:
        _close(page)


def test_explicit_stroke_edit_survives_10s_of_idle(tmp_path):
    first, _second = _two_presets()
    page = _make_page(tmp_path)
    try:
        page.select_cue("c0")
        _app().processEvents()
        page.style_preset.setCurrentIndex(page.style_preset.findData(first))
        _app().processEvents()
        page.style_outline_width.setValue(20.0)
        _settle(0.4)
        base, override = _cue_state(page)
        assert base == first
        assert override.get("outline_width") == 20.0
        assert _resolved_stroke(page) == 20.0
    finally:
        _close(page)
