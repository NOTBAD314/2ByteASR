"""只重新识别这一段字幕 (2026-10-25): recognize only the in/out stretch again.

The Studio's in/out points name a stretch that came out wrong. The ordinary
recognition (same sheet, same pipeline) hears only that stretch; its result
replaces the captions there and nothing else, as one undo step.
"""
from __future__ import annotations

import copy
import json
import os
import wave
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from twobyteasr.projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                                load_project, save_project)
from twobyteasr.recognition import range_recognition as rr
from twobyteasr.recognition.recognition_input import (attach_timeline_result, capture_recognition_snapshot,
                                                      prepare_recognition_input)
from twobyteasr.timeline.studio_caption_timeline import CLOCK, KEY, ensure_independent_captions
from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment, sequence_of, store_sequence
from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence

RATE = 16000
FFMPEG = Path(__file__).resolve().parents[1] / "tools/ffmpeg/bin/ffmpeg.exe"


def _source(tmp_path) -> Path:
    path = tmp_path / "source.wav"
    if not path.is_file():
        # 25 one-second tones, each its own pitch: any stretch is recognizable.
        pcm = np.concatenate([.15 * np.sin(2 * np.pi * (200 + 50 * i) * np.arange(RATE) / RATE)
                              for i in range(25)])
        with wave.open(str(path), "wb") as out:
            out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            out.writeframes((pcm * 32767).astype("<i2").tobytes())
    return path


def _project(tmp_path) -> SubtitleProject:
    source = _source(tmp_path)
    project = SubtitleProject(media=StudioMedia(path=str(source), duration_ms=25000, width=160, height=90))
    project.validate()
    project.speakers = [StudioSpeaker("HOST", name="主播"), StudioSpeaker("GUEST", name="嘉宾")]
    project.cues = [
        StudioCue("a", 1000, 3000, "前面不动", "HOST", original_text="前面不动"),
        StudioCue("b", 9500, 11000, "识别错了一", "HOST", original_text="识别错了一"),
        StudioCue("c", 11500, 13000, "识别错了二", "GUEST", original_text="识别错了二"),
        StudioCue("d", 13800, 15500, "跨出点的一句", "HOST", original_text="跨出点的一句"),
        StudioCue("e", 20000, 22000, "后面不动", "GUEST", original_text="后面不动"),
    ]
    sequence = EditSequence(source_path=str(source), source_duration_ms=25000, video_track_locked=False,
                            segments=[VideoSegment("full", str(source), 0, 25000, 0, 25000)])
    store_sequence(project, sequence)
    sync_primary_video_track_from_sequence(project, sequence)
    ensure_independent_captions(project)
    sequence_of(project).in_point_ms, sequence_of(project).out_point_ms = 10000, 14000
    return project


def _recognized(window_ms: int) -> SubtitleProject:
    """A range run's own result: window-local time, anonymous speakers, measured words."""
    evidence = {
        "segment:1": {"start_ms": 200, "end_ms": 1500, "text": "改好了一", "final_timing_owner": "MOSS",
                      "words": [{"text": "改好", "start_ms": 200, "end_ms": 800},
                                {"text": "了一", "start_ms": 800, "end_ms": 1500}]},
        "segment:2": {"start_ms": 1800, "end_ms": 3200, "text": "改好了二", "final_timing_owner": "MOSS",
                      "words": [{"text": "改好", "start_ms": 1800, "end_ms": 2500},
                                {"text": "了二", "start_ms": 2500, "end_ms": 3200}]},
        "segment:3": {"start_ms": 4000, "end_ms": window_ms, "text": "最后一句", "final_timing_owner": "MOSS",
                      "words": [{"text": "最后", "start_ms": 4000, "end_ms": 4800},
                                {"text": "一句", "start_ms": 4800, "end_ms": window_ms}]},
    }
    return SubtitleProject(
        media=StudioMedia(path=""),
        speakers=[StudioSpeaker("S00"), StudioSpeaker("S01")],
        cues=[StudioCue("c1", 200, 1500, "改好了一", "S00", evidence_refs=["segment:1"]),
              StudioCue("c2", 1800, 3200, "改好了二", "S01", evidence_refs=["segment:2"]),
              StudioCue("c3", 4000, window_ms, "最后一句", "S00", evidence_refs=["segment:3"])],
        asr_evidence=evidence)


# ---------------------------------------------------------------- rules


def test_window_takes_cut_captions_whole_and_problems_say_why(tmp_path):
    project = _project(tmp_path)
    start, end, ids = rr.recognition_window(project, 10000, 14000)
    # b starts before the in point, d ends after the out point: both whole.
    assert (start, end, ids) == (9500, 15500, ["b", "c", "d"])
    assert rr.range_problem(project) == ""
    sequence = sequence_of(project)
    sequence.out_point_ms = None
    assert rr.range_problem(project) == "先设好入点和出点"
    sequence.out_point_ms = 10500
    assert rr.range_problem(project) == "这一段太短（至少 1 秒）"
    sequence.out_point_ms = 9000
    assert rr.range_problem(project) == "入点要早于出点"
    sequence.out_point_ms = 14000
    assert rr.range_problem(project, running=True) == "正在识别，等这次识别完成"
    assert rr.range_problem(project, locked={"GUEST"}) == "这一段有锁定的字幕轨，先解锁"
    assert rr.range_problem(project, locked={"OTHER"}) == ""


def test_edited_captions_are_text_changed_by_hand(tmp_path):
    project = _project(tmp_path)
    project.cues[2].text = "我手改过"
    assert rr.edited_cue_ids(project, ["b", "c", "d"]) == ["c"]


# ---------------------------------------------------------------- snapshot and audio


def test_snapshot_hears_only_the_stretch(tmp_path):
    project = _project(tmp_path)
    snapshot = capture_recognition_snapshot(project, range_ms=(9500, 15500))
    other = capture_recognition_snapshot(project, range_ms=(1000, 7000))
    assert snapshot["duration_ms"] == 6000 and snapshot["range_ms"] == [9500, 15500]
    assert snapshot["fingerprint"] != other["fingerprint"]       # same length, other stretch
    full = capture_recognition_snapshot(project)
    assert "range_ms" not in full and full["duration_ms"] == 25000
    with pytest.raises(ValueError):
        capture_recognition_snapshot(project, range_ms=(20000, 26000))
    if not FFMPEG.is_file():
        pytest.skip("tools/ffmpeg is not in this checkout")
    path = prepare_recognition_input(snapshot, tmp_path / "cache", FFMPEG)
    with wave.open(path, "rb") as wav:
        assert wav.getnframes() == 6000 * 16
        heard = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    with wave.open(project.media.path, "rb") as wav:
        source = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    expected = source[9500 * 16:15500 * 16]
    inner = slice(1600, len(expected) - 1600)
    assert np.corrcoef(heard[inner], expected[inner])[0, 1] > .999
    manifest = json.loads((Path(path).parent / "input.json").read_text(encoding="utf-8"))
    assert manifest["project_range_ms"] == [9500, 15500]
    other_path = prepare_recognition_input(other, tmp_path / "cache", FFMPEG)
    assert other_path != path


# ---------------------------------------------------------------- delivery


def test_result_project_replaces_only_the_stretch(tmp_path):
    from twobyteasr.projects.subtitle_consistency import validate_project
    project = _project(tmp_path)
    snapshot = capture_recognition_snapshot(project, str(tmp_path / "studio.2byteproj"), range_ms=(9500, 15500))
    snapshot["requested_range_ms"] = [10000, 14000]
    result = attach_timeline_result(_recognized(6000), snapshot)
    by_id = {cue.id: cue for cue in result.cues}
    # Outside the stretch: the same captions, ids and speakers.
    assert [(c.id, c.text) for c in result.cues if c.id in {"a", "e"}] == [("a", "前面不动"), ("e", "后面不动")]
    assert not {"b", "c", "d"} & set(by_id)
    info = result.generation_metadata["timeline_recognition"]["range"]
    new = [by_id[cue_id] for cue_id in info["cue_ids"]]
    assert [(c.start_ms, c.end_ms, c.text) for c in new] == [
        (9700, 11000, "改好了一"), (11300, 12700, "改好了二"), (13500, 15500, "最后一句")]
    # Anonymous speakers land on the tracks they overlap; no new tracks.
    assert [c.speaker_id for c in new] == ["HOST", "GUEST", "HOST"]
    assert [s.id for s in result.speakers] == ["HOST", "GUEST"]
    assert info["replaced_cue_ids"] == ["b", "c", "d"] and info["requested_ms"] == [10000, 14000]
    # Evidence keeps its own clock; receipts carry words on project time.
    receipt = result.studio_state[KEY]["instances"][new[0].id]
    assert receipt[CLOCK] == 9500
    assert [(w["text"], w["start_ms"], w["end_ms"]) for w in receipt["words"]] == [
        ("改好", 9700, 10300), ("了一", 10300, 11000)]
    assert all(ref.startswith("range-") and ref in result.asr_evidence for ref in new[0].evidence_refs)
    assert result.asr_evidence[new[0].evidence_refs[0]]["start_ms"] == 200
    archive = {row["id"] for row in result.studio_state[KEY]["source_archive"]}
    assert set(info["cue_ids"]) <= archive
    assert not validate_project(result).errors
    from twobyteasr.recognition.cue_word_alignment import cue_words
    words, _reason = cue_words(result, new[1])
    assert [(w.text, w.start_ms) for w in words] == [("改好", 11300), ("了二", 12000)]
    # A stretch without captions takes the speaker of the nearest caption
    # (e, 4.5 s after it, not a, 6.5 s before).
    project.cues = [cue for cue in project.cues if cue.id in {"a", "e"}]
    lone = attach_timeline_result(_recognized(6000), capture_recognition_snapshot(project, range_ms=(9500, 15500)))
    assert {c.speaker_id for c in lone.cues if c.id not in {"a", "e"}} == {"GUEST"}


def test_delivery_writes_a_verified_result_and_skips_the_library(tmp_path, monkeypatch):
    import twobyteasr.projects.studio_project as storage
    from twobyteasr.recognition.recognition_result import media_identity_for_task, verify_result_reference
    from twobyteasr.recognition.run_context import RuntimeContext
    registered = []
    monkeypatch.setattr(storage, "register_recent_project", lambda *a, **k: registered.append(a))
    project = _project(tmp_path)
    studio_path = save_project(project, tmp_path / "studio" / "studio.2byteproj")
    snapshot = capture_recognition_snapshot(project, str(studio_path), range_ms=(9500, 15500))
    target = tmp_path / "studio" / "recognition-results" / "job1" / "识别结果.2byteproj"
    runtime = [SimpleNamespace(cue_id="r1", start=.2, end=1.5, text="改好了一", speaker="S01"),
               SimpleNamespace(cue_id="r2", start=1.8, end=3.2, text="改好了二", speaker="S02")]
    identity = media_identity_for_task(project.media.path, RuntimeContext())
    outputs = storage.create_studio_outputs(project.media.path, runtime, txt_path="", target_project_path=str(target),
                                            generation_metadata={"job_id": "job1", "media_identity": identity},
                                            recognition_snapshot=snapshot)
    assert registered == []
    delivered = verify_result_reference(outputs["result_ref_json"])
    texts = [cue.text for cue in delivered.cues]
    assert texts == ["前面不动", "改好了一", "改好了二", "后面不动"]
    assert load_project(studio_path).cues[1].text == "识别错了一"      # the Studio project is untouched


# ---------------------------------------------------------------- undo


def _plan_from_result(project, tmp_path, *, requested=(10000, 14000)):
    window = rr.recognition_window(project, *requested)[:2]
    snapshot = capture_recognition_snapshot(project, str(tmp_path / "studio.2byteproj"), range_ms=window)
    snapshot["requested_range_ms"] = list(requested)
    result = attach_timeline_result(_recognized(window[1] - window[0]), snapshot)
    info = result.generation_metadata["timeline_recognition"]["range"]
    return snapshot, result, rr.splice_range(project, info["window_ms"], rr.payload_from_result(result, info),
                                             foreign_speakers=False)


def test_one_undo_step_restores_everything(tmp_path):
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication
    from twobyteasr.timeline.range_replace import ReplaceRangeCuesCommand
    QApplication.instance() or QApplication([])
    project = _project(tmp_path)
    project.generation_metadata["translations"] = {"b": "wrong one", "a": "keep"}
    before = copy.deepcopy(project.to_dict())
    _snapshot, _result, plan = _plan_from_result(project, tmp_path)
    stack = QUndoStack()
    stack.push(ReplaceRangeCuesCommand(project, plan, rr.history_entry(plan, (10000, 14000))))
    assert stack.count() == 1
    assert [cue.text for cue in project.cues] == ["前面不动", "改好了一", "改好了二", "最后一句", "后面不动"]
    assert project.generation_metadata["translations"] == {"a": "keep"}
    assert set(plan.evidence) <= set(project.asr_evidence)
    assert project.generation_metadata[rr.HISTORY_KEY][0]["replaced_cue_ids"] == ["b", "c", "d"]
    after = copy.deepcopy(project.to_dict())
    stack.undo()
    restored = project.to_dict()
    for key in ("cues", "asr_evidence", "studio_state", "generation_metadata", "speakers"):
        assert restored[key] == before[key], key
    stack.redo()
    again = project.to_dict()
    for key in ("cues", "asr_evidence", "studio_state", "generation_metadata"):
        assert again[key] == after[key], key


# ---------------------------------------------------------------- Studio


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _page(tmp_path, monkeypatch):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = _project(tmp_path)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *a, **k: None)
    page.open_project(save_project(project, tmp_path / "studio" / "studio.2byteproj"))
    _app().processEvents()
    page._media_ingest_state = "READY"
    page._empty_playback_state = False
    return page


def _menu_actions(page, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    from twobyteasr.studio import studio_ui
    menus = []

    def menu_without_exec(parent=None, **_options):
        menu = QMenu(parent)
        menu.exec = lambda *_args: None
        menus.append(menu)
        return menu

    monkeypatch.setattr(studio_ui, "create_studio_menu", menu_without_exec)
    page._show_timeline_menu("", QPoint(0, 0))
    return [action for action in menus[-1].actions() if action.objectName() == "rangeRecognitionAction"]


def test_timeline_menu_offers_the_range_and_says_why_not(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    [action] = _menu_actions(page, monkeypatch)
    assert action.isEnabled() and action.text().startswith("只重新识别这一段字幕")
    sequence_of(page.project).out_point_ms = None
    [action] = _menu_actions(page, monkeypatch)
    assert not action.isEnabled() and "先设好入点和出点" in action.text()
    page.close_page()


def test_sheet_names_the_stretch_and_confirms_edited_captions(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    page.project.cues[2].text = "我手改过"
    emitted = []
    page.recognition_requested.connect(lambda *args: emitted.append(args))
    page._open_recognition_sheet(range_ms=(10000, 14000))
    emitted.clear()      # without a main window the sheet also asks it to configure
    controls = page._recognition_controls
    assert controls["range"]["window"] == (9500, 15500)
    notes = [label.text() for label in controls["range_notes"]]
    assert "3 条字幕" in notes[0] and "00:00:09.500" in notes[0]
    assert len(notes) == 2                       # the in/out points cut captions
    assert controls["local_analysis"].isHidden() and controls["translation"].isHidden()
    controls["start"].click()
    assert emitted == [] and not controls["confirm"].isHidden()
    assert "1 条字幕你改过" in controls["confirm_text"].text()
    controls["confirm_replace"].click()
    assert emitted and emitted[0][0] == "start_final"
    options = page.recognition_request_options()
    assert options["recognition_range_ms"] == [9500, 15500] and options["replace_policy"] == "replace_range"
    assert options["requested_range_ms"] == [10000, 14000] and options["subtitle_output"] == "original"
    assert page._recognition_replace_baseline_ids is None
    # Live rows of a range run are window-local: never put into the project.
    count = len(page.project.cues)
    page.apply_recognition_cue_delta({"source_path": page.project.media.path, "state": "provisional",
                                      "cues": [{"id": "live", "start_ms": 0, "end_ms": 900, "text": "临时"}]})
    assert len(page.project.cues) == count
    page.close_page()


def test_finished_range_replaces_the_stretch_as_one_undo_step(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    snapshot, result, _plan = _plan_from_result(page.project, tmp_path)
    path = save_project(result, tmp_path / "studio" / "recognition-results" / "job" / "识别结果.2byteproj")
    before = [cue.text for cue in page.project.cues]
    undo = page.undo_stack.count()
    assert page.apply_range_recognition_result(str(path), snapshot)
    assert [cue.text for cue in page.project.cues] == ["前面不动", "改好了一", "改好了二", "最后一句", "后面不动"]
    assert page.undo_stack.count() == undo + 1
    assert page.cue_model.rowCount() == 5
    page.undo_stack.undo()
    assert [cue.text for cue in page.project.cues] == before
    page.close_page()


def test_stretch_edited_meanwhile_is_asked_and_moved_edit_is_refused(tmp_path, monkeypatch):
    from twobyteasr.studio import studio_range_recognition
    page = _page(tmp_path, monkeypatch)
    snapshot, result, _plan = _plan_from_result(page.project, tmp_path)
    path = save_project(result, tmp_path / "studio" / "recognition-results" / "job" / "识别结果.2byteproj")
    page.project.cues[1].text = "识别期间改的"
    answers = []
    monkeypatch.setattr(studio_range_recognition, "ask_replace_edited", lambda _page: answers.append(1) or False)
    assert not page.apply_range_recognition_result(str(path), snapshot)
    assert answers and page.project.cues[1].text == "识别期间改的"
    monkeypatch.setattr(studio_range_recognition, "ask_replace_edited", lambda _page: True)
    assert page.apply_range_recognition_result(str(path), snapshot)
    assert "改好了一" in [cue.text for cue in page.project.cues]
    page.undo_stack.undo()
    sequence_of(page.project).segments[0].timeline_out_ms = 24000      # the edit changed meanwhile
    assert not page.apply_range_recognition_result(str(path), snapshot)
    page.close_page()


# ---------------------------------------------------------------- main window


def test_main_window_hands_a_finished_range_to_the_studio():
    from twobyteasr.app.ui import MainWindow
    calls = []
    studio = SimpleNamespace(apply_range_recognition_result=lambda path, snap: calls.append((path, snap)),
                             note_recognition_kept_in_memory=lambda: calls.append("kept"))
    snapshot = {"range_ms": [1, 2], "project_id": "p"}
    window = SimpleNamespace(_studio_recognition_context={"snapshot": snapshot}, studio_page=studio)
    MainWindow._finish_studio_recognition(window, "result.2byteproj")
    assert calls == [("result.2byteproj", snapshot)] and window._studio_recognition_context is None
