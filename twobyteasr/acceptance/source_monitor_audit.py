"""Real source-monitor UI, mpv, persistence, drag and production-export audit."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import statistics
import threading
import time
import traceback


def start(window, out):
    from PySide6.QtCore import QObject, QTimer, Qt, QPoint, QPointF
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..timeline.source_selection import SourceSelection, SourceInsertCommand, source_state
    from ..timeline.studio_media_pool import add_media_asset, create_video_track
    from ..timeline.studio_media_commands import media_graph_command
    from ..projects.studio_project import load_project, save_project
    from ..exports.video_export import capture_video_graph
    from ..exports.studio_render import RenderJob, RenderSettings, run_render_job
    from ..exports.export_timeline import write_export_ass
    from ..system.platform_media import ffmpeg_tool
    from ..playback.audio_graph import capture_audio_graph
    from ..studio.studio_source_monitor import source_mime

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = dict(checks={}, screenshots=[], error='', measurements={})
            self.page = None
            self.started = time.monotonic(); self.due = 0
            self.last_beat = time.perf_counter(); self.beats = []
            self.steps = self.run()
            self.timer = QTimer(self); self.timer.setInterval(8); self.timer.timeout.connect(self.tick); self.timer.start()

        def check(self, label, value):
            self.result['checks'][label] = bool(value)
            self.save()
            if not value:
                raise AssertionError(label)

        def save(self):
            (out/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')

        def tick(self):
            now=time.monotonic(); beat=time.perf_counter()
            self.beats.append((beat-self.last_beat)*1000); self.last_beat=beat
            if now < self.due:
                return
            try:
                if now-self.started > 500:
                    raise TimeoutError('source monitor acceptance deadline')
                self.due = now+next(self.steps)
            except StopIteration:
                self.result['finished']=True; self.finish()
            except Exception:
                self.result['error']=traceback.format_exc()
                try:
                    self.capture('failure')
                except Exception:
                    pass
                self.finish()

        def wait(self, predicate, timeout=20, label='wait'):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline and not predicate():
                yield .05
            self.check(label, predicate())

        def capture(self, name):
            path=out/(name+'.png'); _capture(window,path)
            self.result['screenshots'].append(str(path)); self.save()

        def select(self, asset_id, double=True):
            panel=self.page.media_pool_panel
            panel.search.clear()
            for row in range(panel.proxy.rowCount()):
                index=panel.proxy.index(row,0)
                if index.data(Qt.ItemDataRole.UserRole)==asset_id:
                    panel.assets.setCurrentIndex(index); panel.assets.scrollTo(index)
                    if double:
                        # QListView doubleClicked is exercised with actual Qt mouse input.
                        rect=panel.assets.visualRect(index)
                        QTest.mouseClick(panel.assets.viewport(),Qt.MouseButton.LeftButton,
                                         Qt.KeyboardModifier.NoModifier,rect.center())
                        QTest.mouseDClick(panel.assets.viewport(),Qt.MouseButton.LeftButton,
                                          Qt.KeyboardModifier.NoModifier,rect.center())
                        QTest.mouseRelease(panel.assets.viewport(),Qt.MouseButton.LeftButton,
                                           Qt.KeyboardModifier.NoModifier,rect.center())
                    return
            raise KeyError(asset_id)

        def run(self):
            from ..test_isolation import require_isolated_paths
            self.result['isolated_paths']={k:str(v) for k,v in require_isolated_paths('source-monitor',emit=lambda *_:None).items()}
            yield .3
            window.open_studio_project(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            yield from self.wait(lambda: window.built_page('studio') is not None and
                window.built_page('studio').project is not None and window.built_page('studio')._readiness.ready,
                90,'normal MainWindow ready')
            p=self.page=window.built_page('studio'); t=p.timeline; panel=p.media_pool_panel; m=p.source_monitor
            self.result['measurements']['layout']={'window':[window.width(),window.height()],
                'device_pixel_ratio':window.devicePixelRatioF(),'source_parent':'left subtitle tab'}
            p._toggle_drawer(p.media_pool_tab_index)
            p.context_drawer.setCurrentIndex(p.media_pool_tab_index)
            p.video.set_paused(True); p.volume_slider.setValue(0); m.volume.setValue(0)
            fixtures=Path(os.environ['SOURCE_MONITOR_FIXTURES'])
            original_cues=copy.deepcopy(p.project.cues)
            before_graph=copy.deepcopy((p.project.video_tracks,p.project.audio_tracks,p.project.av_track_groups))
            panel.import_paths([fixtures/name for name in ('source-two-audio.mp4','music.wav','silent.mp4','long-source.mp4')])
            yield from self.wait(lambda:len(p.project.media_pool)==5,40,'background multi-import finished')
            self.check('pool import leaves timeline unchanged',(p.project.video_tracks,p.project.audio_tracks,p.project.av_track_groups)==before_graph)
            assets={Path(a.canonical_source).name:a for a in p.project.media_pool}
            video=assets['source-two-audio.mp4']; music=assets['music.wav']; silent=assets['silent.mp4']; long=assets['long-source.mp4']
            self.check('stream metadata includes both audio streams',len(video.audio_metadata.get('streams',[]))==2)
            self.check('silent video classified',silent.audio_metadata['has_audio'] is False)
            self.check('pure audio classified',music.video_metadata['has_video'] is False)
            panel.search.setText('silent'); yield .2
            self.check('search same model',panel.proxy.rowCount()==1 and panel.model.rowCount()==5)
            panel.search.clear(); self.select(video.asset_id,False)
            selected=panel.selected_asset_id(); panel._presentation(False); yield .15
            self.check('list mode retains selection',panel.selected_asset_id()==selected)
            panel._presentation(True); panel.thumbnail_size.setValue(150); yield .7
            self.check('thumbnail mode retains selection',panel.selected_asset_id()==selected)
            self.check('actual video thumbnails decoded',bool(panel.assets.thumbnails.memory))
            self.capture('media-pool-thumbnails')
            p._seek(60); yield .6
            sequence_position=t.playhead_ms
            sequence_view=(t.visible_start_ms,t.visible_duration_ms)
            undo_before=p.undo_stack.count()
            self.select(video.asset_id)
            yield from self.wait(lambda:m.asset_id==video.asset_id and m.controller is not None and not m.loading,25,'double click opens real source mpv')
            self.check('source monitor occupies left subtitle region',p.upper_splitter.widget(0) is p.source_tabs
                and p.source_tabs.isAncestorOf(m) and not p.source_tabs.isAncestorOf(p.video))
            self.check('double click does not insert',p.undo_stack.count()==undo_before)
            self.check('source preserves sequence playhead and view',abs(t.playhead_ms-sequence_position)<2 and
                (t.visible_start_ms,t.visible_duration_ms)==sequence_view and p.project.cues==original_cues)
            m.seek(10000); yield .5
            m.ruler.setFocus(); QTest.keyClick(m.ruler,Qt.Key.Key_I); yield .1
            m.seek(15000); yield .4
            m.ruler.setFocus(); QTest.keyClick(m.ruler,Qt.Key.Key_O); yield .1
            self.check('I O set independent source range',m.range_ms()==(10000,15000))
            m.stream.setCurrentIndex(1); yield .5
            yield from self.wait(lambda:not m.loading,10,'selected audio stream load')
            self.check('source selected stream is actual mpv aid 2',m.controller.get_property('aid')==2)
            m.content_scroll.ensureWidgetVisible(m.ruler); yield .1
            start=QPoint(round(m.ruler.x_for(10000)),40)
            end=QPoint(round(m.ruler.x_for(10400)),40)
            QTest.mousePress(m.ruler,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
            QTest.mouseMove(m.ruler,end); QTest.mouseRelease(m.ruler,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,end)
            self.check('source range boundary can be dragged',abs(m.range_ms()[0]-10400)<=80 and m.range_ms()[1]==15000)
            m.set_boundary('in_ms',12000); m.set_boundary('out_ms',12400)
            m.play_selection(); yield .8
            self.check('selected-range playback stops at exclusive out',m.paused and abs(m.position_ms-12400)<=40)
            m.set_boundary('out_ms',15000); m.set_boundary('in_ms',10000)
            m.seek(11000); yield .6
            m.controller.screenshot_to_file(str(out/'source-real-frame.png'),mode='video')
            self.capture('source-video-range')
            # Input focus owns its keys; it cannot redefine a range or play.
            range_before=m.range_ms(); m.time_edit.setFocus(); m.time_edit.setText('00:00:11.000')
            QTest.keyClick(m.time_edit,Qt.Key.Key_Space); QTest.keyClick(m.time_edit,Qt.Key.Key_I)
            self.check('text field keeps playback shortcuts',m.paused and m.range_ms()==range_before)
            m.time_edit.setText('00:00:11.000'); m.ruler.setFocus()
            if os.environ.get('SOURCE_MONITOR_LAYOUT_ONLY')=='1':
                self.result['measurements']['source_controls']={w.objectName() or w.text() if hasattr(w,'text') else type(w).__name__:
                    [w.width(),w.height(),w.isVisible()] for w in (m.insert_button,m.in_edit,m.out_edit,m.time_edit)}
                m.content_scroll.ensureWidgetVisible(m.insert_button)
                yield .25
                self.check('source insertion control visible',m.insert_button.isVisible() and m.insert_button.width()>60)
                self.check('source monitor is in left subtitle region',p.upper_splitter.widget(0) is p.source_tabs
                    and p.source_tabs.isAncestorOf(m) and not p.source_tabs.isAncestorOf(p.video))
                self.capture('source-layout')
                return
            if os.environ.get('SOURCE_MONITOR_HANDLES_ONLY')=='1':
                from .source_handles_audit import run
                yield from run(self)
                return
            # Mute only the old fixture's sound for an unambiguous audible matrix.
            p.project.audio_tracks[0].muted=True
            for mode,position in (('av',60000),('video',65000),('audio',70000)):
                t.playhead_ms=position; m.set_mode(mode)
                m.video_target.setCurrentIndex(0); m.audio_target.setCurrentIndex(0)
                before=p.undo_stack.index(); m.content_scroll.ensureWidgetVisible(m.insert_button); yield .1
                if mode == 'av':
                    self.capture('source-insert-controls')
                QTest.mouseClick(m.insert_button,Qt.MouseButton.LeftButton); yield .25
                self.check(mode+' insertion one undo step',p.undo_stack.index()==before+1)
            clips=[c for tr in p.project.video_tracks for c in tr.clips if c.asset_id==video.asset_id]
            sounds=[c for tr in p.project.audio_tracks for c in tr.clips if c.asset_id==video.asset_id]
            self.check('AV and video geometry exact',[(c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms) for c in clips]==
                       [(60000,65000,10000,15000),(65000,70000,10000,15000)])
            self.check('only audio has no image clip',len(sounds)==2 and all(c.stream_index==1 for c in sounds))
            self.check('AV linked to its video',any(c.linked_video_clip_id==clips[0].id for c in sounds))
            self.check('video only has no linked audio',not any(c.linked_video_clip_id==clips[1].id for c in sounds))
            m.set_boundary('in_ms',15000); m.set_boundary('out_ms',20000)
            # Change out before in when two ranges share an old endpoint.
            if m.range_ms()!=(15000,20000):
                m.set_boundary('out_ms',20000); m.set_boundary('in_ms',15000)
            t.playhead_ms=75000; m.set_mode('video'); m.video_target.setCurrentIndex(0); m.insert()
            yield .2
            m.clear_range(); m.set_boundary('out_ms',3000)
            self.check('old clips retain captured range',all(c.source_in_ms==10000 and c.source_out_ms==15000 for c in clips))
            after=copy.deepcopy((p.project.video_tracks,p.project.audio_tracks,p.project.av_track_groups))
            p.undo_stack.undo(); yield .15; p.undo_stack.redo(); yield .15
            self.check('undo redo restores tracks clips and links',(p.project.video_tracks,p.project.audio_tracks,p.project.av_track_groups)==after)
            # Real source pause/play and sequence mutual exclusion.
            m.ruler.setFocus(); m.seek(11000); yield .3
            QTest.keyClick(m.ruler,Qt.Key.Key_Space); yield .6
            self.check('source Space advances only source',not m.paused and m.position_ms>11000 and p.video._paused)
            m.pause(); p.source_tabs.setCurrentIndex(0); yield .2
            t.setFocus(); QTest.keyClick(t,Qt.Key.Key_Space); yield .6
            self.check('timeline Space pauses source and plays sequence',m.paused and p.video.playback_intended)
            p.video.set_paused(True)
            # Audio and silent sources expose compatible modes only.
            self.select(music.asset_id); yield from self.wait(lambda:m.asset_id==music.asset_id and not m.loading,15,'audio source ready')
            yield from self.wait(lambda:m.peaks is not None,15,'audio waveform decoded')
            self.check('pure audio mode availability',m.mode_buttons['audio'].isEnabled() and not m.mode_buttons['video'].isEnabled() and not m.mode_buttons['av'].isEnabled())
            m.zoom.setValue(6); yield .6
            self.check('waveform zoom window',m.view_span==2000 and m.scroll.maximum()==10000)
            self.capture('source-audio-waveform')
            m.waveform.setFocus(); m.seek(2000); yield .25; m.toggle_play(); yield .6
            self.check('real audio source plays',m.position_ms>2200 and not m.paused)
            m.pause()
            self.select(silent.asset_id); yield from self.wait(lambda:m.asset_id==silent.asset_id and not m.loading,15,'silent video source ready')
            self.check('silent video mode availability',m.mode_buttons['video'].isEnabled() and not m.mode_buttons['audio'].isEnabled() and not m.mode_buttons['av'].isEnabled())
            # Last request wins while real mpv is changing files.
            for identity in (video.asset_id,music.asset_id,silent.asset_id,video.asset_id):
                m.open_asset(identity)
            yield from self.wait(lambda:m.asset_id==video.asset_id and not m.loading,20,'rapid switch settles on last source')
            self.check('no stale waveform on video',m.visual.currentIndex()==0 and m.peaks is None)
            # Exact source MIME is delivered through the timeline's native Qt drag events.
            m.clear_range(); m.set_boundary('in_ms',1000); m.set_boundary('out_ms',4000)
            selection=SourceSelection.capture(p.project,video.asset_id,'video')
            target=next(tr for tr in p.project.video_tracks if any(c.timeline_in_ms==65000 for c in tr.clips))
            t.set_visible_window(50000,50000); yield .2
            row=t._video_track_rects()[target.id]
            point=QPoint(round(t._time_to_x(85000)),round(row.center().y()))
            mime=source_mime(p.project,selection)
            for event in (QDragEnterEvent(point,Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier),
                          QDragMoveEvent(point,Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)):
                QApplication.sendEvent(t,event)
            placement=copy.deepcopy(p.source_timeline_drop.overlay.placement)
            self.check('drag preview has real selected duration',placement['end_ms']-placement['start_ms']==3000)
            self.capture('drag-selection-preview')
            QApplication.sendEvent(t,QDropEvent(QPointF(point),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
            inserted=next(c for tr in p.project.video_tracks if tr.id==target.id for c in tr.clips if c.source_in_ms==1000)
            self.check('drop matches preview exactly',(inserted.timeline_in_ms,inserted.timeline_out_ms)==(placement['start_ms'],placement['end_ms']))
            # Validation errors cannot commit partial graphs.
            before=p.undo_stack.index()
            target=next(tr for tr in p.project.video_tracks if tr.id==target.id)
            target.locked=True
            m.video_target.setCurrentIndex(m.video_target.findData(target.id)); m.set_mode('video'); m.insert()
            self.check('locked track rejection visible',p.undo_stack.index()==before and '锁定' in m.status.text())
            target.locked=False
            t.playhead_ms=66000; m.insert()
            self.check('collision rejection visible',p.undo_stack.index()==before and '重叠' in m.status.text())
            m.video_target.setCurrentIndex(0)
            self.check('missing track has explicit create entry',m.video_target.currentData()=='new')
            original_path=video.canonical_source; video.canonical_source=str(fixtures/'missing.mp4'); video.offline=True
            m.open_asset(video.asset_id); yield .15
            self.check('missing file recovery visible','缺失' in m.status.text())
            video.canonical_source=original_path; video.offline=False
            m.open_asset(video.asset_id); yield .3
            # Save and reopen the actual UI-created graph.
            path=out/'saved.2byteproj'; p.project_path=path
            # Save owns a nested progress event loop; keep the audit generator
            # out of that loop while the normal controller freezes/writes.
            self.timer.stop()
            try:
                p.save()
            finally:
                self.timer.start()
            self.check('normal manual save wrote project',path.is_file())
            saved=load_project(path)
            self.check('saved graph and source state preserved',(saved.video_tracks,saved.audio_tracks,saved.av_track_groups)==
                (p.project.video_tracks,p.project.audio_tracks,p.project.av_track_groups) and
                saved.studio_state['source_monitor']==p.project.studio_state['source_monitor'])
            previous=p.project; p.undo_stack.setClean()
            p._close_project_session(reason='source-monitor saved-project reopen')
            p.open_project(path,skip_dirty_guard=True)
            yield from self.wait(lambda:p.project is not previous and p.project is not None and p._readiness.ready,60,'actual UI reopen ready')
            self.check('UI reopened graph identical',(p.project.video_tracks,p.project.audio_tracks,p.project.av_track_groups)==
                (saved.video_tracks,saved.audio_tracks,saved.av_track_groups))
            self.check('view preference restored',p.media_pool_panel.assets.thumbnail_mode and p.media_pool_panel.thumbnail_size.value()==150)
            self.check('existing subtitle timing unchanged',p.project.cues==original_cues)
            # Production export is isolated on a background worker. Verify independently below.
            self.export_done=False; self.export_error=''
            from ..timeline.studio_edit_sequence import sequence_of
            sequence=sequence_of(p.project); old_range=(sequence.in_point_ms,sequence.out_point_ms)
            sequence.in_point_ms,sequence.out_point_ms=60000,80000
            p._open_render_dialog(); yield .5
            self.check('normal export workspace opens',p.export_workspace is not None and p.export_workspace.isVisible())
            ui_job=p.export_workspace._job(out/'three-modes.mp4',settings=RenderSettings(encoder='libx264',
                width=320,height=180,fps=25,audio_codec='aac',preset='ultrafast'))
            self.check('UI export job captures project range',ui_job.start_seconds==60 and ui_job.duration_seconds==20)
            self.capture('export-workspace')
            sequence.in_point_ms,sequence.out_point_ms=old_range
            p._close_export_workspace(); yield .2
            def export():
                try:
                    run_render_job(ffmpeg_tool(),ui_job)
                except Exception:
                    self.export_error=traceback.format_exc()
                finally:
                    self.export_done=True
            threading.Thread(target=export,name='source-audit-export',daemon=True).start()
            yield from self.wait(lambda:self.export_done,120,'production export completed')
            self.check('production export successful',not self.export_error and (out/'three-modes.mp4').is_file())
            self.result['export_error']=self.export_error
            # 200 real files (hard-linked copies), including a two-hour video.
            aliases=out/'pool-200'; aliases.mkdir()
            paths=[]
            for i in range(195):
                source=fixtures/('source-two-audio.mp4' if i%3==0 else 'music.wav' if i%3==1 else 'silent.mp4')
                dest=aliases/(f'{i:03d}-'+source.name); os.link(source,dest); paths.append(dest)
            panel=p.media_pool_panel; panel.import_paths(paths)
            yield from self.wait(lambda:len(p.project.media_pool)==200,90,'200 assets imported')
            panel.search.clear(); panel._presentation(True); yield .5
            samples=[]
            for i in range(20):
                began=time.perf_counter(); panel.assets.verticalScrollBar().setValue(round(i/19*panel.assets.verticalScrollBar().maximum()))
                panel.assets.viewport().repaint(); samples.append((time.perf_counter()-began)*1000)
                yield .04
            self.result['measurements']['scroll_repaint_ms']={'median':statistics.median(samples),'max':max(samples)}
            self.check('200 assets use virtualized model',panel.model.rowCount()==200 and panel.assets.uniformItemSizes())
            self.check('bounded thumbnails memory',panel.assets.thumbnails.bytes<=panel.assets.thumbnails.limit)
            self.check('bounded waveform memory',len(m.wave_cache.memory)<=64)
            m.open_asset(long.asset_id); p.source_tabs.setCurrentIndex(1)
            yield from self.wait(lambda:m.asset_id==long.asset_id and not m.loading,20,'two hour source opens')
            m.seek(7190000); yield .8
            self.check('long source seeks near tail',abs(m.position_ms-7190000)<1500)
            self.capture('media-pool-200-long-source')
            p.source_tabs.setCurrentIndex(0); yield .2
            self.capture('sequence-after-inserts')
            self.result['measurements']['gui_heartbeat_ms']={'median':statistics.median(self.beats),'max':max(self.beats)}
            p.undo_stack.setClean()

        def finish(self):
            self.timer.stop()
            if self.page:
                self.page.video.set_paused(True); self.page.source_monitor.pause()
                self.page.undo_stack.setClean(); self.page._recovered_autosave_pending=False
            self.save()
            window.close()
            self.result['gui_shutdown']=not window.isVisible()
            self.save()
            QTimer.singleShot(200,QApplication.instance().quit)

    window._source_monitor_audit=Audit()
