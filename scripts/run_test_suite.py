"""Complete, per-file Qt regression run. Never stops after N failures."""
import argparse
import datetime
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import psutil

ROOT=Path(__file__).resolve().parents[1]


def stop_test_process(child):
    """Bound cleanup even when Windows taskkill cannot open a test process."""
    descendants = []
    try:
        descendants = psutil.Process(child.pid).children(recursive=True)
    except psutil.Error:
        pass
    for process in reversed(descendants):
        try:
            process.kill()
        except psutil.Error:
            continue
    try:
        child.kill()
        return child.wait(timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return child.poll()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    parser.add_argument('--timeout',type=int,default=300)
    parser.add_argument('--files',nargs='+')
    args=parser.parse_args()
    out=(args.output or ROOT/'tmp'/('tests-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))).resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():raise ValueError('fresh repository tmp directory required')
    out.mkdir(parents=True)
    env=os.environ.copy()
    # PowerShell 7's module path is not valid for tests launching Windows
    # PowerShell 5.1. Let that shell construct its own standard module path.
    for name in list(env):
        if name.upper()=='PSMODULEPATH':env.pop(name)
    for name in list(env):
        if name.endswith(('_API_KEY','_ACCESS_TOKEN','_REFRESH_TOKEN')):env.pop(name)
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',QT_QPA_PLATFORM='offscreen',DASHSCOPE_API_KEY='sk-local-test-dummy',
        LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),TEMP=str(out/'temp'),TMP=str(out/'temp'))
    (out/'temp').mkdir()
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    result={'files':[],'checks':[],'counts':dict(passed=0,failed=0,errors=0,skipped=0),'out':str(out)}
    files=args.files or sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'tests').glob('test_*.py'))
    sys.path.insert(0,str(ROOT))
    from twobyteasr.diagnostics.build_identity import source_snapshot_sha256
    def identity():
        source_sha,source_count=source_snapshot_sha256(ROOT)
        digest=hashlib.sha256()
        discovered=files if args.files else sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'tests').glob('test_*.py'))
        inputs=sorted({file.split('::',1)[0] for file in discovered}
            |{path.relative_to(ROOT).as_posix() for path in (ROOT/'tests').rglob('*.py')}
            |{path.relative_to(ROOT).as_posix() for path in (ROOT/'tests'/'fixtures').rglob('*') if path.is_file()}
            |{'scripts/run_test_suite.py','scripts/isolated_pytest.py'})
        for name in inputs:
            digest.update(name.encode('utf8'));digest.update(b'\0')
            path=ROOT/name
            digest.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b'MISSING')
        if (ROOT/'.git').exists():
            head=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,creationflags=flags).stdout.strip()
        else:
            marker=ROOT/'frozen-commit.txt'
            head=marker.read_text('ascii').strip() if marker.is_file() else ''
        if not re.fullmatch(r'[0-9a-f]{40}', head):
            head=''
        return dict(head=head,source_sha256=source_sha,source_inputs=source_count,
                    test_inputs_sha256=digest.hexdigest(),test_files=len(files),python=sys.executable)
    result['identity_start']=identity()
    def save():
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    for label,argv in [('compile',['-m','compileall','-q','twobyteasr']),('entry_compile',['-m','py_compile','auto_asr.py','moss_firered_pipeline.py','subtitle_core.py','moss_worker.py','firered_llm_worker.py','register_host_voiceprint.py'])]:
        process=subprocess.run([sys.executable,*argv],cwd=ROOT,env=env,capture_output=True,creationflags=flags)
        result['checks'].append(dict(name=label,exit_code=process.returncode))
        (out/(label+'.log')).write_bytes(process.stdout+process.stderr)
    for index,file in enumerate(files):
        test_file_name=Path(file.split('::',1)[0]).stem
        name=test_file_name+('-'+hashlib.sha256(file.encode()).hexdigest()[:8] if '::' in file else '')
        folder=out/name;folder.mkdir()
        file_env=dict(env,LOCALAPPDATA=str(folder/'local'),APPDATA=str(folder/'roaming'),
            TEMP=str(folder/'temp'),TMP=str(folder/'temp'))
        (folder/'temp').mkdir()
        began=time.monotonic();xml=folder/'junit.xml'
        with (folder/'output.log').open('wb') as log:
            child=subprocess.Popen([sys.executable,str(ROOT/'scripts/isolated_pytest.py'),file,'--junitxml='+str(xml)],cwd=ROOT,env=file_env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
            # This integration file installs multiple real offline venvs;
            # individual pip operations already have a 600 s bound.
            file_timeout=max(args.timeout,1800) if test_file_name=='test_environment_preflight' else args.timeout
            try:code=child.wait(file_timeout);timeout=False
            except subprocess.TimeoutExpired:
                timeout=True
                stop_test_process(child)
                code=124
        counts=dict(passed=0,failed=0,errors=0,skipped=0)
        receipt_error = ''
        if xml.exists():
            try:
                tree=ET.parse(xml)
            except (OSError, ET.ParseError) as exc:
                receipt_error = type(exc).__name__
            else:
                for case in tree.findall('.//testcase'):
                    key='failed' if case.find('failure') is not None else 'errors' if case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
                    counts[key]+=1
        elif not code:
            receipt_error = 'MissingJUnit'
        if receipt_error and not code:
            code = 125
        row=dict(file=file,artifact_dir=str(folder),exit_code=code,timed_out=timeout,seconds=round(time.monotonic()-began,3),counts=counts)
        if receipt_error:
            row['receipt_error'] = receipt_error
        result['files'].append(row)
        for key,value in counts.items():result['counts'][key]+=value
        save();print(json.dumps(dict(progress=f'{index+1}/{len(files)}',**row)),flush=True)
    with (out/'hygiene.log').open('wb') as log:
        check=subprocess.run([sys.executable,'scripts/check_release_hygiene.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    result['checks'].append(dict(name='release_hygiene',exit_code=check.returncode))
    result['identity_end']=identity()
    # A documentation-only commit can change HEAD; runtime and test bytes
    # must remain identical for this to count as one final-version run.
    unchanged=all(result['identity_start'][key]==result['identity_end'][key]
                  for key in ('source_sha256','source_inputs','test_inputs_sha256','python'))
    result['checks'].append(dict(name='source_and_tests_unchanged',exit_code=0 if unchanged else 1))
    result['passed']=all(row['exit_code']==0 for row in result['files']+result['checks'])
    save();print(json.dumps(dict(passed=result['passed'],counts=result['counts'],output=str(out))))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
