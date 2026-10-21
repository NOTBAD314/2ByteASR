"""Isolated actual-window input, lifecycle and recovery acceptance.

Fixtures contain deterministic recognition-shaped evidence, never user media.
Synthetic queued keys are timestamped at post time. Native IME hardware is not
claimed: input-method tests exercise Qt preedit/commit events only.
"""
from .studio_acceptance_audit import require
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback


def install_call_probe():
    """Acceptance-only bounded timings. No transcript, paths or arguments."""
    from collections import defaultdict, deque
    from functools import wraps
    from ..studio.studio_ass_flow import StudioAssFlowMixin
    from ..studio.studio_canvas_edit import StudioCanvasEditMixin
    from ..rendering.caption_scene import CaptionScene
    from ..projects.studio_revisions import StudioRevisionStore
    from ..playback.playback_gc_budget import PlaybackGcBudget, ProjectHeapPolicy
    samples = defaultdict(lambda: deque(maxlen=2048))
    totals = defaultdict(lambda: [0, 0.0, 0.0])
    def attach(cls, name):
        original = getattr(cls, name)
        @wraps(original)
        def measured(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter()-started)*1000
                key = cls.__name__+'.'+name+(' GUI' if threading.current_thread() is threading.main_thread() else ' worker')
                samples[key].append(elapsed)
                row = totals[key]; row[0] += 1; row[1] += elapsed; row[2] = max(row[2], elapsed)
        setattr(cls, name, measured)
    for cls, names in ((StudioAssFlowMixin, ('_ass_preview_revision', '_ass_ready')),
                       (StudioCanvasEditMixin, ('_flush_edit_preview', '_commit_canvas_inline_edit')),
                       (CaptionScene, ('present', 'prepare', 'scene_items')),
                       (PlaybackGcBudget, ('_collect_paused',)),
                       (ProjectHeapPolicy, ('settle',)),
                       (StudioRevisionStore, ('_capture_render', '_capture_persistence', '_frozen_studio_state'))):
        for name in names: attach(cls, name)
    def snapshot():
        from ..diagnostics.editor_diagnostics import latency_stats
        return {k:dict(**latency_stats(v),total_count=totals[k][0],total_ms=totals[k][1],all_max_ms=totals[k][2]) for k,v in samples.items()}
    return snapshot

def prepare_fixtures(root, output):
    from ..system.processes import run_hidden_subprocess
    from ..projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, hydrate_media_contract
    from ..studio.studio_helpers import probe_media_identity
    output.mkdir(parents=True, exist_ok=True)
    media = output / 'sample.mp4'
    if not media.exists():
        short = output / 'two-seconds.mp4'
        ffmpeg = str(root / 'tools/ffmpeg/bin/ffmpeg.exe')
        run_hidden_subprocess([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30:duration=2', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30', '-an', str(short)], purpose='isolated edit fixture', capture_output=True, check=True, timeout=30)
        run_hidden_subprocess([ffmpeg, '-v', 'error', '-y', '-stream_loop', '10000', '-i', str(short), '-c', 'copy', '-t', '20002', str(media)], purpose='long edit fixture', capture_output=True, check=True, timeout=60)
    for size in (100, 500, 511, 2000, 10000):
        path = output / f'{size}.2byteproj'
        if path.exists():
            continue
        text = '测试字幕 日本語 ABC'
        cues = [StudioCue(f'c{i}', i * 2000, i * 2000 + 1800, text, evidence_refs=[f'e{i}']) for i in range(size)]
        evidence = {f'e{i}': dict(text=text, words=[dict(text=w, start_ms=i * 2000 + j * 400, end_ms=i * 2000 + (j + 1) * 400) for (j, w) in enumerate(('测试', '字幕', '日本語', 'ABC'))]) for i in range(size)}
        project = SubtitleProject(media=StudioMedia(str(media), duration_ms=20002000, width=640, height=360), cues=cues, asr_evidence=evidence)
        if size in (500, 511, 2000):
            from ..projects.studio_project import StudioSpeaker
            project.speakers = [StudioSpeaker(id=f'S0{i}', name=f'Speaker {i}') for i in (1, 2, 3)]
            for i, cue in enumerate(cues):
                cue.speaker_id = 'S03' if i % 255 == 254 else f'S0{1+i%2}'
                cue.text = "Let's move over there."
                evidence[f'e{i}']['text'] = cue.text
                evidence[f'e{i}']['words'] = [dict(text=w, start_ms=i*2000+j*350,
                    end_ms=i*2000+(j+1)*350) for j,w in enumerate(("Let's", 'move', 'over', 'there.'))]
            project.generation_metadata = {'translations': {c.id:'我們往那邊走。' for c in cues}, 'task_language':'en'}
            project.studio_state = {'bilingual': {'mode':'bilingual'}}
        hydrate_media_contract(project, probe_media_identity(str(media)))
        project.validate()
        save_project(project, path)

def install_counterfactual(directory):
    """Run saved pre-change functions in the same measured window/instrumentation."""
    import ast
    from ..projects import studio_revisions
    from ..studio.studio_canvas_edit import StudioCanvasEditMixin
    from ..rendering import ass_compile_actor
    tasks = [('twobyteasr/projects/studio_revisions.py', studio_revisions, studio_revisions.StudioRevisionStore, ['_freeze_studio_state_sharing']), ('twobyteasr/studio/studio_canvas_edit.py', sys.modules[StudioCanvasEditMixin.__module__], StudioCanvasEditMixin, ['_queue_edit_preview']), ('twobyteasr/projects/studio_revisions.py', studio_revisions, studio_revisions.SubtitleRenderRevision, ['compile_key']), ('twobyteasr/projects/studio_revisions.py', studio_revisions, studio_revisions.StudioRevisionStore, ['_capture_persistence']), ('twobyteasr/rendering/ass_compile_actor.py', ass_compile_actor, ass_compile_actor.AssCompileActor, ['_compile'])]
    for (relative, module, cls, names) in tasks:
        tree = ast.parse((directory / relative).read_text('utf-8-sig'))
        owner = tree if cls is None else next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls.__name__))
        for name in names:
            node = next((n for n in owner.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name))
            namespace = dict(vars(module))
            exec(compile(ast.Module(body=[node], type_ignores=[]), relative, 'exec'), namespace)
            if cls is None:
                setattr(module, name, namespace[name])
            else:
                setattr(cls, name, namespace[name])

def install_core_counterfactual(source):
    """Two pre-fix costs under the same current instrumentation, not an old EXE."""
    import ast, hashlib
    from ..projects import studio_project
    from ..studio import studio_ui
    from ..studio.studio_readiness import StudioReadiness
    raw = Path(source).read_bytes()
    tree = ast.parse(raw.decode('utf-8-sig'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'save_autosave_revision')
    namespace = dict(vars(studio_project))
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    studio_project.save_autosave_revision = namespace['save_autosave_revision']
    studio_ui.save_autosave_revision = namespace['save_autosave_revision']
    def warm_unconditionally(self, epoch):
        from ..subtitle_rules.stutter_cleanup import warm_text_analysis
        warm_text_analysis()
    StudioReadiness._warm_text_analysis = warm_unconditionally
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(),
                scope='pre-fix autosave function plus unconditional 1500 ms warmup; other code and diagnostics current')


def run(output, *, window):
    from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, Qt, QTimer
    from PySide6.QtGui import QKeyEvent, QInputMethodEvent, QTextCursor
    from PySide6.QtTest import QTest
    from ..diagnostics.editor_diagnostics import latency_stats, export_bundle, root_dir, record
    from ..projects.studio_project import load_project
    from .blank_project_audit import _capture
    import psutil
    fixture = Path(os.environ['TWOBYTEASR_EDITOR_FIXTURES'])
    mode = os.environ.get('TWOBYTEASR_EDITOR_MODE', 'paused')
    size = int(os.environ.get('TWOBYTEASR_EDITOR_SIZE', '100'))
    baseline = os.environ.get('TWOBYTEASR_EDITOR_BASELINE')
    if baseline:
        install_counterfactual(Path(baseline))
    core_source = os.environ.get('TWOBYTEASR_EDITOR_CORE_BASELINE')
    core_baseline = install_core_counterfactual(core_source) if core_source else None
    page = window.studio_page
    control = os.environ.get('TWOBYTEASR_EDITOR_CONTROL', 'none')
    if control == 'no-lexicon':
        from ..subtitle_rules import stutter_cleanup
        stutter_cleanup.warm_text_analysis = lambda: None
    if control == 'no-draft':
        page._draft_recovery.changed = lambda: None
    call_probe = install_call_probe() if os.environ.get('TWOBYTEASR_EDITOR_CALLS') == '1' else None
    if baseline:
        page._draft_recovery.changed = lambda : None
    window.resize(1440, 900)
    window.show()
    from ..diagnostics.build_identity import load_build_identity
    result = dict(passed=False, pid=os.getpid(), size=size, word_units=size * 4, mode=mode, frozen=bool(getattr(sys, 'frozen', False)), identity=load_build_identity().to_dict(), baseline='saved pre-change freeze/cache/IPC/preview functions; draft journal disabled as before' if baseline else False, measurement='postEvent Windows tick timestamp -> Qt paintEvent completion; not physical scanout', fixture='deterministic recognition-shaped evidence, H264 640x360 30fps CFR, no audio', ime='Qt synthetic preedit/commit only; real installed input methods not covered', cases=[])

    def save():
        result['core_baseline'] = core_baseline
        result['control'] = control
        result['diagnostics'] = os.environ.get('TWOBYTEASR_EDITOR_DIAGNOSTICS', '1')
        if call_probe: result['call_probe'] = call_probe()
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def wait(predicate, seconds=60):
        end = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() > end:
                raise TimeoutError('editor acceptance condition timed out')
            QTest.qWait(20)

    def resource():
        from PySide6.QtCore import QObject
        from PySide6.QtWidgets import QWidget
        qt_objects = page.findChildren(QObject)
        process = psutil.Process()
        children = process.children(recursive=True)
        cpu = process.cpu_times(); io = process.io_counters()
        from ..studio.studio_performance import _pending_work, _gui_loop_stats
        return dict(monotonic=time.monotonic(), rss_mb=round(process.memory_info().rss / 1024 ** 2, 2),
                    cpu_s=cpu.user+cpu.system, read_bytes=io.read_bytes, write_bytes=io.write_bytes,
                    handles=process.num_handles(), threads=process.num_threads(),
                    qt_objects=len(qt_objects), qt_widgets=sum(isinstance(x, QWidget) for x in qt_objects),
                    mpv=sum((p.name().lower() == 'mpv.exe' for p in children if p.is_running())), children=len(children),
                    work=_pending_work(page), loop=_gui_loop_stats(),
                    ass=page._ass_actor.diagnostic_state() if page._ass_actor else {},
                    pending=page.video.controller.actor_status() if page.video.controller else {})

    def open_project(path):
        window.open_studio_project(path, mode='edit', source='editor_diagnostics_audit')
        wait(lambda : page.project is not None and page._readiness.ready)
        page.video.set_paused(True)
        QTest.qWait(600)

    def edit():
        page.select_cue('c0')
        page._begin_canvas_inline_edit()
        wait(lambda : page.subtitle_edit_input.isVisible() and page._canvas_editor is not None, 5)
        QTest.qWait(150)
        return page.subtitle_edit_input

    def post_keys(editor, name, specs, interval=0.025):
        profiler = None
        if os.environ.get('TWOBYTEASR_EDITOR_PROFILE') == '1':
            import cProfile
            profiler = cProfile.Profile()
            profiler.enable()
        editor.input_measurements.clear()
        editor._input_pending.clear()
        kernel = ctypes.WinDLL('kernel32')
        kernel.GetTickCount64.restype = ctypes.c_ulonglong
        errors = []

        def produce():
            try:
                for (key, text, mods) in specs:
                    event = QKeyEvent(QEvent.Type.KeyPress, key, mods, text)
                    event.setTimestamp(int(kernel.GetTickCount64()) & 4294967295)
                    QCoreApplication.postEvent(editor, event)
                    time.sleep(interval)
            except Exception:
                errors.append(traceback.format_exc())
        thread = threading.Thread(target=produce, daemon=True)
        thread.start()
        wait(lambda : not thread.is_alive(), 40)
        QTest.qWait(700)
        if profiler is not None:
            profiler.disable()
            profiler.dump_stats(str(output / f'{name}.pstats'))
        require(not errors, errors)
        values = list(editor.input_measurements)
        require(len(values) >= len(specs) * 0.9, (name, len(values), len(specs)))
        row = dict(name=name, stats=latency_stats([v['total_ms'] for v in values]), queue=latency_stats([v['queue_ms'] for v in values if v['queue_ms'] is not None]), paint=latency_stats([v['paint_ms'] for v in values]), samples=values)
        row['target_passed'] = row['stats']['p95_ms'] <= 50
        result['cases'].append(row)
        if not name.startswith('soak-'): save()
    try:
        path = output / f'{size}.2byteproj'
        path.write_bytes((fixture / f'{size}.2byteproj').read_bytes())
        open_project(path)
        result['initial_resources'] = resource()
        if mode == 'no-player':
            require(page.video.controller is None and result['initial_resources']['mpv'] == 0, 'acceptance requirement failed')
        editor = edit()
        if mode in ('playing', 'no-preview', 'hwdec-no', 'vo-gpu'):
            page.video.set_paused(False)
            wait(lambda : not page.video._paused, 8)
        controller = page.video.controller
        result['player_actual'] = controller.observed_properties() if controller else None
        plain = Qt.KeyboardModifier.NoModifier
        previews_before = len(page._ass_profile)
        post_keys(editor, 'continuous', [(Qt.Key.Key_X, 'x', plain)] * 120)
        result['continuous_preview_completions'] = len(page._ass_profile) - previews_before
        post_keys(editor, 'backspace', [(Qt.Key.Key_Backspace, '', plain)] * 100)
        editor.selectAll()
        post_keys(editor, 'selection_replace', [(Qt.Key.Key_Y, 'y', plain)] + [(Qt.Key.Key_Z, 'z', plain)] * 39)
        cursor = editor.textCursor()
        before = editor.toPlainText()
        QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(editor, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        require(editor.toPlainText() == before, 'local undo/redo changed final text')
        mime = QMimeData()
        mime.setText('第一行\n日本語 {\\}\\N & <字幕>')
        editor.selectAll()
        editor.insertFromMimeData(mime)
        QTest.qWait(200)
        require(editor.toPlainText() == mime.text(), 'acceptance requirement failed')
        editor.selectAll()
        pre = QInputMethodEvent('にほん', [])
        QCoreApplication.sendEvent(editor, pre)
        confirm = QInputMethodEvent()
        confirm.setCommitString('日本語')
        QCoreApplication.sendEvent(editor, confirm)
        QTest.qWait(150)
        require('日本語' in editor.toPlainText(), 'acceptance requirement failed')
        target = '确认字幕 中文\n日本語 {\\} & <>'
        editor.setPlainText(target)
        QTest.qWait(300)
        _capture(window, output / 'editing.png')
        page.video.set_paused(True)
        page._commit_canvas_inline_edit()
        require(page._cue_lookup['c0'].text == target, 'acceptance requirement failed')
        page.undo_stack.undo()
        require(page._cue_lookup['c0'].text != target, 'acceptance requirement failed')
        page.undo_stack.redo()
        require(page._cue_lookup['c0'].text == target, 'acceptance requirement failed')
        page.project_path = output / 'saved.2byteproj'
        page.save()
        reopened = load_project(page.project_path)
        require(reopened.cues[0].text == target, 'acceptance requirement failed')
        require(len(reopened.asr_evidence) == size, 'acceptance requirement failed')
        require(reopened.asr_evidence['e0']['words'] == page.project.asr_evidence['e0']['words'], 'acceptance requirement failed')
        require(reopened.cues[0].speaker_id == page.project.cues[0].speaker_id, 'acceptance requirement failed')
        result['roundtrip'] = dict(text=True, word_evidence=True, speaker=True, timeline=reopened.studio_state.get('caption_timeline') == page.project.studio_state.get('caption_timeline'))
        require(result['roundtrip']['timeline'], 'acceptance requirement failed')
        page.video.seek(.5, project_ms=500)
        QTest.qWait(800)
        _capture(window, output / 'committed.png')
        result['cycles'] = []
        result['seek_during_edit'] = []
        cycles = int(os.environ.get('TWOBYTEASR_EDITOR_CYCLES', '3'))
        for cycle in range(cycles):
            editor = edit()
            if mode in ('playing', 'no-preview', 'hwdec-no', 'vo-gpu'):
                page.video.set_paused(False)
                wait(lambda : not page.video._paused, 8)
                if cycle % 5 == 0:
                    def seek_during_input(cycle=cycle):
                        target_ms = 500 if cycle % 10 == 0 else 1500
                        page.video.seek(target_ms / 1000.0, project_ms=target_ms)
                        result['seek_during_edit'].append(dict(cycle=cycle, target_ms=target_ms,
                            editor_active=page._canvas_editor is not None))
                    QTimer.singleShot(150, seek_during_input)
            post_keys(editor, f'cycle-{cycle}', [(Qt.Key.Key_X, 'x', plain)] * 20)
            page._cancel_canvas_inline_edit()
            if cycle % 2 == 1:
                page.undo_stack.setClean()
                open_project(path)
            result['cycles'].append(resource())
        soak_seconds = int(os.environ.get('TWOBYTEASR_EDITOR_SOAK_SECONDS', '0'))
        if soak_seconds:
            import uuid
            from ..diagnostics import editor_diagnostics as diagnostic_module
            from ..projects.studio_project import save_project
            paths = [output/'soak-A.2byteproj', output/'soak-B.2byteproj']
            for index, destination in enumerate(paths):
                other = load_project(fixture/f'{size}.2byteproj')
                other.project_id = uuid.uuid4().hex
                other.cues[0].text = f'Project {index} initial source'
                save_project(other, destination)
            soak_start = time.monotonic()
            reopen_goal = int(os.environ.get('TWOBYTEASR_EDITOR_REOPENS', '20'))
            require(0 < reopen_goal <= 100 and 0 < soak_seconds <= 3600, 'bounded soak parameters')
            result['soak'] = dict(requested_seconds=soak_seconds, reopens=[], operations=0, resources=[], commands=[])
            soak = result['soak']
            # Acceptance explicitly renews recording at each ten-minute boundary.
            # Keep a bounded stack budget for those windows too; the normal
            # application remains capped at 400 records for the whole process.
            from ..diagnostics import gui_stall_watchdog
            gui_stall_watchdog.MAX_RECORDS = 400 * ((soak_seconds + 599) // 600)
            soak['watchdog_stack_budget'] = gui_stall_watchdog.MAX_RECORDS
            iteration = 0
            next_reopen = soak_start
            while time.monotonic()-soak_start < soak_seconds:
                recorder = diagnostic_module._INSTANCE
                # Explicit acceptance only: each recording window remains ten
                # minutes; the soak deliberately starts another at expiry.
                if recorder is not None and not recorder.recording: recorder.start_recording()
                if len(soak['reopens']) < reopen_goal and time.monotonic() >= next_reopen:
                    page.video.set_paused(True)
                    if not page.undo_stack.isClean(): page.save()
                    require(page.show_project_hub(), 'leave for project library failed')
                    require(page.project is None, 'library retained live project')
                    opening = time.monotonic()
                    open_project(paths[len(soak['reopens']) % 2])
                    soak['reopens'].append(dict(elapsed_s=time.monotonic()-soak_start,
                                               open_ms=(time.monotonic()-opening)*1000,
                                               project_id=page.project.project_id))
                    next_reopen = soak_start + len(soak['reopens'])*soak_seconds/reopen_goal
                page.video.seek(.5, project_ms=500)
                editor = edit()
                page.video.set_paused(iteration % 3 == 0)
                original = page._cue_lookup['c0'].text
                QTest.keyClick(editor, Qt.Key.Key_End)
                specs = [(Qt.Key.Key_X, 'x', plain)]*12 + [(Qt.Key.Key_Backspace, '', plain)]*6
                post_keys(editor, f'soak-{iteration}', specs)
                if iteration % 4 == 0:
                    # Hold a real draft through the five-second recovery timer.
                    QTest.qWait(5500)
                if iteration % 3:
                    expected = editor.toPlainText()
                    started = time.monotonic()
                    page._commit_canvas_inline_edit()
                    elapsed = (time.monotonic()-started)*1000
                    require(page._cue_lookup['c0'].text == expected, 'soak edit lost')
                    undo_text = None
                    for undo_cycle in range(3):
                        page.undo_stack.undo()
                        # Consecutive text commands may legitimately merge.
                        # Verify a stable undo state and exact redo content.
                        if undo_cycle == 0: undo_text = page._cue_lookup['c0'].text
                        require(page._cue_lookup['c0'].text == undo_text, 'soak undo state changed across redo')
                        page.undo_stack.redo()
                        require(page._cue_lookup['c0'].text == expected, 'soak redo lost')
                    soak['commands'].append(dict(operation='commit_model_only', duration_ms=elapsed))
                    if iteration % 5 == 1:
                        page.save()
                        require(load_project(page.project_path).cues[0].text == expected, 'soak saved wrong version')
                else:
                    page._cancel_canvas_inline_edit()
                    require(page._cue_lookup['c0'].text == original, 'soak cancel mutated source')
                QTest.qWait(1000 if iteration % 4 else 3000)
                soak['resources'].append(resource())
                iteration += 1
                soak['operations'] = iteration
                soak['elapsed_seconds'] = time.monotonic()-soak_start
                if iteration % 5 == 0: save()
            require(len(soak['reopens']) == reopen_goal, 'not enough completed reopen cycles')
            soak['input_stats'] = latency_stats([s['total_ms'] for row in result['cases']
                if row['name'].startswith('soak-') for s in row['samples']])
            soak['commit_model_stats'] = latency_stats([r['duration_ms'] for r in soak['commands']])
            page.video.set_paused(True)
            page.save()
            _capture(window, output/'soak-final.png')
        # Actual support dialog controls and screenshot; no file picker or upload.
        if os.environ.get('TWOBYTEASR_EDITOR_DIAGNOSTICS', '1') != '0':
            from PySide6.QtWidgets import QCheckBox
            from ..diagnostics.diagnostics_report import open_diagnostics_dialog
            from ..diagnostics.editor_diagnostics import recording_active, install_early
            dialog = open_diagnostics_dialog(window)
            require(dialog is not None and dialog.objectName() == 'diagnosticsDialog', 'support dialog absent')
            detail = dialog.findChild(QCheckBox, 'diagnosticDetailedMode')
            require(detail is not None, 'detailed recording control absent')
            detail.setChecked(True)
            require(recording_active(), 'detailed recording did not start')
            detail.setChecked(False)
            require(not recording_active(), 'detailed recording did not stop')
            require(install_early().standard_recording, 'standard evidence stopped with detailed recording')
            detail.setChecked(True)
            require(recording_active(), 'detailed recording did not restart')
            QTest.qWait(150)
            _capture(dialog, output/'diagnostics-dialog.png')
            dialog.accept()
        result['final_resources'] = resource()
        if mode == 'no-player':
            require(result['final_resources']['mpv'] == 0, 'acceptance requirement failed')
        if os.environ.get('TWOBYTEASR_EDITOR_DIAGNOSTICS', '1') == '0':
            result['bundle'] = False
            result['bundle_status'] = 'not_run_diagnostics_disabled'
        else:
            export_bundle(output / 'diagnostic.zip')
            result['bundle'] = True
        result['passed'] = all((row['target_passed'] for row in result['cases']))
        result['behavior_passed'] = True
        result['diagnostic_root'] = str(root_dir())
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        if getattr(page, '_canvas_editor', None) is not None:
            page._cancel_canvas_inline_edit()
        page.undo_stack.setClean()
        save()
    return 0 if result['passed'] else 1

def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(output, window=window)
        except Exception:
            (output / 'result.json').write_text(json.dumps(dict(passed=False, error=traceback.format_exc())), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            path = output / 'result.json'
            result = json.loads(path.read_text('utf8'))
            result['gui_shutdown'] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100, execute)
