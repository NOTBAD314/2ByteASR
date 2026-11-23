from copy import deepcopy
from types import SimpleNamespace

import pytest
import subtitle_core

from twobyteasr.glossary.proposal_safety import weak_proposal_reason
from twobyteasr.glossary.source_review_policy import preserve_source_for_delivery
from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
from twobyteasr.timeline.studio_sequence_mapper import open_preview_position


def test_legacy_corrected_cache_cannot_supply_body_or_word_times():
    source = SpeechSegment(407, 0, 3, '狼哥没能量猕猴牙来了', .9, [WordUnit(1, 2, '猕猴牙', .9)])
    cached = deepcopy(source)
    cached.text = cached.final_text = '狼哥没能量能量刃来了'
    cached.words = [WordUnit(1, 2, '能量刃', .9)]
    cached.caption_arbitration['terminology_polish'] = {
        'input_text': source.text, 'accepted_edits': [{'from': '猕猴牙', 'to': '能量刃',
        'accepted_by': 'blind_two_order_second_opinion'}]}
    journal = []
    result = preserve_source_for_delivery([source], [cached], record=lambda name, **event: journal.append(event))
    assert result[0].text == '狼哥没能量猕猴牙来了'
    assert result[0].words[0].text == '猕猴牙'
    receipt = result[0].caption_arbitration['terminology_polish']
    assert receipt['accepted_edits'] == [] and receipt['proposed_edits']
    assert journal[0]['body_edits_applied'] == 0


@pytest.mark.parametrize('text, source, target', [
    ('雪天我们不太好打是吗？', '打是', '打湿'),
    ('耗一下它的能量然后我们切到狮鹫', '能量然', '能量刃'),
    ('主要是偷医用的冲锋也高', '偷医用的冲锋', '充分燃烧'),
    ('冰起的 我们就冰爪呗', '冰起', '奇丽'),
    ('狼哥没能量泥吼牙来了', '泥吼牙', '能量刃'),
])
def test_weak_reference_is_not_a_visible_replacement(text, source, target):
    a = text.index(source)
    assert weak_proposal_reason(text, (a, a+len(source)), target)


def test_homophone_with_valid_span_survives_candidate_filter():
    text = '对面交了三废'
    assert not weak_proposal_reason(text, (4, 6), '三费')


def preview(ms):
    if ms >= 765379:
        return None
    clip_in = 0 if ms < 2400 else 2400
    clip_out = 2400 if ms < 2400 else 765379
    return dict(timeline_in_ms=clip_in, timeline_out_ms=clip_out, clip_id=str(clip_in),
                source_in_ms=858050+clip_in, source_out_ms=858050+clip_out,
                source_ms=858050+ms)


def test_last_ms_stays_inside_clip_and_interior_join_chooses_right():
    logical, actual, target, tail = open_preview_position(765379, 765379, preview)
    assert (logical, actual, target['source_ms']) == (765379, 765378, 1623428)
    assert tail['source_range'] == (860450, 1623429)
    assert tail['fallback_ms'] == 2400
    assert open_preview_position(2400, 765379, preview)[2]['clip_id'] == '2400'
    assert open_preview_position(0, 765379, preview)[2]['source_ms'] == 858050


def test_out_of_clip_frame_falls_back_only_once(monkeypatch):
    from twobyteasr.playback import frame_readiness
    from twobyteasr.studio.studio_readiness import StudioReadiness
    seeks = []
    page = SimpleNamespace(video=SimpleNamespace(_clock_only=False),
        _active_video_preview_clip_id='1', _seek=seeks.append, _studio_trace=lambda *_a, **_k: None)
    state = SimpleNamespace(page=page)
    tail = dict(source_range=(858050, 1623429), clip_id='1', logical_ms=765379,
                fallback_ms=0, fallback_used=False, requested_at=0)
    monkeypatch.setattr(frame_readiness, 'video_frame_witness', lambda _: dict(ready=True, position=1623.433))
    for _ in range(2):
        assert not StudioReadiness._validate_tail_restore(state, tail, True)
    assert seeks == [0.]
    monkeypatch.setattr(frame_readiness, 'video_frame_witness', lambda _: dict(ready=True, position=858.05))
    assert StudioReadiness._validate_tail_restore(state, tail, True)
