"""Real-window playback smoothness at caption starts (2026-10-22 user report).

The user, on a 24-minute bilingual Japanese episode: playback stutters, and
"every time it reaches the first frame of a caption it hitches, then goes on";
opening 说话人管理 takes seconds. This scenario measures both on a copy of a
real project:

* steady playback segments (1x unless given; volume 0). An 8 ms precise GUI timer records
  the media clock; a gap between ticks is time the GUI thread could not run.
  mpv's own counters (dropped / delayed / mistimed frames) are read on every
  tick, so a video stall is told apart from a GUI stall.
* every caption frame posted to the video overlay, with the GUI time spent in
  ``CaptionScene.accept`` and ``_present_caption_scene``.
* a sampling thread keeps the GUI thread's Python stack every 4 ms; the stacks
  inside each tick gap say what the GUI thread was doing.
* the speaker manager is opened (from a timer: its exec() is not Qt-modal) and
  timed until the dialog is visible, then closed.

For every caption start inside a played span: the largest GUI gap and the mpv
drops from 150 ms before to 400 ms after it, against the same numbers away
from caption starts.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from collections import Counter


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..rendering.caption_scene import CaptionScene
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], identity=load_build_identity().to_dict(), passed=False, segments=[])
    page = window.studio_page
    ticks, posts, presents, stacks = [], [], [], []
    phase = {'name': ''}
    main_ident = threading.get_ident()
    counters = ('frame-drop-count', 'vo-delayed-frame-count', 'mistimed-frame-count', 'decoder-frame-drop-count')

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def media_ms():
        return float(page.video.playback_position_snapshot().presentation_media_ms)

    original_accept = CaptionScene.accept

    def accept(self, token, pixels, trace):
        began = time.perf_counter()
        before = self.published
        original_accept(self, token, pixels, trace)
        if phase['name'] and pixels is not None and self.published is pixels and self.published is not before:
            posts.append(dict(phase=phase['name'], wall=began, cost_ms=(time.perf_counter() - began) * 1000,
                              media_ms=media_ms(), cues=list(token[4]), cache_hit=bool(trace.get('cache_hit')),
                              render_ms=trace.get('duration_ms')))
    CaptionScene.accept = accept
    original_present = page._present_caption_scene

    def present_caption_scene(*args, **kwargs):
        began = time.perf_counter()
        try:
            return original_present(*args, **kwargs)
        finally:
            if phase['name']:
                presents.append((began, (time.perf_counter() - began) * 1000))
    page._present_caption_scene = present_caption_scene

    # Which calls throw away the timeline's cached static picture, and what
    # each full repaint costs.
    invalidations, full_paints = Counter(), []
    timeline = page.timeline
    original_update = timeline.update
    original_contents = timeline._paint_timeline_contents

    def update(*args):
        if phase['name']:
            frame, chain = sys._getframe(1), []
            while frame is not None and len(chain) < 5:
                chain.append(f"{frame.f_code.co_filename.replace(chr(92), '/').rsplit('/', 1)[-1]}:{frame.f_lineno}:{frame.f_code.co_name}")
                frame = frame.f_back
            invalidations[' < '.join(chain)] += 1
        return original_update(*args)
    timeline.update = update

    import cProfile
    profiler = cProfile.Profile() if spec.get('profile_paints') else None

    def paint_contents(painter, event, *args, **kwargs):
        began = time.perf_counter()
        profiling = profiler is not None and phase['name'] and len(full_paints) % int(spec['profile_paints']) == 0
        if profiling:
            profiler.enable()
        try:
            return original_contents(painter, event, *args, **kwargs)
        finally:
            if profiling:
                profiler.disable()
            if phase['name'] and not kwargs.get('timing_only'):
                full_paints.append((began, (time.perf_counter() - began) * 1000))
    timeline._paint_timeline_contents = paint_contents

    stop = threading.Event()

    def sample_stacks():
        # A Python stack of the GUI thread every 4 ms (the GIL is needed to read
        # it, so a GUI thread inside Python delays this sample, not the reverse).
        while not stop.wait(0.004):
            if not phase['name']:
                continue
            frame = sys._current_frames().get(main_ident)
            chain = []
            while frame is not None and len(chain) < 14:
                code = frame.f_code
                chain.append(f"{code.co_filename.replace(chr(92), '/').rsplit('/', 1)[-1]}:{frame.f_lineno}:{code.co_name}")
                frame = frame.f_back
            stacks.append((time.perf_counter(), tuple(chain)))
    sampler_thread = threading.Thread(target=sample_stacks, name='audit-stack-sampler', daemon=True)

    sampler = QTimer(window)
    sampler.setTimerType(Qt.PreciseTimer)
    sampler.setInterval(8)

    def tick():
        if not phase['name'] or page.project is None:
            return
        controller = page.video.controller
        observed = getattr(controller, 'observed_property', None)
        values = [observed(name, None) if callable(observed) else None for name in counters]
        ticks.append((phase['name'], time.perf_counter(), media_ms(), bool(page.video._paused),
                      observed('time-pos', None) if callable(observed) else None, values))
    sampler.timeout.connect(tick)

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def speaker_manager():
        from ..studio.studio_speaker_manager import SpeakerManagerDialog
        shown = {}
        original_show = SpeakerManagerDialog.showEvent

        def show_event(dialog, event):
            shown.setdefault('at', time.perf_counter())
            shown['dialog'] = dialog
            return original_show(dialog, event)
        SpeakerManagerDialog.showEvent = show_event
        began = time.perf_counter()
        if spec.get('profile_speaker'):
            speaker_profile.enable()
        QTimer.singleShot(0, page._open_speaker_manager)
        return began, shown, original_show

    import cProfile as _cprofile
    speaker_profile = _cprofile.Profile()

    def steps():
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='playback_hitch_audit')
        yield ready
        # Waveform and filmstrip caches of a fresh profile build in the
        # background first; the user's profile already has them.
        yield float(spec.get('settle_s', 2.0))
        if not page.video._paused:
            page._toggle_playback()
            yield .3
        page.volume_slider.setValue(0)
        sampler_thread.start()
        sampler.start()
        for index, (start_ms, seconds, *rest) in enumerate(spec['segments']):
            rate = float(rest[0]) if rest else 1.0
            name = f'play-{index}-{rate:g}x'
            page._seek(start_ms / 1000.0)
            page._set_speed(rate)
            yield 1.5
            phase['name'] = name
            began = media_ms()
            page._toggle_playback()
            yield float(seconds)
            if not page.video._paused:
                page._toggle_playback()
            ended = media_ms()
            phase['name'] = ''
            yield .6
            result['segments'].append(dict(name=name, media_from=began, media_to=ended, wall_s=seconds, rate=rate))
        # 2026-10-22 (user: jumping while playing still hitches): jumps during
        # 1x playback; each one's seek hold (picture frozen until the new audio
        # is ready) is timed from the canvas.
        holds = result.setdefault('seek_holds', [])
        original_end = page.video._end_seek_hold

        def end_hold(*args, **kwargs):
            if page.video._seek_hold_active:
                holds.append(round((time.monotonic() - page.video._seek_hold_started) * 1000, 1))
            return original_end(*args, **kwargs)
        page.video._end_seek_hold = end_hold
        for index, (start_ms, count, step_ms, interval_s) in enumerate(spec.get('seeks', ())):
            name = f'seek-{index}'
            page._set_speed(1.0)
            page._seek(start_ms / 1000.0)
            yield 1.5
            phase['name'] = name
            began = media_ms()
            page._toggle_playback()
            yield 1.5
            for _ in range(int(count)):
                page._seek((media_ms() + step_ms) / 1000.0)
                yield float(interval_s)
            if not page.video._paused:
                page._toggle_playback()
            phase['name'] = ''
            yield .6
            result['segments'].append(dict(name=name, media_from=began, media_to=media_ms(), wall_s=None, rate=1.0,
                                           seeks=int(count)))
        page.video._end_seek_hold = original_end
        page._set_speed(1.0)
        sampler.stop()
        stop.set()
        for attempt in range(int(spec.get('speaker_manager_opens', 2))):
            yield 1.0
            began, shown, original_show = speaker_manager()
            until = time.monotonic() + 30
            yield lambda: 'dialog' in shown or time.monotonic() > until
            visible_ms = (shown['at'] - began) * 1000 if 'at' in shown else None
            yield .8
            speaker_profile.disable()
            if attempt == 0:
                _capture(window, output / 'speaker-manager.png')
            dialog = shown.get('dialog')
            if dialog is not None:
                dialog.reject()
            from ..studio.studio_speaker_manager import SpeakerManagerDialog
            SpeakerManagerDialog.showEvent = original_show
            result.setdefault('speaker_manager_ms', []).append(visible_ms)
        analyse()

    def analyse():
        boundaries = sorted({c.start_ms for c in page.project.cues})
        rows = []
        for segment in result['segments']:
            span = [t for t in ticks if t[0] == segment['name'] and not t[3]]
            if len(span) < 2:
                continue
            lo, hi = span[0][2], span[-1][2]
            inside = [b for b in boundaries if lo + 100 < b < hi - 300]
            gaps = []
            for previous, current in zip(span, span[1:]):
                gap = (current[1] - previous[1]) * 1000
                drops = [((b or 0) - (a or 0)) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else 0
                         for a, b in zip(previous[5], current[5])]
                media = current[2]
                near = next((b for b in inside if b - 150 <= media <= b + 400), None)
                gaps.append(dict(wall=current[1], gap_ms=gap, media_ms=media, boundary=near, drops=drops))
            near_rows = [g for g in gaps if g['boundary'] is not None]
            far_rows = [g for g in gaps if g['boundary'] is None]

            def summary(items):
                values = sorted(g['gap_ms'] for g in items)
                q = lambda f: round(values[min(len(values) - 1, int(f * (len(values) - 1)))], 1) if values else None
                return dict(ticks=len(items), p50=q(.5), p95=q(.95), max=q(1.0),
                            over_33ms=sum(1 for v in values if v > 33), over_100ms=sum(1 for v in values if v > 100),
                            mpv_dropped=sum(g['drops'][0] for g in items), mpv_delayed=sum(g['drops'][1] for g in items),
                            mpv_mistimed=sum(g['drops'][2] for g in items), decoder_dropped=sum(g['drops'][3] for g in items))
            per_boundary = []
            for b in inside:
                items = [g for g in gaps if g['boundary'] == b]
                if items:
                    per_boundary.append(dict(boundary_ms=b, max_gap_ms=round(max(g['gap_ms'] for g in items), 1),
                                             mpv_dropped=sum(g['drops'][0] for g in items),
                                             mpv_delayed=sum(g['drops'][1] for g in items)))
            media_rate = (hi - lo) / max(1.0, (span[-1][1] - span[0][1]) * 1000)
            rows.append(dict(segment=segment['name'], media_from=lo, media_to=hi, media_rate=round(media_rate, 3),
                             boundaries=len(inside), near=summary(near_rows), far=summary(far_rows),
                             per_boundary=per_boundary))
            # What the GUI thread did inside the long gaps.
            long_gaps = [g for g in gaps if g['gap_ms'] > 33]
            frames = Counter()
            tops = Counter()
            for g in long_gaps:
                begin = g['wall'] - g['gap_ms'] / 1000
                seen = set()
                for at, chain in stacks:
                    if begin <= at <= g['wall'] and chain:
                        tops[chain[:6]] += 1
                        for item in chain:
                            if item not in seen:
                                frames[item] += 1
                                seen.add(item)
            rows[-1]['long_gap_frames'] = frames.most_common(40)
            rows[-1]['long_gap_stacks'] = [(n, list(chain)) for chain, n in tops.most_common(25)]
        result['playback'] = rows
        cost = sorted(p['cost_ms'] for p in posts)
        result['posts'] = dict(count=len(posts), cache_hits=sum(1 for p in posts if p['cache_hit']),
                               accept_p50_ms=round(cost[len(cost) // 2], 2) if cost else None,
                               accept_max_ms=round(cost[-1], 2) if cost else None)
        pres = sorted(ms for _, ms in presents)
        costs = sorted(ms for _, ms in full_paints)
        result['timeline'] = dict(full_repaints=len(costs), p50_ms=round(costs[len(costs) // 2], 1) if costs else None,
                                  max_ms=round(costs[-1], 1) if costs else None, total_ms=round(sum(costs)),
                                  invalidated_by=invalidations.most_common(25))
        result['present'] = dict(count=len(pres), p50_ms=round(pres[len(pres) // 2], 3) if pres else None,
                                 p99_ms=round(pres[int(len(pres) * .99)], 2) if pres else None,
                                 max_ms=round(pres[-1], 2) if pres else None)
        check('played every segment', len(rows) == len(spec['segments']) + len(spec.get('seeks', ())), [r['segment'] for r in rows])
        check('speaker manager opened', all(v is not None for v in result.get(
            'speaker_manager_ms', [None] if int(spec.get('speaker_manager_opens', 2)) else [])),
              result.get('speaker_manager_ms'))
        result['passed'] = all(c['passed'] for c in result['checks'])
        (output / 'ticks.json').write_text(json.dumps(ticks), 'utf-8')
        (output / 'posts.json').write_text(json.dumps(posts, ensure_ascii=False), 'utf-8')
        (output / 'full_paints.json').write_text(json.dumps(full_paints), 'utf-8')
        if profiler is not None:
            profiler.dump_stats(str(output / 'paint.prof'))
        if spec.get('profile_speaker'):
            speaker_profile.dump_stats(str(output / 'speaker.prof'))
        (output / 'stacks.json').write_text(json.dumps([(t, list(c)) for t, c in stacks]), 'utf-8')

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop()
        sampler.stop()
        stop.set()
        save()
        page.session.undo_stack.setClean()
        window.close()
        QTimer.singleShot(500, QApplication.instance().quit)

    def step():
        if state.get('ticking'):
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
                state.update(wait=value, deadline=time.monotonic() + 180)
            else:
                state['until'] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            result['error'] = traceback.format_exc()
            try:
                _capture(window, output / 'failure.png')
            except Exception:
                pass
            finish()
        finally:
            state['ticking'] = False

    def shutdown():
        result['gui_shutdown'] = True
        save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(step)
    timer.start()
