"""Capture the P20.3 project workflow and keyboard-editing acceptance states."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import moss_firered_pipeline  # noqa: E402
import subtitle_core  # noqa: E402
import twobyteasr.ui as ui  # noqa: E402
from twobyteasr.service import MediaResult, QueueResult  # noqa: E402
from twobyteasr.studio_project import (  # noqa: E402
    load_project,
    project_archive_path,
    save_project,
)
from twobyteasr.studio_ui import ShortcutSettingsDialog  # noqa: E402


def main() -> int:
    fixture_root = ROOT / "tmp" / "p20-studio-e2e"
    source_project = fixture_root / "studio.2byteproj"
    project = load_project(source_project)
    output_dir = fixture_root / "p203-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = output_dir / "studio-source_剪映文稿.txt"
    srt_path = output_dir / "studio-source_剪映文稿.srt"
    txt_path.write_text("\n".join(cue.text for cue in project.cues), encoding="utf-8")
    srt_path.write_text("P20.3 acceptance fixture\n", encoding="utf-8")
    archive_path = project_archive_path(srt_path, project.media.path)
    save_project(project, archive_path)

    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR")
    app.setApplicationDisplayName("2ByteASR")
    app.setWindowIcon(ui._app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())

    window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, {"id": "p20.3", "checks": 0})
    window.resize(1920, 1080)
    window.move(0, 0)
    window.show()
    screenshots: dict[str, str] = {}
    report: dict[str, object] = {}

    def capture(widget, name: str) -> None:
        app.processEvents()
        target = fixture_root / f"p20-3-{name}.png"
        pixmap = widget.grab()
        if pixmap.isNull() or not pixmap.save(str(target)):
            raise RuntimeError(f"could not capture {name}")
        screenshots[name] = str(target)
        print(f"captured {name}: {target}", flush=True)

    def show_result() -> None:
        window._show_task_notification = lambda *_args, **_kwargs: None
        result = QueueResult(
            (
                MediaResult(
                    media_path=project.media.path,
                    status="success",
                    txt_path=str(txt_path),
                    srt_path=str(srt_path),
                    project_path=str(archive_path),
                    elapsed_seconds=18.4,
                ),
            ),
            18.4,
        )
        window._handle_result(result)
        window.pages.setCurrentIndex(2)
        capture(window, "completion-open-studio")

    def open_studio() -> None:
        window.open_studio_result_button.click()

    def capture_loaded_and_keyboard() -> None:
        page = window.studio_page
        if page.video.controller:
            page.video.controller.set_paused(True)
        page.follow_playhead_toggle.setChecked(False)
        page.setFocus()
        page.activateWindow()
        page.select_cue(page.project.cues[1].id)
        cue = page.project.cues[1]
        page.timeline.set_playhead(cue.start_ms + 180)
        QTest.keyClick(page, Qt.Key.Key_Q)
        app.processEvents()
        q_start = page.project.cues[1].start_ms
        page.timeline.set_playhead(page.project.cues[1].end_ms - 160)
        QTest.keyClick(page, Qt.Key.Key_W)
        app.processEvents()
        w_end = page.project.cues[1].end_ms
        QTest.keyClick(page, Qt.Key.Key_C)
        app.processEvents()
        razor_mode = page.timeline.tool_mode
        page._split_at(page.project.cues[1].id, page.project.cues[1].start_ms + 250)
        split_count = len(page.project.cues)
        QTest.keyClick(page, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        app.processEvents()
        undo_count = len(page.project.cues)
        QTest.keyClick(page, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        app.processEvents()
        redo_count = len(page.project.cues)
        QTest.keyClick(page, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(page, Qt.Key.Key_V)
        app.processEvents()
        page.follow_playhead_toggle.setChecked(True)
        page.select_cue(page.project.cues[0].id)
        page._position_changed(4.2)
        followed_cue = page.selected_cue_id
        page.save()
        report["keyboard"] = {
            "q_start_ms": q_start,
            "w_end_ms": w_end,
            "razor_mode": razor_mode,
            "split_count": split_count,
            "undo_count": undo_count,
            "redo_count": redo_count,
            "final_tool": page.timeline.tool_mode,
            "followed_cue_at_4_2s": followed_cue,
            "undo_clean_after_save": page.undo_stack.isClean(),
        }
        capture(window, "studio-loaded-real-project")

    def capture_zoomed() -> None:
        page = window.studio_page
        page.timeline.visible_start_ms = 3000
        page.timeline.visible_duration_ms = 9000
        page.timeline.update()
        capture(window, "timeline-zoomed-cue-text")

    def show_shortcuts() -> None:
        dialog = ShortcutSettingsDialog(window.studio_page._shortcut_values, window)
        window._p203_shortcut_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def capture_shortcuts() -> None:
        dialog = window._p203_shortcut_dialog
        capture(dialog, "shortcut-settings")
        dialog.close()
        reopened = load_project(archive_path)
        report.update(
            screenshots=screenshots,
            archive={
                "project": str(archive_path),
                "children": sorted(path.name for path in archive_path.parent.iterdir()),
                "desktop_projects": [str(path) for path in Path.home().glob("*.2byteproj")],
                "desktop_ass": [str(path) for path in Path.home().glob("*.ass")],
            },
            reopened={"cue_count": len(reopened.cues), "selected": reopened.studio_state.get("last_selected_cue")},
            studio={
                "media_exists": Path(reopened.media.path).is_file(),
                "speaker_tracks": len(window.studio_page.timeline.speaker_ids()),
                "preview_ass": str(window.studio_page._preview_path or ""),
                "waveform_loaded": window.studio_page.timeline.cache is not None,
            },
        )
        (fixture_root / "p20-3-acceptance-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        window.close()
        app.quit()

    QTimer.singleShot(500, show_result)
    QTimer.singleShot(1200, open_studio)
    QTimer.singleShot(3500, capture_loaded_and_keyboard)
    QTimer.singleShot(4300, capture_zoomed)
    QTimer.singleShot(5000, show_shortcuts)
    QTimer.singleShot(5600, capture_shortcuts)
    result = app.exec()
    window.studio_page.close_page()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
