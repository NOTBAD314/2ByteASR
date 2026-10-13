"""Real-window check of main / secondary speaker grouping (2026-10-12).

Opens a copy of a multi-speaker project and drives the Studio window: the
old project first shows one track per speaker; the "organize" menu action
groups the secondary speakers into one row (one undo step); overlapping
secondary lines get sub-lanes and stay clickable; the group expands and
collapses from its header; eye/lock act on every member; a manual role
moves one speaker out of the group; resize, playback, save and reopen keep
the grouping. Exports (ASS) and speaker ownership never change.
"""
from __future__ import annotations

import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu
    from .ass_compiler import compile_ass
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .i18n import tr
    from .speaker_roles import KEY, group_members
    from .studio_project import load_project
    from .studio_speaker_roles import group_actions, role_menu
    from .studio_track_header import button_rect
    from .timeline_cue_gesture import CueInterval
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], identity=load_build_identity().to_dict(), passed=False, measures={})
    page = window.studio_page
    log = (output / 'operations.jsonl').open('w', encoding='utf-8')

    def event(kind, **values):
        log.write(json.dumps(dict(t=time.monotonic(), kind=kind, **values), ensure_ascii=False, default=str) + '\n')
        log.flush()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        event('check', **result['checks'][-1])

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def capture(name):
        _capture(window, output / f'{name}.png')
        page.timeline.grab().save(str(output / f'{name}-timeline.png'))

    def kinds():
        return [kind for kind, _key, _h in page.timeline._display_rows()]

    def geometry(name):
        t = page.timeline
        row = dict(rows=len(kinds()), timeline_h=t.height(), timeline_min_h=t.minimumHeight(),
                   preview_h=page.video.height(), preview_w=page.video.width(),
                   content_h=t._subtitle_content_height(), window=[window.width(), window.height()])
        result['measures'][name] = row
        event('geometry', name=name, **row)
        return row

    def trigger(menu, text):
        for action in menu.actions():
            if action.menu() is not None:
                found = trigger(action.menu(), text)
                if found:
                    return found
            elif action.text().startswith(text):
                action.trigger()
                return True
        return False

    def click(point, button=Qt.LeftButton):
        t = page.timeline
        top = t.window()
        QTest.mouseMove(top.windowHandle(), t.mapTo(top, point))
        QTest.mouseClick(t, button, Qt.NoModifier, point)

    def steps():
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='speaker_roles_audit')
        yield ready
        yield 1.5
        if not page.video._paused:
            page._toggle_playback()
            yield .3
        t = page.timeline
        speakers_before = [c.speaker_id for c in page.project.cues]
        ass_before = compile_ass(page.project)
        speaker_count = len(t.speaker_ids())
        page._seek(spec.get('look_ms', 100000) / 1000.0)
        yield 1.0
        before = geometry('before')
        old_minimum = t.RULER_HEIGHT + t._pinned_bottom_height(minimum=True) + max(56, speaker_count * 52 + (44 if t.bilingual else 0))
        result['measures']['old_rule_minimum_h'] = old_minimum
        check('an older project is not regrouped on open', KEY not in page.project.studio_state
              and kinds() == ['speaker'] * speaker_count, dict(rows=len(kinds()), speakers=speaker_count))
        capture('01-before')

        # ---- organize through the real menu action (one undo step) ----
        index = page.undo_stack.index()
        menu = QMenu(window)
        group_actions(page, menu)
        check('organize action is offered on the group menu', trigger(menu, tr('按主要/次要角色整理轨道')))
        yield .8
        members = list(t._group_members)
        grouped = geometry('grouped')
        check('secondary speakers share one collapsed row', kinds()[0] == 'group' and len(members) >= 2
              and grouped['rows'] == speaker_count - len(members) + 1,
              dict(rows=grouped['rows'], members=members, rule=page.project.studio_state[KEY].get('rule')))
        check('organize is one undo step', page.undo_stack.index() == index + 1)
        check('speaker ownership and ASS export unchanged', [c.speaker_id for c in page.project.cues] == speakers_before
              and compile_ass(page.project) == ass_before)
        check('group needs less vertical space', grouped['content_h'] < before['content_h'],
              dict(before=before['content_h'], after=grouped['content_h']))
        check('timeline minimum leaves room for the preview', t.minimumHeight() < old_minimum,
              dict(now=t.minimumHeight(), old_rule=old_minimum))
        page.undo_stack.undo()
        yield .6
        check('undo restores one track per speaker', kinds() == ['speaker'] * speaker_count)
        page.undo_stack.redo()
        yield .6
        check('redo groups again', kinds()[0] == 'group')
        capture('02-grouped')

        # ---- simultaneous secondary lines get sub-lanes and stay clickable ----
        cues = sorted((c for c in page.project.cues if c.speaker_id in members), key=lambda c: c.start_ms)
        first = next((a for a in cues if any(b.speaker_id != a.speaker_id and b.start_ms > a.end_ms + 2000
                                             and b.end_ms - b.start_ms <= a.end_ms - a.start_ms + 4000 for b in cues)), None)
        second = next((b for b in cues if first and b.speaker_id != first.speaker_id and b.start_ms > first.end_ms + 2000), None)
        if first and second:
            shift = first.start_ms + 300 - second.start_ms
            t.timing_edit_committed.emit({second.id: CueInterval(second.start_ms + shift, second.end_ms + shift,
                                                                   second.speaker_id)})
            yield .8
            lanes = (t._group_lane_by_cue.get(first.id), t._group_lane_by_cue.get(second.id))
            check('overlapping secondary lines get separate sub-lanes', t._group_lane_count >= 2 and lanes[0] != lanes[1],
                  dict(first=first.id, second=second.id, lanes=lanes, count=t._group_lane_count))
            t.set_visible_window(max(0, first.start_ms - 3000), 12000)
            yield .4
            rects = t._track_layout()[0]
            moved = next(c for c in page.project.cues if c.id == second.id)
            x = round(t._time_to_x(first.start_ms + 450))
            hits = []
            for target in (first, moved):
                band = t._cue_band(target, rects[target.speaker_id])
                click(QPoint(x, round(band.center().y())))
                yield .4
                hits.append(page.selected_cue_id)
            check('a real click selects the line in its own sub-lane', hits == [first.id, second.id], hits)
            capture('03-overlap-lanes')
            t.setFocus()
            QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier)
            yield .8
            check('undoing the overlap returns to one lane', t._group_lane_count == 1
                  and next(c for c in page.project.cues if c.id == second.id).start_ms == second.start_ms)
        else:
            check('found two secondary lines to overlap', False)

        # ---- header: expand / collapse, eye and lock on every member ----
        group_rect = t._row_layout()[3][0][2]
        click(button_rect('subtitle', 'more', group_rect).center().toPoint())
        yield .6
        expanded = geometry('expanded')
        check('chevron expands the group into member rows', kinds()[0] == 'group_header'
              and kinds().count('speaker') == speaker_count, expanded)
        capture('04-expanded')
        click(button_rect('subtitle', 'more', t._row_layout()[3][0][2]).center().toPoint())
        yield .6
        check('chevron collapses it again', kinds()[0] == 'group')
        click(button_rect('subtitle', 'visibility', t._row_layout()[3][0][2]).center().toPoint())
        yield .6
        hidden = all(key in t.hidden_speakers and page._subtitle_track_visibility.get(key) is False for key in members)
        click(button_rect('subtitle', 'visibility', t._row_layout()[3][0][2]).center().toPoint())
        yield .6
        shown = not any(key in t.hidden_speakers for key in members)
        check('group eye hides and shows every member (preview visibility too)', hidden and shown)
        click(button_rect('subtitle', 'lock', t._row_layout()[3][0][2]).center().toPoint())
        yield .3
        locked = set(members) <= t.locked_speakers
        click(button_rect('subtitle', 'lock', t._row_layout()[3][0][2]).center().toPoint())
        yield .3
        check('group lock locks and unlocks every member', locked and not set(members) & t.locked_speakers)

        # ---- manual role: one speaker gets an own track, undoable ----
        speaker = members[0]
        menu = QMenu(window)
        role_menu(page, menu, speaker)
        check('own-track action is offered', trigger(menu, tr('固定为独立轨（不参与自动分组）')))
        yield .6
        check('manual own track leaves the group', speaker not in t._group_members
              and speaker in [key for kind, key, _h in t._display_rows() if kind == 'speaker'])
        page.undo_stack.undo()
        yield .6
        check('undo puts it back in the group', speaker in t._group_members)

        # ---- display modes, resize, playback ----
        rows_now = len(kinds())
        if page.project.generation_metadata.get('translations'):
            from .studio_bilingual import apply_display
            mode = page.project.studio_state.get('bilingual', {}).get('mode', 'original')
            apply_display(page, mode='bilingual')
            yield .6
            check('bilingual shows one translation row, rows not doubled', len(kinds()) == rows_now
                  and t._track_layout()[1] is not None)
            capture('05-bilingual')
            apply_display(page, mode=mode)
            yield .4
        window.showNormal()
        window.resize(1280, 760)
        yield 1.0
        small = geometry('resized-1280x760')
        check('after resize the preview keeps its space and the group stays', small['preview_h'] >= 200
              and kinds()[0] == 'group', small)
        capture('06-resized')
        window.showMaximized()
        yield 1.0
        page._toggle_playback()
        yield 3.0
        page._toggle_playback()
        yield .5

        # ---- save, reload from disk, reopen in the window ----
        t.setFocus()
        QTest.keyClick(t, Qt.Key_S, Qt.ControlModifier)
        yield lambda: page.session.undo_stack.isClean()
        reopened = load_project(spec['project'])
        check('save keeps the role state and the export', reopened.studio_state.get(KEY, {}).get('grouped')
              and set(group_members(reopened)) == set(members) and compile_ass(reopened) == ass_before)
        window.open_studio_project(spec['project'], mode='edit', source='speaker_roles_audit_reopen')
        yield 1.0
        yield ready
        yield 1.0
        check('reopened window shows the same grouping', kinds()[0] == 'group'
              and list(page.timeline._group_members) == members)
        geometry('reopened')
        capture('07-reopened')
        result['members'] = members
        result['passed'] = all(c['passed'] for c in result['checks'])

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop()
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
