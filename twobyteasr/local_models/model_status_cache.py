"""Bounded shared registry snapshots; one daemon reader, no GUI objects or weights."""
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
        return bool(entry and not entry['pending'] and entry['value'] is value)


def request_registry(root, callback=None, *, force=False):
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
            if force: entry['version'] += 1
            fresh = not force and entry['value'] is not None and time.perf_counter()-entry['updated'] < 5
            if fresh and not entry['pending']:
                callbacks, entry['callbacks'] = entry['callbacks'], []
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
            try:
                from .model_registry import scan_model_registry
                registry = scan_model_registry(install_root=Path(key))
            except Exception:
                registry = None
            with _lock:
                entry = _entries[key]
                if version != entry['version']:
                    continue
                if registry is not None:
                    entry['value'], entry['updated'] = registry, time.perf_counter()
                entry['pending'] = False
                callbacks, entry['callbacks'] = entry['callbacks'], []
                break
        for notify in callbacks:
            try: notify(registry)
            except RuntimeError: pass
        _queue.task_done()
