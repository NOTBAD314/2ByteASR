"""Immutable save capture, asynchronous requests and legacy synchronous helper.

Only the GUI captures mutable project data. The writer sees a frozen revision;
materialization, JSON serialization, backup and fsync all run on its thread.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QProgressDialog

from ..i18n import tr
from .studio_project import SubtitleProject, _utc_now, save_project, save_project_revision
from .studio_revisions import (
    RenderCueDTO, RenderStyleDTO, SpeakerDTO, StudioRevisionStore, freeze_json,
)
from ..diagnostics.text_work import TextWork, measured


@measured('save_snapshot')
def capture_manual_save(page, project, generation):
    """Freeze the exact committed state, including legacy direct assignments."""
    if getattr(page, '_caption_split_session', None) is not None:
        raise RuntimeError('请先确认或取消当前字幕切割草稿')
    runtime = getattr(project, "_studio_state_runtime", None)
    if runtime is not None and runtime._active is not None:
        raise RuntimeError("不能在媒体编辑事务提交前保存工程")
    # Full project.validate() deep-copies all ASR and caption metadata.
    # Validate the detached snapshot on the writer, never the GUI-owned tree.
    store = getattr(page, "_revision_store", None)
    if store is None or store.project is not project:
        store = page._revision_store = StudioRevisionStore(project)
    # Autosaves trust an evidence row object they have seen; a formal save
    # compares every row's content (also catches a row changed in place).
    revision = store.refresh_persistence(generation, deep=True)
    # Importers and compatibility callers may modify these records without
    # emitting a StateDelta. An explicit Save must include those changes too.
    return replace(
        revision,
        updated_at=_utc_now(),
        cues=store.manual_save_cues(),
        speakers=tuple(SpeakerDTO.capture(speaker) for speaker in project.speakers),
        styles=tuple(RenderStyleDTO.capture(style) for style in project.styles),
        effects=freeze_json(project.effects),
        style_recipes=freeze_json(project.style_recipes),
    )


class _SaveProgress(QProgressDialog):
    def reject(self):
        # Escape must not dismiss a durable write or let the dirty guard return
        # before its result is known.
        pass

    def closeEvent(self, event):
        event.ignore()


class _CloseGuard(QObject):
    def __init__(self, page, window):
        super().__init__()
        self.page = page
        self.window = window

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Close and watched in (self.page, self.window):
            event.ignore()
            return True
        return False


@contextmanager
def manual_save_scope(page):
    """Keep reentrant Save/Open/Close requests out of the nested event loop."""
    page._manual_save_in_progress = True
    autosave_timer = page._autosave_timer
    previously_blocked = autosave_timer.blockSignals(True)
    from ..playback.playback_gc_budget import gui_collection_window
    work=TextWork('project.save')
    try:
        with gui_collection_window('manual_save',max_seconds=3),work.activate():
            yield
    finally:
        autosave_timer.blockSignals(previously_blocked)
        page._manual_save_in_progress = False
        page._last_save_work=work.finish()


def cancel_navigation_after_save(page):
    if page is not None:
        page._navigation_after_manual_save = None


def defer_navigation_until_saved(page, callback):
    """Keep one latest navigation, resumed after the complete save controller.

    No loading card starts until the asynchronous queue is idle. The latest
    continuation is queued once and re-enters the normal dirty-state guard.
    """
    from .persistence_queue import queue_for
    queue = queue_for(page)
    if not queue.busy:
        return False
    queue_navigation_after_save(page, callback)
    return True


def queue_navigation_after_save(page, callback):
    from .persistence_queue import queue_for
    queue = queue_for(page)
    session = page.session
    page._navigation_after_manual_save = (session.project, session.generation, callback)
    if not getattr(page, '_manual_save_navigation_connected', False):
        def dispatch():
            from shiboken6 import isValid
            if not isValid(page) or getattr(page, '_close_requested', False):
                page._navigation_after_manual_save = None
                return
            if queue.busy:
                return
            pending = getattr(page, '_navigation_after_manual_save', None)
            page._navigation_after_manual_save = None
            if pending is not None and page.session.project is pending[0] and page.session.generation == pending[1]:
                pending[2]()
        queue.idle.connect(dispatch, Qt.ConnectionType.QueuedConnection)
        page._manual_save_navigation_connected = True


def request_formal_save(controller, *, save_project_fn, message_box_fn, on_finished=None):
    """Capture the requested version on GUI, then acknowledge durable completion."""
    from ..diagnostics.save_trace import SaveTrace
    from ..playback.playback_gc_budget import gui_collection_window
    from ..studio.text_edit_submission import save_operation_ids, record_text_save
    from .persistence_queue import SaveRequest, queue_for
    from PySide6.QtWidgets import QFileDialog
    from ..i18n import bind_text
    page = controller.page
    project = controller.session.project
    if project is None or getattr(page, '_save_capture_in_progress', False):
        return None
    target = controller.session.project_path
    if target is None:
        page._save_capture_in_progress = True
        try:
            name, _ = QFileDialog.getSaveFileName(page, tr('保存 Subtitle Project'), '', '2ByteASR Project (*.2byteproj)')
        finally:
            page._save_capture_in_progress = False
        if not name:
            return None
        target = Path(name)
    trace = SaveTrace()
    trace.start_gc()
    page._save_capture_in_progress = True
    token = None
    watcher = None
    try:
        with trace.activate(), trace.span('gui.editor_commit'):
            style = getattr(page, 'style_controller', None)
            if style is not None and not style.flush_pending_application():
                return None
            if getattr(page, '_canvas_editor', None) is not None:
                if getattr(page, '_caption_following', False):
                    token = page._commit_caption_for_manual_save()
                    if token is False:
                        return None
                elif page._commit_canvas_inline_edit() is False:
                    return None
            timeline = getattr(page, 'timeline', None)
            if getattr(timeline, '_inline_editor', None) is not None:
                timeline._commit_inline_edit()
                if timeline._inline_editor is not None:
                    return None
            translation = getattr(page, 'translation_text', None)
            if callable(getattr(translation, 'commit', None)) and translation.commit() is False:
                return None
            page._capture_studio_state()
        session_generation = controller.session.generation
        undo_index = controller.session.undo_stack.index()
        edit_generation = getattr(page, '_autosave_generation', 0)
        runtime = getattr(project, '_studio_state_runtime', None)
        revision_id = getattr(runtime, 'revision', 0)
        operation_ids = save_operation_ids(page, project, revision_id)
        watcher = observe_save_edits(runtime)
        new_edits = watcher.__enter__()
        with trace.activate(), trace.span('gui.snapshot'), gui_collection_window('save_capture', max_seconds=1):
            revision = capture_manual_save(page, project, revision_id)
        from ..diagnostics.editor_diagnostics import record
        record('MANUAL_SAVE_SNAPSHOT', save_id=trace.save_id,
               duration_ms=trace.events[-1]['duration_ms'], revision=revision_id)
        bind_text(page.save_state, '正在后台保存工程…')
        request = SaveRequest('formal', revision, Path(target), trace,
                              writer=save_project_fn if save_project_fn is not save_project else None)

        def complete(outcome):
            watcher.__exit__(None, None, None)
            if outcome.superseded:
                if on_finished is not None:
                    on_finished(None, RuntimeError('保存请求已由较新版本合并，请按最新状态重试'))
                return
            if controller.session.project is not project or controller.session.generation != session_generation:
                if on_finished is not None:
                    on_finished(outcome.path, outcome.error)
                return
            error = outcome.error
            if error is not None:
                page._formal_save_error = (id(project), session_generation, str(error))
                page._navigation_after_manual_save = None
                page._schedule_autosave()
                bind_text(page.save_state, '保存失败，修改仍在内存中，可按 Ctrl+S 重试')
                page.save_state.setToolTip(str(error))
                record_text_save(operation_ids, kind='formal', revision=revision_id, generation=edit_generation, error=error)
                if token:
                    page._finish_caption_manual_save(token, error=error)
                from ..design.studio_theme import studio_message_box
                if message_box_fn is not studio_message_box:
                    from PySide6.QtWidgets import QMessageBox
                    message_box_fn(page, QMessageBox.Icon.Critical, '保存失败', str(error))
            else:
                controller.session.project_path = Path(outcome.path)
                project.updated_at = outcome.updated_at
                page._formal_save_error = None
                readiness = getattr(page, '_readiness', None)
                if readiness is not None and readiness.ready:
                    from ..studio.studio_readiness import project_file_identity
                    readiness.path = str(Path(outcome.path).resolve())
                    readiness.loaded_file_identity = project_file_identity(outcome.path)
                newer = (controller.session.undo_stack.index() != undo_index
                    or getattr(page, '_autosave_generation', 0) != edit_generation or new_edits[0])
                if newer:
                    if page._autosave_deadline.dirty_since is None:
                        page._schedule_autosave()
                    bind_text(page.save_state, '已保存请求版本，仍有新的未保存修改')
                else:
                    controller.session.undo_stack.setClean()
                    page._recovered_autosave_pending = False
                    page._autosave_deadline.mark_succeeded()
                    page._autosave_timer.stop()
                    draft = getattr(page, '_draft_recovery', None)
                    if draft is not None and draft.snapshot() is not None:
                        bind_text(page.save_state, '已保存工程，编辑草稿尚未确认')
                    else:
                        bind_text(page.save_state, '已保存')
                page.save_state.setToolTip('')
                record_text_save(operation_ids, kind='formal', revision=revision_id, generation=edit_generation)
                if token:
                    page._finish_caption_manual_save(token)
            record('MANUAL_SAVE_WRITE', save_id=trace.save_id, generation=revision.generation,
                   **(outcome.phases or {}), thread='studio-persistence')
            if on_finished is not None:
                on_finished(outcome.path, error)
            finished = getattr(page, 'manual_save_finished', None)
            if finished is not None:
                finished.emit()

        return queue_for(page).submit(request, complete)
    except Exception as error:
        if watcher is not None:
            watcher.__exit__(None, None, None)
        trace.stop_gc()
        page._schedule_autosave()
        bind_text(page.save_state, '保存准备失败，修改仍保留，可重试保存')
        page.save_state.setToolTip(str(error))
        if on_finished is not None:
            on_finished(None, error)
        return None
    finally:
        page._save_capture_in_progress = False
        if watcher is None:
            trace.stop_gc()



@contextmanager
def observe_save_edits(runtime):
    """Ignore transient selection/analysis deltas; watch persisted mutations."""
    from .studio_runtime_state import DirtyDomain
    changed = [False]

    def consume(delta):
        if delta.dirty & DirtyDomain.AUTOSAVE:
            changed[0] = True

    if runtime is not None:
        runtime.subscribe(consume)
    try:
        yield changed
    finally:
        if runtime is not None:
            runtime.unsubscribe(consume)

@measured('save_wait')
def persist_with_progress(page, revision, path, *, save_project_fn=save_project):
    """Return the durable result synchronously while Qt timers/paint keep running."""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("正式保存需要运行中的界面")
    target = Path(path)
    result = {}
    finished = threading.Event()
    loop = QEventLoop()
    progress = _SaveProgress(tr("正在保存工程…"), "", 0, 0, page.window())
    progress.setObjectName("studioManualSaveProgress")
    from ..design.studio_theme import apply_secondary_surface_theme
    apply_secondary_surface_theme(progress)
    progress.setMinimumWidth(360)
    progress.setWindowTitle(tr("保存工程"))
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    progress.setCancelButton(None)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setMinimumDuration(0)
    close_guard = _CloseGuard(page, page.window())
    app.installEventFilter(close_guard)
    pending_autosave = getattr(page, "_autosave_thread", None)
    write_lock = getattr(page, "_autosave_write_lock", None)

    def persist():
        if save_project_fn is save_project:
            saved, phases = save_project_revision(revision, target)
        else:
            # Preserve the existing injectable boundary without handing a
            # mutable GUI-owned project to a plugin or test writer.
            started = perf_counter()
            detached = SubtitleProject.from_dict(revision.to_payload())
            saved = save_project_fn(detached, target)
            phases = {"persist_ms": (perf_counter() - started) * 1000.0}
        result["path"] = Path(saved)
        result["phases"] = phases

    def work():
        try:
            # An older autosave must finish before the formal file's atomic
            # replacement; otherwise its later mtime could offer stale recovery.
            # This wait is on the writer thread, while Qt keeps processing events.
            if pending_autosave is not None and pending_autosave.is_alive():
                pending_autosave.join()
            if write_lock is None:
                persist()
            else:
                with write_lock:
                    persist()
        except BaseException as exc:
            result["error"] = exc
        finally:
            finished.set()

    def poll():
        if finished.is_set():
            loop.quit()

    timer = QTimer()
    timer.setInterval(16)
    timer.timeout.connect(poll)
    from contextvars import copy_context
    diagnostic_context = copy_context()
    worker = threading.Thread(target=lambda:diagnostic_context.run(work), name="studio-manual-save", daemon=False)
    try:
        # Application modality blocks input without recursively disabling and
        # restyling every widget in a large Studio page.
        progress.show()
        timer.start()
        worker.start()
        while not finished.is_set():
            loop.exec()
    finally:
        timer.stop()
        app.removeEventFilter(close_guard)
        progress.hide()
        progress.deleteLater()
    error = result.get("error")
    if error is not None:
        if isinstance(error, Exception):
            raise error
        raise RuntimeError(f"保存线程异常退出: {type(error).__name__}") from error
    from ..diagnostics.editor_diagnostics import record
    record("MANUAL_SAVE_WRITE", generation=revision.generation,
           **result["phases"], thread="studio-manual-save")
    return result["path"]

