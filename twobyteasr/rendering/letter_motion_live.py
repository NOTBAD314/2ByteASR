"""Small glyph tiles for speech-timed motion; whole-line layout stays fixed."""
from collections import OrderedDict

from math import tan, radians

from PySide6.QtCore import QPointF, Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QColor, QPolygonF

from ..caption_style.letter_motion import sample, particles
from ..caption_style.motion_catalog import (SLICE_BANDS, STRIP_SHIFTS, GHOST_ALPHA, RGB_COLORS,
                                            SHINE_SLANT, wipe_bands)


_TILE_CACHE = OrderedDict()
#: Curated modes that own their whole glyph construction (no generic wipe).
GLYPH_MODES = frozenset({'word_sweep', 'word_pulse', 'word_echo'})
_TILE_BYTES = 0

def _remember(key, tile):
    global _TILE_BYTES
    _TILE_CACHE[key] = tile
    _TILE_BYTES += tile.sizeInBytes()
    while _TILE_BYTES > 32*1024*1024 and len(_TILE_CACHE)>1:
        _, old = _TILE_CACHE.popitem(last=False)
        _TILE_BYTES -= old.sizeInBytes()

def paint_units(painter, pieces, snapshot, local_bounds, em, type_scale, text_layer, effects_layer):
    from .advanced_live_renderer import (resolve_fill_brush, outside_stroke_ring, _color,
        _blurred_layer, _draw_shadow_path, _draw_soft_path)
    static_key = (snapshot.text, snapshot.font_family, snapshot.font_weight, snapshot.italic,
        snapshot.letter_spacing, em, type_scale, str(snapshot.fill), str(snapshot.strokes),
        str(snapshot.shadow), str(snapshot.glow), text_layer, effects_layer,
        getattr(snapshot.resolved_caption, 'style_hash', ''), str(local_bounds))
    mode = snapshot.word_animation['mode']
    accent = _color(snapshot.word_animation.get('color'), '#FFB9DDF6')
    for index, (path, unit, milliseconds) in enumerate(pieces):
        state = sample(unit, milliseconds)
        if state['opacity'] <= .001 and state['dust'] <= .001 and state['caret'] <= .001:
            continue
        bounds = path.boundingRect()
        center = bounds.center()
        painter.save()
        painter.translate(center.x()+state['x']*em, center.y()+state['y']*em)
        painter.rotate(state['rotation'])
        if abs(state['skew']) > .01:
            painter.shear(tan(radians(state['skew'])), 0)
        painter.scale(state['scale']*state['sx'], state['scale']*state['sy'])
        painter.translate(-center)
        # Only the mist uses enlarged ghosts. Other modes change the glyph
        # structure itself instead of sharing this same fade/echo treatment.
        if text_layer and state['trail'] > .002:
            for side in (-1,1):
                painter.save()
                painter.setOpacity(state['opacity']*state['trail']*.38)
                factor = 1+.7*state['trail']*(1 if side<0 else .55)
                painter.translate(center); painter.scale(factor,factor); painter.translate(-center)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(accent, max(.5,em*.014)))
                painter.drawPath(path)
                painter.restore()
        padding = max(8.,em*.4)
        rect = bounds.adjusted(-padding,-padding,padding,padding).toAlignedRect()
        key = (static_key, index, str(rect))
        tile = _TILE_CACHE.get(key)
        if tile is None:
            tile = QImage(rect.size(), QImage.Format_ARGB32_Premultiplied)
            tile.fill(Qt.transparent)
            brush = QPainter(tile)
            brush.setRenderHint(QPainter.Antialiasing)
            brush.translate(-rect.topLeft())
            brush.setPen(Qt.NoPen)
            shadow = snapshot.shadow or {}
            if effects_layer and shadow.get('enabled', False):
                brush.save()
                brush.translate(float(shadow.get('offset_x',shadow.get('offsetX',0)))*type_scale,
                                float(shadow.get('offset_y',shadow.get('offsetY',0)))*type_scale)
                _draw_shadow_path(brush,path,color=_color(shadow.get('color'),'#88000000',opacity=shadow.get('opacity',1)),
                    radius=float(shadow.get('blur',0))*type_scale,spread=float(shadow.get('spread',0))*type_scale,fill_core=True)
                brush.restore()
            glow=snapshot.glow or {}
            if effects_layer and glow.get('enabled',False):
                _draw_soft_path(brush,path,color=_color(glow.get('color'),'#FFFFFFFF',opacity=glow.get('opacity',.45)),
                    radius=float(glow.get('radius',glow.get('blur',4)))*type_scale*2.2,
                    spread=float(glow.get('spread',0))*type_scale,fill_core=False,intensity=float(glow.get('intensity',1)))
            if text_layer:
                for stroke in reversed(snapshot.strokes):
                    brush.setBrush(_color(stroke.get('color'),opacity=stroke.get('opacity',1)))
                    brush.drawPath(outside_stroke_ring(path,float(stroke.get('width',0))*type_scale))
                brush.setBrush(resolve_fill_brush(snapshot.fill, local_bounds))
                brush.drawPath(path)
            brush.end()
            _remember(key,tile)
        else:
            _TILE_CACHE.move_to_end(key)
        if text_layer and mode == 'word_mist' and state['glow'] > .001:
            glow_key=(key,'accent',accent.rgba())
            halo=_TILE_CACHE.get(glow_key)
            if halo is None:
                halo=QImage(rect.size(),QImage.Format_ARGB32_Premultiplied);halo.fill(Qt.transparent)
                brush=QPainter(halo);brush.setRenderHint(QPainter.Antialiasing);brush.translate(-rect.topLeft())
                _draw_soft_path(brush,path,color=accent,radius=em*.13,spread=0,fill_core=False)
                brush.end();_remember(glow_key,halo)
            else:
                _TILE_CACHE.move_to_end(glow_key)
            painter.save()
            painter.setOpacity(state['opacity']*state['glow'])
            painter.drawImage(QPointF(rect.topLeft()),halo)
            painter.restore()
        tile = _blurred_layer(tile,state['blur']*em)
        def blit(opacity=1., clip=None, dx=0., dy=0., factor=1.):
            painter.save()
            painter.setOpacity(state['opacity']*opacity)
            painter.translate(dx*em,dy*em)
            if factor != 1.:
                painter.translate(center); painter.scale(factor, factor); painter.translate(-center)
            if clip is not None:painter.setClipRect(clip,Qt.IntersectClip)
            painter.drawImage(QPointF(rect.topLeft()),tile)
            painter.restore()
        def solid(color, opacity, dx=0., clip=None):
            painter.save()
            painter.setOpacity(max(0., min(1., opacity)))
            painter.translate(dx*em, 0)
            if clip is not None:painter.setClipPath(clip,Qt.IntersectClip)
            painter.setPen(Qt.NoPen); painter.setBrush(QColor(color)); painter.drawPath(path)
            painter.restore()
        if text_layer:
            _back_layers(painter, state, tile, rect, path, bounds, center, em, accent, key, blit, solid)
        span = QRectF(bounds.left(), bounds.top()-padding, bounds.width(), bounds.height()+2*padding)
        def band(a, b):
            return QRectF(span.left()+span.width()*a, span.top(), span.width()*(b-a), span.height())
        bands = wipe_bands(state['cut'], state['reveal']) if mode not in GLYPH_MODES else None
        if bands is not None:
            for a, b, alpha in bands:
                blit(alpha, clip=band(a, b))
        elif abs(state['slice']) > .001:
            for a, b, shift in SLICE_BANDS:
                top = bounds.top()-padding+(bounds.height()+2*padding)*a
                blit(clip=QRectF(bounds.left()-padding-em, top, bounds.width()+2*padding+2*em,
                                 (bounds.height()+2*padding)*(b-a)), dx=state['slice']*shift)
        elif state['strips'] > .001:
            width = (bounds.width()+2*padding)/len(STRIP_SHIFTS)
            for k, shift in enumerate(STRIP_SHIFTS):
                blit(clip=QRectF(bounds.left()-padding+k*width, bounds.top()-padding-em, width,
                                 bounds.height()+2*padding+2*em), dy=state['strips']*shift)
        elif state['door'] > .001:
            half = bounds.width()/2/em
            blit(clip=QRectF(bounds.left()-padding-em, bounds.top()-padding, bounds.width()/2+padding+em,
                             bounds.height()+2*padding), dx=-state['door']*half)
            blit(clip=QRectF(center.x(), bounds.top()-padding, bounds.width()/2+padding+em,
                             bounds.height()+2*padding), dx=state['door']*half)
        elif mode == 'word_pulse':
            for side in (-1,1):
                clip=QRectF(bounds.left()-padding, bounds.top()-padding if side<0 else center.y(),
                            bounds.width()+2*padding,bounds.height()/2+padding)
                blit(clip=clip,dx=side*.28*state['split'],dy=side*state['split'])
        elif mode == 'word_echo':
            if text_layer:
                painter.setOpacity(state['opacity']*.85)
                painter.setBrush(Qt.NoBrush);painter.setPen(QPen(accent,max(.7,em*.018)))
                painter.drawPath(path)
            if state['ink']>.001:
                blit(clip=QRectF(bounds.left()-padding,bounds.bottom()-bounds.height()*state['ink'],
                                bounds.width()+2*padding,bounds.height()*state['ink']+padding))
        elif mode in {'karaoke_wipe', 'karaoke_highlight', 'word_current', 'word_current_pop'}:
            blit()
            if text_layer:
                painter.setOpacity(state['opacity'])
                painter.setPen(Qt.NoPen)
                if mode == 'karaoke_wipe':
                    painter.setBrush(QColor('#FFFFFF')); painter.drawPath(path)
                if state['ink'] > .001:
                    painter.setClipRect(QRectF(bounds.left()-padding, bounds.top()-padding,
                        bounds.width()*state['ink']+padding, bounds.height()+2*padding), Qt.IntersectClip)
                    painter.setBrush(accent); painter.drawPath(path)
        elif mode == 'word_sweep':
            painter.setClipRect(QRectF(bounds.left()-padding,bounds.top()-em,
                (bounds.width()+2*padding)*state['reveal'],bounds.height()+2*em),Qt.IntersectClip)
            blit(.25)
            if state['ink']>.001:
                painter.save()
                painter.setClipRect(QRectF(bounds.left()-padding,bounds.top()-padding,
                    bounds.width()*state['ink']+padding,bounds.height()+2*padding),Qt.IntersectClip)
                blit()
                if text_layer:
                    painter.setOpacity(state['opacity']*.7);painter.setPen(Qt.NoPen);painter.setBrush(accent);painter.drawPath(path)
                painter.restore()
            if text_layer and state['glow']>.001:
                # A comet has a visible head and tail, not just a glow on type.
                from math import sin,pi
                at=QPointF(bounds.left()+bounds.width()*state['read'],bounds.top()-(.12+.25*sin(pi*state['read']))*em)
                painter.setOpacity(state['opacity']*state['glow']);painter.setPen(QPen(accent,em*.025,Qt.SolidLine,Qt.RoundCap))
                painter.drawLine(at-QPointF(em*.42,-em*.10),at)
                r=em*.095;painter.setPen(Qt.NoPen);painter.setBrush(accent)
                painter.drawPolygon(QPolygonF([at+QPointF(-r,0),at+QPointF(0,-r),at+QPointF(r,0),at+QPointF(0,r)]))
        elif state['scatter']>.001 and unit.get('shards'):
            cell_bounds=bounds.adjusted(-em*.04,-em*.04,em*.04,em*.04)
            for shard in unit['shards']:
                l,t,w,h=shard['rect']
                clip=QRectF(cell_bounds.left()+l*cell_bounds.width(),cell_bounds.top()+t*cell_bounds.height(),
                            w*cell_bounds.width(),h*cell_bounds.height())
                blit(clip=clip,dx=shard['x']*state['scatter'],dy=shard['y']*state['scatter'])
        else:
            blit()
        if text_layer:
            _front_layers(painter, state, unit, path, bounds, center, em, key, rect, solid)
        painter.restore()
        if text_layer and state['dust'] > .001:
            painter.save()
            painter.setPen(Qt.NoPen)
            for k,(x,y,r,a) in enumerate(particles(unit['char_start'],state['dust'])):
                painter.setOpacity(a)
                painter.setBrush(accent)
                at = QPointF(bounds.left()+bounds.width()*(k+.5)/8+x*em,center.y()+y*em)
                radius=max(.7,r*em)
                painter.drawPolygon(QPolygonF([at+QPointF(-radius,0),at+QPointF(0,-radius),
                                               at+QPointF(radius,0),at+QPointF(0,radius)]))
            painter.restore()


def _halo_tile(key, rect, path, color, radius):
    from .advanced_live_renderer import _draw_soft_path
    halo_key = (key, 'halo', color.rgba(), round(radius, 2))
    halo = _TILE_CACHE.get(halo_key)
    if halo is None:
        halo = QImage(rect.size(), QImage.Format_ARGB32_Premultiplied); halo.fill(Qt.transparent)
        brush = QPainter(halo); brush.setRenderHint(QPainter.Antialiasing); brush.translate(-rect.topLeft())
        _draw_soft_path(brush, path, color=color, radius=radius, spread=0, fill_core=False)
        brush.end(); _remember(halo_key, halo)
    else:
        _TILE_CACHE.move_to_end(halo_key)
    return halo


def _back_layers(painter, state, tile, rect, path, bounds, center, em, accent, key, blit, solid):
    """Glow, motion-trail ghosts and chroma fringes sit under the glyph."""
    opacity = state['opacity']
    if state['halo'] > .001 and opacity > .001:
        painter.save()
        painter.setOpacity(min(1., opacity*state['halo']))
        painter.drawImage(QPointF(rect.topLeft()), _halo_tile(key, rect, path, accent, em*.22))
        painter.restore()
    if state['ghost'] > .001:
        for k in (3, 2, 1):
            f = k/3
            blit(state['ghost']*GHOST_ALPHA[k-1], dx=state['gx']*f, dy=state['gy']*f, factor=1+state['gs']*f)
    if state['rgb'] > .001:
        for color, side in zip(RGB_COLORS, (-1, 1)):
            solid(color, opacity*.78, dx=side*state['rgb'])


def _front_layers(painter, state, unit, path, bounds, center, em, key, rect, solid):
    """Exposure flash, a slanted glint and the typing cursor sit on top."""
    opacity = state['opacity']
    if state['flash'] > .001 and opacity > .001:
        painter.save()
        painter.setOpacity(min(1., opacity*state['flash']*.6))
        painter.drawImage(QPointF(rect.topLeft()), _halo_tile(key, rect, path, QColor('#FFFFFF'), em*.18))
        painter.restore()
        solid('#FFFFFF', opacity*state['flash'])
    shine = state['shine']
    if -.6 < shine < 1.6 and opacity > .001:
        half = float(unit.get('sw', .18))
        slant = bounds.height()*SHINE_SLANT
        for width, alpha in ((half*2.4, .28), (half, .85)):
            left = bounds.left()+bounds.width()*(shine-width)
            right = bounds.left()+bounds.width()*(shine+width)
            band = QPainterPath()
            band.addPolygon(QPolygonF([QPointF(left+slant, bounds.top()-em), QPointF(right+slant, bounds.top()-em),
                                       QPointF(right-slant, bounds.bottom()+em), QPointF(left-slant, bounds.bottom()+em)]))
            band.closeSubpath()
            # White glint on white type is only visible as bloom past the edges.
            painter.save()
            painter.setClipPath(band, Qt.IntersectClip)
            painter.setOpacity(min(1., opacity*alpha))
            painter.drawImage(QPointF(rect.topLeft()), _halo_tile(key, rect, path, QColor('#FFFFFF'), em*.16))
            painter.restore()
            solid('#FFFFFF', opacity*alpha, clip=band)
    if state['caret'] > .001:
        painter.save()
        painter.setOpacity(min(1., state['caret']))
        painter.setPen(Qt.NoPen); painter.setBrush(QColor('#FFFFFF'))
        painter.drawRect(QRectF(bounds.right()+em*.06, bounds.top()-em*.04, max(1., em*.07), bounds.height()+em*.08))
        painter.restore()
