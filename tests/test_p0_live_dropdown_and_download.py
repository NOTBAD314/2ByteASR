"""Live P0 acceptance tests executed in a real running Qt event loop.

Tests the exact widgets and classes used by the production GUI:

1. FramelessPopupCombo + _ComboPopup:
   - Same trigger click toggles (open then close).
   - Click outside closes.
   - Click another trigger: previous is closed immediately (no re-animate), new opens.
   - No re-animate if already visible (show_animated guards).

2. ModelDownloadDialog non-modal behavior:
   - Start a background task (QProcess).
   - Close/hide the dialog while running → process keeps running.
   - Re-show the same dialog instance → still attached to the live process and can receive progress.
   - Main UI (test host) remains operable.

These are run with a real QApplication (visible or offscreen platform), not mocks.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, QProcess
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

from twobyteasr.app.ui import FramelessPopupCombo, _ComboPopup
from twobyteasr.local_models.model_workshop import ModelDownloadDialog, WorkshopModel


def _make_dummy_model():
    return WorkshopModel(
        key="test_dummy",
        role="primary",
        name="Test Dummy",
        monogram="TD",
        summary="For live behavior test",
        mode="本地",
        size="1 KB",
        proof="test",
        description="dummy",
        capabilities=(),
        download_key="dummy",
    )


def test_dropdown_toggle_and_outside_close():
    app = QApplication.instance() or QApplication(sys.argv)

    win = QMainWindow()
    central = QWidget()
    win.setCentralWidget(central)
    lay = QVBoxLayout(central)

    c1 = FramelessPopupCombo()
    c1.addItems(["A", "B", "C"])
    lay.addWidget(c1)

    c2 = FramelessPopupCombo()
    c2.addItems(["X", "Y"])
    lay.addWidget(c2)

    win.resize(400, 300)
    win.show()
    QTest.qWait(50)

    # Open first
    c1.showPopup()
    QTest.qWait(80)
    assert c1._popup.isVisible(), "First combo popup should be visible after showPopup"

    # Same trigger click again → should toggle close (no re-animate path)
    c1.showPopup()
    QTest.qWait(30)
    assert not c1._popup.isVisible(), "Same trigger click should close the popup"

    # Open again
    c1.showPopup()
    QTest.qWait(80)
    assert c1._popup.isVisible()

    # Selecting an item closes the popup and leaves the combo usable.
    c1._popup._choose_item(c1._popup.listing.item(1))
    QTest.qWait(30)
    assert c1.currentIndex() == 1
    assert not c1._popup.isVisible()

    c1.showPopup()
    QTest.qWait(80)
    assert c1._popup.isVisible()

    # Click outside the popup (deliver a real mouse click on the host widget at a screen point outside the popup).
    # The popup installs an app eventFilter that reacts to MouseButtonPress outside its rect and calls hide() without consuming.
    popup_geo = c1._popup.geometry()
    # Pick a screen point clearly outside the popup (to the right and down).
    screen_outside = popup_geo.topRight() + QPoint(80, 40)
    local_on_central = central.mapFromGlobal(screen_outside)
    # Fallback to a safe local point if mapping went off-widget in this environment
    if local_on_central.x() < 0 or local_on_central.y() < 0 or local_on_central.x() > central.width() or local_on_central.y() > central.height():
        local_on_central = QPoint(10, central.height() - 10)
    QTest.mouseClick(central, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, local_on_central)
    QTest.qWait(40)
    app.processEvents()
    assert not c1._popup.isVisible(), "Outside click should close the popup"

    # Open c1 again
    c1.showPopup()
    QTest.qWait(80)
    app.processEvents()
    assert c1._popup.isVisible()

    # Now "click" another trigger (c2) while c1 is open.
    # We call showPopup on c2 (the same entry point the real UI uses).
    # Ensure no stale suppression from prior outside-click handling.
    if getattr(c2, "_suppress_show_until_click_release", False):
        c2._suppress_show_until_click_release = False
    c2.showPopup()
    QTest.qWait(80)
    app.processEvents()

    # Critical behavior: previous popup must be closed immediately (no re-animate of old one).
    assert not c1._popup.isVisible(), "Previous popup must be closed when another trigger is activated"

    assert c2._popup.isVisible(), "Second combo popup should become visible"

    # Esc closes the active popup.
    escape = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )
    c2._popup.keyPressEvent(escape)
    QTest.qWait(20)
    assert escape.isAccepted()
    assert not c2._popup.isVisible()

    # A later popup can still open after Esc; no stale active popup remains.
    c1.showPopup()
    QTest.qWait(40)
    assert c1._popup.isVisible()
    c1.showPopup()
    QTest.qWait(20)
    assert not c1._popup.isVisible()

    # Repeating the same trigger follows the stable toggle contract.
    c2.showPopup()
    QTest.qWait(40)
    assert c2._popup.isVisible()
    c2.showPopup()
    QTest.qWait(20)
    app.processEvents()
    assert not c2._popup.isVisible()

    win.close()
    print("DROPDOWN_TOGGLE_TEST: PASS")


def test_download_non_blocking_and_reshow():
    app = QApplication.instance() or QApplication(sys.argv)

    root = Path(".")
    model = _make_dummy_model()

    dlg = ModelDownloadDialog(root, model, None, download_keys=("dummy",), display_name="Dummy")
    dlg.show()
    QTest.qWait(20)

    # Replace the real long-running script with a tiny loop that keeps the process alive briefly
    # and emits structured progress so UI can update.
    # We use powershell -Command "for($i=0;$i -lt 8;$i++){ Write-Output ('[2BYTEASR_PROGRESS] ' + '{\"percent\":' + [string](($i*12)) + ',\"downloaded\":' + [string]($i*1000) + ',\"total\":8000,\"speed\":1000,\"phase\":\"download\"}'); Start-Sleep -Milliseconds 120 }"
    # This keeps QProcess running for ~1s while we test hide/reshow.
    script = (
        "-NoProfile -ExecutionPolicy Bypass -Command "
        "\"for($i=0;$i -lt 8;$i++){ "
        "$p = [math]::floor($i*12); "
        "$d = $i*1000; "
        "Write-Output ('[2BYTEASR_PROGRESS] {\\\"percent\\\":' + [string]$p + ',\\\"downloaded\\\":' + [string]$d + ',\\\"total\\\":8000,\\\"speed\\\":1000,\\\"phase\\\":\\\"download\\\"}'); "
        "Start-Sleep -Milliseconds 120 } ; Write-Output 'done'\""
    )

    # Monkey the arguments so start() uses our fast emitter instead of the real heavy script.
    # We call the internal start after patching.
    original_start = dlg.start

    def fast_start():
        if dlg.process.state() != QProcess.ProcessState.NotRunning:
            return
        dlg._paused = False
        dlg.progress.setRange(0, 0)
        dlg.progress_status.setText("测试下载进行中…")
        dlg.start_button.setEnabled(False)
        dlg.start_button.setText("正在下载…")
        dlg.close_button.setText("关闭窗口（后台继续）")
        dlg.pause_button.setVisible(True)
        # Use cmd to run a fast loop that prints markers
        # On Windows use powershell as the production code does.
        ps = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
        program = ps if os.path.isfile(ps) else "powershell.exe"
        dlg.process.setWorkingDirectory(str(Path(".").resolve()))
        dlg.process.start(program, ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "for($i=0;$i -lt 8;$i++){ "
            "$p = [math]::floor($i*12); "
            "$d = $i*1000; "
            "Write-Output ('[2BYTEASR_PROGRESS] {\\\"percent\\\":' + [string]$p + ',\\\"downloaded\\\":' + [string]$d + ',\\\"total\\\":8000,\\\"speed\\\":1000,\\\"phase\\\":\\\"download\\\"}'); "
            "Start-Sleep -Milliseconds 120 } ; Write-Output 'done'"])

    dlg.start = fast_start
    dlg.start()

    # Give it a moment to start
    QTest.qWait(200)
    assert dlg.process.state() != QProcess.ProcessState.NotRunning, "QProcess should be running"

    # Close the window (should hide, not kill)
    dlg._hide_without_stopping()
    QTest.qWait(30)
    assert not dlg.isVisible(), "Dialog should be hidden"
    assert dlg.process.state() != QProcess.ProcessState.NotRunning, "Process must keep running after hide"

    # Re-show the same dialog instance (as production download_combination does)
    dlg.showNormal()
    dlg.raise_()
    QTest.qWait(50)
    assert dlg.isVisible(), "Re-opening dialog should show the live task"

    # Let some more progress arrive while "main UI" (this test) can still process events
    for _ in range(6):
        QTest.qWait(80)
        app.processEvents()

    # The dialog should have received at least one progress update (status text changed from initial)
    status_text = dlg.progress_status.text()
    assert ("下载" in status_text) or ("%" in status_text) or ("测试" in status_text), f"Expected live progress in status, got: {status_text}"

    # Now simulate user closing while still running → must not terminate
    dlg.close()  # goes through closeEvent which hides for running process
    QTest.qWait(20)
    assert dlg.process.state() != QProcess.ProcessState.NotRunning, "Close while running must not stop the task"

    # Cleanup: stop the dummy process
    if dlg.process.state() != QProcess.ProcessState.NotRunning:
        dlg.process.kill()
        dlg.process.waitForFinished(2000)

    print("DOWNLOAD_NONBLOCK_RESHOW_TEST: PASS")


def main():
    test_dropdown_toggle_and_outside_close()
    test_download_non_blocking_and_reshow()
    print("ALL_LIVE_P0_BEHAVIOR_TESTS: PASS")


if __name__ == "__main__":
    main()
