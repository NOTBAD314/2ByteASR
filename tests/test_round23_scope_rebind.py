"""第二十三轮：效果范围双模式 + live provider 跨 cue 动态换绑 + motion 联动条款。"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

pytestqt = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.caption_design.web_theme import builtin_web_themes


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication([])


def _web_recipe_payload() -> dict:
    from twobyteasr.caption_style.style_recipe import StyleRecipe

    recipe = StyleRecipe(
        name="R23",
        engine="remotion",
        typography={"fontFamily": "YaHei", "fontSize": 58, "bold": True},
        colors={"fill": "#FFFFFF", "outline": "#000000"},
        web_theme=builtin_web_themes()["doom95"].to_dict(),
    )
    return recipe.to_dict()


def _project_two_web_cues() -> SubtitleProject:
    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    style_id = project.styles[0].id
    project.style_recipes[style_id] = _web_recipe_payload()
    project.cues.append(StudioCue(id="a", start_ms=10_000, end_ms=12_000, text="甲句"))
    project.cues.append(StudioCue(id="b", start_ms=12_000, end_ms=14_000, text="乙句"))
    project.cues.append(StudioCue(id="plain", start_ms=14_000, end_ms=16_000, text="普通"))
    for cue in project.cues:
        cue.style_id = style_id
    # 普通条不带 web 主题：单独样式。
    plain_style = "plain-style"
    project.style_recipes[plain_style] = {}
    project.cues[2].style_id = plain_style
    return project


class _Playback:
    def __init__(self, ms: float, paused: bool) -> None:
        self.presentation_media_ms = ms
        self.paused = paused


def test_provider_rebinds_across_web_cues():
    """跨 web cue：provider 换绑不自毁；到非 web cue/出界才退出。"""
    from twobyteasr.studio import studio_advanced_flow

    project = _project_two_web_cues()
    lookup = {cue.id: cue for cue in project.cues}
    state = {"position": 11_000.0, "paused": True, "at_head": lookup["a"]}

    class _Harness(studio_advanced_flow.StudioAdvancedFlowMixin):
        def __init__(self) -> None:
            self.project = project
            self._cue_lookup = lookup
            self._web_live_cue_id = "a"
            self._playback_mode = "source"
            self.video = SimpleNamespace(
                playback_position_snapshot=lambda: _Playback(state["position"], state["paused"]),
            )

        def _renderer_cue_at_playhead(self):
            return state["at_head"]

    harness = _Harness()
    provider = harness._web_live_time_provider()

    # cue a 内：正常返回。
    value = provider()
    assert value is not None and abs(value[0] - 1000.0) < 1e-6 and value[2] is False

    # 越过 a 出界、播头在 b：换绑到 b（cue_ms 按 b 起点）且不自毁。
    state["position"] = 12_500.0
    state["at_head"] = lookup["b"]
    value = provider()
    assert value is not None and abs(value[0] - 500.0) < 1e-6
    assert harness._web_live_cue_id == "b"

    # 播头在非 web cue：退出（None）。
    state["position"] = 15_000.0
    state["at_head"] = lookup["plain"]
    assert provider() is None


def test_contract_has_motion_linkage_and_scope_words():
    from twobyteasr.caption_design.studio_ai import _WEB_THEME_CONTRACT_SYSTEM

    assert "入场/出场必须与装置物理联动" in _WEB_THEME_CONTRACT_SYSTEM
    assert "禁止" in _WEB_THEME_CONTRACT_SYSTEM and "底板上移弹入" in _WEB_THEME_CONTRACT_SYSTEM
    assert "拉杆下压" in _WEB_THEME_CONTRACT_SYSTEM


def test_effect_scope_combo_exists(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    try:
        combo = getattr(page, "ai_effect_scope", None)
        assert combo is not None
        datas = [combo.itemData(i) for i in range(combo.count())]
        assert "subtitle" in datas and "fullscreen" in datas
        assert combo.currentData() == "subtitle"  # 默认：特效字幕
    finally:
        page.close()
        page.deleteLater()
