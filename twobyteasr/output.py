"""output stage implementation extracted from subtitle_core."""

import json
import os
import re
import shutil
import uuid
from difflib import SequenceMatcher
from statistics import median

# The core owns runtime configuration; these imports preserve the existing public contract.
from subtitle_core import *  # noqa: F401,F403
from twobyteasr import reporting as task_reporting
from twobyteasr.runtime import get_runtime_context

__all__ = [
    'format_review_time',
    'print_review_summary',
    'add_safe_punctuation',
    'final_text_conservation_differences',
    'validate_final_cues',
    'format_srt_time',
    'render_txt',
    'render_srt',
    'build_single_lane_cues',
    'build_review_track_cues',
    '_safe_existing_track_paths',
    'write_all_outputs_transactional',
]

def format_review_time(seconds):
    total_seconds = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def print_review_summary():
    all_items = []
    for source in get_runtime_context().review_items:
        item = dict(source)
        item["severity"] = review_item_severity(item)
        all_items.append(item)
    deduplicated = {}
    for item in all_items:
        key = (
            item.get("category", ""),
            round(float(item.get("timestamp", 0.0)) * 2),
            content_only(item.get("text", "")),
        )
        previous = deduplicated.get(key)
        if previous is None or int(item.get("priority", 0)) > int(
            previous.get("priority", 0)
        ):
            deduplicated[key] = item
    display_items = sorted(
        deduplicated.values(),
        key=lambda item: (-int(item.get("priority", 0)), float(item["timestamp"])),
    )
    warnings = [
        item for item in display_items
        if item.get("severity") in {"error", "warning"}
    ]
    reviews = [item for item in display_items if item.get("severity") == "review"]
    diagnostics = len(all_items) - len(warnings) - len(reviews)
    print("\n[结果提示]")
    if not warnings and not reviews:
        print("   未发现明显异常，可直接导入剪映抽查。")
        if diagnostics:
            print(f"   {diagnostics} 条内部诊断已写入 JSON 报告。")
        return all_items

    aggregated_categories = {
        "校对回退": ("AI 校对部分降级", "个批次使用本地结果"),
        "断句回退": ("AI 智能断句降级", "个批次使用本地断句"),
    }
    aggregated = set()
    for category, (title, suffix) in aggregated_categories.items():
        matching = [item for item in warnings if item.get("category") == category]
        if not matching:
            continue
        total = max(
            (int(item.get("batch_total") or 0) for item in matching),
            default=0,
        )
        count = len({
            int(item.get("batch_index") or index + 1)
            for index, item in enumerate(matching)
        })
        denominator = total or count
        print(f"   [警告] {title}：{count} / {denominator} {suffix}。")
        aggregated.add(category)

    remaining_warnings = [
        item for item in warnings if item.get("category") not in aggregated
    ]
    shown = (remaining_warnings + reviews)[:REVIEW_MAX_ITEMS]
    for item in shown:
        text = item.get("text", "")
        suffix = f"｜{text}" if text else ""
        label = "警告" if item.get("severity") in {"error", "warning"} else "复核"
        print(
            f"   {format_review_time(item['timestamp'])} "
            f"[{label} · {item['category']}] {item['detail']}{suffix}"
        )
    visible_count = len(remaining_warnings) + len(reviews)
    if visible_count > len(shown):
        print(f"   ……另有 {visible_count - len(shown)} 条低优先级提示未展开。")
    if diagnostics:
        print(f"   {diagnostics} 条 info/debug 诊断仅保留在 JSON 报告。")
    return all_items


def add_safe_punctuation(cues):
    """最终稿不再猜测问句；移除 ASR/Qwen 自动推断的问号。"""
    for cue in cues:
        text = clean_subtitle_text(cue.text)
        cue.text = text.replace("?", "").replace("？", "")
    return cues


def final_text_conservation_differences(cues, segments):
    """Return precise per-speaker text differences without weakening validation."""
    source_by_speaker = {}
    output_by_speaker = {}
    for segment in segments:
        source_by_speaker.setdefault(segment.speaker or "S00", []).append(segment.text)
    for cue in cues:
        output_by_speaker.setdefault(cue.speaker or "S00", []).append(cue.text)
    source_by_speaker = {
        speaker: content_only("".join(texts))
        for speaker, texts in source_by_speaker.items()
    }
    output_by_speaker = {
        speaker: content_only("".join(texts))
        for speaker, texts in output_by_speaker.items()
    }
    differences = []
    for speaker in sorted(set(source_by_speaker) | set(output_by_speaker)):
        expected = source_by_speaker.get(speaker, "")
        actual = output_by_speaker.get(speaker, "")
        if expected == actual:
            continue
        matcher = SequenceMatcher(None, expected, actual, autojunk=False)
        first = next(
            (
                (tag, left_start, left_end, right_start, right_end)
                for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes()
                if tag != "equal"
            ),
            ("unknown", 0, min(12, len(expected)), 0, min(12, len(actual))),
        )
        tag, left_start, left_end, right_start, right_end = first
        differences.append(
            {
                "speaker": speaker,
                "expected_length": len(expected),
                "actual_length": len(actual),
                "operation": tag,
                "expected_excerpt": expected[max(0, left_start - 8) : left_end + 8],
                "actual_excerpt": actual[max(0, right_start - 8) : right_end + 8],
            }
        )
    return differences


def validate_final_cues(cues, segments, audio_seconds, validate_text=True):
    if not cues:
        raise RuntimeError("断句后没有可用字幕。")
    source_content = content_only("".join(segment.text for segment in segments))
    output_content = content_only("".join(cue.text for cue in cues))
    if validate_text:
        # Always verify each track. A speaker swap can leave the global joined
        # text unchanged while silently putting words on the wrong output track.
        differences = final_text_conservation_differences(cues, segments)
        if differences:
            sample = differences[0]
            raise RuntimeError(
                "最终字幕出现漏字、重复或调序，已停止写入："
                f"{sample['speaker']} 源文 {sample['expected_length']} 字/"
                f"输出 {sample['actual_length']} 字，首处差异 "
                f"{sample['expected_excerpt']!r} -> {sample['actual_excerpt']!r}。"
            )
        if source_content != output_content:
            # 不同说话人真实重叠时，按时间排序会把 A 的后半句放到 B 的接话之后；
            # 全局字符串顺序因此变化，但每位说话人的文字仍应逐字完整且有序。
            print("   [重叠保护] 全局时间顺序发生说话人交错，但各说话人文字逐字完整。")

    lengths = [display_length(cue.text) for cue in cues]
    durations = [cue.end - cue.start for cue in cues]
    # 三十四轮：短字幕继承长段时间（API/断句产物 2-7 字挂 5.05s）曾把整轮
    # 识别打成"硬性时长上限"失败。时长超限改为截断修复并告警；字数超限与
    # 空段仍是断句真坏了，保持硬失败。
    clamped = []
    for cue in cues:
        if (
            cue.end > cue.start
            and display_length(cue.text) <= COMPLETE_PHRASE_SOFT_MAX_CHARS
            and cue.end - cue.start > MAX_SUBTITLE_SECONDS
        ):
            # 修复性截断用不带容差的阈值（比失败判定更宽松），避免 5.0501s
            # 这类边界值漏网。
            cue.end = cue.start + MAX_SUBTITLE_SECONDS
            clamped.append(cue)
    if clamped:
        sample = "、".join(
            f"{cue.text}({display_length(cue.text)}字)"
            for cue in clamped[:6]
        )
        print(
            f"   [护栏] {len(clamped)} 条短字幕时长超过 {MAX_SUBTITLE_SECONDS:.0f}s "
            f"已截断到上限（不影响文字内容）：{sample}"
        )
        durations = [cue.end - cue.start for cue in cues]
    invalid = [
        cue
        for cue in cues
        if display_length(cue.text) > COMPLETE_PHRASE_SOFT_MAX_CHARS
        or cue.end <= cue.start
    ]
    if invalid:
        sample = "、".join(
            f"{cue.text}({display_length(cue.text)}字/{cue.end - cue.start:.2f}s)"
            for cue in invalid[:6]
        )
        raise RuntimeError(f"最终字幕超过硬性长度上限：{sample}")
    within_preferred = (
        sum(length <= PREFERRED_MAX_SUBTITLE_CHARS for length in lengths) / len(lengths)
    )
    within_limit = sum(length <= MAX_SUBTITLE_CHARS for length in lengths) / len(lengths)
    print(
        f"[完成] 断句：{len(cues)} 条，中位 {median(lengths):.0f} 字/"
        f"{median(durations):.2f} 秒，{within_preferred:.0%} 不超过 "
        f"{PREFERRED_MAX_SUBTITLE_CHARS} 字，{within_limit:.0%} 不超过硬上限 "
        f"{MAX_SUBTITLE_CHARS} 字。"
    )
    if within_preferred < 0.8:
        print("   [警告] 本次长字幕比例偏高，建议抽查现场噪声较重的区段。")
    last_end = max(cue.end for cue in cues)
    if audio_seconds - last_end > 8.0:
        print("   [警告] 最后一条字幕距离音频结尾超过 8 秒，请抽查尾部。")
    return cues


def format_srt_time(seconds):
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def render_txt(cues):
    return "\n".join(format_subtitle_display_text(cue.text) for cue in cues) + "\n"


def render_srt(cues):
    blocks = []
    for index, cue in enumerate(cues, 1):
        text = format_subtitle_display_text(cue.text)
        if SHOW_SPEAKER_LABELS_IN_SRT and cue.speaker:
            text = f"[{cue.speaker}] {text}"
        blocks.append(
            f"{index}\n"
            f"{format_srt_time(cue.start)} --> {format_srt_time(cue.end)}\n"
            f"{text}"
        )
    return "\n\n".join(blocks) + "\n"


def build_single_lane_cues(cues):
    """Return a non-overlapping copy for the combined SRT only.

    Speaker tracks retain real simultaneous speech.  The combined SRT is one
    editorial lane, so a 200 ms display tail from one speaker must not overlap
    the next speaker and make NLE import look like a shifted timeline.
    """
    rows = [
        SubtitleCue(
            cue_id=cue.cue_id,
            start=float(cue.start),
            end=float(cue.end),
            text=cue.text,
            timing_locked=bool(cue.timing_locked),
            speaker=cue.speaker,
        )
        for cue in cues
    ]
    rows.sort(key=lambda cue: (cue.start, cue.end, cue.speaker or "", cue.cue_id))
    adjusted = 0
    for previous, current in zip(rows, rows[1:]):
        if previous.end <= current.start or previous.speaker == current.speaker:
            continue
        lower = previous.start + MIN_SUBTITLE_SECONDS
        upper = current.end - MIN_SUBTITLE_SECONDS
        if lower > upper:
            continue
        boundary = min(max(current.start, lower), upper)
        if boundary < previous.end or boundary > current.start:
            previous.end = boundary
            current.start = boundary
            adjusted += 1
    for cue_id, cue in enumerate(rows, 1):
        cue.cue_id = cue_id
    if adjusted:
        print(
            f"   [总轨时间轴] 修正 {adjusted} 处跨主播显示重叠；"
            "主播分轨仍保留真实抢话。"
        )
        record_run_event("single_lane_overlap_repair", adjusted=adjusted)
    return rows


def build_review_track_cues(review_items=None):
    """把高风险时间点做成独立审核轨；它从不回写主字幕。"""
    review_items = (
        review_items
        if review_items is not None
        else get_runtime_context().review_items
    )
    categories = {
        "MOSS提前结束",
        "MOSS漏段",
        "FireRed漏段",
        "低置信度",
        "ASR分歧",
        "多模型争议",
        "Qwen骨架缺口",
        "孤立实义单字",
        "边界待看",
    }
    deduplicated = {}
    for item in review_items:
        if item.get("category") not in categories:
            continue
        timestamp = max(0.0, float(item.get("timestamp", 0.0)))
        text = clean_subtitle_text(item.get("text", ""))
        if not text:
            text = "请听原音复核"
        label = f"【{item.get('category')}】{text}"
        key = (round(timestamp * 2), label)
        deduplicated[key] = SubtitleCue(
            cue_id=0,
            start=max(0.0, timestamp - 0.30),
            end=timestamp + 3.00,
            text=label,
            speaker="REVIEW",
        )
    rows = sorted(deduplicated.values(), key=lambda cue: (cue.start, cue.end))
    for cue_id, cue in enumerate(rows, 1):
        cue.cue_id = cue_id
    return rows[:REVIEW_MAX_ITEMS]


def _safe_existing_track_paths(srt_path):
    """只枚举严格符合本程序分轨命名格式的文件（不涉及删除决定）。

    命名格式：``{base}_主播{index}_{speaker}{ext}``——index 必须为数字，
    speaker 为 ``_safe_filename_part`` 输出的 1-48 个合法 Windows 文件
    名字符（含中文/空格/Unicode）。旧版本命名不含 sanitize，但含非法
    字符的旧文件在 Windows 上无法创建，因此实际存在的程序旧产物均
    满足该格式；不符合格式的文件一律视为用户文件。
    """
    directory = os.path.dirname(os.path.abspath(srt_path))
    base, extension = os.path.splitext(os.path.basename(srt_path))
    pattern = re.compile(
        r"^" + re.escape(base) + r"_主播\d+_[^\\/:*?\"<>|\x00-\x1f]{1,48}"
        + re.escape(extension) + r"$"
    )
    result = []
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    for name in names:
        if pattern.match(name):
            path = os.path.abspath(os.path.join(directory, name))
            if os.path.dirname(path) == directory:
                result.append(path)
    return result


def _previously_generated_track_paths(srt_path):
    """返回最近一次成功任务报告记录的分轨路径（ownership 证明）。

    文件名只能证明"像程序产物"，不能证明"是程序产物"。自动清理只允许
    删除最近一次成功任务报告明确记录为本程序生成的文件；报告缺失、
    损坏或状态不是 success 时返回空集——宁可留下程序旧分轨，不可误删
    用户文件。
    """
    base = os.path.splitext(os.path.basename(srt_path))[0]
    media_stem = base[: -len("_剪映文稿")] if base.endswith("_剪映文稿") else base
    report_path = os.path.join(
        str(task_reporting.REPORT_ROOT), f"{media_stem}_字幕任务报告.json"
    )
    try:
        with open(report_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, ValueError, TypeError):
        return set()
    if payload.get("status") != "success":
        return set()
    outputs = payload.get("result", {}).get("outputs", {})
    if not isinstance(outputs, dict):
        return set()
    proven = set()
    for item in outputs.get("speaker_outputs", []) or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], str):
            path = item[1].strip()
            if path:
                proven.add(os.path.normcase(os.path.abspath(path)))
    return proven


def _safe_filename_part(value):
    """Return a Windows-safe, non-traversing speaker label for output files."""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or ""))
    value = re.sub(r"\.{2,}", "_", value)
    value = value.strip(" .")[:48]
    return value or "S00"


def write_all_outputs_transactional(
    cues,
    txt_path,
    srt_path,
    include_review_track=False,
    include_srt=True,
    include_txt=True,
    include_speaker_tracks=True,
):
    """先完整生成所有文件，再统一替换；失败时恢复本批写入前版本。

    include_txt / include_speaker_tracks 控制素材同目录的额外产物
    （剪映文稿 txt、分主播 SRT）；默认仅直接调用方保持旧行为，识别管线
    依据设置传入（用户默认：只写合并 SRT，同目录不再堆额外文件）。
    """
    speaker_order = []
    for cue in cues:
        speaker = cue.speaker or "S00"
        if speaker not in speaker_order:
            speaker_order.append(speaker)
    base, extension = os.path.splitext(srt_path)
    from .speaker_names import default_names
    display_names = default_names(speaker_order, preserve_canonical=False)
    speaker_outputs = []
    single_lane_cues = build_single_lane_cues(cues)
    payloads = {}
    if include_txt:
        payloads[os.path.abspath(txt_path)] = (render_txt(cues), "utf-8")
    if include_srt:
        payloads[os.path.abspath(srt_path)] = (render_srt(single_lane_cues), "utf-8-sig")
    for index, speaker in enumerate(speaker_order, 1) if include_srt and include_speaker_tracks else ():
        speaker_cues = [cue for cue in cues if (cue.speaker or "S00") == speaker]
        if not speaker_cues:
            continue
        safe_speaker = _safe_filename_part(display_names[speaker])
        path = os.path.abspath(f"{base}_主播{index}_{safe_speaker}{extension}")
        payloads[path] = (render_srt(speaker_cues), "utf-8-sig")
        speaker_outputs.append((speaker, path, len(speaker_cues)))

    legacy_review_path = os.path.abspath(f"{base}_疑似吞字幕复核{extension}")
    review_root = os.path.join(SCRIPT_DIR, "review_tracks")
    review_name = os.path.basename(base) + "_疑似吞字幕复核" + extension
    review_path = os.path.abspath(os.path.join(review_root, review_name))
    review_cues = build_review_track_cues() if include_srt and include_review_track else []
    if review_cues:
        payloads[review_path] = (render_srt(review_cues), "utf-8-sig")

    transaction_id = uuid.uuid4().hex
    temporary_paths = {}
    backup_paths = {}
    replaced = []
    try:
        for path, (content, encoding) in payloads.items():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temporary = f"{path}.{transaction_id}.tmp"
            with open(temporary, "w", encoding=encoding) as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            temporary_paths[path] = temporary
            if os.path.isfile(path):
                backup = f"{path}.{transaction_id}.bak"
                shutil.copy2(path, backup)
                backup_paths[path] = backup

        for path, temporary in temporary_paths.items():
            os.replace(temporary, path)
            replaced.append(path)

        expected_tracks = {
            path for _, path, _ in speaker_outputs
        }
        # 只清理"最近一次成功报告证明为本程序生成"的旧分轨；
        # 无法证明 ownership 的匹配文件（含用户文件）一律保留。
        proven_old_tracks = (
            _previously_generated_track_paths(srt_path)
            if include_srt and all(display_names[s] == s for s in speaker_order) else set()
        )
        # A display-name migration authorizes new names, not deleting the
        # existing exports bearing old backend labels.
        for stale in _safe_existing_track_paths(srt_path) if include_srt else ():
            if (
                stale not in expected_tracks
                and os.path.normcase(os.path.abspath(stale)) in proven_old_tracks
            ):
                try:
                    os.remove(stale)
                    print(f"   [清理旧分轨] {stale}")
                except OSError as exc:
                    print(f"   [警告] 旧分轨暂时无法清理：{stale}（{exc}）")
        stale_review_paths = [legacy_review_path]
        if not review_cues:
            stale_review_paths.append(review_path)
        for stale_review_path in dict.fromkeys(stale_review_paths):
            if stale_review_path == review_path and review_cues:
                continue
            if os.path.isfile(stale_review_path):
                try:
                    os.remove(stale_review_path)
                    print(f"   [清理旧复核轨] {stale_review_path}")
                except OSError as exc:
                    print(f"   [警告] 旧复核轨暂时无法清理：{stale_review_path}（{exc}）")
    except Exception:
        for path in reversed(replaced):
            backup = backup_paths.get(path)
            if backup and os.path.isfile(backup):
                os.replace(backup, path)
            elif os.path.isfile(path):
                os.remove(path)
        raise
    finally:
        for path in list(temporary_paths.values()) + list(backup_paths.values()):
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    if include_srt:
        print("   [说话人分轨SRT]")
        for speaker, path, count in speaker_outputs:
            print(f"      {speaker}：{count} 条 -> {path}")
    else:
        print("   [仅 TXT] 未选择字幕时间轴，不生成 SRT 或说话人分轨。")
    if review_cues:
        print(f"   [疑似吞字幕复核轨] {len(review_cues)} 条 -> {review_path}")
    return {
        "speaker_outputs": speaker_outputs,
        "review_path": review_path if review_cues else "",
    }


import subtitle_core as _core
for _name in __all__:
    setattr(_core, _name, globals()[_name])
del _core, _name
