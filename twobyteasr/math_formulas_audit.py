"""Real-window check of math formulas in captions, Unicode level (2026-10-16, ADR 0124).

Opens a copy of a project whose captions contain ``$…$`` formulas, captures the
workbench preview with the switch off, turns it on through the real 「标点」menu
action, captures again, undoes and redoes, exports SRT/JSON through the export
module the dialog uses, and saves a copy to check that the switch is kept.
Writes result.json, operations.jsonl and window captures.
"""
from __future__ import annotations

import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from . import math_text
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], identity=load_build_identity().to_dict(), passed=False, captures=[])
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

    def shown_ass():
        """What the preview draws: native ASS events plus the overlay snapshots of every cue
        (a project's style decides which of the two routes a cue takes)."""
        from .visual_snapshot import build_visual_cue_snapshot
        from .studio_revisions import StudioRevisionStore
        from .ass_compiler import compile_ass_revision
        events = compile_ass_revision(StudioRevisionStore(page.project).render).split('[Events]')[1]
        overlay = [build_visual_cue_snapshot(page.project, cue.id).text for cue in page.project.cues]
        return events + '\n' + '\n'.join(overlay)

    def capture(name):
        path = output / f'{name}.png'
        _capture(window, path)
        scene = getattr(page, '_caption_scene', None)
        overlay = None
        if scene is not None and scene.published is not None:
            overlay = output / f'{name}-overlay.png'
            scene.published.image.save(str(overlay))
        result['captures'].append(dict(name=name, window=str(path), overlay=str(overlay) if overlay else None))
        event('capture', name=name)

    def steps():
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='math_formulas_audit')
        yield ready
        yield 1.5
        if not page.video._paused:
            page._toggle_playback()
            yield .3
        page.volume_slider.setValue(0)
        cue = next(c for c in page.project.cues if c.id == spec['cue_id'])
        at = (cue.start_ms + cue.end_ms) / 2000.0
        page._seek(at)
        yield 1.5
        check('switch starts off and the manuscript has the LaTeX source',
              not math_text.project_enabled(page.project) and '$' in cue.text, cue.text)
        before = shown_ass()
        capture('1-off')
        action = getattr(page, 'math_formulas_action', None)
        check('「标点」menu has the checkable math formulas entry',
              action is not None and action.isCheckable() and not action.isChecked()
              and action in page.punctuation_button.menu().actions(), action.text() if action else None)
        undo_count = page.undo_stack.count()
        action.trigger()
        yield 1.5
        page._seek(at)
        yield 1.5
        after = shown_ass()
        capture('2-on')
        check('one undoable step turned the switch on', math_text.project_enabled(page.project)
              and page.undo_stack.count() == undo_count + 1 and action.isChecked(),
              page.undo_stack.undoText())
        expected = [spec['expected'][key] for key in spec['expected']]
        check('preview subtitles show the formulas as symbols when on',
              all(text in after for text in expected) and not any(text in before for text in expected),
              dict(expected=expected))
        check('the manuscript is unchanged', [c.text for c in page.project.cues] == spec['texts'])
        page.undo_stack.undo()
        yield 1.0
        page._seek(at)
        yield 1.2
        capture('3-undo')
        check('undo turns it off again', not math_text.project_enabled(page.project) and not action.isChecked()
              and shown_ass() == before)
        page.undo_stack.redo()
        yield 1.0
        page._seek(at)
        yield 1.2
        capture('4-redo')
        # Export through the module the export dialog uses (combined + per speaker).
        from . import studio_subtitle_export as export
        options = export.SubtitleExportOptions(formats=frozenset({'srt', 'txt', 'json'}), speaker_mode='both')
        artifacts = export.export_subtitle_artifacts(page.project, output / 'export', 'math', options)
        srt = next(a.path for a in artifacts if a.format == 'srt' and not a.speaker_id).read_text('utf-8')
        payload = json.loads(next(a.path for a in artifacts if a.format == 'json' and not a.speaker_id)
                             .read_text('utf-8'))
        result['srt'] = srt
        check('SRT export shows the formulas as symbols', all(text in srt for text in expected))
        check('JSON keeps the LaTeX in original_text', payload.get('math_formulas') is True and any(
            '$' in row['original_text'] and row['text'] != row['original_text'] for row in payload['cues']))
        from .studio_project import load_project, save_project
        saved = save_project(page.project, output / 'saved.2byteproj')
        check('saving keeps the switch', math_text.project_enabled(load_project(saved)))
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
