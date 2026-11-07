"""Existing actions continue only after the asynchronous durability receipt."""
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('failure', [False, True])
def test_recognition_waits_for_durable_save(tmp_path, failure):
    from twobyteasr.app.ui import MainWindow
    media = tmp_path/'media.mp4'
    project_path = tmp_path/'project.2byteproj'
    media.write_bytes(b'owned placeholder')
    project_path.write_text('{}')
    pending, resumed, errors = [], [], []
    page = SimpleNamespace(project=object(), session=SimpleNamespace(generation=4),
        undo_stack=SimpleNamespace(isClean=lambda:False),
        save=lambda **options:pending.append(options['on_finished']) or 'save-id',
        fail_recognition_runtime=errors.append)
    window = SimpleNamespace(_ensure_recognition_page=lambda:None, studio_page=page,
        _handle_studio_recognition_request=lambda *args,**options:resumed.append(options))
    MainWindow._handle_studio_recognition_request(window,'start',str(media),str(project_path))
    assert len(pending) == 1 and resumed == []
    pending[0](project_path, OSError('full') if failure else None)
    assert bool(errors) == failure
    assert bool(resumed) != failure
    if resumed:
        assert resumed[0]['_save_ready'] is True


@pytest.mark.parametrize('failure', [False, True])
def test_mcp_saved_result_is_a_completed_job_after_durability(tmp_path, failure):
    from twobyteasr.local_mcp.production_media import MediaOperations
    path = tmp_path/'project.2byteproj'
    path.write_text('{}')
    pending = []
    job = dict(status='running', result={})
    page = SimpleNamespace(session=SimpleNamespace(project_path=path),
        project_controller=SimpleNamespace(save=lambda **options:pending.append(options['on_finished']) or 'save-id'))
    def finish(current, result):
        current.update(status='completed', result=result)
    def fail(current, error):
        current.update(status='failed', error=str(error))
    host = SimpleNamespace(require_project=lambda *args:(page, object()),
        new_job=lambda *args:job, snapshot=lambda *args:dict(project_id='p',revision=8),
        finish_job=finish, fail_job=fail, public_job=lambda current:dict(current))
    response = MediaOperations.op_save_project(host,'p',8)
    assert response['status'] == 'running' and not response['result'].get('saved')
    pending[0](path, OSError('full') if failure else None)
    assert job['status'] == ('failed' if failure else 'completed')
    if not failure:
        assert job['result']['saved'] is True and job['result']['revision'] == 8


@pytest.mark.parametrize('failure', [False, True])
def test_new_link_project_is_imported_only_after_save_receipt(monkeypatch, failure):
    import twobyteasr.app.link_download_controller as module
    pending, imported, failed, notified = [], [], [], []
    monkeypatch.setattr(module, 'target_matches', lambda *args:True)
    monkeypatch.setattr(module, 'LinkImportCommand', lambda *args,**options:SimpleNamespace(result={'cue_count':1}))
    monkeypatch.setattr(module, 'refresh_after_import', lambda *args:None)
    page = SimpleNamespace(project=SimpleNamespace(project_id='p'),project_path=Path('owned.2byteproj'),
        session=SimpleNamespace(generation=1),video=SimpleNamespace(set_paused=lambda value:None),
        undo_stack=SimpleNamespace(push=lambda command:None),_studio_trace=lambda *args,**options:None,
        save=lambda **options:pending.append(options['on_finished']) or 'save-id')
    host = SimpleNamespace(queue=SimpleNamespace(imported=lambda *args:imported.append(args),pending=lambda *args:failed.append(args)),
        _preparing={'task'},_notify_imported=lambda *args:notified.append(args),_show_error=lambda error:None)
    bundle = {'manifest':{'video_id':'owned'}}
    module.LinkDownloadController._apply(host,page,'task',bundle,{'newly_created':True})
    assert imported == [] and notified == [] and len(pending) == 1
    pending[0](page.project_path,OSError('full') if failure else None)
    assert bool(failed) == failure
    assert bool(imported) != failure and bool(notified) != failure
