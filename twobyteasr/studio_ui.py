"""Subtitle Studio page: video, current cue editor, and waveform timeline."""

from __future__ import annotations

import os
import json
import queue
import threading
import time
import uuid
from collections import deque
from collections.abc import Mapping
from datetime import datetime
from time import perf_counter
from pathlib import Path


from .themed_icons import install_themed_icon
from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QCursor,
    QImage,
    QKeySequence,
    QKeyEvent,
    QMouseEvent,
    QPixmap,
    QShortcut,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .ass_compile_actor import AssCompileActor
from .audio_playback_graph import AudioPlaybackGraph
from .advanced_preview import (
    AdvancedPreviewCache,
    AdvancedPreviewPhase,
    AdvancedPreviewStateMachine,
)
from .runtime_cache import GLOBAL_RUNTIME_CACHE
from .runtime_trace import GLOBAL_STUDIO_TRACE
from .resource_governor import GLOBAL_RESOURCE_GOVERNOR
from .provider_service import GLOBAL_PROVIDER_SERVICE
from .provider_registry import GLOBAL_PROVIDER_REGISTRY

from .i18n import bind_text, tr, user_text


def provider_for_stage(settings, stage):
    """Compatibility seam; Studio shares the application ProviderRegistry."""
    return GLOBAL_PROVIDER_REGISTRY.client(stage=stage, settings=settings)
from .glossary_learning import GlossaryLearningStore
from .teach_hints import TeachHintStore
from .i18n import current_language, translate
from .studio_commands import (
    MutationOrigin,
    cue_by_id,
)
from .studio_timing import (
    CueSelectionModel,
    loop_region,
)
from .selection_scope import (
    SelectionLatencyTrace,
    SelectionScope,
)
from .studio_edit_sequence import (
    sequence_of,
    timeline_duration_ms,
)
from .studio_edit_commands import delete_video_segments_command
from .studio_sequence_mapper import timeline_to_source
from .studio_ai import (
    AIDesignSuggestion,
    StudioSuggestion,
)
from .studio_project import (
    StudioCue,
    SubtitleProject,
    save_autosave,
    save_autosave_revision,
    save_project,
    studio_settings_path,
)
from .studio_revisions import StudioRevisionStore
from .style_recipe import VisualStyleRecipe, route_recipe
from .visual_runtime import (
    VisualOwner,
    VisualOwnershipStateMachine,
)
from .studio_export_ui import StudioExportWorkspace
from .studio_theme import (
    build_studio_qss,
    create_studio_menu,
    studio_message_box,
)
from .ui_theme import theme_definition
from .studio_widgets import ScrubDoubleSpinBox, ScrubSpinBox
from .studio_review import cached_qc_result
from .studio_qc import (
    QCSeverity,
    SubtitleQCEngine,
)
from .font_system import system_font_inventory
from .media_service import GLOBAL_MEDIA_SERVICE
from .autosave_deadline import AutosaveDeadline


from .studio_theme import STUDIO_COMMANDS
from .studio_helpers import (
    _format_ms,
    format_timeline_timecode,
    parse_timeline_timecode,
    media_relink_warning,
    probe_media_identity,
    render_style_sample,
)
from .studio_hub import StudioHubMixin
from .studio_sentence_refine_ui import StudioSentenceRefineMixin
from .studio_cue_controller import StudioCueController
from .studio_project_controller import StudioProjectController
from .studio_review_ui import StudioReviewMixin
from .studio_session import StudioSession
from .studio_style_controller import StudioStyleController

# Feature-domain flow mixins (Phase B of the studio_ui.py breakup).
from .studio_advanced_flow import StudioAdvancedFlowMixin
from .studio_ai_flow import StudioAIFlowMixin
from .studio_ass_flow import StudioAssFlowMixin
from .studio_canvas_edit import StudioCanvasEditMixin
from .studio_edit_assembly import StudioEditAssemblyMixin
from .studio_media_flow import StudioMediaFlowMixin
from .studio_playback_flow import StudioPlaybackFlowMixin
from .studio_project_flow import StudioProjectFlowMixin
from .studio_style_panel import StudioStylePanelMixin
from .studio_video_flow import StudioVideoFlowMixin

# Split-out Studio widget modules (Phase A of the studio_ui.py breakup).
# Several names below are re-exports kept for tests/scripts that still import
# them from twobyteasr.studio_ui; they are not used by this module directly.
from .studio_cards import _SubtitleEditCardEditor
from .studio_cue_table import (
    CueBadgeDelegate,
    CueIndexDelegate,
    CueTableModel,
    _cue_explicitly_confirmed,
    _cue_review_level,
    _cue_status,
    _speaker_color,
    _speaker_name,
)
from .studio_fill_editors import FillEditorDialog
from .studio_font_combo import LazyFontComboBox
from .studio_live_canvas import (
    AdvancedLiveCanvas,
    _count_stroke_pixels,
)
from .studio_motion_browser import MotionBrowserDialog
from .studio_position_overlay import SubtitlePositionOverlay
from .studio_shortcuts import ShortcutSettingsDialog, _StudioNativeKeyFilter
from .studio_speaker_manager import SpeakerManagerDialog
from .studio_style_widgets import StylePropertyRow
from .studio_timeline import WaveformTimeline, adaptive_timeline_ticks
from .studio_video_canvas import MpvCanvas
from .studio_widgets import ScrubDoubleSpinBox, ScrubSpinBox, _icon, _icon_label, _time_spinbox


_ORIGINAL_SAVE_AUTOSAVE = save_autosave


class SubtitleStudioPage(
    StudioHubMixin,
    StudioSentenceRefineMixin,
    StudioReviewMixin,
    StudioProjectFlowMixin,
    StudioMediaFlowMixin,
    StudioStylePanelMixin,
    StudioCanvasEditMixin,
    StudioVideoFlowMixin,
    StudioEditAssemblyMixin,
    StudioAssFlowMixin,
    StudioPlaybackFlowMixin,
    StudioAIFlowMixin,
    StudioAdvancedFlowMixin,
    QWidget,
):

    return_requested = Signal()

    recognition_requested = Signal(str, str, str)

    # 四十二轮：后台识别的取消入口（左侧字幕列表状态芯片）。
    recognition_cancel_requested = Signal()

    # 四十三轮：查看详细进度（跳主页识别进度页，可返回 Studio）。
    recognition_detail_requested = Signal()

    cover_ready_signal = Signal(str, str)
    library_records_ready_signal = Signal(object, int)
    # 2026-09-18 III：工程库封面后台解码完成（worker 线程发 QImage，GUI 转 QPixmap）
    library_cover_ready_signal = Signal(str, int, int, QImage)

    waveform_ready_signal = Signal(int, str, str, object)

    waveform_progress_signal = Signal(int, str, str)

    waveform_failed_signal = Signal(int, str, str)

    startup_milestone_signal = Signal(str, object)

    media_ingest_ready_signal = Signal(object)

    project_media_probe_ready_signal = Signal(int, str, object)

    ai_ready_signal = Signal(object)

    ai_web_theme_signal = Signal(int, str, object)

    ai_refine_signal = Signal(int, object)

    ai_web_adjust_signal = Signal(int, object, object)

    ai_stream_line_signal = Signal(int, str)

    ai_failed_signal = Signal(str)

    ai_stage_signal = Signal(int, str)

    ai_provider_probe_signal = Signal(int, str, str, object)
    ai_provider_progress_signal = Signal(int, str)

    ai_revision_signal = Signal(int, int, object, object, str)

    ai_revision_failed_signal = Signal(int, str)

    reasr_ready_signal = Signal(object)

    reasr_failed_signal = Signal(str)

    ass_ready_signal = Signal(int, str)

    ass_failed_signal = Signal(int, str)

    autosave_ready_signal = Signal(int)

    autosave_failed_signal = Signal(int, str)

    advanced_preview_ready_signal = Signal(object, int, str, bool)

    advanced_preview_failed_signal = Signal(object, int, str)

    ai_variant_preview_ready_signal = Signal(int, int, str, bool)

    close_ready_signal = Signal(object)

    @property
    def project(self) -> SubtitleProject | None:
        return self.session.project

    @project.setter
    def project(self, value: SubtitleProject | None) -> None:
        clear=getattr(getattr(self,'video',None),'clear_caption_boundaries',None)
        if callable(clear):clear()
        previous = self.session.runtime
        if previous is not None:
            previous.unsubscribe(self._consume_state_delta)
        self.session.project = value
        scene = getattr(self, '_caption_scene', None)
        if scene is not None:
            scene.close()
            self._caption_scene = None
        cache = getattr(self, '_caption_playback_cache', None)
        if cache is not None:
            cache.close()
            self._caption_playback_cache = None
        pixels = getattr(self, '_caption_pixel_cache', None)
        if pixels is not None:
            pixels.close()
            self._caption_pixel_cache = None
        self.session.active_cue_id = ""
        self.session.active_cue_ids = frozenset()
        self.session.playhead_target_id = ''
        self.session.observed_playhead_target_id = None
        self.session.preferred_subtitle_speaker = ''
        self._active_video_preview_key = ""
        self._active_video_preview_track_id = ""
        self._active_video_preview_clip_id = ""
        self._active_video_preview_source_path = ""
        self._active_video_preview_source_in_ms = 0
        self._active_video_preview_timeline_in_ms = 0
        self._video_composition_generation = 0
        self._active_video_preview_volume = None
        self._multitrack_composition_active = False
        # Audio-only projects have no decoded video frame for libass to paint
        # against.  Keep subtitle foreground promotion explicit so the same
        # Qt LIVE overlay can render the active cue while ProjectClock advances
        # from AudioEngine telemetry.
        self._audio_only_subtitle_active = False
        self._video_transform_preview_overrides: dict[str, dict[str, object]] = {}
        self._video_effects_preview_overrides: dict[str, dict[str, object]] = {}
        if value is None:
            self.session.runtime = None
            self._revision_store = None
            if hasattr(self, "_visual_ownership"):
                self._visual_ownership.commit(VisualOwner.NONE)
            overlay = getattr(self, "advanced_cue_overlay", None)
            if overlay is not None:
                overlay.hide()
            compositor = getattr(self, "video_compositor", None)
            if compositor is not None:
                compositor.clear()
            video = getattr(self, "video", None)
            if video is not None:
                video.set_native_subtitle_visible(False)
            return
        from .studio_runtime_state import state_for

        runtime = state_for(value)
        runtime.subscribe(self._consume_state_delta)
        self.session.runtime = runtime
        self._revision_store = StudioRevisionStore(value, revision=runtime.revision)

    def _consume_state_delta(self, delta) -> None:
        if self._revision_store is not None:
            self._revision_store.consume(delta)
        self.cue_controller.consume_state_delta(delta)
        from .studio_runtime_state import DirtyDomain

        if delta.touches(DirtyDomain.AUDIO_GAIN):
            self._refresh_audio_mix_only()
            self.timeline.update()

        media_domains = (
            DirtyDomain.MEDIA_POOL
            | DirtyDomain.VIDEO_TRACKS
            | DirtyDomain.AUDIO_TRACKS
            | DirtyDomain.MEDIA_TIMING
            | DirtyDomain.VIDEO_COMPOSITION
        )
        if delta.touches(media_domains):
            if delta.touches(
                DirtyDomain.MEDIA_TIMING | DirtyDomain.VIDEO_COMPOSITION
            ):
                self._invalidate_video_composition_state(delta)
            if hasattr(self, "timeline"):
                self.timeline.refresh_media_graph()
            if hasattr(self, "media_pool_panel"):
                self.media_pool_panel.refresh(self.project)
            if delta.touches(DirtyDomain.MEDIA_POOL):
                self._generate_project_waveforms()
            if hasattr(self, "video") and hasattr(self, "timeline"):
                self._refresh_edit_playback_state()
                self._sync_multitrack_preview_at(int(self.timeline.playhead_ms))
            self._refresh_video_transform_panel()

    def _invalidate_video_composition_state(self, delta=None) -> None:
        """Force the next project-time sample to resolve and bind its base anew."""

        self._video_composition_generation = int(
            getattr(self, "_video_composition_generation", 0)
        ) + 1
        self._active_video_preview_key = ""
        self._active_video_preview_track_id = ""
        self._active_video_preview_clip_id = ""
        self._active_video_preview_source_path = ""
        self._active_video_preview_source_in_ms = 0
        self._active_video_preview_timeline_in_ms = 0
        self._active_video_preview_volume = None
        self._active_mpv_audio_enabled = None
        self._studio_trace(
            "VIDEO_COMPOSITION_INVALIDATED",
            generation=self._video_composition_generation,
            dirty=int(getattr(delta, "dirty", 0) or 0),
            revision=int(getattr(delta, "revision", 0) or 0),
        )

    @property
    def project_path(self) -> Path | None:
        return self.session.project_path

    @project_path.setter
    def project_path(self, value: Path | None) -> None:
        self.session.project_path = value

    @property
    def selected_cue_id(self) -> str:
        return self.session.selected_cue_id

    @property
    def active_cue_id(self) -> str:
        return self.session.active_cue_id

    @property
    def active_cue_ids(self) -> frozenset[str]:
        return self.session.active_cue_ids

    @selected_cue_id.setter
    def selected_cue_id(self, value: str) -> None:
        self.session.selected_cue_id = value
        if not value:
            self._manual_selection_hold = False

    @property
    def _cue_lookup(self) -> dict[str, StudioCue]:
        return self.session._cue_lookup

    @_cue_lookup.setter
    def _cue_lookup(self, value: dict[str, StudioCue]) -> None:
        self.session._cue_lookup = value

    @property
    def undo_stack(self) -> QUndoStack:
        return self.session.undo_stack

    @undo_stack.setter
    def undo_stack(self, value: QUndoStack) -> None:
        self.session.undo_stack = value

    def __init__(self, parent=None):
        super().__init__(parent)
        from .gui_thread_handoff import GuiThreadHandoff
        self._gui_thread_handoff=GuiThreadHandoff()
        self.destroyed.connect(self._gui_thread_handoff.release)
        from .playback_gc_budget import PlaybackGcBudget
        self._playback_gc_budget = PlaybackGcBudget(self)
        self.destroyed.connect(self._playback_gc_budget.close)
        self.setObjectName("subtitleStudio")
        self.setStyleSheet(build_studio_qss())
        self.session = StudioSession()
        self.project_controller = StudioProjectController(self, self.session)
        self.cue_controller = StudioCueController(self, self.session)
        self.style_controller = StudioStyleController(self, self.session)
        self._revision_store: StudioRevisionStore | None = None
        self._ass_actor: AssCompileActor | None = None
        self._ass_snapshot_ms: dict[int, float] = {}
        self.project: SubtitleProject | None = None
        self.project_path: Path | None = None
        self._project_view_state = "hub"
        self._project_opening_path = ""
        self._hub_toolbar_hidden: list[QWidget] = []
        self._hub_card_widgets: list[QToolButton] = []
        self.selected_cue_id = ""
        self.selection_model = CueSelectionModel()
        self._selection_latency = SelectionLatencyTrace()
        self._loop_enabled = False
        self._loop_region_ms: tuple[int, int] | None = None
        self._cue_lookup: dict[str, StudioCue] = {}
        self._subtitle_track_visibility: dict[str, bool] = {}
        self._manual_text_baselines: dict[str, str] = {}
        self._learning_store = GlossaryLearningStore()
        # Evidence tokens recorded per cue (typing chains) so an undo can revert
        # exactly the evidence whose resulting text no longer holds.
        self._learning_evidence_tokens: dict[str, list[str]] = {}
        self._qc_engine = SubtitleQCEngine()
        self._qc_terminology = ()
        self._pending_qc_cue_ids: set[str] = set()
        self._qc_full_scan_pending = False
        self._teach_hints = TeachHintStore()
        self._session_teach_hints: set[str] = set()
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(500)
        self._updating_editor = False
        self._preview_path: Path | None = None
        self._ass_generation = 0
        self._ass_worker_running = False
        self._ass_profile: list[dict[str, object]] = []
        self._autosave_generation = 0
        self._autosave_session_id = uuid.uuid4().hex
        self._autosave_worker_running = False
        self._autosave_thread: threading.Thread | None = None
        self._autosave_write_lock = threading.Lock()
        self._autosave_profile: list[dict[str, object]] = []
        self._recovered_autosave_pending = False
        self._autosave_deadline = AutosaveDeadline()
        self._last_autosave_at = ""
        self._waveform_generation = 0
        self._waveform_inflight: set[str] = set()
        self._waveform_inflight_lock = threading.Lock()
        self._waveform_threads: set[threading.Thread] = set()
        self._waveform_cancel_event = threading.Event()
        self._waveform_last_ready_media = ""
        self._waveform_last_progress_text = ""
        self._waveform_pending_media: list[str] = []
        self._media_ingest_generation = 0
        self._media_ingest_project_token = ""
        self._pending_media_path = ""
        self._pending_media_mode = "primary"
        self._media_ingest_state = "EMPTY"
        self._empty_playback_state = False
        self._active_video_preview_key = ""
        self._active_video_preview_track_id = ""
        self._active_video_preview_clip_id = ""
        self._active_video_preview_source_path = ""
        self._active_video_preview_source_in_ms = 0
        self._active_video_preview_timeline_in_ms = 0
        self._active_video_preview_volume = None
        self._active_mpv_audio_enabled: bool | None = None
        self._audio_playback_graph = AudioPlaybackGraph()
        self._audio_playback_decision = self._audio_playback_graph.last_decision
        self._media_ingest_thread: threading.Thread | None = None
        self._project_probe_generation = 0
        self._project_probe_thread: threading.Thread | None = None
        self._pending_suggestion: StudioSuggestion | AIDesignSuggestion | None = None
        self._ai_request_active = False
        self._ai_request_generation = 0
        self._ai_provider_probe_generation = 0
        self._ai_provider_probe_cache: dict[str, tuple[float, str, str]] = {}
        self._ai_cancel_event: threading.Event | None = None
        self._ai_history: list[AIDesignSuggestion] = []
        self._ai_last_instruction = ""
        # One-round revision state (“微调设计”): per-slot previous versions
        # plus the active revision worker identity.
        self._ai_variant_revisions: dict[int, list[VisualStyleRecipe]] = {}
        self._ai_revision_active = False
        self._ai_revision_generation = 0
        self._ai_revision_cancel: threading.Event | None = None
        self._ai_variant_preview_generation = 0
        self._ai_variant_preview_labels: list[QLabel] = []
        self._ai_variant_preview_paths: list[str] = []
        self._ai_variant_preview_done: set[int] = set()
        self._ai_variant_animations: dict[int, QPropertyAnimation] = {}
        self._ai_variant_motion_timers: dict[int, QTimer] = {}
        self._pending_motion_replay_cue_id = ""
        self._motion_contract_dirty = False
        self._advanced_preview_generation = 0
        self._advanced_preview_cache = AdvancedPreviewCache()
        self._advanced_preview_state = AdvancedPreviewStateMachine()
        self._runtime_cache = GLOBAL_RUNTIME_CACHE
        self._resource_governor = GLOBAL_RESOURCE_GOVERNOR
        self._advanced_live_memory: dict[str, QPixmap] = {}
        self._advanced_live_memory_limit = 64
        self._advanced_canvas_source_kind = "none"
        # Ordered LRU of ready preview frames (write-through in publish path).
        self._advanced_frame_memory: dict[str, QPixmap] = {}
        self._advanced_frame_memory_limit = 24
        self._advanced_prefetch_queue: deque[tuple[object, ...]] = deque()
        self._advanced_prefetch_running = False
        # LIVE layer pre-render bookkeeping (current + next advanced cues).
        self._live_layer_prefetch_keys: set[str] = set()
        self._live_layer_prefetch_running = False
        self._advanced_render_lock = threading.Lock()
        self._advanced_preview_condition = threading.Condition()
        self._advanced_preview_pending_job: tuple[object, ...] | None = None
        self._advanced_preview_worker_running = False
        self._advanced_preview_worker_stopping = False
        self._advanced_preview_thread: threading.Thread | None = None
        self._advanced_preview_pending_payload: dict[str, object] | None = None
        self._advanced_preview_pending_force = False
        self._advanced_preview_expected_key = ""
        self._advanced_preview_snapshot = None
        self._advanced_ass_hidden: set[str] = set()
        self._visual_ownership = VisualOwnershipStateMachine()
        self._advanced_visual_owner_cue_id = ""
        self._advanced_active_cue_id = ""
        self._advanced_overlay_restore = False
        self._last_subtitle_visibility_trace: dict[str, object] = {}
        self._last_visibility_trace_signature: tuple[object, ...] = ()
        self._visibility_trace_ass_path = ""
        self._visibility_trace_ass_event_count = 0
        self._live_edit_text_overrides: dict[str, str] = {}
        self._live_transform_overrides: dict[str, dict[str, float]] = {}
        self._subtitle_transform_interactive = False
        self._copied_style_payload: dict[str, object] | None = None
        self._overlay_cue_id = ""
        self._review_mode = False
        self._scrub_active = False
        # Style is the first-run Studio tool; persisted projects may override it.
        self._last_context_tab = 1
        self._editor_field_visibility = {
            "speaker": False,
            "start": False,
            "duration": False,
            "language": False,
            "actions": True,
        }
        self._editor_compact_mode: bool | None = None
        self._editor_compact_visibility: tuple[bool, ...] | None = None
        self._studio_shortcuts: list[QShortcut] = []
        self._performance_dialog = None
        self._performance_shortcut = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        self._performance_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._performance_shortcut.activated.connect(self._show_performance_panel)
        self._command_callbacks: dict[str, object] = {}
        self._shortcut_lookup: dict[str, str] = {}
        self._review_space_pending = False
        self._review_space_generation = 0
        self._review_space_playing = False
        self._review_edit_lock: dict[str, str] | None = None
        self._event_filter_installed = False
        self._focus_signal_connected = False
        self._native_key_filter = None
        self._studio_session_id = uuid.uuid4().hex
        self._studio_startup_started_perf = 0.0
        self._studio_startup_project_id = ""
        self._studio_startup_media_path = ""
        self._studio_startup_milestones: dict[str, float] = {}
        self.last_open_profile: dict[str, float] = {}
        self.last_close_profile: dict[str, float] = {}
        self._close_requested = False
        self._close_complete = False
        self._close_thread: threading.Thread | None = None
        self._shortcut_values = self._load_shortcut_values()
        from .interaction_runtime import InteractionRuntimeAudit
        self._interaction_runtime_audit = InteractionRuntimeAudit(self)
        self.runtime_settings = getattr(getattr(parent, "legacy", None), "RUNTIME_SETTINGS", {})
        self.setAcceptDrops(True)
        from .studio_workspace import StudioWorkspaceBuilder
        StudioWorkspaceBuilder(
            self,
            advanced_live_canvas_type=AdvancedLiveCanvas,
            cue_badge_delegate_type=CueBadgeDelegate,
            cue_index_delegate_type=CueIndexDelegate,
            cue_table_model_type=CueTableModel,
            mpv_canvas_type=MpvCanvas,
            position_overlay_type=SubtitlePositionOverlay,
            waveform_timeline_type=WaveformTimeline,
            subtitle_editor_type=_SubtitleEditCardEditor,
            icon=_icon,
            icon_label=_icon_label,
            time_spinbox=_time_spinbox,
        ).build()
        self._install_shortcuts()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._event_filter_installed = True
            app.focusChanged.connect(self._restore_edit_card_focus)
            self._focus_signal_connected = True
            if os.name == "nt":
                self._native_key_filter = _StudioNativeKeyFilter(self)
                app.installNativeEventFilter(self._native_key_filter)
        self.waveform_ready_signal.connect(self._waveform_ready)
        self.waveform_failed_signal.connect(self._waveform_failed)
        self.waveform_progress_signal.connect(self._waveform_progress)
        self.startup_milestone_signal.connect(
            self._apply_startup_milestone_signal, Qt.ConnectionType.QueuedConnection
        )
        self.media_ingest_ready_signal.connect(self._media_ingest_ready)
        self.project_media_probe_ready_signal.connect(self._project_media_probe_ready)
        self.ai_ready_signal.connect(self._ai_ready)
        self.ai_failed_signal.connect(self._ai_failed)
        self.reasr_ready_signal.connect(self._reasr_ready)
        self.reasr_failed_signal.connect(self._reasr_failed)
        self.ass_ready_signal.connect(self._ass_ready)
        self.ass_failed_signal.connect(self._ass_failed)
        self.autosave_ready_signal.connect(self._autosave_ready)
        self.autosave_failed_signal.connect(self._autosave_failed)
        # These signals are emitted by Python worker threads.  Make the GUI
        # handoff explicit: an AutoConnection can otherwise execute the slot
        # against the sender QObject's main-thread affinity while the actual
        # emit originates in a native Python thread.  That leaves a completed
        # renderer file on disk but never publishes its pixels to the child
        # canvas in some headed Windows sessions.
        queued = Qt.ConnectionType.QueuedConnection
        self.ai_stage_signal.connect(self._ai_stage_changed, queued)
        self.ai_web_theme_signal.connect(self._ai_web_theme_ready, queued)
        self.ai_refine_signal.connect(self._ai_refine_ready, queued)
        self.ai_web_adjust_signal.connect(self._web_adjust_ready, queued)
        self.ai_stream_line_signal.connect(self._ai_stream_line, queued)
        self.ai_provider_probe_signal.connect(self._ai_provider_probe_finished, queued)
        self.ai_provider_progress_signal.connect(self._ai_provider_progress, queued)
        self.ai_revision_signal.connect(self._ai_revision_ready, queued)
        self.ai_revision_failed_signal.connect(self._ai_revision_failed, queued)
        self.advanced_preview_ready_signal.connect(self._advanced_preview_ready, queued)
        self.advanced_preview_failed_signal.connect(self._advanced_preview_failed, queued)
        self.ai_variant_preview_ready_signal.connect(self._ai_variant_preview_ready, queued)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._refresh_ass_preview)
        self._edit_preview_timer = QTimer(self)
        self._edit_preview_timer.setSingleShot(True)
        self._edit_preview_timer.setInterval(80)
        self._edit_preview_timer.timeout.connect(self._flush_edit_preview)
        self._transform_preview_timer = QTimer(self)
        self._transform_preview_timer.setSingleShot(True)
        self._transform_preview_timer.setInterval(24)
        self._transform_preview_timer.timeout.connect(self._flush_transform_preview)
        self._advanced_preview_timer = QTimer(self)
        self._advanced_preview_timer.setSingleShot(True)
        self._advanced_preview_timer.setInterval(220)
        self._advanced_preview_timer.timeout.connect(self._flush_advanced_preview_request)
        # A native Python rendering thread cannot rely on PySide's PyObject
        # signal marshalling to wake the GUI loop on every Windows session.
        # Keep the public signals for compatibility, but publish internal
        # renderer results through a lock-safe queue drained on the GUI thread.
        self._advanced_preview_publish_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._advanced_preview_publish_timer = QTimer(self)
        self._advanced_preview_publish_timer.setInterval(16)
        self._advanced_preview_publish_timer.timeout.connect(
            self._drain_advanced_preview_results
        )
        self._advanced_preview_publish_timer.start()
        self._advanced_seek_timer = QTimer(self)
        self._advanced_seek_timer.setSingleShot(True)
        self._advanced_seek_timer.setInterval(250)
        self._advanced_seek_timer.timeout.connect(self._queue_selected_advanced_preview)
        self._initial_preview_timer = QTimer(self)
        self._initial_preview_timer.setSingleShot(True)
        self._initial_preview_timer.setInterval(1_000)
        self._initial_preview_timer.timeout.connect(self._refresh_ass_preview)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1_000)
        self._autosave_timer.timeout.connect(self._autosave)
        self.cover_ready_signal.connect(self._cover_backfill_ready)
        self._visual_update_timer = QTimer(self)
        self._visual_update_timer.setSingleShot(True)
        # Cue counters and QC scan the full project. They are analysis, not
        # frame-critical feedback, so keep them out of the typing/selection path.
        self._visual_update_timer.setInterval(350)
        self._visual_update_timer.timeout.connect(self._flush_deferred_updates)
        self._manual_learning_timer = QTimer(self)
        self._manual_learning_timer.setSingleShot(True)
        self._manual_learning_timer.setInterval(1_500)
        self._manual_learning_timer.timeout.connect(self._commit_manual_term_learning)
        QTimer.singleShot(0, lambda: self._show_teach_hint("studio"))
        # 2026-09-19 进工程提速：把打开路径上的重 import 从 begin() 挪到页面
        # 空闲预热（首次打开曾为 studio_mpv/studio_project 的 import 链付出
        # 数百毫秒主线程成本）。绝不能与媒体挂载抢跑——singleShot(0) 只是
        # 让 import 在首帧绘制后的事件循环空档执行。
        def _preimport_open_path_modules():
            if getattr(self, "_close_requested", False):
                return
            try:
                from . import studio_mpv  # noqa: F401
                from . import media_availability  # noqa: F401
                from .studio_project import load_project  # noqa: F401
            except Exception:
                pass
        QTimer.singleShot(0, _preimport_open_path_modules)
        # 二十六轮：渲染服务预热必须避开启动窗口——启动 2.5s 就 warm 时，
        # 冷 webpack 缓存的全量打包（重 CPU/IO）正好砸在媒体挂载上，用户实测
        # "整个视频层黑屏、约两分钟才开始播放"。改为工程打开确认含特效字幕
        # 且媒体 READY 后再延迟 15s 预热；无特效字幕的工程永不预热。
        QTimer.singleShot(8000, self._maybe_schedule_web_renderer_warm)

    def _maybe_schedule_web_renderer_warm(self, attempts: int = 6) -> None:
        if getattr(self, "_close_requested", False):
            return
        if self.project is None or getattr(self.video, "_startup_state", "") != "READY":
            # 工程还没打开/媒体未就绪——10s 后再看，最多 6 次（约 1 分钟）。
            if attempts > 1:
                QTimer.singleShot(10_000, lambda: self._maybe_schedule_web_renderer_warm(attempts - 1))
            return
        try:
            has_web_cue = any(
                isinstance((payload or {}).get("webTheme"), dict) and payload["webTheme"]
                for payload in (self.project.style_recipes or {}).values()
            )
        except Exception:
            has_web_cue = False
        if not has_web_cue:
            return
        QTimer.singleShot(15_000, self._warm_web_renderer_service)

    def _warm_web_renderer_service(self) -> None:
        if getattr(self, "_close_requested", False):
            return
        try:
            from .live_web_preview import live_preview_enabled

            if not live_preview_enabled():
                return
        except Exception:
            return

        def warm_work() -> None:
            try:
                from .renderer_service import GLOBAL_RENDERER_SERVICE

                GLOBAL_RENDERER_SERVICE.warm_live()
            except Exception:
                pass

        threading.Thread(
            target=warm_work, daemon=True, name="web-renderer-warm",
        ).start()

    def _load_shortcut_values(self) -> dict[str, str]:
        from .studio_shortcuts import studio_default_shortcuts
        try:
            payload = json.loads(studio_settings_path().read_text(encoding="utf-8"))
            values = payload.get("shortcuts", {}) if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            values = {}
        loaded = {
            command_id: str(values.get(command_id) or default)
            for command_id, default in studio_default_shortcuts().items()
        }
        # 2026-09-03：合并工具默认键 M→B（用户指定，B 与 V/C 相邻）。设置对话框
        # 在修复前无法打开，因此任何等于旧默认 "M" 的存量值都来自旧默认而非用户
        # 自定义，一律迁移；用户此后可在设置里自行改回。
        if str(loaded.get("merge_tool") or "").strip().upper() == "M":
            loaded["merge_tool"] = STUDIO_COMMANDS["merge_tool"][1]
        # Letter shortcuts are dispatched only outside text editors, so Review
        # can use its compact R / Shift+R pair without stealing typed text.
        if str(values.get("reasr_review") or "").strip().upper() == "R":
            loaded["reasr_review"] = STUDIO_COMMANDS["reasr_review"][1]
        if loaded.get("toggle_review", "").strip().upper() == "SHIFT+R":
            loaded["toggle_review"] = STUDIO_COMMANDS["toggle_review"][1]
        return loaded

    def _studio_trace(self, event: str, **fields: object) -> None:
        """Queue Studio diagnostics without filesystem work on the GUI thread."""
        GLOBAL_STUDIO_TRACE.emit(event, fields)

    def _studio_startup_begin(self, *, project_id: str, media_path: str = "") -> None:
        self._studio_startup_started_perf = perf_counter()
        self._studio_startup_project_id = str(project_id or "")
        self._studio_startup_media_path = str(media_path or "")
        self._studio_startup_milestones = {}
        self._studio_trace(
            "STUDIO_STARTUP_BEGIN",
            project_id=self._studio_startup_project_id,
            media_path=self._studio_startup_media_path,
            studio_session_id=self._studio_session_id,
        )

    def _studio_mark_startup_milestone(self, name: str, **fields: object) -> bool:
        milestone = str(name or "").strip().upper()
        if not milestone or milestone in self._studio_startup_milestones:
            return False
        started = float(self._studio_startup_started_perf or 0.0)
        elapsed_ms = round((perf_counter() - started) * 1000.0, 3) if started else 0.0
        self._studio_startup_milestones[milestone] = elapsed_ms
        supplied_media_path = fields.pop("media_path", "")
        # The milestone owns elapsed_ms; drop any caller-supplied copy so the
        # **fields splat cannot collide with the explicit kwarg below.
        fields.pop("elapsed_ms", None)
        media_path = str(supplied_media_path or self._studio_startup_media_path)
        if not media_path and self.project is not None:
            media_path = str(self.project.media.path or "")
        self._studio_trace(
            milestone,
            milestone=milestone,
            elapsed_ms=elapsed_ms,
            project_id=self._studio_startup_project_id,
            media_path=media_path,
            studio_session_id=self._studio_session_id,
            **fields,
        )
        aliases = {
            "FIRST_FRAME_READY": "MPV_FIRST_FRAME",
            "FIRST_AUDIO_READY": "MPV_FIRST_AUDIO",
        }
        alias = aliases.get(milestone)
        if alias and alias not in self._studio_startup_milestones:
            self._studio_startup_milestones[alias] = elapsed_ms
            self._studio_trace(
                alias,
                milestone=alias,
                elapsed_ms=elapsed_ms,
                project_id=self._studio_startup_project_id,
                media_path=media_path,
                studio_session_id=self._studio_session_id,
                **fields,
            )
        return True

    def _apply_startup_milestone_signal(self, name: str, fields: object) -> None:
        """Apply worker-originated startup telemetry on the Qt GUI thread."""
        payload = dict(fields) if isinstance(fields, Mapping) else {}
        self._studio_mark_startup_milestone(str(name), **payload)

    def _queue_startup_milestone(self, name: str, **fields: object) -> None:
        self.startup_milestone_signal.emit(str(name), dict(fields))

    def _save_shortcut_values(self) -> None:
        path = studio_settings_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError, TypeError):
            payload = {}
        payload["shortcuts"] = dict(self._shortcut_values)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _studio_preferences(self) -> dict[str, object]:
        try:
            payload = json.loads(studio_settings_path().read_text(encoding="utf-8"))
            value = payload.get("studio_preferences", {}) if isinstance(payload, dict) else {}
            return dict(value) if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _schedule_autosave(self) -> None:
        preferences = self._studio_preferences()
        if preferences.get("autosave_enabled", True) is False:
            self._autosave_timer.stop()
            return
        try:
            seconds = max(5, int(preferences.get("autosave_interval_seconds", 60)))
        except (TypeError, ValueError):
            seconds = 60
        try:
            idle_seconds = max(0.25, float(preferences.get("autosave_idle_seconds", 3)))
        except (TypeError, ValueError):
            idle_seconds = 3.0
        self._autosave_deadline.configure(seconds, idle_seconds)
        delay = self._autosave_deadline.mark_dirty(time.monotonic())
        self._autosave_generation += 1
        self._autosave_timer.start(max(1, round(delay * 1000)))

    def _install_shortcuts(self) -> None:
        for shortcut in self._studio_shortcuts:
            shortcut.deleteLater()
        self._studio_shortcuts.clear()
        self._command_callbacks = {
            "play_pause": self._toggle_playback,
            "selection_tool": lambda: self._set_timeline_tool("selection"),
            "razor_tool": lambda: self._set_timeline_tool("razor"),
            "split_at_playhead": self._split_video_at_playhead,
            "merge_tool": lambda: self._set_timeline_tool("merge"),
            "trim_start": lambda: self._trim_to_playhead("start"),
            "trim_end": lambda: self._trim_to_playhead("end"),
            "mark_in": self._mark_in,
            "mark_out": self._mark_out,
            "save_current_frame": self._save_current_frame,
            "add_marker": self._add_timeline_marker,
            "add_io_candidate": self._add_io_candidate,
            "delete": self._delete_current,
            "undo": self._undo_interactive,
            "redo": self._redo_interactive,
            "redo_alt": self._redo_interactive,
            "save": self.save,
            "frame_left": lambda: self._frame_step(True),
            "frame_right": lambda: self._frame_step(False),
            "previous_cue": lambda: self._step_cue(-1),
            "next_cue": lambda: self._step_cue(1),
            "reverse": lambda: self._shuttle(-1),
            "pause": lambda: self._shuttle(0),
            "forward": lambda: self._shuttle(1),
            "toggle_snap": lambda: self.snap_toggle.setChecked(not self.snap_toggle.isChecked()),
            "split": self._split_current,
            "merge": self._merge_next,
            "merge_previous": lambda: self.cue_controller.merge_with_neighbor(-1),
            "merge_next": lambda: self.cue_controller.merge_with_neighbor(1),
            "confirm_review": self._confirm_current_review,
            "confirm_next_review": lambda: self._confirm_current_review(play_next=True),
            "reasr_review": self._reasr_current,
            "toggle_review": lambda: self._set_review_mode(not self._review_mode),
            "edit_review": self._focus_review_editor,
            "skip_review": self._skip_current_review,
            "exit_review": self._exit_review,
            "add_subtitle": self._add_subtitle_at_playhead,
            "track_gain": self._show_track_gain,
        }
        self._shortcut_lookup.clear()
        for command_id in self._command_callbacks:
            sequence = self._shortcut_values.get(command_id, "")
            if not sequence:
                continue
            canonical = QKeySequence(sequence).toString(QKeySequence.SequenceFormat.PortableText)
            if canonical:
                self._shortcut_lookup[canonical] = command_id
        # 2026-09-19：焦点看门狗——mpv/预览子窗口的异步操作可能在编辑自愈
        # 之后再次把 Win32 焦点打到 NULL。仅在本应用处于前台时低频收回，
        # 绝不打扰用户正在使用的其他应用。
        focus_watchdog = getattr(self, "_focus_watchdog", None)
        if focus_watchdog is None:
            focus_watchdog = self._focus_watchdog = QTimer(self)
            focus_watchdog.setInterval(2000)
            focus_watchdog.timeout.connect(self._focus_watchdog_tick)
        if not focus_watchdog.isActive():
            focus_watchdog.start()

    def _focus_watchdog_tick(self) -> None:
        try:
            app = QApplication.instance()
            if (
                app is None
                or app.applicationState() != Qt.ApplicationState.ApplicationActive
                or not self.isVisible()
            ):
                return
            # 模态/弹出对话框（颜色选择器等）打开期间绝不抢焦点：抢走焦点
            # 会让对话框内的 QLineEdit 触发 editingFinished（失焦即提交），
            # 把用户正在输入的 HEX 中间态吞掉并回写上一合法值（2026-09-20
            # 「HEX 输入被纠正成黑色」根因）。
            if QApplication.activeModalWindow() is not None:
                return
            focus_missing = QApplication.activeWindow() is None
            if os.name == "nt" and not focus_missing:
                import ctypes

                focus_missing = not ctypes.windll.user32.GetFocus()
            if focus_missing or QApplication.activeWindow() is not self.window():
                if not self._editing_has_focus():
                    self._reclaim_window_focus()
        except Exception:
            pass

    _FILTERED_EVENT_TYPES = frozenset({
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.InputMethodQuery,
        QEvent.Type.ShortcutOverride,
        QEvent.Type.KeyPress,
        QEvent.Type.Wheel,
        QEvent.Type.Move,
        QEvent.Type.Resize,
        QEvent.Type.Show,
        QEvent.Type.DevicePixelRatioChange,
        QEvent.Type.ApplicationDeactivate,
        QEvent.Type.ApplicationActivate,
        QEvent.Type.WindowDeactivate,
        QEvent.Type.WindowActivate,
    })

    def eventFilter(self, watched, event) -> bool:
        event_type = event.type()
        scroll = getattr(self, 'project_library_scroll', None)
        if scroll is not None and watched is scroll.viewport() and event_type == QEvent.Type.Resize:
            if self.project is None and hasattr(self, '_hub_card_widgets'):
                self._refresh_studio_empty_state(rescan=False)
        if event_type not in self._FILTERED_EVENT_TYPES:
            return False
        if event_type in (QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonPress):
            if watched in {
                getattr(self, "studio_toolbar", None),
                getattr(self, "filename", None),
                getattr(self, "save_state", None),
            }:
                if event_type == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                    self._toggle_window_maximized()
                    event.accept()
                    return True
                if event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    window = self.window()
                    global_pos = event.globalPosition().toPoint()
                    if window.isMaximized():
                        ratio = global_pos.x() / max(1, window.screen().geometry().width())
                        normal = window.normalGeometry()
                        window.showNormal()
                        target = global_pos - QPoint(round(normal.width() * ratio), 18)
                        # 2026-09-19：DPI 变更/拔显示器后 normalGeometry 可能宽于当前
                        # 屏幕，按比例换算出的 x 可为负——窗口左移出屏表现为"轨头列
                        # 消失、标尺贴死可见左缘"。把结果钳回当前屏幕可用区。
                        screen = window.screen().availableGeometry()
                        window.move(
                            min(max(target.x(), screen.left()), screen.right() - normal.width()),
                            min(max(target.y(), screen.top()), screen.bottom() - 40),
                        )
                    handle = window.windowHandle()
                    if handle is not None and handle.startSystemMove():
                        event.accept()
                        return True
        canvas_editor = (
            getattr(self, "_canvas_editor", None)
            if event_type in (QEvent.Type.InputMethodQuery, QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress)
            else None
        )
        if canvas_editor is not None and watched is canvas_editor:
            if (
                event.type() == QEvent.Type.InputMethodQuery
                and hasattr(canvas_editor, "diagnostic")
                and not getattr(canvas_editor, "_input_query_trace_pending", False)
            ):
                canvas_editor._input_query_trace_pending = True
                def trace_input_query(target=canvas_editor) -> None:
                    target._input_query_trace_pending = False
                    if target is getattr(self, "_canvas_editor", None):
                        target.diagnostic.emit("INPUT_METHOD_QUERY", {"focus": target.hasFocus()})
                QTimer.singleShot(30, trace_input_query)
            if event.type() == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key.Key_E or bool(event.text()):
                    event.accept()
                    return True
            if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key.Key_E:
                    self._studio_trace("KEY_E", editing=True, literal_input=True)
                if event.key() == Qt.Key.Key_Escape:
                    self._studio_trace("KEY_ESCAPE", editing=True)
                    self._cancel_canvas_inline_edit()
                    event.accept()
                    return True
                if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    modifiers = event.modifiers()
                    if modifiers & Qt.KeyboardModifier.ShiftModifier and not modifiers & Qt.KeyboardModifier.ControlModifier:
                        self._studio_trace("KEY_SHIFT_ENTER", editing=True)
                        return super().eventFilter(watched, event)
                    self._studio_trace("KEY_ENTER", editing=True, control=bool(modifiers & Qt.KeyboardModifier.ControlModifier))
                    self._commit_canvas_inline_edit(
                        advance=bool(modifiers & Qt.KeyboardModifier.ControlModifier)
                    )
                    event.accept()
                    return True
            return super().eventFilter(watched, event)
        if canvas_editor is not None and event.type() == QEvent.Type.MouseButtonPress and watched is not canvas_editor and not canvas_editor.isAncestorOf(watched):
            self._commit_canvas_inline_edit()
        editor = getattr(getattr(self, "timeline", None), "_inline_editor", None)
        if (
            editor is not None
            and event.type() == QEvent.Type.MouseButtonPress
            and watched is not editor
            and not editor.isAncestorOf(watched)
        ):
            self.timeline._commit_inline_edit()
        wheel_owners = getattr(self, "_wheel_scroll_owners", {})
        if event.type() == QEvent.Type.Wheel and watched in wheel_owners:
            popup_open = isinstance(watched, QComboBox) and watched.view().isVisible()
            if not popup_open:
                event.ignore()
                QApplication.sendEvent(wheel_owners[watched].viewport(), event)
                return True
        if watched is getattr(self, "video", None) and event.type() in {
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.DevicePixelRatioChange,
        }:
            self.position_overlay.sync_to_video(self.video)
            self._sync_advanced_cue_overlay()
        if event_type == QEvent.Type.Resize and watched is getattr(self, "context_drawer", None):
            # Splitter drags resize the drawer without a page-level
            # resizeEvent; re-tier the tab labels from the drawer itself.
            self._update_context_tab_labels()
        if event.type() == QEvent.Type.ApplicationDeactivate:
            if hasattr(self, "advanced_cue_overlay"):
                self.ensure_active_subtitle_renderer(reason="application_deactivate")
        elif event.type() == QEvent.Type.ApplicationActivate or (
            watched is self.window()
            and event.type() in {
                QEvent.Type.WindowActivate,
                QEvent.Type.WindowDeactivate,
                QEvent.Type.Move,
            }
        ):
            if hasattr(self, "advanced_cue_overlay"):
                QTimer.singleShot(
                    0,
                    lambda: self._ensure_renderer_when_visible(
                        reason="window_activity",
                    ),
                )
        selection_trace = getattr(self, "_selection_latency", None)
        selection_active = bool(
            selection_trace is not None
            and getattr(selection_trace, "_started", 0.0) > 0.0
            and "T6_event_loop_settled" not in getattr(selection_trace, "_markers", {})
        )
        if selection_active:
            if watched is getattr(self, "timeline", None) and event.type() == QEvent.Type.Paint:
                selection_trace.increment("timeline_paint")
            elif event.type() == QEvent.Type.LayoutRequest:
                selection_trace.increment("layout")
            elif event.type() == QEvent.Type.PolishRequest:
                selection_trace.increment("style_polish")
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            app = QApplication.instance()
            active = app.activeWindow() if app is not None else None
            target_in_page = watched is self or (
                isinstance(watched, QWidget) and self.isAncestorOf(watched)
            )
            active_for_page = active is self.window() or (
                active is None
                and app is not None
                and app.applicationState() == Qt.ApplicationState.ApplicationActive
            )
            watched_is_editor = (
                isinstance(watched, QLineEdit) and not watched.isReadOnly()
            ) or (
                isinstance(watched, QPlainTextEdit) and not watched.isReadOnly()
            ) or isinstance(watched, QAbstractSpinBox) or (
                isinstance(watched, QComboBox) and watched.isEditable()
            )
            if (
                self.isVisible()
                and target_in_page
                and active_for_page
                and not watched_is_editor
                and not self._editing_has_focus()
            ):
                if self._review_mode and event.key() == Qt.Key.Key_Escape:
                    self._exit_review()
                    event.accept()
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    # Let an in-progress timeline gesture consume Escape first.
                    self.timeline.cancel_timing_edit()
                    if self.timeline._clip_drag:
                        self.timeline.keyPressEvent(event)
                    self.cue_controller.cancel_selection()
                    event.accept()
                    return True
                sequence = QKeySequence(event.keyCombination()).toString(
                    QKeySequence.SequenceFormat.PortableText
                )
                if (
                    sequence.casefold() == "ctrl+a"
                    and self.project
                    and self._cue_list_has_focus()
                ):
                    self._selection_latency.begin()
                if not event.isAutoRepeat() and self._dispatch_shortcut_sequence(sequence):
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _show_performance_panel(self) -> None:
        from .studio_performance import StudioPerformanceDialog
        if self._performance_dialog is None:
            self._performance_dialog = StudioPerformanceDialog(self)
        self._performance_dialog.show()
        self._performance_dialog.raise_()
        self._performance_dialog.activateWindow()

    def _dispatch_shortcut_sequence(self, sequence: str) -> bool:
        if sequence.casefold() == "ctrl+shift+p":
            self._show_performance_panel()
            return True
        # E is a core Studio edit command in both normal and Review modes.
        # Keep it explicit so a stale/custom shortcut map cannot make the
        # visible keyboard contract silently disappear.
        if sequence.casefold() == "ctrl+shift+c" and self.project and self.selected_cue_id:
            self._copy_subtitle_style()
            return True
        if sequence.casefold() == "ctrl+shift+v" and self.project and self.selected_cue_id:
            self._paste_subtitle_style()
            return True
        if (
            sequence.casefold() == "ctrl+a"
            and self.project
            and self._cue_list_has_focus()
        ):
            self._select_all_timeline_cues()
            return True
        if sequence in {"E", "e"} and self.project:
            self._studio_trace(
                "KEY_E",
                key="E",
                focus_widget=type(QApplication.focusWidget()).__name__ if QApplication.focusWidget() else "None",
                active_window=QApplication.activeWindow() is self.window(),
                selected_cue=self.selected_cue_id,
                review_mode=self._review_mode,
            )
            self._edit_subtitle_at_playhead()
            return True
        command_id = self._shortcut_lookup.get(sequence)
        in_review = bool(self._review_mode)
        if in_review and sequence in {"1", "2", "3", "4"}:
            self._adopt_review_candidate(int(sequence) - 1)
            return True
        if in_review and sequence == "Space":
            self._review_space_pending = False
            self._play_review_context()
            return True
        if in_review and sequence in {"Esc", "Escape"}:
            self._exit_review()
            return True
        elif in_review and sequence in {"Enter", "Return"}:
            command_id = "confirm_review"
        elif in_review and sequence in {"Up", "Down"}:
            self._step_priority(-1 if sequence == "Up" else 1)
            return True
        review_only = {
            "confirm_review",
            "confirm_next_review",
            "reasr_review",
            "skip_review",
            "exit_review",
        }
        if command_id in review_only and not in_review:
            return False
        callback = (
            self._play_review_context
            if command_id == "replay_review"
            else self._command_callbacks.get(command_id or "")
        )
        if callback is None:
            return False
        with self._interaction_runtime_audit.measure(command_id or sequence):
            callback()
        return True

    def _clear_review_space(self, generation: int) -> None:
        if generation == self._review_space_generation:
            self._review_space_pending = False

    def _step_priority(self, delta: int) -> None:
        rows = self.cue_model.rowCount()
        if rows <= 0:
            return
        current = self.cue_model.row_for_cue_id(self.selected_cue_id)
        if current < 0:
            target_row = 0 if delta >= 0 else rows - 1
        else:
            target_row = max(0, min(rows - 1, current + int(delta)))
        cue = self.cue_model.cue_at(target_row)
        self.select_cue(cue.id)
        if cue is not None:
            self._seek(cue.start_ms / 1000.0)

    def _editing_has_focus(self) -> bool:
        # Do not rely solely on QApplication.focusWidget(): native child
        # editors have a short None-focus window while Windows IME starts.
        # Presence of the visible canvas editor is the authoritative editing
        # state and disables every global/native Studio shortcut.
        canvas_editor = getattr(self, "_canvas_editor", None)
        shortcuts = getattr(self, "_shortcut_settings_panel", None)
        if shortcuts is not None and shortcuts.isVisible():
            return True
        if canvas_editor is not None and canvas_editor.isVisible():
            return True
        focus = QApplication.focusWidget()
        if focus is None:
            return False
        # 任何本应用窗口（含模态对话框）里的可编辑控件都算"编辑中"：焦点
        # 抢回只针对 mpv/预览子窗口把 Win32 焦点打到 NULL 的场景，绝不针
        # 对用户正在输入的弹窗输入框（颜色选择器 HEX 等，2026-09-20）。
        focus_window = focus.window()
        if focus_window is None:
            return False
        if focus_window is not self and not self.isAncestorOf(focus_window):
            if not focus_window.isVisible():
                return False
        return (
            isinstance(focus, QLineEdit) and not focus.isReadOnly()
        ) or (
            isinstance(focus, QPlainTextEdit) and not focus.isReadOnly()
        ) or isinstance(focus, QAbstractSpinBox) or (
            isinstance(focus, QComboBox) and focus.isEditable()
        )

    def _restore_edit_card_focus(self, _previous, current) -> None:
        editor = getattr(self, "_canvas_editor", None)
        app = QApplication.instance()
        if (
            current is not None
            or editor is None
            or not editor.isVisible()
            or app is None
            or app.applicationState() != Qt.ApplicationState.ApplicationActive
            or not self.isVisible()
        ):
            return
        QApplication.setActiveWindow(self.window())
        editor.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _show_shortcut_settings(self) -> None:
        if getattr(self, "_shortcut_settings_panel", None) is not None:
            return
        from .studio_shortcuts import ShortcutSettingsPanel
        previous = (self.context_panel.isVisible(), self.upper_splitter.sizes(), QApplication.focusWidget())
        panel = ShortcutSettingsPanel(self._shortcut_values, self.context_stack)
        self._shortcut_settings_panel = panel
        self.context_stack.addWidget(panel)
        self.context_stack.setCurrentWidget(panel)
        self.context_panel.show()
        self.context_expand_button.setChecked(True)

        def finish(save=False):
            if save:
                before = self._shortcut_values
                try:
                    self._shortcut_values = panel.values()
                    self._save_shortcut_values()
                    self._install_shortcuts()
                except Exception as exc:
                    self._shortcut_values = before
                    bind_text(panel.conflict_label, '保存失败：{exc}', exc=exc)
                    return
            self.context_stack.setCurrentWidget(self.context_drawer)
            self.context_stack.removeWidget(panel)
            self._shortcut_settings_panel = None
            panel.deleteLater()
            self.context_panel.setVisible(previous[0])
            self.context_expand_button.setChecked(previous[0])
            if self.upper_splitter.sizes() != previous[1]:
                self.upper_splitter.setSizes(previous[1])
            if previous[2] is not None:
                previous[2].setFocus(Qt.FocusReason.OtherFocusReason)

        panel.accepted.connect(lambda: finish(True))
        panel.rejected.connect(lambda: finish(False))

    def _tool_button(self, icon_name: str, tooltip: str, slot) -> QToolButton:
        button = QToolButton()
        button.setObjectName("studioTool")
        install_themed_icon(button, icon_name)
        button.setIconSize(QSize(24, 24))
        button.setMinimumSize(QSize(32, 32))
        button.setProperty('commandSource', tooltip)
        bind_text(button, tooltip, property='toolTip')
        button.clicked.connect(slot)
        return button

    @staticmethod
    def _toolbar_divider() -> QFrame:
        divider = QFrame()
        divider.setObjectName("toolbarDivider")
        divider.setFrameShape(QFrame.Shape.NoFrame)
        return divider

    def _window_control(self, icon_name: str, tooltip: str, slot, *, close: bool = False) -> QToolButton:
        """Studio-local chrome remains available while the global header is hidden."""
        button = QToolButton()
        button.setObjectName("studioWindowControlClose" if close else "studioWindowControl")
        button.setAutoFillBackground(False)
        button.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        install_themed_icon(button, icon_name, "window_control")
        button.setIconSize(QSize(13, 13))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    def _toggle_window_maximized(self) -> None:
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()
        self._sync_window_controls()

    def _sync_window_controls(self) -> None:
        if not hasattr(self, "studio_maximize_button"):
            return
        maximized = self.window().isMaximized()
        install_themed_icon(
            self.studio_maximize_button,
            "fa5s.compress-alt" if maximized else "fa5s.square",
            "window_control",
        )
        (bind_text(self.studio_maximize_button, '还原窗口', property='toolTip') if maximized else bind_text(self.studio_maximize_button, '最大化', property='toolTip'))

    def _begin_list_inline_edit(self, index: QModelIndex) -> None:
        if index.isValid() and index.column() == 3:
            cue_id = str(self.cue_model.data(index, Qt.ItemDataRole.UserRole) or "")
            if cue_id:
                self.select_cue(cue_id)
                self._begin_canvas_inline_edit()

    def _context_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("contextCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(11, 9, 11, 10)
        card_layout.setSpacing(7)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        card_layout.addWidget(heading)
        return card, card_layout

    def _update_editor_compactness(self) -> None:
        if not hasattr(self, "center_splitter"):
            return
        width = self.center_splitter.width()
        if self._editor_compact_mode is None:
            compact = width < 930
        elif self._editor_compact_mode:
            compact = width < 970
        else:
            compact = width < 900
        visibility = tuple(self._editor_field_visibility.values())
        if (
            compact == self._editor_compact_mode
            and visibility == self._editor_compact_visibility
        ):
            return
        self._editor_compact_mode = compact
        self._editor_compact_visibility = visibility
        self.editor_title.setVisible(not compact)
        self.editor_fields.setSpacing(2 if compact else 5)
        bind_text(self.speaker_label, "角色" if compact else "说话人")
        self.start_label.setVisible(not compact and self._editor_field_visibility["start"])
        self.duration_label.setVisible(not compact and self._editor_field_visibility["duration"])
        bind_text(self.start_label, '开始')
        bind_text(self.duration_label, '时长')
        self.speaker.setMinimumWidth(70 if compact else 104)
        self.speaker.setMaximumWidth(84 if compact else 150)
        self.start_ms.setPrefix(tr("始 ") if compact else "")
        self.duration_ms.setPrefix(tr("长 ") if compact else "")
        bind_text(self.start_ms, '开始时间', property='toolTip')
        bind_text(self.duration_ms, '时长', property='toolTip')
        for spin in (self.start_ms, self.duration_ms):
            spin.setMinimumWidth(112)
            spin.setMaximumWidth(120 if compact else 138)
        bind_text(self.mono_button, "单" if compact else "单语")
        bind_text(self.bilingual_button, "双" if compact else "双语")

    def _update_cue_table_layout(self) -> None:
        table = getattr(self, "cue_table", None)
        if table is None:
            return
        responsive = getattr(table, "apply_responsive_layout", None)
        if callable(responsive):
            responsive()

    def _update_context_tab_labels(self) -> None:
        drawer = getattr(self, "context_drawer", None)
        if drawer is None:
            return
        tabbar = drawer.tabBar()
        tabbar.setElideMode(Qt.TextElideMode.ElideNone)
        tabbar.setUsesScrollButtons(False)
        # Expanding stays on: tabs share the drawer width (centered group).
        full = ("AI设计", "样式", "视频", "剪辑助手", "素材")
        medium = ("AI", "样式", "视频", "剪辑", "素材")
        width = max(1, drawer.width())
        # Compact glyphs leave room for readable labels in the default drawer.
        if width >= 460:
            labels, mode, icon_only = full, "full", False
        elif width >= 370:
            labels, mode, icon_only = medium, "medium", False
        else:
            labels, mode, icon_only = ("",) * len(full), "icon", True
        if getattr(self, "_context_tab_mode", "") == mode:
            return
        self._context_tab_mode = mode
        drawer.setProperty("tabMode", mode)
        drawer.style().unpolish(drawer)
        drawer.style().polish(drawer)
        tabbar.style().unpolish(tabbar)
        tabbar.style().polish(tabbar)
        for index, label in enumerate(labels):
            if index >= drawer.count():
                break
            drawer.setTabText(index, tr(label))
            drawer.setTabToolTip(index, tr(full[index]))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_studio_compact_commands"):
            self._sync_navigation_chrome()
        self._update_editor_compactness()
        self._update_cue_table_layout()
        drawer = getattr(self, "context_drawer", None)
        if drawer is not None:
            self._update_context_tab_labels()
        if hasattr(self, "position_overlay") and self.position_overlay.isVisible():
            self.position_overlay.sync_to_video(self.video)
            self._sync_transform_visual_overlay()
        if getattr(self, "_review_mode", False):
            QTimer.singleShot(0, self._refresh_review_summary_strip)
        if hasattr(self, "studio_empty"):
            # workspace_host's StackAll layout owns both page rectangles.
            if self.project is None and not getattr(self, "_hub_refresh_pending", False):
                self._hub_refresh_pending = True
                def refresh_hub() -> None:
                    self._hub_refresh_pending = False
                    self._refresh_studio_empty_state(rescan=False)
                QTimer.singleShot(0, refresh_hub)

    def _show_teach_hint(self, key: str) -> None:
        if self.project is None:
            return
        messages = {
            "studio": "Space：播放 / 暂停    Q / W：播放头前 / 后波纹剪切（未锁视频轨）    双击时间轴字幕：直接编辑",
            "razor": "C：剃刀（按住拖动看两句预览，松开切开）    V：返回选择",
            "priority_review": "Enter：确认并继续    Space：重听    Ctrl+Shift+R：重新识别    E：编辑",
        }
        if key not in messages or key in self._session_teach_hints or not self._teach_hints.should_show(key):
            return
        try:
            self._teach_hints.mark_shown(key)
        except OSError:
            pass
        self._session_teach_hints.add(key)
        bind_text(self.teach_text, messages[key])
        self.teach_banner.show()

    def show_project_hub(self, *, skip_dirty_guard: bool = False) -> bool:
        return self.project_controller.show_project_hub(skip_dirty_guard=skip_dirty_guard)

    def _reset_studio_layout_preferences(self) -> None:
        if self.project:
            self.project.studio_state.pop("layout", None)
            self._apply_default_workspace_layout()

    def _properties_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        heading = QLabel("当前字幕属性")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        card, card_layout = self._context_card("字幕信息")
        self.property_speaker = QLabel("说话人：-")
        self.property_timing = QLabel("字幕：-")
        self.property_style = QLabel("样式：-")
        for label in (self.property_speaker, self.property_timing, self.property_style):
            label.setWordWrap(True)
            label.setObjectName("contextValue")
            card_layout.addWidget(label)
        layout.addWidget(card)
        layout.addStretch(1)
        return panel

    def _populate_speakers(self) -> None:
        return self.project_controller._populate_speakers()

    def selected_cue_ids(self) -> list[str]:
        return self.cue_controller.selected_cue_ids()

    def _timeline_selection_changed(self, cue_ids) -> None:
        return self.cue_controller.timeline_selection_changed(cue_ids)

    def _smart_align_current(self) -> None:
        return self.cue_controller.smart_align_current()

    def _smart_align_selected(self) -> None:
        return self.cue_controller.smart_align_selected()

    def _toggle_loop_current(self) -> None:
        if not self.project or not self.selected_cue_id:
            return
        if self._loop_enabled:
            self._loop_enabled = False
            self._loop_region_ms = None
            self.loop_cue_button.setChecked(False)
            return
        cue = self._cue_lookup.get(self.selected_cue_id)
        if cue is None:
            return
        self._loop_region_ms = loop_region(cue, duration_ms=self.project.media.duration_ms)
        self._loop_enabled = True
        self.loop_cue_button.setChecked(True)
        self._seek(self._loop_region_ms[0] / 1000.0)
        self._show_studio_hint(tr('循环试听 {value0} - {value1}', value0=_format_ms(self._loop_region_ms[0]), value1=_format_ms(self._loop_region_ms[1])))

    def _show_studio_hint(self, message: str) -> None:
        if hasattr(self, "save_state"):
            bind_text(self.save_state, message)

    def _open_speaker_manager(self) -> None:
        if not self.project:
            studio_message_box(self, QMessageBox.Icon.Information, tr('说话人管理'), tr('请先打开字幕工程。'))
            return
        if not self.project.speakers:
            studio_message_box(self, QMessageBox.Icon.Information, tr('说话人管理'), tr('当前工程没有可管理的说话人。'))
            return
        dialog = SpeakerManagerDialog(self)
        dialog.exec()

    def _open_find_replace(self) -> None:
        if not self.project:
            studio_message_box(self, QMessageBox.Icon.Information, tr('批量替换'), tr('请先打开字幕工程。'))
            return
        from .studio_find_replace import FindReplaceDialog

        dialog = FindReplaceDialog(self, self)
        dialog.exec()

    def _speaker_structure_changed(self) -> None:
        return self.cue_controller.speaker_structure_changed()

    def select_cue(self, cue_id: str, *, hydrate: bool = True) -> None:
        return self.cue_controller.select_cue(cue_id, hydrate=hydrate)

    def _changed(self) -> None:
        return self.cue_controller.changed()

    def _sequence_changed(self, before=None, after=None, *, _from_delta: bool = False) -> None:
        """Refresh a structural edit while preserving editing context.

        Structural commands keep the original media resident in mpv.  The
        playhead is translated through source time, and the current viewport is
        restored verbatim instead of being reset by a media reload.
        """
        playhead = int(self.timeline.playhead_ms)
        visible_start = int(self.timeline.visible_start_ms)
        visible_duration = int(self.timeline.visible_duration_ms)
        mapped_ms = playhead
        mapped_segment_id = ""
        source_before = None
        source_after = None
        if before is not None and after is not None:
            from .studio_sequence_mapper import map_playhead_between_sequences

            source_before = timeline_to_source(before, playhead)
            mapped = map_playhead_between_sequences(before, after, playhead)
            if mapped is not None:
                mapped_ms = mapped.timeline_ms
                mapped_segment_id = mapped.segment_id
            mapped_ms = min(max(0, mapped_ms), timeline_duration_ms(self.project))
            source_after = timeline_to_source(after, mapped_ms)
        component_started = perf_counter()
        previous_cues = list(self._cue_lookup.values())
        cues_changed = bool(
            self.project is not None and previous_cues != list(self.project.cues)
        )
        if cues_changed and not _from_delta:
            self.cue_controller.model_changed()
        elif not _from_delta:
            bind_text(self.save_state, translate('未保存', current_language()))
            self._schedule_autosave()
        self._interaction_runtime_audit.add_component(
            "model_update_ms", (perf_counter() - component_started) * 1000.0
        )
        # Structural edits are model-only actions. A repaint may expose a new
        # thumbnail position, but must not start ffmpeg as an edit side effect.
        component_started = perf_counter()
        self.timeline.thumbnail_requests_enabled = False
        self._refresh_edit_playback_state()
        self.timeline.set_visible_window(visible_start, visible_duration)
        self.timeline.set_playhead(mapped_ms)
        if mapped_segment_id:
            self.timeline.selected_segment_id = mapped_segment_id
            self.timeline.selected_segment_ids = {mapped_segment_id}
        else:
            self.timeline.selected_segment_id = ""
            self.timeline.selected_segment_ids.clear()
        # Structural V1 edits only alter the video lane and the playhead. Keep
        # subtitle tracks/waveform out of the dirty region.
        self.timeline.update(self.timeline._video_track_rect().toAlignedRect())
        self.position_label.setText(format_timeline_timecode(mapped_ms))
        duration = timeline_duration_ms(self.project) if self.project else 0
        if duration:
            self.position_slider.setValue(round(mapped_ms * 1000 / duration))
        self._interaction_runtime_audit.add_component(
            "timeline_update_ms", (perf_counter() - component_started) * 1000.0
        )
        if not getattr(self, '_defer_clip_edit_seek', False) and (
            source_before is None
            or source_after is None
            or source_before.source_ms != source_after.source_ms
        ):
            component_started = perf_counter()
            self._seek(mapped_ms / 1000.0)
            self._interaction_runtime_audit.add_component(
                "mpv_ipc_ms", (perf_counter() - component_started) * 1000.0
            )
        # 2026-09-19：结构编辑（剃刀分割等）会触发 mpv/预览子窗口操作，原生
        # 子窗口可能把 Win32 焦点打到 NULL——Qt activeWindow=None 后 eventFilter
        # 与 native 键桥全部停摆，空格/保存/撤销静默失效（真机复现）。编辑完
        # 成即收回键盘焦点；文本编辑中不打扰。
        self._reclaim_window_focus()

    def _reclaim_window_focus(self) -> None:
        """Best-effort keyboard-focus reclamation after native child churn.

        activateWindow() alone is throttled by the Windows foreground lock;
        pair it with a Qt-level activeWindow fix and, when Win32 focus is
        NULL (no window owns it), a direct SetFocus on our own window.
        """
        try:
            from PySide6.QtWidgets import QApplication as _QApp

            window = self.window()
            if (
                _QApp.activeWindow() is window
                or not window.isVisible()
                or self._editing_has_focus()
            ):
                return
            _QApp.setActiveWindow(window)
            window.raise_()
            window.activateWindow()
            if os.name == "nt":
                import ctypes

                user32 = ctypes.windll.user32
                if not user32.GetFocus():
                    user32.SetFocus(int(window.winId()))
        except Exception:
            pass

    def _undo_interactive(self) -> None:
        with self._interaction_runtime_audit.measure("Undo"):
            self.undo_stack.undo()

    def _redo_interactive(self) -> None:
        with self._interaction_runtime_audit.measure("Redo"):
            self.undo_stack.redo()

    def _cue_changed(
        self,
        cue_id: str,
        *,
        timing: bool = False,
        columns: tuple[int, ...] | None = None,
    ) -> None:
        return self.cue_controller.cue_changed(cue_id, timing=timing, columns=columns)

    def _refresh_selected_cue_properties(self, cue: StudioCue) -> None:
        if hasattr(self, "property_speaker"):
            bind_text(self.property_speaker, '说话人：{value0}', value0=_speaker_name(self.project, cue.speaker_id))
            bind_text(self.property_timing, '字幕：{value0}  /  {value1}', value0=_format_ms(cue.start_ms), value1=_format_ms(cue.end_ms - cue.start_ms))
            bind_text(self.property_style, '样式：{value0}  ·  动效：{value1}', value0=cue.style_id, value1=cue.effect_id)

    def _sync_selected_cue_advanced(self, recipe_payload) -> None:
        if isinstance(recipe_payload, Mapping) and recipe_payload and route_recipe(recipe_payload).engine == "remotion":
            self._load_advanced_motion_controls(recipe_payload)
        elif hasattr(self, "advanced_cue_overlay"):
            self._revoke_advanced_preview(reason="native_route")

    def _revoke_advanced_preview(self, *, reason: str = "native_route") -> int:
        """Invalidate all Advanced work before Native can become foreground.

        A route switch must retire both the visible canvas and any queued or
        running Fidelity request.  The worker may still finish, but its
        generation/identity contract can no longer match the revoked state.
        """
        # Web-live has its own worker/session, independent of Fidelity state.
        # Retire it first so queued frames cannot re-publish after this revoke.
        self._stop_web_live_preview(reason)
        state = self._advanced_preview_state
        already_revoked = bool(
            state.identity is None
            and getattr(self, "_advanced_preview_snapshot", None) is None
            and getattr(self, "_advanced_preview_pending_job", None) is None
            and getattr(self, "_advanced_preview_pending_payload", None) is None
            and getattr(self, "_advanced_canvas_source_kind", "none") == "none"
            and not bool(getattr(self, "advanced_cue_overlay", None) and self.advanced_cue_overlay.isVisible())
            and not bool(getattr(self, "video", None) and self.video.ADVANCED_OVERLAY_ID
                         in self.video.active_compositor_overlay_ids())
        )
        if already_revoked:
            return int(state.generation)
        timer = getattr(self, "_advanced_preview_timer", None)
        if timer is not None:
            timer.stop()
        condition = getattr(self, "_advanced_preview_condition", None)
        if condition is not None:
            with condition:
                self._advanced_preview_pending_job = None
                condition.notify_all()
        else:
            self._advanced_preview_pending_job = None
        self._advanced_preview_pending_payload = None
        self._advanced_preview_pending_force = False
        self._advanced_preview_expected_key = ""
        generation = state.invalidate_current()
        self._advanced_preview_generation = generation
        state.identity = None
        state.fallback()
        self._advanced_preview_snapshot = None
        self._advanced_cue_pixmap = QPixmap()
        self._advanced_canvas_source_kind = "none"
        self._advanced_active_cue_id = ""
        canvas = getattr(self, "advanced_cue_overlay", None)
        if canvas is not None:
            # This is an explicit route revocation while the cue may still be
            # inside its time range. Retire its lifecycle before hideEvent, or
            # the active-cue guard rejects removal and native ASS stays muted.
            canvas.set_overlay_lifecycle_context(reason=reason, cue_active=False)
            canvas.revoke_publication()
            canvas.hide()
        self._studio_trace(
            "ADVANCED_REVOKE",
            reason=str(reason),
            generation=generation,
            cue_id=getattr(self, "_advanced_visual_owner_cue_id", ""),
        )
        return generation

    def _sync_loop_region_after_cue_change(self, cue_id: str) -> None:
        if self._loop_enabled and cue_id == self.selected_cue_id and self.project:
            cue = self._cue_lookup.get(cue_id)
            if cue is not None:
                self._loop_region_ms = loop_region(cue, duration_ms=self.project.media.duration_ms)

    def _studio_speaker_name(self, speaker_id: str) -> str:
        return _speaker_name(self.project, speaker_id)

    def _schedule_render_refresh(self, cue_id: str = "") -> None:
        """Single render entry shared by every Studio mutation path."""
        if getattr(self,'_review_fast_select',False):
            self._preview_timer.start()
            return
        if cue_id and cue_id == self.selected_cue_id:
            cue = self._cue_lookup.get(cue_id)
            if cue is not None and hasattr(self, "position_overlay"):
                self.position_overlay.set_text(cue.text)
                self.position_overlay.sync_to_video(self.video)
                self._sync_transform_visual_overlay()
                self._overlay_cue_id = cue.id
        self._preview_timer.start()

    def _flush_deferred_updates(self) -> None:
        if not self.project:
            return
        if self._qc_full_scan_pending:
            self._refresh_review_risks()
        elif self._pending_qc_cue_ids:
            self._refresh_review_risks(cue_ids=set(self._pending_qc_cue_ids))
        if self.cue_model.filter_status in {"priority", "critical"}:
            self.cue_model.refresh()
        self._refresh_cue_list_summary()

    def _text_changed(self) -> None:
        return self.cue_controller.text_changed()

    def _commit_manual_term_learning(self, cue_id: str | None = None) -> None:
        return self.cue_controller.commit_manual_term_learning(cue_id)

    def _translation_changed(self) -> None:
        return self.cue_controller.translation_changed()

    def _speaker_changed(self, _index: int) -> None:
        return self.cue_controller.speaker_changed(_index)

    def _timing_fields_changed(self) -> None:
        return self.cue_controller.timing_fields_changed()

    def _push_timing(self, cue_id: str, start: int, end: int) -> None:
        return self.cue_controller.set_timing(cue_id, start, end)

    def _timeline_timing_changed(self, cue_id: str, start: int, end: int) -> None:
        return self.cue_controller.timeline_timing_changed(cue_id, start, end)

    def _add_subtitle_at_playhead(self) -> None:
        return self.cue_controller.add_subtitle_at_playhead()

    def _timeline_speaker_changed(self, cue_id: str, _old_speaker: str, new_speaker: str) -> None:
        return self.cue_controller.timeline_speaker_changed(cue_id, _old_speaker, new_speaker)

    def _timeline_text_edited(self, cue_id: str, translation: bool, value: str) -> None:
        return self.cue_controller.timeline_text_edited(cue_id, translation, value)

    def _nudge(self, delta: int) -> None:
        return self.cue_controller.nudge(delta)

    def _set_timeline_tool(self, mode: str) -> None:
        mode = mode if mode in {"razor", "merge"} else "selection"
        self.timeline.set_tool_mode(mode)
        self.selection_tool_button.setChecked(mode == "selection")
        self.razor_tool_button.setChecked(mode == "razor")
        merge_button = getattr(self, "merge_tool_button", None)
        if merge_button is not None:
            merge_button.setChecked(mode == "merge")
        if mode == "razor":
            self._show_teach_hint("razor")

    def _toggle_timeline_snap(self, enabled: bool) -> None:
        self.timeline.set_snap_enabled(bool(enabled))
        if self.project:
            self._schedule_autosave()

    def _go_to_timecode(self) -> None:
        milliseconds = parse_timeline_timecode(
            self.timecode_input.text() if hasattr(self, "timecode_input") else ""
        )
        if milliseconds is None:
            if hasattr(self, "timecode_input"):
                bind_text(self.timecode_input, '时间码格式：mm:ss.ms 或 hh:mm:ss.ms', property='toolTip')
            return
        duration = timeline_duration_ms(self.project) if self.project else 0
        milliseconds = min(max(0, milliseconds), max(0, int(duration or milliseconds)))
        if hasattr(self, "timecode_input"):
            self.timecode_input.setText(format_timeline_timecode(milliseconds))
        self._seek(milliseconds / 1000.0)

    def _merge_pair_clicked(self, prior_cue_id: str, clicked_cue_id: str) -> None:
        """Merge tool two-click semantics: first click selects the anchor,
        second click on another cue merges the pair (adjacent in time order)."""
        if not prior_cue_id or prior_cue_id == clicked_cue_id:
            return
        return self.cue_controller.merge_pair(prior_cue_id, clicked_cue_id)

    def _trim_to_playhead(self, edge: str) -> None:
        return self.cue_controller.trim_to_playhead(edge)

    def _split_at(self, cue_id: str, split_ms: int) -> None:
        return self.cue_controller.split_at(cue_id, split_ms)

    def _split_current(self) -> None:
        return self.cue_controller.split_current()

    def _merge_next(self) -> None:
        return self.cue_controller.merge_next()

    def _delete_current(self) -> None:
        from .studio_track_delete import delete_current
        return delete_current(self)

    def _delete_selected_timeline_segments(self) -> None:
        project = self.project
        if project is None:
            return
        sequence = sequence_of(project)
        selected = [item.id for item in sequence.segments if item.id in self.timeline.selected_segment_ids]
        if sequence.video_track_locked or not selected:
            return
        with self._interaction_runtime_audit.measure("Delete"):
            from .studio_track_delete import delete_clips
            from .studio_media_pool import primary_video_track_id
            delete_clips(self, primary_video_track_id(project), selected)

    def _select_all_timeline_cues(self) -> None:
        if not self.project:
            return
        self._manual_selection_hold = True
        current_markers = self._selection_latency.snapshot()["markers_ms"]
        if not current_markers or "T1_shortcut_handler" in current_markers:
            self._selection_latency.begin()
        token = self._selection_latency.token
        self._selection_latency.mark("T1_shortcut_handler", token=token)
        active_id = self.selected_cue_id or (
            self.project.cues[0].id if self.project.cues else ""
        )
        scope = SelectionScope.all(len(self.project.cues), active_id)
        self.cue_table.expect_selected_rows_paint(token)
        self.timeline.selected_segment_id = ""
        self.timeline.selected_segment_ids.clear()
        self.cue_controller.apply_selection_scope(scope)
        self._selection_settle_frame(token, 3)

    def _cue_table_selection_changed(self, *_args) -> None:
        self._selection_latency.increment("selectionChanged")
        self.cue_controller.table_selection_changed()

    def _cue_table_clicked(self, _index) -> None:
        self._manual_selection_hold = bool(self.selected_cue_id)
        if self._manual_selection_hold:
            self.timeline.selected_video_clip_id = ''
            self.timeline.selected_track_header = None

    def _cue_table_current_changed(self, *_args) -> None:
        self._selection_latency.increment("currentChanged")

    def _selection_first_visual(self, token: int) -> None:
        self._selection_latency.increment("table_paint")
        self._selection_latency.mark("T4_first_visible_selected_row_paint", token=token)

    def _selection_settle_frame(self, token: int, remaining: int) -> None:
        if token != self._selection_latency.token:
            return
        if remaining > 0:
            QTimer.singleShot(
                16,
                lambda: self._selection_settle_frame(token, remaining - 1),
            )
            return
        self._selection_latency.mark("T6_event_loop_settled", token=token)

    def selection_latency_snapshot(self) -> dict[str, object]:
        return self._selection_latency.snapshot()

    def save(self) -> None:
        return self.project_controller.save(
            save_project_fn=save_project, message_box_fn=studio_message_box
        )

    def _wait_for_autosave_worker(self, timeout: float = 2.0) -> None:
        worker = self._autosave_thread
        if worker and worker.is_alive():
            worker.join(timeout=max(0.0, float(timeout)))
        if worker and worker.is_alive():
            raise TimeoutError("自动保存仍在写入；正式保存未阻塞界面，可稍后重试。")

    def _autosave(self) -> None:
        if getattr(getattr(self, "_cue_timing_preview", None), "active", False):
            self._autosave_timer.start(100)
            return
        if not self.project or (
            self.undo_stack.isClean() and not self._recovered_autosave_pending
        ):
            return
        delay = self._autosave_deadline.delay_seconds(time.monotonic())
        if delay > 0:
            self._autosave_timer.start(max(1, round(delay * 1000)))
            return
        self._capture_studio_state()
        if not self._autosave_worker_running:
            self._autosave_deadline.mark_started()
            bind_text(self.save_state, translate('正在自动保存…', current_language()))
            self.save_state.setToolTip("")
            self._start_autosave_worker(self._autosave_generation)

    def _start_autosave_worker(self, generation: int) -> None:
        if not self.project:
            return
        runtime = getattr(self.project, "_studio_state_runtime", None)
        if runtime is not None and runtime._active is not None:
            self._autosave_timer.start(25)
            return
        if self._revision_store is None:
            self._revision_store = StudioRevisionStore(self.project)
        snapshot_started = perf_counter()
        revision = self._revision_store.refresh_persistence(generation)
        snapshot_ms = (perf_counter() - snapshot_started) * 1000.0
        project_path = self.project_path
        self._autosave_worker_running = True

        def work():
            try:
                persist_started = perf_counter()
                with self._autosave_write_lock:
                    if save_autosave is not _ORIGINAL_SAVE_AUTOSAVE:
                        # Preserve test/plugin interception of the public save
                        # boundary while production uses the phased DTO writer.
                        save_autosave(revision, project_path)
                        phases = {
                            "materialize_ms": 0.0, "serialize_ms": 0.0,
                            "persist_ms": (perf_counter() - persist_started) * 1000.0,
                            "fsync_ms": 0.0,
                        }
                    else:
                        _target, phases = save_autosave_revision(revision, project_path, session_id=self._autosave_session_id)
                self._autosave_profile.append({
                    "generation": int(generation),
                    "snapshot_ms": round(snapshot_ms, 3),
                    "materialize_ms": round(phases["materialize_ms"], 3),
                    "serialize_ms": round(phases["serialize_ms"], 3),
                    "persist_ms": round(phases["persist_ms"], 3),
                    "fsync_ms": round(phases["fsync_ms"], 3),
                    "thread": threading.current_thread().name,
                })
                del self._autosave_profile[:-128]
            except Exception as exc:
                try:
                    self.autosave_failed_signal.emit(generation, str(exc))
                except RuntimeError:
                    pass
            else:
                try:
                    self.autosave_ready_signal.emit(generation)
                except RuntimeError:
                    pass

        self._autosave_thread = threading.Thread(
            target=work, daemon=True, name="studio-autosave"
        )
        self._autosave_thread.start()

    def _autosave_ready(self, generation: int) -> None:
        self._autosave_worker_running = False
        if generation != self._autosave_generation:
            # Re-enter through the event loop instead of recursively starting a
            # worker in the queued completion slot. One millisecond preserves
            # latest-wins without the former full autosave interval delay.
            self._autosave_timer.start(1)
            return
        self._autosave_deadline.mark_succeeded()
        self._last_autosave_at = datetime.now().strftime("%H:%M:%S")
        bind_text(self.save_state, '已自动保存 · {time}', time=self._last_autosave_at)
        bind_text(self.save_state, '恢复快照已安全写入磁盘；正式工程仍保留未保存修改。', property='toolTip')

    def _autosave_failed(self, generation: int, message: str) -> None:
        self._autosave_worker_running = False
        if generation != self._autosave_generation:
            self._autosave_timer.start(1)
        elif self.project:
            retry = self._autosave_deadline.mark_failed(time.monotonic())
            bind_text(self.save_state, translate('自动保存失败', current_language()))
            bind_text(self.save_state, '自动保存失败: {message}', property='toolTip', message=message)
            self._autosave_timer.start(max(1, round(retry * 1000)))

    def flush_autosave(self) -> Path | None:
        """Synchronously preserve the latest dirty state during normal shutdown."""
        if not self.project or (self.undo_stack.isClean() and not self._recovered_autosave_pending):
            return None
        self._capture_studio_state()
        if self._revision_store is None:
            self._revision_store = StudioRevisionStore(self.project)
        revision = self._revision_store.refresh_persistence(self._autosave_generation + 1)
        with self._autosave_write_lock:
            if save_autosave is not _ORIGINAL_SAVE_AUTOSAVE:
                return save_autosave(revision, self.project_path)
            target, _phases = save_autosave_revision(revision, self.project_path, session_id=self._autosave_session_id)
            return target

    def _capture_studio_state(self) -> None:
        if not self.project:
            return
        duration = self.project.media.duration_ms or max(
            (cue.end_ms for cue in self.project.cues), default=1
        )
        visible = max(1, self.timeline.visible_duration_ms)
        self.project.studio_state.update(
            {
                "last_selected_cue": self.selected_cue_id,
                "playhead_ms": self.timeline.playhead_ms,
                "zoom": max(1.0, duration / visible),
                "scroll_ms": self.timeline.visible_start_ms,
                "bilingual_mode": self.bilingual_button.isChecked(),
                "follow_playhead": self.follow_playhead_toggle.isChecked(),
                "timeline_snap_enabled": bool(self.timeline.snap_enabled),
                "timeline_tool": self.timeline.tool_mode,
                # 2026-09-18 VIII：三类轨高独立持久化（右侧 rail / 分界线拖动共享）。
                "timeline_track_heights": self.timeline.track_heights(),
                "layout": {
                    "upper_sizes": self.upper_splitter.sizes(),
                    "workspace_sizes": self.workspace_splitter.sizes(),
                    "center_sizes": self.center_splitter.sizes(),
                    "context_collapsed": not self.context_panel.isVisible(),
                    # Keep the legacy numeric meaning for older readers; new
                    # readers restore by stable identity after tab removal.
                    "context_tab": self._last_context_tab + (1 if self._last_context_tab else 0),
                    "context_tab_id": ("ai", "style", "video", "highlight", "media")[self._last_context_tab],
                    "cue_list_visible": self.cue_list_panel.isVisible(),
                    "editor_visible": self.cue_editor.isVisible(),
                    "context_visible": self.context_panel.isVisible(),
                    "editor_fields": dict(self._editor_field_visibility),
                },
            }
        )

    def _toggle_drawer(self, index: int) -> None:
        self._last_context_tab = max(0, min(self.context_drawer.count() - 1, int(index)))
        self.context_drawer.setCurrentIndex(self._last_context_tab)
        self._show_context_panel()

    def _remember_context_tab(self, index: int) -> None:
        if index >= 0:
            self._last_context_tab = int(index)

    def _show_context_panel(self) -> None:
        self.context_panel.show()
        self.context_drawer.setCurrentIndex(self._last_context_tab)
        self.context_expand_button.setChecked(True)
        action = getattr(self, "workspace_actions", {}).get("context")
        if action is not None:
            action.blockSignals(True)
            action.setChecked(True)
            action.blockSignals(False)
        sizes = self.upper_splitter.sizes()
        if len(sizes) == 3 and sizes[2] < 370:
            total = max(1110, sum(sizes))
            left = max(380, sizes[0])
            context = min(430, max(380, round(total * 0.22)))
            self.upper_splitter.setSizes([left, max(420, total - left - context), context])
        from .ui_motion import reveal_cue
        if getattr(self, '_project_view_state', '') == 'open':
            reveal_cue(self.context_panel)

    def _collapse_context_panel(self) -> None:
        self._last_context_tab = self.context_drawer.currentIndex()
        self.context_panel.hide()
        self.context_expand_button.setChecked(False)
        action = getattr(self, "workspace_actions", {}).get("context")
        if action is not None:
            action.blockSignals(True)
            action.setChecked(False)
            action.blockSignals(False)

    def _toggle_context_panel(self, checked: bool | None = None) -> None:
        show = bool(checked) if checked is not None else not self.context_panel.isVisible()
        self._show_context_panel() if show else self._collapse_context_panel()

    def _open_clip_assistant(self) -> None:
        if self.project is None or getattr(self, "_project_view_state", "") == "hub":
            self.project_controller.create_blank_project(focus_clip_assistant=False)
            if self.project is None or getattr(self, "_project_view_state", "") == "hub":
                return
        self._show_context_panel()
        if hasattr(self, "context_drawer"):
            self.context_drawer.setCurrentIndex(
                int(getattr(self, "highlight_tab_index", max(0, self.context_drawer.count() - 2)))
            )
        if hasattr(self, "highlight_panel") and self.project is not None:
            sequence = sequence_of(self.project)
            self.highlight_panel.set_project_status(self.project, sequence.danmaku_path)

    def _create_blank_studio(self) -> None:
        self.project_controller.create_blank_project(focus_clip_assistant=False)

    def _sync_video_empty_state(self) -> None:
        hint = getattr(self, "video_empty_hint", None)
        if hint is None:
            return
        path = str(self.project.media.path or "").strip() if self.project else ""
        timeline_empty = False
        if self.project is not None:
            sequence = sequence_of(self.project)
            timeline_empty = bool(sequence.empty_timeline and not sequence.segments)
        # A migrated audio project can retain a disabled V1 clip. Determine
        # audio-only mode from playable video clips, rather than from whether
        # the legacy lane object still exists, so the center surface does not
        # present a misleading black video viewport.
        has_playable_video = bool(
            self.project is not None
            and any(
                track.enabled and any(clip.enabled for clip in track.clips)
                for track in self.project.video_tracks
            )
        )
        audio_only = bool(
            self.project is not None
            and path
            and not has_playable_video
            and any(track.clips for track in self.project.audio_tracks)
        )
        hiding_ingest = (
            self._media_ingest_state in {"LOADING", "ERROR"}
            and str(getattr(self, "_pending_media_mode", "primary") or "primary") == "primary"
        )
        empty = self.project is not None and (
            not path or hiding_ingest or timeline_empty or audio_only
        )
        if timeline_empty:
            bind_text(self.video_empty_label, '时间线为空')
            bind_text(self.video_empty_note, '已清除旧画面、字幕和播放状态；按 Ctrl+Z 可恢复')
            self.video_empty_import.hide()
        elif audio_only:
            bind_text(self.video_empty_label, '纯音频工程')
            bind_text(self.video_empty_note, '{value0} · 音频波形与字幕预览 · 当前时间随 ProjectClock 更新', value0=Path(path).name)
            self.video_empty_import.hide()
        elif self._media_ingest_state == "EMPTY":
            bind_text(self.video_empty_label, '拖入视频或音频')
            bind_text(self.video_empty_note, '支持 MP4 / FLV / MKV / MOV / MP3 / WAV 等常用格式')
            self.video_empty_import.show()
        # LOADING and ERROR own their explanatory/recovery copy through
        # _set_media_ingest_state(); READY is hidden below.  Do not replace
        # those states with the generic empty-project prompt.
        hint.setVisible(empty)
        video = getattr(self, "video", None)
        if video is not None:
            video.setVisible(not empty)
        if empty:
            hint.raise_()

    def _set_major_panel_visible(self, panel: str, visible: bool) -> None:
        visible = bool(visible)
        if panel == "cue_list":
            self.cue_list_panel.setVisible(visible)
        elif panel == "context":
            self._show_context_panel() if visible else self._collapse_context_panel()
        action = self.workspace_actions.get(panel)
        if action is not None and action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        if panel == "cue_list" and hasattr(self, "cue_list_toggle_button"):
            self.cue_list_toggle_button.blockSignals(True)
            self.cue_list_toggle_button.setChecked(visible)
            self.cue_list_toggle_button.blockSignals(False)

    def _set_editor_field_visible(self, field: str, visible: bool) -> None:
        if field not in self._editor_field_visibility:
            return
        self._editor_field_visibility[field] = bool(visible)
        for widget in self.editor_field_widgets.get(field, ()):
            widget.setVisible(bool(visible))
        self._editor_compact_visibility = None
        self._update_editor_compactness()
        action = self.editor_field_actions.get(field)
        if action is not None and action.isChecked() != bool(visible):
            action.blockSignals(True)
            action.setChecked(bool(visible))
            action.blockSignals(False)

    def _apply_default_timeline_height(self) -> None:
        if not self.project:
            return
        subtitle_tracks = len(self.timeline.speaker_ids())
        translations = self.project.generation_metadata.get("translations", {})
        if self.timeline.bilingual and isinstance(translations, dict) and translations:
            subtitle_tracks += 1
        if subtitle_tracks <= 2:
            target = 320
        elif subtitle_tracks <= 5:
            target = 380
        else:
            target = 430
        sizes = self.workspace_splitter.sizes()
        total = sum(sizes) or max(500, self.workspace_splitter.height())
        target = min(target, max(210, total - 240))
        self.workspace_splitter.setSizes([max(240, total - target), target])

    def _apply_default_workspace_layout(self) -> None:
        """Give common 16:9 media the largest practical central viewport."""
        if not self.project:
            return
        width = max(1, int(self.project.media.width or 1920))
        height = max(1, int(self.project.media.height or 1080))
        if width / height >= 1.55:
            total = max(900, self.upper_splitter.width())
            context = min(480, max(420, round(total * 0.24)))
            left = min(420, max(self.cue_list_panel.minimumWidth(), round(total * 0.22)))
            center = max(360, total - left - context)
            if left + center + context > total:
                left = max(self.cue_list_panel.minimumWidth(), total - center - context)
            self.upper_splitter.setSizes([left, max(360, total - left - context), context])
        self._apply_default_timeline_height()

    def _toggle_cue_list(self) -> None:
        self._set_major_panel_visible("cue_list", not self.cue_list_panel.isVisible())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._review_mode and event.key() == Qt.Key.Key_Escape:
            self._exit_review()
            event.accept()
            return
        if not self._editing_has_focus() and not event.isAutoRepeat():
            sequence = QKeySequence(event.keyCombination()).toString(
                QKeySequence.SequenceFormat.PortableText
            )
            if self._dispatch_shortcut_sequence(sequence):
                event.accept()
                return
        super().keyPressEvent(event)

    def retranslate_ui(self):
        from .project_display_name import display_project_name
        if self.project is None:
            bind_text(self.filename, tr('2ByteASR  兔白字幕'))
            self._refresh_studio_empty_state(rescan=False)
        else:
            user_text(self.filename).setText(display_project_name(path=self.project_path, project=self.project))
        self._context_tab_mode = ""
        self._editor_compact_mode = None
        self._update_context_tab_labels()
        self._update_editor_compactness()
        self._sync_navigation_chrome()
        self._refresh_cue_list_summary()
        from .studio_style_controller import _refresh_appearance_summaries
        _refresh_appearance_summaries(self)
        self.cue_model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 4)
        self.cue_table.viewport().update()
        self.timeline.update()

    def _refresh_cue_list_summary(self) -> None:
        # 2026-09-19 P0：统计芯片口径=当前活动序列的投影视图（与列表/
        # 时间轴一致）；QC 查找按源 id 解析。
        if self.project:
            from .studio_edit_sequence import projected_cues
            from .studio_cue_table import _source_key

            view_cues = projected_cues(self.project, domain="timeline")
        else:
            view_cues = []
        total = len(view_cues)
        self.jump_spin.setRange(1, max(1, total))
        self.cue_total_label.setText(f"/ {total}")
        if not self.project:
            for key, label in {'all': '全部', 'priority': '建议确认', 'critical': '需要检查'}.items():
                if key in self.cue_filter_buttons:
                    bind_text(self.cue_filter_buttons[key], '{label} {count}', label=tr(label), count='0' if key == 'all' else '--')
            return
        counts = {"all": total, "priority": 0, "critical": 0, "pending": 0, "issue": 0, "done": 0}
        for cue in view_cues:
            status = _cue_status(self.project, cue)
            counts[status] += 1
            if not _cue_explicitly_confirmed(self.project, cue) and _cue_review_level(self.project, cue) == "suggested":
                counts["priority"] += 1
            if not _cue_explicitly_confirmed(self.project, cue) and any(
                issue.severity == QCSeverity.CRITICAL
                for issue in cached_qc_result(self.project).for_cue(_source_key(cue))
            ):
                counts["critical"] += 1
        captions = {"all": "全部", "priority": "建议确认", "critical": "需要检查", "pending": "待确认", "issue": "有问题", "done": "已完成"}
        for key, button in self.cue_filter_buttons.items():
            if key in {"priority", "critical"} and not hasattr(self.project, "_qc_result"):
                button.setText(f"{tr(captions[key])} --")
            else:
                button.setText(f"{tr(captions[key])} {counts[key]}")
        zero_cues = total == 0
        empty_priority = (
            not zero_cues
            and self.cue_model.filter_status in {"priority", "critical"}
            and self.cue_model.rowCount() == 0
        )
        self.cue_table.setVisible(not zero_cues and not empty_priority)
        self.cue_zero_state.setVisible(zero_cues)
        self.cue_empty_state.setVisible(empty_priority)
        # 四十三轮：识别运行时零态卡跟随可见性（流式字幕进来后零态隐藏）。
        sync_zero = getattr(self, "_sync_recognition_zero_state", None)
        if callable(sync_zero):
            sync_zero()

    def _show_cue_more_menu(self) -> None:
        menu = create_studio_menu(self)
        cue_settings = menu.addAction(_icon("fa5s.sliders-h"), "显示当前 Cue 设置")
        cue_settings.triggered.connect(self._show_current_cue_settings)
        menu.addSeparator()
        menu.addAction(_icon("fa5s.cut"), "拆分", self._split_current)
        menu.addAction(_icon("fa5s.link"), "与下一条合并", self._merge_next)
        menu.addSeparator()
        for caption, delta in (("提前 100 ms", -100), ("提前 50 ms", -50), ("延后 50 ms", 50), ("延后 100 ms", 100)):
            menu.addAction(tr(caption), lambda amount=delta: self._nudge(amount))
        menu.addSeparator()
        menu.addAction(_icon("fa5s.trash-alt"), "删除", self._delete_current)
        menu.addSeparator()
        menu.addAction(_icon("fa5s.info-circle"), "媒体信息", self._show_media_info)
        menu.exec(QCursor.pos())

    def _show_current_cue_settings(self) -> None:
        self._expand_current_cue_editor()
        self.editor_metadata.show()
        for field in ("speaker", "start", "duration"):
            self._set_editor_field_visible(field, True)
        self._editor_compact_visibility = None
        self._update_editor_compactness()

    def _expand_current_cue_editor(self) -> None:
        button = getattr(self, "current_cue_section_button", None)
        if button is not None:
            button.setChecked(True)

    def _show_media_info(self) -> None:
        if not self.project:
            return
        media = self.project.media
        path = Path(media.path)
        details = [
            f"文件：{path.name}",
            f"路径：{path}",
            f"时长：{_format_ms(media.duration_ms)}",
        ]
        if media.fingerprint:
            details.append(f"媒体指纹：{media.fingerprint}")
        studio_message_box(self, QMessageBox.Icon.Information, tr('媒体信息'), "\n".join(details))

    def _show_timeline_menu(self, cue_id: str, global_pos: QPoint) -> None:
        if cue_id:
            self.select_cue(cue_id)
        menu = create_studio_menu(self)
        menu.addAction(_icon("fa5s.cut"), "拆分当前字幕", self._split_current)
        menu.addAction(_icon("fa5s.link"), "与下一条合并", self._merge_next)
        menu.addAction(_icon("fa5s.trash-alt"), "删除当前字幕", self._delete_current)
        menu.addSeparator()
        menu.addAction(_icon("fa5s.magic"), "智能修轴", self._smart_align_current)
        if len(self.selected_cue_ids()) > 1:
            menu.addAction(_icon("fa5s.magic"), f"智能修轴选中字幕（{len(self.selected_cue_ids())}）", self._smart_align_selected)
        loop_menu = menu.addMenu("当前字幕试听")
        loop_menu.addAction("播放一次", lambda: self._seek((cue_by_id(self.project, self.selected_cue_id).start_ms - 250) / 1000.0) if self.project and self.selected_cue_id else None)
        loop_menu.addAction("循环播放", self._toggle_loop_current)
        selected_ids = self.selected_cue_ids()
        offset_menu = menu.addMenu("整体偏移")
        for delta in (-100, -50, 50, 100):
            offset_menu.addAction(f"{delta:+d} ms", lambda delta=delta, ids=selected_ids: self._apply_timing_offset(ids, delta))
        menu.exec(global_pos)

    def _apply_timing_offset(self, cue_ids: list[str], offset_ms: int) -> None:
        return self.cue_controller.apply_timing_offset(cue_ids, offset_ms)

    def _set_bilingual_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self.mono_button.setChecked(not enabled)
        self.bilingual_button.setChecked(enabled)
        toggle = getattr(self, "bilingual_toggle_button", None)
        if toggle is not None:
            toggle.blockSignals(True)
            toggle.setChecked(enabled)
            toggle.blockSignals(False)
        self.translation_text.setVisible(enabled)
        self.timeline.set_bilingual(enabled)
        self.mono_display_action.blockSignals(True)
        self.bilingual_display_action.blockSignals(True)
        self.mono_display_action.setChecked(not enabled)
        self.bilingual_display_action.setChecked(enabled)
        self.mono_display_action.blockSignals(False)
        self.bilingual_display_action.blockSignals(False)
        if self.project:
            self.project.studio_state["bilingual_mode"] = enabled
            refresh_ass = getattr(self, "_refresh_ass_preview", None)
            if callable(refresh_ass):
                refresh_ass()


    def _ignore_ai_preview(self) -> None:
        drafts = getattr(self,'_theme_draft_coordinator',None)
        if drafts is not None: drafts.invalidate()
        self._pending_suggestion = None
        self._pending_web_theme = None
        storyboard = getattr(self, "ai_web_theme_storyboard_wrap", None)
        if storyboard is not None:
            storyboard.setVisible(False)
        stop_animation = getattr(self, "_stop_storyboard_animation", None)
        if callable(stop_animation):
            stop_animation()
        refine_row = getattr(self, "ai_refine_row", None)
        if refine_row is not None:
            refine_row.setVisible(False)
        self.ai_preview.clear()
        bind_text(self.ai_suggestion_title, '尚未生成当前视觉方案')
        bind_text(self.ai_confidence, '建议已忽略')
        if hasattr(self, "ai_suggestion_card"):
            self.ai_suggestion_card.hide()

    def _zoom_timeline(self, factor: float) -> None:
        if not self.project:
            return
        duration = timeline_duration_ms(self.project) or max((cue.end_ms for cue in self.project.cues), default=60_000)
        visible = min(duration, max(1000, round(self.timeline.visible_duration_ms * factor)))
        center = self.timeline.visible_start_ms + self.timeline.visible_duration_ms // 2
        self.timeline.set_visible_window(center - visible // 2, visible)

    def _fit_timeline(self) -> None:
        if not self.project:
            return
        duration = timeline_duration_ms(self.project) or max((cue.end_ms for cue in self.project.cues), default=60_000)
        self.timeline.set_visible_window(0, duration)

    def timeline_update(self) -> None:
        self.timeline.update()

    def _table_activated(self, index: QModelIndex) -> None:
        return self.cue_controller.table_activated(index)

    def _open_render_dialog(self) -> None:
        if not self.project or not self._preview_path:
            return
        self._cancel_scrub()
        if self.export_workspace is not None:
            self.export_workspace.release_preview()
            self.export_workspace.deleteLater()
        self.video_compositor.set_interaction_enabled(False)
        self.position_overlay.hide()
        self.export_workspace = StudioExportWorkspace(
            self.project,
            str(self._preview_path),
            project_path=self.project_path,
            parent=self,
            preview_widget=self.video,
        )
        self.export_workspace.back_requested.connect(self._close_export_workspace)
        self.export_workspace.render_succeeded.connect(lambda path: self._render_succeeded(path, False))
        self.layout().addWidget(self.export_workspace, 1)
        self.workspace_splitter.hide()
        self.workspace_host.hide()
        self.export_workspace.show()
        self.studio_render_button.setEnabled(False)
        self._sync_navigation_chrome()

        from .ui_motion import settle_layout, reveal_cue
        settle_layout(self)
        reveal_cue(self.export_workspace)

    def _close_export_workspace(self) -> None:
        if self.export_workspace is not None:
            try:
                self.export_workspace.release_preview()
            except Exception:
                pass
            self._restore_studio_video()
            self.export_workspace.hide()
            self.export_workspace.deleteLater()
            self.export_workspace = None
            self.video_compositor.set_interaction_enabled(True)
            self.video_compositor.set_selected_clip(self.timeline.selected_video_clip_id)
        if hasattr(self, "workspace_splitter"):
            self.workspace_splitter.show()
            self.workspace_host.show()
        if hasattr(self, "studio_render_button"):
            self.studio_render_button.setEnabled(True)
        self._cancel_scrub()
        self.unsetCursor()
        self._sync_navigation_chrome()

    def _cancel_scrub(self) -> None:
        """End any Studio numeric scrub before/after a modal child dialog."""
        for control in self.findChildren(QAbstractSpinBox):
            cancel = getattr(control, "_cancel_scrub", None)
            if callable(cancel):
                cancel()

    def _render_succeeded(self, path: str, preview: bool) -> None:
        if preview:
            self.video.load(path, "")

    def hideEvent(self, event) -> None:
        self._gui_thread_handoff.release()
        self._playback_gc_budget.close()
        hide_started = perf_counter()

        def hide_checkpoint(step: str) -> None:
            self._studio_trace(
                "HIDE_STEP",
                step=str(step),
                elapsed_ms=round((perf_counter() - hide_started) * 1000.0, 3),
            )

        hide_checkpoint("begin")
        overlay = getattr(self, "advanced_cue_overlay", None)
        if overlay is not None:
            self._advanced_overlay_restore = bool(overlay.isVisible())
            overlay.hide()
            self._advanced_visual_owner_cue_id = ""
        hide_checkpoint("advanced_overlay_hidden")
        if hasattr(self, "_visual_ownership"):
            self._visual_ownership.commit(VisualOwner.NONE)
        hide_checkpoint("ownership_revoked")
        video = getattr(self, "video", None)
        if video is not None:
            video.set_native_subtitle_visible(False)
        hide_checkpoint("native_subtitle_hidden")
        position_overlay = getattr(self, "position_overlay", None)
        if position_overlay is not None:
            position_overlay.hide()
        hide_checkpoint("position_overlay_hidden")
        super().hideEvent(event)
        hide_checkpoint("complete")

    def _ensure_renderer_when_visible(self, *, reason: str, attempt: int = 0) -> None:
        """Recompute the subtitle foreground owner once the page is visible.

        Window activation callbacks and hideEvent/showEvent pairs (minimize,
        page switches) can fire while the page is still flagged hidden. The
        ownership commit then evaluates page_ready=False and revokes NATIVE
        rendering; with playback paused there is no later playhead event to
        restore it, so a normal subtitle stays invisible until the next seek
        (三十一轮用户实录：视频层新建字幕后画面无字幕). Wait briefly for the
        visible state instead of committing a hidden-state verdict.
        """

        if self._close_requested:
            return
        if not self.isVisible():
            if attempt < 40:
                QTimer.singleShot(
                    16,
                    lambda: self._ensure_renderer_when_visible(
                        reason=reason, attempt=attempt + 1,
                    ),
                )
            return
        self.ensure_active_subtitle_renderer(reason=reason)

    def showEvent(self, event) -> None:
        self._gui_thread_handoff.acquire()
        super().showEvent(event)
        QTimer.singleShot(0,self._reload_ai_provider_selection)
        # Initial project selection often happens before this page is shown;
        # always recompute visibility instead of relying on a prior-visible flag.
        restore = bool(getattr(self, "_advanced_overlay_restore", False))
        self._advanced_overlay_restore = False
        if restore:
            QTimer.singleShot(0, self._sync_advanced_cue_overlay)
        QTimer.singleShot(
            0,
            lambda: self._ensure_renderer_when_visible(reason="show_event"),
        )
        QTimer.singleShot(0, self._activate_selected_advanced_if_needed)

    def close_page(self) -> None:
        """Compatibility close for tests and standalone pages; waits only bounded time."""
        self.begin_close_page()
        close_thread = self._close_thread
        is_alive = getattr(close_thread, "is_alive", None)
        if (
            close_thread is not None
            and callable(is_alive)
            and is_alive()
            and threading.current_thread() is not close_thread
        ):
            close_thread.join(timeout=8.0)

    def begin_close_page(self) -> float:
        """Make close visible immediately, then finish process cleanup off the GUI thread."""
        if self._close_requested:
            return float(self.last_close_profile.get("visible_response_ms", 0.0))
        self._close_requested = True
        from .studio_analysis_request import cancel_analysis
        cancel_analysis(self)
        analysis_workers = tuple(getattr(self, "_analysis_workers", ()))
        scene = getattr(self, '_caption_scene', None)
        if scene is not None: scene.close()
        self.video.clear_caption_boundaries()
        self._playback_gc_budget.close()
        caption_cache=getattr(self,'_caption_playback_cache',None)
        if caption_cache is not None:caption_cache.close()
        pixel_cache=getattr(self,'_caption_pixel_cache',None)
        if pixel_cache is not None:pixel_cache.close()
        runner=getattr(self,'_live_raster_runner',None)
        if runner is not None:runner.close()
        thumbnails=getattr(getattr(self,'timeline',None),'_thumbnails',None)
        if callable(getattr(thumbnails,'close',None)):thumbnails.close()
        probe_cancel=getattr(self,"_ai_provider_probe_cancel",None)
        if probe_cancel is not None:probe_cancel.set()
        self._ai_provider_probe_generation+=1
        started = perf_counter()
        # 2026-09-07（双轨轮）：清理线程必须在任何 WMF 拆解开始**之前**孵化。
        # 在 video_compositor.clear() 的媒体会话终结窗口里新建 Python 线程会与
        # WMF 回调编组争用 GIL，形成不可恢复的楔死（close 永不完成、后续任何
        # Python 线程无法 bootstrap）。线程先起来等交接事件，GUI 拆解完再放行。
        handover = threading.Event()
        handover_state: dict[str, object] = {}

        def cleanup() -> None:
            handover.wait()
            # Decode/provider cancellation is cooperative. Join only on this
            # cleanup thread; parentless retained workers cannot die with UI.
            analysis_workers_alive = 0
            for analysis_worker in analysis_workers:
                try:
                    if not analysis_worker.wait(3000):
                        analysis_workers_alive += 1
                except RuntimeError:  # already finished and deleted on GUI
                    pass
            autosave_revision = handover_state.get("autosave_revision")
            autosave_path = handover_state.get("autosave_path")
            detached_player = handover_state.get("detached_player")
            phases: dict[str, float | str | bool] = {"analysis_workers_alive": analysis_workers_alive}
            cleanup_started = perf_counter()

            def cleanup_step(step: str) -> None:
                # Keep the last safe teardown boundary visible when a native
                # multimedia backend fails during process shutdown.
                self._studio_trace("CLOSE_CLEANUP_STEP", step=str(step))

            def phase(name: str, phase_started: float) -> None:
                phases[name] = round((perf_counter() - phase_started) * 1000.0, 3)

            phase_started = perf_counter()
            cleanup_step("ass_begin")
            ass_actor = self._ass_actor
            self._ass_actor = None
            self._ass_worker_running = False
            if ass_actor is not None:
                ass_actor.close()
            phase("ass_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("autosave_begin")
            existing_autosave = self._autosave_thread
            if existing_autosave is not None and existing_autosave.is_alive():
                existing_autosave.join(timeout=2.0)
            if autosave_revision is not None:
                acquired = self._autosave_write_lock.acquire(timeout=2.0)
                if acquired:
                    try:
                        if save_autosave is not _ORIGINAL_SAVE_AUTOSAVE:
                            save_autosave(autosave_revision, autosave_path)
                        else:
                            save_autosave_revision(autosave_revision, autosave_path, session_id=self._autosave_session_id)
                        phases["autosave_status"] = "saved"
                    except Exception as exc:
                        phases["autosave_status"] = f"failed:{type(exc).__name__}"
                    finally:
                        self._autosave_write_lock.release()
                else:
                    phases["autosave_status"] = "lock_timeout"
            else:
                phases["autosave_status"] = "clean"
            phase("autosave_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("provider_begin")
            phases["provider_idle"] = GLOBAL_PROVIDER_SERVICE.shutdown(timeout=1.0)
            phase("provider_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("proxy_begin")
            phases["proxy_idle"] = GLOBAL_MEDIA_SERVICE.wait_for_idle(timeout=1.0)
            phase("proxy_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("waveform_begin")
            with self._waveform_inflight_lock:
                waveform_threads = tuple(self._waveform_threads)
            waveform_deadline = time.monotonic() + 1.0
            for worker in waveform_threads:
                if worker is threading.current_thread() or not worker.is_alive():
                    continue
                worker.join(timeout=max(0.0, waveform_deadline - time.monotonic()))
            phases["waveform_threads_alive"] = sum(
                worker.is_alive() for worker in waveform_threads
            )
            phase("waveform_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("renderer_begin")
            try:
                self._advanced_preview_cache.renderer_service.shutdown(timeout=2.0)
            except Exception as exc:
                phases["renderer_status"] = f"failed:{type(exc).__name__}"
            advanced_thread = self._advanced_preview_thread
            if (
                advanced_thread is not None
                and advanced_thread.is_alive()
                and threading.current_thread() is not advanced_thread
            ):
                advanced_thread.join(timeout=1.0)
            phases["advanced_thread_alive"] = bool(
                advanced_thread is not None and advanced_thread.is_alive()
            )
            phase("renderer_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("audio_begin")
            if hasattr(self, "audio_engine"):
                phases["audio_idle"] = self.audio_engine.wait_for_shutdown(timeout=1.5)
                phases["audio_state"] = str(
                    self.audio_engine.telemetry_snapshot().get("state", "")
                )
            phase("audio_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("mpv_begin")
            if detached_player is not None:
                try:
                    detached_player.close()
                except Exception as exc:
                    phases["mpv_status"] = f"failed:{type(exc).__name__}"
            phase("mpv_shutdown_ms", phase_started)
            cleanup_step("complete")
            phases["cleanup_total_ms"] = round(
                (perf_counter() - cleanup_started) * 1000.0, 3
            )
            self.last_close_profile.update(phases)
            self._close_complete = True
            self._studio_trace("CLOSE_CLEANUP_COMPLETE", **phases)
            try:
                self.close_ready_signal.emit(dict(self.last_close_profile))
            except RuntimeError:
                pass
        # Hatch BEFORE any WMF teardown below; it idles on the handover event.
        self._close_thread = threading.Thread(
            target=cleanup, daemon=True, name="studio-close-cleanup"
        )
        self._close_thread.start()

        def close_checkpoint(step: str) -> None:
            self._studio_trace(
                "CLOSE_RESPONSE_STEP",
                step=str(step),
                elapsed_ms=round((perf_counter() - started) * 1000.0, 3),
            )
            if os.environ.get("TWOBYTEASR_CLOSE_GIL_PROBE") == "1":
                import threading as _threading

                probe = _threading.Thread(target=lambda: None, daemon=True)
                probe.start()
                probe.join(timeout=1.0)
                with open(
                    os.path.join(os.environ["LOCALAPPDATA"], "close-gil-probe.log"),
                    "a", encoding="utf8",
                ) as fh:
                    fh.write(
                        f"{'OK' if not probe.is_alive() else 'WEDGED'} step={step} "
                        f"elapsed={round((perf_counter() - started) * 1000.0, 1)}ms\n"
                    )

        close_checkpoint("begin")
        self._resource_governor.set_dragging(False)
        self._resource_governor.set_playback(False)
        self._cancel_media_ingest()
        close_checkpoint("resources_cancelled")
        active_seek = getattr(self.video, "_active_seek_trace", None)
        if isinstance(active_seek, dict):
            self.video._expire_seek_trace(
                int(active_seek.get("generation", -1)),
                reason="page closing",
            )
        ai_cancel = getattr(self, "_ai_cancel_event", None)
        if ai_cancel is not None:
            ai_cancel.set()
        drafts = getattr(self, '_theme_draft_coordinator', None)
        if drafts is not None:
            drafts.invalidate()
        provider_cancelled = GLOBAL_PROVIDER_SERVICE.cancel_all()
        proxy_cancelled = GLOBAL_MEDIA_SERVICE.cancel_all()
        from .indexed_media import GLOBAL_INDEXED_MEDIA
        optimize_cancelled = GLOBAL_INDEXED_MEDIA.cancel_all()
        close_checkpoint("services_cancelled")
        for timer_name in (
            "_initial_preview_timer", "_preview_timer", "_edit_preview_timer",
            "_transform_preview_timer", "_advanced_preview_timer",
            "_advanced_preview_publish_timer", "_advanced_seek_timer",
            "_autosave_timer", "_visual_update_timer", "_manual_learning_timer",
            "_style_debounce_timer", "_recognition_runtime_timer", "_reverse_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        close_checkpoint("timers_stopped")
        with self._advanced_preview_condition:
            self._advanced_preview_worker_stopping = True
            self._advanced_preview_pending_job = None
            self._advanced_preview_condition.notify_all()
        close_checkpoint("preview_worker_stopping")
        if hasattr(self, "advanced_cue_overlay"):
            self.advanced_cue_overlay.hide()
            self.advanced_cue_overlay.close()
        close_checkpoint("advanced_overlay_closed")
        if hasattr(self, "video_compositor"):
            self.video_compositor.clear()
            close_checkpoint("compositor_cleared")
            self.video_compositor.close()
        close_checkpoint("compositor_closed")
        if hasattr(self, "audio_engine"):
            self.audio_engine.request_shutdown()
        close_checkpoint("audio_shutdown_requested")
        self._visual_ownership.commit(VisualOwner.NONE)
        self.video.set_native_subtitle_visible(False)
        if hasattr(self, "position_overlay"):
            self.position_overlay.hide()
        close_checkpoint("visuals_revoked")
        detached_player = self.video.detach_player_for_close()
        close_checkpoint("player_detached")
        autosave_revision = None
        autosave_path = self.project_path
        try:
            if self.project and (
                not self.undo_stack.isClean() or self._recovered_autosave_pending
            ):
                self._capture_studio_state()
                if self._revision_store is None:
                    self._revision_store = StudioRevisionStore(self.project)
                autosave_revision = self._revision_store.refresh_persistence(
                    self._autosave_generation + 1
                )
        except Exception as exc:
            bind_text(self.save_state, '关闭前自动保存失败: {exc}', property='toolTip', exc=exc)
        close_checkpoint("persistence_captured")
        app = QApplication.instance()
        if app is not None and self._event_filter_installed:
            app.removeEventFilter(self)
            self._event_filter_installed = False
        if app is not None and self._focus_signal_connected:
            try:
                app.focusChanged.disconnect(self._restore_edit_card_focus)
            except (RuntimeError, TypeError):
                pass
            self._focus_signal_connected = False
        if app is not None and self._native_key_filter is not None:
            app.removeNativeEventFilter(self._native_key_filter)
            self._native_key_filter = None
        visible_response_ms = (perf_counter() - started) * 1000.0
        self.last_close_profile = {
            "visible_response_ms": round(visible_response_ms, 3),
            "provider_cancelled": float(provider_cancelled),
            "proxy_cancelled": float(proxy_cancelled),
        }
        self._studio_trace(
            "CLOSE_RESPONSE",
            visible_response_ms=round(visible_response_ms, 3),
            provider_cancelled=provider_cancelled,
            proxy_cancelled=proxy_cancelled,
        )

        def cleanup() -> None:
            handover.wait()
            autosave_revision = handover_state.get("autosave_revision")
            autosave_path = handover_state.get("autosave_path")
            detached_player = handover_state.get("detached_player")
            phases: dict[str, float | str | bool] = {}
            cleanup_started = perf_counter()

            def cleanup_step(step: str) -> None:
                # Keep the last safe teardown boundary visible when a native
                # multimedia backend fails during process shutdown.
                self._studio_trace("CLOSE_CLEANUP_STEP", step=str(step))

            def phase(name: str, phase_started: float) -> None:
                phases[name] = round((perf_counter() - phase_started) * 1000.0, 3)

            phase_started = perf_counter()
            cleanup_step("ass_begin")
            ass_actor = self._ass_actor
            self._ass_actor = None
            self._ass_worker_running = False
            if ass_actor is not None:
                ass_actor.close()
            phase("ass_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("autosave_begin")
            existing_autosave = self._autosave_thread
            if existing_autosave is not None and existing_autosave.is_alive():
                existing_autosave.join(timeout=2.0)
            if autosave_revision is not None:
                acquired = self._autosave_write_lock.acquire(timeout=2.0)
                if acquired:
                    try:
                        if save_autosave is not _ORIGINAL_SAVE_AUTOSAVE:
                            save_autosave(autosave_revision, autosave_path)
                        else:
                            save_autosave_revision(autosave_revision, autosave_path)
                        phases["autosave_status"] = "saved"
                    except Exception as exc:
                        phases["autosave_status"] = f"failed:{type(exc).__name__}"
                    finally:
                        self._autosave_write_lock.release()
                else:
                    phases["autosave_status"] = "lock_timeout"
            else:
                phases["autosave_status"] = "clean"
            phase("autosave_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("provider_begin")
            phases["provider_idle"] = GLOBAL_PROVIDER_SERVICE.shutdown(timeout=1.0)
            phase("provider_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("proxy_begin")
            phases["proxy_idle"] = GLOBAL_MEDIA_SERVICE.wait_for_idle(timeout=1.0)
            phase("proxy_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("waveform_begin")
            with self._waveform_inflight_lock:
                waveform_threads = tuple(self._waveform_threads)
            waveform_deadline = time.monotonic() + 1.0
            for worker in waveform_threads:
                if worker is threading.current_thread() or not worker.is_alive():
                    continue
                worker.join(timeout=max(0.0, waveform_deadline - time.monotonic()))
            phases["waveform_threads_alive"] = sum(
                worker.is_alive() for worker in waveform_threads
            )
            phase("waveform_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("renderer_begin")
            try:
                self._advanced_preview_cache.renderer_service.shutdown(timeout=2.0)
            except Exception as exc:
                phases["renderer_status"] = f"failed:{type(exc).__name__}"
            advanced_thread = self._advanced_preview_thread
            if (
                advanced_thread is not None
                and advanced_thread.is_alive()
                and threading.current_thread() is not advanced_thread
            ):
                advanced_thread.join(timeout=1.0)
            phases["advanced_thread_alive"] = bool(
                advanced_thread is not None and advanced_thread.is_alive()
            )
            phase("renderer_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("audio_begin")
            if hasattr(self, "audio_engine"):
                phases["audio_idle"] = self.audio_engine.wait_for_shutdown(timeout=1.5)
                phases["audio_state"] = str(
                    self.audio_engine.telemetry_snapshot().get("state", "")
                )
            phase("audio_shutdown_ms", phase_started)

            phase_started = perf_counter()
            cleanup_step("mpv_begin")
            if detached_player is not None:
                try:
                    detached_player.close()
                except Exception as exc:
                    phases["mpv_status"] = f"failed:{type(exc).__name__}"
            phase("mpv_shutdown_ms", phase_started)
            cleanup_step("complete")
            phases["cleanup_total_ms"] = round(
                (perf_counter() - cleanup_started) * 1000.0, 3
            )
            self.last_close_profile.update(phases)
            self._close_complete = True
            self._studio_trace("CLOSE_CLEANUP_COMPLETE", **phases)
            try:
                self.close_ready_signal.emit(dict(self.last_close_profile))
            except RuntimeError:
                pass

        handover_state.update(
            autosave_revision=autosave_revision,
            autosave_path=autosave_path,
            detached_player=detached_player,
        )
        handover.set()
        return visible_response_ms
