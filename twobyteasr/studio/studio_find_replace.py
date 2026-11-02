"""Studio subtitle text tools: 批量替换, AI 清理 and the current-glossary review.

2026-10-21 (user): 批量替换 is find/replace only (no tabs); AI 清理 opens from the
cue list beside AI 校对; 文本整理 is no longer offered, and 应用术语库 only reviews
the completion page's retries. All three share one checked preview and one undo step.
2026-10-26: AI 清理 is its own one-page window in ``ai_cleanup_dialog`` (still
importable from here).
"""

from __future__ import annotations

from ..diagnostics.studio_events import observed

from collections import Counter
from dataclasses import asdict, dataclass, fields, is_dataclass
import hashlib
import json
import copy
import html
import weakref

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer, QThread, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QPalette, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import apply_ui_language, current_language
from ..timeline.studio_commands import BatchReplaceTextCommand, MutationOrigin, SetCueFieldsCommand
from .studio_text_tools import (
    SCOPE_ALL,
    SCOPE_CURRENT,
    SCOPE_RANGE,
    SCOPE_SELECTED,
    SCOPE_SPEAKER,
    SCOPE_TRACK,
    TextOccurrence,
    clock_ms,
    find_occurrences,
    format_preview_row,
    scope_cue_ids,
    values_from_occurrences,
    occurrence_conflicts,
)

from ..i18n import bind_text

from ..i18n import tr
from .text_preview_list import TextPreviewList, PreviewItem
from .subtitle_text_targets import entry_lookup, target_label, track_label, navigate_target, scope_entries


# id(project) -> (weakref to it, {binding class: (runtime revision, document fingerprint)})
_DOCUMENT_MEMO = {}


# id(project) -> (weakref to it, {evidence key: (row object, row digest)})
_EVIDENCE_MEMO = {}


def _evidence_digest(project, evidence, *, trust_rows):
    """Content digest of recognition evidence, row by row.

    2026-10-22: the first search keystroke after each edit encoded all
    evidence (~50 MB on 2090 cues, ~0.45 s of GUI time) to fingerprint the
    document. Each row's digest is its marshal bytes' SHA-256; with
    ``trust_rows`` a row object hashed before is not read again.
    """
    import marshal
    if not isinstance(evidence, dict) or any(type(key) is not str for key in evidence):
        return hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True,
                                         default=_dataclass_json).encode('utf8')).hexdigest()
    entry = _EVIDENCE_MEMO.get(id(project))
    previous = entry[1] if entry is not None and entry[0]() is project else {}
    rows, total = {}, hashlib.sha256()
    for key in sorted(evidence):
        row = evidence[key]
        hit = previous.get(key)
        if trust_rows and hit is not None and hit[0] is row:
            digest = hit[1]
        else:
            try:
                digest = hashlib.sha256(marshal.dumps(row, 2)).digest()
            except ValueError:
                digest = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                                   default=_dataclass_json).encode('utf8')).digest()
        rows[key] = (row, digest)
        total.update(key.encode('utf8'))
        total.update(digest)
    for stale in [key for key, (ref, _) in _EVIDENCE_MEMO.items() if ref() is None]:
        del _EVIDENCE_MEMO[stale]
    _EVIDENCE_MEMO[id(project)] = (weakref.ref(project), rows)
    return total.hexdigest()


def _dataclass_json(value):
    # A dataclass nested in a plain field encodes as asdict did before.
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: getattr(value, item.name) for item in fields(value)}
    raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')


@dataclass(frozen=True)
class PreviewBinding:
    project: object
    project_id: str
    revision: int
    fingerprint: str
    document_fingerprint: str

    @staticmethod
    def _document_payload(project):
        # asdict reads persisted edit data without to_dict's validate/persist
        # side effects. Runtime selection/render caches are not dataclass
        # fields; the following known bookmarks are view state only.
        # 2026-10-22 (report-eb10): asdict(project) deep-copied all ASR
        # evidence, ~1.9 s of a 2.4 s live-search keystroke on a 62 MB
        # project. Dataclass parts are still converted (callers edit them);
        # plain JSON values are referenced and encode to the same text.
        payload = {}
        for item in fields(project):
            value = getattr(project, item.name)
            if is_dataclass(value):
                value = asdict(value)
            elif isinstance(value, (list, tuple)) and any(is_dataclass(entry) for entry in value):
                value = [asdict(entry) if is_dataclass(entry) else entry for entry in value]
            payload[item.name] = value
        payload.pop('updated_at', None)
        state = payload.get('studio_state', {})
        if isinstance(state, dict):
            state = payload['studio_state'] = dict(state)
        for key in ('review_risks', 'last_selected_cue', 'playhead_ms', 'zoom',
                'scroll_ms', 'bilingual_mode', 'follow_playhead',
                'timeline_snap_enabled', 'timeline_tool',
                'timeline_track_heights', 'layout'):
            state.pop(key, None)
        return payload

    @classmethod
    def _document_fingerprint(cls, project, *, trust_rows=False):
        # Same daily document digest and evidence-row memo, without Python
        # deepcopy of every cue's nested presentation before JSON encoding.
        payload = {item.name:getattr(project,item.name) for item in fields(project)}
        payload.pop('updated_at',None)
        state = dict(payload.get('studio_state',{}))
        for key in ('review_risks','last_selected_cue','playhead_ms','zoom','scroll_ms',
                    'bilingual_mode','follow_playhead','timeline_snap_enabled','timeline_tool',
                    'timeline_track_heights','layout'):
            state.pop(key,None)
        payload['studio_state']=state
        evidence = payload.pop('asr_evidence', None)
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False,
            sort_keys=True, default=_dataclass_json).encode('utf8'))
        digest.update(_evidence_digest(project, evidence, trust_rows=trust_rows).encode('ascii'))
        return digest.hexdigest()

    @classmethod
    def _cached_document_fingerprint(cls, project, revision):
        """Live search captures a binding on every keystroke. Within one
        runtime revision reuse the last full fingerprint; ``matches`` always
        recomputes before anything is applied, and refreshes this memo, so a
        change made without a revision makes a preview stale, never wrong."""
        entry = _DOCUMENT_MEMO.get(id(project))
        if entry is not None and entry[0]() is project and entry[1].get(cls, (None,))[0] == revision:
            return entry[1][cls][1]
        # A keystroke trusts evidence row objects it has hashed before;
        # ``matches`` re-reads every row before anything is applied.
        digest = cls._document_fingerprint(project, trust_rows=True)
        cls.remember_document_fingerprint(project, revision, digest)
        return digest

    @classmethod
    def remember_document_fingerprint(cls, project, revision, digest):
        entry = _DOCUMENT_MEMO.get(id(project))
        if entry is None or entry[0]() is not project:
            for key in [key for key, (ref, _) in _DOCUMENT_MEMO.items() if ref() is None]:
                del _DOCUMENT_MEMO[key]
            entry = _DOCUMENT_MEMO[id(project)] = (weakref.ref(project), {})
        entry[1][cls] = (revision, digest)

    @staticmethod
    def _fingerprint(project):
        rows = [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id) for c in project.cues]
        # Ordinary previews retain their existing object/revision/text fence;
        # relinking/replacing source media also invalidates pending decisions.
        media = (project.media.path, project.media.fingerprint,
                 [(a.asset_id,a.canonical_source,getattr(a,'fingerprint',''))
                  for a in project.media_pool])
        return hashlib.sha256(json.dumps((media,rows), ensure_ascii=False).encode('utf8')).hexdigest()

    @classmethod
    def capture(cls, project):
        from ..projects.studio_runtime_state import state_for
        revision = state_for(project).revision
        return cls(project, project.project_id, revision,
            cls._fingerprint(project), cls._cached_document_fingerprint(project, revision))

    def matches(self, project):
        from ..projects.studio_runtime_state import state_for
        if not (project is self.project and project.project_id == self.project_id
                and state_for(project).revision == self.revision
                and self._fingerprint(project) == self.fingerprint):
            return False
        current = self._document_fingerprint(project)
        type(self).remember_document_fingerprint(project, self.revision, current)
        return current == self.document_fingerprint


class _GlossaryReviewThread(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, project, cue_ids, snapshot, settings, parent):
        super().__init__(parent)
        from ..recognition.service import CancellationToken
        self.token = CancellationToken()
        self.inputs = (project, cue_ids, snapshot, settings)

    def run(self):
        try:
            from ..recognition.service import preview_glossary_correction
            result = preview_glossary_correction(*self.inputs, cancel_token=self.token)
            self.token.raise_if_cancelled()
            self.ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


def _locked_ids(page) -> list[str]:
    project = page.session.project if page is not None else None
    if project is None:
        return []
    state = getattr(project, "studio_state", {}) or {}
    raw = state.get("locked_cue_ids") if isinstance(state, dict) else []
    return [str(item) for item in (raw or [])]


def _scope_cue_ids(page, scope: str) -> list[str]:
    return scope_cue_ids(page, scope)


def _match_counts(page, cue_ids, needle: str) -> dict[str, int]:
    project = page.session.project
    if project is None or not needle:
        return {}
    hits = find_occurrences(project, cue_ids, needle, needle, case_sensitive=True)
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.cue_id] = counts.get(hit.cue_id, 0) + 1
    return counts


def _search_replace_learning(page, needle: str, replacement: str) -> dict | None:
    """Manual find & replace is learnable human evidence; regex patterns are not."""
    if page is None or getattr(page, "cue_controller", None) is None:
        return None
    if not needle or not replacement or needle == replacement:
        return None
    from ..glossary.glossary_learning import new_evidence_token

    return {
        "token": new_evidence_token(),
        "pair": (needle, replacement),
        "origin": "search_replace",
    }


def replace_next(page, *, needle: str, replacement: str, scope: str) -> bool:
    """Replace the next occurrence at/after the current cue (wraps around)."""
    if not needle or page.session.project is None:
        return False
    cue_ids = _scope_cue_ids(page, scope)
    hits = find_occurrences(page.session.project, cue_ids, needle, replacement, case_sensitive=True)
    if not hits:
        return False
    current = page.session.selected_cue_id
    ordered = list(dict.fromkeys(hit.cue_id for hit in hits))
    if current in ordered:
        target_id = current
    else:
        start = ordered.index(current) if current in ordered else -1
        target_id = ordered[(start + 1) % len(ordered)]
    cue = next(item for item in page.session.project.cues if item.id == target_id)
    page.session.undo_stack.push(SetCueFieldsCommand(
        page.session.project,
        target_id,
        {"text": cue.text.replace(needle, replacement, 1)},
        text="批量替换：下一条",
        changed=page._changed,
        origin=MutationOrigin.SEARCH_REPLACE,
        learning_observer=(
            page.cue_controller.observe_learnable_text
            if getattr(page, "cue_controller", None) is not None
            else None
        ),
        learning_meta=_search_replace_learning(page, needle, replacement),
    ))
    page.select_cue(target_id)
    return True


def replace_all(page, *, needle: str, replacement: str, scope: str) -> tuple[int, int]:
    """Replace every occurrence in scope; one undo step."""
    if not needle or page.session.project is None:
        return 0, 0
    cue_ids = _scope_cue_ids(page, scope)
    hits = find_occurrences(page.session.project, cue_ids, needle, replacement, case_sensitive=True)
    values = values_from_occurrences(page.session.project, hits)
    if not values:
        return 0, 0
    page.session.undo_stack.push(BatchReplaceTextCommand(
        page.session.project,
        values,
        needle=needle,
        changed=page._changed,
        origin=MutationOrigin.SEARCH_REPLACE,
        learning_observer=(
            page.cue_controller.observe_learnable_text
            if getattr(page, "cue_controller", None) is not None
            else None
        ),
        learning_meta=_search_replace_learning(page, needle, replacement),
    ))
    return len(hits), len(values)


def apply_occurrences(
    page,
    hits: list[TextOccurrence],
    *,
    title: str,
    learn_pair: tuple[str, str] | None = None,
    binding: PreviewBinding | None = None,
    glossary_ids=None,
    review_receipt=None,
) -> tuple[int, int]:
    if page.session.project is None or not hits:
        return 0, 0
    if binding is not None and not binding.matches(page.session.project):
        return 0, 0
    if occurrence_conflicts(hits):
        return 0, 0
    if review_receipt is not None:
        review_receipt={**copy.deepcopy(review_receipt),'applied_changes':len(hits),
            'selected_changes':[{'cue_id':hit.cue_id,'span':list(hit.span),'from':hit.original,
                'to':hit.replacement,'source':hit.source,'default_selected':hit.default_selected} for hit in hits]}
    from .subtitle_text_targets import entry_lookup
    entries = entry_lookup(page.session.project, targets=[hit.target for hit in hits])
    values = values_from_occurrences(page.session.project, hits, entries=entries)
    if not values:
        return 0, 0
    hits = [hit for hit in hits if hit.target_key in values and
            entries[hit.target_key].text[hit.span[0]:hit.span[1]] == hit.original]
    if review_receipt is not None:
        review_receipt['applied_changes'] = len(hits)
        review_receipt['selected_changes'] = [dict(cue_id=hit.cue_id, target=entries[hit.target_key].target.to_dict(),
            span=list(hit.span), **{'from': hit.original, 'to': hit.replacement}, source=hit.source,
            default_selected=hit.default_selected) for hit in hits]
    translation_values = {entries[key].target.cue_id: (text, entries[key].target.language)
                          for key, text in values.items() if entries[key].target.storage == 'translation'}
    cue_values = {entries[key].target.cue_id: text for key, text in values.items()
                  if entries[key].target.storage == 'cue'}
    # Translation terminology is not recognition evidence for the source language.
    if any(entries[key].target.layer == 'translation' for key in values):
        learn_pair = None
    origin = MutationOrigin.SEARCH_REPLACE if learn_pair else MutationOrigin.SYSTEM
    learning_meta = None
    if learn_pair is not None:
        learning_meta = _search_replace_learning(page, learn_pair[0], learn_pair[1])
    page.session.undo_stack.push(BatchReplaceTextCommand(
        page.session.project,
        cue_values,
        needle=title,
        changed=page._changed,
        origin=origin,
        learning_observer=(
            page.cue_controller.observe_learnable_text
            if getattr(page, "cue_controller", None) is not None
            else None
        ),
        learning_meta=learning_meta,
        glossary_ids=glossary_ids,
        review_receipt=review_receipt,
        translation_values=translation_values,
    ))
    return len(hits), len(values)



PREVIEW_HTML_ROLE = Qt.ItemDataRole.UserRole + 2
TEXT_TARGET_ROLE = Qt.ItemDataRole.UserRole + 3


def _blend(foreground: str, background: str, share: float) -> str:
    top, base = QColor(foreground), QColor(background)
    mix = lambda a, b: round(a * share + b * (1 - share))
    return QColor(mix(top.red(), base.red()), mix(top.green(), base.green()),
                  mix(top.blue(), base.blue())).name()


def _preview_colors() -> dict[str, str]:
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition

    theme = theme_definition(theme_key())
    return {
        "text": theme.text, "secondary": theme.text_secondary, "muted": theme.text_muted,
        "removed": _blend(theme.danger, theme.input_surface, 0.32),
        "added": _blend(theme.success, theme.input_surface, 0.30),
        "removed_text": theme.danger, "added_text": theme.success,
    }


def replace_row_html(text: str, hit: TextOccurrence, colors: dict[str, str]) -> str:
    """Two lines: the cue with the matched words struck out, then with the new words."""
    start, end = hit.span
    if text[start:end] != hit.original:
        text, start, end = hit.original, 0, len(hit.original)
    clean = lambda part: html.escape(part).replace("\n", " / ")
    removed = (f'<span style="background-color:{colors["removed"]}; text-decoration:line-through;">'
               f'{clean(text[start:end])}</span>')
    added = (f'<span style="background-color:{colors["added"]};">{clean(hit.replacement)}</span>'
             if hit.replacement else "")
    return (f'<span style="color:{colors["muted"]};">{clock_ms(hit.start_ms)}</span>&nbsp;&nbsp;'
            f'<span style="color:{colors["text"]};">{clean(text[:start])}{removed}{clean(text[end:])}</span><br>'
            f'<span style="color:{colors["muted"]};">→</span>&nbsp;'
            f'<span style="color:{colors["secondary"]};">{clean(text[:start])}{added}{clean(text[end:])}</span>')


def replace_card_html(text: str, hits: list[TextOccurrence], colors: dict[str, str], meta: str = "") -> str:
    """One cue as one row: the time (and ``meta``: layer, speaker, track) on the left,
    the sentence with every match struck out and its new words beside it on the right."""
    clean = lambda part: html.escape(part).replace("\n", " / ")
    ordered = sorted(hits, key=lambda hit: hit.span)
    if any(text[hit.span[0]:hit.span[1]] != hit.original for hit in ordered):
        ordered, text = ordered[:1], ordered[0].original
        ordered = [TextOccurrence(ordered[0].cue_id, ordered[0].start_ms, text, ordered[0].replacement,
                                  (0, len(text)))]
    parts, cursor = [], 0
    for hit in ordered:
        start, end = hit.span
        if start < cursor:
            continue
        parts.append(clean(text[cursor:start]))
        parts.append(f'<span style="background-color:{colors["removed"]}; color:{colors["removed_text"]}; '
                     f'text-decoration:line-through;">{clean(text[start:end])}</span>')
        if hit.replacement:
            parts.append(f'<span style="background-color:{colors["added"]}; color:{colors["added_text"]}; '
                         f'font-weight:600;">{clean(hit.replacement)}</span>')
        cursor = end
    parts.append(clean(text[cursor:]))
    count = (f'&nbsp;&nbsp;<span style="color:{colors["muted"]};">{html.escape(tr("{value0} 处", value0=len(ordered)))}</span>'
             if len(ordered) > 1 else "")
    side = (f'<span style="color:{colors["muted"]}; font-size:12px;">{clock_ms(ordered[0].start_ms)}</span>'
            + (f'&nbsp;&nbsp;<span style="color:{colors["secondary"]}; font-size:12px;">{html.escape(meta)}</span>'
               if meta else ''))
    return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td width="150" valign="middle">{side}</td>'
            f'<td valign="middle"><span style="color:{colors["text"]};">{"".join(parts)}</span>{count}</td>'
            f'</tr></table>')


class _PreviewRowDelegate(QStyledItemDelegate):
    """Paints a row's rich text next to the normal check box; plain rows draw as before."""

    def _document(self, font, html_text: str, width: int) -> QTextDocument:
        document = QTextDocument()
        document.setDefaultFont(font)
        document.setDocumentMargin(0)
        document.setHtml(html_text)
        document.setTextWidth(max(40, width))
        return document

    def _option(self, option, index) -> QStyleOptionViewItem:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.text = ""
        return styled

    def paint(self, painter, option, index):
        html_text = index.data(PREVIEW_HTML_ROLE)
        if not html_text:
            return super().paint(painter, option, index)
        styled = self._option(option, index)
        style = styled.widget.style() if styled.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, styled, styled.widget)
        document = self._document(styled.font, html_text, rect.width())
        painter.save()
        painter.translate(rect.left(), rect.top() + max(0, (rect.height() - document.size().height()) / 2))
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QPalette.ColorRole.Text, styled.palette.color(QPalette.ColorRole.Text))
        document.documentLayout().draw(painter, context)
        painter.restore()

    def sizeHint(self, option, index):
        html_text = index.data(PREVIEW_HTML_ROLE)
        if not html_text:
            return super().sizeHint(option, index)
        styled = self._option(option, index)
        view = styled.widget
        width = view.viewport().width() if view is not None else 480
        # Measure the text area of a tall probe row; the rest is padding and the check box.
        styled.rect = QRect(0, 0, width, 400)
        style = view.style() if view is not None else QApplication.style()
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, styled, view)
        document = self._document(styled.font, html_text, rect.width())
        return QSize(width, int(document.size().height()) + 400 - rect.height() + 2)


def _option_chip(text: str, *, checked: bool = False) -> QPushButton:
    chip = QPushButton(text)
    chip.setObjectName("findOptionChip")
    chip.setCheckable(True)
    chip.setChecked(checked)
    chip.setAutoDefault(False)
    # Clicking an option keeps the caret in the text field being typed into.
    chip.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    chip.setCursor(Qt.CursorShape.PointingHandCursor)
    return chip


def _chip_row(chips) -> QWidget:
    from ..exports.subtitle_export_widgets import ChipFlowLayout

    host = QWidget()
    flow = ChipFlowLayout(host, spacing=6)
    for chip in chips:
        flow.addWidget(chip)
    return host


class _TextPreviewDialog(QDialog):
    """Preview list, freshness checks and one-step apply shared by the text tools."""

    _title = "字幕文本工具"

    def __init__(self, page, parent=None):
        super().__init__(parent or page)
        self._page = page
        bind_text(self, self._title, property='windowTitle')
        self.setObjectName("toolDialog")
        self._preview_hits: list[TextOccurrence] = []
        self._preview_binding = None
        self._preview_library_ids = None
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        self._glossary_review_worker = None
        self._review_close_pending = False
        self._review_generation = 0
        self._applied_rows = set()
        self._applying = False
        self._entry_by_key = {}

    def _scope_box(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem("当前字幕", SCOPE_CURRENT)
        combo.addItem("选中字幕", SCOPE_SELECTED)
        combo.addItem("当前说话人", SCOPE_SPEAKER)
        combo.addItem("当前轨道", SCOPE_TRACK)
        combo.addItem("当前时间范围", SCOPE_RANGE)
        combo.addItem("全工程", SCOPE_ALL)
        combo.setCurrentIndex(combo.findData(SCOPE_ALL))
        selected_count = len(self._page.selected_cue_ids()) if self._page is not None else 0
        if selected_count < 1:
            combo.model().item(combo.findData(SCOPE_SELECTED)).setEnabled(False)
        return combo

    def _add_results(self, layout: QVBoxLayout) -> None:
        head = QHBoxLayout()
        head.setSpacing(4)
        self.status_label = QLabel("匹配结果")
        self.status_label.setObjectName("findResultTitle")
        self.status_label.setWordWrap(True)
        head.addWidget(self.status_label, 1)
        self.select_all_button = QPushButton("全选")
        self.select_none_button = QPushButton("全不选")
        for button, checked in ((self.select_all_button, True), (self.select_none_button, False)):
            button.setObjectName("findLinkButton")
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=checked: self._set_all_preview_checked(value))
            head.addWidget(button)
        layout.addLayout(head)
        self.preview = TextPreviewList()
        self.preview.setObjectName("findResultList")
        self.preview.setMinimumHeight(180)
        self.preview.setWordWrap(True)
        self.preview.setResizeMode(QListView.ResizeMode.Adjust)
        self.preview.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.preview.setItemDelegate(_PreviewRowDelegate(self.preview))
        self.preview.setLayoutMode(QListView.LayoutMode.Batched)
        self.preview.setBatchSize(100)
        self.preview.itemDoubleClicked.connect(self._edit_preview_item)
        self.preview.itemClicked.connect(self._preview_item_clicked)
        self.preview.itemChanged.connect(self._refresh_status)
        self.preview.currentItemChanged.connect(self._update_association_button)
        layout.addWidget(self.preview, 1)

    def _add_footer(self, layout: QVBoxLayout, leading=(), trailing=(), *, close_button=True) -> None:
        footer = QHBoxLayout()
        footer.setSpacing(8)
        for widget in leading:
            footer.addWidget(widget)
        footer.addStretch(1)
        closing = ()
        if close_button:
            # The title bar's × and Esc close every tool; some keep a 关闭 button too.
            close = QPushButton("关闭")
            close.clicked.connect(self.reject)
            closing = (close,)
        for widget in (*trailing, *closing):
            footer.addWidget(widget)
        for button in (*leading, *trailing, *closing):
            if isinstance(button, QPushButton):
                button.setMinimumHeight(34)
        layout.addLayout(footer)

    def _finish_setup(self) -> None:
        from ..design.studio_theme import apply_secondary_surface_theme

        for button in self.findChildren(QPushButton):
            # Enter belongs to the text fields; no button is a default button.
            button.setAutoDefault(False)
            button.setDefault(False)
        apply_secondary_surface_theme(self)
        apply_ui_language(self, current_language())
        self._refresh_status()

    # ---------------------------------------------------------- hooks
    def _current_scope(self) -> str:
        return SCOPE_ALL

    def _empty_message(self) -> str:
        return '没有匹配的字幕'

    def _row_text(self, hit: TextOccurrence) -> str:
        return format_preview_row(hit)

    def _row_html(self, hit: TextOccurrence, text: str, colors) -> str:
        return ""

    def _preview_rows(self, hits: list[TextOccurrence]) -> list[list[TextOccurrence]]:
        """Which hits share one list row (and one check box). One each by default."""
        return [[hit] for hit in hits]

    def _rows_html(self, row: list[TextOccurrence], text: str, colors) -> str:
        return self._row_html(row[0], text, colors)

    def _item_html(self, row: list[TextOccurrence], text: str, colors, meta: str, entry=None) -> str:
        """A list row's rich text: the meta line over the row's own text."""
        row_html = self._rows_html(row, text, colors)
        return f'<span style="color:{colors["secondary"]};">{html.escape(meta)}</span><br>{row_html}' if row_html else ""

    def _apply_extras(self, hits) -> dict:
        """Undo title, learning and receipt for this tool's apply."""
        return {"title": self._title}

    def _after_apply(self, total: int, cue_count: int) -> None:
        self._do_preview()
        self._refresh_status()

    def _update_association_button(self, *_args) -> None:
        return None

    def _do_preview(self) -> None:
        return None

    # ---------------------------------------------------------- preview list
    def _fill_preview(self,hits,binding=None):
        project=self._page.session.project
        self._preview_hits=list(hits)
        self._preview_binding=binding or PreviewBinding.capture(project)
        self._applied_rows.clear()
        self._entry_by_key=entry_lookup(project,targets=[hit.target for hit in hits]) if project else {}
        texts={key:entry.text for key,entry in self._entry_by_key.items()}
        colors=_preview_colors() if hits else {}
        self.preview.blockSignals(True)
        self.preview.setUpdatesEnabled(False)
        try:self._add_preview_rows(hits,texts,colors)
        finally:
            self.preview.blockSignals(False)
            self.preview.setUpdatesEnabled(True)
        if hits:bind_text(self.status_label,'找到 {value0} 处',value0=len(hits))
        else:bind_text(self.status_label,self._empty_message())
        self._refresh_status()

    def _add_preview_rows(self,hits,texts,colors):
        self._preview_row_hits=self._preview_rows(hits)
        speakers={s.id:s.name for s in self._page.session.project.speakers}
        items=[]
        for row in self._preview_row_hits:
            hit=row[0]
            entry=self._entry_by_key.get(hit.target_key)
            baseline=entry.text if entry else texts.get(hit.target_key,'')
            label=target_label(entry.target) if entry else ''
            meta=' · '.join(value for value in (label,speakers.get(entry.speaker_id,entry.speaker_id) if entry else '',
                track_label(self._page.session.project,entry.target) if entry else '') if value)
            before_after=baseline
            for each in sorted(row,key=lambda h:h.span,reverse=True):
                before_after=before_after[:each.span[0]]+each.replacement+before_after[each.span[1]:]
            plain=(f'{clock_ms(hit.start_ms)} · {meta}\n'+tr('修改前：{text}',text=baseline)+'\n'
                   +tr('建议：{text}',text=before_after)+'\n'+' · '.join(f'{h.original} → {h.replacement}' for h in row))
            item=PreviewItem(plain)
            row_html=self._item_html(row,baseline,colors,meta,entry)
            if row_html:
                item.setData(PREVIEW_HTML_ROLE,row_html)
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if all(h.default_selected for h in row) else Qt.Unchecked)
            item.setData(Qt.UserRole,entry.target.cue_id if entry else hit.cue_id)
            item.setData(Qt.UserRole+1,dict(surface=hit.original,canonical_options=[hit.replacement],state='proposal',cue_id=hit.cue_id))
            if entry:
                item.setData(TEXT_TARGET_ROLE,entry.target)
                item.setToolTip(tr('对应原文：{text}',text=entry.source_text) if entry.source_text else tr('无可靠原文关联；按当前文本校对。'))
            items.append(item)
        self.preview.replace_items(items)

    def _preview_item_clicked(self, item: QListWidgetItem) -> None:
        cue_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if cue_id and self._page is not None:
            binding = self._preview_binding
            project = self._page.session.project
            was_current = binding is not None and binding.matches(project)
            target=item.data(TEXT_TARGET_ROLE)
            if target is not None:navigate_target(self._page,target)
            else:self._page.select_cue(cue_id)
            if not was_current or self._page.session.project is not project:
                return
            from ..projects.studio_runtime_state import DirtyDomain, state_for
            runtime = state_for(project)
            deltas = [delta for delta in runtime.delta_history if delta.revision > binding.revision]
            navigation = DirtyDomain.CUE_SELECTION | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.TRANSFORM
            # The TRANSFORM flag retires selection handles here. It never
            # permits a manual transform: every editable field must match.
            if (len(deltas) == runtime.revision - binding.revision
                    and all(delta.action_id == 'select_cue' and not delta.dirty & ~navigation for delta in deltas)
                    and PreviewBinding._document_fingerprint(project) == binding.document_fingerprint
                    and PreviewBinding._fingerprint(project) == binding.fingerprint):
                # Just verified at this revision: re-capture without hashing again.
                PreviewBinding.remember_document_fingerprint(project, runtime.revision, binding.document_fingerprint)
                self._preview_binding = PreviewBinding.capture(project)

    def _checked_hits(self) -> list[TextOccurrence]:
        hits = []
        rows = getattr(self, "_preview_row_hits", None)
        if rows is None or sum(map(len, rows)) != len(self._preview_hits):
            rows = [[hit] for hit in self._preview_hits]
        for index, row in enumerate(rows):
            item = self.preview.item(index)
            if item is not None and item.checkState() == Qt.CheckState.Checked and index not in self._applied_rows:
                hits.extend(row)
        return hits

    def _set_all_preview_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.preview.blockSignals(True)
        for index in range(self.preview.count()):
            item = self.preview.item(index)
            if item is not None and item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(state)
        self.preview.blockSignals(False)
        self._refresh_status()

    def _refresh_status(self, *_args) -> None:
        running = self._glossary_review_worker is not None and self._glossary_review_worker.isRunning()
        self.all_button.setEnabled(not running and bool(self._checked_hits()))
        self._update_association_button()

    # ---------------------------------------------------------- apply
    @observed('cue.replace_apply')
    def _do_apply_preview(self) -> None:
        self._apply_checked()

    def _apply_checked(self) -> None:
        if self._preview_binding is None or not self._preview_binding.matches(self._page.session.project):
            self.status_label.setText("工程或文字已改变，请重新预览；本次没有修改字幕。")
            return
        if self._preview_snapshot_digest is not None:
            from ..glossary.terminology import snapshot_glossaries
            import subtitle_core as legacy
            if snapshot_glossaries(legacy, self._preview_library_ids or ()).digest != self._preview_snapshot_digest:
                self.status_label.setText("词库已更新，请按当前词库重新生成预览；本次没有修改字幕。")
                return
        hits = self._checked_hits()
        if not hits:
            bind_text(self.status_label, '没有可应用的预览')
            return
        if occurrence_conflicts(hits):
            self.status_label.setText('同一位置选中了不同候选，请只保留一个后再应用；本次没有修改字幕。')
            return
        extras = self._apply_extras(hits)
        self._last_applied_hits=list(hits)
        self._applying=True
        total, cue_count = apply_occurrences(
            self._page, hits,
            title=extras.get("title") or self._title,
            learn_pair=extras.get("learn_pair"),
            binding=self._preview_binding,
            glossary_ids=extras.get("glossary_ids"),
            review_receipt=extras.get("review_receipt"),
        )
        if total:
            self._page._show_studio_hint(tr('已替换 {value0} 处，涉及 {value1} 条字幕（可 Ctrl+Z 一次撤销）', value0=total, value1=cue_count))
        self._applying=False
        self._after_apply(total, cue_count)

    def reject(self) -> None:
        worker = self._glossary_review_worker
        if worker is not None and worker.isRunning():
            self._review_close_pending = True
            worker.token.cancel()
            self.status_label.setText("正在取消校对，请稍候…")
            return
        super().reject()

    def _add_text_targets(self, layout):
        from .text_target_widgets import TextTargetSelector
        self.text_targets = TextTargetSelector(self)
        self.text_targets.bind(self._page.session.project, self._page)
        self.text_targets.changed.connect(self._text_target_changed)
        layout.addWidget(self.text_targets)

    def _text_target_changed(self):
        self._review_generation += 1
        self._preview_binding = None
        if hasattr(self,'project_entity_box'):
            self.project_entity_box.setEnabled(self.text_targets.mode_value()=='original')
        if hasattr(self,'_search_timer'):
            self._queue_live_search()
        else:
            self._preview_hits=[]
            if hasattr(self,'preview'):self.preview.clear()
            if hasattr(self,'status_label'):self.status_label.setText(tr('操作对象已改变，请重新生成校对建议。'))

    def _scoped_entries(self):
        return scope_entries(self._page,self._current_scope(),mode=self.text_targets.mode_value(),tracks=self.text_targets.tracks())

    def _edit_preview_item(self,item):
        target=item.data(TEXT_TARGET_ROLE)
        if target is None or not hasattr(self._page,'timeline'):return
        if not navigate_target(self._page,target):
            self.status_label.setText(tr('字幕或语言轨道已改变，请重新搜索。'));return
        page=self._page
        self.accept()
        if target.storage=='translation':
            from .studio_translation_edit import edit_translation
            edit_translation(page,target.cue_id)
        else:
            cue=next((c for c in page.session.project.cues if c.id==target.cue_id),None)
            if cue is not None:page.timeline._open_inline_editor(cue,False,cue.text)

    def hideEvent(self,event):
        timer=getattr(self,'_search_timer',None)
        if timer is not None:timer.stop()
        super().hideEvent(event)



class FindReplaceDialog(_TextPreviewDialog):
    """批量替换: find and replace with a checked preview, applied as one undo step."""

    _title = "批量替换"

    def __init__(self, page, parent=None):
        super().__init__(page, parent)
        from ..app.rounded_window import SHADOW, RoundedWindow
        from ..design.themed_icons import install_themed_icon, themed_icon
        from . import find_replace_card as card
        from .text_target_widgets import TextTargetSelector

        # 2026-11-02 (user picked draft B 「软糖卡片」): no Windows title bar, a
        # rounded window that is short until there is something to list.
        self._shown_rows = None
        self.setMinimumWidth(560 + 2 * SHADOW)
        self.resize(640 + 2 * SHADOW, 340 + 2 * SHADOW)
        self._preview_query = None
        self._skipped = Counter()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.root = QWidget()
        self.root.setObjectName("replaceRoot")
        outer.addWidget(self.root)
        column = QVBoxLayout(self.root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.title_bar, self.target_summary, self.close_button = card.title_bar(self._title, self.reject)
        column.addWidget(self.title_bar)
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 2, 16, 14)
        layout.setSpacing(10)
        column.addLayout(layout, 1)

        # 原文 / 译文 / 两者 on the left, the range on the right.
        self.text_targets = TextTargetSelector(self, compact=True)
        self.text_targets.bind(self._page.session.project, self._page)
        self.text_targets.changed.connect(self._text_target_changed)
        self.text_targets.changed.connect(self._update_target_summary)
        self.scope_combo = self._scope_box()
        self.scope_combo.setObjectName("findScopeTag")
        bind_text(self.scope_combo, '范围', property='toolTip')
        self.scope_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        # A tag sized to its label, not the dialog's 180 px field rule.
        self.scope_combo.setProperty("fieldWidth", "tag")
        self.scope_combo.currentIndexChanged.connect(lambda *_args: self._queue_live_search())
        targets = QHBoxLayout()
        targets.setSpacing(8)
        targets.addWidget(self.text_targets)
        targets.addStretch(1)
        targets.addWidget(self.scope_combo)
        layout.addLayout(targets)

        fields = QHBoxLayout()
        fields.setSpacing(8)
        self.find_edit = QLineEdit()
        bind_text(self.find_edit, '要查找的文字，例如：尼奈', property='placeholderText')
        self.replace_edit = QLineEdit()
        bind_text(self.replace_edit, '替换为，例如：她', property='placeholderText')
        for edit, icon_name in ((self.find_edit, "fa5s.search"), (self.replace_edit, "fa5s.pen")):
            edit.setObjectName("findBigField")
            edit.setMinimumHeight(44)
            edit.addAction(themed_icon(icon_name, "muted"), QLineEdit.ActionPosition.LeadingPosition)
            edit.textChanged.connect(self._queue_live_search)
            edit.installEventFilter(self)
        # The find field ends in its match count; the replace field keeps its clear button.
        self.replace_edit.setClearButtonEnabled(True)
        self.count_badge = card.CountBadge(self.find_edit)
        self.swap_button = QPushButton()
        self.swap_button.setObjectName("findSwapButton")
        bind_text(self.swap_button, '对调查找和替换', property='toolTip')
        install_themed_icon(self.swap_button, "fa5s.exchange-alt", "secondary")
        self.swap_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.swap_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.swap_button.clicked.connect(self._swap_fields)
        fields.addWidget(self.find_edit, 1)
        fields.addWidget(self.swap_button, 0, Qt.AlignmentFlag.AlignVCenter)
        fields.addWidget(self.replace_edit, 1)
        layout.addLayout(fields)

        self.lock_box = _option_chip("不修改锁定字幕", checked=True)
        install_themed_icon(self.lock_box, "fa5s.lock", "secondary")
        self.case_box = _option_chip("区分大小写")
        self.word_box = _option_chip("全词匹配")
        self.regex_box = _option_chip("正则表达式")
        self.body_box = _option_chip("仅正文")
        for box in (self.case_box, self.word_box, self.regex_box, self.body_box, self.lock_box):
            box.toggled.connect(self._queue_live_search)
        self.project_entity_box = _option_chip(tr('记录为本工程已确认实体'))
        bind_text(self.project_entity_box, '确认只用于本素材；其它出现位置仍需逐项预览，不写入全局词库。', property='toolTip')
        # The two rarely used options wait behind 更多; turning one on keeps it shown.
        self.more_options_button = QPushButton()
        self.more_options_button.setObjectName("findMoreChip")
        self.more_options_button.setAutoDefault(False)
        self.more_options_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.more_options_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_options_button.clicked.connect(lambda: self._show_more_options(True))
        for box in (self.body_box, self.project_entity_box):
            box.toggled.connect(lambda *_args: self._show_more_options(False))
        self._more_options_open = False
        layout.addWidget(_chip_row((self.lock_box, self.case_box, self.word_box, self.regex_box,
                                    self.body_box, self.project_entity_box, self.more_options_button)))
        self._show_more_options(False)

        # One card: a head line, then the matches, or one line saying what to do.
        self.result_card = QFrame()
        self.result_card.setObjectName("findResultCard")
        card_layout = QVBoxLayout(self.result_card)
        card_layout.setContentsMargins(6, 6, 6, 6)
        card_layout.setSpacing(4)
        self._add_results(card_layout)
        head = card_layout.itemAt(0).layout()
        head.setContentsMargins(8, 2, 2, 0)
        self.status_label.setWordWrap(False)
        self.preview.setObjectName("findResultCards")
        self.preview.setSpacing(2)
        self.preview.setFrameShape(QFrame.Shape.NoFrame)
        self.preview.viewport().setAutoFillBackground(False)
        self.preview.setMinimumHeight(0)
        self.preview.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._empty_row, self._empty_hint = card.empty_row()
        bind_text(self._empty_hint, '也可以在字幕里选字后右键「批量替换相同文字…」')
        card_layout.addWidget(self._empty_row)
        layout.addWidget(self.result_card, 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._live_search)

        footer = QFrame()
        footer.setObjectName("replaceFooter")
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(18, 10, 14, 12)
        actions.setSpacing(8)
        self.key_hint = card.key_hints((("↓", "切到替换"), ("Enter", "替换所选"), ("Esc", "关闭")))
        actions.addWidget(self.key_hint)
        actions.addStretch(1)
        self.next_button = QPushButton("替换下一个")
        self.next_button.setObjectName("findQuietButton")
        self.next_button.clicked.connect(self._do_replace_next)
        self.all_button = QPushButton("替换所选")
        self.all_button.setObjectName("findPrimaryButton")
        self.all_button.setProperty("studioPrimary", True)
        self.all_button.clicked.connect(self._do_apply_preview)
        for button in (self.next_button, self.all_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            actions.addWidget(button)
        column.addWidget(footer)

        self.chrome = RoundedWindow(self, self.root, title_areas=[self.title_bar], radius=card.RADIUS,
                                    maximizable=False)
        self._finish_setup()
        self.refresh_theme_palette()
        self.project_entity_box.setEnabled(self.text_targets.mode_value()=='original')
        self._update_target_summary()
        self._page.session.undo_stack.indexChanged.connect(self._external_text_change)
        self.find_edit.setFocus()

    # ---------------------------------------------------------- frame
    def refresh_theme_palette(self) -> None:
        from ..app.ui_zoom import set_sheet
        from ..design.studio_theme import refresh_secondary_surface_theme
        from ..design.theme_manager import theme_definition, theme_key
        from .find_replace_card import find_replace_qss
        refresh_secondary_surface_theme(self)
        set_sheet(self.root, find_replace_qss(theme_definition(theme_key())))
        self._theme_refresh_pending = False

    def showEvent(self, event):
        if getattr(self, "_theme_refresh_pending", False):
            self.refresh_theme_palette()
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_height)

    def _update_target_summary(self, *_args) -> None:
        label, count = self.text_targets.summary()
        bind_text(self.target_summary, '{scope} · {count} 条文本', scope=label, count=count)
        self.target_summary.setToolTip(self.text_targets.note.text())

    def _fit_height(self) -> None:
        """Short with nothing to list (and not stretchable then); with matches, as
        tall as the rows need up to a limit. Runs only when what is listed changes,
        so a window made taller by hand stays so until the next search."""
        from ..app.ui_zoom import px
        if not self.isVisible():
            return
        rows = self.preview.count() if self._preview_hits else 0
        self.layout().activate()
        if rows:
            self.setMaximumHeight(16777215)
            fixed = self.height() - self.preview.height()
            limit, wanted, spacing = px(360), 0, self.preview.spacing()
            for index in range(rows):
                wanted += self.preview.sizeHintForRow(index) + 2 * spacing
                if wanted >= limit:
                    break
            target = fixed + min(wanted + 2 * self.preview.frameWidth() + 4, limit)
        else:
            target = self.minimumSizeHint().height()
        screen = self.screen()
        if screen is not None:
            target = min(target, screen.availableGeometry().height() - px(40))
        self._shown_rows = rows
        if not rows:
            self.setMaximumHeight(target)
        if target != self.height():
            self.resize(self.width(), target)

    # ---------------------------------------------------------- keyboard
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and watched in (self.find_edit, self.replace_edit):
            key = event.key()
            if key == Qt.Key.Key_Down and watched is self.find_edit:
                self.replace_edit.setFocus(Qt.FocusReason.TabFocusReason)
                self.replace_edit.end(False)
                return True
            if key == Qt.Key.Key_Up and watched is self.replace_edit:
                self.find_edit.setFocus(Qt.FocusReason.BacktabFocusReason)
                self.find_edit.end(False)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._apply_from_keyboard()
                return True
        return super().eventFilter(watched, event)

    def _query(self):
        return (self.find_edit.text(), self.replace_edit.text(), self._current_scope(),
                self.case_box.isChecked(), self.word_box.isChecked(), self.regex_box.isChecked(),
                self.body_box.isChecked(), self.lock_box.isChecked(), self.text_targets.mode_value(),
                self.text_targets.track.currentData(),
                tuple(entry.key for entry in self._scoped_entries()) if self._current_scope() != SCOPE_ALL else ())

    def _apply_from_keyboard(self) -> None:
        if not self.find_edit.text():
            return
        # Typed faster than the live preview: preview what is in the fields now.
        if self._search_timer.isActive() or self._preview_query != self._query():
            self._search_timer.stop()
            self._do_preview()
        self._do_apply_preview()

    def _swap_fields(self) -> None:
        find, replace = self.find_edit.text(), self.replace_edit.text()
        self.find_edit.setText(replace)
        self.replace_edit.setText(find)
        self.find_edit.setFocus()

    # ---------------------------------------------------------- hooks
    def _current_scope(self) -> str:
        return str(self.scope_combo.currentData() or SCOPE_ALL)

    def _empty_message(self) -> str:
        return '没有匹配的字幕' if self.find_edit.text().strip() else '输入查找文字后显示匹配数量'

    def _row_html(self, hit: TextOccurrence, text: str, colors) -> str:
        return replace_card_html(text, [hit], colors)

    def _preview_rows(self, hits: list[TextOccurrence]) -> list[list[TextOccurrence]]:
        # One card per cue: two matches in one sentence are ticked together.
        rows: dict[str, list[TextOccurrence]] = {}
        for hit in hits:
            rows.setdefault(hit.target_key, []).append(hit)
        return list(rows.values())

    def _rows_html(self, row: list[TextOccurrence], text: str, colors) -> str:
        return replace_card_html(text, row, colors)

    def _item_html(self, row: list[TextOccurrence], text: str, colors, meta: str, entry=None) -> str:
        # Draft B: the time and who sit left of the sentence; the layer and
        # language only when translations are searched too.
        if entry is not None:
            project = self._page.session.project
            speaker = next((s.name for s in project.speakers if s.id == entry.speaker_id), entry.speaker_id or "")
            parts = [target_label(entry.target)] if self.text_targets.mode_value() != "original" else []
            meta = " · ".join(dict.fromkeys(part for part in (*parts, speaker) if part))
        return replace_card_html(text, row, colors, meta)

    def _show_more_options(self, open_: bool) -> None:
        """仅正文 and 记录实体 stay behind 更多 until opened or turned on."""
        self._more_options_open = self._more_options_open or bool(open_)
        hidden = 0
        for box in (self.body_box, self.project_entity_box):
            shown = self._more_options_open or box.isChecked()
            box.setVisible(shown)
            hidden += not shown
        bind_text(self.more_options_button, '+ 更多选项')
        self.more_options_button.setVisible(hidden > 0)

    def _apply_extras(self, hits) -> dict:
        extras = {"title": self.find_edit.text() or self._title}
        if self.regex_box.isChecked() or any(h.target is not None and h.target.layer=='translation' for h in hits):
            # Regex patterns are not term corrections; nothing is learned.
            return extras
        needle = self.find_edit.text().strip()
        replacement = self.replace_edit.text().strip()
        if needle and replacement:
            if self.project_entity_box.isChecked():
                from ..glossary.project_entity_confirmations import confirmation_receipt
                project = self._page.session.project
                extras["review_receipt"] = confirmation_receipt(project, needle, replacement, {h.cue_id for h in hits})
                extras["glossary_ids"] = project.glossary_ids
            else:
                extras["learn_pair"] = (needle, replacement)
        return extras

    def _apply_checked(self) -> None:
        # Per cue, how many rows were left unticked: after the apply those are what remains.
        self._skipped = (Counter(hit.target_key for hit in self._preview_hits)
                         - Counter(hit.target_key for hit in self._checked_hits()))
        super()._apply_checked()

    def _after_apply(self, total: int, cue_count: int) -> None:
        self._do_preview()
        if total and self._skipped and Counter(hit.target_key for hit in self._preview_hits) == self._skipped:
            # The rows left are the ones you unticked; a second Enter must not take them.
            self._set_all_preview_checked(False)
        self._refresh_status()
        if total:
            bind_text(self.status_label, '已替换 {value0} 处，涉及 {value1} 条字幕（可 Ctrl+Z 一次撤销）',
                      value0=total, value1=cue_count)
        # Ready for the next pair: the find text is selected, so typing replaces it.
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    # ---------------------------------------------------------- search
    def _queue_live_search(self, *_args) -> None:
        self._refresh_status()
        self._search_timer.start()

    def _live_search(self) -> None:
        self._do_preview()

    def _refresh_status(self, *_args) -> None:
        super()._refresh_status()
        needle = self.find_edit.text()
        enabled = bool(needle) and self._page.session.project is not None
        self.next_button.setEnabled(enabled)
        has_rows=self.preview.count()>0
        self.select_all_button.setVisible(has_rows)
        self.select_none_button.setVisible(has_rows)
        checked=len(self._checked_hits())
        if checked:bind_text(self.all_button,'替换 {value0} 处',value0=checked)
        else:bind_text(self.all_button,'替换所选')
        self.all_button.setEnabled(bool(self._checked_hits()))
        self._show_list(bool(self._preview_hits))
        broken = enabled and self.regex_box.isChecked() and not self._pattern_ok(needle)
        if self.find_edit.property("regexError") != broken:
            self.find_edit.setProperty("regexError", broken)
            self.find_edit.style().unpolish(self.find_edit)
            self.find_edit.style().polish(self.find_edit)
        self._mark_status_error(broken)
        self.count_badge.set_shown(enabled)
        if not enabled:
            bind_text(self.status_label, '输入查找文字后显示匹配数量')
            return
        if broken:
            self.count_badge.set_count(None, tr('正则表达式写法有误；关掉「正则表达式」就按普通文字查找。'))
            bind_text(self.status_label, '正则表达式写法有误；关掉「正则表达式」就按普通文字查找。')
            self.next_button.setEnabled(False)
            return
        if self._preview_query == self._query() and self._preview_binding is not None:
            hits = self._preview_hits
        else:
            hits = find_occurrences(
                self._page.session.project, _scope_cue_ids(self._page, self._current_scope()),
                needle, self.replace_edit.text(), case_sensitive=self.case_box.isChecked(),
                whole_word=self.word_box.isChecked(), regex=self.regex_box.isChecked(),
                body_only=self.body_box.isChecked(), skip_locked=self.lock_box.isChecked(),
                locked_ids=_locked_ids(self._page), entries=self._scoped_entries())
        self.count_badge.set_count(len(hits))
        if not hits:
            bind_text(self.status_label, '没有匹配的字幕')
            self.next_button.setEnabled(False)
            return
        bind_text(self.status_label, '匹配 {cues} 条字幕 · {texts} 条文本 · {hits} 处',
                  cues=len({h.cue_id for h in hits}), texts=len({h.target_key for h in hits}), hits=len(hits))

    def _mark_status_error(self, error: bool) -> None:
        if self.status_label.property("error") != error:
            self.status_label.setProperty("error", error)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)

    def _pattern_ok(self, needle: str) -> bool:
        import re
        from .studio_text_tools import _compile_needle
        try:
            _compile_needle(needle, case_sensitive=self.case_box.isChecked(),
                            whole_word=self.word_box.isChecked(), regex=True)
        except re.error:
            return False
        return True

    def _show_list(self, rows: bool) -> None:
        """The matches, or the card's one-line hint; the window's height follows."""
        changed = self.preview.isHidden() == rows or self._shown_rows != (self.preview.count() if rows else 0)
        self.preview.setVisible(rows)
        self._empty_row.setVisible(not rows)
        if changed and self.isVisible():
            QTimer.singleShot(0, self._fit_height)


    @observed('cue.search')
    def _do_preview(self) -> None:
        project = self._page.session.project
        if project is None:
            return
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        self._preview_query = self._query()
        if not self.find_edit.text().strip():
            self._fill_preview([])
            return
        binding = PreviewBinding.capture(project)
        hits = find_occurrences(
            project, list(dict.fromkeys(entry.target.cue_id for entry in self._scoped_entries())),
            self.find_edit.text(), self.replace_edit.text(),
            case_sensitive=self.case_box.isChecked(),
            whole_word=self.word_box.isChecked(),
            regex=self.regex_box.isChecked(),
            body_only=self.body_box.isChecked(),
            skip_locked=self.lock_box.isChecked(),
            locked_ids=_locked_ids(self._page),
            entries=self._scoped_entries(),
        )
        self._fill_preview(hits, binding)


    @observed('cue.replace_next')
    def _do_replace_next(self) -> None:
        needle = self.find_edit.text()
        if not needle:
            return
        self._do_preview()
        hits = self._checked_hits()
        current = self._page.session.selected_cue_id
        hit = next((h for h in hits if h.cue_id == current), hits[0] if hits else None)
        ok = apply_occurrences(self._page, [hit], title=needle, binding=self._preview_binding)[0] if hit else 0
        if ok and hit.target is not None:
            from .subtitle_text_targets import navigate_target
            navigate_target(self._page, hit.target)
        if ok:
            self._page._show_studio_hint(tr('已替换下一条（可 Ctrl+Z 撤销）'))
        self._do_preview()


    @observed('cue.replace_all')
    def _do_replace_all(self) -> None:
        self._do_preview()
        self._do_apply_preview()

    def _external_text_change(self,*_args):
        if self.isVisible() and not self._applying:self._queue_live_search()



class GlossaryReviewDialog(_TextPreviewDialog):
    """应用术语库: the selected libraries' local and AI review of existing text.

    No longer offered beside find/replace (AI 校对 covers it); the completion
    page's retry and 用当前词库重新校对 still review their results here.
    """

    _title = "应用术语库"

    def _after_apply(self,total,cue_count):
        if not total:return
        from dataclasses import replace
        from difflib import SequenceMatcher
        actuals=entry_lookup(self._page.session.project,targets=[h.target for h in self._preview_hits])
        selected=getattr(self,'_last_applied_hits',())
        self.preview.blockSignals(True)
        try:
            for index,row in enumerate(self._preview_row_hits):
                item=self.preview.item(index)
                if any(hit in selected for hit in row):
                    self._applied_rows.add(index)
                    actual=actuals.get(row[0].target_key)
                    written=tr('已写回：{text}',text=actual.text if actual else '')
                    item.setText(item.text()+'\n'+written)
                    rich=item.data(PREVIEW_HTML_ROLE)
                    if rich:item.setData(PREVIEW_HTML_ROLE,rich+'<br>'+html.escape(written))
                    item.setCheckState(Qt.Unchecked)
                    item.setFlags(item.flags()&~Qt.ItemIsUserCheckable)
                elif index not in self._applied_rows:
                    updated=[]
                    for hit in row:
                        actual=actuals.get(hit.target_key)
                        if actual is not None and hit.baseline is not None and hit.baseline!=actual.text:
                            span=next(((c+hit.span[0]-a,c+hit.span[1]-a) for tag,a,b,c,d in
                                SequenceMatcher(None,hit.baseline,actual.text,autojunk=False).get_opcodes()
                                if tag=='equal' and a<=hit.span[0]<=hit.span[1]<=b),None)
                            if span is None:
                                item.setCheckState(Qt.Unchecked)
                                item.setFlags(item.flags()&~Qt.ItemIsUserCheckable)
                            else:hit=replace(hit,span=span,baseline=actual.text,context_snapshot=actual)
                        updated.append(hit)
                    self._preview_row_hits[index]=updated
            self._preview_hits=[hit for row in self._preview_row_hits for hit in row]
        finally:self.preview.blockSignals(False)
        self._preview_binding=PreviewBinding.capture(self._page.session.project)
        self._refresh_status()

    def __init__(self, page, parent=None):
        super().__init__(page, parent)
        self.setMinimumSize(640, 540)
        self.resize(800, 660)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)
        self._add_text_targets(layout)
        layout.addLayout(self._terms_controls())
        self._add_results(layout)
        self.preview_button = QPushButton("预览")
        bind_text(self.preview_button, '按所选词库重新生成本地预览', property='toolTip')
        self.preview_button.clicked.connect(self._do_preview)
        self.all_button = QPushButton("应用所选预览")
        self.all_button.setProperty("studioPrimary", True)
        self.all_button.clicked.connect(self._do_apply_preview)
        self._add_footer(layout, leading=(self.preview_button,), trailing=(self.all_button,))
        self._finish_setup()

    def _terms_controls(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(8)
        note = QLabel("使用当前工程词库；预览后可取消个别修改，确认后可一次撤销。")
        note.setWordWrap(True)
        note.setObjectName("cardMeta")
        layout.addWidget(note)
        self.terms_scope = self._scope_box()
        self.terms_scope.setCurrentIndex(self.terms_scope.findData(SCOPE_ALL))
        scope_row = QHBoxLayout()
        scope_label = QLabel("范围")
        scope_label.setObjectName("findFieldLabel")
        scope_row.addWidget(scope_label)
        scope_row.addWidget(self.terms_scope)
        scope_row.addStretch(1)
        layout.addLayout(scope_row)
        self.terms_libraries = QListWidget()
        self.terms_libraries.setMaximumHeight(100)
        project = self._page.session.project
        if project:
            import subtitle_core as legacy
            catalog = getattr(legacy, 'glossary_catalog', lambda: [])()
            for row in catalog:
                identity, display = row['id'], row['name']
                item = QListWidgetItem(display)
                item.setData(Qt.UserRole, identity)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if identity in project.glossary_ids else Qt.Unchecked)
                self.terms_libraries.addItem(item)
        if not self.terms_libraries.count():
            note.setText("尚无词库。请先在术语库中建立规范词或已确认纠错。")
        elif project and not project.glossary_ids:
            note.setText("当前工程尚未启用词库。勾选词库并预览，确认应用后保存到本工程。")
        layout.addWidget(self.terms_libraries)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.terms_ai_button = QPushButton("按当前词库生成 AI 校对预览")
        self.terms_ai_button.setToolTip("复用原始转写，以当前所选词库和已配置校对模型生成差异；确认后应用，可一次撤销。")
        self.terms_ai_button.clicked.connect(self._do_terms_ai_preview)
        self.project_entities_button = QPushButton(tr('复核本工程已确认实体'))
        self.project_entities_button.clicked.connect(self._do_project_entities_preview)
        self.associate_button = QPushButton('确认所选名称关联…')
        self.associate_button.setObjectName('glossaryAssociateButton')
        self.associate_button.setEnabled(False)
        self.associate_button.clicked.connect(self._open_term_association)
        for button in (self.terms_ai_button, self.project_entities_button, self.associate_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.terms_libraries.itemChanged.connect(self._invalidate_term_preview)
        self.terms_scope.currentIndexChanged.connect(self._invalidate_term_preview)
        return layout

    def _current_scope(self) -> str:
        return str(self.terms_scope.currentData() or SCOPE_ALL)

    def _row_text(self, hit: TextOccurrence) -> str:
        cue = next((c for c in self._page.session.project.cues if c.id == hit.cue_id), None)
        if cue is None:
            return format_preview_row(hit)
        changed = cue.text[:hit.span[0]] + hit.replacement + cue.text[hit.span[1]:]
        reason = {'case_normalization':'大小写规范化','confirmed_alias':'已确认别名/纠错',
                  'user_confirmed':'用户确认（本工程）'}.get(hit.reason, hit.reason)
        state = ('已确认规范化' if hit.source=='local_confirmed' else 'AI 自动通过（已选）') if hit.default_selected else '待确认（默认未选）'
        extra = ' · '.join(x for x in (hit.evidence, hit.missing_evidence) if x)
        return f"{cue.text} → {changed}\n命中：{hit.original} → {hit.replacement} · {reason} · {state}" + ('\n'+extra if extra else '')

    def _apply_extras(self, hits) -> dict:
        return {"title": self._title, "glossary_ids": self._preview_library_ids,
                "review_receipt": self._glossary_review_receipt}

    def _refresh_status(self, *_args) -> None:
        super()._refresh_status()
        if not (self._glossary_review_worker is not None and self._glossary_review_worker.isRunning()):
            self._update_terms_status()

    def _invalidate_term_preview(self, *_args):
        self._review_generation += 1
        self._preview_binding = None
        self._preview_hits = []
        self._preview_library_ids = None
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        if hasattr(self, 'preview'):
            self.preview.clear()
            self.status_label.setText("词库或范围已改变，请重新预览。")
            self._refresh_status()

    def _do_project_entities_preview(self):
        from ..glossary.project_entity_confirmations import confirmed_entity_occurrences
        project = self._page.session.project
        if project is None:
            return
        self._preview_snapshot_digest = None
        self._preview_library_ids = tuple(project.glossary_ids)
        self._glossary_review_receipt = {'kind': 'project_entity_confirmation_review',
            'source': 'user_confirmed', 'media_fingerprint': project.media.fingerprint,
            'audio_verified_by_model': False}
        cue_ids = set(_scope_cue_ids(self._page,self._current_scope()))
        conflicts = []
        hits = confirmed_entity_occurrences(project, locked_ids=_locked_ids(self._page),diagnostics=conflicts)
        self._fill_preview([h for h in hits if h.cue_id in cue_ids],
            PreviewBinding.capture(project))
        if conflicts:
            bind_text(self.status_label, '同一实体有不同确认写法，已跳过：{aliases}。请逐条确认。', aliases='、'.join(conflicts))

    def _show_terms_result(self, result, binding, snapshot, identities):
        self._fill_preview(list(result.hits), binding)
        self._preview_library_ids = tuple(identities)
        self._preview_snapshot_digest = snapshot.digest
        self._glossary_review_receipt = result.receipt
        for row in result.receipt.get('pending_rows', ()):
            title = '缺失名称关联（不会自动修改）' if row['state']=='missing_alias_or_candidate' else '已拒绝无效输出（不会应用）'
            item = PreviewItem(f"{row['original']}\n{title}：{row['surface']} · {row['reason']}")
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole, row['cue_id'])
            item.setData(Qt.ItemDataRole.UserRole+1, row)
            self.preview.addItem(item)
        self._update_terms_status()
        self._refresh_status()

    def _update_terms_status(self):
        row = self._glossary_review_receipt
        if not row or row.get('kind')!='current_glossary_text_review':
            return
        states = {'request_failed':'调用失败；已保留本地预览', 'library_read_error':'所选词库未找到，请检查',
            'needs_confirmation':'待确认候选默认未选', 'missing_associations':'请选择缺失名称行并确认关联',
            'invalid_output':'无效输出已拒绝', 'changes_ready':'请确认所选修改',
            'no_changes':'已核对当前词库，范围内没有文字变化'}
        selected=len(self._checked_hits())
        summary=row['snapshot_summary']
        revisions='、'.join(f"{x['name']} r{x['revision']}" for x in row['snapshot'].get('libraries',()))
        self.status_label.setText(f"{revisions} · 有效 {summary['effective_terms']} 个规范词\n"
            f"已核对 {row.get('checked_cues',0)} 条 · AI 返回 {row.get('successful_cues',0)} 条 · 回退 {row.get('fallback_cues',0)} 条 · "
            f"自动可选 {row.get('automatic_changes',0)} 处 · 待确认 {row.get('confirmation_changes',0)} 处 · "
            f"拒绝 {row.get('rejected_changes',0)} 处 · 缺失关联 {row.get('missing_associations',0)} 处 · 当前选中 {selected} 处\n"
            + states.get(row.get('empty_state'),'请逐项确认')+'；未核验原音。')
        self.status_label.setToolTip('诊断：'+str(row.get('diagnostic_path',''))+'\n'+'\n'.join(row.get('request_errors',())))

    def _selected_library_ids(self):
        return tuple(str(self.terms_libraries.item(i).data(Qt.UserRole)) for i in range(self.terms_libraries.count())
            if self.terms_libraries.item(i).checkState()==Qt.Checked)

    def _read_selected_snapshot(self):
        import subtitle_core as legacy
        from ..glossary.terminology import snapshot_glossaries
        # A damaged DB must not silently become an empty library or a write target.
        legacy.load_learned_term_payload(strict=True)
        identities=self._selected_library_ids()
        return identities,snapshot_glossaries(legacy,identities)

    def _update_association_button(self, *_args):
        if not hasattr(self,'associate_button') or not hasattr(self,'preview'):
            return
        item=self.preview.currentItem()
        row=item.data(Qt.ItemDataRole.UserRole+1) if item else None
        self.associate_button.setEnabled(bool(row)
            and row.get('state') in {'proposal','missing_alias_or_candidate'}
            and bool(row.get('surface')) and bool(self._selected_library_ids())
            and not (self._glossary_review_worker and self._glossary_review_worker.isRunning()))

    def _open_term_association(self):
        item=self.preview.currentItem()
        row=item.data(Qt.ItemDataRole.UserRole+1) if item else None
        if not row or row.get('state') not in {'proposal','missing_alias_or_candidate'}:
            return
        try:
            identities,snapshot=self._read_selected_snapshot()
        except (OSError,ValueError) as exc:
            self.status_label.setText('词库读取失败，未写入：'+str(exc)); return
        if not identities or (self._preview_snapshot_digest and snapshot.digest!=self._preview_snapshot_digest):
            self.status_label.setText('词库已改变，请重新预览后确认名称。'); return
        dialog=TermAssociationDialog(row, snapshot, self)
        self._association_dialog=dialog
        dialog.saved.connect(self._term_association_saved)
        dialog.open()

    def _term_association_saved(self, identity, source, canonical):
        owner=self._page.window()
        library=getattr(getattr(owner,'term_library_page',None),'library',None)
        notify=getattr(library,'_notify_library_changed',None)
        if callable(notify):notify()
        else:
            refresh=getattr(owner,'_refresh_content_choices',None)
            if callable(refresh):refresh()
        self._invalidate_term_preview()
        self._do_preview()

    @observed('cue.search')
    def _do_preview(self) -> None:
        project = self._page.session.project
        if project is None:
            return
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        prepare = getattr(self._page.window(), '_prepare_glossary_for_task', None)
        if callable(prepare) and not prepare():
            self.status_label.setText('词库输入尚未提交，请先保存或放弃输入后重试。')
            return
        cue_ids = _scope_cue_ids(self._page, self._current_scope())
        binding = PreviewBinding.capture(project)
        from ..glossary.studio_glossary_service import preview_glossary_correction
        try:
            identities,snapshot=self._read_selected_snapshot()
            from .subtitle_text_targets import review_project
            entries=self._scoped_entries()
            result=preview_glossary_correction(review_project(project,entries),[e.key for e in entries],snapshot,{},use_ai=False)
        except Exception as exc:
            self._fill_preview([],binding)
            self.status_label.setText('当前词库本地预览未完成：'+str(exc)); return
        self._show_terms_result(result,binding,snapshot,identities)

    def _do_terms_ai_preview(self) -> None:
        if self._glossary_review_worker is not None and self._glossary_review_worker.isRunning():
            return
        prepare = getattr(self._page.window(), '_prepare_glossary_for_task', None)
        if callable(prepare) and not prepare():
            self.status_label.setText('词库输入尚未提交，请先保存或放弃输入后重试。')
            return
        project = self._page.session.project
        if project is None:
            return
        import subtitle_core as legacy
        try:
            identities,snapshot=self._read_selected_snapshot()
        except (OSError,ValueError) as exc:
            self._fill_preview([])
            self.status_label.setText('词库读取失败，未调用 AI：'+str(exc)); return
        if not snapshot.canonical_terms:
            self.status_label.setText("请先选择有已确认规范词的词库。")
            return
        from ..app.api_key_explainer import ask_for_key_if_missing
        if ask_for_key_if_missing(self, copy.deepcopy(legacy.RUNTIME_SETTINGS), "polish", status=lambda: bind_text(
                self.status_label, 'AI 校对没有运行：还没填 API Key')):
            return
        binding = PreviewBinding.capture(project)
        generation = self._review_generation
        settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
        from ..projects.studio_project import SubtitleProject
        from .subtitle_text_targets import review_project
        entries=self._scoped_entries()
        copied=review_project(project,entries)
        cue_ids = [entry.key for entry in entries]
        self._preview_hits = []
        self._preview_binding = None
        self._preview_snapshot_digest = None
        self._glossary_review_receipt = None
        self.preview.clear()
        self.terms_ai_button.setEnabled(False)
        self.all_button.setEnabled(False)
        self.status_label.setText("正在按当前词库校对已有转写，完成后显示差异…")
        worker = _GlossaryReviewThread(copied, cue_ids, snapshot, settings, self)
        self._glossary_review_worker = worker

        def ready(result):
            if self._review_close_pending:
                return
            if generation != self._review_generation or not binding.matches(self._page.session.project):
                self.status_label.setText("工程、文字或选择已改变，本次校对结果未应用；请重新预览。")
                return
            self._show_terms_result(result,binding,snapshot,identities)

        def failed(message):
            if not self._review_close_pending:
                self.status_label.setText("当前词库校对未完成：" + message)

        def finished():
            self.terms_ai_button.setEnabled(True)
            self._glossary_review_worker = None
            self._refresh_status()
            worker.deleteLater()
            if self._review_close_pending:
                super(GlossaryReviewDialog,self).reject()

        worker.ready.connect(ready)
        worker.failed.connect(failed)
        worker.finished.connect(finished)
        worker.start()


class TermAssociationDialog(QDialog):
    """Explicit user confirmation in the selected current library, with free canonical input."""
    saved = Signal(str,str,str)

    def __init__(self,row,snapshot,parent):
        super().__init__(parent)
        self.setWindowTitle('确认名称关联')
        self.setObjectName('termAssociationDialog')
        self.setMinimumWidth(520)
        self._snapshot=snapshot
        self._selected_ids=tuple(library.id for library in snapshot.libraries)
        layout=QVBoxLayout(self)
        note=QLabel('将别名保存为当前所选词库中的用户确认映射。可以选择已有规范词，也可以明确新增；字幕随后重新预览。')
        note.setWordWrap(True);layout.addWidget(note)
        grid=QGridLayout()
        self.library_combo=QComboBox();self.library_combo.setObjectName('termAssociationLibrary')
        for library in snapshot.libraries:self.library_combo.addItem(library.name,library.id)
        self.alias_edit=QLineEdit(str(row.get('surface','')))
        self.alias_edit.setObjectName('termAssociationAlias')
        self.canonical_combo=QComboBox();self.canonical_combo.setEditable(True)
        self.canonical_combo.setObjectName('termAssociationCanonical')
        self.canonical_combo.setInsertPolicy(QComboBox.NoInsert)
        options=list(dict.fromkeys([*row.get('canonical_options',()),*snapshot.canonical_terms]))
        self.canonical_combo.addItems(options)
        # A roster is context, not a guessed canonical. Require an explicit value.
        self.canonical_combo.setCurrentIndex(-1)
        self.canonical_combo.setEditText('')
        self.canonical_combo.lineEdit().setPlaceholderText('选择已有规范词，或输入新规范词（保留大小写）')
        for index,(label,field) in enumerate((('词库',self.library_combo),('当前别名',self.alias_edit),('规范词',self.canonical_combo))):
            grid.addWidget(QLabel(label),index,0);grid.addWidget(field,index,1)
        layout.addLayout(grid)
        self.status=QLabel('');self.status.setWordWrap(True);layout.addWidget(self.status)
        actions=QHBoxLayout()
        self.save_button=QPushButton('确认并保存关联');self.save_button.setObjectName('termAssociationSave')
        self.save_button.clicked.connect(self._save)
        close=QPushButton('取消');close.clicked.connect(self.reject)
        actions.addStretch(1);actions.addWidget(self.save_button);actions.addWidget(close);layout.addLayout(actions)
        self.canonical_combo.editTextChanged.connect(self._update_status)
        self.alias_edit.textChanged.connect(self._update_status)
        self.library_combo.currentIndexChanged.connect(self._update_status)
        self._update_status()

    def _update_status(self,*_args):
        canonical=self.canonical_combo.currentText().strip()
        source=self.alias_edit.text().strip()
        identity=str(self.library_combo.currentData() or '')
        library=next((library for library in self._snapshot.libraries if library.id==identity),None)
        targets={term.canonical for term in library.terms} if library else set()
        existing=canonical in targets
        self.status.setText(('已存在规范词：' if existing else '将新增规范词：')+canonical if canonical else '请输入并确认规范词；当前没有自动选择。')
        self.save_button.setEnabled(bool(source and canonical and source!=canonical and library and library.found))

    def _save(self):
        import subtitle_core as legacy
        from ..glossary.terminology import snapshot_glossaries
        source=self.alias_edit.text().strip();canonical=self.canonical_combo.currentText().strip()
        identity=str(self.library_combo.currentData() or '')
        if not self.save_button.isEnabled():return
        try:
            legacy.load_learned_term_payload(strict=True)
            current=snapshot_glossaries(legacy,self._selected_ids)
            if current.digest!=self._snapshot.digest:
                raise ValueError('词库已经更新，请关闭此窗口并重新预览')
            library=next((x for x in current.libraries if x.id==identity and x.found),None)
            if library is None:raise ValueError('所选词库未找到，未写入')
            if any(term.canonical.casefold()==source.casefold() and term.canonical.casefold()!=canonical.casefold()
                    for term in library.terms):
                raise ValueError('当前别名也是独立规范词；请在术语库明确编辑，不能在此合并身份')
            legacy.add_learned_mapping(identity,source,canonical,category='选手ID',origin='手动')
        except (OSError,ValueError,TypeError) as exc:
            self.status.setText('未保存：'+str(exc));return
        self.saved.emit(identity,source,canonical)
        self.accept()


def __getattr__(name):
    # AI 清理 lives in ai_cleanup_dialog, which imports this module (2026-10-26).
    if name == "AiCleanupDialog":
        from .ai_cleanup_dialog import AiCleanupDialog
        return AiCleanupDialog
    raise AttributeError(name)
