"""Replay the Japanese grouping requests of a recognition task JSON offline.

2026-11-25. Reads every ``grouping_request_contract`` event (the exact segments
the model saw), rebuilds the batch with the current Japanese engine and reports,
per batch and in total, what the old request offered and what the new engine
does with three model answers that cannot be fetched again (raw AI replies are
stored only as hashes):

* ``source``    the model keeps the source rows (the common "no change" answer);
* ``single``    the model returns one boundary at the end (joins everything);
* ``off_marks`` every source boundary shifted by one (picks between marks).

No network, no audio. Timing is the source rows' own bounds, so duration
results are conservative. Usage::

    python -X utf8 -m twobyteasr.acceptance.japanese_grouping_replay REPORT.json [...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _rows(request_body):
    import subtitle_core as core
    return [core.SpeechSegment(int(row["id"]), float(row["start"]), float(row["end"]), str(row["text"]), .9, [],
                               speaker=str(row.get("speaker") or "S00")) for row in request_body["segments"]]


def _old_mid_word_mandatory(body):
    """Mandatory offsets of the old request that were not phrase ends (marked text)."""
    marked = str(body.get("marked_text") or "")
    count = int(body.get("break_candidate_count") or 0)
    return dict(old_break_candidate_count=count, total_length=int(body.get("total_length") or 0),
                old_every_gap=count >= int(body.get("total_length") or 0) > 1,
                old_marks_inside_hiragana=sum(1 for i in range(1, len(marked) - 1)
                                              if marked[i] == "‹" and "ぁ" <= marked[i - 1] <= "ゟ"
                                              and "ぁ" <= marked[marked.index("›", i) + 1:][:1] <= "ゟ"))


_TAG_SCRIPT = (
    "import json,sys,nagisa\n"
    "texts=json.load(open(sys.argv[1],encoding='utf-8'))\n"
    "rows=[]\n"
    "for t in texts:\n"
    "    g=nagisa.tagging(t) if t.strip() else None\n"
    "    rows.append(dict(text=t,words=[[w,p] for w,p in zip(g.words,g.postags)] if g else []))\n"
    "json.dump(dict(protocol='ja-morphology-v1',tagger='nagisa',tagger_version=nagisa.__version__,results=rows),"
    "open(sys.argv[2],'w',encoding='utf-8'),ensure_ascii=False)\n")


def tag_with(python, texts):
    """nagisa payload from an interpreter that has nagisa (same format as the worker)."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ja_replay_") as folder:
        source, target = Path(folder) / "texts.json", Path(folder) / "tagged.json"
        source.write_text(json.dumps(list(texts), ensure_ascii=False), encoding="utf-8")
        subprocess.run([python, "-I", "-c", _TAG_SCRIPT, str(source), str(target)], check=True, timeout=600)
        return json.loads(target.read_text(encoding="utf-8"))


def replay_report(path, *, tagger_python=None):
    import subtitle_core  # noqa: F401  (import order: core before subtitle_rules)
    from twobyteasr.subtitle_rules import japanese_grouping
    from twobyteasr.subtitle_rules.language_rules import language_scope
    from twobyteasr.subtitle_rules.segmentation_profiles import profile_for
    from twobyteasr.subtitle_rules.text_rules import display_length
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    profile = profile_for("ja")
    batches = []
    totals = dict(batches=0, old_every_gap=0, lines_over_limit_source=0, lines_over_limit_after=0,
                  indivisible_after=0, rejected_batches_after=0, mandatory_moved=0, snapped_picks=0)
    seen = set()
    document = None
    if tagger_python:
        from twobyteasr.subtitle_rules import japanese_morphology
        texts = []
        for event in data.get("events", []):
            if event.get("event") == "grouping_request_contract":
                texts.extend(str(row["text"]) for row in (event.get("request_body") or {}).get("segments", []))
        texts = list(dict.fromkeys(texts))
        document = japanese_morphology.build_document(texts, tag_with(tagger_python, texts))
    from contextlib import nullcontext
    from twobyteasr.subtitle_rules.japanese_morphology import phrase_scope
    scope = phrase_scope(document) if document is not None else nullcontext()
    with scope:
        return _replay_events(data, path, profile, batches, totals, seen)


def _replay_events(data, path, profile, batches, totals, seen):
    from twobyteasr.subtitle_rules import japanese_grouping
    from twobyteasr.subtitle_rules.language_rules import language_scope
    from twobyteasr.subtitle_rules.text_rules import display_length
    for event in data.get("events", []):
        if event.get("event") != "grouping_request_contract":
            continue
        body = event.get("request_body") or {}
        if "segments" not in body or body.get("prompt_version", "").find(":ja:") < 0:
            continue
        key = (event.get("shard_id"), event.get("batch_index"), body.get("total_length"))
        if key in seen:
            continue
        seen.add(key)
        segments = _rows(body)
        text = "".join(s.text for s in segments)
        with language_scope("ja"):
            mandatory = set(body.get("hard_break_character_offsets") or ()) | set(body.get("protected_source_offsets") or ())
            candidates = japanese_grouping.build_candidates(
                text, mandatory, segment_offsets=body.get("source_segment_offsets") or (),
                hard_max=int(profile.hard_max))
            if candidates is None:
                batches.append(dict(shard=event.get("shard_id"), batch=event.get("batch_index"), skipped="unindexable"))
                continue
            source_cuts = sorted(set(body.get("source_segment_offsets") or ()) | {candidates.total})
            answers = dict(source=source_cuts, single=[candidates.total],
                           off_marks=sorted({max(1, c - 1) for c in source_cuts[:-1]} | {candidates.total}))
            results = {}
            for name, answer in answers.items():
                try:
                    cues, receipt = japanese_grouping.finalize_batch(
                        segments, answer, candidates, hard_max=int(profile.hard_max),
                        preferred=int(profile.preferred), max_seconds=float(profile.max_seconds), complete=None)
                except Exception as error:   # a rejected batch is what the old code produced
                    results[name] = dict(error=f"{type(error).__name__}: {error}")
                    continue
                over = [c for c in cues if display_length(c.text) > profile.hard_max]
                results[name] = dict(cues=len(cues), over_limit=len(over),
                                     indivisible=receipt["counts"].get("local_indivisible_retained", 0),
                                     local_split=receipt["counts"].get("local_fallback_split", 0),
                                     snapped=len(receipt["snapped"]),
                                     max_units=max(display_length(c.text) for c in cues),
                                     conserved="".join(c.text for c in cues) == text)
        source_over = sum(1 for s in segments if display_length(s.text) > profile.hard_max)
        row = dict(shard=event.get("shard_id"), batch=event.get("batch_index"), **_old_mid_word_mandatory(body),
                   new_candidate_count=len(candidates.candidates), candidate_source=candidates.source,
                   mandatory_moved=candidates.moved_mandatory, indivisible=candidates.indivisible,
                   source_lines_over_limit=source_over, answers=results)
        batches.append(row)
        totals["batches"] += 1
        totals["old_every_gap"] += int(row["old_every_gap"])
        totals["lines_over_limit_source"] += source_over
        totals["mandatory_moved"] += len(candidates.moved_mandatory)
        src = results.get("source", {})
        if "error" in src:
            totals["rejected_batches_after"] += 1
        else:
            totals["lines_over_limit_after"] += src.get("over_limit", 0)
            totals["indivisible_after"] += src.get("indivisible", 0)
        totals["snapped_picks"] += results.get("off_marks", {}).get("snapped", 0)
    return dict(report=str(path), totals=totals, batches=batches)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    output = None
    tagger = None
    if "--tagger-python" in argv:
        index = argv.index("--tagger-python")
        tagger = argv[index + 1]
        del argv[index:index + 2]
    if "--out" in argv:
        index = argv.index("--out")
        output = Path(argv[index + 1])
        del argv[index:index + 2]
    results = [replay_report(path, tagger_python=tagger) for path in argv]
    for result in results:
        print(json.dumps(dict(report=result["report"], totals=result["totals"]), ensure_ascii=False))
    if output:
        output.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
