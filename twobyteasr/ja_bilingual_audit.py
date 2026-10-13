"""Opt-in real-window check of Japanese word timing and the bilingual workflow (2026-10-12).

Runs inside the normal desktop entry (source or frozen EXE) on an owned copy of
a Japanese recognition project: real QTest mouse/keyboard events on the
Studio timeline (razor preview and cut at measured Japanese boundaries),
a non-equal-length text edit followed by on-demand re-alignment, the
translation dialog driven against a MOCK provider (no network, no key: the
check covers data flow and UI, not translation quality), bilingual preview
captures in both orders and translation-only, split/merge translation states,
save + reopen, the three SRT layers + JSON, and a short burned-in clip.
Results go to ``result.json``; nothing outside ``output`` is written.
"""
import json
import threading
import time
import traceback

SIMPLIFIED_MARKERS = "买袭闻达负认谁讨们动这说话车东传"


def _mock_translation_provider():
    class MockTranslator:
        provider_id, model = "mock-offline", "mock-translator"

        def structured_complete(self, messages, schema=None, **kwargs):
            payload = json.loads(messages[-1]["content"])
            items = payload.get("items") or payload.get("cues") or payload.get("lines") or []
            return {"items": [{"id": item["id"], "translation": f"模拟译文第{index + 1}条"}
                              for index, item in enumerate(items)]}

        complete = structured_complete
    return MockTranslator()


def start(window, output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .cue_word_alignment import cue_words
    from .studio_project import load_project
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], samples=[], identity=load_build_identity().to_dict(), passed=False,
                  translation_provider='MOCK (offline; not a translation-quality check)')
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

    def cue_by(cue_id):
        return next((c for c in page.project.cues if c.id == cue_id), None)

    def track_point(t, cue, ms):
        rect = t._track_layout()[0][cue.speaker_id]
        return QPoint(round(t._time_to_x(ms)), round(rect.center().y()))

    def move_pointer(t, point):
        top = t.window()
        QTest.mouseMove(top.windowHandle(), t.mapTo(top, point))

    def hover(t, cue, ms, holder):
        point = track_point(t, cue, ms)
        move_pointer(t, point)
        want = t._x_to_time(point.x())
        yield lambda: (t._razor_hover or t._razor_drag or {}).get('split_ms') == want
        QApplication.processEvents()
        resolution = t._razor_resolution()
        row = dict(pointer_ms=want, split_ms=resolution.split_ms if resolution else None)
        if resolution is not None:
            res = resolution.result
            row.update(left=getattr(res, 'left_text', ''), right=getattr(res, 'right_text', ''),
                       source=getattr(res, 'timing_source', None), measured=getattr(res, 'measured', None),
                       result_type=type(res).__name__, reason=getattr(res, 'reason', None))
        result['samples'].append(row)
        event('hover', **row)
        holder[:] = [resolution]

    def seek_and_capture(name, ms):
        page._seek(ms / 1000.0)
        yield .9
        capture(name)

    def steps():
        from .language_rules import project_language
        from .studio_caption_timeline import KEY
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='ja_bilingual_audit')
        yield ready
        yield 1.0
        t = page.timeline
        yield lambda: t.waveform_state == 'READY'
        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.LeftButton)
            yield .3
        project = page.project
        # ---- recognition result: language, text, evidence ----
        check('project recorded as Japanese', project_language(project) == 'ja',
              project.generation_metadata.get('language'))
        corrupted = [c.text for c in project.cues if any(ch in c.text for ch in SIMPLIFIED_MARKERS)]
        check('no Japanese kanji converted to simplified Chinese', not corrupted, corrupted[:5])
        aligned = [c for c in project.cues if any(r.startswith('cue-align:') for r in c.evidence_refs)]
        measured = [c for c in project.cues if cue_words(project, c)[0]]

        def row_pieces(c):
            row = project.asr_evidence.get(next(r for r in c.evidence_refs if r.startswith('cue-align:')), {})
            return [p for p in (row.get('caption_arbitration') or {}).get('acoustic_words') or ()
                    if p.get('start_basis') == 'model' and p.get('end_basis') == 'model']
        with_pieces = [c for c in aligned if row_pieces(c)]
        result['alignment_coverage'] = dict(cues=len(project.cues), with_alignment_row=len(aligned),
                                            with_measured_pieces=len(with_pieces), with_measured_words=len(measured),
                                            without_measured_pieces=[c.text for c in aligned if not row_pieces(c)])
        # Captions whose boundaries were all unreliable carry no measured piece
        # (the razor then says "estimate"); every other one must resolve words.
        check('every caption with measured pieces resolves measured words', len(with_pieces) >= 1
              and all(cue_words(project, c)[0] for c in with_pieces), result['alignment_coverage'])
        events = project.generation_metadata.get('model_statuses') or {}
        result['model_statuses'] = events
        candidates = sorted(((len(cue_words(project, c)[0]), c) for c in aligned), key=lambda x: (-x[0], x[1].start_ms))
        cue = candidates[0][1]
        words, reason = cue_words(project, cue)
        result['target'] = dict(id=cue.id, text=cue.text, reason=reason, words=[
            dict(text=cue.text[w.char_start:w.char_end], start_ms=w.start_ms, end_ms=w.end_ms) for w in words])
        check('target caption has several measured pieces', reason == 'exact_token_text' and len(words) >= 3,
              result['target'])
        # ---- razor at Japanese boundaries ----
        QTest.mouseClick(page.razor_tool_button, Qt.LeftButton)
        yield .2
        check('razor tool selected', t.tool_mode == 'razor')
        t.set_visible_window(cue.start_ms - 600, max(3000, cue.end_ms - cue.start_ms + 1200))
        yield .5
        got = []
        sweep = list(range(cue.start_ms + 40, cue.end_ms - 30, 40))
        for ms in sweep:
            yield from hover(t, cue, ms, got)
        hovered = [s for s in result['samples'] if s.get('split_ms') is not None]
        previews = [s for s in hovered if s.get('left') and s.get('right')]
        rejected = [s for s in hovered if not (s.get('left') and s.get('right'))]
        check('every preview keeps all characters once', previews and all(
            (s['left'] + s['right']).replace(' ', '') == cue.text.replace(' ', '') for s in previews),
            dict(previews=len(previews)))
        check('splits are refused only where one side would be empty',
              all(s['split_ms'] <= words[0].end_ms or s['split_ms'] >= words[-1].start_ms for s in rejected),
              [dict(split_ms=s['split_ms'], result_type=s.get('result_type'), reason=s.get('reason')) for s in rejected])
        onsets = {w.start_ms for w in words}
        changes = [(a['pointer_ms'], b['pointer_ms']) for a, b in zip(previews, previews[1:]) if a['left'] != b['left']]
        check('text boundary changes only across a measured onset',
              all(any(a <= onset <= b for onset in onsets) for a, b in changes), changes)
        boundary = words[len(words) // 2]
        click_ms = boundary.start_ms + 20
        yield from hover(t, cue, click_ms, got)
        shown = got[0]
        capture('ja-razor-hover')
        undo_before = page.session.undo_stack.index()
        QTest.mouseClick(t, Qt.LeftButton, Qt.NoModifier, track_point(t, cue, click_ms))
        yield .6
        pieces = sorted((c for c in page.project.cues if c.start_ms >= cue.start_ms - 1 and c.end_ms <= cue.end_ms + 1
                         and c.speaker_id == cue.speaker_id), key=lambda c: c.start_ms)
        check('click split equals the preview at a measured boundary',
              [p.text for p in pieces] == [shown.result.left_text, shown.result.right_text]
              and shown.result.timing_source == 'exact_token_text',
              dict(pieces=[p.text for p in pieces], preview=[shown.result.left_text, shown.result.right_text]))
        capture('ja-razor-after-split')
        t.setFocus()
        QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier)
        yield .5
        check('undo restores the caption and its words', cue_by(cue.id) is not None
              and cue_by(cue.id).text == cue.text and [w.start_ms for w in cue_words(page.project, cue_by(cue.id))[0]]
              == [w.start_ms for w in words])
        QTest.mouseClick(page.select_tool_button, Qt.LeftButton) if hasattr(page, 'select_tool_button') else None
        yield .2
        # ---- non-equal-length edit, then on-demand re-alignment ----
        edited_text = cue.text[: words[-1].char_start].rstrip()
        page.cue_controller.set_text(cue.id, edited_text)
        yield .4
        edited_words, edited_reason = cue_words(page.project, cue_by(cue.id))
        result['edited'] = dict(text=edited_text, reason=edited_reason, words=len(edited_words))
        from .studio_realign import start_realign
        index_before = page.session.undo_stack.index()
        start_realign(page, [cue.id])
        yield lambda: page.session.undo_stack.index() > index_before or '失败' in page.save_state.text()
        realigned, realigned_reason = cue_words(page.project, cue_by(cue.id))
        receipt = page.project.studio_state[KEY]['instances'].get(cue.id, {})
        result['realigned'] = dict(reason=realigned_reason, words=[
            dict(text=edited_text[w.char_start:w.char_end], start_ms=w.start_ms) for w in realigned],
            status=page.save_state.text(), model=(receipt.get('forced_alignment') or {}).get('model'))
        check('re-alignment measures the edited text again', realigned_reason == 'exact_token_text'
              and realigned and receipt.get('text') == edited_text and receipt.get('forced_alignment'),
              result['realigned'])
        t.setFocus()
        QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier); yield .4
        QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier); yield .4
        check('undo re-alignment and edit restores the original', cue_by(cue.id).text == cue.text)
        # ---- translation (MOCK provider) ----
        from . import ai_providers
        from .studio_ai import GLOBAL_PROVIDER_REGISTRY
        from .subtitle_translation import status_counts, cue_status
        ai_providers.provider_for_stage = lambda settings, stage, sender=None: _mock_translation_provider()
        GLOBAL_PROVIDER_REGISTRY.credential = lambda selection: (True, 'mock')
        from .studio_translation_dialog import SubtitleTranslationDialog
        dialog = SubtitleTranslationDialog(page, window)
        dialog.show()
        yield .5
        capture('translation-dialog')
        QTest.mouseClick(dialog.start_button, Qt.LeftButton)
        yield lambda: dialog._thread is None and dialog._result is not None
        yield .5
        counts = status_counts(page.project)
        result['translation_counts'] = counts
        capture('translation-dialog-done')
        dialog.close()
        from .bilingual_layout import settings_from_state
        check('translation filled every caption and switched to bilingual display',
              counts.get('done', 0) == len([c for c in page.project.cues if c.text.strip()])
              and settings_from_state(page.project.studio_state).mode == 'bilingual', counts)
        check('render revision carries the bilingual layout', 'bi:' in page._revision_store.render.compile_key[-1])
        middle = (cue.start_ms + cue.end_ms) // 2
        yield from seek_and_capture('preview-bilingual-translation-first', middle)
        from .studio_bilingual import apply_display
        apply_display(page, order='original_first')
        yield .3
        yield from seek_and_capture('preview-bilingual-original-first', middle)
        apply_display(page, mode='translation')
        yield .3
        yield from seek_and_capture('preview-translation-only', middle)
        apply_display(page, mode='bilingual', order='translation_first')
        yield .3
        # ---- split a translated caption: states, then translate only pending ----
        index_before = page.session.undo_stack.index()
        from .studio_commands import split_cue_command
        from .studio_timing import resolve_split
        cut = resolve_split(cue_by(cue.id), boundary.start_ms, project=page.project)
        page.cue_controller.split_at(cue.id, cut.split_ms) if hasattr(page.cue_controller, 'split_at') else None
        yield .6
        pieces = sorted((c for c in page.project.cues if c.start_ms >= cue.start_ms - 1 and c.end_ms <= cue.end_ms + 1
                         and c.speaker_id == cue.speaker_id), key=lambda c: c.start_ms)
        states = [cue_status(page.project, p) for p in pieces]
        result['split_states'] = dict(texts=[p.text for p in pieces], states=states)
        check('after a split the left needs an update and the right is untranslated (nothing copied as done)',
              len(pieces) == 2 and states == ['needs_update', 'untranslated'], result['split_states'])
        dialog = SubtitleTranslationDialog(page, window)
        dialog.show()
        yield .3
        QTest.mouseClick(dialog.start_button, Qt.LeftButton)
        yield lambda: dialog._thread is None and dialog._result is not None
        dialog.close()
        states = [cue_status(page.project, p) for p in pieces]
        check('translating only pending captions completes both halves', states == ['done', 'done'], states)
        # ---- manual translation is protected ----
        page.cue_controller.set_translation(pieces[0].id, '人工翻译的一句')
        yield .3
        check('typed translation is a manual record', cue_status(page.project, pieces[0]) == 'manual')
        dialog = SubtitleTranslationDialog(page, window)
        dialog.show()
        dialog.scope_buttons['all'].setChecked(True)
        yield .3
        QTest.mouseClick(dialog.start_button, Qt.LeftButton)
        yield lambda: dialog._thread is None and dialog._result is not None
        protected = page.project.generation_metadata['translations'].get(pieces[0].id)
        check('AI run over everything keeps the manual translation', protected == '人工翻译的一句'
              and pieces[0].id in dialog._result.suggestions, protected)
        dialog.close()
        # ---- save and reopen ----
        t.setFocus()
        QTest.keyClick(t, Qt.Key_S, Qt.ControlModifier)
        yield lambda: page.session.undo_stack.isClean()
        reopened = load_project(spec['project'])
        check('save + reopen keeps translations, records, display and alignment rows',
              reopened.generation_metadata.get('translations') == page.project.generation_metadata.get('translations')
              and (reopened.generation_metadata.get('translation_records') or {}).get('records')
              and settings_from_state(reopened.studio_state).mode == 'bilingual'
              and any(k.startswith('cue-align:') for k in reopened.asr_evidence))
        # ---- export: three SRT layers + JSON, never overwriting ----
        from .studio_subtitle_export import export_language_layers
        export_dir = output / 'export'
        export_dir.mkdir()
        first = export_language_layers(reopened, export_dir, 'ja-test', ('original', 'translation', 'bilingual', 'json'))
        second = export_language_layers(reopened, export_dir, 'ja-test', ('original', 'translation', 'bilingual'))
        names = sorted(p.name for p in export_dir.iterdir())
        result['export'] = dict(first=[a.path.name for a in first.artifacts], second=[a.path.name for a in second.artifacts],
                                missing=first.missing_translation_count, stale=first.needs_update_count)
        bilingual_srt = next(a.path for a in first.artifacts if a.layer == 'bilingual').read_text('utf-8')
        check('three SRT layers and JSON written; a second export does not overwrite',
              len(first.artifacts) == 4 and len(names) == 7 and '(2)' in ' '.join(a.path.name for a in second.artifacts),
              result['export'])
        check('bilingual SRT has the Chinese line above the Japanese line', '模拟译文' in bilingual_srt.split('\n\n')[0]
              or '人工翻译' in bilingual_srt.split('\n\n')[0], bilingual_srt[:200])
        exported = json.loads(next(a.path for a in first.artifacts if a.layer == 'json').read_text('utf-8'))
        rows = exported.get('cues') or exported.get('subtitles') or []
        with_timing = [r for r in rows if (r.get('word_timing') or {}).get('pieces')]
        check('JSON keeps original, translation and Japanese word timing', rows and with_timing
              and all('translation' in r and 'original_text' in r for r in rows),
              dict(rows=len(rows), with_timing=len(with_timing)))
        # ---- burned-in bilingual clip (same ASS path as the export dialog) ----
        from .export_timeline import write_export_ass
        from .runtime_paths import get_runtime_paths
        from .studio_render import RenderJob, RenderSettings, run_render_job
        from .video_export import capture_video_graph
        ass = output / 'bilingual-export.ass'
        write_export_ass(page.project, ass)
        ass_text = ass.read_text('utf-8-sig')
        check('export ASS has the translation companion events', '模拟译文' in ass_text or '人工翻译' in ass_text)
        clip = output / 'bilingual-clip.mp4'
        job = RenderJob(page.project.media.path, str(ass), str(clip),
                        RenderSettings(encoder='libx264', preset='ultrafast', width=960, height=540, fps=24,
                                       audio_codec='none'),
                        start_seconds=max(0.0, cue.start_ms / 1000 - 0.2), duration_seconds=1.5,
                        video_graph=capture_video_graph(page.project))
        done = {}

        def render():
            try:
                run_render_job(get_runtime_paths().install_root / 'tools/ffmpeg/bin/ffmpeg.exe', job)
            except Exception:
                done['error'] = traceback.format_exc()
            done['finished'] = True
        threading.Thread(target=render, daemon=True, name='ja-bilingual-export').start()
        yield lambda: done.get('finished')
        check('bilingual clip rendered', not done.get('error') and clip.is_file() and clip.stat().st_size > 1000,
              done.get('error'))
        result['passed'] = all(x['passed'] for x in result['checks'])

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)

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
                state.update(wait=value, deadline=time.monotonic() + 180)
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
