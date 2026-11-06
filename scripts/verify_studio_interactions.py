"""Same real-project/window/profile procedure before and after interaction fixes."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--part',default='all',choices=['all','timeline','proofread','source','colors','instant','long'])
    parser.add_argument('--cycles',type=int,default=5)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--profile',action='store_true')
    parser.add_argument('--observe-failures',action='store_true')
    parser.add_argument('--scale',default='1')
    parser.add_argument('--restart',type=Path)
    parser.add_argument('--complex',action='store_true')
    parser.add_argument('--instant-colors',action='store_true')
    parser.add_argument('--playback-seconds',type=float,default=0)
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('fresh output under source/tmp required')
    out.mkdir(parents=True)
    original=(args.restart/'colors-saved.2byteproj' if args.restart else args.project).resolve()
    digest=hashlib.sha256(original.read_bytes()).hexdigest()
    shutil.copy2(original,out/'project.2byteproj')
    fixtures=root/'tmp/interaction-fixtures'
    fixtures.mkdir(parents=True,exist_ok=True)
    for name in ('red','blue'):
        target=fixtures/(name+'.mp4')
        if not target.exists():
            subprocess.run([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-y',
                '-f','lavfi','-i',f'color=c={name}:s=640x360:r=25:d=12',
                '-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=12',
                '-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac',str(target)],
                check=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='studio-interactions',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_SIZE='1440x900',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,PYTHONUTF8='1',
        REAL_LONG_PROJECT=str(out/'project.2byteproj'),REAL_LONG_PROFILE=str(int(args.profile)),
        REAL_LONG_BASELINE='1',TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_INVOKER_CWD=str(root),INTERACTIONS_PART=args.part,INTERACTIONS_CYCLES=str(args.cycles),
        INTERACTIONS_FIXTURES=str(fixtures),TWOBYTEASR_MPV=str(root/'tools/mpv/mpv.exe'),
        INTERACTIONS_OBSERVE=str(int(args.observe_failures)),
        INTERACTIONS_COLOR_RESTART=str(args.restart.resolve()) if args.restart else '',
        INTERACTIONS_COMPLEX=str(int(args.complex)),
        INTERACTIONS_INSTANT_COLORS=str(int(args.instant_colors)),
        INTERACTIONS_PLAYBACK_SECONDS=str(max(0,args.playback_seconds)),
        INTERACTIONS_VISIBLE=str(int(args.visible)),
        TWOBYTEASR_SEEK_CACHE_ROOT=str(root/'tmp/interactions-seek-cache'))
    env.pop('TWOBYTEASR_STARTUP_OPEN_STUDIO',None)
    profile=out/'local/2ByteASR/SubtitleStudioPreview'
    profile.mkdir(parents=True)
    (profile/'settings.json').write_text(json.dumps({'project_root':str(out/'library'),
        'studio_preferences':{'auto_cover':False,'recovery_policy':'official'}}),'utf8')
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    if args.baseline and not args.exe:
        baseline=args.baseline.resolve()
        modules={'.'.join(p.relative_to(baseline).with_suffix('').parts):str(p)
            for p in (baseline/'twobyteasr').rglob('*.py')
            if 'acceptance' not in p.parts and (root/p.relative_to(baseline)).is_file()
            and (root/p.relative_to(baseline)).read_bytes()!=p.read_bytes()}
        entry=out/'baseline_entry.py'
        entry.write_text('import sys,importlib.abc,importlib.util,runpy\n'
            +'sys.path.insert(0,'+repr(str(root))+')\nmodules='+repr(modules)+'\n'
            +'class Before(importlib.abc.MetaPathFinder):\n'
            +' def find_spec(self,name,path=None,target=None):\n'
            +'  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'
            +'sys.meta_path.insert(0,Before())\nrunpy.run_path('+repr(str(root/'quick_start.py'))+',run_name="__main__")\n','utf8')
        command=[sys.executable,'-B',str(entry)]
        (out/'baseline-modules.json').write_text(json.dumps(modules,indent=2),'utf8')
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=750,
        desktop_name='Default' if args.visible else None)
    result_path=out/'result.json'
    r=json.loads(result_path.read_text('utf8')) if result_path.exists() else {}
    r.update(exit_code=code,input_unchanged=hashlib.sha256(original.read_bytes()).hexdigest()==digest,
             original_sha256=digest)
    stderr=(out/'process/stderr.log').read_text('utf8',errors='replace')
    r['python_failure_detected']='Traceback (most recent call last)' in stderr
    r['passed']=bool(r.get('passed') and all(r.get('checks',{}).values()) and not r['python_failure_detected'])
    result_path.write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str),'utf8')
    print(json.dumps({**{k:r.get(k) for k in ('passed','error','exit_code','input_unchanged')},
        'checked':len(r.get('checks',{})),'failed':[k for k,v in r.get('checks',{}).items() if not v]},ensure_ascii=False))
    return 0 if code==0 and r.get('passed') and r['input_unchanged'] else 1


if __name__=='__main__':
    raise SystemExit(main())
