# SPDX-License-Identifier: GPL-3.0-only
"""Bounded real-entry probes from a relocated app with an independent PATH."""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path


def probe(app: Path, profile: Path, log: Path, *, finder: bool, environment: dict, cwd: Path) -> dict:
    output=profile/'startup-smoke'
    env=dict(environment, TWOBYTEASR_TEST_ROOT=str(profile))
    command=(["/usr/bin/open","-n","-W","--env","PATH="+env['PATH'],
              "--env","TWOBYTEASR_TEST_ROOT="+str(profile),str(app),"--args"]
             if finder else [str(app/'Contents/MacOS/2ByteASR')])
    command += ['--macos-startup-smoke',str(output)]
    record=dict(passed=False,route='launch-services' if finder else 'relocated-executable',
                minimal_path=env['PATH'],profile=str(profile))
    try:
        with log.open('ab') as stream:
            result=subprocess.run(command,env=env,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,timeout=75)
        record['launcher_exit_code']=result.returncode
        saved=output/'result.json'
        if saved.is_file():
            record['application_receipt']=json.loads(saved.read_text('utf8'))
            record['passed']=result.returncode==0 and record['application_receipt'].get('passed') is True
        else:
            record['error']='Normal application entry produced no startup result'
    except Exception as exc:
        record['error']=str(exc)
    finally:
        saved=output/'result.json'
        if saved.is_file() and 'application_receipt' not in record:
            # Keep evidence of a visible app even when its probe timed out;
            # this does not turn a timeout into successful process completion.
            record['application_receipt']=json.loads(saved.read_text('utf8'))
        # Retain only this probe's application diagnostics, never its settings
        # or model/cache trees. A hard-exit inside quick_start still leaves logs.
        for path in (profile/'local/2ByteASR/logs').glob('*'):
            if path.is_file() and path.name in {'2byteasr-startup.log','startup-trace.jsonl'}:
                shutil.copy2(path, log.parent/(log.stem+'-'+path.name))
    return record


def verify_relocated_startup(app: Path, boundary: Path, output: Path, environment: dict) -> dict:
    direct=probe(app,boundary/'relocated-startup-profile',output/'startup-direct.log',
                 finder=False,environment=environment,cwd=output/'relocated')
    finder=probe(app,boundary/'finder-startup-profile',output/'startup-finder.log',
                 finder=True,environment=environment,cwd=output/'relocated')
    return dict(passed=direct['passed'] and finder['passed'],direct=direct,finder=finder,
                artifact_preserved=True)
