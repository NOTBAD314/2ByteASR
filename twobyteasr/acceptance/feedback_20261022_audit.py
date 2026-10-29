"""Real-window check of the 2026-10-22 night feedback round (source or frozen EXE).

Runs on an owned copy of the user's project library (``scripts/verify_feedback_20261022_headed.py``):

* project library: only the first ~10 projects are built (rows completed);
  a scroll near the end builds more; names come in from the library-names thread;
* the user's 《日常》第10话 copy: two speaker tracks + one shared track;
* the 动效 page builds its effect tiles only when first shown, and they render;
* a click on a translation block selects the translation line; E opens the
  timeline translation editor; Enter commits; undo restores;
* the Studio 「识别字幕」 sheet lists the trimmed plans with MOSS Pro + Qwen 对齐.

Nothing outside ``output`` is written; no network or AI calls.
"""
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], identity=load_build_identity().to_dict(), passed=False, metrics={})
    page = window.studio_page

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        save()

    def capture(name):
        try:
            _capture(window, output / (name + '.png'))
        except Exception as exc:  # noqa: BLE001
            result.setdefault('errors', []).append(f'capture {name}: {exc!r}')

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def steps():
        window.showMaximized()
        began = time.monotonic()
        page.show_project_hub()
        window._switch_page(page) if hasattr(window, '_switch_page') else None
        yield lambda: len(page._hub_card_widgets) >= 1
        yield lambda: not getattr(page, '_hub_scan_pending', False)
        yield 2.0
        columns = page._hub_grid_metrics[0]
        built = len(page._hub_card_widgets)
        total = len(getattr(page, '_hub_display_records', ()) or ())
        result['metrics'].update(library_total=total, library_first=built, library_columns=columns,
                                 library_seconds=round(time.monotonic() - began, 2))
        check('library builds about 10 projects first (rows completed)',
              total > 12 and 10 <= built <= -(-10 // columns) * columns, dict(built=built, total=total, columns=columns))
        capture('01-library')
        bar = page.project_library_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        yield 1.0
        check('scrolling near the end builds the next page', len(page._hub_card_widgets) > built,
              len(page._hub_card_widgets))
        renamed = [card for card in page._hub_card_widgets
                   if card.text().splitlines()[0] != __import__('pathlib').Path(card._library_item_path).stem]
        result['metrics']['library_named_cards'] = len(renamed)
        window.open_studio_project(spec['project'], mode='edit', source='feedback_20261022_audit')
        yield ready
        yield 1.5
        t = page.timeline
        rows = [kind for kind, _key, _height in t._display_rows()]
        state = page.project.studio_state.get('speaker_roles') or {}
        check('two speaker tracks plus one shared track', rows.count('speaker') == 2 and rows.count('group') == 1,
              dict(rows=rows, policy=state.get('policy'), cap=state.get('cap')))
        capture('02-tracks')
        inspector = page.motion_inspector
        check('motion tiles not built with the page', not inspector._cards, len(inspector._cards))
        page.context_drawer.setCurrentIndex(page.motion_tab_index)
        yield 1.5
        stage = inspector.stages[inspector.tabs.currentIndex()]
        tiles = [tile for (s, _k), tile in inspector._cards.items() if s == stage]
        drawn = [tile for tile in tiles if tile.preview.pixmap() is not None and not tile.preview.pixmap().isNull()]
        check('motion tiles built and drawn when the page opens', tiles and len(drawn) == len(tiles),
              dict(stage=stage, tiles=len(tiles), drawn=len(drawn)))
        capture('03-motion')
        if not page.timeline.bilingual:
            page._set_bilingual_mode(True)
            yield 1.0
        translations = page.project.generation_metadata.get('translations') or {}
        target = next(c for c in page.project.cues if translations.get(c.id) and c.end_ms - c.start_ms >= 1200)
        if not page.video._paused:
            page._toggle_playback()
        page._seek(target.start_ms / 1000.0)
        yield 1.0
        t.set_visible_window(max(0, target.start_ms - 4000), 12_000)
        yield .5
        _speakers, lane, _wave = t._track_layout()
        if not t._track_viewport().contains(lane.center()):
            t.ensure_rect_visible(lane) if hasattr(t, 'ensure_rect_visible') else None
            yield .3
            _speakers, lane, _wave = t._track_layout()
        point = QPoint(round(t._time_to_x((target.start_ms + target.end_ms) // 2)), round(lane.center().y()))
        hit = t._cue_at(point)
        check('translation block is under the pointer', hit[0] is not None and hit[0].id == target.id and hit[1] == 'translation',
              dict(hit=(hit[0].id if hit[0] else None, hit[1]), point=(point.x(), point.y())))
        QTest.mouseClick(t, Qt.LeftButton, pos=point)
        yield .5
        check('click selects the translation line', t.selected_id == target.id and t.selected_lane == 'translation',
              dict(selected=t.selected_id, lane=t.selected_lane))
        capture('04-translation-selected')
        before = str(translations.get(target.id))
        page._shortcut_edit_at_playhead()   # the E key's handler (private desktops never get focus)
        yield .4
        editor = t._inline_editor
        check('E opens the translation editor on that block', editor is not None and t._inline_target == (target.id, True)
              and editor.toPlainText() == before, dict(target=t._inline_target))
        capture('05-translation-editor')
        if editor is not None:
            editor.selectAll()
            editor.insertPlainText(before + '（改）')
            QTest.keyClick(editor, Qt.Key_Return)
            yield .5
            after = (page.project.generation_metadata.get('translations') or {}).get(target.id)
            check('Enter commits the translation', after == before + '（改）', after)
            page.undo_stack.undo()
            yield .3
            check('undo restores the translation',
                  (page.project.generation_metadata.get('translations') or {}).get(target.id) == before)
        page._open_recognition_sheet()
        yield .8
        sheet = page._recognition_sheet
        plan = next((combo for combo in sheet.findChildren(QComboBox)
                     if combo.findData('home') >= 0), None)
        keys = [plan.itemData(i) for i in range(plan.count())] if plan is not None else []
        labels = [plan.itemText(i) for i in range(plan.count())] if plan is not None else []
        check('recognition sheet lists the trimmed plans',
              keys == ['quality', 'moss_pro_qwen', 'japanese', 'english', 'home'], labels)
        if plan is not None:
            plan.showPopup()
            yield .5
            capture('06-plans')
            plan.hidePopup()
        modal = getattr(window, '_modal_host', None)
        if modal is not None:
            modal.hide_content()
        yield .3
        result['passed'] = all(x['passed'] for x in result['checks'])

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop(); save()
        try:
            page.session.undo_stack.setClean()
        except Exception:  # noqa: BLE001
            pass
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
            capture('failure')
            finish()
        finally:
            state['ticking'] = False

    def shutdown():
        result['gui_shutdown'] = True
        save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    timer.setInterval(30)
    timer.start()
