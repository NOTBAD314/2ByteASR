"""Recoverable, bounded GIF frames. No playback clock and no Qt dependency.

Pillow performs GIF local-frame/disposal composition sequentially once in the
ingest worker. Composed RGBA PNGs and original delays live in an atomic SQLite
cache; readers load only demanded frames, with a byte-bounded LRU.
"""
from __future__ import annotations
from bisect import bisect_right
from collections import OrderedDict
from contextlib import closing
import hashlib
import io
import json
from math import gcd
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

SCHEMA = 1
MEMORY_BYTES = 16 * 1024 * 1024
DISK_BYTES = 1024 * 1024 * 1024
MAX_ASSET_BYTES = 512 * 1024 * 1024
MAX_FRAME_PIXELS = 16_777_216
_build_lock = threading.Lock()


def is_gif(path):
    return str(path).lower().endswith('.gif')


def sampling_fps(metadata):
    """A frame lattice preserving every GIF delay boundary, not average FPS."""
    step = 0
    for duration in metadata['frame_durations_ms']:
        step = gcd(step, int(duration))
    return 1000. / max(10, step)


def _cancel(cancelled):
    if cancelled and cancelled():
        raise InterruptedError('GIF 解析已取消')


def _root():
    from ..runtime_paths import user_data_root
    return user_data_root() / 'SubtitleStudioPreview' / 'cache' / 'animated-gif-v1'


def _identity(source):
    stat = source.stat()
    return dict(path=str(source), size=stat.st_size, mtime_ns=stat.st_mtime_ns, schema=SCHEMA)


def _manifest(path):
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as db:
        data = json.loads(db.execute('select json from metadata').fetchone()[0])
        if db.execute('select count(*) from frames').fetchone()[0] != data['frame_count']:
            raise ValueError('GIF 帧缓存不完整')
        return data


def prepare_gif(path, *, cancelled=None):
    """Background-only on a cache miss; no decoded animation is held in RAM."""
    from PIL import Image
    source = Path(path).resolve()
    identity = _identity(source)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    root = _root()
    target = root / f'{key}.sqlite'
    _cancel(cancelled)
    # SQLite commit + replace publishes only complete animations. Multiple
    # processes may build the same identity; each owns its temporary file.
    with _build_lock:
        if target.is_file():
            try:
                data = _manifest(target)
                if data['identity'] == identity:
                    return target, data
            except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
                pass
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / f'{key}.{uuid.uuid4().hex}.building'
        started = time.perf_counter()
        try:
            with Image.open(source) as gif, closing(sqlite3.connect(temporary)) as db:
                if gif.format != 'GIF':
                    raise ValueError('文件内容不是有效 GIF')
                if gif.width * gif.height > MAX_FRAME_PIXELS:
                    raise ValueError('GIF 单帧超过 1600 万像素，请先缩小素材尺寸')
                loop = gif.info.get('loop')
                db.execute('create table frames (id integer primary key, png blob not null)')
                db.execute('create table metadata (json text not null)')
                starts, durations, elapsed, stored = [], [], 0, 0
                index = 0
                while True:
                    _cancel(cancelled)
                    try:
                        gif.seek(index)
                    except EOFError:
                        break
                    # GIF delays are centiseconds. Missing/zero delays receive
                    # one explicit 100ms fallback, shared by every consumer.
                    duration = int(gif.info.get('duration') or 100)
                    duration = max(10, duration)
                    rgba = gif.convert('RGBA')
                    buffer = io.BytesIO()
                    rgba.save(buffer, format='PNG', compress_level=1)
                    payload = buffer.getvalue()
                    stored += len(payload)
                    if stored > MAX_ASSET_BYTES or index >= 100_000:
                        raise ValueError('GIF 帧缓存超过 512 MB 或 10 万帧，请先缩小或裁短素材')
                    db.execute('insert into frames values (?, ?)', (index, payload))
                    starts.append(elapsed); durations.append(duration)
                    elapsed += duration
                    index += 1
                if not starts:
                    raise ValueError('GIF 没有可解码画面')
                data = dict(identity=identity, width=gif.width, height=gif.height,
                    frame_starts_ms=starts, frame_durations_ms=durations, duration_ms=elapsed,
                    frame_count=index, loop=loop, compressed_bytes=stored,
                    preparation_ms=round((time.perf_counter()-started)*1000, 2))
                db.execute('insert into metadata values (?)', (json.dumps(data),))
                db.commit()
            _cancel(cancelled)
            if _identity(source) != identity:
                raise ValueError('GIF 在解析期间发生变化，请重新导入')
            try:
                os.replace(temporary, target)
            except PermissionError:
                # An identical complete cache can already be open on Windows.
                if not target.is_file() or _manifest(target)['identity'] != identity:
                    raise
            _prune(root, target)
            return target, data
        finally:
            temporary.unlink(missing_ok=True)


def _prune(root, keep):
    files = []
    for path in root.glob('*.sqlite'):
        try:
            stat = path.stat()
            files.append((stat.st_mtime_ns, stat.st_size, path))
        except OSError:
            continue  # Another cache builder may already have evicted it.
    files.sort(reverse=True)
    used = keep.stat().st_size
    for _modified, size, item in files:
        if item == keep:
            continue
        if used + size > DISK_BYTES:
            try:
                item.unlink()
            except OSError:
                pass  # Active SQLite readers retain their cache on Windows.
        else:
            used += size


class GifFrames:
    def __init__(self, path, *, cancelled=None, memory_bytes=MEMORY_BYTES):
        self.source_path = str(Path(path).resolve())
        self.cache_path, self.metadata = prepare_gif(path, cancelled=cancelled)
        self.db = sqlite3.connect(f'{self.cache_path.as_uri()}?mode=ro', uri=True)
        self.cache = OrderedDict()
        self.memory_bytes = max(0, int(memory_bytes))
        self.cached_bytes = self.loads = 0

    def frame_at(self, source_ms, max_size=None):
        """Return BGRA pixels, unwrapped start/end and frame id for a demand."""
        from PIL import Image
        meta = self.metadata
        source_ms = max(0., float(source_ms))
        cycle = int(source_ms // meta['duration_ms'])
        local = source_ms % meta['duration_ms']
        index = max(0, bisect_right(meta['frame_starts_ms'], local)-1)
        width, height = meta['width'], meta['height']
        if max_size:
            scale = min(1., max_size[0]/width, max_size[1]/height)
            width, height = max(1, round(width*scale)), max(1, round(height*scale))
        key = (index, width, height)
        pixels = self.cache.get(key)
        if pixels is None:
            row = self.db.execute('select png from frames where id=?', (index,)).fetchone()
            if row is None:
                raise ValueError('GIF 帧缓存损坏，请重新导入素材以重建')
            with Image.open(io.BytesIO(row[0])) as image:
                image = image.convert('RGBA')
                if image.size != (width, height):
                    image = image.resize((width, height), Image.Resampling.LANCZOS)
                pixels = image.tobytes('raw', 'BGRA')
            self.loads += 1
            if len(pixels) <= self.memory_bytes:
                while self.cache and self.cached_bytes + len(pixels) > self.memory_bytes:
                    _, old = self.cache.popitem(last=False)
                    self.cached_bytes -= len(old)
                self.cache[key] = pixels
                self.cached_bytes += len(pixels)
        else:
            self.cache.move_to_end(key)
        start = cycle*meta['duration_ms'] + meta['frame_starts_ms'][index]
        return (width, height, pixels), start, start+meta['frame_durations_ms'][index], index

    def close(self):
        self.cache.clear()
        self.cached_bytes = 0
        self.db.close()
