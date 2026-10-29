import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from twobyteasr.system.deployment import DeploymentJournal, managed_environment, run_command
from twobyteasr.system import runtime_registry


def test_foreign_interpreters_and_package_configuration_are_removed(tmp_path):
    original=dict(Path='system-path',SystemRoot='windows',HTTPS_PROXY='http://localhost:1234',
        PYTHONHOME='foreign',PYTHONPATH='foreign',CONDA_PREFIX='foreign',PIP_INDEX_URL='foreign',
        UV_PYTHON='foreign',UV_CACHE_DIR='foreign',TWOBYTEASR_MAIN_PYTHON='foreign',PSMODULEPATH='foreign-powershell')
    clean=managed_environment(original,runtime=tmp_path)
    assert clean['Path']=='system-path' and clean['HTTPS_PROXY']==original['HTTPS_PROXY']
    assert all(k not in clean for k in ['PYTHONHOME','PYTHONPATH','CONDA_PREFIX','UV_PYTHON','TWOBYTEASR_MAIN_PYTHON'])
    assert clean['UV_CACHE_DIR']==str(tmp_path/'download-cache')
    assert 'PSMODULEPATH' not in clean
    assert original['PYTHONHOME']=='foreign'


def test_formal_runtime_ignores_external_override_registry_and_desktop(tmp_path,monkeypatch):
    managed=tmp_path/'managed';foreign=tmp_path/'conda/Scripts/python.exe'
    foreign.parent.mkdir(parents=True);foreign.touch()
    owned=managed/'main/version/Scripts/python.exe';owned.parent.mkdir(parents=True);owned.touch()
    monkeypatch.delenv('TWOBYTEASR_DEVELOPER_RUNTIMES',raising=False)
    monkeypatch.setenv('TWOBYTEASR_MAIN_PYTHON',str(foreign))
    monkeypatch.setattr(runtime_registry,'runtimes_root',lambda:managed)
    monkeypatch.setattr(runtime_registry,'load_registry',lambda:{'main':{'python_executable':str(foreign),'root':str(foreign.parent.parent)}})
    assert runtime_registry.resolve_runtime_python('main',register=False)==''
    assert Path(runtime_registry.intended_runtime_root('main')).is_relative_to(managed)
    monkeypatch.setattr(runtime_registry,'load_registry',lambda:{'main':{'python_executable':str(owned)}})
    assert Path(runtime_registry.resolve_runtime_python('main',register=False))==owned
    assert foreign.is_file()


def test_large_child_output_and_exit_are_drained(tmp_path,capsys):
    result=run_command([sys.executable,'-I','-c',"import sys;print('x'*300000);sys.stderr.write('end\\n')"],
        cwd=tmp_path,phase='environment_checking',timeout=10,capture=True)
    assert result.count('x')==300000 and 'end\n' in result
    events=[json.loads(line.split('] ',1)[1]) for line in capsys.readouterr().out.splitlines()]
    assert events[0]['state']=='start' and events[-1]['state']=='done'
    assert events[-1]['exit_code']==0


def test_quiet_child_is_bounded_without_unlimited_validation(tmp_path,capsys):
    began=time.monotonic()
    with pytest.raises(TimeoutError,match='超过'):
        run_command([sys.executable,'-I','-c','import time;time.sleep(60)'],
                    cwd=tmp_path,phase='environment_checking',component='main',timeout=.5)
    assert time.monotonic()-began<15
    assert '"state": "failed"' in capsys.readouterr().out


def test_journal_redacts_credentials_and_signed_queries(tmp_path):
    journal=DeploymentJournal(tmp_path,source='AUTO',models=['moss'])
    journal.record('output',line='https://example.test/a?token=sensitive Authorization: Bearer sensitive')
    text=journal.path.read_text('utf8')
    assert 'sensitive' not in text
    assert 'job_start' in text


@pytest.mark.skipif(os.name!='nt',reason='Windows bootstrap')
def test_powershell_bounded_runner_preserves_unicode_space_and_drains(tmp_path):
    root=Path(__file__).resolve().parents[1]
    script=root/'scripts/setup_managed_backend.ps1'
    quote=lambda s:"'"+str(s).replace("'","''")+"'"
    target=tmp_path/'路径 space';target.mkdir()
    driver=tmp_path/'driver.ps1'
    driver.write_text("$ErrorActionPreference='Stop'\n"+
        '$managed='+quote(target)+"\n$script:phase='test'\n"+
        '$ast=[System.Management.Automation.Language.Parser]::ParseFile('+quote(script)+",[ref]$null,[ref]$null)\n"+
        "$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Run-Bounded'},$true)\n"+
        'Invoke-Expression $fn.Extent.Text\n'+
        'Run-Bounded '+quote(sys.executable)+" @('-I','-X','utf8','-c',"+
        quote("import sys;print('中文 space');print('x'*100000);sys.stderr.write('tail\\n')")+") 15\n",'utf-8-sig')
    result=subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
        '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(driver)],
        capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr.decode('utf8',errors='replace')
    assert b'tail' in result.stdout


@pytest.mark.skipif(os.name!='nt',reason='Windows bootstrap')
@pytest.mark.parametrize('progressing',[False,True])
def test_bootstrap_download_deadline_distinguishes_progress_from_stall(tmp_path,progressing):
    root=Path(__file__).resolve().parents[1]
    quote=lambda value:"'"+str(value).replace("'","''")+"'"
    target=tmp_path/'download.partial'
    code=("import time;from pathlib import Path;p=Path("+repr(str(target))+");"
          "p.touch()\nfor i in range(20):\n"
          +(" with p.open('ab') as f:f.write(b'x'*4096)\n" if progressing else "")
          +" time.sleep(.1)\n"+("" if progressing else "time.sleep(30)\n"))
    driver=tmp_path/'progress.ps1'
    driver.write_text("$ErrorActionPreference='Stop'\n[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"+
        '$managed='+quote(tmp_path)+"\n$script:phase='tools_preparing'\n"+
        '$ast=[Management.Automation.Language.Parser]::ParseFile('+quote(root/'scripts/setup_managed_backend.ps1')+",[ref]$null,[ref]$null)\n"+
        "$fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Run-Bounded'},$true)\n"+
        'Invoke-Expression $fn.Extent.Text\n'+
        'Run-Bounded '+quote(sys.executable)+" @('-I','-X','utf8','-c',"+quote(code)+") 10 "+quote(target)+" 1 'fixture'\n",
        'utf-8-sig')
    began=time.monotonic()
    result=subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
        '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(driver)],
        capture_output=True,timeout=20)
    assert time.monotonic()-began<15
    if progressing:
        assert result.returncode==0,result.stderr.decode('utf8',errors='replace')
        assert target.stat().st_size==81920
    else:
        assert result.returncode!=0
        assert '没有新增数据' in result.stdout.decode('utf8',errors='replace')
