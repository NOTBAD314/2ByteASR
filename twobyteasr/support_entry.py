"""Voluntary support links and a one-way, user-wide entry preference."""

from PySide6.QtCore import QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .design.presentation import button_role
from .i18n import bind_text, tr
from .main_ui_dialogs import DialogSurface, SpringDialog
from .theme_manager import SETTINGS_APP, SETTINGS_ORG, theme_key
from .themed_icons import install_themed_icon
from .ui_theme import theme_definition


SUPPORT_HIDDEN_KEY = "ui/support_entry_hidden"
SUPPORT_CHANNELS = (
    ("PayPal", "https://paypal.me/2byte314"),
    ("爱发电", "https://afdian.com/a/2byteasr"),
)


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


class _SupportCard(DialogSurface):
    """A local variation of the shared card; all colours follow theme tokens."""

    def refresh_theme_palette(self):
        super().refresh_theme_palette()
        theme = theme_definition(theme_key())
        self.setStyleSheet(self.styleSheet() + f"""
            QFrame#dialogSurfaceHeader {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {theme.surface_elevated}, stop:1 {theme.surface});
                border-bottom: 1px solid {theme.border};
            }}
            QLabel#supportParagraph {{ color: {theme.text_secondary}; background: transparent; }}
            QLabel#supportEmphasis {{
                color: {theme.text}; background: {theme.accent_soft};
                border: 1px solid {theme.border}; border-radius: 10px;
                padding: 12px 16px; font-weight: 600;
            }}
            QPushButton#supportChannel {{ background: {theme.surface_elevated}; color: {theme.text}; }}
            QPushButton#supportChannelAlternate {{ background: {theme.selected}; color: {theme.text}; }}
            QPushButton#supportChannel:hover, QPushButton#supportChannelAlternate:hover {{
                background: {theme.accent_soft}; border-color: {theme.border_strong};
            }}
            QFrame#dialogSurfaceFooter {{ background: {theme.panel}; }}
        """)


class _SupportSurface(SpringDialog):
    ENTRY_ANIMATED = False

    def __init__(self, parent, title):
        super().__init__(parent, backdrop=False)
        bind_text(self, title, property="windowTitle")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.surface = _SupportCard(self, close_callback=self.reject)
        self.surface.header_layout.setContentsMargins(16, 14, 16, 14)
        self.surface.header_layout.insertSpacing(0, 30)  # balance the close icon
        self.surface.header_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.surface.header_title.setWordWrap(True)
        self.surface.body_layout.setContentsMargins(28, 22, 28, 22)
        self.surface.body_layout.setSpacing(18)
        bind_text(self.surface.header_title, title)
        layout.addWidget(self.surface)
        self.setMinimumWidth(460)
        self.resize(600, 410)

    def paragraph(self, text, *, emphasis=False):
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("supportEmphasis" if emphasis else "supportParagraph")
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

    def done(self, result):
        # This small utility surface has no entrance/exit animation.
        QDialog.done(self, result)


class SupportHideConfirmation(_SupportSurface):
    def __init__(self, parent):
        super().__init__(parent, '永久关闭「支持我」？')
        self.setObjectName("supportHideConfirmation")
        self.paragraph('这会让「支持我！」按钮从主页上永久消失。')
        self.paragraph("这同样不会影响任何功能的开发和使用。", emphasis=True)
        self.paragraph("也感谢你使用这款软件！")
        self.cancel_button = self.action("取消")
        self.confirm_button = self.action("永久关闭")
        self.surface.footer_layout.addStretch(1)
        self.surface.footer_layout.addWidget(self.cancel_button)
        self.surface.footer_layout.addWidget(self.confirm_button)
        self.surface.footer_layout.addStretch(1)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus(Qt.FocusReason.OtherFocusReason)


class SupportDialog(_SupportSurface):
    entry_hidden = Signal()

    def __init__(self, parent):
        super().__init__(parent, "支持我！")
        self.setObjectName("supportDialog")
        self._confirmation = None
        self.paragraph("支持完全自愿，不影响任何功能的开发和使用。", emphasis=True)
        self.paragraph("如果兔白字幕帮到了你，而你也愿意支持，会让我开心一整天！")
        self.paragraph("不支持也完全没关系，感谢你使用兔白字幕！")
        channels = QHBoxLayout()
        channels.setSpacing(12)
        self.channel_buttons = []
        for index, (name, url) in enumerate(SUPPORT_CHANNELS):
            button = self.action(name)
            button.setObjectName("supportChannel" if index == 0 else "supportChannelAlternate")
            install_themed_icon(button, "fa5s.external-link-alt", "primary")
            bind_text(button, "在默认浏览器中打开：{url}", property="toolTip", url=url)
            button.clicked.connect(lambda _checked=False, address=url: self._open_channel(address))
            channels.addWidget(button, 1)
            self.channel_buttons.append(button)
        self.surface.body_layout.addSpacing(4)
        self.surface.body_layout.addLayout(channels)
        self.hide_button = self.action('永久关闭「支持我」', "ghost")
        self.close_button = self.action("关闭")
        self.surface.footer_layout.addStretch(1)
        self.surface.footer_layout.addWidget(self.hide_button)
        self.surface.footer_layout.addWidget(self.close_button)
        self.surface.footer_layout.addStretch(1)
        self.hide_button.clicked.connect(self._confirm_hide)
        self.close_button.clicked.connect(self.reject)
        self.close_button.setDefault(True)
        self.close_button.setFocus(Qt.FocusReason.OtherFocusReason)

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
