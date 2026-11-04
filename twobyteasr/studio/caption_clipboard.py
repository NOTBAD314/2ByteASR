"""Object clipboard shortcuts; text controls retain their native key handling."""
import json

from PySide6.QtCore import QMimeData, QEvent
from PySide6.QtGui import QKeySequence, QKeyEvent
from PySide6.QtWidgets import QApplication

MIME = 'application/x-2byteasr-caption-objects+json'


def copy_captions(page):
    if not page.project:
        return False
    from ..timeline.caption_copy_command import capture_captions
    timeline = page.timeline
    layer = timeline.active_subtitle_layer
    ids = timeline.translation_selected_ids if layer == 'translation' else page.selected_cue_ids()
    payload = capture_captions(page.project, ids, layer=layer)
    if not payload['rows']:
        return False
    mime = QMimeData()
    mime.setData(MIME, json.dumps(payload, ensure_ascii=False).encode('utf8'))
    mime.setText('\n\n'.join(row['cue']['text'] for row in payload['rows']))
    QApplication.clipboard().setMimeData(mime)
    return True


def paste_captions(page):
    if not page.project:
        return False
    mime = QApplication.clipboard().mimeData()
    if mime is None or not mime.hasFormat(MIME):
        return False
    try:
        payload = json.loads(bytes(mime.data(MIME)).decode('utf8'))
        from ..timeline.caption_copy_command import PasteCaptionsCommand
        command = PasteCaptionsCommand(page.project, payload, page.timeline.playhead_ms,
                                       changed=getattr(page, '_changed', None))
    except (ValueError, TypeError, KeyError) as exc:
        page.save_state.setText(str(exc))
        return True
    page.timeline.set_subtitle_layer('original')
    outcome = command.outcome
    page.undo_stack.push(command)
    if not outcome['applied']:
        page.save_state.setText(outcome['error'] or '字幕复制未提交')
        return True
    page.timeline._publish_clip_selection(command.copied_selection)
    return True


def handle_key(page, event):
    if page._editing_has_focus():
        return False
    if event.matches(QKeySequence.StandardKey.Copy):
        return copy_captions(page)
    if event.matches(QKeySequence.StandardKey.Paste):
        return paste_captions(page)
    return False


def handle_sequence(page, sequence):
    keys = QKeySequence(sequence)
    if keys.count() != 1:
        return False
    key = keys[0]
    return handle_key(page, QKeyEvent(QEvent.KeyPress, key.key(), key.keyboardModifiers()))
