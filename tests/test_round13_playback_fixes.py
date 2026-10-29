"""Round 13 (2026-09-02): three user-reported regressions.

1. AI web-theme completion left the design-draft card stuck on
   "正在生成网页视觉主题..." — _finish_ai_progress_bar referenced
   generation/stage from a different function (NameError aborted the slot
   before the card update and theme application).
2. Natural EOF black-screen: playhead == last clip out (half-open interval)
   resolved to "__gap__" → suspend_media_async → mpv ``stop`` → idle player
   rejected every later seek; same-path re-entry never reloaded.
3. 2-4x playhead judder: singleShot(20) vs 16ms source ticks beat
   (10/32ms intervals); replaced by a persistent 20ms flush timer.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QProgressBar, QPushButton

import pytest

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path) -> SubtitleProject:
    v1 = tmp_path / "v1.mp4"
    v1.write_bytes(b"v1")
    project = SubtitleProject(
        media=StudioMedia(path=str(v1), duration_ms=600_000, width=1920, height=1080),
        cues=[StudioCue("c1", 0, 3_200, "字幕")],
    )
    project.validate()
    project.video_tracks[0].locked = False
    project.validate()
    return project


# ---------------------------------------------------------------------------
# 1) AI completion slot must not NameError and must update the card
# ---------------------------------------------------------------------------

def test_web_theme_ready_routes_current_generation_to_validating_controller(tmp_path):
    from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin
    received=[]
    holder=SimpleNamespace(_ai_request_generation=7,_ai_request_active=True,
        _theme_drafts=lambda:SimpleNamespace(receive=lambda *args:received.append(args)))
    suggestion=SimpleNamespace(source='ai',theme={'name':'fixture'})
    StudioAIFlowMixin._ai_web_theme_ready(holder,6,'c1',suggestion)
    assert received==[]
    StudioAIFlowMixin._ai_web_theme_ready(holder,7,'c1',suggestion)
    assert received==[(7,'c1',suggestion)]
    # Ready UI and application belong to the controller's render gate.
    assert holder._ai_request_active is True


def test_stage_changed_records_design_stage_trace(tmp_path):
    _app()
    from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin

    holder = SimpleNamespace()
    holder._ai_stage_changed = StudioAIFlowMixin._ai_stage_changed.__get__(holder)
    holder._update_ai_progress_bar = StudioAIFlowMixin._update_ai_progress_bar.__get__(holder)
    holder.ai_confidence = QPushButton("conf")
    holder.ai_progress_bar = QProgressBar()
    holder._ai_generation_window = None
    holder._ai_request_generation = 3
    traces: list[tuple] = []
    holder._studio_trace = lambda event, **fields: traces.append((event, fields))

    holder._ai_stage_changed(3, "VALIDATING")

    assert ("AI_DESIGN_STAGE", {"generation": 3, "stage": "VALIDATING"}) in traces


# ---------------------------------------------------------------------------
# 2) EOF keeps the transport attached; gap re-entry rebinds
# ---------------------------------------------------------------------------

def _preview_page(tmp_path: Path):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    page.project = _project(tmp_path)
    return page


def test_natural_eof_keeps_mpv_attached(tmp_path):
    _app()
    page = _preview_page(tmp_path)
    suspends: list[bool] = []
    page.video.suspend_media_async = lambda: suspends.append(True) or True
    page.video._media_attached = True
    page._active_video_preview_key = "primary"

    end = page._activate_multitrack_preview(600_000)
    past = page._activate_multitrack_preview(605_000)

    assert end is None and past is None
    assert suspends == []  # the old code stopped mpv here → black + dead audio
    assert page._active_video_preview_key == "primary"  # seeks keep working


def test_true_gap_still_suspends(tmp_path):
    _app()
    from twobyteasr.timeline.studio_media_pool import add_media_asset, add_video_clip
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    project = _project(tmp_path)
    v2 = tmp_path / "v2.mp4"
    v2.write_bytes(b"v2")
    asset = add_media_asset(project, v2, fingerprint="v2", duration_ms=100_000)
    # Hole: V1 [0, 300s) ... V-clip [500s, 600s); playhead 450s is a real gap.
    from twobyteasr.timeline.studio_media_pool import trim_video_clip_edges
    trim_video_clip_edges(project,"V1",project.video_tracks[0].clips[0].id,timeline_out_ms=300_000)
    from twobyteasr.timeline.studio_media_pool import create_video_track

    track = create_video_track(project)
    add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=500_000)
    # No validate() here: it would re-sync V1 from the EditSequence and
    # restore the pre-shrink clip extent.
    page.project = project

    suspends: list[bool] = []
    page.video.suspend_media_async = lambda: suspends.append(True) or True
    page.video._media_attached = True
    page._active_video_preview_key = "primary"

    assert page._activate_multitrack_preview(450_000) is None
    assert suspends == [True]
    assert page._active_video_preview_key == "__gap__"


def test_gap_reentry_rebinds_same_path_after_suspend(tmp_path):
    _app()
    page = _preview_page(tmp_path)
    media = Path(page.project.media.path).resolve()
    page.video._media_path = str(media)
    page.video._media_attached = False  # what suspend leaves behind
    page._active_video_preview_key = "__gap__"
    rebinds: list[tuple] = []
    page.video.switch_media_at_async = (
        lambda *a, **k: rebinds.append(a) or True
    )

    result = page._activate_multitrack_preview(120_000)

    assert result is not None
    assert len(rebinds) == 1  # same path but detached → must loadfile again
    assert page._active_video_preview_key != "__gap__"


# ---------------------------------------------------------------------------
# 3) Playhead flush timer: persistent, steady, self-disarming
# ---------------------------------------------------------------------------

def test_position_changed_uses_persistent_flush_timer(tmp_path):
    _app()
    page = _preview_page(tmp_path)
    applied: list[int] = []
    page._apply_project_playhead = (
        lambda ms, *, defer_follow=False: applied.append(ms)
    )
    page.video._paused = False

    page._position_changed(1.0)
    timer = getattr(page, "_playhead_flush_timer", None)
    assert timer is not None and timer.isActive() and timer.interval() == 16
    assert applied == []  # throttled: queued, not applied synchronously
    assert page._playhead_ui_pending == (1.0, False)

    page._position_changed(1.5)  # newer sample replaces the queued one
    assert page._playhead_ui_pending == (1.5, False)

    page.video._playback_clock.sample_presentation=lambda **_:SimpleNamespace(presentation_media_ms=1600)
    page._flush_pending_playhead()
    assert applied == [1_600]
    assert page._playhead_ui_pending is None

    page._flush_pending_playhead()  # nothing new → disarm
    assert not timer.isActive()
    assert applied == [1_600]

    # Paused updates bypass the throttle entirely and cancel stale pending.
    page.video._paused = True
    page._position_changed(2.0)
    assert applied == [1_600, 2_000]
    assert page._playhead_ui_pending is None


def test_flush_timer_cadence_documented():
    """Wall-clock cadence is verified by tmp/verify_playhead_cadence.py and
    scripts/verify_round14_web_theme_headed.py (measured 50Hz / stdev 0.9ms).
    An in-suite timing test starves when earlier tests leave Chromium/renderer
    threads running in-process, so it is intentionally not repeated here."""
