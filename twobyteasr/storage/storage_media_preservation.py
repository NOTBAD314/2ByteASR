"""Conservative, read-only proof of a saved project's explicit media relink.

The receipt is created only by the explicit asset-copy action. It is not a
permission to delete: both full files and the saved project graph are checked
again, without loading, repairing or saving any project.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import uuid

MAX_PROJECTS = 2000
MAX_ENTRIES = 20000
MAX_DEPTH = 12
# Every saved project (autosaves included) is read in full before a media
# cache may be removed. 2026-10-11: a real library had 383 project files /
# 231 MB, so the former 64 MB total (16 MB per file, 10 s) always failed
# closed and the storage page could never clean any media cache. The check
# runs on the storage worker and stays cancellable.
MAX_JSON_BYTES = 128 * 1024 * 1024
MAX_TOTAL_JSON_BYTES = 2 * 1024**3
MAX_HASH_BYTES = 32 * 1024**3
SCAN_SECONDS = 90
VERIFY_SECONDS = 60


@dataclass(frozen=True)
class ProjectReferenceScan:
    complete: bool
    references: dict[str, tuple[str, ...]] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    identities: tuple[tuple[str, tuple], ...] = ()


@dataclass(frozen=True)
class RelinkedAssetVerification:
    verified: bool
    reason: str
    asset_path: str = ''
    referenced_projects: tuple[str, ...] = ()
    blocked_projects: tuple[str, ...] = ()
    sha256: str = ''


def canonical_media_path(path, project_path=None):
    path = Path(path)
    if not path.is_absolute() and project_path is not None:
        path = Path(project_path).parent / path
    return os.path.normcase(os.path.abspath(path))


def _identity(path):
    info = Path(path).lstat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _exists(path):
    """Permission/error is unknown, never an absent scope or receipt."""
    from .storage_service import safe_path
    path = Path(os.path.abspath(path))
    if not safe_path(path, (path.parent,)):
        raise ValueError(f'路径含链接或不可验证：{path}')
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def _checked(path, *, regular=True):
    from .storage_service import safe_path
    path = Path(os.path.abspath(path))
    if not safe_path(path, (path.parent,)):
        raise ValueError(f'路径含链接或不可验证：{path}')
    info = path.lstat()
    if regular and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise ValueError(f'文件类型或共享身份不安全：{path}')
    return _identity(path)


def _cancelled(cancel):
    return bool(cancel.is_set() if hasattr(cancel, 'is_set') else cancel() if cancel else False)


def _guard(cancel, deadline):
    if _cancelled(cancel):
        raise InterruptedError('检查已取消；保留缓存')
    if time.monotonic() > deadline:
        raise ValueError('检查达到时间上限；保留缓存')


def _read_json(path, cancel, deadline, limit=MAX_JSON_BYTES):
    _guard(cancel, deadline)
    before = _checked(path)
    if before[2] > limit:
        raise ValueError(f'文件超过读取上限：{path}')
    with Path(path).open('rb') as reader:
        info = os.fstat(reader.fileno())
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != before or info.st_nlink != 1:
            raise ValueError(f'文件在打开时变化：{path}')
        raw = reader.read(limit + 1)
    _guard(cancel, deadline)
    if len(raw) > limit or _checked(path) != before:
        raise ValueError(f'文件在读取时变化：{path}')
    try:
        payload = json.loads(raw.decode('utf-8-sig'))
    except RecursionError as exc:
        raise ValueError(f'JSON 嵌套超过读取能力：{path}') from exc
    return payload, before


def strong_media_references(payload, project_path):
    """Actual persisted media graph only. Malformed/unknown graphs raise."""
    if not isinstance(payload, dict) or type(payload.get('schema_version')) is not int or payload['schema_version'] != 1:
        raise ValueError('工程版本或根结构未知')
    media = payload.get('media')
    if not isinstance(media, dict):
        raise ValueError('工程 media 结构未知')
    refs = set()
    def add(value):
        if value is None or value == '':
            return
        if not isinstance(value, str) or '\x00' in value:
            raise ValueError('工程素材路径结构未知')
        normalized = canonical_media_path(value, project_path)
        from .storage_service import safe_path
        # A stored junction/symlink alias can name the same cache with a
        # different lexical path. Unknown aliases cannot prove no dependency.
        if not safe_path(normalized, (Path(normalized).parent,)):
            raise ValueError(f'工程素材引用含链接或无法核实：{value}')
        refs.add(normalized)
    add(media.get('path'))
    pool = payload.get('media_pool', [])
    if not isinstance(pool, list):
        raise ValueError('工程 media_pool 结构未知')
    assets = {}
    for asset in pool:
        if not isinstance(asset, dict) or not isinstance(asset.get('asset_id'), str) or not asset['asset_id'] or asset['asset_id'] in assets:
            raise ValueError('工程素材身份未知或重复')
        assets[asset['asset_id']] = asset.get('canonical_source')
        add(asset.get('canonical_source'))
    for kind in ('video_tracks', 'audio_tracks'):
        tracks = payload.get(kind, [])
        if not isinstance(tracks, list):
            raise ValueError(f'工程 {kind} 结构未知')
        for track in tracks:
            if not isinstance(track, dict) or not isinstance(track.get('clips', []), list):
                raise ValueError('工程轨道结构未知')
            for clip in track.get('clips', []):
                if not isinstance(clip, dict) or clip.get('asset_id') not in assets:
                    raise ValueError('工程片段引用未知素材')
                add(assets[clip['asset_id']])
                for key in ('source_path', 'path', 'canonical_source'):
                    add(clip.get(key))
    sequence = payload.get('edit_sequence', {})
    if not isinstance(sequence, dict) or not isinstance(sequence.get('segments', []), list):
        raise ValueError('工程 edit_sequence 结构未知')
    add(sequence.get('source_path'))
    for segment in sequence.get('segments', []):
        if not isinstance(segment, dict):
            raise ValueError('工程 segment 结构未知')
        add(segment.get('source_path'))
    return tuple(sorted(refs))


def saved_project_references(runtime_paths, watched_paths, *, cancel=None):
    """Bounded known project root plus the actual Library index's exact files.

    Keys preserve the caller's watched strings; comparison is lexical/case
    normalized. No report, backup, cache JSON or arbitrary drive is searched.
    """
    watched = tuple(dict.fromkeys(str(path) for path in watched_paths))
    wanted = {path: canonical_media_path(path) for path in watched}
    hits = {path: [] for path in watched}
    errors, projects, identities = [], {}, {}
    deadline = time.monotonic() + SCAN_SECONDS
    entries, total = 0, 0
    def remember(path, identity):
        identities[str(path)] = identity
    try:
        roots = [Path(os.path.abspath(runtime_paths.project_root))]
        studio = Path(runtime_paths.user_data_root) / 'SubtitleStudioPreview'
        settings = studio / 'settings.json'
        if _exists(settings):
            payload, identity = _read_json(settings, cancel, deadline, 1024 * 1024)
            remember(settings, identity); total += identity[2]
            if not isinstance(payload, dict):
                raise ValueError(f'工程库设置结构未知：{settings}')
            custom = payload.get('project_root', '')
            recent = payload.get('recent_projects', [])
            if not isinstance(custom, str) or not isinstance(recent, list) or len(recent) > MAX_PROJECTS:
                raise ValueError(f'工程库范围设置未知：{settings}')
            if custom.strip():
                root = Path(custom).expanduser()
                if not root.is_absolute() or root == root.parent:
                    raise ValueError(f'工程库设置路径不可限定：{settings}')
                roots.append(root)
            for entry in recent:
                if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
                    raise ValueError(f'最近工程设置结构未知：{settings}')
                path = Path(entry['path'])
                if not path.is_absolute() or path.suffix.lower() != '.2byteproj':
                    raise ValueError(f'最近工程路径未知：{settings}')
                projects[canonical_media_path(path)] = path
        else:
            remember(settings, ())
        stack = []
        for root in dict.fromkeys(roots):
            if _exists(root):
                stack.append((root, 0))
            else:
                remember(root, ())
        visited = set()
        while stack:
            _guard(cancel, deadline)
            folder, depth = stack.pop()
            if canonical_media_path(folder) in visited:
                continue
            visited.add(canonical_media_path(folder))
            before = _checked(folder, regular=False)
            if not folder.is_dir() or depth > MAX_DEPTH:
                raise ValueError(f'工程目录类型或深度无法核实：{folder}')
            remember(folder, before)
            with os.scandir(folder) as children:
                for child in children:
                    _guard(cancel, deadline)
                    entries += 1
                    if entries > MAX_ENTRIES:
                        raise ValueError(f'工程目录检查达到条目上限：{folder}')
                    path = Path(child.path)
                    info = child.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                        errors.append(f'工程范围内链接不可检查：{path}')
                    elif stat.S_ISDIR(info.st_mode):
                        stack.append((path, depth + 1))
                    elif path.suffix.lower() == '.2byteproj':
                        projects[canonical_media_path(path)] = path
                        if len(projects) > MAX_PROJECTS:
                            raise ValueError(f'工程检查达到数量上限：{path}')
            if _checked(folder, regular=False) != before:
                raise ValueError(f'工程目录在检查中变化：{folder}')
        index = studio / 'library-index.json'
        if _exists(index):
            payload, identity = _read_json(index, cancel, deadline)
            remember(index, identity); total += identity[2]
            if not isinstance(payload, dict) or payload.get('version') != 2 or not isinstance(payload.get('projects'), dict):
                raise ValueError(f'工程索引结构未知：{index}')
            for path, summary in payload['projects'].items():
                if not isinstance(path, str) or not Path(path).is_absolute() or Path(path).suffix.lower() != '.2byteproj' or not isinstance(summary, dict):
                    raise ValueError(f'工程索引路径未知：{index}')
                projects[canonical_media_path(path)] = Path(path)
                if len(projects) > MAX_PROJECTS:
                    raise ValueError(f'工程索引达到数量上限：{index}')
        else:
            remember(index, ())
        for path in projects.values():
            try:
                payload, identity = _read_json(path, cancel, deadline)
                total += identity[2]
                if total > MAX_TOTAL_JSON_BYTES:
                    raise ValueError(f'工程检查达到总读取上限：{path}')
                remember(path, identity)
                refs = set(strong_media_references(payload, path))
                for watched_path, normalized in wanted.items():
                    if normalized in refs:
                        hits[watched_path].append(str(path))
            except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
                errors.append(f'已保存工程不可核实：{path}（{exc}）')
    except (OSError, ValueError, TypeError, InterruptedError, RecursionError) as exc:
        errors.append(str(exc))
    result = ProjectReferenceScan(not errors, {path: tuple(values) for path, values in hits.items()},
        tuple(errors), tuple(str(path) for path in projects.values()), tuple(identities.items()))
    if result.complete and not project_reference_snapshot_current(result):
        return ProjectReferenceScan(False, result.references, ('工程范围在检查后变化；保留缓存',), result.projects, result.identities)
    return result


def project_reference_snapshot_current(result):
    try:
        return result.complete and all((_checked(path, regular=not Path(path).is_dir()) == identity if identity
            else not _exists(path)) for path, identity in result.identities)
    except (OSError, ValueError):
        return False


def _receipt_path(cache_item, runtime_paths):
    key = json.dumps([canonical_media_path(cache_item.path), list(cache_item.identity)], separators=(',', ':'))
    return Path(runtime_paths.user_data_root) / 'storage' / 'media-preservation' / (hashlib.sha256(key.encode('utf8')).hexdigest() + '.json')


def record_preserved_asset(cache_item, runtime_paths, asset_path, sha256):
    """One bounded receipt per cache identity, only after explicit checked copy."""
    if len(sha256) != 64 or any(c not in '0123456789abcdef' for c in sha256):
        raise ValueError('资产 SHA256 无效')
    cache_identity = _checked(cache_item.path)
    if cache_identity != tuple(cache_item.identity):
        raise ValueError('缓存身份在记录资产时变化')
    asset_identity = _checked(asset_path)
    if asset_identity[2] != cache_identity[2]:
        raise ValueError('资产大小与缓存不一致')
    receipt = _receipt_path(cache_item, runtime_paths)
    from .storage_service import safe_path
    if not safe_path(receipt, (Path(runtime_paths.user_data_root) / 'storage',)):
        raise ValueError('资产凭据目录含链接或无法核实')
    receipt.parent.mkdir(parents=True, exist_ok=True)
    old = None
    if _exists(receipt):
        payload, old = _read_json(receipt, None, time.monotonic() + SCAN_SECONDS, 16384)
        if not isinstance(payload, dict) or payload.get('version') != 1 or payload.get('producer') != 'save_cached_media_asset':
            raise ValueError('已有资产凭据归属未知，保留但不覆盖')
    payload = dict(version=1, producer='save_cached_media_asset', cache_path=str(Path(cache_item.path).absolute()),
        cache_identity=list(cache_identity), original_source=str(cache_item.source),
        asset_path=str(Path(asset_path).absolute()), asset_identity=list(asset_identity), sha256=sha256)
    temporary = receipt.with_name('.' + receipt.name + '.' + uuid.uuid4().hex + '.part')
    try:
        with temporary.open('x', encoding='utf8') as writer:
            json.dump(payload, writer, ensure_ascii=False); writer.flush(); os.fsync(writer.fileno())
        if not safe_path(receipt, (receipt.parent,)) or (old is not None and _checked(receipt) != old) or (old is None and os.path.lexists(receipt)):
            raise ValueError('资产凭据在发布时变化')
        os.replace(temporary, receipt)
    finally:
        if os.path.lexists(temporary) and safe_path(temporary, (receipt.parent,)):
            temporary.unlink()


def _hash_file(path, identity, cancel, deadline):
    _guard(cancel, deadline)
    if _checked(path) != identity or identity[2] > MAX_HASH_BYTES:
        raise ValueError(f'媒体身份变化或超过校验上限：{path}')
    digest = hashlib.sha256()
    with Path(path).open('rb') as reader:
        info = os.fstat(reader.fileno())
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != identity or info.st_nlink != 1:
            raise ValueError(f'媒体在打开时变化：{path}')
        while True:
            _guard(cancel, deadline)
            block = reader.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    if _checked(path) != identity:
        raise ValueError(f'媒体在校验中变化：{path}')
    return digest.hexdigest()


def verified_relinked_asset(cache_item, runtime_paths, *, cancel=None):
    """A positive result enables manual review only; callers retain all gates."""
    asset_path = ''
    try:
        if cache_item.category != 'media' or not cache_item.source or not cache_item.producer or cache_item.rebuild != 'local':
            raise ValueError('缓存归属或来源未核实')
        deadline = time.monotonic() + VERIFY_SECONDS
        receipt = _receipt_path(cache_item, runtime_paths)
        payload, receipt_identity = _read_json(receipt, cancel, deadline, 16384)
        if (not isinstance(payload, dict) or payload.get('version') != 1 or payload.get('producer') != 'save_cached_media_asset'
                or canonical_media_path(payload.get('cache_path', '')) != canonical_media_path(cache_item.path)
                or payload.get('cache_identity') != list(cache_item.identity)
                or payload.get('original_source') != cache_item.source):
            raise ValueError('资产凭据与当前缓存不一致')
        asset_path = payload['asset_path']
        if not isinstance(asset_path, str) or not Path(asset_path).is_absolute() or canonical_media_path(asset_path) in {canonical_media_path(cache_item.path), canonical_media_path(cache_item.source)}:
            raise ValueError('资产路径未知或不是独立副本')
        cache_identity = tuple(payload['cache_identity']); asset_identity = tuple(payload['asset_identity'])
        digest = payload['sha256']
        if len(asset_identity) != 4 or any(type(value) is not int for value in asset_identity) or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError('资产凭据身份或 SHA256 结构未知')
        if _hash_file(cache_item.path, cache_identity, cancel, deadline) != digest or _hash_file(asset_path, asset_identity, cancel, deadline) != digest:
            raise ValueError('缓存或独立资产完整 SHA256 校验失败')
        refs = saved_project_references(runtime_paths, [asset_path, cache_item.path, cache_item.source], cancel=cancel)
        if not refs.complete:
            raise ValueError('；'.join(refs.errors[:4]))
        blocked = tuple(dict.fromkeys((*refs.references[cache_item.path], *refs.references[cache_item.source])))
        if blocked:
            return RelinkedAssetVerification(False, '已保存工程仍依赖旧素材或缓存：' + '；'.join(blocked[:4]), asset_path,
                refs.references[asset_path], blocked, digest)
        if not refs.references[asset_path]:
            raise ValueError('尚无已保存工程使用独立资产；请正常重新定位素材并保存工程')
        _guard(cancel, deadline)
        if (_checked(receipt) != receipt_identity or _checked(asset_path) != asset_identity or _checked(cache_item.path) != cache_identity
                or not project_reference_snapshot_current(refs)):
            raise ValueError('资产或工程在检查后变化')
        return RelinkedAssetVerification(True, '独立资产完整校验通过，已保存工程已重新关联；旧缓存仅可手动确认清理',
            asset_path, refs.references[asset_path], sha256=digest)
    except (OSError, ValueError, TypeError, KeyError, InterruptedError, RecursionError) as exc:
        return RelinkedAssetVerification(False, '缓存继续保护：' + str(exc), asset_path)
