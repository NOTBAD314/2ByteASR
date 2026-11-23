"""兔白处理 on the completion page: the bubble in the result card and its window.

2026-11-21 (user chose 乙1 from the third round of drafts,
``tmp/completion-ai-drafts-20261117/index.html``): the result card keeps its
layout; under the numbers a bunny bubble says how many items 兔白 can fix, what
it may cost and offers 「交给兔白」. Its window shows one small card per kind
(a click leaves a kind out), then a bar per kind while it runs (cancel, or keep
going in the background), then what was fixed and what is left and why. A
card's changes can be undone one by one; the whole run can be restored.

The work itself is :mod:`completion_ai_repair`; this module only shows it.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..design.main_ui_dialogs import SpringDialog
from ..design.soft_message import soft_information, soft_question
from ..design.theme_manager import theme_key
from ..design.ui_theme import blend_hex, theme_definition
from ..i18n import tr
from . import completion_ai_repair as repair
from .completion_widgets import COMPLETION_RADIUS_MAIN, COMPLETION_RADIUS_SMALL


def _theme():
    return theme_definition(theme_key())


def _ai_color(theme):
    return theme.zone_colors.get('ai', theme.accent_text)


def _face(size, widget):
    label = QLabel(widget)
    label.setFixedSize(size, size)
    label.setStyleSheet('background:transparent; border:0;')
    try:
        from ..design.bunny_mascot import bunny_face_pixmap
        label.setPixmap(bunny_face_pixmap(size, widget.devicePixelRatioF() or 1.0))
    except Exception:  # noqa: BLE001 - the words still work without the face
        pass
    return label


def _clock(ms):
    seconds, _ = divmod(max(0, int(ms)), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


# ---------------------------------------------------------------- worker

class RepairWorker(QThread):
    progressed = Signal(object)
    finished_ok = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, plan, selected, parent=None):
        super().__init__(parent)
        self.plan, self.selected = plan, set(selected)

    def run(self):
        from ..providers.usage_ledger import usage_scope
        try:
            from ..system.processes import process_action_scope
            with process_action_scope('completion.ai-repair'), usage_scope(
                    project_id=self.plan.project_path, task_label=tr('兔白处理')):
                result = repair.run_repair(self.plan, self.selected, cancelled=self.isInterruptionRequested,
                                           progress=self.progressed.emit)
        except repair.RepairCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:  # noqa: BLE001 - the page says why; nothing was written
            self.failed.emit(' '.join(str(exc).split())[:300] or type(exc).__name__)
            return
        self.finished_ok.emit(result)


class RepairController(QObject):
    """One 兔白处理 at a time for the completion page; outlives its window."""

    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.plan = None
        self.worker = None
        self.cancel_requested = False
        self.state = 'idle'          # idle running done failed cancelled
        self.progress = {}           # category -> (done, total, phase)
        self.result = None
        self.record = None
        self.message = ''
        self.selected = set()
        self.dialog = None

    # --- planning -------------------------------------------------------
    def refresh(self, project_path, report, project):
        """Re-plan for the selected task (the page calls this on every refresh)."""
        if self.state == 'running':
            return
        self.plan = None
        if project is None or not project_path or not isinstance(report, dict):
            self.changed.emit()
            return
        try:
            self.plan = repair.plan_repair(project, report, project_path)
        except Exception as exc:  # noqa: BLE001 - no bubble rather than a broken page
            import sys
            print(f'[ai-repair] plan failed: {type(exc).__name__}: {exc}', file=sys.stderr)
            self.plan = None
        if self.state in {'done', 'failed', 'cancelled'} and self.record is not None:
            if str(self.record.get('project_path')) != str(project_path):
                self.reset()
        self.changed.emit()

    def reset(self):
        self.state, self.result, self.record, self.message, self.progress = 'idle', None, None, '', {}

    def _notice_parent(self):
        """Notices sit over the 兔白 window while it is open, else over the main window."""
        dialog = self.dialog
        try:
            if dialog is not None and dialog.isVisible():
                return dialog
        except RuntimeError:
            pass
        return self.window

    # --- running --------------------------------------------------------
    def blocked_reason(self, path=None):
        window = self.window
        if getattr(window, '_run_in_progress', False) or getattr(window, '_completion_retry_in_progress', False):
            return tr('识别或重试还在运行，结束后再交给兔白')
        if path is None and self.plan is None:
            return tr('这个结果没有可以处理的工程')
        if path is None:
            path = self.plan.project_path
        studio = window.built_page('studio') if hasattr(window, 'built_page') else None
        studio_path = getattr(studio, 'project_path', None)
        if studio_path and Path(studio_path).resolve() == Path(path).resolve():
            return tr('字幕工作台还开着这个工程。请保存并关闭工程，再交给兔白。')
        proofread = getattr(window, 'glossary_proofread_page', None)
        if proofread is not None and not proofread.settle_writes(path):
            return tr('AI 词库校对的修改还在保存，稍等再交给兔白')
        state = (getattr(window, '_proofread_save_states', {}).get(path) or {}).get('state')
        if state in ('pending', 'error'):
            return tr('最新修改还没保存好，先等保存完成')
        return ''

    def start(self, selected):
        if self.state == 'running':
            return False
        reason = self.blocked_reason()
        if reason:
            soft_information(self._notice_parent(), tr('现在不能交给兔白'), reason, tone='warning')
            return False
        self.selected = set(selected)
        self.cancel_requested = False
        self.progress = {key: (0, self.plan.category(key).count, '') for key in self.selected
                         if self.plan.category(key) is not None}
        self.state, self.message, self.result, self.record = 'running', '', None, None
        worker = self.worker = RepairWorker(self.plan, self.selected, self)
        worker.progressed.connect(self._progressed)
        worker.finished_ok.connect(self._finished)
        worker.failed.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self.changed.emit()
        return True

    def cancel(self):
        if self.worker is not None and self.state == 'running':
            self.cancel_requested = True
            self.worker.requestInterruption()
            self.message = tr('正在停下…做到一半的不会保存')
            self.changed.emit()

    def percent(self):
        done = sum(value[0] for value in self.progress.values())
        total = sum(max(1, value[1]) for value in self.progress.values()) or 1
        return max(1, min(99, round(done * 100 / total))) if self.state == 'running' else 100

    def _progressed(self, event):
        key = event.get('category')
        if key in self.progress or key in self.selected:
            total = int(event.get('total') or self.progress.get(key, (0, 1, ''))[1] or 1)
            self.progress[key] = (min(int(event.get('done') or 0), total), total, str(event.get('phase') or ''))
            self.changed.emit()

    def _finished(self, result):
        if self.cancel_requested:
            self._cancelled()
            return
        self.worker = None
        reason = self.blocked_reason()
        if reason:
            self._failed(reason)
            return
        self.result = result
        if repair.text_change_ids(result):
            self.state = 'review'
            self.changed.emit()
            return
        self._commit_result(result)

    def approve_review(self):
        if self.state != 'review' or self.result is None:
            return
        reason = self.blocked_reason()
        if reason:
            self._failed(reason)
            return
        self._commit_result(self.result, approved_text_ids=repair.text_change_ids(self.result))

    def _commit_result(self, result, *, approved_text_ids=()):
        try:
            self.record = repair.commit_repair(self.plan, result, approved_text_ids=approved_text_ids)
        except Exception as exc:  # noqa: BLE001
            self.state, self.message = 'failed', tr('结果没有写入：{reason}', reason=str(exc)[:200])
            self.changed.emit()
            return
        self.result, self.state = result, 'done'
        self.record = repair.read_record(self.plan.project_path) or self.record
        self.window._ai_repair_saved(self.plan.project_path)
        self.changed.emit()

    def _failed(self, message):
        self.worker = None
        self.state, self.message = 'failed', tr('兔白停下了，什么都没改：{reason}', reason=message)
        self.changed.emit()

    def _cancelled(self):
        self.worker = None
        self.state, self.message = 'cancelled', tr('已经停下，什么都没改')
        self.changed.emit()

    # --- after ----------------------------------------------------------
    def undo_change(self, change_id, undone):
        if self.record is None:
            return False
        reason = self.blocked_reason(self.record['project_path'])
        if reason:
            soft_information(self._notice_parent(), tr('现在不能交给兔白'), reason, tone='warning')
            return False
        ok = repair.set_change_undone(self.record, change_id, undone)
        if ok:
            self.window._ai_repair_saved(self.record['project_path'])
        self.changed.emit()
        return ok

    def restore(self):
        record = self.record or (repair.read_record(self.plan.project_path) if self.plan else None)
        if record is None:
            return False
        reason = self.blocked_reason(record['project_path'])
        if reason:
            soft_information(self._notice_parent(), tr('现在不能交给兔白'), reason, tone='warning')
            return False
        if repair.edited_since(record):
            if not soft_question(self._notice_parent(), tr('还原到兔白处理前'),
                                 tr('兔白处理之后，这个工程又被改过（工作台或 AI 词库校对）。还原会把这些修改也一起丢掉。仍要还原吗？'),
                                 accept_text=tr('仍要还原'), reject_text=tr('先不还原'), destructive=True):
                return False
        repair.restore_before_repair(record)
        path = record['project_path']
        self.reset()
        self.window._ai_repair_saved(path)
        self.changed.emit()
        return True


# ---------------------------------------------------------------- bubble

class RepairBubble(QFrame):
    """乙1: a speech bubble from 兔白 at the bottom right of the result card."""

    open_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setObjectName('aiRepairBubble')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        self.face = _face(34, self)
        row.addWidget(self.face, 0, Qt.AlignmentFlag.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.title = QLabel(self)
        self.title.setObjectName('aiRepairBubbleTitle')
        self.title.setTextFormat(Qt.TextFormat.RichText)
        words.addWidget(self.title)
        self.note = QLabel(self)
        self.note.setObjectName('aiRepairBubbleNote')
        words.addWidget(self.note)
        self.pips = QLabel(self)
        self.pips.setObjectName('aiRepairBubblePips')
        self.pips.setTextFormat(Qt.TextFormat.RichText)
        words.addWidget(self.pips)
        row.addLayout(words, 1)
        self.button = QPushButton(self)
        self.button.setObjectName('aiRepairGo')
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.open_requested.emit)
        row.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        controller.changed.connect(self.refresh)
        self.refresh_theme_palette()
        self.hide()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.open_requested.emit()
        super().mouseReleaseEvent(event)

    def refresh_theme_palette(self):
        t = _theme()
        ai = _ai_color(t)
        self.setStyleSheet(f"""
QFrame#aiRepairBubble {{ background:{t.surface_elevated}; border:1px solid {blend_hex(t.surface, ai, 0.35)};
 border-radius:{COMPLETION_RADIUS_MAIN}px; }}
QFrame#aiRepairBubble:hover {{ border-color:{ai}; }}
QLabel#aiRepairBubbleTitle {{ color:{t.text}; font-size:13px; font-weight:600; background:transparent; }}
QLabel#aiRepairBubbleNote {{ color:{t.text_secondary}; font-size:12px; background:transparent; }}
QLabel#aiRepairBubblePips {{ background:transparent; font-size:10px; }}
QPushButton#aiRepairGo {{ background:{ai}; color:{t.on_vivid}; border:0; border-radius:{COMPLETION_RADIUS_SMALL}px;
 font-size:13px; font-weight:700; padding:7px 14px; }}
QPushButton#aiRepairGo:hover {{ background:{blend_hex(ai, t.on_vivid, 0.12)}; }}
QPushButton#aiRepairGo:focus {{ border:1px solid {t.focus}; }}
""")
        self.refresh()

    def refresh(self):
        c = self.controller
        t = _theme()
        ai = _ai_color(t)
        plan = c.plan
        if c.state == 'running':
            self.title.setText(tr('兔白处理中 {percent}%…', percent=c.percent()))
            self.note.setText(c.message or tr('可以先看别的，做完这页的数字会自己更新'))
            self.button.setText(tr('看进度'))
            self.pips.setText('')
            self.show()
            return
        if c.state in {'failed', 'cancelled'}:
            self.title.setText(c.message)
            self.note.setText(tr('点这里再看一次'))
            self.button.setText(tr('交给兔白'))
            self.pips.setText('')
            self.setVisible(plan is not None and plan.fixable > 0)
            return
        if c.state in {'review', 'done'} and c.result is not None:
            if c.state == 'review':
                self.title.setText(tr('{count} 項建議待採用', count=len(c.result.changes)))
                self.note.setText(tr('可先查看各類的修改內容'))
                self.button.setText(tr('查看建議'))
                self.pips.setText('')
                self.show()
                return
            self.title.setText(tr('修好 <b style="color:{color}">{fixed}</b> 项 · 剩 {left} 项留给你',
                                  color=ai, fixed=c.result.fixed, left=c.result.left))
            self.note.setText(tr('点开可以逐条撤回，或还原到兔白处理前'))
            self.button.setText(tr('看结果'))
            self.pips.setText('')
            self.show()
            return
        if plan is None or plan.fixable <= 0:
            self.hide()
            return
        estimate = plan.estimate()
        self.title.setText(tr('<b style="color:{color}">{count}</b> 项我能修，剩下的才要你看',
                              color=ai, count=plan.fixable))
        self.note.setText(tr('{cost}、{time}，不用进工作台', cost=estimate.cost_text(), time=estimate.time_text()))
        dots = ''.join(f'<span style="color:{ai if item.automatic else t.text_muted}">●</span>&nbsp;'
                       for item in plan.categories)
        self.pips.setText(dots)
        self.button.setText(tr('交给兔白'))
        self.show()


# ---------------------------------------------------------------- window

class _FlowLayout(QLayout):
    """Children left to right, wrapping to the next line (the category chips)."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 - Qt override
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802 - Qt override
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802 - Qt override
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width):  # noqa: N802 - Qt override
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self):  # noqa: N802 - Qt override
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802 - Qt override
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect, apply):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y()


class _BunnyRing(QWidget):
    """兔白 (the still) with a progress ring round her while 兔白 works (design B, 2026-11-22)."""

    def __init__(self, size=104, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.progress = None          # None: no ring; 0..1 while running
        self.ring = QColor('#7b5778')
        self.track = QColor('#e8e0d6')
        self._still = None
        try:
            from ..design.bunny_mascot import _still_source
            source = _still_source()
            self._still = None if source.isNull() else source
        except Exception:  # noqa: BLE001 - the ring still works without the picture
            self._still = None

    def set_progress(self, value):
        self.progress = None if value is None else max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        side = min(self.width(), self.height())
        inset = 7
        if self._still is not None:
            box = QRectF(inset, inset, side - 2 * inset, side - 2 * inset)
            image = self._still.size()
            scale = min(box.width() / max(1, image.width()), box.height() / max(1, image.height()))
            w, h = image.width() * scale, image.height() * scale
            painter.drawPixmap(QRectF(box.center().x() - w / 2, box.bottom() - h, w, h), self._still,
                               QRectF(0, 0, image.width(), image.height()))
        if self.progress is not None:
            pen_width = 5
            arc = QRectF(pen_width / 2, pen_width / 2, side - pen_width, side - pen_width)
            painter.setPen(QPen(self.track, pen_width))
            painter.drawEllipse(arc)
            pen = QPen(self.ring, pen_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(arc, 90 * 16, -round(360 * 16 * self.progress))
        painter.end()


class _Tile(QFrame):
    """One of the three big numbers: what 兔白 does locally, with AI, and what she leaves."""

    def __init__(self, tone, parent=None):
        super().__init__(parent)
        self.setObjectName('aiRepairTile')
        self.setProperty('tone', tone)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.icon = QLabel(self)
        self.icon.setObjectName('aiRepairTileIcon')
        self.icon.setProperty('tone', tone)
        self.icon.setFixedSize(30, 30)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.icon)
        self.label = QLabel(self)
        self.label.setObjectName('aiRepairTileLabel')
        head.addWidget(self.label, 1)
        box.addLayout(head)
        self.value = QLabel(self)
        self.value.setObjectName('aiRepairTileValue')
        self.value.setProperty('tone', tone)
        self.value.setTextFormat(Qt.TextFormat.RichText)
        box.addWidget(self.value)
        self.note = QLabel(self)
        self.note.setObjectName('aiRepairTileNote')
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        box.addStretch(1)

    def set(self, icon, color, label, value, unit, note):
        import qtawesome as qta
        self.icon.setPixmap(qta.icon(icon, color=color).pixmap(QSize(15, 15)))
        self.label.setText(label)
        self.value.setText(f'{value}<span style="font-size:13px; font-weight:400"> {unit}</span>')
        self.note.setText(note)


class RepairDialog(SpringDialog):
    """Choose → running → result, in one window.

    2026-11-22 (user picked draft B of ``tmp/repair-window-drafts-20261122``: the old window was
    not good-looking — make it simpler, nicer, easier): 兔白 says the point first in a speech
    bubble, three big numbers say what she fixes locally, what with AI and what she leaves to
    you; the kinds are small chips behind 「调整要修的类别」. While running a ring goes round her
    and a short list ticks off; afterwards the three numbers become fixed / pending / yours and
    the changes are browsed kind by kind, each one undoable. Frameless and rounded like the app's
    other dialogs; modeless, so 「在后台继续」 hides it while the work goes on.
    """

    def __init__(self, controller, parent=None):
        self.controller = controller
        super().__init__(parent, backdrop=False)
        self.setObjectName('aiRepairDialog')
        self.setWindowTitle(tr('交给兔白'))
        self.resize(720, 460)
        self.cards = {}            # automatic kind -> its chip (choosing while idle)
        self.result_chips = {}     # kind -> its chip (browsing the changes when done)
        self.chosen = set()
        self.detail_key = ''
        self.adjusting = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = self.top = QFrame(self)
        top.setObjectName('aiRepairTop')
        top.mousePressEvent = self._move_window
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(26, 12, 12, 0)
        top_row.addStretch(1)
        self.close_button = QPushButton('×', top)
        self.close_button.setObjectName('aiRepairClose')
        self.close_button.setFixedSize(32, 32)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setToolTip(tr('关闭'))
        self.close_button.setAccessibleName(tr('关闭'))
        self.close_button.clicked.connect(self._close_clicked)
        top_row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        outer.addWidget(top)

        scroll = self.scroll = QScrollArea(self)
        scroll.setObjectName('aiRepairScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(scroll)
        body.setObjectName('aiRepairBody')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(26, 0, 26, 8)
        layout.setSpacing(16)

        hero = QHBoxLayout()
        hero.setSpacing(18)
        self.bunny = _BunnyRing(112, body)
        self.bunny.mousePressEvent = self._move_window
        hero.addWidget(self.bunny, 0, Qt.AlignmentFlag.AlignVCenter)
        self.speech = QFrame(body)
        self.speech.setObjectName('aiRepairSpeech')
        words = QVBoxLayout(self.speech)
        words.setContentsMargins(18, 14, 18, 14)
        words.setSpacing(6)
        self.title = QLabel(self.speech)
        self.title.setObjectName('aiRepairTitle')
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.setWordWrap(True)
        words.addWidget(self.title)
        self.subtitle = QLabel(self.speech)
        self.subtitle.setObjectName('aiRepairSubtitle')
        self.subtitle.setWordWrap(True)
        words.addWidget(self.subtitle)
        hero.addWidget(self.speech, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(hero)

        self.tiles_row = QWidget(body)
        tiles = QHBoxLayout(self.tiles_row)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(10)
        self.tiles = [_Tile(tone, self.tiles_row) for tone in ('free', 'ai', 'mine')]
        for tile in self.tiles:
            tiles.addWidget(tile, 1)
        layout.addWidget(self.tiles_row)

        # While running: one line per chosen kind.
        self.steps = QWidget(body)
        self.steps_list = QVBoxLayout(self.steps)
        self.steps_list.setContentsMargins(4, 0, 4, 0)
        self.steps_list.setSpacing(6)
        layout.addWidget(self.steps)

        # Choosing: the kinds, behind a disclosure.
        self.adjust_area = QFrame(body)
        self.adjust_area.setObjectName('aiRepairAdjust')
        adjust = QVBoxLayout(self.adjust_area)
        adjust.setContentsMargins(0, 10, 0, 0)
        adjust.setSpacing(8)
        self.adjust_button = QPushButton(self.adjust_area)
        self.adjust_button.setObjectName('aiRepairDisclose')
        self.adjust_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.adjust_button.clicked.connect(self._toggle_adjust)
        adjust.addWidget(self.adjust_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.chips_host = QWidget(self.adjust_area)
        self.chips = _FlowLayout(self.chips_host, 6)
        adjust.addWidget(self.chips_host)
        self.chips_host.hide()
        layout.addWidget(self.adjust_area)

        # Done: one chip per kind with changes, and that kind's changes.
        self.detail = QFrame(body)
        self.detail.setObjectName('aiRepairAdjust')
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(0, 10, 0, 0)
        detail_layout.setSpacing(8)
        self.result_chips_host = QWidget(self.detail)
        self.result_chips_layout = _FlowLayout(self.result_chips_host, 6)
        detail_layout.addWidget(self.result_chips_host)
        self.detail_title = QLabel(self.detail)
        self.detail_title.setObjectName('aiRepairDetailTitle')
        detail_layout.addWidget(self.detail_title)
        self.detail_rows = QWidget(self.detail)
        self.detail_list = QVBoxLayout(self.detail_rows)
        self.detail_list.setContentsMargins(0, 0, 0, 0)
        self.detail_list.setSpacing(5)
        detail_layout.addWidget(self.detail_rows)
        self.jump_button = QPushButton(self.detail)
        self.jump_button.setObjectName('aiRepairJump')
        self.jump_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.jump_button.clicked.connect(self._jump)
        detail_layout.addWidget(self.jump_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail.hide()
        layout.addWidget(self.detail)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        foot = self.foot = QFrame(self)
        foot.setObjectName('aiRepairFoot')
        foot_row = QHBoxLayout(foot)
        foot_row.setContentsMargins(26, 12, 22, 18)
        foot_row.setSpacing(10)
        self.foot_note = QLabel(foot)
        self.foot_note.setObjectName('aiRepairFootNote')
        self.foot_note.setWordWrap(True)
        foot_row.addWidget(self.foot_note, 1)
        self.secondary = QPushButton(foot)
        self.secondary.setObjectName('aiRepairSecondary')
        self.secondary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secondary.clicked.connect(self._secondary)
        foot_row.addWidget(self.secondary)
        self.primary = QPushButton(foot)
        self.primary.setObjectName('aiRepairPrimary')
        self.primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary.setDefault(True)
        self.primary.clicked.connect(self._primary)
        foot_row.addWidget(self.primary)
        outer.addWidget(foot)
        self.refresh_theme_palette()
        controller.changed.connect(self.refresh)
        self._build_cards()
        self.refresh()

    # --- look ---------------------------------------------------------------
    def _move_window(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.windowHandle() is not None:
            self.windowHandle().startSystemMove()

    def _close_clicked(self):
        # Closing while it runs only hides the window, like 「在后台继续」.
        if self.controller.state == 'running':
            self.hide()
        else:
            self.reject()

    def refresh_theme_palette(self):
        self._applied_theme_key = None          # SpringDialog then always lays its base sheet again
        SpringDialog.refresh_theme_palette(self)
        base = self.styleSheet()
        t = _theme()
        ai = _ai_color(t)
        from ..design.typography import TITLE_FONT_STACK
        heavy = f'font-family: {TITLE_FONT_STACK}; font-weight: 800;'
        on_ai = t.on_vivid
        soft = {'free': (t.success_soft, t.success), 'ai': (blend_hex(t.surface, ai, 0.16), ai),
                'mine': (t.warning_soft, t.warning)}
        if hasattr(self, 'bunny'):
            self.bunny.ring = QColor(ai)
            self.bunny.track = QColor(t.panel)
            self.bunny.update()
        self.setStyleSheet(base + f"""
QDialog#aiRepairDialog, QFrame#aiRepairTop, QWidget#aiRepairBody, QScrollArea#aiRepairScroll,
QScrollArea#aiRepairScroll > QWidget > QWidget {{ background:{t.surface}; border:0; }}
QPushButton#aiRepairClose {{ background:transparent; color:{t.text_muted}; border:0; border-radius:16px; font-size:20px; padding:0; }}
QPushButton#aiRepairClose:hover {{ background:{t.panel}; color:{t.text}; }}
QFrame#aiRepairSpeech {{ background:{t.surface_elevated}; border:1px solid {t.border};
 border-top-left-radius:20px; border-top-right-radius:20px; border-bottom-right-radius:20px; border-bottom-left-radius:6px; }}
QLabel#aiRepairTitle {{ color:{t.text}; font-size:21px; {heavy} background:transparent; }}
QLabel#aiRepairSubtitle {{ color:{t.text_muted}; font-size:13px; background:transparent; }}
QFrame#aiRepairTile {{ background:{t.surface_elevated}; border:1px solid {t.border}; border-radius:16px; }}
QLabel#aiRepairTileIcon {{ border-radius:10px; }}
QLabel#aiRepairTileIcon[tone="free"] {{ background:{soft['free'][0]}; }}
QLabel#aiRepairTileIcon[tone="ai"] {{ background:{soft['ai'][0]}; }}
QLabel#aiRepairTileIcon[tone="mine"] {{ background:{soft['mine'][0]}; }}
QLabel#aiRepairTileLabel {{ color:{t.text_secondary}; font-size:13px; {heavy} background:transparent; }}
QLabel#aiRepairTileValue {{ color:{t.text}; font-size:30px; {heavy} background:transparent; }}
QLabel#aiRepairTileValue[tone="mine"] {{ color:{t.warning}; }}
QLabel#aiRepairTileValue[tone="done"] {{ color:{t.success}; }}
QLabel#aiRepairTileNote {{ color:{t.text_muted}; font-size:12px; background:transparent; }}
QFrame#aiRepairAdjust {{ background:transparent; border:0; border-top:1px dashed {t.border}; }}
QPushButton#aiRepairDisclose {{ background:transparent; border:0; color:{t.text_secondary}; font-size:13px; {heavy} padding:4px 0; text-align:left; }}
QPushButton#aiRepairDisclose:hover {{ color:{t.text}; }}
QPushButton#aiRepairChip {{ background:{t.surface_elevated}; color:{t.text}; border:1px solid {t.border}; border-radius:15px;
 padding:5px 12px; font-size:13px; text-align:left; }}
QPushButton#aiRepairChip:hover {{ border-color:{t.border_strong}; }}
QPushButton#aiRepairChip[chosen="true"] {{ border-color:{blend_hex(t.surface, ai, 0.5)}; }}
QPushButton#aiRepairChip[chosen="false"] {{ color:{t.text_muted}; text-decoration:line-through; }}
QPushButton#aiRepairChip[current="true"] {{ border:2px solid {ai}; padding:4px 11px; }}
QLabel#aiRepairStep {{ color:{t.text_secondary}; font-size:14px; background:transparent; }}
QLabel#aiRepairStepCount {{ color:{t.text_muted}; font-family:Consolas, monospace; font-size:12px; background:transparent; }}
QLabel#aiRepairDetailTitle {{ color:{t.text}; font-size:13px; {heavy} background:transparent; }}
QFrame#aiRepairChange {{ background:{t.surface_elevated}; border:0; border-radius:10px; }}
QLabel#aiRepairChangeText {{ color:{t.text}; font-size:13px; background:transparent; }}
QLabel#aiRepairChangeTime {{ color:{t.text_muted}; font-size:12px; background:transparent; }}
QPushButton#aiRepairUndo {{ background:transparent; color:{ai}; border:0; font-size:12px; {heavy} text-decoration:underline; }}
QPushButton#aiRepairJump {{ background:{t.panel}; color:{t.text}; border:0; border-radius:10px; padding:6px 12px; font-size:12px; }}
QFrame#aiRepairFoot {{ background:{t.surface}; border:0; }}
QLabel#aiRepairFootNote {{ color:{t.text_muted}; font-size:12px; background:transparent; }}
QPushButton#aiRepairSecondary {{ background:transparent; color:{t.text_secondary}; border:0; border-radius:12px;
 padding:9px 16px; font-size:14px; {heavy} }}
QPushButton#aiRepairSecondary:hover {{ background:{t.panel}; color:{t.text}; }}
QPushButton#aiRepairPrimary {{ background:{ai}; color:{on_ai}; border:0; border-radius:12px; font-size:14px; {heavy} padding:10px 22px; }}
QPushButton#aiRepairPrimary:hover {{ background:{blend_hex(ai, on_ai, 0.12)}; }}
QPushButton#aiRepairPrimary:disabled {{ background:{t.panel}; color:{t.disabled}; }}
""")
        if hasattr(self, 'tiles'):
            self.refresh()

    # --- choosing -------------------------------------------------------
    def _chip(self, parent, text, kind):
        button = QPushButton(text, parent)
        button.setObjectName('aiRepairChip')
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        t = _theme()
        colour = {'free': t.success, 'ai': _ai_color(t), 'mine': t.warning}[kind]
        import qtawesome as qta
        button.setIcon(qta.icon('fa5s.circle', color=colour))
        button.setIconSize(QSize(8, 8))
        return button

    def _build_cards(self):
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self.cards = {}
        plan = self.controller.plan
        if plan is None:
            return
        if self.controller.state == 'running':
            self.chosen = set(self.controller.selected)
        else:
            self.chosen = {item.key for item in plan.categories if item.automatic}
        for category in plan.categories:
            if not category.automatic:
                continue
            kind = 'free' if category.key in repair.LOCAL else 'ai'
            chip = self._chip(self.chips_host, f'{tr(category.label)} · {category.count}', kind)
            chip.setToolTip(tr(category.method))
            chip.clicked.connect(lambda _checked=False, key=category.key: self._card_clicked(key))
            self.chips.addWidget(chip)
            self.cards[category.key] = chip
        self._mark_chips()

    def _mark_chips(self):
        for key, chip in self.cards.items():
            chip.setProperty('chosen', key in self.chosen)
            chip.style().unpolish(chip)
            chip.style().polish(chip)

    def _toggle_adjust(self):
        self.adjusting = not self.adjusting
        self.refresh()

    def _card_clicked(self, key):
        c = self.controller
        if c.state != 'idle':
            return
        category = c.plan.category(key) if c.plan else None
        if category is None or not category.automatic:
            return
        self.chosen ^= {key}
        self._mark_chips()
        self.refresh()

    # --- states ---------------------------------------------------------
    def _counts(self):
        plan = self.controller.plan
        local = sum(item.count for item in plan.categories if item.automatic and item.key in self.chosen
                    and item.key in repair.LOCAL)
        ai = sum(item.count for item in plan.categories if item.automatic and item.key in self.chosen
                 and item.key not in repair.LOCAL)
        return local, ai, plan.manual

    def _show_parts(self, *, tiles=True, steps=False, adjust=False, detail=False):
        self.tiles_row.setVisible(tiles)
        self.steps.setVisible(steps)
        self.adjust_area.setVisible(adjust)
        self.detail.setVisible(detail)

    def refresh(self):
        self._refresh_state()
        self._fit()
        QTimer.singleShot(0, self._fit)       # once more after the new rows are laid out

    def _refresh_state(self):
        c = self.controller
        plan = c.plan
        t = _theme()
        ai = _ai_color(t)
        self.bunny.set_progress(None)
        if c.state == 'idle':
            if plan is None:
                self.title.setText(tr('这个结果没有可以交给兔白的'))
                self.subtitle.setText('')
                self._show_parts(tiles=False)
                self.foot_note.setText('')
                self.secondary.setText(tr('关闭'))
                self.primary.setText(tr('交给我吧'))
                self.primary.setEnabled(False)
                return
            if set(self.cards) != {item.key for item in plan.categories if item.automatic}:
                self._build_cards()
            local, with_ai, mine = self._counts()
            estimate = plan.estimate(self.chosen)
            cost = estimate.cost_text()
            if len(cost) <= 12:      # a short price belongs in the sentence; a long caveat below it
                self.title.setText(tr('我能修 <b style="color:{color}">{count}</b> 项，{time}，{cost}。',
                                      color=ai, count=local + with_ai, time=tr(estimate.time_text()), cost=tr(cost)))
                self.subtitle.setText(tr('改完每条都能撤回；不会打开字幕工作台。'))
            else:
                self.title.setText(tr('我能修 <b style="color:{color}">{count}</b> 项，大约 {time}。',
                                      color=ai, count=local + with_ai, time=tr(estimate.time_text())))
                self.subtitle.setText(tr('改完每条都能撤回；不会打开字幕工作台。'))
            self.tiles[0].set('fa5s.stopwatch', t.success, tr('本机修'), local, tr('项'),
                              tr('时间太短、太快的字幕，用前后空档延长。免费。'))
            self.tiles[1].set('fa5s.microphone', ai, tr('用 AI 修'), with_ai, tr('项'),
                              tr('漏掉的台词、没切准的句子、听法不一的字。'))
            self.tiles[2].set('fa5s.user-tag', t.warning, tr('留给你'), mine, tr('项'),
                              tr('说话人和其他要你看的，兔白不猜。'))
            self._set_tone(self.tiles[2], 'mine')
            self._show_parts(adjust=bool(self.cards))
            self.chips_host.setVisible(self.adjusting)
            self.adjust_button.setText(('▾  ' if self.adjusting else '▸  ') + tr('调整要修的类别'))
            notes = [tr(cost)] if len(cost) > 12 else []      # the long price caveat sits down here
            if estimate.audio_seconds:
                notes.append(tr('要再听 {seconds} 秒音频', seconds=round(estimate.audio_seconds)))
            self.foot_note.setText(' · '.join(str(note) for note in notes))
            self.secondary.setText(tr('先不要'))
            self.primary.setText(tr('交给我吧'))
            self.primary.setEnabled(local + with_ai > 0)
        elif c.state == 'running':
            if not self.cards:
                self._build_cards()
            percent = c.percent()
            self.bunny.set_progress(percent / 100)
            self.title.setText(tr('正在修… <b style="color:{color}">{percent}%</b>', color=ai, percent=percent))
            self.subtitle.setText(c.message or tr('可以关掉这个窗，我会在后台做完；取消的话做到一半的不保存。'))
            self._show_steps()
            self._show_parts(tiles=False, steps=True)
            self.foot_note.setText('')
            self.secondary.setText(tr('取消'))
            self.primary.setText(tr('在后台继续'))
            self.primary.setEnabled(True)
        elif c.state in {'review', 'done'} and c.result is not None:
            result = c.result
            reviewing = c.state == 'review'
            if reviewing:
                self.title.setText(tr('{count} 項建議待採用', count=len(result.changes)))
                self.subtitle.setText(tr('展開各類查看前後差異。採用後可逐條撤回。'))
            else:
                self.title.setText(tr('修好了 <b style="color:{color}">{fixed}</b> 项！', color=ai, fixed=result.fixed))
                self.subtitle.setText(tr('剩下的我在结果页标出来了；下面可以逐条撤回。'))
            self.tiles[0].set('fa5s.check', t.success, tr('建議') if reviewing else tr('修好'),
                              len(result.changes) if reviewing else result.fixed, tr('项'), tr('每条都能撤回。'))
            self._set_tone(self.tiles[0], 'done')
            pending = sum(item.left for key, item in result.categories.items() if key not in repair.MANUAL)
            self.tiles[1].set('fa5s.eye', ai, tr('待处理'), pending, tr('项'), tr('原因写在每一类下面。'))
            self.tiles[2].set('fa5s.user-tag', t.warning, tr('留给你'), plan.manual if plan else 0, tr('项'),
                              tr('说话人和其他，兔白没碰。'))
            self._show_parts(detail=True)
            self._show_result_chips()
            self.foot_note.setText(tr('调用了 {count} 次文字 AI（实际花费见「用量与费用」）', count=result.requests)
                                   if result.requests else tr('没有调用文字 AI，不花钱'))
            self.secondary.setText(tr('關閉') if reviewing else tr('还原到兔白处理前'))
            self.primary.setText(tr('採用這 {count} 項', count=len(result.changes)) if reviewing else tr('好'))
            self.primary.setEnabled(True)
        else:
            self.title.setText(c.message or tr('兔白停下了'))
            self.subtitle.setText(tr('工程没有被改动。'))
            self._show_parts(tiles=False)
            self.foot_note.setText('')
            self.secondary.setText(tr('关闭'))
            self.primary.setText(tr('再试一次'))
            self.primary.setEnabled(plan is not None and plan.fixable > 0)

    def _fit(self):
        """The window is as tall as what it shows (design B: no empty space under a short state),
        up to what fits on the screen; past that the middle scrolls."""
        from shiboken6 import isValid
        if not isValid(self):
            return
        body = self.scroll.widget()
        layout = body.layout()
        layout.activate()
        width = max(1, self.width())
        inner = layout.totalHeightForWidth(width) if layout.hasHeightForWidth() else layout.totalSizeHint().height()
        wanted = self.top.sizeHint().height() + inner + self.foot.sizeHint().height() + 2
        screen = self.screen().availableGeometry().height() if self.screen() is not None else 900
        height = max(260, min(wanted, 720, screen - 60))
        if abs(self.height() - height) > 2:
            self.resize(width, height)

    @staticmethod
    def _set_tone(tile, tone):
        tile.value.setProperty('tone', tone)
        tile.value.style().unpolish(tile.value)
        tile.value.style().polish(tile.value)

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()            # gone now, not when the deferred delete runs
                item.widget().deleteLater()

    def _show_steps(self):
        c = self.controller
        t = _theme()
        self._clear(self.steps_list)
        plan = c.plan
        for key in repair.ORDER:
            if key not in c.selected or plan is None or plan.category(key) is None:
                continue
            done, total, phase = c.progress.get(key, (0, plan.category(key).count, ''))
            if done >= total:
                mark, colour = '✓', t.success
            elif done > 0 or phase:
                mark, colour = '●', _ai_color(t)
            else:
                mark, colour = '○', t.border_strong
            row = QWidget(self.steps)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(10)
            sign = QLabel(mark, row)
            sign.setFixedWidth(16)
            sign.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sign.setStyleSheet(f'color:{colour}; background:transparent; font-weight:800;')
            line.addWidget(sign)
            name = QLabel(tr(phase) if phase and 0 < done < total else tr(repair.CATEGORIES[key][0]), row)
            name.setObjectName('aiRepairStep')
            line.addWidget(name, 1)
            count = QLabel(f'{done}/{total}', row)
            count.setObjectName('aiRepairStepCount')
            line.addWidget(count)
            self.steps_list.addWidget(row)

    def _show_result_chips(self):
        c = self.controller
        self._clear(self.result_chips_layout)
        self.result_chips = {}
        keys = [key for key in repair.ORDER if key not in repair.MANUAL and c.result.categories.get(key) is not None
                and (c.result.categories[key].changes or c.result.categories[key].left)]
        if self.detail_key not in keys:
            self.detail_key = next((key for key in keys if c.result.categories[key].changes), keys[0] if keys else '')
        for key in keys:
            result = c.result.categories[key]
            kind = 'free' if key in repair.LOCAL else 'ai'
            chip = self._chip(self.result_chips_host, f'{tr(repair.CATEGORIES[key][0])} · {result.fixed}', kind)
            chip.setProperty('current', key == self.detail_key)
            chip.clicked.connect(lambda _checked=False, key=key: self._select_detail(key))
            self.result_chips_layout.addWidget(chip)
            self.result_chips[key] = chip
        self._show_detail()

    def _select_detail(self, key):
        self.detail_key = key
        for other, chip in self.result_chips.items():
            chip.setProperty('current', other == key)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        self._show_detail()

    def _show_detail(self):
        c = self.controller
        key = self.detail_key
        self._clear(self.detail_list)
        result = c.result.categories.get(key) if c.result else None
        if result is None:
            self.detail_title.setText('')
            self.jump_button.hide()
            return
        label = tr(repair.CATEGORIES.get(key, (key,))[0])
        self.detail_title.setText(tr('{label} · 建議 {count}', label=label, count=len(result.changes))
                                  if c.state == 'review' else
                                  tr('{label} · 修好 {fixed} · 剩 {left}', label=label, fixed=result.fixed, left=result.left))
        undone = {row['change_id']: row.get('undone') for row in (c.record or {}).get('changes', ())}
        for change in result.changes if c.state == 'review' else result.changes[:200]:
            self.detail_list.addWidget(self._change_row(change, bool(undone.get(change.change_id))))
        for count, reason in result.reasons:
            note = QLabel(tr('剩 {count}：{reason}', count=count, reason=tr(reason)), self.detail_rows)
            note.setObjectName('aiRepairChangeTime')
            note.setWordWrap(True)
            self.detail_list.addWidget(note)
        self.jump_button.setVisible(bool(result.left))
        self.jump_button.setText(tr('到工作台看这 {count} 条', count=result.left))

    def _change_row(self, change, undone):
        t = _theme()
        frame = QFrame(self.detail_rows)
        frame.setObjectName('aiRepairChange')
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)
        when = QLabel(_clock(change.at_ms), frame)
        when.setObjectName('aiRepairChangeTime')
        row.addWidget(when)
        old, new = change.describe()
        import html
        if old and new and old == new:
            text = f'<b>{html.escape(new)}</b>'
        elif old and new:
            text = (f'<span style="color:{t.text_muted}; text-decoration:line-through">{html.escape(old)}</span>'
                    f' → <b>{html.escape(new)}</b>')
        elif new:
            text = f'<b>{html.escape(new)}</b>'
        else:
            text = html.escape(tr(change.note))
        if change.note and (old or new):
            text += f' <span style="color:{t.text_muted}">· {html.escape(tr(change.note))}</span>'
        if undone:
            text = f'<span style="color:{t.text_muted}">{text}</span>'
        words = QLabel(text, frame)
        words.setObjectName('aiRepairChangeText')
        words.setTextFormat(Qt.TextFormat.RichText)
        words.setWordWrap(True)
        row.addWidget(words, 1)
        if self.controller.state == 'review':
            return frame
        button = QPushButton(tr('改回兔白的') if undone else tr('撤回这条'), frame)
        button.setObjectName('aiRepairUndo')
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        def toggle(_checked=False, change_id=change.change_id, now=undone):
            if not self.controller.undo_change(change_id, not now):
                soft_information(self, tr('没有撤回'),
                                 tr('这条字幕在兔白之后又被改过，为了不盖掉你的修改，没有动它。'), tone='warning')
        button.clicked.connect(toggle)
        row.addWidget(button)
        return frame

    # --- buttons --------------------------------------------------------
    def _jump(self):
        c = self.controller
        window = c.window
        key = self.detail_key
        plan = c.plan
        category = plan.category(key) if plan else None
        rows = [row for row in (category.rows if category else ()) if isinstance(row, dict)]
        self.accept()
        if key == 'speech':
            window._open_ai_repair_speech()
        elif rows and (rows[0].get('cue_ids') or rows[0].get('target') == 'speakers'):
            window._open_completion_review_row(rows[0])
        else:
            window._show_completion_review_details()

    def _secondary(self):
        c = self.controller
        if c.state == 'idle':
            self.reject()
        elif c.state == 'running':
            c.cancel()
        elif c.state == 'done':
            if c.restore():
                self.accept()
        else:
            self.reject()

    def _primary(self):
        c = self.controller
        if c.state == 'idle':
            c.start(self.chosen)
        elif c.state == 'running':
            self.hide()
        elif c.state == 'done':
            self.accept()
        elif c.state == 'review':
            c.approve_review()
        else:
            c.reset()
            self.detail_key = ''
            self._build_cards()
            self.refresh()


def open_repair(window):
    """The bubble's click: the window for the current state (one at a time)."""
    controller = window._ai_repair
    dialog = controller.dialog
    if dialog is not None:
        try:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return dialog
        except RuntimeError:
            controller.dialog = None
    dialog = RepairDialog(controller, window)
    controller.dialog = dialog

    def closed(_result=0):
        if controller.dialog is dialog:
            controller.dialog = None
        dialog.deleteLater()
    dialog.finished.connect(closed)
    dialog.show()
    return dialog
