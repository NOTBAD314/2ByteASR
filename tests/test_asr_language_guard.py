import copy
from unittest.mock import MagicMock, Mock

import numpy as np
import pytest

from twobyteasr.providers import asr_language_control
from twobyteasr.providers.cloud_asr_jobs import public_identity, transcribe_chunks
from twobyteasr.providers.llm_config import validate_qwen_asr_endpoint
from twobyteasr.providers.qwen31_asr import FLASH, FLASH30, FILETRANS, SentenceRevisions, flash
from twobyteasr.recognition.language_guard import conflict, inspect_primary, settings_policy


@pytest.mark.parametrize(('text', 'target', 'expected'), [
    ('我们今天先讨论这个问题然后再决定怎么解决。', 'en', 'zh'),
    ('Wir wissen nicht, was sie mit dem alten Haus machen wollen.', 'en', 'de'),
    ('Questa è una cosa che non possiamo fare senza di loro.', 'en', 'it'),
    ('Nel cortile della scuola hanno messo delle nuove sedie per gli ospiti.', 'en', 'it'),
    ('We saw Alla, Ai, and Nel at the cinema this afternoon.', 'en', None),
    ('We should do this while the other people are still here.', 'de', 'en'),
    ('そうですね。それは私たちが昨日話していたことです。', 'zh', 'ja'),
    ('もうすぐ始まります。', 'ja', None),
    ('東京国際展示場東展示棟', 'ja', None),
    ('Meet me at 東京ゲームショウ next Friday.', 'en', None),
    ('OK, NYC, RTX 5090, 12:30 https://example.org', 'en', None),
    ('', 'en', None),
])
def test_conservative_source_language_check(text, target, expected):
    assert conflict(text, target) == expected


@pytest.mark.parametrize(('model', 'strict', 'diarization'), [(FLASH, True, False), (FLASH, False, True),
                                                               (FLASH30, True, None)])
def test_native_http_exact_parameters(model, strict, diarization):
    from twobyteasr.recognition.cache import run_event_observer
    client = MagicMock()
    response = client.post.return_value.__enter__.return_value
    response.status_code = 200
    response.headers = {'Content-Type': 'application/json'}
    response.json.return_value = {'output': {'text': 'Hello', 'sentence': {
        'sentence_id': 1, 'sentence_end': True, 'begin_time': 0, 'end_time': 500, 'text': 'Hello',
        'words': [{'begin_time': 0, 'end_time': 500, 'text': 'Hello', 'fixed': True}]}}}
    endpoint = {'model': model, 'protocol': 'dashscope_asr_flash', 'api_key': 'sample-secret-value',
                'url': 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation',
                'speaker_source': 'native', 'strict_language': strict, 'asr_request_language': 'en'}
    validate_qwen_asr_endpoint(endpoint)
    events = []
    with run_event_observer(lambda event, payload: events.append((event, payload))):
        result = flash(np.zeros(16000), endpoint, requests_module=client)
    assert result['text'] == 'Hello'
    request = client.post.call_args.kwargs
    assert request['json']['parameters']['language_hints'] == ['en']
    assert request['json']['parameters'].get('speaker_diarization_enabled') is diarization
    assert 'diarization_enabled' not in request['json']['parameters']
    assert request['headers']['X-DashScope-SSE'] == ('disable' if model == FLASH30 else 'enable')
    event = next(value for name, value in events if name == 'asr_language_request')
    assert 'sample-secret-value' not in repr(event)
    assert event['parameters']['language_hints'] == ['en']
    with pytest.raises(RuntimeError, match='Flash'):
        validate_qwen_asr_endpoint(dict(endpoint, protocol='dashscope_filetrans'))


def test_flash_cumulative_revisions_keep_the_final_measured_words():
    revisions = SentenceRevisions()
    first = {'begin_time': 40, 'end_time': 400, 'text': 'Hello', 'fixed': False}
    second = {'begin_time': 550, 'end_time': 900, 'text': ' world', 'fixed': True}
    for number, text, words in [(1, 'Hello', [first]), (2, 'Hello world', [dict(first, fixed=True), second])]:
        revisions.consume({'output': {'text': text, 'sentence': {'sentence_id': number, 'sentence_end': True,
            'begin_time': 40, 'end_time': words[-1]['end_time'], 'text': text, 'words': words}}})
    result = revisions.result(1.)
    assert len(result['segments']) == 1
    assert result['timing_granularity'] == 'word'
    assert [word['word'] for word in result['words']] == ['Hello', ' world']


def test_flash_cache_partitions_manual_language_and_diarization():
    endpoint = {'model': FLASH, 'speaker_source': 'native', 'requested_language': 'en',
                'asr_request_language': 'en', 'strict_language': True}
    base = public_identity(endpoint)
    for changed in (dict(strict_language=False), dict(speaker_source='single'),
                    dict(requested_language='ja', asr_request_language='ja'), dict(model=FILETRANS),
                    dict(keep_dialect=True), dict(language_guard_repair=True)):
        assert base != public_identity({**endpoint, **changed})


def test_flash_chunk_resume_keeps_language_on_every_request(tmp_path, monkeypatch):
    from twobyteasr.providers import cloud_asr_jobs
    monkeypatch.setattr(cloud_asr_jobs, 'chunk_ranges', lambda *a: [(0, 16000), (16000, 32000), (32000, 48000)])
    endpoint = {'model': FLASH, 'protocol': 'dashscope_asr_flash', 'speaker_source': 'native',
                'asr_request_language': 'en', 'requested_language': 'en', 'strict_language': True}
    seen = []
    def caller(samples, endpoint, *, check):
        seen.append((endpoint['language_request_index'], asr_language_control.flash_parameters(endpoint)[0]))
        if len(seen) == 2:
            raise OSError('test connection interruption')
        return {'text': 'Hello world'}
    with pytest.raises(OSError):
        transcribe_chunks(np.zeros(48000), endpoint, tmp_path, caller=caller)
    rows = transcribe_chunks(np.zeros(48000), endpoint, tmp_path, caller=caller)
    assert [index for index, _ in seen] == [0, 1, 1, 2]
    assert all(p['language_hints'] == ['en'] and p['speaker_diarization_enabled'] is False for _, p in seen)
    assert len(rows) == 3


def test_timed_repair_needs_independent_confirmation_and_preserves_neighbors():
    target = 'We should do this while the other people are still here.'
    old = dict(start=1., end=3., speaker='S02', text='我们今天先讨论这个问题然后再决定怎么解决。')
    neighbor = dict(start=3., end=4., speaker='S03', text='See you.')
    def runner(backend, left, right):
        assert (left, right) == pytest.approx((.65, 3.35))
        result = dict(start=1., end=3., text=target, speaker='RECOGNIZER_0')
        if backend == 'primary':
            result['tokens'] = [dict(start=1.1, end=2.9, text=target)]
        return [result]
    events, reviews = Mock(), Mock()
    rows = [old, neighbor]
    before = copy.deepcopy(rows)
    policy = settings_policy({'subtitle_language': {'language_backup_review': True}}, 'en')
    unconfirmed = inspect_primary(rows, policy, duration=4, primary='primary', runner=runner,
                                  backup=None, event=events, review=reviews)
    assert unconfirmed[0]['text'] == old['text'] and unconfirmed[0]['language_guard']['pending']
    result = inspect_primary(rows, policy, duration=4, primary='primary', backup='independent', runner=runner,
                             event=events, review=reviews)
    assert rows == before and result[1] == neighbor
    assert (result[0]['speaker'], result[0]['start'], result[0]['end']) == ('S02', 1.0, 3.0)
    assert result[0]['language_guard']['original_text'] == old['text']
    assert result[0]['text'] == result[0]['tokens'][0]['text'] == target


def test_repair_budget_leaves_remaining_candidates_in_place():
    rows = [dict(start=2*i, end=2*i+.9, text='我们今天先讨论这个问题然后再决定怎么解决。') for i in range(20)]
    runner, events, review = Mock(return_value=[]), Mock(), Mock()
    result = inspect_primary(rows, settings_policy({}, 'en'), duration=40, primary='primary', runner=runner,
                             event=events, review=review)
    assert runner.call_count == 8
    assert review.call_count == len(result) == 20
    assert [row['text'] for row in result] == [row['text'] for row in rows]
    assert events.call_args.kwargs['pending'] == 20


def test_ecapa_can_split_real_provider_word_layout_without_losing_punctuation():
    from twobyteasr.recognition.speaker_diarization import assign_identities
    row = dict(start=0., end=4., text='Hello world. Goodbye now!', tokens=[
        dict(start=.1, end=.6, text='Hello'), dict(start=.7, end=.9, text='world'),
        dict(start=2., end=2.4, text='Goodbye'), dict(start=2.6, end=3., text='now'),
    ])
    separated = assign_identities([row], [dict(start=0., end=1., speaker='S01'),
                                          dict(start=1.9, end=3.1, speaker='S02')])
    assert [(v['speaker'], v['text']) for v in separated] == [('S01', 'Hello world.'), ('S02', 'Goodbye now!')]
    assert [(v['start'], v['end']) for v in separated] == [(.1, .9), (2., 3.)]
    assert [word['text'] for v in separated for word in v['tokens']] == ['Hello', 'world', 'Goodbye', 'now']


def test_flash_no_speech_preserves_other_chunks_and_records_window(tmp_path, monkeypatch):
    from twobyteasr.providers import cloud_asr_jobs
    from twobyteasr.providers.qwen31_asr import ASRProtocolError
    monkeypatch.setattr(cloud_asr_jobs, 'chunk_ranges', lambda *_: [(0, 16000), (16000, 32000)])
    endpoint = dict(model=FLASH, protocol='dashscope_asr_flash', asr_request_language='en')
    progress = Mock()
    def caller(audio, endpoint, *, check):
        if endpoint['language_request_index'] == 0:
            raise ASRProtocolError('ASR_RESPONSE_HAVE_NO_WORDS', 'CLIENT_ERROR')
        return {'text': 'Hello world'}
    rows = transcribe_chunks(np.zeros(32000), endpoint, tmp_path, caller=caller, progress=progress)
    assert rows[0]['cloud_gap']['reason'] == 'provider_no_words'
    assert rows[1]['text'] == 'Hello world'
    progress.assert_any_call('provider_no_words', 0, 2)


def test_long_task_concurrent_gateway_slices_keep_the_same_language(tmp_path, monkeypatch):
    from threading import Barrier
    import requests
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context

    workers = Barrier(3)
    submitted = []
    def post(url, **kwargs):
        submitted.append(kwargs['json'])
        workers.wait(timeout=5)
        response = Mock(status_code=200)
        response.json.return_value = {'text': 'We are still here.'}
        return response

    monkeypatch.setattr(asr, 'CLOUD_BATCH_WORKERS', 3)
    monkeypatch.setattr(asr, '_ASR_API_THROTTLE', Mock())
    monkeypatch.setattr(requests, 'post', post)
    endpoint = {'model': 'microsoft/mai-transcribe-2', 'protocol': 'openrouter_verbose_json',
                'provider': 'openrouter', 'url': 'https://openrouter.ai/api/v1/audio/transcriptions',
                'api_key': 'sample-secret-value', 'asr_request_language': 'en', 'strict_language': True,
                'audit_root': str(tmp_path / 'evidence')}
    spans = [{'audio': (np.zeros(16000), 16000), 'start': start, 'end': start + 1}
             for start in (0, 305, 610)]
    with activate_runtime_context(RuntimeContext(requested_language='en')):
        rows = asr._transcribe_qwen_api(tmp_path / 'test.wav', spans, _endpoint=endpoint, _context='')
    assert len(submitted) == 3 and {body['language'] for body in submitted} == {'en'}
    assert [row['start'] for row in rows] == [0, 305, 610]


def test_fixed_spark_route_refuses_conflicting_manual_language_before_connecting():
    pytest.importorskip('websockets')
    from twobyteasr.providers import spark_asr
    from twobyteasr.providers.qwen31_asr import ASRProtocolError

    connector = Mock()
    with pytest.raises(ASRProtocolError, match='普通話'):
        spark_asr.transcribe(np.zeros(16000), dict(model=spark_asr.MODEL, requested_language='en', strict_language=True),
                             connection_factory=connector)
    connector.assert_not_called()
def test_short_acoustically_confirmed_switch_preserves_words_without_retry():
    from twobyteasr.recognition.language_guard import inspect_primary, settings_policy

    rows = [
        dict(start=0., end=4., speaker='S01',
             text='We have to keep the recording and we will check it before we publish it.'),
        dict(start=4.1, end=6., speaker='S01', text='今天的節目馬上開始請大家耐心等候。'),
        dict(start=6.1, end=10., speaker='S01',
             text='Please make sure that the subtitles and the original words are saved before we leave.'),
    ]
    events = []
    candidates = inspect_primary(rows, settings_policy({}, 'en'), duration=10.,
        primary='qwen_local', runner=lambda *_: pytest.fail('Confirmed code switch did not need a retry'),
        event=lambda name, **data: events.append((name, data)),
        review=lambda *_args, **_kwargs: pytest.fail('Confirmed code switch does not need review'),
        acoustic_probe=lambda windows: {(window.start, window.end): {'language': 'zh'} for window in windows})
    assert candidates[1]['text'] == rows[1]['text']
    assert candidates[1]['language_guard']['classification'] == 'confirmed_short_switch'
    assert events[-1][1]['confirmed_mixed_count'] == 1


def test_measured_repair_admits_only_verified_silent_extra_edges():
    from twobyteasr.recognition.language_guard import _timed_candidate

    text = 'We should check the recording and make sure all of the original words are still here.'
    original = {'start': 0., 'end': 6.}
    candidate = dict(start=1., end=5., text=text,
                     tokens=[dict(text=text, start=1., end=5., start_basis='model', end_basis='model')])
    audio = np.zeros(6 * 16000, dtype=np.float32)
    audio[16000:5*16000] = .02
    assert _timed_candidate([candidate], original, 'en', audio=audio)[1] == 'measured_silent_source_edges'
    audio[800] = .02
    assert _timed_candidate([candidate], original, 'en', audio=audio) == (None, 'insufficient_edge_coverage')


@pytest.mark.parametrize('backend,comparable,accepted', [
    ('whisper_turbo', True, True),
    ('whisper_turbo', False, False),
    ('qwen_local', True, False),
])
def test_default_repair_requires_independent_matching_unforced_reading(backend, comparable, accepted):
    text = 'We should check the recording and make sure all of the original words are still here.'
    other_text = 'We should read all of the original subtitles before we export the video.'
    original = dict(start=1., end=5., speaker='S02', text='今天的節目馬上開始請大家耐心等候。')
    timed = dict(start=1., end=5., text=text, speaker='S01',
                 tokens=[dict(start=1.1, end=4.9, text=text, start_basis='model', end_basis='model')])
    events, review = Mock(), Mock()

    def observe(windows):
        return {(window.start, window.end): dict(language='en', method='unforced_qwen_local',
                                                text=text if comparable else other_text) for window in windows}

    result, = inspect_primary([original], settings_policy({}, 'en'), duration=6., primary=backend,
                              runner=lambda *_: [timed], event=events, review=review, acoustic_probe=observe)
    assert (result['start'], result['end'], result['speaker']) == (1., 5., 'S02')
    assert result['language_guard']['original_text'] == original['text']
    if accepted:
        assert result['text'] == text and result['tokens'] == timed['tokens']
        assert result['language_guard']['confirmation_backend'] == 'qwen_local'
        review.assert_not_called()
    else:
        assert result['text'] == original['text'] and result['language_guard']['pending']
        review.assert_called_once()
