"""Run real MOSS scheduling from source or a rebuilt EXE, without user writes."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--pipeline', action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    output=args.output.resolve()
    if not output.is_relative_to(root/'tmp') or output.exists():
        raise ValueError('Choose a NEW output under workspace tmp.')
    output.mkdir(parents=True)
    profile=output/'profile'
    # Existing audit isolation requires model/runtime paths INSIDE its boundary.
    # Reuse read-only weights by hardlink and dependencies via .pth; no installs.
    model_records=[]
    for model_name in ('MOSS-Transcribe-Diarize','FireRedVAD','FireRedASR2-AED','Qwen3-ASR-1.7B','spkrec-ecapa-voxceleb'):
        source=root/'models'/model_name
        for item in source.rglob('*'):
            if not item.is_file() or '__pycache__' in item.parts or '.cache' in item.parts:continue
            target=profile/'models'/model_name/item.relative_to(source)
            target.parent.mkdir(parents=True,exist_ok=True)
            if item.stat().st_size>1024*1024:
                os.link(item,target)
            else:shutil.copyfile(item,target)
            model_records.append(dict(source=str(item),target=str(target),bytes=item.stat().st_size))
    for role in ('main','moss'):
        original=root/('.venv-'+role)
        runtime=profile/('runtime-'+role)
        (runtime/'Scripts').mkdir(parents=True)
        (runtime/'Lib/site-packages').mkdir(parents=True)
        shutil.copyfile(original/'pyvenv.cfg',runtime/'pyvenv.cfg')
        for name in ('python.exe','pythonw.exe'):
            if (original/'Scripts'/name).is_file():shutil.copyfile(original/'Scripts'/name,runtime/'Scripts'/name)
        (runtime/'Lib/site-packages/audit-dependencies.pth').write_text(
            'import site; site.addsitedir('+repr(str(original/'Lib/site-packages'))+')\n','utf8')
    (output/'read-only-reuse.json').write_text(json.dumps(model_records,indent=2),'utf8')
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(output/'profile'),
        TWOBYTEASR_STARTUP_TRACE=str(output/'startup.jsonl'),
        TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_MAIN_PYTHON=str(profile/'runtime-main/Scripts/python.exe'),
        TWOBYTEASR_MOSS_PYTHON=str(profile/'runtime-moss/Scripts/python.exe'),
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    env['2BYTEASR_MODEL_ROOT']=str(profile/'models')
    env['2BYTEASR_USER_DATA_ROOT']=str(output/'profile')
    audio=args.audio.resolve()
    if args.pipeline:
        target=output/audio.name
        shutil.copyfile(audio,target)
        audio=target
    spec=output/'spec.json'
    spec.write_text(json.dumps(dict(audio=str(audio),output=str(output),pipeline=args.pipeline)), 'utf8')
    command=([str(args.exe.resolve())] if args.exe else [sys.executable,str(root/'quick_start.py')])
    command+=['--moss-full-context-audit',str(spec)]
    with (output/'launcher.log').open('wb') as stream:
        completed=subprocess.run(command,cwd=root,env=env,stdout=stream,stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    print(json.dumps(dict(output=str(output),returncode=completed.returncode),ensure_ascii=False))
    return completed.returncode


if __name__=='__main__':raise SystemExit(main())
