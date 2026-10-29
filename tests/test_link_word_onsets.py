"""YouTube automatic captions carry each word's start; those become the
caption's word timing (2026-10-26, user: "自动字幕都是词级时间戳 … 英文按词，
别按字母"). Without word times, an estimated English cut lands between words."""
import json

from twobyteasr.media.link_subtitles import parse_subtitles
from twobyteasr.media.media_ingest import MediaIngestResult
from twobyteasr.projects.link_import import LinkImportCommand
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.subtitle_consistency import validate_project
from twobyteasr.recognition.cue_word_alignment import DOWNLOADED_WORD_ONSETS, cue_words
from twobyteasr.timeline.link_timing import onset_words
from twobyteasr.timeline.studio_timing import ESTIMATED_SPLIT, SplitPreview, describe_split, word_safe_position

AUTO_JSON3 = {"events": [
    {"tStartMs": 1000, "dDurationMs": 4000, "wWinId": 1, "segs": [
        {"utf8": "So,"}, {"utf8": " here's", "tOffsetMs": 400}, {"utf8": " the", "tOffsetMs": 700},
        {"utf8": " first", "tOffsetMs": 900}, {"utf8": " guy.", "tOffsetMs": 1300}]},
    {"tStartMs": 5000, "dDurationMs": 1500, "wWinId": 1, "segs": [{"utf8": "Manual line without word times"}]},
]}


def parsed_rows():
    parsed = parse_subtitles(json.dumps(AUTO_JSON3).encode("utf-8"))
    return [dict(start_ms=c.start_ms, end_ms=c.end_ms, text=c.text, events=c.events, anchors=c.anchors,
                 precision=c.precision) for c in parsed.captions]


def bundle():
    track = dict(track_id="primary", platform="Youtube", video_id="BaW_jenozKc", language="en", source="automatic")
    return dict(manifest_path="/download/download.2byte-download.json", media_path="/video.mp4",
        manifest=dict(task_id="task-words", platform="Youtube", video_id="BaW_jenozKc", source_url="",
                      primary_track_id="primary", translation_track_id="", subtitles=[dict(track=track)]),
        captions={"primary": dict(parser_version="2", captions=parsed_rows())})


def media():
    return MediaIngestResult(generation=0, project_token="", source_path="/video.mp4",
                             duration_ms=8000, has_video=True, has_audio=True, width=320, height=240)


def imported(position_ms=10000):
    project = SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    command = LinkImportCommand(project, bundle(), media(), position_ms=position_ms)
    command.redo()
    return project, command


def test_word_onsets_cover_the_caption_and_end_at_the_next_word():
    row = parsed_rows()[0]
    words = onset_words(row["text"], row["anchors"], row["start_ms"], row["end_ms"], "ref")
    assert [(w["text"], w["start_ms"], w["end_ms"]) for w in words] == [
        ("So,", 1000, 1400), ("here's", 1400, 1700), ("the", 1700, 1900), ("first", 1900, 2300), ("guy.", 2300, 5000)]
    assert all(row["text"][w["char_start"]:w["char_end"]] == w["text"] for w in words)


def test_no_word_timing_unless_every_word_has_an_onset():
    text = "two words"
    assert onset_words(text, [dict(char_start=0, char_end=4, start_ms=0)], 0, 1000, "r") == []
    assert onset_words(text, [], 0, 1000, "r") == []
    # Onsets running backwards are not a word stream.
    backwards = [dict(char_start=0, char_end=4, start_ms=500), dict(char_start=4, char_end=9, start_ms=100)]
    assert onset_words(text, backwards, 0, 1000, "r") == []
    # A punctuation-only segment is no word; two segments at one moment are one word.
    rows = [dict(char_start=0, char_end=3, start_ms=0), dict(char_start=3, char_end=4, start_ms=200),
            dict(char_start=4, char_end=9, start_ms=200)]
    words = onset_words("two words", rows, 0, 1000, "r")
    assert [(w["text"], w["start_ms"], w["end_ms"]) for w in words] == [("two", 0, 200), ("words", 200, 1000)]


def test_import_gives_automatic_captions_word_timing_and_razor_snaps_to_words():
    project, command = imported()
    auto, manual = project.cues
    words, reason = cue_words(project, auto)
    assert reason == DOWNLOADED_WORD_ONSETS
    assert [(w.text, w.start_ms) for w in words] == [
        ("So,", 11000), ("here's", 11400), ("the", 11700), ("first", 11900), ("guy.", 12300)]
    assert cue_words(project, manual)[0] == ()      # one segment, no word times: sentence timing
    assert command.result["timing_counts"]["word_onsets"] == 1
    assert validate_project(project).ok
    # A razor through "first" moves to the boundary after it, not into its letters.
    cut = describe_split(auto, 12000, project=project)
    assert isinstance(cut, SplitPreview) and cut.measured
    assert (cut.left_text, cut.right_text, cut.split_ms) == ("So, here's the first", "guy.", 12300)


def test_razor_split_keeps_the_downloaded_basis():
    from twobyteasr.timeline.studio_caption_timeline import caption_replacement_receipts
    project, _command = imported()
    auto = project.cues[0]
    cut = describe_split(auto, 11800, project=project)
    left = StudioCue(id=auto.id + "~a", start_ms=auto.start_ms, end_ms=cut.split_ms, text=cut.left_text,
                     speaker_id=auto.speaker_id, evidence_refs=list(auto.evidence_refs))
    right = StudioCue(id=auto.id + "~b", start_ms=cut.split_ms, end_ms=auto.end_ms, text=cut.right_text,
                      speaker_id=auto.speaker_id, evidence_refs=list(auto.evidence_refs))
    _before, after = caption_replacement_receipts(project, [auto], [left, right])
    assert after[left.id]["word_alignment"] == after[right.id]["word_alignment"] == DOWNLOADED_WORD_ONSETS
    assert [w["text"] for w in after[right.id]["words"]] == ["first", "guy."]   # the cut left "the" whole


def test_edited_text_keeps_the_downloaded_basis():
    project, _command = imported()
    auto = project.cues[0]
    auto.text = "So, here's the first guy!"
    words, reason = cue_words(project, auto)
    assert reason == DOWNLOADED_WORD_ONSETS and words[-1].text.startswith("guy")


def test_words_follow_a_moved_clip_and_clear_when_it_is_cut():
    from twobyteasr.timeline.studio_clip_edit import clip_edit_command
    project, _command = imported(position_ms=0)
    lane = project.video_tracks[0]
    clip = lane.clips[0]
    move = clip_edit_command(project, lane.id, "move", clip_id=clip.id, start=10000)
    move.redo()
    words, reason = cue_words(project, project.cues[0])
    assert reason == DOWNLOADED_WORD_ONSETS and [w.start_ms for w in words] == [11000, 11400, 11700, 11900, 12300]
    move.undo()
    assert [w.start_ms for w in cue_words(project, project.cues[0])[0]] == [1000, 1400, 1700, 1900, 2300]
    # Trimming the clip into the caption: no stale words, sentence timing and a review.
    trim = clip_edit_command(project, lane.id, "trim", clip_id=clip.id, start=2000, end=8000)
    trim.redo()
    cue = project.cues[0]
    assert cue_words(project, cue)[0] == ()
    receipt = project.studio_state["caption_timeline"]["instances"][cue.id]
    assert receipt["word_alignment"] == "downloaded_sentence_or_segment_start" and receipt["words"] == []
    trim.undo()
    assert cue_words(project, project.cues[0])[1] == DOWNLOADED_WORD_ONSETS


def test_estimated_english_cut_lands_between_words():
    text = "So, here's the first guy. He is not"
    assert word_safe_position(text, 6) == 3             # inside "here's" → the space after "So,"
    assert word_safe_position(text, 12) == 10           # inside "the" → before it
    assert word_safe_position(text, 20) == 20           # already at a boundary
    assert word_safe_position("这是中文的句子", 3) == 3   # Chinese characters are their own units
    assert word_safe_position("Unbreakable", 4) == 4      # one word: nowhere better to go
    cue = StudioCue(id="c", start_ms=0, end_ms=3500, text=text)
    for time_ms in range(200, 3400, 150):
        cut = describe_split(cue, time_ms)
        assert cut.timing_source == ESTIMATED_SPLIT
        assert cut.left_text + " " + cut.right_text == text, (time_ms, cut.left_text, cut.right_text)


def test_a_one_word_automatic_row_is_that_word():
    from twobyteasr.timeline.link_timing import single_word
    assert [(w["text"], w["start_ms"], w["end_ms"]) for w in single_word("wearing", 24480, 25400, "r")] == [
        ("wearing", 24480, 25400)]
    assert single_word("two words", 0, 100, "r") == []
    assert single_word("大家好今天我们来玩", 0, 100, "r") == []     # never a whole Chinese line
    data = bundle()
    data["captions"]["primary"]["captions"].append(dict(start_ms=7000, end_ms=7600, text="wearing", events=[],
                                                         anchors=[], precision="sentence"))
    project = SubtitleProject(media=StudioMedia(path=""))
    project.validate()
    LinkImportCommand(project, data, media()).redo()
    cue = next(c for c in project.cues if c.text == "wearing")
    words, reason = cue_words(project, cue)
    assert reason == DOWNLOADED_WORD_ONSETS and [(w.start_ms, w.end_ms) for w in words] == [(7000, 7600)]
