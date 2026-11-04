"""Long-project UI cost boundaries and external pool-drop routing."""
import copy
from types import SimpleNamespace
import time

import pytest
from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QResizeEvent, QUndoStack
from PySide6.QtWidgets import QApplication, QWidget

APP=QApplication.instance() or QApplication([])


def test_same_geometry_resize_does_not_change_timeline_zoom():
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    t=WaveformTimeline();t.resize(1500,400)
    t.vertical_scrollbar.setFixedWidth(t.vertical_scrollbar.sizeHint().width()+17)
    t.set_visible_window(10000,90000)
    for _ in range(5):
        t.resizeEvent(QResizeEvent(t.size(),t.size()))
    assert t.visible_duration_ms==90000
    t.deleteLater()


def test_long_review_shapes_only_visible_rows_and_corrects_scrolled_rows(monkeypatch):
    from twobyteasr.glossary.glossary_proofread import CaptionReviewList
    view=CaptionReviewList();view.resize(900,600)
    rows=[dict(cue_id=str(i),base='A long sentence 字幕 '*20,origin='A long sentence 字幕 '*20,
        number=f'#{i}',time='00:00:01.0',speaker_id='s',speaker=('speaker','#ffffff'),
        issues=[],applied=False,remembered=None) for i in range(7000)]
    calls=[];original=view._row_layout
    monkeypatch.setattr(view,'_row_layout',lambda row:(calls.append(row['cue_id']),original(row))[1])
    view.set_rows(rows)
    assert len(set(calls))<64
    view.show();APP.processEvents()
    view.bar.setValue(view.bar.maximum());APP.processEvents()
    assert '6999' in view._height_cache
    assert len(view._layout_cache)<128
    assert view.offsets[-1]==sum(view.heights)
    view.close();view.deleteLater();APP.processEvents()


@pytest.mark.parametrize('thumbnail',[True,False])
@pytest.mark.parametrize('surface',['panel','blank','card'])
def test_external_pool_drop_keeps_graph_duration_and_usage(tmp_path,monkeypatch,thumbnail,surface):
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.studio.source_media_cache import SourceWaveCache
    from twobyteasr.studio.studio_media_pool_ui import StudioMediaPoolPanel
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    from twobyteasr.timeline.studio_media_pool import media_usage
    main=tmp_path/'main.mp4';main.write_bytes(b'input')
    added=tmp_path/'added.mp4';added.write_bytes(b'input')
    project=SubtitleProject(media=StudioMedia(path=str(main),duration_ms=600000))
    project.validate()
    page=QWidget();page.project=project;page.undo_stack=QUndoStack(page)
    cache=SourceWaveCache(page)
    page.source_monitor=SimpleNamespace(wave_cache=cache,asset_id='',project=None,asset=None,refresh_targets=lambda:None)
    panel=StudioMediaPoolPanel(page);page.media_pool_panel=panel
    panel.refresh();panel.resize(600,600);page.resize(650,650);page.show();panel.show()
    panel.assets.set_presentation(thumbnail,172)
    monkeypatch.setattr('twobyteasr.studio.studio_media_pool_ui.probe_media_identity',
        lambda path:dict(duration_ms=1401983,has_audio=True,has_video=True,width=320,height=180))
    before=copy.deepcopy((project.video_tracks,project.audio_tracks,project.av_track_groups,sequence_of(project)))
    paths=[str(added)]
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
    receiver=panel if surface=='panel' else panel.assets.viewport()
    point=receiver.rect().bottomRight()-receiver.rect().topLeft() if surface=='blank' else receiver.rect().center()
    point.setX(max(1,min(receiver.width()-3,point.x())));point.setY(max(1,min(receiver.height()-3,point.y())))
    enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    APP.sendEvent(receiver,enter)
    drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    APP.sendEvent(receiver,drop)
    assert enter.isAccepted() and drop.isAccepted()
    deadline=time.monotonic()+5
    while len(project.media_pool)<2 and time.monotonic()<deadline:
        APP.processEvents();time.sleep(.005)
    assert len(project.media_pool)==2
    assert (project.video_tracks,project.audio_tracks,project.av_track_groups,sequence_of(project))==before
    asset=next(x for x in project.media_pool if x.canonical_source==str(added))
    assert not media_usage(project)[asset.asset_id]
    page.undo_stack.undo()
    assert len(project.media_pool)==1
    assert (project.video_tracks,project.audio_tracks,project.av_track_groups,sequence_of(project))==before
    panel.shutdown();cache.close();page.close();page.deleteLater();APP.processEvents()


def test_waveform_paint_never_reads_files_and_late_project_result_is_rejected():
    import numpy as np
    from PySide6.QtCore import QRectF
    from twobyteasr.playback.waveform_cache import WaveformLevel
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    from twobyteasr.studio.waveform_tiles import WaveformTileWorker
    class Cache:
        calls=[]
        def read_window(self,start,end,pixels):
            self.calls.append((start,end))
            pairs=np.tile(np.array([[-.5,.5]],dtype=np.float32),(max(1,int((end-start)/10)),1))
            return WaveformLevel(0,6000,10,'fixture'),pairs
    cache=Cache();t=WaveformTimeline()
    t._paint_geometry_cache={};t._waveform_tile_jobs={}
    pieces=t._waveform_envelope_tiles(cache,10000,15000,228,1028,QRectF(0,100,1600,40),0,60000)
    assert not pieces and not cache.calls and t._waveform_tile_jobs
    worker=WaveformTileWorker(t);worker.ready.connect(t._waveform_tile_ready)
    worker.submit(t._waveform_tile_jobs,t.project)
    deadline=time.monotonic()+5
    while not getattr(t,'_waveform_tile_cache',{}) and time.monotonic()<deadline:
        APP.processEvents();time.sleep(.005)
    assert t._waveform_tile_cache and cache.calls
    first=next(iter(t._waveform_tile_cache.values()))
    snapshot=dict(t._waveform_tile_cache)
    t._waveform_tile_ready(object(),('old',),cache,(*first,True))
    assert t._waveform_tile_cache==snapshot
    worker.close();worker.work.thread.join(timeout=2)
    t.deleteLater();APP.processEvents()


@pytest.mark.parametrize('factor',[.8,1,1.1,1.35,1.75,2])
def test_color_wheel_and_painted_square_share_center_after_ui_zoom(factor):
    from PySide6.QtCore import QPointF
    from twobyteasr.app.ui_zoom import apply_to
    from twobyteasr.design.fill_picker import ColorWheel
    w=ColorWheel();w.show();APP.processEvents()
    apply_to(w,factor);APP.processEvents()
    rect=w.sv.plane_rect()
    center=QPointF(w.sv.pos())+rect.center()
    assert abs(center.x()-w.width()/2)<=.51
    assert abs(center.y()-w.height()/2)<=.51
    w.sv._apply(rect.center())
    assert abs(w.sv._sat-.5)<1e-6 and abs(w.sv._val-.5)<1e-6
    w.close();w.deleteLater();APP.processEvents()


def test_solid_property_dialog_has_no_unsupported_gradient_modes():
    from PySide6.QtGui import QColor
    from twobyteasr.caption_style.studio_fill_editors import FillEditorDialog
    seen=[]
    d=FillEditorDialog('#80335577',title='阴影',allow_gradients=False,
        preview_update=lambda widget,color:seen.append(color.name(QColor.HexArgb)))
    assert len(d.mode_group.buttons())==1
    d.picker.set_color(QColor('#aabbcc'));d._picker_changed(d.picker.color())
    assert d.selectedColor()==QColor('#aabbcc') and seen[-1]=='#ffaabbcc'
    assert d.windowTitle()=='阴影'
    d.deleteLater();APP.processEvents()


def test_stale_source_start_does_not_release_new_start_ticket():
    import threading
    from twobyteasr.studio.studio_source_monitor import StudioSourceMonitor
    page=QWidget();page.project=None
    monitor=StudioSourceMonitor(page)
    done=threading.Event()
    monitor.epoch=2;monitor.starting=True;monitor._starting_epoch=2
    monitor._controller_ready(1,SimpleNamespace(close=done.set),'')
    assert monitor.starting and monitor._starting_epoch==2 and monitor.controller is None
    assert done.wait(1)
    monitor.starting=False;monitor._starting_epoch=None
    monitor.shutdown();page.deleteLater();APP.processEvents()


def test_source_reset_retains_only_old_hidden_host_until_controller_closes():
    import threading
    from twobyteasr.studio.studio_source_monitor import StudioSourceMonitor
    page=QWidget();page.project=None
    monitor=StudioSourceMonitor(page)
    release=threading.Event();closed=threading.Event()
    def close():
        release.wait(2);closed.set()
    monitor.controller=SimpleNamespace(running=True,post_set_paused=lambda *_:None,close=close)
    old=monitor.surface;epoch=monitor.epoch
    monitor.reset()
    assert monitor.surface is not old and old.isHidden()
    assert monitor._retired_surfaces[epoch] is old
    release.set();assert closed.wait(1)
    deadline=time.monotonic()+1
    while monitor._retired_surfaces and time.monotonic()<deadline:
        APP.processEvents();time.sleep(.005)
    assert not monitor._retired_surfaces
    monitor.shutdown();page.deleteLater();APP.processEvents()


def test_shadow_rgba_adapts_to_one_rgb_and_opacity_edit():
    from PySide6.QtWidgets import QLineEdit,QSpinBox
    from twobyteasr.caption_style.studio_style_controller import StudioStyleController
    editor=QLineEdit('#000000');opacity=QSpinBox();opacity.setRange(0,100);opacity.setValue(24)
    changed=[]
    page=SimpleNamespace(style_shadow_color=editor,style_shadow_opacity=opacity,
        _updating_style_ui=False,_style_control_changed=lambda *fields:changed.append(fields))
    StudioStyleController._set_style_color(SimpleNamespace(page=page),editor,'#A655AAEE')
    assert editor.text()=='#55aaee' and opacity.value()==65
    assert changed==[('shadow.color','shadow.opacity')] and not page._updating_style_ui


def test_explicit_effect_color_updates_a_previous_local_default():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.caption_style.scoped_style import style_patch_command,effective_layer_recipe
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('c',0,2000,'a')])
    p.validate()
    p.cues[0].appearance_override={'_recipe_patch':{'effects':{'glow':{'color':'#000000'}}}}
    command=style_patch_command(p,['c'],{},recipe_patch={'effects':{'glow':{'color':'#A6EE55AA'}}})
    command.redo()
    assert effective_layer_recipe(p,p.cues[0]).to_dict()['effects']['glow']['color']=='#A6EE55AA'
    command.undo()
    assert p.cues[0].appearance_override['_recipe_patch']['effects']['glow']['color']=='#000000'


def test_review_metadata_is_detached_once_and_survives_live_edits():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.glossary.glossary_proofread import _review_copy
    from twobyteasr.studio.subtitle_text_targets import review_project,text_entries
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('c',0,2000,'source')],
        generation_metadata={'translations':{'c':'译文'},'asr_cue_states':{'c':{'words':['before']}}})
    p.validate();view=_review_copy(p)
    reviewed=review_project(view,text_entries(view))
    assert reviewed.generation_metadata['translations'] is view.generation_metadata['translations']
    p.generation_metadata['translations']['c']='later edit'
    p.generation_metadata['asr_cue_states']['c']['words'].append('after')
    assert reviewed.generation_metadata['translations']['c']=='译文'
    assert reviewed.generation_metadata['asr_cue_states']['c']['words']==['before']


def test_pool_catalog_keeps_qc_and_playback_valid_but_saves_new_asset(tmp_path):
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.projects.studio_runtime_state import state_for
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.timeline.studio_media_commands import media_pool_import_command
    from twobyteasr.timeline.studio_media_pool import add_media_asset
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('c',0,2000,'text')]);p.validate()
    runtime=state_for(p);store=StudioRevisionStore(p);runtime.subscribe(store.consume)
    before=(runtime.qc_revision,runtime.playback_revision,store.render.cues)
    path=tmp_path/'asset.mp4';path.write_bytes(b'fixture')
    mutate=lambda project:add_media_asset(project,path,duration_ms=4000,
        video_metadata={'has_video':True},materialize_audio=False)
    command=media_pool_import_command(p,mutate);command.redo()
    assert (runtime.qc_revision,runtime.playback_revision)==before[:2]
    assert store.render.cues is before[2]
    assert len(store.persistence.to_payload()['media_pool'])==1
    assert media_pool_import_command(p,mutate) is None
    command.undo();assert not p.media_pool
    assert not store.persistence.to_payload()['media_pool']


def test_secondary_source_insert_does_not_rewrite_primary_caption_sequence(tmp_path):
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.projects.studio_runtime_state import state_for,DirtyDomain as D
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    from twobyteasr.timeline.studio_media_pool import add_media_asset
    from twobyteasr.timeline.source_selection import SourceSelection,SourceInsertCommand
    path=tmp_path/'main.mp4';path.write_bytes(b'fixture')
    source=tmp_path/'new.mp4';source.write_bytes(b'fixture')
    cue=StudioCue('c',0,2000,'text')
    p=SubtitleProject(StudioMedia(str(path),duration_ms=100000),cues=[cue]);p.validate()
    p.render_settings['_cue_domain']='timeline'
    asset=add_media_asset(p,source,duration_ms=12000,video_metadata={'has_video':True},materialize_audio=False)
    runtime=state_for(p);changes=[];runtime.subscribe(changes.append)
    sequence=sequence_of(p);before=copy.deepcopy(sequence)
    command=SourceInsertCommand(p,SourceSelection(asset.asset_id,2000,6000,'video'),3000)
    assert sequence_of(p) is sequence and sequence==before
    command.redo()
    assert sequence_of(p) is sequence and sequence==before and p.cues[0] is cue
    assert not changes[-1].touches(D.SEQUENCE_STRUCTURE|D.TIMELINE_INDEX|D.CUE_MODEL|D.CUE_TIMING)
    command.undo();assert sequence_of(p) is sequence and sequence==before


def test_missing_source_detaches_previous_picture_and_ends_loading(tmp_path):
    import threading
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.timeline.studio_media_pool import add_media_asset
    from twobyteasr.studio.studio_source_monitor import StudioSourceMonitor
    p=SubtitleProject(StudioMedia(''));p.validate()
    asset=add_media_asset(p,tmp_path/'missing.mp4',duration_ms=12000,
        video_metadata={'has_video':True},materialize_audio=False)
    page=QWidget();page.project=p
    m=StudioSourceMonitor(page);m.project=p;m.asset_id=asset.asset_id;m.loading=True
    done=threading.Event()
    m.controller=SimpleNamespace(running=True,close=done.set,post_set_paused=lambda *_:None)
    old=m.surface;m._load_current()
    assert not m.loading and m.controller is None and old.isHidden()
    assert '缺失' in m.status.text() and done.wait(1)
    m.shutdown();page.deleteLater();APP.processEvents()


def test_dense_original_and_translation_paint_does_not_query_qt_geometry_per_cue(monkeypatch):
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    cues=[StudioCue(str(i),i*3000,i*3000+2200,'文字 '+str(i)) for i in range(7000)]
    p=SubtitleProject(StudioMedia('missing.mp4',duration_ms=21478087),cues=cues,
        generation_metadata={'translations':{c.id:'译文 '+c.id for c in cues}})
    p.validate()
    t=WaveformTimeline();t.resize(1400,600);t.set_project(p);t.set_bilingual(True)
    t.set_visible_window(0,21478087);t._thumbnails.set_paused(True)
    calls=[];original=t._time_to_x
    monkeypatch.setattr(t,'_time_to_x',lambda ms:(calls.append(ms),original(ms))[1])
    t.show();APP.processEvents();image=t.grab().toImage()
    assert not image.isNull()
    assert t._last_paint_stats.get('dense_cue_spans',0)>0
    assert t._last_paint_stats.get('dense_translation_spans',0)>0
    assert len(calls)<100, 'dense cue edges must use one captured viewport transform'
    t._thumbnails.close();t._thumbnails.thread.join(2)
    t.close();t.deleteLater();APP.processEvents()


def test_sample_qcolor_stroke_matches_its_argb_pixels():
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor,QFont,QPainter,QPixmap
    from twobyteasr.studio.studio_helpers import render_style_sample
    def image(outline):
        surface=QPixmap(320,110);surface.fill(QColor('#343448'))
        painter=QPainter(surface);painter.setRenderHint(QPainter.Antialiasing)
        render_style_sample(painter,text='Aa 123',font=QFont('Arial',32),
            baseline=QPointF(20,75),fill='#44CC88',outline=outline,outline_width=8)
        painter.end()
        return surface.toImage()
    assert image(QColor('#CCFF8A33'))==image('#CCFF8A33')
    assert image(QColor('#00FF8A33'))==image('#00FF8A33')


def test_fully_transparent_sample_glow_adds_no_pixels():
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor,QFont,QPainter,QPixmap
    from twobyteasr.studio.studio_helpers import render_style_sample
    def image(glow=None):
        surface=QPixmap(320,110);surface.fill(QColor('#343448'))
        painter=QPainter(surface)
        render_style_sample(painter,text='Aa 123',font=QFont('Arial',32),
            baseline=QPointF(20,75),fill='#44CC88',outline='#000000',glow=glow)
        painter.end()
        return surface.toImage()
    assert image()==image(dict(enabled=True,color='#00FF0000',blur=6,opacity=1))
    assert image()==image(dict(enabled=True,color='#FFFF0000',blur=6,opacity=0))
    assert image()!=image(dict(enabled=True,color='#FFFF0000',blur=6,opacity=1))
