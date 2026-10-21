"""Japanese line starts from the optional CTC aligner: runs, agreement rule, worker (2026-10-13)."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from twobyteasr.recognition import ctc_alignment as ctc

ROOT = Path(__file__).resolve().parents[1]


def row(id, start, end, speaker="S1", text="あいう"):
    return SimpleNamespace(id=id, start_ms=start, end_ms=end, speaker=speaker, text=text)


def test_runs_join_one_speakers_adjacent_lines_only():
    rows = [row("a", 1000, 2000, text="こんにちは"), row("b", 2300, 3000, text="元気"),
            row("x", 2100, 2900, speaker="S2", text="はい"), row("c", 4000, 5000, text="また")]
    jobs = ctc.plan_jobs(rows)
    s1 = [j for j in jobs if j["speaker"] == "S1"]
    assert [[o[0] for o in j["offsets"]] for j in s1] == [["a", "b"], ["c"]]
    assert s1[0]["text"] == "こんにちは元気" and s1[0]["offsets"][1] == ["b", 5, 2]
    assert s1[0]["window_start_ms"] == 500 and s1[0]["window_end_ms"] == 3500
    assert [j["text"] for j in jobs if j["speaker"] == "S2"] == ["はい"]


def test_agreement_rule_moves_only_starts_that_agree_and_moves_the_cut():
    rows = [row("a", 1000, 2000), row("b", 2000, 3000), row("c", 4000, 5000), row("d", 6000, 6400)]
    starts = {"a": 1060, "b": 1950, "c": 4300, "d": 6150}
    measured = {"a": 1020}
    changes = ctc.propose(rows, starts, lambda r: measured.get(r.id))
    by = {c.cue_id: c for c in changes}
    assert by["a"].new_ms == 1060 and by["a"].reference == "aligner"           # within 80 ms of the aligner
    assert by["b"].new_ms == 1950 and by["b"].previous_id == "a" and by["b"].previous_end_ms == 1950  # cut moves
    assert "c" not in by                                                     # 300 ms from the reference
    assert "d" not in by                                                     # would leave a 250 ms line
    far = ctc.propose([row("e", 10000, 12000)], {"e": 9300}, lambda r: 9320)
    assert far == []                                                          # agrees, but a 700 ms move


FRAME_24 = 1000 / 23.976


def test_other_speakers_touching_or_crossed_ends_move_with_the_start():
    """2026-10-18 (日常 19): a new start left another speaker's touching line 1 frame short (blank frame)."""
    rows = [row("a", 1000, 2002, speaker="S1"), row("b", 2002, 3500, speaker="S2"),
            row("c", 3000, 4180, speaker="S1"), row("d", 4200, 6000, speaker="S2")]
    by = {c.cue_id: c for c in ctc.propose(rows, {"b": 2060, "d": 4140}, lambda r: None, frame_ms=FRAME_24)}
    assert by["b"].new_ms == ctc.frame_grid_ms(2060, FRAME_24) == 2044            # on the 23.976 fps grid
    assert by["b"].followers == (("a", 2044),)                                   # touching end keeps touching
    assert by["d"].new_ms == 4129 and by["d"].followers == (("c", 4129),)        # crossed end trimmed
    assert by["b"].receipt()["previous_end_ms"] == 2044


def test_a_moved_line_is_checked_with_its_new_start():
    rows = [row("a", 1000, 2002), row("b", 2002, 2400, speaker="S2"), row("c", 2400, 4000)]
    assert [c.cue_id for c in ctc.propose(rows, {"c": 2330}, lambda r: None, frame_ms=FRAME_24)] == ["c"]
    # b first starts 42 ms later; c's earlier start would then leave b 292 ms long.
    assert [c.cue_id for c in ctc.propose(rows, {"b": 2060, "c": 2330}, lambda r: None,
                                          frame_ms=FRAME_24)] == ["b"]


def test_runtime_starts_and_moved_ends_land_on_the_frame_grid(monkeypatch):
    fps = 24000 / 1001
    cues = [SimpleNamespace(start=1.0, end=2.002, speaker="S1", text="あいう"),
            SimpleNamespace(start=2.002, end=3.5, speaker="S2", text="えお")]
    monkeypatch.setattr(ctc, "model_dir", lambda: "model")
    monkeypatch.setattr(ctc, "run_worker", lambda audio, jobs: {"results": [], "device": "cpu"})
    monkeypatch.setattr(ctc, "ctc_starts", lambda jobs, payload: {"1": 2060})
    events = []
    legacy = SimpleNamespace(RUNTIME_SETTINGS={}, record_run_event=lambda name, **values: events.append(name))
    receipts = ctc.apply_to_runtime_cues(cues, None, legacy, fps=fps)
    assert len(receipts) == 1 and events == ["ctc_start_refine"]
    assert cues[0].end == cues[1].start == round(2.044 * fps) / fps


def test_run_results_map_back_to_each_line():
    jobs = [dict(id="run-0", offsets=[["a", 0, 3], ["b", 3, 2]], text="あいうえお", window_start_ms=0, window_end_ms=10)]
    payload = {"results": [{"id": "run-0", "status": "aligned", "chars": [
        {"char": 0, "start_ms": 1010.4}, {"char": 1, "start_ms": 1100}, {"char": 3, "start_ms": 2040}]}]}
    assert ctc.ctc_starts(jobs, payload) == {"a": 1010, "b": 2040}


def test_worker_token_spans_split_repeated_labels_on_blanks():
    spec = importlib.util.spec_from_file_location("ctc_aligner_worker", ROOT / "ctc_aligner_worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    path = [0, 5, 5, 0, 5, 7, 7, 0]
    scores = [1, .5, .7, 1, .9, .4, .6, 1]
    spans = worker.token_spans(path, scores)
    assert [(a, b) for a, b, _s in spans] == [(1, 2), (4, 4), (5, 6)]
    assert spans[0][2] == pytest.approx(.6)
    ids, positions = worker.alignable("あ、x？ー", {"<unk>": 3, "あ": 9, "ー": 11})
    assert ids == [9, 3, 11] and positions == [0, 2, 4]


@pytest.mark.skipif(ctc.model_dir() is None, reason="CTC model not installed")
def test_real_worker_aligns_synthetic_job_without_touching_text():
    pcm = np.zeros(16000 * 3, dtype=np.float32)
    rng = np.random.default_rng(1)
    pcm[16000:32000] = rng.normal(0, 0.05, 16000).astype(np.float32)
    jobs = [dict(id="run-0", text="あいうえお", window_start_ms=0, window_end_ms=3000)]
    payload = ctc.run_worker(pcm, jobs)
    assert payload["protocol"] == ctc.PROTOCOL and payload["results"][0]["text"] == "あいうえお"
    assert payload["results"][0]["status"] in {"aligned", "path_mismatch", "window_too_short"}
