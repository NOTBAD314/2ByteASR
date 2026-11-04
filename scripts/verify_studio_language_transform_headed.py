"""Normal Studio entry, private desktop, owned project and twelve-second export."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--media',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args();out=args.output.resolve();media=args.media.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp') or not media.is_relative_to(root/'tmp'):
        parser.error('fresh output and media in repository tmp required')
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    entry=save_project(SubtitleProject(media=StudioMedia('',duration_ms=0)),out/'entry.2byteproj')
    env=os.environ.copy();env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='studio-language-transform',TWOBYTEASR_STARTUP_PROJECT=str(entry),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_REPAIR_MEDIA=str(media),TWOBYTEASR_REPAIR_FIXTURE_ROOT=str(root),QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=600)
    path=out/'result.json';result=json.loads(path.read_text('utf8')) if path.is_file() else {}
    print(json.dumps(dict(exit_code=code,passed=result.get('passed'),checks=len(result.get('checks',[])),
        failures=[row for row in result.get('checks',[]) if not row['passed']],error=result.get('error'),output=str(out)),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') and result.get('gui_shutdown') else 1


if __name__=='__main__':raise SystemExit(main())
