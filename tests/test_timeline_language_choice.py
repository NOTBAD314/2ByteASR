"""The timeline picker, the workshop and the home card name the same model (2026-10-18).

User report: FireRedASR2-AED was 当前 in 选择字幕时间轴模型 while the home card
said Qwen3 对齐 — the home spoken language was Japanese, and Japanese/English
timing always runs Qwen3-ForcedAligner (moss_firered_pipeline.run_firered_stage).
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.local_models import model_workshop as workshop

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def window(monkeypatch):
    import subtitle_core as legacy
    from twobyteasr.app import ui
    from twobyteasr.local_models.model_registry import ModelRegistry
    from twobyteasr.recognition import asr, ctc_alignment

    installed = {"qwen_aligner", "ja_ctc_aligner", "firered_aed", "qwen_asr"}
    monkeypatch.setattr(ModelRegistry, "installed_keys", lambda self: set(installed))
    monkeypatch.setattr(ui, "installed_model_keys", lambda root: set(installed))
    monkeypatch.setattr(workshop, "_readiness_status", lambda key: "PASS")
    monkeypatch.setattr(workshop, "_host_platform_tag", lambda: "win32-x86_64")
    monkeypatch.setattr(ctc_alignment, "model_dir", lambda: "fixture-ctc")
    monkeypatch.setattr(asr, "resolve_qwen_aligner_local_source", lambda: "fixture-qwen")
    monkeypatch.setitem(legacy.RUNTIME_SETTINGS, "models", {
        **legacy.RUNTIME_SETTINGS.get("models", {}),
        "primary_asr_backend": "none", "qwen_asr_backend": "local", "firered_asr_backend": "local",
    })
    monkeypatch.setitem(legacy.RUNTIME_SETTINGS, "switches", {
        **legacy.RUNTIME_SETTINGS.get("switches", {}), "use_ja_ctc_aligner": False,
    })
    # Each test starts from 自动识别语言 (a previous test saved its choice).
    monkeypatch.setitem(legacy.RUNTIME_SETTINGS, "subtitle_language", {"recognition_language": "auto"})
    win = ui.MainWindow([], legacy, object(), None)
    win.show()
    yield win
    win.close()
    win.deleteLater()
    APP.processEvents()


def speak(win, language):
    win.recognition_language.setCurrentIndex(win.recognition_language.findData(language))


def picker(win):
    win._open_model_picker("timeline")
    QTest.qWait(50)
    return win._model_picker_timeline_panel


def click(panel, key):
    action = panel.cards[key].action
    panel.scroll.ensureWidgetVisible(action)
    QTest.mouseClick(action, Qt.MouseButton.LeftButton)
    QTest.qWait(20)


def test_japanese_firered_choice_names_the_aligner_everywhere(window):
    win = window
    speak(win, "ja")
    card = win.recognition_plan.cards["timeline"]
    assert card.model_label.text() == "Qwen3 对齐"
    assert card.description_label.text() == "字幕语言是日语，FireRedASR2-AED 只用于中文"
    panel = picker(win)
    assert panel.current_badge.text() == "当前：Qwen3 对齐"
    firered, aligner = panel.cards["firered"], panel.cards["qwen_aligner"]
    assert firered.action.text() == "日语时不使用" and not firered.action.isEnabled()
    assert not firered.property("selected")
    assert aligner.property("selected") and aligner.action.text() == "取消使用"
    assert panel.language_note.isVisibleTo(panel)
    note = panel.language_note.text()
    assert "不用于日语" in note and "改成中文或自动识别" in note and "CTC" not in note
    # The workshop page agrees (and its detail pane knows the state).
    page = win.workshop_page
    page._set_role("timeline")
    page.refresh()
    page._view_model("firered")
    assert page._cards["firered"].action.text() == "日语时不使用"
    assert page.detail_action.text() == "日语时不使用" and not page.detail_action.isEnabled()
    win._modal_host._request_close()


def test_cancel_and_use_again_keep_picker_and_home_in_step(window):
    win = window
    speak(win, "ja")
    card = win.recognition_plan.cards["timeline"]
    panel = picker(win)
    click(panel, "qwen_aligner")  # 取消使用: the stage that really runs is switched off
    assert win.firered_asr_backend.currentData() == "off"
    assert card.model_label.text() == "已关闭"
    assert panel.cards["qwen_aligner"].action.text() == "使用"
    assert panel.cards["firered"].action.text() == "日语时不使用"
    assert panel.cards["ja_ctc_aligner"].action.text() == "使用"
    click(panel, "qwen_aligner")  # 使用 again
    assert win.firered_asr_backend.currentData() == "qwen_aligner"
    assert card.model_label.text() == "Qwen3 对齐"
    assert panel.current_badge.text() == "当前：Qwen3 对齐"
    # 2026-10-18 (home layout A): the line under the name describes the model.
    assert card.description_label.text() == "11 种语言 · 字/词级对齐"
    assert win.legacy.RUNTIME_SETTINGS["switches"]["use_ja_ctc_aligner"] is False  # unchanged
    win._modal_host._request_close()
    from twobyteasr.storage.settings import load_runtime_settings
    assert load_runtime_settings()[0]["models"]["firered_asr_backend"] == "qwen_aligner"


def test_ctc_switch_shows_in_the_picker_as_on_the_home_card(window):
    win = window
    win.legacy.RUNTIME_SETTINGS["switches"]["use_ja_ctc_aligner"] = True
    win._timeline_helper_changed()  # what the CTC card's switch emits
    speak(win, "ja")
    card = win.recognition_plan.cards["timeline"]
    assert card.model_label.text() == "Qwen3 对齐 + 日语 CTC"
    panel = picker(win)
    assert panel.current_badge.text() == "当前：Qwen3 对齐 + 日语 CTC"
    assert "句首再由日语 CTC 对齐模型校正" in panel.language_note.text()
    assert panel.cards["ja_ctc_aligner"].action.text() == "取消使用"
    win._modal_host._request_close()


def test_chinese_and_english_follow_the_spoken_language(window):
    win = window
    speak(win, "ja")
    panel = picker(win)
    win._modal_host._request_close()
    speak(win, "zh")
    card = win.recognition_plan.cards["timeline"]
    assert card.model_label.text() == "FireRedASR2-AED"
    assert card.description_label.text() == "中英 · 20+ 种方言口音 · 识别并给出字词时间"
    panel = picker(win)
    assert panel.current_badge.text() == "当前：FireRedASR2-AED"
    assert panel.cards["firered"].property("selected")
    assert panel.cards["firered"].action.text() == "取消使用"
    assert not panel.language_note.isVisibleTo(panel)
    win._modal_host._request_close()
    speak(win, "en")
    assert card.model_label.text() == "Qwen3 对齐"
    assert card.description_label.text() == "字幕语言是英语，FireRedASR2-AED 只用于中文"
    panel = picker(win)
    assert panel.cards["firered"].action.text() == "英语时不使用"
    assert "不用于英语" in panel.language_note.text()
    win._modal_host._request_close()


def test_pre_run_summary_names_the_aligner_for_japanese():
    from twobyteasr.recognition.recognition_choices import disclosure_text, run_disclosure
    settings = {"models": {"primary_asr_backend": "moss", "firered_asr_backend": "local",
                           "qwen_asr_backend": "off"},
                "switches": {"use_ja_ctc_aligner": False},
                "subtitle_language": {"recognition_language": "ja"}}
    info = run_disclosure(settings)
    assert info["timestamps"].startswith("本地 Qwen3 对齐模型")
    assert "FireRed" not in info["local"]
    assert "所选 FireRedASR2-AED 只用于中文" in disclosure_text(settings)
    settings["subtitle_language"]["recognition_language"] = "zh"
    assert run_disclosure(settings)["timestamps"].startswith("FireRed 字级时间轴")
    assert "只用于中文" not in disclosure_text(settings)
