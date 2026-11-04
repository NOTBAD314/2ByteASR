import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from twobyteasr.recognition.service import RunOptions
from twobyteasr.recognition.task_journal import (
    TaskJournal, TaskBusy, history_paths, read_record, reconcile, resume_options,
)


def make(tmp_path, name='task1'):
    media=tmp_path/'source.wav'
    media.write_bytes(b'original input')
    options=RunOptions(job_id=name,settings_snapshot_json=json.dumps({'models':{'api_key':'DO-NOT-PERSIST',
        'qwen_asr_api_key_env':'ASR_KEY','group_model':'chosen-model'}}))
    return TaskJournal(name,tmp_path/'recognition-tasks').create([str(media)],options)


def test_created_before_any_executor_with_public_snapshot(tmp_path):
    journal=make(tmp_path)
    raw=journal.path.read_text(encoding='utf-8')
    raw+=''.join(p.read_text(encoding='utf-8') for p in journal.directory.glob('configuration-*.json'))
    assert 'DO-NOT-PERSIST' not in raw
    assert 'ASR_KEY' in raw and 'chosen-model' in raw
    assert read_record(journal.path)['status']=='queued'
    assert read_record(journal.path)['task']['inputs'][0]['size']==14


def test_os_lease_prevents_second_takeover_and_survives_stale_heartbeat(tmp_path):
    journal=make(tmp_path).acquire()
    try:
        journal.record['task']['heartbeat_at']='1990-01-01'
        journal._save()
        with pytest.raises(TaskBusy):
            TaskJournal(journal.job_id,journal.directory.parent).acquire(resume=True)
        assert reconcile(journal.path)['status']=='running'
    finally:journal.close()
    assert reconcile(journal.path)['status']=='interrupted'


def test_killed_executor_remains_visible_and_can_resume_same_identity(tmp_path):
    journal=make(tmp_path)
    script=('import os;from twobyteasr.recognition.task_journal import TaskJournal;'
            'j=TaskJournal("task1",os.environ["CASE_ROOT"]);j.acquire();'
            'j.publish("asr:0",{"text":"saved"},{"pcm":"a"});os._exit(23)')
    env=dict(os.environ,CASE_ROOT=str(journal.directory.parent))
    child=subprocess.run([sys.executable,'-c',script],env=env,timeout=20)
    assert child.returncode==23
    row=reconcile(journal.path)
    assert row['status']=='interrupted'
    assert list(history_paths(journal.directory.parent))==[journal.path]
    journal.acquire(resume=True)
    try:
        assert journal.load_artifact('asr:0',{'pcm':'a'})=={'text':'saved'}
        assert len(journal.record['task']['attempts'])==2
    finally:journal.close()


def test_published_artifact_adopted_after_receipt_write_failure(tmp_path,monkeypatch):
    journal=make(tmp_path).acquire()
    try:
        monkeypatch.setattr(journal,'_save',lambda **kw:(_ for _ in ()).throw(OSError('disk full')))
        with pytest.raises(OSError):journal.publish('align:2',{'words':[1,2]}, {'asr':'a'})
        reopened=TaskJournal('task1',journal.directory.parent)
        assert reopened.load_artifact('align:2',{'asr':'a'})=={'words':[1,2]}
        assert reopened.load_artifact('align:2',{'asr':'changed'}) is None
    finally:journal.close()


def test_incomplete_and_tampered_artifact_not_accepted(tmp_path):
    journal=make(tmp_path).acquire()
    try:
        artifact=journal.publish('part:0',{'text':'good'}, {'input':'a'})
        row=json.loads(artifact.read_text(encoding='utf-8'))
        row['payload']['text']='changed'
        artifact.write_text(json.dumps(row),encoding='utf-8')
        assert journal.load_artifact('part:0',{'input':'a'}) is None
        artifact.write_text('{"payload":',encoding='utf-8')
        assert journal.load_artifact('part:0',{'input':'a'}) is None
    finally:journal.close()


def test_cancelled_not_automatically_resumed_after_restart(tmp_path):
    journal=make(tmp_path).acquire()
    journal.finish(status='cancelled');journal.close()
    assert reconcile(journal.path)['status']=='cancelled'
    with pytest.raises(TaskBusy):journal.acquire()
    options,paths=resume_options(journal.path,{'models':{'api_key':'fresh-secret'}})
    assert options.resume and options.job_id=='task1'
    assert not options.force_refresh_polish and not options.force_refresh_group
    assert json.loads(options.settings_snapshot_json)['models']['api_key']=='fresh-secret'


def test_corrupt_record_isolated_and_previous_commit_remains_usable(tmp_path):
    one=make(tmp_path,'one').acquire()
    one.finish(status='interrupted');one.close()
    two=make(tmp_path,'two')
    one.path.write_text('{broken',encoding='utf-8')
    assert read_record(one.path)['job_id']=='one'
    assert set(history_paths(one.directory.parent))=={one.path,two.path}


def test_final_report_failure_retains_final_payload(tmp_path):
    journal=make(tmp_path).acquire()
    journal.publish('delivery:1',{'cues':[{'text':'result'}]}, {'input':'a','rules':1})
    journal.finish(status='failed',error='report index unavailable');journal.close()
    journal.acquire(resume=True)
    try:
        assert journal.load_artifact('delivery:1',{'input':'a','rules':1})['cues'][0]['text']=='result'
    finally:journal.close()
