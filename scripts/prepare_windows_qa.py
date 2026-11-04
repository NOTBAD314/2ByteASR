"""Prepare explicit, isolated Windows QA runtime/model inputs without relaxing TEST_ROOT.

The controller may use a development Python, but a product worker must execute a
runtime contained inside the QA root. Nothing writes real AppData or user projects.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''): h.update(block)
    return h.hexdigest()

def contained(path: Path, root: Path) -> bool:
    try: path.resolve().relative_to(root.resolve()); return True
    except ValueError: return False

def copy_input(source: Path, target: Path, root: Path) -> dict:
    source=source.resolve()
    if not source.is_dir(): raise ValueError(f'Input directory missing: {source}')
    if not contained(target,root): raise ValueError('Destination escapes QA root.')
    if target.exists(): raise ValueError('Refuse to overwrite a runtime/model; select a fresh QA root.')
    files=[p for p in source.rglob('*') if p.is_file() and not any(v in {'__pycache__','.pytest_cache'} for v in p.relative_to(source).parts)]
    if any(p.is_symlink() for p in source.rglob('*')): raise ValueError('Input contains symlinks; resolve their permitted scope explicitly.')
    size=sum(p.stat().st_size for p in files)
    if shutil.disk_usage(root).free < size + 2*1024**3: raise ValueError('Insufficient free space for isolated copy plus 2 GiB margin.')
    target.mkdir(parents=True)
    for p in files:
        dest=target/p.relative_to(source)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dest)
    return {'source':str(source),'destination':str(target),'files':len(files),'bytes':size,'downloaded':False,'installed_new_dependencies':False}

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--runtime-source',type=Path)
    parser.add_argument('--model-source',type=Path)
    parser.add_argument('--model-name',default='SenseVoiceSmall')
    args=parser.parse_args()
    root=args.output.resolve()
    if 'tmp' not in {part.casefold() for part in root.parts}:
        raise ValueError('QA output must be inside an explicitly named tmp directory, matching TEST_ROOT policy.')
    root.mkdir(parents=True,exist_ok=True)
    receipt_path=root/'qa-environment.json'
    if receipt_path.exists(): raise ValueError('Refuse to overwrite an environment receipt; choose a fresh output.')
    runtime=root/'local'/'2ByteASR'/'runtimes'/'main'
    model=root/'models'/args.model_name
    if Path(args.model_name).name != args.model_name or args.model_name in {'.','..'}: raise ValueError('Model name must be one directory name.')
    receipt={'platform':sys.platform,'root':str(root),'controller_python':sys.executable,'copies':[],'checks':[],'passed':False}
    if args.runtime_source:
        if not (args.runtime_source/'Scripts'/'python.exe').is_file() or not (args.runtime_source/'pyvenv.cfg').is_file():
            raise ValueError('Runtime source must be an existing Windows Python venv, not a repository or user-data tree.')
        receipt['copies'].append(copy_input(args.runtime_source,runtime,root))
    if args.model_source: receipt['copies'].append(copy_input(args.model_source,model,root))
    python=runtime/'Scripts'/'python.exe'
    receipt['checks'].append({'name':'runtime_inside_test_root','passed':contained(python,root) and python.is_file(),'path':str(python)})
    receipt['checks'].append({'name':'model_inside_test_root','passed':contained(model,root) and model.is_dir(),'path':str(model)})
    if args.model_name=='SenseVoiceSmall':
        required=('model.pt','config.yaml','configuration.json','am.mvn','chn_jpn_yue_eng_ko_spectok.bpe.model')
        receipt['checks'].append({'name':'sensevoice_required_files','passed':all((model/name).is_file() and (model/name).stat().st_size>0 for name in required),'required_files':list(required)})
        if all((model/name).is_file() for name in required):
            receipt['model_sha256']={name:sha(model/name) for name in required}
    env=dict(os.environ)
    for key in tuple(env):
        if key.endswith(('_API_KEY','_ACCESS_TOKEN','_AUTH_TOKEN')): env.pop(key,None)
    env.update({'TWOBYTEASR_TEST_ROOT':str(root),'TWOBYTEASR_MAIN_PYTHON':str(python),'LOCALAPPDATA':str(root/'local'),'APPDATA':str(root/'roaming'),'USERPROFILE':str(root/'profile'),'TEMP':str(root/'temp'),'TMP':str(root/'temp'),'HF_HOME':str(root/'hf-cache'),'HUGGINGFACE_HUB_CACHE':str(root/'hf-cache'/'hub'),'MODELSCOPE_CACHE':str(root/'modelscope-cache'),'TORCH_HOME':str(root/'torch-cache'),'2BYTEASR_MODEL_ROOT':str(root/'models'),'QT_QPA_PLATFORM':'offscreen','PYTHONNOUSERSITE':'1'})
    for path in [root/'roaming',root/'profile',root/'temp',root/'hf-cache',root/'modelscope-cache',root/'torch-cache']:
        path.mkdir(parents=True,exist_ok=True)
    if python.is_file():
        result=subprocess.run([str(python),'-c','import json,sys,torch,funasr; print(json.dumps({"python":sys.version.split()[0],"torch":torch.__version__,"funasr":funasr.__version__}))'],cwd=root,env=env,capture_output=True,timeout=90)
        receipt['checks'].append({'name':'isolated_model_dependencies_import','passed':result.returncode==0,'returncode':result.returncode,'stdout':result.stdout.decode('utf-8',errors='replace'),'stderr_tail':result.stderr.decode('utf-8',errors='replace')[-1500:]})
        receipt['runtime_python_sha256']=sha(python)
    receipt['launch_environment']={key:env[key] for key in ['TWOBYTEASR_TEST_ROOT','TWOBYTEASR_MAIN_PYTHON','LOCALAPPDATA','APPDATA','USERPROFILE','TEMP','TMP','HF_HOME','HUGGINGFACE_HUB_CACHE','MODELSCOPE_CACHE','TORCH_HOME','2BYTEASR_MODEL_ROOT','PYTHONNOUSERSITE']}
    receipt['esbuild_note']='Fresh Node/esbuild bundling needs the explicit child-process permission used by the QA controller; this script does not run the product as administrator or change OS policy.'
    receipt['scope']='Dependency preparation/import checks only; actual model inference and frozen EXE UI flow have separate receipts.'
    receipt['passed']=all(c['passed'] for c in receipt['checks'])
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'receipt':str(receipt_path),'passed':receipt['passed'],'checks':receipt['checks']},ensure_ascii=False))
    return 0 if receipt['passed'] else 1

if __name__=='__main__': raise SystemExit(main())
