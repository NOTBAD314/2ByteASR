"""Continuous, offline production-UI acceptance; no user data or settings writes."""
import copy
import json
from pathlib import Path
import time
import traceback
import os
from PySide6.QtCore import QTimer,Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton
from .studio_acceptance_audit import require


def start(window,out):
    def run():
        page=window.studio_page
        report={'passed':False,'checks':{},'exports':[],'frame_saves':[]}
        recorder=None;log=None
        def pump(seconds):
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                QApplication.processEvents();time.sleep(.003)
        def wait(predicate,timeout=90):
            until=time.monotonic()+timeout
            while not predicate() and time.monotonic()<until:pump(.03)
            require(predicate(),'UI wait timed out')
        def check(name,value):
            report['checks'][name]=bool(value);require(value,name)
            (out/'progress.json').write_text(json.dumps(report['checks'],ensure_ascii=False),encoding='utf-8')
        def click_text(host,text):
            button=next(b for b in host.findChildren(QPushButton) if b.text()==text)
            QTest.mouseClick(button,Qt.LeftButton);pump(.12)
        try:
            from .build_identity import load_build_identity
            from .studio_edit_sequence import projected_cues,sequence_of
            from .project_range import range_points
            from .studio_project import save_project,load_project
            from .processes import popen_hidden_subprocess
            report['build']=load_build_identity().to_dict()
            wait(lambda:page.project is not None and page._readiness.ready)
            if os.environ.get('TWOBYTEASR_FRAME_RESTART')=='1':
                check('restarted_frame_directory',Path(str(page.frame_capture.settings.value('frame_export/directory','')))==out/'frames')
                check('restarted_caption_option',str(page.frame_capture.settings.value('frame_export/subtitles','')).lower()=='false')
                page._seek(4.49);pump(.5)
                QTest.mouseClick(page.save_frame_button,Qt.LeftButton)
                wait(lambda:not page.frame_capture.busy,90)
                check('restarted_one_click_frame',page.frame_capture.last is not None)
                report['frame_saves'].append(page.frame_capture.last)
                report['passed']=True
                return
            page.video.set_paused(True);page._set_volume(0)
            primary=QApplication.primaryScreen()
            window.windowHandle().setScreen(primary)
            window.resize(1520,960);window.move(primary.availableGeometry().topLeft()+QPoint(60,50));pump(.5)
            import subprocess
            ffmpeg=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'
            log=(out/'capture.log').open('wb')
            recorder=popen_hidden_subprocess([str(ffmpeg),'-v','warning','-y','-f','lavfi','-i',
                f'gfxcapture=hwnd={int(window.winId())}:max_framerate=30:capture_cursor=0',
                '-c:v','h264_nvenc','-preset','p1','-cq','18',str(out/'continuous.mp4')],
                stdin=subprocess.PIPE,stdout=log,stderr=log,purpose='native cut range frame UI evidence')
            pump(.6)
            p=page.project
            signature=lambda:[(c.text,c.start_ms,c.end_ms) for c in projected_cues(page.project)]
            before=signature();before_data=copy.deepcopy(p.to_dict()['cues'])
            (out/'cut-before-raw.json').write_text(json.dumps(p.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
            (out/'cut-before-projection.json').write_text(json.dumps([vars(c) for c in projected_cues(p)],ensure_ascii=False,indent=2),encoding='utf-8')
            page._seek(4.5);pump(.6);page.timeline.setFocus()
            QTest.keyClick(page.timeline,Qt.Key_K,Qt.ControlModifier);pump(.3)
            check('keyboard_video_cut',len(sequence_of(p).segments)==2)
            (out/'cut-after-raw.json').write_text(json.dumps(p.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
            (out/'cut-after-projection.json').write_text(json.dumps([vars(c) for c in projected_cues(p)],ensure_ascii=False,indent=2),encoding='utf-8')
            check('cut_preserves_all_cues',signature()==before and p.to_dict()['cues']==before_data)
            page.undo_stack.undo();pump(.2);check('cut_undo',len(sequence_of(p).segments)==1)
            page.undo_stack.redo();pump(.2);check('cut_redo',signature()==before and len(sequence_of(p).segments)==2)
            page._seek(9.2);pump(.5);QTest.keyClick(page.timeline,Qt.Key_K,Qt.ControlModifier);pump(.2)
            check('repeated_cut',signature()==before and len(sequence_of(p).segments)==3)
            if os.environ.get('TWOBYTEASR_CUT_ONLY')=='1':
                saved=save_project(p,out/'cut-saved.2byteproj')
                restored=load_project(saved)
                check('cut_independent_save_reopen',restored.to_dict()['cues']==before_data and
                    [(c.text,c.start_ms,c.end_ms) for c in projected_cues(restored)]==before)
                report['passed']=True
                return
            page._seek(2.0);pump(.45);click_text(page.project_range_bar,'入点 I')
            page._seek(10.0);pump(.45);click_text(page.project_range_bar,'出点 O')
            points=range_points(p);check('independent_marks',abs(points[0]-2000)<60 and abs(points[1]-10000)<60)
            page._seek(14);pump(.4);check('seek_does_not_change_range',range_points(p)==points)
            field=page.project_range_bar.fields[0];field.setFocus();field.selectAll()
            QTest.keyClicks(field,'00:00:02.000');QTest.keyClick(field,Qt.Key_Return);pump(.2)
            check('exact_range_edit',range_points(p)[0]==2000)
            # Real manager controls, including table multi-selection and undo.
            from .studio_speaker_manager import SpeakerManagerDialog
            manager=SpeakerManagerDialog(page);manager.show();manager.tabs.setCurrentIndex(manager.tabs.count()-1);pump(.3)
            click_text(manager,'全选筛选结果');check('batch_selection',len(manager._selected_ids())==2)
            click_text(manager,'归入游戏背景声');check('batch_background',len(p.speakers)==1 and len(p.cues)==4)
            page.undo_stack.undo();manager.refresh();pump(.2);check('batch_undo',len(p.speakers)==2)
            manager.speaker_filter.setText('主要');click_text(manager,'全选筛选结果')
            check('filtered_selection_scope',manager._selected_ids()=={'A'})
            manager.speaker_filter.clear();click_text(manager,'全选筛选结果')
            click_text(manager,'删除身份，字幕移到统一轨')
            check('delete_identity_keeps_text',len(p.speakers)==1 and signature()==before)
            page.undo_stack.undo();manager.refresh();click_text(manager,'全选筛选结果')
            from PySide6.QtWidgets import QMessageBox
            confirmation={}
            def confirm_delete():
                dialog=QApplication.activeModalWidget()
                confirmation['counts']=isinstance(dialog,QMessageBox) and '2 个身份及 4 条字幕' in dialog.text()
                if isinstance(dialog,QMessageBox):QTest.mouseClick(dialog.button(QMessageBox.Yes),Qt.LeftButton)
            QTimer.singleShot(150,confirm_delete)
            click_text(manager,'删除所选人物及字幕')
            check('delete_captions_confirmation',confirmation.get('counts') and not p.cues)
            page.undo_stack.undo();manager.refresh();pump(.2)
            check('delete_captions_atomic_undo',len(p.speakers)==2 and signature()==before)
            click_text(manager,'全部合并为单轨');check('batch_single',len(p.speakers)==1 and len(p.cues)==4)
            manager.grab().save(str(out/'speaker-controls.png'));manager.close();pump(.3)
            # Apply an actual advanced recipe via the ordinary style controller.
            from .style_recipe import StyleRecipe
            recipe=StyleRecipe.from_dict({'name':'范围验收渐变','engine':'remotion',
                'typography':{'fontFamily':'Microsoft YaHei','fontSize':72,'bold':True},
                'layout':{'alignment':2,'marginV':85},'colors':{'fill':{'type':'linear','angle':90,
                    'stops':[{'color':'#FFFF50','pos':0},{'color':'#FF5040','pos':1}]}},
                'outline':{'layers':[{'color':'#000000','width':5}]},'motion':{},'background':{'enabled':False}})
            for cue in list(p.cues):
                page.select_cue(cue.id);page._apply_style_recipe(cue.id,recipe)
            pump(.5)
            page.select_cue('after')
            page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
            page.style_font_size.setValue(76);page._commit_style_now();pump(.3)
            check('advanced_applied_in_process',bool(p.style_recipes))
            page._seek(3.05);pump(.6)
            from .subtitle_stacking import project_stack_layout
            check('same_track_overlap_offset',bool(project_stack_layout(p).offsets))
            from .visual_snapshot import build_visual_cue_snapshot
            anchors={c.id:build_visual_cue_snapshot(p,c.id).position_y for c in projected_cues(p)}
            page._seek(5);pump(.4)
            check('stable_anchor_after_peer_ends',anchors=={c.id:build_visual_cue_snapshot(p,c.id).position_y for c in projected_cues(p)})
            save_project(p,out/'edited.2byteproj');reopened=load_project(out/'edited.2byteproj')
            check('reopen_cut_range_cues',len(sequence_of(reopened).segments)==3 and range_points(reopened)==range_points(p)
                  and [(c.text,c.start_ms,c.end_ms) for c in projected_cues(reopened)]==before)
            # Click saves: duplicate timestamps, optional captions, independence from seek.
            frames=out/'frames';frames.mkdir()
            page.frame_capture.settings.setValue('frame_export/directory',str(frames))
            for subtitles in (True,False):
                page._seek(3.05);pump(.5)
                page.frame_capture.settings.setValue('frame_export/subtitles',subtitles)
                page.frame_capture.last=None
                QTest.mouseClick(page.save_frame_button,Qt.LeftButton)
                page._seek(13.5)
                wait(lambda:not page.frame_capture.busy,120)
                receipt=page.frame_capture.last;check('frame_save_'+str(subtitles),receipt is not None)
                report['frame_saves'].append(receipt)
                check('frame_frozen_'+str(subtitles),abs(receipt['milliseconds']-3050)<70)
                check('frame_resolution_'+str(subtitles),(receipt['width'],receipt['height'])==(p.media.width,p.media.height))
            from PySide6.QtGui import QImage
            check('frame_unique_paths',report['frame_saves'][0]['path']!=report['frame_saves'][1]['path'])
            check('caption_toggle_changes_pixels',QImage(report['frame_saves'][0]['path'])!=QImage(report['frame_saves'][1]['path']))
            page._seek(8.25)  # No settling wait: pending seek must own the request.
            page.frame_capture.last=None;QTest.mouseClick(page.save_frame_button,Qt.LeftButton)
            wait(lambda:not page.frame_capture.busy,90)
            receipt=page.frame_capture.last
            check('immediate_seek_frame',receipt is not None and abs(receipt['milliseconds']-8250)<70)
            report['frame_saves'].append(receipt)
            page._seek(4.45);pump(.4);page._toggle_playback();pump(.12)
            page.frame_capture.last=None;QTest.mouseClick(page.save_frame_button,Qt.LeftButton)
            clicked=page.timeline.playhead_ms;wait(lambda:not page.frame_capture.busy,90);pump(.2)
            receipt=page.frame_capture.last
            check('playing_frame_frozen',receipt is not None and abs(receipt['milliseconds']-clicked)<70)
            check('frame_did_not_stop_playback',page.timeline.playhead_ms>clicked+100)
            report['frame_saves'].append(receipt);page.video.set_paused(True)
            # Production media graph command: a trimmed, faster picture-in-picture
            # instance must use its own source time and canvas geometry.
            from .studio_media_commands import media_graph_command
            from .studio_media_pool import create_video_track,add_video_clip
            from .studio_project import VideoTransform
            def overlay(graph_project):
                track=create_video_track(graph_project,'保存帧叠加验收')
                clip=add_video_clip(graph_project,track.id,graph_project.media_pool[0].asset_id,
                                    source_in_ms=12000,source_out_ms=20000,timeline_in_ms=2000)
                clip.playback_rate=2.;clip.timeline_out_ms=6000
                clip.transform=VideoTransform(scale_x=.3,scale_y=.3,position_x=.23,position_y=.24,rotation=12)
            page.undo_stack.push(media_graph_command(p,'保存帧多轨验收',overlay));pump(.3)
            page._seek(3.05);pump(.5);page.frame_capture.last=None
            QTest.mouseClick(page.save_frame_button,Qt.LeftButton);wait(lambda:not page.frame_capture.busy,90)
            receipt=page.frame_capture.last
            check('multitrack_frame_saved',receipt is not None and len(receipt['decode'])==2)
            check('multitrack_frame_source_time',abs(receipt['decode'][1]['source_seconds']-14.1)<.14)
            check('multitrack_frame_composited',QImage(receipt['path'])!=QImage(report['frame_saves'][1]['path']))
            report['frame_saves'].append(receipt);page.undo_stack.undo();pump(.2)
            # Enter export via its real toolbar control, all work in this process.
            QTest.mouseClick(page.studio_render_button,Qt.LeftButton)
            wait(lambda:page.export_workspace is not None)
            ui=page.export_workspace;pump(.4)
            check('export_uses_shared_points',range_points(ui.project)==range_points(p))
            ui.project_range_bar.apply((4000,4000));pump(.15)
            check('zero_range_blocks_start_and_queue',not ui.export_button.isEnabled() and not ui.queue_button.isEnabled())
            for points in ((8000,4000),(-1,4000),(0,999999)):
                ui.project_range_bar.apply(points);pump(.05)
                check('invalid_range_'+str(points),not ui.export_button.isEnabled() and not ui.queue_button.isEnabled())
            ui.project_range_bar.apply((7500,10000));pump(.2)
            ui.directory.setText(str(out/'exports'));ui.filename_prefix.clear();ui.filename_suffix.clear()
            ui.resolution.setCurrentIndex(ui.resolution.findData((1280,720)))
            if ui.encoder.findData('libx264')<0:ui.encoder.addItem('Software x264','libx264')
            ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'))
            ui.audio.setCurrentIndex(ui.audio.findData('aac'))
            for iteration in range(2):
                ui.filename.setText('range-'+str(iteration))
                if iteration:
                    ui._return_to_settings()
                    page.cue_controller.set_text('after','再次导出：本次人工修改')
                    pump(.2)
                began=time.perf_counter()
                QTest.mouseClick(ui.export_button,Qt.LeftButton)
                wait(lambda:ui._last_job is not None)
                wait(lambda:not ui._running,150);pump(.3)
                check('export_success_'+str(iteration),ui.pages.currentWidget()==ui.success_page)
                check('advanced_route_'+str(iteration),ui._advanced_route)
                report['exports'].append(dict(path=ui._last_job.output_path,elapsed_seconds=time.perf_counter()-began,
                    receipt=ui._last_job.completion_metadata))
            # Real preflight failure, then retry after correcting the target.
            ui._return_to_settings();ui.filename.setText('range-1')
            QTest.mouseClick(ui.export_button,Qt.LeftButton);pump(.2)
            check('existing_output_failure',ui.pages.currentWidget()==ui.failure_page)
            ui.filename.setText('retry-ok');ui._retry();wait(lambda:not ui._running,90)
            check('retry_success',ui.pages.currentWidget()==ui.success_page)
            ui._return_to_settings();ui.filename.setText('cancelled')
            QTest.mouseClick(ui.export_button,Qt.LeftButton);wait(lambda:ui._running)
            click_text(ui,'安全取消');wait(lambda:not ui._running,90)
            check('safe_cancel',ui.pages.currentWidget()==ui.setup_page and '取消' in ui.status.text())
            ui.filename.setText('after-cancel');QTest.mouseClick(ui.export_button,Qt.LeftButton)
            wait(lambda:not ui._running,90)
            check('export_after_cancel',ui.pages.currentWidget()==ui.success_page)
            # Real background queue freezes the authored range and recipe.
            ui._return_to_settings();ui.filename.setText('queued')
            from .studio_render_queue import get_render_queue,RenderQueueStore
            queue=get_render_queue(ui.ffmpeg)
            QTest.mouseClick(ui.queue_button,Qt.LeftButton);pump(.15)
            check('advanced_queue_created',bool(queue.jobs()))
            queued=queue.jobs()[-1]
            page.cue_controller.set_text('after','队列提交之后修改');ui.project_range_bar.apply((1000,2000))
            check('queue_range_frozen',queued.job.start_seconds==7.5 and queued.job.duration_seconds==2.5)
            check('queue_text_frozen',next(c['text'] for c in queued.job.export_project_data['cues'] if c['id']=='after')=='再次导出：本次人工修改')
            wait(lambda:queue.jobs()[-1].status in ('Completed','Failed'),90)
            check('advanced_queue_completed',queue.jobs()[-1].status=='Completed')
            report['queue']=queue.jobs()[-1].to_dict()
            queue.stop()
            ui.grab().save(str(out/'export-controls.png'))
            report['passed']=True
        except Exception:report['error']=traceback.format_exc()
        finally:
            if recorder and recorder.poll() is None:
                recorder.stdin.write(b'q\n');recorder.stdin.flush()
                until=time.monotonic()+8
                while recorder.poll() is None and time.monotonic()<until:pump(.03)
                report['capture_exit']=recorder.poll()
            if log:log.close()
            window.grab().save(str(out/'final-controls.png'))
            (out/('restart-runtime.json' if os.environ.get('TWOBYTEASR_FRAME_RESTART')=='1' else 'runtime.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            page.video.set_paused(True);page.undo_stack.setClean();window.close()
    QTimer.singleShot(600,run)
