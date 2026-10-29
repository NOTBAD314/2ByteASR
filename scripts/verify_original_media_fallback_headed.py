"""Owned project referencing an approved original, without copying long media.

Default: read-only probes and cold/warm deleted-cache fallback, plus a tiny
project in a fresh tmp folder. GUI playback and the two-second software render
are separate explicit flags; the coordinator runs them serially.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def identity(path):
    info=Path(path).lstat()
    return [info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--approval',type=Path,required=True)
    parser.add_argument('--approval-sha256',required=True)
    parser.add_argument('--source-index',type=int,default=0)
    parser.add_argument('--start-seconds',type=float,default=90)
    parser.add_argument('--run-ui',action='store_true')
    parser.add_argument('--encode-sample',action='store_true')
    parser.add_argument('--worker',action='store_true')
    args=parser.parse_args();output=args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output==ROOT/'tmp':raise ValueError('Fresh repository tmp directory required')
    raw=args.approval.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.approval_sha256:raise ValueError('Reviewed manifest identity changed')
    approved=json.loads(raw)
    media=[i for i in approved['exact_items'] if i['category']=='media']
    sources=sorted(set(i['source'] for i in media))
    if not 0<=args.source_index<len(sources):raise ValueError('Unknown approved original source index')
    source=Path(sources[args.source_index])
    deleted=[i['path'] for i in media if i['source']==str(source)]
    if not source.is_file() or any(os.path.lexists(path) for path in deleted):
        raise ValueError('Original is missing or reviewed intermediate cache has reappeared; do not delete anything')
    if args.start_seconds<0:raise ValueError('Sample start must be nonnegative')
    if not args.worker:
        if output.exists():raise ValueError('Fresh output required')
        output.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output),PYTHONUTF8='1')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.storage.storage_service import safe_path
    if not safe_path(source,(source.parent,)):raise ValueError('Original path contains links or cannot be verified')

    if args.worker:return run_ui(args,source,output)
    from twobyteasr.playback.audio_engine import studio_ffmpeg_path
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.media.indexed_media import IndexedMediaCache
    from twobyteasr.projects.studio_project import StudioMedia,StudioCue,StudioSpeaker,SubtitleProject,save_project
    before=identity(source);ffmpeg=Path(studio_ffmpeg_path());probe=ffmpeg.with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe')
    command=[str(probe),'-v','error','-show_entries',
        'format=duration,start_time,size:stream=codec_type,codec_name,width,height,avg_frame_rate',
        '-of','json',str(source)]
    inspected=run_hidden_subprocess(command,capture_output=True,text=True,encoding='utf8',errors='replace',
        purpose='read approved original FLV metadata after cache cleanup',timeout=30)
    if inspected.returncode:raise RuntimeError(inspected.stderr)
    metadata=json.loads(inspected.stdout)
    video=next(s for s in metadata['streams'] if s.get('codec_type')=='video')
    duration=float(metadata['format']['duration'])
    if duration<args.start_seconds+2:raise ValueError('Original does not cover requested two-second sample')
    cold=IndexedMediaCache(output/'private-seek-cache')
    cold._sync_scan_done.add(str(source))  # Prevent full-source timestamp generation in this bounded audit.
    cold_path=cold.resolve(str(source));cold_playback=cold.playback_source(str(source))
    warm=IndexedMediaCache(output/'private-seek-cache')
    missing=next(path for path in deleted if Path(path).suffix in {'.mp4','.mkv'})
    warm._ready[str(source)]=missing;warm._ready_identities[str(source)]=(before[2],before[3])
    warm_path=warm.resolve(str(source));warm._sync_scan_done.add(str(source))
    warm_playback=warm.playback_source(str(source))
    if cold_path!=str(source) or warm_path!=str(source) or cold_playback!=(None,'original') or warm_playback!=(None,'original'):
        raise AssertionError('Actual indexed-media reader did not select original source')
    if cold._thread or warm._thread or warm._requested or str(source) in warm._ready:
        raise AssertionError('Fallback unexpectedly scheduled compatibility generation')
    project=SubtitleProject(media=StudioMedia(path=str(source),duration_ms=round(duration*1000),
        width=video.get('width',0),height=video.get('height',0)),
        cues=[StudioCue('original-audit',round(args.start_seconds*1000),round((args.start_seconds+2)*1000),'原素材缓存清理后的本地验收')],
        speakers=[StudioSpeaker('S00')],studio_state=dict(video_thumbnails_visible=False))
    seed=output/'projects'/'seed'/'original.2byteproj';seed.parent.mkdir(parents=True)
    save_project(project,seed)
    if identity(source)!=before:raise ValueError('Original identity changed during preparation')
    prepared=dict(readonly_original=True,source=str(source),source_identity=before,probe=metadata,
        probe_command=command,deleted_cache_paths=deleted,approval_sha256=args.approval_sha256,
        owned_project=str(seed),sample_start_seconds=args.start_seconds,sample_duration_seconds=2,
        fallback=dict(cold_resolve=cold_path,cold_playback=cold_playback,warm_resolve=warm_path,
            warm_playback=warm_playback,warm_stale_ready_cleared=str(source) not in warm._ready),
        scope='Metadata/reader selection only until explicit GUI or software render flags; no full-source waveform/timestamp/proxy generation')
    (output/'preparation.json').write_text(json.dumps(prepared,ensure_ascii=False,indent=2),'utf8')
    if args.encode_sample:
        render_sample(project,ffmpeg,probe,args.start_seconds,output)
        if identity(source)!=before:raise ValueError('Original identity changed during sample export')
    if args.run_ui:
        env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),
            TWOBYTEASR_ACCEPTANCE_SCENARIO='storage-media',TWOBYTEASR_STARTUP_PROJECT=str(seed),
            TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
            TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'),QT_QPA_PLATFORM='windows',
            HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_RAISE','TWOBYTEASR_STARTUP_LEAVE_STUDIO','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):env.pop(key,None)
        for key in ('QT_SCALE_FACTOR','QT_FONT_DPI','QT_ENABLE_HIGHDPI_SCALING','QT_SCALE_FACTOR_ROUNDING_POLICY'):env.pop(key,None)
        argv=[sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--output',str(output),
            '--approval',str(args.approval.resolve()),'--approval-sha256',args.approval_sha256,
            '--source-index',str(args.source_index),'--start-seconds',str(args.start_seconds)]
        from isolated_windows_desktop import run_on_desktop
        code=run_on_desktop(argv,cwd=ROOT,env=env,output=output/'process',timeout=180)
        receipt=output/'result.json';result=json.loads(receipt.read_text('utf8')) if receipt.exists() else dict(passed=False,error='Missing normal UI receipt')
        result.update(process_exit=code,source_identity_after=identity(source))
        result['passed']=bool(result.get('passed') and code==0 and result.get('provider_calls')==0 and identity(source)==before)
        receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps(dict(passed=result['passed'],output=str(output),checks=len(result.get('checks',[]))),ensure_ascii=False))
        return 0 if result['passed'] else 1
    print(json.dumps(dict(prepared=True,encoded=args.encode_sample,source=str(source),output=str(output)),ensure_ascii=False))
    return 0


def render_sample(project,ffmpeg,probe,start,output):
    from twobyteasr.rendering.ass_compiler import compile_ass
    from twobyteasr.exports.studio_render import RenderSettings,RenderJob,run_render_job
    from twobyteasr.system.processes import run_hidden_subprocess
    ass=output/'sample.ass';ass.write_text(compile_ass(project),'utf-8-sig')
    target=output/'original-two-second.mp4';traces=[];started=time.monotonic()
    settings=RenderSettings(encoder='libx264',audio_codec='aac',preset='ultrafast',width=640,height=360,fps=25)
    job=RenderJob(project.media.path,str(ass),str(target),settings,start_seconds=start,duration_seconds=2)
    run_render_job(ffmpeg,job,cancelled=lambda:time.monotonic()-started>90,
        trace=lambda event,payload:traces.append(dict(event=event,payload=payload)))
    result=run_hidden_subprocess([str(probe),'-v','error','-show_entries',
        'format=duration,size:stream=codec_type,codec_name,width,height','-of','json',str(target)],
        capture_output=True,text=True,encoding='utf8',errors='replace',purpose='probe owned two-second source export',timeout=15)
    if result.returncode:raise RuntimeError(result.stderr)
    info=json.loads(result.stdout)
    if not 1.8<=float(info['format']['duration'])<=2.3:raise AssertionError('Export was not bounded to two seconds')
    (output/'software-export.json').write_text(json.dumps(dict(passed=True,route='product run_render_job backend; GUI export controls are validated separately',
        source=project.media.path,output=str(target),start_seconds=start,duration_seconds=2,
        settings=asdict(settings),probe=info,traces=traces,sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False,indent=2),'utf8')


def run_ui(args,source,output):
    from twobyteasr.acceptance import media_storage_audit
    from twobyteasr.media.indexed_media import GLOBAL_INDEXED_MEDIA
    GLOBAL_INDEXED_MEDIA._sync_scan_done.update((str(source),str(source.resolve())))
    GLOBAL_INDEXED_MEDIA.sync_map=lambda path:None
    def generation_denied(*args,**kwargs):
        raise RuntimeError('Full compatibility/proxy generation is outside this bounded original-media audit')
    GLOBAL_INDEXED_MEDIA._prepare=generation_denied
    GLOBAL_INDEXED_MEDIA._build_continuous_proxy=generation_denied
    def start(window,ignored_output):
        from PySide6.QtCore import QObject,QTimer,Qt
        from PySide6.QtWidgets import QApplication,QMessageBox,QFileDialog
        from PySide6.QtTest import QTest
        from twobyteasr.acceptance.blank_project_audit import _capture
        from twobyteasr.acceptance import blank_project_audit
        class Audit(QObject):
            def __init__(self):
                super().__init__(window);self.page=window.studio_page;self.active=False
                # The audit measures direct playback, not full-source auxiliary generation.
                self.page._generate_project_waveforms=lambda:None
                self.result=dict(passed=False,checks=[],source=str(source),provider_calls=0,
                    scope='Normal source quick_start/owned project/mpv playback and seek; full-source waveform/timestamp regeneration deliberately held')
                self.steps=self.run();self.waiting=0;self.deadline=time.monotonic()+60
                self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(25)
            def check(self,name,value,detail=None):
                self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
                if not value:raise AssertionError(name+': '+str(detail))
            def tick(self):
                if self.active:return
                self.active=True
                try:
                    modal=QApplication.activeModalWidget()
                    if isinstance(modal,QMessageBox):raise RuntimeError(modal.text())
                    if callable(self.waiting):
                        if not self.waiting():
                            if time.monotonic()>self.deadline:raise TimeoutError('Original-media UI condition')
                            return
                    elif time.monotonic()<self.waiting:return
                    step=next(self.steps);self.waiting=step if callable(step) else time.monotonic()+float(step);self.deadline=time.monotonic()+60
                except StopIteration:self.result['passed']=True;self.finish()
                except Exception:self.result['error']=traceback.format_exc();self.finish()
                finally:self.active=False
            def timecode(self,seconds):
                value=round(seconds*1000);editor=self.page.timecode_input
                QTest.mouseClick(editor,Qt.LeftButton);QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier)
                QTest.keyClicks(editor,f'{value//3600000:02d}:{value//60000%60:02d}:{value//1000%60:02d}.{value%1000:03d}')
                QTest.keyClick(editor,Qt.Key_Return)
            def shot(self,name):
                _capture(window,output/(name+'.png'))
                self.page.video.controller.screenshot_to_file(output/(name+'-mpv.png'))
            def native_position(self):
                observed=self.page.video.controller.observed_properties().get('time-pos')
                if observed is None:observed=self.page.video.controller.get_property('time-pos')
                return float(observed) if observed is not None else None
            def run(self):
                page=self.page;window.showNormal();window.resize(1440,900);yield .3
                QTest.mouseClick(window.subtitle_studio_button,Qt.LeftButton)
                yield .3
                self.check('normal Home opens Studio library',page.project is None)
                chooser=QFileDialog.getOpenFileName
                QFileDialog.getOpenFileName=lambda *a,**kw:(str(output/'projects/seed/original.2byteproj'),'')
                try:QTest.mouseClick(page.project_import_button,Qt.LeftButton)
                finally:QFileDialog.getOpenFileName=chooser
                yield lambda:page.project is not None and page._readiness.ready and page.video._startup_state=='READY'
                page.timeline.thumbnail_requests_enabled=False
                self.check('owned project retains original canonical path',Path(page.project.media.path)==source)
                self.check('actual mpv opens original after reviewed caches were deleted',Path(page.video.controller.get_property('path'))==source)
                if not page.video._paused or page.video._buffered_play_pending:QTest.mouseClick(page.play_button,Qt.LeftButton)
                yield lambda:page.video._paused and page.video.controller.observed_properties().get('pause') is True
                self.timecode(args.start_seconds)
                yield lambda:self.native_position() is not None and abs(self.native_position()-args.start_seconds)<.25
                initial=self.native_position();QTest.mouseClick(page.play_button,Qt.LeftButton)
                yield lambda:page.video.controller.observed_properties().get('pause') is False
                yield .8
                self.check('actual original FLV playback advances',self.native_position()>initial+.2,
                    dict(native_before=initial,native_after=self.native_position(),visual=page.video.visual_position()))
                QTest.mouseClick(page.play_button,Qt.LeftButton)
                yield lambda:page.video.controller.observed_properties().get('pause') is True
                for index,seconds in enumerate((args.start_seconds+1,args.start_seconds-1,args.start_seconds+2)):
                    self.timecode(max(0,seconds))
                    yield lambda target=max(0,seconds):self.native_position() is not None and abs(self.native_position()-target)<.25
                    self.check('original source retained at seek '+str(index),Path(page.video.controller.get_property('path'))==source)
                    self.check('actual seek position '+str(index),abs(self.native_position()-max(0,seconds))<.25,
                        dict(target=seconds,native=self.native_position(),visual=page.video.visual_position()))
                self.check('source time domain preserved',getattr(page.video,'_playback_time_domain','source')=='source')
                self.check('no full proxy request or generated compatibility file',not GLOBAL_INDEXED_MEDIA._requested and not list(GLOBAL_INDEXED_MEDIA.root.glob('v2/*/optimized.*')))
                yield .25;self.shot('01-original-play-seek')
                yield .2
                self.check('actual mpv frame captured',(output/'01-original-play-seek-mpv.png').is_file())
                self.check('no provider or external requests',blank_project_audit._provider_calls==0 and not blank_project_audit._blocked_external_connections)
                QTest.mouseClick(page.studio_back_button,Qt.LeftButton);yield .25
                self.check('normal project close returns to library',page.project is None)
            def finish(self):
                self.timer.stop();self.result['provider_calls']=blank_project_audit._provider_calls
                self.result['blocked_external_connections']=list(blank_project_audit._blocked_external_connections)
                (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),'utf8')
                window.close();QTimer.singleShot(100,QApplication.instance().quit)
        window._original_media_fallback_audit=Audit()
    media_storage_audit.start=start
    sys.argv=[str(ROOT/'quick_start.py')]
    import quick_start
    return quick_start.main()


if __name__=='__main__':raise SystemExit(main())
