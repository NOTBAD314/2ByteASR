"""Headed smoke driver for the post-split Studio (real platform, real project).

Drives SubtitleStudioPage end-to-end: open project, mpv playback, timeline,
style inspector, AI panel surface, review mode, export workspace, save+reopen.
Every step logs a [SMOKE] line; failures print tracebacks and set exit code 2.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROJECT = Path(
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects"
    r"\[NOTBAD]尼奈小爱7_2026.08.11-15.14.39"
    r"\[NOTBAD]尼奈小爱7_2026.08.11-15.14.39.2byteproj"
)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage

STEPS: list[tuple[str, object]] = []
RESULTS: list[tuple[str, bool, str]] = []


def step(name):
    def deco(fn):
        STEPS.append((name, fn))
        return fn
    return deco


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    print(f"[SMOKE] {'PASS' if condition else 'FAIL'} {label} {detail}", flush=True)


def build_page() -> SubtitleStudioPage:
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()
    return page


def main() -> int:
    app = QApplication.instance() or QApplication([])
    page = build_page()
    state: dict[str, object] = {"page": page, "app": app}

    def run_step(index: int) -> None:
        if index >= len(STEPS):
            finish()
            return
        name, fn = STEPS[index]
        print(f"[SMOKE] RUN  {name}", flush=True)
        try:
            fn(state)
        except Exception:
            traceback.print_exc()
            check(f"step:{name}", False, "exception")
        QTimer.singleShot(600, lambda: run_step(index + 1))

    def finish() -> None:
        ok = all(flag for _, flag, _ in RESULTS)
        try:
            page.close_page()
        except Exception:
            traceback.print_exc()
        print(f"[SMOKE] summary ok={ok} total={len(RESULTS)}", flush=True)
        app.quit()

    @step("open_project")
    def _open(state):
        page = state["page"]
        page.open_project(PROJECT)
        page._wait_for_autosave_worker(timeout=2.0)
        check("project_loaded", page.project is not None and len(page.project.cues) == 62,
              f"cues={len(page.project.cues) if page.project else 0}")
        check("cue_table_rows", page.cue_model.rowCount() > 50,
              f"rows={page.cue_model.rowCount()}")
        check("timeline_widget", page.timeline is not None and page.timeline.waveform_state != "",
              f"wf_state={page.timeline.waveform_state}")

    @step("select_first_cue")
    def _select(state):
        page = state["page"]
        cue = page.project.cues[0]
        page.select_cue(cue.id)
        check("selection", page.selected_cue_id == cue.id)
        check("cue_text_loaded", bool(page.cue_text.toPlainText().strip()))

    @step("playback_3s")
    def _play(state):
        page = state["page"]
        page._toggle_playback()
        state["started_at"] = True

    @step("pause_and_check_position")
    def _pause(state):
        page = state["page"]
        pos = page.video.visual_position()
        check("mpv_position_advanced", pos > 0.5, f"pos={pos:.2f}s")
        paused = page.video.controller.get_property("pause", True)
        check("mpv_alive", page.video.controller is not None, f"paused={paused}")
        page._toggle_playback()

    @step("timeline_seek")
    def _seek(state):
        page = state["page"]
        page._seek(30.0)
        pos = page.video.visual_position()
        check("seek_landed_near_30s", 25.0 < pos < 40.0, f"pos={pos:.2f}s")
        check("timeline_duration", page.timeline._duration_ms() > 60000,
              f"dur={page.timeline._duration_ms()}ms")

    @step("style_inspector")
    def _style(state):
        page = state["page"]
        page._load_style_inspector()
        check("style_preview_widget", page.style_preview is not None)
        check("preset_combo_filled", page.style_preset.count() > 0,
              f"presets={page.style_preset.count()}")
        page._refresh_style_presets()
        check("font_combo", page.style_font is not None and page.style_font.count() >= 0)

    @step("ai_panel_surface")
    def _ai(state):
        page = state["page"]
        page._refresh_ai_design_provider_summary()
        check("ai_provider_summary", page.ai_provider_health is not None)
        page._update_advanced_style_status({"engine": "advanced"})
        check("ai_status_no_crash", True)

    @step("review_mode")
    def _review(state):
        page = state["page"]
        page._set_review_mode(True)
        check("review_mode_on", page._review_mode is True)
        page._refresh_review_summary_strip()
        check("review_summary_built", True)
        page._exit_review()
        check("review_mode_off", page._review_mode is False)

    @step("export_workspace")
    def _export(state):
        page = state["page"]
        page._open_render_dialog()
        state["app"].processEvents()
        visible = page.export_workspace is not None and page.export_workspace.isVisible()
        check("export_workspace_visible", visible)
        page._close_export_workspace()
        state["app"].processEvents()
        check("export_workspace_closed",
              page.export_workspace is None or not page.export_workspace.isVisible())

    @step("canvas_inline_edit")
    def _inline(state):
        page = state["page"]
        page._begin_canvas_inline_edit()
        editor_visible = (
            getattr(page, "_canvas_editor", None) is not None
            and page._canvas_editor.isVisible()
        )
        check("canvas_inline_editor_open", editor_visible,
              f"editor={getattr(page, '_canvas_editor', None)}")
        page._commit_canvas_inline_edit(advance=False)
        check("canvas_inline_edit_committed", True)

    @step("save_and_reopen")
    def _save(state):
        page = state["page"]
        before = len(page.project.cues)
        page.save()
        page._wait_for_autosave_worker(timeout=3.0)
        check("saved", PROJECT.is_file())
        page.close_page()
        page2 = build_page()
        page2.open_project(PROJECT)
        state["page2"] = page2
        check("reopen_cues_match", len(page2.project.cues) == before,
              f"before={before} after={len(page2.project.cues)}")
        page2.close_page()

    QTimer.singleShot(400, lambda: run_step(0))
    app.exec()
    ok = all(flag for _, flag, _ in RESULTS)
    return 0 if ok else 2


if __name__ == "__main__":
    code = main()
    print(f"[SMOKE] exit={code}", flush=True)
    sys.exit(code)
