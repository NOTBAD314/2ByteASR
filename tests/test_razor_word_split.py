# -*- coding: utf-8 -*-
"""Razor splits follow measured word time (2026-10-10 regression).

The evidence below is the real FireRed row behind the user's screenshot
(“主播投的是对面的没挡眼睛的哥哥”, uneven rate: 对 547ms, 眼 120ms). The AI
proofread removed the filler “呃”, which used to discard the whole row and
fall back to a character-count estimate.
"""
from __future__ import annotations

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.recognition.cue_word_alignment import cue_words
from twobyteasr.timeline.studio_caption_timeline import (
    CLOCK, KEY, ensure_independent_captions, recover_caption_words, ripple_caption_range, shift_caption,
)
from twobyteasr.timeline.studio_commands import split_cue_command
from twobyteasr.projects.studio_project import (
    StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, load_project, save_project,
)
from twobyteasr.timeline.studio_timing import SplitBlocked, describe_split, resolve_split

HEARD = [('呃', 3473, 4060), ('主', 4060, 4260), ('播', 4260, 4660), ('投', 4660, 4940),
         ('的', 4940, 5180), ('是', 5180, 5513), ('对', 5513, 6060), ('面', 6060, 6260),
         ('的', 6260, 6593), ('没', 6593, 6940), ('挡', 6940, 7100), ('眼', 7100, 7220),
         ('睛', 7220, 7300), ('的', 7300, 7420), ('哥', 7420, 7500), ('哥', 7500, 7620)]
TEXT = '主播投的是对面的没挡眼睛的哥哥'
# A second sentence with a real 700ms pause after “好”.
PAUSED = [('好', 9000, 9200), ('吧', 9200, 9350), ('我', 10050, 10150), ('们', 10150, 10260),
          ('走', 10260, 10600)]


def _app():
    return QApplication.instance() or QApplication([])


def _row(text, heard, start, end, *, normalized_from=None):
    arbitration = {'acoustic_words': [dict(text=t, start_ms=a, end_ms=b, model='firered') for t, a, b in heard]}
    if normalized_from:
        arbitration['terminology_normalization'] = [{
            'source': normalized_from, 'result': text, 'alignment_provenance': 'model_context_mapping',
            'requires_acoustic_alignment': True}]
    # The production row also keeps derived, evenly spread `words`.
    step = (end - start) / len(text)
    return {'text': text, 'start_ms': start, 'end_ms': end, 'final_timing_owner': 'FireRed',
            'caption_arbitration': arbitration,
            'words': [dict(text=c, start_ms=round(start + i * step), end_ms=round(start + (i + 1) * step))
                      for i, c in enumerate(text)]}


def make_project(independent=True):
    project = SubtitleProject(
        media=StudioMedia(path='D:/missing.mp4', duration_ms=20000),
        cues=[StudioCue('2', 4067, 7617, TEXT, speaker_id='S01', evidence_refs=['segment:2']),
              StudioCue('3', 9000, 10700, '好吧，我们走', speaker_id='S01', evidence_refs=['segment:3'])],
        speakers=[StudioSpeaker(id='S01', name='主播')],
        asr_evidence={'segment:2': _row(TEXT, HEARD, 3750, 7610, normalized_from='呃' + TEXT),
                      'segment:3': _row('好吧我们走', PAUSED, 9000, 10600)})
    project.validate()
    if independent:
        ensure_independent_captions(project)
    return project


def cue(project, cue_id):
    return next(c for c in project.cues if c.id == cue_id)


@pytest.mark.parametrize('independent', [False, True])
def test_filler_removal_keeps_every_measured_word(independent):
    p = make_project(independent)
    words, reason = cue_words(p, cue(p, '2'))
    assert reason == 'exact_token_text'
    assert ''.join(w.text for w in words) == TEXT
    assert [(w.start_ms, w.end_ms) for w in words] == [(a, b) for _t, a, b in HEARD[1:]]


@pytest.mark.parametrize('cut, left, right, straddled', [
    (5300, '主播投的是', '对面的没挡眼睛的哥哥', '是'),     # inside 是 (5180–5513): it stays left
    (5513, '主播投的是', '对面的没挡眼睛的哥哥', None),     # exactly at 对's onset
    (6448, '主播投的是对面的', '没挡眼睛的哥哥', '的'),     # the screenshot position
    (6593, '主播投的是对面的', '没挡眼睛的哥哥', None),
    (7150, '主播投的是对面的没挡眼', '睛的哥哥', '眼'),
])
def test_text_follows_measured_onsets_not_character_count(cut, left, right, straddled):
    p = make_project()
    target = cue(p, '2')
    result = describe_split(target, cut, project=p)
    assert (result.left_text, result.right_text) == (left, right)
    assert result.split_ms == cut and result.measured
    assert (result.straddled.text if result.straddled else None) == straddled
    # The old estimate (share of duration × character count) differs here.
    estimate = round(len(TEXT) * (cut - target.start_ms) / (target.end_ms - target.start_ms))
    if cut == 6448:
        assert TEXT[:estimate] == '主播投的是对面的没挡' != left


def test_pause_keeps_the_boundary_still_and_edges_are_refused():
    p = make_project()
    target = cue(p, '3')
    inside_pause = {describe_split(target, ms, project=p).left_text for ms in range(9360, 10050, 37)}
    assert inside_pause == {'好吧，'}
    started = describe_split(target, 9100, project=p)  # “好” is sounding: it stays left
    assert (started.left_text, started.straddled.text) == ('好', '好')
    early = copy.copy(target)
    early.start_ms = 8800  # display envelope opens before the first word
    assert describe_split(early, 8900, project=p).reason == 'before_first_word'
    blocked = describe_split(target, 10400, project=p)  # “走” already sounding
    assert isinstance(blocked, SplitBlocked) and blocked.reason == 'after_last_word_onset'
    for ms in range(9200, 10300, 13):
        result = describe_split(target, ms, project=p)
        if not isinstance(result, SplitBlocked):
            assert result.left_text + result.right_text == target.text
            assert result.left_end_ms - result.left_start_ms >= 50
            assert result.right_end_ms - result.right_start_ms >= 50


def test_missing_alignment_is_labelled_not_presented_as_word_level():
    p = make_project()
    p.asr_evidence['segment:2']['caption_arbitration'].pop('acoustic_words')
    receipt = p.studio_state[KEY]['instances']['2']
    receipt.update(words=[], word_alignment='text_changed_or_inside_multi_character_token')
    result = describe_split(cue(p, '2'), 6448, project=p)
    assert not result.measured and result.timing_source == 'estimated_text_allocation'


def test_consecutive_splits_undo_redo_and_reopen_keep_words(tmp_path):
    _app()
    p = make_project()
    evidence = copy.deepcopy(p.asr_evidence)
    stack = QUndoStack()
    first = resolve_split(cue(p, '2'), 6448, project=p)
    stack.push(split_cue_command(p, '2', first.split_ms, first.left_text, first.right_text))
    right = next(c for c in p.cues if c.text == '没挡眼睛的哥哥')
    words, reason = cue_words(p, right)
    assert reason == 'exact_token_text' and [w.start_ms for w in words] == [6593, 6940, 7100, 7220, 7300, 7420, 7500]
    second = resolve_split(right, 7200, project=p)
    assert (second.left_text, second.right_text) == ('没挡眼', '睛的哥哥')
    stack.push(split_cue_command(p, right.id, second.split_ms, second.left_text, second.right_text))
    texts = [c.text for c in sorted(p.cues, key=lambda c: c.start_ms)]
    assert texts == ['主播投的是对面的', '没挡眼', '睛的哥哥', '好吧，我们走']
    stack.undo(); stack.undo()
    assert [c.text for c in p.cues if c.speaker_id == 'S01'][0] == TEXT
    assert [w.start_ms for w in cue_words(p, cue(p, '2'))[0]][:2] == [4060, 4260]
    stack.redo(); stack.redo()
    reopened = load_project(save_project(p, tmp_path / 'split.2byteproj'))
    assert reopened.asr_evidence == evidence
    by_text = {c.text: c for c in reopened.cues}
    assert [w.start_ms for w in cue_words(reopened, by_text['睛的哥哥'])[0]] == [7220, 7300, 7420, 7500]
    assert [w.end_ms for w in cue_words(reopened, by_text['主播投的是对面的'])[0]][-1] == 6593


def test_moves_and_ripples_keep_words_on_the_current_project_clock():
    _app()
    p = make_project()
    target = cue(p, '2')
    shift_caption(p, target, 1000)
    assert p.studio_state[KEY]['instances']['2'][CLOCK] == 1000
    assert describe_split(target, 7448, project=p).left_text == '主播投的是对面的'
    # A ripple deletion of 500ms before the sentence moves it back by 500ms.
    ripple_caption_range(p, 1000, 1500)
    target = cue(p, '2')
    assert (target.start_ms, target.end_ms) == (4567, 8117)
    assert describe_split(target, 6948, project=p).left_text == '主播投的是对面的'
    assert describe_split(target, 7092, project=p).left_text == '主播投的是对面的'
    assert describe_split(target, 7094, project=p).left_text == '主播投的是对面的没'


def test_edited_text_realigns_and_unrelated_edits_are_missing():
    p = make_project()
    target = cue(p, '2')
    # Different-length replacement: the new spelling keeps the whole heard span.
    target.text = '主播投的是对面那个没挡眼睛的哥哥'
    words, reason = cue_words(p, target)
    assert reason == 'derived_term_source_span'
    spans = {target.text[w.char_start:w.char_end]: (w.start_ms, w.end_ms) for w in words}
    assert spans['那个'] == (6260, 6593)  # the heard “的” span, never split inside
    assert describe_split(target, 6300, project=p).left_text == '主播投的是对面那个'
    target.text = '这一句和录音完全无关'
    assert cue_words(p, target) == ((), 'text_changed_or_inside_multi_character_token')
    assert not describe_split(target, 6300, project=p).measured


def test_duplicated_firered_tokens_do_not_discard_the_row():
    p = make_project(False)
    heard = [('然', 71179, 73820), ('然', 73700, 73860), ('后', 73860, 73980), ('还', 73980, 74100),
             ('不', 74100, 74260), ('切', 74260, 74460), ('走', 74460, 74700)]
    p.cues.append(StudioCue('30', 73750, 74800, '然后还不切走', speaker_id='S01', evidence_refs=['segment:30']))
    p.asr_evidence['segment:30'] = _row('然后还不切走', heard, 73750, 74700)
    words, reason = cue_words(p, p.cues[-1])
    assert reason == 'exact_token_text' and words[0].start_ms == 73700


def test_old_empty_receipts_are_recovered_from_saved_evidence_on_the_neighbour_clock():
    p = make_project()
    shift_caption(p, cue(p, '3'), 0)
    receipts = p.studio_state[KEY]['instances']
    # A receipt written by an older build: no words and no recorded clock,
    # after a 300ms ripple shifted both captions.
    for item in p.cues:
        shift_caption(p, item, -300)
    receipts['2'].update(words=[], word_alignment='structural_edit_requires_acoustic_alignment')
    receipts['2'].pop(CLOCK)
    receipts['3'].pop(CLOCK)
    assert cue_words(p, cue(p, '2'))[0] == ()
    assert recover_caption_words(p) == 1
    words, reason = cue_words(p, cue(p, '2'))
    assert reason == 'exact_token_text' and words[0].start_ms == 4060 - 300
    assert receipts['2'][CLOCK] == -300 and receipts['2']['word_recovery']['clock_offset_ms'] == -300


def test_controller_refuses_a_commit_that_differs_from_the_preview(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    p = make_project(False)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *a, **k: None)
    page.open_project(save_project(p, tmp_path / "studio.2byteproj"))
    app.processEvents()
    target = next(c for c in page.project.cues if c.id == '2')
    shown = resolve_split(target, 6448, project=page.project)
    stale = type(shown)(**{**shown.__dict__, 'left_text': '主播投的是对面', 'right_text': '的没挡眼睛的哥哥'})
    page.timeline.razor_committed_preview = ('2', stale)
    page.cue_controller.split_at('2', 6448)
    assert len(page.project.cues) == 2 and page.session.undo_stack.count() == 0
    page.timeline.razor_committed_preview = ('2', shown)
    page.cue_controller.split_at('2', 6448)
    assert sorted(c.text for c in page.project.cues if c.speaker_id == 'S01')[:2] == ['主播投的是对面的', '好吧，我们走']
    assert any(c.text == '没挡眼睛的哥哥' for c in page.project.cues)
    page.close_page()
    page.deleteLater()


def test_trimmed_display_keeps_word_times_for_the_preview():
    """Trimming only moves the display envelope; words keep their clock."""
    from twobyteasr.timeline.studio_caption_timeline import sync_caption_interval_words
    p = make_project()
    target = cue(p, '2')
    previous = (target.start_ms, target.end_ms)
    target.start_ms, target.end_ms = 5000, 7200  # trim both edges
    sync_caption_interval_words(p, target, previous)
    assert p.studio_state[KEY]['instances']['2'][CLOCK] == 0
    result = describe_split(target, 6448, project=p)
    assert (result.left_text, result.right_text) == ('主播投的是对面的', '没挡眼睛的哥哥')
    assert result.left_start_ms == 5000 and result.right_end_ms == 7200
