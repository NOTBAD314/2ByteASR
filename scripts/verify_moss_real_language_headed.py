"""Normal source/frozen UI over an explicitly provided real project, isolated copies only."""
from pathlib import Path
import argparse,copy,json,os,sys


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--project',required=True,type=Path);parser.add_argument('--mode',choices=['review','recovered'],required=True)
    parser.add_argument('--exe',type=Path);args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):raise ValueError('Use a fresh owned tmp directory')
    from twobyteasr.runtime_paths import get_runtime_paths
    from twobyteasr.system.runtime_registry import resolve_runtime_python
    installed=get_runtime_paths();model_root=installed.model_root;runtime_root=installed.runtime_root
    runtime_python=resolve_runtime_python('main',register=False)
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import load_project,save_project
    project=load_project(args.project);save_project(project,out/'fixture.2byteproj')
    from twobyteasr.storage.settings import DEFAULT_SETTINGS,project_settings_path
    settings=copy.deepcopy(DEFAULT_SETTINGS)
    settings['models'].update(primary_asr_backend='qwen_local',firered_asr_backend='qwen_aligner',qwen_asr_backend='off')
    settings['switches'].update(enable_ai_polish=False,use_ai_grouping=False,unified_glm_processing=False)
    cfg=project_settings_path();cfg.parent.mkdir(parents=True,exist_ok=True);cfg.write_text(json.dumps(settings),'utf8')
    env=dict(os.environ,TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',TWOBYTEASR_ACCEPTANCE_SCENARIO='moss-real-language',TWOBYTEASR_REAL_LANGUAGE_MODE=args.mode,
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',
        PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=root.as_posix())
    env['2BYTEASR_MODEL_ROOT']=str(model_root)
    env['2BYTEASR_RUNTIME_ROOT']=str(runtime_root)
    env['TWOBYTEASR_MAIN_PYTHON']=str(runtime_python)
    env['2BYTEASR_QWEN3_ASR_DIR']=str(model_root/'Qwen3-ASR-1.7B');env['2BYTEASR_QWEN3_ALIGNER_DIR']=str(model_root/'Qwen3-ForcedAligner-0.6B')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=190)
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').is_file() else {}
    result['process_exit']=code;(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result.get('passed'),checks=len(result.get('checks',[])),phase=result.get('phase'),exit=code,error=result.get('error','')[-1600:]),ensure_ascii=False))
    return 0 if result.get('passed') and result.get('gui_shutdown') and code==0 else 1

if __name__=='__main__':raise SystemExit(main())
