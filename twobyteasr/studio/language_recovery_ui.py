"""One task-level recovery action, routed through the existing range sheet."""
from __future__ import annotations
from ..i18n import tr


def _clock(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f'{minutes:02d}:{seconds:02d}'


def _pending(page):
    from ..recognition.language_recovery_project import project_review_ranges as project_pending
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
    from ..recognition.language_recovery_project import project_review_ranges as project_pending
    pending = project_pending(page.project)
    region = region or (pending[0] if pending else None)
    if region is None:
        from ..recognition.language_recovery_project import review_scope
        region=review_scope(page.project)
    if region is None:
        page._language_recovery_request_status='no_pending_scope'
        return
    requested = region.get('requested_language') or (
        page.project.generation_metadata.get('language') or {}).get('requested', 'en')
    from .language_recovery_dialog import show_candidates
    page._language_recovery_request_status='reviewing_candidates'
    show_candidates(page, region, requested)


def add_actions(page, menu):
    pending = _pending(page)
    project=getattr(page,'project',None)
    if not pending and project is not None and (project.cues or (project.generation_metadata.get('transcript_acceptance') or {}).get('candidate_rows')):
        action=menu.addAction(tr('核对源语言与转写…'),lambda _checked=False:open_recovery(page))
        action.setObjectName('languageReviewAction')
        action.setEnabled(not getattr(page,'_recognition_running',False))
    for region in pending:
        action = menu.addAction(tr('恢复语言异常 {start}–{end}…', start=_clock(region['start']), end=_clock(region['end'])),
                                lambda _checked=False, r=region:open_recovery(page,r))
        action.setObjectName('languageRecoveryAction')
        action.setEnabled(not getattr(page, '_recognition_running', False))
