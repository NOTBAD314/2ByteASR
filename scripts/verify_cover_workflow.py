"""Launch the normal Studio source/EXE entry for isolated cover acceptance."""
import argparse,json,os,sys,time,shutil
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);parser.add_argument('--dpi',type=int,default=100)
    parser.add_argument('--recover-from',type=Path)
    parser.add_argument('--studio-regression',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Use a new folder under workspace/tmp')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out);sys.path.insert(0,str(root))
    from twobyteasr.studio_project import SubtitleProject
    project=SubtitleProject.from_dict(json.loads(args.project.read_text(encoding='utf-8-sig')))
    fixture=out/'fixture.2byteproj';fixture.write_text(json.dumps(project.to_dict(),ensure_ascii=False,indent=2),encoding='utf8')
    if args.recover_from:
        previous=args.recover_from.resolve()
        if not previous.is_relative_to(root/'tmp'):raise ValueError('Recovery fixture must be under workspace/tmp')
        shutil.copytree(previous/'config'/'cover-workspace',out/'config'/'cover-workspace')
    env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(out),LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(args.dpi/100),QT_ENABLE_HIGHDPI_SCALING='0',QT_FONT_DPI='96',QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough',TWOBYTEASR_COVER_DPI=str(args.dpi),PYTHONIOENCODING='utf8',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='cover-workflow',TWOBYTEASR_STARTUP_PROJECT=str(fixture),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    env['TWOBYTEASR_COVER_RECOVERY']='1' if args.recover_from else '0'
    env['TWOBYTEASR_COVER_STUDIO_REGRESSION']='1' if args.studio_regression else '0'
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-X','utf8','-B',str(root/'quick_start.py')]
    from twobyteasr.processes import run_hidden_subprocess
    with (out/'application.log').open('wb') as log:
        result=run_hidden_subprocess(cmd,cwd=root,env=env,stdout=log,stderr=log,timeout=480,purpose='isolated cover Photopea workflow acceptance')
    # The daily root launcher is asynchronous. Wait for its actual child receipt.
    deadline=time.monotonic()+420
    while not (out/'cover-workflow.json').is_file() and time.monotonic()<deadline:time.sleep(.25)
    report=json.loads((out/'cover-workflow.json').read_text(encoding='utf8'))
    print(json.dumps(dict(passed=report['passed'],checks=len(report['checks']),error=report.get('error'),exit_code=result.returncode),ensure_ascii=False))
    return 0 if report['passed'] and result.returncode==0 else 1


if __name__=='__main__':raise SystemExit(main())
