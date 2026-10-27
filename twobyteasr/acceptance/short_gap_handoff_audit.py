"""Existing-project short-gap command: real menu, undo, persistence and bilingual view."""
from __future__ import annotations

import copy
import json
from pathlib import Path


def run(page, window, output, *, check, wait, capture):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu
    from ..subtitle_rules.subtitle_translation import snapshot
    from ..caption_style.bilingual_layout import project_display_cues
    from ..projects.studio_project import load_project

    def gaps(project):
        ordered = sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms, c.id))
        return [(a.id, b.id, a.end_ms, b.start_ms) for a,b in zip(ordered, ordered[1:])
                if 0 < b.start_ms-a.end_ms <= 500]

    p = page.project
    before = copy.deepcopy(p.cues)
    translations = snapshot(p)
    media = copy.deepcopy((p.media, p.media_pool, p.video_tracks, p.audio_tracks, p.styles, p.speakers))
    words = copy.deepcopy(p.generation_metadata.get("cue_forced_alignment"))
    initial = gaps(p)
    check("gaps_real_sample_68", len(initial) == 68, initial)
    check("gaps_sample_170_171_250ms", ("170", "171", 640083, 640333) in initial)
    page._seek(640.208)
    QTest.qWait(600)
    capture("05-gap-before")
    menu_actions = []
    def activate():
        menu = QApplication.activePopupWidget()
        if isinstance(menu, QMenu):
            menu_actions.extend(action.text() for action in menu.actions())
            action = next((action for action in menu.actions() if "衔接 0.5 秒以内" in action.text()), None)
            if action:
                action.trigger()
            menu.close()
    index = page.undo_stack.index()
    button = page.auto_stacking_toggle
    QTimer.singleShot(120, activate)
    pos = button.rect().center()
    QApplication.sendEvent(button, QContextMenuEvent(QContextMenuEvent.Mouse, pos, button.mapToGlobal(pos)))
    check("gaps_real_menu_action", any("衔接 0.5 秒以内" in label for label in menu_actions), menu_actions)
    check("gaps_one_undo_step", page.undo_stack.index() == index+1 and page.undo_stack.undoText() == "衔接短间隙")
    check("gaps_all_short_intervals_closed", not gaps(p), gaps(p))
    after = copy.deepcopy(p.cues)
    changed_other = []
    outside_bound = []
    for left, right in zip(before, after):
        expected = copy.deepcopy(left)
        expected.end_ms = right.end_ms
        if expected != right:
            changed_other.append(left.id)
        if not 0 <= right.end_ms-left.end_ms <= 500:
            outside_bound.append(left.id)
    check("gaps_only_ends_changed", not changed_other, changed_other)
    check("gaps_extensions_bounded_500ms", not outside_bound, outside_bound)
    check("gaps_translation_records_unchanged", snapshot(p) == translations)
    check("gaps_media_and_styles_unchanged", (p.media,p.media_pool,p.video_tracks,p.audio_tracks,p.styles,p.speakers) == media)
    check("gaps_measured_words_unchanged", p.generation_metadata.get("cue_forced_alignment") == words)
    page.undo_stack.undo()
    check("gaps_undo_restores_all_times", p.cues == before and gaps(p) == initial)
    page.undo_stack.redo()
    check("gaps_redo_restores_closed_ends", p.cues == after and not gaps(p))
    # Half-open display intervals: one original, and its translation, throughout
    # the former gap; the next cue takes over at exactly the shared endpoint.
    display = project_display_cues(p)
    samples = [640083, 640125, 640166, 640208, 640250, 640291, 640333, 640375]
    visible = {ms:[c.id for c in display if c.start_ms <= ms < c.end_ms] for ms in samples}
    check("gaps_no_empty_frame_or_duplicate", all(len(ids) == 2 and len(set(ids)) == 2 for ids in visible.values()), visible)
    check("gaps_expected_handoff_ids", "170" in visible[640208] and "171" in visible[640333])
    page._seek(640.208)
    QTest.qWait(600)
    capture("06-gap-closed")
    page.project_controller.save()
    path = Path(page.project_path)
    disk = load_project(path)
    check("gaps_saved_no_short_intervals", not gaps(disk))
    page.project_controller.show_project_hub(skip_dirty_guard=True)
    window.open_studio_project(str(path), mode="edit", source="short_gap_handoff_audit")
    wait(lambda: page.project is not None and page.project is not p and page._readiness.ready, "gap project reopen failed")
    check("gaps_reopen_keeps_translation_and_timing", not gaps(page.project) and snapshot(page.project) == translations)
    result = {"before_count": len(initial), "after_count": len(gaps(page.project)), "before": initial,
              "frame_samples": visible, "project": str(path)}
    (Path(output)/"short-gaps.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
