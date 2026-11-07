"""One Studio writer and one replaceable pending explicit save request."""
from dataclasses import dataclass, replace
from pathlib import Path
from contextvars import copy_context
import os
import threading
import time
from weakref import WeakValueDictionary

from PySide6.QtCore import QObject, Signal, Slot, Qt

from ..diagnostics.save_trace import SaveTrace
from .studio_project import save_project_revision, save_autosave_revision, SubtitleProject

_path_locks = WeakValueDictionary()
_path_locks_guard = threading.Lock()


def _write_lock(path, project_id):
    key = os.path.normcase(os.path.abspath(path)) if path else project_id
    with _path_locks_guard:
        return _path_locks.setdefault(key, threading.Lock())


def same_content(left, right):
    return replace(left, generation=0, updated_at='') == replace(right, generation=0, updated_at='')


def file_identity(path):
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns


def newer_recovery_exists(project_id, path, formal_mtime_ns):
    from .studio_project import _autosave_path_for_identity, autosave_effective_mtime_ns, PROJECT_SUFFIX
    canonical = _autosave_path_for_identity(project_id, path, None)
    try:
        candidates = (canonical, *canonical.parent.glob(f'{canonical.stem}.*{PROJECT_SUFFIX}'))
        return any(candidate.is_file() and autosave_effective_mtime_ns(candidate) > formal_mtime_ns
                   for candidate in candidates)
    except OSError:
        return True  # A normal durable rewrite safely restores formal precedence.


@dataclass(frozen=True)
class SaveRequest:
    kind: str
    revision: object
    path: object
    trace: SaveTrace
    session_id: str = ''
    draft: object = None
    writer: object = None

    @property
    def save_id(self):
        return self.trace.save_id


@dataclass
class SaveOutcome:
    request: SaveRequest
    path: object = None
    phases: object = None
    error: object = None
    identity: object = None
    reused: bool = False
    updated_at: str = ''
    superseded: bool = False


class PersistenceQueue(QObject):
    completed = Signal(object)
    idle = Signal()

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.active = None
        self.pending = None
        self.callbacks = {}
        self.worker_thread = None
        if not hasattr(page, '_autosave_write_lock'):
            page._autosave_write_lock = threading.Lock()
        self.last_formal = None
        self.jobs_started = 0
        self.requests_coalesced = 0
        self.max_pending = 0
        self.completing = False
        self.completed.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.idle.connect(self._schedule_recovery)

    def _schedule_recovery(self):
        page = self.page
        if getattr(page, '_navigation_after_manual_save', None):
            return
        deadline = getattr(page, '_autosave_deadline', None)
        if deadline is None or deadline.dirty_since is None:
            return
        preferences = page._studio_preferences() if hasattr(page, '_studio_preferences') else {}
        if preferences.get('autosave_enabled', True):
            delay = deadline.delay_seconds(time.monotonic())
            page._autosave_timer.start(max(100, round(delay*1000)))

    @property
    def busy(self):
        return self.active is not None or self.pending is not None or self.completing

    @property
    def saving_formal(self):
        return any(task is not None and task.kind == 'formal' for task in (self.active, self.pending))

    def submit(self, request, callback):
        for previous in (self.pending, self.active):
            if (previous is not None and previous.kind == request.kind and previous.path == request.path
                    and same_content(previous.revision, request.revision)):
                self.requests_coalesced += 1
                request.trace.counters['coalesced_same_version'] = 1
                self.callbacks[previous.save_id].append((request, callback))
                request.trace.stop_gc()
                return previous.save_id
        self.callbacks[request.save_id] = [(request, callback)]
        if self.busy:
            if request.kind != 'formal':
                self.callbacks.pop(request.save_id, None)
                return None
            if self.pending is not None:
                for old_request, old_callback in self.callbacks.pop(self.pending.save_id, ()):
                    old_callback(SaveOutcome(old_request, superseded=True))
                self.pending.trace.stop_gc()
                self.requests_coalesced += 1
            self.pending = request
            self.max_pending = 1
            self.page._manual_save_in_progress = True
        else:
            self._start(request)
        return request.save_id

    def _start(self, request):
        self.active = request
        self.jobs_started += 1
        page = self.page
        page._manual_save_in_progress = self.saving_formal
        page._autosave_worker_running = True
        queued_at = time.perf_counter_ns()
        context = copy_context()
        last_formal = self.last_formal
        save_lock = page._autosave_write_lock

        def work():
            outcome = SaveOutcome(request)
            trace = request.trace
            try:
                with trace.activate(), trace.observe_gc():
                    trace.add('writer.queue', queued_at, time.perf_counter_ns())
                    lock_started = time.perf_counter_ns()
                    with save_lock, _write_lock(request.path, request.revision.project_id):
                        trace.add('writer.lock_wait', lock_started, time.perf_counter_ns())
                        can_reuse = (request.kind == 'formal' and last_formal is not None
                            and request.path == last_formal.request.path
                            and same_content(request.revision, last_formal.request.revision))
                        try:
                            can_reuse = can_reuse and file_identity(request.path) == last_formal.identity
                        except OSError:
                            can_reuse = False
                        if can_reuse and newer_recovery_exists(
                                request.revision.project_id, request.path, last_formal.identity[1]):
                            can_reuse = False
                            trace.counters['formal_rewrite_for_recovery_order'] = 1
                        if can_reuse:
                            outcome.path = last_formal.path
                            outcome.identity = last_formal.identity
                            outcome.updated_at = last_formal.updated_at
                            outcome.phases = dict(materialize_ms=0, serialize_ms=0, persist_ms=0, fsync_ms=0)
                            outcome.reused = True
                            trace.counters['unchanged_file_reused'] = 1
                        else:
                            with trace.span('writer.persist'):
                                if request.writer is not None:
                                    custom_started = time.perf_counter()
                                    detached = (SubtitleProject.from_dict(request.revision.to_payload())
                                                if request.kind == 'formal' else request.revision)
                                    outcome.path = request.writer(detached, request.path)
                                    outcome.phases = dict(materialize_ms=0, serialize_ms=0,
                                        persist_ms=(time.perf_counter()-custom_started)*1000, fsync_ms=0)
                                elif request.kind == 'formal':
                                    outcome.path, outcome.phases = save_project_revision(
                                        request.revision, request.path, compact=True)
                                else:
                                    outcome.path, outcome.phases = save_autosave_revision(
                                        request.revision, request.path, session_id=request.session_id)
                                if request.draft is not None:
                                    from .editor_recovery import persist_snapshot
                                    persist_snapshot(request.draft, outcome.path)
                            outcome.updated_at = request.revision.updated_at
                            outcome.identity = file_identity(outcome.path)
            except BaseException as exc:
                outcome.error = exc
            try:
                self.completed.emit(outcome)
            except RuntimeError:
                pass

        self.worker_thread = threading.Thread(target=lambda: context.run(work), name='studio-persistence', daemon=False)
        page._autosave_thread = self.worker_thread
        try:
            self.worker_thread.start()
        except Exception as error:
            self._finished(SaveOutcome(request, error=error))

    @Slot(object)
    def _finished(self, outcome):
        if self.active is None or self.active.save_id != outcome.request.save_id:
            return
        dispatch_started = time.perf_counter_ns()
        self.active = None
        self.completing = True
        if outcome.error is None and outcome.request.kind == 'formal':
            self.last_formal = outcome
        self.page._manual_save_in_progress = self.saving_formal
        self.page._autosave_worker_running = False
        callbacks = self.callbacks.pop(outcome.request.save_id, ())
        try:
            with outcome.request.trace.activate(), outcome.request.trace.span('gui.completion'):
                for request, callback in callbacks:
                    try:
                        callback(replace(outcome, request=request))
                    except Exception as error:
                        from ..diagnostics.event_log import emit
                        emit('project.save_callback_failed', module=__name__, level='ERROR',
                             save_id=request.save_id, error=str(error))
        finally:
            following, self.pending = self.pending, None
            self.completing = False
            if following is not None:
                self._start(following)
            else:
                self.page._manual_save_in_progress = False
                self.idle.emit()
            outcome.request.trace.add('gui.completion_dispatch', dispatch_started, time.perf_counter_ns())
            outcome.request.trace.stop_gc()
            self.page._last_save_timeline = outcome.request.trace.payload()
            self.page._last_save_timeline.update(
                generation=outcome.request.revision.generation,
                save_kind=outcome.request.kind,
                target=str(outcome.request.path),
                phases=outcome.phases,
                error=str(outcome.error) if outcome.error else None)
            from ..diagnostics.event_log import emit
            emit('project.persistence_timeline', module=__name__, result='failed' if outcome.error else 'completed',
                 save_id=outcome.request.save_id, generation=outcome.request.revision.generation,
                 save_kind=outcome.request.kind, timeline=self.page._last_save_timeline)


def queue_for(page):
    queue = getattr(page, '_persistence_queue', None)
    if queue is None:
        queue = page._persistence_queue = PersistenceQueue(page)
    return queue
