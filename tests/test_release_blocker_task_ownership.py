"""A01: delayed signals must never acquire the currently open project."""
import copy
import os
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.studio.studio_edit_assembly import StudioEditAssemblyMixin
from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin
from twobyteasr.projects.studio_session import StudioSession
from twobyteasr.timeline.studio_edit_sequence import sequence_of, HighlightCandidate
from twobyteasr.timeline.studio_edit_commands import razor_video_command
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject

APP = QApplication.instance() or QApplication([])

class DeferredWorker(QObject):
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int)   # 2026-10-24: the clip analysis reports its stage (Codex)
    finished = Signal()
    def __init__(self, *args):
        super().__init__()
        self.project = args[0] if args and isinstance(args[0], SubtitleProject) else None
        self.running = False
        self.cancelled = False
    def start(self): self.running = True
    def isRunning(self): return self.running
    def requestInterruption(self): self.cancelled = True
    def isInterruptionRequested(self): return self.cancelled
    def complete(self, value):
        self.finished_ok.emit(value)
        self.running = False
        self.finished.emit()

class Panel:
    def __init__(self):
        self.events = []
        self.cancel_button = SimpleNamespace(setEnabled=lambda v: None)
        self.autocut_mode = SimpleNamespace(currentData=lambda: 'smart')
        self.autocut_audio_track = SimpleNamespace(currentData=lambda: '')
        self.status = SimpleNamespace(setText=lambda v: self.events.append(v))
    def __getattr__(self, name):
        return lambda *a, **k: self.events.append((name, a))

class Host(QObject, StudioEditAssemblyMixin, StudioVideoFlowMixin):
    def __init__(self, p):
        super().__init__()
        self.project = p
        self.session = StudioSession(project=p)
        self.highlight_panel = Panel()
        self.undo_stack = QUndoStack()
        self.runtime_settings = SimpleNamespace()
        self.timeline = SimpleNamespace(update=lambda: None, playhead_ms=0, locked_speakers=set(),
            selected_video_track_id='', selected_video_clip_id='', selected_segment_id='',
            selected_segment_ids=set(), refresh_media_graph=lambda:None, set_playhead=lambda x:None)
        self.save_state = SimpleNamespace(setText=lambda x:None)
        self._close_requested = False
    def _sequence_changed(self, *a): pass
    def _seek(self, *a): pass

@pytest.fixture
def host(tmp_path, monkeypatch):
    import twobyteasr.studio.studio_edit_assembly as assembly
    import twobyteasr.studio.studio_video_flow as video
    monkeypatch.setattr(assembly, "HighlightAnalyzeWorker", DeferredWorker)
    monkeypatch.setattr(video, "QThread", DeferredWorker)
    monkeypatch.setattr(assembly, "studio_message_box", lambda *a: pytest.fail("late failure dialog"))
    media = tmp_path / "synthetic.wav"
    media.write_bytes(b"test-only")
    p = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=60000), cues=[StudioCue("c", 1000, 2000, "原文")])
    p.validate()
    sequence_of(p).video_track_locked = False
    p.video_tracks[0].locked = False
    h = Host(p)
    yield h
    for attr in ("_highlight_worker", "_autocut_worker"):
        w = getattr(h, attr, None)
        if w and w.isRunning(): w.complete({} if attr == "_highlight_worker" else [])

def result():
    return {"candidates": [HighlightCandidate("a", "旧工程候选", 1000, 5000)]}

@pytest.mark.parametrize("change", ["switch", "close", "edit", "reload"])
def test_late_highlight_is_discarded(host, change):
    host._analyze_highlights({})
    worker = host._highlight_worker
    if change == "switch": host.project = copy.deepcopy(host.project)
    if change == "close": host._close_requested = True
    if change == "edit": razor_video_command(host.project, 10000).redo()
    if change == "reload": host.session.generation += 1
    worker.complete(result())
    assert not sequence_of(host.project).clip_candidates
    assert host.undo_stack.count() == 0

def test_highlight_input_is_frozen_and_cancel_rejects_queued_success(host):
    host._analyze_highlights({})
    worker = host._highlight_worker
    host.project.cues[0].text = "稍后修改"
    assert worker.project.cues[0].text == "原文"
    host._cancel_highlight_analysis()
    worker.complete(result())
    assert host.undo_stack.count() == 0

def test_second_request_wins_and_late_failure_cannot_change_panel(host):
    host._analyze_highlights({})
    old = host._highlight_worker
    host._analyze_highlights({})
    new = host._highlight_worker
    old.failed.emit("old error")
    old.complete(result())
    assert host.undo_stack.count() == 0
    new.complete(result())
    assert host.undo_stack.count() == 1

@pytest.mark.parametrize("change", ["switch", "edit", "close"])
def test_autocut_late_result_cannot_offer_old_ranges(host, change):
    host._detect_autocut_silence(5, .3)
    worker = host._autocut_worker
    if change == "switch": host.project = copy.deepcopy(host.project)
    if change == "edit": razor_video_command(host.project, 10000).redo()
    if change == "close": host._close_requested = True
    worker.complete([(3000, 8000)])
    assert not any(e[0] == "show_autocut_preview" for e in host.highlight_panel.events if isinstance(e, tuple))

def test_autocut_preview_invalid_after_edit_or_repeated_apply(host):
    host._detect_autocut_silence(5, .3)
    host._autocut_worker.complete({'candidates':[{'start_ms':3000,'end_ms':8000}], 'removed_ms':5000,'duration_ms':60000})
    razor_video_command(host.project, 10000).redo()
    host._apply_autocut([(3000, 8000)])
    assert host.undo_stack.count() == 0
    host._detect_autocut_silence(5, .3)
    host._autocut_worker.complete({'candidates':[{'start_ms':3000,'end_ms':8000}], 'removed_ms':5000,'duration_ms':60000})
    host._apply_autocut([(3000, 8000)])
    assert host.undo_stack.count() == 1
    host._apply_autocut([(3000, 8000)])
    assert host.undo_stack.count() == 1


def test_real_thread_cancel_is_retained_until_finished(host, monkeypatch):
    from PySide6.QtCore import QThread
    import twobyteasr.studio.studio_edit_assembly as assembly
    from twobyteasr.studio.studio_analysis_request import cancel_analysis, _running_workers
    class WaitingWorker(QThread):
        finished_ok = Signal(object)
        failed = Signal(str)
        progress = Signal(str, int)
        def __init__(self, *args): super().__init__()
        def run(self):
            while not self.isInterruptionRequested(): self.msleep(2)
            self.finished_ok.emit(result())  # deliberately queued after cancel
    monkeypatch.setattr(assembly, "HighlightAnalyzeWorker", WaitingWorker)
    host._analyze_highlights({})
    worker = host._highlight_worker
    assert worker.parent() is None
    assert worker in _running_workers
    cancel_analysis(host)
    assert worker.wait(1000)
    APP.processEvents()
    assert worker not in _running_workers
    assert host.undo_stack.count() == 0
