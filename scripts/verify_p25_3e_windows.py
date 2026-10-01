"""Headed Windows A-K acceptance for P25.3E Advanced Visual stability."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ.setdefault("QT_SCALE_FACTOR", "1.75")
os.environ["LOCALAPPDATA"] = str(ROOT / "tmp" / "p25.3e" / f"local-{os.getpid()}")
os.environ["TWOBYTEASR_DEBUG_STUDIO"] = "1"
os.environ["TWOBYTEASR_DEBUG_SUBTITLES"] = "1"

from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QColorDialog, QMainWindow

from twobyteasr.advanced_preview import AdvancedPreviewCache, AdvancedPreviewPhase
from twobyteasr.advanced_renderer import (
    AdvancedRendererBackend,
    compile_composition_data,
    normalized_visual_snapshot,
)
from twobyteasr.ass_compiler import compile_ass
from twobyteasr.motion_library import MotionPresetStore
from twobyteasr.studio_project import load_project, save_project
from twobyteasr.studio_render import RenderJob, RenderSettings, windows_subprocess_kwargs
from twobyteasr.studio_ui import FillEditorDialog, MotionBrowserDialog, SubtitleStudioPage
from twobyteasr.style_recipe import FillSpec, StyleRecipe, route_recipe
from twobyteasr.ui import APP_QSS
from twobyteasr.visual_snapshot import build_visual_cue_snapshot


SOURCE_PROJECT = ROOT / "tmp" / "p25.3c" / "mixed-authoritative-visuals.2byteproj"
OUTPUT = ROOT / "tmp" / "p25.3e"
SCREENSHOTS = ROOT / "screenshots" / "p25.3e"
PROJECT_COPY = OUTPUT / "real-project-copy.2byteproj"
REPORT = OUTPUT / "windows-acceptance.json"
TRACE = OUTPUT / "studio-open.log"
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Acceptance:
    def __init__(self, app: QApplication, window: QMainWindow, studio: SubtitleStudioPage):
        self.app = app
        self.window = window
        self.studio = studio
        self.checks: dict[str, dict[str, object]] = {}
        self.errors: list[str] = []
        self.first_started = 0.0
        self.first_ready_ms = 0.0
        self.revisit_started = 0.0
        self.pause_signature: tuple[object, ...] | None = None
        self.pause_frame = SCREENSHOTS / "E-paused-before.png"
        self.export_result: dict[str, object] = {}
        self.export_done = False
        self.final_studio_frame = SCREENSHOTS / "K-studio-preview.png"

    def later(self, milliseconds: int, callback) -> None:
        QTimer.singleShot(milliseconds, callback)

    def screenshot(self, name: str, rect: QRect | None = None) -> Path:
        target = SCREENSHOTS / name
        capture_window = self.app.activeWindow() or self.window
        screen = capture_window.screen() or self.app.primaryScreen()
        if rect is None:
            pixmap = screen.grabWindow(int(capture_window.winId()))
        else:
            local_rect = QRect(capture_window.mapFromGlobal(rect.topLeft()), rect.size())
            pixmap = screen.grabWindow(
                int(capture_window.winId()),
                local_rect.x(), local_rect.y(), local_rect.width(), local_rect.height(),
            )
        if not pixmap.save(str(target), "PNG"):
            raise RuntimeError(f"cannot save screenshot: {target}")
        return target

    def video_rect(self) -> QRect:
        self.studio.position_overlay.sync_to_video(self.studio.video)
        content = self.studio.position_overlay._content_rect().toRect()
        return QRect(self.studio.video.mapToGlobal(content.topLeft()), content.size())

    def overlay_state(self) -> dict[str, object]:
        overlay = self.studio.advanced_cue_overlay
        pixmap = overlay.pixmap()
        return {
            "baseRect": list(overlay._base_rect.getRect()),
            "geometry": list(overlay.geometry().getRect()),
            "contentRect": list(self.studio.position_overlay._content_rect().toRect().getRect()),
            "videoRect": list(self.studio.video.rect().getRect()),
            "devicePixelRatio": overlay.devicePixelRatioF(),
            "pixmapSize": list(pixmap.size().toTuple()) if not pixmap.isNull() else [0, 0],
            "pixmapDevicePixelRatio": pixmap.devicePixelRatio() if not pixmap.isNull() else 0.0,
            "opacity": overlay.graphicsEffect().opacity(),
            "frameSignature": list(overlay._last_frame_signature) if overlay._last_frame_signature else None,
        }

    def wait_for_video_rect(self, callback, attempt: int = 0) -> None:
        rect = self.video_rect()
        if rect.width() >= 320 and rect.height() >= 180:
            callback()
            return
        if attempt >= 100:
            self.fail(f"video content rect did not settle: {rect.getRect()}")
            return
        self.later(100, lambda: self.wait_for_video_rect(callback, attempt + 1))

    def record(self, letter: str, passed: bool, **details: object) -> None:
        self.checks[letter] = {"passed": bool(passed), **details}

    def fail(self, message: str) -> None:
        self.errors.append(str(message))
        self.finish()

    def start(self) -> None:
        try:
            self.window.activateWindow()
            QApplication.setActiveWindow(self.window)
            self.window.raise_()
            self.studio.select_cue("native-before")
            self.studio._seek(2.0)
            self.studio.video.set_paused(True)
            present = "native-before" in {
                cue.id for cue in self.studio._ass_preview_snapshot(self.studio.project).cues
            }
            image = self.screenshot("A-native-cue.png", self.video_rect())
            self.record("A", present, cue="native-before", screenshot=str(image))
            self.later(350, self.select_advanced)
        except Exception as exc:
            self.fail(f"A: {exc}")

    def select_advanced(self) -> None:
        try:
            self.first_started = perf_counter()
            self.studio.select_cue("cyber")
            self.studio._seek(4.3)
            self.studio.video.set_paused(True)
            fallback = "cyber" in {
                cue.id for cue in self.studio._ass_preview_snapshot(self.studio.project).cues
            }
            image = self.screenshot("B-native-fallback.png", self.video_rect())
            self.record("B", fallback, nativeFallbackVisible=fallback, screenshot=str(image))
            self.poll_first_ready(0)
        except Exception as exc:
            self.fail(f"B: {exc}")

    def poll_first_ready(self, attempt: int) -> None:
        state = self.studio._advanced_preview_state
        ready = (
            state.phase == AdvancedPreviewPhase.ADVANCED_VISIBLE
            and self.studio.advanced_cue_overlay.isVisible()
        )
        if ready:
            self.first_ready_ms = (perf_counter() - self.first_started) * 1000
            image = self.screenshot("C-advanced-ready.png", self.video_rect())
            self.record(
                "C", True, phase=state.phase.value,
                firstReadyMs=round(self.first_ready_ms, 2), screenshot=str(image),
            )
            self.later(300, self.leave_advanced)
            return
        if attempt >= 240:
            self.fail(f"C: Advanced did not become visible, phase={state.phase.value}")
            return
        self.later(250, lambda: self.poll_first_ready(attempt + 1))

    def leave_advanced(self) -> None:
        self.studio.select_cue("native-after")
        self.studio._seek(18.0)
        self.revisit_started = perf_counter()
        self.later(250, self.revisit_advanced)

    def revisit_advanced(self) -> None:
        self.studio.select_cue("cyber")
        self.studio._seek(4.3)
        self.studio.video.set_paused(True)
        self.poll_revisit(0)

    def poll_revisit(self, attempt: int) -> None:
        ready = (
            self.studio._advanced_preview_state.phase == AdvancedPreviewPhase.ADVANCED_VISIBLE
            and self.studio.advanced_cue_overlay.isVisible()
        )
        if ready:
            elapsed = (perf_counter() - self.revisit_started) * 1000
            image = self.screenshot("D-cache-revisit.png", self.video_rect())
            self.record(
                "D", elapsed < 1500, revisitMs=round(elapsed, 2),
                thresholdMs=1500, screenshot=str(image),
            )
            self.later(250, self.begin_pause)
            return
        if attempt >= 40:
            self.fail("D: cached cue did not return within 10 seconds")
            return
        self.later(250, lambda: self.poll_revisit(attempt + 1))

    def begin_pause(self) -> None:
        self.studio.video.set_paused(True)
        self.studio._position_changed(4.3)
        overlay = self.studio.advanced_cue_overlay
        self.pause_signature = (
            tuple(overlay.geometry().getRect()),
            overlay.pixmap().cacheKey(),
            overlay.graphicsEffect().opacity(),
            overlay._last_frame_signature,
        )
        self.pause_state = self.overlay_state()
        overlay.grab().save(str(self.pause_frame), "PNG")
        self.later(30_000, self.end_pause)

    def end_pause(self) -> None:
        overlay = self.studio.advanced_cue_overlay
        after = (
            tuple(overlay.geometry().getRect()),
            overlay.pixmap().cacheKey(),
            overlay.graphicsEffect().opacity(),
            overlay._last_frame_signature,
        )
        after_frame = SCREENSHOTS / "E-paused-after.png"
        overlay.grab().save(str(after_frame), "PNG")
        frozen = self.pause_signature == after and sha256(self.pause_frame) == sha256(after_frame)
        self.record(
            "E", frozen, waitedSeconds=30,
            beforeHash=sha256(self.pause_frame), afterHash=sha256(after_frame),
            beforeState=self.pause_state, afterState=self.overlay_state(),
            beforeScreenshot=str(self.pause_frame), afterScreenshot=str(after_frame),
        )
        self.check_motion_clock()

    def check_motion_clock(self) -> None:
        overlay = self.studio.advanced_cue_overlay
        self.studio.video._paused = False
        self.studio._position_changed(4.12)
        first = (tuple(overlay.geometry().getRect()), overlay.graphicsEffect().opacity())
        self.studio._position_changed(4.55)
        second = (tuple(overlay.geometry().getRect()), overlay.graphicsEffect().opacity())
        self.studio.video._paused = True
        self.studio._position_changed(4.55)
        paused = (tuple(overlay.geometry().getRect()), overlay.graphicsEffect().opacity())
        self.studio._position_changed(5.40)
        sought = (tuple(overlay.geometry().getRect()), overlay.graphicsEffect().opacity())
        passed = first != second and second == paused and sought != first
        self.record(
            "F", passed, playChanged=first != second,
            pausePreserved=second == paused, seekChanged=sought != first,
        )
        self.fill_acceptance()

    def fill_acceptance(self) -> None:
        try:
            before = build_visual_cue_snapshot(self.studio.project, "cyber")
            signatures = [before.geometry_signature()]
            fills = (
                FillSpec.linear([
                    {"color": "#FFFFD84A", "position": 0.0},
                    {"color": "#FFFF4FA3", "position": 0.5},
                    {"color": "#FF20D9FF", "position": 1.0},
                ], angle=25),
                FillSpec.radial([
                    {"color": "#FFFFD84A", "position": 0.0},
                    {"color": "#FFFF4FA3", "position": 0.5},
                    {"color": "#FF20D9FF", "position": 1.0},
                ]),
                FillSpec.solid("#FFFFFFFF"),
            )
            for fill in fills:
                self.studio._apply_fill_spec(fill)
                signatures.append(build_visual_cue_snapshot(
                    self.studio.project, "cyber"
                ).geometry_signature())
            self.record("G", len(set(signatures)) == 1, geometrySignatures=[list(row) for row in signatures])
            dialog = FillEditorDialog(fills[1].to_dict(), self.window)
            dialog.mode_group.button(2).setChecked(True)
            dialog.show(); dialog.raise_(); dialog.activateWindow()
            self.app.processEvents()
            image = self.screenshot("H-fill-editor-three-stops.png")
            shared_picker = dialog.palette.testOption(
                QColorDialog.ColorDialogOption.ShowAlphaChannel
            )
            self.record(
                "H", len(dialog.gradient._stops) >= 3 and shared_picker,
                stops=len(dialog.gradient._stops), alphaPicker=shared_picker,
                screenshot=str(image),
            )
            dialog.close(); dialog.deleteLater()
            self.later(250, self.motion_acceptance)
        except Exception as exc:
            self.fail(f"G/H: {exc}")

    def motion_acceptance(self) -> None:
        try:
            style = next(item for item in self.studio.project.styles if item.id == self.studio._cue_lookup["cyber"].style_id)
            dialog = MotionBrowserDialog(style, self.window)
            dialog.show(); dialog.raise_(); dialog.activateWindow()
            self.app.processEvents()
            cards = dialog.findChildren(__import__("twobyteasr.studio_ui", fromlist=["MotionCard"]).MotionCard)
            image = self.screenshot("I-motion-browser.png")
            live = len(cards) >= 12 and all(card.preview._motion_timer.isActive() and card.preview._motion_loop for card in cards)
            dialog.close(); dialog.deleteLater()
            preset = MotionPresetStore().all()["glitch_reveal"]
            self.studio._apply_advanced_motion(preset)
            cue = self.studio._cue_lookup["cyber"]
            recipe = StyleRecipe.from_dict(self.studio.project.style_recipes[cue.style_id])
            glitch = recipe.motion.get("entrance", {}).get("type") == "glitch_reveal"
            self.record(
                "I", live and glitch, cardCount=len(cards), liveCards=live,
                glitchApplied=glitch, screenshot=str(image),
            )
            self.later(500, self.transform_acceptance)
        except Exception as exc:
            self.fail(f"I: {exc}")

    def transform_acceptance(self) -> None:
        try:
            cue = self.studio._cue_lookup["cyber"]
            before = build_visual_cue_snapshot(self.studio.project, cue.id)
            self.studio._commit_canvas_style(
                position=(round(before.position_x + 80), round(before.position_y - 35))
            )
            self.studio._commit_canvas_style(font_size=before.font_size + 8)
            self.studio.style_font.setEditText("Microsoft YaHei UI")
            self.studio._commit_style_now()
            cue = self.studio._cue_lookup["cyber"]
            after = build_visual_cue_snapshot(self.studio.project, cue.id)
            payload = self.studio.project.style_recipes.get(cue.style_id)
            advanced = bool(payload) and route_recipe(payload).engine == "remotion"
            changed = (
                after.position_x != before.position_x
                and after.position_y != before.position_y
                and after.font_size != before.font_size
                and after.font_family == "Microsoft YaHei UI"
            )
            self.studio.select_cue("cyber")
            self.studio._seek(4.3)
            self.window.activateWindow(); QApplication.setActiveWindow(self.window)
            self.window.raise_()
            self.later(500, lambda: self.capture_transform(advanced, changed, before, after))
        except Exception as exc:
            self.fail(f"J: {exc}")

    def capture_transform(self, advanced, changed, before, after) -> None:
        image = self.screenshot("J-advanced-after-transform.png", self.video_rect())
        self.record(
            "J", advanced and changed, advancedRoute=advanced,
            beforeGeometry=list(before.geometry_signature()),
            afterGeometry=list(after.geometry_signature()), screenshot=str(image),
        )
        self.begin_export()

    def begin_export(self) -> None:
        try:
            save_project(self.studio.project, PROJECT_COPY)
            self.screenshot("K-studio-preview.png", self.video_rect())
            project = copy.deepcopy(self.studio.project)
            thread = threading.Thread(
                target=self.export_worker,
                args=(project,),
                daemon=True,
                name="p25-3e-export",
            )
            thread.start()
            self.poll_export(0)
        except Exception as exc:
            self.fail(f"K start: {exc}")

    def export_worker(self, project) -> None:
        try:
            ass_path = OUTPUT / "final-native.ass"
            ass_path.write_text(compile_ass(project), encoding="utf-8-sig")
            output_video = OUTPUT / "p25.3e-final.mp4"
            settings = RenderSettings(
                width=1280, height=720, fps=30.0,
                encoder="libx264", audio_codec="aac", quality=18,
            )
            job = RenderJob(
                project.media.path,
                str(ass_path),
                str(output_video),
                settings,
                start_seconds=0,
                duration_seconds=20,
            )
            events: list[dict[str, object]] = []
            progress: list[dict[str, object]] = []
            AdvancedRendererBackend().render(
                project,
                FFMPEG,
                job,
                trace=lambda event, value: events.append({"event": event, "value": value}),
                progress=lambda value: progress.append(dict(value)),
            )
            final_frame = SCREENSHOTS / "K-export-frame.png"
            subprocess.run([
                str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
                "-ss", "4.3", "-i", str(output_video), "-frames:v", "1", str(final_frame),
            ], check=True, **windows_subprocess_kwargs())
            studio_image = QImage(str(self.final_studio_frame))
            final_image = QImage(str(final_frame))
            comparison_path = SCREENSHOTS / "K-studio-vs-export.png"
            if not studio_image.isNull() and not final_image.isNull():
                final_scaled = final_image.scaledToHeight(
                    studio_image.height(), Qt.TransformationMode.SmoothTransformation
                )
                comparison = QImage(
                    studio_image.width() + final_scaled.width(),
                    studio_image.height(),
                    QImage.Format.Format_ARGB32,
                )
                comparison.fill(Qt.GlobalColor.black)
                painter = QPainter(comparison)
                painter.drawImage(0, 0, studio_image)
                painter.drawImage(studio_image.width(), 0, final_scaled)
                painter.end()
                comparison.save(str(comparison_path), "PNG")
            cue = next(item for item in project.cues if item.id == "cyber")
            snapshot = build_visual_cue_snapshot(project, cue.id, width=1280, height=720, fps=30)
            props = compile_composition_data(
                project, width=1280, height=720, fps=30,
                start_seconds=0, duration_seconds=20,
            )
            exported = next(item for item in props["cues"] if item["id"] == "cyber")
            self.export_result = {
                "output": str(output_video),
                "outputSize": output_video.stat().st_size,
                "outputSha256": sha256(output_video),
                "finalFrame": str(final_frame),
                "comparison": str(comparison_path),
                "events": events,
                "progressEvents": len(progress),
                "snapshotHash": snapshot.stable_hash(),
                "exportSnapshotHash": exported["snapshotHash"],
                "visualContractMatch": exported["visual"] == normalized_visual_snapshot(snapshot),
            }
        except Exception as exc:
            self.export_result = {"error": str(exc)}
        finally:
            self.export_done = True

    def poll_export(self, attempt: int) -> None:
        if self.export_done:
            success = (
                "error" not in self.export_result
                and bool(self.export_result.get("outputSize"))
                and self.export_result.get("snapshotHash") == self.export_result.get("exportSnapshotHash")
                and self.export_result.get("visualContractMatch") is True
            )
            self.record("K", success, studioPreview=str(self.final_studio_frame), **self.export_result)
            self.finish()
            return
        if attempt >= 240:
            self.fail("K: export did not finish within 8 minutes")
            return
        self.later(2_000, lambda: self.poll_export(attempt + 1))

    def finish(self) -> None:
        source_trace = Path(os.environ["LOCALAPPDATA"]) / "2ByteASR" / "logs" / "studio-open.log"
        if source_trace.is_file():
            shutil.copy2(source_trace, TRACE)
        screen = self.app.primaryScreen()
        report = {
            "phase": "P25.3E",
            "qtPlatform": self.app.platformName(),
            "qtScaleFactor": os.environ.get("QT_SCALE_FACTOR"),
            "devicePixelRatio": screen.devicePixelRatio() if screen else None,
            "screenGeometry": list(screen.geometry().getRect()) if screen else None,
            "windowGeometry": list(self.window.geometry().getRect()),
            "splitterSizes": self.studio.upper_splitter.sizes(),
            "projectCopy": str(PROJECT_COPY),
            "sourceMedia": self.studio.project.media.path if self.studio.project else "",
            "checks": self.checks,
            "errors": self.errors,
            "allPassed": len(self.checks) == 11 and all(
                bool(self.checks.get(letter, {}).get("passed")) for letter in "ABCDEFGHIJK"
            ) and not self.errors,
            "trace": str(TRACE),
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        self.studio.close_page()
        self.window.close()
        self.app.quit()


def main() -> int:
    if not SOURCE_PROJECT.is_file():
        raise FileNotFoundError(SOURCE_PROJECT)
    if not FFMPEG.is_file():
        raise FileNotFoundError(FFMPEG)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    project = load_project(SOURCE_PROJECT)
    if not Path(project.media.path).is_file():
        raise FileNotFoundError(project.media.path)
    save_project(project, PROJECT_COPY)

    app = QApplication(sys.argv)
    app.setApplicationName("2ByteASR P25.3E Windows Acceptance")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    window = QMainWindow()
    window.setWindowTitle("2ByteASR P25.3E A-K Acceptance")
    studio = SubtitleStudioPage(window)
    studio._advanced_preview_cache = AdvancedPreviewCache(
        OUTPUT / f"cache-{os.getpid()}"
    )
    window.setCentralWidget(studio)
    window.resize(1720, 980)
    window.showMaximized()
    studio.open_project(PROJECT_COPY)
    acceptance = Acceptance(app, window, studio)
    QTimer.singleShot(2_000, lambda: acceptance.wait_for_video_rect(acceptance.start))
    QTimer.singleShot(10 * 60 * 1000, lambda: acceptance.fail("global timeout"))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
