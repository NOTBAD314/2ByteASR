"""Interaction freezes on a real project (2026-10-28 user report: 1-hour stream, 805 cues).

The user's log showed the GUI thread stopping for 0.6–1.35 s on a review-filter
click, Ctrl+S, entering the workbench and starting playback after a seek. This
opens a copy of their project in the real window, repeats those actions the way
the UI triggers them, and records for each: the synchronous call time, the
longest event-loop gap in the following settle window (5 ms heartbeat) and a
GUI-thread cProfile. Project: TWOBYTEASR_FREEZE_PROJECT; repeats:
TWOBYTEASR_FREEZE_REPEATS. Run through
scripts/verify_editor_diagnostics_headed.py --freeze-audit PROJECT.
"""
from __future__ import annotations

import cProfile
import io
import json
import os
import pstats
import shutil
import time
import traceback
from pathlib import Path

SETTLE_MS = 1500


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(Path(output), window=window)
        except Exception:
            (Path(output) / 'result.json').write_text(json.dumps(dict(passed=False, error=traceback.format_exc())), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            path = Path(output) / 'result.json'
            result = json.loads(path.read_text('utf8'))
            result['gui_shutdown'] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100, execute)


class Heartbeat:
    """Longest gap between 5 ms timer ticks: how long the event loop was blocked."""

    def __init__(self):
        from PySide6.QtCore import QTimer
        self.timer = QTimer()
        self.timer.setInterval(5)
        self.timer.timeout.connect(self._tick)
        self.last = None
        self.gaps = []

    def _tick(self):
        now = time.perf_counter()
        if self.last is not None:
            self.gaps.append((now - self.last) * 1000)
        self.last = now

    def begin(self):
        self.gaps, self.last = [], time.perf_counter()
        self.timer.start()

    def end(self):
        self.timer.stop()
        self._tick()
        gaps = sorted(self.gaps, reverse=True)
        return dict(max_gap_ms=round(gaps[0], 1) if gaps else None,
                    gaps_over_100ms=[round(g, 1) for g in gaps if g > 100][:8])


def stage_widget(window, widget):
    while widget is not None and widget.parentWidget() is not window.pages:
        widget = widget.parentWidget()
    return widget


def run(output, *, window):
    from PySide6.QtTest import QTest
    from ..projects import studio_project_controller
    from ..diagnostics.build_identity import load_build_identity

    source = os.environ['TWOBYTEASR_FREEZE_PROJECT']
    repeats = int(os.environ.get('TWOBYTEASR_FREEZE_REPEATS', '2'))
    page = window.studio_page
    window.resize(1440, 900)
    window.show()
    boxes = []
    studio_project_controller.studio_message_box = lambda *args, **kwargs: boxes.append([str(a) for a in args[1:]])
    result = dict(passed=False, pid=os.getpid(), identity=load_build_identity().to_dict(), actions=[], boxes=boxes)
    profiles = output / 'profiles'
    profiles.mkdir(exist_ok=True)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    QTest.qWait(1500)
    target = output / 'project.2byteproj'
    shutil.copyfile(source, target)
    window.open_studio_project(str(target), mode='edit', source='studio_recognition')
    readiness = page._readiness
    deadline = time.monotonic() + 120
    QTest.qWait(50)
    while readiness.active and time.monotonic() < deadline:
        QTest.qWait(20)
    result['open'] = dict(ready=bool(readiness.ready), error=(getattr(readiness, 'profile', {}) or {}).get('error'))
    save()
    if not readiness.ready:
        return 1
    page.video.set_paused(True)
    # The user's session ran an 8-minute recognition first; its process held
    # ~2.3 GB private (gc.collection_decision). Optional ballast of ordinary
    # GC-tracked objects reproduces a heap of that size.
    ballast_count = int(os.environ.get('TWOBYTEASR_FREEZE_BALLAST', '0'))
    window._freeze_audit_ballast = [{'i': index, 't': (index, 'x')} for index in range(ballast_count)]
    result['ballast_objects'] = ballast_count
    QTest.qWait(8000)  # background QC scan, waveform and caption warm-up settle
    heartbeat = Heartbeat()
    home = window.pages.widget(0)
    studio = stage_widget(window, page)
    duration = max(60.0, (page.project.media.duration_ms or 0) / 1000.0)

    def seek_play(fraction):
        page._seek(duration * fraction)
        QTest.qWait(400)
        page._toggle_playback()

    actions = [
        ('filter_priority', lambda: page.cue_filter_buttons['priority'].click()),
        ('filter_critical', lambda: page.cue_filter_buttons['critical'].click()),
        ('filter_all', lambda: page.cue_filter_buttons['all'].click()),
        ('save', page.save),
        ('seek_play', lambda: seek_play(0.37)),
        ('pause', page._toggle_playback),
        ('seek_play_2', lambda: seek_play(0.61)),
        ('shuttle_2x', lambda: page._shuttle(1)),
        ('pause_2', page._toggle_playback),
        ('to_home', lambda: window._switch_page(home)),
        ('to_studio', lambda: window._switch_page(studio)),
    ]
    # Contention: a background Python thread doing save-like work (pure-Python
    # JSON encoding) while the GUI handles the same actions.
    import sys
    import threading
    switch = os.environ.get('TWOBYTEASR_FREEZE_SWITCH')
    if switch:
        sys.setswitchinterval(float(switch))
    result['switch_interval_s'] = sys.getswitchinterval()
    sample = {'cues': [{'id': index, 'text': '字幕' * 12, 'words': [{'s': i, 'e': i + 1} for i in range(12)]}
                       for index in range(800)]}
    busy = {'stop': threading.Event(), 'rounds': 0}

    def background():
        while not busy['stop'].is_set():
            json.dumps(sample, ensure_ascii=False, indent=2, sort_keys=True)
            busy['rounds'] += 1

    def contended(action):
        def run_contended():
            busy['stop'].clear()
            busy['rounds'] = 0
            worker = threading.Thread(target=background, name='freeze-audit-busy', daemon=True)
            worker.start()
            busy['worker'] = worker
            action()
        return run_contended

    contended_actions = [(name + '_busy', contended(action)) for name, action in actions
                         if name in ('filter_priority', 'filter_all', 'seek_play', 'pause', 'to_home', 'to_studio')]
    for repeat in range(repeats):
        for name, action in actions + contended_actions:
            profiler = cProfile.Profile()
            heartbeat.begin()
            began = time.perf_counter()
            profiler.enable()
            error = None
            try:
                action()
            except Exception:
                error = traceback.format_exc()[-800:]
            call_ms = (time.perf_counter() - began) * 1000
            QTest.qWait(SETTLE_MS)
            profiler.disable()
            gaps = heartbeat.end()
            if busy.get('worker') is not None:
                busy['stop'].set()
                busy.pop('worker').join()
                gaps['background_rounds'] = busy['rounds']
            text = io.StringIO()
            stats = pstats.Stats(profiler, stream=text)
            stats.sort_stats('cumulative').print_stats(40)
            stats.sort_stats('tottime').print_stats(25)
            stem = f'{repeat}-{name}'
            (profiles / f'{stem}.txt').write_text(text.getvalue(), 'utf8')
            profiler.dump_stats(str(profiles / f'{stem}.prof'))
            result['actions'].append(dict(repeat=repeat, name=name, call_ms=round(call_ms, 1), error=error, **gaps))
            save()
            QTest.qWait(500)
        page.video.set_paused(True)
        QTest.qWait(3000)
    # The user's session was smooth until they visited the glossary proofread
    # page (14:12:28) and returned (14:13:59); every freeze came after. Repeat
    # that round trip and the same actions, recording the interpreter switch
    # interval the Studio is left with.
    result['switch_before_proofread_s'] = sys.getswitchinterval()
    try:
        window._show_glossary_proofread(page.project_path, page.project, studio=page)
        QTest.qWait(int(os.environ.get('TWOBYTEASR_FREEZE_PROOFREAD_MS', '6000')))
        result['switch_on_proofread_s'] = sys.getswitchinterval()
        window._switch_page(window._glossary_proofread_return)
        QTest.qWait(2000)
        result['switch_after_proofread_s'] = sys.getswitchinterval()
    except Exception:
        result['proofread_error'] = traceback.format_exc()[-1200:]
    save()
    after = [(name + '_after_proofread', action) for name, action in actions
             if name in ('filter_priority', 'filter_all', 'save', 'seek_play', 'pause', 'to_home', 'to_studio')]
    for name, action in after:
        heartbeat.begin()
        began = time.perf_counter()
        error = None
        try:
            action()
        except Exception:
            error = traceback.format_exc()[-800:]
        call_ms = (time.perf_counter() - began) * 1000
        QTest.qWait(SETTLE_MS)
        gaps = heartbeat.end()
        result['actions'].append(dict(repeat=0, name=name, call_ms=round(call_ms, 1), error=error,
                                      switch_interval_s=sys.getswitchinterval(), **gaps))
        save()
        QTest.qWait(500)
    from ..glossary import glossary_proofread
    trace = []
    for second in range(60):
        proofread = getattr(window, 'glossary_proofread_page', None)
        worker = getattr(proofread, '_worker', None)
        trace.append(dict(s=second, count=glossary_proofread._RESPONSIVE['count'],
                          switch=sys.getswitchinterval(),
                          worker_running=bool(worker is not None and worker.isRunning()),
                          stutter_threads=len(getattr(proofread, '_stutter_threads', ()) or ()),
                          threads=sorted(t.name for t in threading.enumerate() if t.name != 'MainThread')[:20]))
        if trace[-1]['count'] == 0 and second >= 3:
            break
        QTest.qWait(1000)
    result['proofread_check_trace'] = trace
    result['passed'] = all(row['error'] is None for row in result['actions']) and 'proofread_error' not in result
    save()
    return 0 if result['passed'] else 1
