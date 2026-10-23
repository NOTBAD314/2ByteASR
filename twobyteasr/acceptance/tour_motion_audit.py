"""Real-window frame log of the first-run tutorial (2026-10-14, tutorial motion round).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=tour-motion`` (isolated data
folder, offline guards; see scripts/verify_tour_motion_headed.py). It walks
the whole tutorial the way a person does and records what was painted:

* every paint of the tutorial overlay and its bubble: step, bubble geometry,
  fade-in, outline, pointer side - so a bubble that resizes, changes side or
  stops at in-between positions shows up frame by frame;
* for every step with an outline, which window the system puts under a click
  at its centre (``WindowFromPoint``): the main window (the click reaches the
  outlined control) or the tutorial overlay (a step that does the demo thing
  itself, ``TourStep.click``) - and a real press and release sent to that
  window for every step a person clicks to go on;
* what happens right after such a click (page change, outline left behind,
  animation still playing), and a detour: a model card opens the workshop,
  the tutorial steps aside to its chip and comes back with "回到教学";
* whether the workbench video plays while the tutorial points at it, and
  whether the overlay is its own top-level window (never a native child);
* 2026-10-21: a step whose click opens a real window (主力转写 → the MOSS Pro
  sign-up guide, AI → the DeepSeek guide): the tutorial must be gone while the
  window is open and come back when it closes; ``TWOBYTEASR_TOUR_CHOOSE=cloud``
  answers the first-run chooser with the recommended cloud card instead of
  "稍后再说", and 继续学进阶 goes on in the same overlay;
* window pictures during each change of step and after each click (main
  window by PrintWindow so the native video is in them, the overlay window
  laid over it), written as small JPEGs.
* 2026-10-22 (one tutorial): the plan step opens the cloud / local comparison
  by itself (answered with ``TWOBYTEASR_TOUR_CHOOSE``, default cloud); the AI
  step opens AI 设置 and the tutorial points into that window (a click at each
  outline must reach the window, the 申请教程 guide opens and closes, a test
  key is pasted, 测试连接 fails offline, 保存并开启 or 先不开 closes it); the
  home page locks (glossary, web check, translation) are recorded; every show
  and hide of the overlay is logged (no hide while a page opens: the workbench
  flash), and how long each change of step takes.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from pathlib import Path


def _side(tour):
    pointer, hole = tour.pointer, tour.hole
    if pointer is None or hole.isNull():
        return ''
    tip = pointer[0]
    if tip.x() >= hole.right():
        return 'right'
    if tip.x() <= hole.left():
        return 'left'
    if tip.y() >= hole.bottom():
        return 'below'
    return 'above'


def _rect(r):
    return [round(r.x()), round(r.y()), round(r.width()), round(r.height())]


def _print_window_rgba(hwnd: int):
    """PrintWindow (full content) with the alpha channel kept, as a PIL RGBA image."""
    import ctypes
    from ctypes import wintypes as W
    from PIL import Image
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetWindowDC.restype = W.HDC
    gdi.CreateCompatibleDC.restype = W.HDC
    gdi.CreateCompatibleBitmap.restype = W.HBITMAP
    gdi.SelectObject.restype = W.HANDLE
    rect = W.RECT()
    user.GetWindowRect(W.HWND(hwnd), ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    source = user.GetWindowDC(W.HWND(hwnd))
    memory = gdi.CreateCompatibleDC(W.HDC(source))
    bitmap = gdi.CreateCompatibleBitmap(W.HDC(source), width, height)
    previous = gdi.SelectObject(W.HDC(memory), W.HANDLE(bitmap))
    try:
        if not user.PrintWindow(W.HWND(hwnd), W.HDC(memory), 2):
            raise RuntimeError('PrintWindow failed')

        class Header(ctypes.Structure):
            _fields_ = [('biSize', W.DWORD), ('biWidth', W.LONG), ('biHeight', W.LONG), ('biPlanes', W.WORD),
                        ('biBitCount', W.WORD), ('biCompression', W.DWORD), ('biSizeImage', W.DWORD),
                        ('biXPelsPerMeter', W.LONG), ('biYPelsPerMeter', W.LONG), ('biClrUsed', W.DWORD),
                        ('biClrImportant', W.DWORD)]
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi.GetDIBits(W.HDC(memory), W.HBITMAP(bitmap), 0, height, buffer, ctypes.byref(header), 0)
        return Image.frombuffer('RGBA', (width, height), buffer, 'raw', 'BGRA', 0, 1), (rect.left, rect.top)
    finally:
        gdi.SelectObject(W.HDC(memory), W.HANDLE(previous))
        gdi.DeleteObject(W.HANDLE(bitmap))
        gdi.DeleteDC(W.HDC(memory))
        user.ReleaseDC(W.HWND(hwnd), W.HDC(source))


def start(window, output: Path):
    from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import QEnterEvent, QMovie
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QWidget
    from ..diagnostics.build_identity import load_build_identity
    from .onboarding_settings_audit import _offline_dns
    _offline_dns()
    folder = output / 'tour'
    frames = folder / 'frames'
    frames.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = dict(checks=[], identity=load_build_identity().to_dict(), passed=False, steps=[], clicks=[], detour={},
                  windows=[])
    paints: list = []
    presses: list = []
    state = dict(tour=None, capture_until=0.0, label='', wait=None, until=0.0, deadline=0.0, ticking=False,
                 overlay_hwnd=0, offset=0, part='', part_len=0)   # offset: steps of the parts already walked
    clicking = os.environ.get('TWOBYTEASR_TOUR_CLICK', 'real')   # real | helper
    spoken = os.environ.get('TWOBYTEASR_TOUR_LANGUAGE', '')      # '' | zh | ja | en: picked at the language step
    choose = os.environ.get('TWOBYTEASR_TOUR_CHOOSE', '')        # '' (稍后再说) | cloud: the first-run answer
    tooltips = os.environ.get('TWOBYTEASR_TOUR_TOOLTIPS') == '1'  # sample one chooser and one tutorial tooltip

    def now():
        return round((time.monotonic() - started) * 1000)

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    # ---------------------------------------------------------------- paint log
    class PaintLog(QObject):
        def eventFilter(self, watched, event):  # noqa: N802 - Qt override
            if event.type() == QEvent.Type.Paint:
                tour = state['tour']
                if tour is not None:
                    try:
                        page = window.pages.currentWidget()
                        # 进阶 in the same overlay counts on from 基础 even before the walk notices the switch.
                        offset = state['offset'] + (state['part_len'] if state['part']
                                                    and getattr(tour, 'part', '') != state['part'] else 0)
                        paints.append(dict(t=now(), w='tour' if watched is tour else 'bubble', i=offset + tour.index,
                                           v=tour.bubble.isVisible(), b=_rect(tour.bubble.geometry()),
                                           r=round(float(getattr(tour, 'reveal', 1.0)), 2),
                                           m=str(getattr(tour, 'mode', '')),
                                           h=_rect(tour.hole), p=_side(tour), c=bool(getattr(tour, '_compact', False)),
                                           a=tour.anim.name if tour.anim.isVisible() else '',
                                           pg=page.objectName() if page is not None else ''))
                    except RuntimeError:
                        pass
            return False

    paint_log = PaintLog(window)
    # 2026-10-22: how long the tutorial's own handlers take (is a dropped frame ours or the page's?).
    slow: list = []
    from ..app.home_tour import GuidedTour as _Tour

    def timed(name, method):
        def wrapper(self, *args, **kwargs):
            begun = time.perf_counter()
            try:
                return method(self, *args, **kwargs)
            finally:
                spent = (time.perf_counter() - begun) * 1000
                if spent >= 8:
                    slow.append(dict(t=now(), call=name, ms=round(spent, 1), i=getattr(self, 'index', -1),
                                     mode=str(getattr(self, 'mode', ''))))
        return wrapper
    for _name in ('_poll', '_follow_target', '_glide_step', '_glide_done', '_arrive', '_show_bubble', '_reveal_step',
                  '_reveal_done', '_pulse', 'paintEvent', '_place', '_bubble_picture'):
        setattr(_Tour, _name, timed(_name, getattr(_Tour, _name)))
    shows: list = []

    class ShowLog(QObject):
        """Every show and hide of the overlay window, with the tutorial's mode at that moment."""
        def eventFilter(self, watched, event):  # noqa: N802 - Qt override
            if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
                shows.append(dict(t=now(), shown=event.type() == QEvent.Type.Show,
                                  mode=str(getattr(watched, 'mode', '')), i=getattr(watched, 'index', -1)))
            return False

    show_log = ShowLog(window)

    class PressLog(QObject):
        def eventFilter(self, watched, event):  # noqa: N802 - Qt override
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick) \
                    and isinstance(watched, QWidget):
                presses.append(dict(t=now(), cls=type(watched).__name__, name=watched.objectName()))
            return False

    press_log = PressLog(window)
    QApplication.instance().installEventFilter(press_log)

    # ---------------------------------------------------------------- pictures
    hwnd = int(window.winId())

    def capture_loop():
        while not state.get('closing'):
            if time.monotonic() < state['capture_until']:
                try:
                    # The main window only (PrintWindow keeps no alpha for the layered overlay window;
                    # the overlay's motion is in the paint log, and stills() lays it over the page).
                    image, _origin = _print_window_rgba(hwnd)
                    image = image.convert('RGB').resize((image.width // 2, image.height // 2))
                    image.save(frames / f'{now():07d}-{state["label"]}.jpg', quality=72)
                except Exception:  # noqa: BLE001 - a missed frame is just missing
                    time.sleep(0.02)
                time.sleep(0.03)
            else:
                time.sleep(0.02)

    def still(name):
        """The page (PrintWindow, native video included) with the overlay window laid over it (Qt grab)."""
        import ctypes
        from ctypes import wintypes as W
        from PIL import Image
        from PySide6.QtGui import QImage
        try:
            image, origin = _print_window_rgba(hwnd)
            image = image.convert('RGB')
            tour = state['tour']
            host = tour._step_host() if tour is not None and hasattr(tour, '_step_host') else None
            if host is not None:   # 2026-10-22: AI 设置 is its own window, between the page and the overlay
                dialog, corner = _print_window_rgba(int(host.winId()))
                image.paste(dialog.convert('RGB'), (corner[0] - origin[0], corner[1] - origin[1]))
            if tour is not None and tour.isVisible() and tour.isWindow():
                shot = tour.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
                data = bytes(shot.constBits())
                over = Image.frombuffer('RGBA', (shot.width(), shot.height()), data, 'raw', 'RGBA',
                                        shot.bytesPerLine(), 1)
                client = W.POINT(0, 0)
                ctypes.windll.user32.ClientToScreen(W.HWND(hwnd), ctypes.byref(client))
                image.paste(over.convert('RGB'), (client.x - origin[0], client.y - origin[1]), over.getchannel('A'))
            image.resize((image.width // 2, image.height // 2)).save(folder / f'{name}.jpg', quality=80)
        except Exception as exc:  # noqa: BLE001 - a missing picture is reported, not fatal
            result.setdefault('still_errors', []).append(f'{name}: {exc}')

    def film(label, seconds):
        state['label'] = label
        state['capture_until'] = time.monotonic() + seconds

    # ---------------------------------------------------------------- helpers
    def tour_alive():
        from ..app.home_tour import GuidedTour
        return next((t for t in window.findChildren(GuidedTour) if getattr(t, 'mode', '') != 'closed'), None)

    def target_point(tour):
        target = tour._target(tour.index)
        if target is None:
            return None, None
        if isinstance(target, tuple):
            widget, part = target
            centre = window.mapFromGlobal(widget.mapToGlobal(part.center().toPoint()))
        else:
            widget = target
            centre = window.mapFromGlobal(widget.mapToGlobal(widget.rect().center()))
        return widget, centre

    def system_window_at(point):
        """The window the system gives a click at ``point`` (main window coordinates): main | overlay | other."""
        import ctypes
        from ctypes import wintypes as W
        user = ctypes.windll.user32
        user.WindowFromPoint.argtypes = [W.POINT]
        user.WindowFromPoint.restype = W.HWND
        dpr = window.devicePixelRatioF()
        spot = W.POINT(int(point.x() * dpr), int(point.y() * dpr))
        user.ClientToScreen(W.HWND(hwnd), ctypes.byref(spot))
        found = int(user.WindowFromPoint(spot) or 0)
        overlay = state.get('overlay_hwnd') or 0
        if overlay and found == overlay:
            return 'overlay'
        if found == hwnd or user.IsChild(W.HWND(hwnd), W.HWND(found)):
            return 'main'
        tour = state['tour']
        host = tour._step_host() if tour is not None and hasattr(tour, '_step_host') else None
        if host is not None:
            host_hwnd = int(host.winId())
            if found == host_hwnd or user.IsChild(W.HWND(host_hwnd), W.HWND(found)):
                return 'host'
        return f'other:{found}'

    def send_click(point, where, double=False):
        """A press and release where the system would deliver it (QTest through that window's handle)."""
        tour = state['tour']
        top = tour if where == 'overlay' and tour is not None and tour.isWindow() else window
        if where == 'host' and tour is not None and tour._step_host() is not None:
            host = tour._step_host()
            point = host.mapFromGlobal(window.mapToGlobal(point))
            top = host
        handle = top.windowHandle()
        QApplication.sendEvent(handle, QEnterEvent(QPointF(point), QPointF(point), QPointF(window.mapToGlobal(point))))
        QTest.mouseMove(handle, point)
        if double:
            QTest.mouseDClick(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        else:
            QTest.mouseClick(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)

    def close_strays():
        popup = QApplication.activePopupWidget()
        if popup is not None:
            popup.close()
        tour = tour_alive()
        host = tour._step_host() if tour is not None else None
        for top in QApplication.topLevelWidgets():
            if top is host or (tour is not None and getattr(tour._step(), 'host', None) is not None):
                continue
            if top is not window and top.isVisible() and isinstance(top, (QDialog, QMessageBox)):
                top.reject() if isinstance(top, QDialog) else top.close()

    def studio_playing():
        page = window.built_page('studio') if hasattr(window, 'built_page') else None
        if page is None or window.pages.currentWidget() is not page:
            return None
        video = getattr(page, 'video', None)
        return None if video is None else not bool(getattr(video, '_paused', True))

    def settled(tour, quiet_ms=700, limit_ms=9000):
        """Wait until the bubble (or the chip) is shown and nothing has moved for ``quiet_ms``."""
        mark = dict(since=time.monotonic(), last=None, begun=time.monotonic(), index=tour.index)

        def done():
            if tour_alive() is None or compare_window() is not None:
                return True
            if mark['index'] != tour.index:
                mark.update(index=tour.index, since=time.monotonic(), last=None)
            shown = tour.bubble.isVisible() and float(getattr(tour, 'reveal', 1.0)) >= 0.99
            key = (shown, tuple(_rect(tour.bubble.geometry())), tuple(_rect(tour.hole)), getattr(tour, 'mode', ''))
            if key != mark['last']:
                mark.update(last=key, since=time.monotonic())
            if time.monotonic() - mark['begun'] > limit_ms / 1000:
                return True
            return key[0] and (time.monotonic() - mark['since']) * 1000 >= quiet_ms
        return done

    def above(upper: int, lower: int) -> bool:
        """``upper`` comes before ``lower`` in the system's z-order (it is drawn over it)."""
        import ctypes
        from ctypes import wintypes as W
        user = ctypes.windll.user32
        user.GetWindow.argtypes = [W.HWND, W.UINT]
        user.GetWindow.restype = W.HWND
        node = upper
        for _ in range(4000):
            node = int(user.GetWindow(W.HWND(node), 2) or 0)   # GW_HWNDNEXT: the window below
            if not node:
                return False
            if node == lower:
                return True
        return False

    def compare_window():
        from ..app.quick_setup import QuickSetupDialog
        return next((top for top in QApplication.topLevelWidgets()
                     if isinstance(top, QuickSetupDialog) and top.isVisible() and getattr(top, 'compare', False)), None)

    def other_window(host):
        """A visible dialog that is not the window the step points into (a guide shown with exec())."""
        return next((top for top in QApplication.topLevelWidgets()
                     if isinstance(top, QDialog) and top.isVisible() and top is not host), None)

    def watch_overlay(tour):
        state['overlay_hwnd'] = int(tour.winId()) if tour.isWindow() else 0
        state['overlay_shown'] = tour.isVisible()

    def tip(name, widget):
        """2026-10-21 (TWOBYTEASR_TOUR_TOOLTIPS=1): show the real tooltip of ``widget``,
        keep a picture of it and check that its whole text fits at this zoom."""
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QToolTip
        QToolTip.hideText()
        yield 0.1
        text = widget.toolTip()
        QToolTip.showText(widget.mapToGlobal(QPoint(widget.width() // 2, widget.height())), text, widget)
        yield 0.4
        tips = [w for w in QApplication.topLevelWidgets() if w.metaObject().className() == 'QTipLabel' and w.isVisible()]
        row = dict(name=name, widget=widget.objectName() or type(widget).__name__, text=text, shown=bool(tips))
        if tips:
            label = tips[0]
            needed = max(label.fontMetrics().horizontalAdvance(line) for line in text.split('\n'))
            row.update(size=[label.width(), label.height()], inner_width=label.contentsRect().width(),
                       text_width=needed)
            label.grab().save(str(folder / f'tip-{name}.png'))
            check(f'tooltip {name}: whole text fits', row['inner_width'] >= needed, row)
        else:
            check(f'tooltip {name}: shown', False, row)
        result.setdefault('tooltips', []).append(row)
        QToolTip.hideText()
        yield 0.2

    # ---------------------------------------------------------------- the walk
    def run():
        from ..app.quick_setup import QuickSetupDialog

        def later():
            for top in QApplication.topLevelWidgets():
                if isinstance(top, QuickSetupDialog) and top.isVisible():
                    cards = list(top.cards)
                    result['chooser'] = dict(order=cards, selected=top.choice, tour_box=top.tour_check.isChecked(),
                                             cloud_models=top.cards['cloud'].models.text() if 'cloud' in top.cards else '')
                    shot = top.grab()
                    shot.save(str(folder / 'chooser.png'))
                    if choose:
                        top.select(choose)
                        QTest.mouseClick(top.go_button, Qt.MouseButton.LeftButton)
                    else:
                        QTest.mouseClick(top.later_button, Qt.MouseButton.LeftButton)
                    return True
            return False
        window.showMaximized()
        deadline = time.monotonic() + 20
        if tooltips:
            yield lambda: any(isinstance(top, QuickSetupDialog) and top.isVisible()
                              for top in QApplication.topLevelWidgets())
            yield 0.6
            top = next(top for top in QApplication.topLevelWidgets()
                       if isinstance(top, QuickSetupDialog) and top.isVisible())
            if choose:
                top.select(choose)
                yield 0.3
            yield from tip('chooser-source', top.source_combo)
        while time.monotonic() < deadline and not later():
            yield 0.3
        yield lambda: tour_alive() is not None and tour_alive().isVisible()
        tour = tour_alive()
        state['tour'] = tour
        tour.installEventFilter(paint_log)
        tour.installEventFilter(show_log)
        tour.bubble.installEventFilter(paint_log)
        watch_overlay(tour)
        result['overlay'] = dict(top_level=tour.isWindow(), floating=bool(getattr(tour, 'floating', False)))
        threading.Thread(target=capture_loop, name='tour-frames', daemon=True).start()
        film('s01', 1.2)
        walked = []
        detoured = False
        for _ in range(120):
            if tour_alive() is None:
                break
            if tour_alive() is not tour:
                # 基础 went on to 进阶: a new tour object; its steps count on from the last one.
                state['offset'] += len(tour.steps)
                tour = tour_alive()
                state['tour'] = tour
                tour.installEventFilter(paint_log)
                tour.bubble.installEventFilter(paint_log)
                watch_overlay(tour)
            elif state['part'] and getattr(tour, 'part', '') != state['part']:
                state['offset'] += state['part_len']   # 进阶 in the same overlay (2026-10-21)
            state.update(part=getattr(tour, 'part', ''), part_len=len(tour.steps))
            yield settled(tour)
            if tour_alive() is None:
                break
            watch_overlay(tour)
            index = tour.index
            step = tour.steps[index]
            widget, point = target_point(tour)
            row = dict(index=state['offset'] + index, part=getattr(tour, 'part', ''), t=now(),
                       text=tour.text.text()[:120], interactive=step.interactive,
                       click_step=getattr(step, 'click', None) is not None,
                       page=window.pages.currentWidget().objectName(), hole=_rect(tour.hole),
                       bubble=_rect(tour.bubble.geometry()), side=_side(tour), compact=bool(tour._compact),
                       size=getattr(tour, '_size_key', ''), anim=tour.anim.name if tour.anim.isVisible() else '',
                       playing=studio_playing(), native_child=bool(not tour.isWindow() and tour.internalWinId()),
                       top_level=tour.isWindow(), mode=getattr(tour, 'mode', ''))
            plan = window.__dict__.get('recognition_plan')
            if plan is not None:
                card = plan.cards.get('timeline')
                row['timeline_card'] = (card.model_label.text(), card.status_badge.text()) if card is not None else None
            hint = window.__dict__.get('subtitle_language_hint')
            row['language_hint'] = hint.text() if hint is not None and hint.isVisible() else ''
            row['host'] = bool(getattr(step, 'host', None) is not None and tour._step_host() is not None)
            if row['host']:
                row['host_on_top'] = (tour.isVisible() and tour._foreign_dialog() is None
                                      and above(state.get('overlay_hwnd') or 0, int(tour._step_host().winId())))
            if step.anim == 'glossary' and window.__dict__.get('terms') is not None:
                output = window.subtitle_output
                row['locks'] = dict(gate=window.__dict__.get('_ai_gate_state'), terms=window.terms.isEnabled(),
                                    search=window.term_search.isEnabled(),
                                    translation=[output.model().item(i).isEnabled() for i in range(output.count())],
                                    punctuation=window.subtitle_punctuation.isEnabled(),
                                    state_line=window.term_state_label.text())
            if widget is not None:
                where = system_window_at(point)
                want = 'overlay' if row['click_step'] else ('host' if row['host'] else 'main')
                row.update(where=where, reaches=where == want, target=type(widget).__name__)
                hole, box = QRectF(tour.hole), QRectF(tour.bubble.geometry())
                dx = max(0.0, max(hole.left() - box.right(), box.left() - hole.right()))
                dy = max(0.0, max(hole.top() - box.bottom(), box.top() - hole.bottom()))
                row['gap'] = round((dx * dx + dy * dy) ** 0.5)
            walked.append(row)
            result['steps'].append(row)
            still(f"S{row['index'] + 1:02d}")
            if tooltips and not any(t['name'].startswith('tour-') for t in result.get('tooltips', [])):
                # The outlined control's own tooltip, else the first one on the page under the tutorial.
                page = window.pages.currentWidget()
                shown = [w for w in ([widget] if widget is not None else []) + page.findChildren(QWidget)
                         if w.isVisible() and w.toolTip().strip()]
                if shown:
                    yield from tip(f"tour-S{row['index'] + 1:02d}", shown[0])
                    yield settled(tour)
            # Go on the way a person does.
            moving = next((i for i, a in enumerate(step.actions) if a.advance), None)
            before = index
            modal_move = next((i for i, a in enumerate(step.actions) if a.advance and a.modal), None)
            if getattr(step, 'auto', None) is not None:
                # 2026-10-22: the plan step opens the comparison by itself a moment after it appears.
                film(f's{index + 1:02d}-plans', 2.0)
                yield lambda: compare_window() is not None or tour_alive() is None or tour.index != before
                compare = compare_window()
                plans = dict(index=row['index'], opened=compare is not None, mode=getattr(tour, 'mode', ''),
                             overlay_visible=tour.isVisible())
                if compare is not None:
                    yield 0.6
                    compare.grab().save(str(folder / f"S{row['index'] + 1:02d}-plans.png"))
                    plans.update(cards=list(compare.cards), selected=compare.choice,
                                 points={key: len(card.points) for key, card in compare.cards.items()},
                                 tour_box=compare.tour_check.isVisible(), go=compare.go_button.text())
                    compare.select(choose or 'cloud')
                    QTest.mouseClick(compare.go_button, Qt.MouseButton.LeftButton)
                yield lambda: tour_alive() is None or tour.index != before
                plans.update(next_index=tour.index if tour_alive() is not None else None,
                             plan=window._current_plan_key())
                result['plans'] = plans
            elif modal_move is not None and getattr(step, 'host', None) is not None and clicking == 'real':
                # 申请教程 inside AI 设置: the guide opens with exec() - from the timer, never inside this step.
                film(f's{index + 1:02d}-guide', 3.0)
                host = tour._step_host()
                QTimer.singleShot(0, lambda b=tour.action_buttons[modal_move]: QTest.mouseClick(b, Qt.MouseButton.LeftButton))
                opened = dict(index=row['index'], where='action', t=now())
                yield lambda: other_window(host) is not None
                yield 0.8
                dialog = other_window(host)
                opened.update(dialog=type(dialog).__name__, title=dialog.windowTitle() if dialog is not None else '',
                              mode=getattr(tour, 'mode', ''), overlay_visible=tour.isVisible(),
                              bubble_visible=tour.bubble.isVisible())
                if dialog is not None:
                    dialog.grab().save(str(folder / f"S{row['index'] + 1:02d}-window.png"))
                    dialog.reject()
                yield lambda: tour_alive() is None or tour.index != before
                yield settled(tour)
                opened.update(back_index=tour.index, back_mode=getattr(tour, 'mode', ''),
                              back_bubble=tour.bubble.isVisible(), host_still_open=tour._step_host() is not None)
                result['windows'].append(opened)
            elif getattr(step, 'host', None) is not None and not step.show_next and step.actions:
                # 要开启 AI 吗: 保存并开启 (with the test key); if it cannot save, 先不开. From the timer:
                # a refusal comes as a message box with exec().
                tried = []
                for button in list(tour.action_buttons):
                    tried.append(button.text())
                    QTimer.singleShot(0, lambda b=button: QTest.mouseClick(b, Qt.MouseButton.LeftButton))
                    yield 1.5
                    for top in QApplication.topLevelWidgets():
                        if isinstance(top, QMessageBox) and top.isVisible():
                            tried.append('message: ' + top.text()[:80])
                            top.close()
                            yield 0.4
                    if tour_alive() is None or tour.index != before:
                        break
                result['ai_enable'] = dict(index=row['index'], tried=tried,
                                           closed=window.__dict__.get('_ai_settings_dialog') is None,
                                           next_index=tour.index if tour_alive() is not None else None,
                                           gate=window.__dict__.get('_ai_gate_state'))
            elif (not detoured and step.anim == 'plan_ok' and widget is not None and clicking == 'real'
                    and getattr(tour, 'mode', None) is not None):
                # Detour: the model card opens the workshop; the tutorial waits on its chip.
                detoured = True
                detour = result['detour']
                detour['index'] = row['index']
                film('detour', 2.0)
                send_click(point, system_window_at(point))
                yield lambda: window.pages.currentWidget().objectName() != 'settingsScroll' or True
                yield 1.2
                still(f"S{row['index'] + 1:02d}-detour-chip")
                page = window.pages.currentWidget()
                detour.update(page=page.objectName() if page is not None else '', mode=getattr(tour, 'mode', ''),
                              chip=tour.chip.isVisible() if hasattr(tour, 'chip') else None,
                              bubble=tour.bubble.isVisible(), hole=_rect(tour.hole))
                if hasattr(tour, 'chip') and tour.chip.isVisible():
                    chip_point = tour.chip.mapTo(tour, tour.chip_resume.geometry().center())
                    detour['chip_where'] = system_window_at(chip_point)
                    QTest.mouseClick(tour.chip_resume, Qt.MouseButton.LeftButton)
                    yield settled(tour)
                detour.update(back_page=window.pages.currentWidget().objectName(), back_index=tour.index,
                              back_mode=getattr(tour, 'mode', ''), back_bubble=tour.bubble.isVisible())
                QTest.mouseClick(tour.next, Qt.MouseButton.LeftButton)
                yield lambda: tour_alive() is None or tour.index != before
            elif getattr(getattr(step, 'click', None), 'modal', False) and widget is not None and clicking == 'real':
                # A click that opens a real window: nothing of the tutorial over it, back when it closes.
                film(f's{index + 1:02d}-window', 3.0)
                where = system_window_at(point)
                # Later, from the timer: exec() of the window must not run inside this walk step.
                QTimer.singleShot(0, lambda p=point, w=where: send_click(p, w))
                opened = dict(index=row['index'], where=where, t=now())

                def open_window():
                    # SpringDialog.exec() is not Qt-modal (its own loop and a backdrop): any shown dialog.
                    return next((top for top in QApplication.topLevelWidgets()
                                 if isinstance(top, QDialog) and top.isVisible()), None)
                yield lambda: open_window() is not None
                yield 0.8
                dialog = open_window()
                opened.update(dialog=type(dialog).__name__, title=dialog.windowTitle() if dialog is not None else '',
                              mode=getattr(tour, 'mode', ''), overlay_visible=tour.isVisible(),
                              bubble_visible=tour.bubble.isVisible())
                if dialog is not None:
                    dialog.grab().save(str(folder / f"S{row['index'] + 1:02d}-window.png"))
                    dialog.reject()
                yield lambda: tour_alive() is None or tour.index != before or (
                    getattr(tour, 'mode', '') == 'shown' and tour.bubble.isVisible())
                yield settled(tour)
                opened.update(back_index=tour.index, back_mode=getattr(tour, 'mode', ''),
                              back_bubble=tour.bubble.isVisible())
                if tour_alive() is not None and tour.index == before:
                    # Came back on the same step (AI: no key yet): go on with 稍后再填 / 先跳过.
                    later = next((b for b, a in zip(tour.action_buttons, step.actions) if a.advance and not a.modal), None)
                    still(f"S{row['index'] + 1:02d}-back")
                    if later is not None:
                        QTest.mouseClick(later, Qt.MouseButton.LeftButton)
                        yield lambda: tour_alive() is None or tour.index != before
                result['windows'].append(opened)
            elif (step.interactive or getattr(step, 'click', None) is not None) and widget is not None \
                    and clicking == 'real':
                raw = step.text() if callable(step.text) else str(step.text)
                double = step.anim == 'edit'
                presses.clear()
                film(f's{index + 1:02d}-click', 2.5)
                if 'Enter' in raw:
                    how = 'key Enter'
                    QTest.keyClick(QApplication.focusWidget() or widget, Qt.Key.Key_Return)
                elif '1 / 2 / 3' in raw or '1/2/3' in raw:
                    how = 'key 1'
                    keys = step.focus() if step.focus is not None else None
                    QTest.keyClick(keys or QApplication.focusWidget() or window, Qt.Key.Key_1)
                else:
                    where = system_window_at(point)
                    how = ('double-click' if double else 'click') + f' ({where})'
                    send_click(point, where, double=double)
                got = [dict(cls=p['cls'], name=p['name']) for p in presses[:3]]
                click = dict(index=index, how=how, receivers=got, t=now())
                # Right after the click: what the outline and bubble do while the page reacts.
                samples = []
                end = time.monotonic() + 1.5
                while time.monotonic() < end and tour_alive() is not None and tour.index == before:
                    target = tour._target(before)
                    movie = tour.anim._movie
                    samples.append(dict(t=now(), v=tour.bubble.isVisible() and tour.isVisible(), h=_rect(tour.hole),
                                        mode=getattr(tour, 'mode', ''), target_visible=target is not None,
                                        page=window.pages.currentWidget().objectName(),
                                        anim=bool(movie is not None and movie.state() == QMovie.MovieState.Running)))
                    watch_overlay(tour)
                    yield 0.1
                click['after'] = samples
                limit = time.monotonic() + (25 if step.anim == 'studio_open' else 6)
                yield lambda: tour_alive() is None or tour.index != before or time.monotonic() > limit
                click['advanced'] = tour_alive() is None or tour.index != before
                if not click['advanced'] and getattr(step, 'host', None) is not None and step.show_next:
                    # Inside AI 设置 the click is the user's part (a key pasted, a test run offline);
                    # the step itself waits for 下一步.
                    click['advanced'] = True
                    click['inside_window'] = True
                    if step.focus is not None and isinstance(QApplication.focusWidget(), QLineEdit):
                        QApplication.focusWidget().insert('sk-tutorial-audit-0000000000000000')
                        click['typed'] = True
                    QTest.mouseClick(tour.next, Qt.MouseButton.LeftButton)
                    yield lambda: tour_alive() is None or tour.index != before
                elif not click['advanced'] and step.actions:
                    click['helper'] = True     # the click did not do it: "帮我做" so the walk goes on
                    QTest.mouseClick(tour.action_buttons[0], Qt.MouseButton.LeftButton)
                    yield lambda: tour_alive() is None or tour.index != before
                result['clicks'].append(click)
            else:
                if step.anim in ('language', 'spoken') and spoken:
                    label = {'zh': '中文', 'ja': '日本語', 'en': 'English'}[spoken]
                    pick = next((b for b, a in zip(tour.action_buttons, step.actions) if a.label == label), None)
                    if pick is not None:
                        QTest.mouseClick(pick, Qt.MouseButton.LeftButton)
                        yield 0.6
                        still(f'S{index + 1:02d}-{spoken}')
                if moving is not None:
                    button = tour.action_buttons[moving]
                elif step.interactive and tour.action_buttons:
                    button = tour.action_buttons[0]
                else:
                    button = tour.next
                last = index == len(tour.steps) - 1
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                if last and moving is not None:   # 继续学进阶: wait for the second part to start
                    yield lambda: tour_alive() is not None and (tour_alive() is not tour
                                                                or getattr(tour, 'part', '') == 'advanced')
                else:
                    yield lambda: tour_alive() is None or tour.index != before or tour.bubble.isVisible() is False
            close_strays()
            if tour_alive() is tour:   # a new part (进阶) is picked up at the top of the loop
                watch_overlay(tour)
                film(f's{tour.index + 1:02d}', 1.4)
        yield lambda: tour_alive() is None
        check('tutorial walked to its end in one part (no separate 进阶)',
              walked and walked[-1]['index'] == state['offset'] + len(tour.steps) - 1
              and len({r['part'] for r in walked}) == 1, [(r['part'], r['index']) for r in walked])

    # ---------------------------------------------------------------- analysis
    def analyse():
        by_step: dict = {}
        for row in paints:
            by_step.setdefault(row['i'], []).append(row)
        detour_steps = {result['detour']['index']} if result.get('detour', {}).get('index') is not None else set()
        # A step whose click opened a window (MOSS Pro / DeepSeek guide) steps aside and comes back by design.
        detour_steps |= {w['index'] for w in result.get('windows') or () if w.get('back_index') == w.get('index')}
        motion = []
        for index, rows in sorted(by_step.items()):
            visible = [row for row in rows if row['v']]
            if not visible:
                continue
            appearances = sum(1 for a, b in zip([dict(v=False)] + rows, rows) if b['v'] and not a['v'])
            shown = [row['b'][:2] for row in visible if row['r'] >= 0.99]
            jumps = [max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(shown, shown[1:])]
            slide = [row['b'][:2] for row in visible if row['r'] < 0.99]
            slide_jumps = [max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(slide, slide[1:])]
            sides, compacts, sizes = [], [], []
            for row in visible:
                if not sides or sides[-1] != row['p']:
                    sides.append(row['p'])
                if not compacts or compacts[-1] != row['c']:
                    compacts.append(row['c'])
                if not sizes or sizes[-1] != row['b'][2:]:
                    sizes.append(row['b'][2:])
            motion.append(dict(index=index, appearances=appearances, positions=len(set(map(tuple, shown))),
                               max_jump=max(jumps) if jumps else 0, slide_max_jump=max(slide_jumps) if slide_jumps else 0,
                               bubble_sizes=len(sizes), sides=sides, compact_changes=len(compacts) - 1,
                               detour=index in detour_steps))
        result['motion'] = motion
        plain = [m for m in motion if not m['detour']]
        check('bubble: appears once per step (no disappear-and-reappear)',
              plain and all(m['appearances'] <= 1 for m in plain),
              [(m['index'], m['appearances']) for m in plain if m['appearances'] > 1])
        check('bubble: once shown it never jumps (a moving target carries it along smoothly, <= 45 px per frame)',
              all(m['max_jump'] <= 45 for m in motion),
              [(m['index'], m['positions'], m['max_jump']) for m in motion if m['max_jump'] > 45])
        check('bubble: never resizes or changes side within a step; the fade-in slide is small',
              all(m['bubble_sizes'] <= 1 and len([s for s in m['sides'] if s]) <= 1 and m['compact_changes'] == 0
                  and m['slide_max_jump'] <= 12 for m in plain),
              [(m['index'], m['bubble_sizes'], m['sides'], m['compact_changes'], m['slide_max_jump']) for m in plain
               if m['bubble_sizes'] > 1 or len([s for s in m['sides'] if s]) > 1 or m['compact_changes']
               or m['slide_max_jump'] > 12])
        steps = [s for s in result['steps'] if 'reaches' in s]
        check('every outlined control gets a click at its centre (or the step does its demo action)',
              steps and all(s['reaches'] for s in steps),
              [(s['index'], s['target'], s['where']) for s in steps if not s['reaches']])
        stale = []
        for click in result['clicks']:
            bad = [s for s in click.get('after', ()) if s['v'] and not s['target_visible']]
            if bad:
                stale.append((click['index'], len(bad), bad[0]))
        check('after a click that leaves the page, no outline or bubble is left on the old spot', not stale, stale)
        check('every click on an outlined control did what the step asks',
              result['clicks'] and all(c['advanced'] for c in result['clicks']),
              [(c['index'], c['how'], c['receivers']) for c in result['clicks'] if not c['advanced']])
        far = [(s['index'], s['gap']) for s in steps if s.get('gap', 0) > 60]
        check('bubble sits next to its outline (gap at most 60 px)', not far, far)
        playing = [s['index'] for s in result['steps'] if s.get('playing')]
        check('the workbench video does not play while the tutorial points at it', not playing, playing)
        native = [s['index'] for s in result['steps'] if s.get('native_child')]
        check('the overlay never becomes a native child window of the main window', not native, native)
        detour = result.get('detour') or {}
        if detour or not choose:
            check('a model card opens the workshop; the tutorial waits on its chip and comes back with "回到教学"',
                  detour.get('mode') == 'away' and detour.get('chip') and not detour.get('bubble')
                  and detour.get('chip_where') == 'overlay' and detour.get('back_mode') == 'shown'
                  and detour.get('back_bubble'), detour)
        windows = result.get('windows') or []
        if choose == 'cloud':
            check('cloud chosen: the MOSS Pro and DeepSeek guides open from their steps',
                  len(windows) >= 2, [(w.get('index'), w.get('dialog'), w.get('title')) for w in windows])
        if windows:
            check('while a guide window is open, nothing of the tutorial is shown; it comes back when it closes',
                  all(not w.get('overlay_visible') and w.get('mode') == 'dialog' and w.get('back_bubble')
                      for w in windows), windows)
        plans = result.get('plans') or {}
        check('plan step: the cloud / local comparison opens by itself, each card says what it is good for and '
              'what to watch out for, no tutorial box in it; the choice is saved and the tutorial goes on',
              plans.get('opened') and plans.get('cards', [])[:2] in (['cloud', 'local'], ['cloud', 'apple'])
              and all(count >= 4 for count in (plans.get('points') or {0: 0}).values()) and not plans.get('tour_box')
              and plans.get('plan') == (choose or 'cloud') and plans.get('next_index') != plans.get('index'), plans)
        inside = [s for s in result['steps'] if s.get('host')]
        check('AI 设置: the tutorial points into the open window (above it, clicks at each outline reach the window)',
              len(inside) >= 4 and all(s.get('host_on_top') and s.get('reaches') for s in inside),
              [(s['index'], s.get('where'), s.get('host_on_top')) for s in inside])
        enable = result.get('ai_enable') or {}
        check('要开启 AI 吗: the window closes and the tutorial goes on with the content steps',
              enable.get('closed') and enable.get('next_index') is not None, enable)
        locks = next((s.get('locks') for s in result['steps'] if s.get('locks')), None) or {}
        check('without a tested key: 术语库校对 and 联网补充核验 are locked, only "只显示原文" can be picked, '
              'punctuation stays free',
              locks.get('gate') != 'ready' and locks.get('terms') is False and locks.get('search') is False
              and locks.get('translation') == [True, False, False] and locks.get('punctuation') is True, locks)
        flashes = [row for row in shows if not row['shown'] and row['mode'] not in ('dialog', 'closed')]
        check('the overlay is never hidden while a page opens (no bright flash, e.g. entering the workbench)',
              not flashes, flashes)
        # How long a change of step takes: from the first frame of the new step to its bubble fully shown.
        timings = []
        for index, rows in sorted(by_step.items()):
            start = next((row['t'] for row in rows if row['m'] in ('wait', 'glide')), None)
            ready = next((row['t'] for row in rows if row['m'] == 'shown' and row['r'] >= 0.99 and row['v']), None)
            if start is not None and ready is not None and ready >= start:
                timings.append((index, ready - start))
        result['step_ms'] = timings
        values = sorted(ms for _i, ms in timings)
        median = values[len(values) // 2] if values else 0
        check('a change of step takes at most 450 ms in the middle (outline glide + bubble fade-in)',
              values and median <= 450, dict(median=median, slowest=sorted(timings, key=lambda x: -x[1])[:5]))
        chooser = result.get('chooser') or {}
        check('first-run chooser: cloud first, chosen by default, tutorial box ticked',
              chooser.get('order', [None])[0] == 'cloud' and chooser.get('selected') == 'cloud'
              and chooser.get('tour_box'), chooser)
        flat = ' '.join(str(s.get('text', '')) for s in result['steps'])
        check('no step says subtitles work without an API key',
              not any(words in flat for words in ('不填 API Key', '不填也能', 'API Key 也能', '没填也能')),
              [s['text'] for s in result['steps'] if 'API Key' in str(s.get('text', ''))])

    # ---------------------------------------------------------------- runner
    iterator = run()
    timer = QTimer(window)

    def save():
        result['shows'] = shows
        result['slow_calls'] = slow
        (output / 'result-tour.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        with (folder / 'paints.jsonl').open('w', encoding='utf-8') as handle:
            for row in paints:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    def finish():
        timer.stop()
        state['closing'] = True
        try:
            analyse()
        except Exception:  # noqa: BLE001
            result['analysis_error'] = traceback.format_exc()
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result.get('error')
        save()
        page = window.built_page('studio') if hasattr(window, 'built_page') else None
        if page is not None and getattr(page, 'undo_stack', None) is not None:
            page.undo_stack.setClean()
        window.close()
        QTimer.singleShot(500, QApplication.instance().quit)

    def tick():
        if state['ticking']:
            return
        state['ticking'] = True
        try:
            if state['wait'] is not None:
                if state['wait']():
                    state['wait'] = None
                elif time.monotonic() > state['deadline']:
                    raise TimeoutError('Real GUI condition did not settle')
                else:
                    return
            if time.monotonic() < state['until']:
                return
            value = next(iterator)
            if callable(value):
                state.update(wait=value, deadline=time.monotonic() + 60)
            else:
                state['until'] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:  # noqa: BLE001
            result['error'] = traceback.format_exc()
            finish()
        finally:
            state['ticking'] = False

    QApplication.instance().aboutToQuit.connect(lambda: (result.__setitem__('gui_shutdown', True), save()))
    timer.timeout.connect(tick)
    timer.start(30)
