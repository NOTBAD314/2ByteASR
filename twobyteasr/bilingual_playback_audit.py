"""Real-window bilingual playback check (2026-10-12 night).

Plays a copy of a bilingual Japanese project at 1x/2x/4x, seeks to seeded
cue midpoints and captures given moments in each display mode. Evidence is
recorded at the two places that decide what the viewer sees:

* every caption frame actually posted to the video overlay (which captions
  it contains, the media time when it was posted, whether the previous frame
  was held while it was prepared);
* an 8 ms sampler of the media clock, the cues that should be visible at
  that time and the cues of the frame currently posted.

From these: frames missing a translation line, and for every cue start the
delay until a frame with that cue was posted (media and wall time), and how
long the previous cue's frame stayed up after its end.
"""
from __future__ import annotations

import json
import random
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .caption_scene import CaptionScene
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], identity=load_build_identity().to_dict(), passed=False, phases=[], seeks=[])
    page = window.studio_page
    log = (output / 'operations.jsonl').open('w', encoding='utf-8')
    posted, samples, traces = [], [], []
    phase = {'name': ''}

    def event(kind, **values):
        log.write(json.dumps(dict(t=time.monotonic(), kind=kind, **values), ensure_ascii=False, default=str) + '\n')
        log.flush()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        event('check', **result['checks'][-1])

    def media_ms():
        return float(page.video.playback_position_snapshot().presentation_media_ms)

    original_accept = CaptionScene.accept

    def accept(self, token, pixels, trace):
        before = self.published
        original_accept(self, token, pixels, trace)
        if pixels is not None and self.published is pixels and self.published is not before:
            posted.append(dict(phase=phase['name'], wall=time.perf_counter(), media_ms=media_ms(),
                               rate=float(page.video._playback_rate), paused=bool(page.video._paused),
                               cues=list(token[4]), drawn=[row['cue_id'] for row in trace.get('cue_pixels', [])],
                               cache_hit=bool(trace.get('cache_hit')), held_ms=trace.get('held_previous_ms'),
                               sample_ms=trace.get('sample_ms')))
    CaptionScene.accept = accept
    original_trace = page._studio_trace

    def studio_trace(name, **values):
        if name in ('CAPTION_SCENE_HELD', 'CAPTION_SCENE_RETIRED'):
            traces.append(dict(phase=phase['name'], wall=time.perf_counter(), media_ms=media_ms(), event=name,
                               **{k: v for k, v in values.items() if k in ('cue_ids', 'previous_cue_ids', 'reason', 'held_ms')}))
        return original_trace(name, **values)
    page._studio_trace = studio_trace

    sampler = QTimer(window)
    sampler.setTimerType(Qt.PreciseTimer)
    sampler.setInterval(8)

    def sample():
        if not phase['name'] or page.project is None:
            return
        scene = getattr(page, '_caption_scene', None)
        at = media_ms()
        expected = [c.id for c in page.session.runtime.cues_at(int(at))]
        shown = list(scene.token[4]) if scene is not None and scene.published is not None and scene.token else []
        samples.append((phase['name'], time.perf_counter(), at, expected, shown, bool(page.video._paused)))
    sampler.timeout.connect(sample)

    def translated_ids():
        from .bilingual_layout import translations_of
        return {k for k, v in translations_of(page.project.generation_metadata).items() if str(v or '').strip()}

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def steps():
        from .bilingual_layout import settings_from_state
        from .studio_bilingual import apply_display
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='bilingual_playback_audit')
        yield ready
        yield 1.5
        if not page.video._paused:
            page._toggle_playback()
            yield .3
        settings = settings_from_state(page.project.studio_state)
        result['display'] = dict(mode=settings.mode, order=settings.order, gap_ratio=settings.gap_ratio,
                                 layout=getattr(settings, 'layout', ''))
        if settings.mode != 'bilingual':
            apply_display(page, mode='bilingual')
            yield .5
        page.volume_slider.setValue(0)
        sampler.start()
        start_ms = int(spec.get('start_ms', 95000))
        for rate, media_seconds in spec.get('rates', [[1.0, 45], [2.0, 60], [4.0, 120]]):
            phase['name'] = f'play-{rate:g}x'
            page._seek(start_ms / 1000.0)
            yield 1.2
            page._set_speed(float(rate))
            yield .3
            began = media_ms()
            page._toggle_playback()
            wall = media_seconds / float(rate)
            yield wall
            if not page.video._paused:
                page._toggle_playback()
            yield .5
            result['phases'].append(dict(name=phase['name'], rate=rate, media_from=began, media_to=media_ms(),
                                         wall_s=wall))
        page._set_speed(1.0)
        # Seeded seeks to translated cue midpoints (paused).
        phase['name'] = 'seek'
        rng = random.Random(20261012)
        translated = translated_ids()
        pool = [c for c in page.project.cues if c.id in translated and c.end_ms - c.start_ms >= 300]
        for cue in rng.sample(pool, min(int(spec.get('seeks', 24)), len(pool))):
            middle = (cue.start_ms + cue.end_ms) // 2
            count = len(posted)
            page._seek(middle / 1000.0)
            until = time.monotonic() + 3.0
            yield lambda: len(posted) > count and cue.id in posted[-1]['cues'] or time.monotonic() > until
            frame = next((row for row in reversed(posted[count:]) if cue.id in row['cues']), None)
            result['seeks'].append(dict(cue=cue.id, at=middle, posted=frame is not None,
                                        drawn=frame['drawn'] if frame else None))
        phase['name'] = ''
        sampler.stop()
        # Captures in each display mode at the requested moments.
        for at in spec.get('capture_ms', [108979, 156216]):
            for mode, order in (('bilingual', 'translation_first'), ('original', None), ('translation', None)):
                apply_display(page, mode=mode, **({'order': order} if order else {}))
                yield .4
                page._seek(at / 1000.0)
                yield 1.2
                _capture(window, output / f'frame-{at}-{mode}.png')
                scene = getattr(page, '_caption_scene', None)
                if scene is not None and scene.published is not None:
                    # The exact LIVE raster posted to the video overlay (transparent background).
                    scene.published.image.save(str(output / f'overlay-{at}-{mode}.png'))
                event('capture', at=at, mode=mode, published=list(scene.token[4]) if scene and scene.token else None,
                      drawn=posted[-1]['drawn'] if posted else None)
        apply_display(page, mode=settings.mode, order=settings.order)
        yield .3
        analyse()

    def analyse():
        translated = translated_ids()
        frames = [row for row in posted if row['phase']]
        missing = [row for row in frames if any(cue in translated and cue + '#tr' not in row['drawn'] for cue in row['cues'])]
        result['frames'] = dict(total=len(frames), missing_translation=len(missing), examples=missing[:12])
        check('every posted frame has the translation of each translated caption', not missing,
              dict(total=len(frames), missing=len(missing)))
        seeks_ok = [s for s in result['seeks'] if s['posted'] and all(
            c + '#tr' in (s['drawn'] or []) for c in [s['cue']] if c in translated)]
        check('every seek shows the caption with its translation', len(seeks_ok) == len(result['seeks']),
              dict(ok=len(seeks_ok), total=len(result['seeks'])))
        by_id = {c.id: c for c in page.project.cues}
        handoffs = []
        for name in sorted({row['phase'] for row in frames if row['phase'].startswith('play')}):
            rows = [row for row in frames if row['phase'] == name and not row['paused']]
            span = [s for s in samples if s[0] == name and not s[5]]
            if not span:
                continue
            lo, hi = span[0][2], span[-1][2]
            starts = sorted({c.start_ms for c in page.project.cues if lo + 50 < c.start_ms < hi - 50})
            for boundary in starts:
                new = [c.id for c in page.project.cues if c.start_ms == boundary]
                first = next((row for row in rows if row['media_ms'] >= boundary - 400 and any(i in row['cues'] for i in new)), None)
                # What the viewer saw from the boundary until that frame: samples between.
                window_samples = [s for s in span if s[2] >= boundary and (first is None or s[1] <= first['wall'])]
                stale = sum(1 for s in window_samples if s[4] and not any(i in s[4] for i in new))
                blank = sum(1 for s in window_samples if not s[4])
                handoffs.append(dict(phase=name, boundary_ms=boundary, cues=new,
                                     delay_media_ms=None if first is None else round(first['media_ms'] - boundary, 1),
                                     held_ms=None if first is None else first['held_ms'],
                                     cache_hit=None if first is None else first['cache_hit'],
                                     stale_samples=stale, blank_samples=blank))
        result['handoffs'] = handoffs
        summary = {}
        for name in sorted({h['phase'] for h in handoffs}):
            rows = [h for h in handoffs if h['phase'] == name and h['delay_media_ms'] is not None]
            delays = sorted(h['delay_media_ms'] for h in rows)
            if not delays:
                continue
            q = lambda f: delays[min(len(delays) - 1, int(f * (len(delays) - 1)))]
            summary[name] = dict(boundaries=len([h for h in handoffs if h['phase'] == name]), observed=len(delays),
                                 median_ms=q(.5), p90_ms=q(.9), max_ms=delays[-1],
                                 held=sum(1 for h in rows if h['held_ms']),
                                 late_over_100ms=sum(1 for d in delays if d > 100),
                                 stale_handoffs=sum(1 for h in rows if h['stale_samples']),
                                 never_shown=len([h for h in handoffs if h['phase'] == name and h['delay_media_ms'] is None]))
        result['handoff_summary'] = summary
        result['passed'] = all(c['passed'] for c in result['checks'])
        (output / 'samples.json').write_text(json.dumps(samples), 'utf-8')
        (output / 'posted.json').write_text(json.dumps(posted, ensure_ascii=False), 'utf-8')
        (output / 'traces.json').write_text(json.dumps(traces, ensure_ascii=False), 'utf-8')

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop()
        sampler.stop()
        save()
        log.close()
        page.session.undo_stack.setClean()
        window.close()
        QTimer.singleShot(500, QApplication.instance().quit)

    def tick():
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
    timer.timeout.connect(tick)
    timer.start()
