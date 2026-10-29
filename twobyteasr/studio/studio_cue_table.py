"""Cue list table: speaker/cue row helpers, table model, and delegates."""

from __future__ import annotations

from ..i18n import tr
from ..diagnostics.playback_probe import measured

from collections.abc import Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QTextLayout
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QStyledItemDelegate

from .studio_helpers import _format_ms
from ..projects.studio_project import StudioCue, SubtitleProject
from ..subtitle_rules.studio_qc import QCSeverity
from ..subtitle_rules.studio_review import cached_qc_result, cached_review_risks
from ..design.studio_theme import studio_status_colors
from ..design.timeline_theme import TimelinePalette, timeline_palette
from ..design.ui_theme import GREEN

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
                from ..projects.speaker_names import display_speaker_name
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
    from ..timeline.studio_edit_sequence import source_cue_id_of

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


def _cue_review_level(project: SubtitleProject | None, cue: StudioCue, risks: dict | None = None) -> str:
    # Loops over every cue pass ``risks`` once: building it copies the whole
    # risk table, so a per-cue call made a full-list pass O(n^2).
    risks = cached_review_risks(project) if risks is None else risks
    row = risks.get(_source_key(cue), {}) if isinstance(risks, dict) else {}
    return str(row.get("level", "confident")) if isinstance(row, dict) else "confident"


def _cue_review_score(project: SubtitleProject | None, cue: StudioCue, risks: dict | None = None) -> int:
    risks = cached_review_risks(project) if risks is None else risks
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
        from ..timeline.studio_edit_sequence import projected_cues

        view = projected_cues(self.project, domain="timeline")
        self._view_cues = view
        needle = self.query.casefold().strip()
        scope = set(self.scope_ids) if self.scope_ids is not None else None
        risks = cached_review_risks(self.project) if self.filter_status == "priority" else None
        for row, cue in enumerate(view):
            if scope is not None:
                if cue.id not in scope:
                    continue
                self._rows.append(row)
                continue
            status = _cue_status(self.project, cue)
            speaker = _speaker_name(self.project, cue.speaker_id)
            if self.filter_status == "priority":
                if _cue_explicitly_confirmed(self.project, cue) or _cue_review_level(self.project, cue, risks) == "confident":
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
                # Only the playback marker (number cell, or the reading cell
                # in the two-line view); no row selection, scrolling,
                # reset, status/QC calculation or editor signal.
                self.dataChanged.emit(self.index(row, 0), self.index(row, 3), [self.ActiveCueRole])

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

    def refresh_cues(self, cue_ids, columns: tuple[int, ...] | None = None, *, recheck_filter=True) -> None:
        """One model notification per contiguous row span, one filter rebuild."""
        if recheck_filter and self.scope_ids is None and (self.filter_status != 'all' or self.query.strip()):
            self.refresh()
            return
        rows = sorted({row for cue_id in cue_ids if (row := self.row_for_cue_id(cue_id)) >= 0})
        cols = [c for c in (columns if columns is not None else range(self.columnCount()))
                if 0 <= c < self.columnCount()]
        if not rows or not cols:
            return
        first = previous = rows[0]
        for row in [*rows[1:], -1]:
            if row == previous+1:
                previous = row
                continue
            self.dataChanged.emit(self.index(first,min(cols)),self.index(previous,max(cols)))
            first = previous = row

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
            # 2026-10-07: text must contrast with the row, not with the
            # speaker colour — dark themes get the (lifted) speaker colour on
            # a visible wash, light themes a deepened one.
            dark = timeline_palette().dark
            fill = QColor(color)
            fill.setAlpha(62 if dark else 46)
            luminance = (
                color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
            ) / 255.0
            if dark:
                foreground = QColor(color) if luminance >= 0.55 else color.lighter(150)
            else:
                foreground = color.darker(160)
            border = QColor(color)
            border.setAlpha(200 if dark else 225)
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


class CueReadingDelegate(QStyledItemDelegate):
    """Two-line subtitle row (2026-10-09, M16, user: the list reads the
    sentence first). Line one: start time, speaker, status; below it the
    sentence itself, wrapped over up to ``LINES`` lines. Painted in the text
    column; the model, selection and editing are the table's own."""

    LINES = 2
    PAD_X = 12
    PAD_Y = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout_cache: dict[tuple, list[str]] = {}

    @staticmethod
    def meta_font(base: QFont) -> QFont:
        font = QFont(base)
        font.setPixelSize(12)
        return font

    @staticmethod
    def text_font(base: QFont) -> QFont:
        font = QFont(base)
        font.setPixelSize(15)
        return font

    @classmethod
    def row_height(cls, base: QFont) -> int:
        meta = QFontMetrics(cls.meta_font(base)).height()
        text = QFontMetrics(cls.text_font(base)).lineSpacing()
        return cls.PAD_Y * 2 + max(22, meta + 6) + 4 + cls.LINES * text

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self.row_height(option.font))

    def _text_rect(self, option) -> QRect:
        meta = max(22, QFontMetrics(self.meta_font(option.font)).height() + 6)
        rect = option.rect.adjusted(self.PAD_X, self.PAD_Y + meta + 4, -self.PAD_X, -self.PAD_Y)
        return rect

    def updateEditorGeometry(self, editor, option, index) -> None:
        # Edit over the sentence lines, not over the whole two-line cell.
        editor.setGeometry(self._text_rect(option))

    def _wrapped(self, text: str, font: QFont, width: int) -> list[str]:
        key = (text, font.key(), width)
        lines = self._layout_cache.get(key)
        if lines is not None:
            return lines
        metrics = QFontMetrics(font)
        layout = QTextLayout(text, font)
        layout.beginLayout()
        lines = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            lines.append(text[line.textStart():line.textStart() + line.textLength()])
        layout.endLayout()
        if len(lines) > self.LINES:
            rest = "".join(lines[self.LINES - 1:])
            lines = lines[:self.LINES - 1] + [metrics.elidedText(rest, Qt.TextElideMode.ElideRight, width)]
        if len(self._layout_cache) > 4000:
            self._layout_cache.clear()
        self._layout_cache[key] = lines
        return lines

    def paint(self, painter, option, index) -> None:
        model = index.model()
        prepared = QStyleOptionViewItem(option)
        self.initStyleOption(prepared, index)
        prepared.text = ""
        style = prepared.widget.style() if prepared.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, prepared, painter, prepared.widget)
        cue = model.cue_at(index.row())
        project = model.project
        palette = timeline_palette()
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(rect.left(), rect.top(), 3, rect.height(), QColor(GREEN))
        meta_font = self.meta_font(option.font)
        meta_metrics = QFontMetrics(meta_font)
        top = rect.top() + self.PAD_Y
        line_h = max(22, meta_metrics.height() + 6)
        x = rect.left() + self.PAD_X
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        theme = theme_definition(theme_key())
        text_color = QColor(theme.text)
        muted = QColor(theme.text_muted)
        # start time
        painter.setFont(meta_font)
        painter.setPen(muted)
        stamp = _format_ms(cue.start_ms)
        painter.drawText(QRectF(x, top, meta_metrics.horizontalAdvance(stamp) + 2, line_h),
                         int(Qt.AlignmentFlag.AlignVCenter), stamp)
        x += meta_metrics.horizontalAdvance(stamp) + 10
        # speaker chip (display name of the stable identity)
        name = _speaker_name(project, cue.speaker_id)
        color = _speaker_color(project, cue.speaker_id)
        dark = palette.dark
        chip_w = meta_metrics.horizontalAdvance(name) + 16
        chip = QRectF(x, top + 2, chip_w, line_h - 4)
        fill = QColor(color)
        fill.setAlpha(62 if dark else 46)
        border = QColor(color)
        border.setAlpha(200 if dark else 225)
        luminance = (color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114) / 255.0
        foreground = (QColor(color) if luminance >= 0.55 else color.lighter(150)) if dark else color.darker(160)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(fill)
        painter.drawRoundedRect(chip, 5, 5)
        painter.setPen(foreground)
        painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), name)
        x += chip_w + 8
        # status (or review level in the priority filters)
        status_colors = studio_status_colors()
        if model.filter_status in {"priority", "critical"}:
            high = _cue_review_level(project, cue) == "high"
            fill_color, status_color = status_colors["issue" if high else "pending"]
            label = tr({"high": "需要检查", "suggested": "建议确认"}.get(_cue_review_level(project, cue), "待确认"))
        else:
            status = _cue_status(project, cue)
            fill_color, status_color = status_colors[status]
            label = tr({"pending": "待确认", "issue": "有问题", "done": "已完成"}[status])
        status_w = meta_metrics.horizontalAdvance(label) + 14
        badge = QRectF(x, top + 2, status_w, line_h - 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fill_color))
        painter.drawRoundedRect(badge, 5, 5)
        painter.setPen(QColor(status_color))
        painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), label)
        # cue number and playback marker on the right of line one
        number = str(model.source_row(index.row()) + 1)
        right = rect.right() - self.PAD_X
        painter.setPen(muted)
        number_w = meta_metrics.horizontalAdvance(number) + 2
        painter.drawText(QRectF(right - number_w, top, number_w, line_h),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), number)
        if index.data(CueTableModel.ActiveCueRole):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette.playhead))
            painter.drawEllipse(QRectF(right - number_w - 12, top + line_h / 2 - 3, 6, 6))
        # the sentence, wrapped; elided only past the visible lines
        text_font = self.text_font(option.font)
        text_rect = self._text_rect(option)
        painter.setFont(text_font)
        painter.setPen(text_color)
        spacing = QFontMetrics(text_font).lineSpacing()
        for number_line, line in enumerate(self._wrapped(" ".join(str(cue.text).split()), text_font,
                                                         max(40, text_rect.width()))):
            painter.drawText(QRectF(text_rect.left(), text_rect.top() + number_line * spacing, text_rect.width(), spacing),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), line)
        painter.restore()
