"""Preserving a missing-source cache is distinct from deleting that cache."""
import time

from PySide6.QtCore import Qt
from tests.test_storage_media_assets import cached
from tests.test_storage_maintenance_ui import qapp,service
from twobyteasr.storage.storage_ui import StoragePanel
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia


def test_loaded_missing_original_enables_normal_save_but_never_cleanup(service,qapp,monkeypatch):
    cache,item,target=cached(service)
    project=SubtitleProject(media=StudioMedia(item.source,duration_ms=2000))
    service.media_references=lambda:(project.to_dict(),service.paths.project_root/'owned.2byteproj')
    scan=service.scan(include_models=False)
    current=next(i for i in scan.items if i.path==str(cache))
    assert current.reason=='当前打开工程仍依赖失联原素材；请先重新定位并保存工程'
    assert not current.cleanable and not current.manual_cleanable
    panel=StoragePanel(service=service);panel._scanned(scan)
    node=next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
        if panel.tree.topLevelItem(i).data(0,Qt.UserRole)=='media')
    row=next(node.child(i) for i in range(node.childCount()) if node.child(i).data(0,Qt.UserRole)==str(cache))
    panel.tree.setCurrentItem(row);node.setCheckState(0,Qt.Checked)
    assert panel.save_media.isEnabled() and panel.relink_media.isEnabled()
    assert not panel.selected.isEnabled() and not panel.recommended.isEnabled()
    chosen=[]
    def choose(*args,**kwargs):chosen.append(args);return str(target),'Media'
    monkeypatch.setattr('twobyteasr.storage.storage_ui.QFileDialog.getSaveFileName',choose)
    panel.save_media.click()
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        qapp.processEvents()
        if target.exists() and panel.worker is None:break
        time.sleep(.025)
    assert chosen and target.is_file() and cache.is_file() and panel.worker is None
    after=next(i for i in service.scan(include_models=False).items if i.path==str(cache))
    assert after.reason==current.reason and not after.manual_cleanable
    assert not service.clean([after],allow_missing_aux=True).deleted
    assert cache.is_file() and target.is_file()
    panel.deleteLater();qapp.processEvents()


def test_original_present_and_nonlocal_media_never_offer_sole_copy_preservation(service,qapp):
    from pathlib import Path
    from dataclasses import replace
    cache,item,target=cached(service)
    panel=StoragePanel(service=service);scan=service.scan(include_models=False);panel._scanned(scan)
    node=next(panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
        if panel.tree.topLevelItem(i).data(0,Qt.UserRole)=='media')
    row=next(node.child(i) for i in range(node.childCount()) if node.child(i).data(0,Qt.UserRole)==str(cache))
    panel.tree.setCurrentItem(row);assert panel.save_media.isEnabled()
    Path(item.source).write_bytes(b'original returned')
    panel._update_media_controls();assert not panel.save_media.isEnabled()
    Path(item.source).unlink()
    scan.items=[replace(i,rebuild='download') if i.path==str(cache) else i for i in scan.items]
    panel._update_media_controls();assert not panel.save_media.isEnabled()
