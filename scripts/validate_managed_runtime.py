"""Executed by the candidate interpreter before its registry pointer is published."""
import argparse
from importlib import metadata
import json
from pathlib import Path
import sys


def validate(identity, managed):
    problems=[]
    if not Path(sys.base_prefix).resolve().is_relative_to((managed/'python').resolve()):
        problems.append('基础 Python 不在应用管理目录')
    if not Path(sys.prefix).resolve().is_relative_to((managed/identity['role']).resolve()):
        problems.append('环境不在指定角色目录')
    actual='.'.join(map(str,sys.version_info[:3]))
    if actual != identity['python']: problems.append('Python '+actual+' != '+identity['python'])
    expected=dict(identity['packages'])
    if identity['torch']:
        expected.update(torch=identity['torch']+'+'+identity['tag'],torchaudio=identity['torch']+'+'+identity['tag'])
    for name, version in expected.items():
        try: installed=metadata.version(name.split('[')[0])
        except metadata.PackageNotFoundError: installed='missing'
        if installed!=version: problems.append(name+': '+installed+' != '+version)
    imports=['requests']
    if identity['torch']: imports+=['numpy','torch','torchaudio','transformers','soundfile']
    if set(identity['models']) & {'qwen_asr','qwen_aligner'}:
        sys.path.append(str(Path(__file__).resolve().parents[1]))
        from twobyteasr.recognition.qwen_runtime_compat import prepare_qwen_import
        prepare_qwen_import()
        imports+=['qwen_asr']
    for name in imports:
        try: __import__(name)
        except Exception as exc: problems.append(name+': '+str(exc))
    print(json.dumps(dict(interpreter=sys.executable,base=sys.base_prefix,prefix=sys.prefix,
        role=identity['role'],packages_checked=len(expected),imports=imports,problems=problems),ensure_ascii=False),flush=True)
    return not problems


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--managed',type=Path,required=True)
    parser.add_argument('--identity',required=True);args=parser.parse_args()
    raise SystemExit(0 if validate(json.loads(args.identity),args.managed) else 1)
