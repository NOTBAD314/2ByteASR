"""Credential-scoped model metadata. Discovery never probes paid completions."""
from __future__ import annotations

from . import network_policy
import copy
import hashlib
import threading
import time
from urllib.parse import urlsplit, urljoin

_cache = {}
_lock = threading.Lock()


class DiscoveryError(RuntimeError):
    def __init__(self, category, message):
        self.category = category
        super().__init__(message)


def identity(provider, base_url, api_key=''):
    from .llm_config import normalize_base_url
    url = urlsplit(normalize_base_url(base_url))
    base = url._replace(scheme=url.scheme.lower(), netloc=url.netloc.lower()).geturl()
    return str(provider), base, hashlib.sha256(str(api_key).encode()).hexdigest()


def cached(provider, base_url, api_key='', *, max_age=300):
    with _lock:
        hit = _cache.get(identity(provider, base_url, api_key))
        return copy.deepcopy(hit) if hit and time.time()-hit['updated_at'] <= max_age else None


def remember(provider, base_url, api_key, records):
    value = dict(records=copy.deepcopy(records), updated_at=time.time())
    with _lock:
        _cache[identity(provider, base_url, api_key)] = value
    return value


def model_limits(provider, base_url, api_key, model):
    hit = cached(provider, base_url, api_key)
    row = next((r for r in (hit or {}).get('records', []) if r['id'] == model), {})
    limits={k: row[k] for k in ('context_tokens', 'input_tokens', 'output_tokens', 'source') if row.get(k) is not None}
    # Exact model + official endpoint only; never lend these limits to an
    # alias, a relay, or another provider. The application ceiling still wins.
    if (provider=='deepseek' and base_url.rstrip('/') in ('https://api.deepseek.com','https://api.deepseek.com/v1')
            and model=='deepseek-v4-pro' and not limits.get('context_tokens')):
        limits.update(context_tokens=1_000_000,output_tokens=384_000,
            source='https://api-docs.deepseek.com/quick_start/pricing (verified 2026-09-22, exact deepseek-v4-pro)')
    return limits


def capabilities(provider, base_url, api_key, model):
    hit=cached(provider,base_url,api_key)
    row=next((r for r in (hit or {}).get('records',[]) if r['id']==model),{})
    modalities=row.get('input_modalities')
    result=dict(vision=('image' in modalities) if isinstance(modalities,list) else None,
                max_context=model_limits(provider,base_url,api_key,model).get('context_tokens'))
    if provider=='deepseek' and base_url.rstrip('/') in ('https://api.deepseek.com','https://api.deepseek.com/v1') and model=='deepseek-v4-pro':
        result['vision']=False
    return result


def _positive(row, names):
    for name in names:
        value = row.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _records(data, source):
    values = data if isinstance(data, list) else next((data[k] for k in ('data', 'models', 'language_models', 'result')
        if isinstance(data.get(k), list)), []) if isinstance(data, dict) else []
    result = []
    for value in values:
        row = value if isinstance(value, dict) else {'id': value}
        mid = row.get('id') or row.get('model') or row.get('name')
        if not isinstance(mid, str) or not mid.strip():
            continue
        result.append(dict(id=mid, context_tokens=_positive(row, ('context_length', 'context_window', 'max_context_length')),
            input_tokens=_positive(row, ('inputTokenLimit', 'max_input_tokens')),
            output_tokens=_positive(row, ('outputTokenLimit', 'max_output_tokens')),
            input_modalities=row.get('input_modalities'), output_modalities=row.get('output_modalities'), source=source))
    return result


def discover(provider, base_url, api_key, *, timeout=12, force=False):
    import requests
    from .llm_config import models_url, validate_transport_url
    if not force:
        hit = cached(provider, base_url, api_key)
        if hit:
            return hit
    validate_transport_url(base_url, '模型列表')
    url = models_url(base_url)
    headers = {'Authorization': 'Bearer '+api_key} if api_key else {}
    official_xai = urlsplit(base_url).hostname == 'api.x.ai'
    gemini = provider == 'gemini' and urlsplit(base_url).hostname == 'generativelanguage.googleapis.com'
    if gemini:
        url = 'https://generativelanguage.googleapis.com/v1beta/models'
        headers = {'x-goog-api-key': api_key}
    origin = urlsplit(url)[:2]
    records, seen, params = {}, set(), {}
    deadline = time.monotonic()+timeout

    def fetch(target, parameters):
        if urlsplit(target)[:2] != origin:
            raise DiscoveryError('model_discovery_redirect', '列表分页指向另一主机，已停止；密钥未转发。')
        try:
            response = network_policy.get(target, headers=headers, params=parameters, timeout=max(.1, deadline-time.monotonic()), allow_redirects=False)
        except requests.Timeout as exc:
            raise DiscoveryError('model_discovery_timeout', '获取模型列表超时；保留原配置。') from exc
        if 300 <= response.status_code < 400:
            raise DiscoveryError('model_discovery_redirect', '模型列表端点要求重定向；请核对配置地址，密钥未转发。')
        if response.status_code >= 400:
            category = {401:'unauthorized',403:'forbidden',404:'unsupported',405:'unsupported',429:'rate_limited'}.get(response.status_code,'http_error')
            raise DiscoveryError('model_discovery_'+category, f'模型列表 HTTP {response.status_code}；列表权限与生成权限独立，可保留当前模型或手动输入。')
        try:
            return response.json()
        except ValueError as exc:
            raise DiscoveryError('model_discovery_format', '模型列表不是有效 JSON；保留原配置。') from exc

    for _ in range(30):
        marker = (url, str(params))
        if marker in seen or time.monotonic() >= deadline:
            raise DiscoveryError('model_discovery_pagination', '模型列表分页未完成；保留上次完整缓存。')
        seen.add(marker)
        data = fetch(url, params)
        for row in _records(data, url):
            records[row['id']] = row
        if not isinstance(data, dict):
            break
        if data.get('nextPageToken'):
            params = {'pageToken': data['nextPageToken']}
        elif data.get('has_more') and data.get('last_id'):
            params = {'after': data['last_id']}
        elif isinstance(data.get('next'), str) and data['next']:
            url, params = urljoin(url, data['next']), {}
        else:
            break
    else:
        raise DiscoveryError('model_discovery_pagination', '模型列表超过分页上限；保留原缓存。')
    if not records:
        raise DiscoveryError('model_discovery_empty', '服务端返回空模型列表；原选择保留，仍可手动输入。')
    # xAI's richer endpoint supplements IDs actually returned by this account.
    if official_xai and time.monotonic() < deadline:
        try:
            richer = fetch('https://api.x.ai/v1/language-models', {})
            for row in _records(richer, 'https://api.x.ai/v1/language-models'):
                if row['id'] in records:
                    records[row['id']].update({k:v for k,v in row.items() if v is not None})
        except (DiscoveryError, requests.RequestException):
            pass  # A useful /models response is independent of metadata access.
    return remember(provider, base_url, api_key, list(records.values()))
