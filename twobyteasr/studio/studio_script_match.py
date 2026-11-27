"""Studio 「匹配文稿」 (2026-10-14; rounded wizard 2026-11-18; reference
correction & glossary capture 2026-11-25).

Supports two explicit modes via a top 2-way segmented bar:
  1. ``整稿替换`` (default, 100% backward compatible):
     The user pastes a complete line-broken script; every line becomes one
     caption timed by the project's word timestamps (``script_match``),
     committed in one undo step (``MatchScriptCommand``).
  2. ``参考纠错``:
     The user pastes an outline, character bio, lyrics, or loose reference
     script. Improvised spoken sentences are NEVER deleted or overwritten.
     Localized homophone/near-homophone fixes (plus optional Text AI check)
     are presented as checkable diffs and applied via a single undoable
     ``BatchReplaceTextCommand``. Both modes feed discovered diff pairs and
     user-highlighted terms into the inline glossary capture strip.
"""
from __future__ import annotations

from collections import Counter
import copy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence
import uuid

from ..design.typography import weighted_font
from ..i18n import tr
from ..recognition.script_match import ScriptMatch, ScriptMatchError, match_script, parse_script, tokens_from_project
from ..recognition.script_reference import (
    ReferenceFix,
    ReferenceMatchResult,
    ai_diff_script_against_cues,
    apply_reference_fixes_to_cues,
    diff_pairs_from_script_match,
    diff_script_against_cues,
)
from ..timeline.studio_commands import BatchReplaceTextCommand, MutationOrigin, ReplaceCuesCommand

REVIEW_REASON = 'script_match_needs_review'


def read_script_file(path) -> str:
    raw = Path(path).read_bytes()
    for encoding in ('utf-8-sig', 'utf-16', 'gb18030'):
        try:
            text = raw.decode(encoding)
        except UnicodeError:
            continue
        if encoding == 'utf-16' and not raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            continue
        return text
    raise ValueError(tr('无法识别文件编码，请另存为 UTF-8 文本'))


def _project_language(project, fallback_lines: Sequence[str] = ()) -> str:
    from ..subtitle_rules.language_rules import detect_language, project_language
    try:
        return project_language(project) or (detect_language(list(fallback_lines))[0] if fallback_lines else '') or 'zh'
    except Exception:
        return 'zh'


def match_project(project, text: str) -> tuple[list[str], ScriptMatch]:
    lines = parse_script(text)
    if not lines:
        raise ScriptMatchError(tr('文稿是空的：每行一条字幕'))
    tokens = tokens_from_project(project)
    if not tokens:
        raise ScriptMatchError(tr('这个工程还没有字级时间：请先识别，或在首页用「匹配文稿」生成'))
    # 2026-10-15: the project's spoken language picks the comparison rules
    # (Japanese kana/kanji, English letters); Chinese keeps homophone anchoring.
    from ..subtitle_rules.language_rules import detect_language, project_language
    try:
        language = project_language(project) or detect_language(lines)[0]
    except Exception:
        language = ''
    return lines, match_script(lines, tokens, language=language)


def reference_diff_project(project, text: str) -> ReferenceMatchResult:
    """Run zero-network localized homophone diffing against ``project.cues``."""
    raw = str(text or '').strip()
    if not raw:
        raise ScriptMatchError(tr('参考文稿是空的'))
    cues = sorted(getattr(project, 'cues', ()), key=lambda c: (c.start_ms, c.end_ms))
    if not cues:
        raise ScriptMatchError(tr('这个工程里还没有字幕'))
    language = _project_language(project, parse_script(raw))
    return diff_script_against_cues(cues, raw, language=language)


def _overlap(cue, start, end) -> int:
    return min(cue.end_ms, end) - max(cue.start_ms, start)


def build_replacement(project, match: ScriptMatch):
    """New cues, their caption receipts and the ids to review."""
    from ..projects.studio_project import StudioCue
    originals = sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms))
    speakers = [speaker.id for speaker in getattr(project, 'speakers', ())]
    fallback_speaker = (Counter(c.speaker_id for c in originals).most_common(1) or [(speakers[0] if speakers else 'S00', 0)])[0][0]
    cues, receipts, review = [], {}, []
    previous_speaker = fallback_speaker
    for line in match.lines:
        overlapping = [c for c in originals if _overlap(c, line.start_ms, line.end_ms) > 0]
        template = (max(overlapping, key=lambda c: _overlap(c, line.start_ms, line.end_ms)) if overlapping else
                    min(originals, key=lambda c: abs(c.start_ms - line.start_ms)) if originals else None)
        speaker = line.speaker or previous_speaker
        if speakers and speaker not in speakers:
            speaker = previous_speaker if previous_speaker in speakers else speakers[0]
        previous_speaker = speaker
        cue = StudioCue(id='script-' + uuid.uuid4().hex[:12], start_ms=line.start_ms, end_ms=line.end_ms,
                        text=line.text, speaker_id=speaker,
                        style_id=template.style_id if template else 'default',
                        base_preset_id=template.base_preset_id if template else '',
                        effect_id=template.effect_id if template else 'none',
                        original_text=line.text,
                        evidence_refs=[ref for ref in line.refs if not ref.startswith('cue-estimate:')])
        cue.validate()
        words = [asdict(word) for word in line.words]
        reason = line.word_reason if words else (line.word_reason or 'missing_word_timestamps')
        receipt = dict(text=line.text, words=words, word_alignment=reason,
                       word_base_interval=[cue.start_ms, cue.end_ms], word_base_words=copy.deepcopy(words),
                       word_base_alignment=reason, word_clock_offset_ms=0,
                       source_cue_ids=[c.id for c in overlapping], evidence_refs=list(cue.evidence_refs),
                       script_match=dict(version=1, placed_by=line.placed_by, coverage=round(line.coverage, 3),
                                         edges_estimated=line.edges_estimated))
        if line.needs_review:
            receipt['needs_review'] = REVIEW_REASON
            review.append(cue.id)
        receipts[cue.id] = receipt
        cues.append(cue)
    return cues, receipts, review


class MatchScriptCommand(ReplaceCuesCommand):
    """All captions replaced by the script in one step, with their word receipts."""

    def __init__(self, project, cues, receipts, review_ids, changed=None):
        super().__init__(project, cues, tr('匹配文稿（{count} 条）', count=len(cues)), changed, MutationOrigin.IMPORT)
        from ..timeline.studio_caption_timeline import KEY
        state = project.studio_state.get(KEY) or {}
        self._key = KEY
        self._receipts_before = copy.deepcopy(state.get('instances', {})) if KEY in project.studio_state else None
        self._receipts_after = copy.deepcopy(receipts)
        self._statuses_before = copy.deepcopy(project.studio_state.get('cue_statuses'))
        self._statuses_after = {cue_id: 'issue' for cue_id in review_ids}
        self._forward = True

    def _mutate(self, cues):
        super()._mutate(cues)
        state = self.project.studio_state
        if self._forward:
            if self._receipts_before is not None:
                instances = state[self._key].setdefault('instances', {})
                for cue_id in [c.id for c in self.before]:
                    instances.pop(cue_id, None)
                instances.update(copy.deepcopy(self._receipts_after))
            statuses = {k: v for k, v in (self._statuses_before or {}).items()
                        if k not in {c.id for c in self.before}}
            statuses.update(self._statuses_after)
            state['cue_statuses'] = statuses
        else:
            if self._receipts_before is not None:
                state[self._key]['instances'] = copy.deepcopy(self._receipts_before)
            if self._statuses_before is None:
                state.pop('cue_statuses', None)
            else:
                state['cue_statuses'] = copy.deepcopy(self._statuses_before)

    def redo(self):
        self._forward = True
        super().redo()

    def undo(self):
        self._forward = False
        super().undo()


def apply_match(page, match: ScriptMatch) -> MatchScriptCommand:
    cues, receipts, review = build_replacement(page.project, match)
    command = MatchScriptCommand(page.project, cues, receipts, review, getattr(page, '_changed', None))
    page.undo_stack.push(command)
    for refresh in ('cue_model', 'timeline'):
        target = getattr(page, refresh, None)
        if target is not None and hasattr(target, 'set_project'):
            target.set_project(page.project)
    if hasattr(page, '_populate_speakers'):
        page._populate_speakers()
    if cues and hasattr(page, 'select_cue'):
        page.select_cue(cues[0].id)
    return command


def apply_reference_fixes(
    page,
    fixes: Sequence[ReferenceFix],
) -> BatchReplaceTextCommand | None:
    """Apply selected localized reference fixes via one undoable
    ``BatchReplaceTextCommand``; timestamps, speakers, styles, and untouched
    improvised captions remain intact."""
    project = getattr(page, 'project', None)
    if project is None or not fixes:
        return None
    values = apply_reference_fixes_to_cues(project.cues, fixes)
    if not values:
        return None
    command = BatchReplaceTextCommand(
        project,
        values,
        needle=tr('参考纠错'),
        changed=getattr(page, '_changed', None),
        origin=MutationOrigin.SEARCH_REPLACE,
    )
    undo_stack = getattr(page, 'undo_stack', None)
    if undo_stack is not None:
        undo_stack.push(command)
    else:
        command.redo()
    for refresh in ('cue_model', 'timeline'):
        target = getattr(page, refresh, None)
        if target is not None and hasattr(target, 'set_project'):
            target.set_project(project)
    return command


def _format_ms(value: int) -> str:
    seconds, ms = divmod(int(value), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}' if hours else f'{minutes:02d}:{seconds:02d}.{ms:03d}'


def line_status(line) -> str:
    if line.placed_by == 'estimated_between_neighbours':
        return tr('未听到 · 按前后估算')
    if line.placed_by == 'estimated_tokens':
        return tr('{value}% · 时间为估算', value=round(line.coverage * 100))
    if line.needs_review:
        return tr('{value}% · 待检查', value=round(line.coverage * 100))
    return tr('{value}%', value=round(line.coverage * 100))


def _snippet_for_fix(text: str, span: tuple[int, int], radius: int = 10) -> str:
    s, e = span
    if not (0 <= s < e <= len(text)):
        return text
    left = max(0, s - radius)
    right = min(len(text), e + radius)
    prefix = '…' if left > 0 else ''
    suffix = '…' if right < len(text) else ''
    return f'{prefix}{text[left:s]}「{text[s:e]}」{text[e:right]}{suffix}'


def _resolve_studio_context(page) -> tuple[Any, list[str], dict[str, Any]]:
    window = page.window() if hasattr(page, 'window') and callable(page.window) else None
    legacy = getattr(page, 'legacy', None) or getattr(window, 'legacy', None)
    preferred: list[str] = []
    project = getattr(page, 'project', None)
    if project is not None:
        preferred.extend(str(i) for i in getattr(project, 'glossary_ids', ()) if str(i).strip())
    if window is not None and callable(getattr(window, '_enabled_glossary_ids', None)):
        try:
            preferred.extend(str(i) for i in window._enabled_glossary_ids() if str(i).strip())
        except Exception:
            pass
    settings = getattr(page, 'runtime_settings', None)
    if not isinstance(settings, dict) and legacy is not None:
        settings = getattr(legacy, 'RUNTIME_SETTINGS', None)
    return legacy, list(dict.fromkeys(preferred)), settings if isinstance(settings, dict) else {}


def _create_ai_worker(cues, reference_text: str, settings: dict[str, Any], language: str, parent=None):
    from PySide6.QtCore import QThread, Signal

    class _AiReferenceWorker(QThread):
        succeeded = Signal(object)
        failed = Signal(str)

        def __init__(self):
            super().__init__(parent)
            self._cues = list(cues)
            self._text = reference_text
            self._settings = copy.deepcopy(settings)
            self._language = language

        def run(self) -> None:
            try:
                result = ai_diff_script_against_cues(
                    self._cues,
                    self._text,
                    self._settings,
                    language=self._language,
                    cancel_check=self.isInterruptionRequested,
                )
            except Exception as exc:
                self.failed.emit(' '.join(str(exc).split())[:260] or type(exc).__name__)
                return
            self.succeeded.emit(result)

    return _AiReferenceWorker()


def open_script_match_dialog(page) -> bool:
    """Studio's 匹配文稿 wizard with ``整稿替换`` | ``参考纠错`` mode toggle
    and inline glossary capture."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QDialog,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QPushButton,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
    from ..app.home_script_match_ui import (
        ModeSegmentBar,
        ScriptEditor,
        TermCapturePanel,
        WizardDialog,
        build_stepper,
        bunny_tip,
        show_step_states,
    )
    from ..design.presentation import button_role
    from ..design.theme_manager import theme_definition, theme_key

    project = getattr(page, 'project', None)
    if project is None:
        return False

    legacy, preferred_ids, runtime_settings = _resolve_studio_context(page)
    state: dict[str, Any] = {
        'mode': 'replace',
        'match': None,
        'text': None,
        'ref_result': None,
        'ref_text': None,
        'ai_worker': None,
    }
    dialog = WizardDialog(
        page.window() or page,
        object_name='scriptMatchDialog',
        title=tr('匹配文稿'),
        busy=lambda: state['ai_worker'] is not None,
        minimum=(640, 580),
        size=(860, 720),
    )
    layout = dialog.body

    mode_row = QHBoxLayout()
    mode_row.setContentsMargins(0, 0, 0, 0)
    mode_bar = ModeSegmentBar(dialog, default_mode='replace')
    mode_row.addWidget(mode_bar)
    mode_row.addStretch(1)
    layout.addLayout(mode_row)

    stepper, badges, names, step_lines = build_stepper(('贴文稿', '核对预览', '替换字幕'))
    layout.addLayout(stepper)
    pages = QStackedWidget()
    pages.setObjectName('scriptWizardPages')
    layout.addWidget(pages, 1)

    # ① 贴文稿
    script_page = QWidget()
    script_page.setObjectName('scriptWizardPage')
    first = QVBoxLayout(script_page)
    first.setContentsMargins(0, 4, 0, 0)
    first.setSpacing(10)
    first_tip_row, first_tip = bunny_tip(
        tr('每行就是一条字幕，<b>换行的地方就是断句的地方</b>。<br>'
           '只用这个工程已有的字级时间对齐，文字我不会改。')
    )
    first.addLayout(first_tip_row)
    editor = ScriptEditor('scriptMatchInput')
    left = editor.input
    first.addWidget(editor, 1)
    runs = QLabel(tr('不调用识别模型或 AI，也不上传；替换全部字幕后可用 Ctrl+Z 一步恢复。'))
    runs.setObjectName('homeScriptMatchRuns')
    runs.setWordWrap(True)
    first.addWidget(runs)
    pages.addWidget(script_page)

    # ② 核对预览（整稿替换表 / 参考纠错勾选表）
    preview_page = QWidget()
    preview_page.setObjectName('scriptWizardPage')
    second = QVBoxLayout(preview_page)
    second.setContentsMargins(0, 4, 0, 0)
    second.setSpacing(10)
    tip_row, summary = bunny_tip('')
    second.addLayout(tip_row)
    frame = QFrame()
    frame.setObjectName('scriptPreviewFrame')
    frame_lines = QVBoxLayout(frame)
    frame_lines.setContentsMargins(10, 8, 10, 10)

    preview_stack = QStackedWidget(frame)
    preview_stack.setObjectName('scriptWizardPages')

    table = QTableWidget(0, 4)
    table.setObjectName('scriptMatchPreview')
    table.setHorizontalHeaderLabels([tr('开始'), tr('结束'), tr('文稿'), tr('匹配')])
    table.verticalHeader().hide()
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setFrameShape(QFrame.Shape.NoFrame)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    preview_stack.addWidget(table)

    ref_table = QTableWidget(0, 5)
    ref_table.setObjectName('scriptMatchPreview')
    ref_table.setHorizontalHeaderLabels([tr('选'), tr('时间'), tr('原字幕片段'), tr('局部修正'), tr('来源')])
    ref_table.verticalHeader().hide()
    ref_table.setShowGrid(False)
    ref_table.setWordWrap(False)
    ref_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    ref_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    ref_table.setFrameShape(QFrame.Shape.NoFrame)
    ref_header = ref_table.horizontalHeader()
    ref_header.setHighlightSections(False)
    ref_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    ref_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    ref_table.setColumnWidth(0, 36)
    ref_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    ref_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    ref_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    ref_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    preview_stack.addWidget(ref_table)

    frame_lines.addWidget(preview_stack)
    second.addWidget(frame, 1)
    pages.addWidget(preview_page)

    term_panel = TermCapturePanel(legacy=legacy, preferred_ids=preferred_ids, parent=dialog)
    layout.addWidget(term_panel)

    status = QLabel('')
    status.setObjectName('homeScriptMatchStatus')
    status.setWordWrap(True)
    status.hide()
    layout.addWidget(status)

    actions = QHBoxLayout()
    actions.setSpacing(10)
    back = button_role(QPushButton(tr('上一步')), 'ghost')
    select_all = button_role(QPushButton(tr('全不选')), 'ghost')
    ai_ref = button_role(QPushButton(tr('AI 参考')), 'secondary')
    ai_ref.setToolTip(tr('用已配置的文字 AI 结合参考资料校对专名与错字，绝不改写即兴口语'))
    cancel = button_role(QPushButton(tr('取消')), 'secondary')
    preview = button_role(QPushButton(tr('匹配预览')), 'primary')
    diff_btn = button_role(QPushButton(tr('比对纠错')), 'primary')
    diff_btn.setToolTip(tr('本机同音比对，挑出与参考稿不符的专名错字，不删改即兴字幕'))
    apply = button_role(QPushButton(tr('替换全部字幕')), 'primary')
    apply_ref = button_role(QPushButton(tr('应用纠错')), 'primary')
    apply_ref.setToolTip(tr('把勾选的局部修正写回字幕，保留所有原时间与即兴句子，可 Ctrl+Z 撤回'))
    for button in (back, select_all, ai_ref, cancel, preview, diff_btn, apply, apply_ref):
        button.setAutoDefault(False)
    actions.addWidget(back)
    actions.addWidget(select_all)
    actions.addWidget(ai_ref)
    actions.addStretch(1)
    actions.addWidget(cancel)
    actions.addWidget(preview)
    actions.addWidget(diff_btn)
    actions.addWidget(apply)
    actions.addWidget(apply_ref)
    layout.addLayout(actions)

    def show_message(text: str):
        status.setText(text)
        status.setVisible(bool(text))

    def checked_reference_fixes() -> list[ReferenceFix]:
        result = state['ref_result']
        if result is None:
            return []
        chosen: list[ReferenceFix] = []
        for row_idx, fix in enumerate(result.fixes):
            item = ref_table.item(row_idx, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                chosen.append(fix)
        return chosen

    def update_ref_apply_state(*_args):
        if state['mode'] != 'reference' or pages.currentIndex() != 1:
            return
        total = ref_table.rowCount()
        checked = len(checked_reference_fixes())
        apply_ref.setEnabled(checked > 0 and state['ai_worker'] is None)
        select_all.setVisible(total > 0)
        select_all.setText(tr('全不选') if checked == total and total > 0 else tr('全选'))

    def toggle_select_all():
        total = ref_table.rowCount()
        if total == 0:
            return
        all_checked = len(checked_reference_fixes()) == total
        target_state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        ref_table.blockSignals(True)
        for row_idx in range(total):
            item = ref_table.item(row_idx, 0)
            if item is not None:
                item.setCheckState(target_state)
        ref_table.blockSignals(False)
        update_ref_apply_state()

    def sync_mode_copy():
        is_ref = state['mode'] == 'reference'
        editor.set_mode(state['mode'])
        names[2].setText(tr('应用纠错') if is_ref else tr('替换字幕'))
        if is_ref:
            first_tip.setText(
                tr('贴入提纲、角色设定或参考稿，只挑出<b>同音错字与专名</b>，不删改即兴口播。<br>'
                   '在框里划选词点「指定词条」，可顺手加入词库。')
            )
            runs.setText(tr('本机同音比对不联网；可选「AI 参考」做语义校对；应用后可 Ctrl+Z 一步撤回。'))
        else:
            first_tip.setText(
                tr('每行就是一条字幕，<b>换行的地方就是断句的地方</b>。<br>'
                   '只用这个工程已有的字级时间对齐，文字我不会改。')
            )
            runs.setText(tr('不调用识别模型或 AI，也不上传；替换全部字幕后可用 Ctrl+Z 一步恢复。'))

    def go(index: int):
        is_ref = state['mode'] == 'reference'
        busy = state['ai_worker'] is not None
        pages.setCurrentIndex(index)
        preview_stack.setCurrentIndex(1 if is_ref else 0)
        show_step_states(
            badges,
            names,
            step_lines,
            ('done', 'current', 'todo') if index == 1 else ('current', 'todo', 'todo'),
        )
        back.setVisible(index == 1)
        back.setEnabled(not busy)
        ai_ref.setVisible(is_ref)
        ai_ref.setEnabled(not busy)
        preview.setVisible(index == 0 and not is_ref)
        diff_btn.setVisible(index == 0 and is_ref)
        diff_btn.setEnabled(not busy)
        apply.setVisible(index == 1 and not is_ref)
        apply.setEnabled(index == 1 and not is_ref and state['match'] is not None)
        apply_ref.setVisible(index == 1 and is_ref)
        select_all.setVisible(index == 1 and is_ref and ref_table.rowCount() > 0)
        cancel.setEnabled(not busy)
        if index == 1 and is_ref:
            update_ref_apply_state()
        if index == 0:
            left.setFocus()

    def set_mode(mode: str):
        normalized = 'reference' if mode == 'reference' else 'replace'
        state['mode'] = normalized
        mode_bar.set_mode(normalized)
        sync_mode_copy()
        show_message('')
        go(0)

    def load_file():
        path, _ = QFileDialog.getOpenFileName(dialog, tr('选择文稿'), '', tr('文本文件 (*.txt);;所有文件 (*)'))
        if path:
            try:
                left.setPlainText(read_script_file(path))
            except (OSError, ValueError) as exc:
                show_message(str(exc))

    def populate_reference_preview(result: ReferenceMatchResult, text: str):
        state['ref_result'] = result
        state['ref_text'] = text
        cue_map = {c.id: c for c in project.cues}
        accent_ink = QColor(theme_definition(theme_key()).accent)
        ref_table.blockSignals(True)
        ref_table.setRowCount(len(result.fixes))
        for row_idx, fix in enumerate(result.fixes):
            cue = cue_map.get(fix.cue_id)
            start_label = _format_ms(cue.start_ms) if cue is not None else ''
            cue_text = cue.text if cue is not None else fix.heard
            snippet = _snippet_for_fix(cue_text, fix.span)

            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check_item.setCheckState(Qt.CheckState.Checked)
            ref_table.setItem(row_idx, 0, check_item)

            time_item = QTableWidgetItem(start_label)
            ref_table.setItem(row_idx, 1, time_item)

            snippet_item = QTableWidgetItem(snippet)
            snippet_item.setToolTip(cue_text)
            ref_table.setItem(row_idx, 2, snippet_item)

            diff_item = QTableWidgetItem(f'{fix.heard} → {fix.reference}')
            font = diff_item.font()
            weighted_font(font, 700)
            diff_item.setFont(font)
            diff_item.setForeground(accent_ink)
            ref_table.setItem(row_idx, 3, diff_item)

            src_tag = tr('AI') if fix.source == 'ai' else tr('同音')
            src_item = QTableWidgetItem(src_tag)
            src_item.setToolTip(f'{fix.reason}（{round(fix.confidence * 100)}%）' if fix.reason else f'{round(fix.confidence * 100)}%')
            ref_table.setItem(row_idx, 4, src_item)
        ref_table.blockSignals(False)

        if result.term_candidates:
            term_panel.merge_term_candidates(result.term_candidates)

        affected_cues = len({f.cue_id for f in result.fixes})
        untouched = max(0, len(project.cues) - affected_cues)
        if result.fixes:
            summary.setText(
                tr('找到 <b>{fixes}</b> 处可修正（涉及 {cues} 句），其余 {untouched} 句即兴口播保持不动。'
                   '应用后可 Ctrl+Z 一步撤回。',
                   fixes=len(result.fixes), cues=affected_cues, untouched=untouched)
            )
        else:
            summary.setText(
                tr('未检出同音专名错字，其余 {untouched} 句保持不动。可点「AI 参考」再做语义核对，或直接划词加入词库。',
                   untouched=len(project.cues))
            )
        show_message('')
        go(1)

    def run_preview():
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text = left.toPlainText()
            _lines, match = match_project(project, text)
            pairs = diff_pairs_from_script_match(project.cues, match, language=_project_language(project, _lines))
        except ScriptMatchError as exc:
            state['match'] = None
            table.setRowCount(0)
            go(0)
            show_message(str(exc))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        state['match'], state['text'] = match, text
        review_ink = QColor(theme_definition(theme_key()).warning)
        table.setRowCount(len(match.lines))
        for row, line in enumerate(match.lines):
            values = (_format_ms(line.start_ms), _format_ms(line.end_ms), line.text, line_status(line))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3 and line.needs_review:
                    font = item.font()
                    weighted_font(font, 700)
                    item.setFont(font)
                    item.setForeground(review_ink)
                table.setItem(row, column, item)
        if pairs:
            term_panel.merge_term_candidates(pairs)
        summary.setText(
            tr('共 {count} 句；文稿 {coverage}% 的字对上了字级时间；{review} 句标为待检查。'
               '替换后可用 Ctrl+Z 一步恢复。',
               count=len(match.lines), coverage=round(match.coverage * 100), review=match.review_count)
        )
        show_message('')
        go(1)

    def run_reference_diff():
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text = left.toPlainText()
            result = reference_diff_project(project, text)
        except ScriptMatchError as exc:
            state['ref_result'] = None
            ref_table.setRowCount(0)
            go(0)
            show_message(str(exc))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        populate_reference_preview(result, text)

    def run_ai_reference():
        if state['ai_worker'] is not None:
            return
        text = left.toPlainText().strip()
        if not text:
            show_message(tr('请先贴入参考文稿或资料'))
            return
        cues = sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms))
        if not cues:
            show_message(tr('这个工程里还没有字幕'))
            return
        language = _project_language(project, parse_script(text))
        worker = _create_ai_worker(cues, text, runtime_settings, language, dialog)
        state['ai_worker'] = worker
        show_message(tr('正在调用文字 AI 对照参考资料校对专名…'))
        go(pages.currentIndex())

        def on_ok(result: ReferenceMatchResult):
            state['ai_worker'] = None
            populate_reference_preview(result, left.toPlainText())

        def on_fail(reason: str):
            state['ai_worker'] = None
            show_message(tr('AI 参考校对未完成：{reason}', reason=reason))
            go(pages.currentIndex())

        worker.succeeded.connect(on_ok)
        worker.failed.connect(on_fail)
        worker.start()

    def accept():
        if state['match'] is None or state['text'] != left.toPlainText():
            run_preview()
            if state['match'] is None:
                return
        apply_match(page, state['match'])
        dialog.accept()

    def accept_reference():
        fixes = checked_reference_fixes()
        if not fixes:
            show_message(tr('请至少勾选 1 处需要应用的修正'))
            return
        apply_reference_fixes(page, fixes)
        dialog.accept()

    def text_changed():
        show_message('')
        current = left.toPlainText()
        if state['text'] != current:
            state['match'] = None
        if state['ref_text'] != current:
            state['ref_result'] = None

    mode_bar.mode_changed.connect(set_mode)
    editor.term_picked.connect(term_panel.add_selected_word)
    left.textChanged.connect(text_changed)
    editor.load.clicked.connect(load_file)
    ref_table.itemChanged.connect(update_ref_apply_state)
    back.clicked.connect(lambda: go(0))
    select_all.clicked.connect(toggle_select_all)
    ai_ref.clicked.connect(run_ai_reference)
    preview.clicked.connect(run_preview)
    diff_btn.clicked.connect(run_reference_diff)
    cancel.clicked.connect(dialog.reject)
    apply.clicked.connect(accept)
    apply_ref.clicked.connect(accept_reference)

    dialog.finish()
    sync_mode_copy()
    go(0)

    # Automated check handles (keep all legacy hooks intact)
    dialog._run_preview = run_preview
    dialog._accept_match = accept
    dialog._pages = pages
    dialog._status = status
    dialog._mode_bar = mode_bar
    dialog._set_mode = set_mode
    dialog._run_reference_diff = run_reference_diff
    dialog._run_ai_reference = run_ai_reference
    dialog._accept_reference = accept_reference
    dialog._term_panel = term_panel
    dialog._editor = editor
    dialog._ref_table = ref_table
    dialog._state = state
    page._script_match_dialog = dialog
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        worker = state.get('ai_worker')
        if worker is not None:
            worker.requestInterruption()
            worker.wait(3000)
        page._script_match_dialog = None


__all__ = [
    'MatchScriptCommand',
    'apply_match',
    'apply_reference_fixes',
    'build_replacement',
    'line_status',
    'match_project',
    'open_script_match_dialog',
    'read_script_file',
    'reference_diff_project',
]
