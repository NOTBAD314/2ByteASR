"""四十二轮守护：Studio 识别五项——方案/词库/后台化/API 卡死/MAI 探测 404。

背景（用户实录）：
- 在线 API 识别"一直卡住"= _start_run 预检 QMessageBox 盖在识别弹窗下的隐形模态卡死，
  且异步 singleShot 启动让调用方拿不到失败结果；
- 词库勾选后摘要永远"未选择词库"= item flags 缺 ItemIsSelectable，activated 永不发射
  （offscreen 探针实证：视图自动勾选但 activated=[]）；
- MAI 测试连接 404 = models_url 拿完整转写端点拼 /v1/models；
- 识别转后台：dispatch 关弹窗，状态进左侧字幕列表芯片。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twobyteasr.providers.llm_config import models_url
from twobyteasr.projects.studio_project import StudioCue, StudioMedia
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _page(monkeypatch, tmp_path) -> SubtitleStudioPage:
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._create_blank_studio()
    page.project.media = StudioMedia(
        path=str(tmp_path / "fixture.mp4"), duration_ms=60_000, width=1920, height=1080,
    )
    page.project.cues = [StudioCue("cue-old", 0, 4_000, "旧正式字幕", style_id="default")]
    page._media_ingest_state = "READY"
    page._empty_playback_state = False
    return page


def _open_sheet(page, tmp_path) -> dict:
    media = tmp_path / "recognition.flv"
    media.write_bytes(b"fixture")
    page.project.media.path = str(media)
    page.project.glossary_ids = ["洛克王国世界", "全局记忆"]
    page.project_path = tmp_path / "recognition.2byteproj"
    page._open_recognition_sheet()
    return page._recognition_controls


# ---------------------------------------------------------------- models_url


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        # 用户实录的 404：完整转写端点被直接拼 /v1/models。
        (
            "https://openrouter.ai/api/v1/audio/transcriptions",
            "https://openrouter.ai/api/v1/models",
        ),
        ("https://api.groq.com/openai/v1/audio/transcriptions", "https://api.groq.com/openai/v1/models"),
        ("https://api.openai.com/v1/audio/transcriptions", "https://api.openai.com/v1/models"),
        # dashscope filetrans 工作台域名（奇异 /transcription 单数后缀）。
        (
            "https://llm-v4zdjopess7u3ohb.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription",
            "https://llm-v4zdjopess7u3ohb.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/v1/models",
        ),
        # 原有行为不回归：挂载点直接 +/models，裸域名 +/v1/models。
        ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1/models"),
        ("https://api.deepseek.com", "https://api.deepseek.com/v1/models"),
        ("https://xx/gemini/openai", "https://xx/gemini/openai/models"),
        ("https://api.example.com/v1/chat/completions", "https://api.example.com/v1/models"),
    ],
)
def test_models_url_strips_endpoint_suffixes(base, expected):
    assert models_url(base) == expected


# ---------------------------------------------------------------- 词库勾选


def test_recognition_glossary_chips_toggle_and_sync(monkeypatch, tmp_path):
    """四十三轮：词库改为常驻勾选 chips（无 popup 依赖），勾选即同步摘要。"""
    from PySide6.QtWidgets import QCheckBox

    page = _page(monkeypatch, tmp_path)
    controls = _open_sheet(page, tmp_path)
    chips_host = controls["glossaries"]
    boxes = chips_host.findChildren(QCheckBox)
    assert len(boxes) >= 2
    boxes[0].setChecked(True)
    _app().processEvents()
    summary = next(
        (
            label
            for label in page._recognition_sheet.findChildren(QLabel)
            if label.text().startswith(("已选", "未选择词库"))
        ),
        None,
    )
    assert summary is not None and summary.text().startswith("已选 1 个词库"), summary.text()
    boxes[1].setChecked(True)
    _app().processEvents()
    assert summary.text().startswith("已选 2 个词库")
    boxes[0].setChecked(False)
    _app().processEvents()
    assert summary.text().startswith("已选 1 个词库"), summary.text()
    page.close_page()


def test_recognition_glossary_filters_blank_entries(monkeypatch, tmp_path):
    """工程 glossary_ids 里的空串（用户截图 6 项 4 空白）不得生成空白行。"""
    from PySide6.QtWidgets import QCheckBox

    page = _page(monkeypatch, tmp_path)
    page.project.glossary_ids = ["洛克王国世界", "", "  ", "全局记忆"]
    _open_sheet(page, tmp_path)
    boxes = page._recognition_controls["glossaries"].findChildren(QCheckBox)
    assert [box.text() for box in boxes] == ["洛克王国世界", "全局记忆"]
    page.close_page()


# ---------------------------------------------------------------- 方案与模型


def test_recognition_plan_options_match_home_and_apply_api(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    controls = _open_sheet(page, tmp_path)
    plan = controls["plan"]
    keys = {plan.itemData(i) for i in range(plan.count())}
    assert {"quality", "speed", "low_memory", "transcribe_only", "api", "custom", "home"} <= keys
    # API 转写方案：api/off/api（三十三轮语义）。
    plan.setCurrentIndex(plan.findData("api"))
    _app().processEvents()
    assert controls["primary"].currentData() == "api"
    assert controls["timeline"].currentData() == "off"
    assert controls["review"].currentData() == "api"
    page.close_page()


def test_recognition_sheet_has_role_picker_buttons(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QPushButton

    page = _page(monkeypatch, tmp_path)
    _open_sheet(page, tmp_path)
    advanced = page._recognition_controls["advanced"]
    buttons = [b for b in advanced.findChildren(QPushButton) if b.text() == "选择…"]
    assert len(buttons) == 3
    page.close_page()


# ---------------------------------------------------------------- 后台化


def test_recognition_dispatch_closes_sheet_and_starts_chip(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    controls = _open_sheet(page, tmp_path)
    emitted = []
    page.recognition_requested.connect(
        lambda action, media, project: emitted.append((action, media, project))
    )
    # Existing final subtitles require the existing replace confirmation.
    controls["start"].click()
    assert not emitted
    from PySide6.QtWidgets import QPushButton, QRadioButton
    assert not controls["start"].parentWidget().findChildren(QRadioButton)
    controls["confirm"].findChild(QPushButton).click()
    _app().processEvents()
    assert emitted and emitted[0][0] == "start_final"
    # 状态进左侧字幕列表芯片：可见、运行中、取消按钮可见。
    assert page._recognition_running is True
    assert page.recognition_chip.isVisibleTo(page.recognition_chip.parentWidget())
    assert page.recognition_chip_label.text().startswith("识别中")
    assert page.recognition_cancel_button.isVisibleTo(page.recognition_chip)
    options = page.recognition_request_options()
    assert options["purpose"] == "final"
    assert options["enabled_glossary_ids"] == []
    assert page._recognition_replace_baseline_ids == {"cue-old"}
    page.close_page()


def test_recognition_fail_shows_reason_on_chip(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    _open_sheet(page, tmp_path)
    page._recognition_running = True
    page.fail_recognition_runtime("API Key 未配置")
    assert page._recognition_running is False
    assert page.recognition_chip_label.text() == "识别未完成 · API Key 未配置"
    assert not page.recognition_cancel_button.isVisibleTo(page.recognition_chip)
    page.close_page()


# ---------------------------------------------------------------- 完成语义


def test_final_cue_delta_replaces_baseline_for_final_purpose(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    media = tmp_path / "recognition.flv"
    media.write_bytes(b"fixture")
    page.project.media.path = str(media)
    page.project_path = tmp_path / "recognition.2byteproj"
    page._open_recognition_sheet()
    # 模拟 dispatch(start_final) 的基线记录：旧正式字幕整组让位。
    page._recognition_replace_baseline_ids = {cue.id for cue in page.project.cues}
    payload = {
        "source_path": str(media),
        "manifest_key": "k",
        "state": "final",
        "replacement_mapping": {},
        "cues": [
            {"id": "new-1", "start_ms": 0, "end_ms": 2_000, "text": "识别结果一", "speaker_id": "S00"},
            {"id": "new-2", "start_ms": 2_100, "end_ms": 4_000, "text": "识别结果二", "speaker_id": "S00"},
        ],
    }
    page.apply_recognition_cue_delta(payload)
    cue_ids = [cue.id for cue in page.project.cues]
    assert cue_ids == ["new-1", "new-2"]
    # 基线一次性消费：后续 final delta 不再移除新内容。
    assert page._recognition_replace_baseline_ids is None
    page.close_page()


# ---------------------------------------------------------------- P4：启动失败落芯片


def test_studio_recognition_start_failure_lands_on_chip(monkeypatch, tmp_path):
    """_start_run 早退（如 API 缺 Key）→ 原因必须落到字幕列表芯片，而不是
    留下一张计时器还在走的死弹窗（用户实录"在线API识别一直卡住"）。"""
    _app()
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "m.flv"
    media.write_bytes(b"x")
    project_path = tmp_path / "p.2byteproj"
    project_path.write_text("{}", encoding="utf-8")
    win = MainWindow([], legacy, object(), None)
    try:
        win.studio_page._create_blank_studio()
        win.studio_page.project.media.path = str(media)
        win.studio_page.project_path = project_path
        monkeypatch.setattr(win.studio_page, "save", lambda: None)
        monkeypatch.setattr(
            win.studio_page,
            "recognition_request_options",
            lambda: {
                "recognition_plan": "api",
                "models": {"primary": "api", "timeline": "off", "review": "api"},
                "enabled_glossary_ids": [],
                "replace_policy": "replace_cues",
            },
        )

        def _fake_start_run():
            # 模拟 _start_run 的早退：占用后释放，原因留在 _run_block_reason。
            win._run_in_progress = True
            win._run_block_reason = "识别后端未保存：请填写 ASR API Key"
            win._run_in_progress = False

        monkeypatch.setattr(win, "_start_run", _fake_start_run)
        win._handle_studio_recognition_request("start_final", str(media), str(project_path))
        _app().processEvents()
        assert win._studio_recognition_context is not None
        # 主页方案下拉应已切到 API 转写（Studio 选项接管主页状态）。
        assert win.recognition_mode_combo.currentData() == "api"
        assert win.primary_asr_backend.currentData() == "api"
        assert (
            win.studio_page.recognition_chip_label.text()
            == "识别未完成 · 识别后端未保存：请填写 ASR API Key"
        )
        assert win.studio_page._recognition_running is False
    finally:
        win.deleteLater()
        _app().processEvents()


# ================================================================ 四十三轮守护


def test_recognition_zero_state_card_runs_in_no_cue_window(monkeypatch, tmp_path):
    """识别状态必须出现在"暂无字幕"区（用户点名主视觉位），含取消与详细进度。"""
    page = _page(monkeypatch, tmp_path)
    page.project.cues = []
    controls = _open_sheet(page, tmp_path)
    emitted = []
    page.recognition_requested.connect(
        lambda action, media, project: emitted.append(action)
    )
    controls["start"].click()
    _app().processEvents()
    assert emitted == ["start_final"]
    card = page.recognition_zero_card
    assert card.isVisibleTo(page.cue_zero_state)
    assert page.recognition_zero_label.text().startswith("识别中")
    assert page.recognition_zero_cancel.isVisibleTo(card)
    assert page.recognition_zero_detail.isVisibleTo(card)
    # 运行中隐藏"识别字幕"主按钮，避免重入困惑。
    assert not page.cue_recognize_button.isVisibleTo(page.cue_zero_state)
    page.close_page()


def test_recognition_detail_and_cancel_signals(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page.project.cues = []
    controls = _open_sheet(page, tmp_path)
    controls["start"].click()
    _app().processEvents()
    detail_calls = []
    cancel_calls = []
    page.recognition_detail_requested.connect(lambda: detail_calls.append(1))
    page.recognition_cancel_requested.connect(lambda: cancel_calls.append(1))
    page.recognition_zero_detail.click()
    page.recognition_zero_cancel.click()
    _app().processEvents()
    assert detail_calls and cancel_calls
    # 取消请求发出后：可见反馈（正在安全取消）+取消按钮隐藏防重复点击。
    page.set_recognition_cancelling()
    assert "正在安全取消" in page.recognition_chip_label.text()
    assert not page.recognition_cancel_button.isVisibleTo(page.recognition_chip)
    assert not page.recognition_zero_cancel.isVisibleTo(page.recognition_zero_card)
    page.close_page()


def test_recognition_sheet_shows_full_api_model_name(monkeypatch, tmp_path):
    """API 项必须显示完整 provider·model（用户怀疑调错模型）。"""
    page = _page(monkeypatch, tmp_path)
    controls = _open_sheet(page, tmp_path)
    primary = controls["primary"]
    index = primary.findData("api")
    assert index >= 0
    label = primary.itemText(index)
    assert "在线 ASR API" in label and "·" in label, label
    plan = controls["plan"]
    plan_api = plan.itemText(plan.findData("api"))
    assert plan_api.startswith("API 转写（") and plan_api.endswith("）"), plan_api
    page.close_page()


def test_transform_handle_box_caps_composition_overflow(monkeypatch, tmp_path):
    """visualGraph 装置外扩不再把拖拽框撑到 2.5×（四十三轮帽 0.22）。"""
    from twobyteasr.caption_design.visual_design_graph import DecorationLayer, VisualDesignGraph

    page = _page(monkeypatch, tmp_path)
    project = page.project
    style = next(s for s in project.styles if s.id == project.cues[0].style_id)
    deco = DecorationLayer.from_dict(
        {"id": "d1", "primitive": "PARTICLES", "params": {"overflow": 1.2}}
    )
    graph = VisualDesignGraph(name="probe43", decoration_layers=[deco])
    project.style_recipes[style.id] = {
        "name": "probe43",
        "engine": "remotion",
        "visualGraph": graph.to_dict(),
    }
    page._load_style_inspector()
    overflow = page.position_overlay._composition_overflow
    assert overflow <= 0.22
    content = page.position_overlay._rendered_text_rect()
    sel = page.position_overlay._subtitle_rect()
    pad = page.position_overlay.SELECTION_PADDING
    assert sel.width() <= content.width() * (1 + 2 * overflow) + 2 * pad + 1.0
    page.close_page()


def test_compositor_publish_rejected_when_media_detached(monkeypatch, tmp_path):
    """换工程/回主页后迟到帧不得重新 add overlay（旧字幕钉在新视频上根因）。"""
    from PySide6.QtCore import QRect

    page = _page(monkeypatch, tmp_path)
    video = page.video
    calls = []

    class _FakeController:
        running = True

        def set_raw_overlay(self, overlay_id, path, **geometry):
            calls.append(overlay_id)

        def remove_overlay(self, overlay_id):
            calls.append(("remove", overlay_id))

    video.controller = _FakeController()
    target = QRect(10, 10, 40, 20)
    bounds = QRect(0, 0, 40, 20)
    from PySide6.QtGui import QImage

    image = QImage(40, 20, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    video._media_attached = False
    assert video.publish_compositor_overlay(7, image, target, source_bounds=bounds) is False
    assert calls == []
    video._media_attached = True
    try:
        video.publish_compositor_overlay(7, image, target, source_bounds=bounds)
    except Exception:
        raise
    assert calls == [7]
    video.remove_compositor_overlay(7, force=True)
    page.close_page()

