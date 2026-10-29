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
import re
import threading
import time
from time import perf_counter as _phase_clock
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
# Requests of about 20 minutes (2026-10-23). A user's 40-minute request took
# MOSI 864 s every time (and once failed after 24 minutes); the same audio as
# two halves took 98 s and 168 s. Single requests of 16-24 minutes always came
# back within 2.5 minutes, so up to 25 minutes stays one request; longer audio
# is cut into equal parts of at most 22.5 minutes, each cut moved to the
# quietest second nearby.
SINGLE_REQUEST_SECONDS = 25 * 60
REQUEST_MAX_SECONDS = 22.5 * 60
# Requests MOSI has at the same time; it accepted four at once (2026-10-23).
PARALLEL_REQUESTS = 3
# A request MOSI's content review stopped is sent again only cut into pieces
# of about 3 minutes, and only when the user asks (2026-10-24): a block then
# costs a few minutes of subtitles instead of 20. Up to 4 minutes stays one
# piece, which is never sent again.
PIECE_SINGLE_SECONDS = 4 * 60
PIECE_SECONDS = 3 * 60
PIECE_SEARCH_SECONDS = 30
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
    chunks = max(1, math.ceil(seconds / REQUEST_MAX_SECONDS))
    return int(min(6 * 3600, max(3600, seconds * 2 + chunks * 1200)))


SEAM_SEARCH_SECONDS = 2 * 60
SEAM_FRAME = 3200          # 0.2 s at 16 kHz
SEAM_SMOOTH_FRAMES = 5     # quietest full second, not one quiet blip inside a word


def _quietest_cut(audio, lo: int, hi: int, default: int) -> int:
    """Middle of the quietest smoothed second in ``audio[lo:hi]``."""
    import numpy as np
    frames = (hi - lo) // SEAM_FRAME
    if frames <= SEAM_SMOOTH_FRAMES:
        return default
    window = np.asarray(audio[lo:lo + frames * SEAM_FRAME], dtype=np.float64).reshape(frames, SEAM_FRAME)
    energy = np.mean(window * window, axis=1)
    smooth = np.convolve(energy, np.ones(SEAM_SMOOTH_FRAMES) / SEAM_SMOOTH_FRAMES, mode='valid')
    best = int(np.argmin(smooth)) + SEAM_SMOOTH_FRAMES // 2
    return lo + best * SEAM_FRAME + SEAM_FRAME // 2


def plan_ranges(audio, *, single_seconds=None, max_seconds=None, search_seconds=None):
    """Sample ranges for requests: one up to ``single_seconds`` (25 minutes),
    else equal parts of at most ``max_seconds`` (22.5 minutes).

    Each cut is moved to the quietest second within ``search_seconds`` (two
    minutes, at most a quarter part) of its target, and no request grows past
    one part plus that margin. Game audio rarely has true silence, so the
    quietest point is chosen relative to its surroundings rather than against
    a fixed threshold. Ranges are contiguous: every sample belongs to exactly
    one request, and every request stays far below the official 60-minute
    limit.
    """
    samples = len(audio)
    single = (SINGLE_REQUEST_SECONDS if single_seconds is None else single_seconds) * 16000
    if samples <= single:
        return [(0, samples)]
    longest = (REQUEST_MAX_SECONDS if max_seconds is None else max_seconds) * 16000
    count = math.ceil(samples / longest)
    part = samples / count
    search = int(min((SEAM_SEARCH_SECONDS if search_seconds is None else search_seconds) * 16000, part / 4))
    edges = [0]
    for k in range(1, count):
        target = int(round(k * part))
        lo = max(edges[-1] + 16000, target - search)
        hi = min(samples - 16000, target + search, int(edges[-1] + part + search))
        edges.append(_quietest_cut(audio, lo, hi, target))
    edges.append(samples)
    return list(zip(edges, edges[1:]))


def classify_http_error(status_code: int, body) -> tuple[str, str]:
    """(category, user message) for a non-success response."""
    error = body.get('error') if isinstance(body, dict) else None
    code = str((error or {}).get('code') or (error or {}).get('type') or '')
    if code == 'safety_guardrail_blocked':
        return 'content_rejected', (f'MOSI 的内容安全审查拦下了这段音频（HTTP {status_code}：safety_guardrail_blocked），'
                                    '没有受理。')
    if status_code in (401, 403) and code != 'url_not_allowed':
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


def validate_result(payload) -> None:
    """The result's shape. Times are checked per segment by ``usable_segments``."""
    if not isinstance(payload, dict):
        raise ASRProtocolError('MOSS Pro 结果不是 JSON 对象', 'parse_failed')
    segments = payload.get('segments')
    if segments is not None and not isinstance(segments, list):
        raise ASRProtocolError('MOSS Pro 结果 segments 不是数组', 'parse_failed')


# Ends up to this far past the request's audio are MOSI's usual rounding:
# clipped without a note.
END_TOLERANCE_SECONDS = 1.0
REPAIR_KINDS = ('clipped', 'outside', 'reversed', 'invalid')


def _seconds(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def usable_segments(payload, duration: float) -> tuple[list, dict]:
    """The result's segments with text, placed inside the request's audio,
    and what was changed (``REPAIR_KINDS`` counts plus a few examples).

    MOSI can finish a task with a few segments timed past the end of the
    audio it was given, or with a reversed or missing time (2026-10-25: a
    user's English singing stream). 0.8.4 failed the whole task on one such
    segment, and as the result was never kept, every retry read the same
    result and failed again. An end past the audio is clipped to it; a
    segment that lies outside the audio, ends before it starts or has no
    usable time is left out, never moved (that would invent timing). Raises
    only when not one segment with text can be placed.
    """
    kept, examples = [], []
    repair = dict(segments=0, audio_seconds=round(float(duration), 3), latest_end=None,
                  **{kind: 0 for kind in REPAIR_KINDS})
    for row in payload.get('segments') or []:
        if not isinstance(row, dict):
            repair['segments'] += 1
            repair['invalid'] += 1
            continue
        if not str(row.get('text') or '').strip():
            continue
        repair['segments'] += 1
        start, end = row.get('start'), row.get('end')
        if not (_seconds(start) and _seconds(end)):
            kind = 'invalid'
        else:
            start, end = float(start), float(end)
            latest = repair['latest_end']
            repair['latest_end'] = round(end if latest is None else max(latest, end), 3)
            if end < start:
                kind = 'reversed'
            elif start >= duration - .02 or end <= 0:
                kind = 'outside'
            else:
                kind = ('clipped' if end > duration + END_TOLERANCE_SECONDS or start < -END_TOLERANCE_SECONDS
                        else '')
                kept.append(dict(row, start=max(0.0, start), end=min(float(duration), end)))
        if kind:
            repair[kind] += 1
            if len(examples) < 5:
                examples.append(dict(kind=kind, start=row.get('start'), end=row.get('end'),
                                     text=str(row.get('text') or '')[:60]))
    if repair['segments'] and not kept:
        first = examples[0] if examples else {}
        raise ASRProtocolError(
            f'MOSS Pro 返回的 {repair["segments"]} 句都没有落在这段音频里的时间（第一句 {first.get("start")!r}–'
            f'{first.get("end")!r} 秒，这段音频 {float(duration):.1f} 秒）；多半是服务商的结果格式变了，'
            '原样重试不会好转，请回报问题。', 'invalid_timing')
    repair['examples'] = examples
    return kept, repair


def timing_changed(repair: dict) -> bool:
    return any(repair.get(kind) for kind in REPAIR_KINDS)


def _record_event(kind: str, **payload) -> None:
    """A run event (forwarded by the cloud worker); never breaks a request."""
    try:
        import sys
        core = sys.modules.get('subtitle_core')
        recorder = getattr(core, 'record_run_event', None) if core is not None else None
        if not callable(recorder):
            from ..recognition.cache import record_run_event as recorder
        recorder(kind, **payload)
    except Exception:
        pass


def _clock(seconds: float) -> str:
    total = int(round(max(0.0, float(seconds))))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'


def segment_label(segment) -> str:
    """'第 2 / 2 段（55:59–1:36:04）' when the task was split; '' for one request."""
    if not segment or int(segment[1]) <= 1:
        return ''
    index, total, start, end = segment
    return f'第 {int(index)} / {int(total)} 段（{_clock(start)}–{_clock(end)}）'


def remote_reason(body) -> str:
    """MOSI's own words for a FAILED task; '' when it gave none.

    The task query docs only say ``error`` holds the failure information; the
    example is an empty object and no codes are listed (checked 2026-10-23).
    A string ``error`` was dropped before. A real failure (2026-10-24) used
    ``error_msg`` / ``error_code`` and ``internal_error_msg`` /
    ``internal_error_code``.
    """
    from .provider_diagnostics import redact_diagnostics
    error = body.get('error') if isinstance(body, dict) else None
    text = ''
    if isinstance(error, dict):
        words = [str(error[key]).strip() for key in ('message', 'msg', 'error_msg', 'internal_error_msg', 'detail', 'reason')
                 if error.get(key) not in (None, '')]
        codes = [str(error[key]).strip() for key in ('code', 'type', 'error_code', 'internal_error_code')
                 if error.get(key) not in (None, '')]
        text = '；'.join(dict.fromkeys(words))
        if codes:
            code = '，'.join(dict.fromkeys(codes))
            text = f'{text}（{code}）' if text else code
        if not text and error:
            text = json.dumps(error, ensure_ascii=False)
    elif error not in (None, ''):
        text = str(error)
    if not text and isinstance(body, dict):
        text = str(body.get('message') or '')
    return str(redact_diagnostics(' '.join(text.split())))[:300]


def _saved_reason(state: dict) -> str:
    try:
        error = json.loads(state.get('remote_error') or '{}')
    except ValueError:
        # Cut at 500 characters: keep what was worked out at the time.
        return str(state.get('remote_reason') or state.get('remote_error') or '')
    # Worked out again from MOSI's own ``error`` (all that tasks saved before
    # 2026-10-23 kept), so a task saved by an older version also shows fields
    # learned later: 0.8.4 showed error_msg / error_code as raw JSON.
    return remote_reason({'error': error}) or str(state.get('remote_reason') or '')


# MOSI's content safety review (2026-10-24, a user's English game stream):
# one request of a task ended FAILED with {"error_code": 17001, "error_msg":
# "safety policy error", "internal_error_code": 111111004,
# "internal_error_msg": "safety guardrail blocked"}. The error-code page lists
# safety_guardrail_blocked as "被安全策略拦截". The same audio sent again
# meets the same review, so a retry is not suggested.
_GUARDRAIL = re.compile(r'safety[ _]?(guardrail|policy)', re.I)


def guardrail_blocked(error) -> bool:
    """Whether MOSI's content safety review stopped the request."""
    if isinstance(error, (dict, list)):
        error = json.dumps(error, ensure_ascii=False)
    return bool(_GUARDRAIL.search(str(error or '')))


def content_blocked(state: dict) -> bool:
    """A saved request the safety review stopped: FAILED after MOSI took it
    (also tasks saved before 2026-10-24, which kept only the ``error`` JSON),
    or refused at upload."""
    if state.get('status') == 'REJECTED':
        return state.get('category') == 'content_rejected'
    return state.get('status') == 'FAILED' and bool(state.get('remote_blocked') or guardrail_blocked(
        state.get('remote_error')) or guardrail_blocked(state.get('remote_reason')))


def failure_detail(state: dict, segment=None) -> str:
    """Which request failed, its task id and MOSI's reason, in one sentence."""
    where = segment_label(segment)
    task = f'（任务编号 {state["task_id"]}）' if state.get('task_id') else ''
    subject = f'{where}的 MOSI 任务{task}' if where else f'MOSI 任务{task}'
    if state.get('status') == 'UNKNOWN':
        return f'{subject}在 MOSI 查不到（不存在或已超过保留期）。'
    reason = _saved_reason(state)
    if content_blocked(state):
        return (f'{subject}被 MOSI 的内容安全审查拦下，没有返回这一段的字幕'
                f'（MOSI 返回的原因：{reason or "safety_guardrail_blocked"}）。')
    return (f'{subject}执行失败，MOSI 返回的原因：{reason}。' if reason else
            f'{subject}执行失败，MOSI 没有说明原因。')


def gap_row(start: int, end: int, state: dict, segment) -> dict:
    """A request MOSI's content review stopped, as a marker among the result
    rows (2026-10-24): the task finishes with this range uncovered instead of
    failing, and the pipeline fills it with a local model."""
    index, total = (segment or (1, 1))[:2]
    return {'start': start / 16000, 'end': end / 16000, 'text': '',
            'cloud_gap': {'provider': PROVIDER, 'reason': 'content_blocked', 'segment': [int(index), int(total)],
                          'task_id': str(state.get('task_id') or ''), 'provider_reason': _saved_reason(state),
                          'detail': failure_detail(state, segment),
                          'resplittable': end - start > PIECE_SINGLE_SECONDS * 16000}}


def _remote_error(message: str, category: str, state: dict, segment) -> ASRProtocolError:
    error = ASRProtocolError(message, category)
    error.remote_detail = failure_detail(state, segment)
    return error


def result_rows(payload, *, offset: float, duration: float) -> list:
    """Provider segments -> reference rows on the task clock (offset added once)."""
    from ..recognition.asr import _api_transcription_rows
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


def submit(audio, endpoint, *, client, state_path: Path, state: dict, check=lambda: None,
           upload_progress=None) -> dict:
    """Upload one request's audio as multipart and create an async task.

    The body is streamed in blocks. requests sends a request body under the
    *connect* timeout, and one HTTPS write of a whole in-memory body must
    finish within it: a 1-hour WAV (110 MB) died after 15 s on a home uplink
    (2026-10-14). Streaming applies that timeout to each block instead.
    """
    import requests
    from ..recognition.asr import _pcm16_wav_bytes
    from .dashscope_service import ServiceProblem, _MultipartBody
    wav = _pcm16_wav_bytes(audio)
    if len(wav) > MAX_UPLOAD_BYTES:
        raise ASRProtocolError('本段音频超过 MOSI 512 MB 上传限制。', 'too_large')
    fields = {'model': MODEL, 'diarize': 'true', 'async': 'true', 'response_format': 'json'}
    terms = list(endpoint.get('mosi_keyterms') or [])
    if terms:
        fields['keyterms'] = json.dumps(terms, ensure_ascii=False)
    form = _MultipartBody(list(fields.items()), 'audio.wav', wav, upload_progress, file_type='audio/wav')
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
        if category == 'content_rejected':
            state['remote_reason'] = f'safety_guardrail_blocked（HTTP {response.status_code}）'
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
         progress=lambda *a: None, sleep=time.sleep, max_wait: float = 7200.0, segment=None, timings=None) -> dict:
    """Wait for one submitted task. Each state reaches ``progress`` with a
    fourth argument: how long MOSI has had the task (from the original
    submission, also across runs) and the request's audio length, so the
    window can say a wait is unusually long (2026-10-23)."""
    deadline = time.monotonic() + max_wait
    interval = min(10.0, max(2.0, float(state.get('retry_after') or 3)))
    submitted = float(state.get('submitted_at') or time.time())
    while True:
        check()
        if time.monotonic() >= deadline:
            raise ASRProtocolError('本地等待达到时限；任务编号已保存，下次会继续查询原任务。', 'poll_timeout')
        request_started = _phase_clock()
        response = client.get(task_url(endpoint['url'], state['task_id']), headers=_auth(endpoint),
                              timeout=(10, 60), allow_redirects=False)
        if timings is not None:
            timings['poll_requests'] += 1
            timings['poll_http_seconds'] += _phase_clock() - request_started
        body = _json(response)
        if response.status_code == 404:
            state.update(status='UNKNOWN', last_poll_at=time.time())
            _save(state_path, state)
            raise _remote_error('MOSI 查不到这个任务（task_not_found）；未自动重新提交。', 'remote_unknown', state, segment)
        if response.status_code != 200:
            category, message = classify_http_error(response.status_code, body)
            raise ASRProtocolError(message + '任务编号已保存，未重新提交。', 'poll_failed' if category == 'server_error' else category)
        status = str(body.get('status') or '')
        if status not in STATUSES:
            raise ASRProtocolError(f'MOSI 返回了未知任务状态：{status or "空"}', 'invalid_response')
        state.update(status=status, last_poll_at=time.time())
        details = dict(remote_waited_seconds=round(max(0.0, time.time() - submitted), 1),
                       request_audio_seconds=round(float(duration), 1))
        if status == 'FAILED':
            from .provider_diagnostics import redact_diagnostics
            error = body.get('error')
            state['remote_error'] = redact_diagnostics(json.dumps({} if error is None else error, ensure_ascii=False))[:500]
            state['remote_reason'] = details['remote_reason'] = remote_reason(body)
            state['remote_blocked'] = guardrail_blocked(error)
        _save(state_path, state)
        progress(status, 0, 1, details)
        if status == 'FAILED':
            detail = failure_detail(state, segment)
            raise _remote_error(detail + '是否扣积分请以 MOSI 控制台的积分账单为准（官方未写明）。',
                                'content_blocked' if content_blocked(state) else 'remote_terminal', state, segment)
        if status == 'SUCCESS':
            validate_result(body)
            return body
        steps = int(interval * 10)
        waiting = _phase_clock()
        for _ in range(steps):
            check()
            sleep(.1)
        if timings is not None:
            timings['poll_sleep_seconds'] += _phase_clock() - waiting


def _load_state(root: Path) -> dict:
    path = root / 'task.json'
    try:
        return json.loads(path.read_text('utf8')) if path.is_file() else {}
    except ValueError:
        return {}


def _prepared_state(root: Path, *, progress, restart_terminal, segment=None) -> dict:
    """The request's saved state, ready to resume or submit. Raises when the
    request must not be sent again without the user's confirmation."""
    root.mkdir(parents=True, exist_ok=True)
    state = _load_state(root)
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
    if content_blocked(state):
        # Never sent again unchanged, confirmed or not (2026-10-24): only cut
        # into pieces (``resplit_blocked``), which are requests of their own.
        raise _remote_error('已保存远端终态 ' + state['status'] + '：' + failure_detail(state, segment),
                            'content_blocked', state, segment)
    if state.get('status') in {'FAILED', 'UNKNOWN'}:
        if not restart_terminal:
            raise _remote_error('已保存远端终态 ' + state['status'] + '：' + failure_detail(state, segment)
                                + '请显式重新开始识别。', 'remote_terminal', state, segment)
        import uuid
        _save(root / ('previous-task-' + uuid.uuid4().hex + '.json'), state)
        state = {}
        progress('explicit_restart_terminal', 0, 1)
    return state


# Wait before asking again when MOSI already has as many requests as it takes.
RATE_LIMIT_RETRY_SECONDS = 20


def _submit_request(audio, endpoint, root: Path, state: dict, *, client, check, progress, sleep, max_wait, timings=None) -> dict:
    """Upload the request unless MOSI already has it.

    HTTP 429 means MOSI already has as many requests as it takes; nothing was
    accepted or billed, so it is asked again shortly instead of failing the
    task (2026-10-23).
    """
    if state.get('task_id'):
        return state
    deadline = time.monotonic() + max_wait
    while True:
        check()
        progress('uploading', 0, 1)
        began = _phase_clock()
        if timings is not None:
            timings['submit_requests'] += 1
        try:
            return submit(audio, endpoint, client=client, state_path=root / 'task.json', state=state, check=check,
                          upload_progress=lambda sent, total: progress('upload_bytes', sent, total))
        except ASRProtocolError as exc:
            if exc.category != 'rate_limited' or time.monotonic() >= deadline:
                raise
        finally:
            if timings is not None:
                timings['encode_upload_submit_seconds'] += _phase_clock() - began
                timings['upload_bytes'] = int(state.get('bytes') or 0)
        progress('waiting_for_slot', 0, 1)
        for _ in range(int(RATE_LIMIT_RETRY_SECONDS * 10)):
            check()
            sleep(.1)


def _wait_request(audio, endpoint, root: Path, state: dict, *, client, check, progress, sleep, max_wait,
                  segment=None, timings=None) -> dict:
    """Wait for a request MOSI has; keep and account its result."""
    state_path, raw_path = root / 'task.json', root / 'result.json'
    duration = len(audio) / 16000
    began = _phase_clock()
    try:
        payload = poll(endpoint, client=client, state_path=state_path, state=state, duration=duration,
                       check=check, progress=progress, sleep=sleep, max_wait=max_wait, segment=segment,
                       **({'timings': timings} if timings is not None else {}))
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
    finally:
        if timings is not None:
            timings['remote_wait_and_result_seconds'] = _phase_clock() - began
    _save(raw_path, payload)
    from .api_usage import record_api_call
    record_api_call(stage='asr', provider=endpoint.get('provider', ''), model=MODEL, request_mode='mosi_async',
                    usage=payload.get('usage') if isinstance(payload, dict) else None)
    return payload


def _chunk(audio, endpoint, root: Path, *, client, check, progress, sleep, max_wait, restart_terminal, segment=None):
    """One request on its own: cached result, or resume / submit and wait."""
    check()
    if (root / 'result.json').is_file():
        progress('cached_result', 0, 1)
        return json.loads((root / 'result.json').read_text('utf8'))
    state = _prepared_state(root, progress=progress, restart_terminal=restart_terminal, segment=segment)
    state = _submit_request(audio, endpoint, root, state, client=client, check=check, progress=progress, sleep=sleep,
                            max_wait=max_wait)
    return _wait_request(audio, endpoint, root, state, client=client, check=check, progress=progress, sleep=sleep,
                         max_wait=max_wait, segment=segment)


def _request_dir(root: Path, index: int, start: int, end: int) -> Path:
    """A request's folder, found by its sample range: a task planned again
    numbers its requests differently, and a finished request must still be
    found (never uploaded and billed twice)."""
    for found in sorted(root.glob(f'request-*-{start}-{end}')):
        if found.is_dir():
            return found
    return root / f'request-{index:03d}-{start}-{end}'


def _request_ranges(samples, root: Path, restart_terminal: bool, resplit_blocked: bool = False) -> list:
    """Requests for this task.

    A task planned before (until 2026-10-23 in pieces of about 55 minutes)
    keeps every request MOSI has finished or still has, so nothing is
    uploaded or billed twice, and keeps failed or uncertain ones until the
    user confirms resubmitting them. Everything else is planned in the
    current, shorter requests. A request the content review stopped stays as
    it is, unless the user asked to send it again in pieces
    (``resplit_blocked``, 2026-10-24).
    """
    fresh = plan_ranges(samples)
    try:
        saved = [(int(row['start']), int(row['end']))
                 for row in json.loads((root / 'plan.json').read_text('utf8'))['requests']]
    except (OSError, ValueError, KeyError, TypeError):
        return fresh
    if (not saved or (saved == fresh and not resplit_blocked) or saved[0][0] != 0 or saved[-1][1] != len(samples)
            or any(a[1] != b[0] for a, b in zip(saved, saved[1:]))):
        return fresh
    ranges = []
    for index, (start, end) in enumerate(saved):
        folder = _request_dir(root, index, start, end)
        state = _load_state(folder)
        if content_blocked(state):
            if resplit_blocked and end - start > PIECE_SINGLE_SECONDS * 16000:
                ranges.extend((start + a, start + b) for a, b in plan_ranges(
                    samples[start:end], single_seconds=PIECE_SINGLE_SECONDS, max_seconds=PIECE_SECONDS,
                    search_seconds=PIECE_SEARCH_SECONDS))
            else:
                ranges.append((start, end))
            continue
        status = state.get('status')
        blocked = status in {'FAILED', 'UNKNOWN'} or (status == 'SUBMITTING' and not state.get('task_id'))
        if ((folder / 'result.json').is_file() or (state.get('task_id') and not blocked)
                or (blocked and not restart_terminal)):
            ranges.append((start, end))
        else:
            ranges.extend((start + a, start + b) for a, b in plan_ranges(samples[start:end]))
    return ranges


class _Board:
    """All requests of one task as one picture for the progress card
    (2026-10-23): which requests MOSI has, how many are done, the longest
    wait, and the upload in progress. Every report of any request goes out as
    this picture, so parallel requests do not make the card flicker."""
    WAITING = {'PENDING', 'PROCESSING'}

    def __init__(self, total, progress):
        self.total, self.progress = total, progress
        self.lock = threading.Lock()
        self.done, self.waits, self.upload = set(), {}, None

    def _summary(self):
        now = time.monotonic()
        summary = dict(active_requests=[index + 1 for index in sorted(self.waits)])
        if self.waits:
            longest = max(self.waits, key=lambda i: self.waits[i]['waited'] + now - self.waits[i]['at'])
            row = self.waits[longest]
            summary.update(remote_waited_seconds=round(row['waited'] + now - row['at'], 1),
                           request_audio_seconds=row['audio'])
        return summary

    def report(self, index, state, done=0, total=0, details=None):
        with self.lock:
            details = dict(details or {})
            if state not in {'upload_bytes', 'uploading'} and self.upload is not None and self.upload[0] == index:
                self.upload = None  # that upload ended (accepted, refused or interrupted)
            if state == 'upload_bytes':
                self.upload = (index, done, total)
            elif state in self.WAITING:
                self.waits[index] = dict(status=state, at=time.monotonic(),
                                         waited=float(details.pop('remote_waited_seconds', 0) or 0),
                                         audio=float(details.pop('request_audio_seconds', 0) or 0))
            elif state in {'SUCCESS', 'FAILED', 'local_cancel_remote_continues'}:
                self.waits.pop(index, None)
            elif state == 'completed':
                self.done.add(index)
            summary = dict(details, **self._summary())
            if self.upload is not None:
                summary.update(upload_request=self.upload[0] + 1, completed_batches=len(self.done),
                               total_batches=self.total)
                self.progress('upload_bytes', self.upload[1], self.upload[2], summary)
            elif state in self.WAITING or (self.waits and state in {'completed', 'SUCCESS', 'cached_result'}):
                # While other requests still wait, a finished one shows in 已返回批次;
                # the card keeps the waiting picture (no "已完成 2 / 3 段" mid-task).
                waiting = {row['status'] for row in self.waits.values()}
                self.progress('PROCESSING' if 'PROCESSING' in waiting else 'PENDING', len(self.done), self.total,
                              summary)
            else:
                self.progress(state, len(self.done), self.total, summary)


def transcribe(audio, endpoint, cache_root, *, client=None, check=lambda: None, progress=lambda *a: None,
               sleep=time.sleep, max_wait=7200.0, restart_terminal=False, on_rows=None,
               parallel=PARALLEL_REQUESTS, resplit_blocked=False, on_timing=None) -> list:
    """Run (or resume) all requests for the task audio; rows on the task clock.

    Requests are uploaded in order, one at a time, while at most ``parallel``
    are with MOSI (2026-10-23); results come back in any order. After an
    error nothing new is submitted, but every request MOSI already has is
    waited for, so its result is kept for a retry; then the first error is
    raised. A request that must not be resent without confirmation stops the
    task before anything new is uploaded.

    A request MOSI's content review stops (now or in a saved state) is no
    error (2026-10-24): the others go on, and the request comes back as a
    ``gap_row`` marker in its place. ``resplit_blocked`` sends stopped
    requests again in pieces of about 3 minutes.
    """
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor
    from . import network_policy
    from .cloud_asr_jobs import job_root
    from ..recognition.speaker_evidence import scope_request_speakers
    client = client or network_policy
    samples = np.asarray(audio)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ASRProtocolError('MOSS Pro 云端输入必须是有效的 16kHz 单声道音频。', 'input_limit')
    endpoint = dict(endpoint, url=normalize_api_base(endpoint.get('url')))
    root = job_root(audio, endpoint, cache_root)
    ranges = _request_ranges(samples, root, restart_terminal, resplit_blocked)
    total = len(ranges)
    _save(root / 'plan.json', dict(model=MODEL, requests=[dict(start=s, end=e) for s, e in ranges],
                                   keyterms=endpoint.get('mosi_keyterms') or [],
                                   keyterms_dropped=endpoint.get('mosi_keyterms_dropped') or [],
                                   price_cny_per_hour=PRICE_CNY_PER_HOUR, price_checked=PRICE_CHECKED))
    board = _Board(total, progress)
    lock = threading.Lock()
    converted = [None] * total
    timings = [dict(provider=PROVIDER, model=MODEL, request_index=i, request_total=total,
                    audio_seconds=(end-start)/16000, cache_hit=False, submit_requests=0, poll_requests=0,
                    poll_http_seconds=0.0, poll_sleep_seconds=0.0, encode_upload_submit_seconds=0.0,
                    remote_processing_seconds=None, _started=_phase_clock()) for i,(start,end) in enumerate(ranges)]

    def timing(index, outcome, error=None):
        if on_timing is None:
            return
        info = {key: value for key,value in timings[index].items() if not key.startswith('_')}
        info.update(outcome=outcome, wall_seconds=_phase_clock()-timings[index]['_started'])
        if error is not None:
            info['failure_category'] = str(getattr(error, 'category', type(error).__name__))
        on_timing({key: round(value, 6) if isinstance(value, float) else value for key,value in info.items()})

    def finish(index, folder, payload):
        start, end = ranges[index]
        segment = (index + 1, total, start / 16000, end / 16000)
        try:
            kept, repair = usable_segments(payload, (end - start) / 16000)
        except ASRProtocolError as exc:
            where = segment_label(segment)
            raise ASRProtocolError((where + '：' if where else '') + str(exc), exc.category) from None
        if timing_changed(repair):
            # MOSI's own result stays in result.json; what was clipped or
            # left out is kept beside it and reported (2026-10-25).
            _save(folder / 'timing-repair.json', dict(repair, segment=[index + 1, total],
                                                      range=[start / 16000, end / 16000]))
            _record_event('cloud_asr_timing_repaired', provider=PROVIDER, segment=[index + 1, total],
                          start=round(start / 16000, 3), end=round(end / 16000, 3),
                          **{key: value for key, value in repair.items() if key != 'examples'})
        rows = result_rows(dict(payload, segments=kept), offset=start / 16000, duration=(end - start) / 16000)
        if any(row.get('speaker') is not None for row in rows):
            # Labels are only meaningful inside one request: S01 of request 1
            # and S01 of request 2 are not assumed to be the same person.
            rows = scope_request_speakers(rows, index, total)
        with lock:
            converted[index] = rows
            if on_rows is not None:
                on_rows(index, total, rows)
        board.report(index, 'completed')

    def blocked(index, folder, segment):
        # The content review stopped this request: a gap, the task goes on.
        start, end = ranges[index]
        with lock:
            converted[index] = [gap_row(start, end, _load_state(folder), segment)]
        board.report(index, 'completed')

    jobs = []
    for index, (start, end) in enumerate(ranges):
        check()
        folder = _request_dir(root, index, start, end)
        segment = (index + 1, total, start / 16000, end / 16000)
        note = (lambda state, done=0, size=0, details=None, index=index: board.report(index, state, done, size, details))
        if (folder / 'result.json').is_file():
            note('cached_result')
            timings[index]['cache_hit'] = True
            finish(index, folder, json.loads((folder / 'result.json').read_text('utf8')))
            timing(index, 'completed')
            continue
        try:
            state = _prepared_state(folder, progress=note, restart_terminal=restart_terminal, segment=segment)
        except ASRProtocolError as exc:
            if exc.category != 'content_blocked':
                timing(index, 'failed', exc)
                raise
            blocked(index, folder, segment)
            timing(index, 'blocked', exc)
            continue
        jobs.append((index, folder, segment, note, state))
    errors, places = [], threading.Semaphore(max(1, int(parallel)))

    def wait(job, state):
        index, folder, segment, note, _ = job
        start, end = ranges[index]
        try:
            finish(index, folder, _wait_request(samples[start:end], endpoint, folder, state, client=client,
                                                check=check, progress=note, sleep=sleep, max_wait=max_wait,
                                                segment=segment, **({'timings':timings[index]} if on_timing else {})))
            timing(index, 'completed')
        except ASRProtocolError as exc:
            if exc.category == 'content_blocked':
                blocked(index, folder, segment)
                timing(index, 'blocked', exc)
            else:
                timing(index, 'failed', exc)
                with lock:
                    errors.append(exc)
        except BaseException as exc:  # noqa: BLE001 - every request is waited for; the first error is raised
            timing(index, 'failed', exc)
            with lock:
                errors.append(exc)
        finally:
            places.release()

    with ThreadPoolExecutor(max_workers=max(1, min(int(parallel), len(jobs) or 1)),
                            thread_name_prefix='mosi-request') as pool:
        for job in jobs:
            index, folder, segment, note, state = job
            start, end = ranges[index]
            try:
                while not places.acquire(timeout=.1):  # a free place with MOSI
                    check()
                if errors:
                    places.release()
                    break
                try:
                    state = _submit_request(samples[start:end], endpoint, folder, state, client=client, check=check,
                                            progress=note, sleep=sleep, max_wait=max_wait,
                                            **({'timings':timings[index]} if on_timing else {}))
                except BaseException:
                    places.release()
                    raise
            except ASRProtocolError as exc:
                if exc.category == 'content_rejected':
                    # Refused at upload by the same review: a gap like a block.
                    blocked(index, folder, segment)
                    timing(index, 'blocked', exc)
                    continue
                timing(index, 'failed', exc)
                with lock:
                    errors.append(exc)
                break
            except BaseException as exc:  # noqa: BLE001 - recorded; requests MOSI has are still waited for
                timing(index, 'failed', exc)
                with lock:
                    errors.append(exc)
                break
            pool.submit(wait, job, state)
    if errors:
        raise errors[0]
    if total > 1:
        _save(root / 'speaker-scope.json', dict(requests=total, cross_request_identity='unconfirmed',
              note='每段请求的说话人编号只在该段内有效；跨段是否同一人需要人工确认。'))
    return [row for rows in converted for row in rows]


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
