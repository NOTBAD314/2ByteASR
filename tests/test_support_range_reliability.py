"""Stale date controls and corrupt optional records cannot hide a report."""
from datetime import datetime, timedelta, timezone
import json
import zipfile
from twobyteasr.diagnostics.event_log import EventStore
from twobyteasr.diagnostics.support_bundle import collect, export_report
from twobyteasr.diagnostics.support_triage import analyze


def test_recent_export_ignores_stale_hidden_range_controls(tmp_path):
    store=EventStore(tmp_path/'logs')
    try:
        store.record('caption.edit_rejected',dict(edit_session_id='edit-123',reason_code='text_conflict',result='retained'))
        stale=(datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat()
        result=export_report(tmp_path/'report.zip',root=store.root,instance=store,scope='recent',end=stale)
        with zipfile.ZipFile(result['target']) as archive:
            assert archive.testzip() is None
            assert b'edit-123' in archive.read('events.jsonl')
    finally:store.close_store(clean=True)


def test_old_project_provenance_is_separate_from_visible_range(tmp_path):
    old_store=EventStore(tmp_path/'logs')
    old_store.record('data.commit',dict(project_id='one',task_id='old-task'))
    old_store.close_store(clean=True)
    file=old_store.directory/'events.jsonl'
    old=datetime.now(timezone.utc)-timedelta(days=1)
    rows=[json.loads(line) for line in file.read_text('utf8').splitlines()]
    for row in rows:row['time']=old.isoformat()
    file.write_text(''.join(json.dumps(r)+'\n' for r in rows),'utf8')
    store=EventStore(tmp_path/'logs')
    try:
        store.record('problem.marked',dict(project_id='one'))
        data=collect(store.root,instance=store,scope='recent')
        analysis=analyze(data)
        assert analysis.end-analysis.start < 900
        assert data['context_events'] and not any(r.get('task_id')=='old-task' for r in data['events'])
        result=export_report(tmp_path/'report.zip',root=store.root,instance=store,scope='recent')
        with zipfile.ZipFile(result['target']) as archive:
            assert b'old-task' in archive.read('events.jsonl')
            assert json.loads(archive.read('manifest.json'))['context_event_count']>0
    finally:store.close_store(clean=True)


def test_damaged_range_still_exports_minimum_marked_report(tmp_path):
    root=tmp_path/'logs'; folder=root/'session'; folder.mkdir(parents=True)
    (folder/'session.json').write_text(json.dumps(dict(session_id='s',status='ended',build={})), 'utf8')
    (folder/'events.jsonl').write_bytes(b'{bad json}\n')
    result=export_report(tmp_path/'partial.zip',root=root,report=dict(report_id='report-known',marked_at=datetime.now(timezone.utc).isoformat()))
    with zipfile.ZipFile(result['target']) as archive:
        assert archive.testzip() is None
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['status']=='partial' and manifest['missing']
        assert b'report-known' in archive.read('README.txt')


def test_output_budget_preserves_latest_correlated_failure(tmp_path,monkeypatch):
    from twobyteasr.diagnostics import support_bundle as module
    monkeypatch.setattr(module,'MAX_EXPORT_BYTES',512*1024)
    monkeypatch.setattr(module,'MAX_EVENTS_BYTES',256*1024)
    store=EventStore(tmp_path/'logs')
    try:
        for index in range(300):
            store.record('technical.sample',dict(technical_blob='measured stage 0123456789 '*35,index=index))
        store.record('caption.edit_rejected',dict(level='ERROR',edit_session_id='last-failure',reason_code='text_conflict'))
        target=tmp_path/'previous.zip';target.write_bytes(b'previous intact')
        result=export_report(target,root=store.root,instance=store,scope='session')
        with zipfile.ZipFile(result['target']) as archive:
            assert archive.testzip() is None and b'last-failure' in archive.read('events.jsonl')
            manifest=json.loads(archive.read('manifest.json'))
            assert manifest['status']=='partial' and manifest['losses']['export_events_omitted_by_budget']>0
    finally:store.close_store(clean=True)


def test_bad_export_manifest_retains_other_jobs_without_subtitle_bodies(tmp_path):
    root=tmp_path/'user/logs/diagnostic-sessions';store=EventStore(root)
    job='a'*32;export_root=tmp_path/'user/SubtitleStudioPreview/logs/exports'/job
    good=export_root/'good/manifest.json';good.parent.mkdir(parents=True)
    good.write_text(json.dumps(dict(job_id=job,runtime=dict(app_version='0.9.0',git_sha='confirmed',translation='PRIVATE_BODY'),
        settings=dict(encoder='libx264',translation='PRIVATE_BODY'),cues=[dict(text='PRIVATE_BODY')])), 'utf8')
    bad=export_root/'bad/manifest.json';bad.parent.mkdir();bad.write_text('[]','utf8')
    try:
        store.record('video.export.completed',dict(task_id=job,result='completed'))
        result=export_report(tmp_path/'report.zip',root=root,instance=store,scope='session')
        with zipfile.ZipFile(result['target']) as archive:
            names=[name for name in archive.namelist() if name.startswith('exports/')]
            assert len(names)==1 and b'PRIVATE_BODY' not in archive.read(names[0])
            assert b'confirmed' in archive.read(names[0])
            manifest=json.loads(archive.read('manifest.json'))
            assert manifest['status']=='partial' and any(row.get('stage')=='export_manifest' for row in manifest['missing'])
    finally:store.close_store(clean=True)
