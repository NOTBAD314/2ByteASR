from pathlib import Path
import multiprocessing
import os

from twobyteasr.test_isolation import install, isolation_root
install()
from PySide6.QtCore import QSettings


def spawned_settings(queue):
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtCore import QSettings
    setting=QSettings('2ByteASR','2ByteASR')
    setting.setValue('cover/spawn-proof','child');setting.sync()
    queue.put(setting.fileName())


def test_explicit_namespaces_and_spawn_are_isolated():
    root=isolation_root()
    parent=QSettings('2ByteASR','2ByteASR')
    other=QSettings('2ByteASR','ModelWorkshop')
    assert Path(parent.fileName()).is_relative_to(root)
    assert parent.fileName()!=other.fileName()
    parent.setValue('cover/test-directory','中文目录');parent.sync()
    context=multiprocessing.get_context('spawn');queue=context.Queue()
    process=context.Process(target=spawned_settings,args=(queue,));process.start()
    child=queue.get(timeout=20);process.join(20)
    assert process.exitcode==0 and child==parent.fileName()
    parent.sync();assert parent.value('cover/spawn-proof')=='child'
    assert other.value('cover/spawn-proof') is None
    queue.close();queue.join_thread()


def test_source_config_does_not_migrate_user_settings():
    from twobyteasr.storage.settings import stable_settings_root,_legacy_settings_candidates
    assert stable_settings_root()==isolation_root()/'config'
    assert _legacy_settings_candidates()==[]
    assert not any(k.endswith('_API_KEY') for k in os.environ)


def test_nonexecuting_stage_never_claims_worker_start(tmp_path):
    from types import SimpleNamespace
    from moss_firered_pipeline import _run_audited_model_stage
    events=[]
    legacy=SimpleNamespace(record_run_event=lambda event,**kw:events.append((event,kw)))
    _run_audited_model_stage(legacy,model_id='cached',role='primary',backend='cache',
        media_path='offline.wav',worker='',runtime='',runner=lambda:[{'text':'已有结果'}])
    assert 'MODEL_STARTED' not in [event for event,_ in events]
    entered=next(kw for event,kw in events if event=='MODEL_STAGE_ENTERED')
    assert entered['execution']=='stage_entered_not_worker_start'
