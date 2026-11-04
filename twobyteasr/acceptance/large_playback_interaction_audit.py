"""Exercise pause, real caption edits, style changes, playback and teardown."""
import json
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..caption_style.bilingual_layout import companion_id
    from ..caption_style.scoped_style import effective_layer_style
    from .blank_project_audit import _capture

    try:
        page = window.studio_page
    except RuntimeError:
        QTimer.singleShot(100, lambda: start(window, output))
        return
    output = Path(output)
    spec = json.loads((output/'input.json').read_text('utf8'))
    result = {'passed': False, 'checks': {}, 'measurements': {}}

    def save():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')

    def wait(predicate, seconds=30):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            if predicate():
                return True
            QTest.qWait(30)
        return bool(predicate())

    def check(name, condition):
        result['checks'][name] = bool(condition)
        save()
        if not condition:
            raise AssertionError(name)

    def execute():
        scene = None
        try:
            check('project_ready', wait(lambda: page.project is not None and page._readiness.ready and not page._readiness.active, 150))
            check('real_media_online', bool(page.project.media_pool) and all(not a.offline and Path(a.canonical_source).is_file() for a in page.project.media_pool))
            if not page.video._paused:
                page._toggle_playback()
            page.volume_slider.setValue(0)
            page._seek(spec['start']+.5)
            check('seek_completed', wait(lambda: not page.video.playback_position_snapshot().exact_seek_pending, 15))
            QTest.qWait(1300)
            position = int((spec['start']+.5)*1000)
            cue = next(c for c in page.session.runtime.cues_at(position)
                       if page.project.generation_metadata.get('translations', {}).get(c.id))
            page.select_cue(cue.id)
            check('bilingual_scene_ready', wait(lambda: getattr(page, '_caption_scene', None) is not None
                and page._caption_scene.published is not None and cue.id in page._caption_scene.trace()['rendered_cue_ids']
                and companion_id(cue.id) in page._caption_scene.trace()['rendered_cue_ids'], 20))
            page._open_caption_editor(cue.id, 'translation')
            check('translation_editor_opened', wait(lambda: page._caption_draft is not None
                and page._caption_draft.target.cue_id == cue.id and page._caption_draft.target.layer == 'translation', 10))
            editor = page.subtitle_edit_input
            before = editor.toPlainText()
            updated = before + ' [playback-check]'
            editor.setFocus()
            editor.setPlainText(updated)
            QTest.keyClick(editor, Qt.Key.Key_Return)
            check('translation_edit_committed', wait(lambda: page.project.generation_metadata.get('translations', {}).get(cue.id) == updated, 25))
            page.select_cue(cue.id)
            page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
            page.style_layer.setCurrentIndex(page.style_layer.findData('translation'))
            QTest.qWait(200)
            page.style_font.commit_family('Arial')
            check('font_committed', wait(lambda: effective_layer_style(page.project, cue, 'translation').font_family == 'Arial', 25))
            old_size = effective_layer_style(page.project, cue, 'translation').font_size
            page.style_font_size.setValue(int(old_size)+3)
            page.style_font_size.editingFinished.emit()
            check('font_size_committed', wait(lambda: effective_layer_style(page.project, cue, 'translation').font_size == int(old_size)+3, 25))
            old_bold = effective_layer_style(page.project, cue, 'translation').bold
            page.style_bold.click()
            check('style_committed', wait(lambda: effective_layer_style(page.project, cue, 'translation').bold != old_bold, 25))
            key = companion_id(cue.id)
            def refreshed():
                from ..subtitle_rules.punctuation_style import style_translations
                displayed = style_translations(page.project.studio_state, {cue.id: updated})[cue.id]
                prepared = page._prepared_caption(key)
                scene = getattr(page, '_caption_scene', None)
                if prepared is None or scene is None:
                    result['refresh_observed'] = {'prepared': prepared is not None, 'scene': scene is not None}
                    return False
                row = next((row for row in scene.trace().get('cue_pixels', []) if row['cue_id'] == key), None)
                result['refresh_observed'] = dict(prepared=True, scene=True,
                    text_matches=prepared.snapshot.text == displayed, text_length=len(prepared.snapshot.text),
                    expected_length=len(displayed), font_family=prepared.snapshot.font_family,
                    font_size=prepared.snapshot.font_size, row_present=row is not None,
                    hash_matches=bool(row and row.get('snapshot_hash') == prepared.snapshot_hash),
                    bounds=row.get('bounds') if row else None, alpha_nonzero=row.get('alpha_nonzero') if row else None)
                return (prepared.snapshot.text == displayed and prepared.snapshot.font_family == 'Arial'
                        and row is not None and row.get('snapshot_hash') == prepared.snapshot_hash
                        and row.get('bounds') and row.get('alpha_nonzero', 0) > 0)
            page._present_caption_scene()
            check('paused_edited_layer_rerendered_with_precise_geometry', wait(refreshed, 12))
            _capture(window, output/'paused-edited.png')
            scene = page._caption_scene
            timer = time.perf_counter()
            page._toggle_playback()
            QTest.qWait(3000)
            check('resume_advances', not page.video._paused and page.video.playback_position_snapshot().presentation_media_ms > position+300)
            result['measurements']['resume_three_seconds_wall_ms'] = (time.perf_counter()-timer)*1000
            result['measurements']['motion_preheat_before_close'] = scene._motion_preheater.stats()
            check('motion_preheat_worker_started', scene._motion_preheater.thread is not None)
            page._toggle_playback()
            check('pause_again', bool(page.video._paused))
            page.undo_stack.setClean()
            page._close_project_session('large-playback-interaction-audit')
            check('project_released', page.project is None)
            check('scene_worker_stopped', wait(lambda: not scene.thread.is_alive(), 10))
            check('motion_preheat_worker_stopped', wait(lambda: scene._motion_preheater.thread is None or not scene._motion_preheater.thread.is_alive(), 10))
            result['passed'] = all(result['checks'].values())
        except BaseException:
            result['error'] = traceback.format_exc()
        finally:
            save()
            QApplication.instance().aboutToQuit.connect(lambda: (result.update(gui_shutdown=True), save()))
            page.undo_stack.setClean()
            window.result_exit_code = 0 if result['passed'] else 1
            window.close()
    QTimer.singleShot(250, execute)
