"""Actual Home cue29 optional offset failure must not discard a valid batch."""
import copy
import json
from types import SimpleNamespace

import pytest

import subtitle_core  # noqa: F401 - initialize the existing compatibility facade first
from tests.test_stage9_cache_and_budget import context
from twobyteasr.subtitle_rules import polishing
from twobyteasr.recognition.transcript_data import SpeechSegment


def row(identity, text='普通字幕'):
    return SpeechSegment(identity, identity, identity+1, text, .9, [],
        primary_source='moss-dialogue', moss_text=text, firered_text=text, qwen_asr_text=text)


def response(rows, optional):
    return {'checked_ids': [r.segment_id for r in rows], 'cues': [], 'new_suspects': optional}


def install(monkeypatch, payload, *, structured=False):
    calls = []
    def complete(messages, **kwargs):
        calls.append(messages)
        return json.dumps(payload, ensure_ascii=False)
    def structured_complete(messages, schema, **kwargs):
        from jsonschema import validate
        validate(payload, schema)
        calls.append(messages)
        return copy.deepcopy(payload)
    provider = SimpleNamespace(**({'structured_complete': structured_complete} if structured else {'complete': complete}))
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **kw: provider)
    return calls


def call(rows):
    return polishing.call_correction_api(rows, [], '', '', '', '', [], [], [])


@pytest.mark.parametrize('structured', [False, True])
def test_actual_home_wrong_optional_span_keeps_all50_and_valid_neighbor_edits(context, monkeypatch, structured):
    rows = [row(i) for i in range(1, 51)]
    rows[22] = row(23, '叶林直接笼罩点内')
    rows[28] = row(29, '反手还能再推叶林')
    rows[27] = row(28, '这个公鸡很强')
    rows[27].firered_text = rows[27].qwen_asr_text = '这个攻击很强'
    good = {'id': 23, 'start': 0, 'end': 2, 'surface': '叶林', 'evidence': '需确认专名'}
    bad = {'id': 29, 'start': 7, 'end': 9, 'surface': '叶林', 'evidence': '实际 Home 首响应原始条目'}
    payload = response(rows, [good, bad])
    payload['cues'] = [{'id': 28, 'edits': [{'from': '公鸡', 'to': '攻击', 'start': 2, 'end': 4, 'basis': 'F+Q'}]}]
    calls = install(monkeypatch, payload, structured=structured)
    result = call(rows)
    assert len(calls) == 1 and result.succeeded == set(range(1, 51)) and not result.failures
    assert result[29] == '反手还能再推叶林' and result[28] == '这个攻击很强'
    receipt = result.details[29]
    assert receipt['response_state'] == 'validated_with_pending_optional_metadata'
    assert receipt['quality_state'] == 'pending_suspect_adjudication'
    invalid = receipt['new_suspects'][0]
    assert invalid['raw_model_row'] == bad and invalid['validation_state'] == 'invalid'
    assert invalid['validation_errors'] == ['span_out_of_bounds']
    assert result.details[23]['new_suspects'][0]['validation_state'] == 'validated_original_position'
    assert result.details[23]['quality_state'] == 'pending_suspect_adjudication'
    assert result.details[1]['quality_state'] == 'checked_no_pending_identifier_suggestions'


def test_correct_actual_home_span_is_kept_as_pending_discovery(context, monkeypatch):
    rows = [row(29, '反手还能再推叶林')]
    good = {'id': 29, 'start': 6, 'end': 8, 'surface': '叶林', 'evidence': '需确认专名'}
    calls = install(monkeypatch, response(rows, [good]))
    result = call(rows)
    discovery = result.details[29]['new_suspects'][0]
    assert len(calls) == 1 and result.succeeded == {29}
    assert discovery['raw_model_row'] == good and discovery['validation_errors'] == []
    assert discovery['validation_state'] == 'validated_original_position'
    assert result.details[29]['quality_state'] == 'pending_suspect_adjudication'


@pytest.mark.parametrize('entry, errors, assigned', [
    ({'id': 999, 'start': 0, 'end': 2, 'surface': '叶林', 'evidence': '待审'}, ['unknown_editable_cue_id'], False),
    ({'id': '29', 'start': 0, 'end': 2, 'surface': '叶林', 'evidence': '待审'}, ['invalid_cue_id_type'], False),
    ({'id': 29, 'start': '6', 'end': 8, 'surface': '叶林', 'evidence': '待审'}, ['invalid_span_type'], True),
    ({'id': 29, 'start': 6, 'end': 8, 'surface': '夜灵', 'evidence': '待审'}, ['surface_mismatch'], True),
    ({'id': 29, 'start': -1, 'end': 8, 'surface': '叶林', 'evidence': '待审'}, ['span_out_of_bounds'], True),
    ({'id': 29, 'start': 6, 'end': 8, 'surface': ['叶林'], 'evidence': '待审'}, ['invalid_surface_type'], True),
    ({'id': 29, 'start': 6, 'end': 8, 'surface': '叶林', 'evidence': None}, ['invalid_evidence_type'], True),
    (None, ['new_suspect_not_object', 'invalid_cue_id_type', 'invalid_span_type', 'invalid_surface_type', 'invalid_evidence_type'], False),
])
def test_malformed_optional_row_is_quarantined_without_cloud_repair(context, monkeypatch, entry, errors, assigned):
    rows = [row(29, '反手还能再推叶林')]
    calls = install(monkeypatch, response(rows, [entry]))
    result = call(rows)
    assert len(calls) == 1 and result.succeeded == {29} and not result.failures
    assert result[29] == rows[0].text
    entries = result.details[29]['new_suspects'] if assigned else result.unassigned_new_suspects
    assert len(entries) == 1 and entries[0]['raw_model_row'] == entry
    assert entries[0]['validation_errors'] == errors and entries[0]['validation_state'] == 'invalid'
    restored = polishing._decode_polish_batch(polishing._encode_polish_batch(result))
    assert restored.unassigned_new_suspects == result.unassigned_new_suspects
    if assigned:
        assert result.details[29]['quality_state'] == 'pending_suspect_adjudication'
    else:
        assert result.details[29]['new_suspects'] == []


@pytest.mark.parametrize('bad_container', [None, 'malformed', {'id': 29, 'start': 6, 'end': 8, 'surface': '叶林', 'evidence': '待审'}])
def test_invalid_optional_container_preserves_global_metadata(context, monkeypatch, bad_container):
    rows = [row(29, '反手还能再推叶林')]
    calls = install(monkeypatch, response(rows, bad_container), structured=True)
    result = call(rows)
    assert len(calls) == 1 and result.succeeded == {29} and not result.failures
    assert result.unassigned_new_suspects[0]['raw_model_row'] == bad_container
    assert 'new_suspects_not_array' in result.unassigned_new_suspects[0]['validation_errors']
    assert result.details[29]['new_suspects'] == []


def test_full_polish_and_cached_result_keep_unassigned_batch_review(context, monkeypatch):
    _core, owner, cache = context
    rows = [row(29, '反手还能再推叶林')]
    unknown = {'id': 999, 'start': 6, 'end': 8, 'surface': '叶林', 'evidence': '不能归属'}
    calls = install(monkeypatch, response(rows, [unknown]))
    monkeypatch.setattr(polishing, 'load_glossary', lambda: [])
    monkeypatch.setattr(polishing, 'load_verified_game_terms', lambda: [])
    for _ in range(2):
        owner.review_items.clear()
        result = polishing.polish_subtitles(copy.deepcopy(rows), '真实 Home 错跨度回归', cache)
        assert result[0].text == rows[0].text
        assert owner.polishing_summary['success_cues'] == 1
        assert owner.polishing_summary['fallback_cues'] == 0
        metadata = owner.polishing_summary['term_context']
        assert metadata['new_suspect_review_status'] == 'pending_review'
        assert metadata['unassigned_new_suspect_rows'] == 1
        assert metadata['unassigned_new_suspects'][0]['rows'][0]['raw_model_row'] == unknown
        assert any(item.get('review_scope') == 'unassigned_batch_metadata' for item in owner.review_items)
    assert len(calls) == 1


def test_v13_cache_identity_and_native_schema_preserve_strict_mandatory_fields(context):
    from dataclasses import replace
    from jsonschema import validate, ValidationError
    from twobyteasr.providers.asr_provider_snapshot import POLISH_PROMPT_VERSION
    from twobyteasr.providers.cli_schema import request_schema
    _core, owner, _cache = context
    assert POLISH_PROMPT_VERSION == 'correction-edits-v14-pronoun-gender'
    old_versions = dict(owner.provider_snapshot.prompt_versions)
    old_versions['polished'] = 'correction-edits-v13-optional-suspect-local-quarantine'
    old = replace(owner.provider_snapshot, prompt_versions=tuple(old_versions.items()))
    assert old.fingerprint != owner.provider_snapshot.fingerprint
    native, preflight = request_schema(polishing.POLISH_SCHEMA)
    assert preflight['preflight'] == 'passed'
    validate({'checked_ids': [29], 'cues': [], 'new_suspects': 'malformed optional metadata'}, native)
    with pytest.raises(ValidationError):
        validate({'checked_ids': [29], 'cues': [{'id': 29, 'edits': [{'to': 'missing from'}]}]}, native)


@pytest.mark.parametrize('optional_row', [
    {'id': 999, 'start': 6, 'end': 8, 'surface': '叶林', 'evidence': '不能归属'}, None])
def test_studio_review_receipt_keeps_unassigned_rows_and_zero_edits_pending(context, monkeypatch, optional_row):
    from tests.test_stage9_provider_snapshot import config
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
    from twobyteasr.glossary.terminology import GlossarySnapshot
    project = SubtitleProject(media=StudioMedia(path='private.mp4'),
        cues=[StudioCue('project-cue-29', 1000, 2000, '反手还能再推叶林')])
    before = copy.deepcopy(project)
    calls = install(monkeypatch, {'checked_ids': [1], 'cues': [], 'new_suspects': [optional_row]})
    preview = preview_glossary_correction(project, ['project-cue-29'], GlossarySnapshot(), config())
    assert len(calls) == 1 and preview.hits == ()
    receipt = preview.receipt
    assert receipt['successful_cues'] == 1 and receipt['fallback_cues'] == 0
    assert receipt['pending_optional_metadata']['status'] == 'pending_review'
    assert receipt['pending_optional_metadata']['unassigned_rows'] == 1
    preserved = receipt['unassigned_new_suspects'][0]
    assert preserved['raw_model_row'] == optional_row and preserved['validation_state'] == 'invalid'
    assert preserved['validation_errors']
    assert preserved['source_batch_index'] == 1 and preserved['source_processing_ids'] == [1]
    assert preserved['source_project_cue_ids'] == ['project-cue-29']
    assert preserved['source_review_kind'] == 'current_glossary_text_review'
    assert project.cues == before.cues and project.generation_metadata == before.generation_metadata
    assert receipt['asr_run'] is False and receipt['web_search_run'] is False


@pytest.mark.parametrize('optional_row', [
    {'id': 999, 'start': 6, 'end': 8, 'surface': '叶林', 'evidence': '不能归属'}, None])
def test_completion_retry_receipt_keeps_unassigned_rows_without_applying_or_saving(context, monkeypatch, optional_row):
    from tests.test_completion_retry_preview import project
    from tests.test_stage9_provider_snapshot import config
    from twobyteasr.app.completion_retry import completion_retry_preview
    from twobyteasr.recognition.service import RunOptions
    original = project()
    before = copy.deepcopy(original)
    calls = install(monkeypatch, {'checked_ids': [2], 'cues': [], 'new_suspects': [optional_row]})
    preview = completion_retry_preview(original, {'polishing_summary': {'fallback_ids': [2]}},
        RunOptions(settings_snapshot_json=json.dumps(config())))
    assert len(calls) == 1 and preview.hits == ()
    receipt = preview.receipt
    assert receipt['successful_ids'] == [2] and receipt['failed_ids'] == []
    assert receipt['pending_optional_metadata']['status'] == 'pending_review'
    assert receipt['pending_optional_metadata']['unassigned_rows'] == 1
    preserved = receipt['unassigned_new_suspects'][0]
    assert preserved['raw_model_row'] == optional_row and preserved['validation_state'] == 'invalid'
    assert preserved['validation_errors']
    assert preserved['source_review_kind'] == 'failed_stage_retry'
    assert preserved['source_processing_ids'] == [2] and preserved['source_batch_index'] is None
    assert preserved['source_batch_scope'] == 'merged_failed_retry_batches'
    assert original.cues == before.cues and original.asr_evidence == before.asr_evidence
    assert original.generation_metadata == before.generation_metadata
    assert receipt['asr_run'] is False and receipt['user_project_or_glossary_saved'] is False


@pytest.mark.parametrize('mandatory', [
    {'checked_ids': [], 'cues': []},
    {'checked_ids': [True], 'cues': []},
    {'checked_ids': [29], 'cues': [{'id': 999, 'edits': []}]},
    {'checked_ids': [29], 'cues': [{'id': 29, 'edits': [{'to': '错误'}]}]},
    {'checked_ids': [29], 'cues': [{'id': 29, 'edits': 'malformed'}]},
])
@pytest.mark.parametrize('structured', [False, True])
def test_bad_mandatory_payload_still_fails_batch(context, monkeypatch, mandatory, structured):
    rows = [row(29, '反手还能再推叶林')]
    monkeypatch.setattr(polishing, 'API_RETRIES', 1)
    calls = install(monkeypatch, mandatory, structured=structured)
    result = call(rows)
    assert not result.succeeded and result.failures and result[29] == rows[0].text
