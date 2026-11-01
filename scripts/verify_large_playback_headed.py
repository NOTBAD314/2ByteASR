"""Measure source Studio on an owned Windows desktop and a copied project."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--fonts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--cold-seconds',type=float,default=4)
    parser.add_argument('--require-cue',action='append',default=[])
    parser.add_argument('--delay-cue-ms',type=float,default=0)
    parser.add_argument('--start', type=float, default=2100)
    parser.add_argument('--rate', type=float, default=1)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--trace-prefetch', action='store_true')
    parser.add_argument('--interactions', action='store_true')
    parser.add_argument('--wait-scene', action='store_true', help='Wait for paused caption pixels before the screenshot')
    parser.add_argument('--product', type=Path)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--visible', action='store_true')
    parser.add_argument('--size', default='1800x1040')
    parser.add_argument('--audio', action='store_true')
    parser.add_argument('--loopback',type=Path)
    parser.add_argument('--preheat', choices=('normal','motion-off','off'), default='normal')
    parser.add_argument('--mpv', type=Path, required=True)
    args = parser.parse_args()
    if args.loopback and (not args.visible or not args.audio):parser.error('Loopback requires --visible --audio')
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / 'tmp'):
        parser.error('Output must be a new directory under source/tmp')
    out.mkdir(parents=True)
    original = hashlib.sha256(args.project.read_bytes()).hexdigest()
    project = out / 'project.2byteproj'
    shutil.copy2(args.project, project)
    spec = dict(seconds=args.seconds, start=args.start, rate=args.rate, repeats=args.repeats, profile=args.profile,
                wait_scene=args.wait_scene, trace_prefetch=args.trace_prefetch, audio=args.audio, preheat=args.preheat,
                cold_seconds=args.cold_seconds,require_cues=args.require_cue,delay_cue_ms=args.delay_cue_ms)
    spec['visible']=args.visible
    (out / 'input.json').write_text(json.dumps(spec, indent=2), encoding='utf8')
    env = dict(os.environ, TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='review-editor', TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_STARTUP_SIZE=args.size,
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR='1', PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
        LARGE_PLAYBACK_FONTS=str(args.fonts.resolve()))
    env['GIT_OPTIONAL_LOCKS']='0'
    env['TWOBYTEASR_MPV'] = str(args.mpv.resolve())
    if args.interactions:
        env['LARGE_PLAYBACK_INTERACTIONS'] = '1'
    if args.product:
        env['LARGE_PLAYBACK_PRODUCT'] = str(args.product.resolve())
    if args.exe:
        env['TWOBYTEASR_ACCEPTANCE_SCENARIO']='large-playback'
        command=[str(args.exe.resolve())]
    else:command=[sys.executable,'-B',str(root/'scripts/large_playback_entry.py')]
    if args.visible:
        import subprocess
        with (out/'process.stdout.txt').open('wb') as stdout,(out/'process.stderr.txt').open('wb') as stderr:
            process=subprocess.Popen(command,cwd=root,env=env,stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (out/'process.json').write_text(json.dumps(dict(pid=process.pid,command=command,visible=True)),'utf8')
            capture=None;capture_files=[];deadline=__import__('time').monotonic()+max(240,args.seconds+200)
            while process.poll() is None and __import__('time').monotonic()<deadline:
                marker=out/'playback-phase.json'
                if args.loopback and capture is None and marker.is_file():
                    try:phase=json.loads(marker.read_text('utf8'))
                    except (OSError,ValueError):phase={}
                    if phase.get('phase')=='first':
                        capture_files=[(out/'audio-capture.stdout.jsonl').open('wb'),(out/'audio-capture.stderr.txt').open('wb')]
                        (out/'audio-launch.json').write_text(json.dumps(dict(before=__import__('time').perf_counter(),phase=phase)),'utf8')
                        capture=subprocess.Popen([str(args.loopback.resolve()),str(phase['pid']),str(min(10,max(1,args.cold_seconds-1))),str(out/'actual-loopback.wav')],
                            stdout=capture_files[0],stderr=capture_files[1],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                __import__('time').sleep(.1)
            if process.poll() is None:process.terminate();process.wait(10);code=-1
            else:code=process.returncode
            if capture is not None:
                try:capture_code=capture.wait(timeout=15)
                except subprocess.TimeoutExpired:capture.terminate();capture.wait(5);capture_code=-1
                for stream in capture_files:stream.close()
                (out/'audio-capture-exit.json').write_text(json.dumps(dict(exit=capture_code)),'utf8')
    else:
        from isolated_windows_desktop import run_on_desktop
        code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=max(240,args.seconds+200))
    path = out / 'result.json'
    result = json.loads(path.read_text('utf8')) if path.exists() else {}
    result.update(process_exit=code, source_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==original)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: result.get(k) for k in ('passed', 'error', 'performance', 'process_exit', 'source_unchanged')}, ensure_ascii=False))
    return 0 if result.get('passed') and result.get('gui_shutdown') and code == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
