"""Representative cleanup cases after the unchanged original repeat matrix.

Uses only copied fixture projects, fixed request_text_cleanup results, actual
dialog controls, normal manual save and a real project close/reopen boundary.
"""
from dataclasses import asdict
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import math
from pathlib import Path
import time


@contextmanager
def observe_project_open_entry(controller):
    """Observe one slots-based controller without assigning to its instance.

    The wrapper preserves every other controller's behavior and records only
    calls whose self is this exact target. Nested scopes restore in stack order.
    """
    owner = type(controller)
    original = owner.open_project_entry
    calls = []

    @wraps(original)
    def observed(self, target, *args, **kwargs):
        if self is controller:
            calls.append(str(Path(target).resolve()))
        return original(self, target, *args, **kwargs)

    owner.open_project_entry = observed
    try:
        yield calls
    finally:
        owner.open_project_entry = original


def content_receipt(project):
    from ..subtitle_rules.subtitle_translation import snapshot
    from ..caption_style.bilingual_layout import settings_from_state
    return dict(cues=[asdict(cue) for cue in project.cues],
        translations=snapshot(project), bilingual=asdict(settings_from_state(project.studio_state)),
        caption_timeline=project.studio_state.get('caption_timeline', {}),
        styles=[asdict(style) for style in project.styles], style_recipes=project.style_recipes,
        effects=project.effects)


def content_hash(project):
    return hashlib.sha256(json.dumps(content_receipt(project), ensure_ascii=False,
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def probe_schedule(source_fps, offsets=(100, 300)):
    """The small QA movies use exact frames; never loosen the seek witness."""
    fps = float(source_fps)
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('Probe source FPS must be positive and finite')
    result = []
    for value in offsets:
        milliseconds = float(value)
        frame = milliseconds*fps/1000
        if (not math.isfinite(milliseconds) or milliseconds < 0
                or not math.isclose(frame, round(frame), abs_tol=1e-7)):
            raise ValueError('AI probe time is not representable by a source frame')
        result.append(dict(relative_ms=milliseconds, relative_frame=round(frame), source_fps=fps))
    return result


def run_extended(audit, window, output, cases):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from ..projects.studio_runtime_state import state_for
    from ..studio.ai_cleanup_dialog import AiCleanupDialog, ROW_ROLE
    from ..studio.studio_text_tools import parse_cleanup_payload
    from ..projects.link_cleanup_validation import validate_cleanup_response
    from ..studio import link_caption_cleanup
    from ..caption_style.bilingual_layout import companion_id, settings_from_state
    from .caption_layout_audit import gui_layout_sample_ready, scene_sample_receipt
    from .blank_project_audit import _capture

    output = Path(output).resolve()
    results = audit.result['extended_cases'] = []
    previous_provider = link_caption_cleanup.request_text_cleanup
    current = {'count': 1}

    def fixed(project, ids, options, settings=None, **kwargs):
        available = set(ids)
        selected = [cue for cue in project.cues if cue.id in available and cue.text.strip()][:current['count']]
        payload = {'changes': [dict(cue_id=cue.id, original=cue.text, replacement=cue.text+'.',
                                   reason='标点', confidence=.99) for cue in selected]}
        return parse_cleanup_payload(validate_cleanup_response(payload, project.cues), project)

    link_caption_cleanup.request_text_cleanup = fixed
    try:
        for case in cases:
            name = case['id']
            path = Path(case['project']).resolve()
            if not path.is_relative_to(output):
                raise ValueError('Extended AI acceptance may only open its copied projects')
            folder = output / name
            folder.mkdir()
            def progress(stage, **details):
                audit.result['extended_progress'] = dict(case=name, stage=stage,
                    at=time.perf_counter(), **details)
                audit.write()
            progress('opening copied project', project=str(path))
            window.open_studio_project(str(path))
            page = window.studio_page
            yield lambda: (page.project is not None and str(page.project_path) == str(path)
                and page._readiness.ready and not page._readiness.active)
            page.video.set_paused(True)
            cue = next(cue for cue in page.project.cues if cue.text.strip())
            source_fps = float(page.video.controller.observed_properties().get('container-fps') or 0)
            audit.check(name+': fixed QA media is 30fps', math.isclose(source_fps, 30., abs_tol=1e-7), source_fps)
            probes = probe_schedule(source_fps)
            initial_ms = cue.start_ms+probes[0]['relative_ms']
            page.select_cue(cue.id)
            progress('waiting for initial exact probe frame', target_ms=initial_ms, source_fps=source_fps,
                     source_frame=round(initial_ms*source_fps/1000))
            page._seek(initial_ms/1000)
            yield lambda: gui_layout_sample_ready(page, initial_ms)
            mode = case['mode']
            if mode == 'bilingual':
                scene = scene_sample_receipt(page)
                audit.check(name+': bilingual scene is current',
                    settings_from_state(page.project.studio_state).mode == 'bilingual'
                    and scene.get('active') and scene.get('current')
                    and companion_id(cue.id) in scene.get('rendered_cue_ids', []), scene)
            animation = []
            if mode in ('legacy-motion', 'graph-motion'):
                for probe in probes:
                    relative_ms = probe['relative_ms']
                    progress('waiting for animated probe frame', target_ms=cue.start_ms+relative_ms,
                             source_fps=source_fps, source_frame=round((cue.start_ms+relative_ms)*source_fps/1000))
                    page._seek((cue.start_ms+relative_ms)/1000)
                    yield lambda at=cue.start_ms+relative_ms: gui_layout_sample_ready(page, at)
                    scene = page._caption_scene
                    receipt = scene_sample_receipt(page)
                    pixels = getattr(scene, 'published', None)
                    audit.check(name+f': actual animated scene {relative_ms}ms',
                        receipt.get('active') and receipt.get('current') and pixels is not None, receipt)
                    if pixels is None:
                        raise AssertionError('Current caption scene has not published its pixels')
                    image = pixels.image
                    layer = folder / f'actual-caption-layer-{relative_ms}ms.png'
                    image.save(str(layer))
                    animation.append(dict(probe,
                        sha256=hashlib.sha256(bytes(image.constBits())).hexdigest(),
                        file=layer.name, scene=receipt,
                        evidence='actual live caption producer pixels; not physical scanout'))
                audit.check(name+': animation pixels changed between entrance samples',
                            animation[0]['sha256'] != animation[1]['sha256'], animation)

            before = content_hash(page.project)
            original_cues = {cue.id: asdict(cue) for cue in page.project.cues}
            current['count'] = 3 if case.get('partial') else 1
            progress('generating fixed cleanup preview')
            dialog = audit.dialog = AiCleanupDialog(page, page)
            dialog.show()
            yield .2
            # The unchanged 20-round suite already covers mixed local+AI
            # regrouping. These new scene/selection cases isolate AI editing.
            for box in dialog.local_boxes.values():
                if box.isChecked():
                    QTest.mouseClick(box, Qt.MouseButton.LeftButton)
            QTest.mouseClick(dialog.ai_run_button, Qt.MouseButton.LeftButton)
            yield lambda: not dialog._cleanup_running
            audit.check(name+': fixed result reached the real preview',
                        len(dialog._preview_hits) == current['count'] and not dialog._local_splices)
            audit.check(name+': preview leaves content unchanged', content_hash(page.project) == before)
            if case.get('partial'):
                QTest.mouseClick(dialog.select_none_button, Qt.MouseButton.LeftButton)
                for index in (0, 1):
                    item = next(dialog.preview.item(row) for row in range(dialog.preview.count())
                                if tuple(dialog.preview.item(row).data(ROW_ROLE)) == ('ai', index))
                    dialog.preview.scrollToItem(item)
                    dialog.preview.setCurrentItem(item)
                    dialog.preview.setFocus()
                    QTest.keyClick(dialog.preview, Qt.Key.Key_Space)
                    audit.check(name+f': candidate {index} checked through UI', item.checkState() == Qt.CheckState.Checked)
                audit.check(name+': only requested subset is checked',
                            set(map(tuple, dialog._checked_rows())) == {('ai', 0), ('ai', 1)})
            selected_ids = {hit.cue_id for hit in dialog._checked_hits()}
            expected_text = {hit.cue_id: hit.replacement for hit in dialog._checked_hits()}
            runtime = state_for(page.project)
            before_revision, before_count = runtime.revision, page.undo_stack.count()
            progress('waiting for pre-apply exact frame', target_ms=initial_ms)
            page._seek(initial_ms/1000)
            yield lambda: gui_layout_sample_ready(page, initial_ms)
            if case.get('playing'):
                page._toggle_playback()
                start = page.timeline.playhead_ms
                yield lambda: page.timeline.playhead_ms >= start+100
            scene_before_apply = scene_sample_receipt(page)
            progress('applying checked cleanup')
            _capture(dialog, folder/'selection-before-apply.png')
            started = time.perf_counter()
            QTest.mouseClick(dialog.all_button, Qt.MouseButton.LeftButton)
            apply_ms = (time.perf_counter()-started)*1000
            audit.check(name+': one apply publishes one transaction', runtime.revision == before_revision+1)
            audit.check(name+': one apply adds one undo entry', page.undo_stack.count() == before_count+1)
            edited = content_hash(page.project)
            current_cues = {cue.id: asdict(cue) for cue in page.project.cues}
            audit.check(name+': selected changes applied', all(current_cues[key]['text'] == value for key,value in expected_text.items()))
            audit.check(name+': unchecked cue records are unchanged', all(
                current_cues.get(key) == value for key,value in original_cues.items() if key not in selected_ids))
            audit.check(name+': consumed candidates cleared', dialog.preview.count() == 0)
            page.video.set_paused(True)
            dialog.reject()
            audit.dialog = None
            yield .2
            QTest.mouseClick(page.studio_undo_button, Qt.MouseButton.LeftButton)
            audit.check(name+': single UI undo restores complete content', content_hash(page.project) == before)
            QTest.mouseClick(page.studio_redo_button, Qt.MouseButton.LeftButton)
            audit.check(name+': single UI redo reproduces complete content', content_hash(page.project) == edited)

            old_project, old_generation = page.project, page.session.generation
            progress('saving through real GUI')
            audit.check(name+': save button is visible', page.studio_save_button.isVisible())
            # Manual save runs a nested GUI progress loop. Stop only this audit
            # timer, so its generator cannot reenter while the real save runs.
            audit.timer.stop()
            try:
                QTest.mouseClick(page.studio_save_button, Qt.MouseButton.LeftButton)
            finally:
                audit.timer.start()
            yield lambda: not getattr(page, '_manual_save_in_progress', False)
            audit.check(name+': actual manual save completed', page.undo_stack.isClean() and path.is_file())
            saved_content = content_hash(page.project)
            saved_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            progress('closing saved project to library')
            QTest.mouseClick(page.studio_back_button, Qt.MouseButton.LeftButton)
            yield lambda: page.project is None and page.session.project_path is None
            audit.check(name+': real project close retired session', page.session.generation > old_generation
                        and page.undo_stack.count() == 0 and page._project_view_state == 'hub')
            controller = page.project_controller
            with observe_project_open_entry(controller) as entry_calls:
                progress('reopening saved project through GUI', saved_project=str(path))
                window.open_studio_project(str(path))
                yield lambda: (page.project is not None and page.project is not old_project
                    and str(page.project_path) == str(path) and page._readiness.ready and not page._readiness.active)
            audit.check(name+': saved project truly reopened through controller entry',
                        entry_calls == [str(path)] and page.project is not old_project)
            reopened_content = content_hash(page.project)
            audit.check(name+': GUI-reopened content equals the saved live state', reopened_content == saved_content)
            _capture(window, folder/'actual-reopened-studio.png')
            results.append(dict(id=name, mode=mode, playing=bool(case.get('playing')), partial=bool(case.get('partial')),
                source_fps=source_fps, source_probe_schedule=probes,
                selected_ids=sorted(selected_ids), apply_ms=apply_ms, scene_before_apply=scene_before_apply,
                animation=animation, saved_project=str(path), saved_sha256=saved_sha,
                saved_content_sha256=saved_content, reopened_content_sha256=reopened_content,
                old_project_object_id=id(old_project), reopened_project_object_id=id(page.project),
                before_generation=old_generation, reopened_generation=page.session.generation,
                open_project_entry_calls=entry_calls, real_gui_reopened=True, passed=True))
            progress('completed')
            audit.write()
    finally:
        link_caption_cleanup.request_text_cleanup = previous_provider
