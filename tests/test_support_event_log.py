import json
import threading
import time
import zipfile
from pathlib import Path

import pytest

from twobyteasr.diagnostics.event_log import EventStore, Sanitizer, exception_info
from twobyteasr.diagnostics.support_bundle import collect, export_report, maintain_sessions, summary

def test_short_playback_capture_is_included_and_sanitized(tmp_path):
    store=EventStore(tmp_path/'logs')
    try:
        store.record('playback.short_capture',dict(seconds=15))
        store.playback_capture={'performance_pass':'UNVERIFIED','api_key':'FAKE_CAPTURE_SECRET',
            'identity':{'git_sha':'candidate'},'ui_delay_ms':{'p95':2.0}}
        result=export_report(tmp_path/'capture.zip',root=store.root,instance=store,scope='session')
        with zipfile.ZipFile(result['target']) as archive:
            body=archive.read('playback-diagnostic.json')
            assert b'FAKE_CAPTURE_SECRET' not in body
            assert json.loads(body)['performance_pass']=='UNVERIFIED'
    finally:store.close_store(clean=True)


def test_http_header_spellings_and_full_auth_lines_are_private_on_disk_and_in_zip(tmp_path):
    store=EventStore(tmp_path/'logs')
    secrets=['FAKE_AZURE_HEADER','FAKE_PROXY_HEADER','FAKE_SUBSCRIPTION_HEADER',
             'FAKE_CAMEL_HEADER','FAKE_BASIC_PAYLOAD','FAKE_COOKIE_A','FAKE_COOKIE_B','FAKE_REQUEST_BODY',
             'FAKE_LIST_HEADER','FAKE_KEY_VALUE_HEADER','FAKE_CUSTOM_HEADER']
    store.record('header.fixture',dict(headers={
        'X-API-Key':secrets[0],'Proxy-Authorization':'Basic '+secrets[1],
        'Ocp-Apim-Subscription-Key':secrets[2],'apiKey':secrets[3],
        'X-Custom-Provider':secrets[10],
        'X-Request-ID':'public-correlation'},
        note='Proxy-Authorization: Basic '+secrets[4]+'\nCookie: sid='+secrets[5]+'; second='+secrets[6],
        request_headers=[{'name':'X-API-Key','value':secrets[8]},
                         {'key':'Proxy-Authorization','value':'Basic '+secrets[9]}],
        parameter={'name':'Azure header','key':'api-key','value':secrets[0]},
        body=secrets[7],body_characters=17,http_status=401))
    snapshot=store.snapshot()
    on_disk=b'\n'.join(body for name,body in snapshot['files'].items() if name.endswith(('.jsonl','.log')))
    report=export_report(tmp_path/'headers.zip',root=store.root,instance=store,scope='session')
    store.close_store(clean=True)
    with zipfile.ZipFile(report['target']) as archive:
        shared=b'\n'.join(archive.read(name) for name in archive.namelist())
        for secret in secrets:
            assert secret.encode() not in on_disk
            assert secret.encode() not in shared
        row=next(json.loads(line) for line in archive.read('events.jsonl').splitlines()
                 if json.loads(line)['event_name']=='header.fixture')
        assert row['headers']['X-Request-ID']=='public-correlation'
        assert row['http_status']==401 and row['body_characters']==17


def test_input_timing_samples_are_bounded_until_detailed_mode(tmp_path):
    store=EventStore(tmp_path/'logs')
    try:
        for index in range(20):
            store.record('INPUT_RECEIVED',dict(input_id=index,operation='key'))
        assert sum(r['kind']=='INPUT_RECEIVED' for r in store.recent)==1
        assert store.losses['sampled_events']==19
        store.set_detailed(600)
        for index in range(3):
            store.record('INPUT_RECEIVED',dict(input_id=20+index,operation='key'))
        assert sum(r['kind']=='INPUT_RECEIVED' for r in store.recent)==4
    finally:
        store.close_store(clean=True)


def test_summary_excludes_media_length_and_retains_late_failures_and_merge(tmp_path):
    store=EventStore(tmp_path/'logs')
    store.record('MEDIA',dict(duration_ms=12000,sample_rate=0,channels=0))
    store.record('operation.end',dict(operation_id='op-edit',action='cue.edit',duration_ms=400,result='completed'))
    for i in range(12):
        store.record('process.failure',dict(result='failed',purpose='encoder probe',exit_code=7))
    store.record('ai.validation',dict(result='failed',project_id='fixture',task_id='task-ai',
        error_code='parse_failure',rule_detail='回應不是合法 JSON',exception={'chain':[{'type':'GroupingContractError','frames':[{'module':'grouping_contract.py','line':250,'function':'parse_grouping_response'}]}]}))
    store.record('data.commit',dict(operation_id='op-merge',translation_decision='inspect_validity',
        before={'cue_count':3,'valid_translation_sample_count':2},after={'cue_count':2,'valid_translation_sample_count':0}))
    for i in range(8):
        store.record('data.commit',dict(operation_id=f'op-later-{i}',translation_decision='inspect_validity',
            before={'cue_count':2},after={'cue_count':2}))
    store.record('background.start',dict(task_id='task-incomplete'))
    store.record('process.start',dict(child_operation_id='child-incomplete'))
    store.record('problem.marked',dict(project_id='fixture'))
    data=collect(store.root,instance=store,scope='session')
    note=summary(data,'report-test')
    media=next(r for r in data['events'] if r['event_name']=='media')
    assert media['duration_ms'] is None and media['media_duration_ms']==12000
    assert media['sample_rate'] is None and media['channels'] is None
    assert '修改字幕用了 0.40 秒' in note and '12000' not in note and '12 秒' not in note
    assert '（12 次）' in note and 'task-ai' in note and 'GroupingContractError' in note
    assert 'grouping_contract.py:250' in note and 'op-merge' in note and '有效译文从 2 条变成 0 条' in note
    running = next(line for line in note.splitlines() if line.startswith('【仍在执行】'))
    assert 'child-incomplete' in running and 'task-incomplete' in running
    store.close_store(clean=True)


def test_render_fingerprints_are_keyed_and_export_scrub_is_idempotent():
    first=Sanitizer(b'a'*32);second=Sanitizer(b'b'*32)
    raw={'snapshot_hash':'f'*64}
    clean=first.clean(raw)
    assert clean['snapshot_hash'].startswith('fingerprint-')
    assert clean!=second.clean(raw)
    assert first.clean(clean)==clean


def test_one_source_readable_and_json_privacy(tmp_path):
    store=EventStore(tmp_path/'logs')
    store.record('data.commit',dict(project_id='private-project',subtitle_id='cue-1',text='PRIVATE_SUBTITLE',
        api_key='FAKE_SECRET',url='https://bob:password@host.test/p?X-Amz-Signature=SIGNATURE',
        target_path='D:/Private Person/Secret Movie.mp4',details='Authorization: Bearer sk-FAKESECRET12345',result='completed'))
    store.close_store(clean=True)
    result=export_report(tmp_path/'report.zip',root=store.root,instance=store,scope='session')
    with zipfile.ZipFile(result['target']) as z:
        blob=b'\n'.join(z.read(n) for n in z.namelist())
        for secret in (b'PRIVATE_SUBTITLE',b'FAKE_SECRET',b'FAKESECRET',b'SIGNATURE',b'Secret Movie',b'private-project',b'bob:'):
            assert secret not in blob
        rows=[json.loads(line) for line in z.read('events.jsonl').splitlines()]
        assert rows[0]['project_id'].startswith('project-')
        assert rows[0]['event_name']=='data.commit'
        assert rows[0]['message'].encode() in z.read('readable.log')
        assert json.loads(z.read('manifest.json'))['event_count']==len(rows)


def test_rotation_is_whole_lines_and_snapshot_has_cutoff(tmp_path):
    store=EventStore(tmp_path/'logs',file_bytes=1600)
    for i in range(45):store.record('data.commit',dict(index=i,result='completed'))
    snapshot=store.snapshot()
    assert snapshot['cutoff']==45
    rows=[json.loads(line) for name,body in snapshot['files'].items() if name.endswith('.jsonl') for line in body.splitlines()]
    assert rows and max(r['sequence'] for r in rows)<=45
    assert store.losses['rotated_files']>0
    assert len(list(store.directory.glob('events*.jsonl')))<=7
    store.close_store(clean=True)


def test_failed_write_does_not_block_producer_and_manifest_reports(tmp_path,monkeypatch):
    original=Path.open
    store=EventStore(tmp_path/'logs')
    def denied(path,*args,**kwargs):
        if path.name=='events.jsonl':raise PermissionError('test')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',denied)
    started=time.monotonic()
    for i in range(50):store.record('operation.start',dict(index=i))
    assert time.monotonic()-started<1
    store.snapshot()
    assert store.write_error=='PermissionError'
    assert store.losses['write_failed']>0
    with pytest.raises(ValueError,match='沒有可用事件'):
        export_report(tmp_path/'empty.zip',root=store.root,instance=store)
    assert not (tmp_path/'empty.zip').exists()
    store.close_store(clean=False)


def test_queue_pressure_keeps_error_over_debug(tmp_path,monkeypatch):
    gate=threading.Event()
    original=EventStore._write
    def delayed(self):gate.wait(3);original(self)
    monkeypatch.setattr(EventStore,'_write',delayed)
    store=EventStore(tmp_path/'logs',capacity=8)
    store.set_detailed(600)
    for i in range(40):store.record('sample',dict(level='DEBUG',index=i))
    store.record('python.exception',dict(level='ERROR',error_code='injected',result='failed'))
    gate.set();snapshot=store.snapshot()
    assert store.dropped>0
    assert b'injected' in b''.join(snapshot['files'].values())
    store.close_store(clean=True)


def test_exception_chain_keeps_location_without_body():
    try:
        try:raise ValueError('PRIVATE_SUBTITLE')
        except ValueError as exc:raise RuntimeError('sk-FAKESECRET000') from exc
    except RuntimeError as exc:info=exception_info(exc)
    assert [r['type'] for r in info['chain']]==['RuntimeError','ValueError']
    assert info['chain'][0]['frames'][-1]['line']>0
    assert 'PRIVATE' not in json.dumps(info) and 'FAKESECRET' not in json.dumps(info)


def test_detail_expiry_never_enables_content(tmp_path):
    store=EventStore(tmp_path/'logs');store.set_detailed(.01);time.sleep(.02)
    assert not store.detailed
    store.record('data.commit',dict(text='SECRET_BODY'))
    snapshot=store.snapshot();assert b'SECRET_BODY' not in b''.join(snapshot['files'].values())
    store.close_store(clean=True)


def test_upstream_task_retained_and_explicit_content(tmp_path):
    root=tmp_path/'logs'
    old=EventStore(root);old.record('ai.validation',dict(task_id='task-one',project_id='project-one',result='failed'))
    old.close_store(clean=True)
    new=EventStore(root);new.record('problem.marked',dict(project_id='project-one',result='observed'))
    result=export_report(tmp_path/'report.zip',root=root,instance=new,scope='session',
        content=[dict(subtitle_id='cue-1',text='使用者明確選取',translation='api_key=FAKE_KEY')])
    with zipfile.ZipFile(result['target']) as z:
        assert b'task-one' in z.read('events.jsonl')
        assert '使用者明確選取' in z.read('selected-content.json').decode()
        assert b'FAKE_KEY' not in z.read('selected-content.json')
    new.close_store(clean=True)


def test_export_failure_preserves_existing_target(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'logs');store.record('test',{})
    target=tmp_path/'existing.zip';target.write_bytes(b'previous')
    monkeypatch.setattr(zipfile.ZipFile,'writestr',lambda *a,**k:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):export_report(target,root=store.root,instance=store)
    assert target.read_bytes()==b'previous'
    assert not list(tmp_path.glob('*.tmp'))
    store.close_store(clean=True)


def test_retention_never_removes_running_peer(tmp_path):
    one=EventStore(tmp_path/'logs');two=EventStore(one.root)
    one.record('test',{});one.close_store(clean=True)
    # A closed session can be pruned; an active peer cannot.
    maintain_sessions(one.root,current=two.directory,clear=True)
    assert not one.directory.exists() and two.directory.exists()
    two.close_store(clean=True)


def test_rotation_failure_and_formatter_failure_are_visible_not_raised(tmp_path,monkeypatch):
    store=EventStore(tmp_path/'logs',file_bytes=800)
    original=store.sanitizer.clean
    monkeypatch.setattr(store.sanitizer,'clean',lambda *a,**k:(_ for _ in ()).throw(ValueError('format failed')))
    store.record('sample',{})
    assert store.losses['format_failed']==1
    monkeypatch.setattr(store.sanitizer,'clean',original)
    monkeypatch.setattr(store,'_rotate',lambda:(_ for _ in ()).throw(PermissionError('rotation denied')))
    for i in range(8):store.record('operation.end',dict(result='completed',index=i))
    store.snapshot()
    assert store.losses['write_failed'] and store.write_error=='PermissionError'
    result=export_report(tmp_path/'partial.zip',root=store.root,instance=store,scope='session')
    assert result['status']=='partial'
    store.close_store(clean=False)


def test_storm_budget_preserves_first_error_and_counts_suppression(tmp_path):
    store=EventStore(tmp_path/'logs')
    for i in range(100):store.record('controlled.failure',dict(level='ERROR',error_code='same',index=i))
    snapshot=store.snapshot()
    assert store.losses['storm_suppressed']>=80
    rows=[json.loads(line) for name,body in snapshot['files'].items() if name.endswith('.jsonl') for line in body.splitlines()]
    assert rows[0]['index']==0 and len(rows)<=20
    store.close_store(clean=True)


def test_native_and_hang_export_never_copies_private_paths(tmp_path):
    store=EventStore(tmp_path/'logs'/'diagnostic-sessions')
    store.record('problem.marked',{})
    import os
    (store.root.parent/f'gui-hang-{os.getpid()}.txt').write_text('Timeout (0:00:02)!\n  File "C:/PrivateUser/PrivateMovie/worker.py", line 42 in blocked\napi_key=DO_NOT_COPY\n',encoding='utf8')
    result=export_report(tmp_path/'hang.zip',root=store.root,instance=store,scope='session')
    with zipfile.ZipFile(result['target']) as z:
        content=z.read(next(n for n in z.namelist() if n.endswith('-hang.txt'))).decode()
        assert 'worker.py' in content and '42' in content
        assert 'PrivateUser' not in content and 'DO_NOT_COPY' not in content
    store.close_store(clean=True)


def test_simultaneous_sessions_share_alias_key(tmp_path):
    barrier=threading.Barrier(4);stores=[];errors=[]
    def start():
        try:
            barrier.wait();stores.append(EventStore(tmp_path/'logs'))
        except Exception as exc:errors.append(type(exc).__name__)
    threads=[threading.Thread(target=start) for _ in range(4)]
    for t in threads:t.start()
    for t in threads:t.join()
    try:
        assert not errors and len(stores)==4
        assert len({s.sanitizer.alias('same private project','project') for s in stores})==1
        assert len({s.directory for s in stores})==4
    finally:
        for s in stores:s.close_store(clean=True)
