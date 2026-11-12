"""The 2ByteASR bunny keychain, rebuilt from the user's PNGTuber Remix model.

2026-11-02 (user, loading pages): the loading surfaces use the bunny from
``兔子.pngRemix``. ``assets/mascot/bunny/rig.json`` lists its 26 layers in paint
order with the model's pivots and clip masks (glare clipped to the glasses
and the key ring). The widget blinks (open/closed eye layers), talks
(mouth layers), wiggles both ears around their roots, sweeps the glare and
bobs or swings around the key ring. Sad closes the eyes and drops the ears;
happy hops. Missing assets leave an empty widget, never an error.
"""
from __future__ import annotations

import json
import math
import random
import time
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

FRAME_MS = 16


def mascot_root() -> Path:
    from ..runtime_paths import detect_install_root
    return detect_install_root() / 'assets' / 'mascot' / 'bunny'


@lru_cache(maxsize=1)
def load_rig():
    """(rig dict, {file: QPixmap}) or None when the assets are not installed."""
    root = mascot_root()
    try:
        rig = json.loads((root / 'rig.json').read_text('utf-8'))
    except (OSError, ValueError):
        return None
    images = {}
    for layer in rig.get('layers', ()):
        for name in (layer.get('img'), layer.get('mask')):
            if name and name not in images:
                pixmap = QPixmap(str(root / name))
                if pixmap.isNull():
                    return None
                images[name] = pixmap
    # Preserve PNGs and authored pivots. Crop only fully transparent margins
    # AFTER scaling, so pixel phase and the original animation are unchanged.
    try:
        import hashlib
        manifest=json.loads((root/'alpha-bounds.json').read_text('utf-8'))
        rig['_alpha_bounds']={name:entry['box'] for name,entry in manifest.get('images',{}).items()
            if name in images and hashlib.sha256((root/name).read_bytes()).hexdigest()==entry['sha256']}
    except (OSError,ValueError,KeyError):rig['_alpha_bounds']={}
    return rig, images


@lru_cache(maxsize=8)
def bunny_face_pixmap(size: int, ratio: float = 1.0) -> QPixmap:
    """A round crop of the bunny's face (progress knobs, small badges)."""
    side = max(1, round(size * ratio))
    out = QPixmap(side, side)
    out.fill(Qt.GlobalColor.transparent)
    source = QPixmap(str(mascot_root() / 'bunny_face.png'))
    if source.isNull():
        return out
    # Face centre and span in the trimmed composite (561 x 664).
    crop = QRectF(283 - 200, 470 - 200, 400, 400)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, side, side))
    painter.setClipPath(clip)
    painter.drawPixmap(QRectF(0, 0, side, side), source, crop)
    painter.end()
    out.setDevicePixelRatio(ratio)
    return out


class BunnyMascot(QWidget):
    """``motion``: ``bob`` (sitting, gentle bounce) or ``swing`` (hanging from the ring)."""

    def __init__(self, parent=None, *, height: int = 150, motion: str = 'bob'):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.motion = motion
        self.mood = 'idle'
        self._talk_until = 0.0
        self._open_until = 0.0
        self._hop_from = -1.0
        self.stretch = 0.0               # >0 taller and thinner, <0 squashed (the tutorial's puck)
        self.impact_offset = QPointF()  # paint-only; never changes physics or window geometry
        self._started = time.perf_counter()
        self._next_blink = self._started + 1.2
        self._blink_until = 0.0
        self._scaled = None
        self._scale_key = None
        from .mascot_assets import provider
        self._assets = provider()
        self._assets.ready.connect(self._assets_ready)
        self.rig = (self._assets.rig, {}) if self._assets.rig else None
        self.trim = (self.rig[0]['trim'] if self.rig else [0, 0, 1, 1])
        self.set_mascot_height(height)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self.update)
        from .ui_motion import system_reduced_motion
        self.reduced_motion = system_reduced_motion()

    @property
    def available(self) -> bool:
        return self.rig is not None

    def set_mascot_height(self, height: int) -> None:
        self.mascot_height = int(height)
        self.scale = self.mascot_height / float(self.trim[3])
        # Room for the hop above and the swing on both sides.
        self.pad_x = round(self.trim[2] * self.scale * 0.12)
        self.pad_top = round(self.mascot_height * 0.14)
        self.setFixedSize(QSize(round(self.trim[2] * self.scale) + 2 * self.pad_x,
                                self.mascot_height + self.pad_top + round(self.mascot_height * 0.06)))

    # -------------------------------------------------------------- control
    def talk(self, seconds: float = 0.7) -> None:
        self._talk_until = time.perf_counter() + seconds
        self.update()

    def open_mouth(self, seconds: float = 0.08) -> None:
        """One syllable (2026-11-11, the tutorial's babble): the mouth opens now, not on the next flap."""
        self._open_until = time.perf_counter() + seconds
        self.update()

    def hop(self) -> None:
        """One small jump (a click on the tutorial bunny)."""
        self._hop_from = time.perf_counter()
        self.update()

    def set_mood(self, mood: str) -> None:
        if mood != self.mood:
            self.mood = mood
            self.update()

    def showEvent(self, event):
        if self.available and not self.reduced_motion:
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------- painting
    def _layers(self):
        """Demand shared, background-prepared layers for this size and DPI."""
        ratio = self.devicePixelRatioF()
        key = self._assets.request(self.mascot_height, ratio)
        cached = self._assets.cache.get(key)
        if cached is not None and self._scale_key != key:
            self._scaled, offsets, _size = cached
            self._scaled_offsets = {name: QPointF(*offset) for name, offset in offsets.items()}
            self._scale_key = key
        return self._scaled

    @Slot(object)
    def _assets_ready(self, key):
        if key == (self.mascot_height, self.devicePixelRatioF()):
            self.update()

    def _eyes_closed(self, now):
        if self.mood == 'sad':
            return True
        if now >= self._next_blink and now >= self._blink_until:
            self._blink_until = now + 0.14
            self._next_blink = now + 2.2 + random.random() * 2.6
        return now < self._blink_until and not self.reduced_motion

    def _mouth_open(self, now):
        return now < self._open_until or (now < self._talk_until and int(now / 0.11) % 2 == 0)

    HOP_S = 0.42

    def _hop_lift(self, now):
        k = (now - self._hop_from) / self.HOP_S
        return math.sin(math.pi * k) if 0.0 <= k < 1.0 and not self.reduced_motion else 0.0

    def paintEvent(self, _event):
        if not self.available:
            return
        rig, _images = self.rig
        layers = self._layers()
        if layers is None:
            painter = QPainter(self)
            face = bunny_face_pixmap(self.mascot_height, self.devicePixelRatioF())
            painter.drawPixmap(QPointF(self.pad_x, self.pad_top), face)
            painter.end()
            return
        now = time.perf_counter()
        t = 0.0 if self.reduced_motion else now - self._started
        s = self.scale
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(self.impact_offset)
        # Canvas origin so the trimmed bunny sits at (pad_x, pad_top).
        painter.translate(self.pad_x - self.trim[0] * s, self.pad_top - self.trim[1] * s)
        lift = self._hop_lift(now)
        if lift:
            painter.translate(0, -lift * 70 * s)
        feet = QPointF(455 * s, 650 * s)
        if self.stretch:   # 2026-11-11: picked up it stretches, landing it squashes (about its feet)
            painter.translate(feet)
            painter.scale(1 - 0.5 * self.stretch, 1 + self.stretch)
            painter.translate(-feet)
        ring = QPointF(rig['ring'][0] * s, rig['ring'][1] * s)
        if self.mood == 'sad':
            self._rotate(painter, feet, -9)
            painter.translate(0, 10 * s)
        elif self.mood == 'happy':
            painter.translate(0, -abs(math.sin(t * math.pi / 0.5)) * 40 * s)
            self._rotate(painter, feet, 3 * math.sin(t * math.pi / 0.5))
        elif self.motion == 'swing':
            self._rotate(painter, ring, 6 * math.sin(t * 2 * math.pi / 3.2))
        else:
            painter.translate(0, -(0.5 - 0.5 * math.cos(t * 2 * math.pi / 2.4)) * 16 * s)
            self._rotate(painter, feet, 1.5 * math.sin(t * 2 * math.pi / 2.4))
        closed, talking = self._eyes_closed(now), self._mouth_open(now)
        for layer in rig['layers']:
            role = layer.get('role') or ''
            if (role == 'blink' and not closed) or (role == 'eyes' and closed) \
                    or (role == 'mouthOpen' and not talking) or (role == 'mouthClosed' and talking):
                continue
            pixmap = layers[layer['img']]
            at = QPointF(layer['shift'][0] * s, layer['shift'][1] * s) + self._scaled_offsets[layer['img']]
            painter.save()
            angle = self._layer_angle(layer['name'], t)
            if angle:
                self._rotate(painter, QPointF(layer['pivot'][0] * s, layer['pivot'][1] * s), angle)
            if layer.get('mask'):
                self._draw_glare(painter, layer, pixmap, layers[layer['mask']], at, t)
            else:
                painter.drawPixmap(at, pixmap)
            painter.restore()
        painter.end()

    @staticmethod
    def _rotate(painter, pivot, degrees):
        if degrees:
            painter.translate(pivot)
            painter.rotate(degrees)
            painter.translate(-pivot)

    def _layer_angle(self, name, t):
        if self.mood == 'sad':
            return {'左耳': -24, '右耳': 22}.get(name, 0)
        if self.reduced_motion:
            return 0
        wave = lambda period, delay=0.0: math.sin((t - delay) * 2 * math.pi / period)  # noqa: E731
        return {'左耳': -4.5 + 4.5 * wave(2.6), '右耳': 5 - 5 * wave(2.6, .3),
                '头饰': -4 + 4 * wave(3.4)}.get(name, 0)

    def _draw_glare(self, painter, layer, pixmap, mask, at, t):
        """Glare sweeping across its parent, clipped to the parent's pixels."""
        s = self.scale
        period, delay = 3.6, (1.4 if layer['name'] == '反光2' else 0.0)
        phase = ((t - delay) % period) / period
        k = 0.0 if phase < .55 else 1.0 if phase > .85 else (phase - .55) / .30
        offset = QPointF((-260 + 520 * k) * s, (120 - 240 * k) * s)
        ratio = self.devicePixelRatioF()
        canvas = QPixmap(mask.size())
        canvas.setDevicePixelRatio(ratio)
        canvas.fill(Qt.GlobalColor.transparent)
        mask_at = QPointF(layer['maskShift'][0] * s, layer['maskShift'][1] * s) + self._scaled_offsets[layer['mask']]
        inner = QPainter(canvas)
        inner.drawPixmap(at + offset - mask_at, pixmap)
        inner.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        inner.drawPixmap(QPointF(0, 0), mask)
        inner.end()
        painter.drawPixmap(mask_at, canvas)


__all__ = ['BunnyMascot', 'bunny_face_pixmap', 'load_rig', 'mascot_root']
