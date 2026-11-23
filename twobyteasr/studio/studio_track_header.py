"""One fixed three-column control area for every timeline lane."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from ..design.timeline_theme import mix
from ..design.themed_icons import paint_cached_icon
from ..design.typography import weighted_font

HEADER_WIDTH = 228
BUTTON_SIZE = 24
BUTTON_GAP = 4
RIGHT_PADDING = 8
CONTROL_LEFT = HEADER_WIDTH - RIGHT_PADDING - 3 * BUTTON_SIZE - 2 * BUTTON_GAP
ACTIONS = {'video': ('enabled', 'locked', 'more'),
           'audio': ('muted', 'solo', 'delete'),
           'subtitle': ('visibility', 'lock', 'more')}


def button_rect(kind, action, row):
    column = ACTIONS[kind].index(action)
    return QRectF(CONTROL_LEFT + column * (BUTTON_SIZE + BUTTON_GAP),
                  row.center().y() - BUTTON_SIZE / 2, BUTTON_SIZE, BUTTON_SIZE)


def action_at(kind, x, y=None, row=None):
    row = row if row is not None else QRectF(0, 0, HEADER_WIDTH, BUTTON_SIZE)
    for action in ACTIONS[kind]:
        rect = button_rect(kind, action, row)
        if rect.left() <= x < rect.right() and (y is None or rect.top() <= y < rect.bottom()):
            return action
    return ''


def pill_rect(kind, row, slots=None):
    """The rounded tray behind a row's buttons (2026-11-23 header draft B)."""
    actions = ACTIONS[kind][:slots] if slots else ACTIONS[kind]
    first = button_rect(kind, actions[0], row)
    last = button_rect(kind, actions[-1], row)
    return QRectF(first.left() - 3, first.top() - 2, last.right() - first.left() + 6, first.height() + 4)


def header_icon_color(palette):
    """Button icons sit close to the name colour: the old muted grey was too faint."""
    return mix(palette.header_icon, palette.header_name, 0.55)


def header_card_color(palette):
    card = mix(palette.header, palette.track_background, 0.6)
    # Dark themes often have header ≈ lane colour (grape): lift the card a
    # little toward the text colour so it still reads as a card.
    return mix(card, palette.header_name, 0.05) if palette.dark else card


def paint_button(painter, palette, kind, action, row, icon, *, active=False, disabled=False, solo=False,
                 pill_slots=None):
    box = button_rect(kind, action, row)
    painter.save()
    if action == ACTIONS[kind][0]:
        painter.setPen(Qt.NoPen)
        painter.setBrush(mix(header_card_color(palette), palette.header_name, 0.07))
        painter.drawRoundedRect(pill_rect(kind, row, pill_slots), 10, 10)
    if disabled:
        painter.setOpacity(.38)
    if active:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#3867c8' if solo else palette.header_hover))
        painter.drawRoundedRect(box, 7, 7)
    color = header_icon_color(palette)
    if icon == 'S':
        font = QFont(painter.font()); font.setPixelSize(14); weighted_font(font, 700); font.setItalic(False)
        painter.setFont(font)
        painter.setPen(QColor('#ffffff') if solo else color)
        painter.drawText(box, Qt.AlignCenter, 'S')
    else:
        paint_cached_icon(painter, icon, color.name(),
                          box.adjusted(4, 4, -4, -4).toRect(), state='hover' if active else 'normal')
    painter.restore()


# ---- Track header cards (2026-11-23, draft B 「成組卡片」) ----
# Each subtitle track has its own card; a video lane and the audio lane linked
# to it share one card and one colour rail; row text starts after the rail.
CARD_INSET = 5.0
CARD_RADIUS = 9.0
RAIL_LEFT = 10.0
CONTENT_LEFT = 21.0


def paint_header_card(painter, palette, top, bottom, color, joins=()):
    """One rounded card from ``top`` to ``bottom``; dashed lines at ``joins``."""
    if bottom - top < 6:
        return
    card = QRectF(CARD_INSET, top + 2, HEADER_WIDTH - 2 * CARD_INSET, bottom - top - 4)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(mix(palette.header, palette.grid_major, 0.55), 1))
    painter.setBrush(header_card_color(palette))
    painter.drawRoundedRect(card.adjusted(.5, .5, -.5, -.5), CARD_RADIUS, CARD_RADIUS)
    rail_inset = min(7.0, max(3.0, card.height() * 0.18))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(RAIL_LEFT, card.top() + rail_inset, 4, max(2.0, card.height() - 2 * rail_inset)), 2, 2)
    if joins:
        pen = QPen(mix(palette.header, palette.grid_major, 0.7), 1, Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([3.0, 3.0])
        painter.setPen(pen)
        for y in joins:
            painter.drawLine(QPointF(CONTENT_LEFT - 2, round(y) + .5), QPointF(HEADER_WIDTH - CARD_INSET - 6, round(y) + .5))
    painter.restore()


def paint_track_tag(painter, palette, text, left, center_y):
    """Small rounded id tag (V2 / A2 / A); returns the x after it."""
    font = QFont(painter.font()); font.setPointSizeF(7.5); weighted_font(font, 700); font.setItalic(False)
    metrics = QFontMetrics(font)
    # A shared minimum width keeps names aligned across A / V2 / A2 rows.
    box = QRectF(left, center_y - 9, max(26.0, metrics.horizontalAdvance(text) + 12), 18)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(mix(header_card_color(palette), palette.header_name, 0.09))
    painter.drawRoundedRect(box, 6, 6)
    painter.setFont(font)
    painter.setPen(QColor(palette.header_letter))
    painter.drawText(box, Qt.AlignCenter, text)
    painter.restore()
    return box.right()


def paint_track_title(painter, palette, left, right, row, title, detail='', second_line=''):
    """Name (9.5pt bold) with a muted detail after it, or a second line under it."""
    font = QFont(painter.font()); font.setPointSizeF(9.5); weighted_font(font, 700); font.setItalic(False)
    small = QFont(font); small.setPointSizeF(8); weighted_font(small, 400)
    width = max(10.0, right - left)
    two_lines = bool(second_line) and row.height() >= 44
    painter.save()
    painter.setFont(font)
    metrics = QFontMetrics(font)
    detail_width = QFontMetrics(small).horizontalAdvance(detail) + 6 if detail else 0
    shown = metrics.elidedText(str(title), Qt.TextElideMode.ElideRight, int(max(10, width - detail_width)))
    if two_lines:
        title_rect = QRectF(left, row.center().y() - 17, width, 18)
    else:
        title_rect = QRectF(left, row.top(), width, row.height())
    painter.setPen(QColor(palette.header_name))
    painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
    painter.setFont(small)
    painter.setPen(QColor(palette.header_letter))
    if detail:
        x = left + metrics.horizontalAdvance(shown) + 6
        painter.drawText(QRectF(x, title_rect.top(), max(4.0, right - x), title_rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, detail)
    if two_lines:
        painter.drawText(QRectF(left, row.center().y() + 1, width, 17), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         QFontMetrics(small).elidedText(str(second_line), Qt.TextElideMode.ElideRight, int(width)))
    painter.restore()
