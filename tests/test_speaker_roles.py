"""Main / secondary speaker roles and the shared timeline row (2026-10-12)."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr import speaker_roles as roles
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject

MIN = 60_000


def cue(id, start, end, speaker, text=None, refs=None):
    return StudioCue(id, start, end, text or f"line {id}", speaker, evidence_refs=list(refs or [f"segment:{id}"]))


def spaced(speaker, count, start, step, prefix=None):
    return [cue(f"{prefix or speaker}{i}", start + i * step, start + i * step + 900, speaker) for i in range(count)]


def test_split_lines_and_overlap_duplicates_count_once():
    lines = [cue("a1", 0, 800, "S1", "前半", ["segment:7"]), cue("a2", 800, 1600, "S1", "後半", ["segment:7"]),
             cue("a3", 5000, 6000, "S1", "同じ"), cue("a4", 5400, 6200, "S1", "同じ")]  # chunk duplicate
    assert len(roles.utterances(lines)["S1"]) == 2


def test_sliding_window_not_fixed_blocks():
    # 11 utterances between minute 5 and minute 14: no fixed 0-10 / 10-20
    # block holds more than 10, a sliding 10-minute window does.
    lines = spaced("S1", 11, 5 * MIN, 50_000) + spaced("S2", 40, 0, 30_000)
    result = roles.classify(lines, 24 * MIN)
    assert result["speakers"]["S1"]["role"] == "main"
    lines = spaced("S1", 10, 5 * MIN, 50_000) + spaced("S2", 40, 0, 30_000)
    assert roles.classify(lines, 24 * MIN)["speakers"]["S1"]["role"] == "secondary"


def test_splitting_a_line_does_not_flip_a_role():
    base = spaced("S1", 10, 0, 50_000) + spaced("S2", 40, 0, 30_000)
    before = roles.classify(base, 24 * MIN)["speakers"]["S1"]["role"]
    split = []
    for line in base:
        if line.speaker_id == "S1":
            middle = (line.start_ms + line.end_ms) // 2
            split += [cue(line.id + "a", line.start_ms, middle, "S1", refs=line.evidence_refs),
                      cue(line.id + "b", middle, line.end_ms, "S1", refs=line.evidence_refs)]
        else:
            split.append(line)
    assert roles.classify(split, 24 * MIN)["speakers"]["S1"]["role"] == before == "secondary"


def test_short_media_scaling_top_speaker_and_manual():
    # 4 minutes: the count threshold scales to 4 (more than 4 utterances).
    lines = spaced("S1", 5, 0, 40_000) + spaced("S2", 4, 1000, 40_000) + spaced("S3", 30, 0, 8000)
    result = roles.classify(lines, 4 * MIN)
    assert result["speakers"]["S1"]["role"] == "main" and result["speakers"]["S2"]["role"] == "secondary"
    # Under one minute with few speakers everyone keeps an own track.
    tiny = spaced("S1", 1, 0, 1000) + spaced("S2", 1, 2000, 1000) + spaced("S3", 1, 4000, 1000)
    assert {row["role"] for row in roles.classify(tiny, 30_000)["speakers"].values()} == {"main"}
    # The busiest speaker is always main; manual choices win.
    quiet = spaced("S1", 2, 0, 200_000) + spaced("S2", 1, 1000, 1000)
    result = roles.classify(quiet, 24 * MIN, manual={"S2": "own"})
    assert result["speakers"]["S1"]["role"] == "main" and result["speakers"]["S2"]["source"] == "manual"


def project_with_roles(grouped=True):
    speakers = [StudioSpeaker(f"S{i}") for i in range(1, 7)]
    lines = spaced("S1", 40, 0, 30_000) + spaced("S2", 30, 5000, 40_000)
    # Four quiet speakers; S3 and S4 talk at the same time once.
    lines += [cue("q3", 100_000, 103_000, "S3"), cue("q4", 101_000, 104_000, "S4"),
              cue("q5", 300_000, 301_000, "S5"), cue("q6", 400_000, 401_000, "S6")]
    project = SubtitleProject(media=StudioMedia("", duration_ms=24 * MIN), speakers=speakers, cues=lines)
    project.validate()
    if grouped:
        roles.initialize_for_recognition(project)
    return project


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def timeline(application):
    from twobyteasr.studio_timeline import WaveformTimeline
    widget = WaveformTimeline()
    widget.resize(1200, 520)
    yield widget
    widget.close()


def test_group_row_lanes_hits_and_heights(timeline):
    project = project_with_roles()
    assert set(roles.group_members(project)) == {"S3", "S4", "S5", "S6"}
    timeline.set_project(project)
    timeline.set_visible_window(95_000, 15_000)
    rows = timeline._display_rows()
    assert [kind for kind, _key, _h in rows] == ["group", "speaker", "speaker"]
    rects = timeline._track_layout()[0]
    assert rects["S3"] == rects["S6"] and rects["S3"] != rects["S1"]
    # Simultaneous secondary lines: two sub-lanes, both hittable.
    assert timeline._group_lane_count == 2
    q3, q4 = (next(c for c in project.cues if c.id == key) for key in ("q3", "q4"))
    band3, band4 = timeline._cue_band(q3, rects["S3"]), timeline._cue_band(q4, rects["S4"])
    assert band3.bottom() <= band4.top() + 0.5
    x = round(timeline._time_to_x(102_000))
    assert timeline._cue_at(QPoint(x, round(band3.center().y())))[0].id == "q3"
    assert timeline._cue_at(QPoint(x, round(band4.center().y())))[0].id == "q4"
    assert timeline._speaker_at(QPoint(x, round(band4.center().y()))) == "S4"
    # The widget minimum no longer grows with the number of speakers.
    assert timeline.minimumHeight() <= timeline.RULER_HEIGHT + timeline._pinned_bottom_height(minimum=True) + 4 * 52 + 60


def test_dragging_on_the_group_row_never_hands_a_line_to_another_member(timeline):
    project = project_with_roles()
    timeline.set_project(project)
    timeline.set_visible_window(95_000, 15_000)
    rects = timeline._track_layout()[0]
    q3 = next(c for c in project.cues if c.id == "q3")
    timeline._drag = ("q3", "move", 0, q3.start_ms, q3.end_ms)
    try:
        lane4 = timeline._cue_band(next(c for c in project.cues if c.id == "q4"), rects["S4"])
        assert timeline._speaker_at(QPoint(500, round(lane4.center().y()))) == "S3"
    finally:
        timeline._drag = None


def test_expand_old_project_and_undoable_organize(timeline):
    from twobyteasr import studio_speaker_roles as studio_roles
    project = project_with_roles(grouped=False)
    timeline.set_project(project)
    assert all(kind == "speaker" for kind, _key, _h in timeline._display_rows())   # old project untouched
    page = SimpleNamespace(project=project, undo_stack=QUndoStack(), timeline=timeline, save_state=None)
    studio_roles.organize(page)
    assert [k for k, _key, _h in timeline._display_rows()][0] == "group"
    timeline.set_group_expanded(True)
    kinds = [k for k, _key, _h in timeline._display_rows()]
    assert kinds[0] == "group_header" and kinds.count("speaker") == 6
    timeline.set_group_expanded(False)
    studio_roles.set_role(page, "S5", "own")
    assert "S5" not in timeline._group_members and project.studio_state["speaker_roles"]["manual"] == {"S5": "own"}
    page.undo_stack.undo()
    timeline.reindex_project()
    assert "S5" in timeline._group_members
    page.undo_stack.undo()
    timeline.reindex_project()
    assert "speaker_roles" not in project.studio_state and not timeline._group_members
    page.undo_stack.redo()
    timeline.reindex_project()
    assert timeline._group_members


def test_roles_survive_save_and_never_touch_exports(tmp_path):
    from twobyteasr.ass_compiler import compile_ass
    from twobyteasr.studio_project import load_project, save_project
    plain = project_with_roles(grouped=False)
    before = compile_ass(plain)
    grouped = project_with_roles()
    grouped.studio_state["speaker_roles"]["manual"] = {"S6": "main"}
    assert compile_ass(grouped) == before
    path = save_project(grouped, tmp_path / "roles")
    reopened = load_project(path)
    assert reopened.studio_state["speaker_roles"]["manual"] == {"S6": "main"}
    assert set(roles.group_members(reopened)) == {"S3", "S4", "S5"}
    assert [c.speaker_id for c in reopened.cues] == [c.speaker_id for c in grouped.cues]


def test_main_tracks_are_capped_by_activity_and_cap_is_undoable(application):
    # Eight busy speakers: at most five automatic main tracks, the busiest ones.
    lines = []
    for index in range(8):
        lines += spaced(f"S{index + 1}", 30 - index, index * 1000, 25_000)
    result = roles.classify(lines, 24 * MIN)
    mains = sorted(key for key, row in result["speakers"].items() if row["role"] == "main")
    assert mains == ["S1", "S2", "S3", "S4", "S5"]
    assert result["speakers"]["S6"]["note"] == "over cap"
    assert len([1 for row in roles.classify(lines, 24 * MIN, cap=3)["speakers"].values() if row["role"] == "main"]) == 3
    # 30 s of speech in 10 minutes is no longer enough on its own (v2: 90 s).
    talker = [cue("long", 0, 40_000, "S9")] + spaced("S1", 40, 0, 30_000)
    assert roles.classify(talker, 24 * MIN)["speakers"]["S9"]["role"] == "secondary"
    project = SubtitleProject(media=StudioMedia("", duration_ms=24 * MIN),
                              speakers=[StudioSpeaker(f"S{i + 1}") for i in range(8)], cues=lines)
    project.validate()
    from twobyteasr import studio_speaker_roles as studio_roles
    from twobyteasr.studio_timeline import WaveformTimeline
    timeline = WaveformTimeline()
    timeline.set_project(project)
    page = SimpleNamespace(project=project, undo_stack=QUndoStack(), timeline=timeline, save_state=None)
    studio_roles.organize(page)
    assert project.studio_state["speaker_roles"]["cap"] == 5 and len(timeline._group_members) == 3
    studio_roles.organize(page, cap=3)
    assert project.studio_state["speaker_roles"]["cap"] == 3 and len(timeline._group_members) == 5
    page.undo_stack.undo()
    timeline.reindex_project()
    assert project.studio_state["speaker_roles"]["cap"] == 5
    timeline.close()
