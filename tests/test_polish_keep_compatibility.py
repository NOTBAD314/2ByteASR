"""Regressions for the reported keep enum, with synthetic responses.

The user report contains the validation error, not the original response.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
import subtitle_core  # initialize the legacy facade

from tests.test_stage9_cache_and_budget import context  # noqa: F401
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules import polishing


def segment():
    return SpeechSegment(1, 0., 2., 'This is a test', .85, [], speaker='API_S00')


def response():
    return {'checked_ids': [1], 'cues': [{'id': 1, 'edits': [
        {'from': 'test', 'to': 'test', 'start': 10, 'end': 14, 'type': 'keep'}]}]}


def test_verified_legacy_noop_becomes_empty_edits_with_receipt(monkeypatch):
    events = []
    monkeypatch.setattr(polishing, 'record_run_event', lambda event, **data: events.append((event, data)))
    value = polishing._validate_polish_response(response(), [segment()], 23)
    assert value['cues'][0]['edits'] == []
    assert events == [('polishing_legacy_noop_normalized', {
        'batch_index': 23, 'cue_counts': [{'cue_id': 1, 'count': 1}],
        'protocol': polishing.POLISH_PROMPT_VERSION})]
    assert 'keep' not in polishing.POLISH_SCHEMA['properties']['cues']['items']['properties']['edits']['items']['properties']['type']['enum']


@pytest.mark.parametrize('structured', [False, True])
def test_verified_noop_passes_the_whole_polishing_path(context, monkeypatch, structured):
    provider = (SimpleNamespace(structured_complete=lambda *a, **k: response()) if structured
                else SimpleNamespace(complete=lambda *a, **k: json.dumps(response())))
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: provider)
    result = polishing.call_correction_api([segment()], [], '', '', 'fixture', '', [], [], [],
                                          batch_index=23, batch_total=29)
    assert result[1] == 'This is a test'
    assert result.succeeded == {1} and result.failures == {}


@pytest.mark.parametrize('change', ['different_text', 'wrong_span', 'missing_span', 'unknown_id',
                                    'duplicate_id', 'overlap', 'speaker', 'edit_metadata'])
def test_ambiguous_or_unauthorized_keep_is_not_normalized(change):
    value = response()
    row, edit = value['cues'][0], value['cues'][0]['edits'][0]
    if change == 'different_text': edit['to'] = 'best'
    if change == 'wrong_span': edit['start'] = 9
    if change == 'missing_span': edit.pop('start')
    if change == 'unknown_id': row['id'] = 2
    if change == 'duplicate_id': value['cues'].append(deepcopy(row))
    if change == 'overlap': row['edits'].append({'from':'test', 'to':'best', 'start':10, 'end':14, 'type':'asr_correction'})
    if change == 'speaker': row['speaker'] = 'API_S01'
    if change == 'edit_metadata': edit['speaker_id'] = 'API_S01'
    from twobyteasr.providers.ai_providers import AIProviderError
    with pytest.raises(AIProviderError) as exc:
        polishing._validate_polish_response(value, [segment()], 23)
    assert exc.value.category == 'structured_schema_error'


@pytest.mark.parametrize('structured', [False, True])
def test_schema_failure_is_not_reported_as_network_error(context, monkeypatch, structured):
    invalid = response()
    invalid['cues'][0]['edits'][0]['to'] = 'best'
    provider = (SimpleNamespace(structured_complete=lambda *a, **k: invalid) if structured
                else SimpleNamespace(complete=lambda *a, **k: json.dumps(invalid)))
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: provider)
    monkeypatch.setattr(polishing, 'API_RETRIES', 1)
    result = polishing.call_correction_api([segment()], [], '', '', 'fixture', '', [], [], [],
                                          batch_index=23, batch_total=29)
    assert result[1] == 'This is a test'
    assert result.failures == {1: 'structured_schema_error'}


@pytest.mark.parametrize('value,category', [
    ({'checked_ids': [], 'cues': []}, 'coverage_mismatch'),
    ({'checked_ids': [1], 'cues': [{'id': 2, 'edits': []}]}, 'semantic_validation'),
    ({'checked_ids': [1], 'cues': [{'id': 1, 'edits': []}, {'id': 1, 'edits': []}]}, 'semantic_validation'),
])
def test_bad_ids_are_not_mislabeled_as_network_or_schema(context, monkeypatch, value, category):
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(structured_complete=lambda *a, **k: value))
    monkeypatch.setattr(polishing, 'API_RETRIES', 1)
    result = polishing.call_correction_api([segment()], [], '', '', 'fixture', '', [], [], [])
    assert result[1] == 'This is a test'
    assert result.failures == {1: category}


@pytest.mark.parametrize('structured', [False, True])
def test_one_bad_cue_does_not_discard_valid_neighbor(context, monkeypatch, structured):
    second = SpeechSegment(2, 2., 4., 'A second line', .85, [], speaker='API_S00')
    value = {'checked_ids': [1, 2], 'cues': [
        {'id': 1, 'edits': []},
        {'id': 2, 'edits': [{'from': 'second', 'to': 'changed', 'start': 2, 'end': 8, 'type': 'keep'}]},
    ]}
    provider = (SimpleNamespace(structured_complete=lambda *a, **k: value) if structured
                else SimpleNamespace(complete=lambda *a, **k: json.dumps(value)))
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: provider)
    result = polishing.call_correction_api([segment(), second], [], '', '', 'fixture', '', [], [], [],
                                          batch_index=23, batch_total=29)
    assert result.succeeded == {1}
    assert result.failures == {2: 'structured_schema_error'}
    assert result[1] == 'This is a test' and result[2] == 'A second line'
    assert result.details[2]['response_state'] == 'fallback'


@pytest.mark.parametrize('edits', [
    [{'from': 'second', 'to': 'changed', 'start': 2, 'end': 99, 'type': 'asr_correction'}],
    [{'from': 'second', 'to': 'changed', 'start': 2, 'end': 8, 'type': 'asr_correction'},
     {'from': 'second', 'to': 'other', 'start': 2, 'end': 8, 'type': 'asr_correction'}],
])
def test_bad_edit_span_falls_back_only_for_that_cue(context, monkeypatch, edits):
    second = SpeechSegment(2, 2., 4., 'A second line', .85, [], speaker='API_S00')
    value = {'checked_ids': [1, 2], 'cues': [{'id': 1, 'edits': []}, {'id': 2, 'edits': edits}]}
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(structured_complete=lambda *a, **k: value))
    result = polishing.call_correction_api([segment(), second], [], '', '', 'fixture', '', [], [], [])
    assert result.succeeded == {1} and result.failures == {2: 'semantic_validation'}
    assert result[2] == 'A second line'


def test_partial_result_is_not_cached_as_success(context):
    from pathlib import Path
    from twobyteasr.recognition.cache import run_cached_api_batch
    _core, _ctx, cache = context
    calls = []
    def run():
        calls.append(1)
        return polishing.PolishBatchResult({1: 'valid', 2: 'original'}, succeeded={1},
                                           failures={2: 'semantic_validation'})
    for _ in range(2):
        result = run_cached_api_batch('polished', cache, {'ids': [1, 2]}, run,
                                      encoder=polishing._encode_polish_batch,
                                      decoder=polishing._decode_polish_batch)
        assert result.failures == {2: 'semantic_validation'}
    assert len(calls) == 2
    assert not list(Path(cache['cache_dir']).glob('api_batches/polished/*.json'))


def test_unknown_id_prevents_partial_salvage(context, monkeypatch):
    second = SpeechSegment(2, 2., 4., 'A second line', .85, [], speaker='API_S00')
    value = {'checked_ids': [1, 2], 'cues': [
        {'id': 3, 'edits': []},
        {'id': 2, 'edits': [{'from': 'second', 'to': 'changed', 'start': 2, 'end': 8, 'type': 'keep'}]},
    ]}
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(structured_complete=lambda *a, **k: value))
    monkeypatch.setattr(polishing, 'API_RETRIES', 1)
    result = polishing.call_correction_api([segment(), second], [], '', '', 'fixture', '', [], [], [])
    assert not result.succeeded and result.failures == {1: 'semantic_validation', 2: 'semantic_validation'}
