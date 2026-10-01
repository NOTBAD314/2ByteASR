"""Isolated real Studio/ffmpeg/headed evidence; no user project is loaded."""
def main():
    import json, os, sys, time
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    run = root / "tmp/pipeline-headed" / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True)
    sys.path.insert(0, str(root))
    os.environ.update(LOCALAPPDATA=str(run / "local"), APPDATA=str(run / "roaming"),
                      QT_QPA_PLATFORM="windows", QT_SCALE_FACTOR="1", DASHSCOPE_API_KEY="sk-local-test-dummy")
    from PySide6 import QtCore
    from PySide6.QtCore import QSettings, Qt
    class IsolatedSettings(QSettings):
        def __init__(self, *a, **kw):
            super().__init__(str(run / "qt.ini"), QSettings.Format.IniFormat)
    QtCore.QSettings = IsolatedSettings
    from twobyteasr import settings, studio_project
    settings.stable_settings_root = lambda: run / "config"
    config = run / "studio-settings.json"
    config.write_text(json.dumps({"recent_projects": [], "project_root": str(run / "projects"),
        "studio_preferences": {"autosave_enabled": False, "auto_cover": False, "recovery_policy": "official"}}))
    studio_project.studio_settings_path = lambda *a: config
    studio_project.project_library_root = lambda *a: run / "projects"
    from twobyteasr.processes import run_hidden_subprocess
    ffmpeg = root / "tools/ffmpeg/bin/ffmpeg.exe"
    sources = []
    for i, vf in enumerate(("testsrc2=size=1920x1080:rate=60:duration=12",
                             "color=lime:s=640x360:r=60:d=12,drawbox=x=180:y=80:w=280:h=200:color=red:t=fill",
                             "testsrc2=size=640x360:rate=60:duration=12")):
        path = run / f"source-{i}.mp4"
        run_hidden_subprocess([str(ffmpeg), "-v", "error", "-y", "-f", "lavfi", "-i", vf,
                               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", str(path)],
                              purpose="isolated headed fixture", check=True, timeout=60)
        sources.append(path)
    from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue, VideoTransform, save_project
    from twobyteasr.studio_media_pool import add_media_asset, create_video_track, add_video_clip
    project = SubtitleProject(media=StudioMedia(path=str(sources[0]), duration_ms=12000, width=1920, height=1080),
                              cues=[StudioCue("cue", 0, 12000, "三轨合成 · 播放与导出验证")])
    project.validate()
    for i in (1, 2):
        asset = add_media_asset(project, sources[i], duration_ms=12000,
                                video_metadata={"has_video": True, "width": 640, "height": 360, "fps": 60},
                                audio_metadata={"has_audio": False})
        track = create_video_track(project)
        clip = add_video_clip(project, track.id, asset.asset_id, source_out_ms=10000)
        clip.transform = VideoTransform(position_x=.28 if i == 1 else .75, position_y=.4,
                                        scale_x=.42, scale_y=.42)
        if i == 1:
            clip.effects = {"chromaKey": {"enabled": True, "color": "#00FF00", "similarity": .1, "smoothness": .1}}
    fixture = save_project(project, run / "fixture.2byteproj")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    import subtitle_core
    from twobyteasr.ui import MainWindow, _register_bundled_fonts, _app_font
    from twobyteasr.theme_manager import apply_theme
    from twobyteasr.studio_theme import build_studio_qss
    from twobyteasr.studio_performance import performance_snapshot
    app = QApplication([])
    _register_bundled_fonts()
    app.setFont(_app_font())
    apply_theme("slate", app)
    win = MainWindow([], subtitle_core, object(), None)
    win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    win.show()
    def settle(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.005)
    def wait_for(predicate, seconds=8):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            settle(.02)
            if predicate(): return
        raise AssertionError("headed state did not converge")
    def shot(widget, name):
        widget.raise_(); widget.activateWindow(); settle(.15)
        widget.grab().save(str(run / f"{name}-qt.png"))
        rect = widget.frameGeometry()
        widget.screen().grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height()).save(str(run / f"{name}-screen.png"))
    settle(.5)
    win.resize(1600, 960)
    win.open_studio_project(str(fixture), mode="edit", source="pipeline-validation")
    page = win.studio_page
    page._queue_advanced_preview_job = lambda *a, **kw: None
    comp = page.video_compositor
    page._seek(2.)
    wait_for(lambda: len(comp._players) >= 2 and all(not p.image.isNull() for p in comp._players.values()))
    results = {"runtime": "headed-source", "real_user_click": False, "samples": [], "checks": {}}
    results["checks"]["all_decoders_processes"] = all(p.performance_snapshot()["pid"] for p in comp._players.values())
    shot(win, "three-tracks-paused")
    page.video.controller.screenshot_to_file(run / "three-tracks-mpv.png")
    for rate in (1., 2.):
        page._seek(2.)
        page._set_speed(rate)
        settle(.4)
        comp.reset_performance_samples()
        page._toggle_playback()
        settle(2.5)
        results["samples"].append(performance_snapshot(page))
        shot(win, f"playing-{rate:g}x")
        page._toggle_playback()
    for target in (6., 1.):
        started = time.monotonic()
        page._seek(target)
        wait_for(lambda: all(abs(p.pts_ms-target*1000) < 75 for p in comp._players.values()))
        results["samples"].append({"seek_seconds": target, "settle_ms": (time.monotonic()-started)*1000})
    overlay = page.project.video_tracks[2].clips[0]
    overlay.effects = {"blendMode": "multiply"}
    page._sync_video_compositor(1000)
    wait_for(lambda: comp._composes_base and len(comp._layers) == 3 and all(not p.image.isNull() for p in comp._players.values()))
    results["checks"]["blend_includes_base"] = True
    page._video_clip_selected(page.project.video_tracks[2].id, overlay.id)
    for theme in ("warm", "slate", "plum", "lavender"):
        from twobyteasr.ui_theme import theme_definition
        # Registry returns canonical keys; reject a typo in the harness.
        definition = theme_definition(theme)
        apply_theme(definition.key, app)
        page.setStyleSheet(build_studio_qss(definition))
        settle(.2)
        shot(win, f"theme-{definition.key}")
    page.setFocus()
    QTest.keyClick(page, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    wait_for(lambda: page._performance_dialog is not None and page._performance_dialog.isVisible())
    dialog = page._performance_dialog
    dialog.copy_snapshot()
    copied = json.loads(app.clipboard().text())
    results["checks"]["diagnostics_shortcut_copy"] = bool(copied["clock"] and copied["decoders"])
    shot(dialog, "performance")
    dialog.close()
    results["checks"]["diagnostics_stops_hidden"] = not dialog.timer.isActive()
    page._seek(11.)
    settle(.4)
    results["checks"]["overlay_tail_clears"] = not comp.has_video_overlays
    page._seek(2.)
    settle(.4)
    pids = [p.performance_snapshot()["pid"] for p in comp._players.values()]
    start = time.monotonic()
    page.close_page()
    settle(.2)
    results["close_ms"] = (time.monotonic()-start)*1000
    import psutil
    results["checks"]["children_reaped"] = all(not pid or not psutil.pid_exists(pid) for pid in pids)
    results["checks"]["native_overlays_cleared"] = not page.video.active_compositor_overlay_ids()
    (run / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EVIDENCE", run, flush=True)
    print(json.dumps(results, ensure_ascii=False), flush=True)
    win.hide()
    assert all(results["checks"].values()), results["checks"]


if __name__ == "__main__":
    main()


