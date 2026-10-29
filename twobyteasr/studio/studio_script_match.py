"""Studio 「匹配文稿」 (2026-10-14).

The user pastes a complete script that is already broken into subtitle lines.
Every line becomes one caption, timed only by the word timestamps this
project already has (see ``script_match``); no model, AI or network call is
made. The replacement is one undo step that also carries each new caption's
word receipt, so word timing, razor cuts and review keep working. Lines that
could not be heard are placed between their neighbours and marked 待检查.
"""
from __future__ import annotations

from collections import Counter
import copy
from dataclasses import asdict
from pathlib import Path
import uuid

from ..i18n import tr
from ..recognition.script_match import ScriptMatch, ScriptMatchError, match_script, parse_script, tokens_from_project
from ..timeline.studio_commands import MutationOrigin, ReplaceCuesCommand

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


def open_script_match_dialog(page) -> bool:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                                   QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                                   QVBoxLayout)
    from ..design.presentation import button_role
    project = getattr(page, 'project', None)
    if project is None:
        return False
    dialog = QDialog(page.window() or page)
    dialog.setObjectName('scriptMatchDialog')
    dialog.setWindowTitle(tr('匹配文稿'))
    dialog.resize(940, 660)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 18, 20, 16)
    layout.setSpacing(10)
    intro = QLabel(tr('粘贴已断好句的完整文稿，每行一条字幕。只用工程里已有的字级时间对齐，'
                      '不调用识别模型或 AI；文字保持你输入的样子。'))
    intro.setWordWrap(True)
    layout.addWidget(intro)
    split = QSplitter(Qt.Orientation.Horizontal, dialog)
    left = QPlainTextEdit(split)
    left.setObjectName('scriptMatchInput')
    left.setPlaceholderText(tr('每行一条字幕，例如：\n大家好，欢迎回来\n今天我们继续打洛克王国'))
    table = QTableWidget(0, 4, split)
    table.setObjectName('scriptMatchPreview')
    table.setHorizontalHeaderLabels([tr('开始'), tr('结束'), tr('文稿'), tr('匹配')])
    table.verticalHeader().hide()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    split.setSizes([380, 520])
    layout.addWidget(split, 1)
    summary = QLabel(tr('贴上文稿后点「匹配预览」。'))
    summary.setObjectName('scriptMatchSummary')
    summary.setWordWrap(True)
    layout.addWidget(summary)
    actions = QHBoxLayout()
    load = button_role(QPushButton(tr('从文件读取…')), 'secondary')
    preview = button_role(QPushButton(tr('匹配预览')), 'secondary')
    apply = button_role(QPushButton(tr('替换全部字幕')), 'primary')
    cancel = button_role(QPushButton(tr('取消')), 'secondary')
    apply.setEnabled(False)
    actions.addWidget(load)
    actions.addStretch(1)
    actions.addWidget(preview)
    actions.addWidget(cancel)
    actions.addWidget(apply)
    layout.addLayout(actions)
    state = {'match': None, 'text': None}

    def load_file():
        path, _ = QFileDialog.getOpenFileName(dialog, tr('选择文稿'), '', tr('文本文件 (*.txt);;所有文件 (*)'))
        if path:
            try:
                left.setPlainText(read_script_file(path))
            except (OSError, ValueError) as exc:
                summary.setText(str(exc))

    def run_preview():
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text = left.toPlainText()
            _lines, match = match_project(project, text)
        except ScriptMatchError as exc:
            state['match'] = None
            apply.setEnabled(False)
            table.setRowCount(0)
            summary.setText(str(exc))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        state['match'], state['text'] = match, text
        table.setRowCount(len(match.lines))
        for row, line in enumerate(match.lines):
            values = (_format_ms(line.start_ms), _format_ms(line.end_ms), line.text, line_status(line))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3 and line.needs_review:
                    font = item.font(); font.setBold(True); item.setFont(font)
                table.setItem(row, column, item)
        summary.setText(tr('共 {count} 句；文稿 {coverage}% 的字对上了字级时间；{review} 句标为待检查。'
                           '替换后可用 Ctrl+Z 一步恢复。', count=len(match.lines),
                           coverage=round(match.coverage * 100), review=match.review_count))
        apply.setEnabled(True)

    def accept():
        if state['match'] is None or state['text'] != left.toPlainText():
            run_preview()
            if state['match'] is None:
                return
        apply_match(page, state['match'])
        dialog.accept()

    left.textChanged.connect(lambda: apply.setEnabled(False) if state['text'] != left.toPlainText() else None)
    load.clicked.connect(load_file)
    preview.clicked.connect(run_preview)
    cancel.clicked.connect(dialog.reject)
    apply.clicked.connect(accept)
    dialog._run_preview = run_preview  # automated checks drive the real buttons' handlers
    dialog._accept_match = accept
    page._script_match_dialog = dialog
    try:
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        page._script_match_dialog = None


__all__ = ['MatchScriptCommand', 'apply_match', 'build_replacement', 'match_project', 'open_script_match_dialog',
           'read_script_file']
