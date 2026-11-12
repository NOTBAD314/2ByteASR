"""Home export preparation, optional-data recovery and atomic ZIP publication."""
import errno
import json
import threading
import time
import zipfile
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog,QWidget
from shiboken6 import isValid

from twobyteasr.diagnostics import support_bundle as bundle, support_dialog as ui
from twobyteasr.diagnostics.event_log import EventStore


def wait(predicate):
    limit=time.monotonic()+5
    while not predicate() and time.monotonic()<limit:
        QApplication.processEvents()
        time.sleep(.003)
    assert predicate()


def inspect(target):
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        result=json.loads(z.read('manifest.json'))
        assert json.loads(z.read('environment.json'))['application']['build']['app_version']
        assert z.read('README.txt').strip()
        assert [json.loads(line) for line in z.read('events.jsonl').splitlines()]
        return result


@pytest.fixture
def dialog(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    from twobyteasr.diagnostics import editor_diagnostics
    store=EventStore(tmp_path/'logs')
    monkeypatch.setattr(editor_diagnostics,'_INSTANCE',store)
    monkeypatch.setattr(editor_diagnostics,'install_early',lambda:store)
    owner=QWidget()
    view=ui.open_support_dialog(owner)
    QTest.qWait(40)
    yield view,store,owner
    if isValid(view):view.close()
    wait(lambda:view._jobs==0)
    owner.close();owner.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    store.close_store(clean=True)


def test_empty_or_missing_log_root_is_useful_minimum_bundle(tmp_path,monkeypatch):
    from twobyteasr.diagnostics import build_identity
    monkeypatch.setattr(build_identity,'_run_git',lambda *a:pytest.fail('Export must not scan source Git'))
    target=tmp_path/'非 ASCII 空 日志.zip'
    result=bundle.export_report(target,root=tmp_path/'no-logs')
    manifest=inspect(target)
    assert result['status']==manifest['status']=='partial'
    assert manifest['report_id']==result['report_id'] and manifest['missing']
    with zipfile.ZipFile(target) as archive:
        assert json.loads(archive.read('environment.json'))['application']['build']['app_version'] not in {'unknown','?'}


@pytest.mark.parametrize('section',['models','switches','subtitle_language'])
def test_uninitialized_or_legacy_settings_cannot_break_summary(section):
    summary=ui.settings_summary(SimpleNamespace(legacy=SimpleNamespace(RUNTIME_SETTINGS={section:'old-shape'})))
    assert summary['_missing'][0]['field']==section
    assert '_missing' not in ui.settings_summary(None)


@pytest.mark.parametrize('available',['documents','home','temp'])
def test_native_save_default_uses_existing_user_directory_not_install_cwd(dialog,tmp_path,monkeypatch,available):
    from pathlib import Path
    from PySide6.QtCore import QStandardPaths
    view,_store,_owner=dialog
    docs=tmp_path/'用户 文档';home=tmp_path/'用户 主目录';temp=tmp_path/'用户 临时'
    paths={'documents':docs,'home':home,'temp':temp}
    paths[available].mkdir()
    install=tmp_path/'install';install.mkdir();monkeypatch.chdir(install)
    monkeypatch.setattr(Path,'home',staticmethod(lambda:home))
    monkeypatch.setattr(QStandardPaths,'writableLocation',lambda kind:str(docs if kind==QStandardPaths.StandardLocation.DocumentsLocation else temp))
    suggestions=[]
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args,**kw:(suggestions.append(args[2]) or '', ''))
    view._choose_export()
    assert Path(suggestions[0]).is_absolute() and Path(suggestions[0]).parent==paths[available]
    assert not list(install.iterdir()) and view.export.isEnabled()


def test_cancel_then_retry_and_parameter_failure_are_visible_and_copyable(dialog,tmp_path,monkeypatch):
    view,store,owner=dialog
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:('',''))
    view.export.click()
    assert view.export.isEnabled() and '取消' in view.note.text() and not view._exporting
    with monkeypatch.context() as change:
        def fail():raise TypeError('private setting body should not leak')
        change.setattr(view,'_options',fail)
        view._export_to(tmp_path/'never.zip')
    assert view.export.isEnabled() and view._result['stage']=='parameter_preparation' and view._jobs>=0
    view._copy()
    copied=QApplication.clipboard().text()
    assert 'parameter_preparation' in copied and 'TypeError' in copied
    assert 'private setting body' not in copied
    view._export_to(tmp_path/'重试.zip');wait(lambda:not view._exporting)
    assert inspect(tmp_path/'重试.zip')['report_id']==view.identity.text()
    assert str(tmp_path/'重试.zip') in view.note.text()


def test_optional_settings_failure_and_broken_records_leave_partial_bundle(dialog,tmp_path,monkeypatch):
    view,store,owner=dialog
    def fail(_):raise AttributeError('not initialized')
    monkeypatch.setattr(ui,'settings_summary',fail)
    view._export_to(tmp_path/'partial.zip');wait(lambda:not view._exporting)
    manifest=inspect(tmp_path/'partial.zip')
    assert manifest['status']=='partial' and any(m['stage']=='settings_summary' for m in manifest['missing'])


def test_worker_start_failure_can_retry_without_job_leak(dialog,tmp_path,monkeypatch):
    view,store,owner=dialog
    wait(lambda:not view._loading)
    with monkeypatch.context() as change:
        def fail(_):raise RuntimeError('thread unavailable')
        change.setattr(threading.Thread,'start',fail)
        view._export_to(tmp_path/'worker.zip')
    assert not view._exporting and view._jobs==0 and view.export.isEnabled()
    assert view._result['stage']=='worker_start'
    view._export_to(tmp_path/'worker.zip');wait(lambda:not view._exporting)
    inspect(tmp_path/'worker.zip')


def test_reopen_while_exporting_cannot_start_a_conflicting_job(dialog,tmp_path,monkeypatch):
    view,store,owner=dialog
    wait(lambda:not view._loading)
    original=bundle.export_report;entered=threading.Event();gate=threading.Event();calls=[]
    def delayed(*args,**kwargs):
        calls.append(1);entered.set()
        assert gate.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(bundle,'export_report',delayed)
    view.close();wait(lambda:view._jobs==0)
    # Each dialog captures its exporter on construction.
    view=ui.open_support_dialog(owner)
    target=tmp_path/'inflight.zip'
    view._export_to(target);wait(entered.is_set);view.close()
    reopened=ui.open_support_dialog(owner)
    try:
        assert not reopened.export.isEnabled()
        reopened._export_to(target)
        assert len(calls)==1
        gate.set();wait(lambda:not view._exporting)
        inspect(target)
        reopened._tick()
        assert reopened.export.isEnabled()
        reopened._export_to(target);wait(lambda:not reopened._exporting)
        assert inspect(target)['report_id']==reopened.identity.text()
    finally:
        gate.set();reopened.close();wait(lambda:reopened._jobs==0)


@pytest.mark.parametrize('stage',['zip_packaging','zip_verification','atomic_publication'])
def test_fault_does_not_replace_old_target_or_leave_temporary_file(tmp_path,monkeypatch,stage):
    target=tmp_path/'existing.zip';target.write_bytes(b'original target')
    if stage=='zip_packaging':
        def fail(*a,**k):raise OSError(errno.ENOSPC,'disk full')
        monkeypatch.setattr(zipfile.ZipFile,'writestr',fail)
    elif stage=='zip_verification':
        monkeypatch.setattr(zipfile.ZipFile,'testzip',lambda *a:'manifest.json')
    else:
        def fail(*a,**k):raise PermissionError(errno.EACCES,'target in use')
        monkeypatch.setattr(bundle.os,'replace',fail)
    with pytest.raises(OSError) as raised:
        bundle.export_report(target,root=tmp_path/'empty',report={'report_id':'report-test'})
    assert bundle.export_failure_details(raised.value)['stage']==stage
    assert target.read_bytes()==b'original target' and not list(tmp_path.glob('*.tmp'))


def test_bad_optional_record_and_missing_session_preserve_other_information(tmp_path):
    root=tmp_path/'logs';folder=root/'session-bad';folder.mkdir(parents=True)
    (folder/'session.json').write_text('{broken','utf8')
    other=root/'lost-metadata';other.mkdir()
    (other/'events.jsonl').write_text('invalid\n','utf8')
    target=tmp_path/'bad.zip'
    bundle.export_report(target,root=root,content=[None,{'subtitle_id':'good','text':'explicit content'}])
    manifest=inspect(target)
    assert manifest['status']=='partial'
    reasons={m['reason'] for m in manifest['missing']}
    assert {'JSONDecodeError','missing_session_metadata','invalid_selected_record'}.issubset(reasons)


def test_structurally_bad_log_fields_do_not_break_other_events(tmp_path):
    from twobyteasr.diagnostics.event_log import now
    root=tmp_path/'logs';folder=root/'session';folder.mkdir(parents=True)
    (folder/'session.json').write_text(json.dumps(dict(session_id='session',status='closed')),'utf8')
    good=dict(event_name='valid.fixture',time=now(),level='INFO',result='observed',session_id='session')
    rows=[dict(good,level=[]),dict(good,task_id=['bad']),good]
    (folder/'events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),'utf8')
    target=tmp_path/'mixed.zip'
    bundle.export_report(target,root=root)
    manifest=inspect(target)
    assert manifest['status']=='partial' and manifest['serialized_event_count']==1
    assert sum(m['reason']=='invalid_or_partial_line' for m in manifest['missing'])==2
