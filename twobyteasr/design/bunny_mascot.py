"""The 2ByteASR bunny keychain, rebuilt from the user's PNGTuber Remix model.

2026-11-02 (user, loading pages): the loading surfaces use the bunny from
``兔子.pngRemix``. ``assets/mascot/bunny/rig.json`` lists its 26 layers in paint
order with the model's pivots and clip masks (glare clipped to the glasses
and the key ring). The widget blinks (open/closed eye layers), talks
(mouth layers), wiggles both ears around their roots, sweeps the glare and
bobs or swings around the key ring. Sad closes the eyes and drops the ears;
happy hops. Missing assets leave an empty widget, never an error.

2026-11-14 (「问问兔白」): ``play`` acts out a move, ``stick`` floats a sticker by her head and
``act`` does both (``bunny_moves``); ``ear_bias`` / ``lean`` / ``nudge`` let the chat turn her ears
toward something, lean her toward the input and sway her when the window is dragged.
``expression`` picks a layer whose role is ``"<role>:<name>"`` (new eyes or mouths the user draws,
added to rig.json) instead of the plain one, when the rig has it. ``clock`` can be replaced to
render frames at chosen times (the review page).
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


@lru_cache(maxsize=1)
def _still_source() -> QPixmap:
    return QPixmap(str(mascot_root() / 'bunny_face.png'))


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
        self.clock = time.perf_counter     # replaceable: rendering a move frame by frame
        self._move = None                  # (name, started)
        self._stickers = []                # [(name, started)]
        self.ear_bias = 0.0                # degrees: both ears lean toward something (positive: right)
        self.lean = 0.0                    # degrees: the whole bunny leans (toward the input box)
        self.lean_target = 0.0             # where ``lean`` is easing to (the chat eases it)
        self._sway = 0.0                   # a spring: the window was dragged, she swings after it
        self._sway_v = 0.0
        self._sway_at = 0.0
        self.expression = {}               # role -> expression name (D: the user's own new layers)
        self.stretch = 0.0               # >0 taller and thinner, <0 squashed (the tutorial's puck)
        self.impact_offset = QPointF()  # paint-only; never changes physics or window geometry
        self._started = self.clock()
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
        self._talk_until = self.clock() + seconds
        self.update()

    def open_mouth(self, seconds: float = 0.08) -> None:
        """One syllable (2026-11-11, the tutorial's babble): the mouth opens now, not on the next flap."""
        self._open_until = self.clock() + seconds
        self.update()

    def hop(self) -> None:
        """One small jump (a click on the tutorial bunny)."""
        self._hop_from = self.clock()
        self.update()

    def set_mood(self, mood: str) -> None:
        if mood != self.mood:
            self.mood = mood
            self.update()

    # ------------------------------------------------------- moves and stickers (2026-11-14)
    def play(self, name: str) -> bool:
        """Act out ``bunny_moves.MOVES[name]`` (a looping one runs until ``stop_move``)."""
        from .bunny_moves import MOVES
        if name not in MOVES or self.reduced_motion:
            return False
        self._move = (name, self.clock())
        self.update()
        return True

    def stop_move(self, name: str = '') -> None:
        if self._move is not None and (not name or self._move[0] == name):
            self._move = None
            self.update()

    @property
    def current_move(self) -> str:         # (not "move": that is QWidget.move)
        return self._move[0] if self._move is not None else ''

    def stick(self, name: str) -> bool:
        """Float ``bunny_moves.STICKERS[name]`` by her head (a looping one stays until ``unstick``)."""
        from .bunny_moves import STICKERS
        if name not in STICKERS or self.reduced_motion:
            return False
        self._stickers = [item for item in self._stickers if item[0] != name] + [(name, self.clock())]
        self.update()
        return True

    def unstick(self, name: str = '') -> None:
        self._stickers = [item for item in self._stickers if name and item[0] != name]
        self.update()

    @property
    def stickers(self) -> list:
        return [name for name, _started in self._stickers]

    def act(self, name: str) -> bool:
        """A named reaction (``bunny_moves.ACTS``): its move and its sticker together."""
        from .bunny_moves import ACTS
        act = ACTS.get(name)
        if act is None:
            return False
        played = self.play(act.move) if act.move else False
        stuck = self.stick(act.sticker) if act.sticker else False
        return played or stuck

    def nudge(self, push: float) -> None:
        """The window moved by ``push`` px: she swings after it a little (C7)."""
        if self.reduced_motion:
            return
        self._sway_v += max(-70.0, min(70.0, -push * 1.6))
        self.update()

    def _sway_step(self, now: float) -> float:
        dt = min(0.05, max(0.0, now - self._sway_at)) if self._sway_at else 0.0
        self._sway_at = now
        if dt and (self._sway or self._sway_v):
            self._sway_v += (-60.0 * self._sway - 7.0 * self._sway_v) * dt
            self._sway += self._sway_v * dt
            if abs(self._sway) < 0.05 and abs(self._sway_v) < 0.05:
                self._sway = self._sway_v = 0.0
        return max(-25.0, min(25.0, self._sway))

    def _pose(self, now: float):
        from .bunny_moves import MOVES
        if self._move is None:
            return None
        name, started = self._move
        move = MOVES[name]
        elapsed = now - started
        if not move.loop and elapsed >= move.seconds:
            self._move = None
            return None
        k = (elapsed % move.seconds) / move.seconds if move.loop else elapsed / move.seconds
        return move.pose(k, elapsed)

    # Looping stickers that stay until the chat takes them off (she is waiting / dozing). Any other
    # looping sticker is a reaction: it goes by itself. 2026-11-15 (user: "右边一直是晕着的") — the
    # dizzy stars looped forever because nothing ever took them off.
    HELD_STICKERS = frozenset({'dots', 'magnifier', 'zzz'})
    REACTION_STICKER_S = 3.6

    def _live_stickers(self, now: float):
        from .bunny_moves import STICKERS
        live = []
        for name, started in self._stickers:
            sticker = STICKERS[name]
            elapsed = now - started
            if not sticker.loop and elapsed >= sticker.seconds:
                continue
            if sticker.loop and name not in self.HELD_STICKERS and elapsed >= self.REACTION_STICKER_S:
                continue
            live.append((name, started))
        self._stickers = live
        return [(STICKERS[name], ((now - started) % STICKERS[name].seconds) / STICKERS[name].seconds
                 if STICKERS[name].loop else (now - started) / STICKERS[name].seconds) for name, started in live]

    STICKER_SCALE = 1.3

    @staticmethod
    def _draw_paws(painter, pixmap, at, paws, s):
        """The paws layer as two paws (left of x 458, right of it), each with its own shift and turn."""
        ratio = pixmap.devicePixelRatio() or 1.0
        width, height = pixmap.width() / ratio, pixmap.height() / ratio
        split = 458 * s - at.x()
        for side, pivot_x in (('left', 425), ('right', 492)):
            dx, dy, turn, *rest = paws.get(side, (0.0, 0.0, 0.0))
            grow = rest[0] if rest else 1.0          # a paw held out is drawn bigger, so a wave reads
            painter.save()
            painter.translate(dx * s, dy * s)
            pivot = QPointF(pivot_x * s, 612 * s)
            if turn or grow != 1.0:
                painter.translate(pivot)
                painter.rotate(turn)
                painter.scale(grow, grow)
                painter.translate(-pivot)
            clip = QRectF(at.x(), at.y(), split, height) if side == 'left' else QRectF(at.x() + split, at.y(), width - split, height)
            painter.setClipRect(clip)
            painter.drawPixmap(at, pixmap)
            painter.restore()

    @staticmethod
    def _draw_flash(painter, centre, radius, strength):
        """A four-pointed white star with a soft glow: the glasses catching the light."""
        from PySide6.QtGui import QColor, QPainterPath, QRadialGradient
        glow = QRadialGradient(centre, radius * 1.4)
        light = QColor(255, 255, 255)
        light.setAlphaF(0.75 * strength)
        glow.setColorAt(0.0, light)
        light.setAlphaF(0.0)
        glow.setColorAt(1.0, light)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(centre, radius * 1.4, radius * 1.4)
        path = QPainterPath()
        for i in range(8):
            r = radius if i % 2 == 0 else radius * .18
            a = math.radians(-90 + i * 45)
            point = QPointF(centre.x() + math.cos(a) * r, centre.y() + math.sin(a) * r)
            path.moveTo(point) if i == 0 else path.lineTo(point)
        path.closeSubpath()
        star = QColor(255, 255, 255)
        star.setAlphaF(min(1.0, 1.2 * strength))
        painter.setBrush(star)
        painter.drawPath(path)

    def _variant(self, role: str) -> str:
        """The role to draw for ``role``: an expression layer when one is chosen and present."""
        name = self.expression.get(role)
        if name and self.rig is not None and any(layer.get('role') == f'{role}:{name}' for layer in self.rig[0]['layers']):
            return f'{role}:{name}'
        return role

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
            # Her layers are still being prepared: the whole still picture at her real size.
            # 2026-11-15 (user): this used to be a round crop of her face blown up to her full
            # height, so on opening (the chat and the tutorial) she looked huge for a moment.
            still = _still_source()
            if not still.isNull():
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawPixmap(QRectF(self.pad_x, self.pad_top, self.trim[2] * self.scale, self.mascot_height),
                                   still, QRectF(still.rect()))
                painter.end()
            return
        now = self.clock()
        t = 0.0 if self.reduced_motion else now - self._started
        s = self.scale
        pose = self._pose(now)
        sway = self._sway_step(now)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(self.impact_offset)
        # Canvas origin so the trimmed bunny sits at (pad_x, pad_top).
        painter.translate(self.pad_x - self.trim[0] * s, self.pad_top - self.trim[1] * s)
        painter.save()                       # the stickers are drawn from here, not turned with her
        lift = self._hop_lift(now)
        if lift:
            painter.translate(0, -lift * 70 * s)
        feet = QPointF(455 * s, 650 * s)
        if self.stretch:   # 2026-11-11: picked up it stretches, landing it squashes (about its feet)
            painter.translate(feet)
            painter.scale(1 - 0.5 * self.stretch, 1 + self.stretch)
            painter.translate(-feet)
        ring = QPointF(rig['ring'][0] * s, rig['ring'][1] * s)
        if sway or self.lean:
            self._rotate(painter, ring if self.motion == 'swing' else feet, sway + self.lean)
        if pose is not None and not pose.base:
            pass
        elif self.mood == 'sad':
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
        if pose is not None:
            if pose.dx or pose.dy:
                painter.translate(pose.dx * s, pose.dy * s)
            if pose.turn:
                self._rotate(painter, feet, pose.turn)
            if pose.sx != 1.0 or pose.sy != 1.0:
                painter.translate(feet)
                painter.scale(pose.sx, pose.sy)
                painter.translate(-feet)
            if pose.spin:
                self._rotate(painter, QPointF(458 * s, 400 * s), pose.spin)   # about her middle
            if pose.mirror:
                axis = QPointF(458 * s, 0)
                painter.translate(axis)
                painter.scale(-1, 1)
                painter.translate(-axis)
        closed, talking = self._eyes_closed(now), self._mouth_open(now)
        if pose is not None and pose.eyes_closed is not None:
            closed = pose.eyes_closed
        if pose is not None and pose.mouth_open is not None:
            talking = pose.mouth_open
        shown = {'blink': self._variant('blink'), 'eyes': self._variant('eyes'),
                 'mouthOpen': self._variant('mouthOpen'), 'mouthClosed': self._variant('mouthClosed')}
        for layer in rig['layers']:
            role = layer.get('role') or ''
            base_role = role.split(':', 1)[0]
            if base_role in shown and role != shown[base_role]:
                continue                      # another expression of this part is showing
            if (base_role == 'blink' and not closed) or (base_role == 'eyes' and closed) \
                    or (base_role == 'mouthOpen' and not talking) or (base_role == 'mouthClosed' and talking):
                continue
            pixmap = layers.get(layer['img'])
            if pixmap is None:
                continue
            name = layer['name']
            at = QPointF(layer['shift'][0] * s, layer['shift'][1] * s) + self._scaled_offsets[layer['img']]
            painter.save()
            angle = self._layer_angle(name, t)
            if name in ('左耳', '右耳'):
                angle += self.ear_bias
            if pose is not None:
                angle += pose.layer_turn.get(name, 0.0)
                shift = pose.layer_shift.get(name)
                if shift:
                    at += QPointF(shift[0] * s, shift[1] * s)
            if angle:
                self._rotate(painter, QPointF(layer['pivot'][0] * s, layer['pivot'][1] * s), angle)
            if layer.get('mask'):
                self._draw_glare(painter, layer, pixmap, layers[layer['mask']], at, t,
                                 pose.glare if pose is not None else None)
            elif name == '双手' and pose is not None and pose.paws:
                self._draw_paws(painter, pixmap, at, pose.paws, s)
            elif name == '腮红' and pose is not None and pose.blush_scale != 1.0:
                centre = QPointF(458 * s, 568 * s)
                painter.translate(centre)
                painter.scale(pose.blush_scale, pose.blush_scale)
                painter.translate(-centre)
                painter.drawPixmap(at, pixmap)
                painter.setOpacity(min(1.0, max(0.0, pose.blush - 1)))
                painter.drawPixmap(at, pixmap)
                if pose.blush > 2:
                    painter.setOpacity(min(1.0, pose.blush - 2))
                    painter.drawPixmap(at, pixmap)
                painter.setOpacity(1.0)
            else:
                painter.drawPixmap(at, pixmap)
                if name == '腮红' and pose is not None and pose.blush > 1:
                    painter.setOpacity(min(1.0, pose.blush - 1))
                    painter.drawPixmap(at, pixmap)
                    if pose.blush > 2:
                        painter.setOpacity(min(1.0, pose.blush - 2))
                        painter.drawPixmap(at, pixmap)
                    painter.setOpacity(1.0)
                if name == '眼镜' and pose is not None and pose.fog > 0:
                    # Two soft ovals of mist over the lenses (canvas: lenses about x 400 and 518, y 548).
                    from PySide6.QtGui import QColor, QRadialGradient
                    for lens_x in (400, 518):
                        centre = QPointF(lens_x * s, 548 * s)
                        gradient = QRadialGradient(centre, 70 * s)
                        mist = QColor(255, 255, 255)
                        mist.setAlphaF(0.85 * pose.fog)
                        gradient.setColorAt(0.0, mist)
                        mist.setAlphaF(0.55 * pose.fog)
                        gradient.setColorAt(0.6, mist)
                        mist.setAlphaF(0.0)
                        gradient.setColorAt(1.0, mist)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(gradient)
                        painter.drawEllipse(centre, 66 * s, 30 * s)
                if name == '眼镜' and pose is not None and pose.lens_flash > 0:
                    self._draw_flash(painter, QPointF(548 * s, 532 * s), 64 * s * pose.lens_flash, pose.lens_flash)
            painter.restore()
        painter.restore()
        for sticker, k in self._live_stickers(now):
            painter.save()
            head = QPointF(458 * s, 330 * s)               # stickers a third larger, about her head
            painter.translate(head)
            painter.scale(self.STICKER_SCALE, self.STICKER_SCALE)
            painter.translate(-head)
            sticker.draw(painter, k, s)
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

    def _draw_glare(self, painter, layer, pixmap, mask, at, t, forced=None):
        """Glare sweeping across its parent, clipped to the parent's pixels (``forced``: a move's sweep)."""
        s = self.scale
        period, delay = 3.6, (1.4 if layer['name'] == '反光2' else 0.0)
        phase = ((t - delay) % period) / period
        k = 0.0 if phase < .55 else 1.0 if phase > .85 else (phase - .55) / .30
        if forced is not None and layer['name'] == '反光':
            k = max(0.0, min(1.0, forced))
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
