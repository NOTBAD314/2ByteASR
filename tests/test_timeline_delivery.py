import copy
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from twobyteasr.media.media_ingest import MediaIngestResult
from twobyteasr.studio.studio_media_drop import MediaDropCommand
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker
from twobyteasr.timeline.studio_edit_sequence import sequence_of, timeline_duration_ms
from twobyteasr.recognition.speaker_evidence import scope_request_speakers, fuse_moss_speakers
from twobyteasr.exports.studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts
from twobyteasr.exports.completion_export import selected_result


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def test_batch_drop_atomic_order_lock_and_link(app, tmp_path):
    project = SubtitleProject(media=StudioMedia(path="", duration_ms=0))
    project.validate()
    before = copy.deepcopy(project.to_dict())
    results = [MediaIngestResult(1, project.project_id, str(tmp_path/f"{n}.mp4"),
        duration_ms=1000+n*100, has_video=True, has_audio=True, fingerprint=str(n)) for n in range(2)]
    stack = QUndoStack()
    stack.push(MediaDropCommand(project, results, 3000))
    assert stack.count() == 1
    assert timeline_duration_ms(project) == 5100
    assert [s.timeline_in_ms for s in sequence_of(project).segments] == [3000, 4000]
    assert not project.video_tracks[0].locked
    assert len(project.audio_tracks[0].clips) == 2
    assert all(c.playback_rate == 1 for c in project.audio_tracks[0].clips)
    stack.undo()
    restored = project.to_dict()
    for key in ("media", "media_pool", "video_tracks", "audio_tracks", "edit_sequence"):
        assert restored[key] == before[key]
    stack.redo()
    project.video_tracks[0].locked = True
    sequence_of(project).video_track_locked = True
    stack.push(MediaDropCommand(project, results, 3000, project.video_tracks[0].id))
    assert project.video_tracks[0].locked
    assert len(project.video_tracks) == 2
    assert not project.video_tracks[1].locked
    assert len(project.video_tracks[0].clips) == 2


def test_request_identity_and_short_overlap_evidence():
    rows = [{"speaker":"S01", "start":0., "end":2., "text":"甲嗯乙", "tokens":[
        {"start":0.,"end":.8,"text":"甲"}, {"start":.8,"end":1.,"text":"嗯"},
        {"start":1.,"end":2.,"text":"乙"}]}]
    assert scope_request_speakers(rows,0,2)[0]["speaker"] != scope_request_speakers(rows,1,2)[0]["speaker"]
    acoustic = [{"start":0.,"end":.8,"speaker":"S01"},
        {"start":.8,"end":1.,"speaker":"S02"}, {"start":1.,"end":2.,"speaker":"S01"}]
    hybrid = fuse_moss_speakers(rows,acoustic)
    assert [r["speaker"] for r in hybrid] == ["S01","S02","S01"]
    acoustic.append({"start":.8,"end":1.,"speaker":"S01"})
    ambiguous = fuse_moss_speakers(rows,acoustic)[1]
    assert ambiguous["speaker"] == "S00"
    assert ambiguous["text"] == "嗯"
    assert ambiguous["speaker_evidence"]["needs_confirmation"]


def test_selected_export_keeps_unknown_and_gaps(tmp_path):
    project = SubtitleProject(media=StudioMedia(path="", duration_ms=15000),
        speakers=[StudioSpeaker(id="S00",name="未知"), StudioSpeaker(id="S01",name="一"), StudioSpeaker(id="S02",name="二")],
        cues=[StudioCue("a",1000,2000,"甲",speaker_id="S01"),StudioCue("b",7000,7100,"嗯",speaker_id="S00"),
              StudioCue("c",12000,13000,"乙",speaker_id="S02")])
    project.validate()
    frozen = copy.deepcopy(project)
    artifacts = export_subtitle_artifacts(selected_result(frozen,{"S00","S02"}), tmp_path,"测试",
        SubtitleExportOptions(frozenset({"srt","ass","txt","json"}),"both"))
    assert len(artifacts) == 12
    text = (tmp_path/"测试.srt").read_text(encoding="utf-8")
    assert "00:00:07,000" in text and "00:00:12,000" in text and "甲" not in text
    assert len(project.cues) == 3


def test_single_character_reply_is_not_cleaned_away():
    import subtitle_core  # Initialize the legacy facade before its extracted modules.
    from twobyteasr.recognition.transcript_data import SubtitleCue
    from twobyteasr.subtitle_rules.cue_cleanup import resolve_isolated_single_character_cues
    cues = [SubtitleCue(1,0.,1.,"先走这里",speaker="S01"),
            SubtitleCue(2,.9,1.1,"嗯",speaker="S02"),
            SubtitleCue(3,1.1,2.,"再往前走",speaker="S01")]
    after, resolution = resolve_isolated_single_character_cues(cues)
    assert [(c.text,c.speaker) for c in after] == [(c.text,c.speaker) for c in cues]
    assert not resolution["omitted_ids"]


def test_caption_deadline_uses_source_clock_and_repeated_instance(app):
    from types import SimpleNamespace
    from PySide6.QtCore import QObject
    from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin
    from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence
    class Host(QObject, StudioPlaybackFlowMixin):
        pass
    page = Host()
    page.project = SubtitleProject(media=StudioMedia(path="source.mp4",duration_ms=180000))
    page.project.validate()
    store_sequence(page.project,EditSequence(source_path="source.mp4",source_duration_ms=180000,
        segments=[VideoSegment("a","source.mp4",120000,150000,0,30000),
                  VideoSegment("b","source.mp4",120000,150000,30000,60000)]))
    page.timeline = SimpleNamespace(playhead_ms=35000)
    page._active_video_preview_clip_id = "b"
    page._playback_mode = "mapped"
    deadlines=[]
    page.video = SimpleNamespace(_paused=False,_playback_rate=1.,controller=None,
        _playback_clock=SimpleNamespace(generation=1,exact_seek_pending=False,
            media_frame_ms=lambda fps:125000,
            milliseconds_until_media_frame=lambda ms,fps:deadlines.append(ms) or ms-125000))
    page.session = SimpleNamespace(runtime=SimpleNamespace(_cue_starts=[36000],cues_at=lambda ms:[]))
    assert page._caption_sample_ms() == 35000
    page._arm_caption_boundary(35000)
    assert deadlines == [126000]
    assert page._caption_boundary_timer.interval() == 1000
    page._caption_boundary_timer.stop()


def test_primary_clip_rate_is_applied_once_to_decoder(app):
    from types import SimpleNamespace
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    from twobyteasr.playback.playback_clock import PlaybackClock
    class FakeCanvas:
        _decoder_speed=MpvCanvas._decoder_speed
        set_source_rate_multiplier=MpvCanvas.set_source_rate_multiplier
        _source_rate_multiplier=1.
        _playback_rate=1.
        def visual_position(self):return 120.
        def _adopt_playback_snapshot(self,snapshot,**kwargs):
            self._playback_rate=snapshot.playback_rate/self._source_rate_multiplier
    canvas=FakeCanvas();speeds=[]
    canvas.controller=SimpleNamespace(post_set_speed=lambda value:speeds.append(value) or True)
    canvas._playback_clock=PlaybackClock()
    canvas.set_source_rate_multiplier(2.)
    assert speeds==[2.]
    assert canvas._playback_rate==1.
    assert canvas._playback_clock.snapshot().playback_rate==2.
    assert canvas._decoder_speed(4.)==8.
    canvas.set_source_rate_multiplier(1.)
    assert speeds==[2.,1.]
    assert canvas._playback_rate==1.
