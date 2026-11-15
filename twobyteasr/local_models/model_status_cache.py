"""Bounded snapshots: one coordinator and two daemon file readers; no GUI or weights."""
from collections import OrderedDict
from queue import Queue
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_entries = OrderedDict()
_queue = Queue(maxsize=4)
_worker = None


def cached_registry(root):
    with _lock:
        entry = _entries.get(str(Path(root).absolute()))
        return entry.get('value') if entry else None


def registry_is_current(root, value):
    with _lock:
        entry = _entries.get(str(Path(root).absolute()))
        return bool(entry and entry['value'] is value and (not entry['pending'] or
            'published_version' in entry and entry['published_version']==entry.get('version')))


def registry_metrics(root):
    """Read-only timing of real scans, separate from page construction time."""
    with _lock:
        entry = _entries.get(str(Path(root).absolute()), {})
        return {key: entry.get(key) for key in ('pending', 'version', 'scan_count', 'scan_ms', 'last_error')}


def request_registry(root, callback=None, *, force=False, progress_callback=None):
    """Coalesce checks and invalidations; never publish an invalidated result.

    Callback runs on the reader: Qt consumers must pass a queued Signal.emit.
    A filesystem snapshot cannot overwrite the current model selection.
    """
    global _worker
    key = str(Path(root).absolute())
    with _lock:
        rejected = False
        if key not in _entries and len(_entries) >= 4:
            victim = next((k for k,e in _entries.items() if not e['pending']), None)
            if victim is None: rejected = True
            else: del _entries[victim]
        if rejected:
            callbacks, value = [callback] if callback is not None else [], None
        else:
            entry = _entries.setdefault(key, dict(value=None, updated=0., version=0, pending=False, callbacks=[]))
            _entries.move_to_end(key)
            if callback is not None and callback not in entry['callbacks']:
                entry['callbacks'].append(callback)
            if progress_callback is not None:
                observers = entry.setdefault('progress_callbacks', [])
                if progress_callback not in observers:
                    observers.append(progress_callback)
            if force: entry['version'] += 1
            fresh = not force and entry['value'] is not None and time.perf_counter()-entry['updated'] < 5
            if fresh and not entry['pending']:
                callbacks, entry['callbacks'] = entry['callbacks'], []
                entry['progress_callbacks'] = []
                value = entry['value']
            else:
                callbacks, value = [], None
                if not entry['pending']:
                    entry['pending'] = True
                    _queue.put_nowait(key)  # at most four entries, including the running one
                if _worker is None or not _worker.is_alive():
                    _worker = threading.Thread(target=_run, name='shared-model-registry', daemon=True)
                    _worker.start()
    for notify in callbacks:
        try: notify(value)
        except RuntimeError: pass


def _run():
    while True:
        key = _queue.get()
        while True:
            with _lock:
                version = _entries[key]['version']
            started = time.perf_counter()
            error = None
            try:
                from .model_registry import scan_model_registry
                alignment_states = {}
                alignment_tokens = {}
                def with_alignment(value):
                    if not hasattr(value, 'record') or not hasattr(value, 'install_root'):
                        return value
                    from .alignment_readiness import inspect as inspect_alignment
                    groups = {'qwen_aligner': ('qwen_ultra_aligner',),
                              'qwen_ultra_head': ('qwen_ultra_aligner','qwen_ultra_head'),
                              'mfa_aligner': ('mfa_aligner','mfa_aligner_ja')}
                    pending = getattr(value, 'pending_keys', ())
                    for model, required in groups.items():
                        if any(k in pending for k in required):
                            alignment_states[model] = dict(state='checking', ready=False, reason='状态检查中')
                            continue
                        token = tuple(id(value.record(k)) for k in required)
                        if alignment_tokens.get(model) != token:
                            alignment_states.update(inspect_alignment(value, keys=(model,)))
                            alignment_tokens[model] = token
                    value.alignment_readiness = {k:dict(v) for k,v in alignment_states.items()}
                    return value
                def progress(value):
                    value = with_alignment(value)
                    with _lock:
                        entry=_entries[key]
                        if entry['version']!=version:
                            return
                        entry['value']=value
                        entry['published_version']=version
                        observers=list(entry.get('progress_callbacks', []))
                    for notify in observers:
                        try: notify(value)
                        except RuntimeError: pass
                import inspect
                parameters=inspect.signature(scan_model_registry).parameters.values()
                progressive=any(p.name=='on_progress' or p.kind==p.VAR_KEYWORD for p in parameters)
                registry = (scan_model_registry(install_root=Path(key),on_progress=progress,workers=2)
                            if progressive else scan_model_registry(install_root=Path(key)))
                registry = with_alignment(registry)
            except Exception as exc:
                from .model_registry import ModelRegistry
                registry = ModelRegistry(Path(key), Path(key)/'models', error=str(exc)[:240])
                registry.alignment_readiness = {k:dict(state='unreadable',ready=False,reason=str(exc)[:180]) for k in ('qwen_aligner','qwen_ultra_head','mfa_aligner')}
                error = type(exc).__name__
            with _lock:
                entry = _entries[key]
                entry['scan_count'] = entry.get('scan_count', 0) + 1
                entry['scan_ms'] = round((time.perf_counter()-started)*1000, 3)
                entry['last_error'] = error
                if version != entry['version']:
                    continue
                if registry is not None:
                    entry['value'], entry['updated'] = registry, time.perf_counter()
                    entry['published_version']=version
                entry['pending'] = False
                callbacks, entry['callbacks'] = entry['callbacks'], []
                entry['progress_callbacks'] = []
                break
        for notify in callbacks:
            try: notify(registry)
            except RuntimeError: pass
        _queue.task_done()
