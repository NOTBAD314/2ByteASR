"""兔白 in a corner of the window, there by default (2026-11-18, phase 3).

User (2026-11-18): she should appear by default so people know she is there without looking for
「问问兔白」, be more active in helping, and be easy to send away.

A small 兔白 (the same rig as the chat's) sits in the lower right of the main window:

* a click opens her chat; she can be dragged anywhere in the window and stays there;
* a right-click: 「今天先别出来」, 「以后不要自动出现」, and how much she speaks up;
* when something happens in the software (``bunny_events.HINTS``) a small bubble comes up beside her
  with her words and up to two buttons. The words are local; only a pressed button sends a question
  to the chat (and so to the user's text AI).

She keeps quiet while the user types, a dialog or menu is open, the tutorial runs, the chat is open
or the app is not in front; what could not be said waits a little and is then dropped. She hides
with the window and while the chat (which has its own 兔白) is open.

2026-11-26: while the big 兔白 stands on the page with her dialog box folded (``bunny_chat.show_bunny``),
the small one stays hidden and hands her hints to the big one (``BunnyChat.hint``): a short line
shows over her head, a longer one waits in the box with a dot on her bubble.

What she notices by herself: a finished or failed recognition (the results page opening, read from
the newest report when 「让兔白读诊断和识别记录」 is on), a warning or error box that was closed, a
long quiet moment on a page (a tip from ``bunny_tips``), a late night.
"""
from __future__ import annotations

import os
import random
import threading
import time

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..i18n import tr
from . import bunny_events

MASCOT_HEIGHT = 92
BUBBLE_WIDTH = 270
MARGIN = 14
DRAG_SLOP = 6
TICK_MS = 1000
STAY_S, STAY_URGENT_S = 16.0, 30.0
WAIT_S, WAIT_URGENT_S = 20.0, 120.0       # how long a hint that could not be said yet is kept
IDLE_TIP_S = 90.0                         # this quiet on a page, with the app in front
MUTTER_SHARE = 0.3                        # ... and how often it is a word to herself instead of a tip
ANTIC_GAP_S = (35.0, 80.0)                # 2026-11-18 (phase 4): little moves of her own while nothing happens
ANTICS = ('peek', 'stretch', 'tilt', 'brow_raise', 'ear_flap', 'one_ear')     # bunny_moves.MOVES
WATCHING = ('tilt', 'push_glasses', 'search')                                # while a recognition runs she watches it
DOZE_AFTER_S = 180.0
BOND_CHECK_TICKS = 20
TYPING_QUIET_S = 6.0
REPORT_FRESH_S = 240.0
FIRST_HELLO_MS = 3500
FORCE_ENV = 'TWOBYTEASR_BUNNY_RESIDENT'   # "1" shows her under test isolation too, "0" never
# What she reads from the whole application (via design.app_events), not every event.
_APP_EVENT_TYPES = (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel,
                    QEvent.Type.Show, QEvent.Type.Hide)


def tour_open(window) -> bool:
    """The tutorial (``home_tour.GuidedTour``) is showing over ``window``."""
    import sys
    module = sys.modules.get('twobyteasr.app.home_tour')
    tour_type = getattr(module, 'GuidedTour', None) if module is not None else None
    try:
        tour = window.findChild(tour_type) if tour_type is not None else None
        return tour is not None and tour.isVisible()
    except RuntimeError:
        return False


def auto_start_allowed() -> bool:
    """Not under the test isolation or the offscreen platform (audits drive the real window there)."""
    forced = os.environ.get(FORCE_ENV, '')
    if forced in ('0', '1'):
        return forced == '1'
    return not (os.environ.get('TWOBYTEASR_TEST_ROOT') or os.environ.get('QT_QPA_PLATFORM') == 'offscreen')


class HintBubble(QFrame):
    """Her words beside her: a line, up to two buttons, ×."""

    def __init__(self, sheet: str, colors: dict, parent=None):
        super().__init__(parent)
        from .tour_mascot import MarkedLabel
        self.setObjectName('bunnyHint')
        self.colors = colors
        self.setStyleSheet(sheet)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 10, 10)
        outer.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.label = MarkedLabel()
        self.label.setObjectName('bunnyHintText')
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        top.addWidget(self.label, 1)
        self.close_button = QPushButton('×')
        self.close_button.setObjectName('bunnyHintClose')
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setFixedSize(22, 22)
        self.close_button.setToolTip(str(tr('关掉这句（同一类关两次，兔白一周内不再提）')))
        top.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(top)
        self.row = QHBoxLayout()
        self.row.setSpacing(6)
        outer.addLayout(self.row)
        self.buttons: list = []

    def set_hint(self, line: str, buttons, on_button):
        from . import ui_zoom
        from .tour_mascot import marked_html
        for button in self.buttons:
            button.hide()
            button.deleteLater()
        self.buttons = []
        while self.row.count():
            self.row.takeAt(0)
        self.label.setText(marked_html(line, self.colors, keep_words=True))
        for label, question in buttons:
            button = QPushButton(str(tr(label)))
            button.setObjectName('bunnyChatGo')
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _checked=False, said=question: on_button(said))
            self.row.addWidget(button)
            self.buttons.append(button)
        self.row.addStretch(1)
        width = ui_zoom.px(BUBBLE_WIDTH)
        self.setFixedWidth(width)
        self.label.setFixedWidth(width - 14 - 10 - 22 - 6)
        self.layout().activate()
        self.setFixedHeight(self.layout().totalHeightForWidth(width) if self.layout().hasHeightForWidth()
                            else self.layout().sizeHint().height())


class BunnyResident(QWidget):
    _recognition_outcome = Signal(object)
    def __init__(self, window):
        from . import ui_zoom
        from .bunny_chat import _floating, _theme, chat_font_family, chat_sheet
        from .tour_mascot import marker_colors
        floating = _floating()
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus) if floating else Qt.WindowType.Widget
        super().__init__(window, flags)
        self._recognition_outcome.connect(self._deliver_report_outcome, Qt.ConnectionType.QueuedConnection)
        self._reading_outcome = False
        self.setObjectName('bunnyResident')
        self.window_ = window
        self.floating = floating
        if floating:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        theme = _theme()
        self.sheet = chat_sheet(theme, chat_font_family())
        self.session = bunny_events.Session()
        self.values = bunny_events.load()
        self.hint_key = ''
        self._hint_until = 0.0
        self._queue: list = []                 # [event, facts, drop after]
        self._press = None
        self._dragging = False
        from .floating_anchor import Coalesced
        self._placer = Coalesced(self, self.place)    # drags and window moves: one place per frame
        self._placed = None                    # what the last place put where (nothing changed: no native call)
        self._active_at = time.monotonic()     # the user's last key, click or wheel
        self._typed_at = 0.0
        self._idle_said_at = self._active_at
        self._boxes: dict = {}                 # open warning / error boxes: id -> (title, text)
        self._next_antic = time.monotonic() + random.uniform(*ANTIC_GAP_S)
        self._dozing = False
        self._ticks = 0
        self._offset = QPoint(*self.values['place']) if self.values['place'] else None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.bubble = HintBubble(self.sheet, marker_colors(theme), self)
        self.bubble.close_button.clicked.connect(self._close_hint)
        self.bubble.hide()
        layout.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignBottom)
        self.mascot = None
        try:
            from ..design.bunny_mascot import BunnyMascot
            mascot = BunnyMascot(self, height=ui_zoom.px(MASCOT_HEIGHT), motion='swing')
        except Exception:  # noqa: BLE001 - no pictures: a small round button instead
            mascot = None
        if mascot is not None and mascot.available:
            mascot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            mascot._timer.setInterval(33)
            self.mascot = mascot
            self.body = mascot
        else:
            if mascot is not None:
                mascot.deleteLater()
            self.body = QLabel('兔白', self)
            self.body.setObjectName('bunnyHintText')
            self.body.setStyleSheet(self.sheet)
            self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.setFixedSize(ui_zoom.px(56), ui_zoom.px(40))
        self.body.setObjectName('bunnyResidentBody')
        self.body.setCursor(Qt.CursorShape.PointingHandCursor)
        self.body.setToolTip(str(tr('问问兔白（点一下聊天，右键可以让她走开）')))
        self.body.installEventFilter(self)
        layout.addWidget(self.body, 0, Qt.AlignmentFlag.AlignBottom)
        window.installEventFilter(self)
        # 2026-11-19 (user: every page and dialog stutters the first time): an application event
        # filter of her own was a Python call for every event of every widget (about 19,000 while
        # the export workspace is built). The shared hub calls her for the few kinds she reads.
        from ..design import app_events
        if not app_events.listen(self, _APP_EVENT_TYPES, self._app_event):
            QApplication.instance().installEventFilter(self)
        pages = getattr(window, 'pages', None)
        if pages is not None:
            pages.currentChanged.connect(self._page_changed)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.hide()
        if floating:
            try:
                self.winId()            # her native window now, so her first place is already in pixels
                for handle in (self.windowHandle(), window.windowHandle()):
                    if handle is not None:
                        handle.screenChanged.connect(self._screen_changed)
            except RuntimeError:
                pass
        self.sync()

    # ------------------------------------------------------------ where she is
    def _anchor(self) -> QPoint:
        """The window point her lower right corner sits at."""
        from . import ui_zoom
        window = self.window_
        margin = ui_zoom.px(MARGIN)
        if self._offset is not None:
            return QPoint(window.width() + self._offset.x(), window.height() + self._offset.y())
        bottom = window.height() - margin
        start = getattr(window, 'start_button', None)
        try:
            if start is not None and start.isVisible() and start.window() is window:
                top = start.mapTo(window, QPoint(0, 0)).y()
                if self.body.height() + margin <= top < window.height():
                    bottom = min(bottom, top - margin)       # never over 「开始生成字幕」
        except RuntimeError:
            pass
        return QPoint(window.width() - margin, bottom)

    def place(self):
        """Put her at her anchor now. Drags and window moves go through ``request_place``."""
        self._placer.cancel()
        self.layout().activate()
        size = self.layout().sizeHint()
        anchor = self._anchor()
        window = self.window_
        x = max(0, min(anchor.x() - size.width(), window.width() - size.width()))
        y = max(0, min(anchor.y() - size.height(), window.height() - size.height()))
        # 2026-11-19 (user: opening a project in the workbench froze): the same place as last time,
        # for the same window, is not asked of Windows again.
        try:
            key = (x, y, size.width(), size.height(), window.geometry().getRect(),
                   window.devicePixelRatioF(), self.devicePixelRatioF())
        except RuntimeError:
            return
        if key == self._placed and self.size() == size:
            if not self.floating:
                self.raise_()
            return
        self._placed = key
        if self.floating:
            # 2026-11-19 (user, three screens at different scales: she went to another screen and
            # jumped to the upper left when picked up): in physical pixels, see floating_anchor.
            # Size and place in one native step.
            from . import floating_anchor
            floating_anchor.place(self, window, QPoint(x, y), size=size)
        else:
            if self.size() != size:
                self.resize(size)
            self.move(x, y)
            self.raise_()

    def request_place(self):
        """A place soon, at most one per frame and never inside the event that asked (a drag's
        mouse moves, the main window moving or changing size)."""
        self._placer.request()

    def _screen_changed(self, *_args):
        """Her own window is drawn at another scale now (most of her lies on another screen), or
        the main window is: her size in pixels changed, so her place is worked out again."""
        self._placed = None
        if self.isVisible():
            self.request_place()

    # ------------------------------------------------------------ shown or not
    def _chat_open(self) -> bool:
        chat = getattr(self.window_, '_bunny_chat', None)
        try:
            # 2026-11-26: a card folded away while she is played with is still an open chat.
            return chat is not None and (chat.isVisible() or bool(getattr(chat, 'collapsed', False)))
        except RuntimeError:
            return False

    def _tour_open(self) -> bool:
        return tour_open(self.window_)

    def sync(self):
        """Show or hide her for the user's choice, the window and the chat."""
        self.values = bunny_events.load()
        window = self.window_
        wanted = (bunny_events.resident_wanted(self.values) and window.isVisible() and not window.isMinimized()
                  and not self._chat_open() and not self._tour_open())
        if wanted and not self.isVisible():
            self.place()
            self.show()
        elif not wanted and self.isVisible():
            self._hide_hint()
            self.hide()

    def _folded_chat(self):
        """The big 兔白's chat while it stands folded on the page (she takes the hints then)."""
        chat = getattr(self.window_, '_bunny_chat', None)
        try:
            if (chat is not None and getattr(chat, 'collapsed', False) and getattr(chat, 'puck', None) is not None
                    and getattr(chat, 'fold_reason', '') in ('user', 'start')):
                return chat
        except RuntimeError:
            pass
        return None

    def busy(self) -> bool:
        """The user is in the middle of something her bubble must not cut into."""
        app = QApplication.instance()
        if not (self.isVisible() or self._folded_chat() is not None) or not self._app_in_front():
            return True
        if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
            return True
        if app.mouseButtons() != Qt.MouseButton.NoButton or self._dragging:
            return True
        return time.monotonic() - self._typed_at < TYPING_QUIET_S

    @staticmethod
    def _app_in_front() -> bool:
        return QApplication.instance().applicationState() == Qt.ApplicationState.ApplicationActive

    # ------------------------------------------------------------ hints
    def notify(self, event: str, **facts):
        """Something happened: say it now if she may, else keep it a little while."""
        hint = bunny_events.HINTS.get(event)
        if hint is None:
            return
        wait = WAIT_URGENT_S if hint.urgent else WAIT_S
        if event in ('first_run', 'level_up', 'welcome_back', 'welcome_plain'):
            wait = 600.0
        self._queue = [row for row in self._queue if row[0] != event][-3:]
        self._queue.append([event, facts, time.monotonic() + wait])
        self._drain()

    def _drain(self):
        now = time.monotonic()
        self._queue = [row for row in self._queue if row[2] > now]
        if not self._queue or self.hint_key or self.busy():
            return
        self._queue.sort(key=lambda row: not bunny_events.HINTS[row[0]].urgent)
        for row in list(self._queue):
            event, facts, _until = row
            self._queue.remove(row)
            hint = bunny_events.decide(event, self.values, self.session)
            if hint is not None and self._show_hint(hint, facts):
                return

    def _show_hint(self, hint, facts) -> bool:
        line, buttons = bunny_events.wording(hint, facts)
        if not line:
            return False
        chat = self._folded_chat()
        if chat is not None:
            if hint.key == 'error_dialog':
                from . import bunny_permissions
                if not bunny_permissions.load().get('read_diagnostics'):
                    buttons = ()
            if not chat.hint(line, buttons, hint.mood, hint.act):
                return False
            bunny_events.shown(hint.key, self.session)
            self.values = bunny_events.load()
            return True
        self.hint_key = hint.key
        self.bubble.set_hint(line, buttons, self._button)
        self.bubble.show()
        self.place()
        bunny_events.shown(hint.key, self.session)
        self.values = bunny_events.load()
        self._hint_until = time.monotonic() + (STAY_URGENT_S if hint.urgent else STAY_S)
        if self.mascot is not None:
            from .bunny_chat import MOOD_FACE
            self.mascot.set_mood(MOOD_FACE.get(hint.mood, 'idle'))
            if not (hint.act and self.mascot.act(hint.act)):
                self.mascot.hop()
        return True

    def say_line(self, line: str, seconds: float = STAY_S) -> bool:
        """A line from the user's own extension script (2026-11-20, ``ScriptAPI.say``): shown like a hint
        when she is free, else not at all (it is in the script log anyway)."""
        line = str(line or '').strip()[:200]
        if not line or self.busy() or not self.isVisible():
            return False
        self.hint_key = 'extension_script'
        self.bubble.set_hint(line, [], self._button)
        self.bubble.show()
        self.place()
        self._hint_until = time.monotonic() + max(3.0, float(seconds))
        if self.mascot is not None:
            self.mascot.hop()
        return True

    def _hide_hint(self):
        if not self.hint_key:
            return
        self.hint_key = ''
        self.bubble.hide()
        if self.mascot is not None:
            self.mascot.set_mood('idle')
        if self.isVisible():
            self.place()

    def _close_hint(self):
        bunny_events.dismissed(self.hint_key)
        self.values = bunny_events.load()
        self._hide_hint()

    def _button(self, question: str):
        key = self.hint_key
        self._hide_hint()
        if not question:
            return
        if key == 'error_dialog':
            from . import bunny_permissions
            if not bunny_permissions.load().get('read_diagnostics'):
                return
        bunny_events.used(key)
        chat = self.open_chat()
        if chat is not None:
            QTimer.singleShot(250, self, lambda: self._ask(chat, question))

    @staticmethod
    def _ask(chat, question: str):
        try:
            chat.ask_now(question)
        except RuntimeError:                              # the chat was closed in between
            pass

    def open_chat(self):
        opener = getattr(self.window_, '_open_bunny_chat', None)
        try:
            if callable(opener):
                chat = opener()
            else:
                from .bunny_chat import open_bunny_chat
                chat = open_bunny_chat(self.window_)
        except Exception:  # noqa: BLE001 - the chat failing to open must not break her
            return None
        self.sync()
        return chat

    # ------------------------------------------------------------ what she notices
    def _page_changed(self, _index: int):
        from .bunny_chat import current_page
        self._active_at = self._idle_said_at = time.monotonic()
        if self.isVisible():
            QTimer.singleShot(0, self, self.place)
        if current_page(self.window_) == '识别完成的结果页':
            QTimer.singleShot(1500, self, self._report_outcome)

    def _report_outcome(self):
        from . import bunny_permissions
        if self._reading_outcome or not bunny_permissions.load().get('read_diagnostics'):
            return
        self._reading_outcome = True

        def read():
            record = None
            try:
                from ..recognition.recognition_history import parse_recognition_report
                from .bunny_lookup import newest_report
                path = newest_report()
                if path is not None and time.time() - os.path.getmtime(path) <= REPORT_FRESH_S:
                    record = parse_recognition_report(path)
            except Exception:
                pass  # An unreadable report produces no notification.
            try:
                self._recognition_outcome.emit(record)
            except RuntimeError:
                pass  # The window closed while the reader was working.

        threading.Thread(target=read, name='bunny-recognition-outcome', daemon=True).start()

    def _deliver_report_outcome(self, record):
        self._reading_outcome = False
        from . import bunny_permissions
        from .bunny_chat import current_page
        if (record is None or current_page(self.window_) != '识别完成的结果页'
                or not bunny_permissions.load().get('read_diagnostics')):
            return
        event, facts = bunny_events.outcome_event(record.status, int(record.review_count or 0))
        bunny_events.remember(f'一次识别结束了，状态是“{record.status_label or record.status}”，'
                              f'字幕 {record.cue_count} 条，待复核 {record.review_count} 项')
        if event:
            self.notify(event, **facts)
            if event != 'recognition_failed':
                from . import bunny_bond
                bunny_bond.note('done')                  # a subtitle made together

    def _antics(self, now: float, idle: float):
        """Phase 4: she does little things on her own — watches a running recognition, stretches,
        peeks, and dozes off when nothing has happened for a while (a key or click wakes her)."""
        mascot = self.mascot
        if mascot is None:
            return
        if self._dozing and idle < 5:
            self._dozing = False
            mascot.unstick()
            mascot.stop_move()
            mascot.play('wake')
            self._next_antic = now + random.uniform(*ANTIC_GAP_S)
            return
        if self.hint_key or self._dozing or now < self._next_antic or mascot.current_move:
            return
        self._next_antic = now + random.uniform(*ANTIC_GAP_S)
        if idle >= DOZE_AFTER_S:
            self._dozing = True
            mascot.play('doze')
            mascot.stick('zzz')
        elif getattr(self.window_, '_run_in_progress', False):
            mascot.play(random.choice(WATCHING))
        else:
            mascot.play(random.choice(ANTICS))

    def _bond_news(self):
        try:
            from . import bunny_bond
            line = bunny_bond.level_up_line()
        except Exception:  # noqa: BLE001
            line = ''
        if line:
            self.notify('level_up', line=line)

    def _tick(self):
        self.sync()
        if not self.isVisible():
            return
        now = time.monotonic()
        if self.hint_key and now > self._hint_until and not self.bubble.underMouse():
            self._hide_hint()
        self._drain()
        idle = now - self._active_at
        self._antics(now, idle)
        self._ticks += 1
        if self._ticks % BOND_CHECK_TICKS == 0 and not self.hint_key:
            self._bond_news()
        if self.hint_key or self.busy():
            return
        if IDLE_TIP_S <= idle < 4 * IDLE_TIP_S and now - self._idle_said_at >= IDLE_TIP_S:
            self._idle_said_at = now
            from .bunny_chat import current_page
            from .bunny_tips import idle_allowed, next_tip
            if idle_allowed():
                try:
                    _index, tip = next_tip(current_page(self.window_))
                except Exception:  # noqa: BLE001
                    tip = ''
                if random.random() < MUTTER_SHARE and bunny_events.decide('mutter', self.values, self.session):
                    self.notify('mutter')
                elif tip:
                    self.notify('idle_page', tip=tip)
        elif idle < 30 and time.localtime().tm_hour < 5:
            self.notify('late_night')

    def _watch_box(self, box, kind):
        """A warning or error box with nothing to choose: once it is closed she offers to explain it."""
        from . import bunny_permissions
        if not bunny_permissions.load().get('read_diagnostics'):
            self._boxes.pop(id(box), None)
            return
        if kind == QEvent.Type.Show:
            if box.icon() not in (QMessageBox.Icon.Critical, QMessageBox.Icon.Warning):
                return
            if len(box.buttons()) > 1:
                return                                   # a question to the user, not a report
            from ..providers.provider_diagnostics import redact_diagnostics
            title = redact_diagnostics(' '.join(str(box.windowTitle() or '').split())) or str(tr('提示'))
            text = redact_diagnostics(' '.join(str(box.text() or '').split()))
            self._boxes[id(box)] = (title, text)
        elif kind == QEvent.Type.Hide:
            found = self._boxes.pop(id(box), None)
            if found is not None:
                title, text = found
                said = f'{title}：{text}' if text else title
                bunny_events.remember(f'跳出过一个提示框「{said}」')
                QTimer.singleShot(500, self, lambda: self.notify('error_dialog', title=title[:40], said=said))

    # ------------------------------------------------------------ events
    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        kind = event.type()
        if watched is self.body:
            return self._body_event(kind, event)
        if watched is self.window_:
            if kind in (QEvent.Type.Move, QEvent.Type.Resize):
                if self.isVisible():
                    self.request_place()
            elif kind in (QEvent.Type.WindowStateChange, QEvent.Type.Show, QEvent.Type.Hide):
                QTimer.singleShot(0, self, self.sync)
            elif kind == QEvent.Type.Close:
                self._timer.stop()
                self.hide()
            return False
        return self._app_event(watched, event)

    def _app_event(self, watched, event) -> bool:
        """Input anywhere (how long since the person did something) and message boxes."""
        if watched is self.body or watched is self.window_:
            return False                               # their own filters (eventFilter) handle them
        kind = event.type()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
            self._active_at = time.monotonic()
            if kind == QEvent.Type.KeyPress:
                self._typed_at = self._active_at
        elif kind in (QEvent.Type.Show, QEvent.Type.Hide) and isinstance(watched, QMessageBox):
            try:
                self._watch_box(watched, kind)
            except RuntimeError:
                pass
        return False

    def _body_event(self, kind, event) -> bool:
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            from . import floating_anchor
            pointer = floating_anchor.Pointer(self.window_, self.body, event)
            self._press = (pointer.at(event), self._anchor(), pointer)
            self._dragging = False
            return True
        if kind == QEvent.Type.MouseMove and self._press is not None:
            start, anchor, pointer = self._press
            moved = (pointer.at(event) - start).toPoint()
            if self._dragging or moved.manhattanLength() > DRAG_SLOP:
                self._dragging = True
                window = self.window_
                at = anchor + moved
                at.setX(max(self.body.width(), min(at.x(), window.width())))
                at.setY(max(self.body.height(), min(at.y(), window.height())))
                self._offset = QPoint(at.x() - window.width(), at.y() - window.height())
                self.request_place()
            return True
        if kind == QEvent.Type.MouseButtonRelease and self._press is not None:
            self._press = None
            if self._dragging:
                self._dragging = False
                self._placer.flush()                 # she ends exactly where she was let go
                bunny_events.save({'place': [self._offset.x(), self._offset.y()]})
            else:
                self._hide_hint()
                self.open_chat()
            return True
        if kind == QEvent.Type.ContextMenu:
            self._menu(event.globalPos())
            return True
        return False

    def _menu(self, at):
        from PySide6.QtGui import QAction, QActionGroup
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setObjectName('bunnyResidentMenu')
        menu.addAction(str(tr('问问兔白')), self.open_chat)
        menu.addSeparator()
        speak = menu.addMenu(str(tr('兔白主动提醒')))
        group = QActionGroup(speak)
        for mode in bunny_events.MODES:
            action = QAction(str(tr(bunny_events.MODE_LABELS[mode])), speak, checkable=True)
            action.setChecked(self.values['mode'] == mode)
            action.triggered.connect(lambda _checked=False, value=mode: self.set_mode(value))
            group.addAction(action)
            speak.addAction(action)
        menu.addSeparator()
        menu.addAction(str(tr('今天先别出来')), self.away_today)
        menu.addAction(str(tr('以后不要自动出现')), self.away_for_good)
        self.menu = menu
        menu.popup(at)

    def set_mode(self, mode: str):
        if mode in bunny_events.MODES:
            bunny_events.save({'mode': mode})
            self.values = bunny_events.load()
            if mode == 'off':
                self._hide_hint()

    def away_today(self):
        bunny_events.save({'quiet_day': bunny_events.today()})
        self.sync()

    def away_for_good(self):
        """She leaves; 「问问兔白」 in the top bar still opens her, the settings bring her back."""
        bunny_events.save({'resident': False})
        self.sync()

    def closeEvent(self, event):  # noqa: N802 - Qt override
        self._timer.stop()
        super().closeEvent(event)


def install(window, *, hello: bool = True):
    """Create her for ``window`` (once). Returns the resident, or None when she could not be made."""
    resident = getattr(window, '_bunny_resident', None)
    if resident is not None:
        return resident
    try:
        resident = BunnyResident(window)
    except Exception:  # noqa: BLE001 - she is a nicety: never in the way of the app starting
        return None
    window._bunny_resident = resident
    if hello:
        QTimer.singleShot(FIRST_HELLO_MS, resident, lambda: _hello(resident))
    return resident


def _hello(resident):
    resident.notify('first_run')
    if resident.values['intro']:                       # not her first time: welcome back, or the missing AI
        try:
            from . import bunny_bond
            if bunny_bond.welcome_due():
                from .bunny_nav_tools import project_records
                recent = [row for row in project_records(3) if row.get('exists')]
                if recent:
                    resident.notify('welcome_back', name=str(recent[0].get('name') or '')[:24])
                else:
                    resident.notify('welcome_plain')
        except Exception:  # noqa: BLE001
            pass
        try:
            from .bunny_chat import ai_readiness, runtime_settings
            if not ai_readiness(runtime_settings(resident.window_))[0]:
                resident.notify('no_text_ai')
        except Exception:  # noqa: BLE001
            pass


def refresh(window):
    """The settings changed: show, hide or re-read her."""
    resident = getattr(window, '_bunny_resident', None)
    if resident is None:
        if bunny_events.resident_wanted() and window is not None:
            resident = install(window, hello=False)
        return resident
    resident.sync()
    return resident


def notify(window, event: str, **facts):
    resident = getattr(window, '_bunny_resident', None)
    if resident is not None:
        try:
            resident.notify(event, **facts)
        except RuntimeError:
            pass


__all__ = ['BunnyResident', 'HintBubble', 'auto_start_allowed', 'install', 'notify', 'refresh']
