"""Opt-in normal-entry audit of the proofreading workspace (2026-10-10).

Runs inside the real application on a private desktop with an owned copy of
a project: Studio → AI 校对 (time to captions on screen) → every caption
listed with the inherited library, proposals marked in place → previews of
first/middle/tail captions, rapid clicks and a filtered row, each compared
with the recognition timeline audio → direct edit by double click (written
at once, one undo step) → right-click batch replace of the proposal's words
→ Ctrl+H with an input method composing, then Enter → undo → Ctrl+wheel and
Ctrl+0 interface zoom → back to Studio, where Ctrl+wheel over the timeline
still zooms time → export view → undo/redo → save → reopen. Preview audio is
decoded for real and handed to the audio device at volume 0.
"""
import json
import os
import time
import traceback
import wave
from pathlib import Path


def _band(signal, rate=16000, top=4000):
    import numpy as np
    spectrum = np.fft.rfft(signal)
    spectrum[int(len(spectrum) * top / (rate / 2)):] = 0
    return np.fft.irfft(spectrum, len(signal))


def _ncc(samples, reference):
    """Best normalized correlation within ±10 ms, on the speech band."""
    import numpy as np
    n = min(len(samples), len(reference))
    best = 0.0
    if n < 4000:
        return best
    samples, reference = _band(np.asarray(samples[:n])), _band(np.asarray(reference[:n]))
    for lag in range(-160, 161):
        a = samples[max(0, lag):n + min(0, lag)]
        b = reference[max(0, -lag):n - max(0, lag)]
        m = min(len(a), len(b))
        a, b = a[:m], b[:m]
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denominator:
            best = max(best, float(np.dot(a, b) / denominator))
    return round(best, 4)


def _post_ctrl_wheel(window, widget, delta):
    """A real Ctrl+wheel Windows message at the centre of ``widget``."""
    import ctypes
    from ctypes import wintypes
    from PySide6.QtCore import QPoint
    centre = widget.mapToGlobal(QPoint(widget.width() // 2, widget.height() // 2))
    rect = wintypes.RECT()
    hwnd = wintypes.HWND(int(window.winId()))
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    ratio = window.devicePixelRatioF() or 1.0
    frame = window.frameGeometry()
    x = rect.left + round((centre.x() - frame.x()) * ratio)
    y = rect.top + round((centre.y() - frame.y()) * ratio)
    ctypes.windll.user32.PostMessageW(hwnd, 0x020A, ((delta & 0xFFFF) << 16) | 0x0008, ((y & 0xFFFF) << 16) | (x & 0xFFFF))


def start(window, out):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity

    reference_path = os.environ.get("TWOBYTEASR_AUDIT_REFERENCE_WAV", "")

    def run():
        import numpy as np
        page = window.studio_page
        result = dict(passed=False, checks=[], build=load_build_identity().to_dict(), previews=[])

        def save():
            (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")

        def check(name, ok, detail=None):
            result["checks"].append(dict(name=name, passed=bool(ok), detail=detail))
            save()

        def pump(seconds=.25):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                QApplication.processEvents()
                time.sleep(.005)

        def wait(test, seconds=75):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                pump(.025)
                if test():
                    return True
            return False

        reference = None
        if reference_path and Path(reference_path).is_file():
            with wave.open(reference_path, "rb") as stream:
                reference = np.frombuffer(stream.readframes(stream.getnframes()), dtype=np.int16).astype(np.float64)

        def to16k(payload):
            stereo = np.frombuffer(payload, dtype=np.int16).astype(np.float64).reshape(-1, 2).mean(axis=1)
            # 48 kHz -> 16 kHz: remove content above 7.6 kHz, then decimate.
            spectrum = np.fft.rfft(stereo)
            spectrum[int(len(spectrum) * 7600 / 24000):] = 0
            return np.fft.irfft(spectrum, len(stereo))[::3]

        try:
            ready = wait(lambda: page.project and page._readiness.ready and page.video._startup_state == "READY", 180)
            check("studio ready on copied project", ready)
            if not ready:
                raise RuntimeError("studio did not become ready")
            page.volume_slider.setValue(0)
            page.video.set_paused(True)
            window.showMaximized()
            pump(.5)
            project_path = Path(page.project_path)
            cues = sorted(page.project.cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
            _capture(window, out / "01-studio.png")
            clicked_at = time.perf_counter()
            QTest.mouseClick(page.cue_proofread_button, Qt.LeftButton)
            check("AI 校对 opens the workspace", wait(lambda: getattr(window, "glossary_proofread_page", None)
                                                     is window.pages.currentWidget(), 15))
            review = window.glossary_proofread_page
            painted = wait(lambda: review.list.isVisible() and bool(review.list._hit_boxes), 15)
            open_ms = round((time.perf_counter() - clicked_at) * 1000)
            result["open_ms"] = open_ms
            check("captions are on screen within 1.5 s of the click", painted and open_ms < 1500, open_ms)
            check("every caption listed on entry", len(review._rows) == len(cues) and len(review.list.visible) == len(cues),
                  dict(rows=len(review._rows), visible=len(review.list.visible), cues=len(cues)))
            check("binds the open document", review._live_project() == (page.project, page))
            check("binds Studio's undo stack", review._stack is page.undo_stack)
            check("library inherited from recognition", "洛克王国世界" in review._selected_ids(),
                  dict(selected=review._selected_ids(), summary=review.library_summary.text()))
            check("local match only (no AI call on entry)", not review._worker_ai)
            check("local match finishes", wait(lambda: not review.checks_running(), 90))
            check("status says local, not AI", "未使用 AI" in review.status_label.text(), review.status_label.text())
            check("no proposal is written by itself", all(row["base"] == row["origin"] for row in review._rows)
                  and not any(issue["checked"] for row in review._rows for issue in row["issues"]))
            from .glossary_proofread import adopt_text, issue_pair
            rows = {row["number"]: row for row in review._rows}
            r81 = rows.get("#81")
            stammer = [i for i in (r81 or {}).get("issues", ()) if i["kind"] == "stutter" and i.get("default")]
            check("学学聪明了 is not changed to 学虫鸣了 and stammer is offered",
                  r81 is not None and not any("虫鸣" in issue["replacement"] for issue in r81["issues"])
                  and adopt_text(r81["base"], stammer) == "这次就学聪明了影袭影袭",
                  r81 and [(i["kind"], i["original"], i["replacement"], i.get("default")) for i in r81["issues"]])
            ordinary = [row["number"] for row in review._rows if "刚刚" in row["base"]
                        and any(issue["original"] == "刚刚" for issue in row["issues"])]
            check("刚刚 is not flagged", not ordinary, ordinary)
            r174 = next((row for row in review._rows if "天命之暗" in row["base"]), None)
            readings = {i["replacement"] for i in (r174 or {}).get("issues", ()) if i["kind"] == "evidence"}
            check("天命之暗 offers the FireRed/Qwen readings", {"今天运气站", "今天运气在"} <= readings,
                  r174 and [(i["kind"], i["original"], i["replacement"]) for i in r174["issues"]])
            # Proposals are marked in the sentence with the replacement under them.
            suggested = next((row for row in review._rows if any(not i["stale"] and i["replacement"]
                                                                 and i["kind"] != "suspect" for i in row["issues"])), None)
            if suggested is not None:
                review.list.ensure_visible(suggested["cue_id"])
                pump(.2)
                review.list.repaint()
                marks = [rect for rect, action, cue_id, _ in review.list._hit_boxes
                         if action == "mark" and cue_id == suggested["cue_id"]]
                layout = review.list._row_layout(suggested)
                belows = [unit["below"] for line in layout["lines"] for unit in line if unit["mark"] is not None]
                check("a proposal is marked in place with only the replacement under it", bool(marks) and bool(belows)
                      and all(len(text) < len(suggested["base"]) for text in belows),
                      dict(text=suggested["base"], below=belows))
            review.list.setFocus()
            QTest.keyClick(review.list, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
            pump(.2)
            check("Ctrl+F focuses the search box", QApplication.focusWidget() is review.search,
                  type(QApplication.focusWidget()).__name__)
            check("no resident 全部替换 button", not hasattr(review, "replace_button") and review.replace_bar.isHidden())
            review.list.ensure_visible(review._rows[0]["cue_id"])
            pump(.2)
            review.list.repaint()
            edit_boxes = [rect for rect, action, cue_id, _ in review.list._hit_boxes
                          if action == "edit" and cue_id == review._rows[0]["cue_id"]]
            if edit_boxes:
                QTest.mouseClick(review.list, Qt.LeftButton, Qt.KeyboardModifier.NoModifier,
                                 edit_boxes[0].center().toPoint())
                pump(.2)
            check("修改 opens the editor next to the text", bool(edit_boxes) and review.list.editor.isVisible()
                  and review.list.editing() == review._rows[0]["cue_id"], dict(boxes=len(edit_boxes)))
            review.list.cancel_edit()
            # The list keeps responding while a full local match runs.
            beats, last = [], [time.perf_counter()]

            def beat():
                now = time.perf_counter()
                beats.append(now - last[0])
                last[0] = now

            heart = QTimer()
            heart.setInterval(16)
            heart.timeout.connect(beat)
            heart.start()
            review._run(False)
            from PySide6.QtCore import QPoint, QPointF
            from PySide6.QtGui import QWheelEvent
            centre = QPointF(review.list.width() / 2, review.list.height() / 2)
            scrolled_from = review.list.bar.value()
            started = time.perf_counter()
            while review._worker is not None and time.perf_counter() - started < 60:
                wheel = QWheelEvent(centre, QPointF(review.list.mapToGlobal(centre.toPoint())), QPoint(0, 0),
                                    QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                    Qt.ScrollPhase.NoScrollPhase, False)
                QApplication.sendEvent(review.list, wheel)
                pump(.05)
            check("mouse wheel scrolls the list during the match", review.list.bar.value() != scrolled_from,
                  dict(before=scrolled_from, after=review.list.bar.value()))
            heart.stop()
            worst = round(max(beats or [0]) * 1000)
            result["worst_gap_during_match_ms"] = worst
            check("UI keeps responding during a local match (worst gap < 400 ms)", worst < 400,
                  dict(worst_ms=worst, beats=len(beats)))
            check("filters show real counts", all(review.filter_buttons[key].text().split()[-1].isdigit()
                                                  for key in review.filter_buttons),
                  [button.text() for button in review.filter_buttons.values()])
            _capture(window, out / "02-workspace-all.png")

            payloads = {}
            original_start = review._player._start

            def spy(request_id, payload):
                payloads[request_id] = bytes(payload)
                original_start(request_id, payload)

            review._player._start = spy
            review._player.volume = 0.0  # real device output, silent

            def preview(row, label):
                review._play(row["cue_id"])
                plan = review._player.last_plan
                ok = wait(lambda: plan is not None and plan.request_id in payloads, 60)
                entry = dict(label=label, number=row["number"], cue_id=row["cue_id"], text=row["base"],
                             requested=ok, plan=plan.diagnostic() if plan else None)
                if ok and reference is not None:
                    a, b = plan.play_range_ms
                    entry["ncc_vs_recognized_audio"] = _ncc(to16k(payloads[plan.request_id]), reference[int(a * 16):int(b * 16)])
                result["previews"].append(entry)
                save()
                return entry

            first_guron = next(row for row in review._rows if "古龙" in row["base"])
            middle = review._rows[len(review._rows) // 2]
            tail = review._rows[-3]
            for label, row in (("first 古龙", first_guron), ("middle", middle), ("tail second source", tail)):
                entry = preview(row, label)
                check(f"preview {label} plays its own audio", entry.get("ncc_vs_recognized_audio", 0) >= .9, entry)
                clip_ms = (entry["plan"]["play_range_ms"][1] - entry["plan"]["play_range_ms"][0]) if entry.get("plan") else 0
                started = time.monotonic()
                stopped = wait(lambda: review._player.cue_id == "", clip_ms / 1000 + 5)
                check(f"preview {label} stops by itself after the clip", stopped,
                      dict(clip_ms=clip_ms, waited_s=round(time.monotonic() - started, 2)))
            from .runtime_paths import user_data_root
            log = user_data_root() / "logs" / "proofread-preview.jsonl"
            logs = [json.loads(line) for line in log.read_text("utf8").splitlines()] if log.is_file() else []
            check("each preview leaves a diagnostic row", len([x for x in logs if x.get("outcome") == "decoded"]) >= 3,
                  dict(path=str(log), rows=len(logs)))
            delivered = []
            review._player.state_changed.connect(lambda cue_id, state: delivered.append((cue_id, state)))
            for row in (first_guron, middle, tail):
                review._play(row["cue_id"])
                pump(.03)
            last_plan = review._player.last_plan
            wait(lambda: last_plan.request_id in payloads, 60)
            pump(1.0)
            playing = [cue_id for cue_id, state in delivered if state == "playing"]
            check("rapid clicks play only the last caption", playing == [tail["cue_id"]], delivered)
            review._player.stop()
            review.filter_buttons["suggested"].click()
            pump(.3)
            first_visible = review._rows[review.list.visible[0]]
            review.list.ensure_visible(first_visible["cue_id"])
            review.list.repaint()
            boxes = [rect for rect, action, cue_id, _ in review.list._hit_boxes
                     if action == "play" and cue_id == first_visible["cue_id"]]
            if boxes:
                QTest.mouseClick(review.list, Qt.LeftButton, Qt.KeyboardModifier.NoModifier, boxes[0].center().toPoint())
            plan = review._player.last_plan
            check("filtered row plays by stable id", boxes and plan is not None and plan.cue_id == first_visible["cue_id"],
                  dict(cue=first_visible["cue_id"], plan=plan.cue_id if plan else None))
            wait(lambda: plan is not None and plan.request_id in payloads, 60)
            review._player.stop()
            _capture(window, out / "03-filter-suggested.png")
            review.filter_buttons["all"].click()
            pump(.3)

            # Direct edit: 古龙 -> 骨龙 by double click — written at once, no library needed.
            live = {cue.id: cue for cue in page.project.cues}
            cue_id = first_guron["cue_id"]
            original_text = first_guron["base"]
            new_text = original_text.replace("古龙", "骨龙", 1)
            others_before = {row["cue_id"]: row["base"] for row in review._rows
                             if row["cue_id"] != cue_id and "古龙" in row["base"]}
            review.list.ensure_visible(cue_id)
            pump(.2)
            slot = review.list.slot_of(cue_id)
            point = review.list._text_rect(slot).center().toPoint()
            QTest.mouseDClick(review.list, Qt.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            check("double click opens the inline editor", wait(lambda: review.list.editor.isVisible(), 5))
            editor = review.list.editor
            editor.selectAll()
            from PySide6.QtGui import QInputMethodEvent
            commit = QInputMethodEvent("", [])
            commit.setCommitString(new_text)
            QApplication.sendEvent(editor, commit)
            before = page.undo_stack.index()
            edited_at = time.perf_counter()
            QTest.keyClick(editor, Qt.Key.Key_Return)
            edit_ms = round((time.perf_counter() - edited_at) * 1000)
            result["edit_ms"] = edit_ms
            pump(.3)
            check("Enter commits and closes the editor", not editor.isVisible() and review.list.editing() == "")
            check("the edit is in the project at once (one undo step)", live[cue_id].text == new_text
                  and page.undo_stack.index() == before + 1, dict(text=live[cue_id].text, ms=edit_ms))
            check("the row shows it as written", review._by_id[cue_id]["base"] == new_text
                  and review._by_id[cue_id]["origin"] == original_text)
            check("checks after the edit finish", wait(lambda: not review._local_timer.isActive()
                                                       and not review.checks_running(), 60))
            spread = sorted(row["cue_id"] for row in review._rows
                            if any(i["kind"] == "consistency" and i["replacement"] == "骨龙" and not i["checked"]
                                   for i in row["issues"]))
            check("骨龙 is offered for the other 古龙 captions (统一写法), not written", len(spread) >= 3
                  and all(live[k].text == v for k, v in others_before.items()), spread)
            check("remember offers 古龙 → 骨龙 for the inherited library",
                  review.list._remember_action(review._by_id[cue_id]) == ("古龙", "骨龙")
                  and review.target_combo.currentData() == "洛克王国世界",
                  dict(pair=review.list._remember_action(review._by_id[cue_id]), target=review.target_combo.currentData()))
            _capture(window, out / "04-edited.png")
            # Right click on a proposal: replace the same words in the whole project.
            target = next(row for row in review._rows if row["cue_id"] in spread)
            index = next(i for i, issue in enumerate(target["issues"])
                         if issue["kind"] == "consistency" and issue["replacement"] == "骨龙")
            check("the right-click pair is the whole word", issue_pair(target, target["issues"][index]) == ("古龙", "骨龙"),
                  issue_pair(target, target["issues"][index]))
            menus = []
            original_show = review._show_menu
            review._show_menu = lambda menu, _pos: menus.append(menu)
            review.list.ensure_visible(target["cue_id"])
            pump(.2)
            review._context_menu(target["cue_id"], ("mark", target["cue_id"], index), None)
            review._show_menu = original_show
            labels = [action.text() for action in menus[0].actions()] if menus else []
            total = sum(cue.text.count("古龙") for cue in page.project.cues)
            wanted = f"批量替换「古龙」→「骨龙」…（{total} 处"
            check("right click offers the batch replace with the real count", any(label.startswith(wanted) for label in labels),
                  labels)
            action = next((a for a in menus[0].actions() if a.text().startswith(wanted)), None) if menus else None
            before = page.undo_stack.index()
            if action is not None:
                action.trigger()  # 2026-10-10 night: opens the replace box filled in
            pump(.3)
            check("the replace box opens with both words filled in", review.replace_bar.isVisible()
                  and review.search.text() == "古龙" and review.replace_input.text() == "骨龙")
            review.replace_scope.setCurrentIndex(review.replace_scope.findData("project"))
            QTest.keyClick(review.replace_input, Qt.Key.Key_Return)
            pump(.3)
            review.replace_toggle.setChecked(False)
            review.search.clear()
            pump(.2)
            left_old = [cue.id for cue in page.project.cues if "古龙" in cue.text]
            check("batch replace writes every caption, one undo step", not left_old and page.undo_stack.index() == before + 1,
                  dict(left=left_old, steps=page.undo_stack.index() - before))
            _capture(window, out / "05-batch-replaced.png")
            # Ctrl+H, input method Enter, real Enter, undo.
            review.list.setFocus()
            QTest.keyClick(review.list, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
            pump(.2)
            check("Ctrl+H opens the find/replace bar", review.replace_bar.isVisible())
            review.search.setText("骨龙")
            review.replace_input.setFocus()
            review.replace_input.setText("骨龍")
            pump(.3)
            hits = sum(cue.text.count("骨龙") for cue in page.project.cues)
            check("the bar names hits and scope", f"将替换 {hits} 处" in review.replace_count.text()
                  and "即全部字幕里的" in review.replace_count.text(), review.replace_count.text())
            before = page.undo_stack.index()
            composing = QInputMethodEvent("gulong", [])
            QApplication.sendEvent(review.replace_input, composing)
            QTest.keyClick(review.replace_input, Qt.Key.Key_Return)
            pump(.2)
            check("Enter while an input method composes replaces nothing", page.undo_stack.index() == before)
            done = QInputMethodEvent("", [])
            QApplication.sendEvent(review.replace_input, done)
            review._ime_commit_at = 0.0
            QTest.keyClick(review.replace_input, Qt.Key.Key_Return)
            pump(.3)
            check("Enter in the replace box replaces the whole project", page.undo_stack.index() == before + 1
                  and not any("骨龙" in cue.text for cue in page.project.cues))
            page.undo_stack.undo()
            pump(.3)
            check("one undo restores every replaced caption", sum(cue.text.count("骨龙") for cue in page.project.cues) == hits
                  and review._by_id[cue_id]["base"] == live[cue_id].text)
            QTest.keyClick(review.replace_input, Qt.Key.Key_Escape)
            pump(.2)
            check("Esc closes the bar", review.replace_bar.isHidden())
            # Interface zoom on the page: Ctrl+wheel over the list, then Ctrl+0.
            from . import ui_zoom
            zoom_before = ui_zoom.zoom_percent()
            body_before = review.list.body.pixelSize()
            selected_row = review.list.current
            _post_ctrl_wheel(window, review.list, 120)
            check("Ctrl+wheel over the list zooms the page", wait(lambda: ui_zoom.zoom_percent() > zoom_before, 5)
                  and wait(lambda: review.list.body.pixelSize() > body_before, 5),
                  dict(zoom=ui_zoom.zoom_percent(), body=review.list.body.pixelSize()))
            check("zoom keeps the current caption and the project untouched", review.list.current == selected_row
                  and page.undo_stack.index() == before)
            _capture(window, out / "06-zoomed.png")
            review.list.setFocus()
            QTest.keyClick(review.list, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
            check("Ctrl+0 returns to 100%", wait(lambda: ui_zoom.zoom_percent() == 100
                                                 and review.list.body.pixelSize() == body_before, 5))
            QTest.mouseClick(review.back_button, Qt.LeftButton)
            pump(.6)
            check("back in the editor", window.pages.currentWidget() is page)
            # In Studio, Ctrl+wheel over the timeline stays a time zoom.
            # The native Ctrl+wheel over the timeline is left to Qt (no interface
            # zoom); Qt then gives it to the timeline as an ordinary wheel event.
            _post_ctrl_wheel(window, page.timeline, 120)
            pump(.6)
            check("Ctrl+wheel over the timeline does not zoom the interface", ui_zoom.zoom_percent() == 100,
                  ui_zoom.zoom_percent())
            duration = page.timeline.visible_duration_ms
            centre = QPointF(page.timeline.width() / 2, page.timeline.height() / 2)
            QApplication.sendEvent(page.timeline, QWheelEvent(
                centre, QPointF(page.timeline.mapToGlobal(centre.toPoint())), QPoint(0, 0), QPoint(0, 120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False))
            pump(.4)
            check("Ctrl+wheel on the timeline still zooms time",
                  ui_zoom.zoom_percent() == 100 and page.timeline.visible_duration_ms != duration,
                  dict(before=duration, after=page.timeline.visible_duration_ms, zoom=ui_zoom.zoom_percent()))
            from .studio_subtitle_export import _compile_format
            srt = _compile_format(page.project, "srt")
            check("export view has the edit", new_text in srt and original_text not in srt)
            _capture(window, out / "07-studio-after.png")
            texts_now = {cue.id: cue.text for cue in page.project.cues}
            page.undo_stack.undo()
            pump(.3)
            check("Studio undo removes the batch replace", any("古龙" in cue.text for cue in page.project.cues))
            page.undo_stack.redo()
            pump(.3)
            check("redo re-applies", {cue.id: cue.text for cue in page.project.cues} == texts_now)
            page.project_controller.save()
            pump(.3)
            old_project = page.project
            page.project_controller.open_project_entry(str(project_path), single_shot_fn=QTimer.singleShot,
                                                       skip_dirty_guard=True)
            check("reopened", wait(lambda: page.project is not None and page.project is not old_project
                                   and page._readiness.ready, 120))
            reopened = {cue.id: cue.text for cue in page.project.cues}
            check("reopen keeps every written text", reopened == texts_now,
                  [k for k in texts_now if reopened.get(k) != texts_now[k]][:5])
            check("reopened export has the edit", new_text in _compile_format(page.project, "srt"))
            _capture(window, out / "08-reopened.png")
            result["passed"] = all(item["passed"] for item in result["checks"])
        except BaseException:
            result["error"] = traceback.format_exc()
        finally:
            try:
                page.project_dirty = False
                page.undo_stack.setClean()
            except Exception:
                pass
            save()
            window.close()
            result["gui_shutdown"] = True
            save()
            QApplication.quit()

    QTimer.singleShot(1800, run)
