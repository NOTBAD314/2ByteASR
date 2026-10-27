"""Opt-in manual translation acceptance against a copied real project."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

from .studio_acceptance_audit import require


def run(output, window):
    from PySide6.QtCore import QPoint, QTimer, Qt, qInstallMessageHandler
    from PySide6.QtGui import QContextMenuEvent, QInputMethodEvent, QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu
    from ..projects.studio_project import load_project
    from ..subtitle_rules import subtitle_translation as st
    from ..exports.studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts, verify_subtitle_artifact
    from ..caption_style.bilingual_layout import project_display_cues
    from .blank_project_audit import _capture
    from . import blank_project_audit

    output = Path(output)
    require(Path(os.environ["TWOBYTEASR_TEST_ROOT"]).resolve() == output.resolve())
    result = {"passed": False, "checks": [], "screenshots": [], "pid": os.getpid(),
              "entry": "quick_start.py normal MainWindow", "executable": sys.executable,
              "platform": QApplication.platformName(), "frozen": bool(getattr(sys, "frozen", False)),
              "ime_scope": "Qt preedit/commit; physical input method not covered"}
    page = window.studio_page
    result["clipboard_warnings"] = []
    def qt_message(kind, context, message):
        if "clipboard" in message.lower() or "ole" in message.lower():
            result["clipboard_warnings"].append(message)
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes as W
                user = ctypes.windll.user32
                user.GetOpenClipboardWindow.restype = W.HWND
                user.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
                hwnd = user.GetOpenClipboardWindow()
                pid = W.DWORD()
                user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                result["clipboard_locker"] = {"hwnd": hwnd, "pid": pid.value}
        if old_message_handler:
            old_message_handler(kind, context, message)
    old_message_handler = qInstallMessageHandler(qt_message)

    def receipt():
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(name, condition, detail=None):
        result["checks"].append({"name": name, "passed": bool(condition), "detail": detail})
        receipt()
        require(condition, name)

    def wait(predicate, message, seconds=60):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(50)
        require(predicate(), message)

    def capture(name):
        QTest.qWait(150)
        path = output / (name + ".png")
        _capture(window, path)
        result["screenshots"].append(str(path))
        receipt()

    def external_text(value):
        # A fixture writer can retry an OS clipboard lock just like an external
        # application's Copy command; it must verify ownership before pasting.
        for attempt in range(5):
            QApplication.clipboard().setText(value)
            if QApplication.clipboard().ownsClipboard() and QApplication.clipboard().text() == value:
                result.setdefault("fixture_clipboard_attempts", []).append(attempt+1)
                return
            QTest.qWait(180)
        raise AssertionError("External clipboard fixture could not acquire Windows clipboard")

    try:
        window.open_studio_project(os.environ["TWOBYTEASR_STARTUP_PROJECT"], mode="edit", source="manual_translation_audit")
        wait(lambda: page.project is not None and getattr(page, "_readiness", None) and page._readiness.ready,
             "real project did not become ready")
        window.resize(1600, 1000)
        window.show()
        QApplication.setActiveWindow(window)
        p = page.project
        cue_id = os.environ.get("TWOBYTEASR_MANUAL_TRANSLATION_CUE", "171")
        cue = next(cue for cue in p.cues if cue.id == cue_id)
        page._set_bilingual_mode(True)
        t = page.timeline
        t.set_visible_window(cue.start_ms - 7000, 22000)
        page.select_cue(cue_id)
        page._seek((cue.start_ms + 417) / 1000)
        QTest.qWait(900)
        baseline_cues = copy.deepcopy(p.cues)
        baseline_media = copy.deepcopy((p.media, p.media_pool, p.video_tracks, p.audio_tracks, p.speakers, p.styles))
        baseline_view = dict(p.generation_metadata.get("translations", {}))
        baseline_counts = st.status_counts(p)
        result["source_cue"] = {"id": cue_id, "text": cue.text, "start_ms": cue.start_ms, "end_ms": cue.end_ms}
        result["counts_before"] = baseline_counts
        check("real_missing_translation", not baseline_view.get(cue_id))
        check("real_player_loaded", page.video.controller is not None)
        check("no_api_configured", not blank_project_audit._provider_calls)
        track = t._track_layout()[1]
        pos = QPoint(round(t._time_to_x(cue.start_ms + 417)), round(track.center().y()))
        check("translation_position_visible", t._track_viewport().contains(pos))
        capture("01-missing")
        QTest.mouseDClick(t, Qt.LeftButton, pos=pos)
        check("double_click_targets_missing_cue", t._inline_target == (cue_id, True))
        editor = t._inline_editor
        text = "但 DaVinci YRGB\n采用色彩管理"
        external_text(text)
        QTest.keySequence(editor, QKeySequence(QKeySequence.StandardKey.Paste))
        capture("02-pasted-draft")
        QTest.keyClick(editor, Qt.Key_Return)
        check("manual_record_committed", st.records_of(p)[cue_id]["origin"] == "manual")
        check("failure_resolved", st.cue_status(p, cue_id) == "manual" and "error" not in st.records_of(p)[cue_id])
        check("panel_identifies_translation", "译文" in page.current_text_layer_label.text())
        check("panel_has_saved_text", page.translation_text.toPlainText() == text)
        t.setFocus()
        for attempt in range(5):
            QTest.keySequence(t, QKeySequence(QKeySequence.StandardKey.Copy))
            if QApplication.clipboard().text() == text:
                result["copy_shortcut_attempts"] = attempt+1
                break
            check("clipboard_busy_is_visible", "剪贴板正忙" in page.save_state.text(), page.save_state.text())
            QTest.qWait(180)
        check("standard_copy_is_plain_translation", QApplication.clipboard().text() == text)
        (output / "clipboard.txt").write_text(QApplication.clipboard().text(), encoding="utf-8")
        if sys.platform == "win32" and not getattr(sys, "frozen", False):
            import subprocess
            external_receipt = output / "external-clipboard.json"
            child = subprocess.Popen([sys.executable, str(Path(__file__).with_name("native_clipboard_probe.py")), str(external_receipt)],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            wait(lambda: child.poll() is not None, "external clipboard reader timed out", seconds=10)
            external = json.loads(external_receipt.read_text(encoding="utf-8"))
            check("independent_external_unicode_clipboard", child.returncode == 0 and external["text"].replace("\r\n", "\n") == text,
                  external)
        check("one_edit_one_undo", page.undo_stack.command(page.undo_stack.index()-1).text() == "编辑译文")
        QTest.keySequence(t, QKeySequence(QKeySequence.StandardKey.Undo))
        check("undo_restores_failure_counts", st.status_counts(p) == baseline_counts)
        QTest.keySequence(t, QKeySequence(QKeySequence.StandardKey.Redo))
        check("redo_restores_manual_text", p.generation_metadata["translations"][cue_id] == text)
        capture("03-manual-translation")

        # Exercise a real context menu, with a Qt action on the observed text.
        actions_seen = []
        def pick_copy():
            menu = QApplication.activePopupWidget()
            if not isinstance(menu, QMenu):
                menu = next((w for w in QApplication.topLevelWidgets() if isinstance(w, QMenu) and w.isVisible()), None)
            if menu is not None:
                actions_seen.extend(a.text() for a in menu.actions())
                action = next((a for a in menu.actions() if a.text() == "复制译文"), None)
                if action:
                    action.trigger()
                menu.close()
        QTimer.singleShot(120, pick_copy)
        QApplication.sendEvent(t, QContextMenuEvent(QContextMenuEvent.Mouse, pos, t.mapToGlobal(pos)))
        check("context_menu_preserves_translation_layer", "编辑译文" in actions_seen and "复制译文" in actions_seen, actions_seen)
        if QApplication.clipboard().text() != text:
            check("context_clipboard_busy_is_visible", "剪贴板正忙" in page.save_state.text(), page.save_state.text())
            QTest.qWait(180)
            QTimer.singleShot(120, pick_copy)
            QApplication.sendEvent(t, QContextMenuEvent(QContextMenuEvent.Mouse, pos, t.mapToGlobal(pos)))
        check("context_copy_text", QApplication.clipboard().text() == text)

        t.setFocus()
        QTest.keyClick(t, Qt.Key_Delete)
        check("delete_clears_only_translation", st.cue_status(p, cue_id) == "untranslated" and p.cues == baseline_cues)
        QTest.keySequence(t, QKeySequence(QKeySequence.StandardKey.Undo))
        check("clear_undo_manual", p.generation_metadata["translations"][cue_id] == text)

        source = st.translation_source(p)
        pending = st.TranslationResult("zh-Hans", "offline-replay", "fake", overwrite_manual=True,
            project_instance=source.project_instance, project_id=source.project_id, content_revisions=dict(source.content_revisions), revisions=dict(source.revisions), baseline_records=dict(source.records),
            target_at_start=source.target_at_start, sources={cue_id: cue.text})
        pending.translations[cue_id] = st.TranslatedItem(cue_id, "迟到内容", cue.text, st.source_sha(cue.text), "")
        failure = copy.deepcopy(pending)
        failure.translations.clear()
        failure.failed[cue_id] = "provider_error:offline"
        QTest.mouseDClick(t, Qt.LeftButton, pos=pos)
        editor = t._inline_editor
        playhead, scroll = t.playhead_ms, t.visible_start_ms
        QApplication.sendEvent(editor, QInputMethodEvent("中文", []))
        QTest.keyClick(editor, Qt.Key_Return)
        check("ime_enter_does_not_submit", t._inline_editor is editor)
        commit = QInputMethodEvent()
        commit.setCommitString("中文")
        QApplication.sendEvent(editor, commit)
        QTest.keyClicks(editor, " WASD ")
        QTest.keyClick(editor, Qt.Key_Left)
        QTest.qWait(50)
        check("typing_keeps_clock_selection_scroll", t.playhead_ms == playhead and t.visible_start_ms == scroll and page.selected_cue_id == cue_id)
        editor.selectAll()
        external_text(text)
        check("ime_replacement_clipboard_ready", QApplication.clipboard().text() == text,
              {"text": QApplication.clipboard().text(), "owner": QApplication.clipboard().ownsClipboard(),
               "expected": text, "editor_visible": editor.isVisible(), "focus": str(QApplication.focusWidget())})
        QTest.keySequence(editor, QKeySequence(QKeySequence.StandardKey.Paste))
        check("ime_draft_replaced_by_paste", editor.toPlainText() == text,
              {"text": editor.toPlainText(), "clipboard": QApplication.clipboard().text(), "composing": editor._composing})
        QTest.keyClick(editor, Qt.Key_Return)
        expected = st.snapshot(p)
        st.apply_translation_result(p, pending)
        st.apply_translation_result(p, failure)
        check("late_success_and_failure_discarded", st.snapshot(p) == expected and set(pending.discarded) == set(failure.discarded) == {cue_id})

        # Existing add command routes to the selected translation without creating an original.
        t.setFocus()
        page.cue_controller.add_subtitle_at_playhead()
        check("add_command_opens_translation", t._inline_target == (cue_id, True) and len(p.cues) == len(baseline_cues))
        QTest.keyClick(t._inline_editor, Qt.Key_Escape)

        # Panel draft commits once, preserves target and undo state.
        page.translation_text.setFocus()
        QTest.qWait(50)
        page.translation_text.selectAll()
        external_text("DaVinci YRGB / Adobe Premiere Pro")
        index = page.undo_stack.index()
        QTest.keySequence(page.translation_text, QKeySequence(QKeySequence.StandardKey.Paste))
        check("panel_typing_is_draft", page.undo_stack.index() == index)
        QTest.keyClick(page.translation_text, Qt.Key_Return)
        check("panel_commit_one_step", page.undo_stack.index() == index+1 and st.cue_status(p, cue_id) == "manual",
              {"before": index, "after": page.undo_stack.index(), "text": page.translation_text.toPlainText(),
               "binding": str(page.translation_text.binding[1:]) if page.translation_text.binding else None,
               "dirty": page.translation_text.dirty, "composing": page.translation_text.composing,
               "visible": page.translation_text.isVisible(), "enabled": page.translation_text.isEnabled(),
               "record": st.records_of(p).get(cue_id)})
        page.undo_stack.undo()
        check("panel_undo_restores_text", p.generation_metadata["translations"][cue_id] == text)

        # Daily integration: existing Markdown and language-layer controls survive.
        tools = getattr(page, "translation_text_tools", None)
        if tools is not None:
            from ..caption_style.text_marks import layer_marks
            tools.mode.setCurrentIndex(1)
            page.translation_text.setFocus()
            page.translation_text.selectAll()
            external_text("使用 **DaVinci YRGB**")
            index = page.undo_stack.index()
            QTest.keySequence(page.translation_text, QKeySequence(QKeySequence.StandardKey.Paste))
            QTest.keyClick(page.translation_text, Qt.Key_Return)
            check("daily_markdown_body", st.records_of(p)[cue_id]["text"] == "使用 DaVinci YRGB")
            check("daily_markdown_marks", any(mark.get("bold") for mark in layer_marks(cue, "translation")))
            check("daily_markdown_one_undo", page.undo_stack.index() == index+1)
            page.undo_stack.undo()
            tools.mode.setCurrentIndex(0)
            check("daily_markdown_undo", p.generation_metadata["translations"][cue_id] == text)
            t.select_translation(cue_id)
            check("daily_translation_style_layer", page.style_layer.currentData() == "translation")
            t.setFocus()
            external_text("https://example.test/manual-translation")
            check("daily_native_paste_routed", page._dispatch_shortcut_sequence("Ctrl+V"))
            check("daily_native_paste_not_link_card", p.generation_metadata["translations"][cue_id] == "https://example.test/manual-translation")
            page.undo_stack.undo()
            check("daily_native_paste_undo", p.generation_metadata["translations"][cue_id] == text)

        from dataclasses import asdict
        cue_differences = [{"id": left.id, "fields": {key: [asdict(left)[key], asdict(right)[key]]
                            for key in asdict(left) if key != "appearance_generation" and asdict(left)[key] != asdict(right)[key]}}
                           for left,right in zip(baseline_cues,p.cues) if left != right]
        result["appearance_invalidation_revisions"] = [{"id": left.id, "before": left.appearance_generation,
            "after": right.appearance_generation} for left,right in zip(baseline_cues,p.cues)
            if left.appearance_generation != right.appearance_generation]
        # Appearance undo intentionally increments its invalidation revision;
        # text, timing, markup and all authored style values must still match.
        check("original_cue_content_timing_style_unchanged", len(p.cues) == len(baseline_cues)
              and not any(item["fields"] for item in cue_differences), cue_differences[:8])
        check("media_speakers_styles_unchanged", (p.media,p.media_pool,p.video_tracks,p.audio_tracks,p.speakers,p.styles) == baseline_media)
        current_view = {key: value for key, value in p.generation_metadata["translations"].items() if key != cue_id}
        check("neighbor_translations_unchanged", current_view == {key: value for key, value in baseline_view.items() if key != cue_id})
        display = project_display_cues(p)
        check("preview_materializes_saved_translation_once", sum(c.text == text for c in display) == 1)
        page.project_controller.save()
        saved_path = Path(page.project_path)
        saved = load_project(saved_path)
        check("disk_has_manual_record", st.records_of(saved)[cue_id]["text"] == text and st.records_of(saved)[cue_id]["origin"] == "manual")
        previous = page.project
        check("close_saved_project", page.project_controller.show_project_hub(skip_dirty_guard=True))
        window.open_studio_project(str(saved_path), mode="edit", source="manual_translation_audit")
        wait(lambda: page.project is not None and page.project is not previous and page._readiness.ready, "reopen did not finish")
        p = page.project
        check("reopen_keeps_record_and_style", st.records_of(p)[cue_id] == st.records_of(saved)[cue_id] and p.styles == saved.styles)
        page.select_cue(cue_id)
        page.timeline.set_visible_window(cue.start_ms - 7000, 22000)
        page.timeline.select_translation(cue_id)
        page._seek((cue.start_ms + 417)/1000)
        capture("04-saved-reopened")
        artifacts = export_subtitle_artifacts(p, output / "exports", "DaVinci-manual-bilingual",
                                             SubtitleExportOptions(frozenset({"srt", "ass", "json"}), "combined"))
        result["artifacts"] = []
        for artifact in artifacts:
            from ..exports.studio_subtitle_export import _display_text_cues, _export_view_cues
            expected = copy.copy(p)
            expected.cues = (_display_text_cues(p) if artifact.format == "srt"
                             else project_display_cues(p, _export_view_cues(p)) if artifact.format == "ass"
                             else _export_view_cues(p))
            validation = verify_subtitle_artifact(artifact, expected)
            check("export_" + artifact.format + "_readback", validation.valid, validation.first_mismatch)
            body = artifact.path.read_text(encoding="utf-8-sig")
            check("export_" + artifact.format + "_has_translation", "DaVinci YRGB" in body and "采用色彩管理" in body)
            result["artifacts"].append({"format": artifact.format, "path": str(artifact.path),
                                        "sha256": hashlib.sha256(artifact.path.read_bytes()).hexdigest()})
        result["counts_after"] = st.status_counts(p)
        if os.environ.get("TWOBYTEASR_CHECK_SHORT_GAPS") == "1":
            from .short_gap_handoff_audit import run as verify_gaps
            result["short_gaps"] = verify_gaps(page, window, output, check=check, wait=wait, capture=capture)
        check("no_provider_calls", blank_project_audit._provider_calls == 0)
        check("no_external_network", not blank_project_audit._blocked_external_connections,
              blank_project_audit._blocked_external_connections)
        result["passed"] = True
    except Exception:
        result["error"] = traceback.format_exc()
        try:
            capture("failure")
        except Exception:
            pass
    finally:
        page.undo_stack.setClean()
        QApplication.clipboard().clear()
        qInstallMessageHandler(old_message_handler)
        receipt()
    return 0 if result["passed"] else 1


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    def execute():
        code = run(output, window)
        window.result_exit_code = code
        def stopped():
            path = Path(output) / "result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result["gui_shutdown"] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    if os.environ.get("TWOBYTEASR_MANUAL_TRANSLATION_INTERACTIVE") == "1":
        def open_interactive():
            window.open_studio_project(os.environ["TWOBYTEASR_STARTUP_PROJECT"], mode="edit", source="manual_translation_interactive")
            def locate():
                page = window.studio_page
                if page.project is None or not getattr(page, "_readiness", None) or not page._readiness.ready:
                    QTimer.singleShot(250, locate)
                    return
                cue_id = os.environ.get("TWOBYTEASR_MANUAL_TRANSLATION_CUE", "171")
                cue = next(c for c in page.project.cues if c.id == cue_id)
                page._set_bilingual_mode(True)
                page.select_cue(cue_id)
                page.timeline.set_visible_window(cue.start_ms-7000, 22000)
                page._seek((cue.start_ms+417)/1000)
                window.setWindowTitle("兔白字幕 · 手动补译验收副本")
            QTimer.singleShot(250, locate)
        QTimer.singleShot(150, open_interactive)
    else:
        QTimer.singleShot(150, execute)
