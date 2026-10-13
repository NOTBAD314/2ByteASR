"""Studio action: move unmeasured Japanese cuts to the pause between lines (2026-10-12).

Existing projects are never re-timed on open. This explicit action looks at
adjacent lines of one speaker whose cut the aligner did not measure, reads
the audio around each cut through the same audio graph as preview and export
(edits, FLV content clock), and applies the moves found by
``cue_boundary_refine`` as one undoable edit. Text, speakers, translations
and measured word pieces are unchanged.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from .studio_commands import EditCueIntervalsCommand

SAMPLE_RATE = 16000


def _measured(project, cue, side):
    ref = next((r for r in cue.evidence_refs if r.startswith("cue-align:")), None)
    row = project.asr_evidence.get(ref, {}) if ref else {}
    pieces = (row.get("caption_arbitration") or {}).get("acoustic_words") or ()
    if not pieces:
        return None
    piece = pieces[0] if side == "start" else pieces[-1]
    return int(piece[f"{side}_ms"]) if piece.get(f"{side}_basis") == "model" else None


def measure(project, cue_ids=None, *, cancelled=None):
    """Worker thread: proposed moves (CutChange) for the requested lines (all when None)."""
    import numpy as np
    from types import SimpleNamespace
    from .cue_audio_preview import plan_cue_preview, preview_command
    from .cue_boundary_refine import CONTEXT_AFTER_MS, SEARCH_BEFORE_MS, candidate_pairs, propose_for_pair
    from .processes import run_hidden_subprocess
    from .studio_video_track import ffmpeg_executable
    ffmpeg = str(ffmpeg_executable())
    wanted = None if cue_ids is None else {str(c) for c in cue_ids}
    rows = [SimpleNamespace(id=c.id, start_ms=c.start_ms, end_ms=c.end_ms, speaker=c.speaker_id, cue=c)
            for c in project.cues]
    changes = []
    for left, right in candidate_pairs(rows, lambda r: _measured(project, r.cue, "start")):
        if wanted is not None and right.id not in wanted and left.id not in wanted:
            continue
        if cancelled and cancelled():
            return []
        plan = plan_cue_preview(project, right.id, pre_roll_ms=SEARCH_BEFORE_MS + 200,
                                post_roll_ms=max(0, CONTEXT_AFTER_MS - (right.end_ms - right.start_ms)))
        command, _receipts = preview_command(plan, ffmpeg)
        command = list(command)
        command[command.index("-ac") + 1] = "1"
        command[command.index("-ar") + 1] = str(SAMPLE_RATE)
        command[command.index("s16le")] = "f32le"
        completed = run_hidden_subprocess(command, purpose="caption cut audio", capture_output=True,
                                          timeout=120, check=True)
        pcm = np.frombuffer(completed.stdout, dtype="<f4")
        # The plan's range is on the caption's timeline clock; shift it onto the cue clock.
        offset = int(plan.play_range_ms[0]) - (int(plan.cue_range_ms[0]) - int(right.start_ms))
        change = propose_for_pair(left, right, pcm, SAMPLE_RATE, offset_ms=offset,
                                  left_measured_end=_measured(project, left.cue, "end"))
        if change is not None:
            changes.append(change)
    return changes


class SnapCutsToPausesCommand(EditCueIntervalsCommand):
    def __init__(self, project, changes, changed=None):
        from .timeline_cue_gesture import CueInterval
        by_id = {c.id: c for c in project.cues}
        spans = {}
        for change in changes:
            left, right = by_id[change.left_id], by_id[change.right_id]
            spans.setdefault(left.id, [left.start_ms, left.end_ms, left.speaker_id])[1] = change.new_ms
            spans.setdefault(right.id, [right.start_ms, right.end_ms, right.speaker_id])[0] = change.new_ms
        super().__init__(project, {key: CueInterval(*value) for key, value in spans.items()}, changed)
        self.setText("按停顿校正日语切点")


class _Signals(QObject):
    done = Signal(object)


def start_snap_cuts(page, cue_ids=None) -> None:
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
    page._cut_refine_signals = signals
    message(tr("正在查找切点前的停顿…"))

    def finish(result):
        page._cut_refine_signals = None
        if isinstance(result, Exception):
            message(tr("校正切点失败：{error}", error=str(result)[:160]))
            return
        current = {c.id: (c.start_ms, c.end_ms) for c in page.project.cues} if page.project is project else {}
        fresh = [c for c in result if current.get(c.right_id, (None, None))[0] == c.old_ms
                 and current.get(c.left_id, (None, None))[1] == c.old_ms]
        if not fresh:
            message(tr("没有需要校正的切点（已实测或停顿不明确的切点保持不变）"))
            return
        page.undo_stack.push(SnapCutsToPausesCommand(project, fresh))
        message(tr("已把 {count} 个切点移到停顿处（可撤销）", count=len(fresh)))

    signals.done.connect(finish)

    def work():
        try:
            result = measure(snapshot, cue_ids)
        except Exception as exc:  # noqa: BLE001 - reported in the status line
            result = exc
        signals.done.emit(result)

    threading.Thread(target=work, name="caption-cut-refine", daemon=True).start()
