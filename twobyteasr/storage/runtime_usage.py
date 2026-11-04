"""Real disk use of the managed runtimes folder, counting each physical file once.

2026-10-16 (user: "runtimes takes 17 GB"): runtimes are installed from uv's
download cache as hard links, so Explorer adds the same PyTorch files once per
link. This walk keys files by (volume, file ID): what the folder really holds,
how much Explorer-style adding shows, and how much only the download cache
holds (the most that cache maintenance can free).
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

CACHE_FOLDER = 'download-cache'


@dataclass(frozen=True)
class RuntimeUsage:
    unique_bytes: int = 0       # every physical file once
    logical_bytes: int = 0      # every link added up, as Explorer's folder size does
    cache_only_bytes: int = 0   # files that only the download cache links to
    file_count: int = 0
    deduplicated: bool = True   # False when the volume reports no file IDs
    complete: bool = True


def _reparse(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def runtime_disk_usage(managed: Path, cancel=lambda: False) -> RuntimeUsage | None:
    """Walk ``managed`` without following links; None when it does not exist."""
    managed = Path(managed)
    try:
        if not managed.is_dir() or _reparse(managed.lstat()):
            return None
    except OSError:
        return None
    sizes, outside_cache, cache_ids = {}, set(), set()
    logical = files = 0
    deduplicated = complete = True
    for directory, dirs, names in os.walk(managed, followlinks=False):
        if cancel():
            complete = False
            break
        in_cache = Path(directory).is_relative_to(managed / CACHE_FOLDER)
        kept = []
        for name in dirs:
            try:
                if not _reparse((Path(directory) / name).lstat()):
                    kept.append(name)
            except OSError:
                complete = False
        dirs[:] = kept
        for name in names:
            try:
                # DirEntry.stat leaves st_ino at 0 on Windows; lstat reads the file ID.
                info = (Path(directory) / name).lstat()
            except OSError:
                complete = False
                continue
            if _reparse(info):
                continue
            files += 1
            logical += info.st_size
            if info.st_ino:
                key = (info.st_dev, info.st_ino)
            else:
                deduplicated = False
                key = ('path', os.path.join(directory, name))
            sizes[key] = info.st_size
            (cache_ids if in_cache else outside_cache).add(key)
    return RuntimeUsage(unique_bytes=sum(sizes.values()), logical_bytes=logical,
                        cache_only_bytes=sum(sizes[key] for key in cache_ids - outside_cache),
                        file_count=files, deduplicated=deduplicated, complete=complete)
