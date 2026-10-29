"""Recognition progress presentation model (2026-10-08, visual refresh M12).

Pure helpers for the progress page. Every value comes from a real pipeline
event: finished steps, real batch counters inside the running step, real
token counts, the time of the last real output and text the models actually
returned. Nothing here estimates remaining time, and nothing declares a run
healthy or stuck.
"""
from __future__ import annotations

# Pipeline stage label -> (record name, action title). Unknown labels are
# shown verbatim; the console log always keeps the technical label.
STAGE_WORDING = {
    "统一 16k 音频采样时钟": ("准备音频", "正在准备音频"),
    "MOSS 全局说话人与粗时间转写": ("MOSS 识别文字与说话人", "MOSS 正在识别文字与说话人"),
    "FireRedVAD 人声安全检查": ("检测人声区间", "正在检测人声区间"),
    "轻量静音与人声区间检测": ("检测人声区间", "正在检测人声区间"),
    "FireRedASR2-AED 独立文字证据": ("FireRed 逐字识别与对时", "FireRed 正在逐字识别并对时"),
    "Qwen3 ForcedAligner 字词时间轴": ("对齐字词时间", "正在对齐字词时间"),
    "Whisper 多语种字幕时间轴": ("对齐字幕时间", "正在对齐字幕时间"),
    "Paraformer 中文字幕时间轴": ("对齐字幕时间", "正在对齐字幕时间"),
    "筛选 MOSS 主播并建立主稿": ("区分主播并整理主稿", "正在区分主播并整理主稿"),
    "建立统一主稿": ("整理主稿", "正在整理主稿"),
    "Qwen3-ASR VAD短块复核": ("Qwen 独立复核文字", "Qwen 正在独立复核文字"),
    "独立文字复核": ("独立复核文字", "正在独立复核文字"),
    "FireRedASR2-LLM 争议片段复核": ("复核有争议的片段", "正在复核有争议的片段"),
    "云端模型受限校对": ("AI 校对字幕", "AI 正在校对字幕"),
    "云端模型全文智能断句": ("AI 全文断句", "AI 正在全文断句"),
    "本地规则全文断句": ("按本地规则断句", "正在按本地规则断句"),
    "锁定最终字幕时间轴": ("锁定字幕时间轴", "正在锁定字幕时间轴"),
    "保存识别结果与工程": ("保存工程与报告", "正在保存工程与报告"),
    # cloud_gap_fill.STAGE_LABEL (2026-10-24)
    "本地补识别被拦下的片段": ("本地补识别被拦下的片段", "正在用本地模型补识别被拦下的片段"),
}

MOSS_ACTIONS = {
    "audio_preparation": "MOSS 正在准备音频",
    "model_loading": "MOSS 正在加载模型",
    "audio_encoding": "MOSS 正在读取音频",
    "generation": "MOSS 正在识别文本",
    "parsing": "MOSS 正在整理识别结果",
    "handoff": "MOSS 正在交出识别结果",
    "completed": "MOSS 识别已完成",
    "needs_review": "MOSS 识别完成，需要复核",
}

# One plain sentence under the action title (M14): what the step is doing.
STAGE_DESCRIPTIONS = {
    "准备音频": "统一采样率并缓存整段音频",
    "MOSS 识别文字与说话人": "整段识别文字并区分说话人",
    "检测人声区间": "找出有人说话的片段",
    "FireRed 逐字识别与对时": "逐字识别并给出每个字的时间",
    "对齐字词时间": "给字词对齐起止时间",
    "对齐字幕时间": "给字幕对齐起止时间",
    "区分主播并整理主稿": "按说话人筛选主播并整理主稿",
    "整理主稿": "合并各路识别结果，整理主稿",
    "Qwen 独立复核文字": "用独立模型再识别一遍，复核文字",
    "独立复核文字": "用独立模型复核文字",
    "复核有争议的片段": "复核两路识别不一致的片段",
    "AI 校对字幕": "按词库和上下文校对字幕文字",
    "AI 全文断句": "按语义把全文切成字幕句",
    "按本地规则断句": "按停顿与标点把全文切成字幕句",
    "锁定字幕时间轴": "对齐每条字幕的起止时间",
    "保存工程与报告": "写入工程文件与任务报告",
    "本地补识别被拦下的片段": "在线识别服务的内容审查拦下的片段，改用本机模型识别",
}

MOSS_DESCRIPTIONS = {
    "audio_preparation": "正在准备整段音频",
    "model_loading": "正在把模型载入显存",
    "audio_encoding": "正在读取整段音频特征",
    "generation": "正在进行整段音频识别",
    "parsing": "正在把识别结果整理成句子与说话人",
    "handoff": "正在交出识别结果",
    "completed": "整段识别已完成",
    "needs_review": "整段识别已完成，部分结果需要复核",
}

# Preview row states -> (tag, tone).
PREVIEW_TAGS = {
    "provisional": ("尚未校对", "muted"),
    "polished": ("已校对", "info"),
    "polished_changed": ("已校对 · 有修改", "info"),
    "polish_fallback": ("保留原文", "warning"),
    "grouped": ("已断句", "info"),
    "final": ("已保存", "success"),
}

# Async cloud recognition (2026-10-15): the task state each poll returned,
# in words. Upload percentages come from the bytes actually sent.
CLOUD_JOB_STATES = {
    "connecting": "正在连接",
    "uploading": "正在上传音频",
    "request": "识别第 {index} / {total} 段",
    "cached": "复用第 {index} / {total} 段",
    "cached_result": "复用已有结果",
    "PENDING": "排队中",
    # MOSI already has as many requests as it takes at once (HTTP 429); asked again shortly.
    "waiting_for_slot": "排队中",
    "RUNNING": "云端识别中",
    "PROCESSING": "云端识别中",
    "SUCCEEDED": "正在取回结果",
    "SUCCESS": "正在取回结果",
    "completed": "已完成 {done} / {total} 段",
    "retry_incomplete_upload": "重新上传",
    "explicit_restart_uncertain": "按确认重新提交",
    "explicit_restart_terminal": "按确认重新提交",
    "local_cancel_remote_continues": "已停止等待，云端可能仍在运行",
    "local_cancel_remote_unconfirmed": "已停止等待，云端未确认取消",
    "remote_cancel_confirmed": "云端任务已取消",
}


def cloud_job_phase(payload):
    """(source text, arguments) for an async cloud job's latest state, or None.

    Short on purpose: the value sits in the narrow facts column.
    """
    payload = payload or {}
    source = CLOUD_JOB_STATES.get(str(payload.get("state") or ""))
    if source is None:
        return None
    done, total = int(payload.get("completed_batches") or 0), int(payload.get("total_batches") or 0)
    return source, dict(index=done + 1, done=done, total=max(total, 1))


# States in which the provider has the task and the window only waits.
CLOUD_WAIT_STATES = {"PENDING", "RUNNING", "PROCESSING"}


def cloud_wait_limit(audio_seconds) -> float:
    """Seconds after which a provider wait counts as unusually long.

    Measured MOSS Pro tasks: 16-24 minutes of audio finished 1.5-2.5 minutes
    after submission; a user's 40-minute segment still waited after 24 minutes
    and then failed (2026-10-23). 10 minutes, or 30% of the request's audio
    when that is longer, leaves several times the usual margin.
    """
    audio = float(audio_seconds) if isinstance(audio_seconds, (int, float)) and not isinstance(audio_seconds, bool) else 0.0
    return max(600.0, 0.3 * max(0.0, audio))


def cloud_wait(payload, since_event=0.0):
    """(seconds waited, overdue) while the provider has a request, or None.

    The worker reports the wait from the original submission (a resumed task
    keeps counting); ``since_event`` adds the time since that report.
    """
    payload = payload or {}
    waited = payload.get("remote_waited_seconds")
    if str(payload.get("state") or "") not in CLOUD_WAIT_STATES or isinstance(waited, bool) \
            or not isinstance(waited, (int, float)):
        return None
    waited = max(0.0, float(waited)) + max(0.0, float(since_event or 0.0))
    return waited, waited >= cloud_wait_limit(payload.get("request_audio_seconds"))


def upload_progress(payload):
    """(source text, arguments) for the bytes an upload has sent, or None."""
    payload = payload or {}
    sent, size = int(payload.get("uploaded_bytes") or 0), int(payload.get("upload_bytes_total") or 0)
    if payload.get("state") != "uploading" or size <= 0:
        return None
    return "{sent} / {size} MB", dict(sent=f"{min(sent, size) / 1048576:.1f}", size=f"{size / 1048576:.1f}")


def cloud_batch_list(indexes, limit=4) -> str:
    """'19, 20, 21' for the batches being processed; '19, 20, 21, 22 …' beyond ``limit``."""
    ordered = sorted(int(index) for index in indexes)
    text = ", ".join(str(index) for index in ordered[:limit])
    return text + (" …" if len(ordered) > limit else "")


# Online recognition labels carry the service ("在线 ASR API 主力转写（MOSS Pro 云端 ·
# model）"). Verbatim, the title wrapped over eight lines and the "上一步" fact
# squeezed it to one character per line (2026-10-15): short words instead, and
# the service goes on the line under the title.
CLOUD_ASR_WORDING = {
    "在线 ASR API 主力转写": ("在线识别文字", "在线服务正在识别文字"),
    "在线 ASR API 文字复核": ("在线复核文字", "在线服务正在复核文字"),
}


def _cloud_asr_stage(text):
    for prefix, wording in CLOUD_ASR_WORDING.items():
        if text.startswith(prefix):
            return wording, text[len(prefix):].strip().strip("（）()").strip()
    return None


def stage_record_name(label) -> str:
    text = str(label or "").strip()
    cloud = _cloud_asr_stage(text)
    if cloud:
        return cloud[0][0]
    return STAGE_WORDING.get(text, (text, ""))[0]


def stage_action(label) -> str:
    text = str(label or "").strip()
    cloud = _cloud_asr_stage(text)
    if cloud:
        return cloud[0][1]
    wording = STAGE_WORDING.get(text)
    return wording[1] if wording else text


def moss_action(phase) -> str:
    return MOSS_ACTIONS.get(str(phase or ""), "MOSS 正在准备")


def stage_description(label) -> str:
    cloud = _cloud_asr_stage(str(label or "").strip())
    if cloud and cloud[1]:
        return cloud[1]  # the service and model, e.g. "MOSS Pro 云端 · moss-transcribe-diarize-pro"
    return STAGE_DESCRIPTIONS.get(stage_record_name(label), "")


# A long task split into windows (2026-10-13): "whole audio" would be wrong.
MOSS_WINDOW_DESCRIPTIONS = {
    "audio_encoding": "正在读取本段音频特征",
    "generation": "正在分段识别长音频",
    "completed": "分段识别已完成",
    "needs_review": "分段识别已完成，部分结果需要复核",
}


def moss_description(phase, windowed=False) -> str:
    phase = str(phase or "")
    if windowed and phase in MOSS_WINDOW_DESCRIPTIONS:
        return MOSS_WINDOW_DESCRIPTIONS[phase]
    return MOSS_DESCRIPTIONS.get(phase, "")


def phase_ranges(total) -> tuple[set, set, set, set]:
    """The four display phases over the pipeline's real step numbering.

    The last step saves; the two before it segment and lock timing; step 8
    is AI proofreading only when the run has 11 steps (it is absent, not
    renumbered away, when proofreading is off). Everything else is local
    recognition. Holds for 11-, 10- and 8-step runs alike.
    """
    total = max(1, int(total or 1))
    steps = set(range(1, total + 1))
    save = {total}
    grouping = {step for step in (total - 2, total - 1) if step >= 1} - save
    polish = {8} if total == 11 else set()
    local = steps - save - grouping - polish
    return local, polish, grouping, save


def ended_steps(completed, skipped, failed, total) -> set:
    """Steps that are over. A failed step the run continued past counts as
    over; the save step only counts when it completed."""
    total = max(1, int(total or 1))
    return (set(completed) | set(skipped) | (set(failed) - {total})) & set(range(1, total + 1))


def overall_fraction(total, ended, partial, media_index=1, media_total=1) -> float:
    """Finished steps plus real in-step counters, across the media queue.

    Reaches 1.0 only when the last media's save step completed; anything
    short of that is capped below 1.0 so 100% always means saved.
    """
    total = max(1, int(total or 1))
    media_total = max(1, int(media_total or 1))
    media_index = min(media_total, max(1, int(media_index or 1)))
    inside = sum(min(0.99, max(0.0, float(value))) for value in (partial or {}).values())
    per_media = min(1.0, (len(ended) + inside) / total)
    if total not in ended:
        per_media = min(per_media, 0.999)
    fraction = ((media_index - 1) + per_media) / media_total
    if media_index < media_total or total not in ended:
        fraction = min(fraction, 0.999)
    return max(0.0, min(1.0, fraction))


def percent_text(fraction) -> str:
    """Floor, so 99.6% reads 99% and only a saved run reads 100%."""
    return f"{int(max(0.0, min(1.0, float(fraction))) * 100)}%"


def active_spans(total, active, media_index=1, media_total=1, ended=()) -> tuple:
    """Where the running steps sit on the bar: right after the finished
    ones (the fill counts steps, so parallel steps never hide under it)."""
    total = max(1, int(total or 1))
    media_total = max(1, int(media_total or 1))
    running = len([step for step in active if 1 <= step <= total and step not in set(ended)])
    if not running:
        return ()
    base = (max(1, int(media_index or 1)) - 1) / media_total
    start = min(total, len(set(ended))) / total
    end = min(total, len(set(ended)) + running) / total
    return ((base + start / media_total, base + end / media_total),)


def resource_mode(resource):
    """(key, value) for how a step runs, or None. Display only."""
    text = str(resource or "").strip()
    if not text:
        return None
    first = text.replace("·", " · ").split(" · ")[0].strip()
    if "/" in first and " " not in first and not first.startswith(("http", "C:", "D:")):
        provider, _, model = first.partition("/")
        return ("服务", f"{provider} · {model}")
    upper = text.upper()
    if "GPU" in upper:
        return ("运行方式", "GPU 加速")
    if "CPU" in upper:
        return ("运行方式", "CPU")
    if "磁盘" in text:
        return ("运行方式", "本机磁盘")
    return ("运行方式", text)


def clock(seconds) -> str:
    seconds = max(0, int(seconds or 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def time_label(seconds) -> str:
    seconds = max(0, int(seconds or 0))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


# ----------------------------------------------------------------- preview

def _joined(chars) -> str:
    out = ""
    for char in chars:
        if out and out[-1].isascii() and out[-1].isalnum() and char[:1].isascii() and char[:1].isalnum():
            out += " "
        out += char
    return out


def evidence_phrases(row, base: float, *, pause=0.4, limit=22):
    """Split one FireRed evidence row into short phrases.

    FireRed's character stamps are contiguous; a pause is absorbed into the
    next character's duration, so a long character starts a new phrase.
    Phrases are display-only and never feed back into recognition.
    """
    stamps = [stamp for stamp in (row.get("timestamp") or []) if str(stamp.get("text") or "").strip()]
    if not stamps:
        text = str(row.get("text") or "").strip()
        return [(base, base + float(row.get("duration") or 0), text)] if text else []
    phrases, current, start, end = [], [], 0.0, 0.0
    for stamp in stamps:
        s, e = float(stamp.get("start") or 0), float(stamp.get("end") or 0)
        if current and (e - s >= pause or len(current) >= limit):
            phrases.append([base + start, base + end, current])
            current = []
        if not current:
            start = s
        current.append(str(stamp["text"]).strip())
        end = e
    if current:
        phrases.append([base + start, base + end, current])
    merged = []
    for phrase in phrases:
        if merged and len(phrase[2]) < 3 and len(merged[-1][2]) + len(phrase[2]) <= limit + 4:
            merged[-1][1] = phrase[1]
            merged[-1][2] = merged[-1][2] + phrase[2]
        else:
            merged.append(phrase)
    return [(start, end, _joined(chars)) for start, end, chars in merged]


def preview_rows(kind, payload):
    """(family, rows) from an event carrying real text, else (None, [])."""
    payload = payload or {}
    if kind == "asr_evidence_delta":
        rows = []
        for row in payload.get("rows") or []:
            base = float(row.get("offset", payload.get("processed_start", 0)) or 0)
            rows.extend(dict(start=start, end=end, text=text, state="provisional")
                        for start, end, text in evidence_phrases(row, base))
        return "evidence", rows
    if kind == "cue_delta":
        state = "final" if payload.get("state") == "final" else "provisional"
        rows = [dict(start=float(cue.get("start_ms") or 0) / 1000, end=float(cue.get("end_ms") or 0) / 1000,
                     text=str(cue.get("text") or "").strip(), state=state)
                for cue in payload.get("cues") or () if str(cue.get("text") or "").strip()]
        return ("final" if state == "final" else "draft"), rows
    if kind == "terminology_polish_final":
        details = payload.get("details") or {}
        text = str(details.get("final_text") or details.get("original_text") or "").strip()
        if not text:
            return None, []
        state = ("polish_fallback" if details.get("response_state") == "fallback"
                 else "polished_changed" if payload.get("changed") else "polished")
        return "polish", [dict(start=None, cue=payload.get("cue_id"), text=text, state=state)]
    if kind == "cloud_batch_preview":
        # One returned AI batch, shown before the step ends (2026-10-15).
        family = "polish" if payload.get("stage") == "polished" else "grouped"
        rows = [dict(start=row.get("start"), end=row.get("end"), cue=row.get("cue_id"),
                     text=str(row.get("text") or "").strip(), state=str(row.get("state") or "polished"))
                for row in payload.get("rows") or () if str(row.get("text") or "").strip()]
        return family, rows
    return None, []


def merge_preview(buffer, family, previous_family, rows, keep=40):
    """Newer families replace older ones; evidence overlap is de-duplicated."""
    if family != previous_family:
        buffer = []
    buffer = list(buffer)
    if family == "evidence" and buffer:
        last_end = max(float(row.get("end") or 0) for row in buffer)
        rows = [row for row in rows if float(row.get("start") or 0) >= last_end - 0.05]
    buffer.extend(rows)
    return buffer[-keep:]
