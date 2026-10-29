"""Card shown when a recognition queue finishes (success, warning or failure).

Split out of ``app/ui.py`` on 2026-10-15; ``ui`` still exports ``CompletionDialog``.
What it says comes from ``ui._completion_notification_spec``.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QVBoxLayout

from ..design.main_ui_dialogs import DialogSurface, SpringDialog
from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_definition
from ..design.ui_widgets import AnimatedButton
from ..i18n import apply_ui_language
from .main_ui_branding import _app_icon
from .main_ui_helpers import _icon, APP_ICON_SOURCE_PATH


class CompletionDialog(SpringDialog):
    """Theme-stable completion card that does not inherit native dark dialogs."""

    _VISUALS = {
        QMessageBox.Icon.Information: ("success", "fa5s.check", "处理完成"),
        QMessageBox.Icon.Warning: ("warning", "fa5s.exclamation", "任务提醒"),
        QMessageBox.Icon.Critical: ("danger", "fa5s.exclamation", "需要处理"),
    }

    def __init__(self, title: str, message: str, icon, details: str = "", parent=None):
        super().__init__(parent)
        role, icon_name, badge_text = self._VISUALS.get(
            icon,
            self._VISUALS[QMessageBox.Icon.Information],
        )
        theme = theme_definition(theme_key())
        self.accent = getattr(theme, role)
        self.tint = getattr(theme, f"{role}_soft", theme.accent_soft)
        self.setObjectName("completionDialog")
        self.setWindowTitle(f"2ByteASR｜{title}")
        self.setWindowIcon(_app_icon())
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumWidth(480)
        self.setMaximumWidth(580)
        self.setSizeGripEnabled(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.card = DialogSurface(
            self,
            title="2ByteASR",
            close_callback=self.reject,
        )
        self.card.setObjectName("completionCard")
        outer.addWidget(self.card)

        brand_icon = QLabel()
        brand_icon.setFixedSize(30, 30)
        # Use full original sprite for the small UI header logo (do not use the Taskbar face-crop here).
        # The face-cropped icon is only for window/taskbar (setWindowIcon + AppUserModelID).
        if APP_ICON_SOURCE_PATH.is_file():
            brand_icon.setPixmap(QIcon(str(APP_ICON_SOURCE_PATH)).pixmap(QSize(30, 30)))
        else:
            brand_icon.setPixmap(_app_icon().pixmap(QSize(30, 30)))
        brand_icon.setStyleSheet("border: 0; background: transparent;")
        self.card.header_layout.insertWidget(0, brand_icon)

        self.status_badge = QLabel(badge_text)
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setStyleSheet(
            f"color: {self.accent}; background: {self.tint}; border: 1px solid {self.accent}; "
            "border-radius: 11px; padding: 3px 10px; font-size: 12px; font-weight: 800;"
        )
        self.card.header_layout.insertWidget(
            self.card.header_layout.count() - 1,
            self.status_badge,
        )
        card_layout = self.card.body_layout

        body = QHBoxLayout()
        body.setContentsMargins(2, 0, 2, 0)
        body.setSpacing(18)
        icon_well = QLabel()
        icon_well.setFixedSize(72, 72)
        icon_well.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_well.setPixmap(_icon(icon_name, self.accent).pixmap(QSize(34, 34)))
        icon_well.setStyleSheet(
            f"background: {self.tint}; border: 2px solid {self.accent}; border-radius: 36px;"
        )
        body.addWidget(icon_well, 0, Qt.AlignmentFlag.AlignTop)

        copy = QVBoxLayout()
        copy.setSpacing(7)
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(
            f"color: {theme.text}; font-size: 22px; font-weight: 900; border: 0; background: transparent;"
        )
        copy.addWidget(self.title_label)
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message_label.setStyleSheet(
            f"color: {theme.text_muted}; font-size: 14px; border: 0; background: transparent;"
        )
        copy.addWidget(self.message_label)
        body.addLayout(copy, 1)
        card_layout.addLayout(body)

        self.details_label = QLabel(details)
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_label.setStyleSheet(
            f"color: {theme.text}; background: {self.tint}; border: 1px solid {theme.border}; border-radius: 12px; "
            "padding: 10px 12px; font-size: 13px;"
        )
        # 2026-10-15: a long failure (worker stderr, traceback) scrolls inside
        # the card instead of stretching the dialog to the full screen height.
        self.details_scroll = QScrollArea()
        self.details_scroll.setObjectName("completionDetailsScroll")
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll.setStyleSheet("QScrollArea#completionDetailsScroll { background: transparent; border: 0; }")
        self.details_scroll.setWidget(self.details_label)
        self.details_scroll.setMaximumHeight(240)
        self.details_scroll.setVisible(bool(details))
        card_layout.addWidget(self.details_scroll)

        footer = self.card.footer_layout
        footer.setSpacing(12)
        hint = QLabel("任务结果已同步到工作台")
        hint.setStyleSheet(f"color: {theme.text_muted}; font-size: 12px; border: 0; background: transparent;")
        footer.addWidget(hint)
        footer.addStretch(1)
        self.confirm_button = AnimatedButton("知道了")
        self.confirm_button.setDefault(True)
        self.confirm_button.setMinimumSize(112, 42)
        self.confirm_button.setStyleSheet(
            f"QPushButton {{ color: {theme.text_on_accent}; background: {theme.accent}; border: 1px solid {theme.accent}; "
            "border-radius: 12px; padding: 8px 22px; font-size: 14px; font-weight: 800; }}"
            f"QPushButton:hover {{ background: {theme.accent_hover}; border-color: {theme.accent_hover}; }}"
            f"QPushButton:pressed {{ background: {theme.accent_pressed}; border-color: {theme.accent_pressed}; padding-top: 10px; }}"
        )
        self.confirm_button.clicked.connect(self.accept)
        footer.addWidget(self.confirm_button)

        self._fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_in.setDuration(190)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        apply_ui_language(self)

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            geometry = self.frameGeometry()
            geometry.moveCenter(parent.window().frameGeometry().center())
            self.move(geometry.topLeft())
        self.setWindowOpacity(0.0)
        self._fade_in.stop()
        self._fade_in.start()
        self.confirm_button.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
