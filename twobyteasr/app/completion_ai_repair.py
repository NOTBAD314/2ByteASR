"""兔白处理: fix the completion page's open items without opening Studio.

2026-11-17 (user): 「让AI遇到这些问题后也能自主分析并修复……能在识别结束页
解决就别在工作台解决」. 2026-11-21 the user chose design 乙1 (a bunny bubble in
the result card). Decisions: D1 a button, counts and an estimate first; D2
changes are written directly, each can be undone and the whole run restored;
D3 heard-again speech uses another ready model, local first.

The program routes each kind of item to one known fix; the text AI only judges
inside a kind (which reading, is it speech, where to cut). Everything happens
on a detached copy of the saved project. Nothing is written until the run ends
uncancelled; the original file is copied byte for byte first, so 「还原到兔白
处理前」 gives back exactly the file that was there.

No Qt widgets here: the completion page runs :func:`run_repair` on a worker
thread and calls :func:`commit_repair` on the GUI thread.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

RECORD_KEY = 'completion_ai_repair'
DECISION_SOURCE = 'completion_ai_repair'

# (label, how it is fixed, icon, unit). Plain words, as on the draft cards.
CATEGORIES = {
    'stage': ('AI 校对没跑完', '只重跑没完成的批次，思考调高一级', 'fa5s.puzzle-piece', '段'),
    'speech': ('疑似有人说话但没有字幕', '换另一个模型再听一次，AI 判断是不是台词', 'fa5s.microphone', '处'),
    'boundary': ('句子开头或结尾可能没切准', '只让 AI 重挑这几条的断点，不改字', 'fa5s.cut', '条'),
    'short': ('字幕显示时间太短', '本机用前后的空档延长，不用 AI', 'fa5s.stopwatch', '条'),
    'fast': ('字幕太快，来不及读', '本机用前后的空档延长显示，不用 AI', 'fa5s.tachometer-alt', '条'),
    'text': ('几个模型听到的不一样', '对照几个模型的文字和词库挑一个', 'fa5s.balance-scale', '条'),
    'rejected': ('保护规则拒绝的 AI 建议', '带上被拒的原因请 AI 再看一次，有第二个来源支持才改', 'fa5s.shield-alt', '处'),
    'speaker': ('说话人需要确认', 'AI 不猜是谁说的，留给你', 'fa5s.user-tag', '项'),
    'other': ('其他要你看一眼的', '兔白不会改这些，留给你', 'fa5s.eye', '项'),
}
ORDER = ('stage', 'speech', 'boundary', 'short', 'fast', 'text', 'rejected', 'speaker', 'other')
MANUAL = frozenset({'speaker', 'other'})
LOCAL = frozenset({'short', 'fast'})
# Per-kind limits for one run; over the limit the first N are done and named.
LIMITS = dict(stage=40, speech=40, boundary=60, text=60, rejected=60)
# 2026-11-22: rejected AI suggestions 兔白 has looked at again (studio_state).
REJECTED_KEY = 'completion_ai_repair_rejected'
# A rejection that left nothing to apply (the AI quoted text that is not there,
# or its edit changed nothing) is not offered again.
REJECTED_SKIP = frozenset({'invalid_or_no_effect', 'source_quote_not_found'})
REJECTED_REASONS = {
    'local_difference_without_two_sources': '只有一个来源支持这个改法',
    'length_change_without_support': '字数改变却没有其他来源支持',
    'ambiguous_single_character': '只改一个字，容易改错',
    'whole_sentence_safety': '改动的字太多',
    'phonetic_distance': '读音差太远',
    'protected_pronoun_or_colloquial_deletion': '删掉了口语或人称',
}
SPEECH_AUDIO_LIMIT = 600.0
CATEGORY_OF = {
    '边界待看': 'boundary', '断句约束待复核': 'boundary',
    '显示过短': 'short', '阅读较快': 'fast',
    '多模型争议': 'text', '多模型文本冲突': 'text', '术语候选': 'text', '术语候选待确认': 'text',
    '说话人需要确认': 'speaker',
}
TEXT_BATCH = 20
SPEECH_BATCH = 20
GAP_MS = 40          # kept between captions when a time is extended
SPEECH_PAD_MS = 200
SPEECH_MERGE_MS = 1500
SPEECH_WINDOW_MS = 25_000
# A heard-again stretch with only these is a recognizer's habit, not speech.
HALLUCINATIONS = ('谢谢观看', '谢谢大家', '感谢观看', '字幕由', '请不吝点赞', '点赞订阅', '订阅', '转发', '打赏',
                  '明镜与点点', 'thank you for watching', 'subscribe')


class RepairCancelled(Exception):
    """The run was cancelled; nothing is written."""


@dataclass
class Category:
    key: str
    rows: list = field(default_factory=list)       # review rows, stage units or speech ranges
    blocked: str = ''                               # why this kind cannot run now
    requests: int = 0                               # estimated text AI requests
    audio_seconds: float = 0.0
    backend: str = ''
    capped: int = 0                                 # rows left out by the limit

    @property
    def label(self): return CATEGORIES[self.key][0]

    @property
    def method(self): return CATEGORIES[self.key][1]

    @property
    def icon(self): return CATEGORIES[self.key][2]

    @property
    def unit(self): return CATEGORIES[self.key][3]

    @property
    def count(self): return len(self.rows)

    @property
    def automatic(self): return self.key not in MANUAL and not self.blocked


@dataclass
class Estimate:
    requests: int = 0
    audio_seconds: float = 0.0
    cost_low: float | None = None
    cost_high: float | None = None
    currency: str = 'USD'
    minutes: tuple[int, int] = (1, 2)
    priced: bool = True

    def cost_text(self):
        if self.requests == 0 and not self.audio_seconds:
            return '不花钱'
        if self.requests == 0 and not self.priced:
            return '云端重听的音频按服务商计费'
        if self.requests == 0:
            return '本机重听，不花钱'
        if self.cost_high is None or not self.priced:
            return '没有这个模型的价目，花多少以服务商账单为准'
        symbol = '$' if self.currency == 'USD' else '¥'
        if self.cost_high < 0.01:
            return f'大概不到 {symbol}0.01'
        return f'大概 {symbol}{self.cost_low:.2f}–{self.cost_high:.2f}'

    def time_text(self):
        low, high = self.minutes
        return '不到一分钟' if high <= 1 else f'{low}–{high} 分钟'


@dataclass
class RepairPlan:
    categories: list[Category]
    report: dict
    project_path: str
    settings: dict
    file_identity: dict

    def category(self, key):
        return next((item for item in self.categories if item.key == key), None)

    @property
    def fixable(self):
        return sum(item.count for item in self.categories if item.automatic)

    @property
    def manual(self):
        return sum(item.count for item in self.categories if not item.automatic)

    def estimate(self, selected=None):
        chosen = [item for item in self.categories if item.automatic
                  and (selected is None or item.key in selected)]
        return estimate_cost(chosen, self.settings)


@dataclass
class Change:
    change_id: str
    category: str
    before: list            # cue dicts replaced (empty for an inserted caption)
    after: list             # cue dicts written (empty for a removed caption)
    at_ms: int
    note: str = ''
    meta: dict = field(default_factory=dict)   # metadata the change touched, for undo
    undone: bool = False

    def describe(self):
        old = ' / '.join(row['text'] for row in self.before)
        new = ' / '.join(row['text'] for row in self.after)
        return old, new


@dataclass
class CategoryResult:
    key: str
    total: int = 0
    fixed: int = 0
    left: int = 0
    reasons: list = field(default_factory=list)   # [(count, reason)]
    changes: list = field(default_factory=list)
    status: str = 'pending'                        # pending running done partial skipped failed
    error: str = ''

    def leave(self, count, reason):
        if count <= 0:
            return
        self.left += count
        for index, (existing, text) in enumerate(self.reasons):
            if text == reason:
                self.reasons[index] = (existing + count, text)
                return
        self.reasons.append((count, reason))


@dataclass
class RepairResult:
    project: Any
    categories: dict
    resolved_issue_ids: set = field(default_factory=set)
    requests: int = 0
    started_at: str = ''
    elapsed: float = 0.0
    models: dict = field(default_factory=dict)

    @property
    def fixed(self):
        return sum(item.fixed for item in self.categories.values())

    @property
    def left(self):
        return sum(item.left for item in self.categories.values())

    @property
    def changes(self):
        return [change for item in self.categories.values() for change in item.changes]


# ---------------------------------------------------------------- planning

def file_identity(path):
    data = Path(path).read_bytes()
    return dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())


def _settings():
    from ..storage.settings import load_runtime_settings
    loaded = load_runtime_settings()
    return loaded[0] if isinstance(loaded, tuple) else loaded


def text_ai_ready(settings, stage='polish'):
    try:
        from ..providers.llm_config import text_ai_key_missing
        return not text_ai_key_missing(settings, stage)
    except Exception:  # noqa: BLE001 - unknown is treated as not ready
        return False


def speech_backend(settings):
    """(backend for transcribe_qwen_reference, plain name) of a ready model other
    than the primary one, local first (D3), or ('', why not)."""
    models = dict((settings or {}).get('models') or {})
    primary = str(models.get('primary_asr_backend') or '')
    review = str(models.get('qwen_asr_backend') or 'off')
    local_ready = False
    try:
        from ..recognition.asr import resolve_qwen_asr_local_source
        from ..system.runtime_registry import resolve_runtime_python
        local_ready = bool(resolve_qwen_asr_local_source() and resolve_runtime_python('main', register=False))
    except Exception:  # noqa: BLE001 - not installed or not importable
        local_ready = False
    names = dict(local='本机 Qwen3-ASR', api='云端 Qwen3-ASR', firered_llm='本机 FireRedASR2-LLM',
                 whisper_turbo='本机 Whisper', sensevoice='本机 SenseVoice', funasr_nano='本机 Fun-ASR-Nano')
    if review in {'firered_llm', 'whisper_turbo', 'sensevoice', 'funasr_nano'} and review != primary:
        return review, names[review]
    if local_ready and primary != 'qwen_local':
        return 'local', names['local']
    if review == 'api' and primary != 'api':
        return 'api', names['api']
    return '', '没有和主力转写不同、已经就绪的识别模型（可在模型工坊装一个本机 Qwen3-ASR）'


def _speech_windows(ranges):
    """Merge nearby pending speech ranges into a few clips (timeline ms)."""
    windows = []
    for row in sorted(ranges, key=lambda r: (r['timeline_start_ms'], r['timeline_end_ms'])):
        start, end = int(row['timeline_start_ms']), int(row['timeline_end_ms'])
        if (windows and start - windows[-1]['end'] <= SPEECH_MERGE_MS
                and max(end, windows[-1]['end']) - windows[-1]['start'] <= SPEECH_WINDOW_MS):
            windows[-1]['end'] = max(windows[-1]['end'], end)
            windows[-1]['ranges'].append(row)
        else:
            windows.append(dict(start=start, end=end, ranges=[row]))
    return windows


def plan_repair(project, report, project_path, *, settings=None):
    """What 兔白 can fix in the saved project, by kind, with an estimate."""
    from ..recognition.current_review import current_review
    from ..recognition.processing_recovery import TERMINAL, failure_summary, input_matches
    from ..recognition.speech_recovery_project import project_ranges
    settings = settings if settings is not None else _settings()
    report = report or {}
    groups = {key: Category(key) for key in ORDER}
    units = failure_summary(project, report)['units']
    for unit in units:
        if unit.get('status') == 'proposals_pending' and unit.get('input') and input_matches(project, unit['input']):
            groups['stage'].rows.append(unit)
        elif unit.get('status') not in TERMINAL and unit.get('retryable'):
            groups['stage'].rows.append(unit)
    current = current_review(project, report)
    for row in current.get('items') or ():
        groups[CATEGORY_OF.get(str(row.get('category') or ''), 'other')].rows.append(row)
    seen = set()
    for row in project_ranges(project):
        if row['id'] not in seen:
            seen.add(row['id'])
            groups['speech'].rows.append(row)
    polish_ready = text_ai_ready(settings, 'polish')
    group_ready = text_ai_ready(settings, 'group')
    no_key = '还没设置文字 AI 的密钥（AI 模型与密钥）'
    stage = groups['stage']
    if stage.rows:
        calls = sum(1 for unit in stage.rows if unit.get('status') != 'proposals_pending')
        needs = {unit.get('stage') for unit in stage.rows if unit.get('status') != 'proposals_pending'}
        if calls and not (polish_ready if 'grouping' not in needs else polish_ready and group_ready):
            stage.blocked = no_key
        stage.requests = min(calls, LIMITS['stage'])
    speech = groups['speech']
    if speech.rows:
        backend, name = speech_backend(settings)
        speech.backend = name
        if not backend:
            speech.blocked = name
        windows = _speech_windows(speech.rows)[:LIMITS['speech']]
        speech.audio_seconds = min(SPEECH_AUDIO_LIMIT, sum((w['end'] - w['start']) / 1000 for w in windows))
        speech.requests = math.ceil(len(windows) / SPEECH_BATCH) if polish_ready else 0
        speech.capped = max(0, len(speech.rows) - sum(len(w['ranges']) for w in windows))
    boundary = groups['boundary']
    if boundary.rows:
        if not group_ready:
            boundary.blocked = no_key
        boundary.requests = math.ceil(min(len(boundary.rows), LIMITS['boundary']) * 3 / 40)
    text = groups['text']
    if text.rows:
        if not polish_ready:
            text.blocked = no_key
        text.requests = math.ceil(min(len(text.rows), LIMITS['text']) / TEXT_BATCH)
    rejected = groups['rejected']
    rejected.rows.extend(rejected_rows(project, report))
    if rejected.rows:
        if not polish_ready:
            rejected.blocked = no_key
        rejected.requests = math.ceil(min(len(rejected.rows), LIMITS['rejected']) / TEXT_BATCH)
    for key in ('stage', 'boundary', 'text', 'rejected'):
        groups[key].capped = max(groups[key].capped, len(groups[key].rows) - LIMITS[key])
    categories = [groups[key] for key in ORDER if groups[key].rows]
    return RepairPlan(categories, report, str(project_path), settings, file_identity(project_path))


def _rejected_edits(report):
    from ..subtitle_rules.polish_disposition import unresolved_edit

    for event in (report or {}).get('events') or ():
        if not isinstance(event, dict) or event.get('event') != 'terminology_polish_final':
            continue
        record_id = event.get('cue_id')
        details = event.get('details')
        if record_id is None or not isinstance(details, dict):
            continue
        for edit in details.get('rejected_edits') or ():
            if not isinstance(edit, dict):
                continue
            rule = str(edit.get('rule_id') or edit.get('reason') or '')
            source, target = str(edit.get('from') or ''), str(edit.get('to') or '')
            if rule in REJECTED_SKIP or not unresolved_edit(edit):
                continue
            key = f'{record_id}:{source}:{target}:{edit.get("start")}'
            yield key, str(record_id), source, target, rule, edit.get('evidence')


def handled_rejected_count(project, report):
    handled = (project.studio_state or {}).get(REJECTED_KEY)
    if not isinstance(handled, dict) or not handled:
        return 0
    return len({key for key, *_ in _rejected_edits(report) if key in handled})


def rejected_rows(project, report):
    """AI suggestions the protection rules refused that still apply to one current caption.

    Each row names the polish record, the edit (``from`` → ``to``), why it was
    refused and the caption it now belongs to. Suggestions already looked at
    again (``REJECTED_KEY``) and ones with nothing to apply are left out."""
    handled = (project.studio_state or {}).get(REJECTED_KEY) or {}
    owners = {}
    for ref, record in (project.asr_evidence or {}).items():
        if not str(ref).startswith('segment:') or not isinstance(record, dict):
            continue
        identity = (record.get('caption_arbitration') or {}).get('processing_identity') or {}
        if identity.get('polish_record_id') is not None:
            owners.setdefault(str(identity['polish_record_id']), set()).add(str(ref))
    rows, seen = [], set()
    for key, record_id, source, target, rule, evidence in _rejected_edits(report):
        if key in handled or key in seen:
            continue
        refs = owners.get(record_id)
        if not refs:
            continue
        cues = [cue for cue in project.cues if refs.intersection(cue.evidence_refs) and cue.text.count(source) == 1]
        if len(cues) != 1:
            continue
        seen.add(key)
        rows.append(dict(key=key, record_id=record_id, cue_id=cues[0].id, text=cues[0].text, source=source,
                         target=target, rule=rule, reason=REJECTED_REASONS.get(rule, rule),
                         ai_reason=str(evidence if isinstance(evidence, str) else '')[:200]))
    return rows


def estimate_cost(categories, settings):
    """Requests, audio seconds, money and time, with the usage window's price table."""
    requests = sum(item.requests for item in categories)
    audio = sum(item.audio_seconds for item in categories)
    characters = sum(len(str(row.get('text') or '')) for item in categories for row in item.rows
                     if isinstance(row, dict))
    estimate = Estimate(requests=requests, audio_seconds=audio)
    low_minutes = max(1, round((requests * 12 + audio * .25) / 60))
    estimate.minutes = (low_minutes, max(low_minutes + 1, round((requests * 30 + audio * .6) / 60)))
    speech = next((item for item in categories if item.key == 'speech'), None)
    cloud_audio = bool(audio and speech is not None and speech.backend.startswith('云端'))
    if not requests:
        estimate.cost_low = estimate.cost_high = 0.0
        estimate.priced = not cloud_audio
        return estimate
    tokens_in = 1800 * requests + 4 * characters
    tokens_out = 300 * requests + 2 * characters
    try:
        from decimal import Decimal
        from datetime import timezone
        from ..providers.llm_config import endpoint_from_settings
        from ..providers.usage_ledger import price_snapshot
        endpoint = endpoint_from_settings(settings, 'polish')
        price = price_snapshot(str(endpoint.get('base_url') or ''), str(endpoint.get('model') or ''),
                               datetime.now(timezone.utc).isoformat())
        if not price.get('known'):
            estimate.priced = False
            return estimate

        def cost(rates):
            return float((Decimal(tokens_in) * Decimal(str(rates[1])) + Decimal(tokens_out) * Decimal(str(rates[2])))
                         / Decimal(1_000_000))
        estimate.cost_low = cost(price['rates_low'])
        estimate.cost_high = cost(price['rates_high']) * 1.5
        estimate.currency = str(price.get('currency') or 'USD')
    except Exception:  # noqa: BLE001 - an estimate is never a reason to fail
        estimate.priced = False
    return estimate


# ---------------------------------------------------------------- helpers

def _cue_row(cue):
    return asdict(cue)


def _find(project, cue_id):
    return next((cue for cue in project.cues if cue.id == cue_id), None)


def _sort(project):
    project.cues.sort(key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))


def _norm(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold()
    return ''.join(ch for ch in text if ch.isalnum())


def _neighbours(project, start_ms, end_ms):
    before = [cue for cue in project.cues if cue.end_ms <= start_ms + 50]
    after = [cue for cue in project.cues if cue.start_ms >= end_ms - 50]
    previous = max(before, key=lambda cue: cue.end_ms, default=None)
    following = min(after, key=lambda cue: cue.start_ms, default=None)
    return previous, following


def _free_span(project, cue, media_end):
    """(earliest start, latest end) the caption can take without touching another."""
    low, high = 0, media_end or (cue.end_ms + 60_000)
    for other in project.cues:
        if other.id == cue.id:
            continue
        if other.end_ms <= cue.start_ms:
            low = max(low, other.end_ms + GAP_MS)
        elif other.start_ms >= cue.end_ms:
            high = min(high, other.start_ms - GAP_MS)
        else:   # already overlapping: keep this side as it is
            if other.start_ms < cue.start_ms:
                low = max(low, cue.start_ms)
            else:
                high = min(high, cue.end_ms)
    return min(low, cue.start_ms), max(high, cue.end_ms)


def _media_end(project):
    duration = int(project.media.duration_ms or 0)
    if project.render_settings.get('_cue_domain') == 'timeline':
        from ..timeline.studio_edit_sequence import timeline_duration_ms
        duration = int(timeline_duration_ms(project) or duration)
    return duration


def _parse_json(content):
    text = str(content or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```[a-zA-Z]*\s*|\s*```$', '', text)
    try:
        value = json.loads(text)
    except ValueError:
        match = re.search(r'\{.*\}', text, re.S)
        if not match:
            raise ValueError('AI 的回复不是 JSON') from None
        value = json.loads(match.group(0))
    rows = value.get('results') if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise ValueError('AI 的回复缺少 results 列表')
    return [row for row in rows if isinstance(row, dict)]


class _Runner:
    """Shared state of one run: the copy, the cancel flag, progress, AI calls."""

    def __init__(self, plan, project, *, cancelled, progress, ask, transcribe, refine, stage_execute, ffmpeg):
        self.plan, self.project = plan, project
        self.cancelled, self.progress = cancelled, progress
        self.ask, self.transcribe, self.refine, self.stage_execute = ask, transcribe, refine, stage_execute
        self.ffmpeg = ffmpeg
        self.requests = 0
        self.resolved = set()
        self.models = {}

    def check(self):
        if self.cancelled():
            raise RepairCancelled()

    def emit(self, key, done, total, phase=''):
        if self.progress is not None:
            self.progress(dict(category=key, done=done, total=total, phase=phase))

    def ask_json(self, system, payload, *, stage='polish', max_tokens=2500):
        self.check()
        self.requests += 1
        return _parse_json(self.ask(system, payload, stage=stage, max_tokens=max_tokens, cancelled=self.cancelled))

    def change(self, result, key, before, after, *, note='', meta=None):
        at = min([row['start_ms'] for row in (*before, *after)] or [0])
        result.changes.append(Change(uuid.uuid4().hex[:12], key, copy.deepcopy(before), copy.deepcopy(after),
                                     int(at), note, meta or {}))


def _default_ask(system, payload, *, stage, max_tokens, cancelled):
    from ..providers.ai_providers import provider_for_stage
    provider = provider_for_stage(_settings(), stage)
    return provider.complete(
        [{'role': 'system', 'content': system},
         {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
        max_tokens=max_tokens, temperature=0.1, timeout=120.0, cancel_check=cancelled,
        response_format={'type': 'json_object'}, stage='completion_ai_repair')


def _default_ffmpeg():
    return Path(__file__).resolve().parents[2] / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'


# ---------------------------------------------------------------- kinds

def _fix_stage(runner, category, result):
    from ..recognition.processing_recovery import ACTIVE_KEYS
    from .stage_retry_commit import apply_unit
    units = category.rows[:LIMITS['stage']]
    if category.capped:
        result.leave(category.capped, f'超过一次最多处理 {LIMITS["stage"]} 段，先做了前 {LIMITS["stage"]} 段')
    project = runner.project
    for index, unit in enumerate(units, 1):
        runner.check()
        runner.emit('stage', index - 1, len(units), '重跑没完成的批次')
        if unit.get('status') == 'proposals_pending':
            executed = copy.deepcopy(unit)
        else:
            runner.requests += 1
            ACTIVE_KEYS.add(unit['key'])
            try:
                executed = runner.stage_execute(project, runner.plan.report, unit, runner.cancelled)
            except RepairCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - one unit failing leaves the rest
                runner.check()
                result.leave(1, '重跑还是没成功：' + _short(exc))
                continue
            finally:
                ACTIVE_KEYS.discard(unit['key'])
        runner.check()
        status = executed.get('status')
        if status == 'proposals_pending':
            before = {cue.id: copy.deepcopy(cue) for cue in project.cues}
            touched = []
            for row in executed.get('proposals') or ():
                cue = _find(project, str(row.get('cue_id')))
                if cue is None or cue.text != row.get('original'):
                    continue
                cue.text = str(row.get('replacement') or cue.text)
                touched.append(cue.id)
            pending = executed.get('pending_projection') or []
            previous = copy.deepcopy((project.generation_metadata.get('processing_recovery') or {})
                                     .get('units', {}).get(executed['key']))
            executed.update(status='applied' if touched else 'completed_no_change',
                            reason='兔白已直接写入校对结果' if touched else '校对完成，无需修改当前文字')
            apply_unit(project, executed)
            meta = _meta('stage_unit', executed['key'], previous, _stage_unit(project, executed['key']))
            for cue_id in touched:
                runner.change(result, 'stage', [_cue_row(before[cue_id])], [_cue_row(_find(project, cue_id))],
                              note='AI 校对重跑结果', meta=meta)
            if pending:
                result.leave(1, '有改动跨了两条字幕，兔白不敢乱拼，留给你')
            else:
                result.fixed += 1
        elif status in {'completed', 'completed_no_change'}:
            before = [_cue_row(cue) for cue in project.cues if cue.id in set(unit.get('cue_ids') or ())]
            previous = copy.deepcopy((project.generation_metadata.get('processing_recovery') or {})
                                     .get('units', {}).get(executed['key']))
            _, replacements, translation = apply_unit(project, executed)
            if replacements or translation is not None:
                ids = {row['id'] for rows in replacements.values() for row in rows}
                after = [_cue_row(cue) for cue in project.cues if cue.id in ids]
                if replacements:
                    runner.change(result, 'stage', before, after, note='AI 断句重跑结果',
                                  meta=_meta('stage_unit', executed['key'], previous,
                                             _stage_unit(project, executed['key'])))
            result.fixed += 1
        else:
            apply_unit(project, executed)
            result.leave(1, str(executed.get('reason') or '重跑还是没成功')[:80])
        runner.emit('stage', index, len(units))


def _stage_unit(project, key):
    return copy.deepcopy((project.generation_metadata.get('processing_recovery') or {}).get('units', {}).get(key))


def _meta(where, key, before, after):
    """Metadata one change touched: undo writes ``before`` back, redo ``after``."""
    return {'paths': [dict(where=where, id=key, before=copy.deepcopy(before), after=copy.deepcopy(after))]}


def _meta_set(project, where, key, value):
    from ..recognition.speech_coverage import KEY
    if where == 'stage_unit':
        target = project.generation_metadata.setdefault(
            'processing_recovery', {'version': 1, 'units': {}}).setdefault('units', {})
    elif where == 'rejected_edit':
        target = project.studio_state.setdefault(REJECTED_KEY, {})
    else:
        state = project.generation_metadata.get(KEY)
        if not isinstance(state, dict):
            return
        if where == 'speech_gap':
            for index, gap in enumerate(state.get('gaps', [])):
                if gap.get('id') == key and value is not None:
                    state['gaps'][index] = copy.deepcopy(value)
            return
        target = state.setdefault('decisions', {})
    if value is None:
        target.pop(key, None)
    else:
        target[key] = copy.deepcopy(value)


def _short(exc):
    text = ' '.join(str(exc).split())
    return (text[:70] + '…') if len(text) > 70 else (text or type(exc).__name__)


def _fix_timing(runner, category, result, *, fast):
    from ..recognition.current_review import SHORT_SECONDS, reading_limits
    project = runner.project
    text_length, fast_limit = reading_limits(project)
    media_end = _media_end(project)
    rows = category.rows
    for index, row in enumerate(rows, 1):
        runner.check()
        runner.emit(category.key, index - 1, len(rows), '用前后的空档延长')
        ids = [key for key in row.get('cue_ids') or () if _find(project, key) is not None]
        if len(ids) != 1:
            result.leave(1, '字幕已经变了，找不到原来那条')
            continue
        cue = _find(project, ids[0])
        duration = cue.end_ms - cue.start_ms
        if fast:
            length = text_length(cue.text)
            wanted = math.ceil(length / max(.1, fast_limit) * 1000) + 60
        else:
            wanted = max(round(SHORT_SECONDS * 1000) + 150, 600)
        if duration >= wanted:
            result.fixed += 1
            continue
        low, high = _free_span(project, cue, media_end)
        before = _cue_row(cue)
        need = wanted - duration
        end = min(high, cue.end_ms + need)
        start = max(low, cue.start_ms - max(0, need - (end - cue.end_ms)))
        minimum_ok = (end - start) / 1000 >= SHORT_SECONDS if not fast else (
            text_length(cue.text) / max(.001, (end - start) / 1000) <= fast_limit)
        if (start, end) == (cue.start_ms, cue.end_ms) or not minimum_ok:
            result.leave(1, '前后都贴着别的字幕，没有空档可以延长；要你决定合并还是拆开' if not fast else
                         '前后没有足够的空档放慢；要你决定删字还是拆开')
            continue
        cue.start_ms, cue.end_ms = int(start), int(end)
        cue.validate()
        runner.change(result, category.key, [before], [_cue_row(cue)],
                      note=f'显示 {duration / 1000:.2f} 秒 → {(end - start) / 1000:.2f} 秒')
        result.fixed += 1
    _sort(project)
    runner.emit(category.key, len(rows), len(rows))


def _fix_boundary(runner, category, result):
    from ..subtitle_rules.sentence_refine_ranges import build_range_replacement
    from ..timeline.sentence_refine_command import RefineCuesCommand
    project = runner.project
    rows = category.rows[:LIMITS['boundary']]
    if category.capped:
        result.leave(category.capped, f'超过一次最多处理 {LIMITS["boundary"]} 条，先做了前 {LIMITS["boundary"]} 条')
    order = {cue.id: index for index, cue in enumerate(sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms, c.id)))}
    ordered = sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms, c.id))
    wanted, owners = set(), {}
    for row in rows:
        ids = [key for key in row.get('cue_ids') or () if key in order]
        if not ids:
            result.leave(1, '字幕已经变了，找不到原来那条')
            continue
        for key in ids:
            position = order[key]
            for near in ordered[max(0, position - 1):position + 2]:
                wanted.add(near.id)
            owners.setdefault(key, []).append(row)
    cues = [cue for cue in ordered if cue.id in wanted]
    if not cues:
        return
    runner.emit('boundary', 0, len(rows), '请 AI 重挑断点')
    runner.check()
    outcome = runner.refine(cues, project, runner.cancelled)
    runner.requests += len(outcome.requests or ()) or 1
    runner.check()
    actions = {action.cue_id: action for action in outcome.actions}
    positions = {cue.id: index for index, cue in enumerate(project.cues)}
    used = {cue.id for cue in project.cues}
    replacements, handled, changes = [], set(), []
    for unit in outcome.ranges:
        action = actions.get(unit.cue.id)
        originals = [_find(project, cue.id) for cue in unit.originals]
        ids = {cue.id for cue in unit.originals}
        if action is None or any(cue is None for cue in originals):
            continue
        if action.action == 'keep':
            handled |= ids
            continue
        try:
            replacement = build_range_replacement(unit, action, project, used)
        except Exception:  # noqa: BLE001 - this range keeps its captions
            replacement = None
        if not replacement:
            continue
        if [(c.text, c.start_ms, c.end_ms) for c in replacement] == [(c.text, c.start_ms, c.end_ms) for c in originals]:
            handled |= ids
            continue
        replacements.append((positions[originals[0].id], len(originals), replacement))
        changes.append(([_cue_row(c) for c in originals], [_cue_row(c) for c in replacement]))
        handled |= ids
    if replacements:
        RefineCuesCommand(project, replacements).redo()
        for before, after in changes:
            runner.change(result, 'boundary', before, after, note='AI 重挑断点（字没改）')
    for row in rows:
        ids = [key for key in row.get('cue_ids') or () if key in order]
        if not ids:
            continue
        if all(key in handled for key in ids):
            result.fixed += 1
            runner.resolved.add(row.get('issue_id'))
        else:
            result.leave(1, 'AI 这几条的断点没通过校验（没对上字的时间），保留原样')
    runner.emit('boundary', len(rows), len(rows))


TEXT_SYSTEM = (
    '你在帮忙检查游戏实况字幕。每一项是一条字幕：current 是现在的文字，candidates 是几个识别模型听到的写法，'
    'before/after 是前后字幕，terms 是词库里的写法。为每一项选出最可能是实际说出的那个写法：'
    '只能选 candidates 里的一项（按 index），或 choice=-1 表示保留 current；拿不准就 choice=-2。'
    '不要自己编新的写法。只返回 JSON：{"results":[{"id":"…","choice":0,"reason":"一句话"}]}')

SPEECH_SYSTEM = (
    '你在帮忙检查游戏实况字幕里没字幕的片段。每一项是另一个识别模型重新听到的文字 heard，'
    '以及前后已有的字幕 before/after。判断 heard 是不是这段里主播或游戏角色真的说的话：'
    'verdict 只能是 "speech"（真台词）、"not_speech"（音效、背景音乐、识别器常见的幻觉如「谢谢观看」、'
    '只是重复前后字幕）或 "unsure"。speech 时给出 text：只能删去 heard 里明显的重复或幻觉字，不要改写或补字。'
    '只返回 JSON：{"results":[{"id":"…","verdict":"speech","text":"…","reason":"一句话"}]}')


def _fix_text(runner, category, result):
    from ..subtitle_rules.studio_qc import review_candidates, terminology_from_project
    project = runner.project
    rows = category.rows[:LIMITS['text']]
    if category.capped:
        result.leave(category.capped, f'超过一次最多处理 {LIMITS["text"]} 条，先做了前 {LIMITS["text"]} 条')
    try:
        terms = terminology_from_project(project)
    except Exception:  # noqa: BLE001 - glossary is help, not a requirement
        terms = ()
    items, lookup = [], {}
    for index, row in enumerate(rows):
        ids = [key for key in row.get('cue_ids') or () if _find(project, key) is not None]
        if len(ids) != 1:
            result.leave(1, '这一项跨了几条字幕，兔白不敢拼，留给你')
            continue
        cue = _find(project, ids[0])
        candidates = [item.text for item in review_candidates(project, cue)
                      if not item.context_only and item.text and item.text != cue.text]
        if not candidates:
            result.leave(1, '没有别的模型写法可以对照')
            continue
        previous, following = _neighbours(project, cue.start_ms, cue.end_ms)
        joined = ' '.join([cue.text, *candidates])
        hints = []
        for term in terms:
            names = [str(term.canonical or ''), *(str(a) for a in term.wrong_forms or ())]
            if any(name and name in joined for name in names):
                hints.append(names[0])
        key = f'i{index}'
        lookup[key] = (row, cue, candidates)
        items.append(dict(id=key, current=cue.text, candidates=[dict(index=i, text=t) for i, t in enumerate(candidates)],
                          before=previous.text if previous else '', after=following.text if following else '',
                          terms=hints[:8], category=row.get('category')))
    for start in range(0, len(items), TEXT_BATCH):
        batch = items[start:start + TEXT_BATCH]
        runner.emit('text', start, len(items), '请 AI 对照几个模型的写法')
        try:
            answers = {str(row.get('id')): row for row in runner.ask_json(TEXT_SYSTEM, dict(items=batch))}
        except RepairCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - this batch stays for a person
            runner.check()
            result.leave(len(batch), 'AI 这一批没回好：' + _short(exc))
            continue
        for item in batch:
            row, cue, candidates = lookup[item['id']]
            answer = answers.get(item['id']) or {}
            try:
                choice = int(answer.get('choice'))
            except (TypeError, ValueError):
                choice = -2
            if choice == -1:
                result.fixed += 1
                runner.resolved.add(row.get('issue_id'))
            elif 0 <= choice < len(candidates) and _find(project, cue.id) is cue:
                before = _cue_row(cue)
                cue.text = candidates[choice]
                runner.change(result, 'text', [before], [_cue_row(cue)],
                              note=str(answer.get('reason') or '对照几个模型后改用这个写法')[:80])
                result.fixed += 1
                runner.resolved.add(row.get('issue_id'))
            else:
                result.leave(1, 'AI 也拿不准，留给你听')
    runner.emit('text', len(items), len(items))


REJECTED_SYSTEM = (
    '你在帮忙复查游戏实况字幕。每一项是一条字幕 current，以及之前 AI 提出、但被保护规则拦下的改法：'
    '把 source 改成 target；reason 是被拦下的原因，ai_reason 是当时 AI 的理由。candidates 是几个识别模型听到的写法，'
    'terms 是词库里的写法，before/after 是前后字幕。判断这个改法对不对：decision 只能是 "apply"（确实该改）、'
    '"keep"（保留 current）或 "unsure"。只能判断这个改法本身，不要提出别的改法。'
    '只返回 JSON：{"results":[{"id":"…","decision":"keep","reason":"一句话"}]}')


def _fix_rejected(runner, category, result):
    """Second look at refused AI suggestions; applied only with a second source.

    The rule that refused most of them asks for two independent sources. The
    text AI is asked again with the reason; an "apply" is written only when a
    recognizer's reading or the glossary also has the target wording."""
    from ..subtitle_rules.studio_qc import review_candidates, terminology_from_project
    project = runner.project
    rows = category.rows[:LIMITS['rejected']]
    if category.capped:
        result.leave(category.capped, f'超过一次最多处理 {LIMITS["rejected"]} 处，先做了前 {LIMITS["rejected"]} 处')
    try:
        terms = terminology_from_project(project)
    except Exception:  # noqa: BLE001 - glossary is help, not a requirement
        terms = ()
    handled = project.studio_state.setdefault(REJECTED_KEY, {})
    items, lookup = [], {}
    for index, row in enumerate(rows):
        cue = _find(project, row['cue_id'])
        if cue is None or cue.text.count(row['source']) != 1:
            result.leave(1, '字幕已经变了，找不到原来那条')
            continue
        readings = [item.text for item in review_candidates(project, cue)
                    if item.text and item.sources and 'Current' not in item.sources and not item.context_only]
        names = [term.canonical for term in terms if term.canonical == row['target']]
        previous, following = _neighbours(project, cue.start_ms, cue.end_ms)
        key = f'r{index}'
        lookup[key] = (row, cue, readings, names)
        items.append(dict(id=key, current=cue.text, source=row['source'], target=row['target'], reason=row['reason'],
                          ai_reason=row['ai_reason'], candidates=readings[:5], terms=names[:5],
                          before=previous.text if previous else '', after=following.text if following else ''))

    def decide(row, cue, status, note):
        previous = copy.deepcopy(handled.get(row['key']))
        handled[row['key']] = dict(status=status, cue_id=cue.id, decided_by=DECISION_SOURCE, note=note[:80],
                                   at=datetime.now().isoformat(timespec='seconds'))
        return _meta('rejected_edit', row['key'], previous, handled[row['key']])

    for start in range(0, len(items), TEXT_BATCH):
        batch = items[start:start + TEXT_BATCH]
        runner.emit('rejected', start, len(items), '请 AI 再看一次被拦下的改法')
        try:
            answers = {str(row.get('id')): row for row in runner.ask_json(REJECTED_SYSTEM, dict(items=batch))}
        except RepairCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - this batch stays for a person
            runner.check()
            result.leave(len(batch), 'AI 这一批没回好：' + _short(exc))
            continue
        for item in batch:
            row, cue, readings, names = lookup[item['id']]
            answer = answers.get(item['id']) or {}
            decision = str(answer.get('decision') or 'unsure')
            reason = str(answer.get('reason') or '')
            if decision == 'keep':
                meta = decide(row, cue, 'kept', reason or 'AI 复查后保留原文')
                result.changes.append(Change(uuid.uuid4().hex[:12], 'rejected', [], [], cue.start_ms,
                                             f'保留「{row["source"]}」：' + (reason or 'AI 复查后觉得原文对'), meta))
                result.fixed += 1
            elif decision == 'apply':
                supported = any(row['target'] in reading for reading in readings) or bool(names)
                if not supported:
                    result.leave(1, '只有 AI 一个来源支持这个改法，留给你听')
                    continue
                if cue.text.count(row['source']) != 1:
                    result.leave(1, '同一条字幕的另一处已经改过，这处要你看')
                    continue
                before = _cue_row(cue)
                cue.text = cue.text.replace(row['source'], row['target'], 1)
                meta = decide(row, cue, 'applied', reason or '有第二个来源支持')
                runner.change(result, 'rejected', [before], [_cue_row(cue)],
                              note=(reason or '复查后改用') + '（另有模型或词库支持）', meta=meta)
                result.fixed += 1
            else:
                result.leave(1, 'AI 也拿不准，留给你听')
    runner.emit('rejected', len(items), len(items))


def _clip(runner, project, start_ms, end_ms, path):
    from ..system.processes import run_hidden_subprocess
    from ..studio.studio_reasr import build_clip_command
    media = Path(project.media.path)
    duration = (end_ms - start_ms) / 1000
    if project.render_settings.get('_cue_domain') == 'timeline':
        from types import SimpleNamespace
        from ..exports.audio_export import audio_mix_arguments, capture_audio_mix
        job = SimpleNamespace(start_seconds=start_ms / 1000, duration_seconds=duration,
                              video_graph={'duration_ms': end_ms})
        arguments = audio_mix_arguments(str(runner.ffmpeg), job, capture_audio_mix(project))
        if arguments == ['-an']:
            raise RuntimeError('这一段没有启用的素材音频')
        command = [str(runner.ffmpeg), '-hide_banner', '-nostdin', '-loglevel', 'error', '-y',
                   '-f', 'lavfi', '-i', f'anullsrc=r=16000:cl=mono:d={duration:.6f}',
                   *arguments, '-t', f'{duration:.6f}', '-ac', '1', '-ar', '16000', str(path)]
    else:
        if not media.is_file():
            raise FileNotFoundError(media)
        command = build_clip_command(runner.ffmpeg, media, path, start_ms, end_ms)
    completed = run_hidden_subprocess(command, purpose='ffmpeg completion repair clip', capture_output=True,
                                      text=True, encoding='utf-8', errors='replace', timeout=60)
    if completed.returncode != 0 or not path.is_file() or path.stat().st_size <= 44:
        raise RuntimeError('取这段音频失败：' + str(completed.stderr or '')[-200:])


def _speech_local_verdict(heard, previous, following):
    """'not_speech' for what needs no AI, else ''."""
    compact = _norm(heard)
    if not compact:
        return 'not_speech', '另一个模型也没听到字'
    if any(_norm(word) and _norm(word) in compact and len(compact) <= len(_norm(word)) + 4 for word in HALLUCINATIONS):
        return 'not_speech', '只听到识别器常见的幻觉字（像「谢谢观看」）'
    if len(compact) >= 4 and len(set(compact)) <= 2:
        return 'not_speech', '只是同一个字一直重复'
    for near in (previous, following):
        if near is not None and len(compact) >= 2 and compact in _norm(near.text):
            return 'not_speech', '和旁边那条字幕重复，已经有字了'
    return '', ''


def _fix_speech(runner, category, result):
    import tempfile
    from ..projects.studio_project import StudioCue, studio_data_root
    from ..recognition.speech_coverage import KEY
    from ..recognition.speech_recovery_project import audio_version, merge_project_range
    from ..subtitle_rules.chinese_script import for_project
    project = runner.project
    backend, name = speech_backend(runner.plan.settings)
    runner.models['speech'] = name
    windows = _speech_windows(category.rows)
    kept, seconds = [], 0.0
    for window in windows:
        length = (window['end'] - window['start']) / 1000
        if len(kept) >= LIMITS['speech'] or seconds + length > SPEECH_AUDIO_LIMIT:
            break
        kept.append(window)
        seconds += length
    skipped = sum(len(w['ranges']) for w in windows[len(kept):])
    if skipped:
        result.leave(skipped, f'超过一次最多重听 {LIMITS["speech"]} 段 / {int(SPEECH_AUDIO_LIMIT // 60)} 分钟，先做了前面的')
    media_end = _media_end(project)
    heard = []       # (range row, text)
    cache = studio_data_root() / 'reasr'
    cache.mkdir(parents=True, exist_ok=True)
    for index, window in enumerate(kept, 1):
        runner.check()
        runner.emit('speech', index - 1, len(kept), f'用{name}再听一次')
        start = max(0, window['start'] - SPEECH_PAD_MS)
        end = min(media_end or window['end'] + SPEECH_PAD_MS, window['end'] + SPEECH_PAD_MS)
        descriptor, temporary = tempfile.mkstemp(prefix='repair-', suffix='.wav', dir=str(cache))
        os.close(descriptor)
        clip = Path(temporary)
        try:
            _clip(runner, project, start, end, clip)
            regions = [dict(start=max(0.0, (r['timeline_start_ms'] - start) / 1000),
                            end=max(0.05, (r['timeline_end_ms'] - start) / 1000)) for r in window['ranges']]
            rows = runner.transcribe(str(clip), regions, backend) or []
        except RepairCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - this window stays for a person
            runner.check()
            result.leave(len(window['ranges']), '再听一次没成功：' + _short(exc))
            continue
        finally:
            try:
                clip.unlink()
            except OSError:
                pass
        if not rows or any(not isinstance(row, dict) or not isinstance(row.get('text'), str) for row in rows):
            result.leave(len(window['ranges']), '复听没有返回可核对的结果，保留待试听')
            continue
        texts = [row['text'].strip() for row in rows]
        if len(texts) == len(window['ranges']):
            pairs = list(zip(window['ranges'], texts))
        elif len(window['ranges']) == 1:
            pairs = [(window['ranges'][0], ''.join(texts))]
        else:
            result.leave(len(window['ranges']), '复听结果无法对应到每个范围，保留待试听')
            continue
        heard.extend((r, for_project(t, project)) for r, t in pairs)
    runner.emit('speech', len(kept), len(kept), '判断是不是台词')
    state = project.generation_metadata.get(KEY) or {}
    version = audio_version(project, state) if state else ''

    def no_speech(row, reason):
        decisions = state.setdefault('decisions', {})
        previous = copy.deepcopy(decisions.get(row['id']))
        decisions[row['id']] = dict(status='non_speech', audio_version=version, source_identity=state.get('identity'),
                                    start=row['start'], end=row['end'], decided_by=DECISION_SOURCE, reason=reason)
        project.generation_metadata[KEY] = state
        result.changes.append(Change(uuid.uuid4().hex[:12], 'speech', [], [], int(row['timeline_start_ms']),
                                     '记为没有人声：' + reason,
                                     _meta('speech_decision', row['id'], previous, decisions[row['id']])))
        result.fixed += 1

    ask = []
    for row, text in heard:
        previous, following = _neighbours(project, row['timeline_start_ms'], row['timeline_end_ms'])
        verdict, reason = _speech_local_verdict(text, previous, following)
        if verdict:
            no_speech(row, reason)
        else:
            ask.append((row, text, previous, following))
    if ask and not text_ai_ready(runner.plan.settings, 'polish'):
        result.leave(len(ask), '听到了字，但没设置文字 AI，没法判断是不是台词')
        ask = []
    inserted = []
    for start_index in range(0, len(ask), SPEECH_BATCH):
        batch = ask[start_index:start_index + SPEECH_BATCH]
        payload = [dict(id=f's{start_index + i}', heard=text, before=prev.text if prev else '',
                        after=nxt.text if nxt else '') for i, (row, text, prev, nxt) in enumerate(batch)]
        try:
            answers = {str(r.get('id')): r for r in runner.ask_json(SPEECH_SYSTEM, dict(items=payload))}
        except RepairCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            runner.check()
            result.leave(len(batch), 'AI 这一批没回好：' + _short(exc))
            continue
        for i, (row, text, previous, following) in enumerate(batch):
            answer = answers.get(f's{start_index + i}') or {}
            verdict = str(answer.get('verdict') or 'unsure')
            if verdict == 'not_speech':
                no_speech(row, str(answer.get('reason') or 'AI 判断不是台词')[:60])
                continue
            if verdict != 'speech':
                result.leave(1, 'AI 也拿不准是不是人声，留给你听')
                continue
            final = str(answer.get('text') or text).strip()
            # Only deletions of the heard text are accepted; never invented words.
            if _norm(final) and not _subsequence(_norm(final), _norm(text)):
                final = text
            low = max(int(row['timeline_start_ms']), (previous.end_ms + GAP_MS) if previous else 0)
            high = min(int(row['timeline_end_ms']), (following.start_ms - GAP_MS) if following else 10 ** 12)
            if high - low < 300:
                result.leave(1, '这段夹在两条字幕之间太窄，放不下新字幕')
                continue
            neighbour = previous or following
            cue = StudioCue(id='ai-' + uuid.uuid4().hex[:10], start_ms=low, end_ms=high, text=final,
                            speaker_id=neighbour.speaker_id if neighbour else (project.speakers[0].id if project.speakers else 'S00'),
                            style_id=neighbour.style_id if neighbour else 'default', original_text=final)
            cue.validate()
            project.cues.append(cue)
            inserted.append(cue.id)
            runner.change(result, 'speech', [], [_cue_row(cue)], note=f'AI 补录（{name} 听到）',
                          meta={'gap': row['id']})
            result.fixed += 1
    if inserted:
        _sort(project)
        from types import SimpleNamespace
        gaps = lambda: {gap['id']: copy.deepcopy(gap) for gap in (project.generation_metadata.get(KEY) or {}).get('gaps', [])}
        gaps_before = gaps()
        merge_project_range(project, SimpleNamespace(cues=project.cues, inserted_ids=inserted))
        gaps_after = gaps()
        for change in result.changes:
            gap_id = change.meta.pop('gap', None)
            if gap_id is not None and gaps_before.get(gap_id) != gaps_after.get(gap_id):
                change.meta = _meta('speech_gap', gap_id, gaps_before.get(gap_id), gaps_after.get(gap_id))
    runner.emit('speech', len(kept), len(kept))


def _subsequence(short, long):
    position = 0
    for character in short:
        position = long.find(character, position)
        if position < 0:
            return False
        position += 1
    return True


def _default_transcribe(clip, regions, backend):
    from ..recognition.asr import transcribe_qwen_reference
    return transcribe_qwen_reference(clip, regions, None, backend_override=backend)


def _default_refine(cues, project, cancelled):
    from ..subtitle_rules.sentence_refine import refine_cues_with_llm
    return refine_cues_with_llm(cues, project=project, runtime_settings=_settings(), cancel_check=cancelled,
                                boundary_only=True, batch_size=40, max_attempts=2)


def _default_stage_execute(project, report, unit, cancelled):
    from .stage_retry import execute_unit

    class _Token:
        @property
        def is_cancelled(self):
            return cancelled()

        def raise_if_cancelled(self):
            if cancelled():
                raise RepairCancelled()
    return execute_unit(project, report, None, unit, _Token())


def run_repair(plan, selected, *, cancelled=lambda: False, progress=None, ask=None, transcribe=None,
               refine=None, stage_execute=None, ffmpeg=None):
    """Fix the chosen kinds on a copy of the saved project. Raises RepairCancelled."""
    from ..projects.studio_project import load_project
    started, clock = datetime.now().isoformat(timespec='seconds'), time.monotonic()
    if file_identity(plan.project_path) != plan.file_identity:
        raise ValueError('工程在你打开兔白之后被改过；请关掉再点一次「交给兔白」')
    project = load_project(plan.project_path)
    runner = _Runner(plan, project, cancelled=cancelled, progress=progress, ask=ask or _default_ask,
                     transcribe=transcribe or _default_transcribe, refine=refine or _default_refine,
                     stage_execute=stage_execute or _default_stage_execute, ffmpeg=ffmpeg or _default_ffmpeg())
    results = {}
    for category in plan.categories:
        result = results[category.key] = CategoryResult(category.key, total=category.count)
        if category.key in MANUAL:
            result.status = 'skipped'
            result.leave(category.count, '说话人是谁要你来定' if category.key == 'speaker' else '兔白不会改这类，留给你')
            continue
        if category.key not in selected:
            result.status = 'skipped'
            result.leave(category.count, '这次你没让兔白处理这类')
            continue
        if category.blocked:
            result.status = 'skipped'
            result.leave(category.count, category.blocked)
            continue
        result.status = 'running'
        runner.emit(category.key, 0, category.count, '开始')
        try:
            if category.key == 'stage':
                _fix_stage(runner, category, result)
            elif category.key == 'speech':
                _fix_speech(runner, category, result)
            elif category.key == 'boundary':
                _fix_boundary(runner, category, result)
            elif category.key in LOCAL:
                _fix_timing(runner, category, result, fast=category.key == 'fast')
            elif category.key == 'text':
                _fix_text(runner, category, result)
            elif category.key == 'rejected':
                _fix_rejected(runner, category, result)
        except RepairCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - one kind failing keeps the others
            runner.check()
            result.status = 'failed'
            result.error = _short(exc)
            done = result.fixed + result.left
            result.leave(max(0, category.count - done), '这一类出错停下了：' + result.error)
            continue
        handled = result.fixed + result.left
        if handled < category.count:
            result.leave(category.count - handled, '没有处理到')
        result.status = 'done' if not result.left else 'partial'
    runner.check()
    for cue in project.cues:
        cue.validate()
    return RepairResult(project, results, set(filter(None, runner.resolved)), runner.requests,
                        started, time.monotonic() - clock, runner.models)


# ---------------------------------------------------------------- saving

def backup_root():
    from ..projects.studio_project import studio_data_root
    return studio_data_root() / 'ai-repair'


def _resolve_decisions(project, report, issue_ids):
    """The issues 兔白 checked and kept stay off the list for this exact caption state."""
    from ..recognition.current_review import DECISIONS_KEY, current_review
    if not issue_ids:
        return
    decisions = project.studio_state.setdefault(DECISIONS_KEY, {})
    for row in current_review(project, report).get('items') or ():
        if row.get('issue_id') in issue_ids:
            decisions[row['issue_id']] = dict(status='resolved', input_version=row['input_version'],
                                              decided_by=DECISION_SOURCE, at=datetime.now().isoformat(timespec='seconds'))


def _write_atomic(path, data):
    target = Path(path)
    temporary = target.with_name(target.name + f'.{uuid.uuid4().hex[:6]}.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, target)


def text_change_ids(result):
    """Sentence splits can stay automatic when they conserve the exact text."""
    return {change.change_id for change in result.changes if
            ''.join(row['text'] for row in change.before) != ''.join(row['text'] for row in change.after)}


def commit_repair(plan, result, *, approved_text_ids=()):
    """Back up the original bytes, then save the repaired copy. Returns the record."""
    from ..projects.studio_project import PROJECT_SUFFIX, save_project
    required = text_change_ids(result)
    if required != set(approved_text_ids):
        raise ValueError('請先採用這次列出的文字建議')
    path = Path(plan.project_path)
    original = path.read_bytes()
    if dict(size=len(original), sha256=hashlib.sha256(original).hexdigest()) != plan.file_identity:
        raise ValueError('兔白处理期间工程被改过，结果没有写入；可以再交给兔白一次')
    project = result.project
    _resolve_decisions(project, plan.report, result.resolved_issue_ids)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    folder = backup_root() / str(project.project_id) / (stamp + '-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    backup = folder / ('before' + PROJECT_SUFFIX)
    backup.write_bytes(original)
    record = dict(version=1, at=result.started_at, project_path=str(path), project_id=str(project.project_id),
                  backup=str(backup), backup_sha256=plan.file_identity['sha256'], backup_size=plan.file_identity['size'],
                  requests=result.requests, elapsed_seconds=round(result.elapsed, 1), models=result.models,
                  text_approval={'actor': 'user', 'proposal_ids': sorted(required)} if required else None,
                  categories={key: dict(total=item.total, fixed=item.fixed, left=item.left, status=item.status,
                                        error=item.error, reasons=[list(r) for r in item.reasons])
                              for key, item in result.categories.items()},
                  changes=[asdict(change) for change in result.changes])
    project.generation_metadata[RECORD_KEY] = dict(record=str(folder / 'record.json'), at=result.started_at,
        fixed=result.fixed, left=result.left, changes=len(result.changes))
    # Prepare the exact bytes and the matching undo record before publishing
    # a project that points at that record. The rename stays on one volume.
    with tempfile.TemporaryDirectory(prefix='.ai-repair-', dir=path.parent) as staging:
        staged = save_project(project, Path(staging) / path.name)
        record['saved_sha256'] = file_identity(staged)['sha256']
        _write_record(folder / 'record.json', record)
        if file_identity(path) != plan.file_identity:
            raise ValueError('兔白保存前工程被改过，结果没有写入')
        os.replace(staged, path)
    _log('completion.ai_repair.saved', project, record)
    return record


def _write_record(path, record):
    _write_atomic(path, json.dumps(record, ensure_ascii=False, indent=1).encode('utf-8'))


def _log(event, project, record):
    try:
        from ..diagnostics.event_log import emit
        emit(event, project_id=str(project.project_id), fixed=sum(c['fixed'] for c in record['categories'].values()),
             left=sum(c['left'] for c in record['categories'].values()), changes=len(record['changes']),
             requests=record.get('requests', 0), record=str(record.get('backup', '')))
    except Exception:  # noqa: BLE001 - logging never blocks the result
        pass


def read_record(project_path):
    """The latest 兔白处理 record of this project file, if its backup still exists."""
    from ..projects.studio_project import load_project
    try:
        project = load_project(project_path)
    except (OSError, ValueError, TypeError):
        return None
    pointer = project.generation_metadata.get(RECORD_KEY) or {}
    path = Path(str(pointer.get('record') or ''))
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if Path(record.get('project_path') or '') != Path(project_path) or not Path(record.get('backup') or '').is_file():
        return None
    record['_path'] = str(path)
    return record


def edited_since(record):
    """Was the project file changed after the last 兔白 save (by Studio, proofreading…)?"""
    try:
        return (record.get('later_edits', False)
                or file_identity(record['project_path'])['sha256'] != record.get('saved_sha256'))
    except OSError:
        return True


def restore_before_repair(record):
    """Put back exactly the bytes that were there before 兔白处理."""
    data = Path(record['backup']).read_bytes()
    if hashlib.sha256(data).hexdigest() != record['backup_sha256']:
        raise ValueError('备份文件对不上，没有还原')
    _write_atomic(record['project_path'], data)
    record['restored_at'] = datetime.now().isoformat(timespec='seconds')
    _write_record(record['_path'], {k: v for k, v in record.items() if not k.startswith('_')})


def _swap(project, remove, insert):
    current = {cue.id: cue for cue in project.cues}
    for row in remove:
        cue = current.get(row['id'])
        if cue is None or _cue_row(cue) != row:
            return False
    if any(row['id'] in current and row['id'] not in {r['id'] for r in remove} for row in insert):
        return False
    from ..projects.studio_project import StudioCue
    removed = {row['id'] for row in remove}
    project.cues = [cue for cue in project.cues if cue.id not in removed]
    for row in insert:
        cue = StudioCue(**row)
        cue.validate()
        project.cues.append(cue)
    _sort(project)
    return True


def set_change_undone(record, change_id, undone):
    """撤回这条 / 改回兔白的 for one change; False when the captions were edited since."""
    from ..projects.studio_project import load_project, save_project
    change = next((row for row in record['changes'] if row['change_id'] == change_id), None)
    if change is None or bool(change.get('undone')) == bool(undone):
        return False
    path = record['project_path']
    before_save = file_identity(path)
    project = load_project(path)
    remove, insert = (change['after'], change['before']) if undone else (change['before'], change['after'])
    if (remove or insert) and not _swap(project, remove, insert):
        return False
    for row in (change.get('meta') or {}).get('paths', ()):
        _meta_set(project, row['where'], row['id'], row['before'] if undone else row['after'])
    if file_identity(path) != before_save:
        return False
    later_edits = record.get('later_edits', False) or before_save['sha256'] != record.get('saved_sha256')
    save_project(project, path)
    change['undone'] = bool(undone)
    record['later_edits'] = later_edits
    record['saved_sha256'] = file_identity(path)['sha256']
    _write_record(record['_path'], {k: v for k, v in record.items() if not k.startswith('_')})
    return True
