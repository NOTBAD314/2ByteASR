"""Timeline picker and home card name the same model for the spoken language (2026-10-18).

Opt-in source/frozen UI check on a private desktop; model readiness is a
fixture (no recognition runs). Replays the user's report: FireRed chosen while
home 字幕语言 is 日语, cancel and use again, the 日语 CTC card, then Chinese.
"""
import json
import os
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from ..app import ui
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..local_models import model_workshop as workshop
    from ..local_models.model_registry import ModelRegistry
    from ..recognition import asr, ctc_alignment
    from ..storage.settings import load_runtime_settings
    from .blank_project_audit import _capture

    theme = os.environ.get("TWOBYTEASR_TIMELINE_AUDIT_THEME", "grape")
    output = Path(output)
    result = dict(passed=False, checks=[], theme=theme, steps=[], identity=load_build_identity().to_dict(),
                  model_readiness="fixture", pid=os.getpid())
    installed = {"qwen_aligner", "ja_ctc_aligner", "firered_aed", "qwen_asr"}
    originals = []

    def patch(owner, name, value):
        originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def check(name, value, detail=None):
        result["checks"].append(dict(name=name, passed=bool(value), detail=detail))

    def save():
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")

    card = None

    def panel():
        return window.__dict__.get("_model_picker_timeline_panel")

    def record(step):
        picker = panel()
        open_ = bool(picker is not None and picker.isVisible())
        row = dict(step=step, home=card.model_label.text(), note=card.description_label.text(),
                   badge=card.status_badge.text(), timeline=str(window.firered_asr_backend.currentData()),
                   ctc=window.legacy.RUNTIME_SETTINGS.get("switches", {}).get("use_ja_ctc_aligner"))
        if open_:
            row.update(current=picker.current_badge.text(), language_note=picker.language_note.text()
                       if picker.language_note.isVisible() else "",
                       buttons={key: [picker.cards[key].action.text(), picker.cards[key].action.isEnabled(),
                                      bool(picker.cards[key].property("selected"))]
                                for key in ("firered", "qwen_aligner", "ja_ctc_aligner") if key in picker.cards})
            # The picker's 当前 names exactly what the home card names.
            check(step + ": picker current == home card",
                  row["current"] == "当前：" + row["home"] or (row["home"] == "已关闭" and row["current"] == "当前：尚未选择"),
                  [row["current"], row["home"]])
        result["steps"].append(row)
        return row

    def shot(name):
        QTest.qWait(450)
        _capture(window, output / (name + ".png"))
        result.setdefault("screenshots", []).append(name + ".png")

    def click(widget):
        picker = panel()
        if picker is not None and widget is not None and picker.isAncestorOf(widget):
            picker.scroll.ensureWidgetVisible(widget)
            QTest.qWait(120)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        QTest.qWait(250)

    def open_picker():
        click(card)  # the real home card opens 选择字幕时间轴模型
        QTest.qWait(600)
        check("picker opened from home card", panel() is not None and panel().isVisible())

    def close_picker():
        done = next(button for button in panel().findChildren(QPushButton) if button.text() == "完成")
        click(done)
        QTest.qWait(600)

    def run():
        nonlocal card
        try:
            check("Windows runtime", os.name == "nt")
            apply_theme(theme)
            window._switch_page(window.settings_scroll)
            window.showNormal()
            window.resize(1500, 960)
            patch(ModelRegistry, "installed_keys", lambda self: set(installed))
            patch(ui, "installed_model_keys", lambda root: set(installed))
            patch(workshop, "_readiness_status", lambda key: "PASS")
            patch(ctc_alignment, "model_dir", lambda: "fixture-ctc")
            patch(asr, "resolve_qwen_aligner_local_source", lambda: "fixture-qwen")
            window.legacy.RUNTIME_SETTINGS.setdefault("switches", {})["use_ja_ctc_aligner"] = False
            window._refresh_available_asr_choices()
            for combo, value in ((window.primary_asr_backend, "none"), (window.qwen_asr_backend, "local"),
                                 (window.firered_asr_backend, "local")):
                combo.setCurrentIndex(combo.findData(value))
            check("isolated configuration saved", window._save_asr_configuration(show_feedback=False))
            card = window.recognition_plan.cards["timeline"]
            # The user's state: FireRed chosen, home 字幕语言 = 日语.
            window.recognition_language.setCurrentIndex(window.recognition_language.findData("ja"))
            QTest.qWait(200)
            row = record("home ja firered")
            check("home names what runs for Japanese", row["home"] == "Qwen3 对齐")
            check("home says FireRed is for Chinese", "FireRedASR2-AED 只用于中文" in row["note"], row["note"])
            shot("01-home-ja-firered")
            open_picker()
            row = record("picker ja firered")
            check("picker current is the aligner", row["current"] == "当前：Qwen3 对齐")
            check("FireRed cannot be chosen for Japanese", row["buttons"]["firered"][:2] == ["日语时不使用", False])
            check("aligner card is the selected one", row["buttons"]["qwen_aligner"] == ["取消使用", True, True])
            check("picker explains and says how to change", "改成中文或自动识别" in row["language_note"])
            shot("02-picker-ja-firered")
            click(panel().cards["qwen_aligner"].action)  # 取消使用
            row = record("picker ja cancel")
            check("cancel switches the timeline off", row["timeline"] == "off" and row["home"] == "已关闭")
            check("CTC switch untouched by cancel", row["ctc"] is False)
            shot("03-picker-ja-off")
            click(panel().cards["qwen_aligner"].action)  # 使用 again
            row = record("picker ja use again")
            check("use again turns the aligner on", row["timeline"] == "qwen_aligner" and row["home"] == "Qwen3 对齐")
            check("CTC switch untouched by use again", row["ctc"] is False)
            click(panel().cards["qwen_aligner"].action)  # off again, then the 日语 CTC card's 使用
            click(panel().cards["ja_ctc_aligner"].action)
            row = record("picker ja ctc use")
            check("CTC 使用 turns CTC and the aligner on",
                  row["ctc"] is True and row["timeline"] == "qwen_aligner" and row["home"] == "Qwen3 对齐 + 日语 CTC")
            check("picker note mentions CTC", "日语 CTC" in row["language_note"])
            shot("04-picker-ja-ctc")
            close_picker()
            row = record("home ja ctc")
            check("home after 完成 keeps the same name", row["home"] == "Qwen3 对齐 + 日语 CTC")
            shot("05-home-ja-ctc")
            window.recognition_language.setCurrentIndex(window.recognition_language.findData("zh"))
            QTest.qWait(200)
            open_picker()
            click(panel().cards["firered"].action)  # Chinese: FireRed can be chosen again
            row = record("picker zh firered")
            check("Chinese uses FireRed as chosen",
                  row["timeline"] == "local" and row["home"] == "FireRedASR2-AED"
                  and row["buttons"]["firered"] == ["取消使用", True, True] and not row["language_note"])
            panel().scroll.verticalScrollBar().setValue(0)  # FireRed is pinned first
            shot("06-picker-zh-firered")
            close_picker()
            row = record("home zh firered")
            # 2026-10-18 (home layout A): the line under the name describes the model.
            check("home default description back", row["note"] == "中英 · 20+ 种方言口音 · 识别并给出字词时间")
            shot("07-home-zh-firered")
            saved = load_runtime_settings()[0]
            check("saved choice", saved["models"]["firered_asr_backend"] == "local"
                  and saved["subtitle_language"]["recognition_language"] == "zh", saved["models"]["firered_asr_backend"])
            result["passed"] = all(item["passed"] for item in result["checks"])
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
