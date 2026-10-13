"""Opt-in real-window check of word-level razor splits (2026-10-10).

Runs inside the normal desktop entry (source or frozen EXE) on an owned copy of
a project: real QTest mouse/keyboard events on the Studio timeline, window
captures of the hover preview, proof that the waveform pixels are untouched,
the committed split against the preview, undo/redo, save/reopen, a ripple and
a text edit. Results go to ``result.json``; nothing outside ``output`` is
written.
"""
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .cue_word_alignment import cue_words
    from .studio_caption_timeline import KEY
    from .studio_project import load_project
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], samples=[], identity=load_build_identity().to_dict(), passed=False)
    page = window.studio_page
    log = (output / 'operations.jsonl').open('w', encoding='utf-8')

    def event(kind, **values):
        log.write(json.dumps(dict(t=time.monotonic(), kind=kind, **values), ensure_ascii=False, default=str) + '\n')
        log.flush()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        event('check', **result['checks'][-1])

    def capture(name):
        _capture(window, output / (name + '.png'))
        event('capture', name=name)

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def target(text):
        return next(c for c in page.project.cues if c.text == text)

    def track_point(t, cue, ms):
        rect = t._track_layout()[0][cue.speaker_id]
        return QPoint(round(t._time_to_x(ms)), round(rect.center().y()))

    timings = dict(move=[], paint=[])

    def instrument(t):
        """Time the timeline's own move handler and paints (this run only)."""
        cls = type(t)
        move, paint = cls.mouseMoveEvent, cls.paintEvent

        def timed_move(self, event):
            started = time.perf_counter(); move(self, event)
            if self is t:
                timings['move'].append((time.perf_counter() - started) * 1000)

        def timed_paint(self, event):
            started = time.perf_counter(); paint(self, event)
            if self is t:
                timings['paint'].append((time.perf_counter() - started) * 1000)
        cls.mouseMoveEvent, cls.paintEvent = timed_move, timed_paint

    def move_pointer(t, point):
        """A platform-level move (window system interface), as from a mouse."""
        top = t.window()
        QTest.mouseMove(top.windowHandle(), t.mapTo(top, point))

    def press_pointer(t, point, release=False):
        top = t.window()
        (QTest.mouseRelease if release else QTest.mousePress)(
            top.windowHandle(), Qt.LeftButton, Qt.NoModifier, t.mapTo(top, point))

    def text_extent(t, cue):
        """Horizontal extent of the bright caption text inside a cue block."""
        from .timeline_razor import _block_rect
        block = _block_rect(t, cue)
        image = t.grab(block.adjusted(6, 4, -6, -24).toAlignedRect()).toImage()
        xs = [x for x in range(image.width()) for y in range(0, image.height(), 2)
              if min(image.pixelColor(x, y).red(), image.pixelColor(x, y).green(),
                     image.pixelColor(x, y).blue()) > 200]
        return (min(xs), max(xs)) if xs else None

    def hover(t, cue, ms, holder):
        """Move the real cursor; wait until the timeline has the move."""
        point = track_point(t, cue, ms)
        move_pointer(t, point)
        want = t._x_to_time(point.x())
        yield lambda: (t._razor_hover or t._razor_drag or {}).get('split_ms') == want
        QApplication.processEvents()
        resolution = t._razor_resolution()
        row = dict(pointer_ms=want, split_ms=resolution.split_ms if resolution else None,
                   snap=resolution.snap if resolution else None)
        if resolution is not None:
            res = resolution.result
            row.update(result=type(res).__name__, left=getattr(res, 'left_text', ''),
                       right=getattr(res, 'right_text', ''), source=res.timing_source,
                       reason=getattr(res, 'reason', getattr(res, 'timing_reason', '')),
                       straddled=getattr(getattr(res, 'straddled', None), 'text', None),
                       right_word_start_ms=getattr(res, 'right_word_start_ms', None))
        result['samples'].append(row)
        event('hover', **row)
        holder[:] = [resolution]

    def waveform_rect(t):
        from PySide6.QtCore import QRect
        rect = next(iter(t._audio_track_rects().values()))
        return QRect(t.TRACK_HEADER_WIDTH, round(rect.top()) + 2,
                     t._content_right() - t.TRACK_HEADER_WIDTH - 2, round(rect.height()) - 4)

    def steps():
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='razor_split_audit')
        yield ready
        yield 1.0
        t = page.timeline
        yield lambda: t.waveform_state == 'READY'
        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.LeftButton)
            yield .3
        project = page.project
        receipts = project.studio_state.get(KEY, {}).get('instances', {})
        measured = [c.id for c in project.cues if cue_words(project, c)[0]]
        recovered = [c.id for c in project.cues if receipts.get(c.id, {}).get('word_recovery')]
        check('opened project has measured words for every recoverable caption',
              len(measured) >= spec['min_measured'], dict(cues=len(project.cues), measured=len(measured),
                                                          recovered=len(recovered)))
        cue = target(spec['text'])
        words, reason = cue_words(project, cue)
        result['target_words'] = [dict(text=cue.text[w.char_start:w.char_end], start_ms=w.start_ms,
                                       end_ms=w.end_ms, ref=w.evidence_ref) for w in words]
        check('target sentence has FireRed word times', reason == 'exact_token_text' and len(words) == len(cue.text),
              dict(reason=reason, words=len(words)))
        undo_before = page.session.undo_stack.count()
        clean_before = page.session.undo_stack.isClean()
        QTest.mouseClick(page.razor_tool_button, Qt.LeftButton)
        yield .2
        check('razor tool selected by its toolbar button', t.tool_mode == 'razor')
        t.set_visible_window(cue.start_ms - 600, 5200)
        yield .4
        # Baseline pixels of the waveform lane without any razor preview.
        move_pointer(t, QPoint(t.TRACK_HEADER_WIDTH + 5, 5))
        yield .2
        lane = waveform_rect(t)
        clean = t.grab(lane).toImage()
        # Sweep the pointer across the sentence: preview follows every move.
        sweep = list(range(cue.start_ms + 60, cue.end_ms - 40, 45))
        frames = []
        got = []
        instrument(t)
        for index, ms in enumerate(sweep):
            yield from hover(t, cue, ms, got)
            if index % 4 == 0:
                name = f'sweep-{len(frames):02d}'
                t.grab().save(str(output / (name + '.png')))
                frames.append(name)
            yield 0.02
        result['frames'] = frames
        text_changes = [(s['split_ms'], s['left']) for s in result['samples'] if s.get('result') == 'SplitPreview']
        check('every hover sample keeps all characters once', all(
            s['left'] + s['right'] == cue.text for s in result['samples'] if s.get('result') == 'SplitPreview'))
        moves, paints = sorted(timings['move']), sorted(timings['paint'])
        median = lambda values: values[len(values) // 2] if values else None
        result['latency_ms'] = dict(move_median=median(moves), move_p95=moves[int(len(moves) * .95)] if moves else None,
                                    paint_median=median(paints), paint_p95=paints[int(len(paints) * .95)] if paints else None,
                                    moves=len(moves), paints=len(paints))
        check('hover follows the pointer (median move handler + paint under 16ms)',
              moves and paints and median(moves) + median(paints) < 16, result['latency_ms'])
        # Text boundary only moves at measured onsets.
        onsets = {w.start_ms for w in words}
        jumps = [(a, b) for (a, la), (b, lb) in zip(text_changes, text_changes[1:]) if la != lb]
        check('text boundary changes only across a word onset', all(
            any(a <= onset < b for onset in onsets) for a, b in jumps), jumps)
        for ms in spec['positions']:
            move_pointer(t, QPoint(t.TRACK_HEADER_WIDTH + 5, 5))
            yield lambda: t._razor_hover is None
            yield .3
            clean = t.grab(lane).toImage()
            yield from hover(t, cue, ms, got)
            resolution = got[0]
            yield .15
            capture(f'hover-{ms}')
            hovered = t.grab(lane).toImage()
            # Grabs are device pixels (the window may run at 175%).
            scale = hovered.width() / max(1, lane.width())
            cut_x = (t._time_to_x(resolution.split_ms) - lane.left()) * scale
            changed = [(x, y) for x in range(hovered.width()) for y in range(0, hovered.height(), 2)
                       if abs(x - cut_x) > 3 * scale and hovered.pixel(x, y) != clean.pixel(x, y)]
            line = sum(hovered.pixel(x, y) != clean.pixel(x, y) for x in range(hovered.width())
                       for y in range(0, hovered.height(), 2) if abs(x - cut_x) <= 3 * scale)
            box = (min(x for x, _ in changed), min(y for _, y in changed), max(x for x, _ in changed),
                   max(y for _, y in changed)) if changed else None
            if changed:
                hovered.save(str(output / f'waveform-hover-{ms}.png')); clean.save(str(output / f'waveform-clean-{ms}.png'))
            check(f'waveform untouched except the {resolution.split_ms}ms cut line', not changed,
                  dict(changed_pixels=len(changed), cut_line_pixels=line, cut_x_device=round(cut_x, 1),
                       scale=round(scale, 3), box=box, lane=lane.getRect()))
        extents = []
        for ms in (5300, 6448, 7150):
            yield from hover(t, cue, ms, got)
            yield .1
            extents.append(text_extent(t, cue))
        check('razor text stays centred while the boundary moves (extent within 4px)', all(extents) and
              max(e[0] for e in extents) - min(e[0] for e in extents) <= 4 * window.devicePixelRatioF()
              and max(e[1] for e in extents) - min(e[1] for e in extents) <= 4 * window.devicePixelRatioF(),
              extents)
        check('hover never edits the project', page.session.undo_stack.count() == undo_before
              and page.session.undo_stack.isClean() == clean_before)
        # Click commits exactly the hover preview.
        click_ms = spec['click_ms']
        yield from hover(t, cue, click_ms, got)
        shown = got[0]
        yield .1
        QTest.mouseClick(t, Qt.LeftButton, Qt.NoModifier, track_point(t, cue, click_ms))
        yield .5
        left, right = target(shown.result.left_text), target(shown.result.right_text)
        check('click split equals the hover preview', (left.end_ms, right.start_ms) == (shown.split_ms, shown.split_ms),
              dict(left=left.text, right=right.text, split=shown.split_ms))
        right_words, right_reason = cue_words(page.project, right)
        check('right part keeps its FireRed word times', right_reason == 'exact_token_text'
              and right_words[0].start_ms == shown.result.right_word_start_ms,
              [(w.text, w.start_ms) for w in right_words])
        capture('after-click-split')
        yield from hover(t, right, spec['second_ms'], got)
        second = got[0]
        yield .1
        QTest.mouseClick(t, Qt.LeftButton, Qt.NoModifier, track_point(t, right, spec['second_ms']))
        yield .5
        after = sorted((c.start_ms, c.text) for c in page.project.cues if c.start_ms >= cue.start_ms - 1
                       and c.end_ms <= cue.end_ms + 1)
        check('second split matches its preview', [x[1] for x in after] == [
            shown.result.left_text, second.result.left_text, second.result.right_text], after)
        # Esc cancels a pressed cut.
        point = track_point(t, left, (left.start_ms + left.end_ms) // 2)
        count = page.session.undo_stack.count()
        QTest.mousePress(t, Qt.LeftButton, Qt.NoModifier, point)
        QTest.keyClick(t, Qt.Key_Escape)
        QTest.mouseRelease(t, Qt.LeftButton, Qt.NoModifier, point)
        yield .3
        check('Esc cancels the pressed cut', page.session.undo_stack.count() == count and t._razor_preview() is None)
        # Undo / redo through the real shortcuts.
        t.setFocus()
        QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier); yield .4
        QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier); yield .4
        restored = target(spec['text'])
        check('two undos restore the sentence and its words', cue_words(page.project, restored)[0][0].start_ms
              == words[0].start_ms, restored.text)
        QTest.keyClick(t, Qt.Key_Y, Qt.ControlModifier); yield .4
        QTest.keyClick(t, Qt.Key_Y, Qt.ControlModifier); yield .4
        check('two redos restore both splits', [c.text for c in sorted(page.project.cues, key=lambda c: c.start_ms)
                                                if cue.start_ms - 1 <= c.start_ms and c.end_ms <= cue.end_ms + 1]
              == [x[1] for x in after])
        QTest.keyClick(t, Qt.Key_S, Qt.ControlModifier)
        yield lambda: page.session.undo_stack.isClean()
        reopened = load_project(spec['project'])
        by_text = {c.text: c for c in reopened.cues}
        saved_words = cue_words(reopened, by_text[second.result.right_text])[0]
        check('save + reopen keeps texts and word times', [w.start_ms for w in saved_words]
              == [w.start_ms for w in cue_words(page.project, target(second.result.right_text))[0]],
              [w.start_ms for w in saved_words])
        # Ripple: delete a range before the sentence from video, audio and
        # captions with the production ripple command (as pause compression).
        from .studio_clip_edit import ripple_ranges_command, video_track_locked
        for track in page.project.video_tracks:
            if video_track_locked(page.project, track):
                page._video_track_action(track.id, 'locked')  # the V1 header lock button
                yield .3
        check('video track unlocked for the ripple', not any(
            video_track_locked(page.project, track) for track in page.project.video_tracks))
        page.session.undo_stack.push(ripple_ranges_command(page.project, [tuple(spec['ripple'])], page=page))
        yield .8
        delta = spec['ripple'][1] - spec['ripple'][0]
        moved = target(shown.result.left_text)
        t.set_visible_window(moved.start_ms - 600, 5200)
        yield .3
        yield from hover(t, moved, spec['ripple_probe_ms'] - delta, got)
        res = got[0]
        yield .15
        capture('after-ripple-hover')
        check('after a ripple the preview uses the shifted word times',
              res.preview is not None and res.result.left_text == spec['ripple_expect_left'],
              dict(left=getattr(res.result, 'left_text', None), split=res.split_ms))
        # A manual text edit with a different length is realigned, not reused.
        edited = target(shown.result.left_text)
        page.cue_controller.set_text(edited.id, spec['edited_text'])
        yield .4
        yield from hover(t, target(spec['edited_text']), spec['edited_probe_ms'] - delta, got)
        res = got[0]
        yield .15
        capture('edited-text-hover')
        check('edited text realigns to heard tokens', res.preview is not None
              and res.result.timing_source == 'derived_term_source_span'
              and res.result.left_text == spec['edited_expect_left'],
              dict(left=getattr(res.result, 'left_text', None), source=getattr(res.result, 'timing_source', None)))
        page.cue_controller.set_text(edited.id, '这一句和录音完全无关的文字')
        yield .4
        yield from hover(t, target('这一句和录音完全无关的文字'), spec['edited_probe_ms'] - delta, got)
        res = got[0]
        yield .15
        capture('unrelated-text-hover')
        check('unrelated text shows the missing-alignment state', res.preview is not None
              and not res.result.measured, res.result.timing_source)
        # ---- merge tool: in-track preview instead of the card ----
        QTest.mouseClick(page.merge_tool_button, Qt.LeftButton)
        yield .2
        check('merge tool selected by its toolbar button', t.tool_mode == 'merge')
        first, second = target(spec['merge_first']), target(spec['merge_second'])
        t.set_visible_window(first.start_ms - 800, second.end_ms - first.start_ms + 1600)
        yield .3
        move_pointer(t, QPoint(t.TRACK_HEADER_WIDTH + 5, 5))
        yield .3
        clean = t.grab(lane).toImage()
        undo_count = page.session.undo_stack.count()
        anchor_point = track_point(t, first, (first.start_ms + first.end_ms) // 2)
        press_pointer(t, anchor_point)
        yield lambda: t._merge_preview_state() is not None
        check('press anchors the cue', t._merge_preview_state().kind == 'anchor'
              and t._merge_preview_state().anchor.id == first.id)
        for step in range(1, 7):
            move_pointer(t, anchor_point + QPoint(step * 30, 0))
            yield 0.03
        yield lambda: (t._merge_preview_state() or None) is not None and t._merge_preview_state().kind == 'drag'
        state = t._merge_preview_state()
        check('dragging right previews the merge with the next caption',
              state.other is not None and state.other.id == second.id and state.direction == 1,
              dict(kind=state.kind, other=getattr(state.other, 'text', None)))
        capture('merge-drag-preview')
        hovered = t.grab(lane).toImage()
        changed = sum(hovered.pixel(x, y) != clean.pixel(x, y)
                      for x in range(hovered.width()) for y in range(0, hovered.height(), 2))
        check('merge preview leaves the waveform untouched', changed == 0, dict(changed_pixels=changed))
        check('merge preview never edits the project', page.session.undo_stack.count() == undo_count)
        press_pointer(t, anchor_point + QPoint(180, 0), release=True)
        yield .5
        merged = next((c for c in page.project.cues if c.text == first.text + second.text), None)
        check('release merges exactly the previewed pair', merged is not None
              and (merged.start_ms, merged.end_ms) == (first.start_ms, second.end_ms)
              and page.session.undo_stack.count() == undo_count + 1,
              dict(text=getattr(merged, 'text', None)))
        capture('merge-after')
        t.setFocus()
        QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier)
        yield .4
        check('undo restores both captions', target(spec['merge_first']) is not None
              and target(spec['merge_second']) is not None)
        # Click-pair: anchor, hover the second caption, click it.
        first, second = target(spec['merge_first']), target(spec['merge_second'])
        anchor_point = track_point(t, first, (first.start_ms + first.end_ms) // 2)
        press_pointer(t, anchor_point); press_pointer(t, anchor_point, release=True)
        yield .2
        second_point = track_point(t, second, (second.start_ms + second.end_ms) // 2)
        move_pointer(t, second_point)
        yield lambda: (t._merge_preview_state() or None) is not None and t._merge_preview_state().kind == 'pair'
        capture('merge-pair-hover')
        check('hovering a second caption previews the click-to-merge result',
              t._merge_preview_state().other.id == second.id)
        index_before = page.session.undo_stack.index()
        QTest.keyClick(t, Qt.Key_Escape)
        yield .3
        check('Esc drops the merge anchor without editing', t._merge_preview_state() is None
              and page.session.undo_stack.index() == index_before,
              dict(state=repr(t._merge_preview_state()), index=page.session.undo_stack.index(), before=index_before))
        result['passed'] = all(x['passed'] for x in result['checks'])

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)
    timer.setInterval(30)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop(); save(); log.close()
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
                state.update(wait=value, deadline=time.monotonic() + 90)
            else:
                state['until'] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            result['error'] = traceback.format_exc()
            try:
                capture('failure')
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
