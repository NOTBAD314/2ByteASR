"""第十八轮：theme-first 外观（黑字根因回归锁）+ AI 字幕工坊。"""

from __future__ import annotations

import copy

import pytest

pytestqt = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from twobyteasr.rendering.advanced_renderer import normalized_visual_snapshot
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.caption_style.style_recipe import StyleRecipe
from twobyteasr.caption_design.web_theme import (
    builtin_web_themes,
    parse_web_theme_sections,
    theme_archive_html,
)


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication([])


class _FakeSnapshot:
    """最小快照：黑填充/黑描边/雅黑——复现用户工程外观。"""

    def __init__(self, recipe_payload: dict) -> None:
        self.style_recipe = recipe_payload
        self.font_family = "Microsoft YaHei UI"
        self.font_size = 58
        self.font_weight = 700
        self.italic = False
        self.fill = {"type": "solid", "color": "#FF000000"}
        self.strokes = [{"color": "#FF000000", "width": 3.0}]
        self.shadow = {}
        self.glow = {}
        self.letter_spacing = 0.0
        self.alignment = 2
        self.position_x = 0
        self.position_y = 0
        self.anchor_x = 0
        self.anchor_y = 0
        self.scale_x = 1
        self.scale_y = 1
        self.rotation = 0
        self.playres_x = 1920
        self.playres_y = 1080
        self.motion_recipe = {}
        self.start_ms = 0
        self.end_ms = 2000


def _doom_recipe() -> StyleRecipe:
    return StyleRecipe(
        name="DOOM95 Web",
        engine="remotion",
        typography={"fontFamily": "Microsoft YaHei UI", "fontSize": 58, "bold": True},
        colors={"fill": "#C9D1D9", "outline": "#10181E"},
        web_theme=builtin_web_themes()["doom95"].to_dict(),
    )


def test_snapshot_binds_theme_appearance_first():
    """黑字根因回归锁：工程黑外观不得压过主题自带设计。"""
    snapshot = _FakeSnapshot(_doom_recipe().to_dict())
    bound = normalized_visual_snapshot(snapshot)
    appearance = bound["webTheme"]["appearance"]
    assert "俐方体11号" in appearance["fontFamily"]
    assert "Cubic 11" in appearance["fontFamily"]
    assert appearance["color"] == "#C9D1D9"  # 枪灰，不是工程黑
    assert appearance["strokeColor"] == "#10181E"
    assert appearance["fontSize"] == 54
    assert appearance["strokeWidth"] == 3.4


def test_snapshot_legacy_theme_keeps_project_appearance():
    """旧主题（无 appearance）：工程外观继续生效——向后兼容语义。"""
    payload = _doom_recipe().to_dict()
    payload["webTheme"] = dict(payload["webTheme"])
    payload["webTheme"].pop("appearance", None)
    snapshot = _FakeSnapshot(payload)
    bound = normalized_visual_snapshot(snapshot)
    appearance = bound["webTheme"]["appearance"]
    assert appearance["fontFamily"] == "Microsoft YaHei UI"
    assert appearance["color"].startswith("#000000")  # ARGB 快照经 _css_color 归一
    assert appearance["fontSize"] == 58


def test_parse_sections_appearance_block():
    text = (
        "===NAME===\nX\n"
        "===PALETTE===\nprimary=#C22B1E text=#C9D1D9\n"
        "===APPEARANCE===\n"
        'fontFamily="Cubic 11", "俐方体11号", monospace\n'
        "fontSize=48\ncolor=#ABCDEF\nstrokeColor=#101010\nstrokeWidth=3\n"
        "bold=false\nletterSpacing=2\n"
        "===NOTES===\nn"
    )
    payload = parse_web_theme_sections(text)
    own = payload["appearance"]
    assert own["fontFamily"] == '"Cubic 11", "俐方体11号", monospace'
    assert own["fontSize"] == 48.0
    assert own["color"] == "#ABCDEF"
    assert own["bold"] is False
    assert own["letterSpacing"] == 2.0
    # 走完整校验链
    document = builtin_web_themes()["doom95"]
    merged = dict(document.to_dict())
    merged.update(payload)
    merged["name"] = "X"
    from twobyteasr.caption_design.web_theme import WebThemeDocument

    validated = WebThemeDocument.from_dict(merged)
    assert validated.appearance["fontSize"] == 48.0


def test_theme_archive_html_carries_theme_font():
    html = theme_archive_html(
        builtin_web_themes()["doom95"].to_dict(), sample_text="测试",
    )
    assert "俐方体11号" in html
    assert "#C9D1D9" in html
    assert "wt-theme-data" in html


def _workshop_project() -> SubtitleProject:
    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    project.speakers = []
    web_style = project.styles[0].id
    project.style_recipes[web_style] = _doom_recipe().to_dict()
    project.cues.append(StudioCue(id="w1", start_ms=0, end_ms=2000, text="特效一"))
    project.cues.append(StudioCue(id="w2", start_ms=2000, end_ms=4000, text="特效二"))
    for cue in project.cues:
        cue.style_id = web_style
    project.cues[0].speaker_id = "spk-a"
    project.cues[1].speaker_id = "spk-b"
    return project


class _FakeSession:
    def __init__(self, project: SubtitleProject) -> None:
        self.project = project


class _FakePage:
    def __init__(self, project: SubtitleProject) -> None:
        self.session = _FakeSession(project)
        self.project=project
        from types import SimpleNamespace
        self.adopted=[]
        self.drafts=SimpleNamespace(current=None,apply_targets=[],cancel=lambda:None,
            adopt=lambda theme,cue_id,**kwargs:self.adopted.append((dict(theme),cue_id,kwargs)) or 'unit-request')
        self.applied: list[str] = []

    def _theme_drafts(self):return self.drafts

    def _apply_web_theme(self, cue_id: str, theme: dict) -> bool:
        project = self.session.project
        cue = next((item for item in project.cues if item.id == cue_id), None)
        if cue is None:
            return False
        recipe = StyleRecipe.from_dict(
            copy.deepcopy(project.style_recipes[cue.style_id])
        )
        recipe.web_theme = copy.deepcopy(dict(theme))
        project.style_recipes[cue.style_id] = recipe.to_dict()
        self.applied.append(cue_id)
        return True


def test_workshop_dialog_controls_and_scope(monkeypatch):
    app = _app()
    from twobyteasr.caption_design.studio_web_theme_workshop import _QUICK_ASKS, WebThemeWorkshopDialog

    project = _workshop_project()
    page = _FakePage(project)
    dialog = WebThemeWorkshopDialog(
        page,
        cue_id="w1",
        theme=dict(project.style_recipes[project.cues[0].style_id]["webTheme"]),
        cue_text=project.cues[0].text,
        preview=False,
    )
    try:
        # 与文字工具不同的 UI：对话窗+输入+快捷意见，而非字体/字号/颜色参数控件。
        assert not hasattr(dialog, "_font_combo") and not hasattr(dialog, "_size_spin")
        assert dialog._chat is not None and dialog._input is not None
        assert dialog._send.text() == "发送给 AI"
        dialog._fill_ask(_QUICK_ASKS[0])
        assert dialog._input.toPlainText() == _QUICK_ASKS[0]
        # 范围语义：current=1 / speaker=1（同说话人另一条不存在）/ all=2。
        dialog._scope.setCurrentIndex(0)
        assert dialog._target_cue_ids() == ["w1"]
        dialog._scope.setCurrentIndex(2)
        assert dialog._target_cue_ids() == ["w1", "w2"]
        # 套用到范围 + 恢复原始主题都走 page._apply_web_theme。
        dialog._apply_current_to_scope()
        assert len(page.adopted)==1 and page.drafts.apply_targets==["w1","w2"]
        assert page.applied==[]  # application waits for render validation
        dialog._restore_original()
        assert len(page.adopted)==2 and page.drafts.apply_targets==["w1","w2"]
        # 对话记录：欢迎语在，快捷意见填充即用户消息前置。
        assert "AI 字幕工坊" in dialog._chat.toPlainText()
        app.processEvents()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_open_web_theme_workshop_dispatch(monkeypatch):
    """页面入口：特效字幕开对话框；非特效字幕给提示不开。"""
    _app()
    from types import SimpleNamespace

    from twobyteasr.studio import studio_ai_flow

    project = _workshop_project()
    # 加一条普通字幕（无 webTheme）。
    plain = StudioCue(id="plain", start_ms=4000, end_ms=6000, text="普通")
    plain.style_id = "missing"
    project.cues.append(plain)

    created: list[dict] = []

    class _Recorder:
        def __init__(self, page, **kwargs) -> None:
            created.append(kwargs)
            self.shown = False

        def show(self) -> None:
            self.shown = True

    monkeypatch.setattr(
        "twobyteasr.caption_design.studio_web_theme_workshop.WebThemeWorkshopDialog", _Recorder
    )
    hints: list[str] = []
    lookup = {cue.id: cue for cue in project.cues}
    harness = SimpleNamespace(
        project=project,
        _cue_lookup=lookup,
        _renderer_cue_at_playhead=lambda: None,
        selected_cue_id="w1",
        _show_studio_hint=lambda text: hints.append(text),
        _web_theme_workshop=None,
    )
    studio_ai_flow.StudioAIFlowMixin._open_web_theme_workshop(harness, "w1")
    assert created and created[0]["cue_id"] == "w1"
    assert harness._web_theme_workshop.shown

    created.clear()
    studio_ai_flow.StudioAIFlowMixin._open_web_theme_workshop(harness, "plain")
    assert not created
    assert hints and "不是 AI 特效字幕" in hints[-1]
