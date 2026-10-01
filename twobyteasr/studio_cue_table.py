"""Cue list table: speaker/cue row helpers, table model, and delegates."""

from __future__ import annotations

from .i18n import tr
from .playback_probe import measured

from collections.abc import Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QStyledItemDelegate

from .studio_helpers import _format_ms
from .studio_project import StudioCue, SubtitleProject
from .studio_qc import QCSeverity
from .studio_review import cached_qc_result, cached_review_risks
from .studio_theme import studio_status_colors
from .timeline_theme import TimelinePalette, timeline_palette
from .ui_theme import GREEN

_KNOWN_SPEAKER_COLORS = {
    "moss": "#5f9270",
    "玩家": "#6186b0",
    "player": "#6186b0",
    "莉莉丝": "#8d70a0",
    "lilith": "#8d70a0",
    "系统": "#858179",
    "system": "#858179",
    "s01": "#aa855d",
    "s02": "#9b7180",
    "s03": "#628c79",
}


_FALLBACK_SPEAKER_COLORS = ("#638d85", "#9a7f62", "#687f9c", "#7e8363", "#906c76")


def _speaker_name(project: SubtitleProject | None, speaker_id: str) -> str:
    if project:
        for speaker in project.speakers:
            if speaker.id == speaker_id:
                from .speaker_names import display_speaker_name
                return display_speaker_name(project, speaker)
    return speaker_id


def _speaker_color(project: SubtitleProject | None, speaker_id: str, palette: TimelinePalette | None = None) -> QColor:
    active = palette or timeline_palette()
    fallbacks = active.speaker_accents or _FALLBACK_SPEAKER_COLORS
    name = _speaker_name(project, speaker_id)
    if project:
        for speaker in project.speakers:
            if speaker.id == speaker_id and QColor.isValidColor(speaker.color):
                return QColor(speaker.color)
    stable = sum((index + 1) * ord(char) for index, char in enumerate(speaker_id))
    return QColor(fallbacks[stable % len(fallbacks)])


def _source_key(cue: StudioCue) -> str:
    """工程状态映射（状态/审核/QC）按源 cue id 键控；派生 id 解析回源。"""
    from .studio_edit_sequence import source_cue_id_of

    return source_cue_id_of(str(cue.id))


def _cue_status(project: SubtitleProject | None, cue: StudioCue) -> str:
    statuses = project.studio_state.get("cue_statuses", {}) if project else {}
    if isinstance(statuses, dict):
        value = str(statuses.get(_source_key(cue), "") or "").strip().lower()
        if value in {"pending", "issue", "done"}:
            return value
    if not cue.text.strip() or cue.end_ms <= cue.start_ms:
        return "issue"
    return "done" if cue.text != cue.original_text else "pending"


def _cue_review_level(project: SubtitleProject | None, cue: StudioCue) -> str:
    risks = cached_review_risks(project)
    row = risks.get(_source_key(cue), {}) if isinstance(risks, dict) else {}
    return str(row.get("level", "confident")) if isinstance(row, dict) else "confident"


def _cue_review_score(project: SubtitleProject | None, cue: StudioCue) -> int:
    risks = cached_review_risks(project)
    row = risks.get(_source_key(cue), {}) if isinstance(risks, dict) else {}
    try:
        return int(row.get("score", 0)) if isinstance(row, dict) else 0
    except (TypeError, ValueError):
        return 0


def _cue_explicitly_confirmed(project: SubtitleProject | None, cue: StudioCue) -> bool:
    statuses = project.studio_state.get("cue_statuses", {}) if project else {}
    return isinstance(statuses, dict) and str(statuses.get(_source_key(cue), "")).lower() == "done"


class CueTableModel(QAbstractTableModel):
    text_edit_requested = Signal(str, str)
    ActiveCueRole = int(Qt.ItemDataRole.UserRole) + 1
    HEADERS = ("#", "开始时间", "说话人", "文本", "状态")

    def __init__(self, project: SubtitleProject | None = None, parent=None):
        super().__init__(parent)
        self.project = project
        self.filter_status = "all"
        self.query = ""
        self._rows: list[int] = []
        self._cue_row_lookup: dict[str, int] = {}
        self.scope_ids: tuple[str, ...] | None = None
        self.active_cue_ids: frozenset[str] = frozenset()
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        self._rows = []
        self._cue_row_lookup = {}
        self._view_cues = []
        if not self.project:
            return
        # 2026-09-19 P0：列表展示的是当前活动序列的投影视图（identity
        # 序列零开销直通源列表；剪辑模式=派生 cue+序列时间）。行索引与
        # cue_at 全部走 _view_cues；状态/审核/QC 查找按源 id 解析。
        from .studio_edit_sequence import projected_cues

        view = projected_cues(self.project, domain="timeline")
        self._view_cues = view
        needle = self.query.casefold().strip()
        scope = set(self.scope_ids) if self.scope_ids is not None else None
        for row, cue in enumerate(view):
            if scope is not None:
                if cue.id not in scope:
                    continue
                self._rows.append(row)
                continue
            status = _cue_status(self.project, cue)
            speaker = _speaker_name(self.project, cue.speaker_id)
            if self.filter_status == "priority":
                if _cue_explicitly_confirmed(self.project, cue) or _cue_review_level(self.project, cue) == "confident":
                    continue
            elif self.filter_status == "critical":
                issues = cached_qc_result(self.project).for_cue(_source_key(cue))
                if _cue_explicitly_confirmed(self.project, cue) or not any(
                    issue.severity == QCSeverity.CRITICAL for issue in issues
                ):
                    continue
            elif self.filter_status != "all" and status != self.filter_status:
                continue
            if needle and needle not in f"{cue.text} {cue.speaker_id} {speaker}".casefold():
                continue
            self._rows.append(row)
        # Filters change visibility only. Every visible list, including
        # Priority, follows the same chronological order as the timeline.
        self._rows.sort(
            key=lambda source_row: (
                self._view_cues[source_row].start_ms,
                source_row,
                self._view_cues[source_row].id,
            )
        )
        self._cue_row_lookup = {
            self._view_cues[source_row].id: row
            for row, source_row in enumerate(self._rows)
        }

    def set_filter(self, status: str) -> None:
        self.beginResetModel()
        self.filter_status = status if status in {"all", "priority", "critical", "pending", "issue", "done"} else "all"
        self._rebuild_rows()
        self.endResetModel()

    def set_query(self, query: str) -> None:
        self.beginResetModel()
        self.query = str(query or "")
        self._rebuild_rows()
        self.endResetModel()

    def set_scope_ids(self, cue_ids: Iterable[str] | None) -> None:
        self.beginResetModel()
        self.scope_ids = (
            tuple(dict.fromkeys(str(cue_id) for cue_id in cue_ids if str(cue_id)))
            if cue_ids is not None else None
        )
        self._rebuild_rows()
        self.endResetModel()

    def source_row(self, row: int) -> int:
        return self._rows[row]

    def cue_at(self, row: int) -> StudioCue:
        return self._view_cues[self.source_row(row)]

    def row_for_cue_id(self, cue_id: str) -> int:
        return self._cue_row_lookup.get(str(cue_id), -1)

    def set_project(self, project: SubtitleProject | None) -> None:
        self.beginResetModel()
        self.project = project
        self.active_cue_ids = frozenset()
        self._rebuild_rows()
        self.endResetModel()

    @measured('list_highlight')
    def set_active_cues(self, cue_ids: Iterable[str]) -> None:
        ids = frozenset(cue_ids)
        changed = ids ^ self.active_cue_ids
        self.active_cue_ids = ids
        for cue_id in changed:
            row = self.row_for_cue_id(cue_id)
            if row >= 0:
                # Only the number-cell playback marker; no row selection,
                # scrolling, reset, status/QC calculation or editor signal.
                index = self.index(row, 0)
                self.dataChanged.emit(index, index, [self.ActiveCueRole])

    def refresh(self) -> None:
        self.beginResetModel()
        self._rebuild_rows()
        self.endResetModel()
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 4))

    def refresh_cue(self, cue_id: str, columns: tuple[int, ...] | None = None) -> None:
        if self.scope_ids is None and (self.filter_status != "all" or self.query.strip()):
            self.refresh()
            return
        row = self.row_for_cue_id(cue_id)
        if row >= 0:
            changed_columns = columns if columns is not None else tuple(range(self.columnCount()))
            for column in changed_columns:
                if 0 <= column < self.columnCount():
                    self.dataChanged.emit(self.index(row, column), self.index(row, column))

    def rowCount(self, _parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, _parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return tr(self.HEADERS[section])
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not self.project:
            return None
        cue = self.cue_at(index.row())
        if role == self.ActiveCueRole:
            return cue.id in self.active_cue_ids
        status = _cue_status(self.project, cue)
        if role == Qt.ItemDataRole.UserRole:
            return cue.id
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                self.source_row(index.row()) + 1,
                _format_ms(cue.start_ms),
                _speaker_name(self.project, cue.speaker_id),
                cue.text,
                tr({"pending": "待确认", "issue": "有问题", "done": "已完成"}[status]),
            )
            if index.column() == 4 and self.filter_status in {"priority", "critical"}:
                return tr({"high": "需要检查", "suggested": "建议确认"}.get(
                    _cue_review_level(self.project, cue), "待确认"
                ))
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            risks = cached_review_risks(self.project)
            row = risks.get(cue.id, {}) if isinstance(risks, dict) else {}
            reasons = row.get("reasons", []) if isinstance(row, dict) else []
            if reasons:
                return "；".join(str(reason) for reason in reasons)
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 2:
            return _speaker_color(self.project, cue.speaker_id).darker(120)
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 4:
            status_colors = studio_status_colors()
            if self.filter_status in {"priority", "critical"}:
                key = "issue" if _cue_review_level(self.project, cue) == "high" else "pending"
                return QColor(status_colors[key][1])
            return QColor({"pending": status_colors["pending"][1],
                           "issue": status_colors["issue"][1],
                           "done": status_colors["done"][1]}[status])
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {0, 1, 4}:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and index.column() == 3:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (
            role != Qt.ItemDataRole.EditRole
            or not index.isValid()
            or index.column() != 3
            or not self.project
        ):
            return False
        cue = self.cue_at(index.row())
        text = str(value)
        if text != cue.text:
            self.text_edit_requested.emit(cue.id, text)
        return True


class CueBadgeDelegate(QStyledItemDelegate):
    """Paint low-noise speaker and status badges without adding cell widgets."""

    def paint(self, painter, option, index) -> None:
        if index.column() not in {2, 4}:
            super().paint(painter, option, index)
            return
        prepared = QStyleOptionViewItem(option)
        self.initStyleOption(prepared, index)
        text = prepared.text
        prepared.text = ""
        style = prepared.widget.style() if prepared.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, prepared, painter, prepared.widget)

        if index.column() == 2:
            cue = index.model().cue_at(index.row())
            color = _speaker_color(index.model().project, cue.speaker_id)
            # 主题色描边药丸：彩色细边框 + 极淡彩底 + accent 协调对比色文字
            # （不用纯黑——亮 accent 配深化色、暗 accent 配提亮色，颜色更凸显）。
            fill = QColor(color)
            fill.setAlpha(46)
            luminance = (
                color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
            ) / 255.0
            foreground = color.darker(168) if luminance > 0.5 else color.lighter(178)
            border = QColor(color)
            border.setAlpha(225)
            width = min(option.rect.width() - 8, max(52, QFontMetrics(option.font).horizontalAdvance(text) + 22))
        else:
            cue = index.model().cue_at(index.row())
            status_colors = studio_status_colors()
            if index.model().filter_status in {"priority", "critical"}:
                high = _cue_review_level(index.model().project, cue) == "high"
                fill_color, text_color = status_colors["issue" if high else "pending"]
                fill, foreground = QColor(fill_color), QColor(text_color)
            else:
                status = _cue_status(index.model().project, cue)
                fill_color, text_color = status_colors[status]
                fill, foreground = QColor(fill_color), QColor(text_color)
            width = min(option.rect.width() - 8, 58)
        badge = QRectF(
            option.rect.left() + (option.rect.width() - width) / 2,
            option.rect.top() + (option.rect.height() - 24) / 2,
            width,
            24,
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        badge_pen = (
            QPen(border, 1.4)
            if index.column() == 2
            else Qt.PenStyle.NoPen
        )
        painter.setPen(badge_pen)
        painter.setBrush(fill)
        painter.drawRoundedRect(badge, 5, 5)
        painter.setPen(foreground)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class CueIndexDelegate(QStyledItemDelegate):
    """Keep cue numbers quiet while making the active row unmistakable."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if index.data(CueTableModel.ActiveCueRole):
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(timeline_palette().playhead))
            painter.drawEllipse(QRectF(option.rect.right()-9, option.rect.center().y()-3, 6, 6))
            painter.restore()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            painter.fillRect(option.rect.left(), option.rect.top(), 3, option.rect.height(), QColor(GREEN))
            painter.restore()
