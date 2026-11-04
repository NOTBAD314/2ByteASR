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
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QStackedLayout, QVBoxLayout, QHBoxLayout, QWidget
from ..i18n import bind_text
from .loading_faces import ReadinessSteps

TASKS = ('创建工作台界面', '读取工程', '建立时间轴', '准备播放器', '准备音频', '准备字幕', '首屏绘制')
NATIVE_COVER_PENDING_TIMEOUT_MS = 3000  # Failure watchdog, never a successful-handoff delay.

LIBRARY_TASKS = ('搭工作台框架', '装工具面板', '铺时间轴', '摆工程库', '读取工程列表')
# The workspace builder's progress names (SubtitleStudioPage deferred build),
# in order, grouped into the library face's first four steps.
LIBRARY_BUILD_PARTS = (
    ('工作台工具栏', 0), ('字幕列表', 0), ('视频承载区', 0), ('字幕编辑区', 0),
    ('AI 工具', 1), ('字幕样式', 1), ('动效面板', 1), ('视频面板', 1), ('剪辑助手面板', 1), ('素材面板', 1), ('工具面板', 1),
    ('时间轴工具栏', 2), ('时间轴', 2),
    ('工程库布局', 3), ('工程库标题', 3), ('工程库导航', 3),
)


def library_step_state(completed, detail=''):
    """(done groups, current group) of the library face from the real build reports."""
    if '首屏绘制' in completed:
        return set(LIBRARY_TASKS), ''
    if '创建工作台界面' in completed:
        return set(LIBRARY_TASKS[:4]), LIBRARY_TASKS[4]
    names = [name for name, _group in LIBRARY_BUILD_PARTS]
    built = set(names[:names.index(detail) + 1]) if detail in names else set()
    done = {LIBRARY_TASKS[group] for group in range(4)
            if all(name in built for name, owner in LIBRARY_BUILD_PARTS if owner == group)}
    current = next((task for task in LIBRARY_TASKS if task not in done), '')
    return done, current


class StudioLoadingView(QFrame):
    """The loading page: a poster for a project, the bunny and recent projects for the library.

    2026-11-02 redesign (user-approved drafts B and library 3). ``card`` stays
    the same object for the whole request; the shared status label and
    buttons move between the two faces.
    """
    painted = Signal()
    geometry_changed = Signal()
    native_cover_changed = Signal()
    pick_changed = Signal()

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
        self.library_mode = False
        self._ambient = None
        self._line_key = ''
        self._progress_signature = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.window_title_bar = None
        if self.uses_native_cover:
            from ..app.window_chrome_widgets import WindowTitleBar
            self.window_title_bar = WindowTitleBar(self.native_cover_owner)
            self.window_title_bar.setParent(self)
            outer.addWidget(self.window_title_bar)
        outer.addStretch(1)
        self.card = QFrame(self)
        self.card.setObjectName('studioLoadingCard')
        outer.addWidget(self.card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self.faces = QStackedLayout(self.card)
        self._build_project_face()
        self._build_library_face()
        self.faces.addWidget(self.project_face)
        self.faces.addWidget(self.library_face)
        # Shared status and actions; parented to whichever face is showing.
        self.icon = QLabel(self.card)  # Kept for callers; the faces carry the art.
        self.icon.hide()
        self.label = QLabel('', self.card)
        self.label.setObjectName('studioLoadingStatus')
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
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
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        from ..design.bunny_mascot import BunnyMascot
        self.perch = BunnyMascot(self, height=150, motion='bob')
        self.perch.setVisible(self.perch.available)
        self.card.installEventFilter(self)
        self._seat_shared(library=False)
        host.installEventFilter(self)
        if self.coverage is not host:
            self.coverage.installEventFilter(self)
        self.hide()

    # ------------------------------------------------------------ the faces
    def _build_project_face(self):
        from .loading_faces import CoverPane, ReadinessSteps
        from ..design.elided_label import ElidedLabel
        face = self.project_face = QFrame(self.card)
        face.setObjectName('studioLoadingPoster')
        row = QHBoxLayout(face)
        row.setContentsMargins(0, 0, 30, 24)
        row.setSpacing(8)
        self.cover = CoverPane(face)
        self.bar = self.cover.scrubber
        self.bar.setRange(0, len(TASKS))
        row.addWidget(self.cover, 122)
        info = QVBoxLayout()
        info.setContentsMargins(8, 32, 0, 0)
        info.setSpacing(0)
        self.eyebrow = QLabel(face)
        self.eyebrow.setObjectName('studioLoadingEyebrow')
        info.addWidget(self.eyebrow, 0, Qt.AlignmentFlag.AlignLeft)
        info.addSpacing(14)
        self.project_name = ElidedLabel('', face, minimum=40)
        self.project_name.setObjectName('studioLoadingProject')
        info.addWidget(self.project_name)
        info.addSpacing(12)
        self.meta_row = QHBoxLayout()
        self.meta_row.setSpacing(6)
        self.meta_chips = []
        for _index in range(3):
            chip = QLabel(face)
            chip.setObjectName('studioLoadingChip')
            chip.hide()
            self.meta_chips.append(chip)
            self.meta_row.addWidget(chip)
        self.meta_row.addStretch(1)
        info.addLayout(self.meta_row)
        info.addSpacing(20)
        self.steps_view = ReadinessSteps(TASKS, face)
        info.addWidget(self.steps_view)
        info.addStretch(1)
        self.project_status = QVBoxLayout()
        self.project_status.setSpacing(12)
        info.addLayout(self.project_status)
        self.project_actions = QHBoxLayout()
        self.project_actions.setSpacing(8)
        self.project_actions.addStretch(1)
        info.addSpacing(10)
        info.addLayout(self.project_actions)
        row.addLayout(info, 100)

    def _build_library_face(self):
        from .loading_faces import ReadinessSteps, RecentFan
        from ..design.bunny_mascot import BunnyMascot
        face = self.library_face = QFrame(self.card)
        face.setObjectName('studioLoadingLibrary')
        row = QHBoxLayout(face)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(40)
        left = QVBoxLayout()
        left.setSpacing(0)
        left.addStretch(1)
        who = QHBoxLayout()
        who.setSpacing(0)
        self.library_bunny = BunnyMascot(face, height=170, motion='bob')
        self.library_bunny.setVisible(self.library_bunny.available)
        who.addWidget(self.library_bunny, 0, Qt.AlignmentFlag.AlignBottom)
        self.bubble = QLabel(face)
        self.bubble.setObjectName('studioLoadingBubble')
        who.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignTop)
        who.addStretch(1)
        who_box = QVBoxLayout()
        who_box.setContentsMargins(0, 0, 0, 0)
        who_box.addLayout(who)
        left.addLayout(who_box)
        left.addSpacing(10)
        self.library_title = QLabel(face)
        bind_text(self.library_title, '正在打开工程库')
        self.library_title.setObjectName('studioLoadingLibraryTitle')
        left.addWidget(self.library_title)
        left.addSpacing(6)
        self.library_status = QVBoxLayout()
        left.addLayout(self.library_status)
        left.addSpacing(18)
        self.library_steps = ReadinessSteps(LIBRARY_TASKS, face, compact=True)
        self.library_steps.setFixedWidth(340)
        left.addWidget(self.library_steps)
        left.addSpacing(16)
        self.library_actions = QHBoxLayout()
        self.library_actions.setSpacing(8)
        self.library_actions.addStretch(1)
        left.addLayout(self.library_actions)
        left.addStretch(1)
        left_host = QWidget(face)
        left_host.setLayout(left)
        left_host.setFixedWidth(420)
        row.addWidget(left_host)
        panel = self.recent_panel = QFrame(face)
        panel.setObjectName('studioLoadingRecent')
        column = QVBoxLayout(panel)
        column.setContentsMargins(28, 24, 28, 24)
        header = QHBoxLayout()
        title = QLabel(panel)
        bind_text(title, '最近编辑')
        title.setObjectName('studioLoadingRecentTitle')
        header.addWidget(title)
        header.addStretch(1)
        column.addLayout(header)
        self.fan = RecentFan(panel)
        self.fan.picked.connect(lambda _index: self._sync_pick())
        column.addWidget(self.fan, 1)
        self.recent_empty = QLabel(panel)
        bind_text(self.recent_empty, '还没有工程。进入工程库后可以新建或导入。')
        self.recent_empty.setObjectName('studioLoadingRecentHint')
        self.recent_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.recent_empty, 1)
        footer = QHBoxLayout()
        self.recent_hint = QLabel(panel)
        bind_text(self.recent_hint, '点一张卡片，工作台好了就直接打开它；\n不选就照常进入工程库。')
        self.recent_hint.setObjectName('studioLoadingRecentHint')
        footer.addWidget(self.recent_hint, 1)
        self.pick_toggle = QPushButton(panel)
        self.pick_toggle.setObjectName('studioLoadingPick')
        self.pick_toggle.setCheckable(True)
        self.pick_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pick_toggle.toggled.connect(self._toggle_pick)
        footer.addWidget(self.pick_toggle)
        column.addLayout(footer)
        row.addWidget(panel, 1)

    def _seat_shared(self, *, library):
        """Move the status label and the three buttons into the visible face."""
        status = self.library_status if library else self.project_status
        actions = self.library_actions if library else self.project_actions
        for layout in (self.library_status, self.project_status, self.library_actions, self.project_actions):
            for widget in (self.label, self.back, self.copy_error, self.retry):
                layout.removeWidget(widget)
        status.addWidget(self.label)
        for index, button in enumerate((self.back, self.copy_error, self.retry)):
            if library:
                actions.insertWidget(index, button)
            else:
                actions.addWidget(button)

    def _toggle_pick(self, checked):
        self.fan.set_armed(checked)
        self._sync_pick()

    def _sync_pick(self):
        entry = self.fan.selected_entry()
        self.pick_toggle.blockSignals(True)
        self.pick_toggle.setChecked(self.fan.armed)
        self.pick_toggle.blockSignals(False)
        from ..i18n import tr
        self.pick_toggle.setText(('✓ ' if self.fan.armed else '') + tr('就绪后打开「{name}」', name=str(entry.get('name') or '')) if entry else '')
        self.pick_changed.emit()

    def picked_project(self) -> str:
        entry = self.fan.selected_entry() if self.library_mode and self.fan.armed else None
        return str(entry.get('path') or '') if entry else ''

    def set_mode(self, *, library: bool, path: str = '', entries=()):
        """Choose the face for a new request and fill it from the library records."""
        self.library_mode = bool(library)
        self.faces.setCurrentWidget(self.library_face if library else self.project_face)
        self._seat_shared(library=library)
        self.perch.setVisible(self.perch.available and not library)
        self.bar.reset_progress()
        self.cover.set_failed(False)
        self._line_key = ''
        self._progress_signature = None
        for mascot in (self.perch, self.library_bunny):
            mascot.set_mood('idle')
        self.steps_view.times, self.library_steps.times = {}, {}
        self.steps_view.reused, self.library_steps.reused = {}, {}
        self.steps_view.failed_detail = ''
        entries = [entry for entry in (entries or ()) if isinstance(entry, dict)]
        if library:
            self.fan.set_entries(entries)
            has = bool(entries)
            self.fan.setVisible(has)
            self.recent_empty.setVisible(not has)
            self.recent_hint.setVisible(has)
            self.pick_toggle.setVisible(has)
            self._sync_pick()
            self.library_steps.set_state((), LIBRARY_TASKS[0])
        else:
            self._fill_poster(path, entries)
        self._ambient = None
        self.fit_card()
        self.update()

    def _fill_poster(self, path, entries):
        from ..i18n import tr
        key = str(Path(path).resolve()).casefold() if path else ''
        entry = next((item for item in entries if item.get('path')
                      and str(Path(str(item['path'])).resolve()).casefold() == key), {})
        cover = str(entry.get('cover') or '')
        if not cover and path:
            canonical = Path(path).parent / 'preview' / 'project-cover.jpg'
            cover = str(canonical) if canonical.is_file() else ''
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap(cover) if cover and Path(cover).is_file() else QPixmap()
        self.cover.set_cover(pixmap)
        self.cover_pixmap = pixmap
        if entry.get('name'):
            self.project_name.setText(str(entry['name']))
        duration = int(entry.get('duration_ms') or 0)
        clock = ''
        if duration > 0:
            seconds = duration // 1000
            clock = (f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}' if seconds >= 3600
                     else f'{seconds // 60:02d}:{seconds % 60:02d}')
        self.cover.right_chip = clock
        self.cover.left_chip = tr('上次编辑 · {when}', when=entry['edited']) if entry.get('edited') else ''
        chips = []
        if entry.get('count'):
            chips.append(tr('{count} 条字幕', count=entry['count']))
        if clock:
            chips.append(clock)
        if entry.get('speakers'):
            chips.append(tr('{count} 位说话人', count=entry['speakers']))
        for chip, text in zip(self.meta_chips, chips + [''] * 3):
            chip.setText(text)
            chip.setVisible(bool(text))

    # ------------------------------------------------------------- updates
    def show_progress(self, completed, current, detail='', failed=''):
        """Mirror the session's real state onto the active face."""
        from ..i18n import current_language
        signature=(frozenset(completed),current,detail,failed,self.library_mode,current_language())
        if getattr(self,'_progress_signature',None)==signature:return
        self._progress_signature=signature
        from .loading_faces import FAILED_LINE, READY_LINE, STAGE_ICONS, STAGE_LINES, _tr
        from ..i18n import tr
        if self.library_mode:
            done, group = library_step_state(completed, detail)
            if failed:
                self.library_steps.set_state(done, '', group or LIBRARY_TASKS[0])
            else:
                self.library_steps.set_state(done, group)
            stage_for_line = group
            bind_text(self.library_title, '没能打开工程库' if failed else '正在打开工程库')
        else:
            stage_for_line = current
            self.bar.glyph = STAGE_ICONS.get(current, self.bar.glyph)
            self.bar.failed = bool(failed)
            self.bar.finished = len(completed) >= len(TASKS)
            self.bar.update()
        line = FAILED_LINE if failed else READY_LINE if not stage_for_line else STAGE_LINES.get(stage_for_line, '')
        mascot = self.library_bunny if self.library_mode else self.perch
        mascot.set_mood('sad' if failed else 'idle')
        if line != self._line_key:
            self._line_key = line
            if not failed:
                mascot.talk(.7)
            if self.library_mode:
                self.bubble.setText(_tr(line))
            else:
                self.cover.set_line(_tr(line))
        self.cover.set_failed(bool(failed) and not self.library_mode)
        state = 'failed' if failed else 'ready' if not current else 'loading'
        if self.eyebrow.property('state') != state:
            self.eyebrow.setProperty('state', state)
            self.eyebrow.setText('●  ' + (tr('没能打开') if failed else tr('准备好了') if state == 'ready'
                                          else tr('正在打开工程')))
            self.eyebrow.style().unpolish(self.eyebrow)
            self.eyebrow.style().polish(self.eyebrow)
        if self.label.property('failed') != bool(failed):
            self.label.setProperty('failed', bool(failed))
            self.label.setContentsMargins(*((14, 10, 14, 10) if failed else (0, 0, 0, 0)))
            self.label.style().unpolish(self.label)
            self.label.style().polish(self.label)

    # -------------------------------------------------------------- layout
    def eventFilter(self, watched, event):
        if watched is self.card and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self._place_perch()
            self._ambient = None
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

    def _place_perch(self):
        card = self.card.geometry()
        self.perch.move(card.right() - 64 - self.perch.width(), card.top() - self.perch.height() + 26)
        self.perch.raise_()

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
        self.fit_card()

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

    def _ambient_pixmap(self):
        """The poster's cover, blurred, as a soft glow behind the card."""
        pixmap = getattr(self, 'cover_pixmap', None)
        if self.library_mode or pixmap is None or pixmap.isNull() or self.width() <= 0:
            return None
        key = (pixmap.cacheKey(), self.width(), self.height())
        if self._ambient is None or self._ambient[0] != key:
            from PySide6.QtGui import QPixmap
            tiny = pixmap.scaled(32, 18, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            glow = tiny.scaled(self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
            self._ambient = (key, QPixmap(glow))
        return self._ambient[1]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._surface_background)
        glow = self._ambient_pixmap()
        if glow is not None:
            from .loading_faces import active_theme
            theme = active_theme()
            painter.setOpacity(.36 if theme.is_light else .5)
            painter.drawPixmap(QPoint((self.width() - glow.width()) // 2, (self.height() - glow.height()) // 2), glow)
            painter.setOpacity(1.0)
            from PySide6.QtGui import QRadialGradient
            vignette = QRadialGradient(QRectF(self.rect()).center(), max(self.width(), self.height()) * .62)
            clear = QColor(self._surface_background)
            clear.setAlpha(0)
            vignette.setColorAt(.35, clear)
            vignette.setColorAt(1, QColor(self._surface_background.red(), self._surface_background.green(),
                                          self._surface_background.blue(), 255))
            painter.fillRect(self.rect(), vignette)
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
        """Size the card to the window: a poster up to 1160×580, the library up to 1180×600."""
        title = self.window_title_bar.sizeHint().height() if self.window_title_bar is not None else 0
        width, height = self.width(), self.height() - title
        if width <= 0 or height <= 0:
            return
        if self.library_mode:
            size = QSize(max(820, min(1180, width - 100)), max(480, min(600, height - 120)))
        else:
            size = QSize(max(760, min(1160, width - 120)), max(460, min(580, height - 190)))
            failed = bool(self.label.text() and self.label.property('failed'))
            self.steps_view.set_dense(failed)
            info_width = max(1, (size.width() - 38) * 100 // 222 - 8)
            # The card keeps one size while loading; only a failure message grows it.
            status = self.label.heightForWidth(info_width) + 12 if failed else 32
            # Header (eyebrow, name, chips) + steps + status + actions + margins.
            needed = 200 + self.steps_view.minimumHeight() + status + 48 + 34
            size.setHeight(max(size.height(), min(height - 40, needed)))
        if self.card.size() != size:
            self.card.setFixedSize(size)
        self._place_perch()

    def apply_theme(self):
        from ..design.theme_manager import theme_key, theme_definition
        theme = theme_definition(theme_key())
        signature=(theme_key(),self.uses_native_cover)
        if getattr(self,'_applied_theme_signature',None)==signature:return
        self._applied_theme_signature=signature
        self._surface_background = QColor(theme.app_background)
        if self.uses_native_cover:
            self._surface_background.setAlpha(255)
        background = self._surface_background.name() if self.uses_native_cover else theme.app_background
        self._invalidate_native_paint()
        self._ambient = None
        self.setStyleSheet(
            f'QFrame#studioLoadingSurface {{background:{background};}}'
            'QFrame#studioLoadingCard, QFrame#studioLoadingLibrary {background:transparent;border:0;}'
            f'QFrame#studioLoadingPoster {{background:{theme.surface};border:1px solid {theme.border};border-radius:32px;}}'
            f'QFrame#studioLoadingRecent {{background:{theme.surface};border:1px solid {theme.border};border-radius:32px;}}'
            f'QLabel {{color:{theme.text};background:transparent;border:0;}}'
            f'QLabel#studioLoadingEyebrow {{color:{theme.accent_text};background:{theme.accent_soft};border-radius:13px;'
            'padding:4px 12px;font-size:12px;font-weight:700;}'
            f'QLabel#studioLoadingEyebrow[state="failed"] {{color:{theme.danger};background:{theme.danger_soft};}}'
            f'QLabel#studioLoadingEyebrow[state="ready"] {{color:{theme.success};}}'
            'QLabel#studioLoadingProject {font-size:28px;font-weight:900;}'
            f'QLabel#studioLoadingChip {{color:{theme.text_secondary};background:{theme.panel};border:1px solid {theme.border};'
            'border-radius:13px;padding:3px 11px;font-size:12px;}'
            f'QLabel#studioLoadingStatus {{color:{theme.text_muted};font-size:12px;}}'
            f'QLabel#studioLoadingStatus[failed="true"] {{color:{theme.text_secondary};background:{theme.danger_soft};'
            'border-radius:14px;padding:10px 14px;font-size:12px;}'
            'QLabel#studioLoadingLibraryTitle {font-size:30px;font-weight:900;}'
            f'QLabel#studioLoadingBubble {{background:{theme.surface};border:1px solid {theme.border};border-radius:18px;'
            'border-bottom-left-radius:6px;padding:10px 16px;font-size:14px;font-weight:800;margin-top:28px;}'
            'QLabel#studioLoadingRecentTitle {font-size:16px;font-weight:800;}'
            f'QLabel#studioLoadingRecentHint {{color:{theme.text_muted};font-size:12px;}}'
            f'QPushButton {{background:{theme.surface};color:{theme.text_secondary};border:1px solid {theme.border};'
            'border-radius:19px;padding:0 18px;min-height:38px;font-weight:700;}'
            f'QPushButton:hover {{border-color:{theme.border_strong};color:{theme.text};}}'
            f'QPushButton#studioLoadingRetry {{background:{theme.accent};color:{theme.text_on_accent};border:0;}}'
            f'QPushButton#studioLoadingRetry:hover {{background:{theme.accent_hover};}}'
            f'QPushButton#studioLoadingPick {{background:{theme.panel};}}'
            f'QPushButton#studioLoadingPick:checked {{background:{theme.accent_soft};color:{theme.accent_text};border-color:transparent;}}'
            + ('QFrame#windowTitleBar {background:transparent;border:0;}'
               'QPushButton#windowControl,QPushButton#windowControlClose '
               '{padding:0;min-width:30px;max-width:30px;min-height:22px;max-height:22px;border:0;border-radius:6px;}'
               if self.uses_native_cover else ''))
        for widget in (self.steps_view, self.library_steps, self.cover, self.fan):
            widget.update()


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
        # Recent project entries (path/name/cover/count/edited/duration_ms),
        # set by the owner before ``begin``; they fill both faces.
        self.recent_entries = []
        self._detail = ''
        self._mark_at = self.started
        self._surfaces = []
        self._stage_text = ('', '')
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._refresh_elapsed)
        self._completion_callback = None
        self._completion_generation = None
        for steps in (self.view.steps_view, self.view.library_steps):
            steps.completion_painted.connect(self._completion_painted, Qt.ConnectionType.QueuedConnection)
            steps.completion_finished.connect(self._completion_finished, Qt.ConnectionType.QueuedConnection)
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
        self.view.show_progress(self.completed, '', self._detail, failed='首屏绘制')
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
        self._cancel_completion()
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
        self._elapsed_timer.start()
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
        self._detail = ''
        self._mark_at = self.started
        self.view.apply_theme()
        self.view.set_mode(library=not path, path=self.path, entries=self.recent_entries)
        self.stage('创建工作台界面')
        self._record('begin')
        if present:
            self.present()
        return self.generation

    def present(self):
        """Paint the complete cover before withdrawing native video pixels."""
        self.view.ensurePolished()
        self.view.sync_geometry()
        self.view.fit_card()
        # Resolve hidden layouts before making the first pixel visible. A
        # queued LayoutRequest after show used to move the poster/perch.
        for face in (self.view.project_face, self.view.library_face, self.view.card, self.view):
            if face.layout() is not None:
                face.layout().activate()
        self.view._place_perch()
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
        self._stage_text = (stage, detail)
        self._refresh_elapsed()
        self.view.steps_view.set_state(self.completed, task)
        if stage == '创建工作台界面':
            self._detail = str(detail or '')
        self.view.show_progress(self.completed, task, self._detail)
        self.view.fit_card()
        if not self.events or self.events[-1].get('stage') != stage or self.events[-1].get('detail') != detail:
            self._record('stage', stage=stage, detail=detail)

    def _refresh_elapsed(self):
        from ..i18n import tr
        if not self.active:
            self._elapsed_timer.stop()
            return
        stage, detail = self._stage_text
        self.view.label.setText(f"{tr(stage)}{(' · ' + tr(detail)) if detail else ''} · {time.perf_counter()-self.started:.1f}s")

    def mark(self, stage):
        if self.active and stage not in self.completed:
            self.completed.add(stage)
            now = time.perf_counter()
            self.view.steps_view.times[stage] = now - self._mark_at
            self._mark_at = now
            self.view.bar.setValue(len(self.completed))
            current = self.view.steps_view.current
            current = '' if len(self.completed) >= len(TASKS) else current
            self.view.steps_view.set_state(self.completed, current)
            self.view.show_progress(self.completed, current, self._detail)
            self._record('complete_stage', stage=stage)

    def fail(self, stage, error):
        if not self.active:
            return
        self._cancel_completion()
        self.state, self.active = 'failed', False
        self._elapsed_timer.stop()
        self.view.steps_view.set_state(self.completed, '', stage)
        bind_text(self.view.label, '{stage}失败\n{error}\n工程文件仍保留，可重试载入：\n{value2}', stage=stage, error=error, value2=self.path)
        self.view.show_progress(self.completed, '', self._detail, failed=stage)
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

    def reuse(self, stage, reason):
        if self.active:
            self.view.steps_view.reused[stage] = str(reason)
            if stage == '创建工作台界面':
                self.view.library_steps.reused.update({name:str(reason) for name in LIBRARY_TASKS[:4]})
            self.mark(stage)
            self._record('reused', stage=stage, reason=str(reason))

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
            self._elapsed_timer.stop()
            self._retire_view()
        if generation != self.generation or self.state != 'ready':
            return False
        self.deliveries += 1
        self._record('delivered')
        return True

    def complete(self, generation, callback=None):
        """Present real terminal stages and finish a painted success gesture.

        Resource readiness and navigation are separate. No sleeping, nested
        event loop, or fabricated progress: the visible step painter owns the
        animation's start and end; generation checks own the later handoff.
        """
        if (not self.active or generation != self.generation or self.deliveries
                or set(TASKS) - self.completed):
            return False
        if self._completion_generation == generation:
            return True
        self._completion_generation = generation
        self._completion_callback = callback
        self.state = 'finishing'
        self._stage_text = ('准备好了', '')
        self._refresh_elapsed()
        self.view.show_progress(self.completed, '', self._detail)
        self._record('resources_ready')
        steps = self.view.library_steps if self.view.library_mode else self.view.steps_view
        steps.finish_after_paint()
        return True

    def _cancel_completion(self):
        self._completion_generation = None
        self._completion_callback = None
        for steps in (self.view.steps_view, self.view.library_steps):
            steps.cancel_completion()

    def _completion_painted(self):
        if self.active and self._completion_generation == self.generation:
            self._record('completion_painted')

    def _completion_finished(self):
        generation = self._completion_generation
        if generation is None or generation != self.generation or not self.active:
            return
        # A queued finish from a retired face must not finish its successor.
        steps = self.view.library_steps if self.view.library_mode else self.view.steps_view
        if steps._finishing or steps._finish_started is None:
            return
        callback = self._completion_callback
        self._completion_callback = None
        self._record('completion_animation_finished',
                     progress_shown=None if self.view.library_mode else self.view.bar._shown)
        try:
            delivered = self.deliver(generation)
        except Exception as error:
            self.fail('首屏绘制', str(error))
            return
        if delivered and callable(callback) and generation == self.generation:
            callback()

    def resume_ready(self, path):
        """Bind a retained, already verified editor after another open was cancelled.

        No loading view or second delivery is needed. A fresh identity still
        retires results belonging to the cancelled request.
        """
        self._cancel_completion()
        self._elapsed_timer.stop()
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
        self._cancel_completion()
        self._elapsed_timer.stop()
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

    def picked_project(self) -> str:
        """The recent project picked on the library face to open once the library is ready."""
        return self.view.picked_project() if self.state in {'preparing', 'ready'} else ''

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
