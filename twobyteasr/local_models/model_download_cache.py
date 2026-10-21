"""Bounded lifecycle for model download staging, separate from installed models."""
from __future__ import annotations
import json
import math
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

MARKER = '.2byteasr-download-transaction.json'
RESUME_RETENTION_SECONDS = 14 * 86400


def _linked(path):
    try:
        info = path.lstat()
        return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) &
                                        getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))
    except FileNotFoundError: return False


def _safe(root: Path, path: Path) -> bool:
    root, path = Path(os.path.abspath(root)), Path(os.path.abspath(path))
    return (path != root and path.is_relative_to(root) and
            not any(_linked(p) for p in (path, *path.parents)))


def write_transaction(staging: Path, *, model_key: str, destination: Path,
                      files, state: str, detail='') -> None:
    from ..storage.atomic_files import write_text_atomic
    staging.mkdir(parents=True, exist_ok=True)
    if not _safe(staging.parent, staging): raise ValueError('下载暂存目录为链接')
    payload = {'schema_version': 1, 'owner': '2ByteASR.repository_download',
        'model_key': model_key, 'destination': str(destination), 'files': list(files),
        'state': state, 'updated_at': time.time(), 'detail': str(detail)[:1000]}
    write_text_atomic(staging / MARKER, json.dumps(payload, ensure_ascii=False, indent=2))


def _files(staging, payload):
    """Only published manifest names and this downloader's exact sidecar forms."""
    from ..repository_download import _safe_relative
    result = []
    for name in payload.get('files', []):
        name = _safe_relative(str(name))
        path = staging / name
        if _safe(staging, path) and path.is_file(): result.append(path)
        if not path.parent.is_dir() or not _safe(staging, path): continue
        suffixes = {'.download.json', '.attempt.json', '.attempts.jsonl', '.cache-copy'}
        for sibling in path.parent.iterdir():
            suffix = sibling.name[len(path.name):] if sibling.name.startswith(path.name) else ''
            if (suffix in suffixes or re.fullmatch(r'\.part(?:\.[A-Za-z0-9_]+(?:\.\d{3})?)?', suffix)) and _safe(staging, sibling) and sibling.is_file():
                result.append(sibling)
    return list(dict.fromkeys(result))


@dataclass(frozen=True)
class DownloadTransaction:
    root: Path
    model_key: str
    destination: Path
    state: str
    updated_at: float
    paths: tuple[Path, ...]
    logical_bytes: int


def scan_download_transactions(staging_root: Path, cancel=None) -> list[DownloadTransaction]:
    found = []
    cancelled = cancel.is_set if hasattr(cancel, 'is_set') else (cancel or (lambda: False))
    if not staging_root.is_dir() or any(_linked(p) for p in (staging_root, *staging_root.parents)): return found
    for directory, dirs, files in os.walk(staging_root, followlinks=False):
        if cancelled(): break
        base = Path(directory); dirs[:] = [name for name in dirs if not _linked(base / name)]
        if MARKER not in files or not _safe(staging_root, base / MARKER): continue
        try:
            marker = base / MARKER
            if marker.stat().st_size > 1024 * 1024: continue
            payload = json.loads(marker.read_text('utf-8-sig'))
            if not isinstance(payload, dict): continue
            if payload.get('owner') != '2ByteASR.repository_download' or payload.get('schema_version') != 1: continue
            # The path encodes model/source/manifest identity; owner must match.
            if base.relative_to(staging_root).parts[0] != payload.get('model_key'): continue
            if payload.get('state') not in {'downloading', 'paused', 'published', 'cleanup_failed'}: continue
            inventory = payload.get('files')
            if not isinstance(inventory, list) or len(inventory) > 8192 or not all(isinstance(n, str) for n in inventory): continue
            updated_at = float(payload['updated_at'])
            if not math.isfinite(updated_at): continue
            destination = Path(payload['destination'])
            if not destination.is_absolute(): continue
            paths = tuple(_files(base, payload))
            found.append(DownloadTransaction(base, payload['model_key'], destination,
                payload['state'], updated_at, paths, sum(p.stat().st_size for p in paths)))
        except (OSError, ValueError, KeyError, TypeError): continue
    return found


def cleanup_download_transaction(transaction: DownloadTransaction, *, staging_root: Path,
                                  active_keys=(), expired_only=True, now=None, resume_days=14,
                                  cancel=None, busy=lambda: False) -> dict:
    """Recheck receipt/state and nonblocking model lock; never remove a tree."""
    result = {'removed': [], 'failures': {}, 'skipped': [], 'logical_bytes': 0}
    cancelled = cancel.is_set if hasattr(cancel, 'is_set') else (cancel or (lambda: False))
    now = time.time() if now is None else now
    if transaction.model_key in active_keys or busy() or not _safe(staging_root, transaction.root):
        result['skipped'].append('下载正在使用或暂存目录为链接'); return result
    if cancelled():
        result['skipped'].append('维护已取消'); return result
    try:
        from ..repository_download import preparation_lock
        with preparation_lock(staging_root / transaction.model_key / '.prepare.lock', timeout=0):
            current = next((p for p in scan_download_transactions(staging_root, cancel=cancel) if p.root == transaction.root), None)
            if current is None:
                result['skipped'].append('下载归属登记已改变'); return result
            if current.state not in {'published', 'cleanup_failed'} and expired_only and now - current.updated_at < max(1, int(resume_days)) * 86400:
                result['skipped'].append(f'未完成下载保留{max(1, int(resume_days))}天，以便继续下载'); return result
            for path in current.paths:
                if cancelled() or busy():
                    result['skipped'].append('维护已取消或应用重新开始任务'); break
                if not _safe(staging_root, path):
                    result['skipped'].append(str(path)); continue
                try:
                    size = path.stat().st_size
                    path.unlink(); result['removed'].append(str(path)); result['logical_bytes'] += size
                except OSError as exc: result['failures'][str(path)] = str(exc)
            marker = current.root / MARKER
            if not result['failures'] and not result['skipped']:
                marker.unlink(missing_ok=True)
                directories = {current.root}
                for path in current.paths:
                    directories.update(p for p in path.parents if p.is_relative_to(current.root))
                for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
                    if not _safe(staging_root, path): continue
                    try: path.rmdir()
                    except OSError: pass  # unknown files remain, never rmtree
    except (OSError, ValueError, TimeoutError) as exc:
        result['failures'][str(transaction.root)] = str(exc)
    return result


def discard_published_staging(staging: Path, *, staging_root: Path) -> dict:
    """The publisher already holds the model lock; remove only its known files."""
    payload = json.loads((staging / MARKER).read_text('utf-8-sig'))
    result = {'removed': [], 'failures': {}, 'logical_bytes': 0}
    for path in _files(staging, payload):
        if not _safe(staging_root, path): continue
        try:
            size = path.stat().st_size
            path.unlink(); result['removed'].append(str(path)); result['logical_bytes'] += size
        except OSError as exc: result['failures'][str(path)] = str(exc)
    if not result['failures']:
        (staging / MARKER).unlink()
        for directory, dirs, files in os.walk(staging, topdown=False, followlinks=False):
            path = Path(directory)
            if not _safe(staging_root, path): continue
            try: path.rmdir()
            except OSError: pass
    return result
