"""Historical producer layouts, manual safety, and policy are separate gates."""
from twobyteasr.test_isolation import install
install()

import json
import os
from pathlib import Path
from threading import Event
import time
from types import SimpleNamespace

import pytest
from twobyteasr.runtime_paths import RuntimePaths
from twobyteasr.storage.storage_service import StorageService


@pytest.fixture
def service(tmp_path,monkeypatch):
    data=tmp_path/'data';cache=data/'cache';cache.mkdir(parents=True)
    paths=RuntimePaths(tmp_path,data,data/'models',cache,data/'Projects',data,data/'logs',tmp_path/'renderer',data/'tmp')
    monkeypatch.setattr('twobyteasr.storage.storage_legacy.legacy_consumers',lambda:[])
    return StorageService(paths,media_validator=lambda source:'')


def overlay(service,session='a'*32):
    path=service.paths.user_data_root/'SubtitleStudioPreview/mpv-overlays'/session/'overlay-1-0.rgba'
    path.parent.mkdir(parents=True);path.write_bytes(b'\0'*64)
    return path


def test_unregistered_old_overlay_has_executable_manual_plan_without_index_write(service):
    path=overlay(service);other=path.with_name('authored.rgba');other.write_bytes(b'art')
    scan=service.scan(include_models=False)
    assert scan.cleanable_bytes==0 and scan.manual_cleanable_bytes==64
    assert not service.db_path.exists()
    assert service.clean(scan.items).skipped and path.exists()
    result=service.clean(service.manual_items(scan),adopt_legacy=True)
    assert result.logical_removed_bytes==64 and not path.exists() and other.read_bytes()==b'art'


def test_manual_bypasses_only_auto_idle_and_retention(service):
    path=service.paths.cache_root/'fresh.png';path.write_bytes(b'generated')
    service.register(path,'preview',producer='fixture')
    service.busy=lambda:True;service.manual_busy=lambda:False
    scan=service.scan(include_models=False)
    assert not service.recommended(scan)
    assert service.clean(scan.items,automatic=True).skipped
    with service.lease(path):assert service.clean(scan.items).skipped
    assert service.clean(service.scan(include_models=False).items).deleted


def test_scan_readonly_preserves_dead_lease_and_index_mtime(service):
    path=service.paths.cache_root/'preview.png';path.write_bytes(b'pixels')
    service.register(path,'preview',producer='fixture')
    with service._db() as db:db.execute('INSERT INTO leases VALUES(?,?,?)',(str(path),'99999999:1.000000','stale-fixture'))
    before=service.db_path.read_bytes();mtime=service.db_path.stat().st_mtime_ns
    assert service.scan(include_models=False).items[0].cleanable
    assert service.db_path.read_bytes()==before and service.db_path.stat().st_mtime_ns==mtime


def test_unknown_last_used_manual_allowed_auto_retained(service):
    path=service.paths.cache_root/'generated.png';path.write_bytes(b'pixels')
    service.register(path,'preview',producer='fixture')
    with service._db() as db:db.execute('UPDATE entries SET used=NULL')
    scan=service.scan(include_models=False)
    assert service.manual_items(scan) and not service.recommended(scan)
    assert service.clean(scan.items).deleted


def test_missing_waveform_requires_explicit_manual_warning_and_never_auto(service):
    root=service.paths.user_data_root/'SubtitleStudioPreview/waveform-cache'/('b'*32);root.mkdir(parents=True)
    meta=root/'metadata.json';meta.write_text(json.dumps(dict(schema_version=1,source_path=str(root/'missing.flv'),levels=[dict(file='lod0.f32',frames=8)])))
    (root/'lod0.f32').write_bytes(b'\0'*64)
    scan=service.scan(include_models=False)
    assert len(service.manual_items(scan))==2 and all(i.warning for i in scan.items)
    assert service.clean(scan.items,adopt_legacy=True).skipped
    adopted=service.scan(include_models=False)
    assert not service.recommended(adopted)
    assert len(service.clean(adopted.items,allow_missing_aux=True).deleted)==2


def test_old_filmstrip_exact_key_receipt_and_warning(service):
    folder=service.paths.user_data_root/'SubtitleStudioPreview/filmstrip-v3';folder.mkdir(parents=True)
    key='c'*24+'-t0-128x72-lod1000-srgb3'
    (folder/(key+'.json')).write_text(json.dumps(dict(exact=True,requested_ms=0,lod_ms=1000,pts_ms=0)))
    (folder/(key+'.jpg')).write_bytes(b'old thumbnail')
    (folder/'user.json').write_text(json.dumps(dict(exact=True,requested_ms=0,lod_ms=1000,pts_ms=0)))
    scan=service.scan(include_models=False)
    selected=service.manual_items(scan)
    assert len(selected)==2 and all(i.warning for i in selected)
    assert len(service.clean(selected,adopt_legacy=True,allow_missing_aux=True).deleted)==2
    assert (folder/'user.json').exists()


def test_specific_live_session_does_not_protect_old_session(service,monkeypatch):
    old=overlay(service,'d'*32);active=overlay(service,'e'*32)
    from twobyteasr.storage.storage_service import _pid_identity
    pid,born=_pid_identity().split(':')
    (active.parent/'owner.json').write_text(json.dumps(dict(producer='mpv_overlay_session',schema=1,pid=int(pid),create_time=float(born))))
    scan=service.scan(include_models=False)
    assert [i.path for i in service.manual_items(scan)]==[str(old)]
    assert service.clean(service.manual_items(scan),adopt_legacy=True).deleted
    assert active.exists()


def test_missing_intermediate_media_remains_protected_even_manual(service):
    root=service.paths.cache_root/'media/seek/v2'/('f'*32);root.mkdir(parents=True)
    (root/'ready.json').write_text(json.dumps(dict(source=str(root/'missing.flv'),size=1,mtime_ns=2)))
    target=root/'optimized.mp4';target.write_bytes(b'only copy')
    scan=service.scan(include_models=False)
    assert not service.manual_items(scan)
    assert service.clean(scan.items,adopt_legacy=True,allow_missing_aux=True).skipped and target.exists()


def test_original_available_media_checks_reader_again_at_delete(service):
    source=service.paths.user_data_root/'source.flv';source.write_bytes(b'original')
    target=service.paths.cache_root/'proxy.mp4';target.write_bytes(b'proxy')
    service.register(target,'media',source=str(source),producer='indexed_media')
    scan=service.scan(include_models=False)
    service.media_validator=lambda _: '原素材读取失败'
    assert service.clean(scan.items).skipped and target.exists()
    service.media_validator=lambda _: ''
    assert service.clean(service.scan(include_models=False).items).deleted and source.exists()


def test_overlapping_roots_do_not_count_same_path_twice(service):
    sub=service.paths.cache_root/'nested';sub.mkdir();path=sub/'unknown.bin';path.write_bytes(b'1234')
    duplicate=StorageService(service.paths,roots=[sub,service.paths.cache_root,sub])
    scan=duplicate.scan(include_models=False)
    assert scan.total_bytes==4 and len(scan.items)==1


def test_zero_executable_buttons_disabled_and_batch_shows_nonzero(service):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from twobyteasr.storage.storage_ui import StoragePanel,app_busy
    app=QApplication.instance() or QApplication([])
    (service.paths.cache_root/'unknown.mp4').write_bytes(b'user')
    panel=StoragePanel(service=service);panel._scanned(service.scan(include_models=False))
    panel.tree.topLevelItem(0).setCheckState(0,Qt.Checked)
    assert not panel.selected.isEnabled() and not panel.recommended.isEnabled()
    path=overlay(service);panel._scanned(service.scan(include_models=False))
    item=next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount()) if panel.tree.topLevelItem(i).data(0,Qt.UserRole)=='overlay')
    item.setCheckState(0,Qt.Checked)
    assert panel.selected.isEnabled() and '历史待确认' in item.text(2)
    owner=SimpleNamespace(studio_page=SimpleNamespace(project=SimpleNamespace(media=SimpleNamespace(path='original.mp4'))))
    assert app_busy(owner) and not app_busy(owner,manual=True)
    panel.deleteLater();app.processEvents()


def test_manual_uv_clean_is_distinct_from_prune_and_ignores_only_auto_retention(tmp_path):
    from tests.test_runtime_download_cache import fixture
    from twobyteasr.system.runtime_download_cache import clean_runtime_download_cache,mark_runtime_cache_state
    install,data,cache,python=fixture(tmp_path);calls=[]
    mark_runtime_cache_state('paused',data_root=data)
    def runner(argv,cancel):
        args=list(map(str,argv));calls.append(args)
        if '--version' in args:return 'uv 0.11.7 (fixture)'
        if args[-2:]==['cache','clean']:(cache/'duplicate').unlink();return 'Removed 1 file'
        return 'Checked installed dependencies'
    result=clean_runtime_download_cache(install,data_root=data,runner=runner)
    assert result.status=='removed' and result.logical_removed_bytes==2048 and python.exists()
    assert any(call[-2:]==['cache','clean'] for call in calls)
    assert not any('--force' in call or '--ci' in call for call in calls)


def test_manual_uv_unknown_size_does_not_mean_zero_or_disable_tool(tmp_path,monkeypatch):
    from tests.test_runtime_download_cache import fixture
    from twobyteasr.system.runtime_download_cache import clean_runtime_download_cache
    install,data,cache,_=fixture(tmp_path);calls=[]
    monkeypatch.setattr('twobyteasr.system.runtime_download_cache._size',lambda *a:(_ for _ in ()).throw(PermissionError('unmeasured')))
    def runner(argv,cancel):
        args=list(map(str,argv));calls.append(args)
        return 'uv 0.11.7 (fixture)' if '--version' in args else 'Official maintenance complete'
    result=clean_runtime_download_cache(install,data_root=data,runner=runner)
    assert result.status=='removed' and not result.measurement_complete and result.disk_free_delta is not None
    assert any(call[-2:]==['cache','clean'] for call in calls)


def saved_media_project(service,name,media_path):
    project=service.paths.project_root/name;project.parent.mkdir(parents=True,exist_ok=True)
    project.write_text(json.dumps(dict(schema_version=1,media=dict(path=str(media_path)))),'utf8')
    return project


def registered_media(service,*,missing=False):
    source=service.paths.user_data_root/'original.flv'
    if not missing:source.write_bytes(b'original media')
    path=service.paths.cache_root/'proxy.mp4';path.write_bytes(b'generated intermediate')
    service.register(path,'media',source=str(source),producer='indexed_media')
    return path,source


def test_saved_direct_cache_reference_blocks_manual_and_delete_rechecks_new_project(service):
    path,source=registered_media(service)
    saved_media_project(service,'nominal.2byteproj',source)
    scan=service.scan(include_models=False)
    assert service.manual_items(scan)
    project=saved_media_project(service,'direct.2byteproj',path)
    result=service.clean(scan.items)
    assert result.skipped and path.exists() and str(project) in result.skipped[0]['reason']
    assert not service.manual_items(service.scan(include_models=False))


def test_direct_cached_payload_keeps_its_generated_seek_sidecars(service):
    source=service.paths.user_data_root/'original.flv';source.write_bytes(b'original media')
    folder=service.paths.cache_root/'media/seek/v2'/('8'*32);folder.mkdir(parents=True)
    ready=folder/'ready.json';info=source.stat()
    ready.write_text(json.dumps(dict(source=str(source),size=info.st_size,mtime_ns=info.st_mtime_ns)))
    proxy=folder/'optimized.mp4';proxy.write_bytes(b'generated intermediate')
    saved_media_project(service,'direct.2byteproj',proxy)
    scan=service.scan(include_models=False)
    assert len([i for i in scan.items if i.category=='media'])==2
    assert not service.manual_items(scan) and all('direct.2byteproj' in i.reason for i in scan.items)


def test_unknown_saved_graph_or_current_loaded_cache_reference_is_a_hold(service):
    path,source=registered_media(service)
    broken=saved_media_project(service,'unknown.2byteproj',source);broken.write_text('{"schema_version":99}')
    assert not service.manual_items(service.scan(include_models=False))
    broken.unlink()
    service.media_references=lambda:(dict(schema_version=1,media=dict(path=str(path))),str(service.paths.project_root/'unsaved.2byteproj'))
    assert not service.manual_items(service.scan(include_models=False))
    service.media_references=lambda:(dict(schema_version=1,media=dict(path=str(source))),str(service.paths.project_root/'unsaved.2byteproj'))
    assert service.clean(service.scan(include_models=False).items).deleted and source.exists()


def relinked_asset(service,path,source):
    import hashlib
    from twobyteasr.storage.storage_media_preservation import record_preserved_asset
    asset=service.paths.user_data_root/'assets'/'preserved.mp4';asset.parent.mkdir();asset.write_bytes(path.read_bytes())
    item=next(i for i in service.scan(include_models=False).items if i.path==str(path))
    record_preserved_asset(item,service.paths,asset,hashlib.sha256(asset.read_bytes()).hexdigest())
    return asset


def test_verified_saved_relink_only_enables_manual_and_preserves_asset(service):
    path,source=registered_media(service,missing=True)
    asset=relinked_asset(service,path,source)
    assert not service.manual_items(service.scan(include_models=False))
    saved_media_project(service,'relinked.2byteproj',asset)
    scan=service.scan(include_models=False)
    assert service.manual_items(scan) and not service.recommended(scan) and scan.items[0].warning
    assert service.clean(scan.items).skipped and path.exists()
    result=service.clean(scan.items,allow_missing_aux=True)
    assert result.deleted and not path.exists() and asset.exists()


def test_copied_asset_still_has_to_replace_every_saved_and_loaded_reference(service):
    path,source=registered_media(service,missing=True);asset=relinked_asset(service,path,source)
    saved_media_project(service,'new.2byteproj',asset);old=saved_media_project(service,'old.2byteproj',source)
    scan=service.scan(include_models=False)
    assert not service.manual_items(scan) and 'old.2byteproj' in scan.items[0].reason
    old.unlink()
    service.media_references=lambda:(dict(schema_version=1,media=dict(path=str(source))),str(service.paths.project_root/'loaded.2byteproj'))
    assert not service.manual_items(service.scan(include_models=False))


def test_source_or_preserved_asset_changes_after_scan_remain_protected(service):
    path,source=registered_media(service)
    scan=service.scan(include_models=False);source.write_bytes(b'different original')
    assert service.clean(scan.items).skipped and path.exists()
    source.unlink();asset=relinked_asset(service,path,source);saved_media_project(service,'new.2byteproj',asset)
    scan=service.scan(include_models=False);asset.write_bytes(b'different preserved bytes')
    assert service.clean(scan.items,allow_missing_aux=True).skipped and path.exists()


def test_loaded_player_cache_path_is_protected_without_blocking_nominal_original(service):
    path,source=registered_media(service)
    service.media_references=lambda:(dict(schema_version=1,media=dict(path=str(source))),str(service.paths.project_root/'loaded.2byteproj'),(str(path),))
    assert not service.manual_items(service.scan(include_models=False))
    service.media_references=lambda:(dict(schema_version=1,media=dict(path=str(source))),str(service.paths.project_root/'loaded.2byteproj'),(str(source),))
    assert service.clean(service.scan(include_models=False).items).deleted


def test_export_busy_is_a_manual_safety_gate():
    from twobyteasr.storage.storage_ui import app_busy
    worker=SimpleNamespace(is_alive=lambda:True)
    owner=SimpleNamespace(studio_page=SimpleNamespace(export_workspace=SimpleNamespace(_worker=worker)))
    assert app_busy(owner,manual=True)


def test_loaded_graph_inventory_does_not_persist_or_initialize_user_sequence():
    from twobyteasr.storage.storage_ui import loaded_media_graph
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    project=SubtitleProject(media=StudioMedia(path=''))
    before=json.dumps(project.edit_sequence,sort_keys=True)
    runtime_before=getattr(project,'_edit_sequence_runtime',None)
    owner=SimpleNamespace(studio_page=SimpleNamespace(project=project))
    graph,_,_=loaded_media_graph(owner)
    assert graph['media']['path']==project.media.path
    assert json.dumps(project.edit_sequence,sort_keys=True)==before
    assert getattr(project,'_edit_sequence_runtime',None) is runtime_before


def test_project_saved_or_source_changed_during_media_reader_check_is_held(service):
    path,source=registered_media(service);scan=service.scan(include_models=False)
    def change_project(_):
        saved_media_project(service,'during-probe.2byteproj',path)
        return ''
    service.media_validator=change_project
    assert service.clean(scan.items).skipped and path.exists()
    (service.paths.project_root/'during-probe.2byteproj').unlink()
    scan=service.scan(include_models=False)
    def change_source(_):
        source.write_bytes(b'replaced during media reader check')
        return ''
    service.media_validator=change_source
    assert service.clean(scan.items).skipped and path.exists()
