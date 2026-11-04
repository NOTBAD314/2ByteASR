"""Tiny isolated producer/consumer fixtures; no browser, ASR or providers."""
import builtins
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.rendering.advanced_preview import AdvancedPreviewCache
from twobyteasr.storage.storage_service import StorageService


def _set_used(service, path, used):
    with service._db() as db:
        db.execute('UPDATE entries SET used=? WHERE path=?', (used, str(path.absolute())))


def _owned(cache, key, pixels=b'png!'):
    cache.root.mkdir(parents=True, exist_ok=True)
    target=cache.root/(key+'.png');target.write_bytes(pixels)
    assert cache.path_for(key)==target
    return target


def test_preview_budget_uses_owned_last_use_and_preserves_unknown_partial(tmp_path):
    cache=AdvancedPreviewCache(tmp_path/'preview');cache.budget_bytes=4
    assert cache._storage.roots==(cache.root,)
    assert cache._storage.state_root==cache.root/'.storage'
    older=_owned(cache,'older');newer=_owned(cache,'newer')
    _set_used(cache._storage,older,time.time()-100)
    _set_used(cache._storage,newer,time.time()-10)
    # Filesystem access times disagree with the authoritative usage index.
    os.utime(older,(time.time(),time.time()))
    os.utime(newer,(1,1))
    protected=[cache.root/'authored.png',cache.root/'working.png.part',cache.root/'zero.png']
    for path in protected:path.write_bytes(b'other' if path.name!='zero.png' else b'')
    cache.path_for('zero')
    cache.enforce_budget()
    assert not older.exists() and newer.exists()
    assert all(path.exists() for path in protected)


def test_preview_budget_skips_live_lease_and_read_hit_updates_usage(tmp_path):
    cache=AdvancedPreviewCache(tmp_path/'preview');cache.budget_bytes=4
    held=_owned(cache,'held');other=_owned(cache,'other')
    _set_used(cache._storage,held,time.time()-100)
    with cache._lease(held):
        cache.enforce_budget()
        assert held.exists() and not other.exists()
        item=next(item for item in cache._storage.scan(include_models=False).items if item.path==str(held))
        assert not item.cleanable
    _set_used(cache._storage,held,1)
    cache.path_for('held')
    item=next(item for item in cache._storage.scan(include_models=False).items if item.path==str(held))
    assert item.last_used>time.time()-10


def test_preview_link_and_shared_hardlink_survive_budget(tmp_path):
    cache=AdvancedPreviewCache(tmp_path/'preview');cache.root.mkdir()
    asset=tmp_path/'authored.png';asset.write_bytes(b'asset')
    link=cache.root/'linked.png'
    try:link.symlink_to(asset)
    except OSError:pytest.skip('Symbolic links unavailable to this test process')
    shared=cache.root/'shared.png';os.link(asset,shared)
    cache._storage.register(shared,'preview',producer='advanced_preview')
    cache.budget_bytes=1;cache.enforce_budget()
    assert asset.read_bytes()==b'asset' and link.is_symlink() and shared.exists()
    with pytest.raises(ValueError,match='link'):cache.path_for('linked')
    with pytest.raises(ValueError,match='leaf'):cache.path_for('../authored')
    root_link=tmp_path/'linked-root';root_link.symlink_to(cache.root,target_is_directory=True)
    linked_cache=AdvancedPreviewCache(root_link);linked_cache.budget_bytes=1
    linked_cache.enforce_budget()
    with pytest.raises(ValueError,match='link'):linked_cache.path_for('shared')
    assert asset.read_bytes()==b'asset' and shared.exists()


@pytest.mark.parametrize('mode',['legacy','snapshot','batch'])
def test_every_preview_render_contract_leases_target_until_budget_finishes(tmp_path,monkeypatch,mode):
    from twobyteasr.rendering import advanced_preview as module
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    project=SubtitleProject(media=StudioMedia(path='fixture.mp4',duration_ms=1000),
        cues=[StudioCue('cue',0,1000,'isolated')])
    snapshot=build_visual_cue_snapshot(project,'cue',width=64,height=36)
    monkeypatch.setattr(module.AdvancedRendererBackend,'require_available',lambda self:None)
    checked=[]
    cache=AdvancedPreviewCache(tmp_path/'preview');cache.budget_bytes=1
    class Renderer:
        def render(self,jobs,**kwargs):
            for job in jobs:
                target=Path(job.output);target.write_bytes(b'part')
                registered,live=cache._storage._registered()
                assert str(target) in live
                checked.append(str(target))
                cache.enforce_budget()
                assert target.is_file()
                target.write_bytes(b'png!')
            return SimpleNamespace(require_job=lambda job:None)
    cache.renderer_service=Renderer()
    if mode=='legacy':result=cache.render(snapshot.style_recipe,'isolated',width=64,height=36)
    elif mode=='snapshot':result=cache.render_snapshot(snapshot)
    else:result=cache.render_snapshot_batch([(snapshot,0,64,36)],batch_group='isolated',render_type='still')[0]
    key,target,hit=result
    assert checked and not hit and target.read_bytes()==b'png!'
    item=next(item for item in cache._storage.scan(include_models=False).items if item.path==str(target))
    assert item.cleanable and item.producer=='advanced_preview'
    cache.enforce_budget();assert not target.exists()


@pytest.fixture
def log_cache(tmp_path,monkeypatch):
    from twobyteasr.recognition import cache as module
    from twobyteasr.storage import storage_service
    root=tmp_path/'logs';root.mkdir()
    service=StorageService(roots=(root,),state_root=tmp_path/'state')
    context=SimpleNamespace(event_log_path='',identity_task_active=False)
    monkeypatch.setattr(storage_service,'StorageService',lambda:service)
    monkeypatch.setattr(module,'get_runtime_context',lambda:context)
    monkeypatch.setattr(module,'RUN_LOG_ROOT',str(root))
    monkeypatch.setattr(module,'RUN_EVENT_LOG_PATH','')
    monkeypatch.setattr(module,'redact_runtime_secrets',lambda value:str(value).replace('fixture-secret','<redacted>'))
    monkeypatch.setattr(module.task_reporting,'record_media_event',lambda *args,**kwargs:None)
    yield module,service,root
    module.end_run_event_log()


def test_begin_log_registers_and_append_leases_and_touches(log_cache,monkeypatch):
    module,service,root=log_cache
    observed=[]
    def checked_open(path,*args,**kwargs):
        stream=builtins.open(path,*args,**kwargs)
        if Path(path).parent==root and args and args[0]=='a':
            item=next(item for item in service.scan(include_models=False).items if item.path==str(Path(path)))
            observed.append(item.reason)
            assert not item.cleanable and item.category=='log' and item.producer=='cache_run_event_log'
        return stream
    monkeypatch.setattr(module,'open',checked_open,raising=False)
    path=Path(module.begin_run_event_log())
    _set_used(service,path,1)
    module.record_run_event('isolated',token='fixture-secret')
    rows=[json.loads(line) for line in path.read_text('utf8').splitlines()]
    assert rows[-1]['token']=='<redacted>' and len(observed)==2
    item=next(item for item in service.scan(include_models=False).items if item.path==str(path))
    assert not item.cleanable and item.last_used>time.time()-10
    module.end_run_event_log()
    item=next(item for item in service.scan(include_models=False).items if item.path==str(path))
    assert item.cleanable


def test_begin_log_never_adopts_or_prunes_old_named_unknown_logs(log_cache):
    module,service,root=log_cache
    unknown=root/'auto_asr_20000101_000000_1_abcdef.jsonl';unknown.write_text('authored diagnostic','utf8')
    os.utime(unknown,(1,1))
    module._prune_run_event_logs(root,max_age_days=1,max_files=1)
    current=Path(module.begin_run_event_log())
    assert unknown.read_text('utf8')=='authored diagnostic'
    policy=service.policy();assert policy['log_days']==14 and policy['log_budget_bytes']==200*1024**2
    module.end_run_event_log()
    _set_used(service,current,time.time()-15*86400)
    selected=service.recommended(service.scan(include_models=False))
    assert {item.path for item in selected}=={str(current)}
    service.clean(selected)
    assert unknown.is_file() and not current.exists()


def test_next_begin_releases_previous_log_session(log_cache):
    module,service,root=log_cache
    first=Path(module.begin_run_event_log());second=Path(module.begin_run_event_log())
    items={item.path:item for item in service.scan(include_models=False).items}
    assert items[str(first)].cleanable and not items[str(second)].cleanable


def test_audio_npy_and_only_its_sidecar_are_owned_and_leased_through_views(tmp_path,monkeypatch):
    import gc
    import numpy as np
    from twobyteasr.recognition import cache as module
    from twobyteasr.storage import storage_service
    source=tmp_path/'short.wav';source.write_bytes(b'isolated-source')
    folder=tmp_path/'cache';folder.mkdir()
    service=StorageService(roots=(folder,),state_root=tmp_path/'state')
    monkeypatch.setattr(storage_service,'StorageService',lambda:service)
    monkeypatch.setattr(module,'cache_stage_signature',lambda stage:'isolated-audio')
    monkeypatch.setattr(module,'record_run_event',lambda *args,**kwargs:None)
    calls=[]
    def decode(*args,**kwargs):
        calls.append(True)
        return np.array([.1,.2,.3,.4],dtype=np.float32)
    monkeypatch.setattr(module,'decode_audio_to_array',decode)
    context={'cache_dir':str(folder),'identity':{'path':str(source)}}
    evidence=folder/'moss.json';evidence.write_text('preserved ASR evidence','utf8')
    audio=module.load_shared_audio(str(source),context)
    view=audio[:2];del audio;gc.collect()
    items={Path(item.path).name:item for item in service.scan(include_models=False).items}
    assert set(name for name,item in items.items() if item.producer=='cache_shared_audio')=={'audio_16k.npy','audio_meta.json'}
    assert all(items[name].source==str(source) and not items[name].cleanable for name in ('audio_16k.npy','audio_meta.json'))
    assert not items['moss.json'].cleanable
    del view;gc.collect()
    audio=module.load_shared_audio(str(source),context)
    assert len(calls)==1 and audio.size==4
    del audio;gc.collect()
    items={Path(item.path).name:item for item in service.scan(include_models=False).items}
    assert all(items[name].cleanable for name in ('audio_16k.npy','audio_meta.json'))
    source.unlink()
    items={Path(item.path).name:item for item in service.scan(include_models=False).items}
    assert all(not items[name].cleanable for name in ('audio_16k.npy','audio_meta.json'))
    assert evidence.read_text('utf8')=='preserved ASR evidence'
