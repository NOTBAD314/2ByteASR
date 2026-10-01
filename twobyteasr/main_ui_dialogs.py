"""Shared dialog primitives for the Main UI."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QPoint, QParallelAnimationGroup, QPropertyAnimation, Qt, QObject, QEvent, QEventLoop,
)
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from .i18n import apply_ui_language, current_language
from .main_ui_theme import APP_QSS
from .qss_retheme import retheme_qss
from .studio_theme import build_secondary_surface_qss
from .theme_manager import theme_key
from .ui_theme import ThemeDefinition, theme_definition
from .ui_motion import MOTION_FAST_MS, MOTION_STANDARD_MS, motion_duration

from .i18n import bind_text


def _active_theme() -> ThemeDefinition:
    return theme_definition(theme_key())


class _DialogInputGuard(QObject):
    """Keep parent input blocked while allowing its dimmed backdrop to close.

    A native modal QDialog disables the parent HWND, including a backdrop
    widget inside that HWND. A local event loop plus this input guard keeps
    exec()'s return contract without making the outside close target inert.
    """
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog

    def eventFilter(self, obj, event):
        if event.type() not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                QEvent.MouseButtonDblClick, QEvent.Wheel, QEvent.KeyPress,
                QEvent.KeyRelease, QEvent.Shortcut, QEvent.ShortcutOverride):
            return False
        if not isinstance(obj, QWidget):
            return False
        current = obj
        while current is not None:
            if current is self.dialog:
                return False
            current = current.parentWidget()
        # Popups and child dialogs belong to the dialog's widget ancestry.
        # Only its own backdrop may accept input outside that ancestry.
        return obj is not self.dialog._modal_backdrop


class DialogSurface(QFrame):
    """Shared opaque Header/Body/Footer surface for dialogs and modal hosts."""

    def __init__(
        self,
        parent=None,
        *,
        title: str = "",
        close_callback=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dialogSurface")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QFrame(self)
        self.header.setObjectName("dialogSurfaceHeader")
        self.header.mousePressEvent = self._move_window
        self.header_title = QLabel(str(title))
        self.header_title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(18, 12, 10, 12)
        self.header_layout.setSpacing(10)
        self.header_title.setObjectName("dialogSurfaceTitle")
        self.header_layout.addWidget(self.header_title, 1)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("dialogSurfaceClose")
        self.close_button.setFixedSize(30, 30)
        bind_text(self.close_button, '关闭', property='toolTip')
        bind_text(self.close_button, '关闭', property='accessibleName')
        if close_callback is not None:
            self.close_button.clicked.connect(close_callback)
        self.header_layout.addWidget(self.close_button)
        layout.addWidget(self.header)

        self.body = QWidget(self)
        self.body.setObjectName("dialogSurfaceBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(20, 18, 20, 18)
        self.body_layout.setSpacing(14)
        layout.addWidget(self.body, 1)

        self.footer = QFrame(self)
        self.footer.setObjectName("dialogSurfaceFooter")
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(20, 12, 20, 14)
        self.footer_layout.setSpacing(10)
        layout.addWidget(self.footer)
        self.refresh_theme_palette()

    def _move_window(self, event):
        # Embedded modal cards install their own bounded drag handler.
        if event.button() == Qt.LeftButton and isinstance(self.window(), QDialog):
            handle = self.window().windowHandle()
            if handle:
                handle.startSystemMove()

    def set_title(self, title: str) -> None:
        self.header_title.setText(str(title or ""))

    def refresh_theme_palette(self) -> None:
        theme = _active_theme()
        from .design.surface_qss import build_surface_qss
        from .design.control_qss import build_control_qss
        self.setStyleSheet(build_surface_qss(theme) + build_control_qss(theme))



class SpringDialog(QDialog):
    """Solid dialog base that follows the current ThemeDefinition."""

    # 入场滑动+渐入动画开关：应用设置等"高频即开"入口置 False，
    # 用户反馈弹窗动画带来约 1 秒等待感（2026-09-19 轮）。
    ENTRY_ANIMATED = True

    def __init__(self, parent=None, *, backdrop=True):
        super().__init__(parent)
        self._use_backdrop = bool(backdrop)
        self._modal_backdrop = None
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        self.refresh_theme_palette()
        from .window_constraints import install_window_bounds
        install_window_bounds(self, within_parent=True)

    def exec(self):
        if not self._use_backdrop or self.parentWidget() is None:
            return super().exec()
        app = QApplication.instance()
        loop = QEventLoop(self)
        answer = [int(QDialog.Rejected)]
        def completed(value):
            answer[0] = value
            loop.quit()
        self.finished.connect(completed)
        self.destroyed.connect(loop.quit)
        guard = _DialogInputGuard(self)
        self._input_guard = guard
        app.installEventFilter(guard)
        self.setWindowModality(Qt.NonModal)
        self.show()
        self.raise_()
        self.activateWindow()
        try:
            loop.exec()
        finally:
            from shiboken6 import isValid
            if isValid(guard):
                app.removeEventFilter(guard)
            if isValid(self):
                self.finished.disconnect(completed)
                guard.deleteLater()
                self._input_guard = None
        return answer[0]

    def refresh_theme_palette(self) -> None:
        applied_theme_key = theme_key()
        theme = theme_definition(applied_theme_key)
        self._theme_fill = theme.surface
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Base, QColor(theme.input_surface))
        palette.setColor(QPalette.ColorRole.Text, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Button, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.text_muted))
        self.setPalette(palette)
        self.setStyleSheet(retheme_qss(APP_QSS, theme) + build_secondary_surface_qss(theme))
        if self._modal_backdrop is not None:
            self._modal_backdrop.setStyleSheet(
                f"background: {theme.media}; border: 0;"
            )
        self._applied_theme_key = applied_theme_key

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(getattr(self, "_theme_fill", _active_theme().surface)))
        super().paintEvent(event)

    def showEvent(self, event):
        self._exit_pending = False
        from .design.presentation import prepare_controls
        prepare_controls(self)
        from .window_constraints import constrain
        constrain(self, within_parent=True)
        if getattr(self, "_applied_theme_key", None) != theme_key():
            self.refresh_theme_palette()
        apply_ui_language(self, current_language())
        parent = self.parentWidget()
        if self._use_backdrop and parent is not None and self._modal_backdrop is None:
            host = parent.window()
            theme = _active_theme()
            backdrop = QFrame(host)
            backdrop.setObjectName("modalBackdrop")
            backdrop.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            backdrop.setAutoFillBackground(False)
            color = QColor(theme.media)
            color.setAlpha(140)
            backdrop.setStyleSheet(
                f"background: rgba({color.red()}, {color.green()}, {color.blue()}, 140); border: 0;"
            )
            backdrop.setGeometry(host.rect())
            # Close on release so the complete click is consumed by the
            # backdrop and cannot activate an underlying destructive button.
            def _press_backdrop(e):
                backdrop._close_pressed = e.button() == Qt.LeftButton
                e.accept()
            def _release_backdrop(e):
                e.accept()
                if getattr(backdrop, '_close_pressed', False) and e.button() == Qt.LeftButton:
                    backdrop._close_pressed = False
                    self.reject()
            backdrop.mousePressEvent = _press_backdrop
            backdrop.mouseReleaseEvent = _release_backdrop
            backdrop.show()
            backdrop.raise_()
            self._modal_backdrop = backdrop
        super().showEvent(event)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.update()
        duration = motion_duration(MOTION_STANDARD_MS) if self.ENTRY_ANIMATED else 0
        if duration:
            final_pos = QPoint(self.pos())
            self.move(final_pos + QPoint(0, 6))
            self.setWindowOpacity(0.0)
            group = QParallelAnimationGroup(self)
            position = QPropertyAnimation(self, b"pos", group)
            position.setStartValue(self.pos())
            position.setEndValue(final_pos)
            opacity = QPropertyAnimation(self, b"windowOpacity", group)
            opacity.setStartValue(0.0)
            opacity.setEndValue(1.0)
            for animation in (position, opacity):
                animation.setDuration(duration)
                animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._entrance_motion = group
            group.start()
        else:
            self.setWindowOpacity(1.0)

    def done(self, result):
        duration = motion_duration(MOTION_FAST_MS)
        if not duration or not self.isVisible():
            return super().done(result)
        if getattr(self, "_exit_pending", False):
            return
        self._exit_pending = True
        entrance = getattr(self, "_entrance_motion", None)
        if entrance is not None:
            entrance.stop()
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(duration)
        animation.setStartValue(self.windowOpacity())
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: QDialog.done(self, result))
        self._exit_motion = animation
        animation.start()

    def hideEvent(self, event):
        if self._modal_backdrop is not None:
            try:
                self._modal_backdrop.hide()
                self._modal_backdrop.deleteLater()
            except Exception:
                pass
            self._modal_backdrop = None
        super().hideEvent(event)
