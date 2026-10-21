from dataclasses import asdict
from types import SimpleNamespace
from pathlib import Path
import time
import pytest
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QDialog
from twobyteasr.cover.cover_document import CoverDocument
from twobyteasr.cover.cover_editor import CoverEditor
from twobyteasr.cover.cover_local_library import LocalCoverLibrary
from tests.test_cover_local_workflow import png, document, wait_job, app


def test_no_slot_aspect_update_undo_and_master(tmp_path, app):
    master=document();master.layers=master.layers[1:];master.background_id=''
    editor=CoverEditor(document());editor.library=LocalCoverLibrary(tmp_path/'lib')
    entry=editor.library.save_native('transparent',master,png())
    raw=editor.library.asset(entry,'cover').read_bytes()
    original=editor.session.document.signature()
    editor.apply_template(entry,replace=True);wait_job(app,editor)
    value=editor.session.document
    assert (value.width,value.height)==(640,360)
    assert [asdict(x) for x in value.layers[1:]]==[asdict(x) for x in master.layers]
    key=value.background_id
    frame=CoverDocument(width=180,height=320)
    import io
    from PIL import Image
    stream=io.BytesIO();Image.new('RGBA',(180,320),'blue').save(stream,format='PNG')
    frame.add_image(stream.getvalue(),'new.png',(180,320),background=True)
    frame.source=dict(project_id='fixture',milliseconds=4500,captured_at='test')
    prior=value.signature();editor.use_frozen_frame(frame)
    assert editor.session.document.background_id==key and len(editor.session.document.layers)==3
    background=editor.session.document.layer(key)
    assert background.width/background.height==180/320
    assert [asdict(x) for x in editor.session.document.layers[1:]]==[asdict(x) for x in master.layers]
    editor.undo();assert editor.session.document.signature()==prior
    editor.undo();assert editor.session.document.signature()==original
    editor.redo();editor.redo()
    target=tmp_path/'saved.2bytecover';editor.session.document.save(target)
    assert CoverDocument.load(target).source['milliseconds']==4500
    assert editor.library.asset(entry,'cover').read_bytes()==raw
    editor.save_template('no captured pixels');wait_job(app,editor)
    saved=next(e for e in editor.library.entries() if e['name']=='no captured pixels')
    assert not editor.library.load_copy(saved).background_id
    editor.save_template('with captured pixels',include_frame=True);wait_job(app,editor)
    saved=next(e for e in editor.library.entries() if e['name']=='with captured pixels')
    assert editor.library.load_copy(saved).background_id


def test_opaque_design_foreground_is_preserved_and_explained(app):
    doc=document();doc.layers[1].x=doc.layers[1].y=0
    doc.layers[1].width=640;doc.layers[1].height=360;doc.layers[1].opacity=1
    editor=CoverEditor(doc);editor.use_frozen_frame(document())
    assert '遮挡' in editor.status.text()
    assert editor.session.document.layers[1].visible


def test_empty_track_refuses_black_cover(tmp_path,app):
    from twobyteasr.exports.frame_export import save_project_frame
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    project=SubtitleProject(media=StudioMedia('fixture.mp4',duration_ms=6000,width=640,height=360))
    with pytest.raises(ValueError,match='空轨'):
        save_project_frame(project,dict(width=640,height=360,media_pool=[],video_tracks=[]),1000,tmp_path,'frame',
            subtitles=False,require_video_frame=True)


def test_late_capture_after_project_switch_never_opens_editor(app,monkeypatch):
    from twobyteasr.cover import cover_studio
    from twobyteasr.exports import export_timeline, video_export, frame_export
    page=QWidget();page.save_state=QLabel(page)
    page.project=SimpleNamespace(media=SimpleNamespace(path='fixture.mp4'))
    page.timeline=SimpleNamespace(playhead_ms=1200);page.video=SimpleNamespace(set_paused=lambda _:None)
    monkeypatch.setattr(export_timeline,'export_project_snapshot',lambda p:SimpleNamespace(project_id='original'))
    monkeypatch.setattr(video_export,'capture_video_graph',lambda p:{})
    jobs=[]
    monkeypatch.setattr(cover_studio.CoverJob,'start',lambda self,fn:jobs.append(self))
    cover_studio.install_cover_button(page,QVBoxLayout(page));controller=page.cover_controller
    controller.create();page.project=SimpleNamespace(media=SimpleNamespace(path='different.mp4'))
    jobs[0].finished.emit((document(),{}));app.processEvents()
    assert controller.editor is None and '丢弃' in page.save_state.text()
