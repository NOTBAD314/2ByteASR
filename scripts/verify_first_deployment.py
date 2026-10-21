"""Launch the real first-use GUI with independent empty runtime/model caches."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--source',choices=('AUTO','MODELSCOPE'),default='AUTO')
    parser.add_argument('--ui-only',action='store_true')
    parser.add_argument('--physical-relay',default='')
    parser.add_argument('--timeout',type=int,default=10800)
    parser.add_argument('--mode',choices=('fresh','resume','restart','repair','diagnostic'),default='fresh')
    parser.add_argument('--label',default='')
    parser.add_argument('--interrupt-at-bytes',type=int,default=0)
    parser.add_argument('--foreign-environment',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    workspace=(args.workspace or root).resolve()
    out=args.output.resolve()
    if not out.is_relative_to(workspace/'tmp') or (out.exists() if args.mode=='fresh' else not out.is_dir()):
        raise ValueError('Fresh mode requires a new workspace/tmp output; recovery requires an existing owned output')
    out.mkdir(parents=True,exist_ok=True)
    label=args.label or args.mode
    if (out/'evidence'/label).exists():raise ValueError('Choose a new evidence label')
    sys.path.insert(0,str(root))
    os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project
    project=out/'empty.2byteproj'
    if args.mode=='fresh':
        save_project(SubtitleProject(media=StudioMedia(path='')),project)
        shutil.copy2(root/'assets/diagnostics/speech_en.wav',out/'sample.wav')
    (out/'first-deployment.json').write_text(json.dumps(dict(source=args.source,timeout_s=args.timeout,
        ui_only=args.ui_only,label=label,mode=args.mode,interrupt_at_bytes=args.interrupt_at_bytes)),'utf8')
    env=os.environ.copy()
    for key in tuple(env):
        if (key.upper() in {'PATH','PYTHONHOME','PYTHONPATH','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'}
                or key.startswith('TWOBYTEASR_') and key.endswith('_PYTHON')):
            env.pop(key,None)
    windows=Path(os.environ.get('SystemRoot',r'C:\Windows'))
    env['PATH']=os.pathsep.join((str(windows),str(windows/'System32')))
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='first-deployment',
               TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_INVOKER_CWD=str(workspace),
               QT_QPA_PLATFORM='windows',PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    env.pop('TWOBYTEASR_SKIP_FIRST_RUN_WIZARD',None)
    env.pop('TWOBYTEASR_STARTUP_OPEN_STUDIO',None)
    if args.physical_relay:
        env.update(HTTP_PROXY=args.physical_relay,HTTPS_PROXY=args.physical_relay,NO_PROXY='localhost,127.0.0.1')
    if args.foreign_environment:
        foreign=out/'foreign-python-conda'
        foreign.mkdir(exist_ok=True)
        (foreign/'sitecustomize.py').write_text("raise RuntimeError('Foreign Python injection must not run')\n",'utf8')
        env.update(PYTHONHOME=str(foreign),PYTHONPATH=str(foreign),CONDA_PREFIX=str(foreign),
                   CONDA_DEFAULT_ENV='unrelated-environment',VIRTUAL_ENV=str(foreign),
                   UV_PYTHON=str(foreign/'python.exe'),PIP_CONFIG_FILE=str(foreign/'pip.ini'),
                   TWOBYTEASR_MAIN_PYTHON=str(foreign/'python.exe'),
                   TWOBYTEASR_MOSS_PYTHON=str(foreign/'python.exe'))
        env['PATH']=str(foreign)+os.pathsep+env['PATH']
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    (out/(label+'-launch.json')).write_text(json.dumps(dict(command=command,source=args.source,workspace=str(workspace),
        condition='physical-NIC relay' if args.physical_relay else 'current host route',
        runtime_cache_initially_empty=args.mode=='fresh',model_cache_initially_empty=args.mode=='fresh',
        foreign_environment=args.foreign_environment),ensure_ascii=False,indent=2),'utf8')
    code=run_on_desktop(command,cwd=workspace,env=env,output=out/('process-'+label),timeout=args.timeout+90)
    result=out/'evidence'/label/'result.json'
    proof=json.loads(result.read_text('utf8')) if result.exists() else {'error':'audit did not finish'}
    print(json.dumps(dict(exit_code=code,passed=proof.get('passed',False),error=proof.get('error'),output=str(out)),ensure_ascii=False))
    return 0 if code==0 and proof.get('passed') else 1


if __name__=='__main__':raise SystemExit(main())
