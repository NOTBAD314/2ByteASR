import copy
import wave
from pathlib import Path

import numpy as np
import pytest

from twobyteasr.recognition.recognition_input import (capture_recognition_snapshot,
    prepare_recognition_input, attach_timeline_result)
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.timeline.studio_edit_sequence import (EditSequence, VideoSegment,
    store_sequence, projected_cues, timeline_duration_ms)
from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence


@pytest.fixture
def project(tmp_path):
    source = tmp_path / "source.wav"
    rate = 16000
    pcm = np.concatenate([.15*np.sin(2*np.pi*(200+50*i)*np.arange(rate)/rate)
                          for i in range(25)])
    with wave.open(str(source), "wb") as out:
        out.setparams((1,2,rate,0,"NONE","not compressed"))
        out.writeframes((pcm*32767).astype("<i2").tobytes())
    p = SubtitleProject(media=StudioMedia(path=str(source),duration_ms=25000,width=160,height=90))
    p.validate()
    p.cues = [StudioCue("original",21000,22000,"原稿")]
    seq = EditSequence(source_path=str(source),source_duration_ms=25000,video_track_locked=False,
        segments=[VideoSegment(f"cut{i}",str(source),a,a+1000,i*1000,(i+1)*1000)
                  for i,a in enumerate((2000,10000,20000))])
    store_sequence(p,seq)
    sync_primary_video_track_from_sequence(p,seq)
    return p


def test_noncontiguous_audio_and_all_branches_identity(project,tmp_path):
    snapshot = capture_recognition_snapshot(project)
    assert snapshot["duration_ms"] == 3000
    assert [s["source_in_ms"] for s in snapshot["audio_graph"]["segments"]] == [2000,10000,20000]
    ffmpeg = Path(__file__).resolve().parents[1]/"tools/ffmpeg/bin/ffmpeg.exe"
    path = prepare_recognition_input(snapshot,tmp_path,ffmpeg)
    with wave.open(path,"rb") as wav:
        actual = np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2")
        assert wav.getnframes() == 48000
    with wave.open(project.media.path,"rb") as wav:
        original = np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2")
    expected = np.concatenate([original[a*16:(a+1000)*16] for a in (2000,10000,20000)])
    # Export mix resamples via 48k. Boundary filter ringing is expected;
    # correlation and interior amplitude verify source content and no doubling.
    for i in range(3):
        a,b = actual[i*16000+100:(i+1)*16000-100], expected[i*16000+100:(i+1)*16000-100]
        assert np.corrcoef(a,b)[0,1] > .999
        assert abs(np.std(a)/np.std(b)-1) < .002
    assert prepare_recognition_input(snapshot,tmp_path,ffmpeg) == path


def test_fingerprint_changes_for_reorder_repeat_rate_mute_gain(project):
    original = capture_recognition_snapshot(project)["fingerprint"]
    for mutate in (
        lambda p: setattr(p.video_tracks[0].clips[0],"source_in_ms",3000),
        lambda p: setattr(p.video_tracks[0].clips[0],"playback_rate",2.),
        lambda p: setattr(p.audio_tracks[0],"muted",True),
        lambda p: p.studio_state.update(audio_track_gain_db={"A1":-6}),
    ):
        other = copy.deepcopy(project)
        mutate(other)
        assert capture_recognition_snapshot(other)["fingerprint"] != original
    project.video_tracks[0].locked = True
    assert capture_recognition_snapshot(project)["audio_graph"]["segments"]


def test_result_is_timeline_local_and_does_not_overwrite_full(project):
    snapshot = capture_recognition_snapshot(project)
    recognized = SubtitleProject(media=StudioMedia(path=""),cues=[StudioCue("result",2100,2900,"最后一段")])
    result = attach_timeline_result(recognized,snapshot)
    assert result.project_id != project.project_id
    assert project.cues[0].text == "原稿"
    assert [(c.start_ms,c.end_ms) for c in projected_cues(result)] == [(2100,2900)]
    assert [(c.start_ms,c.end_ms) for c in projected_cues(result,domain="source")] == [(20100,20900)]
    reloaded = SubtitleProject.from_dict(result.to_dict())
    assert projected_cues(reloaded)[0].text == "最后一段"
    assert timeline_duration_ms(reloaded) == 3000
    # A cue crossing an edit boundary must not duplicate its full sentence.
    result.cues.append(StudioCue("boundary",900,1100,"跨切点回应"))
    assert len(projected_cues(result)) == 2


def test_new_recognition_does_not_inherit_old_host_or_hidden_anonymous_id(project):
    from twobyteasr.projects.studio_project import StudioSpeaker
    project.speakers=[StudioSpeaker('NEMO_01',is_host=True),StudioSpeaker('OLD')]
    project.studio_state.update(speaker_track_order=['OLD','NEMO_01'],
                               subtitle_track_visibility={'NEMO_01':False},last_selected_cue='old-cue')
    snapshot=capture_recognition_snapshot(project)
    recognized=SubtitleProject(media=StudioMedia(path=''),speakers=[StudioSpeaker('NEMO_01')],
        cues=[StudioCue('new',0,1000,'新说话人','NEMO_01')])
    result=attach_timeline_result(recognized,snapshot)
    assert [s.id for s in result.speakers]==['NEMO_01']
    assert not result.speakers[0].is_host
    assert result.studio_state['speaker_track_order']==['NEMO_01']
    assert not result.studio_state['subtitle_track_visibility']
    assert 'last_selected_cue' not in result.studio_state
    assert result.generation_metadata['timeline_recognition']['original_speakers'][0]['is_host']
    assert project.speakers[0].is_host  # Source and restoration evidence stay intact.


def test_restore_original_and_undo_keep_both_domains(project):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    from twobyteasr.timeline.studio_edit_commands import restore_full_sequence_command
    app = QApplication.instance() or QApplication([])
    snapshot = capture_recognition_snapshot(project)
    recognized = SubtitleProject(media=StudioMedia(path=""),cues=[StudioCue("original",2100,2900,"改稿")])
    result = attach_timeline_result(recognized,snapshot)
    stack = QUndoStack()
    stack.push(restore_full_sequence_command(result))
    assert "timeline_recognition" not in result.generation_metadata
    assert [(c.text,c.start_ms) for c in projected_cues(result)] == [("原稿",21000)]
    stack.undo()
    assert [(c.text,c.start_ms) for c in projected_cues(result)] == [("改稿",2100)]


def test_rate_and_gap_are_preserved(project,tmp_path):
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    seq = copy.deepcopy(sequence_of(project))
    seq.segments = [VideoSegment("cut0",project.media.path,2000,4000,1000,2000),
                    VideoSegment("repeat",project.media.path,2000,4000,3000,5000)]
    store_sequence(project,seq)
    sync_primary_video_track_from_sequence(project,seq)
    snapshot = capture_recognition_snapshot(project)
    assert snapshot["duration_ms"] == 5000
    assert [s["playback_rate"] for s in snapshot["audio_graph"]["segments"]] == [2.,1.]
    ffmpeg = Path(__file__).resolve().parents[1]/"tools/ffmpeg/bin/ffmpeg.exe"
    path = prepare_recognition_input(snapshot,tmp_path,ffmpeg)
    with wave.open(path,"rb") as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2")
    assert len(pcm) == 80000
    assert not np.any(pcm[:15900]) and not np.any(pcm[32100:47900])
    assert np.max(np.abs(pcm[16000:32000])) > 1000
