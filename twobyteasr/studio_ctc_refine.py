"""Studio action: refine Japanese line starts with the CTC aligner (2026-10-13).

Existing projects are never re-timed on open. This explicit action reads the
audio of every same-speaker run of lines through the same audio graph as
preview and export (edits, FLV content clock), runs the optional CTC aligner
once for the whole project, and applies the starts that pass the
``ctc_alignment`` agreement rule as one undoable edit. Ends (except a
same-speaker cut that moves with a start), text, speakers and translations
are unchanged.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from .studio_commands import EditCueIntervalsCommand
from .studio_cut_refine import SAMPLE_RATE, _measured


def _window_audio(project, first, last, margin_ms):
    """PCM (float32, 16 kHz) of [first.start - margin, last.end + margin] and its start on the cue clock."""
    import numpy as np
    from .cue_audio_preview import plan_cue_preview, preview_command
    from .processes import run_hidden_subprocess
    from .studio_video_track import ffmpeg_executable
    plan = plan_cue_preview(project, first.id, pre_roll_ms=margin_ms,
                            post_roll_ms=max(0, last.end_ms - first.end_ms) + margin_ms)
    command, _receipts = preview_command(plan, str(ffmpeg_executable()))
    command = list(command)
    command[command.index("-ac") + 1] = "1"
    command[command.index("-ar") + 1] = str(SAMPLE_RATE)
    command[command.index("s16le")] = "f32le"
    completed = run_hidden_subprocess(command, purpose="caption ctc audio", capture_output=True, timeout=120, check=True)
    pcm = np.frombuffer(completed.stdout, dtype="<f4")
    start = int(first.start_ms) - (int(plan.cue_range_ms[0]) - int(plan.play_range_ms[0]))
    return pcm, start


def measure(project, cue_ids=None):
    """Worker thread: StartChange list for the requested lines (all when None)."""
    import numpy as np
    from types import SimpleNamespace
    from .ctc_alignment import MARGIN_MS, ctc_starts, plan_jobs, propose, run_worker
    rows = [SimpleNamespace(id=c.id, start_ms=c.start_ms, end_ms=c.end_ms, speaker=c.speaker_id, text=c.text, cue=c)
            for c in project.cues]
    by_id = {row.id: row for row in rows}
    jobs = plan_jobs(rows)
    wanted = None if cue_ids is None else {str(c) for c in cue_ids}
    if wanted is not None:
        jobs = [job for job in jobs if any(cue_id in wanted for cue_id, _o, _n in job["offsets"])]
    # One shared PCM: each job's window is laid end to end with 200 ms silence.
    pieces, worker_jobs, shifts = [], [], {}
    cursor = 0
    for job in jobs:
        first, last = by_id[job["offsets"][0][0]], by_id[job["offsets"][-1][0]]
        pcm, real_start = _window_audio(project, first, last, MARGIN_MS)
        pieces += [pcm, np.zeros(SAMPLE_RATE // 5, dtype=np.float32)]
        duration = pcm.size * 1000 // SAMPLE_RATE
        worker_jobs.append(dict(job, window_start_ms=cursor, window_end_ms=cursor + duration))
        shifts[job["id"]] = real_start - cursor
        cursor += duration + 200
    if not worker_jobs:
        return []
    payload = run_worker(np.concatenate(pieces), worker_jobs)
    for row in payload.get("results") or ():
        for char in row.get("chars") or ():
            char["start_ms"] += shifts[str(row["id"])]
            char["end_ms"] += shifts[str(row["id"])]
    starts = ctc_starts(jobs, payload)
    if wanted is not None:
        starts = {key: value for key, value in starts.items() if key in wanted}
    return propose(rows, starts, lambda r: _measured(project, r.cue, "start"))


class RefineStartsCommand(EditCueIntervalsCommand):
    def __init__(self, project, changes, changed=None):
        from .timeline_cue_gesture import CueInterval
        by_id = {c.id: c for c in project.cues}
        spans = {}
        for change in changes:
            cue = by_id[change.cue_id]
            spans.setdefault(cue.id, [cue.start_ms, cue.end_ms, cue.speaker_id])[0] = change.new_ms
            if change.previous_id:
                previous = by_id[change.previous_id]
                spans.setdefault(previous.id, [previous.start_ms, previous.end_ms, previous.speaker_id])[1] = change.previous_end_ms
        super().__init__(project, {key: CueInterval(*value) for key, value in spans.items()}, changed)
        self.setText("按 CTC 对齐模型校正日语句首")


class _Signals(QObject):
    done = Signal(object)


def start_refine_starts(page, cue_ids=None) -> None:
    """Context-menu action: measure in the background, apply as one undo step."""
    import copy
    from .i18n import bind_text, tr
    project = page.project
    if not project:
        return

    def message(text):
        label = getattr(page, "save_state", None)
        if label is not None:
            bind_text(label, text)

    snapshot = copy.deepcopy(project)
    signals = _Signals(page)
    page._ctc_refine_signals = signals
    message(tr("正在用 CTC 对齐模型测量句首…"))

    def finish(result):
        page._ctc_refine_signals = None
        if isinstance(result, Exception):
            message(tr("句首校正失败：{error}", error=str(result)[:160]))
            return
        current = {c.id: (c.start_ms, c.end_ms) for c in page.project.cues} if page.project is project else {}
        fresh = [c for c in result if current.get(c.cue_id, (None, None))[0] == c.old_ms
                 and (not c.previous_id or c.previous_id in current)]
        if not fresh:
            message(tr("没有需要校正的句首（与参考相差 80 ms 以上或已对齐的保持不变）"))
            return
        page.undo_stack.push(RefineStartsCommand(project, fresh))
        message(tr("已按 CTC 对齐模型校正 {count} 条字幕的开头（可撤销）", count=len(fresh)))

    signals.done.connect(finish)

    def work():
        try:
            result = measure(snapshot, cue_ids)
        except Exception as exc:  # noqa: BLE001 - reported in the status line
            result = exc
        signals.done.emit(result)

    threading.Thread(target=work, name="caption-ctc-refine", daemon=True).start()
