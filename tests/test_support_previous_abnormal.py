import json
from datetime import datetime, timezone, timedelta
import zipfile

from twobyteasr.diagnostics.event_log import EventStore
from twobyteasr.diagnostics import support_bundle


def test_recent_export_keeps_previous_abnormal_tail_without_shared_project(tmp_path,monkeypatch):
    root=tmp_path/'logs'
    prior=root/'session-previous'
    prior.mkdir(parents=True)
    old=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
    (prior/'session.json').write_text(json.dumps(dict(session_id=prior.name,pid=999999,
        status='running',started=old,build={'channel':'fixture-prior'})),encoding='utf8')
    row=dict(event_name='studio.open.stage',session_id=prior.name,time=old,sequence=7,
        stage='创建工作台界面',result='started',level='INFO')
    (prior/'events.jsonl').write_text(json.dumps(row)+'\n',encoding='utf8')
    (prior/'native-fault.txt').write_text('Windows fatal exception: access violation\n',encoding='utf8')
    monkeypatch.setattr(support_bundle,'_alive',lambda _:False)
    store=EventStore(root)
    try:
        store.record('healthy.current',dict(result='observed'))
        result=support_bundle.export_report(tmp_path/'recent.zip',root=root,instance=store,scope='recent')
        with zipfile.ZipFile(result['target']) as archive:
            rows=[json.loads(x) for x in archive.read('events.jsonl').splitlines()]
            oldrow=next(r for r in rows if r['event_name']=='studio.open.stage')
            assert oldrow['previous_abnormal_tail'] is True
            assert oldrow['context_only'] is True
            metadata=json.loads(archive.read('environment.json'))
            previous=next(s for s in metadata['sessions'] if s['session_id']==prior.name)
            assert previous['status']=='previous_not_cleanly_ended'
            assert previous['exit_code']=='unknown'
            assert any(n.startswith('crash/session-previous') for n in archive.namelist())
    finally:
        store.close_store(clean=True)
