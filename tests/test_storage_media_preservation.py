"""Tiny owned files; saved graph proof never treats a copied asset as a relink."""
import copy
import hashlib
import json
import os
from pathlib import Path
from threading import Event

import pytest

from tests.test_storage_maintenance_ui import service, qapp
from twobyteasr.storage_media_assets import save_cached_media_asset
from twobyteasr import storage_media_preservation as proof
from twobyteasr.studio_project import SubtitleProject, StudioMedia, save_project


@pytest.fixture
def preserved(service):
    cache = service.paths.cache_root / 'media' / 'sole.mp4'
    cache.parent.mkdir(); cache.write_bytes(b'owned complete media fixture' * 31)
    missing = service.paths.user_data_root / 'missing-original.flv'
    assert service.register(cache, 'media', producer='indexed_media', source=missing)
    item = next(item for item in service.scan(include_models=False).items if item.path == str(cache))
    project_path = service.paths.project_root / 'edited' / 'edited.2byteproj'
    target = project_path.parent / 'assets' / 'preserved.mp4'
    target.parent.mkdir(parents=True)
    result = save_cached_media_asset(service, item, target)
    assert result.status == 'saved', result.detail
    return cache, item, target, project_path


def project(source, path):
    value = SubtitleProject(media=StudioMedia(path=str(source), duration_ms=2000, width=160, height=90))
    value.validate(); save_project(value, path)
    return value


def relink_and_save(value, target, path):
    from twobyteasr.studio_media_commands import media_graph_command
    from twobyteasr.studio_media_pool import relink_media_asset
    command = media_graph_command(value, '重新链接素材',
        lambda working: relink_media_asset(working, working.media_pool[0].asset_id, target))
    command.redo(); save_project(value, path)
    return command


def test_explicit_copy_alone_and_unsaved_relink_never_release(preserved, service, qapp):
    cache, item, asset, path = preserved
    assert not proof.verified_relinked_asset(item, service.paths).verified
    value = project(item.source, path)
    from twobyteasr.studio_media_commands import media_graph_command
    from twobyteasr.studio_media_pool import relink_media_asset
    command = media_graph_command(value, '重新链接素材',
        lambda working: relink_media_asset(working, working.media_pool[0].asset_id, asset))
    command.redo()
    result = proof.verified_relinked_asset(item, service.paths)
    assert not result.verified and str(path) in result.blocked_projects
    assert cache.exists()


def test_normal_relink_save_proves_full_sha_and_preserves_trim_rate_audio_and_undo(preserved, service, qapp):
    cache, item, asset, path = preserved
    value = project(item.source, path)
    for tracks in (value.video_tracks, value.audio_tracks):
        for track in tracks:
            for clip in track.clips:
                clip.source_in_ms = 200; clip.source_out_ms = 1800
                clip.timeline_in_ms = 350; clip.timeline_out_ms = 1150; clip.playback_rate = 2.0
    before = value.to_dict()
    command = relink_and_save(value, asset, path)
    after = value.to_dict()
    assert before['video_tracks'] == after['video_tracks']
    assert before['audio_tracks'] == after['audio_tracks']
    assert before['av_track_groups'] == after['av_track_groups']
    for old, new in zip(before['edit_sequence']['segments'], after['edit_sequence']['segments']):
        assert {k:v for k,v in old.items() if k != 'source_path'} == {k:v for k,v in new.items() if k != 'source_path'}
    result = proof.verified_relinked_asset(item, service.paths)
    assert result.verified and result.asset_path == str(asset)
    assert result.sha256 == hashlib.sha256(cache.read_bytes()).hexdigest()
    assert result.referenced_projects == (str(path),) and not result.blocked_projects
    assert cache.exists()
    command.undo(); save_project(value, path)
    assert not proof.verified_relinked_asset(item, service.paths).verified


@pytest.mark.parametrize('field', ['media', 'media_pool', 'audio_tracks', 'video_tracks', 'edit_sequence'])
def test_any_other_saved_strong_old_reference_holds_exact_project(preserved, service, field):
    cache, item, asset, path = preserved
    value = project(asset, path)
    other = path.parent / 'still-needed.2byteproj'
    payload = copy.deepcopy(value.to_dict())
    if field == 'media': payload['media']['path'] = item.source
    elif field == 'media_pool': payload['media_pool'][0]['canonical_source'] = item.source
    elif field in ('audio_tracks', 'video_tracks'): payload[field][0]['clips'][0]['source_path'] = str(cache)
    else: payload['edit_sequence']['segments'][0]['source_path'] = item.source
    other.write_text(json.dumps(payload), encoding='utf8')
    result = proof.verified_relinked_asset(item, service.paths)
    assert not result.verified and str(other) in result.blocked_projects


def test_weak_report_history_and_evidence_paths_are_not_media_dependencies(preserved, service):
    cache, item, asset, path = preserved
    value = project(asset, path); payload = value.to_dict()
    payload.update(report_path=item.source, original_outputs={'cache': str(cache)},
        generation_metadata={'source': item.source}, asr_evidence={'source_path': item.source},
        edit_history=[{'old_media': str(cache)}])
    path.write_text(json.dumps(payload), encoding='utf8')
    assert proof.verified_relinked_asset(item, service.paths).verified


@pytest.mark.parametrize('target', ['cache', 'asset', 'receipt'])
def test_replaced_or_tampered_files_cannot_reuse_receipt(preserved, service, target):
    cache, item, asset, path = preserved; project(asset, path)
    selected = {'cache': cache, 'asset': asset, 'receipt': proof._receipt_path(item, service.paths)}[target]
    stamp = selected.stat()
    raw = selected.read_bytes(); selected.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    os.utime(selected, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert not proof.verified_relinked_asset(item, service.paths).verified


def test_exact_external_index_paths_are_read_and_missing_or_bad_index_holds(preserved, service):
    cache, item, asset, path = preserved; project(asset, path)
    external = service.paths.user_data_root / 'external' / 'needed.2byteproj'; external.parent.mkdir()
    project(cache, external)
    index = service.paths.user_data_root / 'SubtitleStudioPreview' / 'library-index.json'; index.parent.mkdir()
    index.write_text(json.dumps({'version':2, 'projects':{str(external):{}}}), encoding='utf8')
    result = proof.verified_relinked_asset(item, service.paths)
    assert not result.verified and result.blocked_projects == (str(external),)
    external.unlink()
    result = proof.verified_relinked_asset(item, service.paths)
    assert not result.verified and str(external) in result.reason
    index.write_text('{bad', encoding='utf8')
    assert not proof.saved_project_references(service.paths, [str(cache)]).complete


def test_custom_project_root_and_recent_saved_paths_are_checked(preserved, service):
    cache, item, asset, path = preserved; project(asset, path)
    custom = service.paths.user_data_root / 'custom-library'; custom.mkdir()
    external = service.paths.user_data_root / 'recent' / 'external.2byteproj'; external.parent.mkdir()
    project(item.source, custom / 'custom.2byteproj'); project(cache, external)
    settings = service.paths.user_data_root / 'SubtitleStudioPreview' / 'settings.json'; settings.parent.mkdir()
    settings.write_text(json.dumps({'project_root':str(custom), 'recent_projects':[{'path':str(external)}],
        'unrelated_credentials':'not used'}), encoding='utf8')
    result = proof.verified_relinked_asset(item, service.paths)
    assert not result.verified and set(result.blocked_projects) == {str(custom / 'custom.2byteproj'), str(external)}


@pytest.mark.parametrize('failure', ['invalid', 'schema', 'link', 'hardlink', 'limit', 'cancel', 'read_failure'])
def test_unknown_scope_or_read_failure_never_means_no_reference(preserved, service, monkeypatch, failure):
    cache, item, asset, path = preserved; value = project(asset, path)
    if failure == 'invalid': path.write_text('{bad', encoding='utf8')
    elif failure == 'schema':
        payload=value.to_dict(); payload['schema_version']=99; path.write_text(json.dumps(payload),encoding='utf8')
    elif failure == 'link':
        from tests.test_model_removal import junction
        outside=service.paths.user_data_root/'outside';outside.mkdir();junction(path.parent/'linked',outside)
    elif failure == 'hardlink': os.link(asset, asset.with_name('another-copy.mp4'))
    elif failure == 'limit': monkeypatch.setattr(proof, 'MAX_ENTRIES', 0)
    elif failure == 'read_failure':
        original=Path.open
        def opened(file,*args,**kwargs):
            if file == path: raise PermissionError('fixture locked project')
            return original(file,*args,**kwargs)
        monkeypatch.setattr(Path,'open',opened)
    event=Event()
    if failure == 'cancel':event.set()
    assert not proof.verified_relinked_asset(item,service.paths,cancel=event).verified


def test_direct_cache_reference_keys_and_absent_scope_snapshot_are_conservative(service):
    cache=service.paths.cache_root/'proxy.mp4';cache.write_bytes(b'tiny')
    result=proof.saved_project_references(service.paths,[str(cache)])
    assert result.complete and result.references == {str(cache):()}
    service.paths.project_root.mkdir()
    assert not proof.project_reference_snapshot_current(result)
    path=service.paths.project_root/'direct.2byteproj';project(cache,path)
    result=proof.saved_project_references(service.paths,[str(cache)])
    assert result.complete and result.references[str(cache)] == (str(path),)


def test_asset_receipt_link_cannot_write_outside_owned_metadata(preserved, service):
    cache,item,asset,path=preserved
    receipt=proof._receipt_path(item,service.paths);receipt.unlink()
    from tests.test_model_removal import junction
    receipt.parent.rmdir();outside=service.paths.user_data_root/'outside';outside.mkdir()
    junction(receipt.parent,outside)
    with pytest.raises(ValueError):proof.record_preserved_asset(item,service.paths,asset,hashlib.sha256(cache.read_bytes()).hexdigest())
    assert not list(outside.iterdir()) and not proof.verified_relinked_asset(item,service.paths).verified


@pytest.mark.parametrize('kind', ['malformed_identity', 'deep_json', 'partial_only', 'missing_asset'])
def test_incomplete_or_unknown_receipt_does_not_release(preserved, service, kind):
    cache,item,asset,path=preserved;project(asset,path)
    receipt=proof._receipt_path(item,service.paths)
    if kind == 'malformed_identity':
        payload=json.loads(receipt.read_text('utf8'));payload['asset_identity']=[0]
        receipt.write_text(json.dumps(payload),'utf8')
    elif kind == 'deep_json':receipt.write_text('['*2000+'0'+']'*2000,'utf8')
    elif kind == 'partial_only':receipt.rename(receipt.with_suffix('.part'))
    else:asset.unlink()
    assert not proof.verified_relinked_asset(item,service.paths).verified and cache.exists()


def test_absence_permission_denied_cannot_be_treated_as_empty_project_scope(service,monkeypatch):
    original=Path.lstat
    def checked(path,*args,**kwargs):
        if path==service.paths.project_root:raise PermissionError('fixture project root unavailable')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'lstat',checked)
    result=proof.saved_project_references(service.paths,[])
    assert not result.complete and result.errors


def test_asset_copy_kept_without_receipt_when_metadata_publication_fails(service,monkeypatch):
    cache=service.paths.cache_root/'sole.mp4';cache.write_bytes(b'complete small sole cache')
    missing=service.paths.user_data_root/'missing.mp4';service.register(cache,'media',producer='indexed_media',source=missing)
    item=next(i for i in service.scan(include_models=False).items if i.path==str(cache))
    assets=service.paths.project_root/'assets';assets.mkdir(parents=True);target=assets/'saved.mp4'
    def failed(*args,**kwargs):raise OSError('fixture metadata locked')
    monkeypatch.setattr(proof,'record_preserved_asset',failed)
    result=save_cached_media_asset(service,item,target)
    assert result.status=='saved' and target.read_bytes()==cache.read_bytes() and '凭据' in result.detail
    project(target,service.paths.project_root/'edited.2byteproj')
    assert not proof.verified_relinked_asset(item,service.paths).verified


def test_saved_project_changes_after_reference_snapshot_holds(preserved,service,monkeypatch):
    cache,item,asset,path=preserved;value=project(asset,path)
    original=proof.project_reference_snapshot_current;calls=[0]
    def current(result):
        calls[0]+=1
        if calls[0]==2:
            payload=value.to_dict();payload['media']['path']=str(cache)
            path.write_text(json.dumps(payload),'utf8')
        return original(result)
    monkeypatch.setattr(proof,'project_reference_snapshot_current',current)
    assert not proof.verified_relinked_asset(item,service.paths).verified


def test_saved_cache_junction_alias_is_unknown_even_when_lexical_path_differs(preserved,service):
    cache,item,asset,path=preserved;project(asset,path)
    from tests.test_model_removal import junction
    alias=service.paths.user_data_root/'cache-alias';junction(alias,cache.parent)
    project(alias/cache.name,path.parent/'alias-reference.2byteproj')
    scan=proof.saved_project_references(service.paths,[str(cache)])
    assert not scan.complete and any('链接' in error for error in scan.errors)
    assert not proof.verified_relinked_asset(item,service.paths).verified


def test_library_larger_than_the_old_total_read_cap_is_still_verified(service):
    """2026-10-11: a real library held 383 project/autosave files (231 MB);
    the former 64 MB total cap made every media cache unverifiable, so the
    storage page could never clean any of them."""
    cache=service.paths.cache_root/'proxy.mp4';cache.write_bytes(b'tiny')
    other=service.paths.user_data_root/'other.flv'
    for index in range(70):  # ~70 MB of saved projects without that cache
        value=SubtitleProject(media=StudioMedia(path=str(other),duration_ms=2000,width=160,height=90))
        value.generation_metadata['notes']='x'*(1024*1024)
        value.validate();path=service.paths.project_root/f'p{index}'/f'p{index}.2byteproj'
        save_project(value,path)
    holder=service.paths.project_root/'holder'/'holder.2byteproj';holder.parent.mkdir(parents=True)
    project(cache,holder)
    result=proof.saved_project_references(service.paths,[str(cache)])
    assert result.complete, result.errors[:2]
    assert result.references[str(cache)] == (str(holder),)
