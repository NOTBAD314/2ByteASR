"""Opt-in real-window check of link downloads A+B (2026-10-26). Never loaded in normal use.

User-like path in the real app: Ctrl+V on plain text does nothing; Ctrl+V on a
YouTube link opens the quick card, which parses the real video; Enter
downloads; the toolbar capsule and its popover show the task; the import lands
in the open project and a notice offers 定位到片段. Then the full window: the
home page, 粘贴 + parse, the result card, an audio-only download paused and
continued, and the 队列 / 工具 / 设置 pages. Every visible control is checked
for being cut off at the right or having its words clipped.
"""
from __future__ import annotations
import json
import os
import time
import traceback

LINK = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def install_guards():
    from .link_download_audit import install_guards as guards
    guards()


def clipped(root, area=None):
    """Visible widgets whose right edge leaves ``area`` or whose words do not fit."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QAbstractButton, QLabel, QScrollBar, QWidget
    from ..design.elided_label import ElidedLabel
    area = area or root.rect()
    problems = []
    for widget in root.findChildren(QWidget):
        if not widget.isVisible() or widget.width() <= 0 or isinstance(widget, QScrollBar):
            continue
        rect = QRect(widget.mapTo(root, QPoint(0, 0)), widget.size())
        name = f"{type(widget).__name__}#{widget.objectName()}:{getattr(widget, 'text', lambda: '')()}"[:120]
        if rect.right() > area.right() + 1 or rect.left() < area.left() - 1:
            problems.append(("outside", name, rect.getRect()))
        if isinstance(widget, QAbstractButton) and widget.text() and widget.sizeHint().width() > widget.width() + 2:
            problems.append(("words", name, widget.sizeHint().width(), widget.width()))
        if (isinstance(widget, QLabel) and not isinstance(widget, ElidedLabel) and not widget.wordWrap()
                and widget.text() and widget.pixmap().isNull() and widget.sizeHint().width() > widget.width() + 2):
            problems.append(("words", name, widget.sizeHint().width(), widget.width()))
    return problems


def toolbar_overlaps(page):
    """Visible toolbar commands drawn on top of each other (a squeezed bar)."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QAbstractButton
    bar = getattr(page, "studio_toolbar", None)
    if bar is None:
        return []
    rects = []
    for widget in bar.findChildren(QAbstractButton):
        if widget.isVisible() and widget.width() > 0:
            rects.append((QRect(widget.mapTo(bar, QPoint(0, 0)), widget.size()), widget.objectName() or widget.text()))
    rects.sort(key=lambda item: item[0].left())
    return [(a[1], b[1]) for a, b in zip(rects, rects[1:]) if a[0].right() > b[0].left() + 1]


def window_on_top(widget):
    """The top-level window Windows reports at the centre of ``widget``'s frame.

    Returns (is ``widget`` itself, details). A layered tool window hidden
    under its owner fails here even when Qt calls it visible."""
    import ctypes
    from ctypes import wintypes
    from PySide6.QtCore import QPoint
    frame = getattr(widget, "frame", widget)
    centre = frame.mapToGlobal(frame.rect().center())
    screen = widget.screen()
    origin = screen.geometry().topLeft()
    ratio = screen.devicePixelRatio()
    native = QPoint(round(origin.x() + (centre.x() - origin.x()) * ratio),
                    round(origin.y() + (centre.y() - origin.y()) * ratio))
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    hit = user32.WindowFromPoint(wintypes.POINT(native.x(), native.y()))
    root = user32.GetAncestor(hit, 2) if hit else None
    own = int(widget.winId())
    return int(root or 0) == own, dict(point=(native.x(), native.y()), hit=int(hit or 0), root=int(root or 0), card=own)


def popup_facts(combo, popup, view):
    """Where a dropdown list opened and how it is built (10-26 user report)."""
    from PySide6.QtCore import QPoint, Qt
    from ..app.ui_zoom import px
    from ..design.combo_popup import EDGE, GAP, MAX_ROWS, MIN_ROWS, ROW
    if popup is None or view is None or not popup.isVisible():
        return dict(ok=False, visible=False)
    bottom = combo.mapToGlobal(QPoint(0, combo.height() - 1)).y() + 1
    top = combo.mapToGlobal(QPoint(0, 0)).y()
    geometry = popup.geometry()
    screen = combo.screen().availableGeometry()
    row = view.sizeHintForRow(0)
    rows = round((view.viewport().height()) / max(1, row))
    below = geometry.top() >= bottom
    facts = dict(below=below, above=geometry.bottom() < top, geometry=geometry.getRect(), box_bottom=bottom,
                 screen=screen.getRect(), row=row, expected_row=px(ROW), rows=rows,
                 translucent=popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
                 no_shadow=bool(popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint),
                 on_screen=screen.contains(geometry))
    chrome = geometry.height() - view.viewport().height()
    room = screen.bottom() + 1 - px(EDGE) - (bottom + px(GAP))
    facts.update(room_below=room, least=chrome + MIN_ROWS * row)
    facts["ok"] = bool((below or room < chrome + MIN_ROWS * row) and facts["on_screen"] and rows <= MAX_ROWS
                       and row == px(ROW) and facts["translucent"] and facts["no_shadow"])
    return facts


def finished(task):
    """Final for an automatic import: pending_import alone is the moment before it runs."""
    return task["state"] in {"imported", "failed", "partial"} or (
        task["state"] == "pending_import" and not task.get("auto_import"))


def start(window, out):
    from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .blank_project_audit import _capture
    from ..projects.subtitle_consistency import validate_project

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = dict(passed=False, checks=[], screenshots=[], network="real YouTube, no cookies",
                               theme=os.environ.get("TWOBYTEASR_LINK_UI_THEME", ""),
                               zoom=os.environ.get("TWOBYTEASR_LINK_UI_ZOOM", ""))
            from ..diagnostics.build_identity import load_build_identity
            self.result["identity"] = load_build_identity().to_dict()
            self.steps = self.run()
            self.waiting = 0
            self.deadline = time.monotonic() + 240
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(30)

        def check(self, name, value, detail=None):
            self.result["checks"].append(dict(name=name, passed=bool(value), detail=detail))
            (out / "link-ui-progress.json").write_text(json.dumps(self.result, ensure_ascii=False, indent=2), "utf-8")
            if not value:
                raise AssertionError(name + ": " + str(detail))

        def shot(self, name, surface=None):
            _capture(surface or window, out / (name + ".png"))
            self.result["screenshots"].append(name + ".png")

        def composite(self, name, *floating, base=None):
            """A window (the main one by default) with floating tool windows drawn on top at their places."""
            from PySide6.QtGui import QPainter, QPixmap
            path = out / (name + ".png")
            owner = base or window
            _capture(owner, path)
            base = QPixmap(str(path))
            ratio = base.width() / max(1, owner.frameGeometry().width())
            painter = QPainter(base)
            origin = owner.frameGeometry().topLeft()
            for widget in floating:
                if widget is None or not widget.isVisible():
                    continue
                grab = widget.grab()
                at = widget.geometry().topLeft() - origin
                painter.drawPixmap(QRect(int(at.x() * ratio), int(at.y() * ratio),
                                         int(widget.width() * ratio), int(widget.height() * ratio)), grab)
            painter.end()
            base.save(str(path))
            self.result["screenshots"].append(name + ".png")

        def tick(self):
            try:
                now = time.monotonic()
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QMessageBox):
                    message = modal.text()
                    self.shot("unexpected-modal", modal)
                    modal.reject()
                    raise RuntimeError(message)
                if callable(self.waiting):
                    if not self.waiting():
                        if now > self.deadline:
                            raise TimeoutError("Stage timed out")
                        return
                elif now < self.waiting:
                    return
                value = next(self.steps)
                self.waiting = value if callable(value) else now + float(value)
                self.deadline = now + 240
            except StopIteration:
                self.result["passed"] = True
                self.finish()
            except Exception:
                self.result["error"] = traceback.format_exc()
                controller = getattr(window, "_link_download_controller", None)
                if controller:
                    self.result["tasks"] = controller.queue.snapshots()
                try:
                    self.composite("failure", *(getattr(controller, k, None) for k in ("card", "popover", "toast"))
                                   if controller else ())
                    if controller and controller.dialog and controller.dialog.isVisible():
                        self.shot("failure-window", controller.dialog)
                except Exception:
                    pass
                self.finish()

        def ctrl_v(self, page):
            QTest.keyClick(page.timeline, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)

        def run(self):
            page = None
            yield 1.0
            window.open_studio_project(os.environ["TWOBYTEASR_STARTUP_PROJECT"])

            def studio_ready():
                nonlocal page
                page = window.built_page("studio") if callable(getattr(window, "built_page", None)) else None
                gate = getattr(page, "_readiness", None)
                return page is not None and page.isVisible() and page.project is not None and (gate is None or gate.ready)
            yield studio_ready
            yield .8
            clipboard = QApplication.clipboard()
            # --- B: Ctrl+V -----------------------------------------------------------
            clipboard.setText("普通文字，不是链接")
            self.ctrl_v(page)
            yield .4
            controller = getattr(window, "_link_download_controller", None)
            self.check("plain-text Ctrl+V opens nothing", controller is None or controller.card is None
                       or not controller.card.isVisible())
            # --- B in a maximized window (10-26: the card never showed there) -----------
            window.showMaximized()
            yield 1.2
            clipboard.setText(LINK)
            self.ctrl_v(page)
            yield lambda: getattr(window, "_link_download_controller", None) is not None and window._link_download_controller.card is not None
            yield .8
            card = window._link_download_controller.card
            on_top, where = window_on_top(card)
            frame = window.frameGeometry()
            corner = card.frame.mapToGlobal(QPoint(card.frame.width() - 1, 0))
            inside = frame.contains(card.frame.mapToGlobal(QPoint(0, 0))) and frame.contains(corner)
            self.check("maximized: Ctrl+V card shows above the window, inside it at the top right",
                       card.isVisible() and on_top and inside and frame.right() - corner.x() < 80,
                       dict(where, maximized=window.isMaximized(), card=card.geometry().getRect(),
                            window=frame.getRect()))
            self.composite("00-card-maximized", card)
            card.close()
            window.showNormal()
            yield 1.2
            if os.environ.get("TWOBYTEASR_LINK_UI_ONLY_MAXIMIZED") == "1":
                return
            clipboard.setText("看这个 " + LINK + "&t=3s")
            started = time.monotonic()
            self.ctrl_v(page)
            yield lambda: getattr(window, "_link_download_controller", None) is not None and window._link_download_controller.card is not None
            controller = window._link_download_controller
            card = controller.card
            self.check("link Ctrl+V shows the card and parses at once", card.isVisible() and card.state == "parsing",
                       card.state)
            frame = window.frameGeometry()
            self.check("card sits inside the window at its top right",
                       frame.contains(card.frame.mapToGlobal(QPoint(0, 0)))
                       and card.frame.mapToGlobal(QPoint(card.frame.width() - 1, 0)).x() < frame.right()
                       and frame.right() - card.frame.mapToGlobal(QPoint(card.frame.width() - 1, 0)).x() < 80,
                       (frame.getRect(), card.geometry().getRect()))
            self.composite("01-card-parsing", card)
            # 10-26: title and cover come first, the choices follow (timings on the real network).
            yield lambda: card.state in ("ready", "error") or card._previewed
            previewed = card._previewed and card.state == "parsing"
            timings = dict(preview_s=round(time.monotonic() - started, 2) if previewed else None)
            if previewed:
                self.check("card shows the video's title and cover while the choices load",
                           card.media_box.isVisible() and bool(card.title.text()) and not card.body.isVisible(),
                           card.title.text())
                self.composite("01b-card-preview", card)
            yield lambda: card.state in ("ready", "error")
            timings["ready_s"] = round(time.monotonic() - started, 2)
            self.result["timings"] = timings
            self.check("card parsed the real video", card.state == "ready", dict(card.status.text() and
                       dict(status=card.status.text()) or {}, **timings))
            yield .4
            self.check("card controls fit", not clipped(card.frame), clipped(card.frame))
            selection = card.selection()
            catalog = card.catalog
            formats = {f["format_id"]: f for f in catalog["formats"]}
            manual_en = next(t["track_id"] for t in catalog["tracks"] if t["source"] == "manual" and t["language"] == "en")
            if not selection["track_ids"]:
                # This video has English and German uploads and no language evidence:
                # the card asks, and the user picks English.
                self.check("card asks which subtitle when there is no evidence",
                           card.status.isVisible() and bool(card.status.text()), card.status.text())
                self.composite("02a-card-asks", card)
                QTest.mouseClick(card._chips[manual_en], Qt.MouseButton.LeftButton)
                yield .3
                self.check("prompt goes away after the pick", not card.status.isVisible())
                selection = card.selection()
            yield .3
            need = card.frame.heightForWidth(card.frame.width())
            self.check("card is as tall as its content", abs(card.frame.height() - need) <= 4,
                       (card.frame.height(), need))
            self.check("card defaults: video + original manual subtitles",
                       selection["mode"] == "both" and selection["track_ids"] == [manual_en]
                       and str(formats[selection["video_format"]]["vcodec"]).startswith("avc")
                       and (formats[selection["video_format"]]["height"] or 0) <= 1080, selection)
            self.composite("02-card-ready", card)
            QTest.keyClick(card, Qt.Key.Key_Return)
            tasks = controller.queue.snapshots()
            self.check("Enter queues one task and closes the card", len(tasks) == 1 and not card.isVisible(), tasks)
            key = tasks[0]["task_id"]
            self.check("task targets the open project at the playhead",
                       tasks[0]["target"]["kind"] == "current" and tasks[0]["auto_import"], tasks[0]["target"])
            capsule = page.studio_link_capsule
            yield lambda: capsule.isVisible() or controller.task(key)["state"] not in ("queued", "running")
            self.check("toolbar capsule shows the running download", capsule.isVisible()
                       or controller.task(key)["state"] in ("imported", "pending_import"), capsule.text())
            if capsule.isVisible():
                yield .5
                bar = getattr(page, "studio_toolbar", None)
                self.check("capsule words fit", bool(capsule.text()) and capsule.width() >= capsule.sizeHint().width() - 2,
                           dict(text=capsule.text(), width=capsule.width(), hint=capsule.sizeHint().width(),
                                minimum=capsule.minimumWidth(), maximum=capsule.maximumWidth(),
                                track=capsule.parentWidget().width(),
                                bar_minimum=bar.layout().minimumSize().width() if bar is not None else None,
                                page=page.width(), collapsed=[w.objectName() or getattr(w, "text", lambda: "")()
                                                             for w in getattr(page, "_studio_toolbar_collapsed", [])]))
                yield .4
                self.check("toolbar keeps its commands apart with the capsule", not toolbar_overlaps(page),
                           toolbar_overlaps(page))
                QTest.mouseClick(capsule, Qt.MouseButton.LeftButton)
                yield lambda: controller.popover is not None and controller.popover.isVisible()
                yield .4
                self.check("popover lists the task", key in controller.popover._cards)
                self.check("popover controls fit", not clipped(controller.popover.frame), clipped(controller.popover.frame))
                self.composite("03-capsule-popover", controller.popover)
                controller.popover.hide()
            yield lambda: finished(controller.task(key))
            task = controller.task(key)
            self.check("downloaded and imported into the open project", task["state"] == "imported", task)
            result = task["import_result"]
            self.check("captions imported", result.get("cue_count", 0) > 0 and validate_project(page.project).ok, result)
            yield lambda: controller.toast is not None and controller.toast.isVisible()
            yield .4
            toast = controller.toast
            self.check("import notice fits", not clipped(toast.frame), clipped(toast.frame))
            self.composite("04-import-notice", toast)
            clip = next(c for t in page.project.video_tracks for c in t.clips if c.id == result["clip_id"])
            page._seek(max(0, clip.timeline_in_ms + 5000) / 1000.0)
            yield .6
            QTest.mouseClick(toast.locate_button, Qt.MouseButton.LeftButton)
            yield lambda: abs(page.timeline.playhead_ms - clip.timeline_in_ms) < 200
            self.check("定位到片段 moves the playhead to the clip", True, page.timeline.playhead_ms)
            capsule_after = capsule.isVisible()
            self.check("capsule goes away when nothing runs", not capsule_after, capsule.text())
            toast.hide()
            # --- A: full window ----------------------------------------------------------
            QTest.mouseClick(page.studio_link_download_button, Qt.MouseButton.LeftButton)
            yield lambda: controller.dialog is not None and controller.dialog.isVisible()
            dialog = controller.dialog
            yield .5
            self.check("window opens on the home page with the big link field",
                       dialog.pages.currentIndex() == 0 and dialog.hero_head.isVisible() and dialog.url_field.isVisible())
            self.check("home page fits", not clipped(dialog), clipped(dialog))
            # 10-26 evening: own rounded title bar instead of the Windows one.
            image = dialog.grab().toImage()
            ratio = image.width() / max(1, dialog.width())
            margin = dialog.chrome.margin()
            corner = image.pixelColor(int((margin + 1) * ratio), int((margin + 1) * ratio)).alpha()
            inside = image.pixelColor(int((margin + 40) * ratio), int((margin + 24) * ratio)).alpha()
            self.check("link window: own title bar, rounded transparent corners",
                       bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
                       and dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                       and margin > 0 and corner < 80 and inside == 255,
                       dict(margin=margin, corner_alpha=corner, inside_alpha=inside))
            self.shot("05-window-home", dialog)
            QTest.mouseClick(dialog.window_buttons.maximize_button, Qt.MouseButton.LeftButton)
            yield lambda: dialog.chrome.maximized
            yield .4
            work = dialog.screen().availableGeometry()
            self.check("link window: maximize button fills the screen without corners",
                       dialog.chrome.maximized and dialog.chrome.margin() == 0 and not dialog.chrome.mask.isVisible()
                       and dialog.geometry() == work,
                       (dialog.geometry().getRect(), work.getRect()))
            self.shot("05b-window-maximized", dialog)
            QTest.mouseClick(dialog.window_buttons.maximize_button, Qt.MouseButton.LeftButton)
            yield lambda: not dialog.chrome.maximized
            yield .4
            self.check("link window: restore brings the rounded window back",
                       not dialog.chrome.maximized and dialog.chrome.margin() > 0 and dialog.chrome.mask.isVisible()
                       and dialog.width() < work.width(),
                       dialog.geometry().getRect())
            buttons = [b for b in dialog.hero_tools.findChildren(type(dialog.parse_button)) if b.text()]
            paste = next(b for b in buttons if b.text() in ("粘贴", "Paste", "貼り付け"))
            QTest.mouseClick(paste, Qt.MouseButton.LeftButton)
            self.check("粘贴 reads the clipboard link", dialog.url.text().endswith("jNQXAC9IVRw"), dialog.url.text())
            yield lambda: dialog.catalog is not None or dialog.parse_button.isEnabled()
            self.check("window parsed the real video", dialog.catalog is not None, dialog.message.text())
            yield .6
            viewport = dialog.pages.widget(0).viewport()
            area = QRect(viewport.mapTo(dialog, QPoint(0, 0)), viewport.size())
            problems = [p for p in clipped(dialog) if p[0] == "words"] + [
                p for p in clipped(dialog.result_card) if p[0] == "outside"]
            card_right = dialog.result_card.mapTo(dialog, QPoint(dialog.result_card.width(), 0)).x()
            self.check("result card fits the window", not problems and card_right <= area.right() + 1,
                       (problems, card_right, area.getRect()))
            self.check("window height fits its content (nothing scrolls, no empty band)",
                       dialog.pages.widget(0).verticalScrollBar().maximum() == 0
                       and dialog.height() <= dialog.pages.widget(0).widget().sizeHint().height() + 200,
                       (dialog.height(), dialog.pages.widget(0).verticalScrollBar().maximum()))
            self.shot("06-window-parsed", dialog)
            # --- dropdowns (10-26): below the box, at most ten rows, rounded, on screen
            for name, combo in (("quality", dialog.video_format), ("audio", dialog.audio_format),
                                ("translation", dialog.translation)):
                combo.showPopup()
                yield .4
                facts = popup_facts(combo, combo.view().window(), combo.view())
                self.check(f"{name} list: below its box, at most 10 rows, on screen, no square frame",
                           facts["ok"], facts)
                self.composite(f"06-{name}-list", combo.view().window(), base=dialog)
                combo.hidePopup()
                yield .2
            dialog.all_tracks_toggle.setChecked(True)
            dialog.details_toggle.setChecked(True)
            yield .5
            self.check("expanded card fits", not [p for p in clipped(dialog) if p[0] == "words"], clipped(dialog))
            self.shot("07-window-expanded", dialog)
            dialog.all_tracks_toggle.setChecked(False)
            dialog.details_toggle.setChecked(False)
            # audio-only, paused and continued
            dialog.mode.setCurrentIndex(dialog.mode.findData("audio"))
            dialog.destination.setCurrentIndex(dialog.destination.findData("current"))
            self.check("audio mode: only the audio track is chosen",
                       not dialog.video_format.isEnabled() and bool(dialog.audio_format.currentData()))
            QTest.mouseClick(dialog.add_button, Qt.MouseButton.LeftButton)
            audio = controller.queue.snapshots()[-1]["task_id"]
            self.check("audio task queued", controller.task(audio)["mode"] == "audio", controller.task(audio))
            yield lambda: controller.task(audio)["state"] != "queued"
            if controller.task(audio)["state"] == "running":
                controller.task_action("pause", audio)
                yield lambda: controller.task(audio)["state"] in ("paused", "imported", "pending_import", "failed")
                self.check("pause stops the download and keeps the task", controller.task(audio)["state"] in ("paused", "imported"),
                           controller.task(audio)["state"])
                if controller.task(audio)["state"] == "paused":
                    dialog.show_page("queue")
                    yield .5
                    self.check("queue page fits", not [p for p in clipped(dialog) if p[0] == "words"], clipped(dialog))
                    self.shot("08-queue-paused", dialog)
                    controller.task_action("resume", audio)
            yield lambda: finished(controller.task(audio))
            task = controller.task(audio)
            self.check("audio-only download imported", task["state"] == "imported", task)
            assets = [a for a in page.project.media_pool if not a.video_metadata.get("has_video", True)]
            self.check("an audio-only asset is in the project", bool(assets), [a.display_name for a in page.project.media_pool])
            dialog.show_page("queue")
            yield .6
            self.check("both tasks are cards on the queue page", {key, audio} <= set(dialog._cards))
            self.shot("09-queue-done", dialog)
            for name in ("tools", "settings"):
                dialog.show_page(name)
                yield .5
                self.check(f"{name} page fits", not clipped(dialog), clipped(dialog))
                self.shot(f"10-{name}", dialog)
            dialog.show_page("home")
            self.check("project consistency", validate_project(page.project).ok)
            # --- home page dropdown: the same rows, shape and direction ---------------
            dialog.hide()
            page.undo_stack.setClean()
            window._return_to_settings()
            yield 1.2
            combo = window.recognition_language
            combo.showPopup()
            yield .6
            popup = getattr(combo, "_popup", None)
            facts = popup_facts(combo, popup, getattr(popup, "listing", None))
            self.check("home list: below its box, same rows as the others, no square frame", facts["ok"], facts)
            self.composite("11-home-list", popup)
            combo.hidePopup()

        def finish(self):
            self.timer.stop()
            from .link_download_audit import _provider_calls
            self.result["provider_calls"] = _provider_calls
            window.result_exit_code = 0 if self.result["passed"] else 1

            def write():
                (out / "link-ui.json").write_text(json.dumps(self.result, ensure_ascii=False, indent=2), "utf-8")
            write()

            def stopped():
                self.result["gui_shutdown"] = True
                write()
            QApplication.instance().aboutToQuit.connect(stopped)
            controller = getattr(window, "_link_download_controller", None)
            if controller:
                controller.shutdown()
                if controller.dialog:
                    controller.dialog.hide()
            page = window.built_page("studio")
            if page and page.project:
                page.undo_stack.setClean()
            window.close()

    window._link_ui_audit = Audit()
