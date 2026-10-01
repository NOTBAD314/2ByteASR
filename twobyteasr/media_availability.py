"""Bounded media checks. Filesystem access stays in a disposable worker.

Availability is runtime state, separate from the user's clip/track edits.
The persisted offline flag is refreshed rather than trusted after reopening.
"""
from __future__ import annotations

import multiprocessing
import os
import time


def _probe_worker(connection):
    try:
        while True:
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
                    from .studio_helpers import probe_media_identity
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


def probe_sources(sources, *, timeout=3.0, cancel_check=None, decode=False, previous=None):
    """Call on a background thread. Never wait indefinitely on a remote path."""
    context = multiprocessing.get_context('spawn')
    process = connection = None
    results = {}

    def stop():
        nonlocal process, connection
        if connection is not None:
            connection.close()
            connection = None
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
            process = None

    try:
        for source in dict.fromkeys(str(p) for p in sources if p):
            if cancel_check and cancel_check():
                raise InterruptedError('媒体探测已取消')
            if process is None:
                from .windows_ipc import process_pipe
                connection, child = process_pipe(context)
                process = context.Process(target=_probe_worker, args=(child,), daemon=True)
                process.start()
                child.close()
            connection.send((source, decode, (previous or {}).get(source, {})))
            deadline = time.monotonic() + timeout
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError('媒体探测已取消')
                if connection.poll(.025):
                    try:
                        results[source] = connection.recv()
                    except EOFError:
                        results[source] = dict(path=source, status='probe_failed', reason='媒体探测进程退出')
                        stop()
                    break
                if time.monotonic() >= deadline:
                    results[source] = dict(path=source, status='timeout', reason='媒体位置响应超时')
                    stop()
                    break
        return results
    finally:
        if connection is not None and process is not None and process.is_alive():
            try:
                connection.send(None)
                process.join(timeout=.3)
            except (BrokenPipeError, OSError):
                pass
        stop()


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
