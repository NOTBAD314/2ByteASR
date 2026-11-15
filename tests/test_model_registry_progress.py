import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace


def test_slow_or_failed_model_does_not_hold_other_model_results(tmp_path,monkeypatch):
    from twobyteasr.local_models import model_registry as module
    root=tmp_path/'models'
    specs={key:{'path':'models/'+key,'required_files':['weights.bin']} for key in ('slow','fast','failed','other')}
    (tmp_path/'dependencies.lock.json').write_text(json.dumps({'models':specs}),encoding='utf8')
    for key in specs:
        (root/key).mkdir(parents=True)
        (root/key/'weights.bin').write_bytes(b'fixture')
    release=threading.Event()
    fast_ready=threading.Event()
    snapshots=[]
    original=module._locate_model_folder
    def locate(spec_path,**kwargs):
        name=Path(spec_path).name
        if name=='slow':
            assert release.wait(3)
        if name=='failed':
            raise PermissionError('controlled single-model failure')
        return root/name,'model_root'
    monkeypatch.setattr(module,'_locate_model_folder',locate)
    def progress(snapshot):
        snapshots.append(snapshot)
        if 'fast' in snapshot.installed_keys() and 'other' in snapshot.installed_keys():
            fast_ready.set()
    final=[]
    thread=threading.Thread(target=lambda:final.append(module.scan_model_registry(
        install_root=tmp_path,model_root=root,paths=SimpleNamespace(install_root=tmp_path,model_root=root),
        on_progress=progress,workers=2)),daemon=True)
    thread.start()
    try:
        assert fast_ready.wait(2)
        assert thread.is_alive()
        partial=snapshots[-1]
        assert 'slow' in partial.pending_keys
        assert partial.records['failed'].health==module.ModelHealth.UNREADABLE
        assert set(partial.installed_keys())=={'fast','other'}
        frozen_keys=set(partial.records)
        release.set()
        thread.join(3)
        assert not thread.is_alive() and not final[0].pending_keys
        assert set(final[0].installed_keys())=={'slow','fast','other'}
        assert set(partial.records)==frozen_keys  # published snapshots stay immutable
    finally:
        release.set()
