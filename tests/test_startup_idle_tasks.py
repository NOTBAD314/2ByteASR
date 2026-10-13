"""Startup work that must wait until the first window is usable.

2026-10-12: the startup log's runtime fingerprint imported the whole Studio
module tree before the first window, so the lazy Studio import saved nothing.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import twobyteasr.ui as ui

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_importing_the_main_window_module_does_not_load_studio():
    code = "import sys, twobyteasr.ui; print('twobyteasr.studio_ui' in sys.modules)"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False"


def test_quick_start_writes_the_fingerprint_after_the_window():
    source = (ROOT / "quick_start.py").read_text(encoding="utf-8")
    register = source.index("after_startup_idle(write_runtime_fingerprint)")
    assert source.index("for line in runtime_fingerprint_lines(build_identity):") < register
    assert source.index('_startup_mark("IMPORTS_DONE")') > register
    assert source.count("runtime_fingerprint_lines(build_identity)") == 1


class _Window:
    def __init__(self):
        self.studio = object()

    def built_page(self, name):
        return self.studio if name == "studio" else None

    def _warm_studio_module(self):  # retry slot; the test calls MainWindow's
        raise AssertionError("not reached")


def test_idle_tasks_wait_for_a_released_mouse_then_run_once(monkeypatch, qapp):
    ran, retries = [], []
    monkeypatch.setattr(ui, "_STARTUP_IDLE_TASKS", [])
    ui.after_startup_idle(lambda: ran.append("fingerprint"))
    ui.after_startup_idle(lambda: ran.append("second"))
    monkeypatch.setattr(ui.QTimer, "singleShot", lambda ms, receiver, slot: retries.append(ms))
    pressed = [Qt.MouseButton.LeftButton]
    monkeypatch.setattr(ui.QApplication, "mouseButtons", staticmethod(lambda: pressed[0]))
    window = _Window()

    ui.MainWindow._warm_studio_module(window)
    assert ran == [] and retries == [1000]

    pressed[0] = Qt.MouseButton.NoButton
    ui.MainWindow._warm_studio_module(window)
    assert ran == ["fingerprint", "second"]
    ui.MainWindow._warm_studio_module(window)
    assert ran == ["fingerprint", "second"]
