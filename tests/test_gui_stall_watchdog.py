"""GUI stall watchdog: records a blocked GUI thread with its stack, nothing else."""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from twobyteasr import gui_stall_watchdog as watchdog_module
from twobyteasr.gui_stall_watchdog import GuiStallWatchdog


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _spin(seconds: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


def _block_gui_thread_for(seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        pass


def test_blocked_gui_thread_is_recorded_with_its_stack(app, monkeypatch):
    emitted = []
    monkeypatch.setattr(GuiStallWatchdog, "_emit", lambda self, record: emitted.append(dict(record)))
    watchdog = GuiStallWatchdog()
    watchdog.add_context("probe", lambda: {"state": "after"})
    probes = []
    watchdog.add_native_probe("native", lambda: probes.append(1) or {"ok": True})
    watchdog.start()
    try:
        _spin(0.3)
        _block_gui_thread_for(0.7)
        _spin(0.4)
    finally:
        watchdog.stop()
    stalls = [r for r in emitted if r.get("kind") == "GUI_STALL"]
    assert len(stalls) == 1
    record = stalls[0]
    assert 550 <= record["duration_ms"] <= 1500
    frames = [frame for stack in record["stacks"] for frame in stack["frames"]]
    assert any("_block_gui_thread_for" in frame for frame in frames)
    assert record["context_after"] == {"probe": {"state": "after"}}
    assert record["native"] == {"native": {"ok": True}} and probes == [1]
    assert watchdog.stall_count == 1


def test_steady_event_loop_writes_nothing(app, monkeypatch):
    emitted = []
    monkeypatch.setattr(GuiStallWatchdog, "_emit", lambda self, record: emitted.append(record))
    watchdog = GuiStallWatchdog()
    watchdog.start()
    try:
        _spin(0.8)
        stats = watchdog.lag_stats()
    finally:
        watchdog.stop()
    assert emitted == []
    assert stats["over_250ms"] == 0 and stats["beats"] >= 5


def test_disabled_by_environment(monkeypatch):
    monkeypatch.setenv("TWOBYTEASR_STALL_WATCHDOG", "0")
    monkeypatch.setattr(watchdog_module, "_INSTANCE", None)
    assert watchdog_module.install() is None


def test_gap_the_sampler_never_saw_is_still_reported(app, monkeypatch):
    """A long C call holding the GIL starves the sampler thread too."""
    emitted = []
    monkeypatch.setattr(GuiStallWatchdog, "_emit", lambda self, record: emitted.append(dict(record)))
    watchdog = GuiStallWatchdog()  # sampler thread not started
    watchdog._previous_beat = time.perf_counter() - 0.6
    watchdog._beat()
    watchdog._beat()  # next beat attaches context and emits
    assert [r["kind"] for r in emitted] == ["GUI_STALL"]
    assert emitted[0]["unsampled"] is True and emitted[0]["samples"] == 0
    assert 550 <= emitted[0]["duration_ms"] <= 1000
    assert watchdog.stall_count == 1


def test_native_hang_dump_lists_every_thread(app, monkeypatch, tmp_path):
    emitted = []
    monkeypatch.setattr(GuiStallWatchdog, "_emit", lambda self, record: emitted.append(dict(record)))
    monkeypatch.setattr(watchdog_module, "HANG_DUMP_S", 0.3)
    monkeypatch.setattr(watchdog_module, "HANG_REARM_S", 0.05)
    path = tmp_path / "logs" / "gui-hang-1.txt"
    watchdog = GuiStallWatchdog()
    watchdog.start(hang_dump_path=path)
    try:
        _spin(0.2)
        _block_gui_thread_for(1.3)
        _spin(0.3)
    finally:
        watchdog.stop()
    dumps = [r for r in emitted if r.get("kind") == "GUI_HANG_DUMP"]
    assert len(dumps) == 1
    text = dumps[0]["text"]
    assert "_block_gui_thread_for" in text and "gui-stall-watchdog" not in text  # stacks, no names
    assert text.count("Thread 0x") >= 2  # the GUI thread and the sampler thread
    assert not path.exists()  # emptied after collection, removed on stop


def test_hang_dump_left_to_audits_and_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("TWOBYTEASR_ACCEPTANCE_SCENARIO", "visible-playback")
    assert watchdog_module._hang_dump_path() is None
    monkeypatch.setenv("TWOBYTEASR_ACCEPTANCE_SCENARIO", "perf-regression")
    assert watchdog_module._hang_dump_path().name.startswith("gui-hang-")
    monkeypatch.setenv("TWOBYTEASR_HANG_DUMP", "0")
    assert watchdog_module._hang_dump_path() is None
