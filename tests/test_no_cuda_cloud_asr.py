"""Cloud recognition without CUDA or a local model runtime (2026-10-13).

Covers the Bailian Qwen3-ASR Filetrans schema, the MOSS-Transcribe-Diarize Pro
cloud engine (MOSI), address parsing, runtime/CUDA gates and the aligner CPU
route. Network access goes only to fake clients or a loopback fake server.
"""
import json
import sys
import threading
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import numpy as np
import pytest

from twobyteasr.qwen31_asr import ASRProtocolError, FILETRANS, QWEN3_FILETRANS


class Response:
    def __init__(self, data, code=200):
        self.data = data
        self.status_code = code

    def json(self):
        return self.data


class Storage:
    def __init__(self):
        self.uploads = 0
        self.deletes = 0

    def upload_audio(self, *a):
        self.uploads += 1
        return SimpleNamespace(key='owned/audio.wav')

    def create_download_url(self, *a, **kw):
        return 'https://bucket.example.com/audio.wav?secret=signature'

    def verify_download_url(self, url):
        pass

    def delete_object(self, key, **kw):
        self.deletes += 1


def qwen3_endpoint(**extra):
    return dict(model=QWEN3_FILETRANS, provider='qwen31_filetrans', protocol='dashscope_filetrans',
                url='https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription',
                api_key='key', speaker_source='native', **extra)


QWEN3_RESULT = {'file_url': 'x', 'transcripts': [{'channel_id': 0, 'text': '欢迎使用阿里云。', 'sentences': [
    {'sentence_id': 0, 'begin_time': 100, 'end_time': 1900, 'language': 'zh', 'emotion': 'neutral',
     'text': '欢迎使用阿里云。', 'words': [
         {'begin_time': 100, 'end_time': 500, 'text': '欢迎', 'punctuation': ''},
         {'begin_time': 500, 'end_time': 900, 'text': '使用', 'punctuation': ''},
         {'begin_time': 900, 'end_time': 1900, 'text': '阿里云', 'punctuation': '。'}]}]}]}


def test_qwen3_filetrans_uses_its_own_schema_and_word_timestamps(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    sent = {}
    fetched = []

    class Client:
        @staticmethod
        def post(url, **kw):
            sent.update(kw['json'])
            assert url.endswith('/api/v1/services/audio/asr/transcription')
            assert kw['headers']['X-DashScope-Async'] == 'enable'
            return Response({'output': {'task_id': 't1', 'task_status': 'PENDING'}})

        @staticmethod
        def get(url, **kw):
            if '/api/v1/tasks/t1' in url:
                return Response({'output': {'task_status': 'SUCCEEDED', 'result': {
                    'transcription_url': 'http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/pre/x.json?sig=1'}},
                    'usage': {'seconds': 2}})
            fetched.append(url)
            return Response(QWEN3_RESULT)

    storage = Storage()
    rows = filetrans(np.zeros(32000), qwen3_endpoint(filetrans_language='zh'), tmp_path, storage,
                     client=Client, sleep=lambda *_: None)
    assert sent['model'] == QWEN3_FILETRANS
    assert sent['input'] == {'file_url': 'https://bucket.example.com/audio.wav?secret=signature'}
    assert sent['parameters'] == {'channel_id': [0], 'enable_words': True, 'language': 'zh'}
    assert fetched and fetched[0].startswith('https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/')
    assert len(rows) == 1 and 'speaker' not in rows[0]
    assert rows[0]['timestamp_source'] == 'qwen3_filetrans_native_word'
    assert rows[0]['timing_precision'] == 'word'
    assert [t['text'] for t in rows[0]['tokens']] == ['欢迎', '使用', '阿里云。']
    assert rows[0]['tokens'][0]['start'] == pytest.approx(.1)
    assert storage.deletes == 1


def test_qwen3_filetrans_ignores_hotwords_and_diarization_it_does_not_support(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    from twobyteasr.qwen31_asr import filetrans_hints_for_model
    hints = filetrans_hints_for_model(QWEN3_FILETRANS, ['S0pp', 'BerLIN'], language='auto')
    assert 'vocabulary' not in hints and 'filetrans_language' not in hints
    assert hints['hint_counts']['unsupported_by_model'] == 2
    sent = {}

    class Client:
        @staticmethod
        def post(url, **kw):
            sent.update(kw['json'])
            return Response({'output': {'task_id': 't1', 'task_status': 'PENDING'}})

        @staticmethod
        def get(url, **kw):
            raise OSError('pause')

    endpoint = qwen3_endpoint(vocabulary={'S0pp': 2}, filetrans_context=[{'role': 'user', 'content': []}])
    with pytest.raises(OSError):
        filetrans(np.zeros(16000), endpoint, tmp_path, Storage(), client=Client)
    assert 'vocabulary' not in sent['parameters'] and 'diarization_enabled' not in sent['parameters']
    assert 'context' not in sent['input']


def test_qwen_audio_31_keeps_file_urls_and_diarization(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    sent = {}

    class Client:
        @staticmethod
        def post(url, **kw):
            sent.update(kw['json'])
            return Response({'output': {'task_id': 't1', 'task_status': 'PENDING'}})

        @staticmethod
        def get(url, **kw):
            raise OSError('pause')

    endpoint = dict(qwen3_endpoint(), model=FILETRANS)
    with pytest.raises(OSError):
        filetrans(np.zeros(16000), endpoint, tmp_path, Storage(), client=Client)
    assert sent['input'] == {'file_urls': ['https://bucket.example.com/audio.wav?secret=signature']}
    assert sent['parameters'] == {'channel_id': [0], 'diarization_enabled': True}


def test_filetrans_unknown_task_is_reported_not_resubmitted(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    posts = []

    class Client:
        @staticmethod
        def post(url, **kw):
            posts.append(url)
            return Response({'output': {'task_id': 't1', 'task_status': 'PENDING'}})

        @staticmethod
        def get(url, **kw):
            return Response({'output': {'task_status': 'UNKNOWN'}})

    with pytest.raises(ASRProtocolError) as error:
        filetrans(np.zeros(16000), qwen3_endpoint(), tmp_path, Storage(), client=Client)
    assert error.value.category == 'remote_unknown'
    with pytest.raises(ASRProtocolError):
        filetrans(np.zeros(16000), qwen3_endpoint(), tmp_path, Storage(), client=Client)
    assert len(posts) == 1


def test_endpoint_validation_accepts_both_bailian_models_and_rejects_chat_path():
    from twobyteasr.llm_config import validate_qwen_asr_endpoint
    validate_qwen_asr_endpoint(qwen3_endpoint())
    validate_qwen_asr_endpoint(dict(qwen3_endpoint(), model=FILETRANS))
    with pytest.raises(RuntimeError, match='compatible-mode'):
        validate_qwen_asr_endpoint(dict(qwen3_endpoint(), url='https://llm-abc.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'))
    with pytest.raises(RuntimeError, match='聊天接口|录音文件识别'):
        validate_qwen_asr_endpoint(dict(qwen3_endpoint(), model='qwen3-asr-flash'))
    validate_qwen_asr_endpoint(dict(model='moss-transcribe-diarize-pro', provider='mosi_moss_pro',
                                    protocol='mosi_transcriptions', url='https://api.mosi.cn/v1', api_key='k'))
    with pytest.raises(RuntimeError, match='MOSI'):
        validate_qwen_asr_endpoint(dict(model='moss-transcribe-diarize-pro', protocol='openai_transcription',
                                        url='https://api.mosi.cn/v1', api_key='k'))


# --- Bailian address parsing ------------------------------------------------

@pytest.mark.parametrize('pasted', [
    'llm-abc123.cn-beijing.maas.aliyuncs.com',
    'https://llm-abc123.cn-beijing.maas.aliyuncs.com',
    'https://llm-abc123.cn-beijing.maas.aliyuncs.com/api/v1',
    'https://llm-abc123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
    'https://llm-abc123.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription',
    ' "https://LLM-ABC123.cn-beijing.maas.aliyuncs.com/" ',
])
def test_dashscope_workspace_host_any_pasted_form(pasted):
    from twobyteasr.api_endpoints import parse_dashscope_address
    address = parse_dashscope_address(pasted)
    assert address.host == 'llm-abc123.cn-beijing.maas.aliyuncs.com'
    assert address.region == 'cn-beijing' and address.workspace_id == 'llm-abc123' and not address.legacy
    assert address.filetrans_url == 'https://llm-abc123.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription'
    assert address.task_url('t') == 'https://llm-abc123.cn-beijing.maas.aliyuncs.com/api/v1/tasks/t'
    assert '/v1/v1' not in address.filetrans_url and address.compatible_base_url.endswith('/compatible-mode/v1')


def test_dashscope_legacy_region_workspace_id_and_wrong_hosts():
    from twobyteasr.api_endpoints import EndpointInputError, parse_dashscope_address
    legacy = parse_dashscope_address('https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription')
    assert legacy.legacy and legacy.region == 'cn-beijing' and legacy.notes()
    singapore = parse_dashscope_address('dashscope-intl.aliyuncs.com')
    assert singapore.region == 'ap-southeast-1' and any('地域' in note for note in singapore.notes())
    built = parse_dashscope_address('llm-xyz', region='ap-southeast-1')
    assert built.host == 'llm-xyz.ap-southeast-1.maas.aliyuncs.com'
    with pytest.raises(EndpointInputError, match='地域'):
        parse_dashscope_address('llm-xyz')
    with pytest.raises(EndpointInputError, match='OSS'):
        parse_dashscope_address('https://2byte.oss-cn-hangzhou.aliyuncs.com')
    with pytest.raises(EndpointInputError, match='控制台'):
        parse_dashscope_address('https://bailian.console.aliyun.com/')


# --- MOSS-Transcribe-Diarize Pro cloud ---------------------------------------

def mosi_endpoint(**extra):
    return {**dict(model='moss-transcribe-diarize-pro', provider='mosi_moss_pro', protocol='mosi_transcriptions',
                   url='https://api.mosi.cn/v1', api_key='sk-test', speaker_source='native'), **extra}


@pytest.mark.parametrize('pasted', ['api.mosi.cn', 'https://api.mosi.cn', 'https://api.mosi.cn/v1/',
                                    'https://api.mosi.cn/v1/audio/transcriptions', 'https://api.mosi.cn/v1/v1',
                                    'https://platform.mosi.cn/app/api-keys/'])
def test_mosi_base_url_never_doubles_v1(pasted):
    from twobyteasr.mosi_asr import normalize_api_base, transcriptions_url
    assert normalize_api_base(pasted) == 'https://api.mosi.cn/v1'
    assert transcriptions_url(pasted) == 'https://api.mosi.cn/v1/audio/transcriptions'


def test_mosi_keyterms_keep_spelling_and_official_limits():
    from twobyteasr.mosi_asr import keyterm_hints
    terms = ['MOSS', 'SGLang', 'S0pp', 'MOSS', 'x' * 31] + [f'词{i}' for i in range(30)]
    hints = keyterm_hints(terms)
    assert hints['mosi_keyterms'][:3] == ['MOSS', 'SGLang', 'S0pp']
    assert len(hints['mosi_keyterms']) == 20 and all(len(t) <= 30 for t in hints['mosi_keyterms'])
    reasons = {row['reason'] for row in hints['mosi_keyterms_dropped']}
    assert reasons == {'longer_than_30_characters', 'over_20_terms'}


class MosiClient:
    """Fake MOSI HTTP client: records submissions, scripted poll statuses."""

    def __init__(self, statuses=('PROCESSING', 'SUCCESS'), segments=None, submit_status=200, submit_error=None):
        self.posts = []
        self.gets = 0
        self.statuses = list(statuses)
        self.segments = segments if segments is not None else [
            {'speaker': 'S01', 'text': '你好。', 'start': 0.2, 'end': 1.1},
            {'speaker': 'S02', 'text': '欢迎。', 'start': 1.3, 'end': 1.9}]
        self.submit_status = submit_status
        self.submit_error = submit_error

    def post(self, url, **kw):
        self.posts.append((url, kw))
        if self.submit_error:
            raise self.submit_error
        if self.submit_status != 200:
            return Response({'error': {'code': 'insufficient_credits', 'message': 'no credits'}}, self.submit_status)
        return Response({'id': 'task-1', 'task_id': 'task-1', 'object': 'audio.transcription',
                         'status': 'PENDING', 'retry_after': 2})

    def get(self, url, **kw):
        self.gets += 1
        assert url == 'https://api.mosi.cn/v1/audio/tasks/task-1'
        assert kw['headers']['Authorization'] == 'Bearer sk-test'
        status = self.statuses.pop(0) if self.statuses else 'SUCCESS'
        body = {'id': 'task-1', 'object': 'audio.transcription', 'status': status}
        if status == 'SUCCESS':
            body.update(text='你好。欢迎。', segments=self.segments)
        if status == 'FAILED':
            body['error'] = {}
        return Response(body)


def test_mosi_async_upload_poll_and_segment_rows(tmp_path):
    from twobyteasr.mosi_asr import keyterm_hints, transcribe
    client = MosiClient()
    endpoint = mosi_endpoint(**keyterm_hints(['MOSS', 'S0pp']))
    rows = transcribe(np.zeros(32000, dtype=np.float32), endpoint, tmp_path, client=client, sleep=lambda *_: None)
    url, kw = client.posts[0]
    assert url == 'https://api.mosi.cn/v1/audio/transcriptions'
    assert kw['data']['model'] == 'moss-transcribe-diarize-pro' and kw['data']['diarize'] == 'true'
    assert kw['data']['async'] == 'true' and json.loads(kw['data']['keyterms']) == ['MOSS', 'S0pp']
    assert kw['files']['file'][0] == 'audio.wav' and kw['headers']['Authorization'] == 'Bearer sk-test'
    assert [row['speaker'] for row in rows] == ['API_S01', 'API_S02']
    assert all(row['timestamp_source'] == 'mosi_native_sentence' and row['timing_precision'] == 'segment'
               for row in rows)
    assert 'tokens' not in rows[0]
    assert rows[0]['start'] == pytest.approx(.2) and rows[1]['end'] == pytest.approx(1.9)
    disk = ''.join(p.read_text('utf8') for p in tmp_path.rglob('*.json'))
    assert 'sk-test' not in disk and 'Bearer' not in disk
    # A finished result is reused without a second upload.
    again = transcribe(np.zeros(32000, dtype=np.float32), endpoint, tmp_path, client=client, sleep=lambda *_: None)
    assert len(client.posts) == 1 and [r['text'] for r in again] == [r['text'] for r in rows]


def test_mosi_lost_upload_response_is_never_resubmitted(tmp_path):
    import requests
    from twobyteasr.mosi_asr import transcribe
    client = MosiClient(submit_error=requests.exceptions.ConnectionError('reset'))
    for _ in range(2):
        with pytest.raises(ASRProtocolError) as error:
            transcribe(np.zeros(16000, dtype=np.float32), mosi_endpoint(), tmp_path, client=client)
        assert error.value.category == 'submission_uncertain'
    assert len(client.posts) == 1


def test_mosi_insufficient_credits_is_a_definitive_rejection(tmp_path):
    from twobyteasr.mosi_asr import transcribe
    client = MosiClient(submit_status=402)
    with pytest.raises(ASRProtocolError, match='积分不足') as error:
        transcribe(np.zeros(16000, dtype=np.float32), mosi_endpoint(), tmp_path, client=client)
    assert error.value.category == 'insufficient_credits'
    client.submit_status = 200
    rows = transcribe(np.zeros(16000, dtype=np.float32), mosi_endpoint(), tmp_path, client=client,
                      sleep=lambda *_: None)
    assert rows and len(client.posts) == 2


def test_mosi_poll_failure_resumes_same_task(tmp_path):
    from twobyteasr.mosi_asr import transcribe

    class Flaky(MosiClient):
        def get(self, url, **kw):
            if self.gets == 0:
                self.gets += 1
                raise OSError('network down')
            return super().get(url, **kw)

    client = Flaky()
    with pytest.raises(OSError):
        transcribe(np.zeros(16000, dtype=np.float32), mosi_endpoint(), tmp_path, client=client, sleep=lambda *_: None)
    rows = transcribe(np.zeros(16000, dtype=np.float32), mosi_endpoint(), tmp_path, client=client,
                      sleep=lambda *_: None)
    assert rows and len(client.posts) == 1


def test_mosi_failed_task_and_local_cancel_are_reported_honestly(tmp_path):
    from twobyteasr.mosi_asr import transcribe
    with pytest.raises(ASRProtocolError, match='积分账单'):
        transcribe(np.zeros(16000, dtype=np.float32), mosi_endpoint(), tmp_path / 'a',
                   client=MosiClient(statuses=['FAILED']), sleep=lambda *_: None)
    progress = []
    cancelled = [False]

    def check():
        if cancelled[0]:
            raise RuntimeError('cancelled')

    def sleep(_):
        cancelled[0] = True

    with pytest.raises(RuntimeError):
        transcribe(np.zeros(16000, dtype=np.float32), mosi_endpoint(), tmp_path / 'b',
                   client=MosiClient(statuses=['PROCESSING'] * 5), check=check, sleep=sleep,
                   progress=lambda *a: progress.append(a[0]))
    assert 'local_cancel_remote_continues' in progress
    state = json.loads(next((tmp_path / 'b').rglob('task.json')).read_text('utf8'))
    assert state['remote_cancel_supported'] is False and state['task_id'] == 'task-1'


def test_mosi_long_audio_split_offsets_once_and_speakers_stay_request_local(tmp_path, monkeypatch):
    from twobyteasr import mosi_asr
    monkeypatch.setattr(mosi_asr, 'MAX_AUDIO_SECONDS', 2)
    audio = np.zeros(16000 * 5, dtype=np.float32)
    ranges = mosi_asr.plan_ranges(audio, chunk_seconds=2)
    assert ranges[0][0] == 0 and ranges[-1][1] == len(audio)
    assert all(a[1] == b[0] for a, b in zip(ranges, ranges[1:]))
    monkeypatch.setattr(mosi_asr, 'plan_ranges', lambda a: ranges)

    class PerRequest(MosiClient):
        def get(self, url, **kw):
            return Response({'id': 'task-1', 'status': 'SUCCESS', 'text': '你好。',
                             'segments': [{'speaker': 'S01', 'text': '你好。', 'start': 0.5, 'end': 1.0}]})

    rows = mosi_asr.transcribe(audio, mosi_endpoint(), tmp_path, client=PerRequest(), sleep=lambda *_: None)
    assert len(rows) == len(ranges)
    assert rows[0]['speaker'] == 'R001_S01' and rows[1]['speaker'] == 'R002_S01'
    for row, (start, _end) in zip(rows, ranges):
        assert row['start'] == pytest.approx(start / 16000 + .5)
        assert row['speaker_evidence']['identity_confirmed'] is False


def test_mosi_key_check_reports_validity_and_model_access():
    from twobyteasr.mosi_asr import check_key

    class Client:
        def __init__(self, code, models):
            self.code, self.models = code, models

        def get(self, url, **kw):
            assert url == 'https://api.mosi.cn/v1/models'
            return Response({'data': [{'id': m} for m in self.models]} if self.code == 200 else
                            {'error': {'code': 'permission_error'}}, self.code)

    ok = check_key(mosi_endpoint(), client=Client(200, ['moss-tts-1.5-flash', 'moss-transcribe-diarize-pro']))
    assert ok['connection'] and ok['key_valid'] and ok['model_available']
    missing = check_key(mosi_endpoint(), client=Client(200, ['moss-tts-1.5-flash']))
    assert missing['key_valid'] and missing['model_available'] is False
    bad = check_key(mosi_endpoint(), client=Client(403, []))
    assert bad['key_valid'] is False and 'API Key' in bad['message']


# --- Runtime and CUDA gates ------------------------------------------------------

def cloud_only(**models):
    return {'models': {'primary_asr_backend': 'api', 'firered_asr_backend': 'off', 'qwen_asr_backend': 'off', **models}}


def test_cloud_only_plan_requires_no_local_runtime():
    from twobyteasr.environment import required_environment_roles
    assert required_environment_roles(cloud_only()) == []
    assert required_environment_roles(cloud_only(qwen_asr_backend='api')) == []
    assert required_environment_roles(cloud_only(firered_asr_backend='qwen_aligner')) == ['main']
    assert required_environment_roles({'models': {'primary_asr_backend': 'moss'}}) == ['main', 'moss']


def test_cloud_only_never_starts_the_torch_probe(monkeypatch):
    from twobyteasr import hardware

    def boom():
        raise AssertionError('torch probe must not start for a cloud-only plan')

    monkeypatch.setattr(hardware, 'ready_torch_probe', boom)
    assert hardware.require_local_torch_runtime(cloud_only()) is None
    assert hardware.selected_cuda_components(cloud_only(firered_asr_backend='qwen_aligner')) == []


def test_cuda_error_names_the_selected_components(monkeypatch):
    from twobyteasr import hardware
    monkeypatch.setattr(hardware, 'ready_torch_probe', lambda: {})
    monkeypatch.setattr(hardware, 'detect_cuda_runtime', lambda probe=None: hardware.CudaRuntimeStatus(
        False, 'gpu_or_driver_missing', '未检测到可用的 NVIDIA CUDA GPU。', '请检查驱动。'))
    with pytest.raises(RuntimeError) as error:
        hardware.require_cuda_runtime(['FireRed 字级时间轴'])
    assert 'FireRed 字级时间轴' in str(error.value) and '云端识别' in str(error.value)


def test_cloud_worker_runs_with_the_app_itself(monkeypatch, tmp_path):
    from twobyteasr import cloud_api_worker
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\Apps\2ByteASR\2ByteASR.exe')
    assert cloud_api_worker.cloud_worker_command(tmp_path) == [r'C:\Apps\2ByteASR\2ByteASR.exe', '--asr-api-worker']
    monkeypatch.setattr(sys, 'frozen', False)
    (tmp_path / 'asr_api_worker.py').write_text('', encoding='utf-8')
    command = cloud_api_worker.cloud_worker_command(tmp_path)
    assert command[1:] == ['-u', str(tmp_path / 'asr_api_worker.py')]


def test_aligner_worker_falls_back_to_cpu_float32():
    import importlib
    worker = importlib.import_module('qwen_aligner_worker')

    class FakeCuda:
        def __init__(self, available):
            self.available = available

        def is_available(self):
            return self.available

        def is_bf16_supported(self):
            return True

    fake = SimpleNamespace(cuda=FakeCuda(False), float32='f32', bfloat16='bf16', float16='f16')
    assert worker.select_device(fake, 'auto') == ('cpu', 'f32')
    with pytest.raises(RuntimeError, match='CUDA'):
        worker.select_device(fake, 'cuda')
    fake.cuda = FakeCuda(True)
    assert worker.select_device(fake, 'auto') == ('cuda:0', 'bf16')
    assert worker.select_device(fake, 'cpu') == ('cpu', 'f32')


# --- Cloud transcript + local aligner -----------------------------------------------

def test_sentence_only_cloud_rows_use_own_aligner_tokens_or_are_marked_estimates():
    import subtitle_core as legacy
    import moss_firered_pipeline as pipeline
    from twobyteasr.forced_alignment import segment_alignment_key
    references = [
        {'start': 0.0, 'end': 2.0, 'text': '你好世界', 'speaker': 'API_S01', 'timestamp_source': 'mosi_native_sentence'},
        {'start': 1.5, 'end': 3.0, 'text': '再见', 'speaker': 'API_S02', 'timestamp_source': 'mosi_native_sentence'},
    ]
    key = segment_alignment_key('API_S01', 0.0, 2.0)
    tokens = [dict(text='你好', start=0.3, end=0.8, source='qwen-forced-aligner', alignment_key=key,
                   start_basis='model', end_basis='model', granularity='word'),
              dict(text='世界', start=0.9, end=1.6, source='qwen-forced-aligner', alignment_key=key,
                   start_basis='model', end_basis='model', granularity='word')]
    segments = pipeline.build_alternate_primary_segments(references, tokens, legacy, 'api')
    aligned, other = segments
    assert aligned.final_timing_owner == 'Qwen3-ForcedAligner on primary transcript'
    assert aligned.caption_arbitration['forced_alignment_window']['job'] == key
    assert aligned.words[0].start == pytest.approx(0.3) and aligned.words[-1].end == pytest.approx(1.6)
    # 2026-10-14: the aligner's two-character words stay whole as measured units.
    timing = aligned.caption_arbitration['word_timing']
    assert timing['basis'] == 'aligner_words' and [w['text'] for w in timing['measured_words']] == ['你好', '世界']
    # The overlapping second speaker never borrows the first row's aligner tokens.
    assert other.caption_arbitration['word_timing']['basis'] == 'uniform_display_estimate'
    assert other.final_timing_owner == 'API native sentence timestamps'


# --- End to end: real worker process against a loopback fake MOSI server -------------------

class _FakeMosi(BaseHTTPRequestHandler):
    tasks = {}

    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        assert self.headers['Authorization'] == 'Bearer sk-loopback'
        length = int(self.headers['Content-Length'])
        raw = self.rfile.read(length)
        message = BytesParser(policy=email_policy).parsebytes(
            b'Content-Type: ' + self.headers['Content-Type'].encode() + b'\r\n\r\n' + raw)
        fields = {part.get_param('name', header='content-disposition'): part.get_content()
                  for part in message.iter_parts()}
        audio = fields['file']
        assert isinstance(audio, bytes) and audio[:4] == b'RIFF'
        assert fields['model'] == 'moss-transcribe-diarize-pro' and fields['async'] == 'true'
        _FakeMosi.tasks['loop-1'] = len(audio)
        self._send(200, {'id': 'loop-1', 'task_id': 'loop-1', 'status': 'PENDING', 'retry_after': 2})

    def do_GET(self):
        assert self.path == '/v1/audio/tasks/loop-1'
        self._send(200, {'id': 'loop-1', 'status': 'SUCCESS', 'text': '一二三。四五。', 'segments': [
            {'speaker': 'S01', 'text': '一二三。', 'start': 0.1, 'end': 0.9},
            {'speaker': 'S02', 'text': '四五。', 'start': 1.0, 'end': 1.8}]})


def test_real_worker_process_reaches_cloud_without_model_runtime(monkeypatch, tmp_path):
    from twobyteasr import asr, asr_api_process
    from twobyteasr.runtime import RuntimeContext, activate_runtime_context
    server = ThreadingHTTPServer(('127.0.0.1', 0), _FakeMosi)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = mosi_endpoint(url=f'http://127.0.0.1:{server.server_port}/v1', api_key='sk-loopback')
        context = RuntimeContext(job_id='job-loop', asr_endpoint_snapshot=endpoint,
                                 asr_settings_snapshot={'models': {}}, speaker_source='native')
        monkeypatch.setattr(asr, 'build_qwen_asr_context', lambda *a: '')
        monkeypatch.setattr('twobyteasr.terminology.runtime_snapshot', lambda: SimpleNamespace(canonical_terms=[]))
        # No managed model runtime is registered or needed.
        monkeypatch.setattr('twobyteasr.runtime_registry.resolve_runtime_python',
                            lambda *a: (_ for _ in ()).throw(AssertionError('model runtime must not be used')))
        with activate_runtime_context(context):
            rows = asr_api_process.transcribe('fixture.wav', [dict(start=0, end=2, audio=(np.zeros(32000, np.float32), 16000))])
    finally:
        server.shutdown()
    assert [row['text'].rstrip('。') for row in rows] == ['一二三', '四五']
    assert [row['speaker'] for row in rows] == ['API_S01', 'API_S02']
    assert _FakeMosi.tasks['loop-1'] == 32000 * 2 + 44
