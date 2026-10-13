"""Guarded, normal-entry export acceptance on the user's copied project."""
import json
import os
import time
import traceback
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from .studio_acceptance_audit import require


def start(window, out):
    def run():
        page = window.studio_page
        report = {'passed':False,'checks':{},'progress':[], 'preview':[], 'playback':[]}
        def pump(seconds):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                QApplication.processEvents()
                time.sleep(.004)
        def wait(predicate, timeout=90):
            deadline=time.monotonic()+timeout
            while not predicate() and time.monotonic()<deadline:
                pump(.03)
            require(predicate(), 'runtime wait timed out')
        def check(name, value):
            report['checks'][name]=bool(value)
            require(value, name)
        def subtitle_text():
            from .studio_mpv import MpvCommandError
            try:
                return page.video.controller.get_property('sub-text')
            except MpvCommandError as exc:
                # No selected/native subtitle at this time is a normal mpv
                # unavailable property, not an IPC/process failure.
                if 'property unavailable' not in str(exc):raise
                return ''
        try:
            from .build_identity import load_build_identity
            from .studio_edit_sequence import projected_cues
            report['build']=load_build_identity().to_dict()
            wait(lambda: page.project is not None and page._readiness.ready)
            page.video.set_paused(True)
            from PySide6.QtCore import QPoint
            primary=QApplication.primaryScreen()
            window.windowHandle().setScreen(primary)
            available=primary.availableGeometry()
            window.move(available.topLeft()+QPoint(120,100))
            window.resize(min(1440,available.width()-40),min(900,available.height()-60))
            pump(.5)
            window.resize(min(1440,available.width()-40),min(900,available.height()-60));pump(.15)
            if os.environ.get('TWOBYTEASR_CAPTION_REPAIR_AUDIT')=='1':
                from .caption_repair_audit import exercise
                exercise(page,out,pump,wait)
            if os.environ.get('TWOBYTEASR_EXPORT_RESTART')!='1':
                for seconds in (1.2,2.7,180.6,344.8):
                    page._seek(seconds)
                    pump(.8)
                    path=out/f'studio-{seconds:g}.png'
                    page.video.controller.screenshot_to_file(path)
                    report['playback'].append({'project_seconds':seconds,
                        'mpv_time':page.video.controller.get_property('time-pos'),
                        'subtitle':subtitle_text(),
                        'expected':[c.text for c in projected_cues(page.project) if c.start_ms<=seconds*1000<c.end_ms]})
                # Actual audible playback is recorded separately from human listening.
                page._set_volume(35)
                page._seek(2.2)
                pump(.4)
                page._toggle_playback()
                pump(3)
                page.video.set_paused(True)
                page._set_volume(0)
            QTest.mouseClick(page.studio_render_button, Qt.LeftButton)
            wait(lambda: page.export_workspace is not None)
            ui=page.export_workspace
            pump(.5)
            if os.environ.get('TWOBYTEASR_EXPORT_RESTART')=='1':
                check('restart_prefix',ui.filename_prefix.text()=='[NOTBAD]')
                check('restart_bitrate',ui.bitrate.value()==14000)
                check('restart_directory',Path(ui.directory.text())==out/'exports')
                check('source_resolution_policy',ui.resolution.currentData()==(0,0))
                check('source_fps_policy',ui.fps.currentData()==0.)
                check('single_use_name_not_persisted',ui.filename.text()!='验收成片')
                window.grab().save(str(out/'restart-settings.png'))
                report['passed']=True
                return
            ui.filename.setText('验收成片')
            ui.filename_prefix.setText('[NOTBAD]')
            ui.filename_suffix.clear()
            ui.directory.setText(str(out/'exports'))
            ui.preset.setCurrentIndex(ui.preset.findData('custom'))
            ui.quality.setCurrentIndex(ui.quality.findData('custom'))
            # Explicit software choice keeps the user's old quality settings.
            if ui.encoder.findData('libx264')<0:
                ui.encoder.addItem('Software x264','libx264')
            ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'))
            ui.rate_control.setCurrentIndex(ui.rate_control.findData('crf'))
            ui.quality_value.setValue(20)
            ui.bitrate.setValue(14000)
            ui.encoder_preset.setCurrentIndex(ui.encoder_preset.findData('balanced'))
            ui.audio.setCurrentIndex(ui.audio.findData('aac'))
            length=float(os.environ.get('TWOBYTEASR_EXPORT_DURATION','12'))
            if length>0:
                from .project_range import set_range
                set_range(page.project,0,round(length*1000),page.undo_stack)
                ui._update_range()
                ui.export_range.setCurrentIndex(ui.export_range.findData('in_out'))
            ui.grab().save(str(out/'settings.png'))
            last=[-1]
            stages_seen=set()
            def progress(value,payload):
                shown=ui.progress.value()
                check('progress_monotonic',shown>=last[0])
                last[0]=shown
                check('bar_badge_agree',ui.render_percent.text()==f'{shown}%')
                check('determinate_bar',ui.progress.maximum()==100)
                report['progress'].append({'total':shown,'stage':payload.get('stage'),'stage_percent':payload.get('percent')})
                stage=payload.get('stage')
                if stage and stage not in stages_seen:
                    stages_seen.add(stage)
                    QTimer.singleShot(0,lambda s=stage:ui.grab().save(str(out/f'stage-{s}.png')))
            ui.progress_updated.connect(progress)
            trace=ui._export_trace
            def traced(name,*args,**kwargs):
                trace(name,*args,**kwargs)
                if name=='processed_preview':
                    report['preview'].append(args[0])
                    if len(report['preview']) in (1,3,8):
                        ui.grab().save(str(out/f'running-{len(report["preview"])}.png'))
                        view=ui.render_preview
                        rect=view.frame_rect()
                        size=view.contentsRect()
                        pixmap=view.pixmap()
                        check('preview_aspect_fit',abs(rect.width()/rect.height()-pixmap.width()/pixmap.height())<.01)
                        check('preview_fills_viewport',rect.width()>=size.width()-2 or rect.height()>=size.height()-2)
                        check('details_expanded',ui.running_details_button.isChecked() and ui.running_log.isVisible())
                        report.setdefault('layout',[]).append(dict(window=[window.width(),window.height()],
                            dpr=window.devicePixelRatioF(),viewport=[size.width(),size.height()],
                            frame=[rect.x(),rect.y(),rect.width(),rect.height()],split=ui.render_body.sizes(),
                            header_fraction=ui.render_body.y()/max(1,ui.render_body.parentWidget().height())))
                        if len(report['preview'])==1:
                            QTimer.singleShot(0,lambda:window.resize(min(1120,available.width()-40),min(760,available.height()-60)))
                        elif len(report['preview'])==3:
                            QTimer.singleShot(0,lambda:window.resize(min(1600,available.width()-40),min(960,available.height()-60)))
            ui._export_trace=traced
            clicked=time.perf_counter()
            ui.render_succeeded.connect(lambda _path:report.update(click_to_usable_seconds=time.perf_counter()-clicked))
            QTest.mouseClick(ui.export_button, Qt.LeftButton)
            wait(lambda:ui._last_job is not None)
            wait(lambda:not ui._running,900)
            pump(.3)
            check('success_page',ui.pages.currentWidget()==ui.success_page)
            check('own_actual_output',Path(ui._last_job.output_path).is_file())
            check('processed_preview_changed',len({p['project_ms'] for p in report['preview']})>2)
            check('completion_cover',not ui.success_page.preview.image.isNull())
            check('final_100',ui.progress.value()==100)
            ui.grab().save(str(out/'success.png'))
            report['receipt']=ui._last_job.completion_metadata
            report['export_ass']=ui._last_job.ass_path
            # An independent native player consumes the output just produced;
            # editor playback clocks cannot redirect it to original media.
            from .studio_mpv import MpvController
            screen=QWidget(); screen.setWindowTitle('成片同步验证')
            screen.resize(960,540); screen.setAttribute(Qt.WA_NativeWindow); screen.show()
            player=MpvController()
            try:
                player.start(int(screen.winId()))
                player.load(ui._last_job.output_path)
                pump(.7)
                player.set_audio_enabled(True)
                player.set_volume(35)
                player._send(['set_property','mute',False])
                report['output_playback']=[]
                from .studio_helpers import probe_media_identity
                output_metadata=probe_media_identity(ui._last_job.output_path)
                has_audio=bool(output_metadata.get('has_audio'))
                output_seconds=float(output_metadata.get('duration_ms',0))/1000
                report['output_has_audio']=has_audio
                for at in ((1.2,179.2,343.4) if length<=0 else (1.2,)):
                    at=min(at,max(0.,output_seconds-1.))
                    player.seek(at)
                    player.set_paused(False)
                    pump(min(3.,max(.1,output_seconds-at-.1)))
                    player.set_paused(True)
                    player.screenshot_to_file(out/f'output-playback-{at}.png')
                    properties=['path','time-pos','volume','mute']
                    if has_audio:properties.extend(['audio-pts','avsync','audio-out-params'])
                    report['output_playback'].append({key:player.get_property(key) for key in properties})
                if has_audio:check('output_audio_device',all(p['audio-out-params'] and p['mute'] is False for p in report['output_playback']))
                else:report['output_audio_check']='not_applicable_no_audio_stream'
            finally:
                player.close(); screen.close()
            report['human_listening']='NOT VERIFIED'
            if os.environ.get('TWOBYTEASR_CAPTION_REPAIR_AUDIT')=='1':
                QTest.mouseClick(ui.success_page.back, Qt.LeftButton) if hasattr(ui.success_page,'back') else ui._back()
                pump(.5)
                first=projected_cues(page.project)[0]
                page._seek((first.start_ms+first.end_ms)/2000);pump(.8)
                page.video.controller.screenshot_to_file(out/'caption-after-export.png')
                check('returned_to_editor',page.video.isVisible())
                wait(lambda:bool(subtitle_text()),10)
                check('subtitle_after_export',bool(subtitle_text()))
            report['passed']=True
        except Exception:
            report['error']=traceback.format_exc()
        finally:
            (out/('restart-runtime.json' if os.environ.get('TWOBYTEASR_EXPORT_RESTART')=='1' else 'runtime.json')).write_text(
                json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            page.video.set_paused(True)
            page.undo_stack.setClean()
            window.close()
    QTimer.singleShot(1500,run)
