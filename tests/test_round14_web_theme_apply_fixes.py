"""Round 14 (2026-09-02 evening): web-theme apply pipeline + timeline smoothness.

1. _schedule_advanced_preview crashed with UnboundLocalError for any cue whose
   recipe carries webTheme (grid quantization ran before relative_ms existed)
   — the crash was swallowed by the Qt slot boundary, LIVE never published,
   and with native suppressed the cue's subtitle vanished entirely.
2. 应用/保存样式 buttons were dead for the web route (no _pending_suggestion);
   now the applied theme is stashed and both buttons work.
3. reveal_playhead placed the playhead at 72% of the window with the jump
   threshold at 76% — 4% runway meant a jump storm at review speeds.
4. Playback follow-selection now hydrates the editor/inspector only on pause.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject

_pages=[]

@pytest.fixture(autouse=True)
def close_pages_after_test():
    yield
    while _pages:
        page=_pages.pop()
        page.close_page()
        page.deleteLater()
    app=QApplication.instance()
    if app:app.processEvents()


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _web_theme_project(tmp_path: Path) -> SubtitleProject:
    v1 = tmp_path / "v1.mp4"
    v1.write_bytes(b"v1")
    project = SubtitleProject(
        media=StudioMedia(path=str(v1), duration_ms=60_000, width=1920, height=1080),
        cues=[
            StudioCue("c1", 0, 4_000, "第一句"),
            StudioCue("c2", 4_000, 8_000, "第二句"),
        ],
    )
    project.validate()
    return project


def _web_theme_page(tmp_path: Path):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    os.environ["LOCALAPPDATA"] = str(tmp_path / "local")
    page = SubtitleStudioPage()
    _pages.append(page)
    project = _web_theme_project(tmp_path)
    page.project = project
    page.project_path = tmp_path / "round14.2byteproj"
    page._cue_lookup = {cue.id: cue for cue in project.cues}
    page._manual_text_baselines = {cue.id: cue.text for cue in project.cues}
    page.cue_model.set_project(project)
    page.timeline.set_project(project)
    page._populate_speakers()
    page.undo_stack.clear()
    page.undo_stack.setClean()
    return page


def _theme_payload() -> dict:
    from twobyteasr.caption_design.web_theme import builtin_web_themes

    return builtin_web_themes()["balatro-joker"].to_dict()


# ---------------------------------------------------------------------------
# 1) The UnboundLocalError that hid the cue's subtitle
# ---------------------------------------------------------------------------

def test_schedule_advanced_preview_survives_web_theme(tmp_path):
    _app()
    page = _web_theme_page(tmp_path)
    page.select_cue("c1")
    theme = _theme_payload()
    applied = page._apply_web_theme("c1", theme)
    assert applied, "web theme apply must succeed"

    cue = page._cue_lookup.get("c1")
    payload = page.project.style_recipes.get(cue.style_id, {})
    assert isinstance(payload.get("webTheme"), dict)

    # Before the fix this raised UnboundLocalError (relative_ms used before
    # assignment) and silently killed LIVE publication for the cue.
    page._schedule_advanced_preview(payload, queue_fidelity=False)
    # Playback snapshots are prepared off the GUI thread; the cold request
    # intentionally returns before a renderer identity can be published.
    from PySide6.QtTest import QTest
    import time
    deadline=time.monotonic()+3
    while page._advanced_preview_state.identity is None and time.monotonic()<deadline:
        QTest.qWait(10)
        page._schedule_advanced_preview(payload, queue_fidelity=False)
    assert page._advanced_preview_state.identity is not None


# ---------------------------------------------------------------------------
# 2) 应用/保存样式 work for the web route
# ---------------------------------------------------------------------------

def test_web_theme_buttons_apply_to_current_selection(tmp_path):
    _app()
    page = _web_theme_page(tmp_path)
    page.select_cue("c1")
    assert page._apply_web_theme("c1", _theme_payload())
    from tests.theme_fixture import bind_ready_draft
    bind_ready_draft(page,_theme_payload(),'c1')

    pending = getattr(page, "_pending_web_theme", None)
    assert pending is not None and pending.name

    page.select_cue("c2")
    page._apply_ai_preview()  # the「应用」button
    cue2 = page.session._cue_lookup.get("c2")
    payload2 = page.project.style_recipes.get(cue2.style_id, {})
    assert isinstance(payload2.get("webTheme"), dict), "apply button must re-apply to the selected cue"

    from twobyteasr.caption_style.studio_style_controller import StudioStyleController

    persisted: list[object] = []
    original_persist = StudioStyleController._persist_ai_design

    def _capture(self, suggestion):
        persisted.append(suggestion)

    StudioStyleController._persist_ai_design = _capture
    try:
        page._save_ai_design_presets()  # the「保存样式」button
    finally:
        StudioStyleController._persist_ai_design = original_persist
    assert persisted and persisted[0].recipe.to_dict() == pending.recipe.to_dict()


def test_storyboard_widgets_built_hidden(tmp_path):
    _app()
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    _pages.append(page)
    labels = getattr(page, "ai_web_theme_storyboard_labels", None) or []
    wrap = getattr(page, "ai_web_theme_storyboard_wrap", None)
    demo = getattr(page, "ai_web_theme_demo_label", None)
    # 十六轮起：单条大幅演示带（不再是三格）。labels 保留为兼容引用。
    assert wrap is not None and demo is not None and len(labels) == 1
    assert wrap.isHidden()


# ---------------------------------------------------------------------------
# 3) reveal runway
# ---------------------------------------------------------------------------

def test_reveal_playhead_runway(tmp_path):
    _app()
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    _pages.append(page)
    page.project = _web_theme_project(tmp_path)
    timeline = page.timeline
    timeline.set_project(page.project)
    timeline.visible_start_ms = 0
    timeline.visible_duration_ms = 10_000

    assert timeline.reveal_playhead(7_600) is False, "76% must not jump anymore"
    assert timeline.reveal_playhead(9_000) is True
    position_ratio = (9_000 - timeline.visible_start_ms) / timeline.visible_duration_ms
    assert 0.2 <= position_ratio <= 0.45, (
        f"playhead must land near 30%, got {position_ratio:.2f} (55%+ runway)"
    )


# ---------------------------------------------------------------------------
# 4) Lightweight playback follow-selection
# ---------------------------------------------------------------------------

def test_playback_follow_selection_lightweight_then_hydrates(tmp_path):
    _app()
    page = _web_theme_page(tmp_path)
    page.select_cue("c1")
    assert page.cue_text.toPlainText() == "第一句"

    page.video._paused = False  # playing
    page.select_cue("c2", hydrate=False)
    assert page.selected_cue_id == "c2"
    assert page.cue_text.toPlainText() == "第一句", "editor must stay untouched in lightweight mode"

    page.video._paused = True
    page._playback_state_changed(True)
    assert page.cue_text.toPlainText() == "第二句", "pause re-hydrates the editor"
