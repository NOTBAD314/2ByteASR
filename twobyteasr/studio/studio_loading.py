"""The light Studio loading surface and its request-scoped progress owner."""
from __future__ import annotations
from collections import deque
from contextlib import nullcontext
from pathlib import Path
import sys
import time
import weakref
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRegion
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QProgressBar, QVBoxLayout, QHBoxLayout, QWidget
from ..i18n import bind_text

TASKS = ('创建工作台界面', '读取工程', '建立时间轴', '准备播放器', '准备音频', '准备字幕', '首屏绘制')
NATIVE_COVER_PENDING_TIMEOUT_MS = 3000  # Failure watchdog, never a successful-handoff delay.

class ReadinessSteps(QWidget):
    """The real opening stages: done ✓, current ●, waiting ○, failed ✕."""

    ROW = 30

    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.tasks = tuple(tasks)
        self.completed: set[str] = set()
        self.current = ''
        self.failed = ''
        self.skipped = {}
        self.setMinimumHeight(self.ROW * len(self.tasks))

    def sizeHint(self):
        return QSize(360, self.ROW * len(self.tasks))

    def set_state(self, completed, current='', failed=''):
        self.completed, self.current, self.failed = set(completed), str(current or ''), str(failed or '')
        self.update()

    def paintEvent(self, _event):
        from ..i18n import current_language, translate
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        theme = theme_definition(theme_key())
        language = current_language()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, task in enumerate(self.tasks):
            top = index * self.ROW
            dot = QRectF(4, top + (self.ROW - 16) / 2, 16, 16)
            if task == self.failed:
                state, color = 'failed', QColor(theme.danger)
            elif task in self.completed:
                state, color = 'done', QColor(theme.success)
            elif task == self.current:
                state, color = 'active', QColor(theme.accent_text)
            else:
                state, color = 'waiting', QColor(theme.border_strong)
            if state == 'waiting':
                painter.setPen(QPen(color, 1.6))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(dot.adjusted(1.5, 1.5, -1.5, -1.5))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(dot)
                painter.setPen(QPen(QColor(theme.on_vivid), 1.8, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                c = dot.center()
                if state == 'done':
                    painter.drawLine(c.x() - 3.8, c.y() + 0.2, c.x() - 1.0, c.y() + 3.0)
                    painter.drawLine(c.x() - 1.0, c.y() + 3.0, c.x() + 4.0, c.y() - 2.6)
                elif state == 'failed':
                    painter.drawLine(c.x() - 3, c.y() - 3, c.x() + 3, c.y() + 3)
                    painter.drawLine(c.x() - 3, c.y() + 3, c.x() + 3, c.y() - 3)
                else:
                    painter.setBrush(QColor(theme.on_vivid))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(c, 3, 3)
            font = QFont(self.font())
            font.setPixelSize(14)
            font.setWeight(QFont.Weight.DemiBold if state == 'active' else QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor(theme.text if state in {'active', 'failed'} else
                                  theme.text_secondary if state == 'done' else theme.text_muted))
            label = translate(task, language) if language != 'zh' else task
            if task in self.skipped:
                label += ' · ' + (translate('无需准备', language) if language != 'zh' else '无需准备')
            painter.drawText(QRectF(32, top, self.width() - 32, self.ROW),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)


class StudioLoadingView(QFrame):
    """One light card, used as a real page by the main-window owner."""
    painted = Signal()
    geometry_changed = Signal()
    native_cover_changed = Signal()

    def __init__(self, host, coverage=None, *, page_stack=False, native_cover=False, owner=None):
        from ..design.native_loading_cover import native_cover_supported
        cover_owner = owner if isinstance(owner, QWidget) else host.window()
        use_cover = bool(native_cover and native_cover_supported(cover_owner))
        if use_cover:
            host, coverage, page_stack = cover_owner, cover_owner, False
        super().__init__(host)
        self.native_cover_requested = bool(native_cover)
        self.native_cover_owner = cover_owner
        self.uses_native_cover = use_cover
        self.coverage = coverage or host
        self.page_stack = bool(page_stack)
        self._cover_painted_region = QRegion()
        self._cover_painted_stamp = self._cover_submitted_stamp = None
        self.setObjectName('studioLoadingSurface')
        if self.uses_native_cover:
            # The format is immutable once the native resource exists.
            # This order requests alpha for this child, never for its root.
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
            self.painted.connect(self._confirm_native_paint, Qt.ConnectionType.QueuedConnection)
        elif not self.page_stack:
            self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, sys.platform == 'win32')
            self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._surface_background = QColor('#18171c')
        outer = QVBoxLayout(self)
        self.window_title_bar = None
        if self.uses_native_cover:
            from ..app.window_chrome_widgets import WindowTitleBar
            self.window_title_bar = WindowTitleBar(self.native_cover_owner)
            self.window_title_bar.setParent(self)
            outer.addWidget(self.window_title_bar)
        outer.addStretch(1)
        self.card = QFrame(self)
        self.card.setObjectName('studioLoadingCard')
        self.card.setFixedWidth(460)
        outer.addWidget(self.card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(14)
        self.icon = QLabel(self.card)
        self.icon.setObjectName('studioLoadingIcon')
        self.icon.setFixedSize(48, 48)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        title = QLabel(self.card)
        bind_text(title, '准备工作台')
        title.setObjectName('studioLoadingTitle')
        from ..design.elided_label import ElidedLabel
        self.project_name = ElidedLabel('', self.card, minimum=40)
        self.project_name.setObjectName('studioLoadingProject')
        heading.addWidget(title)
        heading.addWidget(self.project_name)
        head.addLayout(heading, 1)
        layout.addLayout(head)
        self.bar = QProgressBar(self.card)
        self.bar.setRange(0, len(TASKS))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar)
        self.steps_view = ReadinessSteps(TASKS, self.card)
        layout.addWidget(self.steps_view)
        self.label = QLabel('', self.card)
        self.label.setObjectName('studioLoadingStatus')
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch()
        self.back = QPushButton(self.card)
        self.back.setObjectName('studioLoadingBack')
        self.copy_error = QPushButton(self.card)
        bind_text(self.copy_error, '复制错误信息')
        self.copy_error.setObjectName('studioLoadingCopyError')
        self.copy_error.clicked.connect(lambda: QApplication.clipboard().setText(self.label.text()))
        self.retry = QPushButton(self.card)
        bind_text(self.retry, '重试')
        self.retry.setObjectName('studioLoadingRetry')
        for button in (self.back, self.copy_error, self.retry):
            actions.addWidget(button)
        layout.addLayout(actions)
        host.installEventFilter(self)
        if self.coverage is not host:
            self.coverage.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched, event):
        if (self.page_stack and watched is self.parentWidget()
                and event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest)):
            # The owner commits hidden-page geometry after the stack has
            # handled this event. The view never sizes or reveals Studio.
            self.geometry_changed.emit()
        if watched in (self.parentWidget(), self.coverage) and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.sync_geometry()
        if self.uses_native_cover and watched is self.native_cover_owner:
            if event.type() == QEvent.Type.WindowStateChange and self.window_title_bar is not None:
                self.window_title_bar.sync_window_state()
                self.native_cover_changed.emit()
            elif event.type() == QEvent.Type.Show:
                self.native_cover_changed.emit()
        return False

    def sync_geometry(self):
        if self.page_stack:
            return  # The owner's StackOne layout owns the page rectangle.
        host = self.parentWidget()
        origin = self.coverage.mapTo(host, QPoint()) if self.coverage is not host else QPoint()
        self.setGeometry(QRect(origin, self.coverage.size()))

    def _cover_stamp(self):
        from ..design.native_loading_cover import existing_handle
        return (existing_handle(self), existing_handle(self.native_cover_owner),
                tuple(self.geometry().getRect()), tuple(self.native_cover_owner.rect().getRect()),
                float(self.devicePixelRatioF()))

    def _invalidate_native_paint(self):
        if self.uses_native_cover:
            self._cover_painted_region = QRegion()
            self._cover_painted_stamp = self._cover_submitted_stamp = None
            self.native_cover_changed.emit()

    def resizeEvent(self, event):
        self._invalidate_native_paint()
        super().resizeEvent(event)

    def hideEvent(self, event):
        self._invalidate_native_paint()
        super().hideEvent(event)

    def _confirm_native_paint(self, *, notify=True):
        if (self.uses_native_cover and self.isVisible()
                and self._cover_painted_stamp == self._cover_stamp()
                and QRegion(self.rect()).subtracted(self._cover_painted_region).isEmpty()):
            self._cover_submitted_stamp = self._cover_painted_stamp
        if notify:
            self.native_cover_changed.emit()

    def native_cover_state(self):
        from ..design.native_loading_cover import native_cover_state
        complete = bool(self.uses_native_cover and self._cover_submitted_stamp is not None
                        and self._cover_submitted_stamp == self._cover_stamp())
        return native_cover_state(self, self.native_cover_owner,
            requested=self.native_cover_requested, supported=self.uses_native_cover,
            complete_paint=complete, opaque_background=self._surface_background.alpha() == 255)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._surface_background)
        painter.end()
        super().paintEvent(event)
        if self.uses_native_cover:
            stamp = self._cover_stamp()
            if stamp != self._cover_painted_stamp:
                self._cover_painted_region = QRegion()
                self._cover_submitted_stamp = None
            self._cover_painted_stamp = stamp
            self._cover_painted_region |= event.region().intersected(QRegion(self.rect()))
        self.painted.emit()

    def fit_card(self):
        layout = self.card.layout()
        width = self.card.width()
        height = layout.totalHeightForWidth(width) if layout.hasHeightForWidth() else layout.totalSizeHint().height()
        if height > 0:
            self.card.setMinimumHeight(height)

    def apply_theme(self):
        from ..design.theme_manager import theme_key, theme_definition
        theme = theme_definition(theme_key())
        self._surface_background = QColor(theme.app_background)
        if self.uses_native_cover:
            self._surface_background.setAlpha(255)
        background = self._surface_background.name() if self.uses_native_cover else theme.app_background
        self._invalidate_native_paint()
        self.setStyleSheet(
            f'QFrame#studioLoadingSurface {{background:{background};}}'
            f'QFrame#studioLoadingCard {{background:{theme.surface};border:1px solid {theme.border};border-radius:16px;}}'
            f'QLabel {{color:{theme.text};background:transparent;}}'
            f'QLabel#studioLoadingIcon {{background:{theme.accent_tint};border-radius:12px;}}'
            f'QLabel#studioLoadingTitle {{font-size:18px;font-weight:600;}}'
            f'QLabel#studioLoadingProject {{color:{theme.text_secondary};font-size:13px;}}'
            f'QLabel#studioLoadingStatus {{color:{theme.text_muted};font-size:13px;}}'
            f'QProgressBar {{border:0;background:{theme.panel};border-radius:3px;}}'
            f'QProgressBar::chunk {{background:{theme.accent};border-radius:3px;}}'
            f'QPushButton {{background:transparent;color:{theme.text_secondary};border:1px solid {theme.border_strong};border-radius:8px;padding:6px 16px;}}'
            f'QPushButton:hover {{background:{theme.selected};color:{theme.text};}}'
            f'QPushButton#studioLoadingRetry {{background:{theme.accent};color:{theme.text_on_accent};border:0;font-weight:600;}}'
            + ('QFrame#windowTitleBar {background:transparent;border:0;}'
               'QPushButton#windowControl,QPushButton#windowControlClose '
               '{padding:0;min-width:30px;max-width:30px;min-height:22px;max-height:22px;border:0;}'
               if self.uses_native_cover else ''))
        import qtawesome as qta
        self.icon.setPixmap(qta.icon('fa5s.closed-captioning', color=theme.accent_text).pixmap(QSize(22, 22)))


class StudioLoadingSession(QObject):
    """Own request identity, progress and delivery of the persistent loading view.

    Workers and builders report to this request; only its owner navigates.
    A StudioReadiness gate may attach after construction without resetting it.
    """
    changed = Signal()

    def __init__(self, host, owner=None, *, coverage=None, page_stack=False,
                 native_cover=False, input_host=None):
        super().__init__(owner or host)
        from ..design.native_loading_cover import InputHostLease
        self.native_cover_requested = bool(native_cover)
        self.view = StudioLoadingView(host, coverage, page_stack=page_stack,
                                      native_cover=native_cover, owner=owner)
        self.uses_native_cover = self.view.uses_native_cover
        self._input_lease = InputHostLease(input_host)
        self._input_host_requested = input_host is not None
        self._native_input_ready = input_host is None
        self._native_present_pending = None
        self._native_cover_fault = ''
        self._native_pending_token = None
        self._native_callback_complete = False
        self._native_waiting_owner = False
        self._native_cover_authorized_generation = None
        self.on_present = None
        self.on_reveal = None
        self.on_retired = None
        self.handoff_scope = None
        self.generation = 0
        self.active = False
        self.state = 'idle'
        self.path = ''
        self.completed = set()
        self.events = deque(maxlen=256)
        self.started = time.perf_counter()
        self.deliveries = 0
        self.on_cancel = self.on_retry = None
        self.return_target = 'home'
        self._surfaces = []
        self.view.back.clicked.connect(self.request_cancel)
        self.view.retry.clicked.connect(self.request_retry)
        if self.uses_native_cover:
            self.view.native_cover_changed.connect(self._native_cover_updated)
            self.destroyed.connect(self._input_lease.release)
            self.destroyed.connect(self.view.deleteLater)

    def _record(self, event, **fields):
        row = dict(event=event, generation=self.generation, elapsed_ms=round((time.perf_counter()-self.started)*1000, 3), **fields)
        self.events.append(row)
        from ..diagnostics.event_log import emit
        emit('studio.loading', result=event, component='studio_loading',
             request_id=f'load-{id(self):x}-{self.generation}', **row)
        self.changed.emit()

    def attach_surface(self, video):
        from .studio_video_canvas import MpvCanvas
        page = video._studio_page()
        surfaces = page.findChildren(MpvCanvas) if page is not None else [video]
        self._surfaces = [weakref.ref(item) for item in surfaces]
        self._sync_surface()

    def _sync_surface(self):
        from shiboken6 import isValid
        blocked = self.state in {'preparing', 'failed'}
        authorized = self._native_cover_authorized_generation == self.generation
        if (self.uses_native_cover and self.state == 'preparing' and not authorized
                and not self._native_cover_fault):
            # No new editor/IO has been exposed yet. Do not blank the previous
            # owner's frame during theme setup or the cover's first paint.
            return
        covered = bool(self.uses_native_cover and self.state == 'preparing' and authorized
                       and self.native_cover_state()['verified'])
        for reference in self._surfaces:
            video = reference()
            if video is not None and isValid(video):
                exempt = covered and video.window() is self.view.native_cover_owner
                video.set_presentation_blocked('loading', blocked and not exempt)

    def native_cover_state(self):
        result = dict(self.view.native_cover_state())
        result.update(uses_native_cover=self.uses_native_cover, generation=self.generation,
                      input_host_requested=self._input_host_requested,
                      input_lease_held=self._input_lease.held, input_ready=self._native_input_ready,
                      surface_release_authorized=self._native_cover_authorized_generation == self.generation)
        if self.uses_native_cover and not self._native_input_ready:
            result['verified'] = False
            result['reasons'] = [*result['reasons'], 'input host not protected']
        if self._native_cover_fault:
            result['verified'] = False
            result['reasons'] = [*result['reasons'], self._native_cover_fault]
        result['status'] = ('failed' if self._native_cover_fault else
            'verified' if result['verified'] else
            'inactive' if self.uses_native_cover and self.state not in {'preparing', 'failed'} else
            'waiting_for_visible_owner' if self._native_waiting_owner else
            'pending' if self.uses_native_cover else
            'unsupported' if self.native_cover_requested else 'not_requested')
        return result

    def _arm_native_cover_timeout(self):
        token, generation = object(), self.generation
        self._native_pending_token = token
        self._native_waiting_owner = False
        QTimer.singleShot(NATIVE_COVER_PENDING_TIMEOUT_MS, self,
                         lambda: self._native_cover_timeout(token, generation))

    def _native_cover_timeout(self, token, generation):
        if (token is not self._native_pending_token or generation != self.generation
                or self._native_present_pending != generation or self._native_cover_fault
                or self.state not in {'preparing', 'failed'}):
            return
        owner = self.view.native_cover_owner
        if not owner.isVisible() or owner.isMinimized():
            self._native_waiting_owner = True
            return  # An intentional minimized window resumes on its Show/state event.
        try:
            if self._present_behind_native_cover(generation):
                self._sync_surface()
                return
        except Exception as error:
            if generation == self.generation:
                self._recover_native_cover(error)
            return
        if token is self._native_pending_token and generation == self.generation:
            self._recover_native_cover('载入界面未能完成准备，请重试。')

    def _native_cover_updated(self):
        generation = self.generation
        if (self.uses_native_cover and not self._native_cover_fault and self.view.isVisible()
                and self.state in {'preparing', 'failed'}):
            if (self._native_present_pending is None and self._native_callback_complete
                    and not self.view.native_cover_state()['verified']):
                self._native_present_pending = generation
                self._arm_native_cover_timeout()
            elif (self._native_waiting_owner and self.view.native_cover_owner.isVisible()
                    and not self.view.native_cover_owner.isMinimized()):
                self._arm_native_cover_timeout()
        try:
            if self._native_present_pending == self.generation and self.state in {'preparing', 'failed'}:
                self._present_behind_native_cover(self.generation)
        except Exception as error:
            if generation == self.generation:
                self._recover_native_cover(error)
        self._sync_surface()

    def _present_behind_native_cover(self, generation):
        if (self._native_cover_fault or generation != self.generation
                or not self.view.native_cover_state()['verified']):
            return False
        input_ready = self._input_lease.acquire(self.view.native_cover_owner, self.view)
        if generation != self.generation:
            return False
        self._native_input_ready = input_ready
        if not self._native_input_ready:
            self._recover_native_cover('输入区域不属于当前窗口，无法保护准备中的工作台')
            return False
        if not self.view.native_cover_state()['verified']:
            return False  # Disabling input may have changed the owner's layout.
        self._native_present_pending = None
        invoke = not self._native_callback_complete
        self._native_callback_complete = True
        self._native_cover_authorized_generation = generation
        self._sync_surface()
        if generation != self.generation:
            return False
        if invoke and callable(self.on_present):
            self.on_present()
        if generation != self.generation:
            return False
        # Showing the editor may have raised its native ancestors above us.
        self.view.raise_()
        self.view.repaint()
        self.view._confirm_native_paint(notify=False)
        verified = self.native_cover_state()['verified']
        if verified:
            self._native_present_pending = None
            self._native_pending_token = None
            self._native_waiting_owner = False
        else:
            self._native_present_pending = generation
        return verified

    def _recover_native_cover(self, error):
        """Keep the same cover after a handoff callback fails; never recurse into present."""
        generation = self.generation
        self._native_cover_fault = str(error)
        self._native_present_pending = None
        self._native_pending_token = None
        self._native_waiting_owner = False
        self.state, self.active = 'failed', False
        input_ready = self._input_lease.acquire(self.view.native_cover_owner, self.view)
        if generation != self.generation:
            return
        self._native_input_ready = input_ready
        self.view.steps_view.set_state(self.completed, '', '首屏绘制')
        bind_text(self.view.label, '准备工作台失败\n{error}', error=str(error))
        self.view.retry.setVisible(callable(self.on_retry))
        self.view.copy_error.show()
        self.view.fit_card()
        self.view.sync_geometry()
        self.view.show()
        self.view.raise_()
        self.view.repaint()
        self.view._confirm_native_paint(notify=False)
        if generation != self.generation:
            return
        self._block_surfaces('loading', True)
        self._record('native_cover_failed', error=str(error))

    def hold_navigation(self):
        self._block_surfaces('navigation', True)

    def _block_surfaces(self, reason, blocked):
        from shiboken6 import isValid
        for reference in self._surfaces:
            video = reference()
            if video is not None and isValid(video):
                video.set_presentation_blocked(reason, blocked)

    def begin(self, path, *, on_cancel=None, on_retry=None, return_target='home', present=True):
        self.generation += 1
        self._native_cover_fault = ''
        self._native_present_pending = None
        self._native_pending_token = None
        self._native_callback_complete = False
        self._native_waiting_owner = False
        self._native_cover_authorized_generation = None
        self._native_input_ready = not self._input_host_requested or self._input_lease.held
        self.path = str(path or '')
        self.state, self.active = 'preparing', True
        self.started = time.perf_counter()
        self.completed = set()
        self.events.clear()
        self.deliveries = 0
        self.on_cancel, self.on_retry = on_cancel, on_retry
        self.return_target = return_target
        self.view.bar.setValue(0)
        self.view.project_name.setText(Path(path).stem if path else '工程库')
        bind_text(self.view.back, '返回工程库' if return_target == 'hub' else '返回主页')
        self.view.retry.hide()
        self.view.copy_error.hide()
        self.view.steps_view.skipped = {}
        self.view.apply_theme()
        self.stage('创建工作台界面')
        self._record('begin')
        if present:
            self.present()
        return self.generation

    def present(self):
        """Paint the complete cover before withdrawing native video pixels."""
        if self.uses_native_cover:
            generation = self.generation
            self._native_present_pending = generation
            self._native_callback_complete = False
            self._arm_native_cover_timeout()
            self.view.sync_geometry()
            self.view.show()
            self.view.raise_()
            self.view.repaint()
            self.view._confirm_native_paint(notify=False)
            try:
                presented = self._present_behind_native_cover(generation)
            except Exception as error:
                if generation == self.generation:
                    self._recover_native_cover(error)
                raise
            self._sync_surface()
            return presented
        if callable(self.on_present):
            self.on_present()
        self.view.sync_geometry()
        self.view.show()
        self.view.raise_()
        self.view.repaint()
        self._sync_surface()
        return True

    def _retire_view(self):
        if self.uses_native_cover:
            generation = self.generation
            self._native_present_pending = None
            self._native_pending_token = None
            self._native_waiting_owner = False
            self.view.hide()
            if generation != self.generation:
                return
            self._input_lease.release()
            if generation != self.generation:
                return
            self._native_input_ready = not self._input_host_requested
            try:
                if callable(self.on_retired):
                    self.on_retired()
            except Exception as error:
                if generation == self.generation:
                    self._recover_native_cover(error)
                raise
            self._sync_surface()
            return
        visible = self.view.isVisible()
        self.view.hide()
        if visible:
            # Hide invalidates the backing store. Flush that transition before
            # releasing native video, including dirty-guard rejection/reuse.
            self.view.coverage.repaint()
        if callable(self.on_retired):
            self.on_retired()
        self._sync_surface()

    def _hold_native_visibility(self):
        return self.handoff_scope() if callable(self.handoff_scope) else nullcontext()

    def stage(self, stage, detail=''):
        if not self.active:
            return
        task = stage if stage in TASKS else ('建立时间轴' if stage.startswith(('恢复', '建立')) else '准备字幕')
        from ..i18n import tr
        self.view.label.setText(f"{tr(stage)}{(' · ' + tr(detail)) if detail else ''} · {time.perf_counter()-self.started:.1f}s")
        self.view.steps_view.set_state(self.completed, task)
        self.view.fit_card()
        if not self.events or self.events[-1].get('stage') != stage or self.events[-1].get('detail') != detail:
            self._record('stage', stage=stage, detail=detail)

    def mark(self, stage):
        if self.active and stage not in self.completed:
            self.completed.add(stage)
            self.view.bar.setValue(len(self.completed))
            self.view.steps_view.set_state(self.completed, self.view.steps_view.current)
            self._record('complete_stage', stage=stage)

    def fail(self, stage, error):
        if not self.active:
            return
        self.state, self.active = 'failed', False
        self.view.steps_view.set_state(self.completed, '', stage)
        bind_text(self.view.label, '{stage}失败\n{error}\n工程文件仍保留，可重试载入：\n{value2}', stage=stage, error=error, value2=self.path)
        self.view.retry.show()
        self.view.copy_error.show()
        self.view.fit_card()
        self.present()
        self._record('failed', stage=stage, error=str(error))

    def skip(self, stage, reason):
        if self.active:
            self.view.steps_view.skipped[stage] = str(reason)
            self.mark(stage)
            self._record('skipped', stage=stage, reason=str(reason))

    def deliver(self, generation):
        if not self.active or generation != self.generation or self.deliveries:
            return False
        with self._hold_native_visibility():
            try:
                if callable(self.on_reveal):
                    self.on_reveal()
            except Exception as error:
                if generation == self.generation and self.active:
                    if self.uses_native_cover:
                        self._recover_native_cover(error)
                    elif callable(self.on_present):
                        self.on_present()
                raise
            if generation != self.generation or not self.active:
                return False
            self.state, self.active = 'ready', False
            self._retire_view()
        if generation != self.generation or self.state != 'ready':
            return False
        self.deliveries += 1
        self._record('delivered')
        return True

    def resume_ready(self, path):
        """Bind a retained, already verified editor after another open was cancelled.

        No loading view or second delivery is needed. A fresh identity still
        retires results belonging to the cancelled request.
        """
        self.generation += 1
        generation = self.generation
        self._native_cover_fault = ''
        self.path = str(path)
        self.state, self.active = 'ready', False
        self.completed = set(TASKS)
        self.on_retry = None
        with self._hold_native_visibility():
            self._retire_view()
        if generation != self.generation:
            return generation
        self._record('resumed')
        return generation

    def abort(self, *, reveal=None):
        self.generation += 1
        self._native_cover_fault = ''
        generation = self.generation
        self.state, self.active = 'cancelled', False
        with self._hold_native_visibility():
            if callable(reveal):
                reveal()
            if generation != self.generation:
                return
            self._retire_view()
        if generation != self.generation:
            return
        self.on_retry = None
        self._record('cancelled')

    def request_cancel(self):
        callback = self.on_cancel
        if callable(callback):
            callback()
        else:
            self.abort()

    def request_retry(self):
        if self.state == 'failed' and callable(self.on_retry):
            self.on_retry()

    def snapshot(self):
        return dict(generation=self.generation, state=self.state, completed=sorted(self.completed),
                    deliveries=self.deliveries, events=list(self.events))
