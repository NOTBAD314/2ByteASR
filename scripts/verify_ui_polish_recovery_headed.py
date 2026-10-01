"""Five real Qt surfaces and resolved fonts for UI Recovery Session 0/Chunk A.

Run with .venv-main/Scripts/python.exe -B scripts/verify_ui_polish_recovery_headed.py
--phase before. All settings and synthetic content stay under tmp/. This is dev
UI evidence only: it does not exercise ASR, export a video, or prove V2 pixels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import wave

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("before", "after"), default="before")
    parser.add_argument("--theme", choices=("warm", "slate", "plum", "lavender"), default="warm")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    args = parser.parse_args()
    run = ROOT / "tmp" / "ui-polish-recovery" / args.phase / args.theme
    # Preserve baseline captures if the script is run more than once.
    if (run / "inventory.json").exists():
        run = run / time.strftime("run-%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        LOCALAPPDATA=str(run / "local"), APPDATA=str(run / "roaming"),
        QT_QPA_PLATFORM="windows", QT_SCALE_FACTOR="1",
        DASHSCOPE_API_KEY="sk-local-test-dummy", PYTHONIOENCODING="utf-8",
    )
    sys.path.insert(0, str(ROOT))
    evidence = {
        "runtime": "dev", "phase": args.phase, "theme": args.theme,
        "real_user_click": False, "USER VERIFIED": "NOT VERIFIED",
        "screenshots": {}, "completed": False,
        "capture_method": "visible Qt QWidget.grab; no native video pixel claim",
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_hashes": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "twobyteasr").rglob("*.py"))
        },
    }
    app = win = export = None
    try:
        print("START Qt imports", flush=True)
        from PySide6 import QtCore
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QFontInfo
        from PySide6.QtWidgets import QApplication, QLabel, QAbstractButton

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        for scope, folder in ((QSettings.Scope.UserScope, "qsettings"),
                              (QSettings.Scope.SystemScope, "qsettings-system")):
            QSettings.setPath(QSettings.Format.IniFormat, scope, str(run / folder))
        # The organization/application constructor defaults to NativeFormat
        # even after setDefaultFormat. Route it explicitly to the fixture INI.
        class IsolatedSettings(QSettings):
            def __init__(self, *a, **kw):
                super().__init__(str(run / "qt-settings.ini"), QSettings.Format.IniFormat)
        QtCore.QSettings = IsolatedSettings
        from twobyteasr import settings as runtime_settings
        runtime_settings.stable_settings_root = lambda: run / "config"
        from twobyteasr import studio_project
        fixture_settings = run / "studio-settings.json"
        fixture_settings.write_text(json.dumps({"recent_projects": [], "studio_preferences": {
            "project_root": str(run / "projects"), "autosave_enabled": False,
            "auto_cover": False, "recovery_policy": "official",
        }}), encoding="utf-8")
        studio_project.studio_settings_path = lambda: fixture_settings
        studio_project.project_library_root = lambda: run / "projects"

        app = QApplication([])
        print("START UI imports", flush=True)
        from twobyteasr.ui import MainWindow, _register_bundled_fonts, _app_font
        # Match the real launch path; the older inventory omitted registration.
        _register_bundled_fonts()
        print("START application font", flush=True)
        app.setFont(_app_font())
        from twobyteasr.theme_manager import apply_theme
        apply_theme(args.theme, app)
        print("START MainWindow", flush=True)
        import subtitle_core as legacy
        media_path = run / "ui-fixture.wav"
        with wave.open(str(media_path), "wb") as media:
            media.setnchannels(1)
            media.setsampwidth(2)
            media.setframerate(16000)
            media.writeframes(b"\0\0" * 16000)
        win = MainWindow([str(media_path)], legacy, object(), None)
        win.showNormal()
        win.resize(1600, 960)

        def settle(ms=450):
            end = time.perf_counter() + ms / 1000
            while time.perf_counter() < end:
                app.processEvents()
                time.sleep(0.005)

        def font_record(font):
            info = QFontInfo(font)
            return {
                "requested_families": font.families(), "requested_weight": int(font.weight()),
                "family": info.family(), "style": info.styleName(), "weight": int(info.weight()),
                "pixel_size": info.pixelSize(),
            }

        evidence["application_font"] = font_record(app.font())

        def capture(widget, name):
            widget.show()
            if widget in (win, export):
                # Windows can rescale the initial geometry on first show at
                # non-100% DPI; size the already-created native window.
                settle(150)
                widget.showNormal()
                widget.resize(args.width, args.height)
            widget.raise_()
            widget.activateWindow()
            settle()
            assert widget.isVisible() and widget.width() > 0 and widget.height() > 0, name
            path = run / (name + ".png")
            pixmap = widget.grab()
            assert not pixmap.isNull() and pixmap.save(str(path)), name
            labels = []
            for child in widget.findChildren(QLabel) + widget.findChildren(QAbstractButton):
                if child.isVisible():
                    labels.append({"name": child.objectName(), "text": child.text(),
                                   "typography": child.property("typography"),
                                   "size": [child.width(), child.height()],
                                   "font": font_record(child.font())})
            evidence["screenshots"][name] = {
                "file": str(path), "size": [widget.width(), widget.height()],
                "dpr": widget.devicePixelRatioF(), "labels": labels,
            }
            print("CAPTURE", name, flush=True)

        settle(900)
        win._return_to_settings()
        capture(win, "02-recognition")
        evidence["cta"] = font_record(win.start_button.font())
        evidence["cta"]["height"] = win.start_button.height()
        evidence["cta"]["enabled"] = win.start_button.isEnabled()
        evidence["cta"]["own_stylesheet"] = win.start_button.styleSheet()
        evidence["main_window_own_stylesheet"] = win.styleSheet()

        win._open_subtitle_studio()
        capture(win, "01-home-library")
        from twobyteasr.application_settings_ui import ApplicationSettingsDialog
        settings = ApplicationSettingsDialog(
            win, {}, run / "projects", browse=lambda *a: None,
            clear_recent=lambda: None, reset_layout=lambda: None,
        )
        capture(settings, "03-settings")
        if settings.advanced_controls:
            settings.navigation.setCurrentRow(3)
            capture(settings, "07-advanced-settings")
        settings.reject()
        settle()

        from twobyteasr.studio_shortcuts import ShortcutSettingsDialog
        shortcuts = ShortcutSettingsDialog({}, win)
        capture(shortcuts, "05-shortcuts")
        shortcuts.reject()
        settle()

        from twobyteasr.studio_export_ui import StudioExportWorkspace
        project = studio_project.SubtitleProject(
            media=studio_project.StudioMedia(path="", duration_ms=0),
            cues=[studio_project.StudioCue("baseline", 0, 3000, "字幕字体与页面层级基线")]
        )
        ass_path = run / "baseline.ass"
        ass_path.write_text("[Script Info]\nScriptType: v4.00+\n", encoding="utf-8")
        export = StudioExportWorkspace(project, str(ass_path))
        export.resize(1600, 960)
        capture(export, "04-export")
        evidence["export_initial_layout"] = {
            "settings_horizontal_overflow": export.settings_scroll.horizontalScrollBar().maximum(),
            "preview_horizontal_overflow": export.preview_scroll.horizontalScrollBar().maximum(),
        }
        export.subtitle_destination_modes["custom"].setChecked(True)
        export.subtitle_custom_directory.setText(str(run / "exports"))
        export.advanced_button.setChecked(True)
        export.expert_button.setChecked(True)
        settle()
        export.settings_scroll.ensureWidgetVisible(export.quality_value)
        capture(export, "06-export-advanced")
        from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit
        evidence["export_layout"] = {
            "settings_horizontal_overflow": export.settings_scroll.horizontalScrollBar().maximum(),
            "preview_horizontal_overflow": export.preview_scroll.horizontalScrollBar().maximum(),
            "fields": [{"name": name, "width": field.width(), "height": field.height(),
                        "role": field.property("fieldWidth"), "visible": field.isVisible()}
                       for name, field in vars(export).items()
                       if isinstance(field, (QLineEdit, QComboBox, QAbstractSpinBox))],
        }
        evidence["export_fixture"] = "real export widget; synthetic cue, no media/preview"
        evidence["completed"] = len(evidence["screenshots"]) >= 6
    except Exception:
        evidence["error"] = traceback.format_exc()
        print(evidence["error"], flush=True)
    finally:
        if export is not None:
            export.close()
        if win is not None:
            win.studio_page.close_page()
            win.hide()
        (run / "inventory.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("EVIDENCE", run, flush=True)
    return 0 if evidence["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
