"""User-visible platform choices and the CTC/parent timeline switch contract."""
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox

from twobyteasr.local_models import model_workshop as workshop

APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def window(monkeypatch):
    import subtitle_core as legacy
    from twobyteasr.app import ui
    from twobyteasr.local_models.model_registry import ModelRegistry
    from twobyteasr.recognition import ctc_alignment

    if os.environ.get("TIMELINE_MODEL_SCREENSHOTS"):
        APP.setStyle("Fusion")
        ui.apply_application_theme(APP, "grape")
        APP.setFont(ui._app_font())

    installed = {"qwen_aligner", "ja_ctc_aligner", "firered_aed", "qwen_asr"}
    monkeypatch.setattr(ModelRegistry, "installed_keys", lambda self: set(installed))
    monkeypatch.setattr(ui, "installed_model_keys", lambda root: set(installed))
    monkeypatch.setattr(workshop, "_readiness_status", lambda key: "PASS")
    monkeypatch.setattr(workshop, "_host_platform_tag", lambda: "win32-x86_64")
    monkeypatch.setattr(ctc_alignment, "model_dir", lambda: "fixture-ctc")
    monkeypatch.setitem(legacy.RUNTIME_SETTINGS, "models", {
        **legacy.RUNTIME_SETTINGS.get("models", {}),
        "primary_asr_backend": "none", "qwen_asr_backend": "off", "firered_asr_backend": "off",
    })
    monkeypatch.setitem(legacy.RUNTIME_SETTINGS, "switches", {
        **legacy.RUNTIME_SETTINGS.get("switches", {}), "use_ja_ctc_aligner": True,
    })
    win = ui.MainWindow([], legacy, object(), None)
    win.recognition_language.setCurrentIndex(win.recognition_language.findData("ja"))
    yield win, installed
    win.close()
    win.deleteLater()
    APP.processEvents()


def screenshot(win, name):
    folder = os.environ.get("TIMELINE_MODEL_SCREENSHOTS")
    if folder:
        win.show()
        win.resize(1440, 1000)
        QTest.qWait(350)
        path = Path(folder) / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        assert win.grab().save(str(path))


def test_windows_picker_and_workshop_hide_apple_only_models(window):
    win, _ = window
    page = win.workshop_page
    page._set_role("timeline")
    win.show()
    win._open_model_picker("timeline")
    picker = win._model_picker_timeline_panel
    assert "qwen_aligner" in picker.cards
    assert "ja_ctc_aligner" in picker.cards
    assert "mlx_qwen_aligner" not in picker.cards
    assert page._cards["mlx_qwen_aligner"].isHidden()
    assert not page._cards["qwen_aligner"].isHidden()
    picker.scroll.verticalScrollBar().setValue(picker.scroll.verticalScrollBar().maximum())
    screenshot(win, "windows-picker")
    win._modal_host._request_close()


def test_apple_silicon_keeps_mlx_and_windows_rejects_copied_weights(monkeypatch):
    from twobyteasr.app import ui
    mlx = next(m for m in workshop.MODELS if m.key == "mlx_qwen_aligner")
    monkeypatch.setattr(workshop, "_host_platform_tag", lambda: "darwin-arm64")
    assert workshop.model_platform_available(mlx)
    monkeypatch.setattr(workshop, "_host_platform_tag", lambda: "win32-x86_64")
    monkeypatch.setattr(ui, "installed_model_keys", lambda root: {"mlx_qwen_aligner", "mlx_qwen3_asr_0_6b"})
    primary, review, timeline = QComboBox(), QComboBox(), QComboBox()
    ui.populate_available_asr_choices(primary, review, timeline, {"models": {
        "primary_asr_backend": "mlx_qwen3_asr", "firered_asr_backend": "mlx_qwen_aligner"}})
    assert primary.findData("mlx_qwen3_asr") == -1
    assert timeline.findData("mlx_qwen_aligner") == -1
    assert timeline.currentData() == "off"


def test_ctc_use_enables_parent_and_immediately_refreshes_home(window):
    win, _ = window
    page = win.workshop_page
    win.show()
    win._open_model_picker("timeline")
    picker = win._model_picker_timeline_panel
    action = picker.cards["ja_ctc_aligner"].action
    picker.scroll.ensureWidgetVisible(action)
    QTest.qWait(100)
    card = win.recognition_plan.cards["timeline"]
    assert action.text() == "使用"  # saved switch true, but parent stage off
    assert card.model_label.text() == "已关闭"
    assert "不会运行" in win.subtitle_language_hint.text()
    QTest.mouseClick(action, Qt.MouseButton.LeftButton)
    assert win.firered_asr_backend.currentData() == "qwen_aligner"
    assert page.runtime_settings["models"]["firered_asr_backend"] == "qwen_aligner"
    assert page.runtime_settings["switches"]["use_ja_ctc_aligner"] is True
    assert card.model_label.text() == "Qwen3 对齐 + 日语 CTC"
    assert "已就绪" in card.status_badge.text()
    assert "句首再由日语 CTC" in win.subtitle_language_hint.text()
    win._modal_host._request_close()
    screenshot(win, "ctc-on-home")
    win._open_model_picker("timeline")
    picker.scroll.ensureWidgetVisible(action)
    QTest.qWait(100)
    assert action.text() == "取消使用"
    QTest.mouseClick(action, Qt.MouseButton.LeftButton)
    assert win.firered_asr_backend.currentData() == "qwen_aligner"
    assert page.runtime_settings["switches"]["use_ja_ctc_aligner"] is False
    assert card.model_label.text() == "Qwen3 对齐"
    assert "CTC" not in win.subtitle_language_hint.text()
    win._modal_host._request_close()
    screenshot(win, "ctc-off-home")
    from twobyteasr.storage.settings import load_runtime_settings
    saved = load_runtime_settings()[0]
    assert saved["models"]["firered_asr_backend"] == "qwen_aligner"
    assert saved["switches"]["use_ja_ctc_aligner"] is False
    for language, expected in (("en", "Qwen3 对齐"), ("zh", "Aligner")):
        win.recognition_language.setCurrentIndex(win.recognition_language.findData(language))
        assert card.model_label.text() == expected
    picker.close()


def test_missing_parent_does_not_claim_ctc_is_active(window, monkeypatch):
    win, installed = window
    installed.remove("qwen_aligner")
    page = win.workshop_page
    page.refresh()
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    page._perform_action("ja_ctc_aligner", role="timeline")
    assert "Qwen3-ForcedAligner" in messages[0]
    assert win.firered_asr_backend.currentData() == "off"
    ctc = page._cards["ja_ctc_aligner"].model
    assert page._action_text(ctc, "downloaded")[0] == "使用"
    assert win.recognition_plan.cards["timeline"].model_label.text() == "已关闭"
