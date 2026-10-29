"""Opt-in real-window check of the 2026-10-18 workbench fixes (scenario ``workbench-fixes``).

Driver: scripts/verify_workbench_fixes_headed.py (source, or ``--exe`` for a frozen candidate). The
runner prepares a 24-caption project with a long name, overlapping captions and a layout saved with
both side panels hidden at 0 px. Checks, with screenshots in the output folder:

* 6  应用设置: browsing every page and closing asks nothing;
* 7  both side panels open, with their default widths;
* 14 no toolbar widget overlaps another at 1100-2100 px; the name never runs under the home icon;
* 5  a real Ctrl+wheel message over the timeline zooms only the timeline; elsewhere nothing zooms;
* 13 the 跳转 box follows 上一条 / 下一条 and selections;
* 12 the 调整 menu: four everyday entries + 更多; one-click re-layout is one undo step;
* 11 no divider column inside 保存当前帧;
* 9  the drawer shortcut panel: × at the top, the entry closes it, changed keys ask first.

Nothing here contacts the network or AI services.
"""
import ctypes
import json
import os
import sys
import time
import traceback
from ctypes import wintypes as W
from pathlib import Path


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", W.HWND), ("message", W.UINT), ("wParam", W.WPARAM), ("lParam", W.LPARAM),
                ("time", W.DWORD), ("pt", W.POINT)]


def _physical_point(window, global_point):
    rect = W.RECT()
    ctypes.windll.user32.GetWindowRect(W.HWND(int(window.winId())), ctypes.byref(rect))
    frame = window.frameGeometry()
    ratio = window.devicePixelRatioF() or 1.0
    return (rect.left + round((global_point.x() - frame.x()) * ratio),
            rect.top + round((global_point.y() - frame.y()) * ratio))


def _set_ctrl(down):
    """Qt reads modifiers from the thread's key state, not from the message."""
    state = (ctypes.c_ubyte * 256)()
    ctypes.windll.user32.GetKeyboardState(state)
    for key in (0x11, 0xA2):  # VK_CONTROL, VK_LCONTROL
        state[key] = 0x80 if down else 0
    ctypes.windll.user32.SetKeyboardState(state)


def _wheel_message(widget, local, delta=120):
    window = widget.window()
    x, y = _physical_point(window, widget.mapToGlobal(local))
    return int(window.winId()), ((delta & 0xFFFF) << 16) | 0x0008, ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def _post_ctrl_wheel(widget, local):
    hwnd, wparam, lparam = _wheel_message(widget, local)
    _set_ctrl(True)
    ctypes.windll.user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    return bool(ctypes.windll.user32.PostMessageW(W.HWND(hwnd), 0x020A, wparam, lparam))


def _interface_zoom_takes(widget, local):
    """Whether the interface-zoom filter would take a Ctrl+wheel at this point (no zoom happens)."""
    from PySide6.QtWidgets import QApplication
    controller = getattr(QApplication.instance(), "_ui_zoom_controller", None)
    if controller is None or not hasattr(controller, "_native"):
        return False
    hwnd, wparam, lparam = _wheel_message(widget, local)
    message = _MSG()
    message.hwnd, message.message, message.wParam, message.lParam = hwnd, 0x020A, wparam, lparam
    calls = []
    original = controller.wheel
    controller.wheel = calls.append
    try:
        consumed, _ = controller._native.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(message))
    finally:
        controller.wheel = original
    return bool(consumed or calls)


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QRect, QTimer
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
    from ..diagnostics.build_identity import load_build_identity

    app = QApplication.instance()
    output = Path(output)
    theme = os.environ.get("TWOBYTEASR_WORKBENCH_AUDIT_THEME", "grape")

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {"passed": False, "identity": load_build_identity().to_dict(), "checks": [],
                           "pid": os.getpid(), "executable": sys.executable, "screenshots": [], "theme": theme,
                           "values": {}}
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
            self.busy = True  # a modal dialog's own loop also runs this timer
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
            path = output / f"{name}.png"
            widget.grab().save(str(path))
            self.result["screenshots"].append(str(path))

        @staticmethod
        def message_box():
            return next((w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()),
                        None)

        def answer_box(self, button, record, name, timeout=3.0):
            """Answer the next question box from a timer: it runs in the box's own loop.
            Gives up after ``timeout`` s, so a box that never came cannot catch a later one."""
            deadline = time.monotonic() + timeout

            def watch():
                box = self.message_box()
                if box is None:
                    if time.monotonic() < deadline:
                        QTimer.singleShot(100, watch)
                    return
                record.append(box.text())
                self.shot(box, name)
                (box.button(button) or box.buttons()[-1]).click()
            QTimer.singleShot(200, watch)

        # ---------------------------------------------------------------- run
        def run(self):
            yield 1.0
            from ..design.theme_manager import apply_theme
            apply_theme(theme)
            window.showNormal()
            window.resize(1700, 1000)
            yield 1.0
            yield from self.settings()
            page = yield from self.open_studio()
            if page is None:
                return
            yield from self.panels(page)
            yield from self.toolbar(page)
            yield from self.wheel(page)
            yield from self.jump(page)
            yield from self.adjust_menu(page)
            yield from self.save_frame(page)
            yield from self.shortcut_panel(page)

        def settings(self):
            QTimer.singleShot(0, window._open_application_settings)  # modal: its loop keeps ticking us
            dialog = None
            for _ in range(40):
                yield .2
                dialog = next((w for w in QApplication.topLevelWidgets()
                               if type(w).__name__ == "ApplicationSettingsDialog" and w.isVisible()), None)
                if dialog is not None:
                    break
            self.check("6 settings dialog opened", dialog is not None)
            if dialog is None:
                return
            same = [["open", dialog._values() == dialog._saved_values]]
            for row in range(dialog.navigation.count()):
                dialog.navigation.setCurrentRow(row)
                yield .6
                same.append([row, dialog._values() == dialog._saved_values])
            yield 2.0  # the MCP page refreshes every second
            same.append(["after 2 s", dialog._values() == dialog._saved_values])
            asked = []
            self.answer_box(QMessageBox.StandardButton.Discard, asked, "settings-asked")
            dialog.reject()
            yield 1.0
            self.result["values"]["settings"] = same
            self.check("6 browsing every settings page and closing asks nothing",
                       not asked and all(value for _, value in same), [asked, same])

        def open_studio(self):
            window.open_studio_project(os.environ.get("TWOBYTEASR_STARTUP_PROJECT", ""))
            deadline = time.monotonic() + 40
            page = None
            while time.monotonic() < deadline:
                page = window.built_page("studio")
                if page is not None and page.project is not None and \
                        getattr(page.video, "_startup_state", "") == "READY":
                    break
                yield .3
            self.check("studio opened", page is not None and page.project is not None,
                       getattr(getattr(page, "video", None), "_startup_state", None))
            if page is None or page.project is None:
                return None
            yield 2.0
            page.volume_slider.setValue(0)
            page.video.set_paused(True)
            page._sync_play_button(True)
            # A private desktop never composites the first frame the 准备字幕 card waits for.
            loading = [w for w in window.findChildren(QWidget, "studioLoadingSurface") if w.isVisible()]
            self.result["values"]["loading_card_hidden_by_audit"] = bool(loading)
            for surface in loading:
                surface.hide()
            yield .5
            return page

        def panels(self, page):
            values = {"cue_list_visible": page.cue_list_panel.isVisible(),
                      "context_visible": page.context_panel.isVisible(),
                      "upper_sizes": page.upper_splitter.sizes(), "cue_list_width": page.cue_list_panel.width(),
                      "context_width": page.context_panel.width()}
            self.result["values"]["panels_on_open"] = values
            self.check("7 both side panels open over a layout saved hidden at 0 px",
                       values["cue_list_visible"] and values["context_visible"]
                       and values["cue_list_width"] >= 250 and values["context_width"] >= 300, values)
            self.check("7 字幕列表 / 工具面板 show them as open",
                       page.cue_list_toggle_button.isChecked() and page.context_expand_button.isChecked())
            self.shot(window, "01-studio-open")
            yield .2

        def toolbar(self, page):
            rows = []
            for width in (1100, 1280, 1440, 1700, 2100):
                window.resize(width, 1000)
                yield 1.0
                bar = page.studio_toolbar
                layout = bar.layout()
                widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
                widgets = [w for w in widgets if w is not None and w.isVisible() and w.width() > 0]
                rects = [(f"{type(w).__name__}:{w.objectName()}:{w.text() if hasattr(w, 'text') else ''}",
                          QRect(w.mapTo(bar, QPoint(0, 0)), w.size())) for w in widgets]
                overlaps = [[a, b] for i, (a, ra) in enumerate(rects) for b, rb in rects[i + 1:]
                            if ra.intersects(rb)]
                kinds = [w.objectName() == "toolbarDivider" for w in widgets]
                name_end = page.filename.mapTo(bar, QPoint(page.filename.width(), 0)).x()
                home_x = page.studio_home_button.mapTo(bar, QPoint(0, 0)).x()
                rows.append({"width": width, "actual": window.width(), "overlaps": overlaps,
                             "adjacent_dividers": any(a and b for a, b in zip(kinds, kinds[1:])),
                             "name_gap": home_x - name_end, "save_state": page.save_state.isVisible(),
                             "collapsed": [w.text() for w in getattr(page, "_studio_toolbar_collapsed", ())]})
                self.shot(bar, f"02-toolbar-{width}")
            self.result["values"]["toolbar"] = rows
            self.check("14 no toolbar widgets overlap at 1100-2100 px", all(not r["overlaps"] for r in rows),
                       [r["overlaps"] for r in rows])
            self.check("14 the name never runs under the home icon", all(r["name_gap"] >= 0 for r in rows),
                       [r["name_gap"] for r in rows])
            self.check("14 no empty group leaves two dividers side by side",
                       not any(r["adjacent_dividers"] for r in rows))
            window.resize(1700, 1000)
            yield 1.0

        def wheel(self, page):
            from ..app import ui_zoom
            controller = getattr(app, "_ui_zoom_controller", None)
            points = [
                ("timeline", page.timeline, QPoint(page.timeline.width() // 2, page.timeline.height() // 2)),
                ("timeline_header", page.timeline, QPoint(30, page.timeline.height() // 2)),
                ("cue_list", page.cue_table.viewport(), QPoint(40, 40)),
                ("video", page.video, QPoint(page.video.width() // 2, page.video.height() // 2)),
                ("tool_panel", page.context_drawer, QPoint(80, 200)),
                ("toolbar", page.studio_toolbar, QPoint(page.studio_toolbar.width() // 2, 10)),
            ]
            rows = {}
            for name, widget, local in points:
                takes = _interface_zoom_takes(widget, local)
                before = (page.timeline.visible_duration_ms, ui_zoom.zoom_percent())
                posted = _post_ctrl_wheel(widget, local)
                yield .7
                _set_ctrl(False)
                toast = getattr(controller, "_toast", None)
                rows[name] = {"filter_takes": takes, "posted": posted,
                              "timeline_zoomed": page.timeline.visible_duration_ms != before[0],
                              "ui_zoomed": (ui_zoom.zoom_percent() != before[1]
                                            or getattr(controller, "_pending", None) is not None
                                            or bool(toast and toast.isVisible()))}
                if toast is not None:
                    toast.hide()
            self.result["values"]["wheel"] = rows
            self.check("5 Ctrl+wheel over the timeline zooms the timeline only",
                       rows["timeline"]["timeline_zoomed"] and not rows["timeline"]["ui_zoomed"], rows["timeline"])
            self.check("5 nowhere in the workbench does Ctrl+wheel zoom the interface",
                       not any(r["ui_zoomed"] or r["filter_takes"] for r in rows.values()), rows)

        def jump(self, page):
            page.select_cue("c03")
            yield .3
            values = [page.jump_spin.value()]
            for delta in (1, 1, -1):
                page._step_cue(delta)
                yield .4
                values.append(page.jump_spin.value())
            page.timeline.set_selected("c10")
            page.select_cue("c10")
            yield .3
            values.append(page.jump_spin.value())
            self.result["values"]["jump"] = values
            self.check("13 跳转 follows 上一条 / 下一条 and selections", values == [4, 5, 6, 5, 11], values)
            page.select_cue("c05")
            yield .3
            self.shot(page.jump_spin.parentWidget(), "03-cue-footer")

        def adjust_menu(self, page):
            menu = page.timeline_options_button.menu()
            menu.popup(page.timeline_options_button.mapToGlobal(QPoint(0, page.timeline_options_button.height())))
            yield .6
            texts = [a.text() for a in menu.actions() if not a.isSeparator()]
            more = next((a.menu() for a in menu.actions() if a.menu() is not None), None)
            more_texts = [a.text() for a in more.actions() if not a.isSeparator()] if more else []
            self.result["values"]["adjust_menu"] = [texts, more_texts]
            self.shot(menu, "04-adjust-menu")
            self.check("12 调整: four everyday entries then 更多",
                       len(texts) == 5 and texts[-1] == "更多" and not any("预览" in t for t in texts), texts)
            self.check("12 更多 keeps the previews and the measurement", len(more_texts) == 6, more_texts)
            if more is not None:
                more.popup(menu.mapToGlobal(QPoint(menu.width() - 8, menu.height() - 30)))
                yield .5
                self.shot(more, "05-adjust-more")
                more.hide()
            menu.hide()
            yield .3
            from ..studio.subtitle_layout_ui import rearrange_now
            before = page.undo_stack.count()
            transforms = {c.id: dict(c.transform) for c in page.project.cues}
            moved = rearrange_now(page, [c.id for c in page.project.cues])
            hint = page.save_state.text()
            steps = page.undo_stack.count() - before
            page.undo_stack.undo()
            yield .3
            restored = all(dict(c.transform) == transforms[c.id] for c in page.project.cues)
            self.result["values"]["relayout"] = {"moved": moved, "undo_steps": steps, "hint": hint,
                                                 "restored": restored}
            self.check("12 one-click re-layout is one undo step and undoes cleanly",
                       moved > 0 and steps == 1 and restored, self.result["values"]["relayout"])

        def save_frame(self, page):
            frame = page.save_frame_button
            self.shot(frame.parentWidget(), "06-save-frame-and-cover")
            image = frame.grab().toImage()
            ratio = image.devicePixelRatio() or 1.0
            middle = image.height() // 2
            background = image.pixelColor(int(image.width() * 0.62), 3)
            columns = []
            for x in range(int(image.width() * 0.45), int(image.width() - 6 * ratio)):
                column = [image.pixelColor(x, y) for y in range(int(middle - 8 * ratio), int(middle + 8 * ratio))]
                if all(abs(c.lightness() - column[0].lightness()) < 6 for c in column) and \
                        abs(column[0].lightness() - background.lightness()) > 12:
                    columns.append(x)
            self.result["values"]["frame_divider_columns"] = columns
            self.check("11 no divider line inside 保存当前帧", not columns, columns)
            yield .2

        def shortcut_panel(self, page):
            entry = page.studio_shortcut_entry_button
            if not entry.isVisible():  # collapsed into ⋯ on a narrow window
                window.resize(2100, 1000)
                yield 1.0
            entry.click()
            yield .6
            panel = page._shortcut_settings_panel
            close = getattr(panel, "close_button", None)
            self.check("9 the entry opens the panel", panel is not None and panel.isVisible())
            if panel is None:
                return
            top = close.mapTo(panel, QPoint(0, 0)).y() if close is not None else None
            self.check("9 the × is at the top, no scrolling", close is not None and close.isVisible() and top < 40, top)
            self.shot(window, "07-shortcut-panel")
            entry.click()  # unchanged: closes at once
            yield .5
            self.check("9 the entry closes an unchanged panel without asking",
                       page._shortcut_settings_panel is None and self.message_box() is None)
            entry.click()
            yield .6
            panel = page._shortcut_settings_panel
            panel._editors["razor_tool"].setKeySequence(QKeySequence("Shift+C"))
            yield .3
            asked = []
            self.answer_box(QMessageBox.StandardButton.Cancel, asked, "08-ask-cancel")
            entry.click()  # the question's loop runs inside
            yield .6
            self.check("9 changed keys: closing asks, 取消 keeps the panel",
                       len(asked) == 1 and page._shortcut_settings_panel is not None, asked)
            self.answer_box(QMessageBox.StandardButton.Discard, asked, "08-ask-discard")
            page._shortcut_settings_panel.close_button.click()
            yield .6
            from ..studio import shortcut_registry
            self.check("9 × with 不保存 closes and keeps the old key",
                       len(asked) == 2 and page._shortcut_settings_panel is None
                       and shortcut_registry.current_values().get("razor_tool") != "Shift+C", asked)

        def finish(self):
            self.timer.stop()
            _set_ctrl(False)
            checks = self.result["checks"]
            self.result["passed"] = bool(checks) and all(c["passed"] for c in checks) and "error" not in self.result
            path = output / "result.json"
            path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), "utf8")

            def shutdown_done():
                self.result["gui_shutdown"] = True
                path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), "utf8")

            app.aboutToQuit.connect(shutdown_done)
            page = window.built_page("studio")
            if page is not None:
                page.undo_stack.setClean()  # the audit's edits are not the user's
            window.showNormal()
            window.close()

    window._workbench_fixes_audit = Audit()
