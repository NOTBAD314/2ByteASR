# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in QA (``TWOBYTEASR_ACCEPTANCE_SCENARIO=update-flow``): the real update flow.

Clicks the real "检查更新" button against a QA feed (``TWOBYTEASR_UPDATE_FEED``,
channel ``TWOBYTEASR_UPDATE_CHANNEL``), records the offer dialog, downloads and
stages the update, and accepts "退出并更新".  ``UPDATE_FLOW_PLAN`` (JSON) can
add a simulated busy recognition worker (the update must refuse) and an
unsaved Studio project (first "Cancel" at the save prompt, then "Save").

After the updater restarted the program, the same scenario sees the expected
new version (``UPDATE_FLOW_EXPECT``), checks once more ("already latest") and
closes normally.  Results: ``<acceptance dir>/update-flow-<version>.json``.

The dialogs run nested event loops, so the audit is a non-blocking state
machine driven by a repeating timer; every click is deferred with
``QTimer.singleShot(0, ...)``.  Ordinary sessions never import this module.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path


def start(window, output: Path) -> None:
    from PySide6.QtCore import QThread, QTimer
    from PySide6.QtGui import QUndoCommand
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPlainTextEdit, QPushButton
    from .updater import current_version, last_result

    plan = json.loads(os.environ.get("UPDATE_FLOW_PLAN") or "{}")
    version = current_version()
    expect = os.environ.get("UPDATE_FLOW_EXPECT", "")
    result = {"scenario": "update-flow", "version": version, "pid": os.getpid(), "started": time.time(),
              "plan": plan, "steps": [], "status": "RUNNING", "last_helper_result": last_result(),
              "confirm_env_present_at_start": "TWOBYTEASR_UPDATE_CONFIRM" in os.environ}
    target = Path(output) / f"update-flow-{version}.json"
    state = {"name": "begin", "since": time.monotonic(), "busy": None, "saved": False, "cancelled": False}

    def save():
        target.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")

    def step(name, **data):
        result["steps"].append({"name": name, "t": round(time.time() - result["started"], 3), **data})
        save()

    def goto(name):
        state["name"], state["since"] = name, time.monotonic()

    pending_timers = []

    def later(action, delay=20):
        # Static QTimer.singleShot calls made inside a dialog's nested event
        # loop are not delivered with this PySide/Qt; timer instances are.
        deferred = QTimer(window)
        deferred.setSingleShot(True)
        deferred.timeout.connect(action)
        deferred.start(delay)
        pending_timers.append(deferred)

    def finish(status, error=None, close=True):
        result["status"] = status
        if error:
            result["error"] = error
        result["finished"] = time.time()
        save()
        goto("done")
        timer.stop()
        if close:
            later(window.close, 300)
        if os.environ.get("UPDATE_FLOW_DEBUG") == "1":
            def watch(count=[0]):
                count[0] += 1
                visible = [(type(w).__name__, w.windowTitle()) for w in QApplication.topLevelWidgets() if w.isVisible()]
                result.setdefault("debug_after_finish", []).append({"tick": count[0], "visible": visible,
                    "modal": type(QApplication.activeModalWidget()).__name__})
                save()
                if count[0] < 20:
                    later(watch, 1000)
            later(watch, 100)

    def modal(kind):
        widget = QApplication.activeModalWidget()
        return widget if isinstance(widget, kind) and widget.isVisible() else None

    def texts(widget):
        parts = [w.text() for w in widget.findChildren(QLabel)]
        parts += [w.toPlainText() for w in widget.findChildren(QPlainTextEdit)]
        if isinstance(widget, QMessageBox):
            parts += [widget.windowTitle(), widget.text(), widget.informativeText()]
        return "\n".join(p for p in parts if p)

    def press(box, standard):
        button = box.button(standard)
        if button is None:
            raise AssertionError(f"{box.windowTitle()} has no {standard}")
        later(button.click)

    def click_update():
        later(window.update_button.click)

    class BusyWorker(QThread):
        # Stands in for a running recognition worker. time.sleep releases the
        # GIL; QThread.msleep would hold it and starve the GUI thread.
        def run(self):
            while not self.isInterruptionRequested():
                time.sleep(0.05)

    def offer_dialog():
        from .ui import UpdateOfferDialog
        return modal(UpdateOfferDialog)

    def tick():
        try:
            name = state["name"]
            waited = time.monotonic() - state["since"]
            if os.environ.get("UPDATE_FLOW_DEBUG") == "1" and len(result.setdefault("debug_ticks", [])) < 200:
                active = QApplication.activeModalWidget()
                result["debug_ticks"].append([round(time.time() - result["started"], 2), name,
                                              type(active).__name__, active.windowTitle() if active else ""])
            if name == "done":
                return
            if waited > plan.get("step_timeout", 1800):
                raise TimeoutError(f"state {name} timed out")
            if name == "begin":
                if expect and version == expect:
                    step("post_update_started", confirm_env_cleared="TWOBYTEASR_UPDATE_CONFIRM" not in os.environ)
                    goto("post_check")
                    click_update()
                elif plan.get("dirty_project"):
                    goto("opening")
                    later(lambda: window.open_studio_project(os.environ["TWOBYTEASR_STARTUP_PROJECT"],
                                                             mode="edit", source="update_audit"))
                else:
                    goto("await_offer")
                    click_update()
            elif name == "post_check":
                box = modal(QMessageBox)
                if box:
                    info = texts(box)
                    step("post_update_check", text=info)
                    press(box, QMessageBox.StandardButton.Ok)
                    finish("PASS" if ("最新" in info and version in info) else "FAIL")
            elif name == "opening":
                studio = window.built_page("studio")
                if studio is not None and getattr(studio, "project", None) is not None and waited > 2:
                    studio.undo_stack.push(QUndoCommand("qa unsaved change"))
                    step("dirty_project", dirty=studio.project_controller.dirty_guard.is_dirty())
                    goto("await_offer")
                    click_update()
            elif name == "await_offer":
                dialog = offer_dialog()
                if dialog:
                    dialog.grab().save(str(Path(output) / f"update-offer-{version}.png"))
                    step("offer_shown", text=texts(dialog))
                    button = next(b for b in dialog.findChildren(QPushButton) if b.text() == "下载并准备更新")
                    goto("await_prepared")
                    state["download_started"] = time.monotonic()
                    later(button.click)
                elif modal(QMessageBox):
                    box = modal(QMessageBox)
                    step("unexpected_message", text=texts(box))
                    press(box, QMessageBox.StandardButton.Ok) if box.button(QMessageBox.StandardButton.Ok) else later(box.reject)
                    finish("FAIL", "no update offer")
            elif name == "await_prepared":
                box = modal(QMessageBox)
                if box:
                    prepared = getattr(window, "_prepared_update", None)
                    step("download_finished", seconds=round(time.monotonic() - state["download_started"], 3),
                         text=texts(box), prepared=prepared.record if prepared else None)
                    if prepared is None:
                        state["failure_box"] = box
                        goto("after_failure")
                        press(box, QMessageBox.StandardButton.Ok)
                        return
                    if plan.get("busy_worker"):
                        busy = BusyWorker(window)
                        busy.start()
                        state["busy"], state["previous_worker"] = busy, window.worker
                        window.worker = busy
                        goto("await_busy_refusal")
                    elif plan.get("dirty_project"):
                        goto("await_save_prompt")
                    else:
                        goto("handing_off")
                    press(box, QMessageBox.StandardButton.Yes)
            elif name == "after_failure":
                # The user pressed OK: the program must stay usable (no stuck dialog) before it is closed.
                box = modal(QMessageBox)
                if box is None and waited > 1.0:
                    step("failure_dismissed", window_visible=window.isVisible(),
                         button_text=window.update_button.text(), button_enabled=window.update_button.isEnabled())
                    finish("PASS_EXPECTED_FAILURE" if plan.get("expect_download_failure") else "FAIL")
                elif box is not None and waited > 5.0:
                    step("failure_box_did_not_close", text=texts(box))
                    finish("FAIL", "failure message box did not close after OK", close=False)
            elif name == "await_busy_refusal":
                box = modal(QMessageBox)
                if box and box.windowTitle() != "更新已准备好":
                    step("busy_refused", text=texts(box))
                    press(box, QMessageBox.StandardButton.Ok)
                    goto("after_busy")
            elif name == "after_busy":
                if modal(QMessageBox) is None and waited > 0.5:
                    busy = state["busy"]
                    busy.requestInterruption()
                    busy.wait(3000)
                    window.worker = state.get("previous_worker")
                    step("busy_cleared", window_visible=window.isVisible(),
                         pending=getattr(window, "_pending_update", None) is not None)
                    goto("await_reprompt")
                    click_update()
            elif name == "await_reprompt":
                box = modal(QMessageBox)
                if box:
                    step("reprompt", text=texts(box))
                    goto("await_save_prompt" if plan.get("dirty_project") else "handing_off")
                    press(box, QMessageBox.StandardButton.Yes)
            elif name == "await_save_prompt":
                box = modal(QMessageBox)
                if box and box.button(QMessageBox.StandardButton.Save) is not None:
                    if not state["cancelled"]:
                        state["cancelled"] = True
                        step("save_prompt_cancel", text=texts(box))
                        goto("after_cancel")
                        press(box, QMessageBox.StandardButton.Cancel)
                    else:
                        step("save_prompt_save", text=texts(box))
                        goto("handing_off")
                        press(box, QMessageBox.StandardButton.Save)
            elif name == "after_cancel":
                if modal(QMessageBox) is None and waited > 1:
                    step("cancel_kept_program", window_visible=window.isVisible(),
                         pending=getattr(window, "_pending_update", None) is not None,
                         prepared_kept=getattr(window, "_prepared_update", None) is not None)
                    goto("await_reprompt")
                    click_update()
            elif name == "handing_off":
                if not window.isVisible() or getattr(window, "_pending_update", None) is not None:
                    step("handed_to_updater", pending=getattr(window, "_pending_update", None) is not None)
                    finish("HANDED_OFF", close=False)
        except Exception:
            finish("FAIL", traceback.format_exc())

    if os.environ.get("UPDATE_FLOW_DEBUG") == "1":
        for method in ("_update_download_failed", "_update_check_failed", "_update_check_finished",
                       "_set_update_idle", "_download_update"):
            original = getattr(window, method)

            def traced(*a, _name=method, _original=original):
                result.setdefault("debug_calls", []).append({"call": _name, "t": round(time.time() - result["started"], 3)})
                save()
                return _original(*a)
            setattr(window, method, traced)

    timer = QTimer(window)
    timer.setInterval(200)
    timer.timeout.connect(tick)
    save()
    QTimer.singleShot(1500, window, timer.start)
