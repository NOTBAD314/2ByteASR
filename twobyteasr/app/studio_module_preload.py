"""Import Studio on the GUI thread, one dependency group per event-loop turn.

Imports stay serialized with GUI imports; there is no background Qt import
or module-lock race. Already loaded modules consume no additional turn.
"""
import sys
import time
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal


BUILD_MODULES = (
    'studio.gui_thread_handoff', 'diagnostics.gui_stall_watchdog', 'studio.studio_performance',
    'playback.playback_gc_budget', 'projects.editor_recovery', 'projects.evidence_idle_check',
    'studio.interaction_runtime', 'studio.studio_workspace', 'cover.cover_label',
    'design.bunny_moves', 'subtitle_rules.chinese_script', 'studio.studio_chinese_script',
    'design.rich_menu', 'studio.translation_actions', 'caption_style.bilingual_layout',
    'studio.studio_bilingual', 'media.link_choices', 'app.link_download_widgets', 'app.link_quick_card',
    'studio.studio_media_availability', 'diagnostics.support_dialog', 'studio.usage_dialog',
    'studio.studio_task_panel', 'studio.studio_punctuation', 'studio.studio_ai_menu',
    'recognition.range_recognition', 'studio.studio_range_recognition', 'studio.video_viewport',
    'studio.native_video_region', 'rendering.overlay_session', 'playback.audio_process',
    'playback.video_decode_pipe', 'playback.video_compositor', 'playback.secondary_video_process',
    'playback.secondary_video', 'playback.platform_audio', 'playback.audio_recovery',
    'studio.caption_editor_window', 'timeline.source_selection', 'studio.source_media_cache',
    'studio.legacy_source_monitor', 'studio.studio_source_monitor', 'studio.review_strip_widgets',
    'caption_style.text_marks', 'studio.caption_text_tools', 'studio.studio_translation_edit',
    'caption_design.theme_local_polish', 'caption_design.theme_application_ui',
    'rendering.platform_browser', 'recognition.cue_word_alignment', 'caption_style.word_animation',
    'caption_style.motion_application', 'caption_style.motion_controls_ui',
    'caption_style.motion_inspector_ui', 'caption_style.motion_timeline_ui',
    'caption_style.style_application', 'caption_style.scoped_style', 'caption_style.scoped_preset',
    'caption_style.caption_layer_transform', 'caption_style.scoped_transform', 'studio.presentation_scope',
    'studio.video_inspector_widgets', 'caption_style.caption_group_transform',
    'caption_style.caption_transform_panel', 'timeline.studio_transitions', 'studio.studio_transition_ui',
    'timeline.studio_media_commands', 'studio.video_filmstrip', 'studio.media_pool_view',
    'studio.studio_media_pool_ui', 'studio.tool_tab_bar', 'studio.project_range_ui',
    'timeline.studio_track_delete', 'studio.toolbar_audio_buttons', 'studio.gain_scale',
    'studio.gain_fader', 'playback.project_loudness', 'diagnostics.audio_diagnostic_marker',
    'studio.project_loudness_panel', 'studio.timeline_zoom_slider', 'exports.frame_export_ui',
    'cover.cover_document', 'cover.cover_render', 'cover.cover_canvas', 'cover.cover_editor',
    'cover.cover_studio',
    # The finished build and the project library's first entry.
    'design.loading_font', 'design.studio_qss', 'design.candy_chrome_qss', 'design.task_panel_qss',
    'design.usage_dialog_qss', 'design.native_visibility_commit', 'diagnostics.save_trace',
    'playback.avsync', 'projects.persistence_queue', 'projects.studio_save',
    'providers.request_operations', 'recognition.speaker_roles', 'studio.source_timeline_drop',
    'studio.studio_bunny_entry', 'studio.studio_readiness', 'studio.studio_shortcut_actions',
    'studio.studio_timing_preview', 'studio.studio_toolbar_layout', 'studio.timeline_add_track',
    'studio.timeline_overview', 'studio.timeline_scrub', 'timeline.studio_track_gain',
    'studio.timeline_track_gain', 'studio.transport_cursor_overlay',
)

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
    'studio.studio_speaker_manager', 'studio.studio_timeline', 'studio.studio_video_canvas',
    # 2026-11-18: imported by StudioPage.__init__ and its workspace build
    # steps. Left to that moment they cost one compile/load each while the
    # loading card is up (a 211 ms construction step on a source run).
    # Before studio_ui: callers treat an imported studio_ui as "preloaded".
    *BUILD_MODULES,
    'studio.studio_ui',
)


def import_module(name):
    """Import through builtins.__import__, which PySide wraps.

    2026-11-18: PySide reads a module's source the first time an import
    statement returns it (its __feature__ check). importlib.import_module
    skips that wrapper, so every preloaded module was still read later, at
    click time, by Studio's own ``from .x import y`` (6-15 ms each on a
    source run). Returns the module itself, like importlib.import_module.
    """
    return __import__(name, fromlist=('__name__',))


class StudioModulePreloader(QObject):
    ready = Signal()
    failed = Signal(str)

    # 2026-11-27 (user: entering the project library takes a while): while someone waits for
    # Studio (``urgent``), modules are loaded back to back for up to this long per turn, then one
    # 0 ms turn lets the loading card paint; idle warm-up keeps its 16 ms pause after each module.
    URGENT_SLICE_S = 0.030

    def __init__(self, parent=None, *, importer=None, modules=None, allowed=None, urgent=None):
        super().__init__(parent)
        self.importer = importer or import_module
        self.allowed = allowed or (lambda: True)
        self.urgent = urgent or (lambda: False)
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
        began = time.perf_counter()
        while self.pending and sys.modules.get(self.pending[0]) is not None:
            module = sys.modules[self.pending[0]]
            if getattr(getattr(module,'__spec__',None),'_initializing',False):
                self.timer.start(16)
                return
            name = self.pending.popleft()
            if self.importer is import_module:
                # Loaded by another path: still let PySide do its one-time check now.
                import_module(name)
                if time.perf_counter() - began >= .008:
                    self.timer.start(16)
                    return
        if not self.pending:
            self.completed = True
            self.ready.emit()
            return
        urgent = bool(self.urgent())
        turn = time.perf_counter()
        while self.pending:
            name = self.pending[0]
            began = time.perf_counter()
            try:
                self.importer(name)
            except Exception as error:
                self.failed.emit(f'{name}: {type(error).__name__}: {error}')
                return
            self.pending.popleft()
            self.timings.append(dict(module=name,ms=(time.perf_counter()-began)*1000))
            if not urgent or time.perf_counter() - turn >= self.URGENT_SLICE_S:
                break
        # Give posted paints and input a real turn between dependency groups.
        self.timer.start(0 if urgent else 16)
