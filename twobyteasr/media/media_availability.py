"""Bounded media checks. Filesystem access stays in a disposable worker.

Availability is runtime state, separate from the user's clip/track edits.
The persisted offline flag is refreshed rather than trusted after reopening.
"""
from __future__ import annotations

import multiprocessing
import os
import threading
import time

# A reusable worker exits by itself after this long without requests, so a
# hidden Studio does not keep an extra interpreter alive.
_WORKER_IDLE_SECONDS = 60.0


def stat_sources_in_reader(sources, *, cancel_check=lambda:False):
    """First-open filesystem checks on the existing disposable read thread.

    No decoder or additional interpreter is needed to hand subtitle data to
    the GUI. Slow filesystems can only hold this daemon reader; generation
    checks still reject its late result. Full decoding stays in probe_sources.
    """
    results={}
    for source in dict.fromkeys(str(s) for s in sources if s):
        if cancel_check():break
        row={'path':source,'status':'available','reason':''}
        try:
            stat=os.stat(source)
            with open(source,'rb') as stream:stream.read(1)
            row['signature']=[stat.st_size,stat.st_mtime_ns]
        except FileNotFoundError:row.update(status='missing',reason='文件不存在')
        except PermissionError:row.update(status='unreadable',reason='文件存在但没有读取权限')
        except OSError as exc:row.update(status='unavailable',reason=f'位置不可用或读取失败（{getattr(exc,"winerror",None) or exc.errno}）')
        results[source]=row
    return results


def _probe_worker(connection, idle_seconds=None):
    try:
        while True:
            if idle_seconds is not None and not connection.poll(idle_seconds):
                return
            request = connection.recv()
            if request is None:
                return
            source, decode, previous = request
            result = {'path': source, 'status': 'available', 'reason': ''}
            try:
                stat = os.stat(source)
                with open(source, 'rb') as stream:
                    stream.read(1)
                result['signature'] = [stat.st_size, stat.st_mtime_ns]
                if decode and previous.get('signature') == result['signature'] and previous.get('identity'):
                    result['identity'] = previous['identity']
                elif decode:
                    from ..studio.studio_helpers import probe_media_identity
                    identity = dict(probe_media_identity(source))
                    if not identity.get('has_video') and not identity.get('has_audio'):
                        raise ValueError('没有可解码的音频或视频流')
                    result['identity'] = identity
            except FileNotFoundError:
                result.update(status='missing', reason='文件不存在')
            except PermissionError:
                result.update(status='unreadable', reason='文件存在但没有读取权限')
            except OSError as exc:
                result.update(status='unavailable', reason=f'位置不可用或读取失败（{exc.winerror if hasattr(exc, "winerror") else exc.errno}）')
            except Exception as exc:
                result.update(status='decode_failed', reason=f'解码失败或格式不支持：{type(exc).__name__}')
            connection.send(result)
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


class _ProbeProcess:
    """One spawned probe worker. Killed (never reused) after any timeout,
    cancellation or protocol error, so a late reply cannot reach a new caller."""

    def __init__(self, idle_seconds=None):
        from ..system.windows_ipc import process_pipe
        context = multiprocessing.get_context('spawn')
        self.connection, child = process_pipe(context)
        self.process = context.Process(target=_probe_worker, args=(child, idle_seconds), daemon=True)
        self.process.start()
        child.close()

    def alive(self):
        return self.process is not None and self.process.is_alive()

    def close(self, *, graceful=False):
        connection, process = self.connection, self.process
        self.connection = self.process = None
        if connection is not None and process is not None and graceful and process.is_alive():
            try:
                connection.send(None)
                process.join(timeout=.3)
            except (BrokenPipeError, OSError):
                pass
        if connection is not None:
            connection.close()
        if process is not None:
            if process.is_alive():
                # This worker may own an ffprobe child. Reap only this tree.
                import psutil
                try:
                    children = psutil.Process(process.pid).children(recursive=True)
                except psutil.Error:
                    children = []
                for child in reversed(children):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                process.kill()
            process.join(timeout=1)
            process.close()


# Studio checks media every few seconds. Spawning a fresh interpreter for each
# check cost ~0.15-0.3 s CPU every 3 s, so one idle-bounded worker is reused.
_SHARED_LOCK = threading.Lock()
_shared_worker = None


def _shared_probe_process():
    global _shared_worker
    if _shared_worker is None or not _shared_worker.alive():
        if _shared_worker is not None:
            _shared_worker.close()
        _shared_worker = _ProbeProcess(_WORKER_IDLE_SECONDS)
    return _shared_worker


def _discard_shared_probe_process():
    global _shared_worker
    if _shared_worker is not None:
        _shared_worker.close()
        _shared_worker = None


def shutdown_probe_worker():
    """Stop the reusable worker (application exit or tests)."""
    with _SHARED_LOCK:
        global _shared_worker
        if _shared_worker is not None:
            _shared_worker.close(graceful=True)
            _shared_worker = None


def probe_sources(sources, *, timeout=3.0, cancel_check=None, decode=False, previous=None):
    """Call on a background thread. Never wait indefinitely on a remote path."""
    shared = _SHARED_LOCK.acquire(blocking=False)
    worker = None
    results = {}
    clean = False

    def discard():
        nonlocal worker
        if shared:
            _discard_shared_probe_process()
        elif worker is not None:
            worker.close()
        worker = None

    def acquire():
        nonlocal worker
        if worker is None:
            worker = _shared_probe_process() if shared else _ProbeProcess()
        return worker

    try:
        for source in dict.fromkeys(str(p) for p in sources if p):
            if cancel_check and cancel_check():
                raise InterruptedError('媒体探测已取消')
            request = (source, decode, (previous or {}).get(source, {}))
            # A reused worker may exit on its idle limit just as a request
            # arrives. That is not a media failure: retry once on a new one.
            retries = 1 if shared else 0
            while True:
                try:
                    acquire().connection.send(request)
                except (BrokenPipeError, EOFError, OSError):
                    discard()
                    if retries:
                        retries -= 1
                        continue
                    results[source] = dict(path=source, status='probe_failed', reason='媒体探测进程退出')
                    break
                deadline = time.monotonic() + timeout
                reply = None
                while True:
                    if cancel_check and cancel_check():
                        raise InterruptedError('媒体探测已取消')
                    if worker.connection.poll(.025):
                        try:
                            reply = worker.connection.recv()
                        except EOFError:
                            reply = 'eof'
                        break
                    if time.monotonic() >= deadline:
                        reply = 'timeout'
                        break
                if isinstance(reply, dict) and reply.get('path') == source:
                    results[source] = reply
                    break
                discard()
                if reply == 'timeout':
                    results[source] = dict(path=source, status='timeout', reason='媒体位置响应超时')
                    break
                if reply == 'eof' and retries:
                    retries -= 1
                    continue
                results[source] = dict(path=source, status='probe_failed', reason='媒体探测进程退出')
                break
        clean = True
        return results
    finally:
        if shared:
            if not clean:
                # Cancelled or failed mid-request: the worker may still answer.
                _discard_shared_probe_process()
            _SHARED_LOCK.release()
        elif worker is not None:
            worker.close(graceful=clean)


def apply_availability(project, results):
    """Apply only results for the exact currently referenced paths."""
    previous = getattr(project, '_media_availability', {})
    changed = False
    current = {}
    for asset in project.media_pool:
        source = asset.canonical_source
        result = results.get(source, previous.get(source))
        if result is None:
            continue
        current[source] = result
        offline = result['status'] != 'available'
        changed |= asset.offline != offline or previous.get(source) != result
        asset.offline = offline
        if offline:
            asset.relink_state = 'offline'
        elif asset.relink_state == 'offline':
            asset.relink_state = 'linked'
    project._media_availability = current
    return changed


def media_available(project, source):
    """Cached GUI-side lookup; no filesystem or network IO."""
    result = getattr(project, '_media_availability', {}).get(str(source))
    if result is not None:
        return result['status'] == 'available'
    asset = next((a for a in project.media_pool if a.canonical_source == str(source)), None)
    return bool(source) and (asset is None or not asset.offline)


def export_sources(graph, start_ms=0, end_ms=float('inf')):
    """Referenced visible/audible media in the requested export interval."""
    ids = set()
    for kind in ('video_tracks', 'audio_tracks'):
        for track in graph.get(kind, ()):
            if not track.get('enabled', True) or (kind == 'audio_tracks' and track.get('muted')):
                continue
            for clip in track.get('clips', ()):
                if (clip.get('enabled', True) and clip['timeline_in_ms'] < end_ms
                        and start_ms < clip['timeline_out_ms']):
                    ids.add(clip['asset_id'])
    return [a['canonical_source'] for a in graph.get('media_pool', ()) if a['asset_id'] in ids]


def require_available(results):
    failed = [r for r in results.values() if r['status'] != 'available']
    if failed:
        details = '\n'.join(f"{r['path']}\n  {r['reason']}" for r in failed)
        raise ValueError(f'导出范围内有 {len(failed)} 份素材不可用，请在媒体池重新链接后再导出。\n{details}')
