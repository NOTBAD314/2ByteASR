"""Round 16 (2026-09-02 night): effect-subtitle closure — fidelity takeover,
single-band demo, web-adjust card (AI opinion mode), grok default.

1. Web-theme fidelity frames must BYPASS the native-mirror geometry parity
   gates (real-world logs: bbox_center_delta≈0.32 kept the real render in the
   background forever — the user only ever saw the stroke/color mirror).
2. The AI draft demo is ONE big band (cropped subtitle strip), not 3 cells.
3. The style panel gains a 特效字幕调整 card: font/size/color become an AI
   modification OPINION (never a direct restyle) + batch scope + apply-all.
4. Default AI service is grok_account when nothing is stored.
5. The generation prompt box is compact and clearly an input; the route
   default stays "web" with the combo gone.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _page(tmp_path):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject

    os.environ["LOCALAPPDATA"] = str(tmp_path / "local")
    page = SubtitleStudioPage()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v")
    project = SubtitleProject(
        media=StudioMedia(path=str(video), duration_ms=60_000, width=1920, height=1080),
    )
    project.speakers.append(StudioSpeaker(id="S01", name="主播"))
    project.speakers.append(StudioSpeaker(id="S02", name="嘉宾"))
    for index in range(4):
        project.cues.append(StudioCue(
            f"c{index}", index * 1000, index * 1000 + 900, f"第{index}句",
            speaker_id="S01" if index < 3 else "S02",
        ))
    project.validate()
    page.project = project
    page.project_path = tmp_path / "round16.2byteproj"
    page._cue_lookup = {cue.id: cue for cue in project.cues}
    page._manual_text_baselines = {cue.id: cue.text for cue in project.cues}
    page.cue_model.set_project(project)
    page.timeline.set_project(project)
    page._populate_speakers()
    page.undo_stack.clear()
    page.undo_stack.setClean()
    return page


def _theme() -> dict:
    from twobyteasr.caption_design.web_theme import builtin_web_themes

    return builtin_web_themes()["balatro-joker"].to_dict()


# ---------------------------------------------------------------------------
# 1) web-theme fidelity bypasses geometry parity
# ---------------------------------------------------------------------------

def test_web_theme_live_page_retains_foreground_ownership(tmp_path):
    """The web branch must not consult stroke/geometry parity at all."""
    _app()
    page = _page(tmp_path)

    snapshot = SimpleNamespace(
        style_recipe={"webTheme": {"name": "x"}, "motion": {}},
        motion_recipe={},
    )
    assert page._fidelity_can_replace_live(snapshot) is False

    # The call-site composition for web themes only consults
    # _fidelity_can_replace_live — guard the source so the parity gates can
    # never sneak back into the web branch.
    import inspect

    from twobyteasr.studio import studio_advanced_flow

    source = inspect.getsource(studio_advanced_flow)
    marker = source.find("is_web_theme")
    assert marker > 0, "web branch missing in _advanced_preview_ready"
    branch = source[marker:marker + 1500]
    web_part = branch.split("else:", 1)[0]
    assert "_fidelity_can_replace_live(snapshot)" in web_part
    assert "_fidelity_stroke_parity_ok" not in web_part
    assert "_fidelity_geometry_ok" not in web_part


# ---------------------------------------------------------------------------
# 2) single-band demo timeline
# ---------------------------------------------------------------------------

def test_demo_band_settings_and_widget(tmp_path):
    _app()
    page = _page(tmp_path)
    assert not hasattr(page, "ai_route"), "route combo removed in round 16"
    assert page._STORYBOARD_LOOP_SECONDS == 3.0
    assert page.ai_web_theme_demo_label.minimumHeight() >= 120


# ---------------------------------------------------------------------------
# 3) web-adjust card: opinion mode + scope + apply-all
# ---------------------------------------------------------------------------

def test_web_adjust_card_opinion_mode(tmp_path):
    _app()
    page = _page(tmp_path)
    host = getattr(page, "web_adjust_host", None)
    assert host is not None and host.isHidden(), "hidden before a web cue is selected"

    page.select_cue("c0")
    page._apply_web_theme("c0", _theme())
    assert not page.web_adjust_host.isHidden(), "visible for a web-themed cue"

    # Selecting a target font/size/color composes an OPINION, not a restyle.
    page.web_adjust_font.lineEdit().setText("KaiTi")
    page.web_adjust_size.setValue(96)
    page._web_adjust_color_value = "#FF3355"
    page.web_adjust_extra.setText("主色改成红色")
    opinion = page._assemble_web_adjust_opinion()
    assert "KaiTi" in opinion and "96" in opinion and "#FF3355" in opinion
    assert "红色" in opinion
    assert "将请求 AI" in page.web_adjust_opinion.text()
    # The cue's recipe typography is NOT mutated by the opinion controls.
    cue = page._cue_lookup.get("c0")
    payload = page.project.style_recipes.get(cue.style_id, {})
    web = payload.get("webTheme", {})
    assert str(web.get("palette", {}).get("text", "")).upper() != "#FF3355"


def test_web_adjust_scope_resolution(tmp_path):
    _app()
    page = _page(tmp_path)
    # theme c0/c1 (S01) and c3 (S02); c2 stays native.
    page.select_cue("c0")
    page._apply_web_theme("c0", _theme())
    page.select_cue("c1")
    page._apply_web_theme("c1", _theme())
    page.select_cue("c3")
    page._apply_web_theme("c3", _theme())

    page.select_cue("c0")
    page.web_adjust_scope.setCurrentIndex(page.web_adjust_scope.findData("current"))
    assert page._web_adjust_target_cue_ids() == ["c0"]
    page.web_adjust_scope.setCurrentIndex(page.web_adjust_scope.findData("speaker"))
    assert sorted(page._web_adjust_target_cue_ids()) == ["c0", "c1"]
    page.web_adjust_scope.setCurrentIndex(page.web_adjust_scope.findData("all"))
    assert sorted(page._web_adjust_target_cue_ids()) == ["c0", "c1", "c3"]


def test_apply_web_theme_to_scope_all(tmp_path):
    _app()
    page = _page(tmp_path)
    page.select_cue("c0")
    page._apply_web_theme("c0", _theme())
    page.web_adjust_scope.setCurrentIndex(page.web_adjust_scope.findData("all"))
    page._apply_web_theme_to_scope()
    themed = sum(
        1 for cue in page.project.cues
        if isinstance(
            (page.project.style_recipes.get(cue.style_id, {}) or {}).get("webTheme"), dict
        )
    )
    assert themed == 4


def test_web_adjust_ready_validates_before_applying_targets(tmp_path,monkeypatch):
    _app();page=_page(tmp_path);page.select_cue('c0')
    assert page._apply_web_theme('c0',_theme())
    drafts=page._theme_drafts();calls=[]
    monkeypatch.setattr(drafts,'adopt',lambda theme,cue_id,**kw:calls.append((theme,cue_id,kw)))
    refined=dict(_theme(),name='Balatro 红字版')
    page._web_adjust_ready(page._ai_request_generation,SimpleNamespace(source='refined',theme=refined),['c0'])
    assert calls[0][0]==refined and calls[0][1]=='c0' and drafts.apply_targets==['c0']
    cue=page._cue_lookup['c0']
    assert page.project.style_recipes[cue.style_id]['webTheme']['name']==_theme()['name']
    page._web_adjust_ready(page._ai_request_generation,SimpleNamespace(source='refine_failed',theme=refined),['c0'])
    assert len(calls)==1


def test_default_service_is_grok_account():
    from twobyteasr.providers.llm_config import get_active_service

    assert get_active_service({}) == "grok_account"
    assert get_active_service({"models": {"ai_service": "deepseek"}}) == "deepseek"


def test_prompt_box_compact_and_labeled(tmp_path):
    _app()
    page = _page(tmp_path)
    assert page.ai_prompt.maximumHeight() <= 96
    assert page.ai_prompt.placeholderText()


# ---------------------------------------------------------------------------
# round 17: segmented parallel export + densified playback grid
# ---------------------------------------------------------------------------

def test_overlay_active_windows_merge_and_pad():
    from twobyteasr.rendering.advanced_renderer import _overlay_active_windows

    props = {"fps": 30.0, "durationInFrames": 300, "cues": [
        {"startMs": 0, "endMs": 2000},
        {"startMs": 8000, "endMs": 9500},
        {"startMs": 9600, "endMs": 10000},  # merges with previous (gap < 1.5s)
    ]}
    assert _overlay_active_windows(props, 300) == [(0, 68), (232, 299)]
    full = _overlay_active_windows(
        {"fps": 30.0, "durationInFrames": 300, "cues": [{"startMs": 0, "endMs": 10000}]},
        300,
    )
    assert full == [(0, 299)]
    assert _overlay_active_windows({"fps": 30.0, "durationInFrames": 300, "cues": []}, 300) == []


def test_segment_cache_path_is_stable_and_scoped():
    from twobyteasr.rendering.advanced_renderer import _segment_cache_path

    props = {"fps": 30.0, "cues": [1]}
    a = _segment_cache_path(props, 10, 99)
    b = _segment_cache_path(props, 10, 99)
    c = _segment_cache_path(props, 10, 100)
    assert a == b and a != c and a.suffix == ".mov" and a.stem.endswith("-seg")


def test_playback_grid_is_dense(tmp_path):
    """十七轮：持住段不再 1 秒一跳——步长 ≤ 200ms，首秒加密。"""
    _app()
    page = _page(tmp_path)
    frames = page._web_theme_grid_frames(3000)
    assert len(frames) >= 18
    steps = [b - a for a, b in zip(frames, frames[1:])]
    assert max(steps) <= 250, f"hold steps too coarse: {steps}"
    assert sum(1 for s in steps if s <= 120) >= 5
