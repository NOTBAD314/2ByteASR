"""The local checks behind 排查原因: one per known problem (2026-10-23).

Each check reads ``RunFacts`` (one task report, normalized once) and returns a
``Finding`` for its catalog entry, or nothing. They only state what the report
shows: event names, settings and error texts are quoted as evidence, and the
confidence says how directly the report names the cause. Report fields used
here are mapped in ``docs/exec-plans/active/2026-10-23-recognition-diagnosis.md``.
"""
from __future__ import annotations

from collections import Counter
import re

from .run_diagnosis import RunFacts, check, clip, found

# Display names for the settings values; Chinese ones are catalog strings.
PRIMARY_NAMES = {
    "moss": "MOSS", "sensevoice": "SenseVoice", "api": "在线 API", "qwen_local": "Qwen3-ASR",
    "firered": "FireRedASR2", "paraformer": "Paraformer", "whisper_turbo": "Whisper", "funasr_nano": "Fun-ASR Nano",
    "glm_asr_nano": "GLM-ASR", "canary_qwen": "Canary", "mlx_qwen3_asr": "Qwen3-ASR (MLX)",
}
TIMELINE_NAMES = {
    "local": "FireRedASR2-AED", "qwen_aligner": "Qwen3 对齐", "mlx_qwen_aligner": "Qwen3 对齐",
    "mfa_aligner": "MFA（实验）", "paraformer": "Paraformer", "whisper_turbo": "Whisper", "off": "已关闭",
}
LANGUAGE_NAMES = {
    "zh": "中文", "ja": "日语", "en": "英语", "ko": "韩语", "es": "西班牙语", "de": "德语",
    "fr": "法语", "pt": "葡萄牙语", "it": "意大利语", "ru": "俄语",
}
TRANSLATED_NAMES = ("在线 API", "Qwen3 对齐", "MFA（实验）", "已关闭", "开启", "（没有）") + tuple(LANGUAGE_NAMES.values())
# Every task-specific sentence a check can produce (translated like UI text).
SPECIFIC_TEMPLATES = (
    "这次的字幕语言是「{chosen}」，但识别出的文字看起来是{actual}。",
    "这次的主力转写是 {primary}，字幕时间轴：{timeline}。",
    "这次 AI 断句：{group}；AI 校对：{polish}。",
    "出错的位置：说话人 {speaker}，视频的 {clock}。",
    "出错的位置：视频的 {clock}。原文里的数字是 {expected}，断句后读出来是 {actual}；"
    "这次既没有字级时间轴、也没开 AI 断句，本地规则只能按字数切，最容易出现这种情况。",
    "出错的位置：视频的 {clock}。原文里的数字是 {expected}，断句后读出来是 {actual}。",
    "被拦下的时间：{ranges}；补识别用的是本地 {model}。",
    "被拦下的时间：{ranges}。{why}",
    "所在的段：{ranges}。MOSS Pro 返回的 {segments} 句里，{clipped} 句结尾超出上传的音频、已截到音频结尾，"
    "{dropped} 句的时间不在这段音频里或起止颠倒、没有放进字幕。",
)
# Why a gap the cloud's content review left was not filled (cloud_gap_fill).
GAP_FILL_REASONS = {
    "no_local_model": "这台电脑上没有能补这段语言的本地主力模型。",
    "fill_failed": "本地模型补识别失败。",
    "no_text": "本地模型没有识别出文字。",
}
TRANSLATED_NAMES += tuple(GAP_FILL_REASONS.values())


def _name(table: dict, value: str) -> str:
    return table.get(str(value or "").lower(), str(value or "?"))


def _clock(seconds) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "?"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _event_line(row: dict, *keys: str) -> str:
    name = str(row.get("event") or "")
    parts = [f"{key}={clip(row.get(key), 140)}" for key in keys if row.get(key) not in (None, "", [], {})]
    return f"events[{name}]" + (" · " + " · ".join(parts) if parts else "")


def _error_line(error: str) -> str:
    return "error: " + clip(error, 220)


# ---- 素材与音频 ---------------------------------------------------------------

@check("media_unreadable")
def _media_unreadable(facts: RunFacts):
    error = facts.error_matches(r"moov atom not found|Invalid data found when processing input|does not contain any stream|"
                                r"no audio stream|没有音频流|不包含音频|Output file #0 does not contain any stream|无法读取音频|"
                                r"ffmpeg 音频解码失败|统一音频解码没有得到有效的单声道采样")
    if error:
        return found("media_unreadable", "certain", [_error_line(error)])


@check("language_mismatch")
def _language_mismatch(facts: RunFacts):
    event = facts.language_event
    if not event:
        return None
    chosen = str(event.get("requested") or event.get("language") or "").lower()
    actual = str(event.get("disagrees_with_transcript") or "").lower()
    evidence = [_event_line(event, "language", "requested", "decided_by", "disagrees_with_transcript", "kana", "han", "latin")]
    if not actual:
        # Older reports: Japanese requested, but the text has no kana at all.
        try:
            kana, han = int(event.get("kana") or 0), int(event.get("han") or 0)
        except (TypeError, ValueError):
            return None
        if chosen == "ja" and kana == 0 and han >= 50:
            actual = "zh"
        else:
            return None
    if not chosen or actual == chosen:
        return None
    confidence = "certain" if str(event.get("decided_by") or "") == "manual" else "likely"
    return found("language_mismatch", confidence, evidence,
                 specific="这次的字幕语言是「{chosen}」，但识别出的文字看起来是{actual}。",
                 translate=("chosen", "actual"), chosen=_name(LANGUAGE_NAMES, chosen), actual=_name(LANGUAGE_NAMES, actual))


@check("empty_result")
def _empty_result(facts: RunFacts):
    error = facts.error_matches(r"没有生成有效文字|returned no parsed text|no valid output|没有识别出|empty_result|识别结果为空|"
                                r"没有检测到语音|没有发现有效语音|没有形成可用语音区间|没有生成可用片段|returned no usable segments|"
                                r"返回成功，但没有识别文本|没有可用的字幕行|断句后没有可用字幕")
    # The incremental pass may fail on "no parsed text" and the full stage
    # still succeed; only a terminal error or a 0-cue result counts.
    terminal = error and error in (str(facts.result.get("error") or ""), facts.input.item_error) or any(
        error and error == str(row.get("error") or "") for row in facts.failed_stages)
    if terminal:
        return found("empty_result", "likely", [_error_line(error)])
    if not facts.failed and not facts.cancelled and "cue_count" in facts.result and facts.cue_count == 0:
        return found("empty_result", "certain", ["result.cue_count = 0"])


@check("sparse_result")
def _sparse_result(facts: RunFacts):
    minutes = facts.audio_seconds / 60
    if facts.failed or facts.cancelled or minutes < 5 or facts.cue_count <= 0:
        return None
    rate = facts.cue_count / minutes
    if rate < 3:
        return found("sparse_result", "possible",
                     [f"result.cue_count = {facts.cue_count}", f"audio_seconds = {facts.audio_seconds:.0f}",
                      f"cues_per_minute = {rate:.1f}"])


# ---- 运行环境与模型 -------------------------------------------------------------

@check("model_missing")
def _model_missing(facts: RunFacts):
    error = facts.error_matches(r"未完整安装|请先在模型工坊下载|model not found|找不到模型|模型文件(?:不存在|缺失|不完整)|"
                                r"未安装|environment_missing|weights? (?:not found|missing)")
    rows = [row for row in facts.events_named("MODEL_FAILED")
            if str(row.get("failure_reason") or "").startswith("environment_missing")]
    rows += [row for row in facts.events_named("MODEL_ENVIRONMENT_READY")
             if row.get("environment_ready") is False and row.get("missing_paths")]
    if error or rows:
        evidence = ([_error_line(error)] if error else []) + [_event_line(row, "model_id", "failure_reason", "missing_paths") for row in rows[:2]]
        return found("model_missing", "certain", evidence)


@check("runtime_broken")
def _runtime_broken(facts: RunFacts):
    error = facts.error_matches(r"No module named|DLL load failed|ImportError|runtime missing|缺少新流水线组件|"
                                r"environment_not_ready|environment is not ready|运行环境(?:未就绪|缺少|损坏|不可用|不完整)|找不到 ?python|"
                                r"模型运行库未准备完成|环境探测|trampoline failed|os error 32")
    rows = [row for row in facts.events_named("MODEL_FAILED")
            if str(row.get("failure_reason") or "").startswith("environment_not_ready")]
    if error or rows:
        evidence = ([_error_line(error)] if error else []) + [_event_line(row, "model_id", "failure_reason") for row in rows[:2]]
        return found("runtime_broken", "certain", evidence)


@check("no_cuda")
def _no_cuda(facts: RunFacts):
    error = facts.error_matches(r"CUDA (?:is )?not available|no CUDA GPUs|Torch not compiled with CUDA|未检测到 ?NVIDIA|"
                                r"CUDA driver version is insufficient|Found no NVIDIA driver|没有可用的 ?CUDA|需要 NVIDIA CUDA")
    if error:
        return found("no_cuda", "certain", [_error_line(error)])


@check("gpu_out_of_memory")
def _gpu_out_of_memory(facts: RunFacts):
    error = facts.error_matches(r"out of memory|OutOfMemoryError|显存不足|显存分配失败")
    plan = facts.moss.get("window_plan") if isinstance(facts.moss.get("window_plan"), dict) else {}
    insufficient = plan.get("mode") == "insufficient"
    if (error or insufficient) and not facts.error_matches(r"1455|页面文件"):
        gpu = facts.last_event("GPU_STATUS")
        evidence = [_error_line(error)] if error else []
        if insufficient:
            evidence.append(f"moss_execution.window_plan.mode = insufficient · usable_bytes={plan.get('usable_bytes')}")
        if gpu.get("total_vram_gb"):
            evidence.append(_event_line(gpu, "gpu_name", "total_vram_gb", "free_vram_gb"))
        return found("gpu_out_of_memory", "certain", evidence)


@check("pagefile_too_small")
def _pagefile(facts: RunFacts):
    pattern = r"os error 1455|winerror 1455|paging file is too small|页面文件太小|虚拟内存不足|页面文件"
    error = facts.error_matches(pattern)
    if error:
        return found("pagefile_too_small", "certain", [_error_line(error)])
    review = facts.review_matches(pattern)
    if review:  # an optional model (aligner) did not load; the task went on
        return found("pagefile_too_small", "certain", ["review_items: " + clip(review, 200)], severity="problem")
    weak = facts.error_matches(r"Memory allocation failure|CUBLAS_STATUS_ALLOC_FAILED")
    if weak:
        return found("pagefile_too_small", "possible", [_error_line(weak)])


@check("moss_too_long")
def _moss_too_long(facts: RunFacts):
    error = facts.error_matches(r"exceeds max_length|131072")
    if error:
        return found("moss_too_long", "certain", [_error_line(error)])


@check("worker_timeout")
def _worker_timeout(facts: RunFacts):
    error = facts.error_matches(r"worker timeout|超过 ?\d+ ?分钟未完成|没有任何进度输出|worker timed out")
    if error:
        return found("worker_timeout", "certain", [_error_line(error)])


@check("worker_crashed")
def _worker_crashed(facts: RunFacts):
    error = facts.error_matches(r"worker failed \(exit|退出码|子进程未返回具体异常|进程退出后未生成结果文件|0xC0000005|"
                                r"3221225477|access violation|worker produced no valid output")
    exits = [row for row in facts.events_named("asr_worker_exited") if row.get("returncode") not in (None, 0)]
    if error or (facts.failed and exits):
        evidence = ([_error_line(error)] if error else []) + [_event_line(row, "backend", "returncode") for row in exits[:2]]
        moss = facts.last_event("moss_worker_failure")
        if moss:
            evidence.append(_event_line(moss, "returncode", "error", "failure_stage"))
        return found("worker_crashed", "likely", evidence)


# ---- 在线识别 -----------------------------------------------------------------

_CLOUD_WORDS = re.compile(r"云端识别服务|在线 ?ASR|MOSI|MOSS Pro|百炼|Qwen Cloud|Filetrans|录音文件识别|DashScope|短块", re.I)


def _cloud_errors(facts: RunFacts) -> list[str]:
    """Errors of the online recognition steps only (not text AI)."""
    errors = [str(row.get("error") or "") for row in facts.failed_stages
              if re.search(r"API|在线|云端 ?ASR", str(row.get("label") or "")) and row.get("error")]
    for error in facts.errors:
        if ("[2BYTEASR_API_ERROR]" in error or _CLOUD_WORDS.search(error)
                or (facts.primary == "api" and re.search(r"ASR|识别|filetrans|dashscope|transcri", error, re.I))):
            errors.append(error)
    return list(dict.fromkeys(error for error in errors if error))


def _marker_category(error: str) -> str:
    """``category`` of the cloud worker's machine-readable failure line.

    Decoded like the retry button does: since 2026-10-23 the message can quote
    the provider's reason, braces included, which the old pattern cut short.
    """
    from ..providers.cloud_api_worker import failure_from_text
    problem = failure_from_text(error)
    return str((problem or {}).get("category") or "").lower()


def _cloud_check(issue_id: str, categories: set[str], pattern: str):
    def run(facts: RunFacts):
        for error in _cloud_errors(facts):
            if _marker_category(error) in categories or re.search(pattern, error, re.I):
                return found(issue_id, "certain", [_error_line(error)])
    return run


check("cloud_asr_auth")(_cloud_check(
    "cloud_asr_auth", {"key", "permission", "auth_failed"},
    r"\b40[13]\b|InvalidApiKey|Unauthorized|AccessDenied|鉴权|invalid[ _-]?api[ _-]?key|auth_error|"
    r"拒绝了这个 API Key|缺少 API Key|不认这把 API Key|拒绝访问|没有调用.*的权限|还没有填写云端识别服务的 API Key|Token Plan"))
check("cloud_asr_quota")(_cloud_check(
    "cloud_asr_quota", {"balance", "insufficient_credits", "quota_exhausted"},
    r"Arrearage|欠费|余额不足|积分不足|insufficient[ _]balance|insufficient_quota|免费额度已用完|补全付款信息|\b402\b"))
check("cloud_asr_rate_limited")(_cloud_check(
    "cloud_asr_rate_limited", {"rate_limit", "rate_limited"},
    r"\b429\b|请求过于频繁|请求太频繁|并发已满|没有成功返回任何短块"))
check("cloud_asr_network")(_cloud_check(
    "cloud_asr_network", {"network"},
    r"连不上|上传时网络中断|CERTIFICATE_VERIFY_FAILED|ConnectionError|网络"))
check("cloud_asr_content_blocked")(_cloud_check(
    "cloud_asr_content_blocked", {"content_blocked"},
    r"内容安全审查|safety[ _]?guardrail|safety[ _]?policy|\"code\":\s*\"content_(blocked|rejected)\""))
check("cloud_asr_resubmit")(_cloud_check(
    "cloud_asr_resubmit", {"resubmit_needed"},
    r"是否受理未知|已保存远端终态|查不到这个任务|任务执行失败|本地等待达到时限|本地轮询达到时限|超过安全时限|\"resubmit\":\s*true"))
check("cloud_asr_input_limit")(_cloud_check(
    "cloud_asr_input_limit", set(),
    r"512 ?MB|单个文件最长|原生说话人任务限|2GB限制|必须在5分钟以内"))
check("cloud_asr_hotwords")(_cloud_check(
    "cloud_asr_hotwords", set(),
    r"热词|上下文不得超过"))
check("cloud_asr_upload_setup")(_cloud_check(
    "cloud_asr_upload_setup", {"file_access"},
    r"音频交给服务商的方式|Bucket 或 AccessKey|服务端没能读取上传的音频"))
# What 0.8.4 and earlier stopped on (2026-10-25); now such sentences are clipped or left out.
check("cloud_asr_timing_rejected")(_cloud_check(
    "cloud_asr_timing_rejected", set(), r"句段[时時]间越出提交的音[频訊]"))


@check("cloud_asr_timing_repaired")
def _cloud_timing_repaired(facts: RunFacts):
    # One row per request, the last one if a request was converted twice.
    rows = list({tuple(row.get("segment") or ()): row
                 for row in facts.events_named("cloud_asr_timing_repaired")}.values())
    if facts.failed or not rows:
        return None

    def total(*keys):
        return sum(int(row.get(key) or 0) for row in rows for key in keys)

    dropped = total("outside", "reversed", "invalid")
    # Only clipped ends: a note. Sentences left out: some subtitles are missing.
    return found("cloud_asr_timing_repaired", "certain",
                 [_event_line(row, "segment", "segments", "clipped", "outside", "reversed", "invalid", "latest_end")
                  for row in rows[:2]],
                 specific="所在的段：{ranges}。MOSS Pro 返回的 {segments} 句里，{clipped} 句结尾超出上传的音频、已截到音频结尾，"
                          "{dropped} 句的时间不在这段音频里或起止颠倒、没有放进字幕。",
                 severity="quality" if dropped else "",
                 ranges="、".join(f"{_clock(row.get('start'))}–{_clock(row.get('end'))}" for row in rows),
                 segments=total("segments"), clipped=total("clipped"), dropped=dropped)


def _gap_ranges(row: dict) -> str:
    return "、".join(f"{_clock(start)}–{_clock(end)}" for start, end in row.get("ranges") or ())


@check("cloud_asr_gap_filled")
def _cloud_gap_filled(facts: RunFacts):
    row = facts.last_event("cloud_asr_gap_fill")
    if facts.failed or not row or not row.get("filled"):
        return None
    return found("cloud_asr_gap_filled", "certain", [_event_line(row, "ranges", "backend", "rows")],
                 specific="被拦下的时间：{ranges}；补识别用的是本地 {model}。",
                 ranges=_gap_ranges(row), model=str(row.get("model") or row.get("backend") or "?"))


@check("cloud_asr_gap_unfilled")
def _cloud_gap_unfilled(facts: RunFacts):
    row = facts.last_event("cloud_asr_gap_fill")
    if facts.failed or not row or row.get("filled"):
        return None
    return found("cloud_asr_gap_unfilled", "certain", [_event_line(row, "ranges", "reason", "error")],
                 specific="被拦下的时间：{ranges}。{why}", translate=("why",),
                 ranges=_gap_ranges(row), why=GAP_FILL_REASONS.get(str(row.get("reason") or ""), ""))


@check("cloud_asr_failed")
def _cloud_failed(facts: RunFacts):
    errors = _cloud_errors(facts)
    if errors and facts.failed:
        return found("cloud_asr_failed", "likely", [_error_line(errors[0])])


# ---- 字词时间与时间轴 ------------------------------------------------------------

@check("no_word_timing")
def _no_word_timing(facts: RunFacts):
    if facts.timeline != "off" or facts.cancelled:
        return None
    if facts.failed and not facts.stage_named("断句", "最终字幕时间轴"):
        return None  # the run stopped before timing mattered
    evidence = [facts.setting_line("models.primary_asr_backend"), facts.setting_line("models.firered_asr_backend")]
    skipped = facts.first_event("MODEL_SKIPPED")
    if skipped.get("failure_reason") == "timeline_backend_off":
        evidence.append(_event_line(skipped, "model_id", "role", "failure_reason"))
    return found("no_word_timing", "certain", evidence,
                 specific="这次的主力转写是 {primary}，字幕时间轴：{timeline}。",
                 translate=("primary", "timeline"),
                 primary=_name(PRIMARY_NAMES, facts.primary), timeline=_name(TIMELINE_NAMES, facts.timeline))


@check("alignment_degraded")
def _alignment_degraded(facts: RunFacts):
    rows = [row for row in facts.events_named("model_degraded") if row.get("model_id") == "firered"]
    rows += facts.events_named("forced_alignment_failed", "forced_alignment_unavailable", "FIRERED_FORCED_ALIGN_FAILURE")
    failed = [row for row in facts.failed_stages
              if re.search(r"ForcedAligner|字词时间|独立文字证据|中文字幕时间轴|多语种字幕时间轴", str(row.get("label") or ""))
              and "锁定最终" not in str(row.get("label") or "")]
    items = sum(facts.review_categories.get(category, 0)
                for category in ("时间轴模型失败", "时间轴模型 FireRed 未完成", "缺少对齐模型"))
    if not (rows or failed or items):
        return None
    evidence = [_event_line(row, "model_id", "reason", "error", "fallback_owner") for row in rows[:2]]
    evidence += [f"stages[{row.get('label')}] = failed · {clip(row.get('error'), 140)}" for row in failed[:1]]
    if items:
        evidence.append(f"review_items: 时间轴模型失败 × {items}")
    return found("alignment_degraded", "certain", evidence)


@check("review_model_failed")
def _review_model_failed(facts: RunFacts):
    rows = [row for row in facts.events_named("model_degraded") if row.get("model_id") in {"qwen3-asr", "qwen"}]
    items = sum(count for category, count in facts.review_categories.items()
                if category in {"文字复核模型 Qwen3 未完成", "Qwen3失败", "API复核失败", "FireRed-LLM跳过", "FireRed LLM失败",
                                "Whisper失败"})
    failed = [row for row in facts.failed_stages if "复核" in str(row.get("label") or "")]
    if rows or items or failed:
        evidence = [_event_line(row, "model_id", "reason") for row in rows[:1]]
        evidence += [f"stages[{row.get('label')}] = failed · {clip(row.get('error'), 140)}" for row in failed[:1]]
        if items:
            evidence.append(f"review_items: 文字复核未完成 × {items}")
        return found("review_model_failed", "certain", evidence)


@check("timeline_rerouted")
def _timeline_rerouted(facts: RunFacts):
    row = facts.first_event("timeline_backend_rerouted")
    if row:
        return found("timeline_rerouted", "certain", [_event_line(row, "from_backend", "to_backend", "backend", "language", "reason")])


@check("sensevoice_chunk_overlap")
def _sensevoice_overlap(facts: RunFacts):
    if facts.primary not in {"sensevoice", "funasr_nano"} or facts.has_event("incremental_asr_fallback", "incremental_chunk_overlap_split"):
        return None
    rows = facts.events_named("grouping_postprocess_rejected", "grouping_local_source_boundary_fallback")
    stage9 = facts.error_matches(r"Stage 9后处理违反原文逐字符守恒")
    if rows or stage9:
        evidence = [_event_line(row, "batch_index", "reason", "start") for row in rows[:2]]
        if stage9:
            evidence.insert(0, _error_line(stage9))
        return found("sensevoice_chunk_overlap", "likely" if stage9 else "possible", evidence)


# ---- AI 断句与校对 ---------------------------------------------------------------

AI_CATEGORY_ISSUES = (
    (r"auth|unauthori[sz]ed|forbidden|invalid[_ ]?api[_ ]?key|\b40[13]\b", "ai_auth_failed"),
    (r"quota|balance|arrear|payment|\b402\b", "ai_quota"),
    (r"rate[_ ]?limit|too[_ ]many|\b429\b", "ai_rate_limited"),
    (r"request_too_large|context|too[_ ]long|token[_ ]limit", "ai_request_too_large"),
    (r"configuration_error|model_not_supported|model[_ ]not[_ ]found|\b40[04]\b", "ai_model_config_rejected"),
    (r"tls|ssl|connect|network|dns|proxy|resolve", "ai_connection"),
    (r"timeout|timed[_ ]out|deadline", "ai_timeout"),
    (r"parse|format|json|schema|contract|empty_response|truncat|mismatch|invalid|refus|validation", "ai_bad_output"),
)
AI_FAILURE_EVENTS = ("polishing_api_fallback", "grouping_api_fallback", "text_ai_terminal_failure", "llm_request_failed")


def ai_category_issue(category: str, error: str = "") -> str:
    text = f"{category} {error}".lower()
    for pattern, issue in AI_CATEGORY_ISSUES:
        if re.search(pattern, str(category or "").lower()):
            return issue
    for pattern, issue in AI_CATEGORY_ISSUES:
        if re.search(pattern, text):
            return issue
    return ""


def _ai_failures(facts: RunFacts) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in facts.events_named(*AI_FAILURE_EVENTS):
        issue = ai_category_issue(str(row.get("category") or ""), str(row.get("error") or ""))
        grouped.setdefault(issue, []).append(row)
    return grouped


def _ai_check(issue_id: str):
    def run(facts: RunFacts):
        rows = _ai_failures(facts).get(issue_id)
        if not rows:
            return None
        counts = Counter(str(row.get("event")) for row in rows)
        evidence = [f"events[{name}] × {count}" for name, count in counts.items()]
        evidence += [_event_line(row, "category", "error", "batch_index") for row in rows[:2]]
        return found(issue_id, "certain", evidence)
    return run


for _issue in ("ai_auth_failed", "ai_quota", "ai_rate_limited", "ai_request_too_large", "ai_model_config_rejected",
               "ai_connection", "ai_timeout", "ai_bad_output"):
    check(_issue)(_ai_check(_issue))


@check("ai_partial_fallback")
def _ai_partial(facts: RunFacts):
    failures = _ai_failures(facts)
    unexplained = failures.get("", [])
    partial = facts.outcome is not None and facts.outcome.polish_status == "partial"
    fallback_items = facts.review_categories.get("校对回退", 0) + facts.review_categories.get("断句回退", 0)
    if not (unexplained or partial or fallback_items or failures):
        return None
    evidence = []
    if facts.outcome is not None and facts.outcome.fallback_records:
        evidence.append(f"polishing_summary.fallback_cues = {facts.outcome.fallback_records}")
    if fallback_items:
        evidence.append(f"review_items: 校对回退 / 断句回退 × {fallback_items}")
    evidence += [_event_line(row, "category", "error") for row in unexplained[:2]]
    explained = any(issue for issue in failures if issue)
    # The specific cause, when known, comes first; this one adds what to do now.
    return found("ai_partial_fallback", "certain", evidence or ["outcome.polish_status = partial"],
                 severity="tip" if explained else "")


@check("ai_key_missing")
def _ai_key_missing(facts: RunFacts):
    off = _ai_steps_off(facts)
    if not off or facts.input.ai_ready is not False:
        return None
    return found("ai_key_missing", "likely", off,
                 specific="这次 AI 断句：{group}；AI 校对：{polish}。", translate=("group", "polish"),
                 group="已关闭" if facts.switches.get("use_ai_grouping") is False else "开启",
                 polish="已关闭" if facts.switches.get("enable_ai_polish") is False else "开启")


@check("ai_steps_off")
def _ai_steps_off_tip(facts: RunFacts):
    off = _ai_steps_off(facts)
    if not off or facts.input.ai_ready is False:
        return None
    return found("ai_steps_off", "possible", off,
                 specific="这次 AI 断句：{group}；AI 校对：{polish}。", translate=("group", "polish"),
                 group="已关闭" if facts.switches.get("use_ai_grouping") is False else "开启",
                 polish="已关闭" if facts.switches.get("enable_ai_polish") is False else "开启")


def _ai_steps_off(facts: RunFacts) -> list[str]:
    if facts.cancelled or not facts.switches:
        return []
    off = [facts.setting_line(f"switches.{key}") for key in ("use_ai_grouping", "enable_ai_polish")
           if facts.switches.get(key) is False]
    return off


@check("ai_edits_rejected")
def _ai_edits_rejected(facts: RunFacts):
    context = facts.polish.get("term_context") if isinstance(facts.polish.get("term_context"), dict) else {}
    try:
        rejected = int(context.get("rejected_edits") or 0)
    except (TypeError, ValueError):
        rejected = 0
    numeric = facts.event_counts.get("numeric_edit_rejected", 0)
    if rejected or numeric:
        evidence = []
        if rejected:
            evidence.append(f"polishing_summary.term_context.rejected_edits = {rejected}")
        if numeric:
            evidence.append(f"events[numeric_edit_rejected] × {numeric}")
        return found("ai_edits_rejected", "certain", evidence)


@check("search_not_configured")
def _search(facts: RunFacts):
    outcome = facts.outcome
    if outcome is not None and outcome.search_status in {"not_configured", "unsupported"} and not facts.failed:
        return found("search_not_configured", "certain", [f"terminology_summary.status = {outcome.search_status}"])


@check("translation_failed")
def _translation(facts: RunFacts):
    rows = facts.events_named("subtitle_translation_failed")
    items = facts.review_categories.get("翻译未完成", 0)
    if rows or items:
        evidence = [_event_line(row, "error", "category") for row in rows[:2]]
        if items:
            evidence.append(f"review_items: 翻译未完成 × {items}")
        return found("translation_failed", "certain", evidence)


# ---- 断句与字幕保真 --------------------------------------------------------------

_FIDELITY = re.compile(r"字幕保真检查未通过[：:]\s*(\S+)\s+([\d.]+)s")


@check("fidelity_failed")
def _fidelity(facts: RunFacts):
    error = facts.error_matches(r"字幕保真检查未通过")
    if not error:
        return None
    match = _FIDELITY.search(error)
    evidence = [_error_line(error)]
    rows = facts.events_named("final_content_conservation_recovery")
    if rows:
        evidence.append(f"events[final_content_conservation_recovery] × {len(rows)}")
    hard = facts.event_counts.get("local_hard_split_recovery", 0)
    if hard:
        evidence.append(f"events[local_hard_split_recovery] × {hard}")
    if match:
        return found("fidelity_failed", "certain", evidence, specific="出错的位置：说话人 {speaker}，视频的 {clock}。",
                     speaker=match.group(1), clock=_clock(match.group(2)))
    return found("fidelity_failed", "certain", evidence)


@check("fidelity_numbers")
def _fidelity_numbers(facts: RunFacts):
    error = facts.error_matches(r"字幕保真检查未通过")
    if not error:
        return None
    match = _FIDELITY.search(error)
    rows = [row for row in facts.events_named("final_content_conservation_recovery")
            if list(row.get("expected_numbers") or []) != list(row.get("actual_numbers") or [])]
    if not rows:
        return None
    if match:
        # The recovery that ended in the failure, when it is recorded.
        at = float(match.group(2))
        rows.sort(key=lambda row: abs(float(row.get("start") or 0) - at))
    row = rows[0]
    # split_numbers (2026-10-28): where a line edge cut inside a number, e.g. 二十|五.
    evidence = [_error_line(error), _event_line(row, "speaker", "start", "end", "expected_numbers", "actual_numbers",
                                                "split_numbers")]
    without_timing = facts.timeline == "off"
    without_ai = facts.switches.get("use_ai_grouping") is False
    if without_timing and without_ai:
        specific = SPECIFIC_TEMPLATES[4]
    else:
        specific = SPECIFIC_TEMPLATES[5]
    return found("fidelity_numbers", "certain", evidence, specific=specific, translate=("expected", "actual"),
                 clock=_clock(row.get("start") if not match else match.group(2)),
                 expected=" ".join(map(str, row.get("expected_numbers") or [])) or "（没有）",
                 actual=" ".join(map(str, row.get("actual_numbers") or [])) or "（没有）")


@check("stage9_conservation")
def _stage9(facts: RunFacts):
    error = facts.error_matches(r"Stage 9后处理违反原文逐字符守恒")
    if error:
        return found("stage9_conservation", "certain", [_error_line(error)])


@check("japanese_morphology_failed")
def _japanese_morphology(facts: RunFacts):
    row = facts.first_event("japanese_morphology_unavailable")
    if row and not facts.language_event.get("disagrees_with_transcript"):  # the wrong language explains it
        return found("japanese_morphology_failed", "certain", [_event_line(row, "error")])


@check("grouping_local_fallback")
def _grouping_fallback(facts: RunFacts):
    rows = facts.events_named("grouping_postprocess_rejected", "grouping_local_source_boundary_fallback")
    hard = facts.event_counts.get("local_hard_split_recovery", 0)
    if rows or hard >= 10:
        evidence = [f"events[{name}] × {count}" for name, count in Counter(str(row.get("event")) for row in rows).items()]
        if hard:
            evidence.append(f"events[local_hard_split_recovery] × {hard}")
        return found("grouping_local_fallback", "certain" if rows else "likely", evidence)


# ---- 保存与输出 ------------------------------------------------------------------

@check("disk_full")
def _disk_full(facts: RunFacts):
    error = facts.error_matches(r"No space left|磁盘空间不足|WinError 112|ENOSPC|not enough space on the disk|磁盘已满")
    if error:
        return found("disk_full", "certain", [_error_line(error)])


@check("project_save_failed")
def _project_save(facts: RunFacts):
    error = facts.error_matches(r"识别结果工程保存失败|工程保存失败|project_save")
    rows = facts.events_named("studio_project_failed")
    project_error = str(facts.outputs.get("project_error") or facts.result.get("project_save_error") or "")
    if error or rows or project_error:
        evidence = [_error_line(error or project_error)] if (error or project_error) else []
        evidence += [_event_line(row, "error") for row in rows[:1]]
        return found("project_save_failed", "certain", evidence)


@check("cancelled")
def _cancelled(facts: RunFacts):
    if facts.cancelled:
        return found("cancelled", "certain", [f"status = {facts.status}"])


# ---- 设置 -----------------------------------------------------------------------

@check("settings_warnings")
def _settings_warnings(facts: RunFacts):
    if facts.config_warnings:
        return found("settings_warnings", "certain", [f"settings.config_warnings: {clip(item, 160)}" for item in facts.config_warnings[:3]])


# ---- entries recognized by one error sentence ------------------------------------
# (issue, pattern): the program's own message names the problem exactly.
ERROR_SENTENCES = (
    ("media_decode_stall", r"音频解码长时间无响应"),
    ("studio_input_changed", r"识别启动后素材已改变|当前时间轴为空，无法识别字幕|时间轴音频准备失败|时间轴音频长度与剪辑快照不一致"),
    ("no_primary_model", r"当前没有可运行的主力转写模型|尚未选择主力转写模型"),
    ("model_dir_unavailable", r"已登记的模型目录不可用"),
    ("host_filter_empty", r"没有筛出可用的主播字幕|覆盖筛选未保留可靠对白"),
    ("grouping_refused", r"断句阶段结果未通过来源正文"),
    ("hard_split_dead_end", r"单条本地修复未覆盖完整原文"),
    ("ja_number_timing_old", r"本地修复的文字与时间单元不一致"),
    ("final_hard_limit", r"最终字幕超过硬性长度上限"),
    ("ai_model_retired", r"已不可用（服务商已下线）"),
    ("ai_cli_login", r"使用账号登陆传输"),
    ("term_search_polish_off", r"Text AI stage is disabled for this task"),
    ("old_batch_index_crash", r"invalid literal for int\(\) with base 10: '\d+(?:\.\d+)+'"),
    ("studio_result_mismatch", r"工程交付的任务 ID 与当前任务不一致|识别提交后工程已有人工修订|RecognitionResultMismatch"),
    ("skipped_existing", r"已存在字幕结果"),
)


def _sentence_check(issue_id: str, pattern: str):
    def run(facts: RunFacts):
        error = facts.error_matches(pattern)
        if error:
            return found(issue_id, "certain", [_error_line(error)])
    return run


for _issue, _pattern in ERROR_SENTENCES:
    check(_issue)(_sentence_check(_issue, _pattern))


@check("vad_lightweight_fallback")
def _vad_fallback(facts: RunFacts):
    rows = [row for row in facts.events_named("vad_backend_selected") if row.get("reason") == "main_runtime_missing"]
    stages = facts.stage_named("轻量静音与人声区间检测")
    if rows or stages:
        evidence = [_event_line(row, "backend", "reason") for row in rows[:1]]
        evidence += [f"stages[{row.get('label')}] = {row.get('status')}" for row in stages[:1]]
        return found("vad_lightweight_fallback", "certain", evidence)


@check("moss_long_audio")
def _moss_long_audio(facts: RunFacts):
    windows = facts.moss.get("windows") if isinstance(facts.moss.get("windows"), list) else []
    items = facts.review_categories.get("长音频分段识别", 0)
    if len(windows) > 1 or items:
        evidence = [f"moss_execution.windows = {len(windows)}"] if len(windows) > 1 else []
        if items:
            evidence.append(f"review_items: 长音频分段识别 × {items}")
        return found("moss_long_audio", "certain", evidence)


SPEAKER_CATEGORIES = ("说话人需要确认", "主播人数不足", "其他说话人未核对", "主要说话人候选需要确认", "临时说话人找回", "说话人重叠")


@check("speakers_need_review")
def _speakers(facts: RunFacts):
    counts = {category: facts.review_categories.get(category, 0) for category in SPEAKER_CATEGORIES}
    counts = {category: count for category, count in counts.items() if count}
    if counts:
        return found("speakers_need_review", "certain",
                     [f"review_items: {category} × {count}" for category, count in counts.items()])


@check("primary_incomplete")
def _primary_incomplete(facts: RunFacts):
    items = [row for row in facts.review_items if row.get("category") in {"主力转写提前结束", "主力转写不完整"}]
    # A transcript that stops where a range the cloud's content review stopped
    # begins is that gap (cloud_asr_gap_unfilled), not a cut-off (2026-10-24).
    gap = facts.last_event("cloud_asr_gap_fill")
    unfilled = [] if not gap or gap.get("filled") else gap.get("ranges") or []
    items = [row for row in items if row.get("category") != "主力转写提前结束" or not any(
        float(start) - 1.0 <= float(row.get("timestamp") or 0) <= float(end) for start, end in unfilled)]
    coverage = facts.events_named("moss_full_context_coverage")
    if items or coverage:
        evidence = [f"review_items: {row.get('category')} · {clip(row.get('detail'), 160)}" for row in items[:2]]
        evidence += [_event_line(row, "reason") for row in coverage[:1]]
        return found("primary_incomplete", "certain", evidence)


@check("incremental_fallback")
def _incremental(facts: RunFacts):
    row = facts.first_event("incremental_asr_fallback")
    if row:
        return found("incremental_fallback", "certain", [_event_line(row, "backend", "error")])
