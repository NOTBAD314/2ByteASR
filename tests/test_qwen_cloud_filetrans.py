"""Qwen Cloud entry, the official temporary upload and explained provider errors (2026-10-13).

Network access goes only to fake clients. Covers: the getPolicy + signed form
upload exactly like the official QwenCloud CLI, ``oss://`` submission with the
resolve header, resume without resubmission, re-upload of an expiring object,
error codes mapped to their own causes, the upload-mode choice that keeps an
existing OSS setup, and the graded checks (format / connection / key / model).
"""
import json
import time

import numpy as np
import pytest

from twobyteasr.qwen31_asr import ASRProtocolError, FILETRANS


class Response:
    def __init__(self, data, code=200):
        self.data = data
        self.status_code = code
        self.text = json.dumps(data) if not isinstance(data, str) else data

    def json(self):
        if isinstance(self.data, str):
            raise ValueError('not json')
        return self.data


POLICY = {'request_id': 'r', 'data': {
    'policy': 'eyJleHBpcmF0aW9uIjoiMjAyNi0xMC0xNVQwMDowMDowMFoifQ==', 'signature': 'c2lnbmF0dXJl',
    'upload_dir': 'dashscope-instant/abc/2026-10-13/uuid', 'upload_host': 'https://dashscope-file-xyz.oss-ap-southeast-1.aliyuncs.com',
    'expire_in_seconds': 300, 'max_file_size_mb': 100, 'capacity_limit_mb': 999999,
    'oss_access_key_id': 'LTAI5tFAKEFAKEFAKE', 'x_oss_object_acl': 'private', 'x_oss_forbid_overwrite': 'true'}}

RESULT = {'file_url': 'oss://x', 'transcripts': [{'channel_id': 0, 'text': '你好世界。', 'sentences': [
    {'sentence_id': 1, 'begin_time': 100, 'end_time': 1500, 'speaker_id': 0, 'text': '你好世界。', 'words': [
        {'begin_time': 100, 'end_time': 600, 'text': '你好', 'punctuation': ''},
        {'begin_time': 600, 'end_time': 1500, 'text': '世界', 'punctuation': '。'}]}]}]}


def cloud_endpoint(**extra):
    endpoint = dict(model=FILETRANS, provider='qwen_cloud_filetrans', protocol='dashscope_filetrans',
                    url='https://maas.qwencloudapi.com/api/v1/services/audio/asr/transcription',
                    api_key='sk-ws-testkey000000000000', speaker_source='native')
    endpoint.update(extra)
    return endpoint


class CloudClient:
    """A fake Qwen Cloud: policy, OSS form upload, submit, query, result file."""

    def __init__(self, *, submit=None, statuses=('RUNNING', 'SUCCEEDED'), query_code=200):
        self.calls = []
        self.uploads = []
        self.submits = []
        self.statuses = list(statuses)
        self.submit = submit or Response({'output': {'task_id': 't-1', 'task_status': 'PENDING'}})
        self.query_code = query_code

    def get(self, url, **kw):
        self.calls.append(('GET', url, kw))
        if '/api/v1/uploads' in url:
            assert kw['params'] == {'action': 'getPolicy', 'model': FILETRANS}
            assert kw['headers']['Authorization'] == 'Bearer sk-ws-testkey000000000000'
            return Response(POLICY)
        if '/api/v1/tasks/t-1' in url:
            if self.query_code != 200:
                return Response({'code': 'Throttling', 'message': 'Requests throttling triggered.'}, self.query_code)
            status = self.statuses.pop(0) if self.statuses else 'SUCCEEDED'
            output = {'task_id': 't-1', 'task_status': status}
            if status == 'SUCCEEDED':
                output['results'] = [{'file_url': 'oss://x', 'subtask_status': 'SUCCEEDED',
                                      'transcription_url': 'https://dashscope-result-sg.oss-ap-southeast-1.aliyuncs.com/r.json?Expires=1&Signature=s'}]
            if status == 'FAILED':
                output['results'] = [{'file_url': 'oss://x', 'subtask_status': 'FAILED',
                                      'code': 'FILE_DOWNLOAD_FAILED', 'message': 'FILE_DOWNLOAD_FAILED'}]
            return Response({'output': output})
        if 'dashscope-result' in url:
            assert 'headers' not in kw or 'Authorization' not in (kw.get('headers') or {})
            return Response(RESULT)
        raise AssertionError(url)

    def post(self, url, **kw):
        self.calls.append(('POST', url, kw))
        if url.startswith('https://dashscope-file-'):
            body = kw['data'].read()
            assert kw['headers']['Content-Length'] == str(len(body))
            self.uploads.append(body)
            return Response('', 204)
        if url.endswith('/services/audio/asr/transcription'):
            self.submits.append(kw)
            return self.submit
        if url.endswith('/cancel'):
            return Response({'output': {'task_status': 'CANCELED'}})
        raise AssertionError(url)


def test_policy_and_form_upload_match_the_official_cli():
    from twobyteasr.dashscope_service import DashScopeTemporaryStorage
    client = CloudClient()
    progress = []
    storage = DashScopeTemporaryStorage(api_url=cloud_endpoint()['url'], api_key='sk-ws-testkey000000000000',
                                        model=FILETRANS, client=client)
    stored = storage.upload_audio(b'RIFF' + b'\0' * 2000, 'wav', progress=lambda a, b: progress.append((a, b)))
    assert stored.key.startswith('dashscope-instant/abc/2026-10-13/uuid/2byteasr-') and stored.key.endswith('.wav')
    assert storage.create_download_url(stored.key) == 'oss://' + stored.key
    body = client.uploads[0].decode('latin-1')
    names = [part.split('name="', 1)[1].split('"', 1)[0] for part in body.split('Content-Disposition: form-data; ')[1:]]
    # Same fields and order as src/services/oss-uploader.ts; the file is last.
    assert names == ['key', 'OSSAccessKeyId', 'policy', 'signature', 'success_action_status',
                     'x-oss-object-acl', 'x-oss-forbid-overwrite', 'file']
    assert 'LTAI5tFAKEFAKEFAKE' in body and stored.key in body
    # The local file name never reaches the provider.
    assert 'filename="2byteasr-' in body
    assert progress and progress[-1] == (2004, 2004)
    storage.delete_object(stored.key, strict=True)  # no-op: the provider removes it after 48 h


def test_token_plan_key_and_oversized_audio_are_refused_before_upload():
    from twobyteasr.dashscope_service import DashScopeTemporaryStorage, TemporaryUploadError
    with pytest.raises(TemporaryUploadError) as error:
        DashScopeTemporaryStorage(api_url=cloud_endpoint()['url'], api_key='sk-sp-plan', model=FILETRANS)
    assert error.value.category == 'token_plan_key'
    client = CloudClient()
    storage = DashScopeTemporaryStorage(api_url=cloud_endpoint()['url'], api_key='sk-ws-testkey000000000000',
                                        model=FILETRANS, client=client)
    with pytest.raises(TemporaryUploadError) as error:
        storage.upload_audio(b'\0' * (101 * 1024 * 1024), 'wav')
    assert error.value.category == 'file_access' and not client.uploads


def test_filetrans_submits_oss_url_with_resolve_header_and_parses_words(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    from twobyteasr.dashscope_service import DashScopeTemporaryStorage
    client = CloudClient()
    endpoint = cloud_endpoint()
    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=client)
    rows = filetrans(np.zeros(32000), endpoint, tmp_path, storage, client=client, sleep=lambda *_: None)
    submit = client.submits[0]
    assert submit['headers']['X-DashScope-OssResourceResolve'] == 'enable'
    assert submit['headers']['X-DashScope-Async'] == 'enable'
    url = submit['json']['input']['file_urls'][0]
    assert url.startswith('oss://dashscope-instant/abc/')
    assert submit['json']['parameters']['diarization_enabled'] is True
    assert rows and rows[0]['timing_precision'] == 'word'
    assert [t['text'] for t in rows[0]['tokens']] == ['你好', '世界。']
    state = json.loads(next(tmp_path.rglob('task.json')).read_text('utf8'))
    assert state['storage_kind'] == 'dashscope_temporary' and 'oss://' not in json.dumps(state)


def test_disconnect_after_submit_resumes_the_same_task(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    from twobyteasr.dashscope_service import DashScopeTemporaryStorage
    endpoint = cloud_endpoint()
    first = CloudClient(query_code=503)
    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=first)
    with pytest.raises(ASRProtocolError) as error:
        filetrans(np.zeros(32000), endpoint, tmp_path, storage, client=first, sleep=lambda *_: None)
    assert error.value.category == 'poll_failed' and '未重新提交' in str(error.value)
    second = CloudClient()
    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=second)
    rows = filetrans(np.zeros(32000), endpoint, tmp_path, storage, client=second, sleep=lambda *_: None)
    assert rows and not second.submits and not second.uploads  # queried t-1 only; no new charge


def test_unsubmitted_upload_close_to_expiry_is_uploaded_again(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    from twobyteasr.dashscope_service import DashScopeTemporaryStorage
    endpoint = cloud_endpoint()
    refused = CloudClient(submit=Response({'code': 'Arrearage', 'message': 'Access denied, make sure your account is in good standing.'}, 400))
    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=refused)
    with pytest.raises(ASRProtocolError) as error:
        filetrans(np.zeros(32000), endpoint, tmp_path, storage, client=refused, sleep=lambda *_: None)
    assert error.value.problem.category == 'balance' and '余额' in str(error.value)
    assert len(refused.uploads) == 1
    path = next(tmp_path.rglob('task.json'))
    state = json.loads(path.read_text('utf8'))
    state['created_at'] = time.time() - 45 * 3600
    path.write_text(json.dumps(state), 'utf8')
    retry = CloudClient()
    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=retry)
    assert filetrans(np.zeros(32000), endpoint, tmp_path, storage, client=retry, sleep=lambda *_: None)
    assert len(retry.uploads) == 1 and len(retry.submits) == 1


def test_remote_failure_is_explained_and_local_cancel_does_not_claim_remote_cancel(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    from twobyteasr.dashscope_service import DashScopeTemporaryStorage
    endpoint = cloud_endpoint()
    client = CloudClient(statuses=('FAILED',))
    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=client)
    with pytest.raises(ASRProtocolError) as error:
        filetrans(np.zeros(32000), endpoint, tmp_path / 'a', storage, client=client, sleep=lambda *_: None)
    assert error.value.problem.category == 'file_access'
    running = CloudClient(statuses=['RUNNING'] * 50)
    calls = {'n': 0}

    def check():
        calls['n'] += 1
        if calls['n'] > 6:
            raise RuntimeError('本地识别已取消')

    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=running)
    with pytest.raises(RuntimeError):
        filetrans(np.zeros(32000), endpoint, tmp_path / 'b', storage, client=running, check=check, sleep=lambda *_: None)
    state = json.loads(next((tmp_path / 'b').rglob('task.json')).read_text('utf8'))
    assert state['local_cancel_requested'] is True and state['status'] == 'RUNNING'
    assert not state.get('remote_cancel_confirmed')
    assert not any(url.endswith('/cancel') for _m, url, _kw in running.calls)  # RUNNING cannot be cancelled


@pytest.mark.parametrize('status,body,category', [
    (401, {'code': 'InvalidApiKey', 'message': 'Invalid API-key provided.'}, 'key'),
    (400, {'code': 'Arrearage', 'message': 'Access denied, make sure your account is in good standing.'}, 'balance'),
    (403, {'code': 'AccessDenied.Unpurchased', 'message': 'Access to model denied. Make sure you are eligible for using the model.'}, 'billing_info'),
    (403, {'code': 'AllocationQuota.FreeTierOnly', 'message': 'The free tier of the model has been exhausted.'}, 'free_tier_only'),
    (403, {'code': 'Model.AccessDenied', 'message': 'Model access denied.'}, 'permission'),
    (404, {'code': 'ModelNotFound', 'message': 'Model can not be found.'}, 'model'),
    (400, {'code': 'InvalidParameter', 'message': 'The product is not activated, please confirm that you have activated products and try again after activation.'}, 'not_activated'),
    (429, {'code': 'Throttling.RateQuota', 'message': 'Requests rate limit exceeded'}, 'rate_limit'),
    (502, {}, 'server'),
])
def test_each_documented_error_gets_its_own_explanation(status, body, category):
    from twobyteasr.dashscope_service import explain
    problem = explain(status, body, model=FILETRANS, host='maas.qwencloudapi.com')
    assert problem.category == category and problem.message and problem.action
    # Only a refused key is described as a key problem.
    assert ('不认这把 API Key' in problem.message) == (category == 'key')


def test_network_errors_are_not_called_key_errors():
    import requests
    from twobyteasr.dashscope_service import explain
    problem = explain(None, host='maas.qwencloudapi.com', exception=requests.exceptions.ConnectTimeout('timed out'))
    assert problem.category == 'network' and '等待超时' in problem.message


def test_upload_mode_keeps_an_existing_oss_setup():
    # ADR 0112 (2026-10-14): own OSS is the regular route; the temporary upload
    # (officially not for production) is used only when explicitly chosen.
    from twobyteasr.api_setup_catalog import resolve_upload_mode
    assert resolve_upload_mode({'filetrans_upload': 'auto', 'oss_bucket': 'mine'}, 'qwen31_filetrans',
                               has_oss_credentials=True) == 'own_oss'
    assert resolve_upload_mode({'filetrans_upload': 'auto', 'oss_bucket': ''}, 'qwen31_filetrans',
                               has_oss_credentials=True) == 'missing'
    assert resolve_upload_mode({'filetrans_upload': 'auto', 'oss_bucket': 'mine'}, 'qwen31_filetrans',
                               has_oss_credentials=False) == 'missing'
    assert resolve_upload_mode({'filetrans_upload': 'provider_temporary', 'oss_bucket': 'mine'}, 'qwen31_filetrans',
                               has_oss_credentials=True) == 'provider_temporary'
    assert resolve_upload_mode({'filetrans_upload': 'own_oss'}, 'qwen_cloud_filetrans') == 'own_oss'


def test_worker_picks_storage_by_upload_mode():
    from twobyteasr.cloud_api_worker import filetrans_storage
    from twobyteasr.dashscope_service import DashScopeTemporaryStorage
    from twobyteasr.temp_audio_storage import OssTemporaryStorage
    endpoint = cloud_endpoint()
    request = {'settings': {'models': {'filetrans_upload': 'auto', 'oss_bucket': ''}}}
    with pytest.raises(Exception, match='MOSS Pro'):
        filetrans_storage(request, endpoint)  # nothing chosen: stop, never pick the trial upload
    trial = {'settings': {'models': {'filetrans_upload': 'provider_temporary', 'oss_bucket': ''}}}
    assert isinstance(filetrans_storage(trial, endpoint), DashScopeTemporaryStorage)
    bailian = dict(endpoint, provider='qwen31_filetrans',
                   url='https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription')
    own = {'settings': {'models': {'filetrans_upload': 'auto', 'oss_bucket': 'mine', 'oss_region': 'cn-hangzhou',
                                   'oss_endpoint': 'https://oss-cn-hangzhou.aliyuncs.com'}},
           'storage_credentials': ('LTAIid', 'secret')}
    assert isinstance(filetrans_storage(own, bailian), OssTemporaryStorage)
    missing = {'settings': {'models': {'filetrans_upload': 'own_oss', 'oss_bucket': ''}}}
    with pytest.raises(Exception, match='OSS 还没设置完整'):
        filetrans_storage(missing, bailian)


def test_qwen_cloud_address_is_recognised_and_kept_apart_from_bailian():
    from twobyteasr.api_endpoints import describe_dashscope, parse_dashscope_address
    address = parse_dashscope_address('https://maas.qwencloudapi.com')
    assert address.qwen_cloud and address.region == 'ap-southeast-1' and not address.legacy
    assert address.filetrans_url == 'https://maas.qwencloudapi.com/api/v1/services/audio/asr/transcription'
    info = describe_dashscope('maas.qwencloudapi.com')
    assert info['website'] == 'https://home.qwencloud.com/'
    assert any('不能在这里使用' in note for note in info['notes'])
    assert not parse_dashscope_address('dashscope.aliyuncs.com').qwen_cloud


def test_format_check_runs_locally_and_catches_common_paste_mistakes():
    from twobyteasr.cloud_api_test import FAIL, PASS, format_check
    assert format_check(cloud_endpoint()).status('format') == PASS
    assert format_check(cloud_endpoint(api_key='')).status('format') == FAIL
    spaced = format_check(cloud_endpoint(api_key='sk-ws-abc def'))
    assert spaced.status('format') == FAIL and '空格' in spaced.checks[0].detail
    plan = format_check(cloud_endpoint(api_key='sk-sp-abcdef'))
    assert plan.status('format') == FAIL and 'Token Plan' in plan.checks[0].detail
    oss = format_check(cloud_endpoint(), {'filetrans_upload': 'own_oss', 'oss_bucket': ''})
    assert oss.status('format') == FAIL and 'OSS Bucket' in oss.checks[0].detail


def test_qwen_cloud_free_checks_use_compatible_model_list_and_never_claim_more():
    from twobyteasr.cloud_api_test import PASS, UNKNOWN, FAIL, free_checks, temporary_upload_check

    class Client:
        @staticmethod
        def get(url, **kw):
            assert url == 'https://maas.qwencloudapi.com/compatible-mode/v1/models'
            return Response({'data': [{'id': 'qwen3.8-max'}]})

    report = free_checks(cloud_endpoint(), client=Client)
    assert [report.status(level) for level in ('format', 'connection', 'key', 'model')] == [PASS, PASS, PASS, UNKNOWN]
    assert report.status('recognition') == 'skip'

    class Unpurchased:
        @staticmethod
        def get(url, **kw):
            return Response({'code': 'AccessDenied.Unpurchased', 'message': 'Access to model denied.'}, 403)

    report = free_checks(cloud_endpoint(), client=Unpurchased)
    assert report.status('key') == PASS and report.status('model') == FAIL
    assert '付款信息' in next(c.detail for c in report.checks if c.level == 'model')

    class Bailian404:
        @staticmethod
        def get(url, **kw):
            if '/api/v1/models' in url:
                return Response({'code': 'InvalidApiKey', 'message': 'Invalid API-key provided.'}, 401)
            raise AssertionError(url)

    bailian = cloud_endpoint(provider='qwen31_filetrans', api_key='sk-other',
                             url='https://llm-abc.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription')
    report = free_checks(bailian, client=Bailian404)
    assert report.status('key') == FAIL and '不能互换' in next(c.detail for c in report.checks if c.level == 'key')


def test_failed_worker_reports_the_explained_cause_first():
    from twobyteasr.cloud_api_test import failure_detail
    from twobyteasr.cloud_api_worker import ERROR_MARKER, failure_from_text
    stderr = ERROR_MARKER + json.dumps({'category': 'balance', 'message': '账户欠费或余额不足，服务商拒绝了请求。',
                                        'action': '请到控制台的账单页面充值。', 'link': '', 'code': 'Arrearage'},
                                       ensure_ascii=False) + '\nTraceback ...'
    problem = failure_from_text(stderr)
    assert problem['category'] == 'balance'
    error = RuntimeError('PRIMARY_API worker failed')
    error.problem = problem
    assert failure_detail(error).startswith('账户欠费')
    plain = RuntimeError('PRIMARY_API worker failed (exit 1):\nstdout:\n[2BYTEASR_API] progress\nstderr:\nreal cause sk-ws-abcdefghijklmnop')
    detail = failure_detail(plain)
    assert detail.startswith('real cause') and 'sk-ws-abcdefghijklmnop' not in detail


def test_retry_page_finds_the_resubmit_request_in_a_one_line_failure():
    """2026-10-15: a failed media result stores its error with whitespace
    collapsed (service._exception_message); the completion page then never
    asked to resubmit and every "retry failed items" was refused again."""
    from twobyteasr.cloud_api_worker import ERROR_MARKER, failure_from_text
    from twobyteasr.service import _exception_message
    marker = ERROR_MARKER + json.dumps({'category': 'resubmit_needed', 'message': '上次提交时连线中断。',
                                        'action': '确认后重新提交。', 'link': '', 'code': 'submission_uncertain',
                                        'resubmit': True}, ensure_ascii=False)
    error = RuntimeError('上次提交时连线中断。 确认后重新提交。\n\nPRIMARY_API worker failed (exit 1):\nstdout:\n\n'
                         'stderr:\n' + marker + '\n上次上传是否被 MOSI 受理无法确认。\n')
    stored = _exception_message(error, '处理失败')
    assert '\n' not in stored
    problem = failure_from_text(stored)
    assert problem['resubmit'] is True and problem['code'] == 'submission_uncertain'
    assert failure_from_text('PRIMARY_API worker failed: plain error') is None
    assert failure_from_text(ERROR_MARKER + '{broken') is None


def test_redaction_covers_groq_and_alibaba_access_keys():
    from twobyteasr.provider_diagnostics import redact_diagnostics
    text = redact_diagnostics('gsk_abcdefghijklmnopqrstuv LTAI5tABCDEFGHIJKLMN https://b.oss.aliyuncs.com/a?OSSAccessKeyId=LTAIx&Signature=abc')
    assert 'gsk_abcdefghijklmnopqrstuv' not in text and 'LTAI5tABCDEFGHIJKLMN' not in text and 'Signature=abc' not in text


def test_catalog_lists_one_key_route_first_and_qwen_cloud_with_official_links():
    from twobyteasr.api_setup_catalog import ASR_GUIDES, guide_for
    from twobyteasr.ui import ASR_API_PRESETS
    guide = guide_for('qwen_cloud_filetrans')
    # ADR 0112: MOSS Pro (one key, local file upload) first, then Qwen Cloud.
    assert ASR_GUIDES[0] is guide_for('mosi_moss_pro') and ASR_GUIDES[1] is guide
    always = [f.key for f in guide.fields if not f.advanced and not f.show_when]
    assert always == ['api_key', 'filetrans_upload']
    assert all(f.show_when == ('filetrans_upload', 'own_oss') for f in guide.fields if f.key.startswith('oss_'))
    urls = [link.url for link in guide.links]
    assert 'https://home.qwencloud.com/api-keys' in urls
    assert all(url.startswith('https://') for url in urls)
    assert 'qwen.ai' in guide.account_note and '不能互换' in guide.account_note
    preset = ASR_API_PRESETS['qwen_cloud_filetrans']
    assert preset['model'] == FILETRANS and preset['protocol'] == 'dashscope_filetrans'
    assert preset['url'] == 'https://maas.qwencloudapi.com/api/v1/services/audio/asr/transcription'
    assert guide.guide_text().startswith('# 申请与设置 Qwen Cloud')
    bailian = guide_for('qwen31_filetrans')
    upload = next(f for f in bailian.fields if f.key == 'filetrans_upload')
    assert upload.prefilled == 'own_oss' and upload.choices[0][0] == 'own_oss'
    assert '仅供试用' in dict(upload.choices)['provider_temporary']
    assert all(f.show_when == ('filetrans_upload', 'own_oss') for f in bailian.fields if f.key.startswith('oss_'))


def test_vanished_or_uncertain_tasks_are_resubmitted_only_after_confirmation(tmp_path):
    from twobyteasr.cloud_asr_jobs import filetrans
    from twobyteasr.dashscope_service import DashScopeTemporaryStorage
    endpoint = cloud_endpoint()
    gone = CloudClient(statuses=['UNKNOWN'])
    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=gone)
    with pytest.raises(ASRProtocolError) as error:
        filetrans(np.zeros(32000), endpoint, tmp_path, storage, client=gone, sleep=lambda *_: None)
    assert error.value.category == 'remote_unknown'
    again = CloudClient(statuses=['UNKNOWN'])
    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=again)
    with pytest.raises(ASRProtocolError):
        filetrans(np.zeros(32000), endpoint, tmp_path, storage, client=again, sleep=lambda *_: None)
    assert not again.submits  # without confirmation: query only, never a second charge
    confirmed = CloudClient()
    storage = DashScopeTemporaryStorage(api_url=endpoint['url'], api_key=endpoint['api_key'], model=FILETRANS, client=confirmed)
    assert filetrans(np.zeros(32000), endpoint, tmp_path, storage, client=confirmed, sleep=lambda *_: None,
                     restart_terminal=True)
    assert len(confirmed.submits) == 1
    assert list(tmp_path.rglob('previous-task-*.json'))  # the old task record is kept


def test_worker_marks_saved_remote_states_as_needing_confirmation(monkeypatch, capsys):
    import io
    from twobyteasr import cloud_api_worker
    monkeypatch.setattr(cloud_api_worker, '_ensure_stdio', lambda: None)
    monkeypatch.setattr(cloud_api_worker.sys, 'stdin', io.StringIO('{}'))

    def fail(_request):
        raise ASRProtocolError('上次提交是否受理未知', 'submission_uncertain')

    monkeypatch.setattr(cloud_api_worker, 'run', fail)
    assert cloud_api_worker.main() == 1
    problem = cloud_api_worker.failure_from_text(capsys.readouterr().err)
    assert problem['resubmit'] is True and problem['category'] == 'resubmit_needed'
    assert '可能再次计费' in problem['action']


def test_temporary_upload_body_is_sent_with_a_length_not_chunked():
    """2026-10-14 real upload: requests sent the form chunked *and* with
    Content-Length; Alibaba OSS answered 400 BadRequest. The body must report
    its position so requests uses Content-Length only."""
    import requests
    from twobyteasr.dashscope_service import _MultipartBody
    body = _MultipartBody([('key', 'dir/a.wav'), ('OSSAccessKeyId', 'id')], 'a.wav', b'RIFF' + b'\0' * 64)
    prepared = requests.Request('POST', 'https://example.oss-cn-beijing.aliyuncs.com', data=body,
                                headers={'Content-Type': body.content_type}).prepare()
    assert prepared.headers.get('Content-Length') == str(len(body))
    assert 'Transfer-Encoding' not in prepared.headers
