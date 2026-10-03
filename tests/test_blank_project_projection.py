"""Blank and unknown-duration sequences remain safe caption inputs."""
import copy
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from twobyteasr.studio_edit_sequence import (
    EditSequence,
    VideoSegment,
    caption_continuous_segments,
    projected_cues,
    sequence_of,
)
from twobyteasr.studio_project import (
    StudioMedia,
    SubtitleProject,
    load_project,
    save_project,
)


@pytest.mark.parametrize("domain", ["timeline", "source"])
@pytest.mark.parametrize("stage", ["constructed", "validated", "reopened"])
def test_blank_project_caption_projection_survives_creation_and_reopen(
    domain, stage, tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path="", display_name="未命名工程", duration_ms=0)
    )
    if stage == "validated":
        project.validate()
    elif stage == "reopened":
        project = load_project(save_project(project, tmp_path / "blank.2byteproj"))

    assert projected_cues(project, domain=domain) == []
    assert project.media.path == ""
    assert project.media.duration_ms == 0
    assert project.media_pool == []
    assert project.video_tracks == []
    assert project.cues == []
    sequence = sequence_of(project)
    assert sequence.is_identity()
    assert sequence.timeline_duration_ms == 0


@pytest.mark.parametrize("count", [1, 2, 3])
def test_zero_duration_identity_and_siblings_are_preserved_without_mutation(count):
    sequence = EditSequence(
        segments=[VideoSegment(f"piece-{index}", "", 0, 0, 0, 0) for index in range(count)],
        segment_lineage={f"piece-{index}": ["piece-0"] for index in range(1, count)},
    )
    before = copy.deepcopy(sequence)

    result = caption_continuous_segments(sequence)

    assert result == before.segments
    assert sequence == before
    assert all(after is not original for after, original in zip(result, sequence.segments))


def test_zero_total_invalid_group_is_preserved_without_treating_it_as_media():
    # This direct helper input intentionally bypasses persistence validation.
    # Opposing ranges cannot define the affine map used to rejoin real cuts.
    sequence = EditSequence(
        source_path="invalid-range.mp4",
        segments=[
            VideoSegment("original", "", 10, 20, 5, 10),
            VideoSegment("child", "", 20, 10, 10, 5),
        ],
        segment_lineage={"child": ["original"]},
    )
    before = copy.deepcopy(sequence)

    assert caption_continuous_segments(sequence) == before.segments
    assert sequence == before


def test_real_razor_siblings_still_rejoin_with_integer_source_rounding():
    sequence = EditSequence(
        source_path="real-range.mp4",
        source_duration_ms=1017,
        segments=[
            VideoSegment("original", "", 1000, 1007, 2000, 2004),
            VideoSegment("right", "", 1007, 1012, 2004, 2007),
            VideoSegment("tail", "", 1012, 1017, 2007, 2010),
        ],
        segment_lineage={"right": ["original"], "tail": ["right", "original"]},
    )
    before = copy.deepcopy(sequence)

    result = caption_continuous_segments(sequence)

    assert result == [VideoSegment("original", "", 1000, 1017, 2000, 2010)]
    assert sequence == before
