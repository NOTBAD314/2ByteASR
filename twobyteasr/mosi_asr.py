"""MOSS-Transcribe-Diarize Pro cloud engine (MOSI platform, platform.mosi.cn).

This is a separate engine from the local MOSS backend: its provider id, model
id, key scope, job cache and receipts never mix with ``primary_asr_backend=moss``.

Official sources (checked 2026-10-13):

* Transcriptions API https://platform.mosi.cn/docs/reference/transcriptions/
  ``POST {base}/audio/transcriptions``; multipart ``file`` up to 512 MB;
  ``diarize``; ``keyterms`` (<= 20 terms, <= 30 characters each, JSON string
  array in multipart); ``async=true`` returns a task immediately; the
  diarize-pro model accepts audio up to 60 minutes.
* Task query https://platform.mosi.cn/docs/reference/audio-task
  ``GET {base}/audio/tasks/{task_id}``; status PENDING / PROCESSING / SUCCESS /
  FAILED; segments ``start``/``end`` in seconds with ``speaker``. No cancel
  endpoint is documented.
* Errors https://platform.mosi.cn/docs/errors-and-limits/error-codes
* Pricing https://platform.mosi.cn/app/pricing/ (diarize-pro ¥2.00 per hour of
  input audio; 40 credits per hour; 2026-10-14: the page no longer says
  whether failed tasks are charged).

Segment ``start``/``end`` are sentence bounds, never per-character timing.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .qwen31_asr import ASRProtocolError

PROVIDER = 'mosi_moss_pro'
PROTOCOL = 'mosi_transcriptions'
MODEL = 'moss-transcribe-diarize-pro'
API_BASE = 'https://api.mosi.cn/v1'
WEBSITE = 'https://platform.mosi.cn/'
API_KEYS_PAGE = 'https://platform.mosi.cn/app/api-keys/'
PLAYGROUND_PAGE = 'https://platform.mosi.cn/app/playground/'
PRICING_PAGE = 'https://platform.mosi.cn/app/pricing/'
DOCS_PAGE = 'https://platform.mosi.cn/docs/reference/transcriptions/'
GUIDE_PAGE = 'https://platform.mosi.cn/docs/scenarios/transcribe-diarization/'

MAX_AUDIO_SECONDS = 60 * 60
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
# Longer audio is split below the official 60-minute limit, leaving room to
# move each cut to a quiet point.
CHUNK_SECONDS = 55 * 60
MAX_KEYTERMS = 20
MAX_KEYTERM_CHARS = 30
PRICE_CNY_PER_HOUR = 2.00
PRICE_CHECKED = '2026-10-13'
STATUSES = {'PENDING', 'PROCESSING', 'SUCCESS', 'FAILED'}
# (connect, read): the connect value also bounds each upload block.
UPLOAD_TIMEOUT = (15, 900)


def normalize_api_base(value: str) -> str:
    """Return the API Base URL (``https://api.mosi.cn/v1``) from any pasted form.

    Accepts the bare host, the base URL, or a full endpoint such as
    ``.../v1/audio/transcriptions``; never produces ``/v1/v1``.
    """
    text = str(value or '').strip()
    if not text:
        return API_BASE
    if '://' not in text:
        text = 'https://' + text
    parts = urlsplit(text)
    host = (parts.hostname or '').lower()
    if not host:
        raise ValueError('MOSI 地址缺少主机名')
    loopback = host in {'127.0.0.1', 'localhost', '::1'}
    if parts.scheme != 'https' and not loopback:
        raise ValueError('MOSI API 必须使用 https 地址')
    if host == 'platform.mosi.cn':
        # The website/console address is not the API host.
        return API_BASE
    path = '/' + '/'.join(p for p in parts.path.split('/') if p)
    for suffix in ('/audio/transcriptions', '/models', '/files'):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
    if '/audio/tasks/' in path:
        path = path.split('/audio/tasks/', 1)[0]
    while path.endswith('/v1/v1'):
        path = path[:-3]
    if not path.endswith('/v1'):
        path = path.rstrip('/') + '/v1'
    netloc = parts.netloc.split('@')[-1]
    return urlunsplit((parts.scheme, netloc, path, '', ''))


def transcriptions_url(base: str) -> str:
    return normalize_api_base(base) + '/audio/transcriptions'


def task_url(base: str, task_id: str) -> str:
    return normalize_api_base(base) + '/audio/tasks/' + str(task_id)


def models_url(base: str) -> str:
    return normalize_api_base(base) + '/models'


def keyterm_hints(canonical_terms) -> dict:
    """Recognition hotwords within the official limits, original spelling kept.

    Hotwords are a hint to the recognizer, not a guaranteed replacement; the
    glossary still runs after recognition. Terms beyond the limits are listed,
    never silently truncated.
    """
    sent, dropped, seen = [], [], set()
    for raw in canonical_terms or ():
        term = str(raw or '').strip()
        if not term or term in seen or '\n' in term or '\r' in term:
            continue
        seen.add(term)
        if len(term) > MAX_KEYTERM_CHARS:
            dropped.append({'term': term, 'reason': 'longer_than_30_characters'})
        elif len(sent) >= MAX_KEYTERMS:
            dropped.append({'term': term, 'reason': 'over_20_terms'})
        else:
            sent.append(term)
    return {'mosi_keyterms': sent, 'mosi_diarize': True,
            'mosi_keyterms_dropped': dropped[:200],
            'hint_counts': {'keyterms_sent': len(sent), 'keyterms_dropped': len(dropped),
                            'keyterms_limit': MAX_KEYTERMS}}


def estimate_cost_cny(seconds: float) -> float:
    return round(max(0.0, float(seconds)) / 3600.0 * PRICE_CNY_PER_HOUR, 4)


def worker_timeout_seconds(seconds: float) -> int:
    chunks = max(1, math.ceil(seconds / CHUNK_SECONDS))
    return int(min(6 * 3600, max(3600, seconds * 2 + chunks * 1200)))


SEAM_SEARCH_SECONDS = 4 * 60
SEAM_FRAME = 3200          # 0.2 s at 16 kHz
SEAM_SMOOTH_FRAMES = 5     # quietest full second, not one quiet blip inside a word


def plan_ranges(audio, *, chunk_seconds=CHUNK_SECONDS, search_seconds=SEAM_SEARCH_SECONDS):
    """Sample ranges for requests. One request up to the 60-minute limit.

    Longer audio is cut at the quietest second found within ``search_seconds``
    around each target cut (2026-10-14). Game audio rarely has true silence,
    so the quietest point is chosen relative to its surroundings rather than
    against a fixed threshold; every request stays below the official limit.
    Ranges are contiguous: every sample belongs to exactly one request.
    """
    import numpy as np
    samples = len(audio)
    limit = MAX_AUDIO_SECONDS * 16000
    if samples <= limit:
        return [(0, samples)]
    target = int(chunk_seconds * 16000)
    search = int(search_seconds * 16000)
    ranges, start = [], 0
    while start < samples:
        if samples - start <= limit:
            ranges.append((start, samples))
            break
        lo = max(start + 16000, start + target - search)
        hi = min(samples, start + min(limit - SEAM_FRAME, target + search))
        frames = (hi - lo) // SEAM_FRAME
        end = start + target
        if frames > SEAM_SMOOTH_FRAMES:
            window = np.asarray(audio[lo:lo + frames * SEAM_FRAME], dtype=np.float64).reshape(frames, SEAM_FRAME)
            energy = np.mean(window * window, axis=1)
            smooth = np.convolve(energy, np.ones(SEAM_SMOOTH_FRAMES) / SEAM_SMOOTH_FRAMES, mode='valid')
            best = int(np.argmin(smooth)) + SEAM_SMOOTH_FRAMES // 2
            end = lo + best * SEAM_FRAME + SEAM_FRAME // 2
        ranges.append((start, end))
        start = end
    return ranges


def classify_http_error(status_code: int, body) -> tuple[str, str]:
    """(category, user message) for a non-success response."""
    error = body.get('error') if isinstance(body, dict) else None
    code = str((error or {}).get('code') or (error or {}).get('type') or '')
    if status_code in (401, 403) and code not in {'url_not_allowed', 'safety_guardrail_blocked'}:
        return 'auth_failed', (f'MOSI 拒绝了这个 API Key（HTTP {status_code}）：可能填错、已删除，'
                               '或账户没有该模型权限。请到 MOSI 控制台的 API Key 页面重新复制。')
    if status_code == 402 or code in {'insufficient_credits', 'billing_error'}:
        return 'insufficient_credits', 'MOSI 账户积分不足（HTTP 402）。请到 MOSI 控制台充值后再试。'
    if status_code == 429:
        return 'rate_limited', ('MOSI 请求过于频繁或并发已满（HTTP 429）。请稍后再试；'
                                '已提交的任务不会因此重复提交。')
    if code == 'invalid_keyterms':
        return 'invalid_keyterms', '热词不符合 MOSI 限制（最多 20 个，每个不超过 30 字）。'
    if status_code == 413:
        return 'too_large', '上传文件超过 MOSI 512 MB 限制。'
    if status_code == 404:
        return 'not_found', f'MOSI 地址或任务不存在（HTTP 404）。请确认 API Base URL 是 {API_BASE}。'
    if status_code >= 500:
        return 'server_error', f'MOSI 服务暂时异常（HTTP {status_code}）。'
    return 'request_rejected', f'MOSI 拒绝了请求（HTTP {status_code}{"：" + code if code else ""}）。'


def _json(response):
    try:
        return response.json()
    except Exception:
        return {}


def _auth(endpoint) -> dict:
    key = str(endpoint.get('api_key') or '').strip()
    if not key:
        raise ASRProtocolError('MOSS Pro 云端缺少 API Key。', 'auth_failed')
    return {'Authorization': 'Bearer ' + key}


def _save(path: Path, payload) -> None:
    from .cloud_asr_jobs import save
    save(path, payload)


def validate_result(payload, duration: float) -> None:
    if not isinstance(payload, dict):
        raise ASRProtocolError('MOSS Pro 结果不是 JSON 对象', 'parse_failed')
    segments = payload.get('segments')
    if segments is None:
        segments = []
    if not isinstance(segments, list):
        raise ASRProtocolError('MOSS Pro 结果 segments 不是数组', 'parse_failed')
    for row in segments:
        if not isinstance(row, dict):
            raise ASRProtocolError('MOSS Pro 句段格式非法', 'parse_failed')
        start, end = row.get('start'), row.get('end')
        if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float))
                or not isinstance(end, (int, float)) or not math.isfinite(start) or not math.isfinite(end)):
            raise ASRProtocolError('MOSS Pro 句段时间缺失或非法', 'invalid_timing')
        if not 0 <= start <= end <= duration + 1.0:
            raise ASRProtocolError('MOSS Pro 句段时间越出提交的音频', 'invalid_timing')


def result_rows(payload, *, offset: float, duration: float) -> list:
    """Provider segments -> reference rows on the task clock (offset added once)."""
    from .asr import _api_transcription_rows
    segments = []
    for row in payload.get('segments') or []:
        text = str(row.get('text') or '')
        if not text.strip():
            continue
        segment = {'start': float(row['start']), 'end': float(row['end']), 'text': text, 'confidence': 0.78}
        if row.get('speaker') not in (None, ''):
            segment['speaker'] = str(row['speaker'])
        segments.append(segment)
    converted = {'text': str(payload.get('text') or ''), 'segments': segments, 'words': [],
                 'timestamp_source': 'mosi_native'}
    return _api_transcription_rows(converted, dict(start=offset, end=offset + duration))


def submit(audio, endpoint, *, client, state_path: Path, state: dict, check=lambda: None) -> dict:
    """Upload one request's audio as multipart and create an async task.

    The body is streamed in blocks. requests sends a request body under the
    *connect* timeout, and one HTTPS write of a whole in-memory body must
    finish within it: a 1-hour WAV (110 MB) died after 15 s on a home uplink
    (2026-10-14). Streaming applies that timeout to each block instead.
    """
    import requests
    from .asr import _pcm16_wav_bytes
    from .dashscope_service import ServiceProblem, _MultipartBody
    wav = _pcm16_wav_bytes(audio)
    if len(wav) > MAX_UPLOAD_BYTES:
        raise ASRProtocolError('本段音频超过 MOSI 512 MB 上传限制。', 'too_large')
    fields = {'model': MODEL, 'diarize': 'true', 'async': 'true', 'response_format': 'json'}
    terms = list(endpoint.get('mosi_keyterms') or [])
    if terms:
        fields['keyterms'] = json.dumps(terms, ensure_ascii=False)
    form = _MultipartBody(list(fields.items()), 'audio.wav', wav, file_type='audio/wav')
    check()
    state.update(status='SUBMITTING', bytes=len(wav), created_at=time.time())
    _save(state_path, state)
    try:
        response = client.post(transcriptions_url(endpoint['url']),
                               headers={**_auth(endpoint), 'Content-Type': form.content_type,
                                        'Content-Length': str(len(form))},
                               data=form, timeout=UPLOAD_TIMEOUT, allow_redirects=False)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        sent = form.tell()
        if sent < len(form):
            # The closing boundary never left this process, so MOSI has no
            # complete request: nothing was accepted or billed. The next
            # attempt uploads again without asking.
            state.update(status='UPLOAD_INCOMPLETE', transport_error=type(exc).__name__,
                         sent_bytes=sent, body_bytes=len(form))
            _save(state_path, state)
            message = (f'上传到 MOSI 时网络中断（已送出 {sent / 1048576:.0f} / {len(form) / 1048576:.0f} MB），'
                       'MOSI 没有收到完整音频，不会受理也不会计费。')
            error = ASRProtocolError(message, 'upload_interrupted')
            error.problem = ServiceProblem('network', message, '检查网络后直接重新开始识别即可。',
                                           code='upload_interrupted')
            raise error from exc
        state.update(status='SUBMITTING', transport_error=type(exc).__name__)
        _save(state_path, state)
        raise ASRProtocolError('上传时网络中断，无法确认 MOSI 是否已受理（可能已计费）。'
                               '为避免重复收费，没有自动重新提交；请到 MOSI 控制台核对后再重试。',
                               'submission_uncertain') from exc
    if response.status_code not in (200, 201, 202):
        body = _json(response)
        category, message = classify_http_error(response.status_code, body)
        definitive = response.status_code in {400, 401, 402, 403, 404, 409, 413, 415, 422, 429}
        state.update(status='REJECTED' if definitive else 'SUBMITTING', http_status=response.status_code,
                     category=category)
        _save(state_path, state)
        if not definitive:
            message += '服务器可能已受理，已阻止自动重复提交。'
            category = 'submission_uncertain'
        raise ASRProtocolError(message, category)
    body = _json(response)
    task_id = str(body.get('task_id') or body.get('id') or '')
    if not task_id:
        state.update(status='SUBMITTING', http_status=response.status_code)
        _save(state_path, state)
        raise ASRProtocolError('MOSI 回应缺少任务编号，无法确认是否受理；已阻止自动重复提交。', 'submission_uncertain')
    retry_after = body.get('retry_after')
    state.update(task_id=task_id, status=str(body.get('status') or 'PENDING'),
                 retry_after=int(retry_after) if isinstance(retry_after, (int, float)) else None,
                 submitted_at=time.time())
    _save(state_path, state)
    return state


def poll(endpoint, *, client, state_path: Path, state: dict, duration: float, check=lambda: None,
         progress=lambda *a: None, sleep=time.sleep, max_wait: float = 7200.0) -> dict:
    deadline = time.monotonic() + max_wait
    interval = min(10.0, max(2.0, float(state.get('retry_after') or 3)))
    while True:
        check()
        if time.monotonic() >= deadline:
            raise ASRProtocolError('本地等待达到时限；任务编号已保存，下次会继续查询原任务。', 'poll_timeout')
        response = client.get(task_url(endpoint['url'], state['task_id']), headers=_auth(endpoint),
                              timeout=(10, 60), allow_redirects=False)
        body = _json(response)
        if response.status_code == 404:
            state.update(status='UNKNOWN', last_poll_at=time.time())
            _save(state_path, state)
            raise ASRProtocolError('MOSI 查不到这个任务（task_not_found）；未自动重新提交。', 'remote_unknown')
        if response.status_code != 200:
            category, message = classify_http_error(response.status_code, body)
            raise ASRProtocolError(message + '任务编号已保存，未重新提交。', 'poll_failed' if category == 'server_error' else category)
        status = str(body.get('status') or '')
        if status not in STATUSES:
            raise ASRProtocolError(f'MOSI 返回了未知任务状态：{status or "空"}', 'invalid_response')
        state.update(status=status, last_poll_at=time.time())
        _save(state_path, state)
        progress(status, 0, 1)
        if status == 'FAILED':
            from .provider_diagnostics import redact_diagnostics
            error = body.get('error') if isinstance(body.get('error'), dict) else {}
            state['remote_error'] = redact_diagnostics(json.dumps(error, ensure_ascii=False))[:500]
            _save(state_path, state)
            raise ASRProtocolError('MOSI 任务执行失败。是否扣积分请以 MOSI 控制台的积分账单为准（官方未写明）。', 'remote_terminal')
        if status == 'SUCCESS':
            validate_result(body, duration)
            return body
        steps = int(interval * 10)
        for _ in range(steps):
            check()
            sleep(.1)


def _chunk(audio, endpoint, root: Path, *, client, check, progress, sleep, max_wait, restart_terminal):
    root.mkdir(parents=True, exist_ok=True)
    state_path, raw_path = root / 'task.json', root / 'result.json'
    state = json.loads(state_path.read_text('utf8')) if state_path.is_file() else {}
    duration = len(audio) / 16000
    check()
    if raw_path.is_file():
        progress('cached_result', 0, 1)
        return json.loads(raw_path.read_text('utf8'))
    if state.get('status') == 'SUBMITTING' and not state.get('task_id'):
        if not restart_terminal:
            raise ASRProtocolError('上次上传是否被 MOSI 受理无法确认；为避免重复收费，需先到 MOSI 控制台核对，'
                                   '再在完成页选择“重试失败项”并确认重新提交。', 'submission_uncertain')
        # The user checked their account and explicitly chose to submit again.
        import uuid
        _save(root / ('previous-task-' + uuid.uuid4().hex + '.json'), state)
        state = {}
        progress('explicit_restart_uncertain', 0, 1)
    if state.get('status') == 'UPLOAD_INCOMPLETE' and not state.get('task_id'):
        # MOSI never received the whole file (see submit); upload again.
        import uuid
        _save(root / ('previous-task-' + uuid.uuid4().hex + '.json'), state)
        state = {}
        progress('retry_incomplete_upload', 0, 1)
    if state.get('status') in {'FAILED', 'UNKNOWN'}:
        if not restart_terminal:
            raise ASRProtocolError('已保存远端终态 ' + state['status'] + '；请显式重新开始识别。', 'remote_terminal')
        import uuid
        _save(root / ('previous-task-' + uuid.uuid4().hex + '.json'), state)
        state = {}
        progress('explicit_restart_terminal', 0, 1)
    if not state.get('task_id'):
        progress('uploading', 0, 1)
        state = submit(audio, endpoint, client=client, state_path=state_path, state=state, check=check)
    try:
        payload = poll(endpoint, client=client, state_path=state_path, state=state, duration=duration,
                       check=check, progress=progress, sleep=sleep, max_wait=max_wait)
    except BaseException:
        try:
            check()
        except BaseException:
            # No documented cancel endpoint: stopping here does not stop the
            # remote task, which may still finish and be billed.
            state['local_cancel_requested'] = True
            state['remote_cancel_supported'] = False
            _save(state_path, state)
            progress('local_cancel_remote_continues', 0, 1)
        raise
    _save(raw_path, payload)
    return payload


def transcribe(audio, endpoint, cache_root, *, client=None, check=lambda: None, progress=lambda *a: None,
               sleep=time.sleep, max_wait=7200.0, restart_terminal=False) -> list:
    """Run (or resume) all requests for the task audio; rows on the task clock."""
    import numpy as np
    from . import network_policy
    from .cloud_asr_jobs import job_root
    from .speaker_evidence import scope_request_speakers
    client = client or network_policy
    samples = np.asarray(audio)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ASRProtocolError('MOSS Pro 云端输入必须是有效的 16kHz 单声道音频。', 'input_limit')
    endpoint = dict(endpoint, url=normalize_api_base(endpoint.get('url')))
    root = job_root(audio, endpoint, cache_root)
    ranges = plan_ranges(audio)
    _save(root / 'plan.json', dict(model=MODEL, requests=[dict(start=s, end=e) for s, e in ranges],
                                   keyterms=endpoint.get('mosi_keyterms') or [],
                                   keyterms_dropped=endpoint.get('mosi_keyterms_dropped') or [],
                                   price_cny_per_hour=PRICE_CNY_PER_HOUR, price_checked=PRICE_CHECKED))
    rows = []
    for index, (start, end) in enumerate(ranges):
        def chunk_progress(state, _done, _total, index=index):
            progress(state, index, len(ranges))
        payload = _chunk(samples[start:end], endpoint, root / f'request-{index:03d}-{start}-{end}', client=client,
                         check=check, progress=chunk_progress, sleep=sleep, max_wait=max_wait,
                         restart_terminal=restart_terminal)
        converted = result_rows(payload, offset=start / 16000, duration=(end - start) / 16000)
        if any(row.get('speaker') is not None for row in converted):
            # Labels are only meaningful inside one request: S01 of request 1
            # and S01 of request 2 are not assumed to be the same person.
            converted = scope_request_speakers(converted, index, len(ranges))
        rows.extend(converted)
        progress('completed', index + 1, len(ranges))
    if len(ranges) > 1:
        _save(root / 'speaker-scope.json', dict(requests=len(ranges), cross_request_identity='unconfirmed',
              note='每段请求的说话人编号只在该段内有效；跨段是否同一人需要人工确认。'))
    return rows


# --- Setup-dialog checks (no audio unless explicitly requested) -------------

def check_key(endpoint, *, client=None) -> dict:
    """Connection + key validity + model availability via ``GET /models`` (free)."""
    import requests
    from . import network_policy
    client = client or network_policy
    base = normalize_api_base(endpoint.get('url'))
    result = {'connection': None, 'key_valid': None, 'model_available': None, 'message': '', 'models': []}
    try:
        response = client.get(models_url(base), headers=_auth(endpoint), timeout=(10, 30), allow_redirects=False)
    except ASRProtocolError as exc:
        result.update(message=str(exc))
        return result
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        result.update(connection=False, message=f'连不上 {base}：{type(exc).__name__}。请检查网络或代理。')
        return result
    result['connection'] = True
    body = _json(response)
    if response.status_code != 200:
        category, message = classify_http_error(response.status_code, body)
        result.update(key_valid=False if category == 'auth_failed' else None, message=message, category=category)
        return result
    models = [str(row.get('id')) for row in body.get('data') or [] if isinstance(row, dict)]
    result.update(key_valid=True, models=models, model_available=MODEL in models)
    result['message'] = ('API Key 有效，账户可用 ' + MODEL + '。' if MODEL in models else
                         'API Key 有效，但模型列表里没有 ' + MODEL + '；请在 MOSI 控制台确认已开通该模型。')
    return result
