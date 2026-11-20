"""兔白 reads a recognition's raw JSON and says which step went wrong (2026-11-18).

User (2026-11-18): when something went wrong, or someone asks about a recognition, 兔白 should first
get that recognition's raw JSON (new users do not know what it is) and analyse it, so she can tell
whether the trouble is in 主力转写, the 字幕时间轴, AI 断句 or AI 校对, and give advice that fits.
Two cases from the user: subtitles out of place, for which she only suggested 「智能修轴」; and MOSS
Pro hearing the wrong language, which nobody explained (MOSS Pro cannot be told the language; the
fix is another 主力转写).

``analyze(payload)`` takes the task journal (``recognition-tasks/<id>/task.json``) or the task report
(``reports/*_字幕任务报告.json``): both carry the settings, stages, events, result and review items.
It looks at each step on its own:

* 音轨 — which track of the video was heard;
* 主力转写 — the service, the language each request came back in against the one asked for (and
  whether the service can be told the language at all), how much text came back per minute of
  detected speech per request, speech the voice detector found but no subtitle covers;
* 字幕时间轴 — who owns the final times, how many cut points are estimates, low timing anchors, and
  whether the subtitles as a whole sit early or late against the detected speech (an offset);
* AI 校对 / AI 断句 — batches that failed, fell back or were retried;
* the known-problem catalog (``recognition.run_diagnosis``) as a second opinion.

Each finding names the step, how sure it is, what it means and what to do, with the exact names of
the buttons. Nothing here reads audio; paths, keys and subtitle text never leave this module (the
summary has counts, languages and times only). No Qt.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path

STEPS = ('音轨', '主力转写', '字幕时间轴', 'AI 校对', 'AI 断句', '其他')
LANGUAGE_NAMES = {'zh': '中文', 'zh-cn': '中文', 'zh-tw': '中文', 'yue': '粤语', 'ja': '日语', 'en': '英语', 'ko': '韩语',
                  'es': '西班牙语', 'de': '德语', 'fr': '法语', 'pt': '葡萄牙语', 'it': '意大利语', 'ru': '俄语', 'auto': '自动'}
LOW_DENSITY_SHARE = 0.55       # a request with this share of the others' text per speech minute is thin
LOW_DENSITY_MIN_SPEECH_S = 90.0
GAP_SHARE_WARN = 0.08          # speech seconds without a subtitle, of all speech
GAP_SHARE_BAD = 0.18
ESTIMATE_SHARE_WARN = 0.08     # cut points timed by estimate, of all cut points
OFFSET_MIN_S = 0.3             # a whole-film offset at least this large, and clearly better than none
OFFSET_GAIN = 0.04
OFFSET_RANGE_S = 4.0
SCRIPT_SHARE = 0.3             # this share of kana / hangul / latin letters in a Chinese request: wrong language


@dataclass
class Finding:
    step: str
    level: str                   # 'problem' | 'warn' | 'ok' | 'info'
    title: str
    detail: str = ''
    advice: tuple = ()
    sure: str = '很可能'

    def text(self) -> str:
        mark = {'problem': '【有问题】', 'warn': '【要注意】', 'ok': '【正常】', 'info': '【说明】'}[self.level]
        lines = [f'{mark}{self.step} · {self.title}（{self.sure}）']
        if self.detail:
            lines.append(f'  依据：{self.detail}')
        lines += [f'  建议：{item}' for item in self.advice]
        return '\n'.join(lines)


@dataclass
class Analysis:
    overview: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    catalog: list = field(default_factory=list)

    def problems(self) -> list:
        order = {'problem': 0, 'warn': 1, 'info': 2, 'ok': 3}
        return sorted(self.findings, key=lambda item: (order[item.level], STEPS.index(item.step)))

    def text(self, limit: int = 3600) -> str:
        parts = ['【识别概况】', *self.overview, '', '【按步骤分析】（有问题的排在前面）']
        parts += [finding.text() for finding in self.problems()]
        if self.catalog:
            parts += ['', '【本机诊断目录也认出的】', *[f'- {line}' for line in self.catalog]]
        text = '\n'.join(parts)
        return text if len(text) <= limit else text[:limit - 1] + '…'


# ------------------------------------------------------------------ small helpers
def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _events(payload, name) -> list:
    return [event for event in _list(payload.get('events')) if isinstance(event, dict) and event.get('event') == name]


def _language(code) -> str:
    text = str(code or '').strip()
    return LANGUAGE_NAMES.get(text.casefold(), '未知')


def _base(code) -> str:
    text = str(code or '').casefold().replace('_', '-')
    return 'zh' if text.startswith(('zh', 'cmn')) else text.split('-')[0]


def _clock(seconds) -> str:
    seconds = max(0, int(float(seconds or 0)))
    return f'{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}' if seconds >= 3600 else \
        f'{seconds // 60}:{seconds % 60:02d}'


def _ranges(value) -> list:
    out = []
    for item in _list(value):
        try:
            start, end = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if math.isfinite(start) and math.isfinite(end) and end > start:
            out.append((start, end))
    return sorted(out)


def _overlap(rows, speech, shift=0.0) -> float:
    """Seconds of ``rows`` (moved by ``shift``) that fall on detected speech; both sorted."""
    import bisect
    starts = [start for start, _end in speech]
    total = 0.0
    for start, end in rows:
        start, end = start + shift, end + shift
        index = max(0, bisect.bisect_right(starts, start) - 1)
        while index < len(speech) and speech[index][0] < end:
            low, high = speech[index]
            if high > start:
                total += min(high, end) - max(low, start)
            index += 1
    return total


def _speech_in(speech, low, high) -> float:
    return sum(min(end, high) - max(start, low) for start, end in speech if end > low and start < high)


def _script_shares(text: str) -> dict:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return {}
    count = len(letters)
    kana = sum('぀' <= char <= 'ヿ' for char in letters)
    hangul = sum('가' <= char <= '힯' or 'ᄀ' <= char <= 'ᇿ' for char in letters)
    latin = sum(char.isascii() for char in letters)
    han = sum('一' <= char <= '鿿' for char in letters)
    return {'ja': kana / count, 'ko': hangul / count, 'latin': latin / count, 'zh': han / count}


def _final_cues(payload) -> list:
    """(start s, end s) of the saved subtitles, from the last display phase the run logged."""
    phases = _events(payload, 'display_boundary_phase')
    for phase in reversed(phases):
        cues = _list(phase.get('cues'))
        rows = []
        for cue in cues:
            try:
                rows.append((float(cue['start_ms']) / 1000, float(cue['end_ms']) / 1000))
            except (TypeError, ValueError, KeyError):
                continue
        if rows:
            return sorted(rows)
    return []


def _model_names(payload) -> tuple:
    from ..recognition.recognition_history import _PRIMARY_NAMES, _TIMELINE_NAMES
    models = _dict(_dict(payload.get('settings')).get('models'))
    backend = str(models.get('primary_asr_backend') or '')
    primary = _PRIMARY_NAMES.get(backend, '未记录')
    provider = str(models.get('qwen_asr_api_provider') or '')
    if backend == 'api':
        primary = {'mosi_moss_pro': 'MOSS Pro 云端', 'bailian': '阿里云百炼',
                   'qwen_cloud': 'Qwen Cloud'}.get(provider, '云端识别')
    timeline = str(models.get('firered_asr_backend') or 'off')
    return primary, _TIMELINE_NAMES.get(timeline, '未记录'), bool(models.get('polish_model') or models.get('group_model'))


# ------------------------------------------------------------------ the steps
def _overview(payload, analysis: Analysis):
    result = _dict(payload.get('result'))
    settings = _dict(payload.get('settings'))
    asked = _dict(settings.get('subtitle_language')).get('requested_language') or 'auto'
    primary, timeline, ai = _model_names(payload)
    duration = float(_dict(result.get('speech_coverage')).get('duration') or result.get('audio_seconds') or 0)
    status = {'completed': '完成', 'partial': '部分完成', 'failed': '失败', 'running': '进行中',
              'cancelled': '已取消', 'queued': '排队中'}.get(str(payload.get('status')), '未记录')
    analysis.overview += [
        f'- 素材长 {_clock(duration)}；状态：{status}',
        f'- 视频里说的话（用户选的）：{_language(asked)}；字幕 {int(result.get("cue_count") or 0)} 条',
        f'- 主力转写：{primary}；字幕时间轴：{timeline}；文字 AI：{"已选模型" if ai else "未记录模型"}',
    ]
    error = str(_dict(payload.get('task')).get('last_error') or payload.get('error') or '').strip()
    if error:
        analysis.findings.append(Finding('其他', 'problem', '任务报了错', '',
                                         ('在本机查看任务错误详情，或用「说明」→「回报问题／导出诊断…」',), '确定'))


def _audio_track(payload, analysis: Analysis):
    for event in _events(payload, 'audio_stream_selected')[:1]:
        label = str(event.get('label') or '')
        offset = float(event.get('offset_ms') or 0) + float(event.get('lead_ms') or 0)
        level = 'info'
        advice = ()
        track = '任务选中的音轨' if label else '默认音轨'
        if any(word in label.casefold() for word in ('desktop', 'game', '游戏', '桌面', 'bgm', 'music')):
            track = '疑似游戏或桌面音轨'
            level, advice = 'warn', ('这条像是游戏或桌面声音；人声在别的音轨时，到首页素材那里换成人声那一轨再识别',)
        elif any(word in label.casefold() for word in ('microphone', 'mic', '麦克风', '人声')):
            track = '疑似麦克风音轨'
        detail = f'听的是{track}' + (f'，音轨起点相对画面偏移 {offset:+.0f} 毫秒' if offset else '')
        analysis.findings.append(Finding('音轨', level, '用了哪条音轨', detail, advice, '确定'))


def _primary(payload, analysis: Analysis, speech):
    settings = _dict(payload.get('settings'))
    asked = _base(_dict(settings.get('subtitle_language')).get('requested_language') or 'auto')
    primary, _timeline, _ai = _model_names(payload)
    control = ''
    for event in (*_events(payload, 'asr_language_control'), *_events(payload, 'cloud_language_policy')):
        control = control or str(event.get('language_control') or '')
    requests = sorted(_events(payload, 'asr_language_request'), key=lambda event: int(event.get('request_index') or 0))
    rows_by_request = {int(event.get('request_index') or 0): _list(event.get('rows'))
                       for event in _events(payload, 'asr_shard_ready')}
    cannot_choose = control == 'automatic_only'
    wrong = []
    density = []
    for event in requests:
        index = int(event.get('request_index') or 0)
        start, end = float(event.get('start') or 0), float(event.get('end') or 0)
        transcript = _dict(event.get('transcript'))
        heard = _base(transcript.get('language') or event.get('provider_detected_language') or '')
        characters = int(transcript.get('characters') or 0)
        text = ''.join(str(row.get('text') or '') for row in rows_by_request.get(index, ()) if isinstance(row, dict))
        if not characters and text:
            characters = len(text)
        shares = _script_shares(text)
        by_script = ''
        if asked == 'zh' and shares:
            if shares.get('ja', 0) >= SCRIPT_SHARE:
                by_script = 'ja'
            elif shares.get('ko', 0) >= SCRIPT_SHARE:
                by_script = 'ko'
            elif shares.get('latin', 0) >= 0.6 and shares.get('zh', 0) < 0.3:
                by_script = 'en'
        if asked not in ('', 'auto') and ((heard and heard != asked) or by_script):
            wrong.append((index, start, end, heard if heard and heard != asked else by_script))
        seconds = _speech_in(speech, start, end) if speech else 0.0
        if seconds >= LOW_DENSITY_MIN_SPEECH_S:
            density.append((index, start, end, characters / (seconds / 60), seconds, characters))
    if wrong:
        parts = '、'.join(f'第 {index + 1} 段（{_clock(start)}–{_clock(end)}）认成了{_language(code)}'
                         for index, start, end, code in wrong[:4])
        advice = []
        if cannot_choose:
            advice.append(f'{primary} 不能指定语言，只能自己判断，这次判断错了；在首页「主力转写」换一个能指定语言的'
                          '（本机 MOSS、阿里云百炼、Qwen Cloud 等），「视频里说的话」选对语言后重新识别')
        else:
            advice.append('在首页把「视频里说的话」选成实际的语言（不确定选自动识别语言），再重新识别')
        advice.append('只有一段错时：在字幕工作台用 I / O 框住那一段，换好主力转写后「只重新识别这一段字幕…」，其他已改好的字幕不动')
        analysis.findings.append(Finding('主力转写', 'problem', f'{primary} 把语言听错了',
                                         f'用户选的是{_language(asked)}，{parts}', tuple(advice), '确定'))
    elif requests and asked not in ('', 'auto') and all(
        _base(_dict(event.get('transcript')).get('language') or event.get('provider_detected_language')) == asked
        for event in requests
    ):
        note = '；这个服务不能指定语言，只能自己判断' if cannot_choose else ''
        analysis.findings.append(Finding('主力转写', 'ok', '语言没有听错',
                                         f'{len(requests)} 段都认成了{_language(asked)}{note}', (), '确定'))
    if len(density) >= 2:
        rates = [row[3] for row in density]
        for position, (index, start, end, rate, seconds, characters) in enumerate(density):
            reference = statistics.median(rates[:position] + rates[position + 1:])
            if reference > 0 and rate < reference * LOW_DENSITY_SHARE:
                analysis.findings.append(Finding(
                    '主力转写', 'warn', f'第 {index + 1} 段字特别少',
                    f'{_clock(start)}–{_clock(end)} 有 {seconds / 60:.1f} 分钟像人声，只出了 {characters} 个字'
                    f'（每分钟 {rate:.0f} 字，其他段大约 {reference:.0f} 字）',
                    ('试听这一段：真的有人说话却没字幕，就用 I / O 框住这一段「只重新识别这一段字幕…」，或换一个主力转写',
                     '那一段多是游戏声音、音乐时字少是正常的'), '可能'))
    coverage = _dict(_dict(payload.get('result')).get('speech_coverage'))
    gaps = [gap for gap in _list(coverage.get('gaps')) if isinstance(gap, dict)]
    if gaps and speech:
        gap_seconds = sum(max(0.0, float(gap.get('end') or 0) - float(gap.get('start') or 0)) for gap in gaps)
        total = sum(end - start for start, end in speech) or 1.0
        share = gap_seconds / total
        first = sorted(gaps, key=lambda gap: float(gap.get('start') or 0))[:3]
        where = '、'.join(_clock(gap.get('start')) for gap in first)
        level = 'problem' if share >= GAP_SHARE_BAD else 'warn' if share >= GAP_SHARE_WARN else 'info'
        analysis.findings.append(Finding(
            '主力转写', level, '有些像人声的地方没有字幕',
            f'{len(gaps)} 处、共 {gap_seconds / 60:.1f} 分钟（占全部人声的 {share:.0%}），例如 {where}',
            ('在字幕工作台的审核模式里试听这些「疑似语音待试听确认」：真有人说话就按 T 补一条，或用 I / O 框住「只重新识别这一段字幕…」',
             '很多处都漏的话，多半是声音太小、被游戏声盖住，或主力转写漏听；可以换一个主力转写重新识别'),
            '很可能' if share >= GAP_SHARE_WARN else '可能'))
    for status in _dict(_dict(payload.get('result')).get('model_statuses')).values():
        status = _dict(status)
        if status.get('selected') and status.get('failed'):
            analysis.findings.append(Finding('主力转写' if 'primary' in str(status.get('role')) else '字幕时间轴',
                                             'problem', '选用的模型未完成', '',
                                             ('查看本机任务中的失败详情，处理后重新识别',), '确定'))
    pending = _dict(_dict(payload.get('result')).get('transcript_counts')).get('pending_range_count')
    if pending:
        analysis.findings.append(Finding('主力转写', 'problem', f'{pending} 段转写因为语言冲突被暂时扣下',
                                         '这些段有原始文字，但和选的语言对不上，还没变成字幕',
                                         ('完成页点「核对候选与恢复」看原文、试听，确认后选对语言继续处理',), '确定'))


def _timing(payload, analysis: Analysis, speech):
    result = _dict(payload.get('result'))
    owner = str(_dict(result.get('cache_owners')).get('final_timing') or '')
    _primary_name, timeline, _ai = _model_names(payload)
    basis = {}
    for event in _events(payload, 'grouping_timing_evidence'):
        for name, count in _dict(event.get('boundary_basis_counts')).items():
            basis[name] = basis.get(name, 0) + int(count or 0)
    cuts = sum(basis.values())
    estimated = basis.get('estimate', 0)
    low = int(_dict(result.get('review_classification')).get('TIMING_LOW_CONFIDENCE') or 0)
    anchors = sum(1 for item in _list(payload.get('review_items')) if isinstance(item, dict)
                  and item.get('category') == '时间锚覆盖低')
    sentence_only = 'sentence' in owner.casefold() or '句段' in owner
    detail = []
    if owner:
        detail.append(f'最终时间来自：{"主力转写给的整句时间（没有逐字时间）" if sentence_only else timeline}')
    if cuts:
        detail.append(f'切字幕的 {cuts} 个位置里 {estimated} 个是估算的（{estimated / cuts:.0%}）')
    if low or anchors:
        detail.append(f'{low} 条时间可信度低，{anchors} 段逐字时间不够')
    share = estimated / cuts if cuts else 0.0
    weak = share >= ESTIMATE_SHARE_WARN or low >= 20 or (sentence_only and timeline == '未启用')
    if detail:
        advice = []
        if weak:
            advice.append('想让每条字幕的起止都贴着声音：在首页把「字幕时间轴」选成「Qwen3 对齐 · Ultra」，它会按最终字幕的文字重新量时间，再重新识别')
            advice.append('只改几条：在字幕工作台选中那几条，右键「智能修轴」（会按声音重新量这几条的时间，能一步撤销）')
        analysis.findings.append(Finding('字幕时间轴', 'warn' if weak else 'ok',
                                         '有一部分字幕时间是估出来的' if weak else '逐字时间够用',
                                         '；'.join(detail), tuple(advice), '很可能' if weak else '确定'))
    cues = _final_cues(payload)
    if cues and len(speech) >= 20:
        measured = sum(end - start for start, end in cues) or 1.0
        base = _overlap(cues, speech) / measured
        best_shift, best = 0.0, base
        steps = int(OFFSET_RANGE_S * 20)
        for step in range(-steps, steps + 1):
            shift = step / 20
            value = _overlap(cues, speech, shift) / measured
            if value > best + 1e-9:
                best_shift, best = shift, value
        if abs(best_shift) >= OFFSET_MIN_S and best - base >= OFFSET_GAIN:
            late = best_shift < 0
            presses = round(abs(best_shift) / 0.1)
            analysis.findings.append(Finding(
                '字幕时间轴', 'problem', f'整部字幕大约{"晚" if late else "早"}了 {abs(best_shift):.1f} 秒',
                f'字幕整体移动 {best_shift:+.1f} 秒后和人声的重合从 {base:.0%} 变成 {best:.0%}',
                (f'在字幕工作台按 Ctrl+A 全选，再按 {"Alt+←（提前）" if late else "Alt+→（推后）"} {presses} 次'
                 '（每次 0.1 秒）；兔白也能直接帮忙整体移动，能撤销',
                 '如果是多音轨视频，检查听的那条音轨在录制软件里有没有设延迟'), '很可能'))
        else:
            analysis.findings.append(Finding('字幕时间轴', 'ok', '整部字幕没有整体提前或延后',
                                             f'字幕和人声的重合 {base:.0%}，整体移动也不会更好', (), '确定'))


def _polish(payload, analysis: Analysis):
    summary = _dict(payload.get('polishing_summary'))
    fallbacks = _events(payload, 'polishing_api_fallback')
    if not summary and not fallbacks:
        return
    failed = int(summary.get('fallback_cues') or 0)
    categories = _dict(summary.get('failure_categories'))
    done = int(summary.get('success_cues') or 0)
    retried = sum(len(_list(event.get('cue_ids'))) for event in fallbacks)
    if failed:
        known = {'rate_limited', 'timeout', 'auth', 'quota', 'invalid_response', 'empty_response',
                 'truncated', 'network_error', 'provider_error', 'parse_error'}
        names = '、'.join(f'{name}×{int(count)}' for name, count in categories.items() if name in known)
        analysis.findings.append(Finding('AI 校对', 'problem', f'{failed} 条没有校对成',
                                         f'没校对成的原因：{names or "未记录"}；这些条用的是没校对的原文',
                                         ('先确认文字 AI 的 Key 有余额、没被限流，再在完成页按「重试」只补这些（兔白也能帮忙补，会用一点 Key）',),
                                         '确定'))
    else:
        note = f'；中途有 {retried} 条第一次返回格式不对，自动重试后都好了' if retried else ''
        analysis.findings.append(Finding('AI 校对', 'ok', '校对都完成了', f'{done} 条都校对过{note}', (), '确定'))


def _grouping(payload, analysis: Analysis):
    batches = len(_events(payload, 'grouping_trace')) or len(_events(payload, 'grouping_model_quality'))
    if not batches:
        return
    fallback = len(_events(payload, 'grouping_minimal_fallback'))
    retries = len(_events(payload, 'grouping_quality_retry'))
    short = 0
    for event in _events(payload, 'final_subtitle_validation')[-1:]:
        short = int(event.get('short_cues') or 0)
    detail = f'{batches} 批断句；{retries} 处让 AI 重切过，{fallback} 处 AI 切不好、改用本地规则切；{short} 条显示时间太短'
    level = 'warn' if fallback >= max(5, batches) else 'ok'
    advice = ('嫌太长或太碎：选中那几条用「AI 断句（选中范围）」重切，或告诉兔白“一行别超过 N 个字”，她会写进断句偏好',) \
        if level == 'warn' else ()
    analysis.findings.append(Finding('AI 断句', level, '断句有不少是本地规则切的' if level == 'warn' else '断句完成',
                                     detail, advice, '确定'))


def _catalog(payload, analysis: Analysis, ai_ready):
    try:
        from ..recognition.run_diagnosis import DiagnosisInput, diagnose_run
        diagnosis = diagnose_run(DiagnosisInput(report=payload, ai_ready=ai_ready))
    except Exception:  # noqa: BLE001 - the catalog is a second opinion
        return
    for finding in diagnosis.findings[:5]:
        issue = finding.issue
        analysis.catalog.append(f'{issue.title}：{(issue.advice or issue.cause)[:120]}')


def analyze(payload: dict, *, ai_ready: bool | None = None) -> Analysis:
    analysis = Analysis()
    if not isinstance(payload, dict):
        analysis.overview.append('- 这不是识别任务的 JSON')
        return analysis
    speech = _ranges(_dict(_dict(payload.get('result')).get('speech_coverage')).get('speech_ranges'))
    for step in (_overview, _audio_track):
        step(payload, analysis)
    _primary(payload, analysis, speech)
    _timing(payload, analysis, speech)
    _polish(payload, analysis)
    _grouping(payload, analysis)
    _catalog(payload, analysis, ai_ready)
    return analysis


def looks_like_task(payload) -> bool:
    """A recognition task journal or report (what the analysis understands)."""
    return isinstance(payload, dict) and isinstance(payload.get('settings'), dict) and (
        isinstance(payload.get('events'), list) or isinstance(payload.get('result'), dict)) and (
        'stages' in payload or 'journal_version' in payload)


MAX_FILE_BYTES = 80 * 1024 * 1024


def load(path, *, local_journal=False) -> dict:
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('文件太大')
    if local_journal and path.name == 'task.json':
        from ..recognition.task_journal import report_payload
        return report_payload(path)
    return json.loads(path.read_text(encoding='utf-8-sig'))


def summarize(payload, *, ai_ready: bool | None = None) -> str:
    try:
        return analyze(payload, ai_ready=ai_ready).text()
    except (TypeError, ValueError, OverflowError, KeyError):
        return '识别记录中的部分字段无法读取，可在本机打开任务详情查看。'


def analyze_file(path, *, ai_ready: bool | None = None, local_journal=False) -> str:
    try:
        payload = load(path, local_journal=local_journal)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return f'这个文件读不出来（{type(error).__name__}）'
    if not looks_like_task(payload):
        return '这个 JSON 不是识别任务的记录（没有设置、步骤和结果），没法按步骤分析'
    return summarize(payload, ai_ready=ai_ready)


# ---- which recognition: the open project's, a numbered one, or the newest ---------------------
def project_job_id(window) -> str:
    """The recognition task the open workbench project came from ('' when none or unknown)."""
    try:
        from .bunny_tools import _built
        project = getattr(_built(window, 'studio'), 'project', None)
        return str(getattr(project, 'generation_metadata', {}).get('job_id') or '') if project is not None else ''
    except Exception:  # noqa: BLE001 - no project, no preference
        return ''


def task_path(job_id: str = '', number: int = 0):
    """(path, how it was chosen) of the recognition to analyse, or (None, why not)."""
    from ..recognition.task_journal import task_root
    from ..recognition.recognition_result import validate_job_id
    from .bunny_nav_tools import result_records
    if number:
        rows = result_records()
        if not 1 <= number <= len(rows):
            return None, f'没有第 {number} 条识别记录（recent_results 看编号）'
        return rows[number - 1][0], f'识别记录第 {number} 条'
    try:
        job_id = validate_job_id(job_id)
    except ValueError:
        job_id = ''
    if job_id:
        candidate = task_root() / job_id / 'task.json'
        if candidate.is_file():
            return candidate, '现在打开的工程是这次识别做出来的'
    from .bunny_lookup import newest_report
    newest = newest_report()
    if newest is None:
        return None, '这台电脑上还没有识别记录'
    return newest, '最近一次识别'


def _tool(settings, args) -> str:
    from .bunny_tools import ToolError
    from ..recognition.task_journal import task_root
    try:
        number = int(args.get('number') or 0)
    except (TypeError, ValueError):
        raise ToolError('number 要填 recent_results 里的编号（数字）') from None
    path, why = task_path((settings or {}).get('_bunny_recognition_job_id', ''), number)
    if path is None:
        raise ToolError(why)
    path = Path(path).resolve()
    local_journal = path.name == 'task.json' and path.parent.parent == task_root().resolve()
    return f'（分析的是：{why}）\n' + analyze_file(path, local_journal=local_journal)


def tools():
    from .bunny_tools import Tool
    return (
        Tool('analyze_recognition', '{"number": 0}',
             '（后台查，稍慢）读一次识别的原始 JSON，按步骤分析：用的音轨、主力转写（语言有没有听错、漏了多少人声、哪段字特别少）、'
             '字幕时间轴（多少是估算的、整部有没有提前或延后）、AI 校对、AI 断句，每步给原因和怎么办。'
             '不填 = 现在打开的工程那次，没有就最近一次；number = recent_results 的编号',
             _tool, background=True),
    )


__all__ = ['Analysis', 'Finding', 'STEPS', 'analyze', 'analyze_file', 'load', 'looks_like_task', 'project_job_id',
           'task_path', 'tools']
