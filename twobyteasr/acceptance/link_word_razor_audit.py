"""Opt-in real-window check: razor on downloaded YouTube automatic captions (2026-10-26).

User report: imported automatic captions said "此段缺少有效字级对齐 · 文字分界为估算"
and English was cut between letters. The project (built by
``scripts/verify_link_word_razor_headed.py`` from real json3 captions) is
opened in the Studio; the razor hovers inside words of a caption and must show
measured word chips, cut at a word boundary and keep whole words on each side.
Nothing outside ``output`` is written; the project is never saved.
"""
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..recognition.cue_word_alignment import DOWNLOADED_WORD_ONSETS, cue_words
    from ..timeline.studio_timing import SplitPreview
    spec = json.loads((output / "input.json").read_text("utf-8"))
    result = dict(checks=[], samples=[], identity=load_build_identity().to_dict(), passed=False)
    page = window.studio_page

    def check(name, ok, detail=None):
        result["checks"].append(dict(name=name, passed=bool(ok), detail=detail))

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def steps():
        window.showMaximized()
        window.open_studio_project(spec["project"], mode="edit", source="link_word_razor_audit")
        yield ready
        yield 1.0
        t = page.timeline
        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.LeftButton)
            yield .3
        project = page.project
        reasons = [cue_words(project, cue)[1] for cue in project.cues]
        worded = sum(reason == DOWNLOADED_WORD_ONSETS for reason in reasons)
        check("imported automatic captions carry word timing", worded >= 0.9 * len(project.cues),
              dict(cues=len(project.cues), with_words=worded))
        cue = max(project.cues, key=lambda c: len(cue_words(project, c)[0]))
        words = cue_words(project, cue)[0]
        result["target"] = dict(text=cue.text, words=[(w.text, w.start_ms, w.end_ms) for w in words])
        QTest.mouseClick(page.razor_tool_button, Qt.LeftButton)
        yield .2
        check("razor tool selected", t.tool_mode == "razor")
        t.set_visible_window(max(0, cue.start_ms - 400), cue.end_ms - cue.start_ms + 800)
        yield .5
        top = t.window()
        rect = t._track_layout()[0][cue.speaker_id]
        for index, word in enumerate(words[1:-1], 1):
            ms = (word.start_ms + word.end_ms) // 2     # inside the word's sound
            point = QPoint(round(t._time_to_x(ms)), round(rect.center().y()))
            QTest.mouseMove(top.windowHandle(), t.mapTo(top, point))
            want = t._x_to_time(point.x())
            yield lambda: (t._razor_hover or {}).get("split_ms") == want
            QApplication.processEvents()
            resolution = t._razor_resolution()
            res = resolution.result if resolution else None
            row = dict(pointer_ms=want, word=word.text, words_in_lane=len(resolution.words) if resolution else 0,
                       result=type(res).__name__, split_ms=getattr(res, "split_ms", None),
                       left=getattr(res, "left_text", ""), right=getattr(res, "right_text", ""),
                       source=getattr(res, "timing_source", ""), reason=getattr(res, "timing_reason", ""))
            result["samples"].append(row)
            if index in (1, len(words) // 2):
                yield .2
                _capture(window, output / f"razor-{index:02d}.png")
                t.grab().save(str(output / f"razor-timeline-{index:02d}.png"))
        onsets = {w.start_ms for w in words}
        samples = result["samples"]
        check("razor lane shows the caption's words (no estimate warning)",
              samples and all(s["words_in_lane"] == len(words) for s in samples), samples[:3])
        # A cut through a word moves to the next word's start, unless the right
        # part would then be shorter than a caption may be (a very short last word).
        check("every cut is measured and lands on a word start",
              all(s["result"] == SplitPreview.__name__ and s["source"] == DOWNLOADED_WORD_ONSETS
                  and (s["split_ms"] in onsets or s["reason"] == "inside_token_kept_left") for s in samples), samples)
        check("no word is cut in two", all(s["left"] + " " + s["right"] == cue.text for s in samples), samples)
        result["passed"] = all(x["passed"] for x in result["checks"])

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)
    timer.setInterval(30)

    def save():
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), "utf-8")

    def finish():
        timer.stop()
        save()
        page.session.undo_stack.setClean()
        window.close()
        QTimer.singleShot(500, QApplication.instance().quit)

    def tick():
        if state.get("ticking"):
            return
        state["ticking"] = True
        try:
            if state["wait"] is not None:
                if state["wait"]():
                    state["wait"] = None
                elif time.monotonic() > state["deadline"]:
                    raise TimeoutError("Real GUI condition did not settle")
                else:
                    return
            if time.monotonic() < state["until"]:
                return
            value = next(iterator)
            if callable(value):
                state.update(wait=value, deadline=time.monotonic() + 90)
            else:
                state["until"] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            result["error"] = traceback.format_exc()
            try:
                _capture(window, output / "failure.png")
            except Exception:
                pass
            finish()
        finally:
            state["ticking"] = False

    def shutdown():
        result["gui_shutdown"] = True
        save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    timer.start()
