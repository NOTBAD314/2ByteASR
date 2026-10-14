"""Dialogs and popup combos dropped in a reference cycle (2026-10-14).

Left to Python's cycle collector, a dialog was cleared wrapper by wrapper.
When the ``QWidgetItem`` wrapper of a filled sub-layout went before its
layout, Shiboken handed the item to Python, Python deleted it and the layout
deleted it again: 0xC0000374 on Windows, SIGSEGV on macOS, after all tests had
passed. Which wrapper goes first depends on the generations: a full collection
clears what is still in gen0 before what an earlier gen0 pass moved to gen1.
A heap corruption kills the interpreter, so those cases run in a child
process and assert its exit code.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import shiboken6
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.main_ui_popup import FramelessPopupCombo
from twobyteasr.widget_teardown import delete_tree_before_collection

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = """
import faulthandler, gc, threading
faulthandler.enable()
from twobyteasr.test_isolation import install
install()
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout
app = QApplication([])
from twobyteasr import mlx_backend, ui
from twobyteasr.main_ui_dialogs import SpringDialog
from twobyteasr.main_ui_popup import FramelessPopupCombo
ui.detect_cuda_runtime = lambda: None
mlx_backend.platform_supported = lambda: False


class FilledRowDialog(SpringDialog):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        gc.collect(0)  # an ordinary young pass: this dialog now sits in gen1
        row = QHBoxLayout()
        row.addWidget(QLabel("model"))
        row.addWidget(FramelessPopupCombo())
        layout.addLayout(row)  # PySide wraps row's QWidgetItems now, in gen0
"""


def _run_child(body):
    script = PRELUDE + textwrap.dedent(body) + "\nprint('survived', flush=True)\n"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0 and "survived" in result.stdout, (
        f"exit {result.returncode:#x}\n{result.stdout[-2000:]}\n{result.stderr[-6000:]}")
    return result.stdout


def test_dialog_whose_items_are_cleared_first_survives_the_collector():
    _run_child("""
        for _ in range(5):
            gc.disable()
            dialog = FilledRowDialog()
            app.processEvents()  # WindowBounds' pending singleShot pins the dialog
            del dialog
            for _ in range(3):
                gc.collect()
            gc.enable()
        assert not [w for w in app.topLevelWidgets() if isinstance(w, FilledRowDialog)]
    """)


def test_guided_setup_dialogs_survive_varied_collection_orders():
    # Each threshold moves the last young pass to a different point of the
    # dialog's construction; before the fix several of them corrupted the heap.
    _run_child("""
        for threshold in range(20, 1520, 13):
            gc.collect()
            gc.set_threshold(threshold, 10**6, 10**6)
            dialog = ui.GuidedSetupDialog()
            gc.disable()
            dialog.close()
            app.processEvents()
            del dialog
            gc.collect()
            gc.enable()
        gc.set_threshold(700, 10, 10)
        assert not [w for w in app.topLevelWidgets() if isinstance(w, ui.GuidedSetupDialog)]
    """)


def test_collection_on_a_worker_thread_deletes_the_dialog_on_the_gui_thread():
    output = _run_child("""
        gc.disable()
        dialog = FilledRowDialog()
        deleted_on = []
        dialog.destroyed.connect(lambda *_: deleted_on.append(threading.current_thread().name))
        app.processEvents()
        del dialog
        collector = threading.Thread(target=gc.collect, name="collector")
        collector.start()
        collector.join()
        print("after worker", deleted_on, flush=True)
        app.processEvents()
        gc.collect()
        gc.enable()
        print("after events", deleted_on, flush=True)
    """)
    assert "after worker []" in output
    assert "after events ['MainThread']" in output


def test_only_python_owned_widgets_are_deleted_by_the_finalizer():
    QApplication.instance() or QApplication([])
    parent = QWidget()
    owned_by_qt = FramelessPopupCombo(parent)
    delete_tree_before_collection(owned_by_qt)
    assert shiboken6.isValid(owned_by_qt)
    standalone = FramelessPopupCombo()
    popup = standalone._popup
    delete_tree_before_collection(standalone)
    assert not shiboken6.isValid(standalone) and not shiboken6.isValid(popup)
