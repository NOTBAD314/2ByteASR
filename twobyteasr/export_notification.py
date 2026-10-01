"""Non-blocking completion feedback, called on the GUI thread after publication."""
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QStyle, QSystemTrayIcon

from .i18n import bind_text


def notify_export_completed(parent, output: Path) -> None:
    """Keep the receipt visible and alert users working in another window."""
    QApplication.alert(parent.window(), 0)
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except (ImportError, RuntimeError, OSError):
        QApplication.beep()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return
    tray = getattr(parent, "_export_notification_tray", None)
    if tray is None:
        tray = QSystemTrayIcon(parent)
        icon = parent.window().windowIcon()
        if icon.isNull():
            icon = parent.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        tray.setIcon(icon)
        bind_text(tray, '2ByteASR · 成片压制', property='toolTip')
        parent._export_notification_tray = tray
        timer = QTimer(tray)
        timer.setSingleShot(True)
        timer.timeout.connect(tray.hide)
        parent._export_notification_timer = timer
    tray.show()
    tray.showMessage("2ByteASR · 压制完成", f"成片已保存：{output.name}",
                     QSystemTrayIcon.MessageIcon.Information, 10000)
    parent._export_notification_timer.start(30000)
