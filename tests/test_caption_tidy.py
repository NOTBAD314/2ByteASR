"""Tidying captions of a project imported before downloads were tidied (2026-10-26)."""
import json

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.media.link_subtitles import parse_subtitles
from twobyteasr.media.media_ingest import MediaIngestResult
from twobyteasr.projects.link_import import LinkImportCommand
from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
from twobyteasr.projects.subtitle_consistency import validate_project
from twobyteasr.recognition.cue_word_alignment import DOWNLOADED_WORD_ONSETS, cue_words
from twobyteasr.timeline.caption_tidy import apply_caption_tidy, plan_caption_tidy

from tests.test_link_tidy import AUTO


def imported_as_before():
    """YouTube's display rows imported as they were (no tidy), like older projects."""
    parsed = parse_subtitles(json.dumps(AUTO).encode("utf-8"), source="automatic")
    rows = [dict(start_ms=c.start_ms, end_ms=c.end_ms, text=c.text, events=c.events, anchors=c.anchors,
                 precision=c.precision) for c in parsed.captions]
    track = dict(track_id="primary", platform="Youtube", video_id="BaW_jenozKc", language="en", source="automatic")
    bundle = dict(manifest_path="/d/download.2byte-download.json", media_path="/video.mp4",
                  manifest=dict(task_id="old", platform="Youtube", video_id="BaW_jenozKc", source_url="",
                                primary_track_id="primary", translation_track_id="", subtitles=[dict(track=track)]),
                  captions={"primary": dict(parser_version="2", captions=rows)})
    project = SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    LinkImportCommand(project, bundle, MediaIngestResult(generation=0, project_token="", source_path="/video.mp4",
                      duration_ms=20000, has_video=True, has_audio=True, width=320, height=240)).redo()
    return project


def test_old_download_captions_are_tidied_in_one_undo_step():
    QApplication.instance() or QApplication([])
    project = imported_as_before()
    before = [c.text for c in project.cues]
    assert "[Music]" in before and any(">>" in text for text in before)
    plan = plan_caption_tidy(project, [c.id for c in project.cues])
    assert plan.regrouped and plan.labels_removed >= 2
    # Cut where old and new captions end on the same word: one re-break (with
    # the [Music] row before it), one label, and the unchanged "wearing" left out.
    assert [([c.text for c in s.removed], len(s.inserted)) for s in plan.splices] == [
        (["[Music]", "Breaking people's faces in MMA has been", "America's new favorite pastime and",
          "that's what we do."], 2), ([">> Nice shot."], 1)]
    stack = QUndoStack()
    assert apply_caption_tidy(stack, project, plan) > 0 and stack.count() == 1
    texts = [c.text for c in project.cues]
    assert texts == ["Breaking people's faces in MMA has been America's new favorite pastime",
                     "and that's what we do.", "Nice shot.", "wearing"]
    first = project.cues[0]
    words, reason = cue_words(project, first)
    assert reason == DOWNLOADED_WORD_ONSETS and [w.text for w in words][:3] == ["Breaking", "people's", "faces"]
    assert words[0].start_ms == 2000 and validate_project(project).ok
    stack.undo()
    assert [c.text for c in project.cues] == before


def test_labels_only_keeps_each_caption_and_its_words():
    QApplication.instance() or QApplication([])
    project = imported_as_before()
    rows = len(project.cues)
    plan = plan_caption_tidy(project, [c.id for c in project.cues], regroup=False)
    stack = QUndoStack()
    apply_caption_tidy(stack, project, plan)
    texts = [c.text for c in project.cues]
    assert len(texts) == rows - 1 and all("[" not in t and ">>" not in t for t in texts)
    nice = next(c for c in project.cues if c.text == "Nice shot.")
    assert cue_words(project, nice)[1] == DOWNLOADED_WORD_ONSETS
