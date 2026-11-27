"""Windows acceptance for the rough-cut actions and scheme dialogs."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from ..glossary.quick_term_dialog import QuickTermCaptureDialog
from ..projects.series_store import SeriesStore
from ..studio.ai_rough_cut import REASON_RETAKE, active_cut_cue_ids, set_cue_cut_mark
from ..studio.auto_pipeline_ui import AutoPipelineDialog
from ..timeline.studio_edit_sequence import timeline_duration_ms


def _capture(widget, path, check):
    QTest.qWait(120)
    image = widget.grab()
    check(path.stem + " paints in the Windows window",
          widget.isVisible() and not image.isNull() and image.save(str(path)))


def _click_in_rough_cut(bar, button, check, action):
    QTest.qWait(40)
    bar.body_scroll.ensureWidgetVisible(button, 0, 4)
    QTest.qWait(40)
    viewport = bar.body_scroll.viewport()
    spot = button.mapTo(viewport, button.rect().center())
    check(action + " is reachable in the scroll viewport",
          viewport.rect().contains(spot) and button.visibleRegion().contains(button.rect().center())
          and button.isEnabled())
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def run(window, page, output, check):
    page._open_clip_assistant()
    bar = page.highlight_panel.rough_cut_bar
    _capture(bar, output / "rough-cut-viewport.png", check)
    _capture(bar.body, output / "rough-cut-three-steps.png", check)
    check("short workbench shows the first step and can scroll to the rest",
          bar.body_scroll.viewport().height() >= 140
          and bar.title_label.height() >= 16
          and bar.body_scroll.verticalScrollBar().maximum() > 0
          and bar.step_pick.title.height() >= 14)
    check("linking video is opt-in", not bar.linked_toggle.isChecked() and not bar.apply_button.isEnabled())
    project = page.project
    target = project.cues[1].id
    set_cue_cut_mark(project, target, marked=True, reason=REASON_RETAKE)
    page._refresh_rough_cut_ui()
    check("marked cue has a reason and enables the preview",
          target in active_cut_cue_ids(project) and bar.seam_button.isEnabled())
    _click_in_rough_cut(bar, bar.reason_chips[REASON_RETAKE], check, "hold the reason")
    check("reason chip temporarily keeps the marked cue", target not in active_cut_cue_ids(project))
    _click_in_rough_cut(bar, bar.reason_chips[REASON_RETAKE], check, "restore the reason")
    check("reason chip restores the proposed cut", target in active_cut_cue_ids(project))
    _capture(bar, output / "rough-cut-with-reason.png", check)
    initial_duration = timeline_duration_ms(project)
    _click_in_rough_cut(bar, bar.seam_button, check, "start the seam preview")
    check("preview opens a seam session without changing the edit",
          bool(page._rough_cut_seam_session) and timeline_duration_ms(project) == initial_duration)
    _click_in_rough_cut(bar, bar.seam_button, check, "stop the seam preview")
    _click_in_rough_cut(bar, bar.apply_button, check, "apply the cut")
    check("cut shortens the timeline and can be undone",
          timeline_duration_ms(project) < initial_duration and page.undo_stack.canUndo())
    page.undo_stack.undo()
    check("undo restores the original timeline", timeline_duration_ms(project) == initial_duration)
    page._clear_rough_cut_marks()

    store = SeriesStore()
    scheme = store.create("視窗驗收方案")
    store.set_last_selected(scheme.id)
    project.studio_state["series_binding"] = {"series_id": scheme.id, "series_name": scheme.name}
    tabs = page.source_tabs
    panel = page.finish_checklist_panel
    tab_bar = tabs.tabBar()
    QTest.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=tab_bar.tabRect(tabs.indexOf(panel)).center())
    check("scheme tab shows three category controls",
          tabs.currentWidget() is panel and set(panel._inline_switches)
          == {"run_glossary", "run_speakers", "run_style_preset"})
    _capture(panel, output / "scheme-cards.png", check)

    modal = {}
    def inspect_pipeline():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, AutoPipelineDialog):
            modal["wrong_widget"] = True
            if isinstance(dialog, QDialog):
                dialog.reject()
            return
        modal["rounded"] = dialog.findChild(QWidget, "roundedDialogRoot") is not None
        modal["captured"] = dialog.grab().save(str(output / "pipeline-rounded.png"))
        modal["switches"] = all(getattr(dialog.panel, name).isVisible()
                                for name in ("cb_glossary", "cb_speakers", "cb_style"))
        dialog.reject()

    QTimer.singleShot(250, inspect_pipeline)
    QTest.mouseClick(panel.pipeline_btn, Qt.MouseButton.LeftButton)
    check("scheme gear opens the rounded three-switch dialog",
          modal == {"rounded": True, "captured": True, "switches": True})

    quick = QuickTermCaptureDialog(library_name="驗收詞庫", parent=page)
    quick.show()
    try:
        _capture(quick, output / "quick-term-rounded.png", check)
        check("quick term capture has its rounded root and visible input",
              quick.findChild(QWidget, "roundedDialogRoot") is not None and quick.panel.input_box.isVisible())
    finally:
        quick.reject()

    _capture(window, output / "studio-schemes-full-window.png", check)
    QTest.mouseClick(bar.fold_button, Qt.MouseButton.LeftButton)
    check("folding hides the steps and leaves the existing controls usable",
          not bar.body_scroll.isVisible() and page.highlight_panel.clip_tools.isVisible())
    QTest.mouseClick(bar.fold_button, Qt.MouseButton.LeftButton)
    check("opening the steps restores their scroll area", bar.body_scroll.isVisible())

