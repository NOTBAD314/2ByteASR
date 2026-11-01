"""Compare long-project interactions through the normal application entry."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',type=Path)
    p.add_argument('--profile',action='store_true')
    p.add_argument('--seconds',type=int,default=0)
    p.add_argument('--visible',action='store_true')
    p.add_argument('--preparation-off',action='store_true')
    p.add_argument('--baseline',type=Path)
    p.add_argument('--waveform-cache',type=Path)
    a=p.parse_args();out=a.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        p.error('A fresh directory under this source/tmp is required')
    out.mkdir(parents=True)
    raw=a.project.read_bytes();(out/'project.2byteproj').write_bytes(raw)
    if a.waveform_cache:
        shutil.copytree(a.waveform_cache.resolve(),out/'local/2ByteASR/SubtitleStudioPreview/waveform-cache')
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_STARTUP_SIZE='1600x950',TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_SEEK_CACHE_ROOT=str(ROOT/'tmp/long-shared-seek'),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='long-interactions',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        LONG_AUDIT_PROFILE=str(int(a.profile)),LONG_AUDIT_SECONDS=str(a.seconds),
        LONG_AUDIT_PREPARATION_OFF=str(int(a.preparation_off)),LONG_AUDIT_EXTERNAL_RESOURCES='1',
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',PYTHONUTF8='1')
    trusted=ROOT.parents[2]/'dist/2ByteASR/tools/mpv/mpv.exe'
    if trusted.is_file():env['TWOBYTEASR_MPV']=str(trusted)
    from isolated_windows_desktop import run_on_desktop
    command=[str(a.exe.resolve())] if a.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    if a.baseline and not a.exe:
        modules={'.'.join(p.relative_to(a.baseline.resolve()).with_suffix('').parts):str(p)
                 for p in (a.baseline.resolve()/'twobyteasr').rglob('*.py')
                 if 'acceptance' not in p.parts
                 and (ROOT/p.relative_to(a.baseline.resolve())).is_file()
                 and (ROOT/p.relative_to(a.baseline.resolve())).read_bytes()!=p.read_bytes()}
        entry=out/'before_entry.py'
        entry.write_text('import sys,importlib.abc,importlib.util,runpy\n'
            +'sys.path.insert(0,'+repr(str(ROOT))+')\nmodules='+repr(modules)+'\n'
            +'class Before(importlib.abc.MetaPathFinder):\n'
            +' def find_spec(self,name,path=None,target=None):\n'
            +'  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'
            +'sys.meta_path.insert(0,Before())\nrunpy.run_path('+repr(str(ROOT/'quick_start.py'))+',run_name="__main__")\n','utf8')
        command=[sys.executable,'-B',str(entry)]
    import subprocess
    sampler=subprocess.Popen([sys.executable,'-B',str(ROOT/'scripts/long_interaction_resources.py'),'--output',str(out)],
                             cwd=ROOT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',
            timeout=max(900,a.seconds+400),desktop_name='Default' if a.visible else None)
    finally:
        (out/'resources-stop').touch()
        try:sampler.wait(timeout=8)
        except subprocess.TimeoutExpired:sampler.terminate();sampler.wait(5)
    result_file=out/'result.json'
    r=json.loads(result_file.read_text('utf8')) if result_file.exists() else {}
    resources=out/'resources-external.jsonl'
    if resources.exists():
        r['resources']=[json.loads(line) for line in resources.read_text('utf8').splitlines()]
        r['resource_sampling']='external process; no target GIL'
    r.update(exit_code=code,original_unchanged=a.project.read_bytes()==raw,
        original_sha256=hashlib.sha256(raw).hexdigest())
    result_file.write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str),'utf8')
    print(json.dumps({k:r.get(k) for k in ('exit_code','error','finished','gui_shutdown','operations','checks')},ensure_ascii=False))
    return 0 if code==0 and r.get('finished') and not r.get('error') and r.get('original_unchanged') else 1

if __name__=='__main__':raise SystemExit(main())
