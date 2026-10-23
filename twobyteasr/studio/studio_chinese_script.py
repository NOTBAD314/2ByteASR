"""Studio: convert a project's Chinese subtitles between 简体 and 繁體 (2026-10-19, ADR 0132).

The home page choice 繁体中文 converts recognized subtitles once, at delivery.
This command does the same for an existing project, either way, as one undo
step: ``cue.text`` and ``original_text`` are rewritten with the local table
(``subtitle_rules/chinese_script.py``), and the project records
``generation_metadata.language.script``, which later glossary checks and
newly produced text follow.

Every character becomes exactly one character, so timings, speakers, cue ids,
clip mapping and word receipts stay valid: receipts and term word overrides
keep their measured times and only show the new characters; translations whose
source was the old text keep their status. Lines with kana or Hangul are left
alone.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from ..i18n import tr
from ..subtitle_rules import chinese_script
from ..subtitle_rules.chinese_script import SIMPLIFIED, TRADITIONAL
from ..timeline.studio_commands import MutationOrigin, ReplaceCuesCommand

SCRIPT_LABELS = {SIMPLIFIED: '简体中文', TRADITIONAL: '繁体中文'}
SHORT_LABELS = {SIMPLIFIED: '简体', TRADITIONAL: '繁体'}
_MISSING = object()


@dataclass(frozen=True)
class ScriptChange:
    cue_id: str
    before: str
    after: str
    original_before: str
    original_after: str


def is_chinese_project(project) -> bool:
    """Chinese subtitles: the recorded language is Chinese, or older projects without one."""
    from ..subtitle_rules.language_rules import project_language
    return project is not None and project_language(project) in ('', 'zh')


def _convertible(text: str) -> bool:
    return not any('぀' <= ch <= 'ヿ' or 'ㇰ' <= ch <= 'ㇿ' or '가' <= ch <= '힣'
                   for ch in text)


def _converted(text: str, script: str) -> str:
    if not text or not _convertible(text):
        return text
    value = chinese_script.convert_text(text, script)
    return value if len(value) == len(text) else text


def plan_conversion(project, script: str, cue_ids=None, *, layer='original') -> list[ScriptChange]:
    """Every cue whose text or 原文 changes when written in ``script``."""
    changes = []
    ids = None if cue_ids is None else set(cue_ids)
    if layer == 'translation':
        from ..subtitle_rules.subtitle_translation import records_of
        records = records_of(project)
        rendered = project.generation_metadata.get('translations', {})
        for cue in project.cues:
            if ids is not None and cue.id not in ids:
                continue
            record = records.get(cue.id) or {}
            text = str(record.get('text') or rendered.get(cue.id) or '')
            target = str(record.get('target') or '')
            if target and not target.startswith('zh'):
                continue
            after = _converted(text, script)
            if text != after:
                changes.append(ScriptChange(cue.id, text, after, '', ''))
        return changes
    if not is_chinese_project(project):
        return changes
    for cue in project.cues:
        if ids is not None and cue.id not in ids:
            continue
        after = _converted(cue.text, script)
        original = str(cue.original_text or '')
        original_after = _converted(original, script)
        if after != cue.text or original_after != original:
            changes.append(ScriptChange(cue.id, cue.text, after, original, original_after))
    return changes


def _word_text(word_text: str, before: str, after: str, script: str) -> str:
    """A word's text once the cue piece it covers changed from ``before`` to ``after`` (same length)."""
    from ..recognition.cue_word_alignment import normalized_content
    if normalized_content(before, fold=False) == word_text:
        return normalized_content(after, fold=False)
    return _converted(word_text, script)


def _receipt_after(receipt: dict, change: ScriptChange, script: str) -> dict:
    moved = copy.deepcopy(receipt)
    for key in ('words', 'word_base_words'):
        for word in moved.get(key) or ():
            try:
                start, end = int(word['char_start']), int(word['char_end'])
                word['text'] = _word_text(str(word.get('text', '')), change.before[start:end],
                                          change.after[start:end], script)
            except (KeyError, TypeError, ValueError):
                word['text'] = _converted(str(word.get('text', '')), script)
    moved['text'] = change.after
    return moved


def _override_after(override: dict, change: ScriptChange, script: str) -> dict:
    """Term word overrides carry no indexes: their words follow the cue's content characters in order."""
    from ..recognition.cue_word_alignment import content_positions, normalized_content
    moved = copy.deepcopy(override)
    positions = [index for index, _char in content_positions(change.before, fold=False)]
    offset = 0
    for word in moved.get('words') or ():
        text = str(word.get('text', ''))
        size = len(normalized_content(text, fold=False))
        covered = list(dict.fromkeys(positions[offset:offset + size]))
        before = ''.join(change.before[index] for index in covered)
        if covered and normalized_content(before, fold=False) == normalized_content(text, fold=False):
            word['text'] = ''.join(change.after[index] for index in covered)
        else:
            word['text'] = _converted(text, script)
        offset += size
    moved['text'] = change.after
    return moved


def _word_state(project, changes, script):
    from ..timeline.studio_caption_timeline import KEY
    receipts = (project.studio_state.get(KEY) or {}).get('instances', {}) or {}
    overrides = project.studio_state.get('term_word_overrides', {}) or {}
    before = {'instances': {}, 'overrides': {}}
    after = {'instances': {}, 'overrides': {}}
    for change in changes:
        receipt = receipts.get(change.cue_id)
        if isinstance(receipt, dict) and receipt.get('text') == change.before and change.after != change.before:
            before['instances'][change.cue_id] = copy.deepcopy(receipt)
            after['instances'][change.cue_id] = _receipt_after(receipt, change, script)
        override = overrides.get(change.cue_id)
        if isinstance(override, dict) and override.get('text') == change.before and change.after != change.before:
            before['overrides'][change.cue_id] = copy.deepcopy(override)
            after['overrides'][change.cue_id] = _override_after(override, change, script)
    return before, after


def _translation_state(project, changes):
    """Translations made from the old text stay current: only the script of their source changed."""
    from ..subtitle_rules.subtitle_translation import records_of, source_sha
    records = records_of(project)
    before, after = {}, {}
    for change in changes:
        record = records.get(change.cue_id)
        if (isinstance(record, dict) and change.after != change.before
                and str(record.get('source_sha') or '') == source_sha(change.before)):
            before[change.cue_id] = copy.deepcopy(record)
            after[change.cue_id] = {**copy.deepcopy(record), 'source_text': change.after,
                                    'source_sha': source_sha(change.after)}
    return before, after


class ConvertChineseScriptCommand(ReplaceCuesCommand):
    """The project's subtitles written in 简体 or 繁體: exactly one undo step."""

    def __init__(self, project, script: str, changes=None, changed=None, *, set_project_script=True):
        script = chinese_script.normalize_script(script)
        changes = plan_conversion(project, script) if changes is None else list(changes)
        by_id = {change.cue_id: change for change in changes}
        cues = []
        for cue in project.cues:
            change = by_id.get(cue.id)
            if change is not None:
                cue = copy.deepcopy(cue)
                cue.text, cue.original_text = change.after, change.original_after
            cues.append(cue)
        super().__init__(project, cues, tr('字幕转为{value}（{count} 条）', value=tr(SCRIPT_LABELS[script]),
                                           count=len(changes)), changed, MutationOrigin.SYSTEM)
        self.script = script
        self.changes = tuple(changes)
        metadata = project.generation_metadata
        language = metadata.get('language', _MISSING) if isinstance(metadata, dict) else _MISSING
        self._language_before = language if language is _MISSING else copy.deepcopy(language)
        self._language_after = {**(language if isinstance(language, dict) else {}), 'script': script}
        if not set_project_script:
            self._language_after = self._language_before
        self._words_before, self._words_after = _word_state(project, changes, script)
        self._records_before, self._records_after = _translation_state(project, changes)

    def _mutate(self, cues) -> None:
        super()._mutate(cues)
        redo = cues is self.after
        metadata = self.project.generation_metadata
        language = self._language_after if redo else self._language_before
        if language is _MISSING:
            metadata.pop('language', None)
        else:
            metadata['language'] = copy.deepcopy(language)
        from ..timeline.studio_commands import _restore_word_state
        _restore_word_state(self.project, self._words_after if redo else self._words_before)
        records = self._records_after if redo else self._records_before
        if records:
            from ..subtitle_rules.subtitle_translation import records_of
            live = records_of(self.project)
            for cue_id, record in records.items():
                live[cue_id] = copy.deepcopy(record)


def convert_project(page, script: str, *, layer='original', cue_ids=None) -> bool:
    """Push the conversion for the open project (no dialog): True when something changed."""
    project = getattr(page, 'project', None)
    if project is None or not chinese_script.available(script):
        return False
    changes = plan_conversion(project, script, cue_ids, layer=layer)
    if layer == 'translation':
        if not changes:
            return False
        from types import SimpleNamespace
        from ..subtitle_rules import subtitle_translation as st
        from .studio_bilingual import ApplyTranslationSnapshotCommand
        before = st.snapshot(project)
        shadow = SimpleNamespace(generation_metadata=copy.deepcopy(before), cues=project.cues)
        st.migrate(shadow)
        records = st.records_of(shadow)
        by_id = {cue.id: cue for cue in project.cues}
        for change in changes:
            record = records[change.cue_id]
            record.setdefault('previous', []).append({**copy.deepcopy(record), 'previous': []})
            record.update(text=change.after, origin='manual', status=st.MANUAL,
                          source_text=by_id[change.cue_id].text,
                          source_sha=st.source_sha(by_id[change.cue_id].text), display_script=script)
        st._rebuild_view(shadow)
        page.undo_stack.push(ApplyTranslationSnapshotCommand(project, before, st.snapshot(shadow),
            [change.cue_id for change in changes], label='中文译文简繁转换'))
    else:
        if not is_chinese_project(project):
            return False
        if not changes and (cue_ids is not None or chinese_script.project_script(project) == script):
            return False
        page.undo_stack.push(ConvertChineseScriptCommand(project, script, changes, set_project_script=cue_ids is None))
    sync_controls(page)
    refresh = getattr(page, '_refresh_ass_preview', None)
    if callable(refresh):
        refresh()
    return True


# ---------------------------------------------------------------- UI

def build_menu(page, menu) -> None:
    from PySide6.QtGui import QAction, QActionGroup
    group = QActionGroup(menu)
    group.setExclusive(True)
    page.chinese_script_actions = {}
    for script in (SIMPLIFIED, TRADITIONAL):
        # The current script is ticked; choosing the other one previews the conversion.
        action = QAction(tr(SCRIPT_LABELS[script]), menu)
        action.setObjectName('studioChineseScript_' + script)
        action.setCheckable(True)
        action.triggered.connect(lambda _checked=False, value=script: open_convert_dialog(page, value))
        group.addAction(action)
        menu.addAction(action)
        page.chinese_script_actions[script] = action
    menu.addSeparator()
    note = QAction(tr('只换字形，不改用词；时间、说话人和字词时间不变'), menu)
    note.setEnabled(False)
    menu.addAction(note)
    stack = getattr(page, 'undo_stack', None)
    if stack is not None:
        # Undo/redo of a conversion (and project reloads) keep the label right.
        stack.indexChanged.connect(lambda _index: sync_controls(page))
    sync_controls(page)


def _has_chinese_translation(project):
    if project is None:
        return False
    from ..subtitle_rules.subtitle_translation import records_of
    records = records_of(project)
    view = project.generation_metadata.get('translations', {}) or {}
    for cue in project.cues:
        record = records.get(cue.id) or {}
        text = str(record.get('text') or view.get(cue.id) or '')
        target = str(record.get('target') or '')
        if (not target or target.startswith('zh')) and _convertible(text) and any('一' <= c <= '鿿' for c in text):
            return True
    return False


def sync_controls(page) -> None:
    from shiboken6 import isValid
    project = getattr(page, 'project', None)
    chinese = is_chinese_project(project)
    usable = bool(project and (chinese or _has_chinese_translation(project)))
    script = chinese_script.project_script(project) if chinese else SIMPLIFIED
    for value, action in (getattr(page, 'chinese_script_actions', None) or {}).items():
        if not isValid(action):
            continue
        action.setChecked(chinese and value == script)
        action.setEnabled(usable and chinese_script.available(value))
    menu = getattr(page, 'chinese_script_menu', None)
    if menu is not None and isValid(menu):
        # The 双语 / 翻译 submenu (2026-10-22): reachable whenever a project is open.
        menu.menuAction().setEnabled(project is not None)
    button = getattr(page, 'chinese_script_button', None)
    if button is not None and isValid(button):
        # Keep the entry discoverable; an empty project explains why no content qualifies.
        button.setEnabled(project is not None)
        button.setText(tr('字幕简繁转换'))
        button.setToolTip(tr('选择中文原文或中文译文，以及选取字幕或整个工程；可撤销，时间不变') if usable
                          else tr('当前没有可转换的中文原文或中文译文'))


def open_convert_dialog(page, script: str) -> bool:
    """Preview the chosen text layer and scope before a single undoable command."""
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget, QComboBox
    from ..projects.studio_runtime_state import state_for
    project = getattr(page, 'project', None)
    if project is None or not chinese_script.available(script):
        return False
    revision = state_for(project).revision
    window = page.window() if callable(getattr(page, 'window', None)) else None
    dialog = QDialog(window or (page if isinstance(page, QWidget) else None))
    dialog.setObjectName('chineseScriptDialog')
    dialog.setWindowTitle(tr('字幕简繁转换'))
    dialog.resize(700, 560)
    layout = QVBoxLayout(dialog)
    layer = QComboBox(dialog); layer.setObjectName('chineseScriptLayer')
    if is_chinese_project(project):
        layer.addItem(tr('中文原文'), 'original')
    if _has_chinese_translation(project):
        layer.addItem(tr('中文译文'), 'translation')
    layout.addWidget(layer)
    selection = list(page.selected_cue_ids()) if callable(getattr(page, 'selected_cue_ids', None)) else []
    scope = QComboBox(dialog); scope.setObjectName('chineseScriptScope')
    if selection:
        scope.addItem(tr('选取字幕（{count} 条）', count=len(selection)), 'selected')
    scope.addItem(tr('整个工程'), 'all')
    layout.addWidget(scope)
    summary = QLabel(); summary.setObjectName('chineseScriptSummary'); summary.setWordWrap(True)
    layout.addWidget(summary)
    listing = QPlainTextEdit(dialog); listing.setObjectName('chineseScriptPreview'); listing.setReadOnly(True)
    layout.addWidget(listing, 1)
    note = QLabel(tr('只换中文的字形，不改日文原文、用词和时间。按本机 OpenCC 词表转换，可用 Ctrl+Z 一步恢复。'))
    note.setWordWrap(True); layout.addWidget(note)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
    box.button(QDialogButtonBox.Ok).setText(tr('转为{value}', value=tr(SCRIPT_LABELS[script])))
    box.accepted.connect(dialog.accept); box.rejected.connect(dialog.reject); layout.addWidget(box)
    def refresh():
        ids = selection if scope.currentData() == 'selected' else None
        changes = plan_conversion(project, script, ids, layer=layer.currentData()) if layer.count() else []
        summary.setText(tr('将转换 {count} 条{layer}为{value}；时间与说话人不变。', count=len(changes),
            layer=layer.currentText(), value=tr(SCRIPT_LABELS[script])) if layer.count()
            else tr('当前没有可转换的中文原文或中文译文。'))
        listing.setPlainText('\n'.join(f'{c.before}\n→ {c.after}\n' for c in changes[:300]))
        box.button(QDialogButtonBox.Ok).setEnabled(bool(changes) or (layer.currentData() == 'original'
            and ids is None and chinese_script.project_script(project) != script))
    layer.currentIndexChanged.connect(refresh); scope.currentIndexChanged.connect(refresh); refresh()
    try:
        accepted = dialog.exec() == QDialog.Accepted
        if not accepted or page.project is not project or state_for(project).revision != revision:
            return False
        return convert_project(page, script, layer=layer.currentData(),
                               cue_ids=selection if scope.currentData() == 'selected' else None)
    finally:
        sync_controls(page)
        dialog.deleteLater()


__all__ = ['ConvertChineseScriptCommand', 'ScriptChange', 'build_menu', 'convert_project', 'is_chinese_project',
           'open_convert_dialog', 'plan_conversion', 'sync_controls']
