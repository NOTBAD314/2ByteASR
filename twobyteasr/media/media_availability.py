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


def probe_due(previous, now=None):
    """Memory-only policy; a foreground event never wakes a disk."""
    return (time.monotonic() if now is None else now) >= float(previous.get('next_probe_monotonic', 0))


def record_probe(result, previous, *, started, now=None):
    now = time.monotonic() if now is None else now
    failures = 0 if result['status'] == 'available' else int(previous.get('failures', 0)) + 1
    delay = 15. if not failures else (3., 10., 30.)[min(failures-1, 2)]
    return dict(result, checked_monotonic=now, next_probe_monotonic=now+delay,
                failures=failures, probe_count=int(previous.get('probe_count', 0))+1,
                last_verified_identity=(result.get('identity') if result['status']=='available'
                    else previous.get('identity') or previous.get('last_verified_identity')),
                probe_elapsed_ms=round((now-started)*1000, 2))


def availability_identity(result):
    """Only a usable-file transition invalidates decoder/render state."""
    return (result.get('status') == 'available' or bool(result.get('verified_available')),
            result.get('signature'), result.get('identity'))


def stat_sources_in_reader(sources, *, cancel_check=lambda:False):
    """First-open checks from the project reader, with a killable IO owner."""
    # A kernel read on a sleeping external volume can outlive a Python
    # thread's cancellation. The disposable reader can actually be reaped.
    return probe_sources(sources, timeout=6., cancel_check=cancel_check)


def _probe_worker(connection, idle_seconds=None):
    try:
        while True:
            if idle_seconds is not None and not connection.poll(idle_seconds):
                return
            request = connection.recv()
            if request is None:
                return
            source, decode, previous = request
            # Only inherited owned-profile audits may delay a disposable reader.
            if os.environ.get('TWOBYTEASR_TEST_ROOT') and os.environ.get('TWOBYTEASR_TEST_MEDIA_DELAY'):
                time.sleep(min(5.,max(0.,float(os.environ['TWOBYTEASR_TEST_MEDIA_DELAY']))))
            result = {'path': source, 'status': 'available', 'reason': ''}
            started=time.monotonic()
            try:
                stat = os.stat(source)
                with open(source, 'rb') as stream:
                    stream.read(1)
                result['signature'] = [stat.st_size, stat.st_mtime_ns]
                result['path_probe_ms']=round((time.monotonic()-started)*1000,2)
                if decode and previous.get('signature') == result['signature'] and previous.get('identity'):
                    result['identity'] = previous['identity']
                    result['ffprobe_count']=0
                elif decode:
                    from ..studio.studio_helpers import probe_media_identity
                    identity = dict(probe_media_identity(source))
                    if not identity.get('has_video') and not identity.get('has_audio'):
                        raise ValueError('没有可解码的音频或视频流')
                    result['identity'] = identity
                    result['ffprobe_count']=1
                    result['decode_probe_ms']=round((time.monotonic()-started)*1000-result['path_probe_ms'],2)
            except FileNotFoundError:
                drive=os.path.splitdrive(source)[0]
                offline=bool(drive and not os.path.isdir(drive+os.sep))
                result.update(status='offline' if offline else 'missing',
                              reason='素材所在设备离线或盘符不可用' if offline else '文件不存在')
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
    # Coalesce all callers through the one disposable reader. Contention is
    # cancellable; it must not create another process waking the same drive.
    while not _SHARED_LOCK.acquire(timeout=.05):
        if cancel_check and cancel_check():
            raise InterruptedError('媒体探测已取消')
    shared = True
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
            prior = (previous or {}).get(source, {})
            if prior and not probe_due(prior):
                results[source] = prior
                continue
            started = time.monotonic()
            request = (source, decode, prior)
            source_timeout = min(30., float(timeout) * 2**min(int(prior.get('failures', 0)), 3))
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
                deadline = time.monotonic() + source_timeout
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
                    results[source] = dict(path=source, status='slow', reason='素材读取较慢，尚未确认缺失',
                        verified_available=bool(prior.get('status')=='available' or prior.get('verified_available')),
                        signature=prior.get('signature'), identity=prior.get('identity'),
                        probe_timeout_seconds=source_timeout)
                    break
                if reply == 'eof' and retries:
                    retries -= 1
                    continue
                results[source] = dict(path=source, status='probe_failed', reason='媒体探测进程退出')
                break
            results[source] = record_probe(results[source], prior, started=started)
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
        status=result['status']
        # A sleeping/slow device is not evidence that its file disappeared.
        # Keep the last offline flag until an authoritative result arrives.
        offline = (asset.offline if status in {'slow','timeout','probing','cancelled'}
                   else status != 'available')
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
        return result['status']=='available' or bool(result.get('verified_available'))
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
