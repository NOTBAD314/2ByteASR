"""Opt-in runtime UI gates for edited recognition, completion and timeline follow."""
import json
import os
from pathlib import Path
import time
import traceback

from PySide6.QtCore import QTimer, Qt, QPoint, QMimeData, QUrl, QPointF
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def start(window, out):
    def run():
        report = {"checks":{},"performance":[],"passed":False}
        page = window.studio_page
        def pump(seconds):
            deadline = time.perf_counter()+seconds
            while time.perf_counter()<deadline:
                QApplication.processEvents()
                time.sleep(.002)
        def wait(predicate, seconds=60):
            deadline=time.perf_counter()+seconds
            while not predicate() and time.perf_counter()<deadline:
                pump(.05)
            assert predicate()
        def check(name, condition):
            report["checks"][name]=bool(condition)
            assert condition,name
        try:
            from .build_identity import load_build_identity
            from .studio_project import load_project
            from .studio_edit_sequence import timeline_duration_ms, projected_cues
            from .service import QueueResult,MediaResult
            report["build"]=load_build_identity().to_dict()
            wait(lambda:page.project is not None and page._readiness.ready)
            page._set_volume(0)
            page.video.set_paused(True)
            window.resize(1280,860)
            pump(.5)
            report["dpr"]=window.devicePixelRatioF()
            expected_duration=page.project.generation_metadata.get('timeline_recognition',{}).get('duration_ms',180000)
            check("edited_duration",timeline_duration_ms(page.project)==expected_duration)
            timeline=page.timeline
            samples=[]
            paints=[]
            observations=[]
            in_follow=[False]
            observer=QTimer(window);observer.setInterval(8)
            def sample_video():
                info=page.video.controller.observed_property('video-frame-info',{}) or {}
                marker=info.get('pts',info.get('estimated-smpte-timecode'))
                if marker is not None and (not observations or observations[-1][1]!=marker):
                    observations.append((time.perf_counter(),marker))
            observer.timeout.connect(sample_video)
            transport=[]
            for method in ('seek','switch_media_async','switch_media_at_async','set_playback_rate'):
                original=getattr(page.video,method,None)
                if original:
                    def traced(*args,_method=method,_original=original,**kwargs):
                        transport.append((time.perf_counter(),_method,in_follow[0]))
                        return _original(*args,**kwargs)
                    setattr(page.video,method,traced)
            original_follow=timeline.follow_playing_playhead
            original_paint=timeline._paint_timeline
            def follow(ms):
                before=time.perf_counter()
                in_follow[0]=True
                try:value=original_follow(ms)
                finally:in_follow[0]=False
                samples.append((before,ms,timeline.visible_start_ms,(time.perf_counter()-before)*1000))
                return value
            def paint(event):
                before=time.perf_counter()
                original_paint(event)
                paints.append((before,(time.perf_counter()-before)*1000))
            timeline.follow_playing_playhead=follow
            timeline._paint_timeline=paint
            for phase,(rate,zoom) in enumerate(((1.,10000),(1.,10000),(2.,30000),(4.,60000))):
                page.video.set_paused(True)
                page.speed_box.setCurrentIndex(page.speed_box.findData(rate))
                page._seek(35.)
                pump(1.)
                wait(lambda:not page.video._playback_clock.exact_seek_pending,10)
                timeline.set_visible_window(20000,zoom)
                timeline._follow_suspended_until=0
                page.follow_playhead_toggle.setChecked(True)
                samples.clear();paints.clear();observations.clear();transport.clear()
                observer.start()
                import psutil
                process=psutil.Process()
                cpu_before=process.cpu_times();wall_before=time.perf_counter()
                page.video.set_paused(False)
                pump(5.)
                page.video.set_paused(True)
                observer.stop()
                cpu_after=process.cpu_times()
                cpu_percent=100*((cpu_after.user+cpu_after.system)-(cpu_before.user+cpu_before.system))/(time.perf_counter()-wall_before)
                def stats(values):
                    values=sorted(values)
                    return {"count":len(values),"p50":values[len(values)//2] if values else 0,
                            "p95":values[min(len(values)-1,int(len(values)*.95))] if values else 0,
                            "max":max(values,default=0)}
                report["performance"].append({"rate":rate,"zoom_ms":zoom,
                    "phase":"cold_start" if phase==0 else "steady",
                    "main_process_cpu_percent_one_core":cpu_percent,
                    "follow_intervals_ms":stats([(b[0]-a[0])*1000 for a,b in zip(samples,samples[1:])]),
                    "paint_ms":stats([p[1] for p in paints]),
                    "paint_intervals_ms":stats([(b[0]-a[0])*1000 for a,b in zip(paints,paints[1:])]),
                    "video_observed_frame_intervals_ms":stats([(b[0]-a[0])*1000 for a,b in zip(observations,observations[1:])]),
                    "video_measurement":"Distinct mpv video-frame-info observations; excludes display scanout latency",
                    "transport_during_follow":list(transport),
                    "viewport_step_ms":stats([b[2]-a[2] for a,b in zip(samples,samples[1:])]),
                    "samples":list(samples)})
                check(f"clock_advances_{rate}",len(samples)>10 and samples[-1][1]>samples[0][1]+2000)
                check(f"follow_does_not_seek_{rate}",not any(row[2] for row in transport))
            page.video.controller.screenshot_to_file(out/'video-native.png',mode='window')
            timeline.grab().save(str(out/"timeline.png"))
            from .studio_edit_sequence import sequence_of
            sequence=sequence_of(page.project)
            contiguous=next(((a,b) for a,b in zip(sequence.segments,sequence.segments[1:])
                             if a.timeline_out_ms==b.timeline_in_ms and a.source_out_ms!=b.source_in_ms),None)
            if contiguous:
                left,right=contiguous
                page.speed_box.setCurrentIndex(page.speed_box.findData(1.))
                page._seek((left.timeline_out_ms-1000)/1000);pump(.5)
                wait(lambda:not page.video._playback_clock.exact_seek_pending,10)
                page.video.set_paused(False);pump(3.);page.video.set_paused(True)
                report['cut_crossing']={'timeline_ms':timeline.playhead_ms,'boundary_ms':right.timeline_in_ms,
                    'active_clip':page._active_video_preview_clip_id}
                check('cut_crossing_keeps_edit_order',right.timeline_in_ms<timeline.playhead_ms<right.timeline_in_ms+5000)
            repeated=next((b for i,a in enumerate(sequence.segments) for b in sequence.segments[i+1:]
                           if a.source_path==b.source_path and a.source_in_ms==b.source_in_ms),None)
            if repeated:
                target=repeated.timeline_in_ms+5000
                page._seek(target/1000);pump(.5)
                wait(lambda:not page.video._playback_clock.exact_seek_pending,10)
                page.video.set_paused(False);pump(2.);page.video.set_paused(True)
                report['repeat']={'target_ms':target,'actual_ms':timeline.playhead_ms,'clip':page._active_video_preview_clip_id}
                check('repeat_keeps_instance',target<timeline.playhead_ms<target+4000)
                page.video.controller.screenshot_to_file(out/'repeat-native.png',mode='window')
            changed_rate=next((s for s in sequence.segments if s.source_duration_ms!=s.duration_ms),None)
            if changed_rate:
                target=changed_rate.timeline_in_ms+5000
                page._seek(target/1000);pump(.7)
                wait(lambda:not page.video._playback_clock.exact_seek_pending,10)
                page.video.set_paused(False);pump(.5)
                start_ms=timeline.playhead_ms;started=time.perf_counter()
                pump(2.);elapsed=time.perf_counter()-started;page.video.set_paused(True)
                measured_rate=(timeline.playhead_ms-start_ms)/1000/elapsed
                report['clip_rate']={'timeline_rate':measured_rate,'ui_rate':page.video._playback_rate,
                    'decoder_rate':page.video.controller.observed_property('speed',None)}
                check('clip_rate_matches_timeline',.85<measured_rate<1.15)
            gap=next(((a,b) for a,b in zip(sequence.segments,sequence.segments[1:])
                      if b.timeline_in_ms-a.timeline_out_ms>=2000),None)
            if gap:
                left,right=gap
                target=right.timeline_in_ms-1500
                page._seek(target/1000);pump(.3)
                gap_started=time.perf_counter()
                page.video.set_paused(False);pump(3.5)
                report['gap_resume_state']={'paused':page.video._paused,'buffered_play_pending':page.video._buffered_play_pending,
                    'startup_state':page.video._startup_state,'timeline_ms':timeline.playhead_ms}
                wait(lambda:timeline.playhead_ms>right.timeline_in_ms+500,10)
                page.video.set_paused(True)
                report['gap_crossing']={'target_ms':target,'actual_ms':timeline.playhead_ms,'end_ms':right.timeline_in_ms}
                report['gap_crossing']['elapsed_seconds']=time.perf_counter()-gap_started
                check('gap_restores_next_clip',right.timeline_in_ms<timeline.playhead_ms<right.timeline_in_ms+4000)
            # Real drop events; dialog entry is a guard that must never execute.
            timeline.set_visible_window(20000,60000)
            page._choose_media_drop_target=lambda: (_ for _ in ()).throw(AssertionError("drop chooser opened"))
            count=page.undo_stack.count()
            before=len(page.project.media_pool)
            mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(page.project.media.path)]*2)
            point=page.timeline.mapTo(page,QPoint(300,100))
            QApplication.sendEvent(page,QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
            QApplication.sendEvent(page,QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
            wait(lambda:page.undo_stack.count()>count)
            check("drop_single_undo",page.undo_stack.count()==count+1)
            page.undo_stack.undo();pump(.3)
            check("drop_undo_duration",timeline_duration_ms(page.project)==expected_duration)
            page.undo_stack.redo();pump(.2)
            check("drop_redo",sum(len(t.clips) for t in page.project.video_tracks)>=5)
            page.speed_box.setCurrentIndex(page.speed_box.findData(1.))
            overlay=next(t.clips[0] for t in page.project.video_tracks[1:] if t.clips)
            page._seek((overlay.timeline_in_ms+500)/1000);pump(.7)
            wait(lambda:not page.video._playback_clock.exact_seek_pending,10)
            paints.clear();samples.clear()
            page.video.set_paused(False);pump(3.);page.video.set_paused(True)
            report['multitrack']={'layers':len(page._multitrack_preview_layers(timeline.playhead_ms)),
                'paint_intervals_ms':stats([(b[0]-a[0])*1000 for a,b in zip(paints,paints[1:])]),
                'paint_ms':stats([p[1] for p in paints])}
            check('multitrack_actually_played',len(samples)>10 and samples[-1][1]>samples[0][1]+1000)
            check('multiple_visible_layers',report['multitrack']['layers']>=2)
            page.undo_stack.undo();pump(.2)
            project_path=str(out/"fixture.2byteproj")
            window._studio_recognition_context=None
            window._show_task_notification=lambda *a,**k:None
            queue_path=out/'queue-result.json'
            if queue_path.exists():
                saved=json.loads(queue_path.read_text(encoding='utf-8'))
                items=[MediaResult(**{**row,'project_path':project_path}) for row in saved['results']]
                queued=QueueResult(tuple(items),saved['elapsed_seconds'],saved.get('log_path',''))
                report['completion_input']='Actual pipeline QueueResult; project copied into isolated audit'
            else:
                queued=QueueResult((MediaResult(page.project.media.path,"success",project_path=project_path,elapsed_seconds=226.8),),226.8)
                report['completion_input']='UI fixture with synthetic duration/status'
            window._handle_result(queued)
            pump(.4)
            from .i18n import apply_ui_language
            for language in ("zh","en","ja"):
                apply_ui_language(window,language)
                window._ui_language=language
                window.language_combo.blockSignals(True)
                window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                window.language_combo.blockSignals(False)
                pump(.2)
                window.grab().save(str(out/f"completion-{language}.png"))
                check(f"icon_fits_{language}",window.result_icon.pixmap().width()/window.result_icon.pixmap().devicePixelRatio()<=window.result_icon.contentsRect().width())
                check(f"export_visible_{language}",window.export_result_button.isVisible() and window.export_result_button.isEnabled())
            from .completion_export import CompletionExportDialog,selected_result
            frozen=window._completion_tasks[0][1]
            from PySide6.QtWidgets import QFileDialog,QPushButton
            from .studio_subtitle_export import verify_subtitle_artifact
            import copy
            export_checks={}
            choose=QFileDialog.getExistingDirectory
            QFileDialog.getExistingDirectory=lambda *a,**k:str(out/'explicit-export')
            original_project=page.project
            page.project=copy.deepcopy(page.project)
            page.project.cues=[]  # Another open Studio object must not change task export.
            def operate_export():
                try:
                    dialog=QApplication.activeModalWidget()
                    assert isinstance(dialog,CompletionExportDialog)
                    export_checks['all']=dialog.speakers.count()==len({c.speaker_id for c in projected_cues(frozen)})
                    for i in range(dialog.speakers.count()):
                        dialog.speakers.item(i).setCheckState(Qt.Checked if i<2 else Qt.Unchecked)
                    selected={dialog.speakers.item(i).data(Qt.UserRole) for i in range(min(2,dialog.speakers.count()))}
                    for box in dialog.formats.values():box.setChecked(True)
                    dialog.mode.setCurrentIndex(dialog.mode.findData('both'))
                    dialog.grab().save(str(out/'export-dialog.png'))
                    QTest.mouseClick(dialog.findChild(QPushButton,'primary'),Qt.LeftButton)
                    assert dialog.artifacts,dialog.status.text()
                    subset=selected_result(frozen,selected)
                    expected=copy.copy(subset);expected.cues=projected_cues(subset)
                    export_checks['files']=[{'path':str(a.path),'count':a.cue_count} for a in dialog.artifacts]
                    export_checks['verified']=all(verify_subtitle_artifact(a,expected).timestamps_valid for a in dialog.artifacts if not a.speaker_id)
                    export_checks['binding']=bool(expected.cues) and not page.project.cues
                except Exception:
                    export_checks['error']=traceback.format_exc()
                    modal=QApplication.activeModalWidget()
                    if modal:modal.reject()
            try:
                QTimer.singleShot(150,operate_export)
                QTest.mouseClick(window.export_result_button,Qt.LeftButton)
            finally:
                QFileDialog.getExistingDirectory=choose
                page.project=original_project
            report['explicit_export']=export_checks
            check('direct_export_and_binding',export_checks.get('all') and export_checks.get('verified') and export_checks.get('binding'))
            report["passed"]=True
        except Exception:
            report["error"]=traceback.format_exc()
        finally:
            (out/"runtime.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            page.video.set_paused(True)
            page.undo_stack.setClean()
            window.close()
    QTimer.singleShot(2000,run)
