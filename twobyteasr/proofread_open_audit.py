"""Opt-in real-window audit: proofread a fresh recognition result, then edit
in Studio (2026-10-10 night, user report with five screenshots).

Runs inside the real application on a private desktop with an owned copy of
a project that the launcher stamped as a fresh delivery of one recognition
job (``scripts/verify_proofread_open_headed.py``):

result page (exact delivery reference) → AI 词库校对 → one whole skill name
is one group, a one-character change is marked and described as one
character → manual edit, adopt, search 布克 + mouse selection + right-click
batch replace (only the new word typed, a hit excluded, one step, undo,
redo) → 返回结果 → 打开字幕工作台 after each kind of edit → Studio has the
same text, count, times and speakers → wrong job / project / media / broken
references are still refused → save; phase "reopen" restarts the app and
opens the saved project. Screens are captured at every step.
"""
import json
import os
import time
import traceback
from pathlib import Path


def start(window, out):
    from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity

    out = Path(out)
    delivery = json.loads((out / "delivery.json").read_text("utf8"))
    phase = os.environ.get("TWOBYTEASR_AUDIT_PHASE", "edit")
    result = dict(passed=False, phase=phase, checks=[], build=load_build_identity().to_dict())
    name = "result.json"  # each phase runs in its own acceptance folder

    def save():
        (out / name).write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf8")

    def check(label, ok, detail=None):
        result["checks"].append(dict(name=label, passed=bool(ok), detail=detail))
        save()
        return bool(ok)

    def pump(seconds=.25):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(.005)

    def wait(test, seconds=60):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            pump(.025)
            if test():
                return True
        return False

    warnings = []
    original_warning = QMessageBox.warning

    def record_warning(parent, title, text, *args, **kwargs):
        warnings.append(dict(title=str(title), text=str(text)))
        return QMessageBox.StandardButton.Ok

    QMessageBox.warning = staticmethod(record_warning)
    shot = [0]

    def capture(label, widget=None):
        shot[0] += 1
        target = out / f"{shot[0]:02d}-{label}.png"
        try:
            _capture(widget or window, target)
        except Exception as exc:  # a missing screen is reported, not fatal
            result.setdefault("capture_errors", []).append(f"{label}: {exc}")
        return target

    project_path = str(Path(delivery["project_path"]).resolve())

    def studio_texts():
        page = window.studio_page
        return {cue.id: (cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in page.project.cues}

    def open_from_result(label):
        """打开字幕工作台 on the result page, as the button does."""
        warnings.clear()
        window._switch_page(2)
        pump(.3)
        button = window.open_studio_result_button
        enabled = button.isEnabled()
        window._completion_action_last_by_name = {}
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        page = window.studio_page
        ready = wait(lambda: page.project is not None and str(Path(page.project_path or "").resolve()) == project_path
                     and page._readiness.ready and window.pages.currentWidget() is page, 120)
        pump(.5)
        capture(f"studio-{label}")
        return enabled, ready, list(warnings)

    def leave_studio():
        page = window.studio_page
        if not page.undo_stack.isClean():
            page.project_controller.save()
        page._request_return_home()
        pump(.5)

    def run():
        try:
            from .glossary_proofread import change_summary
            from .recognition_result import working_reference
            from .service import MediaResult, QueueResult
            from .studio_project import load_project
            if phase == "reopen":
                return run_reopen()
            delivered = load_project(project_path)
            delivered_rows = {cue.id: (cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in delivered.cues}
            item = MediaResult(media_path=delivery["media_path"], status="success", project_path=project_path,
                               job_id=delivery["job_id"], project_id=delivered.project_id,
                               result_ref_json=delivery["result_ref_json"], elapsed_seconds=1.0)
            window._ensure_recognition_page()
            window._active_job_id = delivery["job_id"]
            window.showMaximized()
            window._handle_result(QueueResult((item,), 1.0, job_id=delivery["job_id"]))
            pump(1.0)
            check("fresh delivery reaches the result page", window.pages.currentWidget() is window.pages.widget(2)
                  and window._last_result_ref_json == delivery["result_ref_json"])
            check("打开字幕工作台 is available", window.open_studio_result_button.isEnabled())
            dialog = getattr(window, "_completion_dialog", None)
            if dialog is not None:
                capture("completion-dialog")
                QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)  # 知道了, as the user does
                wait(lambda: getattr(window, "_completion_dialog", None) is None, 5)
                pump(.4)
            capture("result-page")

            # ---- AI 词库校对 from the result page --------------------------------
            window._completion_action_last_by_name = {}
            window._open_glossary_proofread()
            review = getattr(window, "glossary_proofread_page", None)
            check("AI 词库校对 opens", wait(lambda: review is not None and window.pages.currentWidget() is review, 15))
            check("local checks finish", wait(lambda: not review.checks_running(), 120))
            pump(.5)
            check("library inherited from the recognition", "洛克王国世界" in review._selected_ids(),
                  review._selected_ids())
            check("the libraries' whole names are known", {"疫病吐息", "魔草巫灵", "布克棱岩"} <= set(review._terms.categories),
                  len(review._terms.categories))
            rows = {row["base"]: row for row in review._rows}
            capture("proofread-open")

            # Picture 5: 疫病吐息 is one decision.
            skill = next((row for row in review._rows if "疫病吐息" in row["base"]), None)
            groups = review._groups(skill) if skill else []
            inside = [group for group in groups if group["name"] == "疫病吐息"]
            check("疫病吐息: proposals inside the skill name form one group", len(inside) <= 1 and all(
                len([g for g in groups if set(g["parts"]) & set(group["parts"])]) == 1 for group in inside),
                skill and [(g["parts"], g["name"], g["pending"], [skill["issues"][i]["replacement"] for i in g["parts"]])
                           for g in groups])
            if inside:
                group = inside[0]
                check("疫病吐息: asked, not recommended, one adopt box", group["pending"] and not group["recommended"])
                review.list.expanded.add((skill["cue_id"], group["parts"][0]))
                review._apply_filter()
                review.list.ensure_visible(skill["cue_id"])
                pump(.3)
                review.list.repaint()
                boxes = [index for _rect, action, cue_id, index in review.list._hit_boxes
                         if action == "check" and cue_id == skill["cue_id"]]
                check("疫病吐息: one adopt box for the whole name", len(boxes) == 1, boxes)
                result["picture5"] = dict(text=skill["base"], summary=change_summary(group["before"], group["after"])
                                          if group["after"] else None,
                                          parts=[(skill["issues"][i]["kind"], skill["issues"][i]["original"],
                                                  skill["issues"][i]["replacement"]) for i in group["parts"]])
                capture("picture5-skill-group")
            # Picture 4: 巫 → 乌 marks one character.
            spirit = next((row for row in review._rows if "魔草巫灵" in row["base"]), None)
            one = None
            for group in (review._groups(spirit) if spirit else []):
                issues = [spirit["issues"][i] for i in group["parts"]]
                if any(issue["replacement"] and "乌" in issue["replacement"] for issue in issues):
                    one = group
            if one is not None:
                review.list.ensure_visible(spirit["cue_id"])
                pump(.3)
                review.list.repaint()
                layout = review.list._row_layout(spirit)
                marked = [(unit["top"], unit["below"]) for line in layout["lines"] for unit in line
                          if unit["mark"] is not None and unit["mark"]["style"] != "applied"]
                summary = change_summary(one["before"], one["after"]) if one["after"] else ""
                check("巫 → 乌: only 巫 is marked, 乌 under it, summary 巫 → 乌",
                      ("巫", "乌") in marked and all(len(top) == 1 for top, _below in marked if "巫" in top)
                      and summary == "巫 → 乌", dict(marked=marked, summary=summary))
                result["picture4"] = dict(text=spirit["base"], marked=marked, summary=summary)
                capture("picture4-one-character")
            else:
                result["picture4"] = "no 巫/乌 proposal in this project now"

            # ---- 1) a manual edit, then open Studio ------------------------------
            target = next(row for row in review._rows if " " in row["base"])
            review.list.ensure_visible(target["cue_id"])
            pump(.2)
            review._edit(target["cue_id"])
            pump(.2)
            edited_text = target["base"].replace(" ", "", 1)
            review.list.editor.setText(edited_text)
            QTest.keyClick(review.list.editor, Qt.Key.Key_Return)
            pump(.4)
            check("manual edit written at once", target["base"] == edited_text and review._stack.count() >= 1)
            QTest.mouseClick(review.back_button, Qt.MouseButton.LeftButton)
            check("返回结果", wait(lambda: window.pages.currentWidget() is window.pages.widget(2), 10))
            check("the file holds the edit before Studio reads it",
                  {c.id: c.text for c in load_project(project_path).cues}[target["cue_id"]] == edited_text)
            enabled, ready, seen = open_from_result("after-manual-edit")
            check("after a manual edit: Studio opens, no 无法确认本次识别工程", enabled and ready and not seen,
                  dict(ready=ready, warnings=seen))
            if ready:
                now = studio_texts()
                check("Studio shows the edited text; count, times and speakers unchanged",
                      now[target["cue_id"]][0] == edited_text and len(now) == len(delivered_rows)
                      and all(now[c][1:] == delivered_rows[c][1:] for c in delivered_rows))
            leave_studio()

            # ---- 2) adopt a proposal group, undo/redo, then open Studio -----------
            window._switch_page(2)
            window._completion_action_last_by_name = {}
            window._open_glossary_proofread()
            check("proofreading reopens", wait(lambda: window.pages.currentWidget() is review, 15)
                  and wait(lambda: not review.checks_running(), 120))
            pump(.4)
            candidates = [(row, group) for row in review._rows for group in review._groups(row)
                          if group["state"] == "open" and not group["options"] and group["after"]]
            adopted = None
            if candidates:
                row, group = next(((r, g) for r, g in candidates if g["recommended"]), candidates[0])
                review.list.ensure_visible(row["cue_id"])
                pump(.3)
                review.list.repaint()
                boxes = [rect for rect, action, cue_id, index in review.list._hit_boxes
                         if action == "check" and cue_id == row["cue_id"] and index == group["parts"][0]]
                if boxes:
                    QTest.mouseClick(review.list, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                     boxes[0].center().toPoint())
                    pump(.4)
                adopted = (row["cue_id"], group["after"])
                check("a click adopts the whole group, one undo step", row["base"] == group["after"],
                      dict(text=row["base"], wanted=group["after"]))
                capture("adopted")
                review._undo()
                pump(.3)
                check("undo takes the whole group back", row["base"] == group["before"])
                review._redo()
                pump(.3)
                check("redo writes it again", row["base"] == group["after"])
            QTest.mouseClick(review.back_button, Qt.MouseButton.LeftButton)
            wait(lambda: window.pages.currentWidget() is window.pages.widget(2), 10)
            enabled, ready, seen = open_from_result("after-adopt-undo-redo")
            check("after adopt + undo + redo: Studio opens", enabled and ready and not seen, dict(warnings=seen))
            if ready and adopted:
                check("Studio shows the adopted text", studio_texts()[adopted[0]][0] == adopted[1])
            leave_studio()

            # ---- 3) search 布克, select with the mouse, right-click batch replace --
            window._switch_page(2)
            window._completion_action_last_by_name = {}
            window._open_glossary_proofread()
            wait(lambda: window.pages.currentWidget() is review, 15)
            wait(lambda: not review.checks_running(), 120)
            pump(.4)
            review.search.setFocus()
            review.search.setText("布克")
            pump(.6)
            listed = [review._rows[index]["cue_id"] for index in review.list.visible]
            with_hits = [cue_id for cue_id in listed if "布克" in review._by_id[cue_id]["base"]]
            check("search 布克 lists its captions", len(with_hits) >= 2, dict(listed=len(listed), hits=len(with_hits)))
            capture("search-results")
            chosen = with_hits[1] if len(with_hits) > 1 else with_hits[0]
            row = review._by_id[chosen]
            start_at = row["base"].index("布克")
            review.list.ensure_visible(chosen)
            pump(.3)
            review.list.repaint()
            line = next(entry for entry in review.list._chars[chosen] if any(i == start_at for _a, _b, i in entry[3]))
            boxes = {index: (a, b) for a, b, index in line[3]}
            y = int((line[0] + line[1]) / 2)
            first, last = QPoint(int(boxes[start_at][0] + 1), y), QPoint(int(boxes[start_at + 1][1] - 1), y)
            played = []
            review.list.play_requested.connect(played.append)
            steps_before = review._stack.index()
            QTest.mousePress(review.list, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
            for step in range(1, 7):
                QTest.mouseMove(review.list, first + (last - first) * step / 6)
                pump(.03)
            QTest.mouseRelease(review.list, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, last)
            pump(.3)
            check("a mouse drag selects 布克 in the caption", review.list.selection() == (chosen, start_at, start_at + 2, "布克")
                  and not played and review._stack.index() == steps_before, review.list.selection())
            capture("selected")
            menu_texts, menu_shot = [], []

            def act_on_menu():
                menu = QApplication.activePopupWidget()
                if not isinstance(menu, QMenu):
                    QTimer.singleShot(150, act_on_menu)
                    return
                menu_texts.extend(action.text() for action in menu.actions())
                pump(.2)
                menu_shot.append(capture("context-menu", menu))
                capture("context-menu-window")
                action = next((a for a in menu.actions() if a.text().startswith("批量替换相同文字「布克」")), None)
                menu.close()
                if action is not None:
                    QTimer.singleShot(0, action.trigger)

            QTimer.singleShot(400, act_on_menu)
            point = QPoint((first.x() + last.x()) // 2, y)
            QApplication.sendEvent(review.list, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point,
                                                                  review.list.mapToGlobal(point)))
            pump(.6)
            check("right click keeps the selection and offers 批量替换相同文字",
                  any(text.startswith("批量替换相同文字「布克」") for text in menu_texts), menu_texts)
            check("the replace box opens with 布克 kept as the search",
                  wait(lambda: review.replace_bar.isVisible(), 5) and review.search.text() == "布克")
            check("the cursor waits in 新写法", QApplication.focusWidget() is review.replace_input,
                  type(QApplication.focusWidget()).__name__)
            review.replace_input.insert("布可")
            pump(.4)
            plan = review.replace_plan()
            check("the bar shows how many hits and captions", f"将替换 {plan['hits']} 处（{plan['captions']} 条字幕）"
                  in review.replace_count.text(), review.replace_count.text())
            capture("replace-typed")
            # Exclude the hit in the selected caption with a click.
            review.list.ensure_visible(chosen)
            pump(.3)
            review.list.repaint()
            hits = [rect for rect, action, cue_id, index in review.list._hit_boxes
                    if action == "find" and cue_id == chosen and index == start_at]
            if hits:
                QTest.mouseClick(review.list, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                 hits[0].center().toPoint())
                pump(.3)
            excluded_plan = review.replace_plan()
            check("a click excludes one hit", excluded_plan["excluded"] == 1 and excluded_plan["hits"] == plan["hits"] - 1,
                  dict(before=plan["hits"], after=excluded_plan["hits"], excluded=excluded_plan["excluded"]))
            capture("hit-excluded")
            before_texts = {r["cue_id"]: r["base"] for r in review._rows}
            from .cue_word_alignment import cue_words
            live = review._live_project()[0]
            measured_before = {}
            for cue in live.cues:
                if "布克" in cue.text:
                    words, source = cue_words(live, cue)
                    measured_before[cue.id] = ([(w.start_ms, w.end_ms) for w in words], source)
            steps = review._stack.index()
            QTest.keyClick(review.replace_input, Qt.Key.Key_Return)
            pump(.5)
            changed = [cue_id for cue_id, text in before_texts.items() if review._by_id[cue_id]["base"] != text]
            check("Enter replaces every listed hit except the excluded one, one undo step",
                  review._stack.index() == steps + 1 and len(changed) == excluded_plan["captions"]
                  and "布克" in review._by_id[chosen]["base"], dict(changed=len(changed), plan=excluded_plan["captions"]))
            check("the replaced captions stay listed", set(changed) <= {review._rows[i]["cue_id"] for i in review.list.visible})
            capture("replaced")
            review._undo()
            pump(.4)
            check("one undo restores every caption", all(review._by_id[c]["base"] == before_texts[c] for c in before_texts))
            capture("undone")
            review._redo()
            pump(.4)
            check("redo replaces them again", all(review._by_id[c]["base"] != before_texts[c] for c in changed))
            replaced_texts = {c: review._by_id[c]["base"] for c in changed}
            QTest.mouseClick(review.back_button, Qt.MouseButton.LeftButton)
            wait(lambda: window.pages.currentWidget() is window.pages.widget(2), 10)
            enabled, ready, seen = open_from_result("after-batch-replace")
            check("after a batch replace + undo + redo: Studio opens", enabled and ready and not seen,
                  dict(warnings=seen))
            if ready:
                now = studio_texts()
                check("Studio shows the replaced texts; count, times and speakers unchanged",
                      all(now[c][0] == text for c, text in replaced_texts.items()) and len(now) == len(delivered_rows)
                      and all(now[c][1:] == delivered_rows[c][1:] for c in delivered_rows))
                from .studio_subtitle_export import _compile_format
                srt = _compile_format(window.studio_page.project, "srt")
                check("the export reads the same text", all(text in srt for text in replaced_texts.values()))
                # Word timing: the replaced captions keep their measured span
                # (the replaced characters keep their spoken interval).
                timed = {}
                for cue in window.studio_page.project.cues:
                    if cue.id in replaced_texts and cue.id in measured_before:
                        words, source = cue_words(window.studio_page.project, cue)
                        before_spans, before_source = measured_before[cue.id]
                        timed[cue.id] = dict(before=len(before_spans), after=len(words), source=source,
                                             before_source=before_source,
                                             same_outer=bool(words) and bool(before_spans)
                                             and (words[0].start_ms, words[-1].end_ms)
                                             == (before_spans[0][0], before_spans[-1][1]))
                result["word_timing_after_replace"] = timed
                check("replaced captions keep their measured word timing",
                      all(value["same_outer"] for value in timed.values() if value["before"]), timed)
            # Opening it again right away from the result page.
            leave_studio()
            enabled, ready, seen = open_from_result("reopen-from-result")
            check("returning to the result page and opening again works", enabled and ready and not seen,
                  dict(warnings=seen))

            # ---- safety: other jobs, projects, media and broken references ----
            leave_studio()
            reference = json.loads(delivery["result_ref_json"])
            other = delivery["other_project_path"]
            cases = {
                # (project opened, reference presented)
                "another job's reference for this project": (project_path, delivery["other_result_ref_json"]),
                "this reference for another job's project": (other, delivery["result_ref_json"]),
                "a forged job in the reference": (project_path, json.dumps(dict(reference, job_id="forged-job"))),
                "a broken revision": (project_path, json.dumps(dict(reference, result_revision="0" * 64))),
            }
            refused = {}
            for label, (path, ref) in cases.items():
                warnings.clear()
                window._switch_page(2)
                pump(.2)
                window.open_studio_project(path, mode="edit", source="completion_edit",
                                           expected_result_ref=working_reference(ref))
                pump(1.0)
                refused[label] = dict(warnings=[w["text"] for w in warnings],
                                      opened=window.pages.currentWidget() is window.studio_page)
            check("other jobs, other projects and broken references are still refused",
                  all(value["warnings"] and not value["opened"] for value in refused.values()), refused)
            window._switch_page(2)
            pump(.3)
            capture("refused-stays-on-result")

            # ---- save and hand over to the reopen phase -----------------------
            final = load_project(project_path)
            (out / "expected.json").write_text(json.dumps(
                {cue.id: [cue.text, cue.start_ms, cue.end_ms, cue.speaker_id] for cue in final.cues},
                ensure_ascii=False), "utf8")
            check("saved project keeps every caption, time and speaker", len(final.cues) == len(delivered_rows)
                  and all((c.start_ms, c.end_ms, c.speaker_id) == delivered_rows[c.id][1:] for c in final.cues))
            from .recognition_result import digest_payload, input_graph_identity
            check("media, cuts and audio mapping are the delivered ones",
                  digest_payload(input_graph_identity(final)) == reference["input_graph_digest"])
            check("the recognition stamp is kept, not rewritten",
                  final.generation_metadata.get("recognition_result") == reference)
            result["passed"] = all(item["passed"] for item in result["checks"])
        except Exception:
            result["error"] = traceback.format_exc()
        finally:
            QMessageBox.warning = original_warning
            save()
            QTimer.singleShot(300, close)

    def run_reopen():
        from .studio_project import load_project
        expected = json.loads((out / "expected.json").read_text("utf8"))
        page = window.studio_page
        ready = wait(lambda: page.project is not None and page._readiness.ready, 180)
        window.showMaximized()
        pump(.8)
        check("after a restart the saved project opens in Studio", ready)
        if ready:
            now = {cue.id: [cue.text, cue.start_ms, cue.end_ms, cue.speaker_id] for cue in page.project.cues}
            check("text, count, times and speakers are the saved ones", now == expected,
                  [key for key in expected if now.get(key) != expected[key]][:5])
            capture("reopened-after-restart")
        check("the file on disk matches", {c.id: [c.text, c.start_ms, c.end_ms, c.speaker_id]
                                           for c in load_project(project_path).cues} == expected)
        result["passed"] = all(item["passed"] for item in result["checks"])
        QMessageBox.warning = original_warning
        save()
        QTimer.singleShot(300, close)

    def close():
        result["gui_shutdown"] = True
        save()
        studio = window.built_page("studio")
        if studio is not None and studio.project is not None and not studio.undo_stack.isClean():
            studio.project_controller.save()
        window.close()
        QApplication.instance().quit()

    QTimer.singleShot(2500, run)
