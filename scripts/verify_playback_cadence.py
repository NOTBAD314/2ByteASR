"""Repeatable foreground cadence run, normal source entry or specified EXE.

Reuses the frame-code generator, normal acceptance entry, PlaybackClock probe,
performance_snapshot and DXGI pixel capture. No test project or historic cache
is required: --generate-media builds one. Performance failures never become
functional failures, and missing/invalid measurement never becomes PASS.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def entry_working_directory(source=None, executable=None):
    # Python -m workers inherit cwd after child-environment sanitization drops
    # PYTHONPATH. Changing only the parent's sys.path mixes baseline and current
    # workers; frozen children load their own archive instead.
    return (source or ROOT).resolve() if executable is None else ROOT

def annotate_measurement_scope(result):
    """The primary HWND probe cannot certify unmeasured follower pixels."""
    result['performance_scope']='primary mpv viewport; Qt/audio diagnostics are separate measurements'
    if int((result.get('media') or {}).get('tracks') or 0)>1:
        result['primary_video_performance_pass']=result.get('performance_pass','UNVERIFIED')
        result['performance_pass']='UNVERIFIED'
        result['performance_scope']='primary viewport only; multi-track performance requires independent probes for visible followers'
    return result


def require_visible_capture(result, spec):
    if spec.get('desktop','foreground')!='foreground':return result
    evidence=result.get('visibility')
    if not isinstance(evidence,dict) or evidence.get('measurement_valid') is not True:
        result['measurement_valid']=False
        result['performance_pass']='UNVERIFIED'
        result['measurement_reason']='missing or invalid native foreground/ROI visibility observations'
    return result


def annotate_transport_evidence(result, spec):
    """A same-file cut changes source time without changing the media binding."""
    clips={r.get('audio_request',{}).get('clip_id') for r in result.get('telemetry',[])
           if r.get('audio_request',{}).get('clip_id')}
    if len(clips)<2 or spec.get('phase')!='steady':return
    checks=result.setdefault('checks',{})
    result.setdefault('source_progress_check_across_cuts',checks.pop('advanced_at_rate',None))
    start=result.get('play_start_qpc');end=result.get('play_end_qpc');project_end=result.get('project_end_ms')
    result['rate_measurement']='project timeline across clip boundaries; raw source subtraction is invalid even when the file binding stays primary'
    if start is None or end is None or project_end is None:
        result['project_progress']={'measurement_valid':False,'performance_pass':'UNVERIFIED'}
        return
    expected=spec['start']*1000+(end-start)*spec.get('rate',1)*1000
    error=project_end-expected
    result['project_progress']={'measurement_valid':True,'clock':'play request/end perf_counter; requested exact project seek to final project playhead',
        'project_end_ms':project_end,'expected_end_ms':expected,'error_ms':error,'tolerance_ms':400}
    checks['project_advanced_at_rate']=abs(error)<400
    result['functional_pass']=bool(result.get('finished') and all(checks.values()) and not result.get('errors'))

def capture_region(value):
    """Explicit normalized video region; no guessed follower coordinates."""
    import re
    try:
        name,x,y,w,h,barcode=value.split(',')
        rect=tuple(map(float,(x,y,w,h)));barcode=int(barcode)
        if name=='primary' or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',name):raise ValueError()
        x,y,w,h=rect
        if not (0<=x<1 and 0<=y<1 and 0<w<=1-x and 0<h<=1-y and 0<=barcode<1080):raise ValueError()
    except (ValueError,TypeError):
        raise argparse.ArgumentTypeError('region must be name,x,y,width,height,barcode_y; normalized inside the primary viewport')
    return {'name':name,'rect':rect,'barcode_y':barcode}


def attach_region_results(result, regions, evidence, target, *, source_fps, rate):
    import csv
    from twobyteasr.diagnostics.playback_metrics import desktop_cadence
    result['secondary_capture']=evidence
    result['video_layers']={'primary':result.get('desktop') or {}}
    screen=next((s for s in result.get('environment',{}).get('screens',[]) if s['name']==result.get('window',{}).get('screen')),None)
    for region in regions:
        path=target/(region['name']+'-desktop.csv')
        if not path.exists() or not screen or not result.get('play_end_qpc'):
            data={'measurement_valid':False,'performance_pass':'UNVERIFIED','reason':'missing capture, playback interval, or measured display refresh rate'}
        else:
            with path.open(encoding='utf8') as stream:rows=list(csv.DictReader(stream))
            data=desktop_cadence(rows,result['play_start_qpc']+1,result['play_end_qpc'],source_fps=source_fps*rate,display_hz=screen['refresh_hz'],barcode=True)
        result['video_layers'][region['name']]=data
    layers=list(result['video_layers'].values())
    result['primary_video_performance_pass']=result.get('primary_video_performance_pass',result.get('performance_pass','UNVERIFIED'))
    result['measurement_valid']=all(layer.get('measurement_valid') is True for layer in layers) and not evidence['errors']
    covered=len(regions)>=max(0,int(result.get('media',{}).get('tracks',1))-1)
    result['performance_pass']=(all(layer.get('performance_pass') is True for layer in layers)
        if result['measurement_valid'] and covered and all(isinstance(layer.get('performance_pass'),bool) for layer in layers) else 'UNVERIFIED')
    result['performance_scope']='primary video and explicitly supplied fixed regions; excludes audio, caption pixels, and moving/occluded regions'


def annotate_phase_evidence(result, target, spec):
    """Keep discrete operations out of the steady-playback interpretation."""
    import csv
    from twobyteasr.diagnostics.playback_metrics import distribution
    result['operation_windows']=[dict(operation,window_seconds=1.,qt_delay_ms=distribution([
        row['delay_ms'] for row in result.get('heartbeat',[]) if operation['at']<=row['at']<operation['at']+1]))
        for operation in result.get('operations',[])]
    result['first_changed_video_frame']={'measurement_valid':False,'performance_pass':'UNVERIFIED'}
    path=target/'desktop.csv';start=result.get('play_start_qpc')
    if path.exists() and start and spec.get('barcode_y',-1)>=0:
        with path.open(encoding='utf8') as stream:rows=list(csv.DictReader(stream))
        code=round(float(result.get('before',{}).get('time-pos',spec['start']))*spec['source_fps'])%spec.get('frame_code_period',4096)
        samples=[row for row in rows if start<=float(row['desktop_qpc_s'])<start+1 and int(row['frame_code'])>=0]
        previous=[row for row in rows if start-2<=float(row['desktop_qpc_s'])<start and int(row['frame_code'])>=0]
        # The known paused source code must actually be seen before its first
        # change. A collector starting late must not pass the first-frame gate.
        if samples and (int(samples[0]['frame_code'])==code or (previous and int(previous[-1]['frame_code'])==code)):
            changed=next((row for row in samples if int(row['frame_code'])!=code),None)
            if changed:
                delay=(float(changed['desktop_qpc_s'])-start)*1000
                valid=float(changed['copy_decode_ms'])<=1000/spec['source_fps']
                result['first_changed_video_frame']={'measurement':'play request perf_counter to first changed standard frame code at DXGI LastPresentTime; not physical scanout',
                    'measurement_valid':valid,'delay_ms':delay,'source_frame_budget_ms':1000/spec['source_fps'],
                    'performance_pass':delay<=500 if valid else 'UNVERIFIED','threshold_ms':500}
        if spec.get('phase')=='steady' and result.get('play_end_qpc') and spec.get('frame_pts_ms'):
            from twobyteasr.diagnostics.playback_av_alignment import desktop_pcm_alignment
            result['desktop_pcm_alignment']=desktop_pcm_alignment(rows,result.get('telemetry',[]),
                start=start+1,end=result['play_end_qpc'],play_start=start,
                source_start_ms=float(result.get('before',{}).get('time-pos',spec['start']))*1000,
                source_fps=spec['source_fps'],source_path=result.get('media',{}).get('path',''),rate=spec.get('rate',1.),
                code_period=spec.get('frame_code_period',4096),frame_pts_ms=spec['frame_pts_ms'])
    if spec.get('phase')!='steady':
        result['whole_window_video_performance_pass']=result.get('performance_pass','UNVERIFIED')
        result['performance_pass']='UNVERIFIED'
        result['performance_scope']='discrete-operation run; inspect operation windows, not an uninterrupted steady-playback pass'
    if spec.get('phase')=='resize':
        from twobyteasr.diagnostics.playback_interaction_metrics import resize_results
        evidence=resize_results(result,target,spec)
        result['resize_evidence']=evidence
        result['measurement_valid']=evidence['measurement_valid']
        result['performance_pass']=evidence['performance_pass']
        result['performance_scope']=evidence['scope']
    elif spec.get('phase')=='seek':
        from twobyteasr.diagnostics.playback_interaction_metrics import seek_results
        evidence=seek_results(result,target,spec)
        result['seek_evidence']=evidence
        result['measurement_valid']=evidence['measurement_valid']
        result['performance_pass']=evidence['performance_pass']
        result['performance_scope']=evidence['scope']
        if int((result.get('media') or {}).get('tracks',1))>1:
            result['primary_seek_performance_pass']=evidence['performance_pass']
            result['performance_pass']='UNVERIFIED'
            result['follower_seek_status']='UNVERIFIED: per-follower target PTS matching is not part of this primary probe'


def run_manifest(args,out):
    """Explicit local media/project matrix; never infer replacement fixtures."""
    import re
    manifest=args.manifest.resolve()
    cases=json.loads(manifest.read_text('utf-8-sig')).get('cases',[])
    if not 1<=len(cases)<=20:raise ValueError('manifest must contain 1..20 cases')
    seen=set();results=[]
    for case in cases:
        name=str(case.get('id',''))
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',name) or name in seen:raise ValueError('unique simple case id required')
        seen.add(name)
        kinds=[key for key in ('project','media') if case.get(key)]
        if len(kinds)!=1:raise ValueError('each case requires exactly one project or media')
        kind=kinds[0];path=(manifest.parent/str(case[kind])).resolve()
        if not path.is_file():raise FileNotFoundError(str(path))
        from twobyteasr.diagnostics.playback_diagnostic import runner_command
        command=[*runner_command(Path(__file__).resolve()),'--output',str(out/name),'--'+kind,str(path)]
        for key in ('seconds','repeat','rate','start','settle','phase','captions','diagnostics','desktop','zoom','frame_code_period'):
            command.extend(['--'+key.replace('_','-'),str(case.get(key,getattr(args,key)))])
        for key in ('source','exe','capture','presentmon'):
            value=getattr(args,key)
            if value:command.extend(['--'+key,str(value.resolve())])
        for key in ('elevate_presentmon','maximized','follow','audible','wait_foreground'):
            if case.get(key,getattr(args,key)):command.append('--'+key.replace('_','-'))
        if case.get('barcode_y',args.barcode_y)>=0:command.extend(['--barcode-y',str(case.get('barcode_y',args.barcode_y))])
        for region in case.get('regions',[]):command.extend(['--region',str(region)])
        code=subprocess.call(command,cwd=ROOT)
        summary_path=out/name/'summary.json'
        results.append({'id':name,'exit_code':code,'summary':str(summary_path),
            'runs':json.loads(summary_path.read_text('utf8'))['runs'] if summary_path.is_file() else []})
        (out/'summary.json').write_text(json.dumps({'manifest':str(manifest),'cases':results},ensure_ascii=False,indent=2),'utf8')
    return 0 if all(row['exit_code']==0 for row in results) else 1

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    inputs=p.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--project',type=Path);inputs.add_argument('--media',type=Path);inputs.add_argument('--generate-media',action='store_true');inputs.add_argument('--manifest',type=Path)
    entry=p.add_mutually_exclusive_group();entry.add_argument('--exe',type=Path);entry.add_argument('--source',type=Path)
    p.add_argument('--capture',type=Path,help='Compiled scripts/capture_desktop_cadence.cpp; absent means UNVERIFIED')
    p.add_argument('--region',type=capture_region,action='append',default=[],help='Additional fixed video probe: name,x,y,width,height,barcode_y (coordinates relative to primary viewport)')
    p.add_argument('--presentmon',type=Path,help='Official PresentMon console executable; PID-filtered ETW')
    p.add_argument('--elevate-presentmon',action='store_true',help='Explicitly allow Windows administrator confirmation for ETW')
    p.add_argument('--maximized',action='store_true')
    p.add_argument('--zoom',type=int,choices=[80,90,100,110,120,135,150,175,200],default=100,help='Isolated interface zoom; system DPI is measured separately')
    p.add_argument('--phase',choices=['steady','background','seek','resize'],default='steady')
    p.add_argument('--desktop',choices=['foreground','private'],default='foreground',help='private validates GUI/control only, never screen cadence')
    p.add_argument('--wait-foreground',action='store_true',help='write PID/HWND request and wait for matching foreground-approved.json plus real unobscured foreground')
    p.add_argument('--seconds',type=float,default=20,help='steady wall duration; resize divides this stable sample budget over three windows and records handoff time separately');p.add_argument('--repeat',type=int,default=3)
    p.add_argument('--rate',type=float,default=1);p.add_argument('--start',type=float,default=5)
    p.add_argument('--captions',choices=['none','plain','bilingual','motion'],default='plain')
    p.add_argument('--barcode-y',type=int,default=-1);p.add_argument('--settle',type=float,default=5)
    p.add_argument('--frame-code-period',type=int,default=4096,help='Source-frame-code repeat period; use 1800 only for an explicitly 30s-looped 60fps fixture')
    p.add_argument('--diagnostics',choices=['off','normal','detailed'],default='normal')
    p.add_argument('--follow',action='store_true');p.add_argument('--audible',action='store_true')
    p.add_argument('--compare',type=Path,help='Previous summary.json, all repeats retained')
    a=p.parse_args();out=a.output.resolve()
    from twobyteasr.diagnostics.playback_diagnostic import output_root
    permitted = out.is_relative_to(ROOT/'tmp') or (getattr(sys,'frozen',False) and out.is_relative_to(output_root()))
    if out.exists() or not permitted:p.error('use a fresh output under checkout/tmp (or the packaged diagnostics temporary folder)')
    if not 16<=a.seconds<=180 or not 1<=a.repeat<=10:p.error('seconds 16..180; repeat 1..10')
    if a.phase=='resize' and a.maximized:p.error('resize capture uses a restored window; omit --maximized')
    if not 1<=a.frame_code_period<=4096:p.error('frame-code-period must be 1..4096')
    if a.desktop=='private' and (a.capture or a.presentmon):p.error('display capture requires the foreground desktop')
    if a.desktop=='private' and a.wait_foreground:p.error('--wait-foreground requires the interactive desktop')
    if a.region and (not a.capture or a.desktop!='foreground'):p.error('additional regions require foreground desktop capture')
    if len(a.region)>4 or len({r['name'] for r in a.region})!=len(a.region):p.error('at most four uniquely named regions')
    out.mkdir(parents=True)
    if a.manifest:return run_manifest(a,out)
    if a.capture and not a.capture.is_file():p.error('capture executable missing; compile the checked-in helper or omit --capture (UNVERIFIED)')
    capabilities={}
    if a.capture:
        query=subprocess.run([str(a.capture.resolve()),'--capabilities'],capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
        if query.returncode==0:
            try:capabilities=json.loads(query.stdout)
            except ValueError:pass
    if a.region and not capabilities.get('multi_region'):
        p.error('multi-region audit requires the protocol 3 single-session collector; separate duplication clients are not equivalent')
    if a.generate_media:
        import math
        from verify_visible_playback import make_media
        # Resize uses three stable windows plus explicitly excluded collector
        # handoffs. The continuous source must also cover that extra wall time.
        playback_seconds=a.seconds+(30 if a.phase=='resize' else 0)
        duration=max(30,math.ceil(a.start+playback_seconds*a.rate+2))
        media=make_media(ROOT,out/'media',duration=duration,with_loop=False)/f'V1-{duration}s.mp4';a.barcode_y=710
    elif a.media:media=a.media.resolve()
    else:
        from twobyteasr.projects.studio_project import load_project
        project=load_project(a.project.resolve());media=Path(project.media.path)
    if not media.is_file():p.error('requested media missing: '+str(media))
    ffprobe=ROOT/'tools/ffmpeg/bin/ffprobe.exe'
    info=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_streams','-show_format','-of','json',str(media)],creationflags=subprocess.CREATE_NO_WINDOW))
    video=next((s for s in info['streams'] if s.get('codec_type')=='video'),None)
    if not video:p.error('selected media has no video stream')
    from fractions import Fraction
    fps=float(Fraction(video['avg_frame_rate']))
    if fps<=0:p.error('media frame rate unavailable; provide timestamp-analyzed media instead of assuming 60fps')
    if not a.project:
        from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project
        duration=round(float(info['format']['duration'])*1000)
        project=SubtitleProject(media=StudioMedia(path=str(media),duration_ms=duration,width=video['width'],height=video['height']))
        if a.captions!='none':
            project.cues=[StudioCue(f'cue-{i}',i*2000,i*2000+1800,f'第 {i+1} 条字幕：连续播放与边界检查') for i in range(duration//2000)]
        project.validate()
        if a.captions in ('bilingual','motion'):
            p.error('bilingual/motion require an explicit project; no silent substitution for authored effects')
        original=out/'fixture.2byteproj';save_project(project,original)
    else:original=a.project.resolve()
    original_bytes=original.read_bytes()
    spec={'seconds':a.seconds,'rate':a.rate,'start':a.start,'source_fps':fps,'barcode_y':a.barcode_y,
          'settle':a.settle,'follow':a.follow,'audio':'audible' if a.audible else 'muted',
          'capture':str(a.capture.resolve()) if a.capture else '', 'diagnostics':a.diagnostics,
          'presentmon':str(a.presentmon.resolve()) if a.presentmon else '',
          'elevate_presentmon':a.elevate_presentmon,'maximized':a.maximized,'phase':a.phase,'desktop':a.desktop,'interface_zoom_percent':a.zoom,
          'wait_foreground':a.wait_foreground}
    spec['regions']=a.region
    spec['capture_capabilities']=capabilities
    spec['capture_sha256']=hashlib.sha256(a.capture.read_bytes()).hexdigest() if a.capture else None
    spec['frame_code_period']=a.frame_code_period
    if a.barcode_y>=0 and float(info['format'].get('duration',0))<=600:
        timing=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-select_streams','v:0','-show_frames',
            '-show_entries','frame=best_effort_timestamp_time','-of','json',str(media)],creationflags=subprocess.CREATE_NO_WINDOW,timeout=180))
        points=[float(f['best_effort_timestamp_time'])*1000 for f in timing.get('frames',[]) if f.get('best_effort_timestamp_time') is not None]
        declared=video.get('nb_frames')
        if declared not in (None,'N/A') and len(points)!=int(declared):p.error('source frame PTS count differs from declared frame count; cannot map barcode identity safely')
        spec['frame_pts_ms']=points
        (out/'source-frame-pts.json').write_text(json.dumps(points),'utf8')
    (out/'media-info.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),'utf8')
    rows=[]
    for repeat in range(a.repeat):
        target=out/f'run-{repeat+1}';target.mkdir();(target/'project.2byteproj').write_bytes(original_bytes)
        # Same deterministic INI location as test_isolation._isolate_qsettings;
        # no read or write to the operator's registry is needed.
        settings=target/'qsettings';settings.mkdir()
        digest=hashlib.sha256(b'2ByteASR/2ByteASR').hexdigest()[:10]
        (settings/f'2ByteASR_2ByteASR-{digest}.ini').write_text(f'[ui]\nzoom_percent={a.zoom}\n','utf8')
        fonts=[]
        for font in (ROOT/'assets/fonts').glob('*'):
            if font.suffix.lower() not in ('.otf','.ttf','.ttc'):continue
            destination=target/'local/Microsoft/Windows/Fonts'/font.name
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(font,destination)
            fonts.append({'name':font.name,'sha256':hashlib.sha256(font.read_bytes()).hexdigest()})
        (target/'font-inputs.json').write_text(json.dumps(fonts,indent=2),'utf8')
        (target/'cadence-input.json').write_text(json.dumps(spec),'utf8')
        env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(target),LOCALAPPDATA=str(target/'local'),APPDATA=str(target/'roaming'),
            TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_ACCEPTANCE_DIR=str(target),TWOBYTEASR_STARTUP_PROJECT=str(target/'project.2byteproj'),
            TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_ACCEPTANCE_SCENARIO='playback-cadence',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',PYTHONUNBUFFERED='1',
            TWOBYTEASR_PLAYBACK_PROBE='1' if a.diagnostics!='off' else '0',TWOBYTEASR_PLAYBACK_PROBE_DETAIL='light' if a.diagnostics=='normal' else '',
            HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_RAISE','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):env.pop(key,None)
        env['TWOBYTEASR_CAPTURE_REGIONS']=';'.join(','.join([r['name'],*map(str,r['rect']),str(r['barcode_y'])]) for r in a.region)
        if a.exe:command=[str(a.exe.resolve())]
        else:
            source=(a.source or ROOT).resolve()
            # Source-only instrumentation imports the untouched baseline's normal
            # entry and the current auditor. Production EXEs never load this code.
            driver=target/'source_driver.py'
            driver.write_text('''def main():
    import importlib.util,os,sys
    sys.path.insert(0,os.environ['CADENCE_SOURCE'])
    from twobyteasr.acceptance import studio_acceptance_audit
    metric_spec=importlib.util.spec_from_file_location('twobyteasr.diagnostics.playback_metrics',os.environ['CADENCE_METRICS'])
    metric=importlib.util.module_from_spec(metric_spec);sys.modules[metric_spec.name]=metric;metric_spec.loader.exec_module(metric)
    for name,key in [('twobyteasr.acceptance.playback_interactions','CADENCE_INTERACTIONS'),('twobyteasr.diagnostics.playback_interaction_metrics','CADENCE_OPERATION_METRICS'),('twobyteasr.acceptance.loading_native_probe','CADENCE_NATIVE_PROBE'),('twobyteasr.acceptance.playback_visibility','CADENCE_VISIBILITY')]:
        helper_spec=importlib.util.spec_from_file_location(name,os.environ[key])
        helper=importlib.util.module_from_spec(helper_spec);sys.modules[name]=helper;helper_spec.loader.exec_module(helper)
    spec=importlib.util.spec_from_file_location('twobyteasr.acceptance.playback_cadence_audit',os.environ['CADENCE_AUDIT'])
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    studio_acceptance_audit.start_acceptance=lambda window:module.start(window,studio_acceptance_audit.audit_directory())
    import quick_start
    return quick_start.main()
if __name__=='__main__':raise SystemExit(main())
''','utf8')
            env.update(CADENCE_SOURCE=str(source),CADENCE_AUDIT=str(ROOT/'twobyteasr/acceptance/playback_cadence_audit.py'),CADENCE_METRICS=str(ROOT/'twobyteasr/diagnostics/playback_metrics.py'),
                CADENCE_INTERACTIONS=str(ROOT/'twobyteasr/acceptance/playback_interactions.py'),
                CADENCE_OPERATION_METRICS=str(ROOT/'twobyteasr/diagnostics/playback_interaction_metrics.py'),
                CADENCE_NATIVE_PROBE=str(ROOT/'twobyteasr/acceptance/loading_native_probe.py'),
                CADENCE_VISIBILITY=str(ROOT/'twobyteasr/acceptance/playback_visibility.py'),
                TWOBYTEASR_ACCEPTANCE_SCENARIO='workbench-performance')
            command=[sys.executable,'-B',str(driver)]
        entry_cwd=entry_working_directory(a.source,a.exe)
        region_evidence={'regions':[],'errors':[]}
        if a.desktop=='private':
            from isolated_windows_desktop import run_on_desktop
            code=run_on_desktop(command,cwd=entry_cwd,env=env,output=target/'process',timeout=a.seconds+180)
        else:
          with (target/'application.log').open('wb') as log:
            process=subprocess.Popen(command,cwd=entry_cwd,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                code=process.wait(timeout=a.seconds+180+(300 if a.wait_foreground else 60))
                if a.region:region_evidence={'regions':a.region,'errors':[],'single_duplication':True,'protocol':capabilities.get('protocol')}
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW);code=-1
        path=target/'result.json';result=json.loads(path.read_text('utf8')) if path.exists() else {'functional_pass':False,'measurement_valid':False,'performance_pass':'UNVERIFIED','errors':['no completed result']}
        annotate_transport_evidence(result,spec)
        annotate_measurement_scope(result)
        if a.region and a.phase!='resize':attach_region_results(result,a.region,region_evidence,target,source_fps=fps,rate=a.rate)
        annotate_phase_evidence(result,target,spec)
        require_visible_capture(result,spec)
        if capabilities.get('ready_after_first_frame') and a.phase!='resize':
            names=['desktop.csv',*[r['name']+'-desktop.csv' for r in a.region]]
            ready={}
            for name in names:
                marker=target/(name+'.ready')
                if marker.exists():
                    try:ready[name]=json.loads(marker.read_text('utf8'))
                    except ValueError:pass
            result['capture_readiness']=ready
            all_ready=(len(ready)==len(names) and result.get('play_start_qpc') is not None
                       and all(r.get('ready_qpc_s',float('inf'))<=result['play_start_qpc'] for r in ready.values()))
            result['capture_ready_before_play']=all_ready
            if not all_ready:
                result['measurement_valid']=False;result['performance_pass']='UNVERIFIED'
                result['measurement_reason']='collector had not acquired all initial regions before playback began'
        result['runner_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        result['runtime_working_directory']=str(entry_cwd)
        if not a.exe:
            worker=entry_cwd/'twobyteasr/playback/video_decode_worker.py'
            result['source_worker_provenance']={'module':str(worker),'sha256':hashlib.sha256(worker.read_bytes()).hexdigest(),
                'resolution':'Python -m in selected source cwd; sanitized child environment'}
        result['exit_code']=code;result['input_unchanged']=original.read_bytes()==original_bytes
        if code or not result['input_unchanged']:result['functional_pass']=False
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        rows.append({'run':repeat+1,'result':str(path),**{k:result.get(k) for k in ('functional_pass','measurement_valid','performance_pass','ui_delay_ms','callback_ms','desktop','errors','identity','exit_code')}})
        print(json.dumps({k:rows[-1][k] for k in ('run','functional_pass','measurement_valid','performance_pass','errors')},ensure_ascii=False),flush=True)
    summary={'schema':1,'conditions':spec,'input_sha256':hashlib.sha256(original_bytes).hexdigest(),'media_info':str(out/'media-info.json'),'runs':rows}
    if a.compare:summary['baseline']=json.loads(a.compare.read_text('utf8'))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),'utf8')
    return 0 if all(r['functional_pass'] and r['measurement_valid'] and r['performance_pass'] is True for r in rows) else 1

if __name__=='__main__':raise SystemExit(main())
