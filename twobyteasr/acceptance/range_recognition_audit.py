"""Real-window check: 只重新识别这一段字幕 (2026-10-25).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=range-recognition`` (isolated
data; ``scripts/verify_range_recognition_headed.py``, source or frozen). The
runner makes a clip of three sentences read by a Windows voice
(``TWOBYTEASR_RANGE_RECOGNITION``: media, each sentence's span and words) and
links the local models it needs. In the real window this scenario:

1. imports the clip into an empty project and recognizes it whole;
2. turns the captions of the middle sentence into a wrong recognition, sets
   in/out with the I / O actions so the in point cuts a caption, right-clicks
   the timeline: the menu offers 只重新识别这一段字幕; the sheet names the
   stretch (widened to whole captions), how many captions it replaces, and
   hides translation and 仅本地识别; nothing was edited by hand, so 识别这一段
   starts at once;
3. while it runs the menu entry says why it is unavailable; afterwards only
   the stretch is replaced (captions outside keep id, time and text), the new
   captions say the middle sentence, carry word timing, and are one undo step:
   undo restores the old captions exactly, redo brings the new ones back;
4. edits a caption of the stretch by hand: the sheet asks first (确认替换);
   a caption edited while the run is going makes the finish ask again
   (替换这一段); undo brings both edits back;
5. without an out point the entry is disabled and says 先设好入点和出点;
6. saves, reopens, and the replaced captions are still there and valid.

Nothing contacts the network or a paid service.
"""
from __future__ import annotations

import glob
import json
import os
import time
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads(os.environ['TWOBYTEASR_RANGE_RECOGNITION'])
    result = dict(checks=[], metrics={}, errors=[], dialogs=[], passed=False, pid=os.getpid(),
                  executable=os.path.realpath(__import__('sys').executable))
    answers = {'replace_range': False}

    def save_result():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        save_result()
        return bool(ok)

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def wait_for(predicate, timeout=40.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            try:
                if predicate():
                    return True
            except Exception:  # noqa: BLE001 - keep polling
                pass
            time.sleep(0.05)
        return False

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def handle_boxes():
        for widget in app.topLevelWidgets():
            if not (isinstance(widget, QMessageBox) and widget.isVisible()):
                continue
            entry = dict(title=widget.windowTitle(), text=widget.text(), info=widget.informativeText(),
                         buttons=[b.text() for b in widget.buttons()])
            result['dialogs'].append(entry)
            replace = next((b for b in widget.buttons() if b.text() == '替换这一段'), None)
            if replace is not None and answers['replace_range']:
                grab(widget, 'run2_finish_question')
                answers['replace_range'] = False
                entry['answered'] = '替换这一段'
                replace.click()
            else:
                widget.done(0)

    watchdog = QTimer()
    watchdog.timeout.connect(handle_boxes)
    watchdog.start(300)

    def page():
        return window._studio_page_instance

    def pause(studio):
        try:
            studio.video.set_paused(True)
            studio._sync_play_button(True)
        except Exception:  # noqa: BLE001
            pass

    def open_project(path):
        ready = {'v': False}
        window.open_studio_project(str(path), mode='edit', source='startup_audit',
                                   on_ready=lambda *a, **k: ready.__setitem__('v', True))
        wait_for(lambda: ready['v'], 90)
        settle(1500)
        studio = page()
        pause(studio)
        return studio

    def fit(studio):
        from ..timeline.studio_edit_sequence import timeline_duration_ms
        studio.timeline.set_visible_window(0, max(1000, int(timeline_duration_ms(studio.project)) + 400))
        settle(300)

    def newest_run_log():
        logs = sorted(glob.glob(str(Path(os.environ['LOCALAPPDATA']) / '2ByteASR' / 'logs' / 'auto_asr_*.jsonl')),
                      key=os.path.getmtime)
        return Path(logs[-1]) if logs else None

    def run_events(path):
        rows = []
        for line in Path(path).read_text('utf-8', errors='replace').splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        return rows

    def wait_run(studio, tag, timeout=900):
        running = wait_for(lambda: window._run_in_progress or getattr(studio, '_recognition_running', False), 30)
        check(f'{tag}: recognition started', running)
        return running

    def wait_done(tag, timeout=900):
        started = time.monotonic()
        wait_for(lambda: not window._run_in_progress and not getattr(page(), '_recognition_running', False), timeout)
        settle(2500)
        result['metrics'][f'{tag}_seconds'] = round(time.monotonic() - started, 1)

    def snapshot(studio):
        return [(c.id, c.start_ms, c.end_ms, c.text, c.speaker_id) for c in studio.project.cues]

    def overlapping(studio, start, end):
        return [c for c in studio.project.cues if c.end_ms > start and c.start_ms < end]

    def words_in(text, key):
        return [w for w in config['words'][key] if w in text]

    def right_click(studio, cue, tag, *, trigger=True):
        """A real context-menu event on the caption; picks 只重新识别这一段字幕."""
        found = {}

        def pick(attempt=0):
            menus = [w for w in app.topLevelWidgets() if isinstance(w, QMenu) and w.isVisible()]
            if not menus:
                if attempt < 40:
                    QTimer.singleShot(100, lambda: pick(attempt + 1))
                return
            menu = menus[-1]
            action = next((a for a in menu.actions() if a.objectName() == 'rangeRecognitionAction'), None)
            found.update(text=action.text() if action else None, enabled=action.isEnabled() if action else None,
                         texts=[a.text() for a in menu.actions() if a.text()][-8:])
            grab(menu, f'{tag}_menu')
            menu.close()
            if action is not None and trigger and action.isEnabled():
                found['triggered'] = True
                QTimer.singleShot(0, action.trigger)

        QTimer.singleShot(400, pick)
        timeline = studio.timeline
        tracks = timeline._track_layout()[0]
        rect = tracks.get(cue.speaker_id) if cue is not None else None
        if rect is not None:
            band = timeline._cue_band(cue, rect)
            point = QPoint(int((timeline._time_to_x(cue.start_ms) + timeline._time_to_x(cue.end_ms)) / 2),
                           int(band.center().y()))
            found['hit'] = getattr(timeline._cue_at(point)[0], 'id', None)
            QApplication.sendEvent(timeline, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point,
                                                               timeline.mapToGlobal(point)))
        else:
            studio._show_timeline_menu(cue.id if cue else '', timeline.mapToGlobal(QPoint(300, 40)))
        settle(600)
        return found

    def mark(studio, start_ms, end_ms):
        studio._clear_range()      # I / O at the same place again would clear the point
        settle(200)
        studio._seek(start_ms / 1000.0)
        settle(400)
        studio.timeline.set_playhead(start_ms)
        studio._mark_in()
        studio._seek(end_ms / 1000.0)
        settle(400)
        studio.timeline.set_playhead(end_ms)
        studio._mark_out()
        settle(300)
        from ..projects.project_range import range_points
        return range_points(studio.project)

    def run_full():
        studio = open_project(config['project'])
        check('empty project opened', studio is not None and studio.project is not None)
        primary, timeline_backend, review = config['models']
        set_ok = [window._set_backend_combo(window.primary_asr_backend, primary),
                  window._set_backend_combo(window.firered_asr_backend, timeline_backend),
                  window._set_backend_combo(window.qwen_asr_backend, review)]
        check(f'models set: {primary}/{timeline_backend}/{review}', all(set_ok), set_ok)
        before = len(studio.project.media_pool)
        studio._begin_media_drop([config['media']], 0)
        check('clip imported', wait_for(lambda: len(studio.project.media_pool) > before, 60))
        settle(1500)
        studio.save()
        studio._open_recognition_sheet()
        settle(900)
        studio._recognition_controls['start'].click()
        wait_run(studio, 'full')
        wait_done('full')
        studio = page()
        finished = wait_for(lambda: '识别结果' in str(page().project_path or ''), 30)
        settle(2000)
        pause(page())
        studio = page()
        text = ''.join(c.text for c in studio.project.cues)
        result['metrics']['full_captions'] = snapshot(studio)
        check('whole clip recognized and opened', finished and studio.project.cues,
              dict(path=str(studio.project_path), count=len(studio.project.cues)))
        check('whole run heard all three sentences',
              all(words_in(text, key) for key in ('s1', 's2', 's3')), text[:200])
        return studio

    def make_middle_wrong(studio):
        """The middle sentence's captions as a wrong recognition (text and recognized text)."""
        from ..timeline.studio_commands import MutationOrigin, SetCueFieldsCommand
        a, b = config['spans']['s2']
        middle = overlapping(studio, a + 50, b - 50)
        for index, cue in enumerate(middle):
            wrong = f'识别错了的第{index + 1}句'
            studio.undo_stack.push(SetCueFieldsCommand(studio.project, cue.id, {'text': wrong, 'original_text': wrong},
                                                       'fixture: wrong recognition', studio._changed,
                                                       MutationOrigin.SYSTEM))
        settle(500)
        studio.save()
        return middle

    def range_run(studio, tag, *, edit_first=False, edit_during=False):
        from ..recognition.cue_word_alignment import cue_words
        from ..projects.subtitle_consistency import validate_project
        a, b = config['spans']['s2']
        middle = overlapping(studio, a + 50, b - 50)
        first = middle[0]
        # The in point cuts the first caption of the sentence; the out point
        # sits in the pause before the third sentence.
        in_ms = (first.start_ms + first.end_ms) // 2
        out_ms = min(b + 300, (config['spans']['s3'][0] + b) // 2)
        points = mark(studio, in_ms, out_ms)
        check(f'{tag}: I / O set the range', points == (in_ms, out_ms), points)
        if edit_first:
            studio.cue_controller.set_text(first.id, '我手动改过这一句')
            settle(400)
        fit(studio)
        grab(window, f'{tag}_0_range_set')
        before = snapshot(studio)
        receipts_before = json.dumps(studio.project.to_dict().get('studio_state', {}).get('caption_timeline'),
                                     sort_keys=True, ensure_ascii=False)
        undo_index = studio.undo_stack.index()
        menu = right_click(studio, first, tag)
        check(f'{tag}: right-click hit the caption and the menu offers the entry, enabled',
              menu.get('enabled') is True and menu.get('triggered') and menu.get('hit') in {first.id, None}, menu)
        opened = wait_for(lambda: window._modal_host.isVisible() and (page()._recognition_controls or {}).get('range'), 10)
        settle(900)
        controls = page()._recognition_controls
        info = controls.get('range') or {}
        notes = [label.text() for label in controls.get('range_notes') or ()]
        window_start, window_end = info.get('window') or (0, 0)
        expected_ids = [c.id for c in overlapping(studio, window_start, window_end)] if info else []
        result['metrics'][f'{tag}_sheet'] = dict(title=window._modal_host.title_label.text(), notes=notes, info=info,
                                                 start=controls['start'].text())
        check(f'{tag}: the sheet opened in range mode', opened and info, result['metrics'][f'{tag}_sheet'])
        check(f'{tag}: the stretch is widened to the cut caption', window_start == first.start_ms
              and info.get('requested') == (in_ms, out_ms), dict(window=info.get('window'), first=first.start_ms))
        check(f'{tag}: the sheet says what is replaced and that the cut caption is taken whole',
              len(notes) >= 2 and f"{len(expected_ids)} 条字幕" in notes[0] and '整条' in notes[1], notes)
        check(f'{tag}: translation and 仅本地识别 are hidden; start says 识别这一段',
              controls['translation'].isHidden() and controls['local_analysis'].isHidden()
              and controls['start'].text() == '识别这一段')
        grab(window._modal_host.card, f'{tag}_1_sheet')
        controls['start'].click()
        settle(600)
        if edit_first:
            confirm_visible = not controls['confirm'].isHidden() and controls['start'].isHidden()
            check(f'{tag}: a caption edited by hand is confirmed first', confirm_visible
                  and '1 条字幕你改过' in controls['confirm_text'].text() and not window._run_in_progress,
                  controls['confirm_text'].text())
            grab(window._modal_host.card, f'{tag}_2_confirm')
            controls['confirm_replace'].click()
        else:
            check(f'{tag}: nothing edited by hand, so it starts at once', controls['confirm'].isHidden())
        running = wait_run(studio, tag)
        if running:
            busy = right_click(studio, first, f'{tag}_running', trigger=False)
            check(f'{tag}: during the run the entry says why it is unavailable',
                  busy.get('enabled') is False and '正在识别' in str(busy.get('text')), busy)
            if edit_during:
                other = next((c for c in studio.project.cues if c.id in expected_ids and c.id != first.id), first)
                studio.cue_controller.set_text(other.id, '识别期间改的')
                settle(300)
                answers['replace_range'] = True
                result['metrics'][f'{tag}_edited_during'] = other.id
                # What undo has to bring back now includes this edit.
                before = snapshot(studio)
                receipts_before = json.dumps(studio.project.to_dict().get('studio_state', {}).get('caption_timeline'),
                                             sort_keys=True, ensure_ascii=False)
                undo_index = studio.undo_stack.index()
        wait_done(tag)
        studio = page()
        # The finished result is spliced in right after the run ends.
        wait_for(lambda: '这一段' in str(getattr(studio, '_recognition_status_sticky', '')), 60)
        settle(800)
        after = snapshot(studio)
        label = getattr(studio, 'recognition_chip_label', None)
        chip = label.text() if label is not None else ''
        result['metrics'][f'{tag}_chip'] = chip
        result['metrics'][f'{tag}_after'] = after
        check(f'{tag}: replaced as one undo step', studio.undo_stack.index() == undo_index + 1
              and '这一段识别完成' in chip, dict(index=studio.undo_stack.index(), before=undo_index, chip=chip))
        if edit_during:
            asked = [d for d in result['dialogs'] if d.get('answered') == '替换这一段']
            check(f'{tag}: an edit made during the run is asked about at the finish', asked, result['dialogs'][-2:])
        kept_before = [row for row in before if row[0] not in set(expected_ids)]
        kept_after = [row for row in after if row[0] in {r[0] for r in kept_before}]
        check(f'{tag}: captions outside the stretch keep id, time and text', kept_before == kept_after,
              dict(before=kept_before, after=kept_after))
        new = [c for c in studio.project.cues if c.id not in {row[0] for row in before}]
        new_text = ''.join(c.text for c in new)
        check(f'{tag}: the new captions sit inside the stretch and say the middle sentence',
              new and all(window_start <= c.start_ms < c.end_ms <= window_end for c in new)
              and words_in(new_text, 's2') and not any('识别错了' in c.text or '改过' in c.text for c in new),
              dict(window=[window_start, window_end], new=[(c.id, c.start_ms, c.end_ms, c.text) for c in new]))
        check(f'{tag}: the old captions of the stretch are gone',
              not {c.id for c in studio.project.cues} & set(expected_ids), expected_ids)
        from ..recognition.cue_word_alignment import normalized_content

        def word_profile(cues):
            rows = {}
            for cue in cues:
                words = cue_words(studio.project, cue)[0]
                rows[cue.id] = dict(words=[(w.text, w.start_ms, w.end_ms) for w in words],
                                    covers=''.join(normalized_content(w.text) for w in words)
                                    == normalized_content(cue.text),
                                    edge=max((abs(words[0].start_ms - cue.start_ms), abs(words[-1].end_ms - cue.end_ms)))
                                    if words else None)
            return rows
        timed = word_profile(new)
        # Whole-run captions outside the stretch are the yardstick: a padded first
        # syllable may start in the pause before its caption there too.
        untouched = word_profile([c for c in studio.project.cues if c.id in {r[0] for r in kept_after}])
        yardstick = max((row['edge'] for row in untouched.values() if row['edge'] is not None), default=0)
        result['metrics'][f'{tag}_new_words'] = timed
        result['metrics'][f'{tag}_untouched_word_edges'] = {k: v['edge'] for k, v in untouched.items()}
        check(f'{tag}: the new captions carry word timing like the whole-run captions (cover the text, '
              'inside the stretch, edges no worse than untouched captions)',
              all(row['words'] and row['covers'] and row['edge'] <= yardstick + 150
                  and all(window_start <= s and e <= window_end for _t, s, e in row['words']) for row in timed.values()),
              dict(yardstick=yardstick, new={k: (v['covers'], v['edge']) for k, v in timed.items()}))
        problems = validate_project(studio.project)
        check(f'{tag}: the project stays consistent', not problems.errors, [e.code for e in problems.errors])
        fit(studio)
        grab(window, f'{tag}_3_replaced')
        studio.undo_stack.undo()
        settle(800)
        receipts_undone = json.dumps(studio.project.to_dict().get('studio_state', {}).get('caption_timeline'),
                                     sort_keys=True, ensure_ascii=False)
        undone = snapshot(studio)
        check(f'{tag}: undo restores the old captions exactly (receipts too)',
              undone == before and receipts_undone == receipts_before,
              dict(diff=[r for r in undone if r not in before][:4]))
        grab(window, f'{tag}_4_undone')
        studio.undo_stack.redo()
        settle(800)
        check(f'{tag}: redo brings the new captions back', snapshot(studio) == after)
        return studio, after

    def run_disabled(studio):
        from ..projects.project_range import range_points, set_range
        start, _end = range_points(studio.project)
        set_range(studio.project, start, None, undo_stack=studio.undo_stack)
        settle(400)
        cue = studio.project.cues[0] if studio.project.cues else None
        menu = right_click(studio, cue, 'no_out_point', trigger=False)
        check('without an out point the entry is disabled and says 先设好入点和出点',
              menu.get('enabled') is False and '先设好入点和出点' in str(menu.get('text')), menu)

    def run_reopen(studio, expected):
        studio.save()
        path = studio.project_path
        settle(500)
        reopened = open_project(path)
        check('saved and reopened: the replaced captions are still there',
              snapshot(reopened) == expected, dict(path=str(path)))
        from ..projects.subtitle_consistency import validate_project
        check('reopened project is consistent', not validate_project(reopened.project).errors)

    def run_all():
        try:
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            window.resize(1500, 940)
            settle(800)
            studio = run_full()
            if studio is not None and studio.project.cues:
                middle = make_middle_wrong(studio)
                result['metrics']['wrong_middle'] = [c.id for c in middle]
                check('fixture: the middle sentence has captions to fix', middle)
                studio, after1 = range_run(studio, 'run1')
                studio, after2 = range_run(studio, 'run2', edit_first=True, edit_during=True)
                run_disabled(studio)
                run_reopen(studio, after2)
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        watchdog.stop()
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        save_result()
        studio = page()
        if studio is not None and getattr(studio, 'project', None) is not None:
            try:
                studio.save()
            except Exception as exc:  # noqa: BLE001
                result['errors'].append(f'save before close: {exc!r}')
        window.close()
        QTimer.singleShot(500, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        save_result()

    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
