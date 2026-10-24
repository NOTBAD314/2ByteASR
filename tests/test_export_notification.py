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
