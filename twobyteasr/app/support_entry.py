"""Voluntary support links and a one-way, user-wide entry preference."""

from PySide6.QtCore import QEvent, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QMessageBox, QPushButton

from ..design.presentation import button_role
from ..i18n import bind_text, tr
from ..design.theme_manager import SETTINGS_APP, SETTINGS_ORG
from .support_letter import HighlightNote, LetterDialog, LetterLine, StampButton


SUPPORT_HIDDEN_KEY = "ui/support_entry_hidden"
SUPPORT_CHANNELS = (
    ("PayPal", "https://paypal.me/2byte314"),
    ("爱发电", "https://afdian.com/a/2byteasr"),
)
SUPPORT_CAPTIONS = ("海外 · 银行卡", "国内 · 微信 / 支付宝")


def _settings():
    # The same stable per-user store as appearance/theme; no version/project key.
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def support_entry_hidden():
    return _settings().value(SUPPORT_HIDDEN_KEY, False, type=bool)


def hide_support_entry():
    """Persist only this key. Do not report success for a failed QSettings sync."""
    settings = _settings()
    existed = settings.contains(SUPPORT_HIDDEN_KEY)
    previous = settings.value(SUPPORT_HIDDEN_KEY)
    try:
        settings.setValue(SUPPORT_HIDDEN_KEY, True)
        settings.sync()
        if settings.status() != QSettings.Status.NoError or not settings.value(
            SUPPORT_HIDDEN_KEY, False, type=bool
        ):
            raise OSError("Support preference could not be saved")
    except Exception:
        # QSettings shares an in-process cache: a failed write must not leave a
        # cached true value that hides the entry on window recreation or retry.
        if existed:
            settings.setValue(SUPPORT_HIDDEN_KEY, previous)
        else:
            settings.remove(SUPPORT_HIDDEN_KEY)
        settings.sync()
        raise


class _SupportSurface(LetterDialog):
    """The letter window (2026-11-13, draft B): paper, tape, sticker, stamps."""

    def __init__(self, parent, title, subtitle):
        super().__init__(parent, title, subtitle)

    def note(self, text):
        label = HighlightNote()
        bind_text(label, text)
        self.surface.body_layout.addWidget(label)
        self.surface.body_layout.addSpacing(10)
        return label

    def paragraph(self, text, *, sign=False):
        label = LetterLine(align=Qt.AlignmentFlag.AlignRight if sign else Qt.AlignmentFlag.AlignLeft, sign=sign)
        bind_text(label, text)
        self.surface.body_layout.addWidget(label)
        return label

    def action(self, text, role="secondary"):
        button = button_role(QPushButton(), role)
        bind_text(button, text)
        # Enter activates only the explicit default, never a hovered channel
        # or the permanent-hide action merely because it received focus.
        button.setAutoDefault(False)
        return button

    def footer(self, *buttons):
        self.surface.footer_layout.addStretch(1)
        for button in buttons:
            self.surface.footer_layout.addWidget(button)
        self.surface.footer_layout.addStretch(1)


class SupportHideConfirmation(_SupportSurface):
    def __init__(self, parent):
        super().__init__(parent, '永久关闭「支持我」？', '再确认一下下')
        self.setObjectName("supportHideConfirmation")
        self.note("这同样不会影响任何功能的开发和使用。")
        self.paragraph('这会让「支持我！」按钮从主页上永久消失。')
        self.paragraph("也感谢你使用这款软件！")
        self.cancel_button = self.action("取消")
        self.confirm_button = self.action("永久关闭", "danger")
        self.footer(self.cancel_button, self.confirm_button)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus(Qt.FocusReason.OtherFocusReason)


class SupportDialog(_SupportSurface):
    entry_hidden = Signal()

    def __init__(self, parent):
        super().__init__(parent, "支持我！", "来自兔白的一张小纸条")
        self.setObjectName("supportDialog")
        self._confirmation = None
        self.note("支持完全自愿，不影响任何功能的开发和使用。")
        self.paragraph("如果兔白字幕帮到了你，而你也愿意支持，会让我开心一整天！")
        self.paragraph("不支持也完全没关系，感谢你使用兔白字幕！")
        self.paragraph("— 兔白", sign=True)
        channels = QHBoxLayout()
        channels.setSpacing(16)
        self.channel_buttons = []
        for index, (name, url) in enumerate(SUPPORT_CHANNELS):
            button = StampButton("paypal" if index == 0 else "afdian", -2.0 if index == 0 else 2.0)
            bind_text(button, name)
            bind_text(button, SUPPORT_CAPTIONS[index], property="caption")
            button.setAutoDefault(False)
            bind_text(button, "在默认浏览器中打开：{url}", property="toolTip", url=url)
            button.clicked.connect(lambda _checked=False, address=url: self._open_channel(address))
            button.installEventFilter(self)
            channels.addWidget(button, 1)
            self.channel_buttons.append(button)
        self.surface.body_layout.addSpacing(10)
        self.surface.body_layout.addLayout(channels)
        self.hide_button = self.action('永久关闭「支持我」', "ghost")
        self.close_button = self.action("关闭")
        self.footer(self.hide_button, self.close_button)
        self.hide_button.clicked.connect(self._confirm_hide)
        self.close_button.clicked.connect(self.reject)
        self.close_button.setDefault(True)
        self.close_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched, event):
        # Pointing at a stamp makes the bunny sticker perk up.
        if watched in getattr(self, "channel_buttons", ()) and event.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            self.surface.sticker.set_happy(event.type() == QEvent.Type.Enter)
        return super().eventFilter(watched, event)

    def _open_channel(self, address):
        try:
            opened = QDesktopServices.openUrl(QUrl(address))
        except Exception:
            opened = False
        if not opened:
            QMessageBox.warning(self, tr("无法打开浏览器"),
                tr("未能打开浏览器。请手动访问：\n{url}", url=address))

    def _confirm_hide(self):
        if self._confirmation is not None:
            self._confirmation.raise_()
            self._confirmation.activateWindow()
            return
        dialog = SupportHideConfirmation(self)
        self._confirmation = dialog
        dialog.finished.connect(self._hide_confirmed)
        # Native window modality blocks only this support window. Recognition,
        # playback and their timers continue; no navigation or task callbacks.
        dialog.open()

    def _hide_confirmed(self, result):
        dialog, self._confirmation = self._confirmation, None
        if dialog is not None:
            dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted:
            self.hide_button.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        try:
            hide_support_entry()
        except Exception:
            QMessageBox.warning(self, tr("无法保存设置"),
                tr("未能保存关闭状态，支持入口仍会保留。请稍后重试。"))
            return
        self.entry_hidden.emit()
        self.accept()
