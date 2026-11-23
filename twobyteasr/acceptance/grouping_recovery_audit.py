"""Test a recorded pre-grouping draft through the offline source/frozen paths."""
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch



def text_by_speaker(rows):
    result = defaultdict(str)
    for row in rows:
        result[row.speaker] += row.text
    return dict(result)


def main(output, fixture):
    output = Path(output).resolve()
    os.environ["TWOBYTEASR_TEST_ROOT"] = str(output / "profile")
    from twobyteasr.test_isolation import install, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    import subtitle_core as core
    import moss_firered_pipeline
    from twobyteasr.recognition.grouping_checkpoint import load as load_checkpoint, save
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.service import RunOptions, CancellationToken, CancelledError
    from twobyteasr.recognition.task_journal import TaskJournal
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.subtitle_rules.grouping_contract import GroupingContractError, validate_grouping_result
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.providers.ai_providers import AIProviderError
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.diagnostics.build_identity import load_build_identity
    from twobyteasr.projects.studio_project import load_project
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    from twobyteasr.recognition.cache import atomic_write_json, extend_review_items

    media = fixture["media"]
    rows = core.deserialize_segments(fixture["segments"])
    traces = fixture["traces"]
    acoustic, speech = fixture["tokens"], fixture["regions"]
    settings = fixture["offline_settings"]
    snapshot = resolve_provider_snapshot(settings)
    journal = TaskJournal('offline_replay_b8e903a8', output / 'journal').create([media['path']], RunOptions())
    events, requests = [], []
    mode = 'first'
    token = CancellationToken()
    context = RuntimeContext(task_language='zh', requested_language='zh', job_id=journal.job_id,
        media_path=media['path'], media_identity=media['identity'], provider_snapshot=snapshot,
        task_journal=journal, asr_settings_snapshot=settings, cancellation_token=token,
        execution_budget=SimpleNamespace(ai_requests=16))
    context.provider_snapshots['group'] = snapshot
    context.studio_project_path = str(output / "Grouping recovery - review pending.2byteproj")
    cache = core.media_cache_context(media["path"])
    assert cache["identity"] == media["identity"]

    def record(event, **payload):
        events.append(dict(event=event, run=mode, **payload))

    def complete(messages, **options):
        body = json.loads(messages[1]['content'])
        batch = str(options.get('batch_index') or getattr(grouping._batch_trace, 'batch_id', ''))
        requests.append((mode, batch, 'failed_constraints' in body or 'windows' in body))
        if mode == 'cancel':
            token.cancel()
            token.raise_if_cancelled()
        if 'windows' in body:
            return '{"windows":[]}'
        if 'failed_constraints' in body:
            return json.dumps(dict(boundaries=body.get('current_boundaries', [])))
        if batch in ('2', '15'):
            raise AIProviderError('offline: recorded parent split', category='structured_output_truncated')
        if batch in ('2.1', '15.2'):
            return '{"boundaries":[-1]}'
        trace = traces.get(batch)
        if trace:
            assert trace['source_segment_ids'] == [row['id'] for row in body['segments']]
            assert trace['source_text'] == body['source_text']
            key = 'final_boundaries' if batch == '3' else 'model_boundaries'
            return json.dumps(dict(boundaries=trace[key]))
        return json.dumps(dict(boundaries=sorted(set(body['source_segment_offsets'])
            | set(body['hard_break_character_offsets']) | {body['total_length']})))

    original_fallback = grouping.cues_from_quality
    staged = []
    legacy_group = core.group_subtitles

    def inject_local(*args, **kwargs):
        first_id = args[0][0].segment_id
        if mode == 'first' and first_id == fixture['failed_source_id'] and not kwargs.get('repair', True):
            raise GroupingContractError('offline: local constructor rejected this recorded range',
                                        category='source_time_mismatch')
        return original_fallback(*args, **kwargs)

    def run():
        return grouping.group_subtitles(rows, acoustic, speech, provider_snapshot=snapshot,
            cache_context=cache, max_workers=16)

    def observe_group(*args, **kwargs):
        grouped = legacy_group(*args, **kwargs)
        staged.append(grouped)
        return grouped

    def forbidden(*args, **kwargs):
        raise AssertionError("Recovery tried to repeat ASR or proofreading")

    with activate_runtime_context(context, legacy=core), patch.object(grouping, 'provider_for_stage',
            return_value=SimpleNamespace(complete=complete)), patch.object(grouping, 'record_run_event',
            side_effect=record), patch.object(grouping, 'CLOUD_BATCH_WORKERS', 16), patch.object(
            grouping, 'PARALLEL_CLOUD_BATCHES', True), patch.object(GLOBAL_PROVIDER_SERVICE,
            'scheduling_capacity', return_value={'effective_workers': 16}), patch.object(
            grouping, 'cues_from_quality', side_effect=inject_local), patch.object(
            core, 'transcribe_primary_reference', side_effect=forbidden), patch.object(
            core, 'polish_subtitles', side_effect=forbidden):
        extend_review_items(fixture.get("polishing_reviews", []))
        save(context, core, rows, acoustic, speech, seconds=media['audio_seconds'], fps=fixture['fps'],
             stage=9, use_ai=True, cache_context=cache)
        try:
            first = run()
        finally:
            atomic_write_json(output / 'first-attempt.json', dict(events=events, requests=requests))
        assert text_by_speaker(first) == text_by_speaker(rows)
        validate_grouping_result(rows, first)
        assert context.grouping_pending
        assert any(e['event'] == 'grouping_range_pending_retry' for e in events)
        pending = {p['batch_id'] for p in context.grouping_pending}
        first_plan = next(e for e in events if e['event'] == 'grouping_batch_plan')
        assert (first_plan['batch_count'], first_plan['scheduler_workers']) == (18, 16), first_plan
        children = {str(e.get('batch_index')) for e in events if e['event'] == 'grouping_api_fallback'}
        children.update(batch for _, batch, _ in requests)
        assert {'2.1', '15.2'} <= children
        context.resume = True
        context.grouping_pending.clear()
        assert len(load_checkpoint(context, cache_context=cache)['segments']) == 576
        mode = 'resume'
        with patch.object(core, 'group_subtitles', side_effect=observe_group):
            moss_firered_pipeline.process_media(media['path'], 1, 1, core, runtime_context=context)
        second = staged[-1]
        assert context.committed_result_ref
        target = Path(context.committed_result_ref["path"])
        report_path, _ = core.task_reporting.report_paths_for_media(media['path'])
        result_report = json.loads(Path(report_path).read_bytes())
        assert result_report["status"] == "partial_recovery"
        assert [(stage["index"], stage["status"]) for stage in result_report["stages"]] == [
            (9, "partial"), (10, "completed"), (11, "completed")]
        assert all(stage["status"] != "running" for stage in result_report["stages"])
        assert text_by_speaker(second) == text_by_speaker(rows)
        reused = {e['batch_index'] for e in events if e['run'] == 'resume' and e['event'] == 'grouping_range_reused'
                  and isinstance(e['batch_index'], int)}
        assert reused and reused == set(range(1, 19)) - pending, (reused, pending)
        assert not reused & {int(batch) for phase, batch, _ in requests if phase == 'resume' and batch.isdecimal()}
        mode = 'cancel'
        context.force_refresh_group_cache = True
        try:
            run()
        except CancelledError:
            assert token.is_cancelled
        else:
            raise AssertionError('Grouping did not propagate cancellation')
        assert len(load_checkpoint(context, cache_context=cache)['segments']) == 576
        assert len([r for r in requests if r[0] == 'cancel']) <= 16
        mode = 'save'
        validate_grouping_result(rows, second)
        reopened = load_project(target)
        assert len(reopened.cues) == len(second)
        assert all(cue.evidence_refs for cue in reopened.cues)
        exported = export_language_layers(reopened, output, target.stem, layers=('original',))
        atomic_write_json(output / 'verification.json', dict(source_rows=len(rows), first_cues=len(first),
            resumed_cues=len(second), reopened=len(reopened.cues), scheduler=first_plan,
            pending_first=sorted(pending), reused_on_resume=sorted(reused),
            request_counts=dict(Counter(phase for phase, _, _ in requests)),
            requests=requests, evidence_tokens=len(acoustic), original_vad_regions=len(speech),
            result_report=str(report_path), recovered_project=str(target), raw_model_bodies=0,
            identity=load_build_identity().to_dict(),
            exported=[str(item.path) for item in exported.artifacts]))
    atomic_write_json(output / 'events.json', events)

    return 0
