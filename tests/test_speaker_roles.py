"""Main / secondary speaker roles and the shared timeline row (2026-10-12)."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.recognition import speaker_roles as roles
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject

MIN = 60_000


def cue(id, start, end, speaker, text=None, refs=None):
    return StudioCue(id, start, end, text or f"line {id}", speaker, evidence_refs=list(refs or [f"segment:{id}"]))


def spaced(speaker, count, start, step, prefix=None):
    return [cue(f"{prefix or speaker}{i}", start + i * step, start + i * step + 900, speaker) for i in range(count)]


def test_split_lines_and_overlap_duplicates_count_once():
    lines = [cue("a1", 0, 800, "S1", "前半", ["segment:7"]), cue("a2", 800, 1600, "S1", "後半", ["segment:7"]),
             cue("a3", 5000, 6000, "S1", "同じ"), cue("a4", 5400, 6200, "S1", "同じ")]  # chunk duplicate
    assert len(roles.utterances(lines)["S1"]) == 2


def test_the_two_speakers_with_most_subtitles_keep_own_tracks():
    # 2026-10-22 (user): 只挑最多字幕的两轨 + 一轨其它全部角色.
    lines = spaced("S1", 11, 5 * MIN, 50_000) + spaced("S2", 40, 0, 30_000) + spaced("S3", 30, 1000, 30_000)
    result = roles.classify(lines, 24 * MIN)
    assert {key for key, row in result["speakers"].items() if row["role"] == "main"} == {"S2", "S3"}
    assert result["speakers"]["S1"]["role"] == "secondary" and result["speakers"]["S1"]["note"] == "over cap"
    assert result["cap"] == 2 and "2 位" in result["rule"]
    assert {key for key, row in roles.classify(lines, 24 * MIN, cap=1)["speakers"].items()
            if row["role"] == "main"} == {"S2"}


def test_equal_counts_go_to_more_speech_and_manual_choices_win():
    lines = spaced("S1", 5, 0, 40_000) + [cue(f"long{i}", 300_000 + i * 20_000, 310_000 + i * 20_000, "S2") for i in range(5)]
    lines += spaced("S3", 5, 1000, 40_000)
    result = roles.classify(lines, 24 * MIN, cap=1)
    assert result["speakers"]["S2"]["role"] == "main"
    result = roles.classify(lines, 24 * MIN, manual={"S3": "own"})
    assert result["speakers"]["S3"]["role"] == "own" and result["speakers"]["S3"]["source"] == "manual"


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
    from twobyteasr.studio.studio_timeline import WaveformTimeline
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
    # The widget minimum no longer grows with the number of speakers; since
    # 2026-10-22 it counts one subtitle row (the rows scroll).
    assert timeline.minimumHeight() < max(180, timeline.RULER_HEIGHT + timeline._pinned_bottom_height(minimum=True) + 2 * 52)


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
    from twobyteasr.studio import studio_speaker_roles as studio_roles
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
    from twobyteasr.rendering.ass_compiler import compile_ass
    from twobyteasr.projects.studio_project import load_project, save_project
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


def test_main_tracks_follow_the_default_and_a_picked_cap_is_undoable(application):
    # Eight busy speakers: two automatic main tracks by default, the ones with most subtitles.
    lines = []
    for index in range(8):
        lines += spaced(f"S{index + 1}", 30 - index, index * 1000, 25_000)
    result = roles.classify(lines, 24 * MIN)
    mains = sorted(key for key, row in result["speakers"].items() if row["role"] == "main")
    assert mains == ["S1", "S2"]
    assert result["speakers"]["S3"]["note"] == "over cap"
    assert len([1 for row in roles.classify(lines, 24 * MIN, cap=3)["speakers"].values() if row["role"] == "main"]) == 3
    project = SubtitleProject(media=StudioMedia("", duration_ms=24 * MIN),
                              speakers=[StudioSpeaker(f"S{i + 1}") for i in range(8)], cues=lines)
    project.validate()
    from twobyteasr.studio import studio_speaker_roles as studio_roles
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    timeline = WaveformTimeline()
    timeline.set_project(project)
    page = SimpleNamespace(project=project, undo_stack=QUndoStack(), timeline=timeline, save_state=None)
    studio_roles.organize(page)
    state = project.studio_state["speaker_roles"]
    assert state["cap"] == 2 and not state["cap_chosen"] and len(timeline._group_members) == 6
    studio_roles.organize(page, cap=3)
    state = project.studio_state["speaker_roles"]
    assert state["cap"] == 3 and state["cap_chosen"] and len(timeline._group_members) == 5
    # A picked cap is the project's own: a different default leaves it alone.
    assert not roles.refresh_automatic_roles(project, 5)
    page.undo_stack.undo()
    timeline.reindex_project()
    assert project.studio_state["speaker_roles"]["cap"] == 2
    timeline.close()


def test_older_automatic_groups_follow_the_new_rule_when_opened():
    project = project_with_roles()
    # The 2026-10-13 rule kept up to five busy speakers.
    old = roles.decide(project)
    old.update(policy="speaker-roles-v2", cap=5, cap_chosen=False)
    old["auto"] = {key: "main" for key in old["auto"]}
    old.pop("cap_chosen")
    old["manual"] = {"S6": "own"}
    project.studio_state["speaker_roles"] = old
    assert roles.refresh_automatic_roles(project, None)
    state = project.studio_state["speaker_roles"]
    assert state["policy"] == roles.POLICY and state["cap"] == 2 and state["manual"] == {"S6": "own"}
    assert set(roles.group_members(project)) == {"S3", "S4", "S5"}
    assert not roles.refresh_automatic_roles(project, 2)          # nothing to do
    assert roles.refresh_automatic_roles(project, 3)              # the default changed
    assert project.studio_state["speaker_roles"]["cap"] == 3
    ungrouped = project_with_roles(grouped=False)
    assert not roles.refresh_automatic_roles(ungrouped, 2) and "speaker_roles" not in ungrouped.studio_state
