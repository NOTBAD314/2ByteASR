from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.timeline.studio_edit_sequence import (EditSequence, VideoSegment, store_sequence,
    sequence_of, projected_cues, split_at_playhead)


def recognition_project():
    p = SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=20000))
    p.cues = [StudioCue('early',1000,2000,'前段'), StudioCue('cross',9000,12000,'人工跨切点'),
              StudioCue('late',15000,17000,'后段')]
    seq = EditSequence(source_path='fixture.mp4',source_duration_ms=20000,video_track_locked=False,
                       segments=[VideoSegment('original','fixture.mp4',0,20000,0,20000)])
    store_sequence(p, seq)
    p.generation_metadata['timeline_recognition'] = {'sequence': seq.to_dict()}
    return p


def signature(p):
    return [(c.text,c.start_ms,c.end_ms) for c in projected_cues(p)]


def test_cut_retains_right_captions_and_crossing_sentence_undo_reopen():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    from twobyteasr.timeline.studio_edit_commands import razor_video_command
    app = QApplication.instance() or QApplication([])
    p = recognition_project()
    before = signature(p)
    stack = QUndoStack()
    stack.push(razor_video_command(p,10000))
    assert signature(p) == before
    stack.push(razor_video_command(p,16000))
    assert signature(p) == before
    stack.undo(); assert signature(p) == before
    stack.redo(); assert signature(p) == before
    loaded = SubtitleProject.from_dict(p.to_dict())
    assert signature(loaded) == before
    assert sequence_of(loaded).segment_lineage == sequence_of(p).segment_lineage


def test_legacy_cut_recovers_only_exact_unambiguous_mapping():
    p = recognition_project()
    before = signature(p)
    seq = split_at_playhead(sequence_of(p),10000)
    seq.segment_lineage = {}
    store_sequence(p,seq)
    assert signature(p) == before
    seq.segments[1].timeline_in_ms += 3000
    seq.segments[1].timeline_out_ms += 3000
    store_sequence(p,seq)
    assert '后段' not in [c.text for c in projected_cues(p)]


def test_authored_cue_id_can_contain_fragment_separator():
    p=recognition_project()
    p.cues[1].id='authored#sentence'
    before=signature(p)
    store_sequence(p,split_at_playhead(sequence_of(p),10000))
    assert signature(p)==before
    assert projected_cues(p)[1].id=='authored#sentence'


def test_descendant_can_move_and_repeated_source_is_not_multiplied():
    p = recognition_project()
    seq = split_at_playhead(sequence_of(p),10000)
    seq.segments[1].timeline_in_ms += 3000
    seq.segments[1].timeline_out_ms += 3000
    store_sequence(p,seq)
    assert ('后段',18000,20000) in signature(p)
    seq.segments.append(VideoSegment('unrelated','fixture.mp4',10000,20000,30000,40000))
    store_sequence(p,seq)
    assert sum(c.text == '后段' for c in projected_cues(p)) == 1


def test_range_independent_persisted_and_invalid_is_not_clamped():
    import pytest
    from twobyteasr.projects.project_range import set_range, range_points, validated_range
    p = recognition_project()
    set_range(p,1234,None)
    assert validated_range(p) == (1234,20000)
    set_range(p,range_points(p)[0],9876)
    loaded=SubtitleProject.from_dict(p.to_dict())
    assert validated_range(loaded) == (1234,9876)
    for points in ((9876,9876),(9876,1234),(0,21000),(-1,20000)):
        set_range(p,*points)
        loaded=SubtitleProject.from_dict(p.to_dict())
        assert range_points(loaded) == points
        with pytest.raises(ValueError):validated_range(loaded)


def test_export_snapshot_does_not_reproject_or_read_stale_runtime():
    from twobyteasr.exports.export_timeline import export_project_snapshot
    from twobyteasr.projects.studio_runtime_state import state_for
    p=recognition_project()
    state_for(p)
    seq=split_at_playhead(sequence_of(p),10000)
    seq.segments[1].timeline_in_ms+=3000
    seq.segments[1].timeline_out_ms+=3000
    store_sequence(p,seq)
    frozen=export_project_snapshot(p)
    assert not hasattr(frozen,'_studio_state_runtime')
    assert signature(frozen)==signature(p)
    reloaded=SubtitleProject.from_dict(frozen.to_dict())
    assert signature(reloaded)==signature(frozen)
    p.cues[-1].text='后续编辑'
    assert frozen.cues[-1].text=='后段'


def test_export_ui_independent_marks_and_pre_submit_gate(tmp_path,monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from twobyteasr.exports import studio_export_ui
    from twobyteasr.projects.project_range import range_points
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(studio_export_ui,'QSettings',lambda *a:QSettings(str(tmp_path/'qt.ini'),QSettings.IniFormat))
    p=recognition_project()
    ui=studio_export_ui.StudioExportWorkspace(p,str(tmp_path/'preview.ass'))
    ui.preview_scrub.setValue(2000);ui._set_in()
    ui.preview_scrub.setValue(12000);ui._set_out()
    ui.preview_scrub.setValue(18000)
    assert range_points(p)==(2000,12000)
    assert ui._range_seconds()==(2.,10.,10.)
    ui.preview_scrub.setValue(2000);ui._set_out()
    assert not ui.export_button.isEnabled() and not ui.queue_button.isEnabled()
    import pytest
    with pytest.raises(ValueError):ui._job(tmp_path/'no.mp4')
    ui.close()


def test_export_does_not_require_expired_preview_generation(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
    from twobyteasr.projects.project_range import set_range
    app=QApplication.instance() or QApplication([])
    p=recognition_project();set_range(p,1000,2000)
    ui=StudioExportWorkspace(p,str(tmp_path/'expired.ass'))
    ui.directory.setText(str(tmp_path))
    called=[]
    def capture(output):
        called.append(output)
        raise ValueError('intentional test preflight stop')
    monkeypatch.setattr(ui,'_job',capture)
    ui._start()
    assert called
    ui.close()
