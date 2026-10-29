from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget, QStackedWidget
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace

APP = QApplication.instance() or QApplication([])


def test_completed_receipt_notifies_once_and_os_failure_does_not_hide_success(monkeypatch, tmp_path):
    notifications = []
    def notify(parent, path):
        notifications.append(path)
        raise OSError("notification service unavailable")
    monkeypatch.setattr("twobyteasr.exports.export_notification.notify_export_completed", notify)
    output = tmp_path / "成片.mp4"
    output.write_bytes(b"publication fixture")
    panel = QWidget()
    panel.path, panel.preview, panel.error, panel.play = QLabel(), QWidget(), QLabel(), QPushButton()
    panel.values = {name: QLabel() for name in ("格式", "分辨率", "帧率", "时长", "大小", "平均码率")}
    # The success page also names video / audio output (project audio export).
    panel.title, panel.preview_host, panel.section_label = QLabel(), QWidget(), QLabel()
    panel.metric_labels = {name: QLabel() for name in ("分辨率", "帧率")}
    panel._fit = lambda: None
    pages = QStackedWidget()
    pages.addWidget(panel)
    trace = []
    target = SimpleNamespace(_running=True, _last_job=None, _move_preview_to_setup=lambda: None,
        _settings=SimpleNamespace(setValue=lambda *args: None), success_name=QLabel(), success_meta=QLabel(),
        success_page=panel, pages=pages, _export_trace=lambda *args: trace.append(args))
    StudioExportWorkspace._show_success(target, str(output))
    StudioExportWorkspace._show_success(target, str(output))
    assert notifications == [output]
    assert not target._running
    assert target.pages.currentWidget() is panel
    assert any(event[0] == "completion_notification_failed" for event in trace)
    target._completion_notified = False  # the next submitted export gets a new receipt
    StudioExportWorkspace._show_success(target, str(output))
    assert notifications == [output, output]


def test_a_result_page_that_never_painted_is_written_down(tmp_path):
    """2026-10-27 user report: 压制完成 arrived while the window kept showing the
    progress page. Diagnostics only: 3 s later an unpainted result page is traced."""
    from twobyteasr.exports.export_success import ExportSuccessPanel, report_unpainted_success
    panel = ExportSuccessPanel(lambda: None, lambda: None, lambda: None, lambda: None)
    pages = QStackedWidget()
    pages.addWidget(panel)
    trace = []
    workspace = SimpleNamespace(pages=pages, _export_trace=lambda *args: trace.append(args))
    panel.painted = False
    report_unpainted_success(workspace, panel, tmp_path / "out.mp4")
    assert [event[0] for event in trace] == ["success_page_not_painted"]
    assert trace[0][1]["page_visible"] is False and trace[0][1]["output"].endswith("out.mp4")
    trace.clear()
    from PySide6.QtTest import QTest
    pages.resize(1100, 760)
    pages.show()
    assert QTest.qWaitForWindowExposed(pages)
    pages.repaint()
    assert panel.painted   # a shown page paints, and nothing is written down
    report_unpainted_success(workspace, panel, tmp_path / "out.mp4")
    assert trace == []
    pages.close()


def test_the_completion_notification_waits_for_the_result_page():
    """2026-10-27 user report: the toast appeared while the window still showed
    97%. The notification (tray icon + Explorer call) now runs after the
    result page has painted; a page that cannot paint (minimized) still gets it."""
    from PySide6.QtTest import QTest
    from twobyteasr.exports.export_success import ExportSuccessPanel
    panel = ExportSuccessPanel(lambda: None, lambda: None, lambda: None, lambda: None)
    pages = QStackedWidget()
    pages.addWidget(panel)
    calls = []
    panel.call_after_paint(lambda: calls.append("hidden"), fallback_ms=200)
    APP.processEvents()
    assert calls == []           # not before the page had a chance to paint
    QTest.qWait(300)
    assert calls == ["hidden"]   # never shown: the fallback still notifies
    pages.resize(1100, 760)
    panel.call_after_paint(lambda: calls.append("shown"), fallback_ms=5000)
    pages.show()
    assert QTest.qWaitForWindowExposed(pages)
    pages.repaint()
    QTest.qWait(50)
    assert calls == ["hidden", "shown"] and panel.painted
    QTest.qWait(50)
    assert calls == ["hidden", "shown"]   # once
    pages.close()
