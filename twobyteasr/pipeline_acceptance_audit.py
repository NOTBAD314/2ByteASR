"""Fixed, opt-in frozen acceptance sequence inside the existing audit sandbox."""
from __future__ import annotations
import json
import sys
import threading
import time


def start_pipeline_acceptance(window, output):
    from PySide6.QtCore import QObject, QTimer
    from .build_identity import load_build_identity
    from .studio_performance import performance_snapshot

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.start = time.monotonic()
            self.phase = "waiting"
            self.samples = []
            self.results = {"runtime": "frozen" if getattr(sys, "frozen", False) else "source",
                            "build": vars(load_build_identity()), "checks": {}}
            self.export_done = False
            self.export_error = ""
            self.timer = QTimer(self)
            self.timer.setInterval(30)
            self.timer.timeout.connect(self.tick)
            self.timer.start()

        def tick(self):
            try:
                self.step()
            except Exception:
                import traceback
                self.results["error"] = traceback.format_exc()
                self.finish()

        def step(self):
            page = self.page
            elapsed = time.monotonic() - self.start
            if elapsed > 65:
                raise TimeoutError("frozen pipeline acceptance timed out")
            if self.phase == "waiting":
                if page.project is None or len(page.project.video_tracks) < 3:
                    return
                page._queue_advanced_preview_job = lambda *a, **kw: None
                page._seek(2.)
                self.phase = "cold"
                return
            comp = page.video_compositor
            if self.phase == "cold":
                if len(comp._players) < 2 or not all(not p.image.isNull() for p in comp._players.values()):
                    return
                self.results["checks"]["process_decoders"] = all(p.performance_snapshot()["pid"] for p in comp._players.values())
                self.results["cold_ms"] = elapsed * 1000
                page._toggle_playback()
                self.phase_start = time.monotonic()
                self.phase = "playing"
                return
            if self.phase in {"playing", "double"}:
                self.samples.append(performance_snapshot(page))
                if time.monotonic() - self.phase_start < 3:
                    return
                if self.phase == "playing":
                    page._set_speed(2.)
                    page._seek(2.)
                    self.phase = "double"
                    self.phase_start = time.monotonic()
                    return
                page._toggle_playback()
                page._seek(1.)
                self.phase = "diagnostics"
                return
            if self.phase == "diagnostics":
                if not all(abs(p.pts_ms-1000) < 100 for p in comp._players.values()):
                    return
                clock = page.video._playback_clock.snapshot()
                if clock.seeking or clock.exact_seek_pending or abs(clock.observed_media_ms-1000) > 100:
                    return
                self.results["checks"]["seek_settled"] = True
                self.results["post_seek"] = performance_snapshot(page)
                page.video.controller.screenshot_to_file(output / "frozen-native.png")
                window.grab().save(str(output / "frozen-studio.png"))
                page._dispatch_shortcut_sequence("Ctrl+Shift+P")
                self.phase = "capture"
                self.phase_start = time.monotonic()
                return
            if self.phase == "capture":
                if time.monotonic() - self.phase_start < .3:
                    return
                panel = page._performance_dialog
                panel.copy_snapshot()
                panel.grab().save(str(output / "frozen-performance.png"))
                self.results["checks"]["diagnostics"] = panel.isVisible() and bool(panel._snapshot["decoders"])
                self.results["checks"]["diagnostics_geometry"] = panel.summary.height() >= panel.summary.heightForWidth(panel.summary.width())
                panel.close()
                from .studio_revisions import StudioRevisionStore
                from .studio_project import save_autosave_revision, load_project
                revision = StudioRevisionStore(page.project).refresh_persistence(1)
                saved, _ = save_autosave_revision(revision, page.project_path, output / "recovery", session_id="frozen")
                restored = load_project(saved)
                self.results["checks"]["recovery_graph"] = len(restored.video_tracks) == 3 and sum(len(t.clips) for t in restored.video_tracks) == 3
                from .video_export import capture_video_graph
                from .studio_render import RenderJob, RenderSettings, run_render_job
                from .ass_compiler import compile_ass
                from .runtime_paths import get_runtime_paths
                ass = output / "subtitles.ass"
                ass.write_text(compile_ass(page.project), encoding="utf-8-sig")
                job = RenderJob(page.project.media.path, str(ass), str(output / "frozen-export.mp4"),
                                RenderSettings(encoder="libx264", preset="ultrafast", width=320, height=180, fps=10, audio_codec="none"),
                                start_seconds=1., duration_seconds=.5, video_graph=capture_video_graph(page.project))
                ffmpeg = get_runtime_paths().install_root / "tools/ffmpeg/bin/ffmpeg.exe"
                def export():
                    try:
                        run_render_job(ffmpeg, job)
                    except Exception:
                        import traceback
                        self.export_error = traceback.format_exc()
                    finally:
                        self.export_done = True
                threading.Thread(target=export, daemon=True, name="pipeline-frozen-export").start()
                self.phase = "export"
            elif self.phase == "export" and self.export_done:
                if self.export_error:
                    raise RuntimeError(self.export_error)
                self.results["checks"]["native_export"] = (output / "frozen-export.mp4").stat().st_size > 0
                self.finish()

        def finish(self):
            self.timer.stop()
            import psutil
            comp = self.page.video_compositor
            pids = [p.performance_snapshot().get("pid") for p in comp._players.values()]
            started = time.monotonic()
            self.page.close_page()
            self.results["close_ms"] = (time.monotonic() - started) * 1000
            self.results["checks"]["children_reaped"] = all(not pid or not psutil.pid_exists(pid) for pid in pids)
            self.results["checks"]["overlays_cleared"] = not self.page.video.active_compositor_overlay_ids()
            self.results["samples"] = self.samples
            (output / "pipeline-acceptance.json").write_text(json.dumps(self.results, ensure_ascii=False, indent=2), encoding="utf-8")
            window.hide()
            from PySide6.QtWidgets import QApplication
            QTimer.singleShot(300, QApplication.instance().quit)

    window._acceptance_audit = Audit()
