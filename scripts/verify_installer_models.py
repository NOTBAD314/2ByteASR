"""Launch source/frozen production GUI in a private Windows QA desktop/profile."""
import argparse
import json
import os
from pathlib import Path
import sys
import shutil


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--models',default='sensevoice')
    parser.add_argument('--cpu',action='store_true')
    parser.add_argument('--scale',default='')
    parser.add_argument('--ui',action='store_true')
    parser.add_argument('--native-ui',action='store_true')
    parser.add_argument('--project',action='store_true')
    parser.add_argument('--audio',type=Path)
    parser.add_argument('--model-root',type=Path)
    parser.add_argument('--cancel-retry',action='store_true')
    parser.add_argument('--diagnostic-only',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('QA output must stay in repo tmp')
    out.mkdir(parents=True,exist_ok=True)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    if args.model_root:
        selected=args.model_root.resolve()
        if not selected.is_relative_to(out):raise ValueError('Custom QA model directory must stay in output root')
        os.environ['2BYTEASR_MODEL_ROOT']=str(selected)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.studio_project import SubtitleProject,StudioMedia,save_project
    project=out/'empty.2byteproj'
    if not project.is_file():save_project(SubtitleProject(media=StudioMedia(path='')),project)
    (out/'installer-qa.json').write_text(json.dumps(dict(models=args.models.split(','),source='AUTO',timeout_s=7200,ui_only=args.ui,native_ui=args.native_ui,project_only=args.project,cancel_retry=args.cancel_retry,diagnostic_only=args.diagnostic_only)),'utf8')
    if args.audio:
        shutil.copy2(args.audio.resolve(),out/'sample.wav')
    env=os.environ.copy()
    # Windows env block may contain Path/PATH variants; retain exactly one.
    for key in list(env):
        if key.casefold() in {'path','pythonpath','pythonhome'} or key.startswith('TWOBYTEASR_') and key.endswith('_PYTHON'):
            env.pop(key,None)
    system_root=os.environ.get('SystemRoot',r'C:\Windows')
    env['Path']=os.pathsep.join([system_root,str(Path(system_root)/'System32')])
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='installer-model-qa',
               TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               QT_QPA_PLATFORM='windows',PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
    if args.cpu:env['2BYTEASR_CPU_ONLY']='1'
    if args.scale:env['QT_SCALE_FACTOR']=args.scale
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    if args.native_ui:
        import subprocess
        with (out/'native-process.log').open('w',encoding='utf8') as log:
            exit_code=subprocess.run(cmd,cwd=root,env=env,stdout=log,stderr=log,
                timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
    else:
        from isolated_windows_desktop import run_on_desktop
        exit_code=run_on_desktop(cmd,cwd=root,env=env,output=out/'process',timeout=28800)
    print(json.dumps(dict(output=str(out),exit_code=exit_code)))


if __name__=='__main__':main()
