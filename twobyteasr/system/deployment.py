"""Stdlib-only deployment events, isolated child environment and bounded commands."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

MARKER = '[2BYTEASR_DEPLOY] '
HEARTBEAT_S = 15.0


def managed_environment(env=None, *, runtime=None):
    child = dict(os.environ if env is None else env)
    # Package-manager configuration is process-local. Keep OS, TLS and the
    # user's network proxy; remove interpreter/package selection from outside.
    for key in tuple(child):
        upper = key.upper()
        if (upper.startswith(('PYTHON', 'PIP_', 'UV_', 'CONDA_', '_PYI'))
                or upper in {'VIRTUAL_ENV', '__PYVENV_LAUNCHER__', 'PSMODULEPATH'}
                or upper.startswith('TWOBYTEASR_') and upper.endswith('_PYTHON')):
            child.pop(key, None)
    child.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONNOUSERSITE='1',
                 PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1',
                 UV_NO_CONFIG='1', UV_NO_PROGRESS='1', UV_HTTP_TIMEOUT='30', UV_HTTP_RETRIES='1',
                 UV_PYTHON_NO_REGISTRY='1', UV_NO_MODIFY_PATH='1', UV_LINK_MODE='hardlink',
                 TWOBYTEASR_MANAGED_RUNTIME_ONLY='1')
    if runtime is not None:
        runtime = Path(runtime).resolve()
        child.update(UV_CACHE_DIR=str(runtime/'download-cache'),
                     UV_PYTHON_INSTALL_DIR=str(runtime/'python'),
                     UV_PYTHON_BIN_DIR=str(runtime/'unused-bin'),
                     PIP_CACHE_DIR=str(runtime/'pip-cache'))
    return child


def event(phase, state='start', **details):
    from ..local_models.download_diagnostics import redact
    payload = dict(job_id=os.environ.get('TWOBYTEASR_DEPLOY_JOB_ID', ''),
                   time=time.time(), pid=os.getpid(), phase=phase, state=state, **details)
    print(MARKER + json.dumps(redact(payload), ensure_ascii=False), flush=True)
    return payload


def run_command(arguments, *, cwd, phase, component='', timeout=1200, env=None, capture=False):
    """One bounded attempt; completion owns both the process tree and stdout."""
    args = [str(x) for x in arguments]
    started = time.monotonic()
    process = job = reader = None
    output, reader_errors, last = [], [], [started]
    failure = None

    def pump():
        try:
            for line in process.stdout:
                output.append(line)
                if len(output) > 5000:
                    del output[:1000]
                if not capture:
                    print(line, end='', flush=True)
                last[0] = time.monotonic()
        except Exception as exc:
            reader_errors.append(exc)

    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        if os.name == 'nt':
            flags |= 0x4  # CREATE_SUSPENDED: own descendants before any can spawn.
        process = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf8', errors='replace', creationflags=flags)
        if os.name == 'nt':
            from .process_job import RequestProcessJob
            job = RequestProcessJob(process)
        event(phase, component=component, executable=args[0], arguments=args[1:],
              child_pid=process.pid, deadline_s=timeout, waiting='subprocess')
        reader = threading.Thread(target=pump, name='deployment-output', daemon=True)
        reader.start()
        heartbeat = started
        while True:
            if reader_errors:
                raise RuntimeError(f'{component or phase} 输出读取失败：{reader_errors[0]}') from reader_errors[0]
            now = time.monotonic()
            if now-started > timeout:
                raise TimeoutError(f'{component or phase} 超过 {timeout} 秒；停止本次子程序并保留下载缓存。请重试或导出诊断。')
            try:
                process.wait(timeout=.05)
                break
            except subprocess.TimeoutExpired:
                pass
            if now-heartbeat >= HEARTBEAT_S:
                event(phase, 'waiting', component=component, child_pid=process.pid,
                      elapsed_s=round(now-started, 1), output_age_s=round(now-last[0], 1),
                      waiting='subprocess')
                heartbeat = now
    except BaseException as exc:
        failure = exc
    finally:
        # Close the job before waiting for EOF: a descendant may still own
        # stdout after its root has exited. Exactly this caller closes the job.
        cleanup_errors = []
        if job is not None:
            try:
                job.close(timeout=3)
            except Exception as exc:
                cleanup_errors.append(exc)
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)
            except Exception as exc:
                cleanup_errors.append(exc)
            if reader is not None:
                reader.join(3)
                if reader.is_alive():
                    cleanup_errors.append(RuntimeError('输出管道仍未关闭，不能确认本次操作完成'))
            if reader is None or not reader.is_alive():
                process.stdout.close()
        if cleanup_errors:
            detail = '; '.join(f'{type(exc).__name__}: {exc}' for exc in cleanup_errors)
            cause = failure
            failure = RuntimeError(f'{component or phase} 进程树或输出清理未完成：{detail}'
                                   + (f'；原始失败：{type(cause).__name__}: {cause}' if cause else ''))
            failure.__cause__ = cause or cleanup_errors[0]
    if failure is None and reader_errors:
        failure = RuntimeError(f'{component or phase} 输出读取失败：{reader_errors[0]}')
        failure.__cause__ = reader_errors[0]
    if failure is None and process.returncode:
        failure = subprocess.CalledProcessError(process.returncode, args, output=''.join(output))
    if failure is not None:
        try:
            event(phase, 'failed', component=component,
                  child_pid=getattr(process, 'pid', None),
                  exit_code=getattr(process, 'returncode', None), reason=str(failure),
                  elapsed_s=round(time.monotonic()-started, 1))
        except Exception:
            pass  # A broken diagnostic sink must not obscure the original failure.
        raise failure
    event(phase, 'done', component=component, child_pid=process.pid,
          exit_code=process.returncode, elapsed_s=round(time.monotonic()-started, 1))
    return ''.join(output)


class DeploymentJournal:
    """One GUI owner records redacted subprocess events and diagnostic lines."""
    def __init__(self, directory, *, source, models, job_id=None):
        self.job_id = job_id or uuid.uuid4().hex
        self.path = Path(directory)/f'{self.job_id}.jsonl'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.record('job_start', source=source, models=list(models))

    def record(self, state, **details):
        from ..local_models.download_diagnostics import redact
        with self.path.open('a', encoding='utf8') as stream:
            stream.write(json.dumps(redact(dict(job_id=self.job_id,time=time.time(),state=state,**details)),ensure_ascii=False)+'\n')
