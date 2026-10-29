"""Re-measure word timing of edited captions with the selected aligner (on demand).

When a caption's text was edited (by hand or AI), its stored word timing
belongs to the old text: Studio realigns the new text to the old measured
words where it can, and otherwise reports a missing alignment. This action
measures the caption's *current* text again on its own audio, taken with the
same audio graph the preview and the export use (edits, FLV content clock),
together with adjacent captions of the same speaker as context (see
``cue_forced_alignment.plan_runs``). The result replaces only the requested
captions' receipt words, as one undoable edit; timing, text and speaker do
not change.

2026-10-22 (MFA plan step 4): every language with an aligner (it was
Japanese only), the timeline's aligner (MFA when selected), and the cut
positions are graded like recognition does (``boundary_grades``: the other
aligner and pauses), so "split at the cursor" can use them right away.
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
    from ..playback.cue_audio_preview import plan_cue_preview, preview_command
    plan = plan_cue_preview(project, cue_id, pre_roll_ms=pre_roll_ms, post_roll_ms=post_roll_ms)
    command, _receipts = preview_command(plan, ffmpeg)
    # Same mix, delivered as the aligner's 16 kHz mono float input.
    command = list(command)
    command[command.index("-ac") + 1] = "1"
    command[command.index("-ar") + 1] = str(SAMPLE_RATE)
    command[command.index("s16le")] = "f32le"
    from ..system.processes import run_hidden_subprocess
    completed = run_hidden_subprocess(command, purpose="caption realignment audio", capture_output=True,
                                      timeout=120, check=True)
    return plan, np.frombuffer(completed.stdout, dtype="<f4").copy()


CONTEXT_MS = 2000


def _runs(project, cue_ids):
    """Alignment runs holding the requested captions; unchanged neighbours are context only."""
    from ..playback.cue_audio_preview import caption_timeline_range
    from ..recognition.cue_forced_alignment import plan_runs
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


def aligner_language(project) -> str | None:
    """The aligner's language name for this project (None: no aligner for it)."""
    from ..subtitle_rules.language_rules import project_language, qwen_language_name
    return qwen_language_name(project_language(project) if project is not None else "")


class _Quiet:
    """``legacy`` for the shared second-opinion helper: Studio keeps no run log."""

    @staticmethod
    def record_run_event(*_args, **_kwargs):
        return None


def _shifted(rows, shift):
    out = []
    for row in rows:
        moved = dict(row)
        for key in ("at_ms", "second_ms", "pause_ms"):
            if moved.get(key):
                moved[key] = [int(value) + shift for value in moved[key]]
        out.append(moved)
    return out


def measure(project, cue_ids, *, language=None, cancelled=None):
    """Worker-thread part: audio of each run, one aligner call, receipts of the requested captions.

    Adjacent captions of the same speaker are measured together (texts joined),
    so a caption's first word cannot be forced onto its neighbour's last word
    inside the padding; only the requested captions get new receipts.
    """
    import numpy as np
    from ..recognition.asr import run_qwen_aligner_worker
    from ..recognition.boundary_grades import SpeechBand, grade_caption
    from ..recognition.cue_forced_alignment import second_opinion, split_run_row
    from .studio_video_track import ffmpeg_executable
    language = language or aligner_language(project) or "Japanese"
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
    audio = np.concatenate(pieces)
    payload = run_qwen_aligner_worker(audio, jobs)
    # The other aligner and the pauses grade every cut position (boundary_grades).
    second = None if cancelled and cancelled() else second_opinion(audio, jobs, payload, _Quiet())
    second_rows = {str(row.get("id")): row for row in (second or {}).get("results") or ()}
    engine = "" if second is None else "mfa" if str(second.get("protocol") or "").startswith("mfa-") else "qwen3"
    band = SpeechBand(audio)
    out = {}
    for row in payload.get("results") or ():
        plan, offset, run = plans[str(row["id"])]
        shift = plan.play_range_ms[0] - offset          # concatenated PCM clock -> project time
        other = second_rows.get(str(row["id"]))
        other_parts = (split_run_row(other, run, edge_shift_ms=shift)
                       if other is not None and other.get("text") == run["text"] else [None] * len(run["members"]))
        for member, part, other_part in zip(run["members"], split_run_row(row, run, edge_shift_ms=shift), other_parts):
            if member["key"] not in wanted:
                continue
            check = other_part["segments"] if other_part and other_part["text"] == part["text"] else None
            graded = _shifted(grade_caption(part["text"], part["segments"], check or None, band.pause), shift)
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
                                       "cue_range_ms": [member["start_ms"], member["end_ms"]],
                                       "boundaries": graded, "second": engine}
    return out


class RealignWordsCommand(QUndoCommand):
    def __init__(self, project, results, changed=None):
        super().__init__("重新对齐字词时间")
        from ..timeline.studio_caption_timeline import KEY
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
            if result.get("boundaries"):
                # Graded cut positions on the project clock (boundary_grades), read by text_split.
                from ..recognition.boundary_grades import POLICY
                receipt.update(boundaries=copy.deepcopy(result["boundaries"]), boundary_policy=POLICY,
                               boundary_second=result.get("second") or "")
            else:
                for key in ("boundaries", "boundary_policy", "boundary_second"):
                    receipt.pop(key, None)
            self.after[cue_id] = receipt
        self.changed = changed

    def _apply(self, receipts):
        from ..timeline.studio_caption_timeline import KEY
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain

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


def start_realign(page, cue_ids, on_done=None) -> None:
    """Context-menu action: measure in the background, apply as one undo step.

    ``on_done(results)`` runs after the receipts are applied (split at the cursor re-plans then).
    """
    from ..i18n import bind_text, tr
    project = page.project
    if not project or not cue_ids:
        return

    def message(text):
        label = getattr(page, "save_state", None)
        if label is not None:
            bind_text(label, text)

    from ..timeline.studio_caption_timeline import independent_captions
    if not independent_captions(project):
        message(tr("这个工程还没有转换成时间轴字幕，无法重新对齐"))
        return
    snapshot = copy.deepcopy(project)
    signals = _Signals(page)
    page._realign_signals = signals
    message(tr("正在重新对齐 {count} 条字幕，并用第二份证据检查切点…", count=len(cue_ids)))

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
        from ..recognition.boundary_grades import counts
        graded = counts([row for value in fresh.values() for row in value.get("boundaries") or ()])
        message(tr("已重新对齐 {count} 条字幕：可独立切 {independent} 处、只能整词 {whole} 处、不可靠 {unreliable} 处",
                   count=len(fresh), **graded))
        if callable(on_done):
            on_done(fresh)

    signals.done.connect(finish)

    def work():
        try:
            result = measure(snapshot, list(cue_ids))
        except Exception as exc:  # noqa: BLE001 - reported in the status line
            result = exc
        signals.done.emit(result)

    threading.Thread(target=work, name="caption-realign", daemon=True).start()
