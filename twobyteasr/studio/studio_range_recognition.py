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
    from .language_recovery_ui import add_actions
    add_actions(page, menu)
    from .speech_recovery_ui import add_actions as add_speech_actions
    add_speech_actions(page, menu)
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


def _translation_signature(metadata, cue_ids):
    view = metadata.get('translations') or {}
    records = (metadata.get('translation_records') or {}).get('records') or {}
    return {cue_id: (view.get(cue_id), tuple((records.get(cue_id) or {}).get(key)
                    for key in ('text', 'origin', 'target', 'status', 'source_text')))
            for cue_id in cue_ids}


def apply_range_result(page, result_path, snapshot) -> bool:
    """Splice a finished range run into the open project (one undo step)."""
    from ..projects.studio_project import load_project
    from ..recognition.range_recognition import (cue_signature, history_entry, payload_from_result,
                                                 splice_range)
    from ..timeline.range_replace import ReplaceRangeCuesCommand
    from ..timeline.studio_edit_sequence import sequence_of
    from shiboken6 import isValid
    if not isValid(page) or getattr(page, '_close_requested', False):
        return False
    page._recognition_range = None
    project = getattr(page, "project", None)
    if project is None or project.project_id != snapshot.get("project_id"):
        _note(page, tr("这一段的识别结果没有替换：工作台已经换了工程"))
        return False
    if (getattr(page, '_caption_split_session', None) is not None
            or getattr(project, '_caption_preview_active', False)):
        _note(page, tr('当前字幕切割草稿尚未确认，识别结果已保存，已保留当前编辑'))
        return False
    try:
        result = load_project(result_path)
    except Exception as exc:  # noqa: BLE001 - the user sees why; the open project stays
        _note(page, tr("这一段的识别结果读取失败：{error}", error=str(exc)[:160]))
        return False
    info = (result.generation_metadata.get("timeline_recognition") or {}).get("range") or {}
    from ..recognition.transcript_acceptance import pending_ranges
    if pending_ranges(result.generation_metadata.get('transcript_acceptance')):
        _note(page,tr('替代识别仍有未恢复范围；原工程和正常字幕保持，请检查模型或音轨后明确重试'))
        return False
    if not info:
        _note(page, tr("这一段的识别结果不完整，没有替换"))
        return False
    if sequence_of(project).to_dict() != snapshot.get("sequence"):
        # The heard audio no longer sits where the captions would go.
        _note(page, tr("识别期间时间轴的剪辑变了，这一段的新字幕可能对不上，没有替换；请重新识别这一段"))
        return False
    delivery = result.generation_metadata.get('timeline_recognition') or {}
    if (delivery.get('source_project_id') != snapshot.get('project_id')
            or delivery.get('fingerprint') != snapshot.get('fingerprint')
            or delivery.get('source_project_revision') != snapshot.get('project_revision')
            or list(info.get('window_ms') or ()) != list(snapshot.get('range_ms') or ())):
        _note(page, tr('这一段的识别结果与请求的工程、区间或版本不匹配，没有替换'))
        return False
    if not result.cues:
        from ..recognition.speech_recovery_project import failed_range_attempt
        if failed_range_attempt(project, snapshot.get('range_ms'), 'no_usable_captions'):
            page._changed()
        _note(page, tr('这一段没有生成可用字幕，已保留原字幕和人工修改'))
        return False
    payload = payload_from_result(result, info)
    plan = splice_range(project, info["window_ms"], payload, foreign_speakers=False)
    if not plan.inserted_ids:
        _note(page, tr('这一段没有生成可用字幕，已保留原字幕和人工修改'))
        return False
    if any(row.get('result_key') == plan.result_key for row in project.generation_metadata.get('range_recognitions', ())):
        _note(page, tr('这一段的识别结果已经应用，没有重复替换'))
        return False
    if any(row.get('source_revision') == snapshot.get('project_revision')
            and row.get('window_ms') == list(plan.window)
            for row in project.generation_metadata.get('range_recognitions', ())):
        _note(page, tr('同一区间已有较新的识别结果，已拒绝过期返回'))
        return False
    current_signature = cue_signature(project, plan.removed_ids)
    translations = _translation_signature(project.generation_metadata, plan.removed_ids)
    baseline_metadata = (snapshot.get('project') or {}).get('generation_metadata') or {}
    baseline_translations = _translation_signature(baseline_metadata, plan.removed_ids)
    if current_signature != (info.get("replaced_signature") or {}) or translations != baseline_translations:
        if not ask_replace_edited(page):
            _note(page, tr("这一段识别完成；按你的选择保留了现在的字幕"))
            return False
        # Modal confirmation runs a nested event loop. Preserve edits and
        # translations completed elsewhere while the question was visible.
        start, end = plan.window
        current_ids = {cue.id for cue in project.cues if cue.end_ms > start and cue.start_ms < end}
        if (getattr(page, 'project', None) is not project
                or sequence_of(project).to_dict() != snapshot.get('sequence')
                or current_ids != set(plan.removed_ids)
                or cue_signature(project, current_ids) != current_signature
                or _translation_signature(project.generation_metadata, current_ids) != translations):
            _note(page, tr('确认期间工程或这一段字幕又有变化，已保留当前编辑，请重新识别'))
            return False
        plan = splice_range(project, info['window_ms'], payload, foreign_speakers=False)
    if payload.acceptance:
        from ..recognition.language_recovery_project import inherit_range_appearance
        inherit_range_appearance(project, plan)
    reference = result.generation_metadata.get("recognition_result") or {}
    entry = history_entry(plan, info.get("requested_ms"), fingerprint=snapshot.get("fingerprint", ""),
                          job_id=str(reference.get("job_id") or ""),
                          source_revision=snapshot.get("project_revision"))
    # A new task can introduce several distinct, unconfirmed identities.
    # Refresh the roster as well as cue rows, including undo/redo.
    def changed():
        page._populate_speakers()
        page._changed()
    command = ReplaceRangeCuesCommand(project, plan, entry, changed)
    outcome = command.outcome
    page.undo_stack.push(command)
    if not outcome['applied']:
        _note(page, tr('这一段替换失败，已保留当前工程：{error}', error=outcome['error']))
        return False
    if plan.inserted_ids:
        page.select_cue(plan.inserted_ids[0])
    _note(page, tr("这一段识别完成 · {old} 条换成 {new} 条（可撤销）",
                   old=len(plan.removed_ids), new=len(plan.inserted_ids)))
    return True
