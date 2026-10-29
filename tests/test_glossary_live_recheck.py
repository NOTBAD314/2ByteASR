"""Offline checks of paid-request fences and honest Studio receipt coverage."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from twobyteasr.acceptance.glossary_live_recheck_audit import RequestBudget, review_coverage, wire_contexts


def test_concurrent_reservations_cannot_exceed_explicit_global_allowance():
    budget = RequestBudget(2)
    budget.armed = True

    def reserve(index):
        try:
            return budget.reserve('submit', dict(index=index))['number']
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(reserve, range(40)))
    assert sorted(value for value in results if value) == [1, 2]
    assert len(budget.snapshot()['provider_submissions']) == 2
    assert len(budget.snapshot()['rejections']) == 38


def test_independent_actual_cli_guard_counts_repair_and_failed_dispatch():
    budget = RequestBudget(2)
    budget.armed = True
    budget.reserve('submit', dict(kind_of_call='first'))
    # Even if an adapter tried a second call inside one submission, its model
    # dispatch consumes the same finite allowance; the third never delegates.
    first = budget.reserve('cli', dict(stage='polished'))
    first['error'] = 'Bad JSON returned by actual transport'
    budget.reserve('cli', dict(stage='JSON repair'))
    with pytest.raises(RuntimeError, match='no additional model request dispatched'):
        budget.reserve('cli', dict(stage='third repair'))
    assert len(budget.snapshot()['actual_cli_model_calls']) == 2
    assert budget.snapshot()['rejections'][-1]['armed'] is True


def test_background_denial_spends_no_allowance_and_one_request_mode_is_strict():
    budget = RequestBudget(1)
    with pytest.raises(RuntimeError, match='visible Studio AI'):
        budget.reserve('submit', {})
    assert not budget.snapshot()['provider_submissions']
    budget.armed = True
    budget.reserve('submit', {})
    with pytest.raises(RuntimeError, match='budget exhausted'):
        budget.reserve('submit', {})
    for value in (0, 3, True, '2'):
        with pytest.raises(ValueError): RequestBudget(value)


def receipt(count=57):
    return dict(successful_cues=count, fallback_cues=0, proposed_cues=0,
        audio_verified=False, segments=[dict(cue_id=f'cue:{i}', input_text='原文', final_text='原文',
            detail=dict(quality_state='checked_no_pending_identifier_suggestions')) for i in range(count)])


def test_zero_proposals_are_valid_success_for_57_current_cues_not_50_asr_records():
    row = receipt()
    result = review_coverage(row, [f'cue:{i}' for i in range(57)])
    assert result['exact_cue_coverage'] and result['all_cues_received_without_fallback']
    assert result['proposed_cues'] == 0
    assert result['audio_verified'] is False
    assert not review_coverage(row, [f'cue:{i}' for i in range(50)])['exact_cue_coverage']


def test_optional_bad_suspect_metadata_remains_pending_without_fake_fallback():
    row = receipt(3)
    row['segments'][0]['detail'] = dict(quality_state='pending_suspect_adjudication',
        response_state='validated_with_pending_optional_metadata',
        new_suspects=[dict(validation_state='invalid', validation_errors=['bad original span'])])
    row['segments'][1]['detail'] = dict(quality_state='pending_rejected_edit_review',
        rejected_edits=[dict(rule_id='length_change_without_support')])
    result = review_coverage(row, [f'cue:{i}' for i in range(3)])
    assert result['all_cues_received_without_fallback']
    assert result['pending_cue_ids'] == ['cue:0', 'cue:1']
    assert result['new_suspects'] == 1 and result['rejected_edits'] == 1


def test_duplicate_missing_or_fallback_receipt_cannot_pass_full_coverage():
    row = receipt(3)
    row['segments'][1]['cue_id'] = 'cue:0'
    result = review_coverage(row, [f'cue:{i}' for i in range(3)])
    assert not result['exact_cue_coverage']
    row = receipt(3); row.update(successful_cues=2, fallback_cues=1)
    assert not review_coverage(row, [f'cue:{i}' for i in range(3)])['all_cues_received_without_fallback']


def test_wire_observation_never_parses_assistant_or_blocks_plain_repair_instruction():
    messages = [dict(role='assistant', content='{bad returned JSON'),
        dict(role='user', content='{malformed repair instruction'),
        dict(role='user', content='Please repair only mandatory JSON fields'),
        dict(role='user', content='{"prompt_version":"actual-v13","content_scene":{"domain":"actual-domain"}}')]
    assert wire_contexts(messages) == [dict(prompt_version='actual-v13', content_scene={'domain': 'actual-domain'})]


def test_unassigned_optional_receipt_rows_keep_zero_edit_success_pending():
    row = receipt(3)
    row['unassigned_new_suspects'] = [dict(validation_state='invalid', validation_errors=['unknown cue id'],
        raw_model_row=dict(id='unknown'), source_batch_index=1, source_project_cue_ids=['cue:0','cue:1','cue:2'])]
    row['pending_optional_metadata'] = dict(status='pending_review', unassigned_rows=1,
        scoped_new_suspect_rows=0, invalid_scoped_new_suspect_rows=0)
    result = review_coverage(row, [f'cue:{i}' for i in range(3)])
    assert result['all_cues_received_without_fallback'] and result['proposed_cues'] == 0
    assert result['pending_cue_count'] == 0 and result['pending_quality']
    assert result['unassigned_new_suspect_rows'] == result['invalid_unassigned_new_suspect_rows'] == 1


@pytest.fixture
def actual_submission_guard(tmp_path, monkeypatch):
    """Real frozen profile and guard; both dispatch delegates are local fakes."""
    import json
    import threading
    from types import SimpleNamespace
    import subtitle_core  # noqa: F401 - initialize the existing facade first
    from twobyteasr.recognition import cache
    from twobyteasr.acceptance import glossary_live_resources
    from twobyteasr.providers.ai_providers import CLIProvider
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot, snapshot_in_settings
    from twobyteasr.acceptance.glossary_live_recheck_audit import LiveGuard
    from twobyteasr.providers.provider_service import ProviderService

    settings = {'models': {'ai_service': 'grok_account'},
        'switches': {'unified_glm_processing': True}}
    for stage in ('group', 'polish'):
        settings['models'].update({f'{stage}_{key}': value for key, value in {
            'provider': 'grok_oauth', 'transport': 'grok_cli', 'model': 'grok-4.7',
            'base_url': '', 'protocol': 'openai_compatible_chat'}.items()})
    settings_path = tmp_path/'settings.json'
    settings_path.write_text(json.dumps(settings), 'utf8')
    (tmp_path/'recheck-input.json').write_text(json.dumps(dict(settings=str(settings_path),
        expected_model='grok-4.7', maximum_requests=2)), 'utf8')
    monkeypatch.setenv(glossary_live_resources.MANIFEST_ENV, 'fixture-manifest')
    monkeypatch.setattr(glossary_live_resources, 'validate_manifest', lambda *a: {})
    monkeypatch.setattr(glossary_live_resources, 'BorrowedResources',
        lambda *a: SimpleNamespace(restore=lambda: None))
    monkeypatch.setattr(cache, 'add_run_event_observer', lambda callback: callback)
    monkeypatch.setattr(cache, 'remove_run_event_observer', lambda observer: None)
    captures = []
    adapter = SimpleNamespace(provider_id='grok_oauth', model='grok-4.7',
        last_invocation_trace={'terminal_status': 'success', 'offline_fake': True})
    monkeypatch.setattr(CLIProvider, 'complete', lambda *a, **kw: '{"checked_ids":[1],"cues":[]}')

    def original_submit(service, selected, stage, messages, **options):
        captures.append(snapshot_in_settings(selected).public_identity())
        CLIProvider.complete(adapter, messages, stage=options['_adapter_stage'])
        event = threading.Event(); event.set()
        return SimpleNamespace(request_id=f'fixture-{len(captures)}', provider_id=adapter.provider_id,
            _event=event, _error=None, trace={})

    monkeypatch.setattr(ProviderService, 'submit', original_submit)
    snapshot = resolve_provider_snapshot(settings, stage='polish')
    guard = LiveGuard(tmp_path)
    guard.budget.armed = True
    try:
        yield guard, snapshot, captures
    finally:
        guard.restore()


def test_actual_guard_honors_frozen_cli_marker_and_original_submit_exact_identity(actual_submission_guard):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.providers.provider_service import ProviderService
    guard, snapshot, captures = actual_submission_guard
    selected = snapshot.execution_settings()
    assert 'ai_service' not in selected['models'] and 'polish_base_url' not in selected['models']
    # The former guard incorrectly repeated this legacy migration, although
    # the production endpoint and transport already honor the typed marker.
    with pytest.raises(ValueError, match='explicitly selected'):
        resolve_provider_snapshot(selected, stage='polish')
    for _ in range(2):
        ProviderService.submit(object(), selected, 'polish', [{'role': 'user', 'content': 'fixture'}],
            _adapter_stage='polished', operation_kind='polish')
    assert captures == [snapshot.public_identity(), snapshot.public_identity()]
    assert all(row == guard.provider for row in captures)
    with pytest.raises(RuntimeError, match='budget exhausted'):
        ProviderService.submit(object(), selected, 'polish', [],
            _adapter_stage='polished', operation_kind='polish')
    assert len(captures) == 2
    recorded = guard.snapshot()
    assert len(recorded['provider_submissions']) == len(recorded['actual_cli_model_calls']) == 2
    assert recorded['rejections'][-1]['requested_number'] == 3


@pytest.mark.parametrize('changed', [
    {'model': 'different-model'}, {'transport': 'antigravity_cli'},
    {'profile_id': 'different-profile'}, {'profile_revision': 'different-profile-digest'},
])
def test_actual_guard_rejects_changed_typed_identity_before_any_dispatch(actual_submission_guard, changed):
    from dataclasses import replace
    from twobyteasr.providers.provider_service import ProviderService
    guard, snapshot, captures = actual_submission_guard
    with pytest.raises(RuntimeError, match='unchanged configured'):
        ProviderService.submit(object(), replace(snapshot, **changed).execution_settings(), 'polish', [],
            _adapter_stage='polished', operation_kind='polish')
    assert not captures
    assert not guard.snapshot()['provider_submissions']
    assert not guard.snapshot()['actual_cli_model_calls']


def test_actual_guard_rejects_serialized_marker_without_silent_cli_default(actual_submission_guard):
    from twobyteasr.providers.provider_service import ProviderService
    guard, snapshot, captures = actual_submission_guard
    selected = snapshot.execution_settings()
    selected['_asr_provider_snapshot'] = snapshot.public_identity()
    with pytest.raises(ValueError, match='explicitly selected'):
        ProviderService.submit(object(), selected, 'polish', [],
            _adapter_stage='polished', operation_kind='polish')
    assert not captures and not guard.snapshot()['provider_submissions']
