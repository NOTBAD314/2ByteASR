"""Read-only interpreter-chain evidence and an isolated stdlib startup probe."""
from pathlib import Path
import json
import os
import subprocess


def interpreter_chain(executable):
    entry=Path(executable).absolute()
    cfg=entry.parent.parent/'pyvenv.cfg'
    values={}
    if cfg.is_file():
        for line in cfg.read_text('utf-8-sig',errors='replace').splitlines():
            key,sep,value=line.partition('=')
            if sep:values[key.strip().lower()]=value.strip()
    home=values.get('home','')
    base=Path(values['executable']) if values.get('executable') else (Path(home)/('python.exe' if os.name=='nt' else 'bin/python3') if home else None)
    if base is not None and not base.is_absolute():base=cfg.parent/base
    def identity(path):
        if path is None:return None
        try:
            stat=path.stat()
            return [str(path),str(path.resolve()),stat.st_size,stat.st_mtime_ns]
        except OSError:return [str(path),None]
    return dict(entry=str(entry),resolved_entry=str(entry.resolve()),
                config=str(cfg) if cfg.exists() else '',config_values=values,
                base=str(base) if base is not None else '',
                base_exists=base.is_file() if base is not None else None,
                identity=[identity(entry),identity(cfg),identity(base)])


def startup_probe(executable, *, cwd, env=None, timeout=15, _inspect_base=True):
    from .processes import popen_hidden_subprocess, sanitized_child_environment, stop_process_tree
    chain=interpreter_chain(executable)
    code="import json,sys;print(json.dumps(dict(executable=sys.executable,base_executable=getattr(sys,'_base_executable',''),prefix=sys.prefix,base_prefix=sys.base_prefix,version=sys.version)))"
    command=[str(executable),'-I','-X','utf8','-c',code]
    result=dict(stage='python_startup',command=command,cwd=str(cwd),chain=chain)
    process=None
    try:
        process=popen_hidden_subprocess(command,purpose='Python startup probe',cwd=str(cwd),
            env=sanitized_child_environment() if env is None else env,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        stdout,stderr=process.communicate(timeout=timeout)
        result.update(returncode=process.returncode,stdout=stdout.decode('utf8',errors='replace'),
                      stderr=stderr.decode('utf8',errors='replace'))
        try:result['python']=json.loads(result['stdout'])
        except ValueError:pass
        result['ok']=process.returncode==0 and isinstance(result.get('python'),dict)
    except subprocess.TimeoutExpired as exc:
        result.update(ok=False,timed_out=True,error=f'Python 启动检查超时（>{timeout} 秒）',exception=str(exc))
    except OSError as exc:
        result.update(ok=False,error=f'{type(exc).__name__}: {exc}')
    finally:
        if process is not None and process.poll() is None:stop_process_tree(process)
    # The environment launcher and its configured base are different programs.
    # Keep both outcomes, including a missing base, before repair writes anything.
    if _inspect_base and not result['ok'] and chain['base'] and chain['base']!=chain['entry']:
        base=chain['base']
        if chain['base_exists']:
            probe=startup_probe(base,cwd=cwd,env=env,timeout=timeout,_inspect_base=False)
            result['base_probe']={k:v for k,v in probe.items() if k!='base_probe'}
        else:result['base_probe']=dict(ok=False,executable=base,error='base_python_missing')
    return result
