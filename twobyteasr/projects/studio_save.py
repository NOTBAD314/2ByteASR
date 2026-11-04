"""Immutable manual-save snapshots and an event-driven modal wait.

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


def capture_manual_save(page, project, generation):
    """Freeze the exact committed state, including legacy direct assignments."""
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
        cues=tuple(RenderCueDTO.capture(cue) for cue in project.cues),
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
    try:
        yield
    finally:
        autosave_timer.blockSignals(previously_blocked)
        page._manual_save_in_progress = False


def cancel_navigation_after_save(page):
    if page is not None:
        page._navigation_after_manual_save = None


def defer_navigation_until_saved(page, callback):
    """Keep one latest navigation, resumed after the complete save controller.

    The save's nested event loop may receive external open requests. No loading
    card starts yet. The completion signal is emitted after success/error UI,
    then queued once; no polling or repeated zero-timers are needed.
    """
    if not getattr(page, '_manual_save_in_progress', False):
        return False
    finished = getattr(page, 'manual_save_finished', None)
    if finished is None:
        return False
    session = page.session
    page._navigation_after_manual_save = (session.project, session.generation, callback)
    if not getattr(page, '_manual_save_navigation_connected', False):
        def dispatch():
            from shiboken6 import isValid
            if not isValid(page) or getattr(page, '_close_requested', False):
                page._navigation_after_manual_save = None
                return
            if getattr(page, '_manual_save_in_progress', False):
                return  # A new save has its own completion signal.
            pending = getattr(page, '_navigation_after_manual_save', None)
            page._navigation_after_manual_save = None
            if pending is not None and page.session.project is pending[0] and page.session.generation == pending[1]:
                pending[2]()
        finished.connect(dispatch, Qt.ConnectionType.QueuedConnection)
        page._manual_save_navigation_connected = True
    return True



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

