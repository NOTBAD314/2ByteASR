"""Convert authored em pixels to libass REAL_DIM once, without project mutation.

libass ass_font.c uses OS/2 Win ascent + descent with FT_SIZE_REQUEST_TYPE_REAL_DIM.
Qt setPixelSize and CSS font-size use units-per-em. Production captions use
their common measured ink anchor; width-only legacy callers retain their old
single-line baseline adjustment.
"""
from dataclasses import replace
from ..caption_style.font_metadata import resolve_local_face


def ass_font_style(style, width, height, *, layout=None, rotation=0.):
    face, _ = resolve_local_face(style.font_family, style.font_weight, style.font_style_name,
                                 style.bold, style.font_file, style.font_face_index)
    ratio = (face.win_ascent + face.win_descent) / face.units_per_em
    if ratio <= 0:
        raise ValueError(f'Invalid font vertical metrics: {face.full_name}')
    anchor_y = (1., .5, 0.)[(style.alignment - 1) // 3]
    x = style.position_x
    y = style.position_y
    if x is None:
        x = (style.margin_l, width / 2, width - style.margin_r)[(style.alignment - 1) % 3]
    if y is None:
        y = (height - style.margin_v, height / 2, style.margin_v)[(style.alignment - 1) // 3]
    ink = (layout or {}).get('inkBoundsPx')
    if ink and len(ink) == 4 and ink[2] > ink[0] and ink[3] > ink[1]:
        # libass anchors the line box. Move that box so the actual glyph-ink
        # anchor remains the authored point, exactly as LIVE/Browser do.
        from math import cos, sin, radians
        anchor_x = ((style.alignment-1) % 3)/2
        dx = (float(layout['lineBoxWidthPx'])*anchor_x-ink[0]-(ink[2]-ink[0])*anchor_x)*style.scale_x/100
        dy = (float(layout['lineBoxHeightPx'])*anchor_y-ink[1]-(ink[3]-ink[1])*anchor_y)*style.scale_y/100
        angle = radians(rotation)
        x, y = x+cos(angle)*dx-sin(angle)*dy, y+sin(angle)*dx+cos(angle)*dy
    else:
        y += (anchor_y-.5)*style.font_size*(ratio-1.12)*style.scale_y/100
    return replace(style, font_size=style.font_size * ratio, position_x=x, position_y=y)
