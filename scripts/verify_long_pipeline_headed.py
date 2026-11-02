"""Audit long-pipeline progress in the normal isolated source or frozen UI."""
import argparse,json,os,sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];output=args.output.resolve()
    if output.exists() or not output.is_relative_to(root/'tmp'):
        raise ValueError('Use a new output under this source/tmp')
    output.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(output)
    sys.path.insert(0,str(root))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    project=save_project(SubtitleProject(media=StudioMedia(path='',duration_ms=0)),output/'fixture.2byteproj')
    env=dict(os.environ,TWOBYTEASR_ACCEPTANCE_SCENARIO='long-pipeline-progress',
        TWOBYTEASR_ACCEPTANCE_DIR=str(output),TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='0',TWOBYTEASR_STARTUP_SIZE='1400x880',
        TWOBYTEASR_STARTUP_TRACE=str(output/'startup.jsonl'),TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1',
        QT_QPA_PLATFORM='windows',PYTHONUTF8='1',HF_HUB_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=output/'process',timeout=180)
    path=output/'result.json';result=json.loads(path.read_text('utf8')) if path.exists() else dict(passed=False)
    result['process_exit']=code;result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
