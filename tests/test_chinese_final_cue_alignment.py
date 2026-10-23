"""Chinese captions aligned with their final text when the timeline is a forced aligner (2026-10-22)."""
from types import SimpleNamespace

import numpy as np
import pytest

import subtitle_core  # noqa: F401  (legacy core first: segmentation star-imports it)

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.recognition import asr, timing_evidence
from twobyteasr.recognition.cue_forced_alignment import (CUE_ALIGNMENT_PREFIX, align_final_cues,
                                                         attach_project_evidence, chinese_final_alignment)
from twobyteasr.recognition.cue_word_alignment import cue_words


def test_only_chinese_tasks_with_an_aligner_timeline_align_their_captions():
    for backend in ("mfa_aligner", "qwen_aligner", "mlx_qwen_aligner"):
        assert chinese_final_alignment("zh", backend)
    for backend in ("local", "paraformer", "whisper_turbo", "off", ""):
        assert not chinese_final_alignment("zh", backend)
    assert not chinese_final_alignment("ja", "mfa_aligner")  # Japanese has its own (unconditional) branch


def _piece(a, b, start, end):
    return {"char_start": a, "char_end": b, "start_ms": start, "end_ms": end, "granularity": "word",
            "start_basis": "model", "end_basis": "model"}


@pytest.fixture
def aligned(monkeypatch, tmp_path):
    """Two adjacent captions of one speaker, aligned by a stand-in MFA worker."""
    cues = [SimpleNamespace(start=10.0, end=12.0, speaker="S01", text="看开头这个路面"),
            SimpleNamespace(start=12.0, end=13.5, speaker="S01", text="画面很好看")]
    jobs_seen, events = [], []

    def worker(audio, jobs, engine=None):
        jobs_seen.append((engine, jobs))
        # run text "看开头这个路面 画面很好看": the second caption starts at index 8
        if engine == "qwen3":  # the second opinion: agrees except on the second line's start
            protocol, model = "qwen-aligner-units-v1", "Qwen/Qwen3-ForcedAligner-0.6B"
            pieces = [_piece(0, 3, 10120, 10610), _piece(3, 7, 10610, 11880),
                      _piece(8, 10, 12300, 12520), _piece(10, 13, 12520, 13380)]
        else:
            protocol, model = "mfa-aligner-units-v1", "MontrealCorpusTools/mandarin_mfa (MFA 3.4.3 models)"
            pieces = [_piece(0, 3, 10100, 10600), _piece(3, 7, 10600, 11900),
                      _piece(8, 10, 12050, 12500), _piece(10, 13, 12500, 13400)]
        return {"protocol": protocol, "model": model,
                "results": [{"id": job["id"], "text": job["text"], "language": job["language"], "status": "aligned",
                             "window_start_ms": job["window_start_ms"], "window_end_ms": job["window_end_ms"],
                             "segments": pieces} for job in jobs]}

    monkeypatch.setattr(asr, "run_qwen_aligner_worker", worker)
    legacy = SimpleNamespace(add_review_item=lambda *a, **k: None,
                             record_run_event=lambda event, **data: events.append((event, data)))
    attached = align_final_cues(cues, np.zeros(16000 * 15, np.float32), legacy, language="Chinese",
                                evidence_dir=tmp_path / "timing-evidence")
    return SimpleNamespace(cues=cues, jobs=jobs_seen, events=events, attached=attached, folder=tmp_path / "timing-evidence")


def test_adjacent_chinese_captions_are_aligned_as_one_run(aligned):
    assert aligned.attached == 2
    (first_engine, jobs), (second_engine, again) = aligned.jobs
    assert [(j["text"], j["language"], j["window_start_ms"], j["window_end_ms"]) for j in jobs] == [
        ("看开头这个路面 画面很好看", "Chinese", 9700, 13800)]
    assert (first_engine, second_engine, again) == (None, "qwen3", jobs)  # Qwen3 re-checks MFA's cuts
    second = aligned.cues[1].forced_alignment
    assert second["text"] == "画面很好看" and second["segments"][0]["start_ms"] == 12050
    assert second["segments"][0]["start_basis"] == "model"  # the cut between the two lines is measured
    record = timing_evidence.load_receipt(aligned.folder / "final_cues-chinese-mfa.json.gz")
    assert record["stage"] == "final_cues" and record["runs"][0]["members"] == [1, 2]
    alignment_event = next(data for event, data in aligned.events if event == "forced_alignment")
    assert alignment_event["evidence"].endswith("final_cues-chinese-mfa.json.gz")
    assert timing_evidence.load_receipt(aligned.folder / "final_cues-chinese-qwen3.json.gz")["engine"] == "qwen3"


def test_second_opinion_runs_beside_the_first_aligner(monkeypatch, tmp_path):
    # 2026-10-22: Qwen3 checked MFA's cuts only after MFA finished (22 s of a 491 s task).
    import threading
    from twobyteasr.recognition import cue_forced_alignment, mfa_aligner
    cues = [SimpleNamespace(start=10.0, end=12.0, speaker="S01", text="看开头这个路面"),
            SimpleNamespace(start=12.0, end=13.5, speaker="S01", text="画面很好看")]
    second_started, events = threading.Event(), []

    def worker(audio, jobs, engine=None):
        if engine == "qwen3":
            second_started.set()
            protocol, model = "qwen-aligner-units-v1", "Qwen/Qwen3-ForcedAligner-0.6B"
        else:
            assert second_started.wait(5), "the second opinion waited for the first aligner"
            protocol, model = "mfa-aligner-units-v1", "MontrealCorpusTools/mandarin_mfa (MFA 3.4.3 models)"
        pieces = [_piece(0, 3, 10100, 10600), _piece(3, 7, 10600, 11900),
                  _piece(8, 10, 12050, 12500), _piece(10, 13, 12500, 13400)]
        return {"protocol": protocol, "model": model,
                "results": [{"id": job["id"], "text": job["text"], "language": job["language"], "status": "aligned",
                             "window_start_ms": job["window_start_ms"], "window_end_ms": job["window_end_ms"],
                             "segments": pieces} for job in jobs]}

    monkeypatch.setattr(asr, "run_qwen_aligner_worker", worker)
    monkeypatch.setattr(mfa_aligner, "handles", lambda jobs: True)
    monkeypatch.setattr(cue_forced_alignment, "_predicted_second_engine", lambda jobs: "qwen3")
    legacy = SimpleNamespace(add_review_item=lambda *a, **k: None,
                             record_run_event=lambda event, **data: events.append((event, data)))
    attached = align_final_cues(cues, np.zeros(16000 * 15, np.float32), legacy, language="Chinese",
                                evidence_dir=tmp_path / "timing-evidence")
    assert attached == 2
    opinion = next(data for event, data in events if event == "boundary_second_opinion")
    assert opinion["engine"] == "qwen3" and opinion["model"] == "Qwen/Qwen3-ForcedAligner-0.6B"
    assert cues[0].forced_alignment["second"]["engine"] == "qwen3"


def test_every_cut_position_is_graded_with_the_second_aligner(aligned):
    first, second = (cue.forced_alignment["boundaries"] for cue in aligned.cues)
    assert [(r["pos"], r["grade"], r["reason"]) for r in first] == [
        (0, "independent", "second_aligner"), (1, "whole", "inside_unit"), (2, "whole", "inside_unit"),
        (3, "independent", "second_aligner"), (4, "whole", "inside_unit"), (5, "whole", "inside_unit"),
        (6, "whole", "inside_unit"), (7, "independent", "second_aligner")]
    # 画面|很好看: the cut inside the line is confirmed; the line start is 250 ms apart (silent audio: no pause).
    assert [(r["pos"], r["grade"], r["reason"], r.get("delta_ms")) for r in second if r["grade"] != "whole"] == [
        (0, "unreliable", "aligners_disagree", 250), (2, "independent", "second_aligner", 20),
        (5, "independent", "second_aligner", 20)]
    assert aligned.cues[1].forced_alignment["second"]["engine"] == "qwen3"
    assert aligned.events[-1][0] == "boundary_grades" and aligned.events[-1][1]["independent"] == 5


def test_traditional_delivery_keeps_the_caption_alignment(aligned):
    # 繁體 is converted after alignment, character for character.
    project = SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=20000), cues=[
        StudioCue("1", 10000, 12000, "看開頭這個路面", speaker_id="S01"),
        StudioCue("2", 12000, 13500, "畫面很好看", speaker_id="S01")])
    assert attach_project_evidence(project, aligned.cues) == 2
    row = project.asr_evidence[CUE_ALIGNMENT_PREFIX + "2"]
    assert row["text"] == "畫面很好看" and row["words"][0] == {"text": "畫面", "start_ms": 12050, "end_ms": 12500}
    assert row["final_timing_owner"] == "Montreal-Forced-Aligner" and row["caption_arbitration"]["acoustic_words"][0]["model"] == "mfa_aligner"
    assert row["cue_alignment"]["script_remapped"] is True and row["cue_alignment"]["aligned_text"] == "画面很好看"
    words, reason = cue_words(project, project.cues[1])
    assert reason == "exact_token_text" and [(w.text, w.start_ms) for w in words] == [("畫面", 12050), ("很好看", 12500)]
    from twobyteasr.recognition.boundary_grades import caption_boundaries
    rows, policy = caption_boundaries(project, project.cues[1])
    assert policy == "boundary-grades-v1" and [(r["pos"], r["grade"]) for r in rows if r["grade"] != "whole"] == [
        (0, "unreliable"), (2, "independent"), (5, "independent")]
    project.cues[1].text = "畫面真好看"
    assert caption_boundaries(project, project.cues[1]) == ([], "text_changed")


def test_other_text_changes_still_drop_the_alignment(aligned):
    project = SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=20000), cues=[
        StudioCue("1", 10000, 12000, "看开头这个路面", speaker_id="S01"),
        StudioCue("2", 12000, 13500, "画面真好看", speaker_id="S01")])
    assert attach_project_evidence(project, aligned.cues) == 1
    assert CUE_ALIGNMENT_PREFIX + "2" not in project.asr_evidence


def test_pauses_confirm_boundaries_the_other_aligner_did_not_measure():
    from twobyteasr.recognition.boundary_grades import grade_caption
    primary = [_piece(0, 2, 1000, 1400), _piece(2, 4, 1600, 2000)]
    second = [{**_piece(0, 4, 1010, 1990)}]  # the other aligner kept the line whole
    rows = grade_caption("画面好看", primary, second, lambda a, b, side: (1400, 1600) if side == "gap" else None)
    assert [(r["pos"], r["grade"], r["reason"]) for r in rows] == [
        (0, "independent", "second_aligner"), (1, "whole", "inside_unit"), (2, "independent", "pause"),
        (3, "whole", "inside_unit"), (4, "independent", "second_aligner")]
    unconfirmed = grade_caption("画面好看", primary, None, lambda a, b, side: None)
    assert [r["reason"] for r in unconfirmed if r["grade"] != "whole"] == ["unconfirmed"] * 3
    edge = [dict(_piece(0, 2, 1000, 1400), start_basis="window_edge"), _piece(2, 4, 1600, 2000)]
    assert grade_caption("画面好看", edge)[0] == {"pos": 0, "at_ms": [1000, 1000], "grade": "unreliable",
                                               "reason": "unmeasured:window_edge"}


def test_speech_band_pauses_on_a_synthetic_track():
    from twobyteasr.recognition.boundary_grades import SpeechBand
    rng = np.random.default_rng(7)
    pcm = rng.normal(0, 0.2, 16000 * 3).astype(np.float32)   # "speech" everywhere ...
    pcm[16000:int(16000 * 1.3)] *= 0.001                     # ... except a 300 ms pause at 1.0-1.3 s
    band = SpeechBand(pcm)
    assert band.pause(1300, 1300, "start") and band.pause(1000, 1000, "end") and band.pause(1100, 1200, "gap")
    assert band.pause(600, 600, "gap") is None and band.pause(1000, 1000, "start") is None


# ── split at a text position (2026-10-22, MFA plan step 4) ──────────────────

def _graded_project(aligned):
    project = SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=20000), cues=[
        StudioCue("1", 10000, 12000, "看开头这个路面", speaker_id="S01"),
        StudioCue("2", 12000, 13500, "画面很好看", speaker_id="S01")])
    attach_project_evidence(project, aligned.cues)
    return project


def test_an_independent_position_is_cut_at_its_acoustic_boundary(aligned):
    from twobyteasr.timeline.text_split import plan_text_split
    project = _graded_project(aligned)
    plan = plan_text_split(project, project.cues[0], 3)
    assert (plan.grade, plan.split_ms, plan.left_text, plan.right_text) == ("independent", 10600, "看开头", "这个路面")
    assert plan_text_split(project, project.cues[0], 0).grade == "blocked"
    assert plan_text_split(project, project.cues[0], 7).grade == "blocked"


def test_inside_a_word_offers_the_nearest_independent_cut(aligned):
    from twobyteasr.timeline.text_split import plan_text_split
    project = _graded_project(aligned)
    plan = plan_text_split(project, project.cues[0], 5)
    assert (plan.grade, plan.reason) == ("whole", "inside_unit")
    assert [(c.kind, c.position, c.split_ms) for c in plan.choices] == [("cut", 3, 10600)]


def test_an_unreliable_position_offers_realignment_first(aligned):
    from twobyteasr.timeline.text_split import plan_text_split
    project = _graded_project(aligned)
    row = project.asr_evidence[CUE_ALIGNMENT_PREFIX + "2"]["caption_arbitration"]["forced_alignment"]
    for item in row["boundaries"]:
        if item["pos"] == 2:
            item.update(grade="unreliable", reason="aligners_disagree")
    plan = plan_text_split(project, project.cues[1], 2)
    assert (plan.grade, plan.reason) == ("unreliable", "aligners_disagree")
    assert [(c.kind, c.split_ms) for c in plan.choices] == [("realign", 0), ("estimate", 12500)]


def test_a_caption_split_from_a_graded_one_reads_its_slice(aligned):
    from twobyteasr.recognition.boundary_grades import caption_boundaries
    from twobyteasr.timeline.text_split import plan_text_split
    project = _graded_project(aligned)
    right = StudioCue("1-split-a", 10600, 12000, "这个路面", speaker_id="S01",
                      evidence_refs=list(project.cues[0].evidence_refs))
    rows, source = caption_boundaries(project, right)
    assert source == "evidence_slice" and [(r["pos"], r["grade"]) for r in rows if r["grade"] != "whole"] == [
        (0, "independent"), (4, "independent")]
    assert plan_text_split(project, right, 2).grade == "whole"


def test_split_receipts_keep_a_slice_of_their_parents_grades():
    from twobyteasr.timeline.studio_caption_timeline import KEY, caption_replacement_receipts
    parent = StudioCue("1", 10000, 12000, "看开头这个路面", speaker_id="S01")
    project = SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=20000), cues=[parent])
    project.render_settings["_cue_domain"] = "timeline"
    graded = [{"pos": 0, "grade": "independent"}, {"pos": 3, "grade": "independent"},
              {"pos": 5, "grade": "unreliable"}, {"pos": 7, "grade": "independent"}]
    project.studio_state[KEY] = {"version": 1, "instances": {"1": {"text": parent.text, "words": [],
                                                                   "boundaries": graded}}}
    left = StudioCue("1", 10000, 10600, "看开头", speaker_id="S01")
    right = StudioCue("1-split-b", 10600, 12000, "这个路面", speaker_id="S01")
    _before, after = caption_replacement_receipts(project, [parent], [left, right])
    assert [(r["pos"], r["grade"]) for r in after["1"]["boundaries"]] == [(0, "independent"), (3, "independent")]
    assert [(r["pos"], r["grade"]) for r in after["1-split-b"]["boundaries"]] == [
        (0, "independent"), (2, "unreliable"), (4, "independent")]
    merged = StudioCue("1", 10000, 12000, "看开头这个路面呀", speaker_id="S01")
    _before, after = caption_replacement_receipts(project, [parent], [merged])
    assert "boundaries" not in after["1"]


def test_words_of_a_studio_realignment_are_read_back():
    """2026-10-22: 'realign:' words were rejected as a missing source, so re-aligned captions lost their words."""
    from twobyteasr.recognition.cue_word_alignment import cue_words
    from twobyteasr.timeline.studio_caption_timeline import KEY
    cue = StudioCue("2", 1933, 3183, "也能感觉", speaker_id="S01")
    project = SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=20000), cues=[cue])
    project.render_settings["_cue_domain"] = "timeline"
    words = [{"text": t, "char_start": i, "char_end": i + 1, "start_ms": a, "end_ms": b, "evidence_ref": "realign:2"}
             for i, (t, a, b) in enumerate((("也", 1940, 2040), ("能", 2040, 2210), ("感", 2210, 2380), ("觉", 2380, 2460)))]
    project.studio_state[KEY] = {"version": 1, "instances": {"2": {
        "text": cue.text, "words": words, "word_alignment": "exact_token_text", "acoustic_word_observation": True}}}
    found, reason = cue_words(project, cue)
    assert reason == "exact_token_text" and [w.start_ms for w in found] == [1940, 2040, 2210, 2380]


# ── acoustic time apart from display time; every timing step kept (2026-10-22, MFA plan step 5) ──

def test_acoustic_span_reads_measured_words_and_their_edge_grades(aligned):
    from twobyteasr.timeline.acoustic_span import acoustic_span
    project = _graded_project(aligned)
    first, second = (acoustic_span(project, cue) for cue in project.cues)
    assert (first.start_ms, first.end_ms, first.confirmed) == (10100, 11900, True)
    assert (second.start_ms, second.start_grade, second.confirmed) == (12050, "unreliable", False)
    bare = StudioCue("9", 0, 900, "没有证据", speaker_id="S01")
    assert acoustic_span(project, bare) is None


def test_the_timeline_offers_the_acoustic_span_of_a_caption(aligned):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    app = QApplication.instance() or QApplication([])
    timeline = WaveformTimeline()
    timeline.resize(1200, 300)
    project = _graded_project(aligned)
    timeline.set_project(project)
    span = timeline.acoustic_span_of(project.cues[0])
    assert span is not None and span.confirmed
    timeline.grab()  # paints the line without errors
    assert app is not None


def test_timing_ledger_records_each_step_and_the_acoustic_spans(aligned, tmp_path):
    import gzip
    import json
    from twobyteasr.recognition.timing_ledger import TimingLedger
    ledger = TimingLedger()
    ledger.checkpoint("formed", aligned.cues, reason="captions")
    aligned.cues[1].start = 12.05
    aligned.cues[0].end = 12.05
    ledger.checkpoint("pause_snap", aligned.cues, reason="cuts", receipts=[{"left": "1", "right": "2"}])
    ledger.acoustic(aligned.cues)
    formed, snap, acoustic = ledger.stages
    assert formed["snapshot"][1][:3] == [2, 12000, 13500]
    assert snap["changed"] == 2 and snap["changes"][1] == {"cue": 2, "text": "画面很好看", "before": [12000, 13500],
                                                         "after": [12050, 13500]}
    assert acoustic["rows"][1]["acoustic"] == [12050, 13400] and acoustic["rows"][1]["grades"] == ["unreliable", "independent"]
    path = ledger.save(tmp_path, job_id="abcdef123456")
    assert json.loads(gzip.decompress(open(path, "rb").read()))["stages"][1]["stage"] == "pause_snap"


def test_manual_timing_edits_are_appended_to_a_journal_outside_the_project(tmp_path):
    import json
    from types import SimpleNamespace as NS
    from twobyteasr.projects.timing_journal import TimingJournal, journal_path
    project = SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=20000), cues=[
        StudioCue("1", 10000, 12000, "看开头这个路面", speaker_id="S01")])
    path = tmp_path / "demo.2byteproj"
    journal = TimingJournal(project, lambda: path)
    project.cues[0].end_ms = 10600
    project.cues.append(StudioCue("1-split-x", 10600, 12000, "这个路面", speaker_id="S01"))
    journal.consume(NS(affected_cue_ids=frozenset({"1", "1-split-x"}), revision=3, action_id="split_subtitle"))
    journal.consume(NS(affected_cue_ids=frozenset({"1"}), revision=4, action_id="edit_text"))  # nothing moved
    rows = [json.loads(line) for line in journal_path(path).read_text("utf-8").splitlines()]
    assert [(r["cue"], r["before"], r["after"], r["action"]) for r in rows] == [
        ("1", [10000, 12000], [10000, 10600], "split_subtitle"), ("1-split-x", None, [10600, 12000], "split_subtitle")]
    assert not path.exists() and journal_path(path).parent.name == "timing-journal"


def test_the_journal_notices_a_caption_removed_by_an_undone_split(tmp_path):
    import json
    from types import SimpleNamespace as NS
    from twobyteasr.projects.timing_journal import TimingJournal, journal_path
    project = SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=20000), cues=[
        StudioCue("1", 10000, 10600, "看开头", speaker_id="S01"), StudioCue("1-split-x", 10600, 12000, "这个路面", speaker_id="S01")])
    path = tmp_path / "demo.2byteproj"
    journal = TimingJournal(project, lambda: path)
    project.cues = [StudioCue("1", 10000, 12000, "看开头这个路面", speaker_id="S01")]
    journal.consume(NS(affected_cue_ids=frozenset({"1"}), revision=9, action_id="split_subtitle"))
    rows = [json.loads(line) for line in journal_path(path).read_text("utf-8").splitlines()]
    assert [(r["cue"], r["before"], r["after"]) for r in rows] == [
        ("1", [10000, 10600], [10000, 12000]), ("1-split-x", [10600, 12000], None)]


def test_moving_a_caption_display_time_leaves_its_acoustic_span(aligned):
    import copy
    from twobyteasr.timeline.acoustic_span import acoustic_span
    project = _graded_project(aligned)
    evidence = copy.deepcopy(project.asr_evidence)
    before = acoustic_span(project, project.cues[0])
    project.cues[0].start_ms, project.cues[0].end_ms = 9800, 12300   # a reading lead-in and a longer tail
    assert acoustic_span(project, project.cues[0]) == before and project.asr_evidence == evidence
