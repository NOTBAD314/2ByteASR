"""A surviving launcher does not prove that its configured base Python exists."""
import json,os,sys
from pathlib import Path
import pytest
from twobyteasr.system.python_startup import interpreter_chain,startup_probe
from twobyteasr.system import environment
from twobyteasr.recognition.run_diagnosis import diagnose_run,DiagnosisInput


def entry(tmp_path):
    root=tmp_path/'中文 空格'/'main';exe=root/'Scripts/python.exe'
    exe.parent.mkdir(parents=True);exe.write_bytes(b'inert launcher')
    base=tmp_path/'old version'/'python.exe'
    cfg=root/'pyvenv.cfg';cfg.write_text('home = '+str(base.parent)+'\nimplementation = CPython\n','utf8')
    return exe,base,cfg


def test_chain_retains_missing_base_separately_from_entry(tmp_path):
    exe,base,cfg=entry(tmp_path);chain=interpreter_chain(exe)
    assert exe.is_file() and chain['base_exists'] is False
    assert chain['base']==str(base) and chain['config']==str(cfg)
    old=chain['identity'];base.parent.mkdir();base.write_bytes(b'base')
    assert interpreter_chain(exe)['identity']!=old


def test_startup_records_actual_command_cwd_and_full_stderr(tmp_path,monkeypatch):
    exe,base,cfg=entry(tmp_path)
    class Failed:
        returncode=1
        def communicate(self,timeout):return b'',b'error: uv trampoline failed to spawn Python child process\nCaused by: entity not found (os error 2)'
        def poll(self):return 1
    import twobyteasr.system.processes as processes
    calls=[]
    monkeypatch.setattr(processes,'popen_hidden_subprocess',lambda args,**kw:calls.append((args,kw)) or Failed())
    result=startup_probe(exe,cwd=tmp_path)
    assert not result['ok'] and result['stage']=='python_startup'
    assert result['returncode']==1 and 'os error 2' in result['stderr']
    assert result['command'][0]==str(exe) and result['cwd']==str(tmp_path)
    assert result['base_probe']['error']=='base_python_missing'


def test_cached_success_expires_when_base_disappears(tmp_path,monkeypatch):
    exe,base,cfg=entry(tmp_path);base.parent.mkdir();base.write_bytes(b'base')
    chain=interpreter_chain(exe)
    result=environment.PreflightResult('main',True,str(exe),detail={'startup':{'chain':chain}})
    monkeypatch.setattr(environment,'_CACHE',{'main':('contract',result)})
    monkeypatch.setattr(environment,'environment_interpreter',lambda role:str(exe))
    assert environment._cache_valid('main','contract')
    base.unlink()
    assert not environment._cache_valid('main','contract')


def test_trampoline_diagnosis_targets_main_not_all_models():
    diagnosis=diagnose_run(DiagnosisInput(report={},item_error='main 环境探测进程失败（退出码 1）：error: uv trampoline failed to spawn Python child process Caused by: entity not found (os error 2)'))
    match=next(x for x in diagnosis.findings if x.rule_id=='python_startup_main')
    assert match.issue.actions==('repair_runtime_main',)
    assert not any(x.rule_id=='runtime_broken' for x in diagnosis.findings)


def test_python_launch_failure_does_not_claim_dependency_or_weight_corruption():
    result=environment.PreflightResult('main',False,problems=['base missing'],detail={'stage':'python_startup'})
    message=environment.human_message(result)
    assert 'Python 无法启动' in message and 'main' in message and '模型' in message
    assert '版本不匹配' not in message
