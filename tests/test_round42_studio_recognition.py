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


def test_empty_project_recognition_button_opens_sheet(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page.project.cues = []
    media = tmp_path / 'empty-project.mp4'
    media.write_bytes(b'fixture')
    page.project.media.path = str(media)
    page.project_path = tmp_path / 'empty-project.2byteproj'
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda kind, value, tb: errors.append((kind, str(value))))
    page.cue_recognize_button.click()
    _app().processEvents()
    assert not errors, errors
    assert getattr(page, '_recognition_sheet', None) is not None
    page.close_page()


def test_recognition_sheet_rejects_reentry_and_allows_retry(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    page.project.cues = []
    controls = _open_sheet(page, tmp_path)
    emitted = []
    page.recognition_requested.connect(lambda action, media, project: emitted.append(action))
    controls['start'].click()
    controls['start'].click()
    assert emitted == ['start_final']
    page.fail_recognition_runtime('测试失败')
    controls['start'].click()
    assert emitted == ['start_final', 'start_final']
    page.close_page()


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
    # 2026-10-23: the glossary dropdown itself says what is ticked.
    from PySide6.QtWidgets import QComboBox
    summary = page._recognition_sheet.findChild(QComboBox, "recognitionGlossaryButton")
    assert summary is not None and summary.text().startswith("已选 1 个"), summary.text()
    boxes[1].setChecked(True)
    _app().processEvents()
    assert summary.text().startswith("已选 2 个")
    boxes[0].setChecked(False)
    _app().processEvents()
    assert summary.text().startswith("已选 1 个") and boxes[1].text() in summary.text(), summary.text()
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
    # 2026-10-23: 本地识别 / API 转写 / 日语 / 外语 + 当前主页方案; 自定义 only
    # while the models were changed by hand. API 转写 = MOSS Pro + FireRedASR2
    # for Chinese / auto (Qwen3 对齐 for other languages), no review.
    assert keys == {"quality", "japanese", "english", "moss_pro_qwen", "home"}
    plan.setCurrentIndex(plan.findData("moss_pro_qwen"))
    _app().processEvents()
    assert controls["primary"].currentData() == "api"
    assert controls["timeline"].currentData() == "local"
    assert controls["review"].currentData() == "off"
    controls["review"].setCurrentIndex(controls["review"].findData("local"))
    _app().processEvents()
    assert plan.currentData() == "custom" and plan.currentText() == "自定义"
    plan.setCurrentIndex(plan.findData("quality"))
    _app().processEvents()
    assert plan.findData("custom") < 0
    page.close_page()


def test_recognition_sheet_scrolls_instead_of_squeezing_rows(monkeypatch, tmp_path):
    # 2026-10-22 user report: 高级配置 opened inside the fixed-height modal card
    # squeezed the three model rows into one strip. The content scrolls now.
    # 2026-10-23: speakers follow the primary model; the sheet has no speaker selector.
    from PySide6.QtWidgets import QComboBox, QScrollArea

    page = _page(monkeypatch, tmp_path)
    controls = _open_sheet(page, tmp_path)
    scroll = page._recognition_sheet.findChild(QScrollArea, "studioRecognitionScroll")
    assert scroll is not None and scroll.widgetResizable()
    body = scroll.widget()
    assert body.isAncestorOf(controls["advanced"])
    assert not any(c.findData("single") >= 0 or c.findData("ecapa") >= 0 for c in body.findChildren(QComboBox))
    assert controls["start"].parentWidget() is not None
    page.close_page()


def test_recognition_sheet_layout_c_plan_roles_left_summary_right(monkeypatch, tmp_path):
    # 2026-10-23 user chose layout C: the left column has 识别方案 and under it
    # three thin model rows (logo, role, name with its languages, readiness);
    # 「这次识别」 on the right (glossary, translation, what is missing, the one
    # start button); both columns share their top and bottom edge.
    from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QPushButton, QWidget

    page = _page(monkeypatch, tmp_path)
    controls = _open_sheet(page, tmp_path)
    sheet = page._recognition_sheet
    rows = controls["rows"]
    assert list(rows) == ["primary", "timeline", "review"]
    assert [row.objectName() for row in rows.values()] == ["sheetRoleRow"] * 3
    for key in ("primary", "timeline", "review"):
        assert controls["advanced"].isAncestorOf(rows[key]) and controls[key].isHidden()
    summary_card = controls["summary"]
    assert summary_card.objectName() == "recognitionSummary"
    glossary_button = sheet.findChild(QWidget, "recognitionGlossaryButton")
    for widget in (controls["start"], controls["confirm"], controls["translation"], glossary_button):
        assert summary_card.isAncestorOf(widget)
    assert controls["start"].property("buttonRole") == "primary" and controls["start"].property("controlSize") == "large"
    primary_buttons = [b for b in sheet.findChildren(QPushButton) if b.property("buttonRole") == "primary"]
    assert set(primary_buttons) <= {controls["start"], controls["confirm"].findChild(QPushButton)}
    sheet.resize(1040, 300)  # shorter than the content: everything at its natural height
    sheet.show()
    _app().processEvents()
    body = controls["left"].parentWidget()
    plan_bottom = controls["plan"].mapTo(body, controls["plan"].rect().bottomLeft()).y()
    left, right = controls["left"].geometry(), summary_card.geometry()
    assert controls["left"].isAncestorOf(controls["plan"]) and controls["left"].isAncestorOf(controls["advanced"])
    assert plan_bottom < controls["advanced"].mapTo(body, controls["advanced"].rect().topLeft()).y()
    assert left.top() == right.top() and left.bottom() == right.bottom()
    assert left.right() < right.left()
    tops = [rows[key].geometry().top() for key in ("primary", "timeline", "review")]
    assert tops == sorted(tops)
    for row in rows.values():                      # thin rows: one line, not stretched into cards
        assert row.height() <= row.sizeHint().height() * 1.6
    # A local model the catalog knows shows its languages right after the name.
    controls["primary"].setCurrentIndex(controls["primary"].findData("moss"))
    _app().processEvents()
    assert rows["primary"].languages.has_badges()
    assert rows["primary"].name.text()
    assert rows["primary"].languages.geometry().left() >= rows["primary"].name.geometry().right()
    # No description line under the plan (user, 10-23): what it does is its tooltip.
    controls["plan"].setCurrentIndex(controls["plan"].findData("quality"))
    _app().processEvents()
    assert controls["plan"].toolTip().startswith("主稿 + 字级时间轴")
    assert not sheet.findChildren(QFrame, "recognitionFooter")
    assert not [b for b in sheet.findChildren(QPushButton) if "在主页管理" in b.text()]
    # Plan, glossary and translation are the same kind of dropdown.
    assert all(isinstance(w, QComboBox) for w in (controls["plan"], glossary_button, controls["translation"]))
    assert len({w.property("controlSize") for w in (controls["plan"], glossary_button, controls["translation"])}) == 1
    box = controls["glossaries"].findChildren(QCheckBox)[0]
    box.setChecked(True)
    _app().processEvents()
    assert glossary_button.text().startswith("已选 1 个") and box.text() in glossary_button.text()
    page.close_page()


def test_recognition_sheet_rows_open_the_model_picker(monkeypatch, tmp_path):
    page = _page(monkeypatch, tmp_path)
    opened = []
    page._open_model_picker = lambda role, on_closed=None: opened.append(role)
    controls = _open_sheet(page, tmp_path)
    row = controls["rows"]["timeline"]
    page._recognition_sheet.resize(1040, 680)
    page._recognition_sheet.show()
    _app().processEvents()
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)
    QTest.keyClick(controls["rows"]["review"], Qt.Key.Key_Space)
    assert opened == ["timeline", "review"]
    page.close_page()


def test_recognition_sheet_translation_needs_a_connected_ai(monkeypatch, tmp_path):
    # 2026-10-23: translation took the speaker selector's place; like home it
    # stays on 只显示原文 until the AI text service has a key and passed a test.
    from PySide6.QtWidgets import QPushButton

    import twobyteasr.providers.ai_connection_record as record

    page = _page(monkeypatch, tmp_path)
    page._subtitle_language_options = lambda: {"recognition_language": "ja", "chinese_script": "zh-Hans",
                                               "subtitle_output": "bilingual", "translation_script": "zh-Hans"}
    monkeypatch.setattr(record, "feature_gate", lambda _settings: "no_key")
    controls = _open_sheet(page, tmp_path)
    output, target = controls["translation"], controls["translation_target"]
    assert output.currentData() == "original"
    assert not output.model().item(output.findData("bilingual")).isEnabled()
    assert target.isHidden()
    page.close_page()

    page = _page(monkeypatch, tmp_path)
    page._subtitle_language_options = lambda: {"recognition_language": "ja", "chinese_script": "zh-Hans",
                                               "subtitle_output": "bilingual", "translation_script": "zh-Hans"}
    monkeypatch.setattr(record, "feature_gate", lambda _settings: "ready")
    controls = _open_sheet(page, tmp_path)
    output, target = controls["translation"], controls["translation_target"]
    assert output.currentData() == "bilingual"
    targets = [target.itemData(i) for i in range(target.count())]
    assert "ja" not in targets and "zh-Hans" in targets
    output.setCurrentIndex(output.findData("translation"))
    controls["start"].click()
    controls["confirm"].findChild(QPushButton).click()
    _app().processEvents()
    options = page.recognition_request_options()
    assert options["subtitle_output"] == "translation" and options["translation_script"] == "zh-Hans"
    assert options["speaker_source"] in {"moss", "native"}
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
                "recognition_plan": "moss_pro_qwen",
                "models": {"primary": "api", "timeline": "qwen_aligner", "review": "off"},
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
        guides = []
        monkeypatch.setattr(win, "_open_api_setup_guide", lambda preset="", kind="asr": guides.append(preset))
        monkeypatch.setattr("twobyteasr.providers.llm_config.read_asr_api_key", lambda *a, **k: ("", ""))
        win._handle_studio_recognition_request("start_final", str(media), str(project_path))
        _app().processEvents()
        assert win._studio_recognition_context is not None
        # 云端方案（Studio 选项接管主页状态）；没存 MOSS Pro Key 时提醒去填。
        assert win.primary_asr_backend.currentData() == "api"
        assert win.qwen_asr_api_provider.currentData() == "mosi_moss_pro"
        assert guides == ["mosi_moss_pro"]
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


def test_language_badges_put_the_interface_language_first_and_count_the_rest():
    # 2026-10-23 user: the interface language's support first, "+N" when the rest does not fit.
    from twobyteasr.studio.recognition_role_rows import LanguageBadges, badge_plan

    support = {"tiers": {"zh": "strong", "yue": "no", "dialects": "unknown", "en": "strong",
                         "ja": "usable", "ko": "strong"}, "more": 12, "summary": ""}
    badges, more = badge_plan(support, "ja")
    assert [code for code, _tier in badges] == ["ja", "zh", "en", "ko"] and more == 12
    badges, _more = badge_plan(support, "zh")
    assert badges[0] == ("zh", "strong") and ("yue", "no") not in badges
    not_supported = dict(support, tiers=dict(support["tiers"], en="no"))
    assert badge_plan(not_supported, "en")[0][0] == ("en", "no")   # shown first, struck through
    _app()
    row = LanguageBadges()
    row._badges, row._more = badge_plan(support, "zh")
    shown, more_text = row.layout_badges(10_000)
    assert len(shown) == 4 and more_text == "+12"
    shown, more_text = row.layout_badges(row.minimumSizeHint().width())
    assert shown == [("zh", "strong")] and more_text == "+15"
