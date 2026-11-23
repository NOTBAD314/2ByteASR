from types import SimpleNamespace

import pytest
import subtitle_core

from twobyteasr.glossary.terminology_support import recall_gaps, suspicious_spans, unresolved_recall_gaps
from twobyteasr.recognition.edited_text_alignment import _validate_tokens
from twobyteasr.subtitle_rules.ai_boundary_policy import break_candidates, inspect, select_model_boundary_domain
from twobyteasr.subtitle_rules.grouping_quality import quality_for_segments
from twobyteasr.subtitle_rules.grouping_quality_request import _record_window
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.text_rules import content_exact


@pytest.mark.parametrize('name, part', [('沙石阵', '沙石'), ('卡瓦重', '卡瓦'),
                                       ('乌拉塔', '乌拉'), ('鸭吉吉', '吉吉')])
def test_confirmed_entity_only_covers_its_own_occurrence(monkeypatch, name, part):
    import jieba.posseg
    text = name + '和' + part + '获得1200元'
    start = name.index(part)
    tokens = [(name[:start], 'x'), (part, 'nr'), (name[start+len(part):], 'x'),
              ('和', 'x'), (part, 'nr'), ('获得1200元', 'x')]
    monkeypatch.setattr(jieba.posseg, 'cut',
                       lambda *args, **kwargs: [SimpleNamespace(word=word, flag=flag)
                                                for word, flag in tokens if word])
    segment = SimpleNamespace(segment_id=860, text=text)
    candidate = dict(canonical=name, status='confirmed', matches=[dict(
        cue_id=860, asr_source='text', method='exact', start=0, end=len(name))])
    snapshot = SimpleNamespace(libraries=[SimpleNamespace(terms=())])
    with language_scope('zh'):
        gaps = recall_gaps([segment], [candidate], snapshot)
    assert [(gap['surface'], gap['spans']) for gap in gaps] == [
        (part, [[len(name)+1, len(name)+1+len(part)]])]
    spans = suspicious_spans([segment], [], gaps)
    assert [row['start'] for row in spans] == [len(name)+1]
    kept = dict(suspect_id=spans[0]['suspect_id'], disposition='keep',
                validation_state='validated_against_input_and_local_edits')
    assert unresolved_recall_gaps(dict(input_text=text, recall_gaps=gaps, suspect_results=[kept]), 860, text) == []
    assert unresolved_recall_gaps(dict(input_text=text, recall_gaps=gaps), 860, text) == gaps


def test_novel_recipient_cut_is_not_offered_or_adoptable():
    segment = subtitle_core.SpeechSegment(860, 0, 4, '对面上卡瓦重给我们那个虫群过境的机会了', .8, [])
    with language_scope('zh'):
        quality = quality_for_segments([segment])
        select_model_boundary_domain(quality)
        cut = segment.text.index('给') + 1
        assert cut not in break_candidates(quality)
        issues = inspect(quality, [cut, quality.total])
    assert any(issue.get('reason') == 'boundary_not_allowed' and issue['start'] == cut for issue in issues)


def test_unchanged_retry_is_not_counted_as_improved():
    segment = subtitle_core.SpeechSegment(872, 0, 3, '现在已经来到 1200 元的奖金了', .8, [])
    with language_scope('zh'):
        quality = quality_for_segments([segment])
        select_model_boundary_domain(quality)
        positions = [4, quality.total]
        output, ledger = [], []
        _record_window(lambda name, **kw: output.append(kw), SimpleNamespace(record_outcome=ledger.append),
            28, '28.quality-2', (0, quality.total), {'current_boundaries': positions,
            'current_answer': quality.index.pieces(positions)}, positions, positions, quality,
            'improved', dispatched=True, round_number=2, reason='unchanged_with_violations',
            candidate=[6, quality.total])
    assert ledger == ['unchanged_with_violations']
    assert not output[0]['accepted'] and not output[0]['improved']


def test_verified_padding_can_supply_a_measured_start_without_stealing_neighbor_time():
    segment = subtitle_core.SpeechSegment(222, 1.1, 2, '10000元', .8, [])
    job = dict(window_start_ms=1000, window_end_ms=2100)
    worker = dict(input_processing={'absolute_original_pcm_samples': [16000, 33600]})
    tokens = [dict(text='10000', start=1.08, end=1.4, start_basis='model', end_basis='model'),
              dict(text='元', start=1.4, end=1.5, start_basis='model', end_basis='model')]
    assert _validate_tokens(segment, [segment], tokens, job, worker, content_exact) is None
    neighbor = subtitle_core.SpeechSegment(221, 0, 1.1, '上一句', .8, [])
    assert _validate_tokens(segment, [neighbor, segment], tokens, job, worker, content_exact) == 'extension_conflicts_with_neighbor'
    tokens[0]['start_basis'] = 'window_edge'
    assert _validate_tokens(segment, [segment], tokens, job, worker, content_exact) == 'unmeasured_endpoint'


def test_presentation_reads_published_qc_without_running_segmentation(monkeypatch):
    from twobyteasr.subtitle_rules import current_issues
    from twobyteasr.subtitle_rules.studio_review import cached_review_risks

    view = current_issues.CurrentIssueView({}, {}, (), {'455': 'suggested'})
    project = SimpleNamespace(_qc_result=object(), _current_issue_view=(None, None, view),
                              _current_issue_dirty_ids={'455'})
    monkeypatch.setattr(current_issues, 'current_issue_view',
                        lambda *_: pytest.fail('presentation must not recalculate QC'))
    assert cached_review_risks(project, refresh=False)['455']['level'] == 'suggested'


def test_terminal_empty_worker_error_is_not_cached_as_success(tmp_path):
    from twobyteasr.recognition.speech_coverage import transcribe_recovery_window

    calls = []

    def handle(*args):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError('ASR_RESPONSE_HAVE_NO_WORDS')
        return []

    events = []
    legacy = SimpleNamespace(transcribe_primary_reference=handle,
        build_qwen_asr_context=lambda _: '', record_run_event=lambda key, **kwargs: events.append((key, kwargs)))
    owner = SimpleNamespace(requested_language='zh', media_identity={}, asr_settings_snapshot={'configured': True},
                            asr_endpoint_snapshot={})
    import numpy as np
    pcm = np.zeros(16000, dtype=np.float32)
    def window():
        return transcribe_recovery_window('api', '', pcm, 0, 1, {'cache_dir': tmp_path}, owner, legacy)

    assert window().failure['category'] == 'provider_empty_response_failure'
    assert not window().cache_hit
    assert window().cache_hit
    assert [fields['outcome'] for event, fields in events if event == 'speech_recovery_window'] == [
        'failed', 'empty_success', 'empty_success']
