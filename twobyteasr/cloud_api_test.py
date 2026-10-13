"""Graded checks for the "申请与设置 API" dialog (2026-10-13).

Each level is reported separately and only claims what it actually observed:

0. ``format``      — local only: the pasted address, key shape and required
                     fields make sense (nothing is sent anywhere);
1. ``connection``  — the API host answered at all;
2. ``key``         — the provider accepted this key (an authenticated request
                     returned success);
3. ``model``       — the provider lists the selected model for this key/region;
4. ``recognition`` — a real short audio was recognized through the same worker
                     path a recognition job uses (uploads audio; may cost money);
5. ``timestamps`` / ``speakers`` — what that real result actually contained.

Free checks never upload audio. The paid check runs only after the user
confirmed provider, data and cost in the dialog.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

PASS, FAIL, UNKNOWN, SKIP = 'pass', 'fail', 'unknown', 'skip'

LEVELS = ('format', 'connection', 'key', 'model', 'storage', 'recognition', 'timestamps', 'speakers')
LEVEL_LABELS = {
    'format': '设置格式',
    'connection': '服务可以连线',
    'key': '认证成功（API Key 有效）',
    'model': '指定模型可用',
    'storage': '音频上传方式',
    'recognition': '实际短音频识别',
    'timestamps': '回传时间戳',
    'speakers': '回传说话人',
}

SAMPLE_AUDIO = 'assets/diagnostics/speech_en.wav'  # 5.97 s synthetic English, shipped with the app
SAMPLE_SECONDS = 5.97375


@dataclass
class Check:
    level: str
    status: str
    detail: str = ''


@dataclass
class Report:
    checks: list = field(default_factory=list)
    models: list = field(default_factory=list)
    price: dict = field(default_factory=dict)

    def add(self, level, status, detail=''):
        self.checks = [c for c in self.checks if c.level != level] + [Check(level, status, detail)]
        return self

    def status(self, level):
        return next((c.status for c in self.checks if c.level == level), SKIP)


def _json(response):
    try:
        return response.json()
    except Exception:
        return {}


def _get(client, url, key, **kwargs):
    import requests
    try:
        return client.get(url, headers={'Authorization': 'Bearer ' + key} if key else {},
                          timeout=(10, 30), allow_redirects=False, **kwargs), None
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        return None, exc


def format_check(endpoint: dict, values: dict | None = None) -> Report:
    """Local sanity checks before anything is sent (no network)."""
    from urllib.parse import urlsplit
    from .dashscope_service import explain_token_plan_key, is_token_plan_key
    report = Report()
    values = values or {}
    protocol = str(endpoint.get('protocol') or '')
    key = str(endpoint.get('api_key') or '').strip()
    problems = []
    if protocol == 'spark_wss':
        problems += [f'还缺 {label}' for name, label in (('app_id', 'AppID'), ('api_key', 'APIKey'),
                                                       ('api_secret', 'APISecret'))
                     if not str(endpoint.get(name) or '').strip()]
    elif not key:
        problems.append('还没有填写 API Key。')
    elif any(ch.isspace() for ch in key):
        problems.append('API Key 里有空格或换行，请重新复制（只要那一串字符）。')
    elif protocol == 'dashscope_filetrans' and is_token_plan_key(key):
        problems.append(explain_token_plan_key().text())
    url = str(endpoint.get('url') or '')
    parts = urlsplit(url) if url else None
    if protocol != 'spark_wss' and (not parts or parts.scheme != 'https' or not parts.hostname):
        problems.append('服务地址无效：需要 https 开头的完整地址。')
    if values.get('filetrans_upload') == 'own_oss':
        missing = [label for name, label in (('oss_bucket', 'OSS Bucket 名称'), ('oss_access_key_id', 'AccessKey ID'),
                                             ('oss_access_key_secret', 'AccessKey Secret'))
                   if not str(values.get(name) or '').strip()]
        if missing:
            problems.append('选了自己的 OSS，但还缺：' + '、'.join(missing))
    if problems:
        return report.add('format', FAIL, '\n'.join(problems))
    host = parts.hostname if parts else ''
    return report.add('format', PASS, f'格式正确（地址 {host}）。这一步只在本机检查，没有联系服务商。' if host
                      else '格式正确。这一步只在本机检查，没有联系服务商。')


def free_checks(endpoint: dict, *, client=None, values: dict | None = None) -> Report:
    """Checks that upload no audio and cost nothing."""
    from . import network_policy
    client = client or network_policy
    protocol = str(endpoint.get('protocol') or '')
    key = str(endpoint.get('api_key') or '').strip()
    report = format_check(endpoint, values)
    if report.status('format') == FAIL:
        return report
    if protocol == 'mosi_transcriptions':
        from .mosi_asr import check_key
        result = check_key(endpoint, client=client)
        report.models = result.get('models') or []
        report.add('connection', PASS if result['connection'] else FAIL if result['connection'] is False else UNKNOWN,
                   '' if result['connection'] else result['message'])
        report.add('key', PASS if result['key_valid'] else FAIL if result['key_valid'] is False else UNKNOWN,
                   '' if result['key_valid'] else result['message'])
        if result['key_valid']:
            report.add('model', PASS if result['model_available'] else FAIL, result['message'])
        return report
    if protocol == 'dashscope_filetrans':
        return _dashscope_checks(endpoint, key, client, report)
    if protocol in {'openai_transcription', 'openrouter_verbose_json'}:
        return _openai_models_check(endpoint, key, client, report)
    if protocol == 'spark_wss':
        missing = [label for name, label in (('app_id', 'AppID'), ('api_key', 'APIKey'), ('api_secret', 'APISecret'))
                   if not str(endpoint.get(name) or '').strip()]
        if missing:
            return report.add('key', FAIL, '还缺：' + '、'.join(missing))
        return report.add('key', UNKNOWN, '讯飞没有免费的密钥查询接口；请用“实际短音频识别”确认。')
    return report.add('key', UNKNOWN, '这个服务没有可用的免费检查；请用“实际短音频识别”确认。')


def _problem_text(status, body, *, model, address):
    from .dashscope_service import explain
    problem = explain(status, body, model=model, host=address.host, region_label=address.region_label)
    return problem.text() + (f'（HTTP {status}' + (f' {problem.code}' if problem.code else '') + '）'
                             if status is not None else ''), problem


def _dashscope_checks(endpoint, key, client, report):
    """Bailian / Qwen Cloud free checks; none uploads audio.

    * Bailian workspace and legacy hosts: ``GET {Base URL}/models?model=<id>``
      (官方“查询模型列表”接口).
    * Qwen Cloud (``maas.qwencloudapi.com``) has no native model list (HTTP 404,
      probed 2026-10-13); its OpenAI-compatible ``/compatible-mode/v1/models``
      proves the key. Whether this model accepts audio is checked by asking for
      a temporary-upload credential (``storage`` level, no file uploaded).
    """
    from .api_endpoints import EndpointInputError, parse_dashscope_address
    try:
        address = parse_dashscope_address(endpoint.get('url') or '')
    except EndpointInputError as exc:
        return report.add('format', FAIL, str(exc))
    model = str(endpoint.get('model') or '')
    native = None if address.qwen_cloud else address.base_url + '/models'
    response, error = _get(client, native, key, params={'model': model}) if native else (None, None)
    if native and error is None and response.status_code == 404:
        native = None
    if not native:
        response, error = _get(client, address.compatible_base_url + '/models', key)
    if error is not None:
        from .dashscope_service import explain
        return report.add('connection', FAIL, explain(None, host=address.host, exception=error).text())
    report.add('connection', PASS, f'{address.host} 有回应。')
    body = _json(response)
    if response.status_code != 200:
        detail, problem = _problem_text(response.status_code, body, model=model, address=address)
        if problem.category in {'key', 'token_plan_key'}:
            return report.add('key', FAIL, detail)
        if problem.category in {'balance', 'billing_info', 'free_tier_only', 'not_activated', 'permission'}:
            # The key itself was recognised; the account cannot use it yet.
            report.add('key', PASS, '服务商认得这把 Key，但账户目前不能调用（见下一项）。')
            return report.add('model', FAIL, detail)
        if problem.category == 'model':
            report.add('key', PASS)
            return report.add('model', FAIL, detail)
        return report.add('key', UNKNOWN, detail)
    report.add('key', PASS, '服务商接受了这把 API Key。')
    if native:
        models = [row for row in (body.get('output') or {}).get('models') or [] if isinstance(row, dict)]
        report.models = [str(row.get('model') or '') for row in models]
        match = next((row for row in models if row.get('model') == model), None)
        if match is None:
            return report.add('model', FAIL, f'{address.region_label}的模型列表里没有 {model}。'
                                             '请确认地域、模型名，或在控制台开通该模型。')
        report.price = {'source': 'bailian_model_list_api', 'prices': match.get('prices') or []}
        return report.add('model', PASS, f'{address.region_label}提供 {model}。能否计费调用，以实际短音频识别为准。')
    report.models = [str(row.get('id')) for row in body.get('data') or [] if isinstance(row, dict)]
    if model in report.models:
        return report.add('model', PASS, f'模型列表里有 {model}。能否计费调用，以实际短音频识别为准。')
    return report.add('model', UNKNOWN, f'这个接口的模型列表不列出录音文件识别模型；{model} 是否可用请看“音频上传方式”'
                                        '检查与实际短音频识别。')


def _openai_models_check(endpoint, key, client, report):
    from .llm_config import models_url
    url = models_url(str(endpoint.get('url') or ''))
    params = None
    if str(endpoint.get('protocol')) == 'openrouter_verbose_json':
        # OpenRouter's default list has no speech-to-text models (2026-10-14:
        # 462 models, 0 transcription); its documented filter lists them.
        params = {'output_modalities': 'transcription'}
    response, error = _get(client, url, key, params=params) if params else _get(client, url, key)
    if error is not None:
        return report.add('connection', FAIL, f'连不上服务：{type(error).__name__}。')
    report.add('connection', PASS)
    if response.status_code in (401, 403):
        return report.add('key', FAIL, f'服务拒绝了这个 API Key（HTTP {response.status_code}）。')
    if response.status_code != 200:
        return report.add('key', UNKNOWN, f'模型列表返回 HTTP {response.status_code}；无法判断密钥是否有效。')
    body = _json(response)
    report.models = [str(row.get('id')) for row in body.get('data') or [] if isinstance(row, dict)]
    if str(endpoint.get('protocol')) == 'openrouter_verbose_json':
        # OpenRouter's model list is public: a 200 here does not prove the key.
        report.add('key', UNKNOWN, 'OpenRouter 的模型列表不需要密钥，不能证明密钥有效；请用实际短音频识别确认。')
    else:
        report.add('key', PASS)
    model = str(endpoint.get('model') or '')
    if model:
        report.add('model', PASS if model in report.models else FAIL,
                   '' if model in report.models else f'模型列表里没有 {model}。')
    return report


def oss_check(settings: dict, credentials: tuple) -> Report:
    """Uploads a tiny probe object (not audio) to the user's own bucket, then deletes it."""
    from .provider_diagnostics import redact_diagnostics
    from .temp_audio_storage import oss_storage_from_settings
    report = Report()
    try:
        storage = oss_storage_from_settings(settings, credentials=tuple(credentials or ()))
    except Exception as exc:
        return report.add('storage', FAIL, redact_diagnostics(str(exc))[:300])
    if storage is None:
        return report.add('storage', FAIL, '还没有填写完整的 OSS 存储（Bucket、Endpoint、AccessKey）。')
    try:
        result = storage.test_connection()
    except Exception as exc:
        return report.add('storage', FAIL, redact_diagnostics(str(exc))[:300])
    detail = redact_diagnostics(str(getattr(result, 'message', '') or ''))
    if result.ok:
        detail = (detail + '；' if detail else '') + '可以上传、生成签名链接并删除测试对象。'
    return report.add('storage', PASS if result.ok else FAIL, detail)


def temporary_upload_check(endpoint: dict) -> Report:
    """Free: the provider issues an upload credential for this key and model.

    Proves the key may hand audio to this model; no file is uploaded.
    """
    from .dashscope_service import DashScopeTemporaryStorage, TemporaryUploadError
    report = Report()
    try:
        storage = DashScopeTemporaryStorage(api_url=str(endpoint.get('url') or ''),
                                            api_key=str(endpoint.get('api_key') or ''),
                                            model=str(endpoint.get('model') or ''))
    except (TemporaryUploadError, ValueError) as exc:
        return report.add('storage', FAIL, str(exc))
    result = storage.test_connection()
    return report.add('storage', PASS if result.ok else FAIL,
                      ('服务商临时上传：' + result.message) if result.ok else result.message)


def storage_check(endpoint: dict, settings: dict, values: dict, credentials: tuple) -> Report:
    """The upload route this provider will actually use."""
    from .api_setup_catalog import MISSING_UPLOAD_MESSAGE, UPLOAD_OWN_OSS, UPLOAD_PROVIDER, resolve_upload_mode
    models = dict((settings or {}).get('models', {}) or {})
    if values.get('filetrans_upload'):
        models['filetrans_upload'] = values['filetrans_upload']
    mode = resolve_upload_mode(models, str(endpoint.get('provider') or ''),
                               has_oss_credentials=all(credentials or ('', '')))
    if mode == UPLOAD_OWN_OSS:
        return oss_check(settings, credentials)
    if mode == UPLOAD_PROVIDER:
        report = temporary_upload_check(endpoint)
        for check in report.checks:
            if check.level == 'storage' and check.status == PASS:
                check.detail += '（这是“仅供试用”的临时上传：48 小时失效，官方说明勿用于生产。）'
        return report
    return Report().add('storage', FAIL, MISSING_UPLOAD_MESSAGE)


def estimate_test_cost(endpoint: dict, price: dict | None = None, seconds: float = SAMPLE_SECONDS) -> str:
    """Plain-language cost note for one short test; never claims "free"."""
    from .mosi_asr import MODEL as MOSI_MODEL, PRICE_CHECKED, PRICE_CNY_PER_HOUR, estimate_cost_cny
    model = str(endpoint.get('model') or '')
    if model == MOSI_MODEL:
        return (f'约 ¥{estimate_cost_cny(seconds):.4f}（按 MOSI 价格页 ¥{PRICE_CNY_PER_HOUR:.2f}/小时音频，'
                f'{PRICE_CHECKED} 核对；以账单为准）')
    for block in (price or {}).get('prices') or []:
        for row in block.get('prices') or []:
            if str(row.get('price_unit') or '').lower() in {'second', 'seconds', '秒', 'per_second'}:
                try:
                    amount = float(row['price']) * seconds
                    return f'约 ¥{amount:.4f}（按百炼模型列表接口刚返回的单价；以账单为准）'
                except (TypeError, ValueError, KeyError):
                    pass
    return '无法事先估算（服务商未提供可用单价）；按服务商的计费规则收费，通常是几秒音频的费用。'


def short_recognition(endpoint: dict, settings: dict, *, audio_path: str | None = None,
                      storage_credentials: tuple = (), cancel=lambda: False) -> Report:
    """Recognize a short clip through the production worker; uses a throwaway job cache."""
    import numpy as np
    from . import asr_api_process
    from .cache import decode_audio_to_array
    from .runtime import RuntimeContext, activate_runtime_context
    from .runtime_paths import detect_install_root
    report = Report()
    path = Path(audio_path) if audio_path else detect_install_root() / SAMPLE_AUDIO
    audio = decode_audio_to_array(str(path))
    if len(audio) > 60 * 16000:
        return report.add('recognition', FAIL, '测试音频请不要超过 60 秒。')
    snapshot = dict(settings or {})
    context = RuntimeContext(job_id='api-setup-test', asr_endpoint_snapshot=dict(endpoint),
                             asr_settings_snapshot=snapshot, speaker_source='native')
    try:
        with tempfile.TemporaryDirectory(prefix='2byte-api-test-') as cache, activate_runtime_context(context):
            chunks = [dict(start=0.0, end=len(audio) / 16000, audio=(np.asarray(audio, dtype=np.float32), 16000))]
            rows = asr_api_process.transcribe(str(path), chunks, cache_root=cache,
                                              storage_credentials=tuple(storage_credentials) or None)
    except Exception as exc:
        return report.add('recognition', FAIL, failure_detail(exc))
    report.add('recognition', PASS if rows else FAIL,
               f'识别出 {len(rows)} 段文字。' if rows else '服务正常返回，但没有识别出文字（测试音频是否有人声？）。')
    if rows:
        words = sum(len(row.get('tokens') or ()) for row in rows)
        precision = {row.get('timing_precision') for row in rows} - {None}
        if words:
            report.add('timestamps', PASS, f'有字/词级时间（{words} 个时间片）。')
        elif precision == {'segment'}:
            report.add('timestamps', PASS, '只有句段起止时间，没有逐字时间；需要精细剪辑时请再配本地对齐。')
        elif 'request' in precision:
            report.add('timestamps', FAIL, '服务没有回传时间戳：每段文字只有兔白送出的整段范围。'
                                           '需要可用时间时请换支持时间戳的模型，或再配本地对齐。')
        else:
            report.add('timestamps', UNKNOWN, '无法判断服务回传的是句段时间还是没有时间。')
        speakers = {row.get('speaker') for row in rows if row.get('speaker') not in (None, 'S00')}
        report.add('speakers', PASS if speakers else SKIP,
                   f'返回 {len(speakers)} 个说话人标签。' if speakers else '这次结果没有说话人标签（单人音频或模型不支持）。')
    report.models = [str(row.get('text') or '') for row in rows[:3]]
    return report


def failure_detail(exc: BaseException) -> str:
    """The real reason a cloud call failed, explained first, never a key."""
    from .provider_diagnostics import redact_diagnostics
    problem = getattr(exc, 'problem', None)
    if isinstance(problem, dict) and problem.get('message'):
        text = str(problem['message']) + (('\n' + str(problem['action'])) if problem.get('action') else '')
        return redact_diagnostics(text)
    if problem is not None and getattr(problem, 'message', ''):
        return redact_diagnostics(problem.text())
    text = redact_diagnostics(str(exc))
    if 'stderr:' in text:
        # Worker failures carry progress lines first; the cause is at the end.
        tail = text.rsplit('stderr:', 1)[1].strip()
        if tail:
            return tail[-600:]
    return text[:600]
