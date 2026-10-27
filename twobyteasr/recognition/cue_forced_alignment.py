"""Forced alignment of final caption text and its project evidence.

Japanese, English, Korean and the European languages; Chinese when its
timeline is a forced aligner (2026-10-22, ``chinese_final_alignment``).

Every final cue is aligned with its current text, so the stored timing
always belongs to the effective transcript. Adjacent cues of one speaker are
aligned together as one *run* (their texts joined, one audio window) and the
result is split back per cue: aligned alone on a padded window, a cue's
first word was forced onto the previous cue's last word inside the padding
(both cues then claimed the same audio). A run's window is padded only up to
other speakers' cues; overlapping speakers are still aligned independently.
The project keeps one evidence row per aligned cue: the reliable pieces
Studio may cut at, plus the raw slot predictions, the official monotonic
repair and the slot posteriors of both passes, so every millisecond can be
traced to the model.
"""
from __future__ import annotations

import copy

CUE_ALIGNMENT_PREFIX = "cue-align:"
UNIT_FIELDS = ("text", "char_start", "char_end", "kind", "word_index", "raw_start_ms", "raw_end_ms",
               "start_ms", "end_ms", "start_basis", "end_basis", "start_p", "end_p",
               "start_local", "end_local", "start_spread_ms", "end_spread_ms")
WINDOW_PAD_MS = 300
# Same-speaker cues closer than this share one alignment run.
RUN_GAP_MS = 2 * WINDOW_PAD_MS
RUN_MAX_MS = 30_000
RUN_MAX_CUES = 8
RUN_SEPARATOR = " "
# A pause of this length (voice activity) between two lines ends a run even
# when display tails and short-gap bridging made the lines touch.
RUN_PAUSE_BREAK_MS = 700
# Timelines that are forced aligners. FireRed, Paraformer and Whisper
# timelines time Chinese characters themselves (and Qwen3 may be absent).
ALIGNER_TIMELINES = frozenset({"qwen_aligner", "mlx_qwen_aligner", "mfa_aligner"})


def chinese_final_alignment(task_language, timeline_backend) -> bool:
    """A Chinese task whose timeline is a forced aligner aligns its final captions too (2026-10-22).

    Before, only the primary transcript was aligned, per segment in windows
    that overlap the neighbours': reviewed or glossary-changed words had no
    measured time, and one line's first syllable could be counted into the
    previous line.
    """
    from ..subtitle_rules.language_rules import ZH
    return str(task_language or "") == ZH and str(timeline_backend or "") in ALIGNER_TIMELINES


def _compact(units):
    if not units:
        return []
    return [[unit.get(name) for name in UNIT_FIELDS] for unit in units]


def expand_units(rows):
    return [dict(zip(UNIT_FIELDS, row)) for row in rows or ()]


def plan_runs(rows, *, pad_ms=WINDOW_PAD_MS):
    """Group captions into alignment runs and give each run its audio window.

    ``rows``: dicts with ``key, start_ms, end_ms, speaker, text``. Captions of
    one speaker that follow each other (gap <= RUN_GAP_MS, nobody else in
    between) form a run; its text is the members' texts joined by a space
    (a tokenizer and alignment break), ``spans`` give each member's range in
    it. The window is padded by ``pad_ms`` but never into another run that
    lies before/after it; truly overlapping speech cannot be excluded.
    """
    order = sorted((row for row in rows if int(row["end_ms"]) > int(row["start_ms"]) and str(row["text"]).strip()),
                   key=lambda row: (int(row["start_ms"]), int(row["end_ms"])))
    runs = []
    for row in order:
        last = runs[-1] if runs else None
        if (last and last["speaker"] == row["speaker"] and int(row["start_ms"]) - last["end_ms"] <= RUN_GAP_MS
                and not row.get("break_before")
                and len(last["members"]) < RUN_MAX_CUES and int(row["end_ms"]) - last["start_ms"] <= RUN_MAX_MS):
            last["members"].append(row)
            last["end_ms"] = max(last["end_ms"], int(row["end_ms"]))
        else:
            runs.append({"speaker": row["speaker"], "members": [row], "start_ms": int(row["start_ms"]),
                         "end_ms": int(row["end_ms"])})
    for run in runs:
        left, right = max(0, run["start_ms"] - pad_ms), run["end_ms"] + pad_ms
        for other in runs:
            if other is run:
                continue
            if left < other["end_ms"] <= run["start_ms"]:
                left = other["end_ms"]
            if run["end_ms"] <= other["start_ms"] < right:
                right = other["start_ms"]
        run["window_start_ms"], run["window_end_ms"] = left, right
        texts, spans, cursor = [], [], 0
        for member in run["members"]:
            text = str(member["text"])
            spans.append((cursor, cursor + len(text)))
            texts.append(text)
            cursor += len(text) + len(RUN_SEPARATOR)
        run["text"] = RUN_SEPARATOR.join(texts)
        run["spans"] = spans
    return runs


def _units_in(rows, start, end):
    out = []
    for unit in rows or ():
        if start <= int(unit["char_start"]) and int(unit["char_end"]) <= end:
            moved = dict(unit)
            moved["char_start"], moved["char_end"] = int(unit["char_start"]) - start, int(unit["char_end"]) - start
            out.append(moved)
    return out


def _member_pieces(segments, start, end, edge_start_ms, edge_end_ms):
    """Pieces of one member: inside ones as measured; edges completed with the caption's own times.

    A piece crossing the member edge means the model did not measure that
    boundary: the member keeps its own part, with the caption's start/end at
    that side (basis ``cue_edge``), so the text stays fully covered and only
    measured inner boundaries are ever offered as cut points.
    """
    pieces, crossing = [], 0
    for piece in segments or ():
        a, b = int(piece["char_start"]), int(piece["char_end"])
        if b <= start or a >= end:
            continue
        part = dict(piece, char_start=max(a, start) - start, char_end=min(b, end) - start)
        if a < start or b > end:
            crossing += 1
            part["granularity"] = "merged"
            if a < start:
                part["start_ms"], part["start_basis"] = int(edge_start_ms), "cue_edge"
            if b > end:
                part["end_ms"], part["end_basis"] = int(edge_end_ms), "cue_edge"
        pieces.append(part)
    pieces.sort(key=lambda piece: piece["char_start"])
    if pieces and pieces[0].get("start_basis") != "model":
        pieces[0] = dict(pieces[0], start_ms=int(edge_start_ms), start_basis="cue_edge")
    if pieces and pieces[-1].get("end_basis") != "model":
        pieces[-1] = dict(pieces[-1], end_ms=int(edge_end_ms), end_basis="cue_edge")
    measured_inner = any(piece.get("start_basis") == "model" or piece.get("end_basis") == "model"
                         for piece in pieces)
    if not measured_inner or any(int(p["end_ms"]) <= int(p["start_ms"]) for p in pieces) or any(
            int(left["end_ms"]) > int(right["start_ms"]) for left, right in zip(pieces, pieces[1:])):
        return [], crossing
    return pieces, crossing


def split_run_row(row, run, *, edge_shift_ms=0):
    """Per-member parts of one run result.

    ``edge_shift_ms`` converts the members' caption times into the clock of
    ``row`` (0 for the recognition task clock).
    """
    out = []
    for member, (start, end) in zip(run["members"], run["spans"]):
        pieces, crossing = _member_pieces(row.get("segments"), start, end,
                                          int(member["start_ms"]) - edge_shift_ms,
                                          int(member["end_ms"]) - edge_shift_ms)
        stats = dict(row.get("stats") or {})
        stats["run"] = {"members": len(run["members"]), "offset": start, "edge_pieces_split": crossing}
        out.append({"text": row["text"][start:end], "segments": pieces,
                    "stats": stats, "word_units": _units_in(row.get("word_units"), start, end),
                    "char_units": (_units_in(row.get("char_units"), start, end)
                                   if row.get("char_units") is not None else None)})
    return out


def longest_silence_ms(speech_regions, start_ms, end_ms):
    """Longest stretch inside [start_ms, end_ms) not covered by a voice-activity region (seconds dicts)."""
    regions = sorted((max(start_ms, round(float(r["start"]) * 1000)), min(end_ms, round(float(r["end"]) * 1000)))
                     for r in speech_regions or ())
    longest, cursor = 0, start_ms
    for a, b in regions:
        if b <= a:
            continue
        longest = max(longest, a - cursor)
        cursor = max(cursor, b)
    return max(longest, end_ms - cursor)


def alignment_jobs(cues, *, language="Japanese", pad_ms=WINDOW_PAD_MS, speech_regions=None):
    """Worker jobs (one per run) and the runs they came from (for ``attach_results``).

    With ``speech_regions`` a line whose previous same-speaker line is
    separated from it by RUN_PAUSE_BREAK_MS of silence starts its own run.
    """
    rows = [{"key": index, "start_ms": int(round(float(getattr(cue, "start", 0.0)) * 1000)),
             "end_ms": int(round(float(getattr(cue, "end", 0.0)) * 1000)),
             "speaker": str(getattr(cue, "speaker", "") or "S00"), "text": str(getattr(cue, "text", "") or "")}
            for index, cue in enumerate(cues, 1)]
    if speech_regions:
        ordered = sorted(rows, key=lambda row: (row["start_ms"], row["end_ms"]))
        for left, right in zip(ordered, ordered[1:]):
            if left["speaker"] == right["speaker"]:
                middle = (left["start_ms"] + left["end_ms"]) // 2
                right["break_before"] = longest_silence_ms(speech_regions, middle, right["start_ms"] + 150) >= RUN_PAUSE_BREAK_MS
    runs = plan_runs(rows, pad_ms=pad_ms)
    jobs = [{"id": f"run-{number}", "window_start_ms": run["window_start_ms"], "window_end_ms": run["window_end_ms"],
             "text": run["text"], "language": language} for number, run in enumerate(runs, 1)]
    return jobs, runs


def local_alignment_jobs(cues, reused_keys, *, language="English", speech_regions=None):
    """Bound changed cues to local windows with at most one neighbor of context."""
    _jobs, full_runs = alignment_jobs(cues, language=language, speech_regions=speech_regions)
    runs, targets = [], set()
    for full in full_runs:
        members = full['members']
        bad = {index for index, member in enumerate(members) if member['key'] not in reused_keys}
        if not bad:
            continue
        targets.update(members[index]['key'] for index in bad)
        selected = sorted({neighbor for index in bad for neighbor in (index - 1, index, index + 1)
                           if 0 <= neighbor < len(members)})
        groups = []
        for index in selected:
            if not groups or index != groups[-1][-1] + 1:
                groups.append([index])
            else:
                groups[-1].append(index)
        # A narrow gap between two affected regions must not lead to two
        # overlapping audio windows that independently claim the same words.
        merged = []
        for group in groups:
            if (merged and int(members[merged[-1][-1]]['end_ms']) + WINDOW_PAD_MS
                    >= int(members[group[0]]['start_ms']) - WINDOW_PAD_MS):
                merged[-1] = list(range(merged[-1][0], group[-1] + 1))
            else:
                merged.append(group)
        for group in merged:
            subset = [members[index] for index in group]
            start, end = min(int(x['start_ms']) for x in subset), max(int(x['end_ms']) for x in subset)
            left = max(int(full['window_start_ms']), start - WINDOW_PAD_MS)
            right = min(int(full['window_end_ms']), end + WINDOW_PAD_MS)
            spans, texts, cursor = [], [], 0
            for member in subset:
                text = str(member['text'])
                spans.append((cursor, cursor + len(text)))
                texts.append(text)
                cursor += len(text) + len(RUN_SEPARATOR)
            runs.append({'speaker': full['speaker'], 'members': subset, 'start_ms': start, 'end_ms': end,
                         'window_start_ms': left, 'window_end_ms': right,
                         'text': RUN_SEPARATOR.join(texts), 'spans': spans})
    jobs = [{'id': f'run-{index}', 'window_start_ms': run['window_start_ms'],
             'window_end_ms': run['window_end_ms'], 'text': run['text'], 'language': language}
            for index, run in enumerate(runs, 1)]
    return jobs, runs, targets


def attach_results(cues, runs, payload, *, target_keys=None):
    """Attach each cue's part of its run result as ``cue.forced_alignment``."""
    by_id = {str(row.get("id")): row for row in payload.get("results") or ()}
    meta = {key: payload.get(key) for key in ("model", "model_revision", "code", "unit_policy", "dtype", "torch_version")}
    attached = 0
    for number, run in enumerate(runs, 1):
        row = by_id.get(f"run-{number}")
        if row is None or row.get("text") != run["text"]:
            continue
        for member, part in zip(run["members"], split_run_row(row, run)):
            if target_keys is not None and member['key'] not in target_keys:
                continue
            cue = cues[member["key"] - 1]
            if part["text"] != str(getattr(cue, "text", "")):
                continue
            cue.forced_alignment = {
                **meta, "language": row.get("language"), "status": row.get("status"), "mapping": row.get("mapping"),
                "text": part["text"], "window_start_ms": row.get("window_start_ms"),
                "window_end_ms": row.get("window_end_ms"),
                "run": {"id": f"run-{number}", "members": len(run["members"]), "text": run["text"]},
                "segments": copy.deepcopy(part["segments"]), "stats": copy.deepcopy(part["stats"]),
                "tokenizer_words": list(row.get("tokenizer_words") or []),
                "units_word": _compact(part["word_units"]), "units_char": _compact(part["char_units"]),
                "unit_fields": list(UNIT_FIELDS)}
            attached += 1
    return attached


def align_final_cues(cues, audio, legacy, *, language="Japanese", speech_regions=None, evidence_dir=None):
    """Align every final cue's own text; failures leave cues without words.

    ``evidence_dir``: where the whole worker receipt is kept (``timing_evidence``).
    """
    cues = list(cues)
    jobs, runs = alignment_jobs(cues, language=language, speech_regions=speech_regions)
    if not jobs:
        return 0
    from concurrent.futures import ThreadPoolExecutor
    from twobyteasr.recognition.asr import AlignerUnavailableError, run_qwen_aligner_worker, summarize_aligner_payload
    from twobyteasr.recognition.service import CancelledError
    from .run_context import get_runtime_context
    context = get_runtime_context()
    evidence = getattr(context, 'segment_alignment_evidence', None)
    context.segment_alignment_evidence = None  # never leak a receipt into another media item
    reusable, reasons, targets = {}, {}, None
    def require_current():
        if (get_runtime_context() is not context or
                bool(getattr(context.cancellation_token, 'is_cancelled', False))):
            raise CancelledError('对齐任务已取消，丢弃迟到的时间证据。')
    require_current()
    if (isinstance(evidence, dict) and evidence.get('audio') is audio
            and evidence.get('job_id') == context.job_id
            and str(evidence.get('language', '')).casefold() == str(language).casefold()):
        from .word_evidence_reuse import audio_sha256, plan_reuse
        try:
            reusable, reasons = plan_reuse(cues, evidence.get('payload'), language=language,
                                           audio_digest=audio_sha256(audio), cancel_check=require_current)
        except CancelledError:
            raise
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            reasons = {'invalid_receipt': len(cues)}
            legacy.record_run_event('forced_alignment_reuse_rejected', reason=type(exc).__name__)
        require_current()
        for key, alignment in reusable.items():
            cues[key - 1].forced_alignment = alignment
        original_job_count = len(jobs)
        if reusable:
            jobs, runs, targets = local_alignment_jobs(cues, set(reusable), language=language,
                                                       speech_regions=speech_regions)
        legacy.record_run_event('forced_alignment_reuse_plan', language=language,
            source_jobs=len((evidence.get('payload') or {}).get('results') or ()),
            reused_cues=len(reusable), reused_words=sum(x['stats']['reused_words'] for x in reusable.values()),
            invalidated_cues=len(targets) if targets is not None else len(cues),
            local_jobs=len(jobs), full_final_jobs=original_job_count, reasons=reasons,
            context_cues=(sum(len(run['members']) for run in runs) - len(targets)) if targets is not None else 0)

    def grade_reused(band=None):
        if not reusable:
            return band
        from .boundary_grades import GRADES, POLICY, SpeechBand, grade_caption
        band = band or SpeechBand(audio)
        totals = {grade: 0 for grade in GRADES}
        for key, alignment in reusable.items():
            require_current()
            graded = grade_caption(alignment['text'], alignment['segments'], None, band.pause)
            alignment.update(boundaries=graded, boundary_policy=POLICY)
            for item in graded:
                totals[item['grade']] += 1
        legacy.record_run_event('forced_alignment_reuse_graded', policy=POLICY,
                                second='none', **totals)
        return band

    if not jobs:
        grade_reused()
        return len(reusable)
    # 2026-10-22 (user report: a 24-minute MOSS Pro task took 491 s): the
    # second opinion only needs the same jobs, not the first aligner's answer,
    # so it runs beside it (Qwen3 on the GPU while MFA runs on the CPU: 22 s).
    # Its result is used only when the first aligner is the one predicted.
    predicted = _predicted_second_engine(jobs)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="second-aligner") if predicted else None
    early = pool.submit(_second_attempt, predicted, audio, jobs) if pool else None
    try:
        try:
            payload = run_qwen_aligner_worker(audio, jobs)
        except AlignerUnavailableError as exc:
            legacy.add_review_item(0.0, "缺少对齐模型", str(exc), priority=3, severity="warning")
            legacy.record_run_event("forced_alignment_unavailable", stage="final_cues", reason=str(exc))
            grade_reused()
            return len(reusable)
        except CancelledError:
            raise
        except Exception as exc:
            # A failed aligner must not discard the recognized subtitles; cues keep
            # their recognizer bounds and stay marked as lacking word alignment.
            legacy.add_review_item(0.0, "字级对齐失败", str(exc)[:200], priority=2, severity="warning")
            legacy.record_run_event("forced_alignment_failed", stage="final_cues", reason=str(exc)[:500])
            grade_reused()
            return len(reusable)
        require_current()
        attached = attach_results(cues, runs, payload, target_keys=targets)
        from .timing_evidence import save_aligner_payload
        saved = save_aligner_payload(evidence_dir, "final_cues", language, payload,
                                     runs=[{"id": f"run-{number}", "members": [m["key"] for m in run["members"]],
                                            "targets": [m['key'] for m in run['members'] if targets is None or m['key'] in targets],
                                            "spans": run["spans"]} for number, run in enumerate(runs, 1)])
        legacy.record_run_event("forced_alignment", stage="final_cues", language=language, attached=attached,
                                runs=len(runs), **summarize_aligner_payload(payload), **({"evidence": saved} if saved else {}))
        band = grade_reused()
        if attached:
            matched = early is not None and _second_engine(payload) == predicted
            second = second_opinion(audio, jobs, payload, legacy, attempt=early.result() if matched else None)
            if second is not None:
                save_aligner_payload(evidence_dir, "final_cues", language, second)
            grade_final_cues(cues, runs, second, audio, legacy, target_keys=targets, band=band)
        return attached + len(reusable)
    finally:
        if pool is not None:
            pool.shutdown(wait=True)  # never leave an aligner process running into the next stage


def _second_engine(payload) -> str:
    return "qwen3" if str((payload or {}).get("protocol") or "").startswith("mfa-") else "mfa"


def _predicted_second_engine(jobs) -> str:
    """The second-opinion engine before the first aligner answers ('' when unsure).

    Same routing as ``run_qwen_aligner_worker``: MFA first when it is the
    selected timeline and handles these jobs, otherwise Qwen3 (or MLX) first.
    """
    try:
        from twobyteasr.recognition import asr
        from . import mfa_aligner
        from .run_context import get_runtime_context
        settings = get_runtime_context().asr_settings_snapshot or asr._legacy_runtime_value(
            "RUNTIME_SETTINGS", asr.RUNTIME_SETTINGS)
        backend = str(((settings or {}).get("models") or {}).get("firered_asr_backend"))
        return "qwen3" if backend == "mfa_aligner" and mfa_aligner.handles(jobs) else "mfa"
    except Exception:  # noqa: BLE001 - no prediction: the second opinion runs after the first
        return ""


def _second_attempt(engine, audio, jobs):
    """Run the other aligner; ``(status, value)`` without recording, so it may run on a helper thread."""
    from twobyteasr.recognition.asr import AlignerUnavailableError, run_qwen_aligner_worker
    from twobyteasr.recognition.service import CancelledError
    from . import mfa_aligner
    if engine == "mfa" and not (mfa_aligner.handles(jobs) and mfa_aligner.runtime_python()):
        return "not_installed", None
    try:
        return "ok", (run_qwen_aligner_worker(audio, jobs, engine="qwen3") if engine == "qwen3"
                      else mfa_aligner.run_aligner(audio, jobs))
    except CancelledError as exc:
        return "cancelled", exc
    except (AlignerUnavailableError, mfa_aligner.MfaUnavailableError) as exc:
        return "unavailable", exc
    except Exception as exc:  # noqa: BLE001 - the second opinion is optional; grades then rest on pauses
        return "failed", exc


def second_opinion(audio, jobs, payload, legacy, *, attempt=None):
    """The other aligner on the same jobs (Qwen3 after MFA, MFA after Qwen3), or None (2026-10-22).

    It only confirms or questions the first aligner's boundaries
    (``boundary_grades``); its times never replace them. ``attempt`` is a
    ``_second_attempt`` result that already ran beside the first aligner.
    """
    engine = _second_engine(payload)
    if attempt is None:
        from . import mfa_aligner
        if not (engine == "mfa" and not (mfa_aligner.handles(jobs) and mfa_aligner.runtime_python())):
            print(f"   [切点分级] 用{'Qwen3 对齐器' if engine == 'qwen3' else ' MFA（实验）'}复核同一批字幕的切点…")
        attempt = _second_attempt(engine, audio, jobs)
    else:
        print(f"   [切点分级] {'Qwen3 对齐器' if engine == 'qwen3' else ' MFA（实验）'}已与第一个对齐器同时复核了同一批字幕的切点。")
    status, value = attempt
    if status == "cancelled":
        raise value
    if status == "not_installed":
        legacy.record_run_event("boundary_second_opinion", engine=engine, skipped="not_installed_or_language")
        return None
    if status == "unavailable":
        legacy.record_run_event("boundary_second_opinion", engine=engine, skipped="unavailable", reason=str(value)[:300])
        return None
    if status == "failed":
        legacy.record_run_event("boundary_second_opinion", engine=engine, failed=f"{type(value).__name__}: {value}"[:400])
        return None
    legacy.record_run_event("boundary_second_opinion", engine=engine, model=value.get("model"),
                            inference_ms=value.get("inference_ms"))
    return value


def grade_final_cues(cues, runs, second, audio, legacy, *, target_keys=None, band=None):
    """Grade every cut position of the aligned captions (``boundary_grades``) into ``cue.forced_alignment``."""
    from .boundary_grades import GRADES, POLICY, SpeechBand, grade_caption
    band = band or SpeechBand(audio)
    by_id = {str(row.get("id")): row for row in (second or {}).get("results") or ()}
    engine = ("" if second is None else "mfa" if str(second.get("protocol") or "").startswith("mfa-") else "qwen3")
    totals, reasons = {grade: 0 for grade in GRADES}, {}
    for number, run in enumerate(runs, 1):
        row = by_id.get(f"run-{number}")
        parts = (split_run_row(row, run) if row is not None and row.get("text") == run["text"]
                 else [None] * len(run["members"]))
        for member, part in zip(run["members"], parts):
            if target_keys is not None and member['key'] not in target_keys:
                continue
            alignment = getattr(cues[member["key"] - 1], "forced_alignment", None)
            if not alignment:
                continue
            other = part["segments"] if part and part["text"] == alignment.get("text") and part["segments"] else None
            graded = grade_caption(str(alignment.get("text") or ""), alignment.get("segments"), other, band.pause)
            alignment.update(boundaries=graded, boundary_policy=POLICY)
            if other is not None:
                alignment["second"] = {"engine": engine, "model": second.get("model"), "segments": copy.deepcopy(other)}
            for item in graded:
                totals[item["grade"]] += 1
                reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    print(f"   [切点分级] 可独立切 {totals['independent']}、只能整词 {totals['whole']}、不可靠 {totals['unreliable']}"
          f"（第二份证据：{ {'qwen3': 'Qwen3 对齐器 + 停顿', 'mfa': 'MFA + 停顿'}.get(engine, '只有停顿') }）。")
    legacy.record_run_event("boundary_grades", policy=POLICY, second=engine, **totals, reasons=reasons)
    return totals


def evidence_row(cue_id, start_ms, end_ms, speaker_id, alignment):
    """Project evidence row for one aligned cue (time = task/recognition clock).

    The row names the aligner that measured it (2026-10-22: MFA rows were
    labelled Qwen3-ForcedAligner).
    """
    pieces = []
    text = str(alignment.get("text") or "")
    mfa = str(alignment.get("model") or "").startswith("MontrealCorpusTools/")
    model, source, owner = (("mfa_aligner", "montreal-forced-aligner", "Montreal-Forced-Aligner") if mfa
                            else ("qwen3_forced_aligner", "qwen3-forced-aligner", "Qwen3-ForcedAligner"))
    for piece in alignment.get("segments") or ():
        a, b = int(piece["start_ms"]), int(piece["end_ms"])
        fragment = text[int(piece["char_start"]):int(piece["char_end"])]
        if b > a and fragment.strip():
            pieces.append({"text": fragment, "start_ms": a, "end_ms": b, "char_start": int(piece["char_start"]),
                           "char_end": int(piece["char_end"]), "model": model,
                           "granularity": piece.get("granularity"), "start_basis": piece.get("start_basis"),
                           "end_basis": piece.get("end_basis")})
    return {
        "start_ms": int(start_ms), "end_ms": int(end_ms), "text": text, "speaker_id": str(speaker_id),
        "primary_source": source, "final_timing_owner": owner,
        "final_text_owner": "current caption text",
        "cue_alignment": {key: alignment.get(key) for key in (
            "model", "model_revision", "code", "unit_policy", "language", "status", "mapping", "stats",
            "window_start_ms", "window_end_ms", "run")} | {"cue_id": str(cue_id)} | {
            key: alignment[key] for key in ("script_remapped", "aligned_text") if key in alignment},
        "words": [{k: p[k] for k in ("text", "start_ms", "end_ms")} for p in pieces],
        "caption_arbitration": {"acoustic_words": pieces, "forced_alignment": {
            "unit_fields": alignment.get("unit_fields"), "units_word": alignment.get("units_word"),
            "units_char": alignment.get("units_char"), "tokenizer_words": alignment.get("tokenizer_words"),
            # 2026-10-22: every cut position graded (boundary_grades) and the second aligner's pieces.
            **{key: alignment[key] for key in ("boundaries", "boundary_policy", "second") if key in alignment}}},
    }


def remap_whitespace_only(alignment, text):
    """Alignment re-indexed onto ``text`` when only whitespace (or 简/繁) differs, else None.

    The delivery step normalises formatting whitespace after alignment, and
    (2026-10-22, Chinese captions are aligned too) converts 繁體 subtitles
    character for character; every other character must be identical and in
    the same order. The units keep the text the aligner heard
    (``aligned_text``); the pieces read the delivered text.
    """
    old = str(alignment.get("text") or "")
    if old == text:
        return alignment
    from ..subtitle_rules.chinese_script import fold
    old_key, new_key = fold(old), fold(text)
    old_positions = [i for i, c in enumerate(old) if not c.isspace()]
    new_positions = [i for i, c in enumerate(text) if not c.isspace()]
    if [old_key[i] for i in old_positions] != [new_key[i] for i in new_positions]:
        return None
    index = {o: n for o, n in zip(old_positions, new_positions)}

    def start(value):
        following = [o for o in old_positions if o >= value]
        return index[following[0]] if following else len(text)

    def end(value):
        preceding = [o for o in old_positions if o < value]
        return index[preceding[-1]] + 1 if preceding else 0

    moved = copy.deepcopy(alignment)
    moved["text"] = text
    for piece in [*(moved.get("segments") or ()), *((moved.get("second") or {}).get("segments") or ())]:
        piece["char_start"], piece["char_end"] = start(int(piece["char_start"])), end(int(piece["char_end"]))
    for row in moved.get("boundaries") or ():  # the line start and end stay the text's own edges
        position = int(row["pos"])
        row["pos"] = 0 if position == 0 else len(text) if position >= len(old) else start(position)
    for key in ("units_word", "units_char"):
        for row in moved.get(key) or ():
            row[1], row[2] = start(int(row[1])), end(int(row[2]))
    moved["whitespace_remapped"] = True
    if [old[i] for i in old_positions] != [text[i] for i in new_positions]:
        moved["script_remapped"] = True
        moved["aligned_text"] = old
    return moved


def attach_project_evidence(project, runtime_cues):
    """Give each aligned project cue its own alignment row as preferred evidence."""
    added = 0
    for runtime_cue, cue in zip(runtime_cues, project.cues):
        alignment = getattr(runtime_cue, "forced_alignment", None)
        alignment = remap_whitespace_only(alignment, cue.text) if alignment else None
        if not alignment:
            continue
        reference = CUE_ALIGNMENT_PREFIX + cue.id
        project.asr_evidence[reference] = evidence_row(cue.id, cue.start_ms, cue.end_ms, cue.speaker_id, alignment)
        cue.evidence_refs = [reference, *[ref for ref in cue.evidence_refs if ref != reference]]
        added += 1
    if added:
        project.generation_metadata["cue_forced_alignment"] = {
            "rows": added, "prefix": CUE_ALIGNMENT_PREFIX, "policy": "per-cue current text; reliable pieces only"}
    return added


def is_cue_alignment_row(row) -> bool:
    return isinstance(row, dict) and isinstance(row.get("cue_alignment"), dict)
