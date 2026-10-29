"""Run cold/hot/cancel/retry loading through the normal source or EXE entry."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def _same_path(left,right):
    return os.path.normcase(str(Path(left).resolve()))==os.path.normcase(str(Path(right).resolve()))


def cleanup_owned_recorders(out, expected_exe):
    """Inspect only persisted child PIDs; never enumerate or kill by name."""
    import psutil
    out=Path(out).resolve()
    report={'recorders':[],'orphan_count':0,'cleanup_complete':True}
    try:receipt=json.loads((out/'recorders.json').read_text('utf-8-sig'))
    except (OSError,ValueError) as error:
        return {**report,'cleanup_complete':False,'receipt_status':'missing_or_invalid','error':str(error)}
    if not isinstance(receipt.get('recorders'),list) or len(receipt['recorders'])>2:
        return {**report,'cleanup_complete':False,'receipt_status':'invalid_recorder_inventory'}
    try:
        app=psutil.Process(int(receipt['app_pid']))
        if abs(app.create_time()-float(receipt['app_create_time']))<.001 and app.is_running():
            return {**report,'cleanup_complete':False,'receipt_status':'main_app_still_running'}
    except psutil.NoSuchProcess:pass
    except (psutil.AccessDenied,KeyError,ValueError,TypeError) as error:
        return {**report,'cleanup_complete':False,'receipt_status':'main_app_identity_unavailable','error':str(error)}
    allowed={'loading-continuous.mp4','loading-desktop-dda.mp4'}
    for item in receipt.get('recorders',[]):
        result={'pid':item.get('pid'),'output':item.get('output')};report['recorders'].append(result)
        try:
            output=Path(item['output']).resolve();command=list(map(str,item['command']))
            if (output.parent!=out or output.name not in allowed or not command
                    or not _same_path(item['exe'],expected_exe)
                    or not _same_path(command[0],expected_exe) or not _same_path(command[-1],output)):
                raise ValueError('receipt executable/output is outside this exact audit')
            process=psutil.Process(int(item['pid']))
            if abs(process.create_time()-float(item['create_time']))>=.001:
                raise ValueError('PID creation time differs')
            if not _same_path(process.exe(),expected_exe):raise ValueError('live executable differs')
            if process.ppid()!=int(receipt['app_pid']):raise ValueError('live parent PID differs')
            actual=process.cmdline()
            if (len(actual)!=len(command) or not _same_path(actual[0],command[0])
                    or actual[1:-1]!=command[1:-1] or not _same_path(actual[-1],output)):
                raise ValueError('live command differs')
            result['identity_confirmed']=True
            try:
                result['observed_exit_code']=process.wait(timeout=.2)
                result['status']='exited_during_grace'
            except psutil.TimeoutExpired:
                process.terminate()
                result['observed_exit_code']=process.wait(timeout=5)
                report['orphan_count']+=1
                result['status']='terminated_exact_owned_orphan'
        except psutil.NoSuchProcess:result['status']='already_exited'
        except (psutil.AccessDenied,psutil.TimeoutExpired,ValueError,KeyError,TypeError) as error:
            result.update(status='not_touched_or_cleanup_failed',error=str(error))
            report['cleanup_complete']=False
    return report


def validate_recordings(out, ffprobe, names):
    rows=[]
    for name in names:
        path=Path(out)/name
        row={'file':name,'exists':path.is_file()}
        if path.is_file():
            probe=subprocess.run([str(ffprobe),'-v','error','-show_streams','-show_format','-of','json',str(path)],
                capture_output=True,text=True,errors='replace',timeout=20,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            row.update(ffprobe_exit=probe.returncode,container_readable=probe.returncode==0,error=probe.stderr[-8000:])
            if probe.returncode==0:row['metadata']=json.loads(probe.stdout)
        else:row.update(container_readable=False,error='recording was not created')
        rows.append(row)
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--no-record', action='store_true')
    parser.add_argument('--private', action='store_true')
    parser.add_argument('--native-forensics', action='store_true', help='pair DDA/WGC with native parent/region evidence and labelled held stages')
    parser.add_argument('--skip-widget-grabs', action='store_true', help='exclude QWidget.grab instrumentation from the capture comparison')
    parser.add_argument('--skip-native-frame-grabs', action='store_true', help='avoid screenshot commands that could trigger an mpv redraw')
    parser.add_argument('--foreground-gate', action='store_true', help='wait for foreground-approved.json after a human/computer-use activation')
    parser.add_argument('--no-diagnostic-holds', action='store_true', help='record the normal flow without holding readiness stages')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        parser.error('Use a new repository tmp output')
    if args.private and not args.no_record:
        parser.error('WGC recording requires the interactive desktop')
    if args.native_forensics and (args.private or args.no_record):
        parser.error('native forensics requires both capture paths on the interactive desktop')
    if args.foreground_gate and not args.native_forensics:
        parser.error('foreground gate requires --native-forensics')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    sys.path.insert(0,str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, hydrate_media_contract
    base=Path(args.exe).resolve().parent if args.exe else ROOT
    font_root=base/'assets/fonts'
    for font in font_root.glob('SourceHan*'):
        target=out/'local/Microsoft/Windows/Fonts'/font.name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(font,target)
    ffmpeg=base/'tools/ffmpeg/bin/ffmpeg.exe'
    video=out/'source.mp4'
    audio=out/'source.wav'
    subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=1280x720:rate=30:duration=12',
        '-f','lavfi','-i','sine=frequency=440:duration=12','-c:v','libx264','-preset','ultrafast',
        '-c:a','aac','-shortest',str(video)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run([str(ffmpeg),'-v','error','-i',str(video),'-vn',str(audio)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if args.project:
        shutil.copyfile(args.project,out/'project.2byteproj')
    else:
        save_project(SubtitleProject(media=StudioMedia(path=str(video),duration_ms=12000,width=1280,height=720),
            cues=[StudioCue(f'c{i}',i*1000,i*1000+900,f'载入验收字幕 {i}') for i in range(12)]),out/'project.2byteproj')
    shutil.copyfile(out/'project.2byteproj',out/'other.2byteproj')
    audio_project=SubtitleProject(media=StudioMedia(path=str(audio),duration_ms=12000,width=0,height=0),
        cues=[StudioCue('a',0,1000,'纯音频工程')])
    from twobyteasr.studio.studio_helpers import probe_media_identity
    hydrate_media_contract(audio_project, probe_media_identity(str(audio)), source_path=str(audio))
    save_project(audio_project,out/'audio.2byteproj')
    save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)),out/'empty.2byteproj')
    silent=SubtitleProject(media=StudioMedia(path=str(video),duration_ms=12000,width=1280,height=720))
    hydrate_media_contract(silent, probe_media_identity(str(video)), source_path=str(video))
    for track in silent.audio_tracks:
        track.muted=True
    save_project(silent,out/'silent-video.2byteproj')
    save_project(SubtitleProject(media=StudioMedia(path=str(out/'missing.mp4'),duration_ms=12000,width=1280,height=720),
        cues=[StudioCue('missing',0,1000,'素材尚未关联')]),out/'missing-media.2byteproj')
    shutil.copyfile(out/'empty.2byteproj',out/'entry.2byteproj')
    env=dict(os.environ, TWOBYTEASR_ACCEPTANCE_SCENARIO='studio-loading', TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'entry.2byteproj'), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_LOADING_RECORD='0' if args.no_record else '1', QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    env['TWOBYTEASR_LOADING_NATIVE_FORENSICS']='1' if args.native_forensics else '0'
    env['TWOBYTEASR_LOADING_SKIP_WIDGET_GRABS']='1' if args.skip_widget_grabs else '0'
    env['TWOBYTEASR_LOADING_SKIP_NATIVE_FRAMES']='1' if args.skip_native_frame_grabs else '0'
    env['TWOBYTEASR_LOADING_FOREGROUND_GATE']='1' if args.foreground_gate else '0'
    env['TWOBYTEASR_LOADING_NO_HOLDS']='1' if args.no_diagnostic_holds else '0'
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):
        env.pop(key,None)
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=-1
    try:
        if args.private:
            from isolated_windows_desktop import run_on_desktop
            code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=480)
        else:
            with (out/'application.log').open('wb') as log:
                result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=log,timeout=480,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
                code=result.returncode
    except subprocess.TimeoutExpired:
        (out/'runner-timeout.json').write_text(json.dumps({'reason':'isolated app exceeded 480 seconds'}),'utf8')
    finally:
        cleanup=cleanup_owned_recorders(out,ffmpeg) if not args.no_record else {'cleanup_complete':True,'orphan_count':0,'recorders':[]}
        (out/'recorders-cleanup.json').write_text(json.dumps(cleanup,ensure_ascii=False,indent=2),'utf8')
        names=[] if args.no_record else ['loading-continuous.mp4']+(['loading-desktop-dda.mp4'] if args.native_forensics else [])
        try:recordings=validate_recordings(out,ffmpeg.with_name('ffprobe.exe'),names)
        except Exception as error:recordings=[{'container_readable':False,'error':str(error)}]
        (out/'recorders-validation.json').write_text(json.dumps(recordings,ensure_ascii=False,indent=2),'utf8')
    data=json.loads((out/'loading.json').read_text('utf-8')) if (out/'loading.json').exists() else {}
    from twobyteasr.acceptance.studio_loading_audit import completion_errors
    incomplete=completion_errors(data,record_required=not args.no_record,
        native_required=args.native_forensics,foreground_required=args.foreground_gate)
    if os.environ.get('TWOBYTEASR_NATIVE_LOADING_COVER') == '1':
        presentation = data.get('loading_presentation') or {}
        if (not presentation.get('native_cover_requested')
                or not presentation.get('uses_native_cover') or presentation.get('page_stack') is not False):
            incomplete.append('requested native child cover was not exercised')
    passed=bool(code==0 and data.get('passed') and not incomplete and data.get('normal_shutdown')
                and (args.no_record or data.get('capture_exit_code')==0))
    if args.native_forensics:
        passed=passed and data.get('dda_capture_exit_code')==0 and not data.get('native_probe_errors') and data.get('capture_visibility_valid')
    passed=passed and cleanup['cleanup_complete'] and not cleanup['orphan_count'] and all(row['container_readable'] for row in recordings)
    print(json.dumps(dict(passed=passed,exit_code=code,checks=len(data.get('checks',[])),errors=data.get('errors'),
        completion_errors=incomplete,
        cleanup_complete=cleanup['cleanup_complete'],orphan_recorders=cleanup['orphan_count'],
        recordings_readable=all(row['container_readable'] for row in recordings),output=str(out)),ensure_ascii=False))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
