"""Run the daily Studio entry with private cover data; never invokes ASR."""
import argparse,json,os,sys,time
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',type=Path);p.add_argument('--dpi',type=int,default=100)
    args=p.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp') or out.exists():raise ValueError('Use a new directory under workspace/tmp')
    out.mkdir(parents=True);fixture=out/'fixture.2byteproj';fixture.write_bytes(args.project.read_bytes())
    env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(out),LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),
        QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=str(args.dpi/100),QT_ENABLE_HIGHDPI_SCALING='0',QT_FONT_DPI='96',
        QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough',TWOBYTEASR_COVER_DPI=str(args.dpi),PYTHONIOENCODING='utf8',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='cover-gimp',TWOBYTEASR_STARTUP_PROJECT=str(fixture),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    for directory in ('local','roaming','temp'):(out/directory).mkdir(exist_ok=True)
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-X','utf8','-B',str(root/'quick_start.py')]
    sys.path.insert(0,str(root))
    from twobyteasr.processes import run_hidden_subprocess
    with (out/'application.log').open('wb') as log:
        result=run_hidden_subprocess(cmd,cwd=root,env=env,stdout=log,stderr=log,timeout=420,purpose='offline GIMP cover acceptance')
    deadline=time.monotonic()+360
    while not (out/'cover-gimp.json').exists() and time.monotonic()<deadline:time.sleep(.25)
    report=json.loads((out/'cover-gimp.json').read_text(encoding='utf8'))
    print(json.dumps(dict(passed=report['passed'],checks=len(report['checks']),error=report.get('error'),exit_code=result.returncode),ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
