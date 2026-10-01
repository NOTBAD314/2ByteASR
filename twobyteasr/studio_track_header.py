"""One fixed three-column control area for every timeline lane."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont
from .themed_icons import paint_cached_icon

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


def paint_button(painter, palette, kind, action, row, icon, *, active=False, disabled=False, solo=False):
    box = button_rect(kind, action, row)
    painter.save()
    if disabled:
        painter.setOpacity(.38)
    if active:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#3867c8' if solo else palette.header_hover))
        painter.drawRoundedRect(box, 4, 4)
    if icon == 'S':
        font = QFont(painter.font()); font.setPixelSize(14); font.setBold(True); font.setItalic(False)
        painter.setFont(font)
        painter.setPen(QColor('#ffffff' if solo else palette.header_icon))
        painter.drawText(box, Qt.AlignCenter, 'S')
    else:
        paint_cached_icon(painter, icon, palette.header_icon,
                          box.adjusted(4, 4, -4, -4).toRect(), state='hover' if active else 'normal')
    painter.restore()
