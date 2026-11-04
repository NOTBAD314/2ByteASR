"""Explicitly preserve a sole cached media copy outside disposable cache roots."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import uuid


@dataclass(frozen=True)
class MediaAssetResult:
    status: str
    source: str
    destination: str
    logical_bytes: int = 0
    sha256: str = ''
    detail: str = ''


def _identity(path):
    info = path.lstat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _destination(path, service):
    from .storage_service import safe_path
    path = Path(os.path.abspath(path))
    if not path.parent.is_dir() or not safe_path(path, (path.parent,)):
        raise ValueError('资产目标目录不可用或含链接，请选择真实工程资产目录')
    if os.path.lexists(path): raise FileExistsError('目标已存在；请选择新文件名，不覆盖现有文件')
    for root in service.roots:
        if path.is_relative_to(Path(root).absolute()):
            raise ValueError('资产必须保存在应用缓存范围之外，避免后续维护误认为临时文件')
    return path


def save_cached_media_asset(service, item, destination, *, cancel=None):
    """Copy after a fresh ownership check, retain the source, never edit a project."""
    from .storage_service import safe_path
    cancelled = cancel.is_set if hasattr(cancel, 'is_set') else (cancel or (lambda: False))
    source = Path(item.path); target = Path(destination); temporary = None; published = False
    try:
        if cancelled(): raise InterruptedError('保存已取消')
        target = _destination(target, service)
        if item.category != 'media' or source.suffix.lower() not in {'.mp4', '.mkv', '.mov', '.avi', '.webm'}:
            raise ValueError('请选择有来源登记的中间媒体文件，不能把元数据或任意视频当作缓存资产')
        if not safe_path(source, service.roots) or not stat.S_ISREG(source.lstat().st_mode):
            raise ValueError('中间媒体路径为链接、越界或不可读取')
        # Re-run the producer/legacy contract rather than trusting the tree row.
        from types import SimpleNamespace
        fresh = service.scan(SimpleNamespace(is_set=cancelled), include_models=False)
        if fresh.cancelled or cancelled(): raise InterruptedError('保存已取消')
        current = next((value for value in fresh.items if value.path == item.path), None)
        if (not current or current.category != 'media' or not current.producer or
                current.rebuild != 'local' or current.identity != item.identity or
                current.source != item.source):
            raise ValueError('缓存归属、来源或文件身份已变化，请重新扫描')
        if not current.source or Path(current.source).is_file():
            raise ValueError('此操作用于原素材不可访问时保留唯一缓存副本，请重新检查素材状态')
        if shutil.disk_usage(target.parent).free < current.size + 1024 * 1024:
            raise OSError('目标磁盘空间不足；未生成资产副本')
        temporary = target.with_name('.' + target.name + '.' + uuid.uuid4().hex + '.part')
        if not safe_path(temporary, (target.parent,)):
            raise ValueError('资产暂存路径不安全')
        digest = hashlib.sha256(); copied = 0
        with service.lease(source), source.open('rb') as reader, temporary.open('xb') as writer:
            if not safe_path(source, service.roots) or _identity(source) != item.identity:
                raise ValueError('缓存文件在保存前已变化，请重新扫描')
            while True:
                if cancelled(): raise InterruptedError('保存已取消')
                block = reader.read(1024 * 1024)
                if not block: break
                writer.write(block); digest.update(block); copied += len(block)
            writer.flush(); os.fsync(writer.fileno())
            writer.close()  # Windows publication requires the writer's handle closed.
            written_identity = _identity(temporary)
            if copied != current.size or not safe_path(source, service.roots) or _identity(source) != item.identity:
                raise ValueError('缓存文件在复制过程中已变化，未发布资产')
            if Path(current.source).is_file():
                raise ValueError('原素材状态在复制过程中已变化，请重新扫描后选择保留方式')
            verify = hashlib.sha256()
            with temporary.open('rb') as check:
                while True:
                    if cancelled(): raise InterruptedError('保存已取消')
                    block = check.read(1024 * 1024)
                    if not block: break
                    verify.update(block)
            if verify.digest() != digest.digest(): raise OSError('资产副本SHA256校验失败')
            target = _destination(target, service)
            if (not safe_path(temporary, (target.parent,)) or temporary.stat().st_nlink != 1 or
                    _identity(temporary) != written_identity or not safe_path(source, service.roots) or
                    _identity(source) != item.identity):
                raise ValueError('资产暂存文件被替换或共享，未发布')
            if cancelled(): raise InterruptedError('保存已取消')
            if os.name == 'nt':
                os.rename(temporary, target)  # Windows refuses an existing destination.
            else:
                os.link(temporary, target)  # Atomic no-overwrite publication on POSIX.
                temporary.unlink()
            temporary = None
            published = True
            from .storage_media_preservation import record_preserved_asset
            record_preserved_asset(current, service.paths, target, digest.hexdigest())
        return MediaAssetResult('saved', str(source), str(target), copied, digest.hexdigest(),
            '已校验并保存独立媒体资产；原缓存保留。请在工作台重新定位素材后保存工程。')
    except InterruptedError as exc:
        return MediaAssetResult('cancelled', str(source), str(target), detail=str(exc))
    except (OSError, ValueError) as exc:
        if published:
            return MediaAssetResult('saved', str(source), str(target), copied, digest.hexdigest(),
                '资产副本已保存并通过SHA256校验；原缓存保留。资产凭据或租约结束记录未完成：' + str(exc))
        return MediaAssetResult('failed', str(source), str(target), detail=str(exc))
    finally:
        if temporary is not None:
            try:
                if not any(p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & 0x400
                           for p in (temporary, *temporary.parents) if os.path.lexists(p)):
                    temporary.unlink(missing_ok=True)
            except OSError: pass
