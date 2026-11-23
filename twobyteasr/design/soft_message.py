"""Small rounded notice / question windows in the app's own style (2026-11-22).

User: these pop-ups should not use the Windows ones (the system QMessageBox: a square title bar,
the blue "i" and an "OK" button), they look ugly. ``soft_information`` and ``soft_question`` are
drop-in replacements built on :class:`SpringDialog` (frameless, rounded by the window manager,
the dim backdrop behind it) and the shared :class:`DialogSurface` card.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..i18n import tr
from .main_ui_dialogs import DialogSurface, SpringDialog
from .theme_manager import theme_key
from .ui_theme import blend_hex, theme_definition

_TONES = {
    # tone: (theme colour, its soft colour, icon)
    "info": ("accent", "accent_soft", "fa5s.info"),
    "warning": ("warning", "warning_soft", "fa5s.exclamation"),
    "question": ("accent", "accent_soft", "fa5s.question"),
    "danger": ("danger", "danger_soft", "fa5s.exclamation"),
}


class SoftMessage(SpringDialog):
    """A rounded card: icon well, title, message and one or two buttons."""

    def __init__(self, parent, title: str, text: str, *, tone: str = "info",
                 accept_text: str = "", reject_text: str = "", destructive: bool = False):
        super().__init__(parent)
        t = theme_definition(theme_key())
        colour_name, soft_name, icon_name = _TONES.get(tone, _TONES["info"])
        colour = getattr(t, colour_name, t.accent)
        soft = getattr(t, soft_name, t.accent_soft)
        self.setObjectName("softMessage")
        self.setWindowTitle(str(title))
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setMaximumWidth(560)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = DialogSurface(self, title="", close_callback=self.reject)
        self.card.header.hide()
        outer.addWidget(self.card)

        body = QHBoxLayout()
        body.setSpacing(16)
        well = QLabel()
        well.setObjectName("softMessageIcon")
        well.setFixedSize(52, 52)
        well.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            import qtawesome as qta
            well.setPixmap(qta.icon(icon_name, color=colour).pixmap(QSize(22, 22)))
        except Exception:  # noqa: BLE001 - the words still work without the icon
            pass
        well.setStyleSheet(f"background: {soft}; border: 0; border-radius: 26px;")
        body.addWidget(well, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(6)
        self.title_label = QLabel(str(title))
        self.title_label.setObjectName("softMessageTitle")
        self.title_label.setWordWrap(True)
        words.addWidget(self.title_label)
        self.text_label = QLabel(str(text))
        self.text_label.setObjectName("softMessageText")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        words.addWidget(self.text_label)
        body.addLayout(words, 1)
        close = QPushButton("×")
        close.setObjectName("softMessageClose")
        close.setFixedSize(30, 30)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setAccessibleName(tr("关闭"))
        close.clicked.connect(self.reject)
        body.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.card.body_layout.setContentsMargins(22, 22, 16, 8)
        self.card.body_layout.addLayout(body)

        self.card.footer.setStyleSheet("QFrame#dialogSurfaceFooter { border-top: 0; }")
        self.card.footer_layout.setContentsMargins(22, 6, 22, 18)
        self.card.footer_layout.addStretch(1)
        self.reject_button = None
        if reject_text:
            self.reject_button = QPushButton(str(reject_text))
            self.reject_button.setObjectName("softMessageSecondary")
            self.reject_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.reject_button.clicked.connect(self.reject)
            self.card.footer_layout.addWidget(self.reject_button)
        self.accept_button = QPushButton(str(accept_text or tr("知道了")))
        self.accept_button.setObjectName("softMessagePrimary")
        self.accept_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.accept_button.setDefault(not destructive)
        self.accept_button.clicked.connect(self.accept)
        self.card.footer_layout.addWidget(self.accept_button)
        if destructive and self.reject_button is not None:
            self.reject_button.setDefault(True)      # Enter never confirms a destructive choice

        primary = t.danger if destructive else colour
        on_primary = getattr(t, "on_vivid", "") or getattr(t, "text_on_accent", "") or "#ffffff"
        from .typography import TITLE_FONT_STACK
        heavy = f"font-family: {TITLE_FONT_STACK}; font-weight: 800;"
        self.card.setStyleSheet(self.card.styleSheet() + f"""
QFrame#dialogSurface {{ border: 0; border-radius: 0; }}
QLabel#softMessageTitle {{ color: {t.text}; font-size: 18px; {heavy} background: transparent; }}
QLabel#softMessageText {{ color: {t.text_secondary}; font-size: 14px; background: transparent; }}
QPushButton#softMessageClose {{ background: transparent; color: {t.text_muted}; border: 0; border-radius: 15px;
    font-size: 18px; padding: 0; }}
QPushButton#softMessageClose:hover {{ background: {t.panel}; color: {t.text}; }}
QPushButton#softMessagePrimary {{ background: {primary}; color: {on_primary}; border: 1px solid {primary};
    border-radius: 12px; padding: 8px 20px; font-size: 14px; {heavy} }}
QPushButton#softMessagePrimary:hover {{ background: {blend_hex(primary, on_primary, 0.12)}; }}
QPushButton#softMessageSecondary {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    border-radius: 12px; padding: 8px 18px; font-size: 14px; {heavy} }}
QPushButton#softMessageSecondary:hover {{ background: {t.panel}; border-color: {t.border_strong}; }}
""")
        self.adjustSize()


def soft_information(parent, title: str, text: str, *, tone: str = "info") -> None:
    """Instead of ``QMessageBox.information``."""
    SoftMessage(parent, title, text, tone=tone).exec()


def soft_question(parent, title: str, text: str, *, accept_text: str = "", reject_text: str = "",
                  destructive: bool = False) -> bool:
    """Instead of ``QMessageBox.question``: True when the user chose ``accept_text``."""
    dialog = SoftMessage(parent, title, text, tone="danger" if destructive else "question",
                         accept_text=accept_text or tr("确定"), reject_text=reject_text or tr("取消"),
                         destructive=destructive)
    return dialog.exec() == SoftMessage.DialogCode.Accepted
