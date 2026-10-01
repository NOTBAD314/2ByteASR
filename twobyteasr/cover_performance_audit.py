"""Bounded before/after cover comparison on an existing real long project copy."""
import json
from pathlib import Path
import time
import traceback

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def start(window, out):
    def run():
        import psutil
        from .build_identity import load_build_identity
        from .studio_project import project_content_fingerprint
        from .long_project_acceptance_audit import mpv_timecode_ms
        from .studio_acceptance_audit import require
        page=window.studio_page;process=psutil.Process();editor=None
        began=time.perf_counter()
        report=dict(passed=False, checks={}, resources=[], comparison={}, captures=[], build=load_build_identity().to_dict(),
                    cache_scope='Fresh application process; OS file cache not cleared. Before/after in the same process, not an old-version benchmark.')
        def pump(seconds):
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                QApplication.processEvents();time.sleep(.004)
        def wait(predicate, timeout=120):
            until=time.monotonic()+timeout
            while not predicate() and time.monotonic()<until:pump(.02)
            require(predicate(), 'Long-project acceptance timed out')
        def check(key, value):
            report['checks'][key]=bool(value);require(value,key)
        def resource(label):
            report['resources'].append(dict(label=label, elapsed=time.perf_counter()-began,
                rss=process.memory_info().rss,handles=process.num_handles(),threads=process.num_threads()))
        def compare(label):
            rows=[];report['comparison'][label]=rows
            for target in (60., 3600., 10800., 3600.):
                page.video.set_paused(True)
                started=time.perf_counter();page._seek(target);dispatch=(time.perf_counter()-started)*1000
                generation=page.video._playback_clock.generation
                def acknowledged():
                    traces=page.video.seek_latency_traces();trace=traces[-1] if traces else {}
                    expected=trace.get('decoder_target_seconds',target)*1000
                    info=page.video.controller.observed_property('video-frame-info',{}) or {}
                    pts=float(info.get('pts',-100))*1000
                    if pts<0 and info.get('estimated-smpte-timecode'):
                        pts=mpv_timecode_ms(info['estimated-smpte-timecode'])
                    accepted=page.video.controller.applied_seek_state()
                    return accepted.get('generation')==generation and abs(pts-expected)<=50
                wait(acknowledged,30)
                ack=(time.perf_counter()-started)*1000
                # Wait for observed progress and record startup separately from
                # the seek ACK; a fixed 1.2s sleep concealed slow cold startup.
                origin=page.video.visual_position();play_started=time.perf_counter()
                page.video.set_paused(False)
                while page.video.visual_position()<=origin+.1 and time.perf_counter()-play_started<10:pump(.02)
                progressed=page.video.visual_position()>origin+.1
                current=page.video.visual_position();play_ms=(time.perf_counter()-play_started)*1000
                pump(.4);page.video.set_paused(True);pump(.1)
                rows.append(dict(target_seconds=target, gui_dispatch_ms=dispatch, decoded_ack_ms=ack, playback_start_ms=play_ms,
                    playback_origin=origin,playback_observed=current,playback_progress=progressed,
                    buffered_pending=getattr(page.video,'_buffered_play_pending',None),
                    audio_ready=page.audio_engine.ready_for_playback()))
                # A pre-existing long playback problem must not hide the cover
                # measurements. Preserve it explicitly as an unresolved finding.
                if not progressed:
                    report.setdefault('unresolved_playback',[]).append(dict(phase=label, target_seconds=target,
                        message='No playback progress within 10 seconds after a confirmed decoded seek.'))
            report['comparison'][label]=rows;resource(label)
        try:
            wait(lambda:page.project is not None and page._readiness.ready)
            report['ready_seconds']=time.perf_counter()-began
            page._set_volume(0);page.video.set_paused(True);pump(.3)
            report['project']=dict(duration_ms=page.project.media.duration_ms,cues=len(page.project.cues),source=page.project.media.path)
            check('real_long_project',len(page.project.cues)>1000 and page.project.media.duration_ms>10000000)
            original=page.project;fingerprint=project_content_fingerprint(original);undo=page.undo_stack.index()
            resource('ready');compare('before_cover')
            page.cover_controller.settings.setValue('cover/subtitles',False)
            for index,target in enumerate((3600.25,10800.25,3600.25,3600.25)):
                page._seek(target)
                QTest.mouseClick(page.make_cover_button,Qt.LeftButton)
                wait(lambda:page.cover_controller.editor is not None and not page.cover_controller.busy,120)
                editor=page.cover_controller.editor;report['captures'].append(page.cover_controller.last_receipt)
                editor.add_text();editor.text_edit.setPlainText('四小时真实工程 · 本地封面');pump(.1)
                editor.flush_text()
                for _ in range(5):editor.session.duplicate_selected()
                editor.view.setFocus();QTest.keyClick(editor.view,Qt.Key_A,Qt.ControlModifier)
                QTest.keyClick(editor.view,Qt.Key_Right,Qt.ShiftModifier)
                editor.save_document(out/f'long-{index}.2bytecover');wait(lambda:not editor.busy)
                editor.export_document(out/f'long-{index}.png');wait(lambda:not editor.busy)
                check('capture_'+str(index),abs(editor.session.document.source['milliseconds']-target*1000)<1)
                editor.close();pump(.2);wait(lambda:page.cover_controller.editor is None);editor=None
                resource('cover_closed_'+str(index))
            compare('after_cover')
            before=report['comparison']['before_cover'];after=report['comparison']['after_cover']
            check('no_new_long_playback_failure',all(not b['playback_progress'] or a['playback_progress'] for b,a in zip(before,after)))
            check('studio_project_history_unchanged',page.project is original and page.undo_stack.index()==undo and project_content_fingerprint(original)==fingerprint)
            # Idle after releasing cover documents: allocator/backend caches can
            # remain; record the measured plateau without promising zero leaks.
            pump(5);resource('settled')
            window.grab().save(str(out/'long-studio-return.png'))
            report['passed']=True
        except Exception:
            report['error']=traceback.format_exc()
        finally:
            if editor:
                editor.session.saved_signature=editor.session.document.signature();editor.close()
            report['elapsed_seconds']=time.perf_counter()-began
            (out/'cover-runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            page.video.set_paused(True);page.undo_stack.setClean();window.close()
    QTimer.singleShot(600,run)
