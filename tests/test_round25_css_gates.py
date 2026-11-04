"""第二十五轮：CSS 括号平衡硬门 + 发布门控 trailing-flush 保底。"""

from __future__ import annotations

import time

import pytest

pytestqt = pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QObject
from PySide6.QtWidgets import QApplication

from twobyteasr.caption_design.web_theme import (
    WebThemeValidationError,
    WebThemeDocument,
    builtin_web_themes,
    validate_generated_theme,
)


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication([])


def _balatro() -> dict:
    return builtin_web_themes()["balatro-joker"].to_dict()


# ---------------------------------------------------------------------------
# CSS 括号平衡硬门（死亡搁浅主题 .wt-w 少右括号 → animation 被吞 → 字永久隐形）
# ---------------------------------------------------------------------------


def test_gate_rejects_unbalanced_paren():
    payload = _balatro()
    # 模拟真实事故形态：translateY(calc(...) 少一个右括号。
    payload["cueCss"] += "\n.wt-text .wt-w { transform: rotateX(85deg) translateY(calc(.6 * var(--wt-u)); }"
    doc = WebThemeDocument.from_dict(payload)
    with pytest.raises(WebThemeValidationError, match="括号不配对"):
        validate_generated_theme(doc)


def test_gate_rejects_unbalanced_brace():
    payload = _balatro()
    payload["stageCss"] += "\n.joker-hat { left: 2%;"
    doc = WebThemeDocument.from_dict(payload)
    with pytest.raises(WebThemeValidationError, match="括号不配对"):
        validate_generated_theme(doc)


def test_gate_balanced_theme_still_passes():
    doc = WebThemeDocument.from_dict(_balatro())
    validate_generated_theme(doc)


# ---------------------------------------------------------------------------
# 发布门控 trailing-flush：门控拦下的帧必须保底落地（出场清屏帧不可丢）
# ---------------------------------------------------------------------------


def test_publish_gate_flushes_trailing_frame():
    _app()
    from twobyteasr.studio import studio_advanced_flow
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject

    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    project.cues.append(StudioCue(id="w1", start_ms=0, end_ms=1200, text="甲"))

    class _Overlay:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def set_visual(self, pixmap, snapshot, animate_graph=False) -> None:
            self.calls.append(pixmap)

    class _Snapshot:
        cue_id = "w1"
        text = "甲"
        style_recipe: dict = {}

    overlay = _Overlay()

    app = QApplication.instance()

    class _Harness(studio_advanced_flow.StudioAdvancedFlowMixin):
        def __init__(self) -> None:
            self.project = project
            self.advanced_cue_overlay = overlay
            self._web_live_snapshot = _Snapshot()
            self._web_live_cue_id = "w1"
            self._web_live_last_frame_at = 0.0
            self._advanced_canvas_source_kind = "web_live"
            self._advanced_cue_pixmap = None
            self._studio_trace = lambda event, **fields: None

    from PySide6.QtGui import QImage
    from tests.test_round24_web_strip_playback import _TINY_PNG

    harness = _Harness()
    image = QImage.fromData(_TINY_PNG)
    assert not image.isNull()
    # 第一帧立即发布。
    harness._on_web_live_frame(image, 100.0, 100.0)
    assert len(overlay.calls) == 1
    # 1ms 后的第二帧被门控拦下（不出现在画布），但必须进入 pending。
    harness._on_web_live_frame(image, 400.0, 400.0)
    assert len(overlay.calls) == 1
    assert harness._web_live_pending_frame is not None
    # 35ms 定时器到期后补发（事件循环处理后）——出场清屏帧不丢。
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and len(overlay.calls) < 2:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    assert len(overlay.calls) == 2, "trailing frame must land after flush timer"
    # 兼容 bytes 旧形态。
    harness._web_live_publish_gate = 0.0
    harness._on_web_live_frame(_TINY_PNG, 500.0, 500.0)
    assert len(overlay.calls) == 3


# ---------------------------------------------------------------------------
# 二十六轮：渲染服务预热必须避开启动窗口（黑屏两分钟回归）
# ---------------------------------------------------------------------------


def test_renderer_warm_waits_for_ready_project_and_web_cues():
    _app()
    from PySide6.QtCore import QTimer
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject

    scheduled: list[tuple[int, object]] = []
    original_single_shot = QTimer.singleShot

    def fake_single_shot(ms, callback):
        scheduled.append((ms, callback))

    from types import SimpleNamespace

    stub = SimpleNamespace(
        _close_requested=False, project=None,
        video=SimpleNamespace(_startup_state="LOADING"),
        _warm_web_renderer_service=lambda: None,
        _maybe_schedule_web_renderer_warm=None,
    )
    method = SubtitleStudioPage._maybe_schedule_web_renderer_warm.__get__(stub)
    stub._maybe_schedule_web_renderer_warm = method
    page = stub

    QTimer.singleShot = staticmethod(fake_single_shot)
    try:
        # 工程未打开 → 只重排等待，不排 warm。
        page._maybe_schedule_web_renderer_warm()
        assert scheduled and scheduled[-1][1] != page._warm_web_renderer_service

        # 工程打开但无特效字幕 → 不排 warm。
        project = SubtitleProject(media=StudioMedia(path="x.mp4"))
        project.cues.append(StudioCue(id="p1", start_ms=0, end_ms=1000, text="甲"))
        page.project = project
        page.video._startup_state = "READY"
        page._maybe_schedule_web_renderer_warm()
        assert all(cb != page._warm_web_renderer_service for _, cb in scheduled)

        # 含特效字幕 → 媒体 READY 后延迟 15s 排 warm（避开启动/挂载窗口）。
        from twobyteasr.caption_style.style_recipe import StyleRecipe
        from twobyteasr.caption_design.web_theme import builtin_web_themes

        recipe = StyleRecipe(
            name="W", engine="remotion",
            typography={"fontFamily": "Microsoft YaHei UI", "fontSize": 58},
            colors={"fill": "#FFFFFF", "outline": "#000000"},
            web_theme=builtin_web_themes()["balatro-joker"].to_dict(),
        )
        project.style_recipes["webx"] = recipe.to_dict()
        project.cues[0].style_id = "webx"
        page._maybe_schedule_web_renderer_warm()
        warm_entries = [ms for ms, cb in scheduled if cb == page._warm_web_renderer_service]
        assert warm_entries == [15_000], warm_entries
    finally:
        QTimer.singleShot = original_single_shot


# ---------------------------------------------------------------------------
# 二十七轮：底板质感硬门——平涂底板拒收（死亡搁浅实测"只是一个描边框"）
# ---------------------------------------------------------------------------


def test_gate_rejects_flat_plate_background():
    from twobyteasr.caption_design.web_theme import _reject_flat_plate
    payload=_balatro()
    payload['cueHtml']='<div class="plate">{{text}}</div>'
    payload['cueCss']='.plate{font-family:var(--wt-font);background:rgba(14,16,18,.82);border:2px solid #C9A227;}'
    with pytest.raises(WebThemeValidationError,match='平涂'):
        _reject_flat_plate(WebThemeDocument.from_dict(payload),'工业字幕')


def test_gate_gradient_plate_and_glass_exemption_pass():
    from twobyteasr.caption_design.web_theme import _reject_flat_plate
    payload=_balatro();payload['cueHtml']='<div class="plate">{{text}}</div>'
    payload['cueCss']='.plate{font-family:var(--wt-font);background:linear-gradient(#333,#111);}'
    _reject_flat_plate(WebThemeDocument.from_dict(payload),'工业字幕')
    payload['cueCss']='.plate{font-family:var(--wt-font);background:rgba(200,220,255,.25);}'
    _reject_flat_plate(WebThemeDocument.from_dict(payload),'玻璃质感字幕')
