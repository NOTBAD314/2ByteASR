"""AI settings -> 断句提示词 in the real app (scenario ``grouping-prompt``, 2026-10-18).

Opens the AI settings dialog and the line-break prompt editor: the built-in guidance per subtitle
language, an edited Japanese guidance (custom state, fixed part shown), save into settings
``grouping_prompts``, the prompt the next task would send, reopen keeps the text, restore and save
bring the built-in back. Nothing leaves the machine.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

ADDED = "短い相づち（うん、はい）は前後の行とまとめてよい。"


def install_guards() -> None:
    import socket
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("External network prohibited in the grouping-prompt acceptance")
        return original_connect(sock, address)

    socket.socket.connect = local_only


def start(window, output):
    from PySide6.QtCore import QObject, QTimer
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..i18n import tr
    from ..storage.settings import load_runtime_settings
    from ..subtitle_rules import grouping_request as gr

    app = QApplication.instance()
    output = Path(output)
    theme = os.environ.get("TWOBYTEASR_GROUPING_PROMPT_AUDIT_THEME", "grape")

    def editor():
        return next((w for w in QApplication.topLevelWidgets()
                     if type(w).__name__ == "PromptDialog" and w.isVisible()), None)

    def saved():
        return load_runtime_settings()[0].get("grouping_prompts", {})

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {"passed": False, "identity": load_build_identity().to_dict(), "checks": [],
                           "pid": os.getpid(), "executable": sys.executable, "screenshots": [], "theme": theme}
            self.steps = self.run()
            self.wait_until = 0
            self.busy = False
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(40)

        def check(self, name, value, detail=None):
            self.result["checks"].append({"name": name, "passed": bool(value), "detail": detail})

        def tick(self):
            if self.busy or time.monotonic() < self.wait_until:
                return
            self.busy = True
            try:
                self.wait_until = time.monotonic() + next(self.steps)
            except StopIteration:
                self.finish()
            except Exception:
                self.result["error"] = traceback.format_exc()
                self.finish()
            finally:
                self.busy = False

        def shot(self, widget, name):
            path = output / f"{theme}-{name}.png"
            widget.grab().save(str(path))
            self.result["screenshots"].append(str(path))

        def run(self):
            from ..design.theme_manager import apply_theme
            apply_theme(theme)
            window.showMaximized()
            yield 1.0
            QTimer.singleShot(0, window._open_ai_settings_dialog)
            yield 1.5
            dialog = window.__dict__.get("_ai_settings_dialog")
            button = window.grouping_prompt_button
            self.check("AI 设置窗口里有「断句提示词」按钮",
                       dialog is not None and button.isVisible() and button.text() == tr("断句提示词"), button.text())
            self.shot(dialog, "1-ai-settings")
            QTimer.singleShot(0, button.click)          # modal exec; this timer keeps ticking inside it
            yield 1.5
            prompt = editor()
            self.check("打开断句提示词编辑窗", prompt is not None)
            self.check("没有自定义时显示内置说明、不能恢复",
                       prompt.state.text() == tr("内置说明") and not prompt.restore.isEnabled()
                       and prompt.editor.toPlainText() == gr.default_grouping_guidance(prompt._current),
                       dict(language=prompt._current, state=prompt.state.text()))
            self.shot(prompt, "2-editor-default")
            prompt.language.setCurrentIndex(prompt.language.findData("ja"))
            yield .4
            self.check("切到日语字幕：内置日语说明",
                       prompt.editor.toPlainText() == gr.default_grouping_guidance("ja"))
            prompt.editor.setPlainText(prompt.editor.toPlainText() + "\n" + ADDED)
            prompt.fixed_toggle.setChecked(True)
            yield .4
            fixed = prompt.fixed.toPlainText()
            self.check("改过后显示自定义说明、可以恢复",
                       prompt.state.text() == tr("自定义说明") and prompt.restore.isEnabled(), prompt.state.text())
            self.check("程序固定部分只读显示（照抄加竖线的协议、硬性上限）",
                       prompt.fixed.isVisible() and prompt.fixed.isReadOnly() and "segmented_text" in fixed
                       and "16" in fixed, fixed[-160:])
            self.shot(prompt, "3-editor-ja-custom")
            prompt.save_button.click()
            yield .8
            stored = saved()
            self.check("保存后窗口关闭，设置里是新的日语说明、中文仍为内置",
                       editor() is None and stored.get("ja", "").endswith(ADDED) and stored.get("zh") == "",
                       {k: v[-30:] for k, v in stored.items()})
            settings = load_runtime_settings()[0]
            sent = gr.compose_grouping_prompt("ja", 16, 5.0, gr.custom_grouping_guidance("ja", settings))
            self.check("下一次日语识别会发出这段说明（附硬性上限提醒），缓存键随之改变",
                       ADDED in sent and "绝对不超过16字或5.0秒" in sent
                       and gr.grouping_prompt_key("ja", settings).startswith(gr.JAPANESE_GROUPING_PROMPT_VERSION + "+custom-"),
                       gr.grouping_prompt_key("ja", settings))
            QTimer.singleShot(0, button.click)
            yield 1.5
            prompt = editor()
            prompt.language.setCurrentIndex(prompt.language.findData("ja"))
            yield .4
            self.check("重新打开仍是保存的日语说明",
                       prompt.state.text() == tr("自定义说明") and prompt.editor.toPlainText().endswith(ADDED))
            self.shot(prompt, "4-reopened-ja")
            prompt.restore.click()
            yield .3
            self.check("恢复内置说明", prompt.state.text() == tr("内置说明") and not prompt.restore.isEnabled())
            prompt.save_button.click()
            yield .8
            self.check("保存恢复后设置里日语为空（内置）", editor() is None and saved().get("ja") == "", saved())
            dialog.reject()
            yield .8

        def finish(self):
            self.timer.stop()
            checks = self.result["checks"]
            self.result["passed"] = bool(checks) and all(c["passed"] for c in checks) and "error" not in self.result
            path = output / "result.json"
            path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), "utf8")

            def shutdown_done():
                self.result["gui_shutdown"] = True
                path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), "utf8")

            app.aboutToQuit.connect(shutdown_done)
            window.showNormal()
            window.close()

    window._grouping_prompt_audit = Audit()
