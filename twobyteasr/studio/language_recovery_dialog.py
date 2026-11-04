"""Review preserved source candidates, then dispatch an explicit recovery."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
    QListWidget, QPushButton, QVBoxLayout)

from ..i18n import tr


def show_candidates(page, region, requested):
    project = page.project
    rows = region.get('raw_rows') or []
    dialog = QDialog(page)
    dialog.setObjectName('languageCandidateReview')
    dialog.setWindowTitle(tr('核对转写候选与输入音频'))
    dialog.resize(820, 560)
    layout = QVBoxLayout(dialog)
    advisory=region.get('status')=='observation'
    reference_only=region.get('raw_origin')=='project_subtitles'
    reusable=region.get('reusable',True)
    note = QLabel(tr('已按你选择的源语言处理；以下候选疑似其他语言，可试听核对或主动重新识别。文字观察不能证明真实音频语言。' if advisory else '旧审核保留了此范围候选。可以按原手动选择继续处理；修改源语言前请主动核对。'))
    if region.get('reason')=='user_requested_review':
        note.setText(tr('请试听输入并核对源语言。候选错误时可直接重新识别，不需要确认错误候选正确。' + (' 以下是已保存的工程字幕，不是原始云端候选，不能直接复用。' if reference_only else '')))
    note.setWordWrap(True)
    layout.addWidget(note)
    source = QLabel(tr('范围 {start:.3f}–{end:.3f} 秒 · 候选 {count} 段 · 远端任务 {remote}',
        start=region['start'], end=region['end'], count=len(rows), remote=region.get('remote_task_id') or tr('未记录')))
    source.setWordWrap(True)
    layout.addWidget(source)
    models=(project.generation_metadata or {}).get('models') or {}
    if models.get('qwen_asr_api_model')=='moss-transcribe-diarize-pro':
        capability=QLabel(tr('MOSS云端使用自动语种识别，尚无已确认的固定源语言参数。可选择已有本地模型，从音频重新识别错误范围。'))
        capability.setObjectName('languageCandidateCloudCapability')
        capability.setWordWrap(True)
        layout.addWidget(capability)
    candidates = QListWidget()
    candidates.setObjectName('languageCandidateRows')
    candidates.setWordWrap(True)
    for row in rows:
        candidates.addItem(f"{row['start']:.3f}–{row['end']:.3f}  {row.get('speaker') or ''}\n{row.get('text') or ''}")
    layout.addWidget(candidates, 1)
    if rows:
        candidates.setCurrentRow(0)
    listen = QPushButton(tr('试听所选候选（最多 12 秒）'))
    listen.setObjectName('languageCandidateListen')
    layout.addWidget(listen)
    problem = QLabel('' if rows else tr('此工程未保存候选原文。可从原始缓存恢复，或明确重新识别该范围。'))
    problem.setWordWrap(True)
    layout.addWidget(problem)
    language = QComboBox()
    language.setObjectName('languageCandidateSource')
    for code, label in [('auto','自动判断'),('en','英语'),('de','德语'),('zh','中文'),('ja','日语'),('ko','韩语'),
                        ('it','意大利语'),('fr','法语'),('es','西班牙语'),('pt','葡萄牙语'),('ru','俄语'),('pt-BR','葡萄牙语（巴西）'),('pt-PT','葡萄牙语（葡萄牙）')]:
        language.addItem(tr(label), code)
    language.setCurrentIndex(max(0, language.findData(requested)))
    choice = QHBoxLayout()
    choice.addWidget(QLabel(tr('核对后的源语言')))
    choice.addWidget(language, 1)
    layout.addLayout(choice)
    source_confirmed=QCheckBox(tr('我已试听并确认所选音频源语言（重新识别不要求候选正确）'))
    source_confirmed.setObjectName('languageCandidateSourceConfirmed')
    layout.addWidget(source_confirmed)
    confirmed = QCheckBox(tr('我已试听核对，确认所选语言、候选原文与输入相符（复用候选）'))
    confirmed.setObjectName('languageCandidateConfirmed')
    layout.addWidget(confirmed)
    reuse = QPushButton(tr('复用候选，继续审核与字幕处理…'))
    reuse.setObjectName('languageCandidateReuse')
    reuse.setEnabled(False)
    cloud = QPushButton(tr('候选错误：重新云端识别此范围…'))
    cloud.setObjectName('languageCandidateCloud')
    local = QPushButton(tr('选择本地模型恢复此范围…'))
    local.setObjectName('languageCandidateLocal')
    for button in (reuse, cloud, local):
        layout.addWidget(button)
    from ..recognition.language_decision import mode_for
    from ..subtitle_rules.language_rules import normalize_language
    def can_continue():
        unchanged=mode_for(requested)=='manual' and normalize_language(language.currentData())==normalize_language(requested)
        reuse.setEnabled(bool(reusable and rows and (confirmed.isChecked() or unchanged)))
    confirmed.toggled.connect(lambda _:can_continue())
    def language_changed(_):
        source_confirmed.setChecked(False)
        confirmed.setChecked(False)
        problem.clear()
        can_continue()
    language.currentIndexChanged.connect(language_changed)
    can_continue()

    def listen_row():
        if page.project is not project:
            problem.setText(tr('工程已变化，请重新打开恢复入口。'))
            return
        index = candidates.currentRow()
        start = rows[index]['start'] if 0 <= index < len(rows) else region['start']
        end = rows[index]['end'] if 0 <= index < len(rows) else region['end']
        page._seek(start)
        page.video.set_paused(False)
        QTimer.singleShot(round(min(12., end-start)*1000), lambda: page.video.set_paused(True)
                          if page.project is project else None)

    def dispatch(mode):
        if page.project is not project or getattr(page, '_recognition_running', False):
            problem.setText(tr('工程已变化或正在识别，请重新打开恢复入口。'))
            return
        if normalize_language(language.currentData())!=normalize_language(requested) and not (source_confirmed.isChecked() or confirmed.isChecked()):
            problem.setText(tr('请先试听并确认音频源语言；候选错误时不需要确认候选正确。'))
            return
        policy = dict(conflict_id=region['id'], requested_language=language.currentData(), explicit_retry=True)
        if mode == 'reuse':
            from ..recognition.candidate_reprocess import policy_for
            try:
                policy = policy_for(project, region, language.currentData(), confirmed=confirmed.isChecked())
            except ValueError as exc:
                problem.setText(str(exc))
                return
        else:
            policy.update(force_cloud=mode == 'cloud', explicit_local_range=mode == 'local',
                source_language_confirmed=bool(source_confirmed.isChecked() or confirmed.isChecked()),
                candidate_text_confirmed=bool(confirmed.isChecked()))
        dialog.accept()
        page._open_recognition_sheet(range_ms=(round(region['start']*1000), round(region['end']*1000)),
                                     language_recovery=policy)

    listen.clicked.connect(listen_row)
    reuse.clicked.connect(lambda: dispatch('reuse'))
    cloud.clicked.connect(lambda: dispatch('cloud'))
    local.clicked.connect(lambda: dispatch('local'))
    page._language_candidate_dialog = dialog
    page._language_candidate_controls = dict(rows=candidates, language=language, confirmed=confirmed,source_confirmed=source_confirmed,
        reuse=reuse, cloud=cloud, local=local, listen=listen, problem=problem)
    dialog.show()
    dialog.raise_()
