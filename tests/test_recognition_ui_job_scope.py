"""Queued completion/progress/finished signals cannot change a different job."""
from types import SimpleNamespace

from twobyteasr.app.ui import MainWindow


def test_late_signal_owner_is_checked_before_any_ui_mutation():
    page = SimpleNamespace(_active_job_id='new')
    received = []
    for payload in ('progress', 'console', 'result', 'error', 'finished'):
        assert not MainWindow._dispatch_recognition_job(page, 'old', received.append, payload)
    assert received == []
    assert MainWindow._dispatch_recognition_job(page, 'new', received.append, 'result')
    assert received == ['result']
    page._committed_job_ids = {'new'}
    assert not MainWindow._dispatch_recognition_job(page, 'new', received.append, 'late error')
    assert MainWindow._dispatch_recognition_job(page, 'new', received.append, 'Studio handoff', allow_committed=True)
    assert received == ['result', 'Studio handoff']


def test_result_with_another_job_or_committed_job_is_ignored_before_releasing_worker():
    for owner, result_job, committed in (('new', 'old', set()), ('new', '', set()), ('new', 'new', {'new'})):
        page = SimpleNamespace(_active_job_id=owner, _committed_job_ids=committed)
        MainWindow._handle_result(page, SimpleNamespace(job_id=result_job))


def test_cancelled_late_success_is_kept_out_of_completion_handoff():
    received = []
    page = SimpleNamespace(_active_job_id='cancelled', _committed_job_ids=set(),
        _cancelled_job_ids={'cancelled'}, _handle_unexpected_error=received.append)
    MainWindow._handle_result(page, SimpleNamespace(job_id='cancelled', successes=[object()]))
    assert len(received) == 1 and '未自动载入' in received[0]


def test_task_key_includes_job_identity_even_for_the_same_path():
    a = SimpleNamespace(job_id='a', report_json_path='', project_path='same.2byteproj', media_path='same.mp4')
    b = SimpleNamespace(job_id='b', report_json_path='', project_path='same.2byteproj', media_path='same.mp4')
    assert MainWindow._completion_task_key(a) != MainWindow._completion_task_key(b)
