"""Sole media cache preservation in isolated paths; no user's project is edited."""
import hashlib
import json
from pathlib import Path
from threading import Event

import pytest
from tests.test_storage_maintenance_ui import service, qapp
from twobyteasr.storage.storage_media_assets import save_cached_media_asset
from twobyteasr.storage.storage_ui import StoragePanel


def cached(service, *, registered=True):
    folder=service.paths.cache_root/'media/seek/v2/fixture';folder.mkdir(parents=True)
    path=folder/'optimized.mp4';path.write_bytes(b'controlled sole media copy'*65536)
    missing=service.paths.user_data_root/'missing-original.flv'
    if registered: assert service.register(path,'media',producer='indexed_media',source=missing)
    else:(folder/'ready.json').write_text(json.dumps(dict(source=str(missing),size=123,mtime_ns=456)),encoding='utf8')
    item=next(i for i in service.scan(include_models=False).items if i.path==str(path))
    assets=service.paths.user_data_root/'Projects/owned/assets';assets.mkdir(parents=True)
    return path,item,assets/'preserved.mp4'


@pytest.mark.parametrize('registered',[True,False])
def test_preserve_registered_or_strict_legacy_cache_with_full_sha_and_original_kept(service,registered):
    source,item,target=cached(service,registered=registered)
    expected=hashlib.sha256(source.read_bytes()).hexdigest()
    result=save_cached_media_asset(service,item,target)
    assert result.status=='saved' and result.sha256==expected
    assert result.logical_bytes==source.stat().st_size==target.stat().st_size
    assert hashlib.sha256(target.read_bytes()).hexdigest()==expected
    assert source.exists() and not service._registered()[1]
    assert str(target) not in service._registered()[0]
    assert not list(target.parent.glob('*.part'))


def test_preserve_never_overwrites_existing_asset_or_saves_inside_cache(service):
    source,item,target=cached(service)
    target.write_bytes(b'valuable existing asset')
    result=save_cached_media_asset(service,item,target)
    assert result.status=='failed' and target.read_bytes()==b'valuable existing asset'
    inside=source.parent/'saved.mp4'
    assert save_cached_media_asset(service,item,inside).status=='failed'
    assert not inside.exists() and source.exists()


def test_unknown_files_and_changed_source_are_rejected(service):
    source,item,target=cached(service)
    with service._db() as db:db.execute('DELETE FROM entries WHERE path=?',(str(source),))
    assert save_cached_media_asset(service,item,target).status=='failed' and not target.exists()
    assert service.register(source,'media',producer='indexed_media',source=item.source)
    source.write_bytes(b'changed after scan')
    assert save_cached_media_asset(service,item,target).status=='failed' and not target.exists()


def test_original_restored_before_save_is_rejected(service):
    source,item,target=cached(service)
    Path(item.source).write_bytes(b'restored original')
    assert save_cached_media_asset(service,item,target).status=='failed'
    assert not target.exists() and source.exists()


def test_cancel_mid_copy_removes_only_owned_partial_and_releases_lease(service):
    source,item,target=cached(service)
    counter=[0]
    def cancel():
        counter[0]+=1
        return counter[0]>=5
    result=save_cached_media_asset(service,item,target,cancel=cancel)
    assert result.status=='cancelled' and source.exists() and not target.exists()
    assert not list(target.parent.iterdir()) and not service._registered()[1]


def test_destination_junction_is_never_followed(service,tmp_path):
    source,item,target=cached(service)
    outside=tmp_path/'outside';outside.mkdir()
    from tests.test_model_removal import junction
    linked=target.parent/'linked';junction(linked,outside)
    result=save_cached_media_asset(service,item,linked/'preserved.mp4')
    assert result.status=='failed' and not list(outside.iterdir()) and source.exists()


def test_source_has_live_lease_during_actual_read(service,monkeypatch):
    source,item,target=cached(service);original=Path.open;observed=[]
    def opened(path,*a,**kw):
        if path==source and a and a[0]=='rb':
            observed.append(str(source) in service._registered()[1])
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'open',opened)
    assert save_cached_media_asset(service,item,target).status=='saved' and observed==[True]


def test_asset_appearing_during_copy_is_not_overwritten(service,monkeypatch):
    source,item,target=cached(service)
    from twobyteasr.storage import storage_media_assets as module
    original=module._destination;calls=[0]
    def destination(path,svc):
        calls[0]+=1
        if calls[0]==2:Path(path).write_bytes(b'appeared while copying')
        return original(path,svc)
    monkeypatch.setattr(module,'_destination',destination)
    result=save_cached_media_asset(service,item,target)
    assert result.status=='failed' and target.read_bytes()==b'appeared while copying'
    assert source.exists() and not list(target.parent.glob('*.part'))


def test_normal_storage_asset_button_opens_explicit_save_and_uses_background_worker(service,qapp,monkeypatch):
    source,item,target=cached(service)
    panel=StoragePanel(service=service);panel._scanned(service.scan(include_models=False))
    node=next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
        if panel.tree.topLevelItem(i).data(0,256)=='media')
    row=next(node.child(i) for i in range(node.childCount()) if node.child(i).data(0,256)==str(source))
    panel.tree.setCurrentItem(row)
    assert panel.save_media.isEnabled() and panel.relink_media.isEnabled()
    selections=[]
    def choose(*args,**kwargs):selections.append(args);return str(target),'Media'
    monkeypatch.setattr('twobyteasr.storage.storage_ui.QFileDialog.getSaveFileName',choose)
    panel.save_media.click()
    import time
    for _ in range(160):
        qapp.processEvents()
        if target.exists() and panel.worker is None:break
        # PySide's qWait holds the GIL on this runtime and starves the Python
        # producer. Keep the same bounded deadline while letting it execute.
        time.sleep(.025)
    assert selections and target.exists() and source.exists() and panel.worker is None
    assert hashlib.sha256(target.read_bytes()).hexdigest() in panel.summary.text()
    panel.deleteLater();qapp.processEvents()
