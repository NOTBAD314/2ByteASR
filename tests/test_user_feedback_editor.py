import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QUndoStack
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.timeline.studio_commands import EditCueIntervalsCommand
from twobyteasr.timeline.studio_selection import ClipSelection, copy_selection_command
from twobyteasr.app.window_constraints import restore_minimized_window


@pytest.fixture(scope='module', autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def project():
    p = SubtitleProject(media=StudioMedia('synthetic.mp4', duration_ms=10000), cues=[
        StudioCue('a', 1000, 3000, '第一句', speaker_id='S1'),
        StudioCue('b', 5000, 6500, '第二句', speaker_id='S1')])
    p.validate()
    return p


def mouse(widget, kind, point, modifiers):
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
    event = QMouseEvent(kind, point, widget.mapToGlobal(point.toPoint()).toPointF(),
                        Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton, buttons, modifiers)
    QApplication.sendEvent(widget, event)


def timeline_fixture():
    p = project()
    widget = WaveformTimeline()
    widget.resize(1200, 480)
    widget.set_project(p)
    widget.set_visible_window(0, 10000)
    widget.snap_enabled = False
    y = widget._track_layout()[0]['S1'].center().y()
    return p, widget, QPointF(widget._time_to_x(2000), y)


def test_ctrl_middle_drag_adjusts_ends_one_undo_and_leaves_neighbour():
    p, widget, origin = timeline_fixture()
    widget.set_selected('a')
    stack = QUndoStack()
    widget.timing_edit_committed.connect(lambda values: stack.push(EditCueIntervalsCommand(p, values)))
    before = copy.deepcopy(p.to_dict())
    mouse(widget, QEvent.MouseButtonPress, origin, Qt.ControlModifier)
    mouse(widget, QEvent.MouseMove, origin + QPointF(80, 0), Qt.ControlModifier)
    widget._flush_timing_preview()
    assert p.to_dict() == before
    assert widget._timing_preview['a'].start_ms == 1000
    assert widget._timing_preview['a'].end_ms > 3000
    mouse(widget, QEvent.MouseButtonRelease, origin + QPointF(80, 0), Qt.ControlModifier)
    assert stack.count() == 1 and p.cues[0].start_ms == 1000
    assert (p.cues[1].start_ms, p.cues[1].end_ms) == (5000, 6500)
    stack.undo()
    assert p.to_dict() == before
    widget.close()


def test_ctrl_click_still_toggles_selection_and_escape_cancels():
    p, widget, origin = timeline_fixture()
    widget.set_selected('a')
    mouse(widget, QEvent.MouseButtonPress, origin, Qt.ControlModifier)
    mouse(widget, QEvent.MouseButtonRelease, origin, Qt.ControlModifier)
    assert 'a' not in widget.selected_ids
    mouse(widget, QEvent.MouseButtonPress, origin, Qt.ControlModifier)
    mouse(widget, QEvent.MouseButtonRelease, origin, Qt.ControlModifier)
    assert 'a' in widget.selected_ids
    mouse(widget, QEvent.MouseButtonPress, origin, Qt.ControlModifier)
    mouse(widget, QEvent.MouseMove, origin + QPointF(-400, 0), Qt.ControlModifier)
    widget._flush_timing_preview()
    assert widget._timing_preview['a'].end_ms - widget._timing_preview['a'].start_ms == 50
    assert widget.cancel_timing_edit()
    assert p.cues[0].end_ms == 3000
    widget.close()


def test_alt_drag_copies_multiple_cues_and_cancellation_creates_nothing(tmp_path):
    p, widget, origin = timeline_fixture()
    widget._publish_clip_selection(ClipSelection(cue_ids={'a', 'b'}))
    stack = QUndoStack()
    widget.group_copy_committed.connect(lambda selected, delta: stack.push(copy_selection_command(p, selected, delta)))
    before = copy.deepcopy(p.to_dict())
    mouse(widget, QEvent.MouseButtonPress, origin, Qt.AltModifier)
    mouse(widget, QEvent.MouseMove, origin + QPointF(150, 0), Qt.AltModifier)
    assert p.to_dict() == before
    mouse(widget, QEvent.MouseButtonRelease, origin + QPointF(150, 0), Qt.AltModifier)
    assert len(p.cues) == 4 and stack.count() == 1
    assert len({c.id for c in p.cues}) == 4
    assert next(c for c in p.cues if c.id == 'a').start_ms == 1000
    saved = load_project(save_project(p, tmp_path/'copied.2byteproj'))
    assert saved.cues == p.cues
    stack.undo()
    assert p.to_dict() == before
    mouse(widget, QEvent.MouseButtonPress, origin, Qt.AltModifier)
    mouse(widget, QEvent.MouseMove, origin + QPointF(150, 0), Qt.AltModifier)
    assert widget.cancel_selection_gesture()
    mouse(widget, QEvent.MouseButtonRelease, origin + QPointF(150, 0), Qt.AltModifier)
    assert p.to_dict() == before
    widget.close()


def test_copy_cues_preserves_style_and_immutable_acoustic_provenance():
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions, KEY
    p = project()
    ensure_independent_captions(p)
    p.cues[0].appearance_override = {'font_size': 42}
    before = copy.deepcopy(p.to_dict())
    command = copy_selection_command(p, ClipSelection(cue_ids={'a'}), 2000)
    command.redo()
    clone = next(c for c in p.cues if c.id in command.copied_selection.cue_ids)
    assert clone.text == '第一句' and clone.start_ms == 3000
    assert clone.appearance_override == p.cues[0].appearance_override
    assert p.studio_state[KEY]['instances'][clone.id]['source_cue_id'] == 'a'
    command.undo()
    assert p.to_dict() == before


def test_copy_media_remaps_audio_and_collision_is_atomic():
    from twobyteasr.projects.studio_project import VideoTrack, VideoClip
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    from twobyteasr.timeline.studio_media_pool import sync_linked_av_contract
    p = project()
    p.video_tracks[0].locked = True
    sequence_of(p).video_track_locked = True
    asset = p.media_pool[0]
    p.video_tracks.append(VideoTrack('V2', '视频', clips=[VideoClip('v', asset.asset_id, 0, 1000, 1000, 2000)], z_index=1))
    sync_linked_av_contract(p)
    p.validate()
    before = copy.deepcopy(p.to_dict())
    with pytest.raises(ValueError):
        copy_selection_command(p, ClipSelection(video_ids={'v'}), 500)
    assert p.to_dict() == before
    command = copy_selection_command(p, ClipSelection(video_ids={'v'}), 2000)
    command.redo()
    clone_id = next(iter(command.copied_selection.video_ids))
    audio = [c for t in p.audio_tracks for c in t.clips if c.linked_video_clip_id == clone_id]
    assert len(audio) == 1 and audio[0].timeline_in_ms == 3000
    assert p.video_tracks[1].clips[0].id == 'v'
    command.undo()
    assert p.to_dict() == before
    with pytest.raises(ValueError):
        copy_selection_command(p, ClipSelection(cue_ids={'a'}), 2000, locked_speakers={'S1'})


@pytest.mark.parametrize('maximized', [False, True])
def test_restore_keeps_window_state(maximized):
    widget = QWidget()
    widget.resize(600, 400)
    widget.showMaximized() if maximized else widget.show()
    QApplication.processEvents()
    widget.showMinimized()
    QApplication.processEvents()
    restore_minimized_window(widget)
    QApplication.processEvents()
    assert not widget.isMinimized() and widget.isMaximized() == maximized
    widget.close()


@pytest.mark.parametrize('exists', [False, True])
def test_last_card_delete_clears_recent_index_and_repeated_delete(tmp_path, monkeypatch, exists):
    import twobyteasr.studio.studio_hub as hub
    path = tmp_path/'last.2byteproj'
    if exists:
        path.write_text('fixture')
    settings = tmp_path/'settings.json'
    settings.write_text(json.dumps({'recent_projects': [{'path': str(path).upper()}]}))
    index = {str(path): {'name': '最后一个'}}
    monkeypatch.setattr(hub, 'studio_settings_path', lambda: settings)
    import twobyteasr.projects.studio_project as sp
    monkeypatch.setattr(sp, 'load_library_index', lambda: index.copy())
    monkeypatch.setattr(sp, 'save_library_index', lambda value: (index.clear(), index.update(value)))
    class Menu:
        def addAction(self, text):
            action = object()
            if text == '删除工程': self.delete = action
            return action
        def addSeparator(self): pass
        def exec(self, pos): return self.delete
    monkeypatch.setattr(hub, 'create_studio_menu', lambda _: Menu())
    monkeypatch.setattr(hub, 'studio_message_box', lambda *args: QMessageBox.Yes)
    page = SimpleNamespace(_hub_library_records=[{'path': str(path)}], _hub_scan_generation=0,
                           _project_library_records=lambda: [], _refresh_studio_empty_state=lambda: None)
    page._remove_recent_project_metadata_batch = lambda targets: hub.StudioHubMixin._remove_recent_project_metadata_batch(page, targets)
    page._remove_recent_project_metadata = lambda target: page._remove_recent_project_metadata_batch({target})
    hub.StudioHubMixin._recent_project_menu(page, str(path))
    assert not path.exists() and not index and page._hub_library_records == []
    assert json.loads(settings.read_text())['recent_projects'] == []
    assert page._hub_scan_generation == 1


@pytest.mark.parametrize('duration, playhead', [(500, 100), (10000, 9000), (0, 7000)])
def test_manual_add_respects_playhead_short_media_and_undo(monkeypatch, duration, playhead):
    from twobyteasr.studio.studio_cue_controller import StudioCueController
    p = SubtitleProject(media=StudioMedia('', duration_ms=duration), cues=[])
    p.validate()
    stack = QUndoStack()
    session = SimpleNamespace(project=p, selected_cue_id='', _cue_lookup={}, undo_stack=stack)
    page = SimpleNamespace(timeline=SimpleNamespace(playhead_ms=playhead, selected_track_header=('subtitle', 'S00'),
                                                  locked_speakers=set(), speaker_ids=lambda: []),
                           _begin_canvas_inline_edit=lambda: None)
    monkeypatch.setattr(StudioCueController, 'model_changed', lambda self,*a: setattr(session,'_cue_lookup',{c.id:c for c in p.cues}))
    monkeypatch.setattr(StudioCueController, 'select_cue', lambda self,key,**kw: setattr(session,'selected_cue_id',key))
    StudioCueController(page,session)._add_subtitle_at_playhead()
    assert len(p.cues)==1 and p.cues[0].start_ms==playhead
    assert p.cues[0].end_ms==min(playhead+2000,duration) if duration else p.cues[0].end_ms==playhead+2000
    stack.undo()
    assert not p.cues


def test_uncreated_library_is_empty_and_stale_scan_cannot_restore_index(tmp_path, monkeypatch):
    import twobyteasr.studio.studio_hub as hub
    root = tmp_path/'uncreated-library'
    page = SimpleNamespace(_hub_scan_generation=0, recent_project_records=lambda: [])
    monkeypatch.setattr(hub, 'project_library_root', lambda: root)
    monkeypatch.setattr(hub, 'load_library_index', lambda **kw: {})
    written = []
    monkeypatch.setattr(hub, 'save_library_index', lambda value: written.append(value))
    assert hub.StudioHubMixin._project_library_records(page) == []
    root.mkdir(); target = root/'last.2byteproj'; target.write_text('fixture')
    def snapshot(path, record):
        # A deletion invalidates the worker after it took a filesystem snapshot.
        target.unlink(); page._hub_scan_generation += 1
        return None, {'name': 'last'}, False
    monkeypatch.setattr(hub, 'library_project_snapshot', snapshot)
    hub.StudioHubMixin._project_library_records(page)
    assert not written and not target.exists()


def test_ctrl_multi_selection_changes_only_unlocked_selected_ends():
    p, widget, origin = timeline_fixture()
    widget._publish_clip_selection(ClipSelection(cue_ids={'a','b'}))
    widget.locked_speakers = set()
    mouse(widget, QEvent.MouseButtonPress, origin, Qt.ControlModifier)
    mouse(widget, QEvent.MouseMove, origin + QPointF(80,0), Qt.ControlModifier)
    widget._flush_timing_preview()
    a, b = widget._timing_preview['a'], widget._timing_preview['b']
    assert (a.start_ms, b.start_ms) == (1000,5000)
    assert a.end_ms-3000 == b.end_ms-6500 > 0
    widget.cancel_timing_edit(); widget.close()


def test_manual_add_on_locked_selected_speaker_creates_nothing(monkeypatch):
    monkeypatch.setattr('twobyteasr.studio.studio_cue_controller.bind_text', lambda *a: None)
    from twobyteasr.studio.studio_cue_controller import StudioCueController
    p = project(); stack = QUndoStack()
    session = SimpleNamespace(project=p, selected_cue_id='', _cue_lookup={}, undo_stack=stack)
    page = SimpleNamespace(save_state=None, timeline=SimpleNamespace(playhead_ms=8000,
        selected_track_header=('subtitle','S1'), locked_speakers={'S1'}, speaker_ids=lambda: ['S1']))
    before = copy.deepcopy(p.to_dict())
    StudioCueController(page,session)._add_subtitle_at_playhead()
    assert p.to_dict() == before and stack.count() == 0
