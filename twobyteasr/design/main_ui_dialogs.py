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

from ..i18n import apply_ui_language, current_language
from .main_ui_theme import APP_QSS
from .qss_retheme import retheme_qss
from .studio_theme import build_secondary_surface_qss
from .theme_manager import theme_key
from .ui_theme import ThemeDefinition, theme_definition
from .ui_motion import MOTION_FAST_MS, MOTION_STANDARD_MS, motion_duration
from .widget_teardown import delete_tree_before_collection

from ..i18n import bind_text


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
        # A history/settings dialog may open another dialog with the main
        # window as owner. Its widgets are siblings, not descendants of this
        # dialog. Only the most recently entered, visible exec owns input.
        # Otherwise an older guard blocks the new dialog after its own guard
        # allowed the event, leaving a live event loop with inert buttons.
        from shiboken6 import isValid
        visible = getattr(QApplication.instance(), '_spring_visible_dialogs', ())
        active = next((dialog for dialog in reversed(visible)
                       if isValid(dialog) and dialog.isVisible()), None)
        if not self.dialog.isVisible() or active is not self.dialog:
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
        # The rounded surface is the sole background owner. A palette auto
        # fill is rectangular and leaks behind its styled rounded outline.
        self.setAutoFillBackground(False)

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
        from .surface_qss import build_surface_qss
        from .control_qss import build_control_qss
        self.setStyleSheet(build_surface_qss(theme) + build_control_qss(theme))



class _FadingBackdrop(QFrame):
    """The dim behind a dialog: it fades in with the dialog's growth and out with its shrinking
    (2026-11-19; it used to appear at full strength and vanish at once, so closing a dialog showed
    a bright Home between the dialog and its shrinking picture)."""

    ALPHA = 140

    def __init__(self, host, color):
        super().__init__(host)
        self.setObjectName("modalBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.color = QColor(color)
        self.alpha = 0.0
        self._fade = None
        self._under = None             # the window under the dim, held while the dim moves
        self._grabbing = False
        self.shade = None
        self.flight_owned = False
        host.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self._release_window()
            self.setGeometry(watched.rect())
        return False

    def set_progress(self, alpha) -> None:
        self.alpha = alpha
        if self.shade is not None:
            self.shade.update()
        else:
            self.update()

    def retire(self) -> None:
        if self.shade is not None:
            self.shade.hide()
            self.shade.deleteLater()
            self.shade = None
        self.hide()
        self.deleteLater()

    def paint_shade(self, target):
        if self.alpha > 0:
            painter = QPainter(target)
            fill = QColor(self.color)
            fill.setAlpha(max(0, min(255, round(self.alpha))))
            painter.fillRect(target.rect(), fill)

    def set_color(self, color) -> None:
        self.color = QColor(color)
        self.set_progress(self.alpha)

    def _hold_window(self) -> None:
        """2026-11-20 (user: the settings open at a low frame rate): a translucent dim made Qt draw
        the whole window under it again for every step of its fade (every 8 ms), Home's cards and
        all, on the thread that also draws the dialog's motion. While the dim moves it paints a
        picture of the window taken once, and is opaque, so nothing under it is drawn again."""
        host = self.parentWidget()
        if host is None or self._under is not None:
            return
        self._grabbing = True
        try:
            picture = host.grab(self.geometry())
        finally:
            self._grabbing = False
        if picture.isNull():
            return
        self._under = picture
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def _release_window(self) -> None:
        if self._under is None:
            return
        self._under = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        if self.shade is not None or self._grabbing:
            return                         # the window's picture is taken without the dim
        under = self._under
        if self.alpha <= 0.0 and under is None:
            return
        painter = QPainter(self)
        if under is not None:
            from .device_pixels import draw_picture
            draw_picture(painter, QPoint(0, 0), under)
        fill = QColor(self.color)
        fill.setAlpha(max(0, min(255, round(self.alpha))))
        painter.fillRect(self.rect(), fill)
        painter.end()

    def fade_to(self, alpha: float, tween, then=None) -> None:
        """Move the dim to ``alpha`` over ``tween`` (at once without motion); ``then`` after."""
        import time
        from PySide6.QtCore import QTimer
        from . import motion_tokens as tokens
        from .transitions import enabled
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        start = self.alpha
        if not enabled() or tween.ms <= 0:
            self.set_progress(alpha)
            if callable(then):
                then()
            return
        curve = tokens.easing_curve(tween)
        began = time.perf_counter()
        timer = self._fade = QTimer(self)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        if self.shade is None:
            self._hold_window()

        def step():
            k = min(1.0, (time.perf_counter() - began) * 1000 / tween.ms)
            self.set_progress(start + (alpha - start) * curve.valueForProgress(k))
            if k >= 1.0:
                timer.stop()
                self._fade = None
                self._release_window()
                if callable(then):
                    then()

        timer.timeout.connect(step)
        from .transitions import _frame_ms
        timer.start(_frame_ms(self))       # one step a screen frame (it was every 8 ms)
        step()


class _SettingsShade(QWidget):
    """One scrim above every native child, including the page stack."""
    def __init__(self, backdrop, cover):
        super().__init__(cover)
        self.backdrop = backdrop
        self.setObjectName('settingsShade')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(cover.rect())
        cover.installEventFilter(self)
        self.show()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        return False

    def paintEvent(self, event):
        self.backdrop.paint_shade(self)


class SpringDialog(QDialog):
    """Solid dialog base that follows the current ThemeDefinition."""

    # 入场滑动+渐入动画开关：应用设置等"高频即开"入口置 False，
    # 用户反馈弹窗动画带来约 1 秒等待感（2026-09-19 轮）。
    ENTRY_ANIMATED = True
    EXIT_ANIMATED = True
    UNIFIED_TRANSITION = False

    # A parentless dialog always sits in a reference cycle (WindowBounds);
    # left to the cycle collector it must not be torn down wrapper by wrapper.
    __del__ = delete_tree_before_collection

    def __init__(self, parent=None, *, backdrop=True):
        super().__init__(parent)
        self._owns_theme_sheet = True
        self._use_backdrop = bool(backdrop)
        self._modal_backdrop = None
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        self.refresh_theme_palette()
        from ..app.window_constraints import install_window_bounds
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
        guards = getattr(app, '_spring_dialog_guards', None)
        if guards is None:
            guards = app._spring_dialog_guards = []
        guards.append(guard)
        app.installEventFilter(guard)
        self.setWindowModality(Qt.NonModal)
        self.show()
        self.raise_()
        self.activateWindow()
        try:
            loop.exec()
        finally:
            from shiboken6 import isValid
            if guard in guards:
                guards.remove(guard)
            if isValid(guard):
                app.removeEventFilter(guard)
            if isValid(self):
                self.finished.disconnect(completed)
                guard.deleteLater()
                self._input_guard = None
            # A reused dialog owns one loop per visit. The loop has finished;
            # retaining it as a child would accumulate destroy connections.
            if isValid(loop):
                loop.deleteLater()
        return answer[0]

    def refresh_theme_palette(self) -> None:
        applied_theme_key = theme_key()
        if getattr(self, '_applied_theme_key', None) == applied_theme_key:
            return
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
        if getattr(self, '_theme_scope_owner', False):
            from .theme_scopes import refresh
            refresh(self)
        else:
            self.setStyleSheet(retheme_qss(APP_QSS, theme) + build_secondary_surface_qss(theme))
        if self._modal_backdrop is not None:
            if hasattr(self._modal_backdrop, 'set_color'):
                self._modal_backdrop.set_color(theme.media)
            else:
                self._modal_backdrop.setStyleSheet(f"background: {theme.media}; border: 0;")
        if self.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            self._apply_native_window_style(theme)
        self._applied_theme_key = applied_theme_key

    def _apply_native_window_style(self, theme=None) -> None:
        """Round the window and switch off the Windows show/hide fade.

        2026-11-13: the dialog square corners read as sharp, and DWM's own
        fade made opening feel like a choppy three-frame darken. The window
        manager rounds the native window (Windows 11) and the dialog appears
        in one step; Qt motion (ENTRY/EXIT_ANIMATED) stays the only animation.
        """
        app = QApplication.instance()
        if app is None or app.platformName() != 'windows':
            return
        theme = theme or _active_theme()
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = wintypes.HWND(int(self.winId()))
            if getattr(self, '_native_transitions_hwnd', None) != hwnd.value:
                disable = wintypes.BOOL(True)
                DWMWA_TRANSITIONS_FORCEDISABLED = 3
                status = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_TRANSITIONS_FORCEDISABLED,
                    ctypes.byref(disable), ctypes.sizeof(disable))
                self._native_transitions_status = status
                if status == 0:
                    self._native_transitions_hwnd = hwnd.value
        except (OSError, AttributeError, ValueError):
            pass
        # 2026-11-13 (user): a RoundedWindow (translucent, its own rounded
        # content and shadow) drew a second, square-ish frame: DWM rounds and
        # borders the whole window, shadow margin included. Those draw their own.
        if self.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            self._native_rounding_applied = False
            return
        from .popup_corners import round_native_window
        self._native_rounding_applied = round_native_window(self, theme.border)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(getattr(self, "_theme_fill", _active_theme().surface)))
        super().paintEvent(event)

    def showEvent(self, event):
        app = QApplication.instance()
        visible = getattr(app, '_spring_visible_dialogs', None)
        if visible is None:
            visible = app._spring_visible_dialogs = []
        if self in visible:
            visible.remove(self)
        visible.append(self)
        self._exit_pending = False
        from .presentation import prepare_controls
        prepare_controls(self)
        from ..app.window_constraints import constrain
        constrain(self, within_parent=True)
        if getattr(self, "_applied_theme_key", None) != theme_key():
            self.refresh_theme_palette()
        apply_ui_language(self, current_language())
        parent = self.parentWidget()
        if self._use_backdrop and parent is not None and self._modal_backdrop is None:
            host = parent.window()
            theme = _active_theme()
            backdrop = _FadingBackdrop(host, theme.media)
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
            from . import motion_tokens as tokens
            from .transitions import handles, stage_cover
            self._modal_backdrop = backdrop
            if self.UNIFIED_TRANSITION:
                cover = stage_cover(host)
                if cover is not None:
                    cover.stack_over_owner()
                    backdrop.shade = _SettingsShade(backdrop, cover)
                backdrop.flight_owned = handles(self)
            backdrop.show()
            backdrop.raise_()
            if not backdrop.flight_owned:
                backdrop.fade_to(_FadingBackdrop.ALPHA,
                                 tokens.SETTINGS_TRANSITION if self.UNIFIED_TRANSITION else tokens.SCRIM_IN)
        self._apply_native_window_style()
        super().showEvent(event)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.update()
        # 2026-11-18: when the app-wide dialog motion (design.transitions) grows this dialog out of
        # its button, the old fade-and-rise stands down and the opacity is left to it.
        from .transitions import handles
        if handles(self):
            return
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
        from .transitions import animate_done, closing_now, handles
        if animate_done(self, result):
            return
        if self.isVisible() and handles(self) and not getattr(self, "_exit_pending", False):
            # 2026-11-19 (user: closing the settings flashes): the shrinking picture is up before
            # the window hides, so Home never shows between the two.
            closing_now(self)
        duration = motion_duration(MOTION_FAST_MS) if self.EXIT_ANIMATED and not handles(self) else 0
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
        visible = getattr(QApplication.instance(), '_spring_visible_dialogs', ())
        if self in visible:
            visible.remove(self)
        if self._modal_backdrop is not None:
            backdrop, self._modal_backdrop = self._modal_backdrop, None
            try:
                backdrop.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                if backdrop.alpha <= 0:
                    backdrop.retire()
                elif backdrop.flight_owned:
                    pass  # The dialog flight releases the shade on its last frame.
                elif not QApplication.closingDown():
                    from . import motion_tokens as tokens
                    backdrop.fade_to(0.0, tokens.SETTINGS_TRANSITION if self.UNIFIED_TRANSITION else tokens.SCRIM_OUT,
                                     then=backdrop.retire)
                else:
                    backdrop.retire()
            except Exception:
                pass
        super().hideEvent(event)
