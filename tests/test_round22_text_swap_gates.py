"""第二十二轮：换字快速路径 + 丰富度/框结实度生成硬门。"""

from __future__ import annotations

import pytest

pytestqt = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from twobyteasr.caption_design.web_theme import (
    WebThemeDocument,
    builtin_web_themes,
    theme_archive_html,
    validate_generated_theme,
    WebThemeValidationError,
)


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication([])


def _doom():
    return builtin_web_themes()["doom95"].to_dict()


def test_archive_html_embeds_set_cue_template():
    html = theme_archive_html(_doom(), sample_text="测试", duration_seconds=2.0, auto_replay=False)
    assert "__2byteSetCue" in html
    assert "window.__2byteCueTemplate" in html
    # 模板保留占位符原文（换字用），而渲染出来的 cue 已替换。
    assert "{{words}}" in html.split("window.__2byteCueTemplate", 1)[1]
    assert "{{words}}" not in html.split('id="wt-cue"', 1)[1].split("</div>", 1)[0]


def test_worker_theme_key_separates_text():
    """同主题换文案：不置 dirty（走 live_text 快路径）；换主题才整页重载。"""
    _app()
    from twobyteasr.rendering.live_web_preview import LiveWebPreviewWorker

    worker = LiveWebPreviewWorker(loop_seconds=2.4)
    theme = _doom()
    key1 = worker.configure(theme=theme, text="第一句")
    assert worker._html_dirty is True  # 首次装载
    # 模拟泵已处理 live_set（清 dirty 并记录已装载文案）。
    worker._html_dirty = False
    worker._loaded_text = "第一句"
    key2 = worker.configure(theme=theme, text="第二句")
    assert key2 == key1
    assert worker._html_dirty is False  # 未置脏——换字不重载
    assert worker._pending_text == ("第二句", "")
    changed = dict(theme)
    changed["notes"] = "theme changed"
    key3 = worker.configure(theme=changed, text="第二句")
    assert key3 != key1 and worker._html_dirty is True
    assert worker._pending_text is None  # 重载带上新文案，无需快路径


def test_gate_minimum_scene_objects():
    thin = dict(_doom())
    thin["concept"] = "扫描线 .scanlines 血溅 .splat"
    with pytest.raises(WebThemeValidationError, match="场景物件太少"):
        validate_generated_theme(WebThemeDocument.from_dict(thin))


def test_gate_rich_scene_with_loops_passes():
    ok = dict(_doom())
    ok["concept"] = "扫描线 .scanlines 血溅 .splat 火花 .ember 刻度 .hudgrid 脉冲 .pulse"
    validate_generated_theme(WebThemeDocument.from_dict(ok))


def test_gate_washed_out_plate_rejected_unless_glass():
    base = dict(_doom())
    base["concept"] = "扫描线 .scanlines 血溅 .splat 火花 .ember 刻度 .hudgrid 脉冲 .pulse"
    washed = dict(base)
    washed["cueCss"] = base["cueCss"] + "\n.wt-cue .plate{background-color:rgba(20,20,20,.18)}"
    document = WebThemeDocument.from_dict(washed)
    with pytest.raises(WebThemeValidationError, match="底板太透"):
        validate_generated_theme(document)
    # 用户点名玻璃 → 豁免；结实的框 → 通过。
    validate_generated_theme(document, instruction="玻璃质感字幕框")
    solid = dict(base)
    solid["cueCss"] = base["cueCss"] + "\n.wt-cue .plate{background-color:rgba(18,20,16,.92)}"
    validate_generated_theme(WebThemeDocument.from_dict(solid))


def test_service_exposes_live_text():
    from twobyteasr.rendering.renderer_service import RendererService

    assert hasattr(RendererService, "live_text")
    assert hasattr(RendererService, "live_play")
    assert hasattr(RendererService, "live_latest")
