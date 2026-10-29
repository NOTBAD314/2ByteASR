"""Actual Windows PS5 frozen configurator dispatch, without installing models."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(os.name!='nt',reason='Windows PowerShell entry')
@pytest.mark.parametrize('explicit,expected',[('', 'main'),('moss','moss')])
def test_frozen_configurator_parses_and_repairs_only_requested_roles(tmp_path,explicit,expected):
    root=Path(__file__).resolve().parents[1]
    source=root/'scripts/bootstrap_install.ps1'
    assert source.read_bytes().startswith(b'\xef\xbb\xbf')
    app=tmp_path/'中文 程序';scripts=app/'scripts';scripts.mkdir(parents=True)
    shutil.copy2(source,scripts/source.name)
    (app/'2ByteASR.exe').write_bytes(b'fixture is never launched')
    (app/'2byteasr_build.json').write_text('{}','utf8')
    (scripts/'setup_managed_backend.ps1').write_text(
        "param([string[]]$ModelKey,[string]$RepairRoles)\n"
        "@{roles=$RepairRoles;models=$ModelKey} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'invocation.json')\n"
        "$global:LASTEXITCODE=0\n",'utf-8-sig')
    env=os.environ.copy();env.pop('PSMODULEPATH',None)
    env.update(TEMP=str(tmp_path),TMP=str(tmp_path))
    command=[str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
             '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
             str(scripts/source.name),'-Repair','-NoLaunch','-NonInteractive']
    if explicit:command+=['-RepairRole',explicit]
    result=subprocess.run(command,cwd=app,env=env,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr.decode('utf8',errors='replace')
    actual=json.loads((app/'invocation.json').read_text('utf-8-sig'))
    assert actual['roles']==expected
