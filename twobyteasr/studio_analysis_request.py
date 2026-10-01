"""Ownership fence for the two edit-assistant tasks; never persisted."""
from dataclasses import dataclass
from threading import Event
from .studio_edit_sequence import sequence_of
from .studio_runtime_state import state_for

# A page can be destroyed before a cooperative worker has finished. These
# parentless QThreads retain their Python owner until Qt emits finished.
_running_workers = set()


@dataclass
class AnalysisRequest:
    project: object
    generation: int
    revision: int
    sequence: dict
    cancelled: Event

    @property
    def is_cancelled(self):
        return self.cancelled.is_set()

    def matches(self, page):
        return (not self.is_cancelled and not getattr(page, "_close_requested", False)
                and page.project is self.project
                and page.session.generation == self.generation
                and state_for(self.project).revision == self.revision
                and sequence_of(self.project).to_dict() == self.sequence)


def begin_request(page, kind):
    cancel_request(page, kind)
    p = page.project
    request = AnalysisRequest(p, page.session.generation, state_for(p).revision,
                              sequence_of(p).to_dict(), Event())
    setattr(page, f"_{kind}_request", request)
    return request


def current_request(page, kind, request):
    return request is not None and getattr(page, f"_{kind}_request", None) is request and request.matches(page)


def cancel_request(page, kind):
    request = getattr(page, f"_{kind}_request", None)
    if request is not None:
        request.cancelled.set()
    setattr(page, f"_{kind}_request", None)
    worker = getattr(page, f"_{kind}_worker", None)
    if worker is not None and worker.isRunning():
        worker.requestInterruption()


def retain_worker(page, worker):
    _running_workers.add(worker)
    owned = getattr(page, "_analysis_workers", None)
    if owned is None:
        owned = page._analysis_workers = set()
    owned.add(worker)
    def finished():
        for kind in ("highlight", "autocut"):
            if getattr(page, f"_{kind}_worker", None) is worker:
                setattr(page, f"_{kind}_worker", None)
        owned.discard(worker)
        _running_workers.discard(worker)
        worker.deleteLater()
    worker.finished.connect(finished)


def cancel_analysis(page):
    player = getattr(page, '_autocut_player', None)
    if player is not None:
        player.stop()
    for kind in ("highlight", "autocut"):
        cancel_request(page, kind)
    page._autocut_preview_request = None
    page._autocut_preview_ranges = ()
    for worker in tuple(getattr(page, "_analysis_workers", ())):
        if worker.isRunning():
            worker.requestInterruption()
    panel = getattr(page, "highlight_panel", None)
    if panel is not None:
        panel.analysis_finished()
        panel.set_autocut_busy(False)
        panel.show_autocut_result("检测已取消，请在当前工程重新检测。")
