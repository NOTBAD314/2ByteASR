import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.timeline.studio_commands import MergeSpeakerCommand, SetSpeakerCommand
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.studio.studio_ui import SpeakerManagerDialog, SubtitleStudioPage


def _app():
    return QApplication.instance() or QApplication([])


def test_speaker_manager_mutations_keep_timeline_list_save_and_undo_consistent(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=10_000),
        speakers=[
            StudioSpeaker("S01", "S01", "default", "#477f59"),
            StudioSpeaker("S03", "S03", "default", "#9a6f55"),
        ],
        cues=[
            StudioCue("a", 0, 1_000, "第一句", speaker_id="S01"),
            StudioCue("b", 1_200, 2_500, "第二句", speaker_id="S03"),
        ],
    )
    path = save_project(project, tmp_path / "speakers.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)

    manager = SpeakerManagerDialog(page)
    assert list(manager.cards) == ["S01", "S03"]
    assert manager.cards["S01"].meta_label.text() == "1 条字幕 · 1 秒"
    assert manager.cards["S01"].strip.intervals() == [(0, 1_000)]
    manager.close()

    page.undo_stack.push(SetSpeakerCommand(
        page.project, "S01", {"name": "主播"}, changed=page._speaker_structure_changed
    ))
    page.undo_stack.push(MergeSpeakerCommand(
        page.project, "S03", "S01", changed=page._speaker_structure_changed
    ))
    assert page.timeline.speaker_ids() == ["S01"]
    assert [page.cue_model.data(page.cue_model.index(row, 2)) for row in range(2)] == ["主播", "主播"]
    page.save()
    saved = load_project(path)
    assert [cue.speaker_id for cue in saved.cues] == ["S01", "S01"]
    assert [speaker.id for speaker in saved.speakers] == ["S01"]

    page.undo_stack.undo()
    assert page.timeline.speaker_ids() == ["S01", "S03"]
    assert [cue.speaker_id for cue in page.project.cues] == ["S01", "S03"]
    assert [speaker.id for speaker in page.project.speakers] == ["S01", "S03"]
    page.close_page()
    page.deleteLater()
