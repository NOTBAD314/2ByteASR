"""Isolated normal-entry settings, translation, usage and insertion audit."""
import argparse,json,os,sys
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--long-media',type=Path,required=True)
    parser.add_argument('--scenario',choices=('feedback-workflow','speaker-name-render'),default='feedback-workflow')
    args=parser.parse_args();out=args.output.resolve()
    if out.exists():parser.error('Use a fresh output directory')
    if 'tmp' not in out.parts:parser.error('Acceptance output must be in a tmp directory')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    entry=out/'entry.2byteproj';save_project(SubtitleProject(StudioMedia('')),entry)
    env=os.environ.copy();env.update(QT_QPA_PLATFORM='windows',PYTHONUTF8='1',
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO=args.scenario,
        TWOBYTEASR_STARTUP_PROJECT=str(entry),TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_FEEDBACK_FIXTURES=str(args.fixtures.resolve()),
        TWOBYTEASR_FEEDBACK_LONG_MEDIA=str(args.long_media.resolve()))
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=420)
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').is_file() else {}
    passed=code==0 and result.get('passed') and result.get('gui_shutdown')
    print(json.dumps(dict(passed=bool(passed),exit_code=code,checks=len(result.get('checks',[])),error=result.get('error'),output=str(out)),ensure_ascii=True))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
