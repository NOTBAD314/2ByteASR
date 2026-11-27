"""Cue list table: speaker/cue row helpers, table model, and delegates."""

from __future__ import annotations

from ..i18n import tr
from ..diagnostics.playback_probe import measured

from collections.abc import Iterable, Mapping

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QTextLayout, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QStyledItemDelegate, QToolTip

from .studio_helpers import _format_ms
from ..projects.studio_project import StudioCue, SubtitleProject
from ..subtitle_rules.studio_qc import QCSeverity
from ..subtitle_rules.studio_review import cached_qc_result, cached_review_risks
from ..subtitle_rules.current_issues import DECISIONS, reviewed_version
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
                return _lazy('display_speaker_name')(project, speaker)
    return speaker_id


# Per-row helpers run for every painted cell. An import statement in them ran
# PySide's import hook each time (1200 hook calls per list repaint); the
# functions are bound once instead (the modules import this one, so lazily).
_LAZY: dict[str, object] = {}


_LAZY_HOMES = {
    'display_speaker_name': '..projects.speaker_names',
    'theme_key': '..design.theme_manager',
    'theme_definition': '..design.ui_theme',
    'source_cue_id_of': '..timeline.studio_edit_sequence',
}


def _lazy(name: str):
    # The module is bound once; the function is looked up on it each call, so
    # a replaced attribute (a theme preview, a test) is still honoured.
    module = _LAZY.get(name)
    if module is None:
        import importlib
        module = _LAZY[name] = importlib.import_module(_LAZY_HOMES[name], __package__)
    return getattr(module, name)


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


def _paint_theme():
    """(theme, timeline palette, status colors) of the active theme: one
    settings read per painted row instead of five."""
    key = _lazy('theme_key')()
    return _lazy('theme_definition')(key), timeline_palette(key), studio_status_colors()


def _source_key(cue: StudioCue) -> str:
    """工程状态映射（状态/审核/QC）按源 cue id 键控；派生 id 解析回源。"""
    return _lazy('source_cue_id_of')(str(cue.id))


def _review_key(project, cue):
    # Independent captions can retain a legacy-looking ID as their actual
    # persistent identity. Only a legacy display projection uses the fallback.
    if project and project.render_settings.get('_cue_domain') == 'timeline':
        return str(cue.id)
    return _source_key(cue)


def _cue_status(project: SubtitleProject | None, cue: StudioCue, risks: dict | None = None) -> str:
    if project and _cue_review_level(project, cue, risks) != 'confident':
        return 'issue'
    if project:
        reviewed = project.studio_state.get(DECISIONS, {}).get('reviewed:'+cue.id, {})
        if reviewed and reviewed.get('input_version') == reviewed_version(project, cue):
            return 'done'
    statuses = project.studio_state.get("cue_statuses", {}) if project else {}
    if isinstance(statuses, dict):
        value = str(statuses.get(_review_key(project, cue), "") or "").strip().lower()
        if value in {"pending", "done"}:
            return value
    if not cue.text.strip() or cue.end_ms <= cue.start_ms:
        return "issue"
    return "done" if cue.text != cue.original_text else "pending"


def _cue_review_level(project: SubtitleProject | None, cue: StudioCue, risks: dict | None = None) -> str:
    # Loops over every cue pass ``risks`` once: building it copies the whole
    # risk table, so a per-cue call made a full-list pass O(n^2).
    risks = cached_review_risks(project, refresh=False) if risks is None else risks
    row = risks.get(_review_key(project, cue), {}) if isinstance(risks, dict) else {}
    return str(row.get("level", "confident")) if isinstance(row, dict) else "confident"


def _cue_review_score(project: SubtitleProject | None, cue: StudioCue, risks: dict | None = None) -> int:
    risks = cached_review_risks(project, refresh=False) if risks is None else risks
    row = risks.get(_review_key(project, cue), {}) if isinstance(risks, dict) else {}
    try:
        return int(row.get("score", 0)) if isinstance(row, dict) else 0
    except (TypeError, ValueError):
        return 0


def _cue_explicitly_confirmed(project: SubtitleProject | None, cue: StudioCue) -> bool:
    statuses = project.studio_state.get("cue_statuses", {}) if project else {}
    return isinstance(statuses, dict) and str(statuses.get(_review_key(project, cue), "")).lower() == "done"


def _cue_status_label(project, cue):
    level = _cue_review_level(project, cue)
    if level != 'confident':
        return tr('需要检查' if level == 'high' else '建议确认')
    return tr({'pending': '未审核', 'issue': '有问题', 'done': '已处理'}[_cue_status(project, cue)])


def project_has_translations(project: SubtitleProject | None) -> bool:
    """True when the project carries at least one non-empty translation."""
    if project is None:
        return False
    meta = getattr(project, 'generation_metadata', None)
    if not isinstance(meta, Mapping):
        return False
    translations = meta.get('translations')
    if isinstance(translations, Mapping) and any(str(value or '').strip() for value in translations.values()):
        return True
    container = meta.get('translation_records')
    records = container.get('records') if isinstance(container, Mapping) else None
    if isinstance(records, Mapping):
        for record in records.values():
            if isinstance(record, Mapping) and str(record.get('text') or '').strip():
                return True
    return False


def cue_translation_text(project: SubtitleProject | None, cue: StudioCue) -> str:
    """Raw translation text for ``cue`` (render map first, record fallback)."""
    if project is None:
        return ''
    meta = getattr(project, 'generation_metadata', None)
    if not isinstance(meta, Mapping):
        return ''
    key = _source_key(cue)
    translations = meta.get('translations')
    if isinstance(translations, Mapping):
        for candidate in (key, str(cue.id)):
            value = str(translations.get(candidate, '') or '')
            if value:
                return value
    container = meta.get('translation_records')
    records = container.get('records') if isinstance(container, Mapping) else None
    if isinstance(records, Mapping):
        for candidate in (key, str(cue.id)):
            record = records.get(candidate)
            if isinstance(record, Mapping):
                value = str(record.get('text') or '')
                if value:
                    return value
    return ''


def cue_translation_needs_update(project: SubtitleProject | None, cue: StudioCue) -> bool:
    """O(1) dirty check: True when the source cue changed after translation."""
    if project is None:
        return False
    from ..subtitle_rules.subtitle_translation import NEEDS_UPDATE, normalize_source, records_of, status_of
    records = records_of(project)
    key = _source_key(cue)
    record = records.get(key)
    if record is None and str(cue.id) != key:
        record = records.get(str(cue.id))
    if isinstance(record, Mapping):
        if str(record.get('status') or '') == NEEDS_UPDATE:
            return True
        if status_of(record, cue.text) == NEEDS_UPDATE:
            return True
        if str(record.get('text') or '').strip() and record.get('source_text') is not None:
            if normalize_source(record.get('source_text')) != normalize_source(cue.text):
                return True
        return False
    # Legacy project with render-only `translations` dict (not yet migrated):
    # fall back to comparing against the cue's initial original_text.
    if cue_translation_text(project, cue).strip():
        initial = str(getattr(cue, 'original_text', '') or '')
        if initial.strip() and normalize_source(initial) != normalize_source(cue.text):
            return True
    return False


def _rough_cut_reason(project: SubtitleProject | None, cue: StudioCue) -> str:
    """Minimal read-only rough-cut contract (Task 4): <=4-char tag iff marked to cut."""
    if project is None:
        return ""
    marks = project.studio_state.get("rough_cut_marks")
    if not isinstance(marks, dict) or not marks:
        return ""
    entry = marks.get(str(cue.id))
    if not isinstance(entry, dict):
        entry = marks.get(_source_key(cue))
    if not isinstance(entry, dict) or entry.get("keep") is not False:
        return ""
    text = " ".join(str(entry.get("reason") or "待剪除").split()).strip()
    return (text[:4] or "待剪除")


class CueTableModel(QAbstractTableModel):
    text_edit_requested = Signal(str, str)
    translation_edit_requested = Signal(str, str)
    text_layer_changed = Signal(str)
    ActiveCueRole = int(Qt.ItemDataRole.UserRole) + 1
    OriginalTextRole = int(Qt.ItemDataRole.UserRole) + 2
    TranslationTextRole = int(Qt.ItemDataRole.UserRole) + 3
    NeedsRetranslateRole = int(Qt.ItemDataRole.UserRole) + 4
    HEADERS = ("#", "开始时间", "说话人", "文本", "状态")
    TEXT_LAYERS = ("bilingual", "original", "translation")

    def __init__(self, project: SubtitleProject | None = None, parent=None):
        super().__init__(parent)
        self.project = project
        self._explicit_layer = False
        self.text_layer = self._default_text_layer(project)
        self.filter_status = "all"
        self.query = ""
        self._rows: list[int] = []
        self._cue_row_lookup: dict[str, int] = {}
        self.scope_ids: tuple[str, ...] | None = None
        self.review_anchor_id = ''
        self.active_cue_ids: frozenset[str] = frozenset()
        self.retranslating_cue_ids: frozenset[str] = frozenset()
        self._rebuild_rows()

    @property
    def bilingual_cards(self) -> bool:
        return self.text_layer == 'bilingual'

    @classmethod
    def _default_text_layer(cls, project: SubtitleProject | None) -> str:
        if not project_has_translations(project):
            return 'original'
        state = getattr(project, 'studio_state', None)
        if isinstance(state, Mapping):
            saved = str(state.get('cue_list_text_layer') or '').strip()
            if saved in cls.TEXT_LAYERS:
                return saved
        return 'bilingual'

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
        self._view_cues = list(view)
        needle = self.query.casefold().strip()
        scope = set(self.scope_ids) if self.scope_ids is not None else None
        risks = cached_review_risks(self.project, refresh=False) if self.filter_status != 'all' else None
        for row, cue in enumerate(view):
            if scope is not None:
                if cue.id not in scope:
                    continue
            if cue.id == self.review_anchor_id:
                self._rows.append(row)
                continue
            if self.filter_status == "priority":
                if _cue_review_level(self.project, cue, risks) != "suggested":
                    continue
            elif self.filter_status == "critical":
                if _cue_review_level(self.project, cue, risks) != "high":
                    continue
            elif self.filter_status != "all" and _cue_status(self.project, cue, risks) != self.filter_status:
                # Only status filters need the status (2026-11-19: every cue's
                # status on each open of the full list was 0.5 s on a busy PC).
                continue
            if not self.matches_query(cue, needle):
                continue
            self._rows.append(row)
        # Filters change visibility only. Every visible list, including
        # Priority, follows the same chronological order as the timeline.
        # Rows were appended in source order; the stable sort retains that
        # order for equal start times.
        self._rows.sort(key=lambda source_row: self._view_cues[source_row].start_ms)
        self._cue_row_lookup = {
            self._view_cues[source_row].id: row
            for row, source_row in enumerate(self._rows)
        }

    def set_filter(self, status: str) -> None:
        self.beginResetModel()
        self.filter_status = status if status in {"all", "priority", "critical", "pending", "issue", "done"} else "all"
        self._rebuild_rows()
        self.endResetModel()

    def editing_translation(self, cue):
        if self.text_layer not in {'translation', 'bilingual'} or self.project is None:
            return False
        key = _source_key(cue)
        meta = self.project.generation_metadata
        if key in (meta.get('translations') or {}):
            return True
        container = meta.get('translation_records')
        if isinstance(container, Mapping) and key in (container.get('records') or {}):
            return True
        # Imported tracks own cue.text. Generated translation lanes own records,
        # including currently empty records that can be edited manually.
        return cue.speaker_id not in meta.get('subtitle_imports', {}).get('tracks', {})

    def original_text(self, cue, *, styled=True) -> str:
        text = str(cue.text or '')
        if not styled or self.project is None:
            return text
        from ..subtitle_rules.punctuation_style import style_text, project_mode, math_enabled, protected_terms_of
        from ..subtitle_rules.language_rules import project_language
        options = dict(math=math_enabled(self.project), protected_terms=protected_terms_of(self.project))
        return style_text(text, project_mode(self.project), language=project_language(self.project) or '', **options).text

    def translation_text(self, cue, *, styled=True) -> str:
        text = cue_translation_text(self.project, cue)
        if not styled or self.project is None or not text:
            return text
        from ..subtitle_rules.punctuation_style import style_translation, project_mode, math_enabled, protected_terms_of
        options = dict(math=math_enabled(self.project), protected_terms=protected_terms_of(self.project))
        return style_translation(text, project_mode(self.project), **options)

    def needs_retranslate(self, cue) -> bool:
        return cue_translation_needs_update(self.project, cue)

    def set_retranslating(self, cue_id: str, active: bool) -> None:
        key = str(cue_id or '')
        if not key:
            return
        updated = (self.retranslating_cue_ids | {key}) if active else (self.retranslating_cue_ids - {key})
        if updated == self.retranslating_cue_ids:
            return
        self.retranslating_cue_ids = updated
        self.refresh_cue(key, (3, 4))

    def matches_query(self, cue, needle=None):
        needle = self.query.casefold().strip() if needle is None else str(needle).casefold().strip()
        if not needle:
            return True
        speaker = f'{cue.speaker_id} {_speaker_name(self.project, cue.speaker_id)}'
        if self.text_layer == 'bilingual':
            raw_trans = cue_translation_text(self.project, cue)
            styled_trans = self.translation_text(cue, styled=True) if raw_trans else ''
            orig_styled = self.original_text(cue, styled=True)
            haystack = f'{styled_trans} {raw_trans} {orig_styled} {cue.text} {speaker}'
            return needle in haystack.casefold()
        return needle in f'{self.display_text(cue)} {speaker}'.casefold()

    def display_text(self, cue, *, styled=True):
        if self.text_layer == 'bilingual':
            if not styled:
                return self.translation_text(cue, styled=False) if self.editing_translation(cue) else self.original_text(cue, styled=False)
            translated = self.translation_text(cue, styled=True)
            return translated if translated.strip() else self.original_text(cue, styled=True)
        if self.editing_translation(cue):
            return self.translation_text(cue, styled=styled)
        return self.original_text(cue, styled=styled)

    def set_text_layer(self, layer, *, explicit: bool = False):
        layer = layer if layer in self.TEXT_LAYERS else 'original'
        if explicit:
            self._explicit_layer = True
        if self.text_layer == layer:
            return
        self.text_layer = layer
        if self.query:
            self.beginResetModel()
            self._rebuild_rows()
            self.endResetModel()
        elif self.rowCount():
            self.dataChanged.emit(self.index(0, 3), self.index(self.rowCount() - 1, 3),
                                  [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
        self.text_layer_changed.emit(self.text_layer)

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
        old_layer = self.text_layer
        self.beginResetModel()
        self.project = project
        self.review_anchor_id = ''
        self._explicit_layer = False
        self.text_layer = self._default_text_layer(project)
        self.active_cue_ids = frozenset()
        self.retranslating_cue_ids = frozenset()
        self._rebuild_rows()
        self.endResetModel()
        if self.text_layer != old_layer:
            self.text_layer_changed.emit(self.text_layer)

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
        old_layer = self.text_layer
        if not self._explicit_layer and self.text_layer == 'original' and project_has_translations(self.project):
            self.text_layer = self._default_text_layer(self.project)
        elif self.text_layer == 'bilingual' and not project_has_translations(self.project):
            self.text_layer = 'original'
        self.beginResetModel()
        self._rebuild_rows()
        self.endResetModel()
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 4))
        if self.text_layer != old_layer:
            self.text_layer_changed.emit(self.text_layer)

    def refresh_caption_splice(self, affected):
        """Keep unrelated rows and selection indexes during a small editor splice."""
        affected = set(affected)
        visible = [self.cue_at(row).id for row in range(self.rowCount())]
        for row in reversed(range(len(visible))):
            if visible[row] in affected:
                self.beginRemoveRows(QModelIndex(), row, row)
                self._rows.pop(row)
                visible.pop(row)
                self.endRemoveRows()
        self._view_cues = list(self.project.cues)
        source = {cue.id: row for row, cue in enumerate(self._view_cues)}
        self._rows = [source[key] for key in visible]
        scope = set(self.scope_ids) if self.scope_ids is not None else None
        needle = self.query.casefold().strip()
        risks = cached_review_risks(self.project, refresh=False) if self.filter_status != 'all' else None
        for cue in sorted((c for c in self._view_cues if c.id in affected), key=lambda c: (c.start_ms, source[c.id], c.id)):
            if scope is not None and cue.id not in scope:
                continue
            if cue.id != self.review_anchor_id:
                if self.filter_status in {'priority', 'critical'}:
                    level = 'suggested' if self.filter_status == 'priority' else 'high'
                    if _cue_review_level(self.project, cue, risks) != level:
                        continue
                elif self.filter_status != 'all' and _cue_status(self.project, cue, risks) != self.filter_status:
                    continue
                if not self.matches_query(cue, needle):
                    continue
            key = (cue.start_ms, source[cue.id], cue.id)
            row = next((i for i, old in enumerate(self._rows) if
                        (self._view_cues[old].start_ms, old, self._view_cues[old].id) > key), len(self._rows))
            self.beginInsertRows(QModelIndex(), row, row)
            self._rows.insert(row, source[cue.id])
            self.endInsertRows()
        self._cue_row_lookup = {self.cue_at(row).id: row for row in range(self.rowCount())}

    def refresh_cue(self, cue_id: str, columns: tuple[int, ...] | None = None) -> None:
        if (self.filter_status != "all" or self.query.strip()):
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
        if recheck_filter and (self.filter_status != 'all' or self.query.strip()):
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
        return 0 if _parent.isValid() else len(self._rows)

    def columnCount(self, _parent=QModelIndex()) -> int:
        return 0 if _parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal
                and 0 <= section < len(self.HEADERS)):
            return tr(self.HEADERS[section])
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if (not index.isValid() or not self.project or index.model() is not self
                or not 0 <= index.row() < len(self._rows)
                or not 0 <= index.column() < len(self.HEADERS)):
            return None
        cue = self.cue_at(index.row())
        if role == self.ActiveCueRole:
            return cue.id in self.active_cue_ids
        if role == self.OriginalTextRole:
            return self.original_text(cue)
        if role == self.TranslationTextRole:
            return self.translation_text(cue)
        if role == self.NeedsRetranslateRole:
            return self.needs_retranslate(cue)
        if role == Qt.ItemDataRole.UserRole:
            return cue.id
        if role == Qt.ItemDataRole.EditRole and index.column() == 3:
            return self.display_text(cue, styled=False)
        if role == Qt.ItemDataRole.DisplayRole:
            column = index.column()
            if column == 0:
                return self.source_row(index.row()) + 1
            if column == 1:
                return _format_ms(cue.start_ms)
            if column == 2:
                return _speaker_name(self.project, cue.speaker_id)
            if column == 3:
                return self.display_text(cue)
            if _cue_review_level(self.project, cue) != 'confident':
                return tr({"high": "需要检查", "suggested": "建议确认"}.get(
                    _cue_review_level(self.project, cue), "待确认"
                ))
            return _cue_status_label(self.project, cue)
        if role == Qt.ItemDataRole.ToolTipRole:
            risks = cached_review_risks(self.project, refresh=False)
            row = risks.get(cue.id, {}) if isinstance(risks, dict) else {}
            reasons = row.get("reasons", []) if isinstance(row, dict) else []
            if reasons:
                return "；".join(str(reason) for reason in reasons)
        if role == Qt.ItemDataRole.FontRole and index.column() == 3:
            if _rough_cut_reason(self.project, cue):
                font = QApplication.font()
                font.setStrikeOut(True)
                return font
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 3:
            if _rough_cut_reason(self.project, cue):
                return QColor(_lazy('theme_definition')(_lazy('theme_key')()).text_muted)
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 2:
            return _speaker_color(self.project, cue.speaker_id).darker(120)
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 4:
            status_colors = studio_status_colors()
            if self.filter_status in {"priority", "critical"}:
                key = "issue" if _cue_review_level(self.project, cue) == "high" else "pending"
                return QColor(status_colors[key][1])
            return QColor({"pending": status_colors["pending"][1],
                           "issue": status_colors["issue"][1],
                           "done": status_colors["done"][1]}[_cue_status(self.project, cue)])
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {0, 1, 4}:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    # Inherit the native read-only QAbstractTableModel flags. A Python virtual
    # trampoline doing only super().flags() adds an enum conversion for every
    # accessibility cell query. The 2026-11-03 native dump enters that exact
    # trampoline from UIAutomation/QPersistentModelIndex, then PyErr_PrintEx.
    # No ItemIsEditable is added: double click still owns the caption editor.

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
        if text != self.display_text(cue, styled=False):
            if self.editing_translation(cue):
                self.translation_edit_requested.emit(_source_key(cue), text)
            else:
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
            if _cue_review_level(index.model().project, cue) != "confident":
                high = _cue_review_level(index.model().project, cue) == "high"
                fill_color, text_color = status_colors["issue" if high else "pending"]
                fill, foreground = QColor(fill_color), QColor(text_color)
            else:
                status = _cue_status(index.model().project, cue)
                fill_color, text_color = status_colors[status]
                fill, foreground = QColor(fill_color), QColor(text_color)
                if status == 'pending':
                    fill, foreground = QColor(Qt.GlobalColor.transparent), option.palette.color(QPalette.ColorRole.PlaceholderText)
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
    sentence first). Line one: start time, speaker, status (and compact
    ``重翻此句`` button when original text diverged from translation); below
    it the sentence itself — or, in bilingual mode, translation (primary) over
    original (secondary). Painted in the text column; the model, selection and
    editing are the table's own."""

    LINES = 2
    BILINGUAL_GAP = 4
    BILINGUAL_BOTTOM_PAD = 4
    PAD_X = 12
    PAD_Y = 8
    # 2026-11-12 (user, design A): every row is its own rounded card with a
    # small gap to the next; the chosen row has an accent outline.
    CARD_INSET_X = 2
    CARD_INSET_Y = 3
    # 2026-11-09 (user, redesign): review reasons show in the row itself and
    # a ✓ on the right confirms the cue without entering review mode.
    review_confirm_requested = Signal(str)
    retranslate_requested = Signal(str)
    # Task 4: clicking the rough-cut reason pill restores/toggles the cue.
    rough_cut_toggle_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout_cache: dict[tuple, list[str]] = {}
        self._rough_cut_rects: dict[int, QRectF] = {}
        self._hidden_retranslate_rows: set[int] = set()

    def _meta_line_height(self, option) -> int:
        return max(22, QFontMetrics(self.meta_font(option.font)).height() + 6)

    @staticmethod
    def _show_retranslate_button(model, cue) -> bool:
        if model is None or model.project is None:
            return False
        if cue.id in getattr(model, 'retranslating_cue_ids', ()):
            return True
        needs = getattr(model, 'needs_retranslate', None)
        return bool(needs(cue)) if callable(needs) else cue_translation_needs_update(model.project, cue)

    @staticmethod
    def _retranslate_label(model, cue) -> str:
        if cue.id in getattr(model, 'retranslating_cue_ids', ()):
            return tr('重翻中…')
        return tr('重翻此句')

    def _confirm_rect(self, option, model, row) -> QRectF:
        """The ✓ left of the cue number on line one (risky cues only)."""
        meta_metrics = QFontMetrics(self.meta_font(option.font))
        line_h = self._meta_line_height(option)
        number_w = meta_metrics.horizontalAdvance(str(model.source_row(row) + 1)) + 2
        size = line_h - 4
        right = option.rect.right() - self.PAD_X - number_w - 16
        return QRectF(right - size, option.rect.top() + self.PAD_Y + 2, size, size)

    def _retranslate_rect(self, option, model, row, *, level: str | None = None) -> QRectF:
        """Compact ``重翻此句`` pill on the right of line one (dirty translated cues)."""
        meta_metrics = QFontMetrics(self.meta_font(option.font))
        action_metrics = QFontMetrics(self.action_font(option.font))
        line_h = self._meta_line_height(option)
        cue = model.cue_at(row)
        number_w = meta_metrics.horizontalAdvance(str(model.source_row(row) + 1)) + 2
        right = option.rect.right() - self.PAD_X - number_w - 16
        cue_level = _cue_review_level(model.project, cue) if level is None else level
        if cue_level != "confident":
            right -= (line_h - 4) + 6
        label = self._retranslate_label(model, cue)
        btn_w = action_metrics.horizontalAdvance(label) + 14
        btn_h = max(19, line_h - 2)
        return QRectF(right - btn_w, option.rect.top() + self.PAD_Y + (line_h - btn_h) / 2.0, btn_w, btn_h)

    def _retranslate_visible_for_row(self, model, cue, row: int) -> bool:
        return self._show_retranslate_button(model, cue) and row not in self._hidden_retranslate_rows

    def hit_action_button(self, option, model, row: int, pos: QPointF) -> str:
        """Return 'retranslate' / 'rough_cut' / 'confirm' if ``pos`` lands on an inline row action."""
        if model is None or model.project is None or not (0 <= row < model.rowCount()):
            return ''
        cue = model.cue_at(row)
        if self._retranslate_visible_for_row(model, cue, row) and self._retranslate_rect(option, model, row).contains(pos):
            return 'retranslate'
        cut_rect = self._rough_cut_rects.get(row)
        if cut_rect is not None and _rough_cut_reason(model.project, cue) and cut_rect.contains(pos):
            return 'rough_cut'
        if _cue_review_level(model.project, cue) != "confident" and self._confirm_rect(option, model, row).contains(pos):
            return 'confirm'
        return ''

    @staticmethod
    def _review_reason(project, cue) -> str:
        risks = cached_review_risks(project, refresh=False)
        row = risks.get(_review_key(project, cue), {}) if isinstance(risks, dict) else {}
        reasons = row.get("reasons", []) if isinstance(row, dict) else []
        return str(reasons[0]) if reasons else ""

    def editorEvent(self, event, model, option, index) -> bool:
        if (event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick)
                and event.button() == Qt.MouseButton.LeftButton
                and model.project is not None and 0 <= index.row() < model.rowCount()):
            cue = model.cue_at(index.row())
            pos = event.position()
            if self._retranslate_visible_for_row(model, cue, index.row()) and self._retranslate_rect(option, model, index.row()).contains(pos):
                if (event.type() == QEvent.Type.MouseButtonRelease
                        and cue.id not in getattr(model, 'retranslating_cue_ids', ())):
                    self.retranslate_requested.emit(cue.id)
                return True
            cut_rect = self._rough_cut_rects.get(index.row())
            if (cut_rect is not None and _rough_cut_reason(model.project, cue)
                    and cut_rect.contains(pos)):
                if event.type() == QEvent.Type.MouseButtonRelease:
                    self.rough_cut_toggle_requested.emit(cue.id)
                return True
            if (_cue_review_level(model.project, cue) != "confident"
                    and self._confirm_rect(option, model, index.row()).contains(pos)):
                if event.type() == QEvent.Type.MouseButtonRelease:
                    self.review_confirm_requested.emit(cue.id)
                return True
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index) -> bool:
        if (event is not None and event.type() == QEvent.Type.ToolTip and index.isValid()):
            model = index.model()
            if model is not None and getattr(model, 'project', None) is not None and 0 <= index.row() < model.rowCount():
                cue = model.cue_at(index.row())
                pos = QPointF(event.pos())
                if (self._retranslate_visible_for_row(model, cue, index.row())
                        and self._retranslate_rect(option, model, index.row()).contains(pos)):
                    QToolTip.showText(
                        event.globalPos(),
                        tr('只重翻这一句译文，不影响其他字幕，可 Ctrl+Z 撤销'),
                        view,
                    )
                    return True
                cut_rect = self._rough_cut_rects.get(index.row())
                if cut_rect is not None and _rough_cut_reason(model.project, cue) and cut_rect.contains(pos):
                    QToolTip.showText(
                        event.globalPos(),
                        tr('点击恢复保留这一句，取消待剪标记'),
                        view,
                    )
                    return True
        return super().helpEvent(event, view, option, index)

    @staticmethod
    def meta_font(base: QFont) -> QFont:
        font = QFont(base)
        font.setPixelSize(12)
        return font

    @staticmethod
    def action_font(base: QFont) -> QFont:
        font = QFont(base)
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    @staticmethod
    def text_font(base: QFont) -> QFont:
        font = QFont(base)
        font.setPixelSize(15)
        return font

    @staticmethod
    def primary_font(base: QFont) -> QFont:
        font = QFont(base)
        font.setStyleName("")
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    @staticmethod
    def secondary_font(base: QFont) -> QFont:
        font = QFont(base)
        font.setStyleName("")
        font.setBold(False)
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Normal)
        return font

    @classmethod
    def row_height(cls, base: QFont, *, bilingual: bool = False) -> int:
        meta = QFontMetrics(cls.meta_font(base)).height()
        meta_h = max(22, meta + 6)
        if not bilingual:
            text = QFontMetrics(cls.text_font(base)).lineSpacing()
            return cls.PAD_Y * 2 + meta_h + 4 + cls.LINES * text
        primary_ls = QFontMetrics(cls.primary_font(base)).lineSpacing()
        secondary_ls = QFontMetrics(cls.secondary_font(base)).lineSpacing()
        return (cls.PAD_Y * 2 + meta_h + 4
                + 2 * primary_ls + cls.BILINGUAL_GAP + secondary_ls
                + cls.BILINGUAL_BOTTOM_PAD)

    def sizeHint(self, option, index) -> QSize:
        model = index.model() if index.isValid() else None
        bilingual = bool(getattr(model, 'bilingual_cards', False))
        return QSize(option.rect.width(), self.row_height(option.font, bilingual=bilingual))

    def _text_rect(self, option) -> QRect:
        meta = max(22, QFontMetrics(self.meta_font(option.font)).height() + 6)
        rect = option.rect.adjusted(self.PAD_X, self.PAD_Y + meta + 4, -self.PAD_X, -self.PAD_Y)
        return rect

    def _bilingual_layout(self, option, model, cue) -> dict[str, object]:
        text_rect = self._text_rect(option)
        width = max(40, text_rect.width())
        p_font = self.primary_font(option.font)
        s_font = self.secondary_font(option.font)
        p_spacing = QFontMetrics(p_font).lineSpacing()
        s_spacing = QFontMetrics(s_font).lineSpacing()
        trans_raw = " ".join(str(model.translation_text(cue)).split())
        orig_raw = " ".join(str(model.original_text(cue)).split())
        has_translation = bool(trans_raw)
        primary_text = trans_raw if has_translation else orig_raw
        secondary_text = orig_raw if has_translation else tr('未翻译')
        primary_lines = self._wrapped(primary_text, p_font, width, max_lines=2) if primary_text else ['']
        secondary_max = 2 if len(primary_lines) <= 1 else 1
        secondary_lines = self._wrapped(secondary_text, s_font, width, max_lines=secondary_max) if secondary_text else []
        primary_top = text_rect.top()
        primary_height = max(1, len(primary_lines)) * p_spacing
        secondary_top = primary_top + primary_height + self.BILINGUAL_GAP
        return {
            'rect': text_rect,
            'width': width,
            'has_translation': has_translation,
            'primary_font': p_font,
            'secondary_font': s_font,
            'primary_spacing': p_spacing,
            'secondary_spacing': s_spacing,
            'primary_lines': primary_lines,
            'secondary_lines': secondary_lines,
            'primary_top': primary_top,
            'secondary_top': secondary_top,
        }

    def hit_edit_layer(self, option, index, pos: QPointF) -> str:
        """Resolve which text layer a double-click at ``pos`` targets."""
        if not index.isValid():
            return 'original'
        model = index.model()
        if model is None or getattr(model, 'project', None) is None:
            return 'original'
        layer = getattr(model, 'text_layer', 'original')
        if layer == 'original':
            return 'original'
        cue = model.cue_at(index.row())
        if layer == 'translation':
            return 'translation' if model.editing_translation(cue) else 'original'
        layout = self._bilingual_layout(option, model, cue)
        if pos.y() >= float(layout['secondary_top']) - 2.0:
            return 'original'
        return 'translation' if model.editing_translation(cue) else 'original'

    def updateEditorGeometry(self, editor, option, index) -> None:
        # Edit over the sentence lines, not over the whole two-line cell.
        editor.setGeometry(self._text_rect(option))

    def _wrapped(self, text: str, font: QFont, width: int, max_lines: int | None = None) -> list[str]:
        limit = self.LINES if max_lines is None else max(1, int(max_lines))
        key = (text, font.key(), width, limit)
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
        if len(lines) > limit:
            rest = "".join(lines[limit - 1:])
            lines = lines[:limit - 1] + [metrics.elidedText(rest, Qt.TextElideMode.ElideRight, width)]
        if len(self._layout_cache) > 4000:
            self._layout_cache.clear()
        self._layout_cache[key] = lines
        return lines

    def card_rect(self, option) -> QRectF:
        return QRectF(option.rect).adjusted(self.CARD_INSET_X + 0.5, self.CARD_INSET_Y + 0.5,
                                            -self.CARD_INSET_X - 0.5, -self.CARD_INSET_Y - 0.5)

    def card_colors(self, option, theme) -> tuple[str, str, float]:
        """(fill, outline, outline width) for the row's card."""
        from ..design.ui_theme import blend_hex
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        card = theme.surface_elevated
        if selected:
            return blend_hex(card, theme.accent, 0.10), theme.accent, 1.6
        if hover:
            return blend_hex(card, theme.text, 0.03), blend_hex(card, theme.text, 0.22), 1.0
        return card, blend_hex(card, theme.text, 0.12), 1.0

    def paint(self, painter, option, index) -> None:
        from ..design.ui_theme import blend_hex
        model = index.model()
        cue = model.cue_at(index.row())
        project = model.project
        # One theme lookup per row (2026-11-19: five settings reads per row
        # were half of every list repaint while a project opened).
        theme, palette, status_colors = _paint_theme()
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fill, outline, outline_width = self.card_colors(option, theme)
        cut_reason = _rough_cut_reason(project, cue)
        if cut_reason:
            fill = blend_hex(fill, theme.app_background, 0.42)
        painter.setPen(QPen(QColor(outline), outline_width))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(self.card_rect(option), 10, 10)
        meta_font = self.meta_font(option.font)
        meta_metrics = QFontMetrics(meta_font)
        top = rect.top() + self.PAD_Y
        line_h = max(22, meta_metrics.height() + 6)
        x = rect.left() + self.PAD_X
        text_color = QColor(theme.text)
        muted = QColor(theme.text_muted)

        risks = cached_review_risks(project, refresh=False)
        level = _cue_review_level(project, cue, risks)
        show_retranslate = self._show_retranslate_button(model, cue)

        # Compute right-side anchors first so left meta chips never overlap them.
        number = str(model.source_row(index.row()) + 1)
        right = rect.right() - self.PAD_X
        number_w = meta_metrics.horizontalAdvance(number) + 2
        right_bound = float(right - number_w - 16)
        confirm = None
        if level != "confident":
            confirm = self._confirm_rect(option, model, index.row())
            right_bound = min(right_bound, confirm.left() - 6.0)

        # start time width (needed early to decide narrow-width pill priority)
        stamp = _format_ms(cue.start_ms)
        stamp_w = meta_metrics.horizontalAdvance(stamp) + 2
        cut_tag_w = (meta_metrics.horizontalAdvance(cut_reason) + 12) if cut_reason else 0

        retranslate_rect = None
        if show_retranslate:
            candidate_rect = self._retranslate_rect(option, model, index.row(), level=level)
            # On a narrow row that is ALREADY marked for rough-cut deletion,
            # keep the full rough-cut pill readable rather than crushing it to "…".
            min_left_needed = x + stamp_w + 8 + 44 + 6 + (cut_tag_w + 6)
            if not cut_reason or candidate_rect.left() - 8.0 >= min_left_needed:
                retranslate_rect = candidate_rect
                right_bound = min(right_bound, retranslate_rect.left() - 8.0)
                self._hidden_retranslate_rows.discard(index.row())
            else:
                self._hidden_retranslate_rows.add(index.row())
        else:
            self._hidden_retranslate_rows.discard(index.row())

        # start time
        painter.setFont(meta_font)
        painter.setPen(muted)
        painter.drawText(QRectF(x, top, stamp_w, line_h),
                         int(Qt.AlignmentFlag.AlignVCenter), stamp)
        x += stamp_w + 8

        # speaker chip (display name of the stable identity)
        name = _speaker_name(project, cue.speaker_id)
        color = _speaker_color(project, cue.speaker_id, palette)
        dark = palette.dark
        reserve_cut = (cut_tag_w + 6) if cut_reason else 0
        max_chip_w = max(36, int(right_bound - x - 4 - reserve_cut))
        chip_text = meta_metrics.elidedText(name, Qt.TextElideMode.ElideRight, max(20, max_chip_w - 14))
        chip_w = min(max_chip_w, meta_metrics.horizontalAdvance(chip_text) + 14)
        if chip_w >= 28:
            chip = QRectF(x, top + 2, chip_w, line_h - 4)
            chip_fill = QColor(color)
            chip_fill.setAlpha(62 if dark else 46)
            border = QColor(color)
            border.setAlpha(200 if dark else 225)
            luminance = (color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114) / 255.0
            foreground = (QColor(color) if luminance >= 0.55 else color.lighter(150)) if dark else color.darker(160)
            painter.setPen(QPen(border, 1.2))
            painter.setBrush(chip_fill)
            painter.drawRoundedRect(chip, 5, 5)
            painter.setPen(foreground)
            painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), chip_text)
            x += chip_w + 6

        # status (or review level in the priority filters)
        status = None
        if level != "confident":
            high = level == "high"
            fill_color, status_color = status_colors["issue" if high else "pending"]
            label = tr({"high": "需要检查", "suggested": "建议确认"}.get(level, "待确认"))
        else:
            status = _cue_status(project, cue, risks)
            fill_color, status_color = status_colors[status]
            label = tr({'pending': '未审核', 'issue': '有问题', 'done': '已处理'}[status])
            if status == 'pending':
                fill_color = 'transparent'
                status_color = option.palette.color(QPalette.ColorRole.PlaceholderText)
        status_w = meta_metrics.horizontalAdvance(label) + 12
        status_needed_right = x + status_w + reserve_cut
        if status_needed_right <= right_bound + 2 and not (show_retranslate and status == 'pending' and status_needed_right + 8 > right_bound):
            badge = QRectF(x, top + 2, status_w, line_h - 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill_color))
            painter.drawRoundedRect(badge, 5, 5)
            painter.setPen(QColor(status_color))
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), label)
            x += status_w + 6

        # Task 4: compact clickable rough-cut reason pill (guaranteed inside right_bound)
        if cut_reason:
            avail_cut_w = max(24, int(right_bound - x + 2))
            shown_cut = meta_metrics.elidedText(cut_reason, Qt.TextElideMode.ElideRight, max(16, avail_cut_w - 10))
            tag_w = min(avail_cut_w, meta_metrics.horizontalAdvance(shown_cut) + 12)
            tag_rect = QRectF(x, top + 2, tag_w, line_h - 4)
            tag_bg = QColor(blend_hex(theme.surface_elevated, theme.danger, 0.16 if theme.is_light else 0.28))
            tag_fg = QColor(theme.danger)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tag_bg)
            painter.drawRoundedRect(tag_rect, 5, 5)
            painter.setPen(tag_fg)
            painter.drawText(tag_rect, int(Qt.AlignmentFlag.AlignCenter), shown_cut)
            self._rough_cut_rects[index.row()] = tag_rect
            x += tag_w + 6
        else:
            self._rough_cut_rects.pop(index.row(), None)

        if level != "confident" and confirm is not None:
            reason = self._review_reason(project, cue)
            room = int(right_bound - x)
            if reason and room > 24:
                painter.setPen(QColor(status_color))
                painter.drawText(QRectF(x, top, room, line_h), int(Qt.AlignmentFlag.AlignVCenter),
                                 meta_metrics.elidedText(reason, Qt.TextElideMode.ElideRight, room))
            ring = QColor(status_color)
            ring.setAlpha(150)
            painter.setPen(QPen(ring, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(confirm, confirm.height() / 2, confirm.height() / 2)
            painter.setPen(QPen(QColor(status_color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            c = confirm.center()
            s = confirm.height() * 0.22
            painter.drawPolyline([c + type(c)(-s, 0), c + type(c)(-s * 0.3, s * 0.7), c + type(c)(s * 1.1, -s * 0.8)])

        # Compact 「重翻此句」 action pill when original text diverged from translation
        if show_retranslate and retranslate_rect is not None:
            running = cue.id in getattr(model, 'retranslating_cue_ids', ())
            hovered = bool(option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected))
            if running:
                btn_fill = QColor(theme.accent_soft)
                btn_edge = QColor(theme.accent)
                btn_edge.setAlpha(150)
                btn_ink = QColor(theme.accent)
            else:
                base_fill = blend_hex(theme.warning_soft, theme.warning, 0.14) if hovered else theme.warning_soft
                btn_fill = QColor(base_fill)
                btn_edge = QColor(theme.warning)
                btn_edge.setAlpha(185 if hovered else 145)
                btn_ink = QColor(theme.warning)
            painter.setPen(QPen(btn_edge, 1.0))
            painter.setBrush(btn_fill)
            painter.drawRoundedRect(retranslate_rect, 6, 6)
            painter.setFont(self.action_font(option.font))
            painter.setPen(btn_ink)
            painter.drawText(retranslate_rect, int(Qt.AlignmentFlag.AlignCenter), self._retranslate_label(model, cue))
            painter.setFont(meta_font)

        # cue number and playback marker on the right of line one
        painter.setPen(muted)
        painter.drawText(QRectF(right - number_w, top, number_w, line_h),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), number)
        if index.data(CueTableModel.ActiveCueRole):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette.playhead))
            painter.drawEllipse(QRectF(right - number_w - 12, top + line_h / 2 - 3, 6, 6))
        # Sentence area: bilingual dual-line cards or standard single-layer reading cards
        # (both respect soft rough-cut strikethrough + muted ink when marked for cut)
        if getattr(model, 'bilingual_cards', False):
            layout = self._bilingual_layout(option, model, cue)
            text_rect = layout['rect']
            p_font = QFont(layout['primary_font'])
            if cut_reason:
                p_font.setStrikeOut(True)
            p_spacing = layout['primary_spacing']
            p_top = layout['primary_top']
            painter.setFont(p_font)
            painter.setPen(muted if cut_reason else text_color)
            for idx_line, line in enumerate(layout['primary_lines']):
                painter.drawText(
                    QRectF(text_rect.left(), p_top + idx_line * p_spacing, text_rect.width(), p_spacing),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    line,
                )
            s_font = QFont(layout['secondary_font'])
            has_translation = bool(layout['has_translation'])
            if not has_translation:
                s_font.setItalic(True)
            elif cut_reason:
                s_font.setStrikeOut(True)
            s_spacing = layout['secondary_spacing']
            s_top = layout['secondary_top']
            painter.setFont(s_font)
            secondary_ink = (
                theme.text_muted
                if (cut_reason or not has_translation)
                else blend_hex(theme.text_secondary, theme.text_muted, 0.45)
            )
            painter.setPen(QColor(secondary_ink))
            for idx_line, line in enumerate(layout['secondary_lines']):
                painter.drawText(
                    QRectF(text_rect.left(), s_top + idx_line * s_spacing, text_rect.width(), s_spacing),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    line,
                )
        else:
            text_font = self.text_font(option.font)
            if cut_reason:
                text_font.setStrikeOut(True)
                text_color = muted
            text_rect = self._text_rect(option)
            painter.setFont(text_font)
            painter.setPen(text_color)
            spacing = QFontMetrics(text_font).lineSpacing()
            for number_line, line in enumerate(self._wrapped(" ".join(str(model.display_text(cue)).split()), text_font,
                                                             max(40, text_rect.width()))):
                painter.drawText(QRectF(text_rect.left(), text_rect.top() + number_line * spacing, text_rect.width(), spacing),
                                 int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), line)
        painter.restore()
