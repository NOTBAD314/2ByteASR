"""Owned cloud ASR request process body. Credentials arrive only through stdin.

The same body runs in three launch forms (see ``cloud_worker_command``):

* packaged app: ``2ByteASR.exe --asr-api-worker`` (no PyTorch runtime needed);
* source checkout: the GUI's own interpreter running ``asr_api_worker.py``;
* never the managed model runtime: cloud recognition must work on a machine
  that has no local model environment at all (2026-10-13).

Only HTTP clients, numpy and the project's own modules are imported here.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path


def cloud_worker_command(install_root=None) -> list[str]:
    """Command that starts this worker without the local model runtime."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--asr-api-worker"]
    from .runtime_paths import detect_install_root
    root = Path(install_root) if install_root is not None else detect_install_root()
    worker = root / "asr_api_worker.py"
    if (root / "workers" / worker.name).is_file():
        worker = root / "workers" / worker.name
    if not worker.is_file():
        raise RuntimeError(f"云端识别 worker 脚本缺失：{worker}")
    return [sys.executable, "-u", str(worker)]


def run(request: dict) -> list:
    import numpy as np
    import subtitle_core as legacy
    from . import asr
    from .runtime import RuntimeContext, activate_runtime_context
    from .cache import run_event_observer
    audio = np.load(request['audio_array'], mmap_mode='r')
    chunks = [dict(audio=(audio[row['offset']:row['offset'] + row['samples']], 16000),
                   start=row['start'], end=row['end']) for row in request['chunks']]
    asr.CLOUD_BATCH_WORKERS = request['workers']
    legacy.RUNTIME_SETTINGS = request['settings']
    lock = threading.Lock()

    def event(kind, payload):
        if kind not in {'cue_delta', 'asr_progress', 'asr_reference_delta'}:
            return
        with lock:
            print('[2BYTEASR_API] ' + json.dumps(dict(kind=kind, payload=payload), ensure_ascii=False), flush=True)

    context = RuntimeContext(job_id=request['job_id'], speaker_source=request.get('speaker_source', 'single'))
    with activate_runtime_context(context), run_event_observer(event):
        if not request.get('native_job'):
            return asr._transcribe_qwen_api(request['source_path'], chunks, publish_primary=request['publish_primary'],
                                            _endpoint=request['endpoint'], _context=request['context'])
        from .cloud_asr_jobs import filetrans, transcribe_chunks
        from .qwen31_asr import is_filetrans_model
        from .mosi_asr import MODEL as MOSI_MODEL, transcribe as mosi_transcribe
        from .runtime_paths import user_data_root
        from .llm_config import validate_qwen_asr_endpoint
        endpoint = request['endpoint']
        validate_qwen_asr_endpoint(endpoint)

        def check():
            if Path(request['cancel_file']).exists():
                raise RuntimeError('本地识别已取消；远端受理任务需按回执核对')

        # Setup-dialog tests pass a throwaway cache so they never reuse (or
        # leave behind) a recognition job of a real project.
        cache = Path(request.get('cache_root') or (Path(user_data_root()) / 'cache' / 'asr-jobs'))

        def progress(state, done, total):
            event('asr_progress', dict(backend=endpoint['provider'], model=endpoint['model'],
                                       state=state, completed_batches=done, total_batches=total))

        if is_filetrans_model(endpoint['model']):
            storage = filetrans_storage(request, endpoint)
            return filetrans(audio, endpoint, cache, storage, progress=progress, check=check,
                             auto_delete=bool(request['settings'].get('models', {}).get('oss_auto_delete', True)),
                             restart_terminal=bool(request.get('restart_terminal')))
        if endpoint['model'] == MOSI_MODEL:
            # The user's explicit "重新提交" confirmation (completion page) must
            # reach MOSS Pro too; without it a saved terminal/uncertain task is
            # never resubmitted (no double charge).
            return mosi_transcribe(audio, endpoint, cache, progress=progress, check=check,
                                   restart_terminal=bool(request.get('restart_terminal')))
        return transcribe_chunks(audio, endpoint, cache, progress=progress, check=check)


def filetrans_storage(request: dict, endpoint: dict):
    """Where 录音文件识别 audio goes: the user's own OSS bucket (the regular
    route) or, only when the user picked it, the provider's temporary upload
    (trial; the official docs say not for production). With neither, stop
    before anything is uploaded (ADR 0112)."""
    from .api_setup_catalog import MISSING_UPLOAD_MESSAGE, UPLOAD_OWN_OSS, UPLOAD_PROVIDER, resolve_upload_mode
    from .dashscope_service import DashScopeTemporaryStorage, ServiceProblem
    from .qwen31_asr import ASRProtocolError
    credentials = tuple(request.get('storage_credentials') or ())
    models = (request.get('settings') or {}).get('models', {}) or {}
    mode = resolve_upload_mode(models, str(endpoint.get('provider') or ''),
                               has_oss_credentials=bool(credentials) and all(credentials))

    def not_ready(message):
        error = ASRProtocolError(message, 'input_limit')
        error.problem = ServiceProblem('file_access', message, '打开“申请与设置 API”完成设置后再开始识别；没有上传任何音频。',
                                       code='upload_route_missing')
        return error

    if mode == UPLOAD_OWN_OSS:
        from .temp_audio_storage import oss_storage_from_settings
        storage = oss_storage_from_settings(request['settings'], credentials=credentials or None)
        if storage is None:
            raise not_ready('已选择“我自己的 OSS 私有存储”，但 OSS 还没设置完整（Bucket、地域与 AccessKey）。')
        return storage
    if mode != UPLOAD_PROVIDER:
        raise not_ready(MISSING_UPLOAD_MESSAGE)
    return DashScopeTemporaryStorage(api_url=str(endpoint.get('url') or ''), api_key=str(endpoint.get('api_key') or ''),
                                     model=str(endpoint.get('model') or ''))


def write_results(request: dict, results: list) -> None:
    path = Path(request['output'])
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'results': results}, ensure_ascii=False), 'utf8')
    temporary.replace(path)


def _ensure_stdio() -> None:
    """A windowed (GUI-subsystem) packaged app starts children with no
    sys.stdin/stdout even though the parent attached pipes; bind them."""
    if sys.stdin is not None and sys.stdout is not None and sys.stderr is not None:
        return
    import io
    import os
    if os.name != 'nt':
        for number, attribute, mode in ((0, 'stdin', 'r'), (1, 'stdout', 'w'), (2, 'stderr', 'w')):
            if getattr(sys, attribute) is None:
                setattr(sys, attribute, os.fdopen(os.dup(number), mode, encoding='utf-8', buffering=1))
        return
    import ctypes
    import msvcrt
    kernel32 = ctypes.windll.kernel32
    for number, attribute, flags in ((-10, 'stdin', os.O_RDONLY), (-11, 'stdout', os.O_WRONLY),
                                     (-12, 'stderr', os.O_WRONLY)):
        if getattr(sys, attribute) is not None:
            continue
        handle = kernel32.GetStdHandle(number)
        if handle in (0, -1, None):
            if attribute == 'stdin':
                raise SystemExit('--asr-api-worker needs a request on stdin')
            setattr(sys, attribute, open(os.devnull, 'w', encoding='utf-8'))
            continue
        stream = os.fdopen(msvcrt.open_osfhandle(handle, os.O_BINARY | flags), 'rb' if attribute == 'stdin' else 'wb',
                           buffering=0)
        setattr(sys, attribute, io.TextIOWrapper(stream, encoding='utf-8', write_through=True))


def main() -> int:
    _ensure_stdio()
    try:
        request = json.loads(sys.stdin.read())
        write_results(request, run(request))
    except Exception as exc:
        from .provider_diagnostics import redact_diagnostics
        problem = getattr(exc, 'problem', None)
        if problem is None and getattr(exc, 'category', '') in RESUBMIT_CATEGORIES:
            from .dashscope_service import ServiceProblem
            problem = ServiceProblem('resubmit_needed', RESUBMIT_CATEGORIES[exc.category],
                                     '要再试，可在完成页按“重试失败项”并确认重新提交；重新提交会再次上传并可能再次计费。',
                                     code=exc.category)
        if problem is not None:
            # One machine-readable line first so the window can show the real
            # cause (and a fix link) instead of a truncated log tail.
            print(ERROR_MARKER + json.dumps(dict(category=problem.category, message=problem.message,
                                                 action=problem.action, link=problem.link, code=problem.code,
                                                 resubmit=getattr(exc, 'category', '') in RESUBMIT_CATEGORIES),
                                            ensure_ascii=False), file=sys.stderr)
        print(redact_diagnostics(str(exc)), file=sys.stderr)
        return 1
    return 0


ERROR_MARKER = '[2BYTEASR_API_ERROR] '
# Saved remote states that are never resubmitted automatically (no double charge).
RESUBMIT_CATEGORIES = {
    'remote_terminal': '上次提交的云端识别任务已结束但没有成功（失败或已取消）。',
    'remote_unknown': '服务商查不到上次的识别任务（不存在或已超过官方保留的 24 小时）。',
    'submission_uncertain': '上次提交时连线中断，无法确认服务商是否已经受理；为避免重复收费没有自动重新提交。',
}


def failure_from_text(text: str) -> dict | None:
    """The explained provider problem a failed worker reported, if any."""
    for line in str(text or '').splitlines():
        line = line.strip()
        if line.startswith(ERROR_MARKER):
            try:
                value = json.loads(line[len(ERROR_MARKER):])
            except ValueError:
                return None
            return value if isinstance(value, dict) else None
    return None
