"""Private Qt/Win32 validation of the product visibility coordinator."""
import argparse
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import traceback


def worker(output, root_path):
    sys.path.insert(0, str(root_path))
    from PySide6.QtCore import Qt, QTimer, qVersion
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget
    from shiboken6 import delete, isValid
    from twobyteasr.design.native_visibility_commit import NativeVisibilityCommit, _Win32Visibility

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    checks, batches, stages = [], [], []

    def require(name, ok, **details):
        checks.append(dict(name=name, passed=bool(ok), **details))
        if not ok:
            raise AssertionError(name + ": " + repr(details))

    class Api(_Win32Visibility):
        def __init__(self):
            super().__init__()
            self.user.IsWindowVisible.argtypes = [W.HWND]
            self.user.IsWindowVisible.restype = W.BOOL
            self.handles = []

        def states(self):
            return {str(h): dict(own_visible=self.visible_style(h),
                                effective_visible=bool(self.user.IsWindowVisible(h)),
                                parent=self.identity(h).parent if self.identity(h) else None)
                    for h in self.handles}

        def batch(self, targets):
            row = dict(parent=targets[0][0].parent,
                       targets=[dict(hwnd=i.hwnd, visible=v) for i, v in targets],
                       filter_installed=gate._installed, before=self.states())
            batches.append(row)
            require("filter_removed_before_batch", not gate._installed)
            require("same_parent_batch", len({i.parent for i, _v in targets}) == 1)
            super().batch(targets)
            row["after"] = self.states()

    class Box(QWidget):
        def __init__(self, color, parent=None):
            super().__init__(parent)
            self.color = QColor(color)
            self.paints = 0

        def paintEvent(self, event):
            self.paints += 1
            painter = QPainter(self)
            painter.fillRect(event.rect(), self.color)

    class Root(Box):
        def closeEvent(self, event):
            gate.close()
            super().closeEvent(event)

    def native_box(color, parent, rect):
        widget = Box(color, parent)
        widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        widget.setGeometry(*rect)
        return widget

    root = Root("#393939")
    root.resize(640, 400)
    layout = QVBoxLayout(root)
    stack = QStackedWidget(root)
    layout.addWidget(stack)
    a, b = Box("#254a70"), Box("#965430")
    stack.addWidget(a)
    stack.addWidget(b)
    pa = native_box("#264338", a, (60, 40, 360, 220))
    ca = native_box("#1eb965", pa, (20, 20, 300, 150))
    pb = native_box("#4c3824", b, (60, 40, 360, 220))
    cb = native_box("#ddaf37", pb, (20, 20, 300, 150))
    api = Api()
    gate = NativeVisibilityCommit(root, _api=api)
    done, warmup = False, 0
    outcome = dict(result="RUNNING", pid=os.getpid(), qt=qVersion(), checks=checks,
                   batches=batches, stages=stages, mechanism="Qt native visibility only")

    def save_stage(name):
        stages.append(dict(name=name, result=json.loads(json.dumps(gate.last_result))))

    def finish(error=None):
        nonlocal done
        if done:
            return
        done = True
        outcome["result"] = "FAIL" if error else "PASS"
        outcome["error"] = error
        gate.close()
        if isValid(root):
            root.close()
        (output / "receipt.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
        print(json.dumps(dict(result=outcome["result"], checks=len(checks),
                             failed=[c for c in checks if not c["passed"]], error=error)), flush=True)
        app.exit(1 if error else 0)

    def paint_target(page):
        before = page.paints
        page.repaint()
        root.repaint()
        require("target_page_painted_in_scope", page.paints > before,
                before=before, after=page.paints)

    def check_state(label, widget, hwnd, qt_visible, native_visible):
        require(label, widget.isVisible() == qt_visible
                and bool(api.user.IsWindowVisible(hwnd)) == native_visible,
                qt_visible=widget.isVisible(), qt_hidden=widget.isHidden(),
                win32_visible=bool(api.user.IsWindowVisible(hwnd)),
                own_visible=api.visible_style(hwnd), parent_chain=api.states())

    def execute():
        try:
            handles = [int(x.internalWinId() or 0) for x in (pa, ca, pb, cb)]
            ha, hca, hb, hcb = handles
            api.handles = handles
            require("all_handles_naturally_created", all(handles))
            require("ordinary_pages_non_native", not a.internalWinId() and not b.internalWinId())
            require("native_child_parent_matches", api.identity(hca).parent == ha and api.identity(hcb).parent == hb)
            require("native_parents_share_stable_host", api.identity(ha).parent == api.identity(hb).parent)
            require("new_child_own_visibility_initially_hidden", not api.visible_style(hcb))
            outcome["topology"] = {str(h): vars(api.identity(h)) for h in handles}
            outcome["surface"] = root.windowHandle().surfaceType().name
            with gate.scope([pa, ca, pb, cb]):
                stack.setCurrentWidget(b)
                check_state("exit_qt_hidden_native_visible", ca, hca, False, True)
                check_state("entry_qt_visible_native_hidden", cb, hcb, True, False)
                paint_target(b)
            check_state("exit_committed", ca, hca, False, False)
            check_state("entry_committed", cb, hcb, True, True)
            top_index = next(i for i, batch in enumerate(batches)
                             if {t["hwnd"] for t in batch["targets"]} == {ha, hb})
            require("old_and_new_top_levels_switch_together",
                    {(t["hwnd"], t["visible"]) for t in batches[top_index]["targets"]} == {(ha, False), (hb, True)})
            require("old_child_hidden_last", batches[-1]["targets"] == [dict(hwnd=hca, visible=False)] and top_index < len(batches) - 1)
            before_top = batches[top_index]["before"][str(hcb)]
            require("new_child_prepared_before_parent", before_top["own_visible"])
            require("prepared_child_not_exposed_before_parent", not before_top["effective_visible"])
            require("child_show_batch_precedes_parent_if_needed",
                    all(i < top_index for i, batch in enumerate(batches)
                        if any(t["hwnd"] == hcb for t in batch["targets"])))
            save_stage("hierarchical_exit_entry")
            with gate.scope([pa, ca, pb, cb]):
                stack.setCurrentWidget(a)
                check_state("reverse_qt_visible_native_hidden", ca, hca, True, False)
                paint_target(a)
            check_state("reverse_committed", ca, hca, True, True)
            save_stage("hierarchical_reverse")
            count = len(batches)
            with gate.scope([ca]):
                ca.hide()
                with gate.scope([ca]):
                    ca.show()
                    require("nested_no_early_commit", len(batches) == count)
                paint_target(a)
            check_state("cancel_hide_final_visible", ca, hca, True, True)
            require("cancel_hide_no_native_commit", len(batches) == count)
            ca.hide()
            with gate.scope([ca]):
                ca.show()
                ca.hide()
                paint_target(a)
            check_state("cancel_show_final_hidden", ca, hca, False, False)
            ca.show()
            save_stage("nested_latest_targets")
            try:
                with gate.scope([pa, ca]):
                    pa.hide()
                    check_state("exception_pending_native_visible", ca, hca, False, True)
                    paint_target(a)
                    raise ValueError("intentional exception")
            except ValueError:
                pass
            check_state("exception_scope_committed", ca, hca, False, False)
            require("exception_parent_hidden_first", batches[-2]["targets"] == [dict(hwnd=ha, visible=False)])
            require("exception_child_hidden_second", batches[-1]["targets"] == [dict(hwnd=hca, visible=False)])
            save_stage("exception_hide")
            pa.show()
            count = len(batches)
            with gate.scope([ca]):
                ca.hide()
                delete(ca)
                require("destroyed_hwnd_invalid", api.identity(hca) is None)
            require("destroyed_hwnd_not_submitted", len(batches) == count)
            save_stage("destroy_pending")
            api.handles.remove(hca)
            replacement = native_box("#28c885", pa, (20, 20, 300, 150))
            replacement.show()
            hr = int(replacement.internalWinId() or 0)
            api.handles.append(hr)
            count = len(batches)
            with gate.scope([replacement]):
                replacement.hide()
                root.close()
            require("close_removed_filter", not gate._installed and gate._closed)
            require("close_did_not_submit", len(batches) == count)
            require("closed_child_not_visible", not api.user.IsWindowVisible(hr))
            save_stage("close_pending")
            require("no_commit_errors", all(not stage["result"].get("errors") for stage in stages))
            finish()
        except BaseException:
            finish(traceback.format_exc())

    def advance():
        nonlocal warmup
        if done:
            return
        if warmup == 0 and ca.paints:
            warmup = 1
            stack.setCurrentWidget(b)
        elif warmup == 1 and cb.paints:
            warmup = 2
            cb.hide()
            stack.setCurrentWidget(a)
            cb.show()  # Logical intent only while its ordinary page is hidden.
        elif warmup == 2 and a.isVisible() and ca.isVisible():
            execute()
            return
        QTimer.singleShot(0, advance)

    root.show()
    QTimer.singleShot(0, advance)
    QTimer.singleShot(5000, lambda: finish("natural creation/paint timeout") if not done else None)
    return app.exec()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--worker", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if args.worker:
        return worker(output, root)
    output.mkdir(parents=True, exist_ok=True)
    for name, source in (("probe.py", Path(__file__)), ("native_visibility_commit.py", root / "twobyteasr/design/native_visibility_commit.py")):
        (output / name).write_bytes(source.read_bytes())
    env = dict(os.environ)
    for key in ("QT_WIDGETS_RHI", "QSG_RHI_BACKEND", "QT_WIDGETS_RHI_BACKEND"):
        env.pop(key, None)
    env.update(QT_QPA_PLATFORM="windows", PYTHONDONTWRITEBYTECODE="1",
               TWOBYTEASR_TEST_ROOT=str(output / "profile"),
               LOCALAPPDATA=str(output / "profile/local"), APPDATA=str(output / "profile/roaming"))
    sys.path.insert(0, str(root / "scripts"))
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop([sys.executable, "-B", str(Path(__file__).resolve()),
                           "--worker", "--output", str(output)], cwd=root, env=env, output=output, timeout=20)
    print(json.dumps(dict(exit=code, output=str(output))))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
