"""Opt-in source/frozen UI checks; model readiness is an explicit fixture."""
import json
import os
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from ..app import ui
    from ..local_models import model_workshop as workshop
    from ..local_models.model_registry import ModelRegistry
    from ..recognition import asr, ctc_alignment
    from ..storage.settings import load_runtime_settings
    from ..diagnostics.build_identity import load_build_identity
    from .blank_project_audit import _capture
    from .studio_acceptance_audit import require

    result = dict(passed=False, checks=[], identity=load_build_identity().to_dict(),
                  model_readiness="fixture", pid=os.getpid())
    installed = {"qwen_aligner", "ja_ctc_aligner", "firered_aed", "qwen_asr"}
    originals = []

    def patch(owner, name, value):
        originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def check(name, value):
        result["checks"].append(dict(name=name, passed=bool(value)))
        require(value, name)

    def save():
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")

    def shot(name):
        QTest.qWait(300)
        _capture(window, output / (name + ".png"))

    def picker():
        window._open_model_picker("timeline")
        panel = window._model_picker_timeline_panel
        QTest.qWait(200)
        action = panel.cards["ja_ctc_aligner"].action
        panel.scroll.ensureWidgetVisible(action)
        QTest.qWait(150)
        check("CTC action visible", action.isVisible() and action.isEnabled())
        return panel, action

    def run():
        try:
            check("Windows runtime", os.name == "nt")
            window._switch_page(window.settings_scroll)
            window.showNormal()
            window.resize(1500, 960)
            patch(ModelRegistry, "installed_keys", lambda self: set(installed))
            patch(ui, "installed_model_keys", lambda root: set(installed))
            patch(workshop, "_readiness_status", lambda key: "PASS")
            patch(ctc_alignment, "model_dir", lambda: "fixture-ctc")
            patch(asr, "resolve_qwen_aligner_local_source", lambda: "fixture-qwen")
            window.legacy.RUNTIME_SETTINGS.setdefault("switches", {})["use_ja_ctc_aligner"] = True
            window.legacy.RUNTIME_SETTINGS["models"].update(
                primary_asr_backend="none", qwen_asr_backend="off", firered_asr_backend="off")
            window._refresh_available_asr_choices()
            for combo, value in ((window.primary_asr_backend, "none"), (window.qwen_asr_backend, "off"),
                                 (window.firered_asr_backend, "off")):
                combo.setCurrentIndex(combo.findData(value))
            check("isolated configuration saved", window._save_asr_configuration(show_feedback=False))
            window.recognition_language.setCurrentIndex(window.recognition_language.findData("ja"))
            page = window.workshop_page
            page.update_runtime_settings(window.legacy.RUNTIME_SETTINGS)
            page.refresh()
            card = window.recognition_plan.cards["timeline"]
            panel, action = picker()
            check("Windows picker excludes Apple MLX", not any(key.startswith("mlx_") for key in panel.cards))
            page._set_role("timeline")
            check("Windows workshop hides MLX", page._cards["mlx_qwen_aligner"].isHidden())
            check("Windows Qwen aligner remains", "qwen_aligner" in panel.cards)
            check("off parent shows use, not cancel", action.text() == "使用")
            check("home says timeline off", card.model_label.text() == "已关闭")
            check("off hint does not promise alignment", "不会运行" in window.subtitle_language_hint.text())
            shot("picker-off")
            QTest.mouseClick(action, Qt.MouseButton.LeftButton)
            check("CTC enables Qwen parent", window.firered_asr_backend.currentData() == "qwen_aligner")
            check("home changes before popup closes", card.model_label.text() == "Qwen3 对齐 + 日语 CTC")
            check("home is ready", "已就绪" in card.status_badge.text())
            check("hint includes CTC", "句首再由日语 CTC" in window.subtitle_language_hint.text())
            check("action becomes cancel", action.text() == "取消使用")
            window._modal_host._request_close()
            shot("ctc-on-home")
            panel, action = picker()
            QTest.mouseClick(action, Qt.MouseButton.LeftButton)
            check("cancel leaves Qwen enabled", window.firered_asr_backend.currentData() == "qwen_aligner")
            check("cancel updates home immediately", card.model_label.text() == "Qwen3 对齐")
            check("cancel removes CTC hint", "CTC" not in window.subtitle_language_hint.text())
            window._modal_host._request_close()
            shot("ctc-off-home")
            saved = load_runtime_settings()[0]
            check("Qwen parent persists", saved["models"]["firered_asr_backend"] == "qwen_aligner")
            check("CTC off persists", saved["switches"]["use_ja_ctc_aligner"] is False)
            for language, expected in (("en", "Qwen3 对齐"), ("zh", "Aligner")):
                window.recognition_language.setCurrentIndex(window.recognition_language.findData(language))
                check(language + " home model", card.model_label.text() == expected)
            window.recognition_language.setCurrentIndex(window.recognition_language.findData("ja"))
            window._apply_workshop_backend("firered", "off")
            installed.remove("qwen_aligner")
            page.refresh()
            messages = []
            patch(QMessageBox, "information", lambda *args: messages.append(args[2]))
            panel, action = picker()
            QTest.mouseClick(action, Qt.MouseButton.LeftButton)
            check("missing parent explains dependency", bool(messages) and "Qwen3-ForcedAligner" in messages[0])
            check("missing parent stays off", window.firered_asr_backend.currentData() == "off")
            check("missing parent does not claim CTC active", action.text() == "使用")
            window._modal_host._request_close()
            result["passed"] = True
        except Exception:
            result["error"] = traceback.format_exc()
        finally:
            for owner, name, value in reversed(originals):
                setattr(owner, name, value)
            save()
            window.close()
            QTimer.singleShot(500, QApplication.instance().quit)

    def shutdown():
        result["gui_shutdown"] = True
        save()

    QApplication.instance().aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run)
