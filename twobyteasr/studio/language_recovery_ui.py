"""One task-level recovery action, routed through the existing range sheet."""
from __future__ import annotations
from ..i18n import tr


def _clock(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f'{minutes:02d}:{seconds:02d}'


def _pending(page):
    from ..recognition.language_recovery_project import project_pending
    project = getattr(page, 'project', None)
    runtime = getattr(getattr(page, 'session', None), 'runtime', None)
    revision = getattr(runtime, 'language_source_revision', getattr(runtime, 'revision', None))
    metadata = project.generation_metadata if project else {}
    state = metadata.get('transcript_acceptance')
    if isinstance(state, dict):
        return project_pending(project)
    from pathlib import Path
    try:
        report = Path(project.report_path).stat() if project else None
        report_key = (report.st_size, report.st_mtime_ns) if report else None
    except OSError:
        report_key = None
    key = (id(project), revision, len(project.cues) if project else 0,
           str(metadata.get('language')), metadata.get('job_id'),
           str(getattr(project, 'report_path', '')), report_key)
    old = getattr(page, '_language_recovery_pending_cache', None)
    if old is not None and old[0] == key:
        return old[1]
    value = project_pending(project)
    page._language_recovery_pending_cache = (key,value)
    return value


def open_recovery(page, region=None):
    if getattr(page, '_recognition_running', False):
        page._language_recovery_request_status='busy'
        return
    from ..recognition.language_recovery_project import project_pending
    pending = project_pending(page.project)
    region = region or (pending[0] if pending else None)
    if region is None:
        page._language_recovery_request_status='no_pending_scope'
        return
    requested = region.get('requested_language') or (
        page.project.generation_metadata.get('language') or {}).get('requested', 'en')
    page._language_recovery_request_status='opening_sheet'
    page._open_recognition_sheet(range_ms=(round(region['start']*1000), round(region['end']*1000)),
        language_recovery={'conflict_id':region['id'], 'requested_language':requested,
            'explicit_local_range':True, 'explicit_retry':True})


def add_actions(page, menu):
    pending = _pending(page)
    for region in pending:
        action = menu.addAction(tr('恢复语言异常 {start}–{end}…', start=_clock(region['start']), end=_clock(region['end'])),
                                lambda _checked=False, r=region:open_recovery(page,r))
        action.setObjectName('languageRecoveryAction')
        action.setEnabled(not getattr(page, '_recognition_running', False))


def sync_action(page):
    from PySide6.QtWidgets import QPushButton
    if getattr(page,'_recognition_running',False):
        button = getattr(page,'_language_recovery_button',None)
        if button is not None:
            button.hide()
        return
    pending = _pending(page)
    parts = page._recognition_chip_parts()
    if parts is None:
        return
    frame, label = parts
    button = getattr(page, '_language_recovery_button', None)
    if pending and button is None:
        button = QPushButton(tr('仅恢复异常范围…'), frame)
        button.setObjectName('languageRecoveryButton')
        button.clicked.connect(lambda _checked=False:open_recovery(page))
        frame.layout().addWidget(button)
        page._language_recovery_button = button
    if button is not None:
        button.setVisible(bool(pending) and not getattr(page, '_recognition_running', False))
    if pending and not getattr(page, '_recognition_running', False):
        cancel=getattr(page,'recognition_cancel_button',None)
        if cancel is not None:cancel.hide()
        label.setText(tr('语言待恢复 {count} 段 · {start}–{end}',count=len(pending),
                         start=_clock(pending[0]['start']),end=_clock(pending[0]['end'])))
        frame.show()
        page._language_recovery_notice = True
    elif getattr(page, '_language_recovery_notice', False) and not getattr(page, '_recognition_running', False):
        page._language_recovery_notice = False
        frame.hide()
