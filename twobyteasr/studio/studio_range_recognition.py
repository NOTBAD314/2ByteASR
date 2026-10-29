"""「只重新识别这一段字幕」 in Subtitle Studio (2026-10-25).

A stretch came out wrong: with in/out points set, the timeline's right-click
menu offers to recognize only that stretch again. The ordinary recognition
sheet opens in range mode (``_open_recognition_sheet(range_ms=...)``): same
plan, models and glossaries, and it says which stretch is heard and how many
captions it replaces. The main window runs the ordinary recognition on that
stretch alone (``capture_recognition_snapshot(range_ms=...)``); when it is
done, ``apply_range_result`` splices the new captions into the open project
as one undo step. Captions edited by hand are confirmed before the start and,
when the stretch was edited meanwhile, again before the replacement.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from ..i18n import bind_text, tr


def range_state(page):
    """(problem, (in, out)) for the open project; problem '' when the range can be recognized."""
    from ..recognition.range_recognition import range_problem, requested_range
    from ..timeline.studio_caption_timeline import locked_caption_speakers
    project = getattr(page, "project", None)
    locked = locked_caption_speakers(project, page) if project is not None else ()
    problem = range_problem(project, running=bool(getattr(page, "_recognition_running", False)), locked=locked)
    return problem, requested_range(project)


def add_range_action(page, menu, icon=None):
    """The menu entry; disabled with its reason when the range cannot be recognized."""
    problem, _points = range_state(page)
    if problem:
        action = menu.addAction(tr("只重新识别这一段字幕（{reason}）", reason=tr(problem)))
        action.setEnabled(False)
    else:
        action = menu.addAction(tr("只重新识别这一段字幕…"), lambda: open_range_recognition(page))
        action.setToolTip(tr("只对入点到出点这一段重新识别，用新结果替换这一段的字幕；其他字幕不动，可一步撤销"))
    if icon is not None:
        action.setIcon(icon)
    action.setObjectName("rangeRecognitionAction")
    return action


def open_range_recognition(page) -> None:
    problem, points = range_state(page)
    if problem or points is None:
        bind_text(page.save_state, problem or "先设好入点和出点")
        return
    page._open_recognition_sheet(range_ms=points)


def ask_replace_edited(page) -> bool:
    """The stretch changed while it was being recognized: replace it anyway?"""
    from ..design.studio_theme import apply_secondary_surface_theme
    box = QMessageBox(page)
    bind_text(box, '只重新识别这一段字幕', property='windowTitle')
    box.setIcon(QMessageBox.Icon.Question)
    bind_text(box, '识别期间你改过这一段的字幕。')
    bind_text(box, '用新识别结果替换这一段吗？替换后可以撤销；保留则不改动这一段。', property='informativeText')
    replace = box.addButton(tr("替换这一段"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(tr("保留现在的字幕"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(replace)
    apply_secondary_surface_theme(box)
    box.exec()
    return box.clickedButton() is replace


def _note(page, text: str) -> None:
    """Final line of the recognition chip in the caption list."""
    parts = page._recognition_chip_parts()
    page._recognition_status_sticky = str(text)
    if parts is not None:
        _frame, label = parts
        label.setProperty("recognitionStage", "")
        label.setText(str(text))
    page._sync_recognition_zero_state()
    save_state = getattr(page, "save_state", None)
    if save_state is not None:
        save_state.setText(str(text))


def apply_range_result(page, result_path, snapshot) -> bool:
    """Splice a finished range run into the open project (one undo step)."""
    from ..projects.studio_project import load_project
    from ..recognition.range_recognition import (cue_signature, history_entry, payload_from_result,
                                                 splice_range)
    from ..timeline.range_replace import ReplaceRangeCuesCommand
    from ..timeline.studio_edit_sequence import sequence_of
    page._recognition_range = None
    project = getattr(page, "project", None)
    if project is None or project.project_id != snapshot.get("project_id"):
        _note(page, tr("这一段的识别结果没有替换：工作台已经换了工程"))
        return False
    try:
        result = load_project(result_path)
    except Exception as exc:  # noqa: BLE001 - the user sees why; the open project stays
        _note(page, tr("这一段的识别结果读取失败：{error}", error=str(exc)[:160]))
        return False
    info = (result.generation_metadata.get("timeline_recognition") or {}).get("range") or {}
    if not info:
        _note(page, tr("这一段的识别结果不完整，没有替换"))
        return False
    if sequence_of(project).to_dict() != snapshot.get("sequence"):
        # The heard audio no longer sits where the captions would go.
        _note(page, tr("识别期间时间轴的剪辑变了，这一段的新字幕可能对不上，没有替换；请重新识别这一段"))
        return False
    payload = payload_from_result(result, info)
    plan = splice_range(project, info["window_ms"], payload, foreign_speakers=False)
    if cue_signature(project, plan.removed_ids) != (info.get("replaced_signature") or {}):
        if not ask_replace_edited(page):
            _note(page, tr("这一段识别完成；按你的选择保留了现在的字幕"))
            return False
    reference = result.generation_metadata.get("recognition_result") or {}
    entry = history_entry(plan, info.get("requested_ms"), fingerprint=snapshot.get("fingerprint", ""),
                          job_id=str(reference.get("job_id") or ""))
    page.undo_stack.push(ReplaceRangeCuesCommand(project, plan, entry, page._changed))
    if plan.inserted_ids:
        page.select_cue(plan.inserted_ids[0])
    _note(page, tr("这一段识别完成 · {old} 条换成 {new} 条（可撤销）",
                   old=len(plan.removed_ids), new=len(plan.inserted_ids)))
    return True
