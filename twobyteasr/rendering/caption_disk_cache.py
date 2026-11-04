"""Disposable, content-addressed static caption frames, used only on workers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from PySide6.QtGui import QImage


class CaptionDiskCache:
    SCHEMA = 'static-caption-scene-v1'
    MAX_BYTES = 512 * 1024 * 1024
    MAX_ENTRIES = 8192

    def __init__(self, root=None, *, max_bytes=MAX_BYTES, max_entries=MAX_ENTRIES):
        if root is None:
            from ..projects.studio_project import studio_data_root
            root = studio_data_root() / 'caption-scene-cache'
        self.root = Path(root)
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.entries = None
        self.hits = self.misses = self.writes = self.evictions = self.errors = 0

    @classmethod
    def key(cls, dependencies):
        from .advanced_live_renderer import LIVE_RENDERER_VERSION
        return hashlib.sha256(repr((cls.SCHEMA, LIVE_RENDERER_VERSION, dependencies)).encode('utf-8')).hexdigest()

    def _scan(self):
        if self.entries is not None:
            return
        self.entries = {}
        self.root.mkdir(parents=True, exist_ok=True)
        for path in self.root.glob('*.png'):
            if len(path.stem) != 64 or any(c not in '0123456789abcdef' for c in path.stem) or path.is_symlink():
                continue
            try:
                meta = path.with_suffix('.json')
                info = path.stat()
                self.entries[path.stem] = (info.st_mtime, info.st_size + meta.stat().st_size)
            except OSError:
                continue
        self._trim()

    def _trim(self):
        size = sum(item[1] for item in self.entries.values())
        for key, (_, weight) in sorted(self.entries.items(), key=lambda row: row[1][0]):
            if size <= self.max_bytes and len(self.entries) <= self.max_entries:
                break
            for suffix in ('.png', '.json'):
                try:(self.root / (key+suffix)).unlink(missing_ok=True)
                except OSError:pass
            size -= weight
            self.entries.pop(key, None)
            self.evictions += 1

    def get(self, key):
        try:
            self._scan()
            if key in self.entries:
                meta = json.loads((self.root / (key+'.json')).read_text('utf-8'))
                image = QImage(str(self.root / (key+'.png')))
                if (meta.get('schema') == self.SCHEMA and not image.isNull()
                        and [image.width(), image.height()] == meta.get('size')):
                    self.hits += 1
                    now = time.time()
                    self.entries[key] = (now, self.entries[key][1])
                    os.utime(self.root / (key+'.png'), (now, now))
                    return image.convertToFormat(QImage.Format_ARGB32_Premultiplied), meta['rows']
        except (OSError, ValueError, KeyError, TypeError):
            self.errors += 1
        self.misses += 1
        return None

    def put(self, key, image, rows):
        temporary = self.root / (key+'.'+uuid.uuid4().hex+'.tmp')
        metadata = temporary.with_suffix('.json.tmp')
        try:
            self._scan()
            if not image.save(str(temporary), 'PNG'):
                return
            payload = dict(schema=self.SCHEMA, size=[image.width(), image.height()], rows=rows)
            metadata.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), 'utf-8')
            weight = temporary.stat().st_size + metadata.stat().st_size
            if weight > self.max_bytes:
                return
            os.replace(temporary, self.root / (key+'.png'))
            os.replace(metadata, self.root / (key+'.json'))
            self.entries[key] = (time.time(), weight)
            self.writes += 1
            self._trim()
        except (OSError, ValueError, TypeError):
            self.errors += 1  # Cache failure never fails the current frame.
        finally:
            for path in (temporary, metadata):
                try:path.unlink(missing_ok=True)
                except OSError:pass

    def stats(self):
        return dict(hits=self.hits, misses=self.misses, writes=self.writes, evictions=self.evictions,
                    errors=self.errors, entries=len(self.entries or {}),
                    bytes=sum(row[1] for row in (self.entries or {}).values()),
                    budget_bytes=self.max_bytes, max_entries=self.max_entries)
