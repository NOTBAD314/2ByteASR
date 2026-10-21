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
ends after the new start ends there (the cut moves). Other ends, text, speakers and
translations are unchanged. Without the model installed nothing happens.

2026-10-18 (日常 19, MOSS Pro): the start moved alone, but after short-gap
bridging the previous line - often another speaker's - ends exactly at this
start. Moving the start 12-90 ms later left a blank frame between two lines
that should touch (47 in one episode); moving it earlier across another
speaker's end stacked both lines for a frame. A line of any speaker that ends
at the old start, or between the new and the old start, now ends at the new
start too (the cut moves; never shorter than 300 ms, else no move). With a
frame rate the new start is placed on the frame grid; a move that rounds back
onto the old frame is dropped.

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
CUT_TOLERANCE_MS = 1   # rounding of seconds to ms: a line ending within 1 ms of a start touches it


class CtcAlignerUnavailable(RuntimeError):
    pass


@dataclass
class StartChange:
    cue_id: str
    old_ms: int
    new_ms: int
    reference: str
    reference_ms: int
    # Lines whose end moves with this start: (id, new end ms).
    followers: tuple = ()

    @property
    def previous_id(self) -> str:
        return self.followers[0][0] if self.followers else ""

    @property
    def previous_end_ms(self) -> int | None:
        return self.followers[0][1] if self.followers else None

    def receipt(self) -> dict:
        row = dict(cue=self.cue_id, old_ms=self.old_ms, new_ms=self.new_ms, reference=self.reference,
                   reference_ms=self.reference_ms, policy=POLICY)
        if self.followers:
            row.update(previous=self.previous_id, previous_end_ms=self.previous_end_ms)
        if len(self.followers) > 1:
            row.update(also_ends=[list(item) for item in self.followers[1:]])
        return row


def frame_grid_ms(ms: float, frame_ms: float | None) -> int:
    """``ms`` on the frame grid (nearest frame start) when a frame length is given."""
    if not frame_ms:
        return int(round(ms))
    return int(round(round(ms / frame_ms) * frame_ms))


def model_dir() -> str | None:
    """The installed model folder (shared model root first), or None."""
    from ..runtime_paths import iter_model_dir_candidates
    env = os.environ.get("2BYTEASR_JA_CTC_ALIGNER_DIR", "").strip()
    candidates = [Path(env).expanduser()] if env else []
    candidates += [Path(p) for p in iter_model_dir_candidates(MODEL_DIR_NAME)]
    candidates.append(Path(__file__).resolve().parents[2] / "models" / MODEL_DIR_NAME)
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


def propose(rows, starts: dict[str, int], measured_start, *, frame_ms: float | None = None,
            alternate_start=None) -> list[StartChange]:
    """Apply the agreement rule; rows sorted by time, one change per line at most.

    ``frame_ms`` (optional) places each new start on the frame grid.
    """
    ordered = sorted(rows, key=lambda r: (r.start_ms, r.end_ms))
    previous_of: dict[str, object] = {}
    last_by_speaker: dict[str, object] = {}
    for row in ordered:
        previous_of[row.id] = last_by_speaker.get(row.speaker)
        last_by_speaker[row.speaker] = row
    # Accepted changes update these, so a line whose start and end both move
    # is checked against both.
    start_of = {row.id: row.start_ms for row in ordered}
    end_of = {row.id: row.end_ms for row in ordered}
    changes = []
    for row in ordered:
        ctc = starts.get(row.id)
        if ctc is None:
            continue
        measured = measured_start(row)
        reference, reference_ms = ("aligner", int(measured)) if measured is not None else ("current", row.start_ms)
        agree, limit = AGREE_MS, MAX_MOVE_MS
        if alternate_start is not None and measured is not None and abs(ctc - reference_ms) > AGREE_MS:
            alternate = alternate_start(row)
            # A weak word onset can lag its own reliable char pass. Only an
            # independent CTC agreement can replace it; a char pass alone cannot.
            if (alternate is not None and abs(ctc - alternate) <= 120
                    and abs(row.start_ms - reference_ms) <= 120):
                reference, reference_ms = 'aligner_char_conflict', int(alternate)
                agree, limit = 120, 800
        if abs(ctc - reference_ms) > agree or not MIN_MOVE_MS <= abs(ctc - row.start_ms) <= limit:
            continue
        new_ms = frame_grid_ms(ctc, frame_ms)
        if abs(new_ms - row.start_ms) <= CUT_TOLERANCE_MS or end_of[row.id] - new_ms < MIN_LINE_MS:
            continue
        # Ends that move with the start: a line (any speaker) touching the old
        # start or ending between the new and the old start, and the same
        # speaker's previous line when it ends after the new start.
        same_speaker_previous = previous_of.get(row.id)
        followers = [other for other in ordered if other is not row and other.start_ms < row.start_ms and (
            abs(end_of[other.id] - row.start_ms) <= CUT_TOLERANCE_MS
            or new_ms < end_of[other.id] < row.start_ms
            or (other is same_speaker_previous and end_of[other.id] > new_ms))]
        if reference == 'aligner_char_conflict':
            # Repair this speaker's shared cut only. Real overlapping speech on
            # another track is independent and must retain its end.
            followers = [other for other in followers if other is same_speaker_previous
                         and abs(end_of[other.id] - row.start_ms) <= CUT_TOLERANCE_MS]
        if any(new_ms - start_of[other.id] < MIN_LINE_MS for other in followers):
            continue
        start_of[row.id] = new_ms
        for other in followers:
            end_of[other.id] = new_ms
        changes.append(StartChange(row.id, row.start_ms, new_ms, reference, reference_ms,
                                   tuple((other.id, new_ms) for other in followers)))
    return changes


def run_worker(audio, jobs) -> dict:
    """``ctc_aligner_worker.py`` in the main managed runtime; the GUI never imports torch."""
    import numpy as np
    from .asr import AUDIO_SAMPLE_RATE, SCRIPT_DIR, _main_worker_python, _run_isolated_asr_worker
    from ..system.processes import python_utf8_command
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


def disputed_char_start(alignment):
    """An independently checkable alternative for a low-confidence word onset.

    Compact Qwen receipts keep both passes. Require literal text at char 0,
    model-based positive spans, a weak word posterior and a locally supported
    char onset; never treat repaired/nearest/window-edge slots as measurements.
    """
    fields = alignment.get('unit_fields') or ()
    words = alignment.get('units_word') or ()
    chars = alignment.get('units_char') or ()
    if not fields or not words or not chars:
        return None
    word, char = dict(zip(fields, words[0])), dict(zip(fields, chars[0]))
    try:
        if (int(word['char_start']) == int(char['char_start']) == 0
                and word['start_basis'] == char['start_basis'] == 'model'
                and int(char['end_ms']) > int(char['start_ms'])
                and float(word['start_p']) < .3 and float(char['start_p']) >= .35
                and float(char['start_local']) >= .7
                and 300 <= int(word['start_ms']) - int(char['start_ms']) <= 1000):
            return int(char['start_ms'])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _runtime_measured_start(cue):
    pieces = (getattr(cue, "forced_alignment", None) or {}).get("segments") or ()
    if pieces and pieces[0].get("start_basis") == "model":
        return int(pieces[0]["start_ms"])
    return None


SWITCH = "use_ja_ctc_aligner"


def enabled(settings=None) -> bool:
    """The user's choice; installed means used unless they turned it off (2026-10-14)."""
    if settings is None:
        from ..storage.settings import load_runtime_settings
        settings = load_runtime_settings()[0]
    return (settings.get("switches") or {}).get(SWITCH, True) is not False


def set_enabled(value: bool, runtime_settings=None) -> None:
    """Persist the 模型工坊 「使用 / 取消使用」 choice and mirror it in memory."""
    from ..storage.settings import load_runtime_settings, save_runtime_settings
    settings, path, warnings = load_runtime_settings()
    if any("could not be read" in str(item) for item in warnings):
        # Saving now would replace the unreadable file with defaults.
        raise RuntimeError(f"无法读取设置文件 {path}，未修改")
    settings.setdefault("switches", {})[SWITCH] = bool(value)
    save_runtime_settings(settings)
    if isinstance(runtime_settings, dict):
        runtime_settings.setdefault("switches", {})[SWITCH] = bool(value)


def apply_to_runtime_cues(cues, audio, legacy, *, fps: float | None = None) -> list[dict]:
    """Recognition (after final alignment and pause snapping): refine line starts.

    ``fps``: the timeline frame rate; new starts (and the ends that move with
    them) land on its frame grid like every other final cue endpoint.
    """
    from types import SimpleNamespace
    runtime = getattr(legacy, "RUNTIME_SETTINGS", None)
    if isinstance(runtime, dict) and not enabled(runtime):
        legacy.record_run_event("ctc_start_refine", policy=POLICY, skipped="disabled_by_user")
        return []
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
    fps = float(fps) if fps else None

    def seconds(ms):
        return round(ms * fps / 1000) / fps if fps else ms / 1000.0

    changes = propose(rows, ctc_starts(jobs, payload), lambda r: _runtime_measured_start(r.cue),
                      frame_ms=1000.0 / fps if fps else None,
                      alternate_start=lambda r: disputed_char_start(getattr(r.cue, 'forced_alignment', None) or {}))
    for change in changes:
        cue = by_id[change.cue_id].cue
        cue.start = seconds(change.new_ms)
        pieces = (getattr(cue, "forced_alignment", None) or {}).get("segments") or []
        if pieces and (pieces[0].get("start_basis") != "model" or change.reference == 'aligner_char_conflict'):
            pieces[0]["start_ms"], pieces[0]["start_basis"] = change.new_ms, "ctc"
        for follower_id, end_ms in change.followers:
            previous = by_id[follower_id].cue
            previous.end = seconds(end_ms)
            tail = (getattr(previous, "forced_alignment", None) or {}).get("segments") or []
            if tail and tail[-1].get("end_basis") != "model" and tail[-1]["end_ms"] > end_ms:
                tail[-1]["end_ms"] = end_ms
    receipts = [c.receipt() for c in changes]
    legacy.record_run_event("ctc_start_refine", policy=POLICY, moved=len(receipts), jobs=len(jobs),
                            aligned=sum(1 for r in payload["results"] if r.get("status") == "aligned"),
                            device=payload.get("device"), inference_ms=payload.get("inference_ms"),
                            changes=receipts[:60])
    return receipts
