"""Decode/scale the authored PNG rig off the GUI; publish bounded pixmaps on it."""
from collections import OrderedDict
import hashlib
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

MAX_BYTES = 24 * 1024 * 1024


class MascotAssets(QObject):
    decoded = Signal(object)
    ready = Signal(object)

    def __init__(self, app):
        super().__init__(app)
        from .bunny_mascot import mascot_root
        self.root = mascot_root()
        try:
            self.rig = json.loads((self.root / 'rig.json').read_text('utf8'))
        except (OSError, ValueError):
            self.rig = None
        self.cache = OrderedDict()
        self.pending = set()
        self.failed = set()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='mascot-assets')
        self.bytes = 0
        self.decoded.connect(self.commit, Qt.ConnectionType.QueuedConnection)

    def request(self, height, ratio):
        key = (int(height), float(ratio))
        if key in self.cache:
            self.cache.move_to_end(key)
        elif (key not in self.pending and key not in self.failed and self.rig is not None
              and len(self.pending) < 4):
            self.pending.add(key)
            def decode():
                images, offsets = {}, {}
                error = ''
                try:
                    manifest = json.loads((self.root / 'alpha-bounds.json').read_text('utf8'))
                    bounds = manifest.get('images', {})
                    factor = height / self.rig['trim'][3] * ratio
                    for layer in self.rig['layers']:
                        for name in (layer.get('img'), layer.get('mask')):
                            if not name or name in images:
                                continue
                            data = (self.root / name).read_bytes()
                            source = QImage.fromData(data)
                            if source.isNull():
                                raise ValueError('Invalid mascot image: '+name)
                            # Match QPixmap's premultiplied scaling. Filtering
                            # straight-alpha PNG channels changes translucent edges.
                            source = source.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                            image = source.scaled(max(1, round(source.width()*factor)), max(1, round(source.height()*factor)),
                                Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                            offset = (0, 0)
                            entry = bounds.get(name)
                            if entry and hashlib.sha256(data).hexdigest() == entry['sha256']:
                                box = entry['box']
                                sx, sy = image.width()/source.width(), image.height()/source.height()
                                left, top = max(0, math.floor(box[0]*sx)-4), max(0, math.floor(box[1]*sy)-4)
                                right, bottom = min(image.width(), math.ceil(box[2]*sx)+4), min(image.height(), math.ceil(box[3]*sy)+4)
                                image = image.copy(left, top, max(1,right-left), max(1,bottom-top))
                                offset = (left/ratio, top/ratio)
                            image.setDevicePixelRatio(ratio)
                            images[name], offsets[name] = image, offset
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    error = str(exc)
                try:
                    self.decoded.emit((key, images, offsets, error))
                except RuntimeError:
                    pass  # Application already closed; no callback outlives Qt.
            self.executor.submit(decode)
        return key

    @Slot(object)
    def commit(self, result):
        key, images, offsets, error = result
        self.pending.discard(key)
        if error:
            self.failed.add(key)
            import logging
            logging.getLogger(__name__).warning('Mascot preparation: %s', error)
            return
        size = sum(image.sizeInBytes() for image in images.values())
        if size > MAX_BYTES:
            self.failed.add(key)
            return
        while self.cache and (len(self.cache) >= 4 or self.bytes+size > MAX_BYTES):
            _, (_, _, old_size) = self.cache.popitem(last=False)
            self.bytes -= old_size
        self.cache[key] = ({name: QPixmap.fromImage(image) for name,image in images.items()}, offsets, size)
        self.bytes += size
        self.ready.emit(key)


def provider():
    app = QApplication.instance()
    from .bunny_mascot import mascot_root
    if not hasattr(app, '_mascot_assets') or app._mascot_assets.root != mascot_root():
        app._mascot_assets = MascotAssets(app)
    return app._mascot_assets
