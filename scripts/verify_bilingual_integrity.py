"""Real quick_start/EXE, private Windows desktop, isolated profile."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--project',type=Path);parser.add_argument('--scale',type=float,default=1.)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('Fresh source/tmp output required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    save_project(SubtitleProject(StudioMedia('')),out/'startup.2byteproj')
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(args.scale),QT_AUTO_SCREEN_SCALE_FACTOR='0',
        TWOBYTEASR_ACCEPTANCE_SCENARIO='bilingual-integrity',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'startup.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='0',
        TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    if args.project:env['BILINGUAL_AUDIT_PROJECT']=str(args.project.resolve())
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=240,receipt=out/'result.json')
    (out/'exit.json').write_text(json.dumps({'exit_code':code}),'utf-8')
    result=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else {}
    print(json.dumps({'passed':result.get('passed'),'checks':len(result.get('checks',[])),'exit':code,'error':result.get('error')},ensure_ascii=False))
    return code or (0 if result.get('passed') else 1)
if __name__=='__main__':raise SystemExit(main())
