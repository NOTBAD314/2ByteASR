"""Windows check of timing gestures and the native media transport."""
from __future__ import annotations

import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(400, lambda: run(window, output))


def run(window, output):
    from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
    from PySide6.QtGui import QInputMethodEvent, QKeyEvent, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit, QPushButton, QSpinBox

    app = QApplication.instance()
    checks = []
    error = None
    page = None

    def check(name, value, detail=None):
        checks.append(dict(name=name, passed=bool(value), detail=detail))
        if not value:
            raise AssertionError(f"{name}: {detail}")

    def wait(test, timeout=20):
        deadline = time.monotonic() + timeout
        while not test():
            if time.monotonic() > deadline:
                return False
            app.processEvents()
            time.sleep(.01)
        return True

    try:
        window.resize(1560, 980)
        window.open_studio_project(str(output / "fixture.2byteproj"))
        check("Studio page opened", wait(lambda: window.built_page("studio") is not None
              and window.built_page("studio").project is not None, 40))
        page = window.studio_page
        check("Native preview ready", wait(lambda: page.video._startup_state == "READY", 40))
        check("Loading overlay cleared", wait(lambda: getattr(window, "_studio_loading_session", None) is None
              or not window._studio_loading_session.active
              and not window._studio_loading_session.view.isVisible(), 35))
        page.video.set_paused(True)
        app.setActiveWindow(window)
        timeline = page.timeline
        timeline.setFocus()
        timeline.set_visible_window(0, 12000)
        def sample_cue():
            return next((cue for cue in timeline._timeline_cue_by_id.values()
                         if cue.text == "English timing sample."), None)

        check("Saved subtitle projected to timeline", wait(sample_cue),
              (list(timeline._timeline_cue_by_id), [cue.id for cue in page.project.cues]))
        cue = sample_cue()
        rect = timeline._track_layout()[0][cue.speaker_id]
        target = QPoint(round(timeline._time_to_x(cue.start_ms + 500)), rect.center().y())
        zoom = timeline.visible_duration_ms
        hit, _ = timeline._cue_at(target)
        check("Pointer hits subtitle body", hit is not None and hit.id == cue.id,
              (target.x(), target.y(), timeline.width(), timeline.height()))
        emitted = []
        timeline.cue_start_requested.connect(emitted.append)
        QTest.mouseDClick(timeline, Qt.LeftButton, Qt.NoModifier, target)
        check("Double click dispatches exactly once", emitted == [cue.id], emitted)
        check("Double click selects and seeks to start",
              wait(lambda: page.selected_cue_id == cue.id and abs(timeline.playhead_ms - cue.start_ms) <= 45),
              (page.selected_cue_id, timeline.playhead_ms))
        check("Zoom, paused state and editor", timeline.visible_duration_ms == zoom and page.video._paused
              and timeline._inline_editor is None)
        window.grab().save(str(output / "timeline-double-click.png"))

        def key(code):
            timeline.setFocus()
            QTest.keyClick(timeline, code)

        def finished():
            playback = page._review_playback
            return playback is not None and playback.finished and page.video._paused

        for code, name, interval in [(Qt.Key_F6, "Head", (2000, 3000)),
                                     (Qt.Key_F7, "Tail", (4000, 5000)),
                                     (Qt.Key_F5, "Full", (2000, 5000))]:
            key(code)
            playback = page._review_playback
            check(name + " requested interval", playback is not None and
                  (playback.start_ms, playback.stop_ms) == interval)
            check(name + " stopped on the media clock", wait(finished) and
                  abs(timeline.playhead_ms - interval[1]) <= 180, timeline.playhead_ms)
        key(Qt.Key_F8)
        generation = page._review_play_generation
        check("Loop restarts at the same cue", wait(lambda: page._review_play_generation > generation, 10)
              and page._review_playback.repeat)
        key(Qt.Key_F8)
        check("Loop toggle stops", page._review_playback is None and page.video._paused)
        window.grab().save(str(output / "caption-audition.png"))
        page._seek(3.0)
        check("Playhead at the intended split", wait(lambda: abs(timeline.playhead_ms - 3000) <= 20),
              timeline.playhead_ms)
        QTest.keyClick(timeline, Qt.Key_S, Qt.ControlModifier | Qt.ShiftModifier)
        check("Split at the playhead instead of the midpoint", wait(lambda: len(page.project.cues) == 2),
              [cue.text for cue in page.project.cues])
        left, right = sorted(page.project.cues, key=lambda cue: cue.start_ms)
        check("Split respects measured word boundaries",
              (left.end_ms, right.start_ms, left.text.strip(), right.text.strip()) ==
              (3000, 3000, "English", "timing sample."))
        page.undo_stack.undo()
        check("Undo restores the original subtitle", len(page.project.cues) == 1)
        page.select_cue(cue.id)
        QTest.keyClick(timeline, Qt.Key_Return, Qt.ControlModifier)
        check("Insert after uses an available interval", len(page.project.cues) == 2)
        inserted = next(item for item in page.project.cues if item.id != cue.id)
        check("Blank subtitle inherits speaker and style",
              (inserted.start_ms, inserted.end_ms, inserted.text, inserted.speaker_id, inserted.style_id) ==
              (5000, 7000, "", cue.speaker_id, cue.style_id))
        page._cancel_bound_caption_editor(trigger='acceptance_cleanup')
        if len(page.project.cues) > 1:
            page.undo_stack.undo()
        page.select_cue(cue.id)
        QTest.keyClick(timeline, Qt.Key_Return, Qt.ControlModifier | Qt.ShiftModifier)
        before = next((item for item in page.project.cues if item.id != cue.id), None)
        check("Insert before respects the available same-lane gap", before is not None
              and (before.start_ms, before.end_ms, before.speaker_id, before.style_id) ==
              (0, 2000, cue.speaker_id, cue.style_id))
        page._cancel_bound_caption_editor(trigger='acceptance_cleanup')
        if len(page.project.cues) > 1:
            page.undo_stack.undo()
        page.select_cue(cue.id)
        from ..projects.project_range import set_range
        set_range(page.project, 6600, 7950)
        QTest.keyClick(timeline, Qt.Key_Return, Qt.ControlModifier | Qt.AltModifier)
        ranged = next((item for item in page.project.cues if item.id != cue.id), None)
        check("I/O shortcut inserts on the project clock", ranged is not None
              and (ranged.start_ms, ranged.end_ms, ranged.speaker_id, ranged.style_id) ==
              (6600, 7950, cue.speaker_id, cue.style_id))
        page._cancel_bound_caption_editor(trigger='acceptance_cleanup')
        if len(page.project.cues) > 1:
            page.undo_stack.undo()
        set_range(page.project, None, None)
        page.select_cue(cue.id)
        page.spectrogram_toggle.setChecked(True)
        page.waveform_toggle.setChecked(False)
        check("Spectrogram remains visible with waveform hidden",
              timeline.audio_layers_visible and not timeline.waveform_visible and bool(timeline._audio_track_rects()))
        check("Real decoded spectrum tiles reach the visible viewport",
              wait(lambda: any(image is not None for image in timeline._spectrogram_tiles._tiles.values()), 25))
        window.grab().save(str(output / "spectrogram.png"))
        page.spectrogram_toggle.setChecked(False)
        page.waveform_toggle.setChecked(True)
        page.precise_timing_toggle.click()
        check("Precision mode uses the same project and waveform", timeline.waveform_timing.enabled
              and timeline.project is page.project and timeline.waveform_visible)
        audio = next(iter(timeline._audio_track_rects().values()), None)
        check("Waveform is visible for timing", audio is not None)

        def wave_position(milliseconds):
            return QPoint(round(timeline._time_to_x(milliseconds)), round(audio.center().y()))

        old_count = page.undo_stack.index()
        position = wave_position(2700)
        check("Pointer hits the editable waveform",
              timeline.waveform_timing.waveform_at(position) is not None and timeline.waveform_timing.cue() is not None,
              (position.x(), position.y(), str(audio), str(timeline._track_viewport()),
               timeline.selected_id, list(timeline.selected_ids)))
        QTest.mousePress(timeline, Qt.LeftButton, Qt.NoModifier, position)
        check("Waveform captures gesture", timeline.waveform_timing.gesture is not None)
        check("Pointer down alone creates no edit", page.undo_stack.index() == old_count)
        QTest.mouseRelease(timeline, Qt.LeftButton, Qt.NoModifier, position)
        check("Waveform left click sets cue start", abs(page.project.cues[0].start_ms - 2700) <= 15
              and page.undo_stack.index() == old_count + 1, page.project.cues[0].start_ms)
        position = wave_position(4600)
        QTest.mouseClick(timeline, Qt.RightButton, Qt.NoModifier, position)
        check("Waveform right click sets cue end", abs(page.project.cues[0].end_ms - 4600) <= 15,
              page.project.cues[0].end_ms)
        page.select_cue(cue.id)
        original = (page.project.cues[0].start_ms, page.project.cues[0].end_ms)
        old_count = page.undo_stack.index()
        QTest.mousePress(timeline, Qt.LeftButton, Qt.NoModifier, wave_position(3100))
        QTest.mouseMove(timeline, wave_position(4050))
        check("Drag previews without committing per pointer move",
              cue.id in timeline._timing_preview and page.undo_stack.index() == old_count)
        QTest.mouseRelease(timeline, Qt.LeftButton, Qt.NoModifier, wave_position(4050))
        check("Waveform drag commits one transaction", page.undo_stack.index() == old_count + 1 and
              abs(page.project.cues[0].start_ms - 3100) <= 15 and abs(page.project.cues[0].end_ms - 4050) <= 15)
        page.undo_stack.undo()
        check("Waveform drag undo restores both endpoints",
              (page.project.cues[0].start_ms, page.project.cues[0].end_ms) == original)
        window.grab().save(str(output / "waveform-timing.png"))
        page.precise_timing_toggle.click()
        check("Return to editing without reopening the project", not timeline.waveform_timing.enabled
              and timeline.project is page.project)
        from ..studio.studio_exact_timing import show

        def enter_exact_values():
            dialog = page.findChild(QDialog, "ExactCaptionTiming")
            dialog.findChild(QLineEdit, "ExactCaptionStart").setText("00:00:02.701")
            dialog.findChild(QLineEdit, "ExactCaptionEnd").setText("00:00:04.609")
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()

        QTimer.singleShot(0, enter_exact_values)
        show(page)
        check("Exact dialog commits integer milliseconds", (page.project.cues[0].start_ms,
              page.project.cues[0].end_ms) == (2701, 4609))
        from ..projects.studio_project import load_project, save_project
        from ..exports.studio_subtitle_export import compile_srt

        copied = output / "timing-roundtrip.2byteproj"
        save_project(page.project, copied)
        reloaded = load_project(copied)
        check("Project save and reopen preserve milliseconds",
              (reloaded.cues[0].start_ms, reloaded.cues[0].end_ms) == (2701, 4609))
        exported = output / "timing-roundtrip.srt"
        exported.write_text(compile_srt(reloaded.cues), "utf8")
        check("SRT output preserves milliseconds", "00:00:02,701 --> 00:00:04,609" in exported.read_text("utf8"))
        from ..studio.studio_batch_timing import show as show_batch

        def preview_batch():
            dialog = page.findChild(QDialog, "BatchCaptionTiming")
            dialog.findChild(QSpinBox, "BatchCaptionTiming_shift").setValue(50)
            dialog.findChild(QPushButton, "PreviewBatchCaptionTiming").click()
            after_preview = page.project.cues[0].start_ms
            dialog.setProperty("startAfterPreview", after_preview)
            dialog.findChild(QPushButton, "ApplyBatchCaptionTiming").click()

        count = page.undo_stack.index()
        QTimer.singleShot(0, preview_batch)
        show_batch(page)
        dialog = page.findChild(QDialog, "BatchCaptionTiming")
        check("Batch preview does not change the project", dialog.property("startAfterPreview") == 2701)
        check("Batch applies the requested shift as one undoable transaction",
              page.project.cues[0].start_ms == 2751 and page.project.cues[0].end_ms == 4659
              and page.undo_stack.index() == count + 1)
        page.undo_stack.undo()
        check("Batch undo restores both endpoints", page.project.cues[0].start_ms == 2701
              and page.project.cues[0].end_ms == 4609)

        row = page.project.cues[0]
        original_text = row.text
        original_timing = row.start_ms, row.end_ms
        before_ime = page.undo_stack.index()
        page.select_cue(row.id)
        page._open_caption_editor(row.id, "original")
        editor = page.subtitle_edit_input
        check("Caption editor is bound for the composition test", page._caption_draft.target.cue_id == row.id)
        editor.moveCursor(QTextCursor.MoveOperation.End)
        QApplication.sendEvent(editor, QInputMethodEvent("編輯", []))
        check("Qt composition records a Chinese preedit", editor._preediting)
        for code in (Qt.Key_F5, Qt.Key_F6, Qt.Key_F7, Qt.Key_F8, Qt.Key_I, Qt.Key_O):
            QTest.keyClick(editor, code)
        from ..projects.project_range import range_points
        check("Timeline shortcuts leave active composition and timeline intact",
              editor._preediting and page._review_playback is None and range_points(page.project) == (None, None)
              and page.undo_stack.index() == before_ime)
        committed_before_escape = editor.toPlainText()
        QTest.keyClick(editor, Qt.Key_Escape)
        check("Escape cancels preedit and keeps the bound caption editor",
              not editor._preediting and page._caption_draft is not None
              and editor.toPlainText() == committed_before_escape,
              (editor._preediting, page._caption_draft is not None, editor.toPlainText()))
        editor.setPlainText(original_text)
        editor.moveCursor(QTextCursor.MoveOperation.End)
        QApplication.sendEvent(editor, QInputMethodEvent("にほんご", []))
        committed = QInputMethodEvent()
        committed.setCommitString("日本語")
        QApplication.sendEvent(editor, committed)
        check("Qt candidate commit becomes editable Japanese text",
              not editor._preediting and editor.toPlainText() == original_text + "日本語"
              and page.project.cues[0].text == original_text)
        QApplication.sendEvent(editor, QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Return, Qt.NoModifier))
        check("Candidate confirmation key does not save the caption",
              page._caption_draft is not None and page.undo_stack.index() == before_ime)
        QTest.qWait(20)
        QTest.keyClick(editor, Qt.Key_Return)
        check("Editor confirmation applies the Japanese draft once",
              page._caption_draft is None and page.project.cues[0].text == original_text + "日本語"
              and page.undo_stack.index() == before_ime + 1
              and (page.project.cues[0].start_ms, page.project.cues[0].end_ms) == original_timing)
        page.undo_stack.undo()
        check("Undo restores the original subtitle after composition", page.project.cues[0].text == original_text)

        from ..studio import shortcut_registry

        page.cue_controller.set_text(row.id, "他说现在就到。")
        page._set_review_mode(True)
        page.select_cue(row.id)
        timeline.setFocus()
        QTest.keyClick(timeline, Qt.Key_F, Qt.ShiftModifier)
        check("Default review shortcut changes one target pronoun", page.project.cues[0].text == "她说现在就到。")
        shortcut_registry.save_values({"review_flip_pronoun": "F4"})
        QTest.keyClick(timeline, Qt.Key_F, Qt.ShiftModifier)
        check("Rebinding the review shortcut releases the old key", page.project.cues[0].text == "她说现在就到。")
        QTest.keyClick(timeline, Qt.Key_F4)
        check("Rebound review shortcut uses the same target", page.project.cues[0].text == "它说现在就到。")
    except Exception:
        error = traceback.format_exc()
        window.grab().save(str(output / "failure.png"))
    finally:
        (output / "result.json").write_text(json.dumps(
            dict(passed=error is None and bool(checks), checks=checks, error=error),
            ensure_ascii=False, indent=2), "utf8")
        if page is not None:
            page.undo_stack.setClean()
        window.close()
        app.quit()
