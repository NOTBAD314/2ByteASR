"""Studio panel dividers and the video following them, in the real window (2026-10-22).

User report (1920x1080 screen, review mode, three speakers): the dividers between
the panels cannot be moved freely and stop at fixed places, and after moving
them the video picture follows one beat late.

For each window size this records the dividers' allowed ranges and the minimum
heights that set them, drags each divider with mouse events on the window, and
samples the native mpv child window and the picture drawn in it (PrintWindow)
until they match the Qt video surface again, during and after each drag. It
also times each drag step (mouse move + event processing) and the release.

Diagnostics: TWOBYTEASR_SPLITTER_PROFILE=workspace|upper writes a cProfile of
that divider's first drag; TWOBYTEASR_SPLITTER_VARIANT (noreview, nocontext,
nocues, notimeline, combined with '-') removes parts to see what a step costs,
and 'subtitle-latency' only times the subtitle redraw after large resizes.
Subtitle presence is the count of near-white pixels in mpv's own window.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(Path(output), window=window)
        except Exception:
            path = Path(output) / 'result.json'
            try:
                result = json.loads(path.read_text('utf8'))
            except (OSError, ValueError):
                result = {}
            result.update(passed=False, error=traceback.format_exc())
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            path = Path(output) / 'result.json'
            result = json.loads(path.read_text('utf8'))
            result['gui_shutdown'] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100, execute)


def _native_rects(canvas):
    """Screen rects of the Qt video surface and of mpv's child window inside it."""
    if sys.platform != 'win32':
        return None, None
    import ctypes
    from ctypes import wintypes as W
    user = ctypes.windll.user32
    parent = int(canvas.winId())
    found = []
    proc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

    def collect(hwnd, _param):
        pid = W.DWORD()
        user.GetWindowThreadProcessId(W.HWND(hwnd), ctypes.byref(pid))
        if pid.value != os.getpid() and user.IsWindowVisible(W.HWND(hwnd)):
            found.append(int(hwnd))
        return True
    callback = proc(collect)
    user.EnumChildWindows(W.HWND(parent), callback, 0)

    def rect(hwnd):
        value = W.RECT()
        user.GetWindowRect(W.HWND(hwnd), ctypes.byref(value))
        return (value.left, value.top, value.right - value.left, value.bottom - value.top)
    _native_rects.mpv_hwnd = found[0] if found else 0
    return rect(parent), (rect(found[0]) if found else None)


def _picture_box(hwnd: int, size: tuple[int, int]):
    """Bounding box of the drawn picture inside mpv's window (non-black pixels), device px."""
    import numpy as np
    from scripts.capture_process_window import print_window
    captured = print_window(hwnd, (0, 0, size[0], size[1]))
    _picture_box.last_image = captured
    image = np.asarray(captured)
    mask = image.max(axis=2) > 48
    # Count only rows/columns with real picture in them; a stray 1 px mark
    # at the window edge is not the picture.
    # (the 1 px theme border at the window edge is not either).

    def longest_run(flags):
        best, start = (0, -1), None
        for index, flag in enumerate([*flags, False]):
            if flag and start is None:
                start = index
            elif not flag and start is not None:
                if index - start > best[1] - best[0] + 1:
                    best = (start, index - 1)
                start = None
        return best
    left, right = longest_run(mask.sum(axis=0) >= max(8, mask.shape[0] // 20))
    top, bottom = longest_run(mask.sum(axis=1) >= max(8, mask.shape[1] // 20))
    if right < left or bottom < top:
        return None
    return (left, top, right - left + 1, bottom - top + 1)


def _expected_box(size: tuple[int, int], aspect: float):
    width = min(size[0], size[1] * aspect)
    height = width / aspect
    return (round((size[0] - width) / 2), round((size[1] - height) / 2), round(width), round(height))


def _boxes_match(found, expected, tolerance=4) -> bool:
    return found is not None and all(abs(a - b) <= tolerance for a, b in zip(found, expected))


def _picture_lag(limit_ms=600.0):
    """Milliseconds until the drawn picture fits mpv's current window (None = never within limit)."""
    began = time.perf_counter()
    last = None
    while True:
        _canvas, mpv = _native_rects(_picture_lag.canvas)
        elapsed = (time.perf_counter() - began) * 1000
        if mpv is not None:
            found = _picture_box(_native_rects.mpv_hwnd, (mpv[2], mpv[3]))
            expected = _expected_box((mpv[2], mpv[3]), 16 / 9)
            last = dict(found=found, expected=expected)
            if _boxes_match(found, expected):
                return round((time.perf_counter()-began)*1000, 1), last
        if elapsed > limit_ms:
            return None, last
        from PySide6.QtTest import QTest
        QTest.qWait(4)


def run(output, *, window):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QSplitter, QWidget
    from .blank_project_audit import _capture
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                           hydrate_media_contract, save_project)
    from ..studio.studio_helpers import probe_media_identity

    output = Path(output).resolve()
    if output != Path(os.environ['TWOBYTEASR_TEST_ROOT']).resolve():
        raise RuntimeError('isolated root required')
    apply_theme(os.environ.get('TWOBYTEASR_SPLITTER_THEME', 'grape'))
    expect_fix = os.environ.get('TWOBYTEASR_SPLITTER_EXPECT', 'after') == 'after'
    sizes = [tuple(int(v) for v in item.split('x'))
             for item in os.environ.get('TWOBYTEASR_SPLITTER_SIZES', '1920x1040').split(',')]
    media = Path(os.environ['TWOBYTEASR_SPLITTER_MEDIA']).resolve()
    result = dict(passed=False, checks=[], sizes=[], expect_fix=expect_fix,
                  identity=load_build_identity().to_dict(), frozen=bool(getattr(sys, 'frozen', False)),
                  platform=QApplication.platformName(), pid=os.getpid(),
                  screen=QApplication.primaryScreen().availableGeometry().getRect(),
                  dpr=QApplication.primaryScreen().devicePixelRatio())

    def receipt():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, value, detail=None):
        result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
        receipt()

    def wait(fn, label, seconds=60):
        end = time.monotonic() + seconds
        while not fn():
            if time.monotonic() > end:
                raise TimeoutError(label)
            QTest.qWait(20)

    page = window.studio_page
    speakers = ('S00', 'S01', 'S02')
    if os.environ.get('TWOBYTEASR_DRAG_PROJECT'):
        from ..projects.studio_project import load_project
        import hashlib
        original=Path(os.environ['TWOBYTEASR_DRAG_PROJECT'])
        project=load_project(original)
        result['input_project']={'path':str(original),'sha256':hashlib.sha256(original.read_bytes()).hexdigest()}
    else:
        project = SubtitleProject(
            media=StudioMedia(str(media), duration_ms=40_000, width=1920, height=1080),
            cues=[StudioCue(f'c{i}', 500 + i * 1000, 1400 + i * 1000, f'第 {i + 1} 句字幕，拖动工作区',
                            speaker_id=speakers[i % 3]) for i in range(int(os.environ.get('TWOBYTEASR_DRAG_CUES','0')))])
        project.speakers = [StudioSpeaker(id=s, name=s) for s in speakers]
        hydrate_media_contract(project, probe_media_identity(str(media)))
        project.validate()
    path = output / 'splitter.2byteproj'
    save_project(project, path)

    window.showNormal()
    window.resize(*sizes[0])
    window.show()
    QTest.qWait(300)
    prior = page.project
    window.open_studio_project(str(path), mode='edit', source='studio_splitter_audit')
    wait(lambda: page.project is not None and page.project is not prior and page._readiness.ready, 'project readiness')
    wait(lambda: page.video.controller is not None, 'player')
    QTest.qWait(1000)
    if not page.video._paused:
        page._toggle_playback()
    page.volume_slider.setValue(0)
    # Drags start after the waveform worker finished (it competes for CPU).
    wait(lambda: page.timeline.waveform_state in {'READY', 'ERROR'}, 'waveform ready', 60)
    QTest.qWait(1500)
    variant = os.environ.get('TWOBYTEASR_SPLITTER_VARIANT', '')  # experiments only
    if os.environ.get('TWOBYTEASR_DRAG_REVIEW')=='1':
        page._set_review_mode(True)
    if 'nocontext' in variant:
        page.context_panel.hide()
    if 'nocues' in variant:
        page.cue_list_panel.hide()
    if 'notimeline' in variant:
        page.timeline.hide()
    result['variant'] = variant
    QTest.qWait(800)
    wait(lambda: _native_rects(page.video)[1] is not None, 'mpv child window', 30)
    _picture_lag.canvas = page.video
    initial_host=int(page.video.winId());initial_player=_native_rects.mpv_hwnd
    if os.environ.get('TWOBYTEASR_DRAG_AUX_ONLY')=='1':sizes=[]

    def tall_minimums(root_widget, floor=90):
        """Visible widgets whose own minimum height is at least ``floor`` (who pins the layout)."""
        rows = []
        for widget in [root_widget, *root_widget.findChildren(QWidget)]:
            if not widget.isVisible():
                continue
            hint = widget.minimumSizeHint().height() if widget.layout() is None else widget.layout().minimumSize().height()
            own = max(widget.minimumHeight(), hint if widget.minimumHeight() == 0 else 0)
            if own >= floor:
                rows.append(dict(cls=type(widget).__name__, name=widget.objectName(), min=own,
                                 height=widget.height()))
        rows.sort(key=lambda row: -row['min'])
        return rows[:24]

    def native_children():
        import ctypes
        from ctypes import wintypes as W
        user = ctypes.windll.user32
        rows = []
        proc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

        def collect(hwnd, _param):
            pid = W.DWORD()
            user.GetWindowThreadProcessId(W.HWND(hwnd), ctypes.byref(pid))
            widget = QWidget.find(int(hwnd)) if pid.value == os.getpid() else None
            rows.append(dict(own=pid.value == os.getpid(), visible=bool(user.IsWindowVisible(W.HWND(hwnd))),
                             widget=(type(widget).__name__ + ':' + widget.objectName()) if widget is not None else None))
            return True
        callback = proc(collect)
        user.EnumChildWindows(W.HWND(int(window.winId())), callback, 0)
        return rows

    def wide_minimums(root_widget, floor=300):
        rows = []
        for widget in [root_widget, *root_widget.findChildren(QWidget)]:
            if not widget.isVisible():
                continue
            hint = widget.minimumSizeHint().width() if widget.layout() is None else widget.layout().minimumSize().width()
            own = max(widget.minimumWidth(), hint if widget.minimumWidth() == 0 else 0)
            if own >= floor:
                rows.append(dict(cls=type(widget).__name__, name=widget.objectName(), min=own, width=widget.width(),
                                 text=(widget.text()[:40] if hasattr(widget, 'text') and callable(widget.text) else '')))
        rows.sort(key=lambda row: -row['min'])
        return rows[:24]

    def splitter_state(splitter: QSplitter):
        state = dict(sizes=splitter.sizes(), opaque=splitter.opaqueResize(), ranges=[], children=[])
        for index in range(1, splitter.count()):
            try:
                state['ranges'].append(list(splitter.getRange(index)))
            except Exception as exc:  # protected in some bindings
                state['ranges'].append(repr(exc))
        for index in range(splitter.count()):
            child = splitter.widget(index)
            state['children'].append(dict(name=child.objectName() or type(child).__name__,
                                          min_hint=child.minimumSizeHint().toTuple(),
                                          min=child.minimumSize().toTuple(), size=child.size().toTuple()))
        return state

    def lag_until_matched(limit_s=1.5):
        """Milliseconds until mpv's child window matches the Qt surface (None = never)."""
        began = time.perf_counter()
        samples = []
        while True:
            canvas, mpv = _native_rects(page.video)
            elapsed = (time.perf_counter() - began) * 1000
            samples.append((round(elapsed, 1), canvas, mpv))
            if mpv is not None and canvas == mpv:
                return round(elapsed, 1), samples[-6:]
            if elapsed > limit_s * 1000:
                return None, samples[-6:]
            QTest.qWait(4)

    def subtitle_pixels():
        import numpy as np
        _canvas, mpv = _native_rects(page.video)
        if mpv is None:
            return 0
        _picture_box(_native_rects.mpv_hwnd, (mpv[2], mpv[3]))
        image = np.asarray(_picture_box.last_image)
        return int((image.min(axis=2) > 235).sum())

    def drag(splitter, index, delta, steps=32):
        handle = splitter.handle(index)
        handle_window = window.windowHandle()
        start_point = handle.mapTo(window, handle.rect().center())
        vertical = splitter.orientation() == Qt.Orientation.Vertical
        before = splitter.sizes()
        local = QPointF(start_point)
        QApplication.sendEvent(handle_window, QEnterEvent(local, local, QPointF(window.mapToGlobal(start_point))))
        QTest.mouseMove(handle_window, start_point, delay=0)
        QTest.qWait(30)
        QTest.mousePress(handle_window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_point)
        during = []
        for step in range(1, steps + 1):
            offset = round(delta * step / steps)
            point = start_point + (QPoint(0, offset) if vertical else QPoint(offset, 0))
            began = time.perf_counter()
            QTest.mouseMove(handle_window, point, delay=0)
            QApplication.processEvents()
            step_ms = round((time.perf_counter() - began) * 1000, 1)
            canvas_now, mpv_now = _native_rects(page.video)
            # Do not wait for each picture to catch up: that hid the lag in
            # the prior test. A continuous drag records geometry immediately.
            picture_ms, picture = None, None
            subtitle_now = subtitle_later = 0
            if step in (1, steps//2, steps):
                began_capture=time.perf_counter()
                if mpv_now:
                    found=_picture_box(_native_rects.mpv_hwnd,(mpv_now[2],mpv_now[3]))
                    picture=dict(found=found,expected=_expected_box((mpv_now[2],mpv_now[3]),16/9))
                    picture['matches']=_boxes_match(found,picture['expected'])
                    picture_ms=(time.perf_counter()-began_capture)*1000
                    _picture_box.last_image.save(str(output/f'held-{splitter.objectName()}-{index}-{delta}-{step}.png'))
            QTest.qWait(8)
            canvas_later, mpv_later = _native_rects(page.video)
            during.append(dict(step=step, sizes=splitter.sizes(), canvas=canvas_now, mpv=mpv_now,
                               mpv_after_16ms=mpv_later, matched_now=canvas_now == mpv_now,
                               matched_after_16ms=canvas_later == mpv_later,
                               picture_ms=picture_ms, picture=picture, step_ms=step_ms,
                               subtitle_px=(subtitle_now, subtitle_later)))
        began = time.perf_counter()
        QTest.mouseRelease(handle_window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QApplication.processEvents()
        release_ms = round((time.perf_counter() - began) * 1000, 1)
        released = splitter.sizes()
        lag_ms, tail = lag_until_matched()
        release_picture_ms, release_picture = _picture_lag()
        last_image = getattr(_picture_box, 'last_image', None)
        if last_image is not None:
            last_image.save(str(output / f'release-{splitter.objectName()}-{index}{delta:+d}-{len(window.findChildren(QSplitter))}.png'))
        QTest.qWait(250)
        after = splitter.sizes()
        # Moving a handle by +d grows the widget before it by d.
        achieved = after[index - 1] - before[index - 1]
        return dict(splitter=splitter.objectName(), index=index, requested=delta, achieved=achieved,
                    before=before, released=released, after=after, during=during,
                    live_steps=sum(1 for row in during if row['sizes'] != before),
                    mismatched_now=sum(1 for row in during if not row['matched_now']),
                    mismatched_after_16ms=sum(1 for row in during if not row['matched_after_16ms']),
                    release_lag_ms=lag_ms, release_tail=tail,
                    release_picture_ms=release_picture_ms, release_picture=release_picture,
                    step_picture_ms=[row['picture_ms'] for row in during],
                    step_ms=[row['step_ms'] for row in during], release_ms=release_ms,
                    subtitle_px=[row['subtitle_px'] for row in during])

    from PySide6.QtCore import QEvent, QObject

    class ResizeTrace(QObject):
        """Who resized the window (Python stack at each top-level resize)."""
        def __init__(self):
            super().__init__()
            self.rows = []

        def eventFilter(self, obj, event):
            if obj is window and event.type() == QEvent.Type.Resize and len(self.rows) < 40:
                import traceback as tb
                self.rows.append(dict(size=event.size().toTuple(), old=event.oldSize().toTuple(),
                                      min=window.minimumSize().toTuple(),
                                      stack=[line.strip() for line in tb.format_stack(limit=14)[:-1]]))
            return False
    tracer = ResizeTrace()
    window.installEventFilter(tracer)

    if 'subtitle-latency' in variant:
        # After a large resize (the end of a drag), how long until the
        # subtitle text is drawn again at the new size.
        window.showNormal()
        window.resize(*sizes[0])
        QTest.qWait(1500)
        result['subtitle_latency'] = []
        baseline = subtitle_pixels()
        for target in ('timeline-minimum', 'back', 'upper-minimum', 'back'):
            current = page.workspace_splitter.sizes()
            total = sum(current)
            host_minimum = page.workspace_splitter.widget(1).minimumSizeHint().height()
            upper_minimum = page.workspace_splitter.widget(0).minimumSizeHint().height()
            if target == 'timeline-minimum':
                wanted = [total - host_minimum, host_minimum]
            elif target == 'upper-minimum':
                wanted = [upper_minimum, total - upper_minimum]
            else:
                wanted = previous
            previous = current
            page.workspace_splitter.setSizes(wanted)
            began = time.perf_counter()
            samples = []
            shots = 0
            while time.perf_counter() - began < 3.0:
                samples.append((round((time.perf_counter() - began) * 1000), subtitle_pixels()))
                if shots < 2 and time.perf_counter() - began > (0.5 if shots == 0 else 2.0):
                    tag = f"{len(result['subtitle_latency'])}-{target}-{shots}"
                    _capture(window, output / f'latency-window-{tag}.png')
                    _picture_box.last_image.save(str(output / f'latency-mpv-{tag}.png'))
                    shots += 1
                QTest.qWait(25)
            visible = [ms for ms, count in samples if count >= max(200, baseline // 3)]
            result['subtitle_latency'].append(dict(target=target, sizes=page.workspace_splitter.sizes(),
                                                   baseline=baseline, first_visible_ms=visible[0] if visible else None,
                                                   missing_after_visible=[ms for ms, count in samples
                                                                          if visible and ms > visible[0] and count < max(200, baseline // 3)][:10],
                                                   samples=samples[:12]))
            receipt()
        sizes = []

    for width, height in sizes:
        window.showNormal()
        tracer.rows.clear()
        window.resize(width, height)
        QTest.qWait(900)
        entry = dict(requested=(width, height), window=window.size().toTuple(), resize_trace=list(tracer.rows),
                     window_min_hint=window.minimumSizeHint().toTuple(), window_min=window.minimumSize().toTuple(),
                     page=page.size().toTuple(),
                     workspace=splitter_state(page.workspace_splitter),
                     upper=splitter_state(page.upper_splitter),
                     upper_tall=tall_minimums(page.upper_splitter),
                     timeline_tall=tall_minimums(page.workspace_splitter.widget(1)),
                     center_wide=wide_minimums(page.center_splitter),
                     native_children=native_children(),
                     cue_list_wide=wide_minimums(page.upper_splitter.widget(0), 200),
                     drags=[])
        _capture(window, output / f'window-{width}x{height}.png')
        if os.environ.get('TWOBYTEASR_DRAG_PLAY')=='1':
            page._seek(1);page.video.set_paused(False);QTest.qWait(400)
        distance=int(os.environ.get('TWOBYTEASR_DRAG_DISTANCE','160'))
        plan = ((page.workspace_splitter, 1, -220), (page.workspace_splitter, 1, 220),
                (page.upper_splitter, 1, distance), (page.upper_splitter, 1, -distance),
                (page.upper_splitter, 2, -distance), (page.upper_splitter, 2, distance))
        if variant:
            plan = plan[:2] * 2
        if os.environ.get('TWOBYTEASR_DRAG_ONLY')=='workspace':plan=plan[:2]
        for splitter, index, delta in plan:
            profile = os.environ.get('TWOBYTEASR_SPLITTER_PROFILE', '')
            profile_target = page.workspace_splitter if profile == 'workspace' else page.upper_splitter
            if profile and splitter is profile_target and index == 1:
                import cProfile
                import pstats
                profiler = cProfile.Profile()
                profiler.enable()
                entry['drags'].append(drag(splitter, index, delta, steps=32))
                profiler.disable()
                with open(output / f'profile-{width}-{delta:+d}.txt', 'w', encoding='utf8') as handle:
                    pstats.Stats(profiler, stream=handle).sort_stats('cumulative').print_stats(70)
            else:
                entry['drags'].append(drag(splitter, index, delta))
            receipt()
        _capture(window, output / f'window-{width}x{height}-after.png')
        # The timeline at its minimum: rows scroll inside the track viewport,
        # which must end above the pinned video lanes.
        sizes_now = page.workspace_splitter.sizes()
        host_minimum = page.workspace_splitter.widget(1).minimumSizeHint().height()
        before_jump = subtitle_pixels()
        page.workspace_splitter.setSizes([sum(sizes_now) - host_minimum, host_minimum])
        began = time.perf_counter()
        subtitle_samples = []
        while time.perf_counter() - began < 4.0:
            subtitle_samples.append((round((time.perf_counter() - began) * 1000), subtitle_pixels()))
            QTest.qWait(40)
        visible = [ms for ms, count in subtitle_samples if count >= max(150, before_jump // 3)]
        timeline = page.timeline
        lanes = timeline._video_track_rects()
        entry['timeline_minimum'] = dict(
            sizes=page.workspace_splitter.sizes(), timeline_height=timeline.height(),
            viewport=timeline._track_viewport().getRect(),
            video_top=min(rect.top() for rect in lanes.values()) if lanes else None,
            scroll_maximum=timeline.vertical_scrollbar.maximum(),
            scroll_visible=timeline.vertical_scrollbar.isVisible(),
            subtitle_before=before_jump, subtitle_first_visible_ms=visible[0] if visible else None,
            subtitle_samples=subtitle_samples[::5])
        _capture(window, output / f'window-{width}x{height}-timeline-minimum.png')
        page.workspace_splitter.setSizes(sizes_now)
        QTest.qWait(300)
        result['sizes'].append(entry)
        receipt()

        label = f'{width}x{height}'
        if expect_fix:
            for row in entry['drags']:
                name = f"{label}: {row['splitter']}[{row['index']}] {row['requested']:+d}"
                check(f'{name} moves within its legal layout range', abs(row['achieved']) > 30,
                      dict(achieved=row['achieved']))
                if row['splitter'] != page.workspace_splitter.objectName():
                    check(f'{name} follows the pointer while dragging', row['live_steps'] >= 8, row['live_steps'])
                check(f'{name} no stale native geometry during movement', row['mismatched_now']==0, row['mismatched_now'])
                check(f'{name} video matches the surface within 100 ms of release',
                      row['release_lag_ms'] is not None and row['release_lag_ms'] <= 100, row['release_lag_ms'])
    if os.environ.get('TWOBYTEASR_DRAG_AUX')=='1':
        from PySide6.QtWidgets import QLabel
        from PIL import Image
        page.video.set_paused(True)
        marker=QLabel('工作区弹窗层叠检查')
        marker.setStyleSheet('background:#d23849;color:white;font-size:24px;')
        window._modal_host.show_content(marker,title='层叠检查',size=(640,360))
        QTest.qWait(200)
        image_path=output/'modal-over-video.png';_capture(window,image_path)
        point=marker.mapTo(window,QPoint(20,20));dpr=window.devicePixelRatioF()
        pixel=Image.open(image_path).convert('RGB').getpixel((round(point.x()*dpr),round(point.y()*dpr)))
        check('modal content covers video surface',pixel[0]>150 and pixel[1]<110 and pixel[2]<120,pixel)
        window._modal_host.hide_content();QTest.qWait(200)
        drop=window.drop_overlay;prior_style=drop.target.styleSheet()
        drop.target.setStyleSheet('background:#d23849;')
        window._set_drop_active(True)
        wait(lambda:drop.opacity.opacity()>=.999,'drop animation')
        QTest.qWait(100)
        result['drop_state']={'visible':drop.isVisible(),'requested':drop._requested_visible,'opacity':drop.opacity.opacity(),'geometry':drop.geometry().getRect()}
        image_path=output/'drop-over-video.png';_capture(window,image_path)
        point=drop.target.mapTo(window,QPoint(25,25))
        pixel=Image.open(image_path).convert('RGB').getpixel((round(point.x()*dpr),round(point.y()*dpr)))
        check('file drop card covers video surface',pixel[0]>150 and pixel[1]<110 and pixel[2]<120,pixel)
        window._set_drop_active(False);QTest.qWait(200);drop.target.setStyleSheet(prior_style)
        if page.project.cues:
            cue=page.project.cues[0];old=cue.text
            page._seek(.9);page.select_cue(cue.id);QTest.qWait(200)
            page._begin_canvas_inline_edit();QTest.qWait(150)
            editor=getattr(page,'_canvas_editor',None)
            check('inline editor remains visible',editor is not None and editor.isVisible())
            if editor is not None:
                editor.setFocus();QTest.keyClicks(editor,'XYZ');QTest.qWait(100)
                old_card_style=page.subtitle_edit_card.styleSheet()
                page.subtitle_edit_card.setStyleSheet('QFrame#subtitleEditCard{background:#d23849;}')
                QTest.qWait(100)
                _capture(window,output/'inline-over-video.png')
                point=page.subtitle_edit_card.mapTo(window,QPoint(8,8))
                pixel=Image.open(output/'inline-over-video.png').convert('RGB').getpixel((round(point.x()*dpr),round(point.y()*dpr)))
                check('inline editor card covers video',pixel[0]>150 and pixel[1]<110 and pixel[2]<120,pixel)
                page.subtitle_edit_card.setStyleSheet(old_card_style)
                check('inline editor accepts input','XYZ' in editor.toPlainText())
                page._cancel_canvas_inline_edit();check('cancel preserves caption',cue.text==old)
        _capture(window,output/'after-aux.png')
        _native_rects(page.video)
        check('video native hosts are stable',initial_host==int(page.video.winId()) and initial_player==_native_rects.mpv_hwnd)
        page.undo_stack.setClean()
        window._return_to_settings();QTest.qWait(200)
        import ctypes
        from ctypes import wintypes as W
        check('home hides native video',not ctypes.windll.user32.IsWindowVisible(W.HWND(initial_host)))
        _capture(window,output/'home-after-close.png')
        window.open_studio_project(str(path),mode='edit',source='workspace_drag_reopen')
        wait(lambda:page._readiness.ready and page.video.controller is not None,'reopen')
        QTest.qWait(150)
        canvas_rect,player_rect=_native_rects(page.video)
        check('reopen restores embedded geometry',canvas_rect==player_rect and player_rect is not None)
        page.undo_stack.setClean()

    result['passed'] = all(c['passed'] for c in result['checks']) if expect_fix else True
    receipt()
    return 0 if result['passed'] else 1
