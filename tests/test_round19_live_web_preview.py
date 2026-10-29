"""第十九轮：实时 Web 预览（视频层真身）+ 反克隆契约 + 阴影闪烁消抖。"""

from __future__ import annotations

import base64
import time
from types import SimpleNamespace

import pytest

pytestqt = pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal, QRectF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.caption_design.web_theme import (
    WebThemeDocument,
    builtin_web_themes,
    theme_archive_html,
)


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication([])


def _doom_recipe_payload() -> dict:
    from twobyteasr.caption_style.style_recipe import StyleRecipe

    recipe = StyleRecipe(
        name="D95",
        engine="remotion",
        typography={"fontFamily": "Microsoft YaHei UI", "fontSize": 58, "bold": True},
        colors={"fill": "#C9D1D9", "outline": "#10181E"},
        web_theme=builtin_web_themes()["doom95"].to_dict(),
    )
    return recipe.to_dict()


def _project_with_web_cue() -> SubtitleProject:
    project = SubtitleProject(media=StudioMedia(path="x.mp4"))
    style_id = project.styles[0].id
    project.style_recipes[style_id] = _doom_recipe_payload()
    project.cues.append(StudioCue(id="w1", start_ms=10_000, end_ms=13_000, text="像素真身"))
    project.cues[0].style_id = style_id
    return project


class _FakeSnapshot:
    def __init__(self, cue_id: str, text: str, recipe: dict) -> None:
        self.cue_id = cue_id
        self.text = text
        self.style_recipe = recipe

    def stable_hash(self):
        return self.cue_id+':'+self.text


def test_words_wrapper_rejected():
    payload = builtin_web_themes()["doom95"].to_dict()
    payload["cueHtml"] = (
        '<div class="plate"><div class="line">'
        '<span class="wt-w">{{words}}</span></div></div>'
    )
    with pytest.raises(Exception, match="wt-w"):
        WebThemeDocument.from_dict(payload)
    # 包其它类的 span 不受影响（占位符校验照旧通过）。
    ok = builtin_web_themes()["doom95"].to_dict()
    ok["cueHtml"] = '<div class="line">{{words}}</div>'
    assert WebThemeDocument.from_dict(ok).name


def test_archive_html_live_driver_variants():
    doom = builtin_web_themes()["doom95"].to_dict()
    live = theme_archive_html(doom, sample_text="测试", duration_seconds=2.0, auto_replay=False)
    assert "__2byteSeek" in live and "setInterval" not in live
    assert "--wt-dur: 2.000s" in live
    replay = theme_archive_html(doom, sample_text="测试")
    # The shared async replay awaits play before arming its next timeout;
    # an interval would overlap in-flight browser operations.
    assert '__2byteSeek' in replay and 'setTimeout(replay' in replay
    assert 'setInterval' not in replay and '__2byteStopReplay' in replay


def test_live_worker_configure_dedup_and_gate(monkeypatch):
    _app()
    from twobyteasr.rendering import live_web_preview as lwp
    from twobyteasr.rendering.live_web_preview import LiveWebPreviewWorker

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert lwp.live_preview_enabled() is False
    monkeypatch.setenv("TWOBYTEASR_FORCE_WEB_LIVE", "1")
    assert lwp.live_preview_enabled() is True
    monkeypatch.setenv("TWOBYTEASR_DISABLE_WEB_LIVE", "1")
    assert lwp.live_preview_enabled() is False

    doom = builtin_web_themes()["doom95"].to_dict()
    worker = LiveWebPreviewWorker(loop_seconds=2.4)
    key1 = worker.configure(theme=doom, text="字幕预览ABC123")
    assert worker.html_key == key1
    # 二十二轮新契约：主题键与文案分离——同主题换文案同 key、走 live_text
    # 快路径（pending_text）；换主题才换 key（整页重载）。
    worker._html_dirty = False
    worker._loaded_text = "字幕预览ABC123"
    assert worker.configure(theme=doom, text="字幕预览ABC123") == key1
    assert worker._pending_text is None and worker._html_dirty is False
    assert worker.configure(theme=doom, text="第二句字幕") == key1
    assert worker._pending_text == ("第二句字幕", "")
    key2 = worker.configure(theme=dict(doom, notes="changed"), text="第二句字幕")
    assert key2 != key1 and worker._html_dirty is True
    assert worker.running is False and worker._thread is None


def test_ensure_web_live_preview_takeover_and_breaker(monkeypatch):
    """web cue 调度接管 + 失败熔断（offscreen 用 FORCE 开闸 + stub worker）。"""
    _app()
    from twobyteasr.rendering import live_web_preview as lwp
    from twobyteasr.studio import studio_advanced_flow

    created: list[object] = []

    class _StubWorker(QObject):
        frame_ready = Signal(bytes, float, float)
        failed = Signal(str)
        exited = Signal()

        def __init__(self, **kwargs) -> None:
            super().__init__()
            self.configured: list[dict] = []
            self.started = False
            self._width=kwargs['width'];self._height=kwargs['height']
            created.append(self)

        def mark_dirty(self) -> None:
            return None

        @property
        def running(self) -> bool:
            return self.started

        @property
        def html_key(self) -> str:
            return "stub-key"

        def configure(self, **kwargs) -> str:
            self.configured.append(kwargs)
            return "stub-key"

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.started = False

    monkeypatch.setenv("TWOBYTEASR_FORCE_WEB_LIVE", "1")
    monkeypatch.setattr(lwp, "LiveWebPreviewWorker", _StubWorker)

    project = _project_with_web_cue()
    cue = project.cues[0]
    recipe = project.style_recipes[cue.style_id]

    class _Harness(studio_advanced_flow.StudioAdvancedFlowMixin):
        def __init__(self) -> None:
            self.project = project
            self._web_live_worker = None
            self._web_live_bridge = None
            self._web_live_failed_at = 0.0
            self._web_live_snapshot = None
            self._web_live_cue_id = ""
            self._web_live_last_frame_at = 0.0
            # Current rendering binds to the actual viewport and Clock. The
            # old fixture predated those required collaborators.
            self.position_overlay=SimpleNamespace(_content_rect=lambda:QRectF(0,0,1280,720))
            self.video=SimpleNamespace(devicePixelRatioF=lambda:1.,playback_position_snapshot=lambda:SimpleNamespace(
                paused=True,playback_generation=1,presentation_media_ms=10500,playback_rate=1.))
            self.advanced_cue_overlay=SimpleNamespace(_snapshot=None)

    harness = _Harness()
    snapshot = _FakeSnapshot(cue.id, cue.text, recipe)
    assert harness._ensure_web_live_preview(cue, snapshot)
    worker = created[-1]
    assert worker.started and worker.configured[0]["text"] == cue.text
    assert harness._web_live_cue_id == cue.id
    # 二次调用复用同一 worker（running=True 不重建）。
    harness._ensure_web_live_preview(cue, snapshot)
    assert len(created) == 1

    # 熔断：失败时间戳新鲜 → 拒绝接管，走旧路径。
    harness._web_live_failed_at = time.monotonic()
    assert not harness._ensure_web_live_preview(cue, snapshot)
    # 时间戳过期 → 恢复。
    harness._web_live_failed_at = time.monotonic() - 60.0
    assert harness._ensure_web_live_preview(cue, snapshot)
    harness._web_live_watchdog_timer.stop()
    harness._web_frame_decode_runner.close()
    worker.stop()


# 1x1 PNG（offscreen 下 QImage.save(QBuffer) 会 abort，用真实 base64 常量替代）。
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M"
    "9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _tiny_png_bytes(color: str = "#2ECC71") -> bytes:
    return _TINY_PNG


def test_web_live_frame_publishes_and_fresh_guard():
    _app()
    from twobyteasr.studio import studio_advanced_flow

    class _Overlay:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def set_visual(self, pixmap, snapshot, animate_graph=False) -> None:
            self.calls.append((pixmap, snapshot, animate_graph))

    project = _project_with_web_cue()
    cue = project.cues[0]
    snapshot = _FakeSnapshot(cue.id, cue.text, project.style_recipes[cue.style_id])
    overlay = _Overlay()
    traces: list[tuple] = []

    class _Harness(studio_advanced_flow.StudioAdvancedFlowMixin):
        def __init__(self) -> None:
            self.advanced_cue_overlay = overlay
            self._web_live_snapshot = snapshot
            self._web_live_cue_id = cue.id
            self._web_live_last_frame_at = 0.0
            self._advanced_canvas_source_kind = ""
            self._advanced_cue_pixmap = None
            self._studio_trace = lambda event, **fields: traces.append((event, fields))

    harness = _Harness()
    harness._on_web_live_frame(_tiny_png_bytes(), 500.0, 10500.0)
    assert overlay.calls and harness._advanced_canvas_source_kind == "web_live"
    assert harness._advanced_cue_pixmap is not None
    assert traces and traces[-1][0] == "WEB_LIVE_FRAME"
    # fresh 判定：刚发布 → True；十秒前 → False。
    assert harness._web_live_is_fresh() is True
    harness._web_live_last_frame_at = time.monotonic() - 10.0
    assert harness._web_live_is_fresh() is False


def test_native_visible_debounce_keeps_advanced_overlay():
    """字幕真身 overlay 在显示时，原生 True 请求被消抖吞掉（闪烁修复）。"""
    _app()
    from twobyteasr.studio.studio_video_canvas import MpvCanvas

    canvas = MpvCanvas()
    canvas._active_compositor_overlays.add(MpvCanvas.ADVANCED_OVERLAY_ID)
    canvas._native_subtitle_visible = False
    # True 请求：进入消抖（不立即改控制器；controller 为 None 也安全）。
    canvas.set_native_subtitle_visible(True)
    timer = canvas._native_visible_debounce
    assert timer.isActive()
    # 窗口内 False 到达：撤销请求并停表。
    canvas.set_native_subtitle_visible(False)
    assert not timer.isActive() and canvas._native_subtitle_visible is False
    # overlay 摘掉后 True 生效（经延迟重查路径）。
    canvas._active_compositor_overlays.discard(MpvCanvas.ADVANCED_OVERLAY_ID)
    canvas.set_native_subtitle_visible(True)
    assert canvas._native_subtitle_visible is True
    canvas.deleteLater()


def test_invalid_svg_selection_rectangle_does_not_break_frame_alpha():
    from twobyteasr.studio.selection_geometry import alpha_bounds
    png=_tiny_png_bytes()
    assert alpha_bounds(png,[None,None,None,None]) is None
    assert alpha_bounds(png,[0,0,float('nan'),10]) is None
    assert alpha_bounds(png) is not None
