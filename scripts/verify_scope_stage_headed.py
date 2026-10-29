"""Same-window real-project scope/gesture/retry audit on an owned Windows desktop."""
import argparse,hashlib,json,os,sys,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--baseline',type=Path)
    p.add_argument('--large',type=int,default=0);p.add_argument('--skip-retry',action='store_true')
    p.add_argument('--profile',action='store_true')
    p.add_argument('--retry-only',action='store_true')
    p.add_argument('--cases',default='21,speaker,all')
    p.add_argument('--exe',type=Path)
    p.add_argument('--expected-gui-sha256')
    a=p.parse_args();out=a.output.resolve()
    if a.exe and (not a.exe.is_file() or a.baseline):p.error('Existing EXE with no external source override required')
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):p.error('fresh tmp output required')
    out.mkdir(parents=True);data=a.project.read_bytes();(out/'project.2byteproj').write_bytes(data)
    shutil.copy2(a.report,out/'report.json')
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='scope-stage-retry',TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_SIZE='1600x950',TWOBYTEASR_INVOKER_CWD=str(ROOT),
        QT_QPA_PLATFORM='windows',PYTHONUTF8='1',SCOPE_AUDIT_LARGE=str(a.large),SCOPE_AUDIT_SKIP_RETRY=str(int(a.skip_retry)),
        SCOPE_AUDIT_PROFILE=str(int(a.profile)),
        SCOPE_AUDIT_RETRY_ONLY=str(int(a.retry_only)),
        SCOPE_AUDIT_CASES=a.cases,
        HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9',NO_PROXY='127.0.0.1,localhost')
    entry=ROOT/'quick_start.py'
    if a.exe:
        env['SCOPE_AUDIT_EXPECT_FROZEN']='1'
        env['SCOPE_AUDIT_EXPECT_GUI_SHA256']=a.expected_gui_sha256 or hashlib.sha256(a.exe.read_bytes()).hexdigest()
    if a.baseline:
        modules={}
        for file in (a.baseline/'twobyteasr').rglob('*.py'):
            rel=file.relative_to(a.baseline);current=ROOT/rel
            if 'acceptance' not in rel.parts and current.is_file() and file.read_bytes().replace(b'\r\n',b'\n')!=current.read_bytes().replace(b'\r\n',b'\n'):
                modules['.'.join(rel.with_suffix('').parts)]=str(file.resolve())
        entry=out/'entry.py'
        entry.write_text('import sys,importlib.abc,importlib.util,runpy\n'+
            'sys.path.insert(0,'+repr(str(ROOT))+')\nmodules='+repr(modules)+'\n'+
            'class Before(importlib.abc.MetaPathFinder):\n def find_spec(self,name,path=None,target=None):\n'+
            '  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'+
            'sys.meta_path.insert(0,Before())\nrunpy.run_path('+repr(str(ROOT/'quick_start.py'))+',run_name="__main__")\n','utf8')
    from isolated_windows_desktop import run_on_desktop
    command=[str(a.exe.resolve())] if a.exe else [sys.executable,'-B',str(entry)]
    code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=300)
    receipt=out/'result.json';result={};deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        try:
            result=json.loads(receipt.read_text('utf8'))
            if result.get('gui_shutdown'):break
        except (OSError,ValueError):pass
        time.sleep(.2)
    import psutil
    if result.get('pid') and psutil.pid_exists(result['pid']):
        try:result['child_exit']=psutil.Process(result['pid']).wait(timeout=25)
        except psutil.NoSuchProcess:pass
        except psutil.TimeoutExpired:result['error']='Owned audit GUI did not exit after normal close'
    result.update(exit_code=code,original_unchanged=a.project.read_bytes()==data,original_sha256=hashlib.sha256(data).hexdigest())
    if a.exe:
        result['passed']=bool(result.get('passed') and result.get('frozen') and result.get('gui_sha256')==env['SCOPE_AUDIT_EXPECT_GUI_SHA256'] and result.get('child_exit',0)==0)
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','exit_code','error','original_unchanged')},ensure_ascii=False))
    return 0 if code==0 and result.get('passed') and result.get('gui_shutdown') else 1
if __name__=='__main__':raise SystemExit(main())
