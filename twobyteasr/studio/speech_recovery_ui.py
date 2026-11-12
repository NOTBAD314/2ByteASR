"""Persistent speech-gap list, seek and the existing single-range retry sheet."""
from __future__ import annotations

from ..i18n import tr
from ..recognition.speech_recovery_project import project_ranges

STATUS_LABELS = dict(pending='疑似漏识，待恢复', partial='部分恢复',
                     needs_confirmation='疑似语音，待试听确认', failed='处理失败，待重试',timing_confirmation='文字仍在，时间待核对')
STAGE_LABELS = dict(parsed_response='原始响应解析', response_generation='模型生成', window_merge='跨窗合并',
                    language_acceptance='语言接纳', speaker_filter_alignment='说话人筛选与对齐',
                    segmentation='断句', final_cues='最终字幕', deduplication='去重',
                    speaker_filter='说话人筛选', alignment='对齐')
REASON_LABELS = dict(speech_without_transcript='检测到疑似人声，缺少有效字幕', token_limit='输出达到预算',
    unfinished_transcript_tail='尾句未完整返回', unexpected_stop='生成异常结束',
    invalid_timestamp='返回时间戳异常', downstream_text_loss='上游文字在此阶段缺失',
    text_retained_timing_contracted='原文完整，时间范围收紧；尚未完成试听',
    parsed_text_lost_in_merge='已有识别文字在合并时缺失', content_blocked='服务内容安全审查拒绝')


def _clock(milliseconds):
    hours, rest = divmod(max(0, int(milliseconds)), 3600000)
    minutes, rest = divmod(rest, 60000)
    return f'{hours:02d}:{minutes:02d}:{rest/1000:06.3f}'


def summary(ranges):
    rows = {row['id']: row for row in ranges}.values()
    from collections import Counter
    counts = Counter(row.get('classification') for row in rows)
    parts = []
    for kind, text in (('processing_failure', '处理失败'), ('supported_speech_gap', '疑似漏识'),
                       ('uncertain_speech', '待试听确认'),('timing_confirmation','时间待核对')):
        if counts[kind]:
            parts.append(f'{text} {counts[kind]} 处')
    return '识别已结束 · ' + ' · '.join(parts) if parts else '语音范围已处理'


def open_recovery(page):
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget, QCheckBox
    from ..design.studio_theme import apply_secondary_surface_theme
    project = page.project
    ranges = project_ranges(project,include_timing=True)
    dialog = QDialog(page)
    dialog.setObjectName('speechRecoveryDialog')
    dialog.setWindowTitle(tr('语音缺口与时间核对'))
    dialog.resize(720, 420)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(summary(ranges)))
    toolbar = QHBoxLayout()
    select_all = QCheckBox(tr('全选'), dialog)
    toolbar.addWidget(select_all)
    confirm = QPushButton(tr('确认选中范围无语音／无需恢复'), dialog)
    confirm.setObjectName('speechGapConfirmNoSpeech')
    toolbar.addWidget(confirm)
    undo = QPushButton(tr('撤销'), dialog)
    toolbar.addWidget(undo)
    layout.addLayout(toolbar)
    selected = []
    def refresh():
        dialog.close()
        if page.project is project:
            page._sync_recognition_zero_state()
            open_recovery(page)
    def apply_decision():
        ids = {key for key, box in selected if box.isChecked()}
        if page.project is project and ids:
            from ..timeline.speech_gap_commands import ConfirmNoSpeechCommand
            page.undo_stack.push(ConfirmNoSpeechCommand(project, ids, changed=page._changed))
            refresh()
    confirm.clicked.connect(apply_decision)
    select_all.toggled.connect(lambda checked: [box.setChecked(checked) for _, box in selected])
    def undo_decision():
        if page.project is project and page.undo_stack.canUndo():
            page.undo_stack.undo()
            refresh()
    undo.clicked.connect(undo_decision)
    undo.setEnabled(page.undo_stack.canUndo())
    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    content = QWidget(scroll)
    listing = QVBoxLayout(content)
    for row in ranges:
        line = QHBoxLayout()
        checkbox = QCheckBox(content)
        checkbox.setObjectName('speechGapSelect')
        timing_only=row.get('classification')=='timing_confirmation'
        if timing_only:
            checkbox.hide()
        else:selected.append((row['id'], checkbox))
        line.addWidget(checkbox)
        start, end = row['timeline_start_ms'], row['timeline_end_ms']
        reason = '、'.join(REASON_LABELS.get(r, r) for r in row['reason'].split(','))
        label = QLabel(f"{_clock(start)}–{_clock(end)} · {STATUS_LABELS.get(row['status'], row['status'])}\n"
                       f"{STAGE_LABELS.get(row['first_missing_stage'], row['first_missing_stage'])} · {reason}\n"
                       f"{tr('已尝试')} {len(row.get('attempts', []))}", content)
        label.setToolTip(f"{row['id']} · {row.get('recovery_source') or ''}\n"
                        f"{row.get('evidence', {})}\n{row.get('processing_errors', [])}\n"
                        f"{[a.get('error') for a in row.get('attempts', ()) if a.get('error')]}")
        label.setWordWrap(True)
        line.addWidget(label, 1)
        jump = QPushButton(tr('跳转试听'), content)
        jump.setObjectName('speechGapJump')
        def seek(_checked=False, point=start):
            if page.project is project:
                page._seek(point/1000)
        jump.clicked.connect(seek)
        line.addWidget(jump)
        retry = QPushButton(tr('仅重试该范围…'), content)
        retry.setObjectName('speechGapRetry')
        if timing_only:
            retry.setText(tr('查看文字与时间'))
            retry.setObjectName('speechGapTimingReview')
            retry.setToolTip(tr('文字已保留，只核对时间；不会自动请求重新识别。'))
        if row.get('reason') == 'content_blocked':
            retry.setToolTip(tr('此范围已有服务内容安全拒绝，请在识别面板选择本地模型恢复'))
        retry.setEnabled(not getattr(page, '_recognition_running', False))
        def recognize(_checked=False, bounds=(start, end),timing_only=timing_only):
            if page.project is project and not getattr(page, '_recognition_running', False):
                dialog.accept()
                if timing_only:
                    page._seek(bounds[0]/1000)
                else:page._open_recognition_sheet(range_ms=bounds)
        retry.clicked.connect(recognize)
        line.addWidget(retry)
        listing.addLayout(line)
    listing.addStretch(1)
    scroll.setWidget(content)
    layout.addWidget(scroll)
    apply_secondary_surface_theme(dialog)
    page._speech_recovery_dialog = dialog
    dialog.open()
    return dialog


def add_actions(page, menu):
    """Keep the existing gap listening/recovery panel in the timeline menu."""
    if not project_ranges(getattr(page, 'project', None), include_timing=True):
        return
    action = menu.addAction(tr('语音缺口与时间核对…'), lambda: open_recovery(page))
    action.setObjectName('speechRecoveryAction')
