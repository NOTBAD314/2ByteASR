"""Import Studio on the GUI thread, one dependency group per event-loop turn.

Imports stay serialized with GUI imports; there is no background Qt import
or module-lock race. Already loaded modules consume no additional turn.
"""
import importlib
import sys
import time
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal


MODULES = (
    'rendering.ass_compile_actor', 'playback.audio_playback_graph', 'rendering.advanced_preview',
    'providers.provider_service', 'glossary.glossary_learning', 'timeline.studio_commands',
    'caption_design.visual_design_graph', 'playback.playback_clock', 'playback.audio_engine',
    'timeline.media_time', 'playback.waveform_cache',
    'caption_design.studio_ai', 'projects.studio_revisions', 'exports.studio_export_ui',
    'caption_style.font_system', 'studio.studio_hub', 'studio.studio_sentence_refine_ui',
    'studio.studio_cue_controller', 'projects.studio_project_controller', 'studio.studio_review_ui',
    'caption_style.studio_style_controller', 'studio.studio_advanced_flow', 'studio.studio_ai_flow',
    'studio.studio_ass_flow', 'studio.studio_canvas_edit', 'studio.studio_edit_assembly',
    'studio.studio_media_flow', 'studio.studio_playback_flow', 'studio.studio_project_flow',
    'caption_style.studio_style_panel', 'studio.studio_video_flow', 'studio.studio_cue_table',
    'caption_style.studio_fill_editors', 'caption_style.studio_font_combo', 'rendering.studio_live_canvas',
    'caption_style.studio_motion_browser', 'studio.studio_position_overlay', 'studio.studio_shortcuts',
    'studio.studio_speaker_manager', 'studio.studio_timeline', 'studio.studio_video_canvas', 'studio.studio_ui',
)


class StudioModulePreloader(QObject):
    ready = Signal()
    failed = Signal(str)

    def __init__(self, parent=None, *, importer=None, modules=None, allowed=None):
        super().__init__(parent)
        self.importer = importer or importlib.import_module
        self.allowed = allowed or (lambda: True)
        self.pending = deque(modules if modules is not None else ('twobyteasr.'+name for name in MODULES))
        self.completed = False
        self.timings = []
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._step)

    def start(self):
        if not self.completed and not self.timer.isActive():
            self.timer.start(0)

    def _step(self):
        if not self.allowed():
            self.timer.start(250)
            return
        while self.pending and sys.modules.get(self.pending[0]) is not None:
            module = sys.modules[self.pending[0]]
            if getattr(getattr(module,'__spec__',None),'_initializing',False):
                self.timer.start(16)
                return
            self.pending.popleft()
        if not self.pending:
            self.completed = True
            self.ready.emit()
            return
        name = self.pending[0]
        began = time.perf_counter()
        try:
            self.importer(name)
        except Exception as error:
            self.failed.emit(f'{name}: {type(error).__name__}: {error}')
            return
        self.pending.popleft()
        self.timings.append(dict(module=name,ms=(time.perf_counter()-began)*1000))
        # Give posted paints and input a real turn between dependency groups.
        self.timer.start(16)
