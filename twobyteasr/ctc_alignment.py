"""Japanese line starts refined with a CTC aligner (2026-10-13).

The user approved downloading ``jonatasgrosman/wav2vec2-large-xlsr-53-japanese``
(Apache-2.0, character CTC, 20 ms frames). Measured on 206 line starts that
follow a clear pause (two Nichijou recognitions) and on the hand-labelled set:

* CTC starts are typically closer (median error 62 -> 32 ms episode, 42 -> 26 ms
  clip) but have a heavier tail when the model mishears the line (anime audio
  with music: it recognises much of the dialogue poorly);
* its own posterior is not a usable confidence (high-scoring first characters
  were *worse*), and its line ends are 0.2-0.4 s early (CTC peaks early in the
  last character), so ends are never taken from it.

Rule (``ctc-start-v1``): a line's start moves to the CTC start only when the
CTC start agrees within 80 ms with an independent reference - the Qwen
aligner's measured start when there is one, else the line's current start -
the move keeps every line at least 300 ms long and is at most 600 ms. A same-speaker line that
ends after the new start ends there (the cut moves). Ends, text, speakers and
translations are unchanged. Without the model installed nothing happens.

Same-speaker adjacent lines (gap < 700 ms) are aligned together in one window
(500 ms margins), so a cut inside an utterance is decided by the model; other
speakers' lines are never part of a job.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

POLICY = "ctc-start-v1"
PROTOCOL = "ja-ctc-align-v1"
MODEL_KEY = "ja_ctc_aligner"
MODEL_DIR_NAME = "wav2vec2-large-xlsr-53-japanese"
AGREE_MS = 80
RUN_GAP_MS = 700
MARGIN_MS = 500
MAX_WINDOW_MS = 30_000
MIN_LINE_MS = 300
MIN_MOVE_MS = 10
MAX_MOVE_MS = 600      # safety bound; two models agreeing on a larger move is left to the user


class CtcAlignerUnavailable(RuntimeError):
    pass


@dataclass
class StartChange:
    cue_id: str
    old_ms: int
    new_ms: int
    reference: str
    reference_ms: int
    previous_id: str = ""
    previous_end_ms: int | None = None

    def receipt(self) -> dict:
        row = dict(cue=self.cue_id, old_ms=self.old_ms, new_ms=self.new_ms, reference=self.reference,
                   reference_ms=self.reference_ms, policy=POLICY)
        if self.previous_id:
            row.update(previous=self.previous_id, previous_end_ms=self.previous_end_ms)
        return row


def model_dir() -> str | None:
    """The installed model folder (shared model root first), or None."""
    from .runtime_paths import iter_model_dir_candidates
    env = os.environ.get("2BYTEASR_JA_CTC_ALIGNER_DIR", "").strip()
    candidates = [Path(env).expanduser()] if env else []
    candidates += [Path(p) for p in iter_model_dir_candidates(MODEL_DIR_NAME)]
    candidates.append(Path(__file__).resolve().parents[1] / "models" / MODEL_DIR_NAME)
    for candidate in candidates:
        if ((candidate / "config.json").is_file() and (candidate / "pytorch_model.bin").is_file()
                and not (candidate / ".2byteasr-install-pending.json").exists()):
            return str(candidate)
    return None


def plan_jobs(rows) -> list[dict]:
    """Runs of one speaker's adjacent lines (rows: id, start_ms, end_ms, speaker, text)."""
    by_speaker: dict[str, list] = {}
    for row in sorted(rows, key=lambda r: (r.start_ms, r.end_ms)):
        by_speaker.setdefault(row.speaker, []).append(row)
    jobs = []
    for speaker, items in by_speaker.items():
        runs: list[list] = []
        for row in items:
            if (runs and 0 <= row.start_ms - runs[-1][-1].end_ms < RUN_GAP_MS
                    and row.end_ms - runs[-1][0].start_ms + 2 * MARGIN_MS <= MAX_WINDOW_MS):
                runs[-1].append(row)
            else:
                runs.append([row])
        for run in runs:
            offsets, text = [], ""
            for row in run:
                offsets.append([row.id, len(text), len(row.text)])
                text += row.text
            jobs.append(dict(id=f"run-{len(jobs)}", text=text, offsets=offsets, speaker=speaker,
                             window_start_ms=max(0, run[0].start_ms - MARGIN_MS),
                             window_end_ms=run[-1].end_ms + MARGIN_MS))
    return jobs


def ctc_starts(jobs, payload) -> dict[str, int]:
    """Each line's first aligned character start (ms) from the worker results."""
    results = {str(row.get("id")): row for row in payload.get("results") or ()}
    starts = {}
    for job in jobs:
        row = results.get(job["id"]) or {}
        if row.get("status") != "aligned":
            continue
        chars = row.get("chars") or []
        for cue_id, offset, length in job["offsets"]:
            own = [c for c in chars if offset <= int(c["char"]) < offset + length]
            if own:
                starts[str(cue_id)] = round(float(own[0]["start_ms"]))
    return starts


def propose(rows, starts: dict[str, int], measured_start) -> list[StartChange]:
    """Apply the agreement rule; rows sorted by time, one change per line at most."""
    ordered = sorted(rows, key=lambda r: (r.start_ms, r.end_ms))
    previous_of: dict[str, object] = {}
    last_by_speaker: dict[str, object] = {}
    for row in ordered:
        previous_of[row.id] = last_by_speaker.get(row.speaker)
        last_by_speaker[row.speaker] = row
    changes = []
    for row in ordered:
        ctc = starts.get(row.id)
        if ctc is None:
            continue
        measured = measured_start(row)
        reference, reference_ms = ("aligner", int(measured)) if measured is not None else ("current", row.start_ms)
        if abs(ctc - reference_ms) > AGREE_MS or not MIN_MOVE_MS <= abs(ctc - row.start_ms) <= MAX_MOVE_MS:
            continue
        if row.end_ms - ctc < MIN_LINE_MS:
            continue
        change = StartChange(row.id, row.start_ms, int(ctc), reference, reference_ms)
        previous = previous_of.get(row.id)
        if previous is not None and previous.end_ms > ctc:
            if ctc - previous.start_ms < MIN_LINE_MS:
                continue
            change.previous_id, change.previous_end_ms = previous.id, int(ctc)
        changes.append(change)
    return changes


def run_worker(audio, jobs) -> dict:
    """``ctc_aligner_worker.py`` in the main managed runtime; the GUI never imports torch."""
    import numpy as np
    from .asr import AUDIO_SAMPLE_RATE, SCRIPT_DIR, _main_worker_python, _run_isolated_asr_worker
    from .processes import python_utf8_command
    path = model_dir()
    if not path:
        raise CtcAlignerUnavailable("日语 CTC 对齐模型（wav2vec2-large-xlsr-53-japanese）未安装")
    runtime = _main_worker_python()
    worker = os.path.join(os.path.abspath(SCRIPT_DIR), "ctc_aligner_worker.py")
    if not os.path.isfile(worker):
        worker = os.path.join(os.path.abspath(SCRIPT_DIR), "workers", "ctc_aligner_worker.py")
    if not os.path.isfile(runtime) or not os.path.isfile(worker):
        raise RuntimeError(f"CTC aligner runtime missing: python={runtime}, worker={worker}")
    pcm = np.ascontiguousarray(audio, dtype=np.float32)
    if pcm.ndim != 1 or not np.isfinite(pcm).all():
        raise RuntimeError("CTC 对齐需要有限值单声道 float32 PCM")
    digest = hashlib.sha256(pcm.tobytes()).hexdigest()
    policy = {"version": PROTOCOL, "audio_format": "float32-mono-npy-v1", "sample_rate": AUDIO_SAMPLE_RATE}
    worker_jobs = [dict(id=job["id"], text=job["text"], window_start_ms=job["window_start_ms"],
                        window_end_ms=job["window_end_ms"]) for job in jobs]
    with tempfile.TemporaryDirectory(prefix="ja_ctc_aligner_") as temp_dir:
        audio_path = os.path.join(temp_dir, "audio.npy")
        np.save(audio_path, pcm, allow_pickle=False)
        manifest = os.path.join(temp_dir, "manifest.json")
        output = os.path.join(temp_dir, "results.json")
        Path(manifest).write_text(json.dumps({"policy": policy, "jobs": worker_jobs, "audio": {
            "path": audio_path, "samples": int(pcm.size), "sha256": digest}}, ensure_ascii=False), encoding="utf-8")
        payload = _run_isolated_asr_worker(
            python_utf8_command([runtime, "-I", worker, "--manifest", manifest, "--output", output, "--model-dir", path]),
            output, model_id="JA-CTC-ALIGNER", audio_input="shared_audio", model_path=path,
            entrypoint="ctc_aligner_worker.py")
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or [str(r.get("id")) for r in results] != [j["id"] for j in worker_jobs]:
        raise RuntimeError("CTC 对齐 worker 返回的任务缺失、重复或乱序")
    if payload.get("policy") != policy or payload.get("audio_sha256") != digest or payload.get("protocol") != PROTOCOL:
        raise RuntimeError("CTC 对齐 worker 回执与输入不一致")
    if any(r.get("text") != j["text"] for r, j in zip(results, worker_jobs)):
        raise RuntimeError("CTC 对齐 worker 改写了输入文字")
    return payload


def _runtime_measured_start(cue):
    pieces = (getattr(cue, "forced_alignment", None) or {}).get("segments") or ()
    if pieces and pieces[0].get("start_basis") == "model":
        return int(pieces[0]["start_ms"])
    return None


def apply_to_runtime_cues(cues, audio, legacy) -> list[dict]:
    """Recognition (after final alignment and pause snapping): refine line starts."""
    from types import SimpleNamespace
    if not model_dir():
        legacy.record_run_event("ctc_start_refine", policy=POLICY, skipped="model_not_installed")
        return []
    rows = [SimpleNamespace(id=str(index), start_ms=round(float(cue.start) * 1000), end_ms=round(float(cue.end) * 1000),
                            speaker=str(getattr(cue, "speaker", "") or "S00"), text=str(getattr(cue, "text", "") or ""),
                            cue=cue)
            for index, cue in enumerate(cues)]
    jobs = plan_jobs(rows)
    try:
        payload = run_worker(audio, jobs)
    except Exception as exc:  # noqa: BLE001 - optional refinement; recognition result stays as aligned
        legacy.record_run_event("ctc_start_refine", policy=POLICY, failed=f"{type(exc).__name__}: {exc}"[:400])
        return []
    by_id = {row.id: row for row in rows}
    changes = propose(rows, ctc_starts(jobs, payload), lambda r: _runtime_measured_start(r.cue))
    for change in changes:
        cue = by_id[change.cue_id].cue
        cue.start = change.new_ms / 1000.0
        pieces = (getattr(cue, "forced_alignment", None) or {}).get("segments") or []
        if pieces and pieces[0].get("start_basis") != "model":
            pieces[0]["start_ms"], pieces[0]["start_basis"] = change.new_ms, "ctc"
        if change.previous_id:
            previous = by_id[change.previous_id].cue
            previous.end = change.new_ms / 1000.0
            tail = (getattr(previous, "forced_alignment", None) or {}).get("segments") or []
            if tail and tail[-1].get("end_basis") != "model" and tail[-1]["end_ms"] > change.new_ms:
                tail[-1]["end_ms"] = change.new_ms
    receipts = [c.receipt() for c in changes]
    legacy.record_run_event("ctc_start_refine", policy=POLICY, moved=len(receipts), jobs=len(jobs),
                            aligned=sum(1 for r in payload["results"] if r.get("status") == "aligned"),
                            device=payload.get("device"), inference_ms=payload.get("inference_ms"),
                            changes=receipts[:60])
    return receipts
