"""Normal Windows Studio, real selected Qwen/HTDemucs and playback controls."""
import json
import os
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from ..timeline.selection_scope import SelectionScope

    result = {"checks": [], "passed": False}
    deadline = time.perf_counter() + 300

    def check(name, agrees):
        result["checks"].append({"name": name, "passed": bool(agrees)})
        if not agrees:
            raise AssertionError(name)

    def workflow():
        while True:
            page = window.built_page("studio")
            if page and page.project and page._readiness.ready:
                break
            yield False
        page.runtime_settings.setdefault("models", {}).update(primary_asr_backend="qwen_local", qwen_asr_backend="local")
        project = page.project
        baseline = tuple((cue.id, cue.text, cue.start_ms, cue.end_ms) for cue in project.cues)
        page.cue_controller.apply_selection_scope(SelectionScope.explicit(
            ("audio-enhance", "audio-original", "protected"), "audio-enhance"))
        action = page.ai_reasr_auto_audio_action
        action.parent().aboutToShow.emit()
        check("real menu action is enabled for selected audio", action.isEnabled())
        overlap_playback = os.environ.get("TWOBYTEASR_AUDIT_BACKGROUND_PLAYBACK") == "1"
        playback_start = int(page.timeline.playhead_ms)
        if overlap_playback:
            page.video.set_paused(False)
        action.trigger()
        task = page._reasr_task
        concurrent_advance = 0
        while task.ended is None:
            if overlap_playback:
                concurrent_advance = max(concurrent_advance, int(page.timeline.playhead_ms) - playback_start)
            yield False
        if overlap_playback:
            check("Audio clock advances while actual Qwen background work is active", concurrent_advance > 750)
            result["audio_advance_during_recognition_ms"] = concurrent_advance
            page.video.set_paused(True)
            page._seek(0.)
        check("confirmed caption did not enter inference", set(task.cue_ids) == {"audio-enhance", "audio-original"})
        check("only confirmed music selects enhancement", {
            cue_id: item.audio_source for cue_id, item in task.results.items()
        } == {"audio-enhance": "htdemucs", "audio-original": "original"})
        check("real Qwen returned two unapplied drafts",
              all(task.rows[key]["status"] == "suggestion" for key in task.cue_ids))
        check("draft stage keeps source text and cue edges", baseline == tuple(
            (cue.id, cue.text, cue.start_ms, cue.end_ms) for cue in project.cues))
        panel = page._subtitle_task_panel()
        check("task results are visible", panel.isVisible())
        for row, key in enumerate(panel._row_keys):
            if key == "audio-enhance":
                panel.table.selectRow(row)
                break
        yield False
        check("enhanced result presents A/B transport and two waveform envelopes",
              panel.listen_enhanced.isVisible() and panel.listen_original.isVisible()
              and panel.voice_comparison.isVisible() and all(panel.voice_comparison.peaks))

        # Mute this isolated test output only. QMediaPlayer still decodes the file.
        page._reasr_preview_player = QMediaPlayer(page)
        page._reasr_preview_audio = QAudioOutput(page)
        page._reasr_preview_audio.setMuted(True)
        page._reasr_preview_player.setAudioOutput(page._reasr_preview_audio)
        QTest.mouseClick(panel.listen_enhanced, Qt.MouseButton.LeftButton)
        wait_end = time.perf_counter() + 8
        while page._reasr_preview_player.position() <= 150 and time.perf_counter() < wait_end:
            yield False
        check("enhanced audio really decodes on the native player", page._reasr_preview_player.position() > 150)
        QTest.mouseClick(panel.listen_original, Qt.MouseButton.LeftButton)
        wait_end = time.perf_counter() + 10
        while int(page.timeline.playhead_ms) < 150 and time.perf_counter() < wait_end:
            yield False
        check("A/B switch stops the alternate player", page._reasr_preview_player.playbackState() ==
              QMediaPlayer.PlaybackState.StoppedState)
        check("original audio advances the source clock", int(page.timeline.playhead_ms) >= 150)
        page.video.set_paused(True)

        before = page.undo_stack.index()
        QTest.mouseClick(panel.adopt_button, Qt.MouseButton.LeftButton)
        check("explicit adoption applies with one undo step",
              page.undo_stack.index() == before + 1 and task.rows["audio-enhance"]["status"] == "applied")
        check("changed text matches the reviewed candidate",
              next(c.text for c in project.cues if c.id == "audio-enhance") ==
              task.results["audio-enhance"].recommendation)
        page.undo_stack.undo()
        check("undo restores every original caption", baseline == tuple(
            (cue.id, cue.text, cue.start_ms, cue.end_ms) for cue in project.cues))
        check("undo returns the original proposal to review", task.rows["audio-enhance"]["status"] == "suggestion")
        from ..studio.studio_reasr_batch import still_current

        check("undo allows explicit readoption", still_current(page, task, "audio-enhance"))
        page.undo_stack.redo()
        check("redo projects the same adoption command", task.rows["audio-enhance"]["status"] == "applied")
        page.undo_stack.undo()

        from ..projects.project_range import set_range

        set_range(project, 250, 11000, page.undo_stack)
        range_action = page.ai_range_reasr_suggestions_action
        range_action.parent().aboutToShow.emit()
        check("I/O re-recognition is available on the actual menu", range_action.isEnabled())
        range_action.trigger()
        range_task = page._reasr_task
        check("range excludes crossing, confirmed and manually edited captions",
              range_task is not task and range_task.cue_ids == ("audio-original",))
        while range_task.ended is None:
            yield False
        check("I/O produces one real unapplied suggestion",
              range_task.rows["audio-original"]["status"] == "suggestion")
        check("I/O leaves every original caption intact", baseline == tuple(
            (cue.id, cue.text, cue.start_ms, cue.end_ms) for cue in project.cues))
        page._retry_subtitle_task_range({"task_id": range_task.task_id,
                                        "record": range_task.rows["audio-original"]})
        retry = page._reasr_task
        check("Retry handler submits only the requested row",
              retry is not range_task and retry.is_retry and retry.cue_ids == ("audio-original",))
        while retry.ended is None:
            yield False
        from ..storage.project_stage_history import latest_stages

        receipts = latest_stages(project.project_id)
        while not receipts.done():
            yield False
        check("Real retry is recorded as a pending adoption",
              any(row["stage"] == "retry" and row["outcome"] == "suggestion"
                  and row.get("source") == "re_asr_retry" for row in receipts.result()))
        panel.hide()
        page.undo_stack.setClean()

    def save():
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")

    def finish():
        timer.stop()
        result["passed"] = bool(result["checks"]) and not result.get("error") and all(
            item["passed"] for item in result["checks"])
        save()
        window.result_exit_code = 0 if result["passed"] else 1
        def shutdown():
            result["gui_shutdown"] = True
            save()
        QApplication.instance().aboutToQuit.connect(shutdown)
        QTimer.singleShot(0, window.close)

    steps = workflow()
    def tick():
        try:
            if time.perf_counter() >= deadline:
                raise TimeoutError("Local voice acceptance did not reach its next real state")
            next(steps)
        except StopIteration:
            finish()
        except Exception:
            result["error"] = traceback.format_exc()
            finish()

    timer = QTimer(window, interval=70)
    timer.timeout.connect(tick)
    timer.start()
