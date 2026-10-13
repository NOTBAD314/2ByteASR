"""Qwen Cloud / 百炼 shared pieces: fixed addresses, the official temporary
upload, and plain-language explanations of service errors (2026-10-13).

Qwen Cloud (https://www.qwencloud.com, docs https://docs.qwencloud.com) is the
official international Qwen API platform. Its pay-as-you-go keys (``sk-ws-``,
older ``sk-``) call ``https://maas.qwencloudapi.com/api/v1`` (Singapore); the
official QwenCloud CLI uses the same keys on ``dashscope-intl.aliyuncs.com``.
Token Plan keys (``sk-sp-``) only work on the Token Plan gateway with the
OpenAI/Anthropic chat protocols and cannot upload local files, so they cannot
run 录音文件识别. 阿里云百炼（中国站）keys belong to their own region and
workspace host and are not interchangeable with Qwen Cloud keys.

The temporary upload is the documented ``oss://`` route of the DashScope REST
API (``GET /api/v1/uploads?action=getPolicy&model=<id>``, then a signed form
POST to the returned OSS host). Objects expire after 48 hours. The official
docs advise against it for high-concurrency production systems (100 QPS cap,
48 h validity); a desktop app uploads one file per task, and the official
QwenCloud CLI uses exactly this route for local files. Requests that reference
an ``oss://`` URL must send ``X-DashScope-OssResourceResolve: enable``.

Sources, checked 2026-10-13:
https://docs.qwencloud.com/developer-guides/speech/speech-to-text-models ,
https://docs.qwencloud.com/api-reference/speech-recognition/fun-asr-recording/restful-api ,
https://docs.qwencloud.com/api-reference/preparation/api-key ,
https://docs.qwencloud.com/api-reference/preparation/error-messages ,
https://github.com/QwenCloud/qwencloud-cli/blob/main/src/services/oss-uploader.ts (Apache-2.0).
"""
from __future__ import annotations

import io
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

QWEN_CLOUD_HOST = 'maas.qwencloudapi.com'
QWEN_CLOUD_INTL_HOST = 'dashscope-intl.aliyuncs.com'
QWEN_CLOUD_BASE_URL = f'https://{QWEN_CLOUD_HOST}/api/v1'
QWEN_CLOUD_FILETRANS_URL = QWEN_CLOUD_BASE_URL + '/services/audio/asr/transcription'
QWEN_CLOUD_CONSOLE = 'https://home.qwencloud.com/'
QWEN_CLOUD_API_KEYS = 'https://home.qwencloud.com/api-keys'
QWEN_CLOUD_BILLING = 'https://home.qwencloud.com/billing/overview'
QWEN_CLOUD_FREE_TIER = 'https://home.qwencloud.com/benefits'
QWEN_CLOUD_WORKSPACES = 'https://home.qwencloud.com/settings/workspaces'
QWEN_CLOUD_HOSTS = frozenset({QWEN_CLOUD_HOST, QWEN_CLOUD_INTL_HOST})

UPLOAD_POLICY_PATH = '/api/v1/uploads'
TEMPORARY_OBJECT_HOURS = 48
# Re-upload instead of submitting an object this close to its expiry.
TEMPORARY_OBJECT_REUSE_SECONDS = 40 * 3600
OSS_RESOLVE_HEADER = {'X-DashScope-OssResourceResolve': 'enable'}


def is_token_plan_key(key: str) -> bool:
    return str(key or '').strip().startswith('sk-sp-')


def is_qwen_cloud_host(host: str) -> bool:
    return str(host or '').lower().rstrip('.') in QWEN_CLOUD_HOSTS


def api_root(url: str) -> str:
    """``https://host`` of any DashScope native URL (Base URL or endpoint)."""
    parts = urlsplit(str(url or ''))
    if parts.scheme != 'https' or not parts.hostname:
        raise ValueError('需要 https 开头的服务地址。')
    return f'https://{parts.hostname}' + (f':{parts.port}' if parts.port else '')


def needs_oss_resolve(url: str) -> bool:
    return str(url or '').startswith('oss://')


# ----------------------------------------------------------------- errors

@dataclass(frozen=True)
class ServiceProblem:
    """One failure explained for a person, plus where to fix it."""
    category: str     # network, key, token_plan_key, balance, billing_info, free_tier_only,
                      # permission, model, not_activated, rate_limit, file_access, server, unknown
    message: str
    action: str = ''  # what the user should do next
    link: str = ''    # official page that fixes it, when there is one
    code: str = ''    # provider code, kept for support (never secret)

    def text(self) -> str:
        return self.message + ('\n' + self.action if self.action else '')


def _body_code(body) -> tuple[str, str]:
    if not isinstance(body, dict):
        return '', ''
    code = str(body.get('code') or '')
    message = str(body.get('message') or '')
    output = body.get('output')
    if not code and isinstance(output, dict):
        code = str(output.get('code') or '')
        message = message or str(output.get('message') or '')
    return code, message


def explain(status: int | None, body=None, *, model: str = '', host: str = '',
            region_label: str = '', exception: BaseException | None = None) -> ServiceProblem:
    """Turn an HTTP status / DashScope error body into a readable cause.

    Never maps everything to "API Key 错误": the documented codes for
    balance, billing info, free-tier-only, model permission, missing model,
    product activation, throttling and file access each get their own text.
    """
    qwen_cloud = is_qwen_cloud_host(host)
    console = QWEN_CLOUD_CONSOLE if qwen_cloud else 'https://bailian.console.aliyun.com/'
    keys_page = QWEN_CLOUD_API_KEYS if qwen_cloud else 'https://bailian.console.aliyun.com/?tab=model#/api-key'
    if exception is not None:
        name = type(exception).__name__
        timeout = 'timeout' in name.lower() or 'timed out' in str(exception).lower()
        where = host or '服务'
        return ServiceProblem(
            'network', f'连不上 {where}（{"等待超时" if timeout else name}）。',
            '请检查网络或代理后重试；已经提交的识别任务会继续查询，不会重复提交。'
            + ('Qwen Cloud 在新加坡，大陆网络可能需要稳定的国际线路。' if qwen_cloud else ''),
            code=name)
    code, message = _body_code(body)
    lowered = f'{code} {message}'.lower()
    model_text = model or '所选模型'
    if code == 'Arrearage' or 'arrearage' in lowered or 'out_of_service' in lowered or 'good standing' in lowered:
        return ServiceProblem('balance', '账户欠费或余额不足，服务商拒绝了请求。',
                              '请到控制台的账单页面充值或结清欠费，几分钟后再试。',
                              QWEN_CLOUD_BILLING if qwen_cloud else console, code or 'Arrearage')
    if 'unpurchased' in lowered or 'eligible for using the model' in lowered:
        return ServiceProblem('billing_info', '账户还没补全付款信息，暂时不能调用模型。',
                              '在控制台“账单”里补全付款信息（补全后才会解锁新用户免费额度）。',
                              QWEN_CLOUD_BILLING + '?target=payment' if qwen_cloud else console, code)
    if 'freetieronly' in lowered or 'free tier of the model has been exhausted' in lowered:
        return ServiceProblem('free_tier_only', f'{model_text} 的免费额度已用完，且账户开着“仅使用免费额度”。',
                              '要继续按量付费，请在控制台关闭“仅使用免费额度”（新用户需先补全资料）；不想付费就到此为止。',
                              QWEN_CLOUD_FREE_TIER if qwen_cloud else console, code)
    if code in {'Model.AccessDenied', 'Workspace.AccessDenied', 'App.AccessDenied'} or 'model access denied' in lowered:
        return ServiceProblem('permission', f'这把 API Key 没有调用 {model_text} 的权限。',
                              '子业务空间的 Key 需要先在控制台给这个模型授权；或者改用默认业务空间创建的 Key。',
                              QWEN_CLOUD_WORKSPACES if qwen_cloud else console, code)
    if code in {'ModelNotFound', 'model_not_found'} or 'model not exist' in lowered or 'model can not be found' in lowered \
            or ('does not exist' in lowered and 'model' in lowered):
        where = f'（{region_label}）' if region_label else ''
        return ServiceProblem('model', f'这个入口{where}找不到 {model_text}。',
                              '请确认选的是“录音文件识别”模型，且入口/地域提供它（Qwen-Audio-3.1 录音文件识别在北京与新加坡提供）。',
                              console, code)
    if 'not activated' in lowered:
        return ServiceProblem('not_activated', '这个账号还没有开通模型服务。',
                              '先登录控制台开通服务（同意服务协议）后再试。', console, code)
    if status == 401 or code in {'InvalidApiKey', 'invalid_api_key'} or 'api-key' in lowered or 'api key' in lowered:
        hint = ''
        if region_label and not qwen_cloud:
            hint = f'当前地址属于{region_label}，密钥必须是同一地域创建的；'
        return ServiceProblem('key', '服务商不认这把 API Key。',
                              hint + '常见原因：没复制完整或多了空格、Key 已删除、或把 Qwen Cloud 与阿里云百炼（中国站）的 Key 混用（两者不能互换）。',
                              keys_page, code or 'InvalidApiKey')
    if status == 403 or code.startswith('AccessDenied'):
        return ServiceProblem('permission', '服务商拒绝访问（没有权限）。',
                              '如果用的是 Token Plan 订阅 Key（sk-sp- 开头），请改用按量付费的 API Key；'
                              '否则请检查业务空间的模型权限。', keys_page, code or 'AccessDenied')
    if status == 429 or code.startswith('Throttling') or 'quota' in lowered:
        return ServiceProblem('rate_limit', '请求太频繁或配额暂时用尽。',
                              '稍等几分钟再试；反复出现时到控制台查看限流与配额。已提交的任务不会被重复提交。',
                              console, code or 'Throttling')
    if 'file_download_failed' in lowered or 'failed to download' in lowered or 'url error' in lowered \
            or 'download the media' in lowered:
        return ServiceProblem('file_access', '服务端没能读取上传的音频。',
                              '暂存上传可能已过期（48 小时）或中途断线；请重新开始识别，兔白会重新上传，已完成的任务结果会保留。',
                              '', code or 'FILE_DOWNLOAD_FAILED')
    if status is not None and status >= 500:
        return ServiceProblem('server', f'服务端暂时出错（HTTP {status}）。',
                              '稍后再试。已经提交的任务会继续查询原任务，不会重复提交。', '', code)
    detail = f'HTTP {status}' if status is not None else ''
    if code:
        detail = (detail + ' ' if detail else '') + code
    return ServiceProblem('unknown', f'服务商返回了未识别的错误（{detail or "无代码"}）。',
                          '请把“复制诊断信息”的内容发给维护者；其中不会包含密钥。', console, code)


def explain_token_plan_key() -> ServiceProblem:
    return ServiceProblem('token_plan_key', '这是 Token Plan 订阅专用的 Key（sk-sp- 开头）。',
                          '它只能用于聊天类工具，不能上传音频做录音文件识别。请在同一页面创建“按量付费”的 API Key（sk-ws- 开头）。',
                          QWEN_CLOUD_API_KEYS, 'token_plan_key')


# ----------------------------------------------------------------- temporary upload

class TemporaryUploadError(RuntimeError):
    def __init__(self, problem: ServiceProblem):
        super().__init__(problem.text())
        self.problem = problem
        self.category = problem.category


@dataclass
class TemporaryObject:
    key: str              # object key inside the provider's temporary bucket
    bucket: str = 'dashscope-temporary'
    region: str = ''
    size_bytes: int = 0
    uploaded_seconds: float = 0.0


class _MultipartBody(io.RawIOBase):
    """Form fields then the file, with a known length and a progress callback."""

    def __init__(self, fields, filename, payload: bytes, progress=None):
        super().__init__()
        self.boundary = '----2ByteASR' + uuid.uuid4().hex
        head = io.BytesIO()
        for name, value in fields:
            head.write(f'--{self.boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                       f'{value}\r\n'.encode('utf-8'))
        head.write(f'--{self.boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                   'Content-Type: application/octet-stream\r\n\r\n'.encode('utf-8'))
        self._parts = [head.getvalue(), memoryview(payload), f'\r\n--{self.boundary}--\r\n'.encode('ascii')]
        self._total = sum(len(p) for p in self._parts)
        self._index = 0
        self._offset = 0
        self._sent = 0
        self._progress = progress
        self._payload_size = len(payload)

    @property
    def content_type(self) -> str:
        return f'multipart/form-data; boundary={self.boundary}'

    def __len__(self):
        return self._total

    def tell(self):
        # requests sizes a stream as len() - tell(). The default tell() raises
        # on this unseekable stream, so requests sent it chunked *and* with our
        # Content-Length; Alibaba OSS rejects that with 400 BadRequest (found by
        # the first real upload, 2026-10-14).
        return self._sent

    def readable(self):
        return True

    def read(self, size=-1):
        if size is None or size < 0:
            size = self._total
        out = bytearray()
        while size > 0 and self._index < len(self._parts):
            part = self._parts[self._index]
            chunk = part[self._offset:self._offset + size]
            out += chunk
            self._offset += len(chunk)
            size -= len(chunk)
            if self._offset >= len(part):
                self._index += 1
                self._offset = 0
        self._sent += len(out)
        if self._progress is not None and out:
            try:
                self._progress(min(self._sent, self._payload_size), self._payload_size)
            except Exception:
                pass
        return bytes(out)


def _new_filename(extension: str) -> str:
    ext = re.sub(r'[^A-Za-z0-9]', '', str(extension or 'wav')).lower() or 'wav'
    # Never the local file name: the provider sees only a random name.
    return f'2byteasr-{uuid.uuid4().hex}.{ext}'


def _join_key(directory: str, filename: str) -> str:
    clean = str(directory or '').lstrip('/')
    if not clean:
        return filename
    return clean + filename if clean.endswith('/') else f'{clean}/{filename}'


class DashScopeTemporaryStorage:
    """The provider's official 48-hour temporary upload, shaped like
    ``temp_audio_storage.TemporaryAudioStorage`` so ``cloud_asr_jobs.filetrans``
    can use either. Nothing is created in the user's own cloud account."""

    kind = 'dashscope_temporary'
    max_object_age_seconds = TEMPORARY_OBJECT_REUSE_SECONDS

    def __init__(self, *, api_url: str, api_key: str, model: str, client=None,
                 policy_timeout=(10, 60), upload_timeout=(10, 1800)):
        self.root = api_root(api_url)
        self.api_key = str(api_key or '').strip()
        self.model = str(model or '').strip()
        self._client = client
        self.policy_timeout = policy_timeout
        self.upload_timeout = upload_timeout
        if not self.api_key:
            raise TemporaryUploadError(ServiceProblem('key', '还没有填写 API Key。'))
        if is_token_plan_key(self.api_key):
            raise TemporaryUploadError(explain_token_plan_key())

    @property
    def client(self):
        if self._client is None:
            from . import network_policy
            self._client = network_policy
        return self._client

    def describe(self) -> str:
        return f'{urlsplit(self.root).hostname} 官方暂存（{TEMPORARY_OBJECT_HOURS} 小时后自动删除）'

    def get_policy(self) -> dict:
        import requests
        url = f'{self.root}{UPLOAD_POLICY_PATH}'
        try:
            response = self.client.get(url, params={'action': 'getPolicy', 'model': self.model},
                                       headers={'Authorization': 'Bearer ' + self.api_key,
                                                'Accept': 'application/json'},
                                       timeout=self.policy_timeout, allow_redirects=False)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise TemporaryUploadError(explain(None, host=urlsplit(self.root).hostname or '',
                                               exception=exc)) from None
        body = _json(response)
        if response.status_code != 200:
            raise TemporaryUploadError(explain(response.status_code, body, model=self.model,
                                               host=urlsplit(self.root).hostname or ''))
        policy = normalize_policy(body)
        if policy is None:
            raise TemporaryUploadError(ServiceProblem('server', '服务商返回的上传凭证不完整，无法上传。',
                                                      '稍后再试；反复出现请复制诊断信息给维护者。'))
        return policy

    def upload_audio(self, payload: bytes, extension: str, *,
                     progress: Callable[[int, int], None] | None = None) -> TemporaryObject:
        import requests
        started = time.perf_counter()
        policy = self.get_policy()
        limit = float(policy.get('max_file_size_mb') or 0) * 1024 * 1024
        if len(payload) > limit:
            raise TemporaryUploadError(ServiceProblem(
                'file_access', f'音频有 {len(payload) / 1048576:.0f} MB，超过服务商暂存上传上限 '
                               f'{policy.get("max_file_size_mb")} MB。',
                '请缩小识别范围（例如分段识别）后再试。'))
        filename = _new_filename(extension)
        key = policy.get('key') or _join_key(policy['upload_dir'], filename)
        # Same fields, names and order as the official QwenCloud CLI uploader.
        fields = [('key', key), ('OSSAccessKeyId', policy['oss_access_key_id']), ('policy', policy['policy']),
                  ('signature', policy['signature']), ('success_action_status', '200')]
        if policy.get('x_oss_object_acl'):
            fields.append(('x-oss-object-acl', policy['x_oss_object_acl']))
        if policy.get('x_oss_forbid_overwrite'):
            fields.append(('x-oss-forbid-overwrite', policy['x_oss_forbid_overwrite']))
        body = _MultipartBody(fields, filename, payload, progress)
        try:
            response = self.client.post(policy['upload_host'], data=body,
                                        headers={'Content-Type': body.content_type,
                                                 'Content-Length': str(len(body))},
                                        timeout=self.upload_timeout, allow_redirects=False)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise TemporaryUploadError(explain(None, host=urlsplit(policy['upload_host']).hostname or '',
                                               exception=exc)) from None
        if response.status_code not in (200, 204):
            raise TemporaryUploadError(ServiceProblem(
                'file_access', f'上传音频到服务商暂存空间失败（HTTP {response.status_code}）。',
                '请检查网络后重新开始识别；这一步还没有提交识别任务，不会产生识别费用。',
                code=f'upload_http_{response.status_code}'))
        seconds = time.perf_counter() - started
        print(f'   [暂存上传] 完成（{len(payload) / 1048576:.1f} MB，{seconds:.1f}s，'
              f'{TEMPORARY_OBJECT_HOURS} 小时后由服务商自动删除）')
        return TemporaryObject(key=key, size_bytes=len(payload), uploaded_seconds=seconds,
                               region=urlsplit(self.root).hostname or '')

    def create_download_url(self, key: str, ttl_seconds: int | None = None) -> str:
        return 'oss://' + str(key).lstrip('/')

    def verify_download_url(self, url: str) -> None:
        # The temporary bucket is private to the provider; only the service can
        # read it. Reachability is proven by the task, not by a local GET.
        if not needs_oss_resolve(url):
            raise TemporaryUploadError(ServiceProblem('file_access', '暂存上传地址格式不对。'))

    def delete_object(self, key: str, *, strict=False) -> None:
        # No delete API exists for temporary uploads; the provider removes them
        # after 48 hours. Nothing to do and nothing left in the user's account.
        return None

    def cleanup_stale_objects(self, max_age_hours: float = 48.0) -> int:
        return 0

    def test_connection(self):
        """Free check: the provider issues an upload credential for this key and
        model. No audio or file is uploaded."""
        from .temp_audio_storage import StorageTestResult
        try:
            self.get_policy()
        except TemporaryUploadError as exc:
            return StorageTestResult(ok=False, message=exc.problem.text())
        return StorageTestResult(ok=True, message='服务商同意为这个模型发放暂存上传凭证（没有上传任何文件）。')


def normalize_policy(raw) -> dict | None:
    """Accept the documented shape and the ``{"data": {...}}`` envelope."""
    if not isinstance(raw, dict):
        return None
    data = raw.get('data') if isinstance(raw.get('data'), dict) else raw

    def text(*names):
        for name in names:
            value = data.get(name)
            if isinstance(value, str) and value:
                return value
        return ''

    policy = {
        'upload_host': text('upload_host'),
        'upload_dir': text('upload_dir'),
        'key': text('key'),
        'oss_access_key_id': text('oss_access_key_id', 'OSSAccessKeyId', 'ossaccesskeyid'),
        'signature': text('signature'),
        'policy': text('policy'),
        'x_oss_object_acl': text('x_oss_object_acl', 'x-oss-object-acl'),
        'x_oss_forbid_overwrite': text('x_oss_forbid_overwrite', 'x-oss-forbid-overwrite'),
    }
    try:
        policy['max_file_size_mb'] = float(data.get('max_file_size_mb') or 0)
    except (TypeError, ValueError):
        policy['max_file_size_mb'] = 0.0
    if not all(policy[k] for k in ('upload_host', 'upload_dir', 'oss_access_key_id', 'signature', 'policy')):
        return None
    if urlsplit(policy['upload_host']).scheme != 'https':
        return None
    return policy


def _json(response):
    try:
        return response.json()
    except Exception:
        try:
            return json.loads(response.text)
        except Exception:
            return {}
