"""Re-measure word timing of edited captions with Qwen3-ForcedAligner (on demand).

When a Japanese caption's text was edited (by hand or AI), its stored word
timing belongs to the old text: Studio realigns the new text to the old
measured words where it can, and otherwise reports a missing alignment. This
action measures the caption's *current* text again on its own audio, taken
with the same audio graph the preview and the export use (edits, FLV content
clock), together with adjacent captions of the same speaker as context (see
``cue_forced_alignment.plan_runs``). The result replaces only the requested
captions' receipt words, as one undoable edit; timing, text and speaker do
not change.
"""
from __future__ import annotations

import copy
import subprocess
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand

PAD_MS = 300
SAMPLE_RATE = 16000


def _cue_pcm(project, cue_id, ffmpeg, pre_roll_ms=PAD_MS, post_roll_ms=PAD_MS):
    import numpy as np
    from .cue_audio_preview import plan_cue_preview, preview_command
    plan = plan_cue_preview(project, cue_id, pre_roll_ms=pre_roll_ms, post_roll_ms=post_roll_ms)
    command, _receipts = preview_command(plan, ffmpeg)
    # Same mix, delivered as the aligner's 16 kHz mono float input.
    command = list(command)
    command[command.index("-ac") + 1] = "1"
    command[command.index("-ar") + 1] = str(SAMPLE_RATE)
    command[command.index("s16le")] = "f32le"
    from .processes import run_hidden_subprocess
    completed = run_hidden_subprocess(command, purpose="caption realignment audio", capture_output=True,
                                      timeout=120, check=True)
    return plan, np.frombuffer(completed.stdout, dtype="<f4").copy()


CONTEXT_MS = 2000


def _runs(project, cue_ids):
    """Alignment runs holding the requested captions; unchanged neighbours are context only."""
    from .cue_audio_preview import caption_timeline_range
    from .cue_forced_alignment import plan_runs
    wanted = {str(cue_id) for cue_id in cue_ids}
    targets = [cue for cue in project.cues if cue.id in wanted]
    if not targets:
        return [], wanted
    near = [cue for cue in project.cues
            if any(cue.end_ms >= t.start_ms - CONTEXT_MS and cue.start_ms <= t.end_ms + CONTEXT_MS for t in targets)]
    rows = []
    for cue in near:
        _cue, (start, end), domain = caption_timeline_range(project, cue.id)
        # Captions on different clocks (projected vs source) are never joined.
        rows.append({"key": cue.id, "start_ms": start, "end_ms": end, "text": cue.text,
                     "speaker": f"{cue.speaker_id}|{domain}"})
    runs = [run for run in plan_runs(rows, pad_ms=PAD_MS) if wanted & {member["key"] for member in run["members"]}]
    return runs, wanted


def measure(project, cue_ids, *, language="Japanese", cancelled=None):
    """Worker-thread part: audio of each run, one aligner call, receipts of the requested captions.

    Adjacent captions of the same speaker are measured together (texts joined),
    so a caption's first word cannot be forced onto its neighbour's last word
    inside the padding; only the requested captions get new receipts.
    """
    import numpy as np
    from .asr import run_qwen_aligner_worker
    from .cue_forced_alignment import split_run_row
    from .studio_video_track import ffmpeg_executable
    ffmpeg = str(ffmpeg_executable())
    runs, wanted = _runs(project, cue_ids)
    pieces, jobs, plans, cursor = [], [], {}, 0
    for number, run in enumerate(runs, 1):
        if cancelled and cancelled():
            return {}
        first = run["members"][0]
        plan, pcm = _cue_pcm(project, first["key"], ffmpeg,
                             pre_roll_ms=max(0, first["start_ms"] - run["window_start_ms"]),
                             post_roll_ms=max(0, run["window_end_ms"] - first["end_ms"]))
        if pcm.size < SAMPLE_RATE // 10:
            continue
        start_ms = round(cursor * 1000 / SAMPLE_RATE)
        pieces.append(pcm)
        cursor += pcm.size
        job_id = f"run-{number}"
        jobs.append({"id": job_id, "window_start_ms": start_ms,
                     "window_end_ms": round(cursor * 1000 / SAMPLE_RATE), "text": run["text"],
                     "language": language})
        plans[job_id] = (plan, start_ms, run)
        # A short silence keeps neighbouring windows apart.
        pieces.append(np.zeros(SAMPLE_RATE // 5, dtype=np.float32))
        cursor += SAMPLE_RATE // 5
    if not jobs:
        return {}
    payload = run_qwen_aligner_worker(np.concatenate(pieces), jobs)
    out = {}
    for row in payload.get("results") or ():
        plan, offset, run = plans[str(row["id"])]
        shift = plan.play_range_ms[0] - offset          # concatenated PCM clock -> project time
        for member, part in zip(run["members"], split_run_row(row, run, edge_shift_ms=shift)):
            if member["key"] not in wanted:
                continue
            words = []
            for piece in part["segments"]:
                a, b = int(piece["start_ms"]) + shift, int(piece["end_ms"]) + shift
                if b <= a:
                    continue
                words.append({"text": part["text"][int(piece["char_start"]):int(piece["char_end"])],
                              "char_start": int(piece["char_start"]), "char_end": int(piece["char_end"]),
                              "start_ms": a, "end_ms": b, "evidence_ref": "realign:" + str(member["key"]),
                              "granularity": piece.get("granularity"), "start_basis": piece.get("start_basis"),
                              "end_basis": piece.get("end_basis")})
            out[str(member["key"])] = {"text": part["text"], "words": words, "status": row.get("status"),
                                       "stats": part["stats"], "model": payload.get("model"),
                                       "model_revision": payload.get("model_revision"),
                                       "cue_range_ms": [member["start_ms"], member["end_ms"]]}
    return out


class RealignWordsCommand(QUndoCommand):
    def __init__(self, project, results, changed=None):
        super().__init__("重新对齐字词时间")
        from .studio_caption_timeline import KEY
        self.project = project
        instances = project.studio_state.setdefault(KEY, {"version": 1, "instances": {}}).setdefault("instances", {})
        self.before = {cue_id: copy.deepcopy(instances.get(cue_id)) for cue_id in results}
        self.after = {}
        for cue_id, result in results.items():
            receipt = copy.deepcopy(instances.get(cue_id) or {})
            words = [{key: word[key] for key in ("text", "char_start", "char_end", "start_ms", "end_ms",
                                                 "evidence_ref")} for word in result["words"]]
            cue = next((c for c in project.cues if c.id == cue_id), None)
            receipt.update(text=result["text"], words=words, word_alignment="exact_token_text",
                           word_base_words=copy.deepcopy(words), word_base_alignment="exact_token_text",
                           word_base_interval=[cue.start_ms, cue.end_ms] if cue else result["cue_range_ms"],
                           acoustic_word_observation=True,
                           forced_alignment={"model": result.get("model"), "revision": result.get("model_revision"),
                                             "stats": result.get("stats"),
                                             "pieces": copy.deepcopy(result["words"])})
            self.after[cue_id] = receipt
        self.changed = changed

    def _apply(self, receipts):
        from .studio_caption_timeline import KEY
        from .studio_commands import _commit_mutation
        from .studio_runtime_state import DirtyDomain

        def mutate():
            instances = self.project.studio_state.setdefault(KEY, {"version": 1, "instances": {}}) \
                .setdefault("instances", {})
            for cue_id, receipt in receipts.items():
                if receipt is None:
                    instances.pop(cue_id, None)
                else:
                    instances[cue_id] = copy.deepcopy(receipt)

        _commit_mutation(self.project, action_id=self.text(),
                         dirty=DirtyDomain.TIMELINE_PIXELS | DirtyDomain.AUTOSAVE, cue_ids=tuple(receipts),
                         mutate=mutate, changed=self.changed, sync_caption_words=False)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


class _Signals(QObject):
    done = Signal(object)


def start_realign(page, cue_ids) -> None:
    """Context-menu action: measure in the background, apply as one undo step."""
    from .i18n import bind_text, tr
    project = page.project
    if not project or not cue_ids:
        return

    def message(text):
        label = getattr(page, "save_state", None)
        if label is not None:
            bind_text(label, text)

    from .studio_caption_timeline import independent_captions
    if not independent_captions(project):
        message(tr("这个工程还没有转换成时间轴字幕，无法重新对齐"))
        return
    snapshot = copy.deepcopy(project)
    signals = _Signals(page)
    page._realign_signals = signals
    message(tr("正在用 Qwen3-ForcedAligner 重新对齐 {count} 条字幕…", count=len(cue_ids)))

    def finish(result):
        page._realign_signals = None
        if isinstance(result, Exception):
            message(tr("重新对齐失败：{error}", error=str(result)[:160]))
            return
        current = {cue.id: cue.text for cue in page.project.cues} if page.project is project else {}
        fresh = {cue_id: value for cue_id, value in result.items() if current.get(cue_id) == value["text"]}
        if not fresh:
            message(tr("字幕在对齐期间被修改，结果已丢弃，请再试一次"))
            return
        page.undo_stack.push(RealignWordsCommand(project, fresh))
        measured = sum(len(value["words"]) for value in fresh.values())
        message(tr("已重新对齐 {count} 条字幕（{pieces} 个模型实测的字词片段）", count=len(fresh), pieces=measured))

    signals.done.connect(finish)

    def work():
        try:
            result = measure(snapshot, list(cue_ids))
        except Exception as exc:  # noqa: BLE001 - reported in the status line
            result = exc
        signals.done.emit(result)

    threading.Thread(target=work, name="caption-realign", daemon=True).start()
