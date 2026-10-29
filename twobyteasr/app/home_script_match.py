"""首页「匹配文稿」 (2026-10-14): new media plus the user's own script.

The user already has the complete text, broken into subtitle lines. Only the
character-timestamp model runs: the local FireRedASR2-AED worker reports the
characters it hears with their times, ``script_match`` places the user's lines
on those times, and the result opens in Studio. MOSS, Qwen3-ASR review, AI
proofreading and AI line breaking never run, and nothing is uploaded. The
heard characters are kept as the project's word evidence, so Studio's word
timing and razor cuts work on the new captions as usual.

2026-10-15 (user: match scripts in other languages, not only Chinese):
FireRed only hears Chinese (and English inside Chinese speech). A Japanese or
English script is timed by the local Qwen3-ASR 1.7B (it writes down what it
hears, in that language) plus Qwen3-ForcedAligner 0.6B (word / character
times of that text); the user's lines are then placed on those times exactly
as for Chinese. The language is picked in the dialog or read from the script.
"""
from __future__ import annotations

from pathlib import Path
import re
from types import SimpleNamespace
import uuid

from PySide6.QtCore import QThread, Signal

from ..i18n import tr
from ..recognition.script_match import ScriptMatch, ScriptMatchError, Token, match_script, parse_script

TIMESTAMP_MODEL = 'FireRedASR2-AED'
MODEL_KEY = 'firered_aed'
QWEN_ASR_MODEL = 'Qwen3-ASR 1.7B'
QWEN_ALIGNER_MODEL = 'Qwen3-ForcedAligner 0.6B'
# Recognition languages other than Chinese go the Qwen route.
QWEN_MODEL_KEYS = (('qwen_asr', QWEN_ASR_MODEL), ('qwen_aligner', QWEN_ALIGNER_MODEL))


def uses_qwen(language: str) -> bool:
    return str(language or 'zh') not in ('', 'zh')


def script_language(lines, chosen: str = '') -> str:
    """The chosen language, else the one the script is written in (zh when unsure)."""
    if chosen:
        return chosen
    from ..subtitle_rules.language_rules import detect_language
    try:
        return detect_language(list(lines))[0] or 'zh'
    except Exception:
        return 'zh'


def timestamp_model_ready(language: str = 'zh') -> tuple[bool, str]:
    """Are the timestamp models for this language installed with their runtime?"""
    try:
        from ..local_models.model_registry import installed_model_keys
        from ..runtime_paths import get_runtime_paths
        installed = installed_model_keys(get_runtime_paths().install_root)
        if uses_qwen(language):
            missing = [name for key, name in QWEN_MODEL_KEYS if key not in installed]
            if missing:
                return False, tr('需要先在模型工坊安装 {model}（日语、英语文稿用它听写并生成字词时间）',
                                 model='、'.join(missing))
            model = QWEN_ASR_MODEL
        else:
            if MODEL_KEY not in installed:
                return False, tr('需要先在模型工坊安装 {model}（提供字级时间）', model=TIMESTAMP_MODEL)
            model = TIMESTAMP_MODEL
        from ..recognition.asr import _main_worker_python
        runtime = _main_worker_python()
        if not runtime or not Path(runtime).is_file():
            return False, tr('模型运行环境还没准备好，请在模型工坊准备 {model}', model=model)
    except Exception as exc:  # any probe failure reads as "not ready", with the reason
        return False, str(exc)
    return True, ''


def _speech_regions(audio):
    """Energy-VAD regions (seconds) and the same in milliseconds."""
    try:
        import moss_firered_pipeline
        regions = moss_firered_pipeline.detect_lightweight_vad(audio, SimpleNamespace(AUDIO_SAMPLE_RATE=16000))
    except Exception:  # no usable regions: lines keep the model's own edges
        return [], []
    return regions, [(round(r['start'] * 1000), round(r['end'] * 1000)) for r in regions]


def _qwen_heard_tokens(audio, regions, language: str, progress=None):
    """Qwen3-ASR's text per speech window, timed by Qwen3-ForcedAligner."""
    from ..recognition.asr import (_transcribe_qwen_worker, build_qwen_asr_chunks, resolve_qwen_asr_local_source,
                                   transcribe_qwen_aligner_reference)
    from ..subtitle_rules.language_rules import language_scope, qwen_language_name
    model_path = resolve_qwen_asr_local_source()
    if not model_path:
        raise ScriptMatchError(tr('需要先在模型工坊安装 {model}（日语、英语文稿用它听写并生成字词时间）',
                                  model=QWEN_ASR_MODEL))
    chunks = build_qwen_asr_chunks(audio, [{'start': r['start'], 'end': r['end']} for r in regions], 16000)
    if not chunks:
        raise ScriptMatchError(tr('素材里没有可用的音频'))
    if progress:
        progress(tr('{model} 正在听写（只用来对时间，不改你的文稿）…', model=QWEN_ASR_MODEL))
    with language_scope(language):
        heard = _transcribe_qwen_worker(audio, chunks, model_path, context='', evidence_root='')
        if progress:
            progress(tr('{model} 正在生成字词时间…', model=QWEN_ALIGNER_MODEL))
        aligned = transcribe_qwen_aligner_reference(
            audio, [dict(start=row['start'], end=row['end'], text=row['text'], speaker='S00') for row in heard],
            language=qwen_language_name(language), raise_errors=True)
    tokens: list[Token] = []
    rows: dict[str, dict] = {}
    refs: dict[str, str] = {}
    for piece in aligned:
        start, end = round(float(piece['start']) * 1000), round(float(piece['end']) * 1000)
        text = str(piece.get('text') or '')
        if end <= start or not text.strip():
            continue
        key = str(piece.get('alignment_key') or piece.get('alignment_job') or '')
        ref = refs.setdefault(key, f'qwen-aligned:{len(refs) + 1}')
        measured = piece.get('start_basis') == 'model' and piece.get('end_basis') == 'model'
        tokens.append(Token(start, end, text, ref, 'S00', not measured))
        row = rows.setdefault(ref, {'text': '', 'words': [], 'final_timing_owner': QWEN_ALIGNER_MODEL,
                                    'source': 'script_match', 'text_source': QWEN_ASR_MODEL})
        if measured:
            row['words'].append({'text': text, 'start_ms': start, 'end_ms': end})
        row['text'] += text if not row['text'] or language in ('zh', 'ja', '') else ' ' + text
    for row in rows.values():
        if row['words']:
            row['start_ms'], row['end_ms'] = row['words'][0]['start_ms'], row['words'][-1]['end_ms']
    rows = {ref: row for ref, row in rows.items() if row['words']}
    return tokens, rows


def heard_tokens(media_path: str, progress=None, language: str = 'zh'
                 ) -> tuple[list[Token], dict[str, dict], list[tuple[int, int]]]:
    """The heard characters / words on the media clock, the evidence rows they
    came from, and the speech regions of a plain energy VAD (no model).
    Chinese: FireRed; Japanese / English: Qwen3-ASR + Qwen3-ForcedAligner."""
    from ..recognition.asr import _transcribe_firered_worker
    from ..recognition.cache import decode_audio_to_array
    from ..runtime_paths import resolve_model_dir
    if progress:
        progress(tr('读取音频…'))
    audio = decode_audio_to_array(media_path)
    seconds = len(audio) / 16000.0
    if seconds <= 0.05:
        raise ScriptMatchError(tr('素材里没有可用的音频'))
    regions, speech = _speech_regions(audio)
    if uses_qwen(language):
        tokens, rows = _qwen_heard_tokens(audio, regions, language, progress)
        return tokens, rows, speech
    if progress:
        progress(tr('{model} 正在生成字级时间（只听字和时间，不改你的文稿）…', model=TIMESTAMP_MODEL))
    normalized = _transcribe_firered_worker(audio, seconds, str(resolve_model_dir('FireRedASR2-AED')))
    tokens: list[Token] = []
    rows: dict[str, dict] = {}
    for index, segment in enumerate(normalized.get('segments', ()), 1):
        ref = f'firered:{index}'
        words = []
        for token in segment.get('tokens', ()):
            start, end = round(float(token['start']) * 1000), round(float(token['end']) * 1000)
            if end <= start or not str(token.get('text', '')).strip():
                continue
            words.append({'text': str(token['text']), 'start_ms': start, 'end_ms': end})
            tokens.append(Token(start, end, str(token['text']), ref, 'S00'))
        if words:
            rows[ref] = {'text': str(segment.get('text', '')), 'words': words,
                         'start_ms': words[0]['start_ms'], 'end_ms': words[-1]['end_ms'],
                         'final_timing_owner': TIMESTAMP_MODEL, 'source': 'script_match'}
    return tokens, rows, speech


def build_project(media_path: str, match: ScriptMatch, rows: dict[str, dict], language: str = 'zh'):
    from ..recognition.recognition_result import recognition_project_path
    from ..projects.studio_project import project_from_runtime_cues, save_project
    language = str(language or 'zh')
    cues = [SimpleNamespace(cue_id=f'script-{line.index + 1}', start=line.start_ms / 1000, end=line.end_ms / 1000,
                            text=line.text, speaker='S00') for line in match.lines]
    review = [f'script-{line.index + 1}' for line in match.lines if line.needs_review]
    source = f'{QWEN_ASR_MODEL} + {QWEN_ALIGNER_MODEL}' if uses_qwen(language) else TIMESTAMP_MODEL
    project = project_from_runtime_cues(media_path, cues, asr_evidence=rows, generation_metadata={
        'script_match': {'version': 1, 'timestamp_source': source, 'lines': len(match.lines),
                         'coverage': round(match.coverage, 4), 'review_cue_ids': review,
                         'note': '用户文稿按字级时间对齐；未调用其他识别模型或 AI。'},
        'language': {'code': language, 'requested': language, 'evidence': {'source': 'script_match'}},
    })
    by_id = {line_id: line for line_id, line in zip((c.cue_id for c in cues), match.lines)}
    for cue in project.cues:
        line = by_id.get(cue.id)
        if line is not None:
            cue.evidence_refs = [ref for ref in line.refs if ref in rows]
    if review:
        project.studio_state.setdefault('cue_statuses', {}).update({cue_id: 'issue' for cue_id in review})
    path = recognition_project_path(media_path, 'script-' + uuid.uuid4().hex[:16])
    path.parent.mkdir(parents=True, exist_ok=True)
    return save_project(project, path)


def failure_text(exc: BaseException) -> tuple[str, str]:
    """One line for the dialog and the full error for 「复制错误详情」.

    2026-10-16 (user: English matching "did nothing"): a model worker's error
    is its whole stdout/stderr tail, so the dialog shows only its last line,
    and running out of Windows commit (page file too small) reads as advice.
    """
    import traceback
    detail = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
    text = str(exc).strip() or type(exc).__name__
    if isinstance(exc, ScriptMatchError):
        return text, detail
    from ..recognition.asr import windows_commit_limit_error
    if windows_commit_limit_error(text):
        return tr('电脑的可用内存不够加载模型（Windows 虚拟内存/页面文件太小）。请先关闭浏览器、游戏等占内存的程序再试；'
                  '仍失败时，在“系统属性 → 高级 → 性能设置 → 高级 → 虚拟内存”里改为“系统管理的大小”，重启电脑后再试。'), detail
    head, _, rest = text.partition('\n')
    worker = re.match(r'(\S+) worker failed \(exit (-?\d+)\):', head)
    if worker:
        lines = [line.strip() for line in rest.splitlines()
                 if line.strip() and line.strip() not in ('stdout:', 'stderr:') and not line.startswith('[2BYTEASR_')]
        reason = lines[-1][:300] if lines else tr('退出码 {code}', code=worker.group(2))
        return tr('{model} 运行失败：{reason}', model=worker.group(1), reason=reason), detail
    return head[:300], detail


class ScriptMatchJob(QThread):
    progressed = Signal(str)
    succeeded = Signal(str, object)
    failed = Signal(str, str)   # one-line reason, full error

    def __init__(self, media_path: str, lines: list[str], parent=None, *, language: str = 'zh'):
        super().__init__(parent)
        self.media_path, self.lines = str(media_path), list(lines)
        self.language = str(language or 'zh')

    def run(self):
        try:
            tokens, rows, speech = heard_tokens(self.media_path, self.progressed.emit, self.language)
            self.progressed.emit(tr('按字级时间对齐文稿…'))
            match = match_script(self.lines, tokens, speech_regions_ms=speech, language=self.language)
            path = build_project(self.media_path, match, rows, self.language)
            self.succeeded.emit(str(path), match)
        except Exception as exc:
            try:
                reason, detail = failure_text(exc)
            except Exception:  # never lose the failure itself
                reason = detail = str(exc) or type(exc).__name__
            self.failed.emit(str(reason), str(detail))


def open_home_script_match(window) -> None:
    from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                                   QProgressBar, QPushButton, QVBoxLayout)
    from ..design.presentation import button_role
    from ..studio.studio_script_match import read_script_file
    media = [str(path) for path in getattr(window, 'media_paths', ()) if str(path).strip()]
    # 'error': (reason, full error) of the last failed run, shown until an input changes.
    state = {'media': media[0] if media else '', 'job': None, 'ready': {}, 'error': None}

    class _Dialog(QDialog):
        def reject(self):  # ×, Esc and 取消 wait while the timestamp job runs
            if state['job'] is None:
                super().reject()

    dialog = _Dialog(window)
    dialog.setObjectName('homeScriptMatchDialog')
    dialog.setWindowTitle(tr('匹配文稿'))
    dialog.resize(760, 620)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 18, 20, 16)
    layout.setSpacing(10)
    intro = QLabel(tr('你已经有完整文稿并断好句：每行一条字幕。这里只生成字级时间来对齐，文字保持你输入的样子。'))
    intro.setWordWrap(True)
    layout.addWidget(intro)
    media_row = QHBoxLayout()
    media_label = QLabel()
    media_label.setObjectName('homeScriptMatchMedia')
    media_label.setWordWrap(True)
    choose = button_role(QPushButton(tr('选择素材…')), 'secondary')
    media_row.addWidget(media_label, 1)
    media_row.addWidget(choose)
    layout.addLayout(media_row)
    language_row = QHBoxLayout()
    language_row.addWidget(QLabel(tr('文稿语言')))
    language_box = QComboBox()
    language_box.setObjectName('homeScriptMatchLanguage')
    for code, caption in (('', tr('自动判断')), ('zh', tr('中文')), ('ja', tr('日语')), ('en', tr('英语')),
                          ('ko', tr('韩语')), ('es', tr('西班牙语')), ('de', tr('德语')), ('fr', tr('法语')),
                          ('pt', tr('葡萄牙语')), ('it', tr('意大利语')), ('ru', tr('俄语'))):
        language_box.addItem(caption, code)
    language_row.addWidget(language_box)
    language_row.addStretch(1)
    layout.addLayout(language_row)
    script = QPlainTextEdit()
    script.setObjectName('homeScriptMatchInput')
    script.setPlaceholderText(tr('每行一条字幕，例如：\n大家好，欢迎回来\n今天我们继续打洛克王国'))
    layout.addWidget(script, 1)
    runs = QLabel()
    runs.setObjectName('homeScriptMatchRuns')
    runs.setWordWrap(True)
    layout.addWidget(runs)
    status = QLabel('')
    status.setObjectName('homeScriptMatchStatus')
    status.setWordWrap(True)
    layout.addWidget(status)
    bar = QProgressBar()
    bar.setRange(0, 0)
    bar.setTextVisible(False)
    bar.setFixedHeight(6)
    bar.hide()
    layout.addWidget(bar)
    actions = QHBoxLayout()
    load = button_role(QPushButton(tr('从文件读取…')), 'secondary')
    workshop = button_role(QPushButton(tr('打开模型工坊')), 'secondary')
    copy_error = button_role(QPushButton(tr('复制错误详情')), 'secondary')
    copy_error.setObjectName('homeScriptMatchCopyError')
    copy_error.hide()
    cancel = button_role(QPushButton(tr('取消')), 'secondary')
    start = button_role(QPushButton(tr('开始匹配')), 'primary')
    actions.addWidget(load)
    actions.addWidget(workshop)
    actions.addWidget(copy_error)
    actions.addStretch(1)
    actions.addWidget(cancel)
    actions.addWidget(start)
    layout.addLayout(actions)

    def current_language():
        return script_language(parse_script(script.toPlainText()), str(language_box.currentData() or ''))

    def refresh():
        name = Path(state['media']).name if state['media'] else ''
        media_label.setText(tr('素材：{name}', name=name) if name else tr('素材：还没选择'))
        if len(media) > 1 and state['media'] == media[0]:
            media_label.setText(media_label.text() + tr('（本批共 {count} 个，只匹配第一个）', count=len(media)))
        language = current_language()
        if uses_qwen(language):
            runs.setText(tr('只运行：{asr} 听写 + {aligner} 字词时间（本机）。不会运行 MOSS、AI 校对与 AI 断句，也不上传。'
                            '适用于{language}。', asr=QWEN_ASR_MODEL, aligner=QWEN_ALIGNER_MODEL,
                            language=tr({'ja': '日语', 'ko': '韩语', 'es': '西班牙语', 'de': '德语', 'fr': '法语',
                                         'pt': '葡萄牙语', 'it': '意大利语', 'ru': '俄语'}.get(language, '英语'))))
        else:
            runs.setText(tr('只运行：{model} 字级时间（本机显卡）。不会运行 MOSS、Qwen3-ASR 复核、AI 校对与 AI 断句，也不上传。'
                            '适用于中文（含中英混合）。', model=TIMESTAMP_MODEL))
        route = 'qwen' if uses_qwen(language) else 'zh'
        if route not in state['ready']:  # the model scan reads the disk: once per route
            state['ready'][route] = timestamp_model_ready(language)
        ready, reason = state['ready'][route]
        workshop.setVisible(not ready)
        error = state['error']
        if state['job'] is None:
            # A failed run keeps its reason here; it used to be cleared right away,
            # so a failure looked like the button "did nothing" (2026-10-16).
            status.setText(tr('匹配没有完成：{error}', error=error[0]) if error else ('' if ready else reason))
        copy_error.setVisible(bool(error) and state['job'] is None)
        start.setEnabled(bool(ready and state['media'] and state['job'] is None))

    def inputs_changed():
        state['error'] = None
        refresh()

    def choose_media():
        from .main_ui_helpers import SUPPORTED_MEDIA_SUFFIXES
        pattern = ' '.join('*' + suffix for suffix in sorted(SUPPORTED_MEDIA_SUFFIXES))
        path, _ = QFileDialog.getOpenFileName(dialog, tr('选择素材'), '', tr('音视频 ({pattern})', pattern=pattern))
        if path:
            state['media'] = path
            inputs_changed()

    def load_file():
        path, _ = QFileDialog.getOpenFileName(dialog, tr('选择文稿'), '', tr('文本文件 (*.txt);;所有文件 (*)'))
        if path:
            try:
                script.setPlainText(read_script_file(path))
            except (OSError, ValueError) as exc:
                status.setText(str(exc))

    def finished(path, match):
        bar.hide()
        state['job'] = None
        status.setText(tr('共 {count} 句；文稿 {coverage}% 的字对上了字级时间；{review} 句标为待检查。正在打开工作台…',
                          count=len(match.lines), coverage=round(match.coverage * 100), review=match.review_count))
        dialog.accept()
        window.open_studio_project(path, mode='edit', source='script_match')

    def failed(reason, detail=''):
        bar.hide()
        state['job'] = None
        state['error'] = (reason, detail or reason)
        copy_error.setText(tr('复制错误详情'))
        for widget in (script, load, choose, cancel, language_box):
            widget.setEnabled(True)
        refresh()

    def copy_failure():
        from PySide6.QtWidgets import QApplication
        if state['error']:
            QApplication.clipboard().setText(state['error'][1])
            copy_error.setText(tr('已复制'))

    def begin():
        lines = parse_script(script.toPlainText())
        if not lines:
            status.setText(tr('文稿是空的：每行一条字幕'))
            return
        state['error'] = None
        copy_error.hide()
        job = ScriptMatchJob(state['media'], lines, dialog, language=current_language())
        state['job'] = job
        job.progressed.connect(status.setText)
        job.succeeded.connect(finished)
        job.failed.connect(failed)
        for widget in (script, load, choose, start, cancel, language_box):
            widget.setEnabled(False)
        bar.show()
        job.start()

    choose.clicked.connect(choose_media)
    load.clicked.connect(load_file)
    workshop.clicked.connect(lambda: (dialog.reject(), window._open_model_workshop()))
    copy_error.clicked.connect(copy_failure)
    cancel.clicked.connect(dialog.reject)
    start.clicked.connect(begin)
    language_box.currentIndexChanged.connect(lambda _index: inputs_changed())
    script.textChanged.connect(inputs_changed)
    refresh()
    window._home_script_match_dialog = dialog
    dialog._begin = begin  # automated checks drive the real handlers
    dialog._script = script
    dialog._state = state
    dialog._language = language_box
    dialog._status = status
    dialog._start = start
    dialog._copy_error = copy_error
    try:
        dialog.exec()
    finally:
        window._home_script_match_dialog = None
        job = state['job']
        if job is not None:
            job.wait()


__all__ = ['ScriptMatchJob', 'build_project', 'failure_text', 'heard_tokens', 'open_home_script_match',
           'script_language', 'timestamp_model_ready', 'uses_qwen']
