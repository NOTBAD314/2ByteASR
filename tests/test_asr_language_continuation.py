from types import SimpleNamespace
from unittest.mock import Mock

from twobyteasr.providers.asr_language_control import flash_parameters, policy
from twobyteasr.providers.qwen31_asr import FLASH, FLASH30, FILETRANS, SentenceRevisions
from twobyteasr.recognition.asr_capabilities import issue
from twobyteasr.recognition.language_guard import inspect_primary, settings_policy
from twobyteasr.recognition.language_repair_budget import RepairBudget, plan_windows


def test_registry_distinguishes_flash_filetrans_fixed_and_detect_only():
    assert flash_parameters(dict(model=FLASH, asr_request_language='tr'))[0]['language_hints'] == ['tr']
    assert issue('api', 'ja', endpoint={'model': 'spark_asr_v2', 'protocol': 'spark_wss'})
    assert issue('canary_qwen', 'de') and not issue('canary_qwen', 'en')
    assert issue('firered', 'ja') and not issue('firered', 'en')
    assert policy({'model': FILETRANS, 'protocol': 'dashscope_filetrans'}, 'en')['parameter'] == 'parameters.language_hints'
    assert policy({'model': 'qwen3-asr-flash-filetrans', 'protocol': 'dashscope_filetrans'}, 'en')['parameter'] == 'parameters.language'
    assert policy({'model': 'moss-transcribe-diarize-pro', 'protocol': 'mosi_transcriptions'}, 'ja')['request_language'] is None
    assert FLASH != FLASH30


def test_repair_schedules_later_sections_before_exhausting_early_sections():
    rows = [dict(start=zone*1800+2*i, end=zone*1800+2*i+1, speaker='S01') for zone in range(12) for i in range(10)]
    windows = list(plan_windows(rows, range(len(rows)), 21600))
    assert [window.zone for window in windows[:12]] == list(range(12))
    speech = [{'start': 0, 'end': 20000}]
    budget = RepairBudget(windows, 21600, speech, {'repair_profile': 'custom', 'repair_max_requests': 15})
    admitted = [window for window in windows if not budget.reserve(window, 'local')]
    assert len(admitted) == 15
    assert {window.zone for window in admitted} == set(range(12))


def test_adjacent_language_flags_use_one_upload_and_preserve_each_row():
    rows = [dict(start=1., end=2., speaker='S01', text='我们先考虑一下这个具体的问题吧。'),
            dict(start=2.15, end=3., speaker='S01', text='你可以解释一下具体的处理方法吗？'),
            dict(start=3.05, end=4., speaker='S02', text='我们不能忽略这个重要的问题。')]
    runner, review, events = Mock(return_value=[]), Mock(), Mock()
    result = inspect_primary(rows, settings_policy({}, 'en'), duration=4., primary='api', runner=runner,
                             event=events, review=review)
    assert runner.call_count == 2
    assert [row['text'] for row in result] == [row['text'] for row in rows]
    assert all(row['language_guard']['pending'] for row in result)


def test_cost_cap_requires_a_conservative_cloud_quote():
    windows = list(plan_windows([dict(start=2., end=6.)], [0], 10))
    cap = {'repair_profile': 'custom', 'repair_max_cost_cents': 2}
    assert RepairBudget(windows, 10, [], cap).reserve(windows[0], 'api') == 'cost_unverified'
    budget = RepairBudget(windows, 10, [], cap, quote=lambda model, duration: .003, prior_cost_usd=.018)
    assert budget.reserve(windows[0], 'api') == 'cost_limit'
    assert not budget.reserve(windows[0], 'local')


def _partial(text, number, begin=0, end=None, words=()):
    return {'output': {'text': text, 'sentence': {'sentence_id': number, 'text': text, 'begin_time': begin,
                      'end_time': end, 'sentence_end': end is not None, 'words': list(words)}}}


def test_flash_reordered_cumulative_prefix_with_a_corrected_word():
    parser = SentenceRevisions()
    parser.consume(_partial('We should walk now', 3, end=1900, words=[
        {'text': 'We', 'begin_time': 0, 'end_time': 200, 'fixed': True},
        {'text': ' should', 'begin_time': 200, 'end_time': 700, 'fixed': True},
        {'text': ' walk', 'begin_time': 700, 'end_time': 1300, 'fixed': True},
        {'text': ' now', 'begin_time': 1400, 'end_time': 1900, 'fixed': True}]))
    parser.consume(_partial('We should talk', 2, end=1300))
    parser.consume(_partial('We should walk', 3))
    result = parser.result(2.)
    assert result['text'] == 'We should walk now' and len(result['segments']) == 1
    assert len(result['words']) == 4 and result['segments'][0]['response_event'] == 1


def test_confirmed_repeated_words_at_distinct_times_are_not_deduplicated():
    parser = SentenceRevisions(native=True)
    parser.consume(_partial('Yes. Yes.', 2, begin=850, end=1200))
    second = parser.sentences[(0, 2)]
    second['text'] = 'Yes.'
    parser.consume(_partial('Yes.', 1, end=400))
    assert len(parser.result(2.)['segments']) == 2


def test_coverage_reports_acoustic_time_without_inventing_word_recall():
    from twobyteasr.recognition.speech_coverage import finalize, make_state
    state = make_state([{'start': 0., 'end': 30.}, {'start': 30., 'end': 40., 'kind': 'music'}],
                       [], duration=40.)
    legacy = SimpleNamespace(record_run_event=Mock(), add_review_item=Mock())
    finalize(SimpleNamespace(speech_coverage=state), [dict(start=0., end=10., text='test')], legacy)
    metrics = state['coverage_metrics']
    assert metrics['speech_seconds'] == 30
    assert metrics['covered_speech_seconds'] == 10
    assert metrics['longest_uncovered_seconds'] == 20
    assert metrics['annotated_word_omission_rate'] is None


def test_five_native_flash_requests_run_concurrently_and_resume_only_the_failure(tmp_path, monkeypatch):
    import threading
    import numpy as np
    import pytest
    from twobyteasr.providers import cloud_asr_jobs
    monkeypatch.setattr(cloud_asr_jobs, 'chunk_ranges', lambda *_: [(16000*i, 16000*(i+1)) for i in range(5)])
    audio = np.zeros(80000, np.float32)
    endpoint = {'model': FLASH, 'protocol': 'dashscope_asr_flash', 'asr_request_language': 'ja'}
    barrier = threading.Barrier(5)
    sent = []

    def initial(_, frozen, *, check):
        sent.append(frozen['language_request_index'])
        assert flash_parameters(frozen)[0]['language_hints'] == ['ja']
        barrier.wait(5.)
        if frozen['language_request_index'] == 2:
            raise OSError('fixture disconnect')
        return {'text': '確認します。'}

    with pytest.raises(OSError):
        cloud_asr_jobs.transcribe_chunks(audio, endpoint, tmp_path, caller=initial, workers=5)
    assert sorted(sent) == list(range(5))
    retried = []

    def resume(_, frozen, *, check):
        retried.append(frozen['language_request_range'])
        assert flash_parameters(frozen)[0]['language_hints'] == ['ja']
        return {'text': '再開します。'}

    rows = cloud_asr_jobs.transcribe_chunks(audio, endpoint, tmp_path, caller=resume, workers=3)
    assert retried == [[2., 3.]]
    assert [row['start'] for row in rows] == [0., 1., 2., 3., 4.]


def test_matching_local_acoustic_evidence_defers_forced_repair():
    row = dict(start=1., end=4., speaker='S01', text='我们今天先讨论这个问题然后再决定怎么解决。')
    attempts = Mock(return_value=[])
    observations = lambda windows: {(w.start, w.end): {'language': 'zh', 'method': 'unforced_qwen_local'} for w in windows}
    result = inspect_primary([row], settings_policy({}, 'en'), duration=5., primary='api', runner=attempts,
                             event=Mock(), review=Mock(), acoustic_probe=observations)
    attempts.assert_not_called()
    assert result[0]['text'] == row['text']
    assert result[0]['language_guard']['attempts'][0]['category'] == 'source_language_may_differ'


def test_mixed_language_confirmation_is_undoable_and_exactly_bound_to_original_pcm():
    import numpy as np
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
    from twobyteasr.recognition.alignment_audio import pcm_digest
    from twobyteasr.recognition.language_guard import confirmed_mixed_reading
    from twobyteasr.recognition.language_recovery_project import project_review_ranges
    from twobyteasr.timeline.language_review_commands import ConfirmMixedLanguageCommand
    audio = np.zeros(16000, dtype=np.float32)
    row = dict(start=0., end=1., text='这是录音中的一整句真实切换。')
    observation = dict(id='o1', status='observation', reason='language_guard_pending',
                       review_required=True, requested_language='en', start_sample=0, end_sample=16000,
                       pcm_sha256=pcm_digest(audio), language_guard={'original_text':row['text']})
    project = SubtitleProject(media=StudioMedia(path='input.wav', duration_ms=1000))
    project.generation_metadata['transcript_acceptance'] = {'observed_ranges':[observation]}
    command = ConfirmMixedLanguageCommand(project, 'o1')
    command.redo()
    context = SimpleNamespace(recognition_snapshot={'project':project.to_dict()}, requested_language='en')
    assert not project_review_ranges(project)
    assert confirmed_mixed_reading(audio, context, row)
    changed = audio.copy()
    changed[0] = .2
    assert not confirmed_mixed_reading(changed, context, row)
    command.undo()
    assert project_review_ranges(project)[0]['id'] == 'o1'


def test_exact_alternate_reference_skips_the_phonetic_search(monkeypatch):
    import subtitle_core as core
    phonetics = Mock(side_effect=AssertionError('exact reference cannot improve above 1.0'))
    monkeypatch.setattr(core, 'phonetic_text', phonetics)
    assert core.best_alternate_window('Keep the source text.', 'Before that. Keep the source text. Then continue.') == (
        'keepthesourcetext', 1.0)
    phonetics.assert_not_called()
