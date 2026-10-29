"""The cue list summary and priority filter read the review risks once per pass.

2026-10-10 performance round 2: every edit's deferred refresh looked up each
cue's review level through ``cached_review_risks``, which copies the whole
risk table and rebuilds the set of cue ids, so one refresh was O(n^2)
(~0.5 s after every edit or drag at 3000 cues).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.studio import studio_cue_table
from twobyteasr.subtitle_rules import studio_review
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def _app():
    return QApplication.instance() or QApplication([])


def _page(tmp_path, monkeypatch, count=120):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=count * 2000),
        cues=[StudioCue(f"c{i}", i * 2000, i * 2000 + 1500, f"第{i}句", speaker_id="S01") for i in range(count)],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *a, **k: None)
    page.open_project(save_project(project, tmp_path / "studio.2byteproj"))
    _app().processEvents()
    levels = {0: "suggested", 1: "high", 2: "confident"}
    page.project._review_risks_cache = {
        cue.id: {"level": levels[index % 3], "score": 10 * (index % 3), "reasons": []}
        for index, cue in enumerate(page.project.cues)}
    return page


def _count_risk_builds(monkeypatch):
    calls = []
    original = studio_review.cached_review_risks

    def counting(project):
        calls.append(1)
        return original(project)
    monkeypatch.setattr(studio_review, "cached_review_risks", counting)
    monkeypatch.setattr(studio_cue_table, "cached_review_risks", counting)
    return calls


def test_summary_counts_unchanged_with_one_risk_build(tmp_path, monkeypatch):
    _app()
    page = _page(tmp_path, monkeypatch)
    calls = _count_risk_builds(monkeypatch)
    page._refresh_cue_list_summary()
    assert len(calls) == 1
    assert page.cue_filter_buttons["priority"].text().endswith(" 40")
    page.close_page()
    page.deleteLater()


def test_priority_filter_rows_unchanged_with_one_risk_build(tmp_path, monkeypatch):
    _app()
    page = _page(tmp_path, monkeypatch)
    calls = _count_risk_builds(monkeypatch)
    model = page.cue_model
    model.filter_status = "priority"
    model._rebuild_rows()
    assert len(calls) == 1
    assert len(model._rows) == 80  # suggested + high, not confident
    page.close_page()
    page.deleteLater()
