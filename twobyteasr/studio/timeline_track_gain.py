"""Whole-track gain gesture; no clip/timing mutation while a pointer is held."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPen
from ..timeline.studio_track_gain import track_gain_db, audio_track_locked


def geometry(timeline, track_id, row, value=None):
    value = track_gain_db(timeline.project, track_id) if value is None else value
    top, height = row.top()+10, max(12., row.height()-24)
    y = top+(24.-value)/84.*height
    return QRectF(timeline.TRACK_HEADER_WIDTH+8, y-5,
                  max(1, timeline._content_right()-timeline.TRACK_HEADER_WIDTH-16), 10)


def paint(timeline, painter):
    if not timeline.project or not timeline.waveform_visible: return
    drag = getattr(timeline, '_track_gain_drag', None)
    painter.save()
    # Media rows may be pinned below the scrolling subtitle viewport.
    painter.setClipRect(timeline.rect())
    for key, row in timeline._audio_track_rects().items():
        if audio_track_locked(timeline.project, key): continue
        value = drag['value'] if drag and drag['project'] is timeline.project and drag['track'] == key else track_gain_db(timeline.project, key)
        rect = geometry(timeline, key, row, value)
        painter.setPen(QPen(QColor('#e6bf7b'), 2 if drag and drag['track'] == key else 1.5))
        painter.drawLine(rect.topLeft()+QPointF(0,5), rect.topRight()+QPointF(0,5))
        painter.setBrush(QColor('#e6bf7b')); painter.drawRoundedRect(QRectF(rect.left()+5, rect.top(), 14, 10), 3, 3)
        # 2026-11-23: the value now sits in the track header; the label over
        # the waveform only shows while this line is hovered or dragged.
        if not ((drag and drag['track'] == key) or getattr(timeline, '_track_gain_hover', '') == key):
            continue
        painter.setPen(QColor('#ffffff')); painter.setBrush(QColor('#302c35'))
        label = f'{key}  轨道音量 {value:+.1f} dB'
        box = QRectF(rect.left()+25, rect.top()-16, timeline.fontMetrics().horizontalAdvance(label)+14, 20)
        painter.drawRoundedRect(box, 3, 3); painter.drawText(box, Qt.AlignCenter, label)
    painter.restore()


def hit(timeline, point):
    if not timeline.project or not timeline.waveform_visible or not QRectF(timeline.rect()).contains(point): return ''
    for key, row in timeline._audio_track_rects().items():
        if not audio_track_locked(timeline.project, key) and geometry(timeline, key, row).adjusted(0,-2,0,2).contains(point): return key
    return ''


def press(timeline, event):
    if event.button() != Qt.LeftButton or timeline.tool_mode != 'selection': return False
    key = hit(timeline, event.position())
    if not key: return False
    before = track_gain_db(timeline.project, key)
    timeline._track_gain_drag = dict(project=timeline.project, track=key, before=before, value=before, y=event.position().y())
    timeline.selected_audio_track_id = key
    timeline.setFocus(Qt.MouseFocusReason); timeline.grabMouse(); timeline.setCursor(Qt.SizeVerCursor)
    timeline.interaction_changed.emit(True)
    return True


def move(timeline, event):
    drag = getattr(timeline, '_track_gain_drag', None)
    if drag is None: return False
    if timeline.project is not drag['project']:
        finish(timeline, cancel=True); return True
    row = timeline._audio_track_rects().get(drag['track'])
    if row is None: finish(timeline, cancel=True); return True
    multiplier = .25 if event.modifiers() & Qt.ShiftModifier else 5. if event.modifiers() & Qt.ControlModifier else 1.
    value = round(max(-60., min(24., drag['before']+(drag['y']-event.position().y())*84/max(120.,row.height()-24)*multiplier)), 1)
    if value != drag['value']:
        drag['value'] = value
        timeline.track_gain_preview.emit(drag['track'], value); timeline.update()
    return True


def finish(timeline, *, cancel=False):
    drag = getattr(timeline, '_track_gain_drag', None)
    if drag is None: return False
    timeline._track_gain_drag = None
    timeline.releaseMouse(); timeline.unsetCursor(); timeline.interaction_changed.emit(False)
    if not cancel and drag['project'] is timeline.project and drag['value'] != drag['before']:
        timeline.track_gain_committed.emit(drag['track'], drag['value'])
    else:
        timeline.track_gain_cancelled.emit()
    timeline.update()
    return True


def connect(page):
    def preview(key, value):
        page._gain_preview_values = {key: value}
        page._refresh_audio_mix_only()
    def cancel():
        page._gain_preview_values = {}; page._refresh_audio_mix_only()
    def commit(key, value):
        from ..timeline.studio_track_gain import gain_command
        page._gain_preview_values = {}
        try: page.undo_stack.push(gain_command(page.project, key, value))
        except ValueError as exc: page.save_state.setText(str(exc)); page._refresh_audio_mix_only()
    page.timeline.track_gain_preview.connect(preview)
    page.timeline.track_gain_cancelled.connect(cancel)
    page.timeline.track_gain_committed.connect(commit)
