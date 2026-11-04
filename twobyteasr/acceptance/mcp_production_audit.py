"""Owned-window, offline production MCP checks for source and frozen builds."""
from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .studio_acceptance_audit import require
    from ..diagnostics.build_identity import load_build_identity
    from ..local_mcp import mcp_common as common
    from ..local_mcp.mcp_bridge import bridge_for
    from ..local_mcp.mcp_stdio import _call
    from ..timeline.studio_edit_sequence import timeline_duration_ms

    page = window.built_page('studio')
    if page is None:
        QTimer.singleShot(100, lambda: start(window, output))
        return
    result = dict(passed=False, checks=[], identity=load_build_identity().to_dict())
    spec = json.loads((output / 'input.json').read_text('utf8'))
    bridge = bridge_for(window)
    state = dict(wait=None, deadline=0., until=0., ticking=False)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        save()
        require(ok, name + ': ' + str(detail))

    def request(method, *, expected_error='', **params):
        box = {}
        def invoke():
            try:
                box['value'] = _call(method, **params)
            except Exception as exc:
                box['error'] = str(exc)
        thread = threading.Thread(target=invoke, daemon=True)
        thread.start()
        yield lambda: not thread.is_alive()
        if expected_error:
            check(method + ' refused: ' + expected_error, expected_error in box.get('error', ''), box)
            return box
        require('error' not in box, method + ': ' + str(box))
        return box['value']

    def terminal(job):
        while job['status'] in {'queued', 'running', 'cancelling'}:
            yield .05
            job = yield from request('get_job', job_id=job['job_id'])
        check(job['kind'] + ' completed', job['status'] == 'completed', job.get('error'))
        return job

    def status():
        value = yield from request('status')
        return dict(project_id=value['project']['project_id'], revision=value['project']['revision'])

    def detect():
        identity = yield from status()
        job = yield from request('detect_speech_pauses', **identity, mode='silence', minimum_s=1., padding_s=.2)
        job = yield from terminal(job)
        check('real silence detection found candidates', bool(job['result']['candidates']), job['result'])
        return job

    def steps():
        yield lambda: page.project is not None and page._readiness.ready and not page._readiness.active
        common.save_settings(dict(common.DEFAULTS, enabled=True, acknowledged=True,
                                  allow_edits=True, allow_export=True))
        bridge.apply_settings()
        check('real pipe listening under isolated profile', bridge.listening() and bool(common.read_key()))
        before = page.project.cues[0].text
        identity = yield from status()
        preview = yield from request('cleanup_stutter', **identity)
        preview = yield from terminal(preview)
        check('local stutter preview proposes edits', bool(preview['result']['changes']))
        identity = yield from status()
        changed = yield from request('cleanup_stutter', **identity, action='apply', job_id=preview['job_id'])
        check('direct subtitle edit needs no approval plan', changed['changed_cues'] == 1
              and page.project.cues[0].text != before and not bridge.plans, changed)
        yield .4
        _capture(window, output / 'direct-subtitle-edit.png')
        page.undo_stack.undo()
        check('native subtitle undo restores text', page.project.cues[0].text == before)

        # Do not create or access a real glossary. Any attempted read is a failure.
        import subtitle_core as legacy
        old_loader = legacy.load_learned_term_payload
        attempts = []
        def no_read(*args, **kwargs):
            attempts.append(True)
            raise RuntimeError('Denied glossary read attempted')
        page.project.glossary_ids = ['acceptance-private-library']
        legacy.load_learned_term_payload = no_read
        try:
            identity = yield from status()
            yield from request('cleanup_stutter', **identity, expected_error='not_permitted')
            check('denied glossary was never read', not attempts)
        finally:
            legacy.load_learned_term_payload = old_loader
            page.project.glossary_ids = []

        job = yield from detect()
        count, duration = page.undo_stack.count(), timeline_duration_ms(page.project)
        media = Path(page.project.media.path).resolve()
        require(media.is_relative_to(output), 'Only the owned media may be replaced')
        shutil.copyfile(spec['replacement'], media)
        identity = yield from status()
        yield from request('apply_pause_cuts', **identity, job_id=job['job_id'],
                           candidate_ids=[job['result']['candidates'][0]['candidate_id']], expected_error='input_changed')
        check('source replacement leaves timeline and undo unchanged',
              page.undo_stack.count() == count and timeline_duration_ms(page.project) == duration)
        yield .3
        _capture(window, output / 'stale-pause-refused.png')

        fresh = yield from detect()
        identity = yield from status()
        cut = yield from request('apply_pause_cuts', **identity, job_id=fresh['job_id'],
                                 candidate_ids=[fresh['result']['candidates'][0]['candidate_id']])
        check('fresh detection cuts the real native timeline', cut['removed_ms'] > 0
              and timeline_duration_ms(page.project) < duration, cut)
        yield .5
        _capture(window, output / 'fresh-pause-applied.png')
        page.undo_stack.undo()
        check('native cut undo restores duration', timeline_duration_ms(page.project) == duration)
        identity = yield from status()
        saved = yield from request('save_project', **identity)
        check('native project save verified', saved['saved'] and saved['size_bytes'] > 0, saved)
        identity = yield from status()
        exported = yield from request('export_video', **identity, name='mcp-verified-output')
        exported = yield from terminal(exported)
        video = Path(exported['result']['output_path'])
        check('real video output exists', video.is_file() and video.stat().st_size > 0)
        result['video'] = str(video)
        _capture(window, output / 'production-complete.png')
        result['passed'] = all(row['passed'] for row in result['checks'])

    iterator = steps()
    timer = QTimer(window)
    timer.setInterval(50)

    def finish():
        timer.stop()
        save()
        bridge.stop('acceptance complete')
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
                    raise TimeoutError('Native MCP acceptance did not settle')
                else:
                    return
            if time.monotonic() < state['until']:
                return
            value = next(iterator)
            if callable(value):
                state.update(wait=value, deadline=time.monotonic() + 120)
            else:
                state['until'] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            result['passed'] = False
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
