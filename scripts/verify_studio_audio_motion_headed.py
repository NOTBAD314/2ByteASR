"""Isolated real-media audit for Studio navigation, V2 and export geometry.

Reads the supplied fixture/media, but writes projects, preferences and evidence
only under tmp/studio-polish. Runs the actual Qt event loop between probes.
"""
from __future__ import annotations

import argparse
import cProfile
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import pstats
import sys
import time


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--theme", choices=("warm", "slate", "plum"), default="warm")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--baseline-playback", action="store_true")
    args = parser.parse_args()
    run = root / "tmp/studio-audio-motion" / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True)
    # Seed the FLV seek-index cache from the newest earlier run so this audit
    # measures the steady "already preloaded" state instead of re-copying 1.4GB.
    import shutil
    cache_rel = ("local", "2ByteASR", "cache", "media", "seek")
    for older in sorted((root / "tmp/studio-audio-motion").glob("*/"), reverse=True):
        src = older.joinpath(*cache_rel)
        if src.is_dir() and older.resolve() == run.resolve():
            continue
        if not any(p.joinpath("ready.json").is_file() for p in src.glob("*") if p.is_dir()):
            continue
        dst = run.joinpath(*cache_rel)
        dst.mkdir(parents=True, exist_ok=True)
        for entry in src.iterdir():
            if entry.is_dir() and entry.joinpath("ready.json").is_file():
                shutil.copytree(entry, dst / entry.name, dirs_exist_ok=True)
        break
    sys.path.insert(0, str(root))
    os.environ.update(LOCALAPPDATA=str(run / "local"), APPDATA=str(run / "roaming"),
                      QT_QPA_PLATFORM="windows", QT_SCALE_FACTOR="1",
                      DASHSCOPE_API_KEY="sk-local-test-dummy")
    os.environ["TWOBYTEASR_MPV"] = str(root / "tools/mpv/mpv.exe")
    from PySide6 import QtCore
    from PySide6.QtCore import QEventLoop, QSettings, QTimer, QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    class IsolatedSettings(QSettings):
        def __init__(self, *a, **kw):
            super().__init__(str(run / "qt.ini"), QSettings.Format.IniFormat)
    QtCore.QSettings = IsolatedSettings
    import twobyteasr
    if args.baseline_playback:
        twobyteasr.__path__.insert(0, str(root / "tmp/studio-audio-motion/baseline-modules"))
    from twobyteasr import settings, studio_project
    settings.stable_settings_root = lambda: run / "config"
    preferences = run / "studio-settings.json"
    preferences.write_text(json.dumps({"recent_projects": [], "studio_preferences": {
        "project_root": str(run / "projects"), "autosave_enabled": False,
        "auto_cover": False, "recovery_policy": "official"}}))
    studio_project.studio_settings_path = lambda: preferences
    studio_project.project_library_root = lambda: run / "projects"
    data = json.loads(args.project.read_text(encoding="utf-8-sig"))
    clip = data["video_tracks"][1]["clips"][0]
    entry = clip["timeline_in_ms"]
    clip["transform"].update(position_x=.457, position_y=.4721, scale_x=.885, scale_y=.885, rotation=1.25)
    data["report_path"] = ""
    data["original_outputs"] = {}
    data["studio_state"].update(playhead_ms=entry-1000, scroll_ms=entry-5000,
                                audio_master_mode="mix_all", audio_master_track_id="")
    data["studio_state"]["layout"].update(context_tab=3, context_visible=True,
                                          context_collapsed=False, upper_sizes=[0, 1500, 430])
    # Keep a realistic subtitle load so clock/timeline costs cannot hide behind
    # the single-cue fixture used by the decoder-only sync probe.
    data["cues"] = [dict(id=f"cue-{i}", start_ms=i*3000, end_ms=i*3000+2400,
                         text=f"字幕工作台 · 第 {i+1} 句", speaker_id="S00", style_id="default")
                    for i in range(min(1500, data["media"]["duration_ms"]//3000))]
    fixture = run / "fixture.2byteproj"
    fixture.write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
    import subtitle_core
    from twobyteasr.ui import MainWindow, _register_bundled_fonts, _app_font
    from twobyteasr.theme_manager import apply_theme
    app = QApplication([])
    _register_bundled_fonts(); app.setFont(_app_font()); apply_theme(args.theme, app)
    win = MainWindow([], subtitle_core, object(), None)
    win.show(); win.resize(1920, 1040)

    def settle(ms):
        loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

    def timed(action):
        start = time.perf_counter(); action()
        sync = (time.perf_counter()-start)*1000
        loop = QEventLoop(); QTimer.singleShot(0, loop.quit); loop.exec()
        return dict(sync_ms=round(sync, 2), ready_ms=round((time.perf_counter()-start)*1000, 2))

    settle(700); win.resize(1920, 1040); settle(250)
    win.grab().save(str(run / "home.png"))
    result = {"baseline_playback": args.baseline_playback, "theme": args.theme, "fixture": str(fixture), "navigation": {}}
    result["navigation"]["enter_studio"] = timed(win._open_subtitle_studio)
    settle(600)
    result["navigation"]["open_project"] = timed(lambda: win.open_studio_project(str(fixture), mode="edit", source="polish-audit"))
    page = win.studio_page
    settle(3000)
    assert page.video.controller is not None, "mpv must be attached before measuring playback"
    comp = page.video_compositor
    page._seek((entry-750)/1000); settle(350)
    page._video_clip_selected(data["video_tracks"][1]["id"], clip["id"])
    comp.reset_performance_samples()
    heartbeat = []; pubs = []; last = [time.perf_counter()]
    import threading as _threading
    wedge_log = run / "gil-probe.log"
    phase_marker = {"phase": "pre-play"}
    def probe_gil():
        t0 = time.perf_counter()
        t = _threading.Thread(target=lambda: None, daemon=True)
        t.start()
        t.join(timeout=1.0)
        if t.is_alive():
            with open(wedge_log, "a", encoding="utf8") as fh:
                fh.write(f"WEDGED phase={phase_marker['phase']} at={time.strftime('%H:%M:%S')}\n")
    timer = QTimer(); timer.setInterval(16); timer.setTimerType(Qt.TimerType.PreciseTimer)
    def beat():
        now = time.perf_counter(); heartbeat.append((now-last[0])*1000); last[0] = now
        if len(heartbeat) % 60 == 0:
            probe_gil()
    timer.timeout.connect(beat)
    original = page.video.publish_compositor_overlay
    def publish(slot, *a, **kw):
        value = original(slot, *a, **kw)
        if slot == 0:
            pubs.append((time.perf_counter(), page.timeline.playhead_ms,
                         [p.pts_ms for p in comp._players.values()]))
        return value
    page.video.publish_compositor_overlay = publish
    playheads = []
    set_playhead = page.timeline.set_playhead
    def record_playhead(value):
        playheads.append((time.perf_counter(), value))
        return set_playhead(value)
    page.timeline.set_playhead = record_playhead
    profiler = cProfile.Profile()
    timer.start()
    if args.profile: profiler.enable()
    phase_marker["phase"] = "playback"
    page._toggle_playback(); settle(8500)
    profiler.disable(); timer.stop()
    measured_playheads = list(playheads)
    page._toggle_playback(); settle(350)
    if args.profile:
        stream = io.StringIO(); pstats.Stats(profiler, stream=stream).sort_stats("cumtime").print_stats(65)
        (run / "profile.txt").write_text(stream.getvalue(), encoding="utf8")
    result["playback"] = comp.performance_snapshot()
    result["audio"] = page.audio_engine.telemetry_snapshot()
    result["heartbeat_p95_ms"] = sorted(heartbeat)[int(len(heartbeat)*.95)]
    result["heartbeat_max_ms"] = max(heartbeat)
    result["native_samples"] = pubs
    result["playhead_samples"] = measured_playheads
    gaps = sorted((b[0]-a[0])*1000 for a,b in zip(measured_playheads,measured_playheads[1:]))
    result["playhead_intervals"] = dict(count=len(gaps), p95=gaps[int(len(gaps)*.95)] if gaps else 0, max=max(gaps,default=0))
    # Exercise seeks with V2 already visible. Measure the newest requested
    # frame and actual PCM sink, including a burst which supersedes old work.
    phase_marker["phase"] = "seeks"
    result["seeks"] = []
    page._toggle_playback()
    for targets in ([entry+60000], [entry+3000], [entry+90000, entry+30000, entry+15000]):
        for target in targets[:-1]:
            page._seek(target/1000); settle(30)
        start = time.perf_counter()
        page._seek(targets[-1]/1000)
        observations = []
        for _ in range(100):
            settle(20)
            clock = page.video._playback_clock
            runtimes = list(comp._players.values())
            audio = page.audio_engine.telemetry_snapshot()
            observations.append(dict(elapsed_ms=(time.perf_counter()-start)*1000,
                pending=clock.exact_seek_pending, playhead=page.timeline.playhead_ms,
                frames=[dict(pts=p.pts_ms, requested=p.requested_ms, generation=p.generation,
                             image_generation=p._image_generation, visible=not p.image.isNull()) for p in runtimes],
                audio={k:audio.get(k) for k in ("state","source_generation","estimated_source_ms","drift_ms","sink_consumed_bytes","sink_consumed_rms","decode_lateness_ms")}))
        result["seeks"].append(dict(targets=targets, observations=observations))
    page._toggle_playback(); settle(100)
    page._video_clip_selected(data["video_tracks"][1]["id"], clip["id"])
    settle(350)
    win.grab().save(str(run / "studio.png"))
    page.context_drawer.grab().save(str(run / "video-panel.png"))
    page.timeline.grab().save(str(run / "timeline.png"))
    page.video.controller.screenshot_to_file(run / "studio-native.png")
    before = comp.geometry().getRect()
    expected_transform = asdict(page.project.video_tracks[1].clips[0].transform)
    phase_marker["phase"] = "export"
    probe_gil()
    result["navigation"]["enter_export"] = timed(page._open_render_dialog)
    settle(700)
    assert not comp._interaction_enabled and not comp._selected_clip_id
    assert not page.position_overlay.isVisible()
    assert page.video.rect().contains(comp.geometry()), (page.video.rect(), comp.geometry())
    assert abs(comp.width()/comp.height()-16/9) < .01
    # A mouse drag in export must not mutate the selected clip transform.
    QTest.mousePress(comp, Qt.MouseButton.LeftButton, pos=QPoint(comp.width()//2, comp.height()//2))
    QTest.mouseMove(comp, QPoint(comp.width()-5, comp.height()-5), delay=20)
    QTest.mouseRelease(comp, Qt.MouseButton.LeftButton, pos=QPoint(comp.width()-5, comp.height()-5))
    assert asdict(page.project.video_tracks[1].clips[0].transform) == expected_transform
    win.grab().save(str(run / "export.png"))
    page.video.controller.screenshot_to_file(run / "export-native.png")
    result["export_geometry"] = dict(editor=before, canvas=page.video.rect().getRect(),
                                      overlay=comp.geometry().getRect(), transform_unchanged=True)
    result["navigation"]["return_editor"] = timed(page._close_export_workspace)
    settle(500)
    assert comp._interaction_enabled and comp._selected_clip_id == clip["id"]
    assert page.video.parentWidget().layout().indexOf(page.video) >= 0
    assert page.video.rect().contains(comp.geometry())
    win.grab().save(str(run / "returned-editor.png"))
    result["completed"] = True
    (run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"native_samples", "playhead_samples", "seeks"}}, ensure_ascii=False), flush=True)
    phase_marker["phase"] = "close"
    probe_gil()
    page.close_page(); settle(300); win.hide()
    phase_marker["phase"] = "post-close"
    probe_gil()
    print("EVIDENCE", run, flush=True)


if __name__ == "__main__":
    main()
