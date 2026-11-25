"""Editable audio-event marks on the project clock, independent of subtitles."""
from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from uuid import uuid4

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QUndoCommand
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableView, QVBoxLayout,
)

from ..i18n import tr
from ..projects.project_range import clock_text, parse_clock
from ..timeline.interval_end_index import IntervalEndIndex
from ..timeline.studio_edit_sequence import timeline_duration_ms


KEY = "sound_event_notes"
KINDS = {
    "laugh": "笑声", "cough": "咳嗽", "sigh": "叹气", "throat": "清嗓",
    "pant": "喘息", "inhale": "吸气", "cry": "哭声", "applause": "掌声",
    "music": "音乐", "other": "其他声音",
}


@dataclass(frozen=True, slots=True)
class SoundEvent:
    id: str
    kind: str
    start_ms: int
    end_ms: int
    confirmed: bool = False


def read_events(project):
    rows = project.studio_state.get(KEY, ())
    if not isinstance(rows, (list, tuple)):
        return ()
    events = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident, kind = row.get("id"), row.get("kind")
        start, end = row.get("start_ms"), row.get("end_ms")
        if (not isinstance(ident, str) or not ident or not isinstance(kind, str)
                or kind not in KINDS or type(start) is not int or type(end) is not int
                or not 0 <= start < end):
            continue
        events.setdefault(ident, SoundEvent(ident, kind, start, end, row.get("confirmed") is True))
    return tuple(sorted(events.values(), key=lambda event: (event.start_ms, event.end_ms, event.id)))


class SoundEventsCommand(QUndoCommand):
    def __init__(self, project, after):
        super().__init__(tr("编辑声音事件"))
        self.project = project
        self.before = deepcopy(project.studio_state.get(KEY))
        self.had_events = KEY in project.studio_state
        self.after = [asdict(event) for event in after]

    def _apply(self, events, *, present=True):
        from ..projects.studio_runtime_state import DirtyDomain
        from ..timeline.studio_commands import _commit_mutation

        def mutate():
            if present:
                self.project.studio_state[KEY] = deepcopy(events)
            else:
                self.project.studio_state.pop(KEY, None)

        _commit_mutation(self.project, action_id="sound_events",
                         dirty=DirtyDomain.TIMELINE_PIXELS | DirtyDomain.AUTOSAVE,
                         cue_ids=(), studio_state_keys=(KEY,), changed=None,
                         mutate=mutate)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before, present=self.had_events)


class SoundEventsModel(QAbstractTableModel):
    def __init__(self, events, parent):
        super().__init__(parent)
        self.events = list(events)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.events)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 4

    def headerData(self, column, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(("声音", "开始", "结束", "状态")[column])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        event = self.events[index.row()]
        return (tr(KINDS[event.kind]), clock_text(event.start_ms), clock_text(event.end_ms),
                tr("已确认" if event.confirmed else "待确认"))[index.column()]

    def update_row(self, row, value):
        if row is None:
            position = len(self.events)
            self.beginInsertRows(QModelIndex(), position, position)
            self.events.append(value)
            self.endInsertRows()
            return
        self.events[row] = value
        self.dataChanged.emit(self.index(row, 0), self.index(row, 3))

    def remove_row(self, row):
        self.beginRemoveRows(QModelIndex(), row, row)
        self.events.pop(row)
        self.endRemoveRows()


def _edit(parent, event, duration):
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("声音事件"))
    form = QFormLayout(dialog)
    kind = QComboBox(dialog)
    for key, title in KINDS.items():
        kind.addItem(tr(title), key)
    kind.setCurrentIndex(kind.findData(event.kind))
    start = QLineEdit(clock_text(event.start_ms), dialog)
    end = QLineEdit(clock_text(event.end_ms), dialog)
    error = QLabel(dialog)
    form.addRow(tr("声音"), kind)
    form.addRow(tr("开始"), start)
    form.addRow(tr("结束"), end)
    form.addRow(error)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, dialog)
    form.addRow(buttons)
    buttons.rejected.connect(dialog.reject)
    result = []

    def save():
        first, last = parse_clock(start.text()), parse_clock(end.text())
        if first is None or last is None or not 0 <= first < last <= duration:
            error.setText(tr("时间必须在工程内，且终点晚于起点"))
            return
        value = SoundEvent(event.id, str(kind.currentData()), first, last)
        result.append(event if value == replace(event, confirmed=False) else value)
        dialog.accept()

    buttons.accepted.connect(save)
    dialog.exec()
    return result[0] if result else None


def show(page):
    project = page.project
    if project is None:
        return
    duration = timeline_duration_ms(project)
    if duration <= 0:
        page._show_studio_hint(tr("请先添加包含声音的素材"))
        return
    original = read_events(project)
    dialog = QDialog(page)
    dialog.setObjectName("studioSoundEvents")
    dialog.setWindowTitle(tr("声音事件"))
    dialog.resize(645, 388)
    layout = QVBoxLayout(dialog)
    table = QTableView(dialog)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setStretchLastSection(True)
    model = SoundEventsModel(original, table)
    table.setModel(model)
    layout.addWidget(table)
    row_actions = QHBoxLayout()
    layout.addLayout(row_actions)

    def index():
        row = table.currentIndex().row()
        return row if 0 <= row < len(model.events) else None

    def mutate(edit):
        row = index() if edit else None
        if edit and row is None:
            return
        start = min(max(0, int(page.timeline.playhead_ms)), duration - 1)
        seed = SoundEvent(uuid4().hex, "other", start, min(duration, start + 500))
        value = _edit(dialog, model.events[row] if edit else seed, duration)
        if value is not None:
            model.update_row(row, value)

    def confirm():
        row = index()
        if row is not None:
            model.update_row(row, replace(model.events[row], confirmed=True))

    def remove():
        row = index()
        if row is not None:
            model.remove_row(row)

    def locate():
        row = index()
        if row is not None and page.project is project:
            page._seek(model.events[row].start_ms / 1000)

    for label, callback in (("新增", lambda: mutate(False)), ("修改", lambda: mutate(True)),
                            ("确认", confirm), ("删除", remove), ("定位", locate)):
        button = QPushButton(tr(label), dialog)
        button.setAutoDefault(False)
        button.clicked.connect(callback)
        row_actions.addWidget(button)
    row_actions.addStretch(1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, dialog)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    from ..design.studio_theme import apply_secondary_surface_theme
    apply_secondary_surface_theme(dialog)
    if dialog.exec() != QDialog.DialogCode.Accepted or page.project is not project:
        return
    after = tuple(sorted(model.events, key=lambda event: (event.start_ms, event.end_ms, event.id)))
    if after != original:
        page.undo_stack.push(SoundEventsCommand(project, after))
        page.sound_event_toggle.setChecked(True)


def paint(timeline, painter, visible_start, visible_end):
    project = timeline.project
    raw = project.studio_state.get(KEY)
    cached = getattr(timeline, "_sound_events_paint_cache", None)
    if cached is None or cached[0] != id(project) or cached[1] is not raw:
        events = read_events(project)
        starts = tuple(event.start_ms for event in events)
        ends = IntervalEndIndex(event.end_ms for event in events)
        cached = timeline._sound_events_paint_cache = (id(project), raw, events, starts, ends)
    _, _, events, starts, ends = cached
    left, right = timeline.TRACK_HEADER_WIDTH, timeline._content_right()
    stop = bisect_left(starts, visible_end)
    for index in ends.before_with_end_after(stop, visible_start):
        event = events[index]
        first = max(left, timeline._time_to_x(event.start_ms))
        last = min(right, timeline._time_to_x(event.end_ms))
        if last > first:
            color = QColor("#2f9e86" if event.confirmed else "#c48c3a")
            painter.fillRect(QRectF(first, timeline.RULER_HEIGHT - 6, last - first, 4), color)
