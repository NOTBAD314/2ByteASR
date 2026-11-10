"""Offline regression evidence, not acoustic recognition accuracy."""
import copy
from types import SimpleNamespace

import numpy as np
import pytest

from twobyteasr.recognition import speech_coverage as coverage


def row(start, end, text='原文', speaker='S02'):
    return dict(start=start, end=end, text=text, speaker=speaker)


def test_union_uses_accumulated_maximum_end():
    assert coverage.union([(0, 100), (10, 20), (21, 30), (90, 110)]) == [(0, 110)]
    assert coverage.subtract([(0, 120)], [(0, 100), (10, 20), (90, 110)]) == [(110, 120)]


def test_ten_minute_internal_speech_gap_with_normal_tail():
    speech = [dict(start=120, end=720, speech_verified=True), dict(start=900, end=920)]
    state = coverage.make_state(speech, [row(0, 120), row(720, 1000)], duration=1000)
    gap, = state['gaps']
    assert gap['start'] == 120.25 and gap['end'] == 719.75
    assert gap['status'] == 'pending' and gap['first_missing_stage'] == 'parsed_response'


def test_music_energy_and_uncertain_vad_are_not_automatically_transcribed():
    state = coverage.make_state([dict(start=0, end=10, kind='music'),
        dict(start=20, end=30, confidence=.4), dict(start=40, end=50, detector='energy')], [], duration=60)
    calls = []
    assert coverage.recover(state, [], lambda *a: calls.append(a), source='api') == []
    assert len(state['gaps']) == 2 and all(g['status'] == 'needs_confirmation' for g in state['gaps'])
    assert not calls
    silent = coverage.make_state([], [], duration=60)
    assert not silent['gaps']


def test_explicit_exclusions_and_window_anomaly_are_independent():
    state = coverage.make_state([dict(start=0, end=20, detector='firered_vad')], [], duration=20,
        windows=[dict(index=8, start=0, end=20, complete=False, truncation_reasons=['unfinished_transcript_tail'])],
        excluded=[(0, 10)])
    gap, = state['gaps']
    assert gap['start'] == 10 and gap['window_ids'] == [8] and gap['status'] == 'failed'


def test_low_confidence_vad_stays_unconfirmed_even_with_a_truncated_window():
    state = coverage.make_state([dict(start=0, end=20, detector='firered_vad', confidence=.4)], [], duration=20,
        windows=[dict(index=1, start=0, end=20, complete=False, truncation_reasons=['token_limit'])])
    calls = []
    coverage.recover(state, [], lambda *args: calls.append(args), source='api')
    assert not calls and state['gaps'][0]['classification'] == 'processing_failure'


def test_multiple_gaps_and_partial_one_never_mark_all_recovered():
    state = coverage.make_state([dict(start=10, end=20, speech_verified=True),
        dict(start=40, end=50, speech_verified=True)], [], duration=60)
    calls = []
    def recognize(a, b):
        calls.append((a, b))
        return [row(10, 13, '补到三个秒')] if a < 20 else []
    result = coverage.recover(state, [], recognize, source='moss')
    assert len(result) == 1 and len(calls) == 2
    first, second = state['gaps']
    assert first['status'] == 'partial' and first['remaining_ranges'][0][0] == 13.25
    assert second['status'] == 'needs_confirmation' and second['remaining_ranges'] == [[40.0, 50.0]]
    assert state['recovery_cost']['request_count'] == 2


def test_downstream_loss_first_stage_and_overlapping_cues():
    state = coverage.make_state([dict(start=10, end=30, speech_verified=True)],
        [row(10, 30)], duration=40)
    coverage.checkpoint(state, 'parsed', [row(10, 30)])
    coverage.checkpoint(state, 'accepted', [row(10, 30)])
    coverage.checkpoint(state, 'speaker_filter', [row(10, 15), row(25, 30)])
    coverage.checkpoint(state, 'final', [row(10, 15), row(25, 30)])
    assert {g['first_missing_stage'] for g in state['gaps']} == {'speaker_filter'}


def test_merge_preserves_true_repetition_and_never_offsets_again():
    original = [row(100, 102, '快跑'), row(200, 202, '别动')]
    merged, accepted = coverage.merge_rows(original,
        [row(100.1, 102.1, '快跑'), row(103, 105, '快跑'), row(106, 108, '快跑')], [(100, 110)])
    assert len(accepted) == 2 and [r['start'] for r in merged] == [100, 103, 106, 200]
    assert original == [row(100, 102, '快跑'), row(200, 202, '别动')]


def test_recovery_budget_and_cancellation():
    state = coverage.make_state([dict(start=0, end=1000, speech_verified=True)], [], duration=1000)
    coverage.recover(state, [], lambda a, b: [row(a+2, b-2)], source='moss', max_requests=2)
    assert state['recovery_cost']['request_count'] == 2 and state['budget_exhausted']
    class CancelledError(Exception):
        pass
    def cancel():
        raise CancelledError()
    with pytest.raises(CancelledError):
        coverage.recover(copy.deepcopy(state), [], lambda *a: pytest.fail('cancelled request'), source='api', cancel=cancel)


def test_service_refusal_category_is_retained_without_resplitting():
    state = coverage.make_state([dict(start=0, end=600, speech_verified=True)], [], duration=600)
    class Rejected(Exception):
        category = 'content_blocked'
    def recognize(*args):
        raise Rejected('服务安全策略拒绝')
    coverage.recover(state, [], recognize, source='api')
    assert state['recovery_cost']['request_count'] == 1
    assert state['gaps'][0]['error_category'] == 'content_blocked'


@pytest.mark.parametrize('reason', ['token_limit', 'unfinished_transcript_tail', 'unexpected_stop', 'invalid_timestamp'])
def test_worker_recovery_uses_small_windows_and_preserves_native_rows(reason, monkeypatch):
    import moss_worker as worker
    calls = []
    def generate(model, processor, audio, messages, device, dtype, progress, receipt, inputs=None):
        calls.append(len(audio)/16000)
        receipt.update(complete=True, generation_attempts=1)
        return str(len(audio)/16000)
    def parse(raw):
        return [SimpleNamespace(start=0, end=float(raw), speaker='S01', text='实际模型回执夹具')]
    monkeypatch.setattr(worker, 'generate_full_context', generate)
    native = row(0, 10, '原始有效文字')
    chunk = dict(chunk_id=8, duration=200, segments=[copy.deepcopy(native)])
    record = dict(complete=False, generated_tokens=5000, truncation_reasons=[reason])
    budget = dict(requests=0, audio_seconds=0, started=__import__('time').monotonic())
    progress = SimpleNamespace(ops=None, stop=SimpleNamespace(is_set=lambda: False))
    worker.recover_moss_window(chunk, record, None, None, np.zeros(200*16000, np.float32),
                               [], None, None, progress, parse, budget)
    assert calls and max(calls) <= 94 and len(calls) <= 12
    assert native in chunk['segments'] and all(r['end'] <= 200 for r in chunk['segments'])
    assert all(r['speaker'].startswith('UNCONFIRMED_') for r in chunk['segments'] if r != native)


def test_worker_oom_recovery_has_bounded_subdivision(monkeypatch):
    import moss_worker as worker
    def generate(*args, **kwargs):
        raise RuntimeError('OOM')
    monkeypatch.setattr(worker, 'generate_full_context', generate)
    chunk = dict(chunk_id=1, duration=40, segments=[row(0, 3)])
    progress = SimpleNamespace(ops=SimpleNamespace(is_oom=lambda exc: True, empty_cache=lambda: None),
                               stop=SimpleNamespace(is_set=lambda: False))
    budget = dict(requests=0, audio_seconds=0, started=__import__('time').monotonic())
    worker.recover_moss_window(chunk, dict(complete=False), None, None, np.zeros(40*16000),
                               [], None, None, progress, lambda raw: [], budget)
    assert 1 <= budget['requests'] <= 12 and chunk['recovery']['remaining_ranges']


def test_resumed_internal_remainder_is_not_erased_by_a_later_valid_tail(monkeypatch):
    import moss_worker as worker
    def generate(*args, **kwargs):
        args[-1].update(complete=True, generation_attempts=1)
        return ''
    monkeypatch.setattr(worker, 'generate_full_context', generate)
    chunk = dict(chunk_id=1, duration=40, segments=[row(0, 10), row(30, 40)],
                 recovery=dict(attempts=[], remaining_ranges=[[10, 30]]))
    receipt = dict(complete=False)
    progress = SimpleNamespace(ops=None, stop=SimpleNamespace(is_set=lambda: False))
    budget = dict(requests=0, audio_seconds=0, started=__import__('time').monotonic())
    worker.recover_moss_window(chunk, receipt, None, None, np.zeros(40*16000), [], None, None,
                               progress, lambda raw: [], budget)
    assert chunk['recovery']['remaining_ranges'] == [(10.25, 29.75)] and not receipt['complete']


def test_eos_at_budget_is_a_fact_not_proof_of_lost_speech():
    import moss_worker as worker
    assert worker.ending_assessment(100, 100, 9, 9) == ('eos_at_token_limit', True)
    assert worker.ending_assessment(100, 100, 8, 9) == ('token_limit', False)


def test_failed_recovery_project_save_reopen_and_terminal_state(tmp_path):
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, load_project
    from twobyteasr.recognition.transcript_delivery import terminal_status
    project = SubtitleProject(media=StudioMedia(path='fixture.wav', duration_ms=60000))
    project.cues = [StudioCue('a', 0, 1000, '正常字幕', 'S01')]
    state = coverage.make_state([dict(start=10, end=20, speech_verified=True)], [], duration=60)
    coverage.recover(state, [], lambda a, b: [], source='moss')
    project.generation_metadata[coverage.KEY] = state
    path = tmp_path/'partial.2byteproj'
    save_project(project, path)
    reopened = load_project(path)
    assert reopened.cues[0].text == '正常字幕'
    assert coverage.pending(reopened.generation_metadata[coverage.KEY])[0]['attempts']
    assert terminal_status(dict(pending_range_count=0, speech_gap_count=1), 1) == 'partial_recovery'


def test_scored_vad_uses_actual_probability_and_bounds():
    from firered_vad_worker import scored_regions
    regions = scored_regions(dict(dur=10, timestamps=[(1, 3), (5, 8)]),
                             np.array([.1, .9, .95, .85, .2, .4, .5, .3, .2, .1]),
                             offset=20, bounds=(22, 27))
    assert [(r['start'], r['end']) for r in regions] == [(22, 23), (25, 27)]
    assert regions[0]['confidence'] >= .85 and regions[1]['confidence'] < .85


def test_saved_input_clock_maps_through_a_speed_changed_edit():
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    from twobyteasr.timeline.studio_edit_sequence import EditSequence, VideoSegment, store_sequence
    from twobyteasr.recognition.speech_recovery_project import project_ranges, merge_project_range
    project = SubtitleProject(media=StudioMedia(path='source.mp4', duration_ms=100000))
    original = EditSequence(source_path='source.mp4', source_duration_ms=100000,
        segments=[VideoSegment('original', 'source.mp4', 20000, 80000, 0, 30000)])
    current = EditSequence(source_path='source.mp4', source_duration_ms=100000,
        segments=[VideoSegment('current', 'source.mp4', 20000, 80000, 0, 60000)])
    store_sequence(project, current)
    state = coverage.make_state([dict(start=10, end=20, speech_verified=True)], [], duration=30)
    state['input_sequence'] = original.to_dict()
    project.generation_metadata[coverage.KEY] = state
    projected, = project_ranges(project)
    assert (projected['timeline_start_ms'], projected['timeline_end_ms']) == (20000, 40000)
    plan = SimpleNamespace(inserted_ids=['new'], cues=[SimpleNamespace(id='new', start_ms=20000, end_ms=26000, text='真实局部结果')])
    merge_project_range(project, plan)
    gap, = coverage.pending(project.generation_metadata[coverage.KEY])
    assert gap['remaining_ranges'] == [[13.25, 20.0]]


def test_full_pipeline_keeps_internal_gap_independent_from_language_pending(tmp_path, monkeypatch):
    from tests import test_moss_recovery_pipeline as fixture
    monkeypatch.setattr(fixture, 'raw_rows', lambda **kwargs: [row(0, 10, 'The opening speech remains intact'),
                                                           row(360, 370, 'The ending speech remains intact')])
    project, report, context = fixture.run_fixture(tmp_path, monkeypatch, 'fixture')
    assert project.cues and report['result']['transcript_counts']['pending_range_count'] == 0
    assert report['result']['transcript_counts']['speech_gap_count'] == 0
    assert report['result']['transcript_counts']['speech_confirmation_count'] > 0
    assert report['status'] in {'success', 'degraded_success'}
    assert coverage.pending(project.generation_metadata[coverage.KEY])


def test_recovered_identity_is_not_promoted_by_host_selection_or_window_merge(monkeypatch):
    import moss_firered_pipeline as pipeline
    from tests.test_moss_long_audio_windows import legacy, windowed_payload
    label = 'UNCONFIRMED_W1_R1_S01'
    selected = pipeline.select_host_speakers([row(0, 10, speaker=label), row(20, 30, speaker='S02')], 60,
                                            SimpleNamespace(), SimpleNamespace(expected_speakers=0))
    assert selected == ['S02']
    audio = np.zeros(100*16000, np.float32)
    payload = windowed_payload(audio)
    payload['chunks'][0]['segments'].append(row(4, 6, '局部恢复独立身份', label))
    monkeypatch.setattr(pipeline, '_compute_chunk_speaker_embeddings', lambda *args, **kwargs: {})
    normalized = pipeline._normalize_moss_full_context(payload, audio, legacy([], []))
    assert any(r['speaker'] == label and r['text'] == '局部恢复独立身份' for r in normalized['segments'])


def test_retained_incomplete_main_output_seeds_windows_without_weakening_main_cache(tmp_path):
    import json
    import moss_worker as worker
    import moss_firered_pipeline as pipeline
    from tests.test_moss_long_audio_windows import windowed_payload, legacy
    audio = np.zeros(100*16000, np.float32)
    prior = windowed_payload(audio)
    prior['model'] = 'exact-local-model'
    prior['execution']['complete'] = False
    for i, chunk in enumerate(prior['chunks']):
        chunk['raw_text'] = 'retained native output'
        prior['execution']['windows'][i].update(complete=i != 1, generation_attempts=1,
            truncation_reasons=[] if i != 1 else ['token_limit'])
    path = tmp_path/'retained.json'
    path.write_text(json.dumps(prior), 'utf8')
    receipt = dict(prior['execution'], window_checkpoint_dir=str(tmp_path/'windows'))
    worker.seed_window_checkpoints(path, dict(model=prior['model']), receipt)
    assert receipt['seeded_window_checkpoints'] == 3
    saved = [json.loads(p.read_text('utf8')) for p in (tmp_path/'windows').glob('window-*.json')]
    assert sum(v['record']['complete'] for v in saved) == 2
    assert len(list((tmp_path/'windows').glob('schedule-*.json'))) == 1
    with pytest.raises(ValueError):
        pipeline._decode_moss_full_context_cache(prior, audio, legacy([], []))
    foreign = dict(receipt, task_audio_fingerprint='other-audio', window_checkpoint_dir=str(tmp_path/'foreign'))
    worker.seed_window_checkpoints(path, dict(model=prior['model']), foreign)
    assert not (tmp_path/'foreign').exists()


def test_checkpoint_atomic_replace_retries_transient_windows_reader(tmp_path, monkeypatch):
    import json
    import moss_worker as worker
    path = tmp_path/'checkpoint.json'
    path.write_text('{"old":1}', 'utf8')
    replace = worker.os.replace
    attempts = []
    def temporarily_locked(source, target):
        attempts.append(str(source))
        if len(attempts) < 3:
            assert json.loads(path.read_text('utf8')) == {'old': 1}
            raise PermissionError('simulated Windows sharing violation')
        return replace(source, target)
    monkeypatch.setattr(worker.os, 'replace', temporarily_locked)
    worker.atomic_write_json(path, {'new': 2})
    assert len(attempts) == 3 and json.loads(path.read_text('utf8')) == {'new': 2}
    assert not list(tmp_path.glob('*.tmp'))


def test_range_result_adds_coverage_to_a_legacy_project_and_undo_restores_absence(tmp_path):
    from tests.test_studio_range_recognition import _project, _recognized
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot, attach_timeline_result
    from twobyteasr.recognition.range_recognition import payload_from_result, splice_range
    from twobyteasr.timeline.range_replace import ReplaceRangeCuesCommand
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    project = _project(tmp_path)
    assert coverage.KEY not in project.generation_metadata
    snapshot = capture_recognition_snapshot(project, range_ms=(9500, 15500))
    recognized = _recognized(6000)
    state = coverage.make_state([dict(start=0, end=6, speech_verified=True)], [], duration=6)
    state.update(input_sequence=snapshot['sequence'], input_offset_ms=9500)
    recognized.generation_metadata[coverage.KEY] = state
    result = attach_timeline_result(recognized, snapshot)
    assert coverage.KEY in result.generation_metadata
    info = result.generation_metadata['timeline_recognition']['range']
    plan = splice_range(project, info['window_ms'], payload_from_result(result, info), foreign_speakers=False)
    stack = QUndoStack()
    stack.push(ReplaceRangeCuesCommand(project, plan))
    assert project.generation_metadata[coverage.KEY]['input_offset_ms'] == 9500

    stack.undo()
    assert coverage.KEY not in project.generation_metadata
    stack.redo()
    assert project.generation_metadata[coverage.KEY]['input_offset_ms'] == 9500


def test_safety_refusal_cannot_be_sent_back_as_a_range_request(tmp_path):
    from tests.test_studio_range_recognition import _project
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot
    from twobyteasr.recognition.speech_recovery_project import validate_range_backend
    from twobyteasr.providers.qwen31_asr import ASRProtocolError
    project = _project(tmp_path)
    state = coverage.make_state([dict(start=10, end=14, speech_verified=True)], [], duration=25)
    state['gaps'][0]['reason'] = 'content_blocked'
    project.generation_metadata[coverage.KEY] = state
    snapshot = capture_recognition_snapshot(project, range_ms=(9500,15500))
    with pytest.raises(ASRProtocolError) as error:
        validate_range_backend(snapshot, 'api')
    assert error.value.category == 'content_blocked'
    validate_range_backend(snapshot, 'moss')
    validate_range_backend(capture_recognition_snapshot(project, range_ms=(1000,3000)), 'api')


def test_worker_attempt_history_survives_in_the_independent_project_ledger():
    from twobyteasr.recognition.run_context import RuntimeContext
    context = RuntimeContext(job_id='history')
    legacy = SimpleNamespace(record_run_event=lambda *args, **kwargs: None)
    payload = dict(segments=[row(100,120)], execution={}, chunks=[dict(chunk_id=4, offset=100, duration=40,
        recovery=dict(target_ranges=[[10,40]], remaining_ranges=[[20,40]], reason=['token_limit'],
            attempts=[dict(start=8, end=30, complete=False, accepted_segments=1, elapsed_seconds=2)]))])
    state = coverage.audit_primary(payload, [dict(start=100, end=140, speech_verified=True)], context,
                                   duration=140, legacy=legacy, source='moss')
    gap, = coverage.pending(state)
    assert len(gap['attempts']) == 1 and gap['attempts'][0]['start'] == 108
    assert gap['attempts'][0]['request_id'] == 'W4:R1'
    assert state['worker_recovery'][0]['remaining_ranges'] == [[120,140]]
    payload['segments'] = [row(100,140)]
    payload['chunks'][0]['recovery']['remaining_ranges'] = []
    state = coverage.audit_primary(payload, [dict(start=100, end=140, speech_verified=True)], context,
                                   duration=140, legacy=legacy, source='moss')
    assert not coverage.pending(state) and state['worker_recovery'][0]['attempts']
