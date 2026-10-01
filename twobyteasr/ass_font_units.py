"""Convert authored em pixels to libass REAL_DIM once, without project mutation.

libass ass_font.c uses OS/2 Win ascent + descent with FT_SIZE_REQUEST_TYPE_REAL_DIM.
Qt setPixelSize and CSS font-size use units-per-em. ASS also anchors that taller
line box, while the canonical single-line browser layout uses line-height 1.12.
"""
from dataclasses import replace
from .font_metadata import resolve_local_face


def ass_font_style(style, width, height):
    face, _ = resolve_local_face(style.font_family, style.font_weight, style.font_style_name,
                                 style.bold, style.font_file, style.font_face_index)
    ratio = (face.win_ascent + face.win_descent) / face.units_per_em
    if ratio <= 0:
        raise ValueError(f'Invalid font vertical metrics: {face.full_name}')
    anchor_y = (1., .5, 0.)[(style.alignment - 1) // 3]
    x = style.position_x
    y = style.position_y
    if x is None or y is None:
        x = (style.margin_l, width / 2, width - style.margin_r)[(style.alignment - 1) % 3]
        y = (height - style.margin_v, height / 2, style.margin_v)[(style.alignment - 1) // 3]
    delta_y = (anchor_y - .5) * style.font_size * (ratio - 1.12) * style.scale_y / 100
    return replace(style, font_size=style.font_size * ratio, position_x=x, position_y=y + delta_y)
