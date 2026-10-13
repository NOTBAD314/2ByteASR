"""Opt-in performance regression audit for the normal window (source or frozen).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=perf-regression`` via
``scripts/verify_perf_regression_headed.py``. It drives the real Studio with
QMouseEvent, the shortcut handlers and the undo stack, and reports per action:

- ``handler_ms``: synchronous time inside the injected input handler.
- ``frame_ms``: injection → end of the next timeline paint (what the user sees).
- ``idle_ms``: injection → the event loop has drained (two zero-timer turns),
  i.e. including deferred work queued by the action.

Continuous gestures inject one move every 16 ms and report per-move frame
latency, coalescing and frame pacing; repeated gestures are kept separately so
degradation over a session is visible rather than only the best sample.
"""
from __future__ import annotations

import ctypes
import json
import os
import statistics
import threading
import time
import traceback
from pathlib import Path


def _dist(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"n": 0}
    pick = lambda q: values[min(len(values) - 1, int(round((len(values) - 1) * q)))]
    return {"n": len(values), "p50": round(pick(.5), 2), "p95": round(pick(.95), 2),
            "max": round(values[-1], 2), "mean": round(statistics.fmean(values), 2)}


def _gui_objects():
    try:
        kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        user32.GetGuiResources.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        handle = kernel32.GetCurrentProcess()
        return {"gdi": user32.GetGuiResources(handle, 0), "user": user32.GetGuiResources(handle, 1)}
    except Exception:
        return {}


DEFAULT_PHASES = ("idle,select,drag-repeat,wide-press,select-all-drag,undo-redo,delete-cues,ripple-trim,"
                  "text-edit,playback,save-reopen,close-while-busy,leak-cycles,idle-final")


def start(window, out: Path):
    import psutil
    from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    process = psutil.Process()
    started = time.perf_counter()
    phases = [p for p in os.environ.get("PERF_PHASES", DEFAULT_PHASES).split(",") if p]
    drag_repeats = int(os.environ.get("PERF_DRAG_REPEATS", "5"))
    profile_actions = {a for a in os.environ.get("PERF_PROFILE_ACTIONS", "").split(",") if a}
    profile_phases = {a for a in os.environ.get("PERF_PROFILE_PHASES", "").split(",") if a}

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.phase = "open"
            self.result = {"phases": {}, "actions": {}, "gestures": {}, "loop": {}, "resources": [],
                           "checks": {}, "errors": {}, "scenario": "perf-regression",
                           "phases_requested": phases}
            try:
                from .build_identity import load_build_identity
                self.result["build"] = load_build_identity().to_dict()
            except Exception as exc:
                self.result["build"] = repr(exc)
            self.paint_ends: list[float] = []
            self.paint_ms: dict[str, list[float]] = {}
            self.gaps: dict[str, list[float]] = {}
            self.last_tick = time.perf_counter()
            self.idle_marks: dict[int, float] = {}
            # Garbage-collector pauses per phase and generation (a full
            # collection over a large project heap lands inside whatever
            # action happens to allocate at that moment).
            import gc
            self.gc_pauses: dict[str, list] = {}
            self.full_gc_windows: list[tuple[float, float]] = []
            self._gc_started = 0.0

            def on_gc(stage, info):
                if stage == "start":
                    self._gc_started = time.perf_counter()
                else:
                    end = time.perf_counter()
                    self.gc_pauses.setdefault(self.phase, []).append(
                        (info.get("generation"), (end - self._gc_started) * 1000, info.get("collected", 0)))
                    if info.get("generation") == 2:
                        self.full_gc_windows.append((self._gc_started, end))
            gc.callbacks.append(on_gc)
            self.heartbeat = QTimer(self)
            self.heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
            self.heartbeat.timeout.connect(self._beat)
            self.heartbeat.start(16)
            timeline = self.page.timeline
            original = timeline._paint_timeline

            def paint(event):
                t = time.perf_counter()
                original(event)
                end = time.perf_counter()
                self.paint_ends.append(end)
                if len(self.paint_ends) > 4096:
                    del self.paint_ends[:2048]
                self.paint_ms.setdefault(self.phase, []).append((end - t) * 1000)
            timeline._paint_timeline = paint
            self.pending = 0.0
            self.sequence = self.run()
            self.driver = QTimer(self)
            self.driver.setTimerType(Qt.TimerType.PreciseTimer)
            self.driver.timeout.connect(self._tick)
            self.driver.start(5)

        # ---------------------------------------------------------------- infra
        def _beat(self):
            now = time.perf_counter()
            self.gaps.setdefault(self.phase, []).append((now - self.last_tick) * 1000)
            self.last_tick = now

        def _tick(self):
            try:
                if time.perf_counter() - started > float(os.environ.get("PERF_TIMEOUT_S", "900")):
                    raise TimeoutError("perf regression audit timeout")
                if callable(self.pending):
                    if not self.pending():
                        return
                elif time.perf_counter() < self.pending:
                    return
                value = next(self.sequence)
                self.pending = value if callable(value) else time.perf_counter() + value
            except StopIteration:
                self.finish()
            except Exception:
                self.result["errors"]["fatal"] = traceback.format_exc()
                self.finish()

        def save(self):
            self.result["elapsed_s"] = round(time.perf_counter() - started, 3)
            self.result["loop"] = {
                phase: {"heartbeat": _dist(gaps), "stalls_50ms": sum(g >= 50 for g in gaps),
                        "stalls_100ms": sum(g >= 100 for g in gaps),
                        "stalls_250ms": sum(g >= 250 for g in gaps),
                        "paint_ms": _dist(self.paint_ms.get(phase, [])),
                        "paints": len(self.paint_ms.get(phase, []))}
                for phase, gaps in self.gaps.items()}
            self.result["gc"] = {
                phase: {f"gen{gen}": {"count": sum(1 for g, *_ in rows if g == gen),
                                      "total_ms": round(sum(ms for g, ms, _ in rows if g == gen), 1),
                                      "max_ms": round(max((ms for g, ms, _ in rows if g == gen), default=0), 1)}
                        for gen in (0, 1, 2)}
                for phase, rows in self.gc_pauses.items()}
            try:
                from .gui_stall_watchdog import instance
                watchdog = instance()
                if watchdog is not None:
                    self.result["gui_stalls"] = list(watchdog.recent)
                    self.result["gui_stall_stats"] = watchdog.lag_stats(window_s=time.perf_counter() - started)
            except Exception as exc:
                self.result["gui_stalls"] = repr(exc)
            (out / "perf.json").write_text(json.dumps(self.result, ensure_ascii=False, indent=2), "utf8")

        def finish(self):
            self.driver.stop()
            self.heartbeat.stop()
            try:
                stack = self.page.undo_stack
                while stack.canUndo():
                    stack.undo()
                stack.setClean()
                self.page.project_dirty = False
            except Exception:
                pass
            self.result["finished"] = True
            self.save()
            window.close()
            self.result["gui_shutdown"] = True
            self.save()
            QApplication.quit()

        def ready(self):
            page = self.page
            return bool(page.project and page._readiness.ready
                        and getattr(page.video, "_startup_state", "") == "READY")

        def snapshot(self, label):
            try:
                cpu = process.cpu_times()
                children = []
                for child in process.children(recursive=True):
                    try:
                        children.append({"pid": child.pid, "name": child.name(),
                                         "rss_mb": round(child.memory_info().rss / 1e6, 1)})
                    except psutil.Error:
                        pass
                memory = process.memory_info()
                row = {"label": label, "t": round(time.perf_counter() - started, 2),
                       "rss_mb": round(memory.rss / 1e6, 1),
                       # private / handles exist only on Windows; macOS reports open descriptors (2026-10-14).
                       "private_mb": round(getattr(memory, "private", memory.rss) / 1e6, 1),
                       "threads": process.num_threads(),
                       "handles": process.num_handles() if hasattr(process, "num_handles") else process.num_fds(),
                       "cpu_s": round(cpu.user + cpu.system, 3), **_gui_objects(),
                       "children": children, "caches": self.cache_stats()}
            except Exception as exc:
                row = {"label": label, "error": repr(exc)}
            self.result["resources"].append(row)
            return row

        def cache_stats(self):
            page, stats = self.page, {}
            try:
                preview = getattr(page, "_cue_timing_preview", None)
                if preview is not None:
                    stats["timing_preview"] = {"entries": len(preview._cache),
                                               "mb": round(getattr(preview, "_cache_bytes", 0) / 1e6, 1)}
            except Exception:
                pass
            try:
                from .live_layer_cache import GLOBAL_LIVE_LAYER_CACHE
                live = GLOBAL_LIVE_LAYER_CACHE.stats()
                stats["live_layers"] = {k: live[k] for k in ("entries", "bytes") if k in live}
            except Exception:
                pass
            try:
                from . import style_recipe
                entries = style_recipe._VALIDATED_RECIPES
                stats["recipe_cache"] = {"entries": len(entries),
                                         "mb": round(sum(len(k) + len(v) for k, v in entries.items()) / 1e6, 2)}
            except Exception:
                pass
            try:
                film = getattr(page.timeline, "_thumbnails", None)
                stats["filmstrip_mb"] = round(getattr(film, "bytes", 0) / 1e6, 1)
            except Exception:
                pass
            return stats

        def thread_cpu(self):
            """CPU seconds per OS thread, named where Python knows the thread."""
            import threading
            names = {getattr(t, "native_id", None): t.name for t in threading.enumerate()}
            try:
                return {row.id: (names.get(row.id, "native"), row.user_time + row.system_time)
                        for row in process.threads()}
            except Exception:
                return {}

        def phase_run(self, name, body):
            self.phase = name
            self.last_tick = time.perf_counter()
            print("PERF_PHASE", name, flush=True)
            before = self.snapshot(name + ":before")
            threads_before = self.thread_cpu()
            profiler = None
            if name in profile_phases:
                import cProfile
                profiler = cProfile.Profile()
                profiler.enable()
            t = time.perf_counter()
            try:
                yield from body()
            except Exception:
                self.result["errors"][name] = traceback.format_exc()
            if profiler is not None:
                # GUI-thread work of the whole phase (timers, paints, ticks).
                import io, pstats
                profiler.disable()
                stream = io.StringIO()
                stats = pstats.Stats(profiler, stream=stream)
                stats.sort_stats("cumtime").print_stats(90)
                stats.sort_stats("tottime").print_stats(40)
                (out / f"profile-phase-{name}.txt").write_text(stream.getvalue(), "utf8")
            after = self.snapshot(name + ":after")
            threads_after = self.thread_cpu()
            busy = sorted(((cpu - threads_before.get(tid, (label, 0.0))[1], label, tid)
                           for tid, (label, cpu) in threads_after.items()), reverse=True)[:6]
            paints = sorted(self.paint_ms.get(name, []))
            seconds = time.perf_counter() - t
            self.result["phases"][name] = {
                "seconds": round(seconds, 3),
                "cpu_s": round(after.get("cpu_s", 0) - before.get("cpu_s", 0), 3),
                "threads_cpu_s": [[label, tid, round(cpu, 3)] for cpu, label, tid in busy if cpu > 0.01],
                # Timeline frames actually painted (rate) and their GUI cost.
                "timeline_paints": len(paints),
                "timeline_paint_fps": round(len(paints) / max(seconds, 1e-6), 1),
                "timeline_paint_ms_p50_p95": ([round(paints[len(paints) // 2], 2),
                                               round(paints[min(len(paints) - 1, int(len(paints) * .95))], 2)]
                                              if paints else None)}
            self.save()

        def _idle_probe(self):
            token = object()
            key = id(token)
            self._idle_token = token

            def second():
                self.idle_marks[key] = time.perf_counter()
            QTimer.singleShot(0, lambda: QTimer.singleShot(0, second))
            return key

        def track(self, name, action):
            """Run ``action`` once and record handler/frame/idle latency."""
            paints_before = len(self.paint_ends)
            profiler = None
            if name in profile_actions:
                import cProfile
                profiler = cProfile.Profile()
                profiler.enable()
            t0 = time.perf_counter()
            action()
            t1 = time.perf_counter()
            key = self._idle_probe()
            deadline = t1 + 2.0
            yield lambda: key in self.idle_marks or time.perf_counter() > deadline
            idle = self.idle_marks.pop(key, None)
            frame_deadline = time.perf_counter() + 0.5
            yield lambda: len(self.paint_ends) > paints_before or time.perf_counter() > frame_deadline
            frame = next((end for end in self.paint_ends[paints_before:] if end > t0), None)
            if profiler is not None:
                # Covers the handler, deferred work and everything up to the
                # first timeline paint (a delayed repaint shows up here).
                import io, pstats
                profiler.disable()
                stream = io.StringIO()
                stats = pstats.Stats(profiler, stream=stream)
                stats.sort_stats("cumtime").print_stats(70)
                stats.sort_stats("tottime").print_stats(25)
                count = len(self.result["actions"].get(name, {}).get("handler_ms", []))
                safe = name.replace(":", "_")
                (out / f"profile-{safe}-{count}.txt").write_text(stream.getvalue(), "utf8")
            row = self.result["actions"].setdefault(name, {"handler_ms": [], "frame_ms": [], "idle_ms": [],
                                                           "full_gc_ms": []})
            until = max(filter(None, (idle, frame, t1)))
            row.setdefault("full_gc_ms", []).append(round(sum(
                min(b, until) - max(a, t0) for a, b in self.full_gc_windows if b > t0 and a < until) * 1000, 1))
            row["handler_ms"].append(round((t1 - t0) * 1000, 2))
            row["frame_ms"].append(round((frame - t0) * 1000, 2) if frame else None)
            row["idle_ms"].append(round((idle - t0) * 1000, 2) if idle else None)

        def mouse(self, kind, point, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton,
                  modifiers=Qt.KeyboardModifier.NoModifier):
            timeline = self.page.timeline
            point = QPointF(point)
            global_point = timeline.mapToGlobal(point.toPoint())
            QApplication.sendEvent(timeline, QMouseEvent(kind, point, QPointF(global_point), button,
                                                         buttons, modifiers))

        def gesture(self, name, start, dx_total, steps=40, interval_ms=16):
            """Press, continuous moves at a fixed cadence, release: a real drag."""
            moves, state = [], {"i": 0}
            paints_before = len(self.paint_ends)
            gaps_before = len(self.gaps.get(self.phase, []))
            # Like a hand: the first move follows the press by one interval,
            # so deferred press work competes with the drag as it really does.
            t_press = time.perf_counter()
            self.mouse(QEvent.Type.MouseButtonPress, start)
            press_handler = (time.perf_counter() - t_press) * 1000
            timeline = self.page.timeline
            drag = getattr(timeline, "_drag", None)
            mode = ("group" if getattr(timeline, "_group_drag", None) is not None
                    else (drag[1] if drag else "none"))
            timer = QTimer(self)
            timer.setTimerType(Qt.TimerType.PreciseTimer)

            def step():
                state["i"] += 1
                x = start.x() + dx_total * state["i"] / steps
                t = time.perf_counter()
                self.mouse(QEvent.Type.MouseMove, QPointF(x, start.y()), Qt.MouseButton.NoButton)
                moves.append((t, time.perf_counter()))
                if state["i"] >= steps:
                    timer.stop()
            timer.timeout.connect(step)
            timer.start(interval_ms)
            yield lambda: state["i"] >= steps
            yield 0.05
            end = QPointF(start.x() + dx_total, start.y())
            yield from self.track(name + ":release", lambda: self.mouse(
                QEvent.Type.MouseButtonRelease, end, buttons=Qt.MouseButton.NoButton))
            yield 1.5  # deferred work after release (QC, previews) shows up as stalls
            paints = [p for p in self.paint_ends[paints_before:]]
            per_move = []
            for injected, handled in moves:
                frame = next((p for p in paints if p > injected), None)
                per_move.append(((frame - injected) * 1000) if frame else None)
            move_paints = [p for p in paints if moves and moves[0][0] <= p <= moves[-1][1] + 0.05]
            intervals = [(b - a) * 1000 for a, b in zip(move_paints, move_paints[1:])]
            gaps = self.gaps.get(self.phase, [])[gaps_before:]
            press_frame = next((p for p in paints if p > t_press), None)
            record = self.result["gestures"].setdefault(name, [])
            record.append({"mode": mode, "press_handler_ms": round(press_handler, 2),
                           "press_frame_ms": round((press_frame - t_press) * 1000, 2) if press_frame else None,
                           "first_move_frame_ms": round(per_move[0], 2) if per_move and per_move[0] else None,
                           "move_handler_ms": _dist([(h - i) * 1000 for i, h in moves]),
                           "move_frame_ms": _dist(per_move), "frame_interval_ms": _dist(intervals),
                           "moves": len(moves), "paints": len(move_paints),
                           "stall_after_release_ms": round(max(gaps) if gaps else 0, 1)})

        def visible_cue_rects(self, limit=None):
            timeline = self.page.timeline
            rows = []
            for cue in timeline.visible_cues():
                rect = timeline._active_cue_rect(cue.id)
                if rect.width() > 14:
                    rows.append((cue, rect))
            return rows[:limit] if limit else rows

        def until(self, condition, seconds, label):
            """Wait for ``condition``; a timeout is recorded, never hangs the run."""
            deadline = time.perf_counter() + seconds

            def check():
                if condition():
                    return True
                if time.perf_counter() > deadline:
                    self.result["errors"].setdefault("timeouts", []).append(label)
                    return True
                return False
            return check

        def body_grab(self, rows):
            """The widest cue whose centre really grabs its body (not an edge or
            an overlapping neighbour's handle), or None."""
            timeline = self.page.timeline
            for cue, rect in sorted(rows, key=lambda row: -row[1].width()):
                hit, mode = timeline._cue_at(rect.center())
                if hit is not None and hit.id == cue.id and mode == "move":
                    return cue, rect
            return None

        def grab_rect(self, rows):
            return self.body_grab(rows) or max(rows, key=lambda row: row[1].width())

        def clean_project(self):
            stack = self.page.undo_stack
            while stack.canUndo():
                stack.undo()
            stack.setClean()
            self.page.project_dirty = False

        # --------------------------------------------------------------- phases
        def run(self):
            page = self.page
            t_open = time.perf_counter()
            yield self.until(self.ready, 120, "open")
            self.result["open_ready_s"] = round(time.perf_counter() - t_open, 3)
            self.result["cue_count"] = len(page.project.cues)
            self.result["speakers"] = len({c.speaker_id for c in page.project.cues})
            page.video.set_paused(True)
            try:
                page.volume_slider.setValue(0)
            except Exception:
                pass
            yield 6.0
            for name in phases:
                body = getattr(self, "phase_" + name.replace("-", "_"), None)
                if body is None:
                    self.result["errors"][name] = "unknown phase"
                    continue
                yield from self.phase_run(name, body)

        def phase_idle(self):
            yield 5.0

        phase_idle_final = phase_idle

        def phase_select(self):
            timeline = self.page.timeline
            timeline.set_visible_window(300_000, 120_000)
            yield 0.6
            rows = self.visible_cue_rects(12)
            for cue, rect in rows:
                c = rect.center()
                yield from self.track("select-click", lambda c=c: (
                    self.mouse(QEvent.Type.MouseButtonPress, c),
                    self.mouse(QEvent.Type.MouseButtonRelease, c, buttons=Qt.MouseButton.NoButton)))
                yield 0.2
            self.result["checks"]["select_last_ok"] = bool(rows) and self.page.session.selected_cue_id == rows[-1][0].id

        def phase_drag_repeat(self):
            page, timeline = self.page, self.page.timeline
            timeline.set_visible_window(300_000, 120_000)
            yield 0.6
            window_ms = 120_000
            if self.body_grab(self.visible_cue_rects(23)) is None:
                # Dense overlapping tracks: zoom in until a cue body is grabbable.
                window_ms = 30_000
                timeline.set_visible_window(300_000, window_ms)
                yield 0.6
            self.result["checks"]["drag_window_ms"] = window_ms
            for repeat in range(drag_repeats):
                rows = self.visible_cue_rects(23)
                ids = [cue.id for cue, _ in rows]
                if len(ids) < 2:
                    raise RuntimeError("not enough visible cues for a multi drag")
                cue, rect = self.grab_rect(rows)
                before = {c.id: (c.start_ms, c.end_ms) for c in page.project.cues if c.id in ids}
                timeline.set_selected_ids(ids, cue.id)
                yield 0.3
                direction = 1 if repeat % 2 == 0 else -1
                if repeat == 0:
                    # Press and release in place: isolates what a press costs
                    # until the event loop is idle, without a drag following.
                    c = rect.center()
                    yield from self.track("multi-press", lambda: self.mouse(QEvent.Type.MouseButtonPress, c))
                    yield from self.track("multi-press-release", lambda: self.mouse(
                        QEvent.Type.MouseButtonRelease, c, buttons=Qt.MouseButton.NoButton))
                    timeline.set_selected_ids(ids, cue.id)
                    yield 0.5
                yield from self.gesture("multi-drag", rect.center(), 60 * direction)
                after = {c.id: (c.start_ms, c.end_ms) for c in page.project.cues if c.id in ids}
                self.result["checks"].setdefault("multi_drag_moved", []).append(
                    sum(before[k] != after.get(k) for k in before))
            self.result["checks"]["multi_selected"] = len(ids)

        def phase_wide_press(self):
            """Press/release in place on a 300-cue selection (like a Shift range
            selection, mostly off screen): press cost must not grow with it."""
            page, timeline = self.page, self.page.timeline
            timeline.set_visible_window(300_000, 120_000)
            yield 0.6
            rows = self.visible_cue_rects()
            if not rows:
                raise RuntimeError("no visible cue for a wide press")
            cue, rect = self.grab_rect(rows)
            others = [c.id for c in sorted(page.project.cues, key=lambda c: (c.start_ms, c.id))]
            ids = list(dict.fromkeys([cue.id, *others]))[:300]
            for repeat in range(3):
                timeline.set_selected_ids(ids, cue.id)
                yield 0.4
                c = rect.center()
                yield from self.track("wide-press", lambda: self.mouse(QEvent.Type.MouseButtonPress, c))
                yield from self.track("wide-press-release", lambda: self.mouse(
                    QEvent.Type.MouseButtonRelease, c, buttons=Qt.MouseButton.NoButton))
                yield 0.4
            self.result["checks"]["wide_press_selected"] = len(ids)

        def phase_select_all_drag(self):
            page, timeline = self.page, self.page.timeline
            timeline.set_visible_window(300_000, 120_000)
            yield 0.5
            from PySide6.QtGui import QKeyEvent
            timeline.setFocus()
            yield 0.2

            def ctrl_a():
                for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                    QApplication.sendEvent(timeline, QKeyEvent(kind, Qt.Key.Key_A,
                                                               Qt.KeyboardModifier.ControlModifier, "a"))
            yield from self.track("select-all", ctrl_a)
            yield 0.5
            rows = self.visible_cue_rects()
            if not rows:
                raise RuntimeError("no visible cue")
            cue, rect = self.grab_rect(rows)
            selected = timeline.clip_selection().count
            before = {c.id: c.start_ms for c in page.project.cues}
            yield from self.gesture("select-all-drag", rect.center(), 40, steps=20)
            moved = sum(before[c.id] != c.start_ms for c in page.project.cues if c.id in before)
            self.result["checks"]["select_all"] = {"selected": selected, "moved": moved}
            yield from self.track("select-all-undo", page._undo_interactive)
            yield 1.0

        def phase_undo_redo(self):
            page = self.page
            for _ in range(4):
                if page.undo_stack.canUndo():
                    yield from self.track("undo", page._undo_interactive)
                yield 0.4
            for _ in range(4):
                if page.undo_stack.canRedo():
                    yield from self.track("redo", page._redo_interactive)
                yield 0.4

        def phase_delete_cues(self):
            page, timeline = self.page, self.page.timeline
            timeline.set_visible_window(600_000, 120_000)
            yield 0.5
            rows = self.visible_cue_rects(20)
            ids = [cue.id for cue, _ in rows]
            count = len(page.project.cues)
            # Leave the earlier Ctrl+A cross-track selection like a click on
            # empty space does (clicking a cue inside it keeps it whole), then
            # click a cue; the rest is the Ctrl+click multi-selection result.
            from .studio_selection import ClipSelection
            timeline._publish_clip_selection(ClipSelection())
            yield 0.2
            c = self.grab_rect(rows)[1].center()
            self.mouse(QEvent.Type.MouseButtonPress, c)
            self.mouse(QEvent.Type.MouseButtonRelease, c, buttons=Qt.MouseButton.NoButton)
            yield 0.3
            # The state a run of Ctrl+clicks leaves: page and timeline in sync.
            from .selection_scope import SelectionScope
            page.cue_controller.apply_selection_scope(SelectionScope.explicit(ids, ids[0]))
            timeline.setFocus()
            yield 0.3
            self.result["checks"]["delete_selected"] = len(page.cue_controller.selected_cue_ids())
            yield from self.track("delete-cues", page._delete_current)
            self.result["checks"]["delete_removed"] = count - len(page.project.cues)
            yield 0.8
            yield from self.track("delete-undo", page._undo_interactive)
            self.result["checks"]["delete_restored"] = len(page.project.cues) == count
            yield 0.8

        def phase_ripple_trim(self):
            page, timeline = self.page, self.page.timeline
            # Inside the edited video of every test project (its sequence is
            # shorter than the source media the large projects spread over).
            target_ms = min(max(c.end_ms for c in page.project.cues) // 2, 200_000)
            page._seek(target_ms / 1000)
            yield self.until(lambda: abs(timeline.playhead_ms - target_ms) < 80, 10, "ripple-seek")
            self.result["checks"]["ripple_playhead_ms"] = int(timeline.playhead_ms)
            yield 0.6
            timeline.set_selected_ids((), "")
            page.session.selected_cue_id = ""
            timeline.setFocus()
            before = [(c.id, c.start_ms) for c in page.project.cues]
            yield from self.track("ripple-trim", lambda: page._trim_to_playhead("start"))
            after = {c.id: c.start_ms for c in page.project.cues}
            self.result["checks"]["ripple_shifted"] = sum(after.get(k) != v for k, v in before)
            yield 1.0
            yield from self.track("ripple-undo", page._undo_interactive)
            self.result["checks"]["ripple_restored"] = [(c.id, c.start_ms) for c in page.project.cues] == before
            yield 1.0

        def phase_text_edit(self):
            page = self.page
            cue = next((c for c in page.project.cues if c.start_ms >= 300_000), page.project.cues[0])
            page.cue_controller.select_cue(cue.id)
            yield 0.4
            original = cue.text
            for i in range(5):
                yield from self.track("text-commit", lambda i=i: page.cue_controller.set_text(cue.id, original + str(i)))
                yield 0.4
            self.result["checks"]["text_applied"] = cue.text == original + "4"

        def phase_playback(self):
            page = self.page
            page._seek(300.0)
            yield 1.5
            before = page.video.visual_position()
            page.video.set_paused(False)
            yield 8.0
            after = page.video.visual_position()
            page.video.set_paused(True)
            self.result["checks"]["playback_advanced_s"] = round(after - before, 3)
            yield 1.0

        # ------------------------------------------------ long rate endurance
        def _av_sample(self):
            """Video clock vs audio engine position, both in source/project media ms."""
            page = self.page
            clock = page.video._playback_clock
            snap = clock.sample_presentation(source="audit")
            engine = getattr(page, "audio_engine", None)
            tele = dict(getattr(engine, "_telemetry", {}) or {})
            now = time.monotonic()
            est = tele.get("estimated_source_ms")
            rate = float(tele.get("effective_rate") or 1.0)
            age = now - float(tele.get("received_monotonic") or now)
            playing = str(tele.get("state") or "") in {"PLAYING", "SYNCED"}
            audio_now = (float(est) + (age * 1000.0 * rate if playing else 0.0)) if est is not None else None
            video_ms = float(snap.presentation_media_ms)
            return {"wall": round(time.perf_counter() - started, 3), "rate": float(page.video._playback_rate),
                    "paused": bool(page.video._paused), "video_ms": round(video_ms, 1),
                    "audio_ms": round(audio_now, 1) if audio_now is not None else None,
                    "av_ms": round(video_ms - audio_now, 1) if audio_now is not None and playing else None,
                    "audio_state": str(tele.get("state") or ""), "telemetry_age_ms": round(age * 1000, 1),
                    "generation": int(snap.playback_generation)}

        def _playing_intent(self):
            """User intent, not the transport: buffering and the seek hold
            pause the transport while the user is still playing. (Treating
            those as "paused" made this audit press Space and pause playback.)"""
            video = self.page.video
            intended = getattr(video, "playback_intended", None)
            if intended is not None:
                return bool(intended)
            return not video._paused or bool(getattr(video, "_buffered_play_pending", False))

        def _pause_latency(self, label):
            """Toggle pause like the Space key and time until audio/video both stop."""
            page = self.page
            if not self._playing_intent():
                self.result.setdefault("pause_latency_ms", []).append({"label": label, "skipped": "not playing"})
                return
            t = time.perf_counter()
            page._toggle_playback()
            engine = getattr(page, "audio_engine", None)

            def stopped():
                tele = dict(getattr(engine, "_telemetry", {}) or {})
                audio_paused = str(tele.get("state") or "") not in {"PLAYING", "SYNCED"} or bool(tele.get("paused"))
                mpv_paused = bool(getattr(page.video.controller, "observed_property", lambda *_: None)("pause", None))
                return (audio_paused and mpv_paused) or time.perf_counter() - t > 10
            yield stopped
            self.result.setdefault("pause_latency_ms", []).append(
                {"label": label, "ms": round((time.perf_counter() - t) * 1000, 1)})

        def phase_playback_endurance(self):
            """Continuous fast playback with rate switches, seeks, pauses and panel work.

            Reports media progress and wall time separately; never treats media
            minutes at 4x as wall minutes.
            """
            import random
            page = self.page
            rng = random.Random(int(os.environ.get("PERF_ENDURANCE_SEED", "20261012")))
            wall_s = float(os.environ.get("PERF_ENDURANCE_S", "600"))
            duration_ms = max(1, int(getattr(page.timeline, "duration_ms", 0) or 0))
            try:
                from .studio_edit_sequence import timeline_duration_ms
                duration_ms = max(duration_ms, int(timeline_duration_ms(page.project)))
            except Exception:
                pass
            samples = self.result.setdefault("endurance_samples", [])
            events = self.result.setdefault("endurance_events", [])
            page._seek(min(30.0, duration_ms / 4000.0))
            yield 1.5
            page._set_speed(4.0)
            yield 0.3
            page._toggle_playback()
            yield 1.0
            t0 = time.perf_counter()
            media_played = 0.0
            next_sample = 0.0
            next_action = 6.0
            last_video = None
            tabs = page.context_drawer.count() if hasattr(page, "context_drawer") else 0
            actions = ("rate", "seek", "pause", "panel", "rate", "seek", "scroll")
            index = 0
            next_snapshot = 30.0
            while time.perf_counter() - t0 < wall_s:
                elapsed = time.perf_counter() - t0
                if elapsed >= next_snapshot:
                    # Memory/handle trend inside the run, not only before/after.
                    self.snapshot(f"endurance@{int(elapsed)}s")
                    next_snapshot = elapsed + 30.0
                if elapsed >= next_sample:
                    row = self._av_sample()
                    if last_video is not None and not row["paused"] and row["generation"] == last_video[1]:
                        media_played += max(0.0, row["video_ms"] - last_video[0])
                    last_video = (row["video_ms"], row["generation"])
                    samples.append(row)
                    next_sample = elapsed + 0.5
                if elapsed >= next_action:
                    kind = actions[index % len(actions)]
                    index += 1
                    stamp = round(elapsed, 2)
                    try:
                        if kind == "rate":
                            value = rng.choice((1.0, 2.0, 4.0, 4.0))
                            page._set_speed(value)
                            events.append({"t": stamp, "action": "rate", "value": value})
                        elif kind == "seek":
                            target = rng.uniform(0, max(1.0, duration_ms / 1000.0 - 20))
                            page._seek(target)
                            events.append({"t": stamp, "action": "seek", "target_s": round(target, 2)})
                        elif kind == "pause":
                            yield from self._pause_latency(f"pause@{stamp}")
                            yield 1.0
                            if not self._playing_intent():
                                page._toggle_playback()
                            events.append({"t": stamp, "action": "pause-resume"})
                        elif kind == "panel" and tabs:
                            page.context_drawer.setCurrentIndex(rng.randrange(tabs))
                            events.append({"t": stamp, "action": "panel"})
                        elif kind == "scroll":
                            page._zoom_timeline(rng.choice((0.8, 1.25)))
                            events.append({"t": stamp, "action": "scroll"})
                    except Exception:
                        self.result["errors"][f"endurance-{kind}-{stamp}"] = traceback.format_exc()
                    if not self._playing_intent() and kind != "pause":
                        page._toggle_playback()
                    next_action = elapsed + rng.uniform(4.0, 9.0)
                yield 0.02
            yield from self._pause_latency("final")
            from .gui_stall_watchdog import instance
            watchdog = instance()
            offsets = [abs(r["av_ms"]) for r in samples if r.get("av_ms") is not None]
            self.result["endurance"] = {
                "wall_s": round(time.perf_counter() - t0, 1),
                "media_played_s": round(media_played / 1000.0, 1),
                "samples": len(samples), "actions": len(events),
                "av_abs_ms": _dist(offsets),
                "stall_watchdog": watchdog.lag_stats(window_s=wall_s + 30) if watchdog is not None else None,
            }
            page._set_speed(1.0)
            yield 1.0

        # --------------------------------------------- back-to-back captions
        def _window_frames(self, crop_widget):
            """PrintWindow burst of the real window, cropped to the caption band."""
            import ctypes, threading
            from ctypes import wintypes as W
            from PySide6.QtCore import QPoint
            user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
            user.GetWindowDC.argtypes = [W.HWND]; user.GetWindowDC.restype = W.HDC
            user.ReleaseDC.argtypes = [W.HWND, W.HDC]
            user.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
            gdi.CreateCompatibleDC.argtypes = [W.HDC]; gdi.CreateCompatibleDC.restype = W.HDC
            gdi.CreateCompatibleBitmap.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
            gdi.CreateCompatibleBitmap.restype = W.HBITMAP
            gdi.SelectObject.argtypes = [W.HDC, W.HANDLE]; gdi.SelectObject.restype = W.HANDLE
            gdi.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, ctypes.c_void_p, ctypes.c_void_p, W.UINT]
            gdi.DeleteObject.argtypes = [W.HANDLE]; gdi.DeleteDC.argtypes = [W.HDC]
            hwnd = int(window.winId())
            rect = W.RECT(); user.GetWindowRect(W.HWND(hwnd), ctypes.byref(rect))
            width, height = rect.right - rect.left, rect.bottom - rect.top
            ratio = window.devicePixelRatioF()
            origin = crop_widget.mapTo(window, QPoint(0, 0))
            w, h = crop_widget.width(), crop_widget.height()
            # Caption band: lower 24 % of the video, central 80 %.
            crop = (int((origin.x() + w * 0.1) * ratio), int((origin.y() + h * 0.76) * ratio),
                    int((origin.x() + w * 0.9) * ratio), int((origin.y() + h) * ratio))
            frames, stop = [], threading.Event()

            class Info(ctypes.Structure):
                _fields_ = [('biSize', ctypes.c_uint32), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                            ('biPlanes', ctypes.c_ushort), ('biBitCount', ctypes.c_ushort),
                            ('biCompression', ctypes.c_uint32), ('biSizeImage', ctypes.c_uint32),
                            ('a', ctypes.c_long), ('b', ctypes.c_long), ('c', ctypes.c_uint32),
                            ('d', ctypes.c_uint32), ('colors', ctypes.c_uint32 * 3)]

            def loop():
                import numpy as np
                source = user.GetWindowDC(W.HWND(hwnd))
                memory = gdi.CreateCompatibleDC(source)
                bitmap = gdi.CreateCompatibleBitmap(source, width, height)
                previous = gdi.SelectObject(memory, bitmap)
                buffer = ctypes.create_string_buffer(width * height * 4)
                info = Info(); info.biSize = 40; info.biWidth = width; info.biHeight = -height
                info.biPlanes = 1; info.biBitCount = 32
                try:
                    while not stop.is_set():
                        started = time.perf_counter()
                        if user.PrintWindow(W.HWND(hwnd), memory, 2) and gdi.GetDIBits(
                                memory, bitmap, 0, height, buffer, ctypes.byref(info), 0) == height:
                            pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
                            band = pixels[crop[1]:crop[3], crop[0]:crop[2], :3].copy()
                            frames.append((started, band))
                finally:
                    gdi.SelectObject(memory, previous); gdi.DeleteObject(bitmap); gdi.DeleteDC(memory)
                    user.ReleaseDC(W.HWND(hwnd), source)
            worker = threading.Thread(target=loop, daemon=True, name="audit-frame-capture")
            return frames, stop, worker

        def phase_caption_handoff(self):
            """Play across back-to-back cue boundaries at 1x/2x/4x and look at
            the actual window: a captured frame without caption ink between
            two frames with ink is a blank; overlay REMOVE events in the same
            window are the state-side evidence."""
            import numpy as np
            from .runtime_trace import GLOBAL_STUDIO_TRACE
            page = self.page
            cues = sorted(page.project.cues, key=lambda c: (c.start_ms, c.id))
            pairs = [(a, b) for a, b in zip(cues, cues[1:])
                     if a.end_ms == b.start_ms and a.end_ms - a.start_ms >= 2000 and b.end_ms - b.start_ms >= 700
                     and a.text.strip() and b.text.strip()]
            pairs = pairs[:int(os.environ.get("PERF_HANDOFF_PAIRS", "5"))]
            report = self.result.setdefault("caption_handoff", {"pairs": len(pairs), "runs": []})
            out_dir = out / "handoff"
            out_dir.mkdir(exist_ok=True)
            clock_rows = []

            def sample_clock():
                # Timeline time: cue times live there (mapped FLV clocks run in source time).
                clock_rows.append((time.perf_counter(), float(page.timeline.playhead_ms)))
            ticker = QTimer(self)
            ticker.setTimerType(Qt.TimerType.PreciseTimer)
            ticker.setInterval(8)
            ticker.timeout.connect(sample_clock)
            for rate in (1.0, 2.0, 4.0):
                page._set_speed(rate)
                yield 0.3
                for index, (a, b) in enumerate(pairs):
                    boundary = int(a.end_ms)
                    # Project (timeline) time: cues are in timeline time.
                    page.video.set_paused(True)
                    # Start inside cue A like a user does: the boundary lies
                    # beyond a fixed media look-ahead at 2x/4x.
                    page._seek((a.start_ms + 100) / 1000.0)
                    yield 1.2
                    frames, stop, worker = self._window_frames(page.video)
                    clock_rows.clear()
                    ticker.start()
                    worker.start()
                    t_start = time.perf_counter()
                    m_start = time.monotonic()
                    epoch_start = time.time()
                    page._toggle_playback()
                    deadline = time.perf_counter() + 6.0
                    yield lambda: (int(page.timeline.playhead_ms) >= boundary + 700 * rate
                                   or time.perf_counter() > deadline)
                    page.video.set_paused(True)
                    stop.set(); worker.join(2); ticker.stop()
                    t_end = time.perf_counter()
                    m_end = time.monotonic()
                    epoch_end = time.time()
                    if not frames or len(clock_rows) < 2:
                        report["runs"].append({"rate": rate, "pair": index, "error": "no frames"})
                        continue
                    times = np.array([row[0] for row in clock_rows]); media = np.array([row[1] for row in clock_rows])
                    rows = []
                    for at, band in frames:
                        white = np.count_nonzero((band > 225).all(axis=2))
                        rows.append({"t_ms": round((at - t_start) * 1000, 1),
                                     "media_ms": round(float(np.interp(at, times, media)), 1), "ink": int(white)})
                    # Caption ink in frames around the boundary while a cue must show.
                    covered = [r for r in rows if a.start_ms + 150 * rate <= r["media_ms"] <= b.end_ms - 150 * rate]
                    inks = [r["ink"] for r in covered]
                    reference = float(np.median(inks)) if inks else 0.0
                    blanks = [r for r in covered if reference > 0 and r["ink"] < 0.25 * reference
                              and abs(r["media_ms"] - boundary) <= 400 * rate]
                    removes = [e for e in list(GLOBAL_STUDIO_TRACE._ring)
                               if e.get("event") == "COMPOSITOR_OVERLAY_LIFECYCLE" and e.get("overlay_id") == 1
                               and e.get("action") == "REMOVE"
                               and m_start - 0.05 <= float(e.get("time_monotonic") or 0) <= m_end]
                    # State side: a retire of a non-empty set followed by the
                    # next set's publication is a blank interval on screen.
                    from datetime import datetime
                    def epoch(record):
                        try:
                            return datetime.fromisoformat(str(record.get("time"))).timestamp()
                        except (TypeError, ValueError):
                            return 0.0
                    trace_rows = [r for r in list(GLOBAL_STUDIO_TRACE._ring)
                                  if epoch_start - 0.05 <= epoch(r) <= epoch_end + 0.5
                                  and r.get("event") in ("CAPTION_SCENE_RETIRED", "CAPTION_SCENE", "CAPTION_SCENE_HELD")]
                    blank_intervals, held = [], []
                    retired_at = None
                    for r in trace_rows:
                        if (r["event"] == "CAPTION_SCENE_RETIRED" and r.get("previous_cue_ids")
                                and r.get("cue_ids") and not r.get("geometry_changed")):
                            retired_at = epoch(r)
                        elif r["event"] == "CAPTION_SCENE" and r.get("posted") and retired_at is not None:
                            blank_intervals.append(round((epoch(r) - retired_at) * 1000, 1))
                            retired_at = None
                        elif r["event"] == "CAPTION_SCENE" and r.get("held_previous_ms") is not None:
                            held.append(r.get("held_previous_ms"))
                    folder = out_dir / f"x{int(rate)}-pair{index}"
                    folder.mkdir(exist_ok=True)
                    try:
                        from PIL import Image
                        for frame_index, (at, band) in enumerate(frames):
                            Image.fromarray(band[:, :, ::-1]).reduce(2).save(folder / f"{frame_index:03d}.png")
                    except Exception as exc:
                        self.result["errors"][f"handoff-save-{rate}-{index}"] = repr(exc)
                    (folder / "frames.json").write_text(json.dumps(dict(
                        boundary_ms=boundary, cue_a=a.id, cue_b=b.id, rate=rate, frames=rows), indent=1), "utf8")
                    report["runs"].append({"rate": rate, "pair": index, "boundary_ms": boundary,
                                           "frames": len(rows), "covered_frames": len(covered),
                                           "reference_ink": reference, "blank_frames": len(blanks),
                                           "blank_media_ms": [r["media_ms"] for r in blanks],
                                           "overlay_removes": len(removes),
                                           "trace_blank_ms": blank_intervals, "trace_held_ms": held})
                    self.save()
            page._set_speed(1.0)
            yield 0.5

        # ----------------------------------------------- across edit points
        def phase_cut_crossing(self):
            """Ripple-delete ranges with the product's own command, then play
            across every resulting edit point at 1x/2x/4x and compare the
            video clock with the audio position before and after the cut."""
            from .studio_clip_edit import ripple_ranges_command
            from .studio_edit_sequence import timeline_duration_ms
            page = self.page
            duration = int(timeline_duration_ms(page.project))
            fractions = ((0.18, 0.04), (0.45, 0.03), (0.72, 0.05))
            ranges = [(int(duration * a), int(duration * (a + w))) for a, w in fractions]
            undo_before = page.undo_stack.index()
            page.undo_stack.push(ripple_ranges_command(page.project, ranges, page=page, label="audit ripple"))
            yield 1.5
            # Edit points in the new timeline: each deletion closes onto its start.
            removed = 0
            points = []
            for a, b in ranges:
                points.append(a - removed)
                removed += b - a
            report = self.result.setdefault("cut_crossing", {"ranges": ranges, "points": points, "runs": []})
            for rate in (1.0, 2.0, 4.0):
                page._set_speed(rate)
                yield 0.3
                for point in points:
                    page.video.set_paused(True)
                    page._seek(max(0.0, (point - 2500 * rate) / 1000.0))
                    yield 1.2
                    page._toggle_playback()
                    rows = []
                    deadline = time.perf_counter() + 9.0
                    while time.perf_counter() < deadline and int(page.timeline.playhead_ms) < point + 3500 * rate:
                        row = self._av_sample()
                        row["timeline_ms"] = int(page.timeline.playhead_ms)
                        rows.append(row)
                        yield 0.1
                    page.video.set_paused(True)
                    yield 0.3

                    def offsets(lo, hi):
                        values = [abs(r["av_ms"]) / rate for r in rows
                                  if r.get("av_ms") is not None and lo <= r["timeline_ms"] < hi]
                        return _dist(values)
                    report["runs"].append({
                        "rate": rate, "point_ms": point, "samples": len(rows),
                        # Offsets in WALL ms (media ms / rate) so rates compare fairly.
                        "before_wall_ms": offsets(point - 2000 * rate, point),
                        "after_wall_ms": offsets(point + 700 * rate, point + 3500 * rate),
                        "reached_ms": rows[-1]["timeline_ms"] if rows else None})
                    self.save()
            page._set_speed(1.0)
            while page.undo_stack.index() > undo_before and page.undo_stack.canUndo():
                page.undo_stack.undo()
            yield 1.0

        # ------------------------- does a stuck mpv window freeze our GUI?
        def phase_mpv_stall_coupling(self):
            """Suspend the mpv child process (its window thread stops pumping
            messages, as when presentation blocks) while playing at 4x and
            while the user keeps interacting; measure our GUI thread."""
            import psutil
            page = self.page
            controller = page.video.controller
            process = getattr(controller, "_process", None)
            report = self.result.setdefault("mpv_stall_coupling", [])
            if process is None:
                report.append({"error": "no mpv process"})
                return
            mpv = psutil.Process(process.pid)
            page._seek(30.0)
            yield 1.0
            page._set_speed(4.0)
            yield 0.3
            if not self._playing_intent():
                page._toggle_playback()
            yield 3.0
            for label, poke in (
                ("idle", lambda: None),
                ("panel+zoom", lambda: (page.context_drawer.setCurrentIndex(
                    (page.context_drawer.currentIndex() + 1) % max(1, page.context_drawer.count())),
                    page._zoom_timeline(1.1))),
                ("resize", lambda: window.resize(window.width() - 40, window.height())),
                ("pause", lambda: page._toggle_playback()),
            ):
                gaps_before = len(self.gaps.get(self.phase, []))
                t = time.perf_counter()
                import threading
                # Resumed from another thread: if the GUI thread itself gets
                # stuck behind the suspended window, it still ends.
                resumer = threading.Timer(3.0, mpv.resume)
                mpv.suspend()
                resumer.start()
                poke_started = poke_ended = None
                end = time.perf_counter() + 3.2
                while time.perf_counter() < end:
                    if poke_started is None and time.perf_counter() - t > 0.5:
                        poke_started = time.perf_counter(); poke(); poke_ended = time.perf_counter()
                    yield 0.02
                resumer.join(1.0)
                window_gaps = self.gaps.get(self.phase, [])[gaps_before:]
                report.append({"case": label, "suspended_s": round(time.perf_counter() - t, 2),
                               "gui_max_gap_ms": round(max(window_gaps), 1) if window_gaps else None,
                               "gui_beats": len(window_gaps),
                               "poke_ms": round((poke_ended - poke_started) * 1000, 1) if poke_started else None})
                self.save()
                yield 2.0
                if label == "pause" and not self._playing_intent():
                    page._toggle_playback()
                    yield 1.0
            page.video.set_paused(True)
            page._set_speed(1.0)
            yield 1.0

        def phase_save_reopen(self):
            page = self.page
            cue = page.project.cues[0]
            page.cue_controller.set_text(cue.id, cue.text + "·")
            yield 0.4
            yield from self.track("save", page.save)
            yield 1.0
            path = str(page.session.project_path)
            old = page.project
            t = time.perf_counter()
            page.show_project_hub(skip_dirty_guard=True)
            yield self.until(lambda: page.project is None, 30, "close")
            self.result.setdefault("close_s", []).append(round(time.perf_counter() - t, 3))
            yield 1.0
            t = time.perf_counter()
            deadline = t + 90
            window.open_studio_project(path, mode="edit", source="startup_audit")
            yield lambda: (page.project is not None and page.project is not old and self.ready()) or time.perf_counter() > deadline
            self.result.setdefault("reopen_ready_s", []).append(round(time.perf_counter() - t, 3))
            page.video.set_paused(True)
            self.result["checks"]["saved_text_reopened"] = bool(page.project) and page.project.cues[0].text.endswith("·")
            # Restore the copy for later phases (the original stays untouched).
            if page.project:
                page.cue_controller.set_text(page.project.cues[0].id, page.project.cues[0].text[:-1])
                yield 0.3
                page.save()
            yield 2.0

        def phase_close_while_busy(self):
            """Discard an unsaved edit while background work is in flight, then
            reopen: nothing stale may be written back into the project."""
            import hashlib
            page, timeline = self.page, self.page.timeline
            path = Path(str(page.session.project_path))
            digest = lambda: hashlib.sha256(path.read_bytes()).hexdigest()
            self.clean_project()
            page.save()
            yield 1.0
            saved = digest()
            cue = page.project.cues[len(page.project.cues) // 2]
            original_text = cue.text
            page.cue_controller.set_text(cue.id, original_text + "【丢弃】")
            # Start a drag preview warm-up and a QC refresh, then leave at once.
            timeline.set_selected_ids([c.id for c in page.project.cues[:40]], cue.id)
            page._cue_timing_preview.request_warm()
            yield 0.03
            page.show_project_hub(skip_dirty_guard=True)
            yield self.until(lambda: page.project is None, 30, "busy-close")
            yield 3.0  # late workers / autosave timers would land here
            self.result["checks"]["busy_close_file_unchanged"] = digest() == saved
            deadline = time.perf_counter() + 90
            window.open_studio_project(str(path), mode="edit", source="startup_audit")
            yield lambda: (page.project is not None and self.ready()) or time.perf_counter() > deadline
            page.video.set_paused(True)
            yield 2.0
            reopened = next((c for c in page.project.cues if c.id == cue.id), None) if page.project else None
            self.result["checks"]["busy_close_discarded_text_absent"] = bool(reopened) and reopened.text == original_text
            from .project_dirty_guard import ProjectDirtyGuard
            self.result["checks"]["busy_close_reopened_clean"] = bool(page.project) and page.undo_stack.isClean()                 and not ProjectDirtyGuard(page).is_dirty() and not page._cue_timing_preview.active
            self.result["checks"]["busy_close_file_unchanged_after_reopen"] = digest() == saved
            self.snapshot("busy-close-reopened")

        def phase_leak_cycles(self):
            page = self.page
            path = str(page.session.project_path)
            for i in range(int(os.environ.get("PERF_LEAK_CYCLES", "3"))):
                self.clean_project()
                yield 0.5
                page.show_project_hub(skip_dirty_guard=True)
                yield self.until(lambda: page.project is None, 30, f"cycle-close-{i}")
                yield 2.0
                self.snapshot(f"closed-{i}")
                deadline = time.perf_counter() + 90
                t = time.perf_counter()
                window.open_studio_project(path, mode="edit", source="startup_audit")
                yield lambda: (page.project is not None and self.ready()) or time.perf_counter() > deadline
                self.result.setdefault("cycle_ready_s", []).append(round(time.perf_counter() - t, 3))
                page.video.set_paused(True)
                yield 3.0
                self.snapshot(f"reopened-{i}")

    Audit()
