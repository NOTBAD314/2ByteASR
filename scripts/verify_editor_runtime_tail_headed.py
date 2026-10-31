"""Copied real project, normal source/frozen entry, continuous native Qt input."""
import argparse,hashlib,json,os,sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    ap=argparse.ArgumentParser();ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--baseline-source',type=Path)
    ap.add_argument('--exe',type=Path);ap.add_argument('--theme',default='warm');ap.add_argument('--scale-factor',default='0.5714285714')
    args=ap.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):ap.error('Use a fresh source/tmp output')
    out.mkdir(parents=True);digest=hashlib.sha256(args.project.read_bytes()).hexdigest()
    payload=json.loads(args.project.read_text('utf-8-sig'));payload.pop('autosave',None)
    payload['report_path']=str(out/'reports')
    project=out/'project.2byteproj';project.write_text(json.dumps(payload,ensure_ascii=False),'utf8')
    (out/'input.json').write_text(json.dumps(dict(theme=args.theme,baseline=bool(args.baseline_source),
        project=str(project),source=str(args.project.resolve()),sha256=digest),ensure_ascii=False),'utf8')
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='editor-runtime-tail',TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_STARTUP_SIZE='1840x1050',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale_factor,PYTHONUTF8='1',PYTHONFAULTHANDLER='1')
    if args.baseline_source:env['FOUR_FIXES_BASELINE_SOURCE']=str(args.baseline_source.resolve())
    from isolated_windows_desktop import run_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'scripts/editor_runtime_tail_entry.py')]
    code=run_on_desktop(cmd,cwd=root,env=env,output=out/'process',timeout=420)
    file=out/'result.json';r=json.loads(file.read_text('utf8')) if file.exists() else {}
    r.update(exit_code=code,input_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==digest)
    r['passed']=bool(r.get('passed') and r.get('gui_shutdown') and code==0 and r['input_unchanged'])
    file.write_text(json.dumps(r,ensure_ascii=False,indent=2),'utf8');print(json.dumps({k:v for k,v in r.items() if k!='views'},ensure_ascii=False))
    return 0 if r['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
