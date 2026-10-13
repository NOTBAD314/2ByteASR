"""Opt-in page-entry timing audit for the management pages (2026-10-12).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=perf-pages`` through
``scripts/verify_perf_regression_headed.py --scenario pages``. It navigates
exactly like a user: it clicks the same header / sidebar / card buttons whose
signals the pages already connect (``QAbstractButton.click``), never private
page methods. Per entry it reports, from the click:

- ``handler_ms``: synchronous time inside the click handler.
- ``feedback_ms``: end of the first window frame painted after the click.
- ``content_ms``: end of the first frame painted while the page's useful
  content was present (cards filled with record data, workshop cards with
  their state, library cards present, the selected report's summary).
- ``interactive_ms``: after content, the first zero-timer round trip that
  completes within 50 ms (the event loop is responsive again).
- ``background_ms``: page-specific background work finished (scans, index
  writes, cover decoding, lazy batches).
- heartbeat stalls (16 ms precise timer) between the click and background.

Entries are measured once after process start ("first") and again in
``PAGES_CYCLES`` re-entry cycles. Sidebar geometry of Model Workshop,
Recognition History and Term Library is captured with window grabs at the
same window size. Results: ``<out>/perf.json``.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path


def _dist(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"n": 0}
    pick = lambda q: values[min(len(values) - 1, int(round((len(values) - 1) * q)))]
    return {"n": len(values), "min": round(values[0], 1), "p50": round(pick(.5), 1),
            "max": round(values[-1], 1)}


def _gui_objects():
    try:
        import ctypes
        kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        user32.GetGuiResources.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        handle = kernel32.GetCurrentProcess()
        return {"gdi": user32.GetGuiResources(handle, 0), "user": user32.GetGuiResources(handle, 1)}
    except Exception:
        return {}


def sidebar_metrics(window, page) -> dict:
    """Window-relative geometry of a management page's shared sidebar."""
    from PySide6.QtCore import QPoint
    from .ui_navigation import WorkspaceNavigation
    nav = page.findChild(WorkspaceNavigation)
    if nav is None:
        return {"error": "no WorkspaceNavigation"}
    sidebar = nav.parentWidget()
    while sidebar is not None and sidebar.parentWidget() is not page and sidebar is not page:
        sidebar = sidebar.parentWidget()
    sidebar = sidebar or nav.parentWidget()
    origin = sidebar.mapTo(window, QPoint(0, 0))
    content_left = None
    layout = page.layout()
    if layout is not None:
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is not None and widget is not sidebar and widget.isVisible():
                content_left = widget.mapTo(window, QPoint(0, 0)).x()
                break
    buttons = []
    for key, button in nav.buttons.items():
        top_left = button.mapTo(window, QPoint(0, 0))
        font = button.font()
        buttons.append({"key": key, "x": top_left.x(), "y": top_left.y(), "w": button.width(),
                        "h": button.height(), "font_px": font.pixelSize(), "font_pt": round(font.pointSizeF(), 2),
                        "font_weight": int(font.weight()), "icon": [button.iconSize().width(),
                                                                    button.iconSize().height()],
                        "checked": button.isChecked()})
    nav_origin = nav.mapTo(window, QPoint(0, 0))
    return {"sidebar_x": origin.x(), "sidebar_y": origin.y(), "sidebar_w": sidebar.width(),
            "sidebar_h": sidebar.height(), "nav_x": nav_origin.x(), "nav_y": nav_origin.y(),
            "nav_w": nav.width(), "content_left": content_left, "buttons": buttons,
            "sidebar_object": sidebar.objectName()}


_COSTS: dict[str, list] = {}
_REBUILD_REASONS: list[dict] = []


def _instrument() -> None:
    """Count time spent in the shared per-switch passes and page refreshes.

    Wrappers only measure; they call the original function unchanged. Module
    functions are looked up by name at call time by their callers.
    """
    def wrap(owner, name, label):
        original = getattr(owner, name, None)
        if original is None or getattr(original, "_perf_pages_wrapped", False):
            return

        def timed(*args, **kwargs):
            begin = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                row = _COSTS.setdefault(label, [0, 0.0])
                row[0] += 1
                row[1] += (time.perf_counter() - begin) * 1000
        timed._perf_pages_wrapped = True
        timed.__name__ = getattr(original, "__name__", name)
        timed.__doc__ = getattr(original, "__doc__", None)
        setattr(owner, name, timed)

    from . import i18n_widgets, ui_motion, ui_zoom
    wrap(ui_zoom, "apply_to", "zoom_walk")
    wrap(i18n_widgets, "apply", "language_pass")
    wrap(ui_motion, "settle_layout", "settle_layout")
    try:
        from .model_workshop import ModelWorkshopPage
        wrap(ModelWorkshopPage, "refresh", "workshop_refresh")
    except Exception:
        pass
    try:
        from .recognition_history import RecognitionHistoryPage
        wrap(RecognitionHistoryPage, "refresh", "history_refresh")
    except Exception:
        pass
    try:
        from .studio_hub import StudioHubMixin
        wrap(StudioHubMixin, "_rebuild_project_library", "library_rebuild_call")
    except Exception:
        pass
    try:
        from .studio_hub import StudioHubMixin
        rebuild = StudioHubMixin._rebuild_project_library

        def explained(self, *args, **kwargs):
            # Why a full library rebuild happened (diagnostics only).
            before_signature = getattr(self, "_hub_render_signature", None)
            before_generation = getattr(self, "_library_build_generation", 0)
            result = rebuild(self, *args, **kwargs)
            after_signature = getattr(self, "_hub_render_signature", None)
            if getattr(self, "_library_build_generation", 0) != before_generation:
                reason = {"t": round(time.perf_counter(), 3)}
                if before_signature is None or after_signature is None:
                    reason["what"] = "first"
                else:
                    names = ("records", "query", "sort", "columns", "card_width", "theme", "selection", "language")
                    reason["what"] = [name for name, a, b in zip(names, before_signature, after_signature) if a != b]
                    if before_signature[0] != after_signature[0]:
                        old_rows, new_rows = before_signature[0], after_signature[0]
                        reason["records"] = [len(old_rows), len(new_rows)]
                        diffs = []
                        for a, b in zip(old_rows, new_rows):
                            if a != b:
                                da, db = dict(a), dict(b)
                                diffs.append({key: [da.get(key), db.get(key)] for key in set(da) | set(db)
                                              if da.get(key) != db.get(key) and key != "path"})
                            if len(diffs) >= 3:
                                break
                        reason["diffs"] = diffs
                _REBUILD_REASONS.append(reason)
            return result
        explained._perf_pages_wrapped = True
        StudioHubMixin._rebuild_project_library = explained
    except Exception:
        pass
    try:
        from .model_registry import scan_model_registry  # noqa: F401
        from . import model_registry
        wrap(model_registry, "_scan_model_registry", "registry_scan")
    except Exception:
        pass


def start(window, out: Path):
    import psutil
    from PySide6.QtCore import QEvent, QObject, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QWidget

    process = psutil.Process()
    started = time.perf_counter()
    _instrument()
    cycles = int(os.environ.get("PAGES_CYCLES", "3"))
    warmup_s = float(os.environ.get("PAGES_WARMUP_S", "6"))
    timeout_s = float(os.environ.get("PERF_TIMEOUT_S", "600"))
    update_request, paint, expose = QEvent.Type.UpdateRequest, QEvent.Type.Paint, QEvent.Type.Expose

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {"scenario": "perf-pages", "entries": [], "sidebars": {}, "errors": {},
                           "resources": [], "checks": {}, "cycles": cycles,
                           "window_size": [window.width(), window.height()]}
            try:
                from .build_identity import load_build_identity
                self.result["build"] = load_build_identity().to_dict()
            except Exception as exc:
                self.result["build"] = repr(exc)
            try:
                from . import ui_zoom
                self.result["zoom_percent"] = ui_zoom.zoom_percent()
            except Exception:
                pass
            self.cur = None
            self.gaps: list[tuple[float, float]] = []
            self.last_tick = time.perf_counter()
            self.heartbeat = QTimer(self)
            self.heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
            self.heartbeat.timeout.connect(self._beat)
            self.heartbeat.start(16)
            QApplication.instance().installEventFilter(self)
            self.pending = 0.0
            self.sequence = self.run()
            self.driver = QTimer(self)
            self.driver.setTimerType(Qt.TimerType.PreciseTimer)
            self.driver.timeout.connect(self._tick)
            self.driver.start(5)

        # ------------------------------------------------------------ infra
        def _beat(self):
            now = time.perf_counter()
            gap = (now - self.last_tick) * 1000
            if gap >= 50:
                self.gaps.append((now, gap))
                if len(self.gaps) > 20000:
                    del self.gaps[:10000]
            self.last_tick = now

        def eventFilter(self, obj, event):
            cur = self.cur
            if cur is None:
                return False
            kind = event.type()
            if kind != update_request and kind != paint and kind != expose:
                return False
            try:
                is_window = obj.isWindowType() or (obj.isWidgetType() and obj.isWindow())
            except RuntimeError:
                return False
            if not is_window:
                return False
            ready = False
            if cur.get("content") is None:
                try:
                    ready = bool(cur["content_ready"]())
                except Exception:
                    ready = False

            def painted(ready=ready, cur=cur):
                end = time.perf_counter()
                if cur.get("first_paint") is None:
                    cur["first_paint"] = end
                if ready and cur.get("content") is None:
                    cur["content"] = end
            QTimer.singleShot(0, painted)
            return False

        def _tick(self):
            try:
                if time.perf_counter() - started > timeout_s:
                    raise TimeoutError("perf pages audit timeout")
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
            self.result["summary"] = self.summary()
            (out / "perf.json").write_text(json.dumps(self.result, ensure_ascii=False, indent=2), "utf8")

        def summary(self):
            rows = {}
            for entry in self.result["entries"]:
                key = f"{entry['label']}:{'first' if entry['first'] else 'again'}"
                row = rows.setdefault(key, {name: [] for name in (
                    "handler_ms", "feedback_ms", "content_ms", "interactive_ms", "background_ms",
                    "max_stall_ms")})
                for name in row:
                    row[name].append(entry.get(name))
            return {key: {name: _dist(values) for name, values in row.items()} for key, row in rows.items()}

        def finish(self):
            self.driver.stop()
            self.heartbeat.stop()
            QApplication.instance().removeEventFilter(self)
            self.result["finished"] = True
            self.save()
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QDialog) and widget.isVisible():
                    widget.reject()
            window.close()
            self.result["gui_shutdown"] = True
            self.save()
            QApplication.quit()

        def snapshot(self, label):
            try:
                cpu = process.cpu_times()
                memory = process.memory_info()
                row = {"label": label, "t": round(time.perf_counter() - started, 2),
                       "rss_mb": round(memory.rss / 1e6, 1), "private_mb": round(memory.private / 1e6, 1),
                       "threads": process.num_threads(), "handles": process.num_handles(),
                       "cpu_s": round(cpu.user + cpu.system, 3), **_gui_objects()}
            except Exception as exc:
                row = {"label": label, "error": repr(exc)}
            self.result["resources"].append(row)
            return row

        def idle(self, quiet_s=1.0, limit_s=20.0):
            """Wait until no heartbeat stall happened for ``quiet_s``."""
            begin = time.perf_counter()

            def quiet():
                now = time.perf_counter()
                last = self.gaps[-1][0] if self.gaps else 0.0
                return now - max(last, begin) >= quiet_s or now - begin > limit_s
            yield quiet

        # ---------------------------------------------------------- pages
        def page(self, name):
            return window.built_page(name) if hasattr(window, "built_page") else None

        def current(self):
            return window.pages.currentWidget()

        def nav_button(self, page, key):
            from .ui_navigation import WorkspaceNavigation
            nav = page.findChild(WorkspaceNavigation)
            return nav.buttons[key]

        # content / background predicates (work for the old and new pages)
        def workshop_content(self):
            page = self.page("workshop")
            if page is None or self.current() is not page or not page.isVisible():
                return False
            cards = getattr(page, "_cards", {})
            return bool(cards) and all(getattr(card, "_state_badge_state", None) is not None
                                       for card in cards.values())

        def workshop_background(self):
            page = self.page("workshop")
            busy = getattr(page, "background_busy", None)
            return not (callable(busy) and busy())

        def history_content(self):
            page = self.page("history")
            if page is None or self.current() is not page or not page.isVisible():
                return False
            cards = getattr(page, "_cards", [])
            return bool(cards) and cards[0].isVisible() and bool(cards[0].record.media_name)

        def history_background(self):
            page = self.page("history")
            busy = getattr(page, "background_busy", None)
            return not (callable(busy) and busy())

        def detail_dialog(self):
            from .recognition_history import RecognitionHistoryDetail
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QDialog) and widget.isVisible():
                    detail = widget.findChild(RecognitionHistoryDetail)
                    if detail is not None:
                        return widget, detail
            return None, None

        def detail_content(self):
            _dialog, detail = self.detail_dialog()
            return (detail is not None and detail.isVisible() and hasattr(detail, "stage_table")
                    and bool(getattr(detail, "summary_ready", True)))

        def terms_content(self):
            page = getattr(window, "term_library_page", None)
            return (page is not None and self.current() is page and page.isVisible()
                    and page.library is not None and page.library.isVisible())

        def library_content(self):
            page = self.page("studio")
            if page is None or self.current() is not page or page.project is not None:
                return False
            if not page.studio_empty.isVisible():
                return False
            mode = getattr(page, "_project_library_view_mode", "card")
            widgets = getattr(page, "_hub_row_widgets" if mode == "list" else "_hub_card_widgets", None) or []
            return bool(widgets) and widgets[0].isVisible()

        def library_background(self):
            page = self.page("studio")
            if page is None:
                return True
            timers = [getattr(page, "_library_build_timer", None), getattr(page, "_hub_relayout_timer", None),
                      *(getattr(page, "_library_build_timers", None) or {}).values()]
            scan_timer = getattr(page, "_hub_scan_timer", None)
            queue = getattr(page, "_library_cover_queue", None)
            return (not getattr(page, "_hub_scan_pending", False)
                    and not getattr(page, "_hub_scan_again", False)
                    and not any(timer is not None and timer.isActive() for timer in timers)
                    and not (scan_timer is not None and scan_timer.isActive())
                    and not (queue is not None and queue.qsize())
                    and not getattr(page, "_library_cover_queued", set()))

        # ---------------------------------------------------------- measure
        def measure(self, label, click, content_ready, background_done=None, *, deferred=False,
                    timeout=40.0, extra=None):
            first = label not in self._seen
            self._seen.add(label)
            before = self.snapshot(f"{label}:before")
            studio = self.page("studio")
            entry = {"label": label, "first": first, "cycle": self._cycle,
                     "pages_built": {name: self.page(name) is not None
                                     for name in ("workshop", "history", "studio")},
                     "library_generation_before": getattr(studio, "_library_build_generation", None)}
            cur = {"content_ready": content_ready}
            self.cur = cur
            gaps_before = len(self.gaps)
            costs_before = {key: list(value) for key, value in _COSTS.items()}
            t0 = time.perf_counter()
            cur["t0"] = t0
            if deferred:
                # A modal dialog runs its own loop inside the click handler;
                # click from a timer so this driver keeps ticking inside it.
                QTimer.singleShot(0, lambda: (cur.__setitem__("t0", time.perf_counter()), click(),
                                              cur.__setitem__("returned", time.perf_counter())))
                yield lambda: "returned" in cur or self.detail_dialog()[0] is not None or \
                    time.perf_counter() - t0 > timeout
                t0 = cur["t0"]
            else:
                click()
                cur["returned"] = time.perf_counter()
            if "returned" in cur:
                entry["handler_ms"] = round((cur["returned"] - t0) * 1000, 1)
            deadline = t0 + timeout
            yield lambda: cur.get("content") is not None or time.perf_counter() > deadline
            if cur.get("content") is None and content_ready():
                # Content was already up when no new frame was needed.
                cur["content"] = time.perf_counter()
            if cur.get("content") is None:
                self.result["errors"][f"{label}:{self._cycle}"] = "content not ready before timeout"
            # Event-loop responsiveness after content.
            interactive = None
            for _attempt in range(400):
                fired = []
                posted = time.perf_counter()
                QTimer.singleShot(0, lambda fired=fired: fired.append(time.perf_counter()))
                yield lambda fired=fired: bool(fired) or time.perf_counter() > deadline
                if not fired:
                    break
                if fired[0] - posted < 0.05:
                    interactive = fired[0]
                    break
            background = None
            if background_done is not None:
                yield lambda: background_done() or time.perf_counter() > deadline
                if background_done():
                    background = time.perf_counter()
            else:
                background = interactive
            end = time.perf_counter()
            self.cur = None
            stalls = [gap for when, gap in self.gaps[gaps_before:] if t0 <= when <= end + 0.001]
            ms = lambda value: None if value is None else round((value - t0) * 1000, 1)
            entry.update(feedback_ms=ms(cur.get("first_paint")), content_ms=ms(cur.get("content")),
                         interactive_ms=ms(interactive), background_ms=ms(background),
                         max_stall_ms=round(max(stalls), 1) if stalls else 0.0,
                         stalls_over_100ms=sum(gap >= 100 for gap in stalls),
                         blocked_ms=round(sum(gap - 16 for gap in stalls), 1))
            entry["library_rebuild_reasons"] = [row for row in _REBUILD_REASONS if row["t"] >= t0]
            entry["costs"] = {key: [value[0] - costs_before.get(key, [0, 0.0])[0],
                                    round(value[1] - costs_before.get(key, [0, 0.0])[1], 1)]
                              for key, value in _COSTS.items()
                              if value[0] != costs_before.get(key, [0, 0.0])[0]}
            studio = self.page("studio")
            entry["library_generation_after"] = getattr(studio, "_library_build_generation", None)
            if extra is not None:
                try:
                    entry.update(extra())
                except Exception as exc:
                    entry["extra_error"] = repr(exc)
            after = self.snapshot(f"{label}:after")
            entry["resources_delta"] = {key: (after.get(key, 0) or 0) - (before.get(key, 0) or 0)
                                        for key in ("rss_mb", "handles", "gdi", "user", "threads")}
            self.result["entries"].append(entry)
            print("PERF_PAGE", label, "first" if first else "again", entry.get("content_ms"),
                  entry.get("interactive_ms"), entry.get("background_ms"), flush=True)
            self.save()

        # ---------------------------------------------------------- flows
        def go_home(self):
            current = self.current()
            if current is getattr(window, "settings_scroll", None):
                return
            studio = self.page("studio")
            if studio is not None and current is studio:
                button = getattr(studio, "studio_back_button", None)
                if button is not None and button.isVisible() and button.isEnabled():
                    button.click()
                else:
                    window._return_to_settings()
            else:
                try:
                    self.nav_button(current, "recognition").click()
                except Exception:
                    window._return_to_settings()

        def history_extra(self):
            page = self.page("history")
            from PySide6.QtWidgets import QWidget as _W
            return {"history_records": len(getattr(page, "records", []) or []),
                    "history_widgets": len(page.findChildren(_W)),
                    "history_errors": len(getattr(page, "_errors", []) or [])}

        def workshop_extra(self):
            page = self.page("workshop")
            from PySide6.QtWidgets import QWidget as _W
            return {"workshop_widgets": len(page.findChildren(_W)),
                    "workshop_refreshes": getattr(page, "_refresh_count", None)}

        def library_extra(self):
            page = self.page("studio")
            return {"library_records": len(getattr(page, "_hub_display_records", []) or []),
                    "library_cards": len(getattr(page, "_hub_card_widgets", []) or []),
                    "library_rows": len(getattr(page, "_hub_row_widgets", []) or []),
                    "library_rebuilds": (getattr(page, "_library_build_generation", 0) or 0)}

        def largest_record(self):
            page = self.page("history")

            def size(record):
                try:
                    return record.path.stat().st_size
                except OSError:
                    return 0
            records = list(getattr(page, "records", []) or [])
            return max(records, key=size) if records else None

        def detail_button(self, large=False):
            page = self.page("history")
            cards = [card for card in (getattr(page, "_cards", []) or []) if card.isVisible()]
            if not cards:
                return None
            card = cards[0]
            if large:
                target = self.largest_record()
                card = next((item for item in cards if target is not None and item.record.path == target.path), None)
                if card is None:
                    return None
            from PySide6.QtWidgets import QPushButton
            for button in card.findChildren(QPushButton):
                if button.objectName() == "historyDetails":
                    return button
            return None

        def open_detail(self, label, large=False):
            page = self.page("history")
            searched = False
            if large and self.detail_button(large) is None and self.largest_record() is not None:
                # Like a user: type the media name to find that report's card.
                page.search.setText(self.largest_record().media_name)
                searched = True
                yield from self.idle(0.5)
            button = self.detail_button(large)
            if button is None:
                self.result["errors"][f"{label}:{self._cycle}"] = "no detail button"
                return
            scroll = None
            from PySide6.QtWidgets import QScrollArea
            area = page.findChild(QScrollArea)
            if area is not None:
                scroll = area.verticalScrollBar().value()
                area.ensureWidgetVisible(button)
                yield 0.3
                scroll_before = area.verticalScrollBar().value()
            query = page.search.text() if hasattr(page, "search") else ""
            yield from self.measure(label, button.click, self.detail_content, None, deferred=True)
            dialog, detail = self.detail_dialog()
            info = {}
            if detail is not None:
                # Never touch a lazy property here: only report what exists.
                raw = vars(detail).get("raw_view")
                info = {"raw_json_built": raw is not None and raw.document().blockCount() > 1}
            yield 0.3
            if dialog is not None:
                dialog.accept()
            yield lambda: self.detail_dialog()[0] is None
            yield 0.2
            if area is not None:
                info["scroll_kept"] = area.verticalScrollBar().value() == scroll_before
            info["search_kept"] = (page.search.text() if hasattr(page, "search") else "") == query
            info["searched_for_card"] = searched
            self.result["entries"][-1].update(info)
            if searched:
                page.search.clear()
            if area is not None and scroll is not None:
                area.verticalScrollBar().setValue(scroll)
            self.save()

        def grab_sidebar(self, name, page):
            if name in self.result["sidebars"]:
                return
            try:
                path = out / f"sidebar-{name}.png"
                window.grab().save(str(path))
                metrics = sidebar_metrics(window, page)
                metrics["png"] = str(path)
                self.result["sidebars"][name] = metrics
            except Exception:
                self.result["errors"][f"sidebar-{name}"] = traceback.format_exc()

        def run(self):
            self._seen: set[str] = set()
            self._cycle = 0
            yield lambda: time.perf_counter() - started >= warmup_s
            yield from self.idle(1.5)
            self.snapshot("ready")
            for cycle in range(cycles + 1):
                self._cycle = cycle
                self.go_home()
                yield from self.idle(1.0)
                yield from self.measure("workshop", window.model_workshop_button.click,
                                        self.workshop_content, self.workshop_background,
                                        extra=self.workshop_extra)
                yield from self.idle(1.0)
                if cycle == 1:
                    self.grab_sidebar("workshop", self.page("workshop"))
                yield from self.measure("history", self.nav_button(self.page("workshop"), "history").click,
                                        self.history_content, self.history_background,
                                        extra=self.history_extra)
                yield from self.idle(1.0)
                if cycle == 1:
                    self.grab_sidebar("history", self.page("history"))
                yield from self.open_detail("detail")
                yield from self.idle(1.0)
                yield from self.open_detail("detail-largest", large=True)
                yield from self.idle(1.0)
                yield from self.measure("terms", self.nav_button(self.page("history"), "terms").click,
                                        self.terms_content, None)
                yield from self.idle(1.0)
                if cycle == 1:
                    self.grab_sidebar("terms", window.term_library_page)
                yield from self.measure("history-from-terms",
                                        self.nav_button(window.term_library_page, "history").click,
                                        self.history_content, self.history_background,
                                        extra=self.history_extra)
                yield from self.idle(1.0)
                self.go_home()
                yield from self.idle(1.0)
                yield from self.measure("library", window.subtitle_studio_button.click,
                                        self.library_content, self.library_background,
                                        extra=self.library_extra)
                yield from self.idle(1.0)
                self.go_home()
                yield from self.idle(1.0)
            self.check_sidebars()

        def check_sidebars(self):
            bars = self.result["sidebars"]
            if len(bars) < 3:
                return
            keys = ("sidebar_x", "sidebar_w", "nav_x", "nav_w", "content_left")
            first = next(iter(bars.values()))
            self.result["checks"]["sidebar_geometry_equal"] = all(
                all(bar.get(key) == first.get(key) for key in keys) for bar in bars.values())
            shape = lambda bar: [(b["w"], b["h"], b["font_px"], b["font_pt"], tuple(b["icon"]))
                                 for b in bar.get("buttons", [])]
            self.result["checks"]["nav_items_equal"] = all(shape(bar) == shape(first) for bar in bars.values())

    window._perf_pages_audit = Audit()
