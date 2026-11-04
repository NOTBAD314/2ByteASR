"""Object duplication must survive source edits, undo and serialization."""
import copy
import pytest
from types import SimpleNamespace as NS

from PySide6.QtCore import QPointF, Qt, QEvent
from PySide6.QtGui import QUndoStack, QMouseEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QLabel

from tests.test_subtitle_edit_integrity import APP, project
from twobyteasr.timeline.caption_copy_command import capture_captions, PasteCaptionsCommand
from twobyteasr.projects.studio_project import save_project, load_project
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand, delete_cues_command
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.studio.studio_timeline import WaveformTimeline


@pytest.fixture(autouse=True)
def clipboard_lifetime():
    yield
    # Release Qt-owned MIME objects before the offscreen QApplication exits.
    APP.clipboard().clear()
    APP.processEvents()


def test_multiple_source_copies_keep_properties_links_and_relative_time(tmp_path):
    p = project()
    st.set_manual(p, 'a', '译文甲')
    st.set_manual(p, 'c', '译文丙')
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    ensure_independent_captions(p)
    p.cues[0].transform = {'position_x': .3, 'scale_x': 1.2, 'language_motion': {'translation_effect_id': 'none'}}
    p.cues[0].appearance_override = {'font_size': 45, 'translation_group': {'id': 'a', 'text': '译文甲'}}
    before = copy.deepcopy(p.to_dict())
    untouched = p.cues[1]
    payload = capture_captions(p, ['a', 'c'])
    stack = QUndoStack(); command = PasteCaptionsCommand(p, payload, 9000)
    stack.push(command)
    added = [c for c in p.cues if c.id in command.ids]
    assert [(c.start_ms, c.end_ms) for c in added] == [(9000, 10000), (13000, 14000)]
    assert untouched is next(c for c in p.cues if c.id == 'b')
    assert added[0].transform == payload['rows'][0]['cue']['transform']
    assert added[0].appearance_override['translation_group']['id'] != 'a'
    assert p.generation_metadata['translations'][added[0].id] == '译文甲'
    stack.push(SetCueFieldsCommand(p, added[0].id, {'text': '副本独立修改'}, '编辑'))
    assert p.cues[0].text == '第一句'
    stack.undo(); stack.undo()
    assert p.to_dict()['cues'] == before['cues']
    stack.redo()
    path = tmp_path/'copy.2byteproj'; save_project(p, path)
    reopened = load_project(path)
    assert {c.id for c in reopened.cues} == {c.id for c in p.cues}
    assert reopened.generation_metadata['translations'] == p.generation_metadata['translations']
    from twobyteasr.projects.subtitle_consistency import validate_export_view
    assert validate_export_view(p, p.cues).ok
    stack.push(delete_cues_command(p, command.ids))
    assert {c.id for c in p.cues} == {'a', 'b', 'c'}
    assert p.generation_metadata['translations']['a'] == '译文甲'


def test_translation_only_copy_never_changes_source_and_is_an_editable_track(tmp_path):
    p = project(); st.set_manual(p, 'b', '第二条译文')
    before = copy.deepcopy(p.cues)
    data = capture_captions(p, ['b'], layer='translation')
    stack = QUndoStack(); command = PasteCaptionsCommand(p, data, 10000); stack.push(command)
    clone = next(c for c in p.cues if c.id in command.ids)
    assert clone.text == '第二条译文' and clone.start_ms == 10000
    assert [c for c in p.cues if c.id not in command.ids] == before
    assert p.generation_metadata['subtitle_imports']['tracks'][clone.speaker_id]['role'] == 'translation'
    from twobyteasr.studio.subtitle_text_targets import text_entries
    assert next(e for e in text_entries(p) if e.target.cue_id == clone.id).target.layer == 'translation'
    stack.undo(); assert p.cues == before
    stack.redo(); save_project(p, tmp_path/'translation-copy.2byteproj')
    assert next(c for c in load_project(tmp_path/'translation-copy.2byteproj').cues if c.id == clone.id).text == clone.text


def test_clipboard_snapshot_is_independent_and_text_focus_is_not_stolen():
    from twobyteasr.studio.caption_clipboard import handle_key, copy_captions, paste_captions
    p = project(); calls = []
    timeline = NS(active_subtitle_layer='original', translation_selected_ids=set(), playhead_ms=11000,
                  set_subtitle_layer=lambda layer: calls.append(layer), _publish_clip_selection=lambda x: calls.append(x))
    page = NS(project=p, timeline=timeline, selected_cue_ids=lambda: ['a', 'b'], undo_stack=QUndoStack(),
              _editing_has_focus=lambda: True, save_state=QLabel())
    assert not handle_key(page, QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier))
    assert copy_captions(page)
    p.cues[0].text = '原字幕后改'
    assert paste_captions(page)
    assert next(c for c in p.cues if c.start_ms == 11000).text == '第一句'
    assert page.undo_stack.count() == 1


def mouse(kind, pos, modifiers=Qt.AltModifier):
    return QMouseEvent(kind, QPointF(pos), QPointF(pos), Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton,
                       Qt.LeftButton if kind != QEvent.MouseButtonRelease else Qt.NoButton, modifiers)


def test_alt_drag_previews_only_and_commits_once_or_cancels():
    p = project(); t = WaveformTimeline(); t.resize(1100, 450); t.set_project(p); t.set_visible_window(0, 10000)
    t.set_selected_ids(['a', 'b'], 'a'); t.snap_enabled = False
    committed = []; t.group_copy_committed.connect(lambda selection, delta: committed.append((selection, delta)))
    try:
        rect = t._track_layout()[0]['S00']; start = QPointF(t._time_to_x(1500), rect.center().y())
        t.mousePressEvent(mouse(QEvent.MouseButtonPress, start))
        assert t._group_drag and t._group_drag['copy']
        for delta in (30, 60, 100):
            t.mouseMoveEvent(mouse(QEvent.MouseMove, start + QPointF(delta, 0)))
        assert len(p.cues) == 3 and not committed
        assert t.cancel_selection_gesture()
        t.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, start + QPointF(100, 0)))
        assert not committed
        t.mousePressEvent(mouse(QEvent.MouseButtonPress, start))
        t.mouseMoveEvent(mouse(QEvent.MouseMove, start + QPointF(100, 0)))
        t.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, start + QPointF(100, 0)))
        assert len(committed) == 1 and committed[0][0].cue_ids == {'a', 'b'}
        assert len(p.cues) == 3
    finally:
        t.close(); t._thumbnails.thread.join(2)
