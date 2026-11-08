"""Continuous E editing and async persistence through the normal Studio."""
import json
import os
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt, QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.save_trace import SaveTrace
    app = QApplication.instance()
    result = dict(passed=False, checks={}, edits=[], saves=[], preview_samples=[], timelines=[])
    from ..diagnostics.build_identity import launch_identity_payload
    result['build_identity'] = launch_identity_payload()
    result['scope'] = 'normal MainWindow on private desktop, synthetic Qt input, prepared preview receipt'
    pending_previews = []
    ticks = []
    previous_tick = [time.perf_counter()]
    timer = QTimer(window)
    timer.setInterval(10)

    def heartbeat():
        now = time.perf_counter()
        ticks.append((now-previous_tick[0])*1000)
        previous_tick[0] = now
        page = window.studio_page
        for pending in pending_previews[:]:
            caption = page._prepared_caption(pending['render_id'])
            if caption is not None and caption.snapshot.text == pending['text']:
                result['preview_samples'].append(dict(cue_id=pending['cue_id'],
                    prepared_ms=(now-pending['started'])*1000))
                pending_previews.remove(pending)
    timer.timeout.connect(heartbeat)

    def receipt():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name, value):
        result['checks'][name] = bool(value)
        receipt()
        if not value:
            raise AssertionError(name)
    def wait(predicate, timeout=45):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            if predicate():
                return
            app.processEvents()
            time.sleep(.002)
        raise TimeoutError('edit/save wait')
    def idle(page):
        queue = getattr(page,'_persistence_queue',None)
        return queue is None or not queue.busy

    def run():
        page = window.studio_page
        try:
            from ..projects.studio_project import load_project
            from ..caption_style.bilingual_layout import companion_id
            window._switch_page(page)
            opened_at = time.perf_counter()
            page.project_controller.open_project_entry(os.environ['EDIT_SAVE_PROJECT'],single_shot_fn=QTimer.singleShot,skip_dirty_guard=True)
            wait(lambda:page.project is not None and page._readiness.ready,90)
            wait(lambda:page._readiness.loading.state == 'ready'
                 and not page._readiness.overlay.isVisible(),30)
            app.processEvents()
            check('workspace visibly presented', page.isVisible() and page.timeline.isVisible())
            result['open_ms'] = (time.perf_counter()-opened_at)*1000
            page.video.set_paused(True)
            check('real project opened',len(page.project.cues)>=5555)
            controller_type = type(page.project_controller)
            original_save = controller_type.save
            manual_requests = []
            def counted_save(controller,*args,**kwargs):
                manual_requests.append(time.perf_counter())
                if os.environ.get('EDIT_SAVE_BASELINE'):
                    trace = SaveTrace()
                    with trace.activate(),trace.observe_gc(),trace.span('request_to_ack'):
                        value = original_save(controller,*args,**kwargs)
                    result['timelines'].append(trace.payload())
                    return value
                return original_save(controller,*args,**kwargs)
            controller_type.save = counted_save
            preferences = dict(page._studio_preferences())
            preferences.update(autosave_enabled=True,autosave_interval_seconds=30,autosave_idle_seconds=3)
            page._studio_preferences = lambda:dict(preferences)
            timer.start()
            cues = list(page.project.cues[:30])
            started_all = time.perf_counter()
            part = os.environ.get('EDIT_SAVE_PART', 'edits')
            if part == 'reliability':
                reliability(page, output, check, wait, idle, result)
                result['passed'] = all(result['checks'].values())
                return
            for number,cue in enumerate(cues if part == 'edits' else []):
                layer = 'original' if number<15 else 'translation'
                preferences['caption_default_layer'] = layer
                page.select_cue(cue.id)
                page._seek((cue.start_ms+min(100,(cue.end_ms-cue.start_ms)//2))/1000)
                wait(lambda:cue.start_ms<=page.timeline.playhead_ms<cue.end_ms,10)
                page.timeline.setFocus()
                QTest.keyClick(page.timeline,Qt.Key_E)
                wait(lambda:getattr(page,'_caption_draft',None) is not None)
                app.processEvents()
                draft = page._caption_draft
                check(f'E target {number}',draft.target.cue_id==cue.id and draft.target.layer==layer)
                before_index = page.undo_stack.index()
                value = draft.before+f' 验收{number}'
                page.subtitle_edit_input.setFocus()
                page.subtitle_edit_input.setPlainText(value)
                paused = page.video._paused
                ticks.clear()
                previous_tick[0] = time.perf_counter()
                began = time.perf_counter()
                profiler = None
                if os.environ.get('EDIT_SAVE_PROFILE'):
                    import cProfile
                    profiler = cProfile.Profile()
                    profiler.enable()
                if number%3==0:
                    QTest.keyClick(page.subtitle_edit_input,Qt.Key_Return)
                    trigger = 'enter'
                elif number%3==1:
                    QTest.mouseClick(page.timeline,Qt.LeftButton,pos=page.timeline.rect().center())
                    trigger = 'blank'
                else:
                    from PySide6.QtGui import QFocusEvent
                    QApplication.setActiveWindow(window)
                    window.activateWindow()
                    page.timeline.setFocus()
                    QTest.qWait(10)
                    QApplication.sendEvent(page.subtitle_edit_input,QFocusEvent(QEvent.Type.FocusOut,Qt.TabFocusReason))
                    trigger = 'focus'
                    result['focus_evidence'] = dict(active=type(QApplication.activeWindow()).__name__,
                        focused=type(QApplication.focusWidget()).__name__,following=page._caption_following)
                    if os.environ.get('EDIT_SAVE_BASELINE'):
                        QTest.keyClick(page.subtitle_edit_input,Qt.Key_Return)
                        trigger = 'legacy-focus-then-enter'
                handler_ms = (time.perf_counter()-began)*1000
                if profiler is not None:
                    profiler.disable()
                    profiler.dump_stats(str(output/f'edit-{number}.pstats'))
                wait(lambda:not getattr(page,'_caption_following',False))
                ready_ms = (time.perf_counter()-began)*1000
                check(f'single command {number}',page.undo_stack.index()==before_index+1)
                check(f'committed value {number}',draft.target.read(page.project)==value)
                check(f'playback state {number}',page.video._paused==paused)
                check(f'editable after confirm {number}',page.isEnabled() and app.activeModalWidget() is None)
                result['edits'].append(dict(number=number,layer=layer,trigger=trigger,
                    handler_ms=handler_ms,ready_ms=ready_ms,max_gui_gap_ms=max(ticks,default=ready_ms)))
                pending_previews.append(dict(cue_id=cue.id,render_id=companion_id(cue.id) if layer=='translation' else cue.id,
                    text=value,started=began))
                if number==12:
                    # Resume editing while the real recovery writer is active.
                    page._autosave_timer.stop()
                    page._autosave_deadline.last_edit_at=time.monotonic()-3.1
                    page._autosave()
                QTest.qWait(8)
            result['continuous_edit_ms']=(time.perf_counter()-started_all)*1000
            result['manual_requests_during_E']=len(manual_requests)
            if not os.environ.get('EDIT_SAVE_BASELINE'):
                check('E has zero formal save requests',not manual_requests)
            page.grab().save(str(output/'after-thirty.png'))
            # No-change and cancellation preserve the undo history.
            for cancel in ((False,True) if part == 'edits' else ()):
                page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E)
                wait(lambda:page._caption_draft is not None)
                before = page.undo_stack.index()
                if cancel:
                    page.subtitle_edit_input.setPlainText('discarded draft')
                    page._cancel_canvas_inline_edit()
                else:
                    page._commit_canvas_inline_edit()
                check('cancel keeps undo' if cancel else 'unchanged keeps undo',page.undo_stack.index()==before)
            # Explicit save variants. Keep the target path fixed across runs.
            if part == 'edits':
                preferences['caption_default_layer'] = 'translation'
                page.timeline.setFocus()
                QTest.keyClick(page.timeline,Qt.Key_E)
                wait(lambda:page._caption_draft is not None)
                app.processEvents()
                draft = page._caption_draft
                before = page.undo_stack.index()
                generation = page._autosave_generation
                page.subtitle_edit_input.setPlainText(draft.before+' \n')
                page._commit_canvas_inline_edit()
                check('translation normalized no-change closes',not page._caption_following)
                check('translation normalized no-change has no undo',page.undo_stack.index()==before)
                check('translation normalized no-change has no autosave request',page._autosave_generation==generation)
                page.timeline.setFocus()
                QTest.keyClick(page.timeline,Qt.Key_E)
                wait(lambda:page._caption_draft is not None)
                app.processEvents()
                draft = page._caption_draft
                value = draft.before+' 空白验收'
                page.subtitle_edit_input.setPlainText(' '+value+' \n')
                page._commit_canvas_inline_edit()
                check('translation trim submits once',page.undo_stack.index()==before+1)
                check('translation trim stores expected value',draft.target.read(page.project)==value)
            for case in ('cold-formal','unchanged','two-edits','batch-thirty'):
                if case in ('cold-formal','two-edits','batch-thirty'):
                    for cue in cues[:30 if case=='batch-thirty' else 2]:
                        page.cue_controller.set_text(cue.id,cue.text+' 保存验收')
                began=time.perf_counter();ticks.clear();previous_tick[0]=began
                page.save()
                handler=(time.perf_counter()-began)*1000
                wait(lambda:idle(page),90)
                result['saves'].append(dict(case=case,handler_ms=handler,total_ms=(time.perf_counter()-began)*1000,
                    max_gui_gap_ms=max(ticks,default=handler),output_bytes=page.project_path.stat().st_size,
                    timeline=getattr(page,'_last_save_timeline',None)))
                check(case+' durable',page.undo_stack.isClean())
            # Ctrl+S while a draft is open commits its current value once.
            cue = page.project.cues[0]
            page.select_cue(cue.id)
            page._seek((cue.start_ms+min(100,(cue.end_ms-cue.start_ms)//2))/1000)
            wait(lambda:cue.start_ms<=page.timeline.playhead_ms<cue.end_ms,10)
            page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E)
            wait(lambda:page._caption_draft is not None)
            draft=page._caption_draft;before=page.undo_stack.index()
            page.subtitle_edit_input.setPlainText(draft.before+' CtrlS验收')
            QTest.keyClick(page.subtitle_edit_input,Qt.Key_S,Qt.ControlModifier)
            wait(lambda:idle(page),90)
            check('CtrlS submits editor once',page.undo_stack.index()==before+1)
            page._cancel_canvas_inline_edit()
            reopened=load_project(page.project_path)
            check('saved content readback',any('CtrlS验收' in c.text for c in reopened.cues)
                  or any('CtrlS验收' in str(r.get('text','')) for r in reopened.generation_metadata['translation_records']['records'].values()))
            queue=getattr(page,'_persistence_queue',None)
            if queue is not None:
                result['queue']=dict(jobs_started=queue.jobs_started,coalesced=queue.requests_coalesced,max_pending=queue.max_pending)
            page.undo_stack.setClean();page.project_dirty=False
            result['passed']=all(result['checks'].values())
        except Exception:
            result['error']=traceback.format_exc()
        finally:
            if 'original_save' in locals():
                controller_type.save = original_save
            timer.stop()
            receipt()
            page._cancel_canvas_inline_edit()
            page.undo_stack.setClean();page.project_dirty=False
            window.close()
    app.aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
    QTimer.singleShot(1200,run)


def reliability(page, output, check, wait, idle, result):
    """Fault injection at the actual writer, with the real project/window alive."""
    import threading
    from ..projects import studio_project as persistence
    from ..projects.studio_save import defer_navigation_until_saved
    from ..system.resident_worker import shared_worker
    from PySide6.QtCore import QTimer
    original = persistence._atomic_json_blob_write
    target = page.project_path
    preferences = dict(page._studio_preferences(), autosave_enabled=False)
    page._studio_preferences = lambda: dict(preferences)
    cue = page.project.cues[0]
    released = threading.Event()
    started = threading.Event()

    def held_write(path, content):
        if Path(path) == target:
            started.set()
            if not released.wait(45):
                raise TimeoutError('audit writer release')
        return original(path, content)

    try:
        persistence._atomic_json_blob_write = held_write
        page.cue_controller.set_text(cue.id, cue.text+' N')
        page.save()
        wait(started.is_set)
        requested = cue.text
        page.cue_controller.set_text(cue.id, cue.text+' N+1')
        page.undo_stack.undo()
        page.undo_stack.redo()
        released.set()
        wait(lambda: idle(page))
        check('N cannot clean N+1 after undo redo', not page.undo_stack.isClean())
        check('N durable snapshot stable', persistence.load_project(target).cues[0].text == requested)
        page.save()
        for number in range(3):
            page.cue_controller.set_text(cue.id, cue.text+f' pending{number}')
            page.save()
        wait(lambda: idle(page))
        check('latest explicit request durable', persistence.load_project(target).cues[0].text == cue.text)
        check('single bounded pending', page._persistence_queue.max_pending <= 1)

        persistence._atomic_json_blob_write = original
        preferences['autosave_enabled'] = True
        page.cue_controller.set_text(cue.id, cue.text+' recovery')
        page._autosave_timer.stop()
        page._autosave_deadline.last_edit_at = time.monotonic()-3.1
        page._autosave()
        check('recovery started', page._persistence_queue.busy)
        page.undo_stack.undo()
        page.undo_stack.redo()
        wait(lambda: idle(page))
        wait(lambda: idle(page) and page._autosave_deadline.dirty_since is None)
        recovered = persistence.recoverable_autosave(target)
        check('abnormal exit recovery discoverable', recovered is not None)
        check('recovery readback includes latest edit', persistence.load_project(recovered).cues[0].text == cue.text)
        result['recovery_receipt'] = str(recovered)
        check('recovery leaves formal dirty', not page.undo_stack.isClean())
        if os.environ.get('EDIT_SAVE_CRASH_AFTER_RECOVERY') == '1':
            result.update(crash_ready=True,crash_target=str(target),crash_expected_text=cue.text)
            receipt = output/'result.json'
            with receipt.open('w',encoding='utf8') as stream:
                json.dump(result,stream,ensure_ascii=False,indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name == 'nt':
                import ctypes
                ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), 91)
            os._exit(91)

        preferences['autosave_enabled'] = False
        def failed_write(path, content):
            if Path(path) == target:
                raise OSError('injected disk full')
            return original(path, content)
        persistence._atomic_json_blob_write = failed_write
        previous = target.read_bytes()
        page.save()
        continuation = []
        check('navigation deferred during save', defer_navigation_until_saved(page, lambda: continuation.append(True)))
        wait(lambda: idle(page))
        check('write failure keeps formal and dirty', target.read_bytes() == previous and not page.undo_stack.isClean())
        check('write failure prevents navigation', not continuation)
        check('write failure retains recovery', persistence.recoverable_autosave(target) is not None)
        persistence._atomic_json_blob_write = original
        page.save()
        wait(lambda: idle(page))
        check('failed save retry succeeds', page.undo_stack.isClean())

        # A real resident process termination must fall back to the same encoder.
        persistence._FORMAL_TEXT_CACHES.clear()
        persistence._AUTOSAVE_TEXT_CACHES.clear()
        worker = shared_worker()
        prior_failures = len(worker.failures)
        prior_token = worker._token
        page.cue_controller.set_text(cue.id, cue.text+' worker-failure')
        killed = []
        def kill_encoder():
            if worker.running and worker._lock.locked() and worker._token > prior_token:
                worker._process.terminate()
                killed.append(True)
            else:
                QTimer.singleShot(10, kill_encoder)
        QTimer.singleShot(10, kill_encoder)
        page.save()
        wait(lambda: idle(page),90)
        check('worker failure injected', bool(killed) and len(worker.failures)>prior_failures)
        check('worker failure fallback is durable', page.undo_stack.isClean() and persistence.load_project(target).cues[0].text == cue.text)

        # Opening another project while the old writer is blocked resumes once.
        started.clear()
        released.clear()
        persistence._atomic_json_blob_write = held_write
        page.cue_controller.set_text(cue.id, cue.text+' switch')
        page.save()
        wait(started.is_set)
        old_project = page.project
        destination = persistence.save_project(persistence.SubtitleProject(persistence.StudioMedia('')), output/'switch.2byteproj')
        page.open_project(destination)
        check('switch waits for active save', page.project is old_project)
        released.set()
        wait(lambda:page.project is not old_project and page._readiness.ready,90)
        check('switch resumes after durable save', 'switch' in persistence.load_project(target).cues[0].text)
        persistence._atomic_json_blob_write = original
        page.open_project(target)
        wait(lambda:page.project_path == target and page._readiness.ready,90)
        cue = page.project.cues[0]
        page.cue_controller.set_text(cue.id, cue.text+' close')
        started.clear()
        released.clear()
        persistence._atomic_json_blob_write = held_write
        page.save()
        wait(started.is_set)
        window = page.window()
        window.close()
        check('close waits for active save', window.isVisible() and page._persistence_queue.busy)
        released.set()
        wait(lambda:not window.isVisible(),90)
        check('close resumes after durable save', 'close' in persistence.load_project(target).cues[0].text)
    finally:
        released.set()
        persistence._atomic_json_blob_write = original
