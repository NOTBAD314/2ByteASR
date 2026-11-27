"""自动剪口播气口（四十四轮）：能量 VAD 检出长静音 → 时间轴波纹删除。

检测 deliberately 免模型免 torch（Studio GUI/frozen 进程可用）：帧 RMS +
自适应阈值得到语音掩码，互补区间里 ≥ 阈值的静音段（两侧各留缓冲）即气口。
静音区间在**源时间域**计算，经 EditSequence 映射到当前时间轴后再删——
已经剪掉的区域不会被重复处理。应用走 EditSequenceCommand（可撤销，
字幕通过现有投影同步，原始字幕不变）。
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np


def compute_silence_ranges_ms(
    audio: np.ndarray,
    sample_rate: int,
    *,
    min_silence_s: float = 5.0,
    padding_s: float = 0.35,
) -> list[tuple[int, int]]:
    """从 16k 单声道 float32 PCM 检出静音气口（源时间域毫秒）。

    与管线的轻量 VAD 同思路但方向相反：这里要的是"足够长的安静区间"。
    padding_s 是每个气口两侧保留的呼吸余量（避免切到换气尾音）。
    """
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size < max(1, sample_rate):
        return []
    frame = max(1, int(round(sample_rate * 0.030)))
    hop = max(1, int(round(sample_rate * 0.010)))
    from ..recognition.vad import bounded_rms
    rms = bounded_rms(samples, frame, hop)
    return _silence_ranges(rms, len(samples), sample_rate, min_silence_s, padding_s)


def compute_silence_ranges_wav(path, *, min_silence_s=5.0, padding_s=.35, check=lambda: None):
    from ..recognition.vad import wav_rms
    rms, samples = wav_rms(path, check=check)
    if samples < 16000:
        return []
    return _silence_ranges(rms, samples, 16000, min_silence_s, padding_s)


def _silence_ranges(rms, sample_count, sample_rate, min_silence_s, padding_s):
    duration_s = sample_count/float(sample_rate)
    frame = max(1, int(round(sample_rate*.030)))
    hop = max(1, int(round(sample_rate*.010)))
    peak = float(np.max(rms))
    floor = float(np.percentile(rms, 30))
    threshold = max(1e-4, floor * 2.2, peak * 0.025)
    active = rms >= threshold
    if not np.any(active):
        # Constant game ambience/music is not silence just because an
        # adaptive threshold sits above every frame. Honor the same guards.
        if peak > .003 or duration_s < max(.5,float(min_silence_s)):
            return []
        lo,hi=round(padding_s*1000),round((duration_s-padding_s)*1000)
        return [(lo,hi)] if hi-lo >= 250 else []

    # 语音掩码两侧各补 ~0.18s，避免把词间短停顿当成气口起点。
    pad_frames = max(1, int(round(0.18 / (hop / sample_rate))))
    active_indices = np.flatnonzero(active)
    padded = np.zeros_like(active, dtype=bool)
    for index in active_indices:
        padded[max(0, index - pad_frames): min(len(padded), index + pad_frames + 1)] = True

    # 互补静音段（帧边界换算回秒，最后一帧到结尾也算）。
    silences: list[tuple[float, float]] = []
    start = None
    for index, is_active in enumerate(np.append(padded, True)):
        if not is_active and start is None:
            start = index
        elif is_active and start is not None:
            begin = start * hop / sample_rate
            end = min(duration_s, (index * hop + frame) / sample_rate)
            if end - begin > 0:
                silences.append((begin, end))
            start = None
    ranges: list[tuple[int, int]] = []
    for begin, end in silences:
        if end - begin < max(0.5, float(min_silence_s)):
            continue
        lo = max(0.0, begin + padding_s)
        hi = min(duration_s, end - padding_s)
        if hi - lo >= 0.25:
            ranges.append((int(round(lo * 1000)), int(round(hi * 1000))))
    # 收缩后可能首尾相接，合并相邻区间。
    merged: list[tuple[int, int]] = []
    for lo, hi in ranges:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def source_ranges_to_timeline(sequence, ranges_ms: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """把源时间域静音区间映射到当前时间轴（只保留落在保留段内的部分）。"""
    out: list[tuple[int, int]] = []
    for segment in sequence.segments:
        source_lo = int(segment.source_in_ms)
        source_hi = int(segment.source_out_ms)
        for lo, hi in ranges_ms:
            clip_lo = max(int(lo), source_lo)
            clip_hi = min(int(hi), source_hi)
            if clip_hi - clip_lo <= 0:
                continue
            rate = segment.source_duration_ms / max(1, segment.duration_ms)
            out.append((round(segment.timeline_in_ms + (clip_lo - source_lo) / rate),
                        round(segment.timeline_in_ms + (clip_hi - source_lo) / rate)))
    return sorted(out)


def auto_cut_silence_command(project, timeline_ranges: Iterable[tuple[int, int]], changed=None):
    """按时间轴区间逐段波纹删除（可撤销；字幕同步位移）。

    区间必须按时间升序传入（source_ranges_to_timeline 的输出即是）。
    每删一段，后续区间按已删除总量左移——与用户手动 Q/W 波纹修剪同构。
    """
    from ..timeline.studio_edit_commands import EditSequenceCommand
    from ..timeline.studio_edit_sequence import delete_timeline_range, sequence_of

    sequence = sequence_of(project)
    applied = 0
    removed_total = 0
    shift = 0
    for raw_start, raw_end in sorted((int(a), int(b)) for a, b in timeline_ranges):
        start = raw_start - shift
        end = raw_end - shift
        if end - start <= 0:
            continue
        candidate = delete_timeline_range(sequence, start, end)
        removed = sequence.timeline_duration_ms - candidate.timeline_duration_ms
        if removed <= 0:
            continue
        sequence = candidate
        shift += removed
        removed_total += removed
        applied += 1
    label = f"自动剪口播气口（{applied} 段，共 {removed_total / 1000:.1f} 秒）"
    return EditSequenceCommand(project, sequence, None, label, changed)


def rough_cut_apply_command(
    project,
    timeline_ranges: Iterable[tuple[int, int]],
    *,
    cue_ids: Iterable[str] | None = None,
    label: str | None = None,
    changed=None,
):
    """Apply rough-cut ranges via one undoable ``EditSequenceCommand`` and clear marks.

    On ``redo()``: ripples ``EditSequence`` (and timeline-domain captions when
    independent captions are enabled) and clears executed ``rough_cut_marks``.
    On ``undo()``: restores the original ``EditSequence``, captions, and marks.
    """
    import copy
    from ..timeline.studio_edit_commands import EditSequenceCommand
    from ..timeline.studio_edit_sequence import delete_timeline_range, sequence_of
    from .ai_rough_cut import ROUGH_CUT_MARKS_KEY, clear_rough_cut_marks, get_rough_cut_marks

    ordered = sorted((int(a), int(b)) for a, b in timeline_ranges if int(b) > int(a))
    sequence = sequence_of(project)
    applied = 0
    removed_total = 0
    shift = 0
    for raw_start, raw_end in ordered:
        start = raw_start - shift
        end = raw_end - shift
        if end - start <= 0:
            continue
        candidate = delete_timeline_range(sequence, start, end)
        removed = sequence.timeline_duration_ms - candidate.timeline_duration_ms
        if removed <= 0:
            continue
        sequence = candidate
        shift += removed
        removed_total += removed
        applied += 1

    after_cues = None
    if project.render_settings.get("_cue_domain") == "timeline" and ordered:
        from ..timeline.studio_caption_timeline import ripple_caption_range

        working = copy.copy(project)
        working.cues = copy.deepcopy(project.cues)
        working.studio_state = copy.deepcopy(project.studio_state)
        for a, b in reversed(ordered):
            ripple_caption_range(working, a, b, locked=())
        after_cues = working.cues

    command_label = label or f"文稿粗剪（{applied} 段，共 {removed_total / 1000:.1f} 秒）"
    before_marks = copy.deepcopy(get_rough_cut_marks(project))
    executed_ids = list(cue_ids) if cue_ids is not None else None

    class RoughCutApplyCommand(EditSequenceCommand):
        def redo(self) -> None:
            clear_rough_cut_marks(self.project, cue_ids=executed_ids)
            try:
                super().redo()
            except Exception:
                if before_marks:
                    self.project.studio_state[ROUGH_CUT_MARKS_KEY] = copy.deepcopy(before_marks)
                else:
                    self.project.studio_state.pop(ROUGH_CUT_MARKS_KEY, None)
                raise

        def undo(self) -> None:
            if before_marks:
                self.project.studio_state[ROUGH_CUT_MARKS_KEY] = copy.deepcopy(before_marks)
            else:
                self.project.studio_state.pop(ROUGH_CUT_MARKS_KEY, None)
            try:
                super().undo()
            except Exception:
                clear_rough_cut_marks(self.project, cue_ids=executed_ids)
                raise

    return RoughCutApplyCommand(project, sequence, after_cues, command_label, changed)
