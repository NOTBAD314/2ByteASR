"""Measure original/translation/list/timeline first paint on a real 1392-cue copy."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profile',action='store_true')
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--expected-gui-sha256')
    parser.add_argument('--cue-count',type=int,default=1392)
    args=parser.parse_args();out=args.output.resolve()
    if args.exe and (not args.exe.is_file() or args.baseline):parser.error('existing EXE with no source overrides required')
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):parser.error('use a fresh tmp output')
    out.mkdir(parents=True)
    original=args.project.read_bytes();payload=json.loads(original.decode('utf-8-sig'))
    payload.setdefault('studio_state',{}).update(playhead_ms=29591,last_selected_cue='6',scroll_ms=0,zoom=55)
    for name in ('project.2byteproj','alternate.2byteproj'):
        (out/name).write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),'utf8')
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-first-display',TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_SIZE='1600x950',
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        QT_QPA_PLATFORM='windows',PYTHONUTF8='1',PYTHONFAULTHANDLER='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    env['CAPTION_FIRST_PROFILE']=str(int(args.profile))
    env['CAPTION_FIRST_CUE_COUNT']=str(args.cue_count)
    if args.exe:
        env['CAPTION_FIRST_EXPECT_FROZEN']='1'
        env['CAPTION_FIRST_EXPECT_GUI_SHA256']=args.expected_gui_sha256 or hashlib.sha256(args.exe.read_bytes()).hexdigest()
    entry=ROOT/'quick_start.py'
    if args.baseline:
        modules={}
        for file in (args.baseline/'twobyteasr').rglob('*.py'):
            rel=file.relative_to(args.baseline);current=ROOT/rel
            if 'acceptance' not in rel.parts and current.is_file() and file.read_bytes().replace(b'\r\n',b'\n')!=current.read_bytes().replace(b'\r\n',b'\n'):
                modules['.'.join(rel.with_suffix('').parts)]=str(file.resolve())
        entry=out/'entry.py'
        entry.write_text('import sys,importlib.abc,importlib.util,runpy\n'+
            'sys.path.insert(0,'+repr(str(ROOT))+')\nmodules='+repr(modules)+'\n'+
            'class Before(importlib.abc.MetaPathFinder):\n def find_spec(self,name,path=None,target=None):\n'+
            '  if name in modules:return importlib.util.spec_from_file_location(name,modules[name])\n'+
            'sys.meta_path.insert(0,Before())\nrunpy.run_path('+repr(str(ROOT/'quick_start.py'))+',run_name="__main__")\n','utf8')
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE'):env.pop(key,None)
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(entry)]
    code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=150)
    result={};deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        try:
            result=json.loads((out/'caption-first-display.json').read_text('utf8'))
            if result.get('normal_shutdown'):break
        except (OSError,ValueError):pass
        if code not in (0,259):break
        time.sleep(.2)
    result.update(exit_code=code,source_unchanged=args.project.read_bytes()==original,input_sha256=hashlib.sha256(original).hexdigest())
    (out/'caption-first-display.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    summary={k:result.get(k) for k in ('passed','exit_code','normal_shutdown','errors')}
    summary['rounds']=[{k:v for k,v in row.items() if k not in ('readiness','open_profile')} for row in result.get('rounds',())]
    print(json.dumps(summary,ensure_ascii=False,default=str))
    return 0 if result.get('passed') and result.get('normal_shutdown') and code==0 and result['source_unchanged'] else 1
if __name__=='__main__':raise SystemExit(main())
