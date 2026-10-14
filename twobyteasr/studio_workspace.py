"""Construction collaborator for the Subtitle Studio workspace.

The builder is a plain Python object. Widgets and Qt resources remain owned by
SubtitleStudioPage and are created in their legacy order.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMenu,
    QAbstractItemView,
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStackedLayout,
    QTabWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .studio_theme import GREEN, StudioComboBox, apply_secondary_surface_theme, create_studio_menu
from .llm_config import (
    AI_SERVICE_SPECS,
    active_service_values,
    get_active_service,
    normalize_base_url,
    service_model_catalog,
)
from .cover_label import CoverPreviewLabel
from .themed_icons import install_themed_tabs, install_themed_icon
from .studio_widgets import ScrubDoubleSpinBox
from .design.components import StatusBadge

from .i18n import bind_text

from .i18n import tr

# Candidate row of the review strip: one ReviewCandidateCard (min 86 px).
REVIEW_DOCK_ROW_HEIGHT = 92


class ResponsiveCueTableView(QTableView):
    first_selected_rows_painted = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._selection_paint_token = 0
        # Two-line reading view by default (2026-10-09, M16); the classic
        # five-column table stays available.
        self.reading = False

    def expect_selected_rows_paint(self, token: int) -> None:
        self._selection_paint_token = int(token)
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._selection_paint_token and self.selectionModel().hasSelection():
            token = self._selection_paint_token
            self._selection_paint_token = 0
            self.first_selected_rows_painted.emit(token)

    def apply_responsive_layout(self) -> None:
        if self.model() is None or self.model().columnCount() < 5:
            return
        if self.reading:
            for column in (0, 1, 2, 4):
                self.setColumnHidden(column, True)
            self.setColumnHidden(3, False)
            return
        for column in (0, 1, 2, 3):
            self.setColumnHidden(column, False)
        compact = self.viewport().width() < 370
        self.setColumnHidden(4, compact)
        widths = (32, 88, 52) if compact else (36, 88, 66)
        widths = tuple(max(width, self.fontMetrics().horizontalAdvance(str(self.model().headerData(column, Qt.Orientation.Horizontal))) + 14) for column, width in enumerate(widths))
        for column, width in enumerate(widths):
            self.setColumnWidth(column, width)
        if not compact:
            self.setColumnWidth(4, 58)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.apply_responsive_layout()


class StudioWorkspaceBuilder:
    """Build the workspace while retaining all widget fields on the page."""

    def __init__(
        self,
        page,
        *,
        advanced_live_canvas_type,
        cue_badge_delegate_type,
        cue_index_delegate_type,
        cue_table_model_type,
        mpv_canvas_type,
        position_overlay_type,
        waveform_timeline_type,
        subtitle_editor_type,
        icon,
        icon_label,
        time_spinbox,
    ):
        self.page = page
        self._advanced_live_canvas_type = advanced_live_canvas_type
        self._cue_badge_delegate_type = cue_badge_delegate_type
        self._cue_index_delegate_type = cue_index_delegate_type
        self._cue_table_model_type = cue_table_model_type
        self._mpv_canvas_type = mpv_canvas_type
        self._position_overlay_type = position_overlay_type
        self._waveform_timeline_type = waveform_timeline_type
        self._subtitle_editor_type = subtitle_editor_type
        self._icon = icon
        self._icon_label = icon_label
        self._time_spinbox = time_spinbox

    def build(self) -> None:
        page = self.page
        _icon = self._icon
        _icon_label = self._icon_label
        _time_spinbox = self._time_spinbox
        AdvancedLiveCanvas = self._advanced_live_canvas_type
        MpvCanvas = self._mpv_canvas_type
        SubtitlePositionOverlay = self._position_overlay_type
        WaveformTimeline = self._waveform_timeline_type
        _SubtitleEditCardEditor = self._subtitle_editor_type
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName("studioToolbar")
        page.studio_toolbar = toolbar
        toolbar.installEventFilter(page)
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(12, 7, 12, 7)
        bar.setSpacing(5)
        page._studio_command_layout = bar
        back = page._tool_button("fa5s.arrow-left", "返回上一层", page._request_back)
        page.studio_back_button = back
        bar.addWidget(back)
        from .elided_label import ElidedLabel
        page.filename = ElidedLabel("兔白字幕", minimum=120)
        page.filename.setObjectName("studioFilename")
        page.filename.setMinimumWidth(120)
        page.filename.setMaximumWidth(420)
        bar.addWidget(page.filename)
        page.filename.installEventFilter(page)
        from .studio_widgets import StudioStatusLabel
        page.save_state = StudioStatusLabel("未打开项目")
        page.save_state.setObjectName("studioSaveState")
        page.save_state.setMinimumWidth(110)
        page.save_state.setMaximumWidth(220)
        page.save_state.setWordWrap(False)
        page.save_state.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        bar.addWidget(page.save_state)
        page.save_state.installEventFilter(page)
        bar.addStretch(1)
        home = page._tool_button("fa5s.home", "返回字幕识别", page._request_return_home)
        page.studio_home_button = home
        bar.addWidget(home)
        library = page._tool_button("fa5s.th-large", "兔白字幕工程库", page._request_return_library)
        library.setCheckable(True)
        page.studio_library_button = library
        bar.addWidget(library)
        bar.addWidget(page._toolbar_divider())
        open_button = page._tool_button("fa5s.folder-open", "打开已有工程", page.open_project_dialog)
        page.studio_open_button = open_button
        bar.addWidget(open_button)
        import_media = page._tool_button("fa5s.plus", "导入媒体", page.import_media_dialog)
        page.studio_import_media_button = import_media
        bar.addWidget(import_media)
        page.studio_hub_settings_button = page._tool_button(
            "fa5s.cog", "应用设置", page._show_hub_preferences
        )
        bar.addWidget(page.studio_hub_settings_button)
        page.relink_button = page._tool_button("fa5s.link", "重新定位源媒体", page._relink_media)
        page.relink_button.hide()
        bar.addWidget(page.relink_button)
        page.save_button = page._tool_button("fa5s.save", "保存项目 (Ctrl+S)", page.save)
        page.studio_save_button = page.save_button
        bar.addWidget(page.save_button)
        bar.addWidget(page._toolbar_divider())
        undo_button = page._tool_button("fa5s.undo", "撤销 (Ctrl+Z)", page._undo_interactive)
        redo_button = page._tool_button("fa5s.redo", "重做 (Ctrl+Y)", page._redo_interactive)
        undo_button.setEnabled(page.undo_stack.canUndo())
        redo_button.setEnabled(page.undo_stack.canRedo())
        page.undo_stack.canUndoChanged.connect(undo_button.setEnabled)
        page.undo_stack.canRedoChanged.connect(redo_button.setEnabled)
        bar.addWidget(undo_button)
        bar.addWidget(redo_button)
        bar.addWidget(page._toolbar_divider())
        page.workspace_actions: dict[str, QAction] = {}
        page.editor_field_actions: dict[str, QAction] = {}
        # Display mode lives in the Tool Panel settings menu, not the removed
        # workspace dropdown.
        page.mono_display_action = QAction("单语", page)
        page.bilingual_display_action = QAction("双语", page)
        for action in (page.mono_display_action, page.bilingual_display_action):
            action.setCheckable(True)
        page.mono_display_action.setChecked(True)
        page.mono_display_action.triggered.connect(lambda: page._set_bilingual_mode(False))
        page.bilingual_display_action.triggered.connect(lambda: page._set_bilingual_mode(True))
        page.cue_list_toggle_button = QPushButton("字幕列表")
        page.cue_list_toggle_button.setObjectName("studioButton")
        page.cue_list_toggle_button.setIcon(_icon("fa5s.list", GREEN))
        page.cue_list_toggle_button.setCheckable(True)
        page.cue_list_toggle_button.setChecked(True)
        bind_text(page.cue_list_toggle_button, '显示或收起左侧字幕列表', property='toolTip')
        page.cue_list_toggle_button.clicked.connect(
            lambda checked: page._set_major_panel_visible("cue_list", checked)
        )
        bar.addWidget(page.cue_list_toggle_button)
        page.context_expand_button = QPushButton("工具面板")
        page.context_expand_button.setObjectName("studioButton")
        page.context_expand_button.setIcon(_icon("fa5s.columns", GREEN))
        page.context_expand_button.setCheckable(True)
        page.context_expand_button.setChecked(True)
        bind_text(page.context_expand_button, '显示或收起右侧工具面板', property='toolTip')
        page.context_expand_button.clicked.connect(page._toggle_context_panel)
        bar.addWidget(page.context_expand_button)
        page.review_mode_button = QPushButton("进入审核模式")
        page.review_mode_button.setObjectName("studioButton")
        # 2026-09-06（用户四图反馈·图三）：审核模式此前是工具行里唯一无图标的
        # 按钮；与行内其它工具按钮统一走 themed role 图标（随主题重着色）。
        install_themed_icon(page.review_mode_button, "fa5s.glasses", "primary")
        page.review_mode_button.setCheckable(True)
        bind_text(page.review_mode_button, 'R 进入 / 退出审核模式', property='toolTip')
        page.review_mode_button.toggled.connect(page._set_review_mode)
        page.review_mode_button.setParent(page)
        page.review_mode_button.hide()
        find_replace = QPushButton("批量替换")
        page.studio_find_replace_button = find_replace
        find_replace.setObjectName("studioButton")
        find_replace.setStyleSheet("min-width: 86px; padding: 0 4px;")
        find_replace.setIcon(_icon("fa5s.exchange-alt", GREEN))
        bind_text(find_replace, '查找并替换字幕文字 (Ctrl+F / Ctrl+H)', property='toolTip')
        find_replace.clicked.connect(page._open_find_replace)
        bar.addWidget(find_replace)
        # 2026-10-14: the user's own line-broken script, timed by the project's
        # word timestamps only (no model, no AI); see studio_script_match.
        script_match = QPushButton("匹配文稿")
        page.studio_script_match_button = script_match
        script_match.setObjectName("studioButton")
        bind_text(script_match, '贴上已断好句的完整文稿，只用字级时间对齐（不调用模型或 AI）', property='toolTip')

        def open_script_match():
            from .studio_script_match import open_script_match_dialog
            open_script_match_dialog(page)
        script_match.clicked.connect(open_script_match)
        bar.addWidget(script_match)
        bar.addWidget(page._toolbar_divider())
        # 2026-09-02（用户指示）：说话人管理改为与其它工具一致的
        # 文本按钮 + 同色图标，不再是无文字的白色纯图标。
        page.speaker_manager_button = QPushButton("说话人管理")
        page.speaker_manager_button.setObjectName("studioButton")
        page.speaker_manager_button.setIcon(_icon("fa5s.users", GREEN))
        bind_text(page.speaker_manager_button, '打开 Speaker Manager', property='toolTip')
        page.speaker_manager_button.clicked.connect(page._open_speaker_manager)
        bar.addWidget(page.speaker_manager_button)
        page.bilingual_toggle_button = QPushButton("双语")
        page.bilingual_toggle_button.setObjectName("studioButton")
        page.bilingual_toggle_button.setIcon(_icon("fa5s.language", GREEN))
        page.bilingual_toggle_button.setCheckable(True)
        bind_text(page.bilingual_toggle_button, '切换单语 / 双语显示模式；菜单里可打开 AI 字幕翻译', property='toolTip')
        from PySide6.QtWidgets import QMenu

        bilingual_menu = create_studio_menu(page)
        # Original / translation / bilingual display, order, fonts, translation.
        from .studio_bilingual import build_menu as build_bilingual_menu
        build_bilingual_menu(page, bilingual_menu)
        page.bilingual_toggle_button.setMenu(bilingual_menu)
        bar.addWidget(page.bilingual_toggle_button)
        # 2026-10-13: punctuation style (添加标点 / 不加标点 / 保留原文) for preview
        # and every export; the manuscript is never rewritten by the choice.
        page.punctuation_button = QPushButton("标点")
        page.punctuation_button.setObjectName("studioButton")
        page.punctuation_button.setIcon(_icon("fa5s.paragraph", GREEN))
        punctuation_menu = create_studio_menu(page)
        from .studio_punctuation import build_menu as build_punctuation_menu
        build_punctuation_menu(page, punctuation_menu)
        page.punctuation_button.setMenu(punctuation_menu)
        bar.addWidget(page.punctuation_button)
        clip_assistant = QPushButton("剪辑助手")
        page.studio_clip_assistant_button = clip_assistant
        clip_assistant.setObjectName("studioButton")
        clip_assistant.setIcon(_icon("fa5s.film", GREEN))
        bind_text(clip_assistant, '录播爆点候选 / 剪辑助手', property='toolTip')
        clip_assistant.clicked.connect(page._open_clip_assistant)
        clip_assistant.setParent(page)
        clip_assistant.hide()
        shortcut_entry = QPushButton("快捷键设置")
        page.studio_shortcut_entry_button = shortcut_entry
        # One owned entry only. The old unattached icon button was later shown
        # by _set_hub_toolbar_mode(False), becoming an orphan native window.
        page.studio_shortcut_button = shortcut_entry
        shortcut_entry.setObjectName("studioButton")
        shortcut_entry.setStyleSheet("min-width: 86px; padding: 0 4px;")
        shortcut_entry.setIcon(_icon("fa5s.keyboard", GREEN))
        bind_text(shortcut_entry, '配置 Studio 快捷键', property='toolTip')
        shortcut_entry.clicked.connect(page._show_shortcut_settings)
        bar.addWidget(shortcut_entry)
        # Keys come from the shortcut registry (_install_shortcuts re-keys them).
        find_replace_shortcut = QShortcut(QKeySequence(page._shortcut_values.get("find_replace", "Ctrl+H")), page)
        find_replace_shortcut.activated.connect(page._open_find_replace)
        page._find_replace_shortcut = find_replace_shortcut
        # Ctrl+F is the usual "find"; it opens the same find/replace tools.
        find_shortcut = QShortcut(QKeySequence(page._shortcut_values.get("find", "Ctrl+F")), page)
        find_shortcut.activated.connect(page._open_find_replace)
        page._find_shortcut = find_shortcut
        bar.addWidget(page._toolbar_divider())
        export = QPushButton("导出字幕")
        page.studio_export_button = export
        export.setObjectName("studioButton")
        export.setIcon(_icon("fa5s.file-export"))
        export.clicked.connect(page.export_subtitles)
        bar.addWidget(export)
        render = QPushButton("压制成片")
        page.studio_render_button = render
        render.setObjectName("studioButton")
        render.clicked.connect(page._open_render_dialog)
        bar.addWidget(render)
        # Less frequent commands share one menu; their existing buttons retain
        # signal/shortcut ownership and are used by the menu actions.
        page._studio_toolbar_overflow_widgets = (open_button,
            page.bilingual_toggle_button, page.review_mode_button, clip_assistant)
        page._studio_compact_commands = (page.speaker_manager_button, shortcut_entry, find_replace, script_match)
        overflow=page._tool_button('fa5s.ellipsis-h', '更多工作区操作', lambda: None)
        overflow_menu=create_studio_menu(overflow)
        def update_workspace_menu():
            overflow_menu.clear()
            sources = page._studio_toolbar_overflow_widgets
            if any(not button.isVisible() for button in page._studio_compact_commands):
                sources += tuple(b for b in page._studio_compact_commands if not b.isVisible())
            for source in sources:
                if source.menu() is not None:
                    submenu = source.menu()
                    submenu.setTitle(source.text())
                    submenu.setIcon(source.icon())
                    overflow_menu.addMenu(submenu)
                    continue
                action=overflow_menu.addAction(source.icon(), source.text() or source.toolTip())
                action.setEnabled(source.isEnabled())
                action.setCheckable(source.isCheckable())
                action.setChecked(source.isChecked())
                action.triggered.connect(lambda _checked=False, button=source: button.click())
        overflow_menu.aboutToShow.connect(update_workspace_menu)
        overflow.setMenu(overflow_menu);overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        overflow.setProperty('hideMenuIndicator', True)  # "•••" already says "more"
        bar.addWidget(overflow)
        from .design.presentation import button_role
        for button, role, icon_name in (
            (page.cue_list_toggle_button,'toggle','fa5s.list'),
            (page.context_expand_button,'toggle','fa5s.columns'),
            (page.speaker_manager_button,'ghost','fa5s.users'),
            (page.bilingual_toggle_button,'secondary','fa5s.language'),
            (page.review_mode_button,'secondary','fa5s.glasses'),
            (find_replace,'secondary','fa5s.exchange-alt'),
            (script_match,'secondary','fa5s.align-left'),
            (clip_assistant,'secondary','fa5s.film'),
            (shortcut_entry,'secondary','fa5s.keyboard'),
            (page.punctuation_button,'secondary','fa5s.paragraph'),
            (export,'secondary','fa5s.file-export'),(render,'secondary','fa5s.file-video')):
            button_role(button,role,icon=icon_name)
        # 2026-10-14 (user screenshot): 「标点」 kept the old outlined combo look
        # with a green icon and 「压制成片」 was the only filled block with a
        # film-strip icon. Both now share the toolbar's ghost buttons; render
        # keeps its emphasis through accent text and icon only.
        for button in (page.punctuation_button, page.bilingual_toggle_button):
            button.setProperty('hasMenu', True)
        render.setProperty('emphasis', 'accent')
        install_themed_icon(render, 'fa5s.file-video', 'accent')
        # The application header is intentionally removed in Studio focus
        # mode. Keep the expected desktop controls in the Studio toolbar.
        controls = QFrame()
        controls.setObjectName("studioWindowControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(4, 0, 0, 0)
        controls_layout.setSpacing(1)
        page.studio_minimize_button = page._window_control(
            "fa5s.minus", "最小化", lambda: page.window().showMinimized()
        )
        page.studio_maximize_button = page._window_control(
            "fa5s.square", "最大化", page._toggle_window_maximized
        )
        page.studio_close_button = page._window_control(
            "fa5s.times", "关闭", lambda: page.window().close(), close=True
        )
        for control in (page.studio_minimize_button, page.studio_maximize_button, page.studio_close_button):
            controls_layout.addWidget(control)
        bar.addWidget(controls)
        outer.addWidget(toolbar)
        page._hub_toolbar_hidden = [
            page.studio_save_button if hasattr(page, "studio_save_button") else page.save_button,
            undo_button, redo_button, page.cue_list_toggle_button, page.context_expand_button,
            page.speaker_manager_button, find_replace, shortcut_entry, export, render,
            import_media,
            # A per-project display choice; nothing to set in the library (2026-10-14).
            page.punctuation_button, script_match,
        ]
        page._hub_toolbar_hidden.extend([page.relink_button])
        page._hub_toolbar_hidden.extend(toolbar.findChildren(QFrame, "toolbarDivider"))
        page._set_hub_toolbar_mode(True)
        page.teach_banner = QFrame()
        page.teach_banner.setObjectName("studioTeachBanner")
        page._apply_teach_banner_theme()
        teach_layout = QHBoxLayout(page.teach_banner)
        teach_layout.setContentsMargins(14, 6, 10, 6)
        teach_layout.setSpacing(8)
        page.teach_text = QLabel()
        page.teach_text.setWordWrap(True)
        teach_layout.addWidget(page.teach_text, 1)
        page.teach_close = page._tool_button("fa5s.times", "关闭提示", page.teach_banner.hide)
        teach_layout.addWidget(page.teach_close)
        page.teach_banner.hide()
        outer.addWidget(page.teach_banner)

        from .studio_media_availability import StudioMediaAvailability
        page.media_availability = StudioMediaAvailability(page, outer)

        page.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        page.workspace_splitter.setObjectName("studioWorkspaceSplitter")
        page.workspace_splitter.setChildrenCollapsible(False)
        page.workspace_splitter.setHandleWidth(5)
        # Rubber-band the timeline split so mpv/HWND is not resized on every
        # mouse pixel. Video preview follows after the drag, not ahead of it.
        page.workspace_splitter.setOpaqueResize(False)
        page.upper_splitter = QSplitter(Qt.Orientation.Horizontal)
        page.upper_splitter.setObjectName("studioUpperSplitter")
        page.upper_splitter.setChildrenCollapsible(False)
        page.upper_splitter.setHandleWidth(5)
        page.upper_splitter.setOpaqueResize(True)

        page.cue_list_panel = self._cue_list_panel()
        page.upper_splitter.addWidget(page.cue_list_panel)

        page.center_splitter = QSplitter(Qt.Orientation.Vertical)
        page.center_splitter.setObjectName("studioCenterSplitter")
        page.center_splitter.setChildrenCollapsible(False)
        page.center_splitter.setHandleWidth(5)
        page.center_splitter.setOpaqueResize(True)
        video_host = QWidget()
        video_host.setMinimumHeight(160)
        video_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        video_layout = QVBoxLayout(video_host)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)
        overlay_host = QWidget()
        overlay_host.setObjectName("studioVideoOverlayHost")
        page.video_overlay_host = overlay_host
        video_stack = QGridLayout(overlay_host)
        video_stack.setContentsMargins(0, 0, 0, 0)
        video_stack.setSpacing(0)
        page.video = MpvCanvas()
        page.video.error.connect(page._show_video_error)
        page.video.position_changed.connect(page._position_changed)
        page.video.playback_state_changed.connect(page._playback_state_changed)
        # 十八轮：双击视频层 → AI 字幕工坊（对话式二修特效字幕）。
        page.video.workshop_requested.connect(page._open_web_theme_workshop)
        video_stack.addWidget(page.video, 0, 0)
        from .video_compositor import VideoCompositionScene
        from .audio_engine import StudioAudioEngine

        page.video_compositor = VideoCompositionScene(page.video)
        page.audio_engine = StudioAudioEngine(page)
        page.video.playback_prepare = lambda: page._sync_video_compositor(int(page.timeline.playhead_ms))
        page.video.playback_ready = page._playback_buffers_ready
        page.video.set_external_clock_provider(page.audio_engine.clock_observation)
        page.video_compositor.transform_preview.connect(page._video_transform_previewed)
        page.video_compositor.transform_committed.connect(page._video_transform_committed)
        empty_host = QWidget()
        empty_host.setObjectName("studioVideoEmptyHost")
        empty_layout = QVBoxLayout(empty_host)
        empty_layout.setContentsMargins(20, 20, 20, 20)
        empty_layout.setSpacing(0)
        empty_layout.addStretch(1)
        page.video_drop_zone = QFrame()
        page.video_drop_zone.setObjectName("studioVideoDropZone")
        page.video_drop_zone.setMinimumSize(280, 220)
        page.video_drop_zone.setMaximumWidth(720)
        page.video_drop_zone.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        drop_layout = QVBoxLayout(page.video_drop_zone)
        drop_layout.setContentsMargins(28, 24, 28, 24)
        drop_layout.setSpacing(10)
        page.video_empty_icon = QLabel()
        page.video_empty_icon.setObjectName("studioVideoEmptyIcon")
        page.video_empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.video_empty_icon.setPixmap(_icon("fa5s.film").pixmap(40, 40))
        drop_layout.addWidget(page.video_empty_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        page.video_empty_label = QLabel("拖入视频或音频")
        page.video_empty_label.setObjectName("studioVideoEmptyHint")
        page.video_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.video_empty_label.setWordWrap(True)
        page.video_empty_label.setMinimumWidth(0)
        drop_layout.addWidget(page.video_empty_label)
        page.video_empty_import = QPushButton("导入媒体")
        page.video_empty_import.setObjectName("studioPrimary")
        page.video_empty_import.setMinimumHeight(36)
        page.video_empty_import.setMinimumWidth(132)
        page.video_empty_import.setCursor(Qt.CursorShape.PointingHandCursor)
        page.video_empty_import.clicked.connect(page.import_media_dialog)
        drop_layout.addWidget(page.video_empty_import, 0, Qt.AlignmentFlag.AlignHCenter)
        recovery_row = QHBoxLayout()
        recovery_row.setSpacing(8)
        page.video_empty_retry = QPushButton("重试")
        page.video_empty_retry.setObjectName("studioPrimary")
        page.video_empty_retry.clicked.connect(page._retry_media_ingest)
        page.video_empty_retry.hide()
        recovery_row.addWidget(page.video_empty_retry)
        page.video_empty_reselect = QPushButton("重新选择")
        page.video_empty_reselect.setObjectName("studioButton")
        page.video_empty_reselect.clicked.connect(page.import_media_dialog)
        page.video_empty_reselect.hide()
        recovery_row.addWidget(page.video_empty_reselect)
        drop_layout.addLayout(recovery_row)
        page.video_empty_note = QLabel("支持 MP4 / FLV / MKV / MOV / MP3 / WAV 等常用格式")
        page.video_empty_note.setObjectName("studioVideoEmptyNote")
        page.video_empty_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.video_empty_note.setWordWrap(True)
        page.video_empty_note.setMinimumWidth(0)
        drop_layout.addWidget(page.video_empty_note)
        empty_layout.addWidget(page.video_drop_zone, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(1)
        page.video_empty_hint = empty_host
        empty_host.hide()
        video_stack.addWidget(empty_host, 0, 0)
        # One child overlay stack owns every Studio visual. A Qt.Tool here is
        # an independent top-level HWND and can flash outside the main window.
        page.advanced_cue_overlay = AdvancedLiveCanvas(page.video)
        page.advanced_cue_overlay.hide()

        page.subtitle_edit_card = QFrame(overlay_host)
        page.subtitle_edit_card.setObjectName("subtitleEditCard")
        # Keep the editor as an ordinary child.  A native, initially parentless
        # QFrame creates a transient top-level HWND during project open.
        page.subtitle_edit_card.setAttribute(
            Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True
        )
        page._apply_subtitle_edit_card_theme()
        edit_card_layout = QVBoxLayout(page.subtitle_edit_card)
        edit_card_layout.setContentsMargins(16, 6, 16, 8)
        edit_card_layout.setSpacing(4)
        edit_header = QHBoxLayout()
        edit_title = QLabel("当前字幕")
        edit_title.setObjectName("subtitleEditCardTitle")
        edit_header.addWidget(edit_title)
        edit_header.addStretch(1)
        edit_shortcuts = QLabel("Enter 确认  ·  Shift+Enter 换行  ·  Esc 取消")
        edit_shortcuts.setObjectName("subtitleEditCardHint")
        edit_header.addWidget(edit_shortcuts)
        edit_card_layout.addLayout(edit_header)
        page.subtitle_edit_input = _SubtitleEditCardEditor()
        page.subtitle_edit_input.setObjectName("subtitleEditCardInput")
        page.subtitle_edit_input.setMinimumHeight(52)
        page.subtitle_edit_input.setMaximumHeight(84)
        bind_text(page.subtitle_edit_input, '选中时间轴上的字幕后，在这里直接改文字', property='placeholderText')
        page.subtitle_edit_input.setTabChangesFocus(False)
        option = page.subtitle_edit_input.document().defaultTextOption()
        option.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        page.subtitle_edit_input.document().setDefaultTextOption(option)
        page.subtitle_edit_input.commit_requested.connect(
            lambda advance=False: page._commit_canvas_inline_edit(advance=advance)
        )
        page.subtitle_edit_input.cancel_requested.connect(page._cancel_canvas_inline_edit)
        page.subtitle_edit_input.textChanged.connect(page._queue_edit_preview)
        edit_card_layout.addWidget(page.subtitle_edit_input)
        page.subtitle_edit_card.setMinimumWidth(680)
        page.subtitle_edit_card.setMaximumHeight(108)
        page.subtitle_edit_card.setMaximumWidth(1100)
        video_stack.addWidget(
            page.subtitle_edit_card, 0, 0,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        )
        page.subtitle_edit_card.hide()
        page.subtitle_edit_card.raise_()
        video_layout.addWidget(overlay_host, 1)
        page.review_summary_strip = QFrame()
        page.review_summary_strip.setObjectName("reviewSummaryStrip")
        strip_layout = QVBoxLayout(page.review_summary_strip)
        strip_layout.setContentsMargins(10, 4, 10, 4)
        strip_layout.setSpacing(7)
        strip_header = QHBoxLayout()
        page.review_summary_text = QLabel("需要检查：-")
        page.review_summary_text.setObjectName("reviewIssueSummary")
        page.review_summary_text.setWordWrap(False)
        strip_header.addWidget(page.review_summary_text, 1)
        page.review_reason_label = QLabel("")
        page.review_reason_label.setObjectName("reviewReason")
        page.review_reason_label.setWordWrap(False)
        strip_header.addWidget(page.review_reason_label, 2)
        page.review_queue_label = QLabel("需要检查  - / -")
        page.review_queue_label.setObjectName("reviewQueueCount")
        page.review_queue_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        strip_header.addWidget(page.review_queue_label, 0)
        review_confirm = QPushButton("当前正确")
        review_confirm.setObjectName("studioPrimary")
        bind_text(review_confirm, '确认当前字幕，不修改文本 (Enter)', property='toolTip')
        review_confirm.clicked.connect(page._confirm_current_review)
        strip_header.addWidget(review_confirm)
        review_replay = QPushButton("重听")
        review_replay.setObjectName("studioButton")
        review_replay.clicked.connect(page._play_review_context)
        strip_header.addWidget(review_replay)
        review_details = QPushButton("详情")
        review_details.setObjectName("studioButton")
        review_details.clicked.connect(lambda: page._show_context_panel())
        strip_header.addWidget(review_details)
        review_collapse = QToolButton()
        review_collapse.setObjectName("reviewCollapseButton")
        review_collapse.setText("⌃")
        bind_text(review_collapse, '收起或展开审核面板', property='toolTip')
        review_collapse.setCheckable(True)
        review_collapse.toggled.connect(page._toggle_review_dock)
        strip_header.addWidget(review_collapse)
        strip_layout.addLayout(strip_header)
        page.review_dock_candidates = QWidget()
        page.review_dock_candidate_layout = QGridLayout(page.review_dock_candidates)
        page.review_dock_candidate_layout.setContentsMargins(0, 0, 0, 0)
        page.review_dock_candidate_layout.setHorizontalSpacing(8)
        page.review_dock_candidate_layout.setVerticalSpacing(6)
        # 2026-10-15: one fixed-height row. Rebuilt cards used to change the
        # strip between 125 and 255 px per caption, so the video above it
        # (mpv, captions, overlays) re-laid out on every review step.
        page.review_dock_scroll = QScrollArea()
        page.review_dock_scroll.setObjectName("reviewDockScroll")
        page.review_dock_scroll.setWidgetResizable(True)
        page.review_dock_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page.review_dock_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page.review_dock_scroll.setFixedHeight(REVIEW_DOCK_ROW_HEIGHT)
        page.review_dock_scroll.setWidget(page.review_dock_candidates)
        strip_layout.addWidget(page.review_dock_scroll)
        page.review_legend = QLabel("[1–4] 采用并下一条   [↑↓] 切换   [Space] 重听   [E] 编辑   [R] 退出审核   [Enter] 当前正确")
        page.review_legend.setObjectName("reviewLegend")
        page.review_legend.setTextFormat(Qt.TextFormat.RichText)
        strip_layout.addWidget(page.review_legend)
        page.review_summary_strip.hide()
        video_layout.addWidget(page.review_summary_strip)
        # Keep exactly one regular Qt child for Transform painting/interaction.
        # It must never become a helper top-level HWND.
        page.position_overlay = SubtitlePositionOverlay(page.video, top_level=False)
        page.video.video_display_size_changed.connect(page.position_overlay.set_video_size)
        page.position_overlay.position_moved.connect(page._position_overlay_moved)
        page.position_overlay.position_committed.connect(page._position_overlay_committed)
        page.position_overlay.font_size_preview.connect(page._position_overlay_font_preview)
        page.position_overlay.font_size_committed.connect(page._position_overlay_font_committed)
        page.position_overlay.position_cancelled.connect(page._position_overlay_cancelled)
        page.position_overlay.doubleClickRequested.connect(page._begin_canvas_inline_edit)
        page.position_overlay.interaction_started.connect(
            page._position_overlay_interaction_started
        )
        page.video.installEventFilter(page)
        page.position_slider = QSlider(Qt.Orientation.Horizontal)
        page.position_slider.setRange(0, 1000)
        page.position_slider.sliderMoved.connect(page._slider_seek)
        page.position_slider.hide()
        page.center_splitter.addWidget(video_host)

        page.cue_editor = QFrame()
        page.cue_editor.setObjectName("cueEditor")
        page.cue_editor.setMinimumHeight(88)
        editor_layout = QVBoxLayout(page.cue_editor)
        editor_layout.setContentsMargins(14, 7, 12, 8)
        editor_layout.setSpacing(5)

        page.editor_fields = QHBoxLayout()
        fields = page.editor_fields
        fields.setSpacing(5)
        page.editor_title = QLabel("当前字幕编辑器")
        page.editor_title.setObjectName("sectionTitle")
        fields.addWidget(page.editor_title)
        fields.addSpacing(5)
        page.speaker_label = QLabel("说话人")
        page.speaker_label.setObjectName("fieldLabel")
        fields.addWidget(page.speaker_label)
        page.speaker = StudioComboBox()
        page.speaker.setMinimumWidth(104)
        page.speaker.setMaximumWidth(150)
        page.speaker.setProperty("i18nUserText", True)
        page.speaker.currentIndexChanged.connect(page._speaker_changed)
        fields.addWidget(page.speaker)
        page.editor_field_widgets = {"speaker": (page.speaker_label, page.speaker)}
        page.start_label = QLabel("开始")
        page.start_label.setObjectName("fieldLabel")
        fields.addWidget(page.start_label)
        page.start_ms = _time_spinbox()
        page.start_ms.setMaximumWidth(138)
        page.start_ms.editingFinished.connect(page._timing_fields_changed)
        fields.addWidget(page.start_ms)
        page.editor_field_widgets["start"] = (page.start_label, page.start_ms)
        page.duration_label = QLabel("时长")
        page.duration_label.setObjectName("fieldLabel")
        fields.addWidget(page.duration_label)
        page.duration_ms = _time_spinbox()
        page.duration_ms.setMaximumWidth(138)
        page.duration_ms.editingFinished.connect(page._timing_fields_changed)
        fields.addWidget(page.duration_ms)
        page.editor_field_widgets["duration"] = (page.duration_label, page.duration_ms)
        page.end_ms = _time_spinbox()
        fields.addStretch(1)
        page.mono_button = QPushButton("单语")
        page.bilingual_button = QPushButton("双语")
        bind_text(page.mono_button, '单语显示模式', property='toolTip')
        bind_text(page.bilingual_button, '双语显示模式', property='toolTip')
        page.language_group = QButtonGroup(page)
        page.language_group.setExclusive(True)
        for button in (page.mono_button, page.bilingual_button):
            button.setObjectName("filterChip")
            button.setCheckable(True)
            page.language_group.addButton(button)
            # 2026-09-02：编辑字段旁的双语 chip 退役（工具栏语言按钮接管）；
            # 保留对象以兼容 _set_bilingual_mode 的既有引用。
            button.hide()
        page.mono_button.setChecked(True)
        page.mono_button.clicked.connect(lambda: page._set_bilingual_mode(False))
        page.bilingual_button.clicked.connect(lambda: page._set_bilingual_mode(True))
        page.editor_field_widgets["language"] = (page.mono_button, page.bilingual_button)
        page.editor_metadata = QWidget(page.cue_editor)
        page.editor_metadata.setLayout(fields)
        page.editor_metadata.hide()
        editor_layout.addWidget(page.editor_metadata)

        page.cue_text = QPlainTextEdit(page.cue_editor)
        page.cue_text.setObjectName("cueText")
        bind_text(page.cue_text, '当前字幕文本', property='placeholderText')
        page.cue_text.setMinimumHeight(58)
        page.cue_text.textChanged.connect(page._text_changed)
        page.translation_text = QPlainTextEdit(page.cue_editor)
        page.translation_text.setObjectName("cueText")
        bind_text(page.translation_text, '第二语言文本', property='placeholderText')
        page.translation_text.setMinimumHeight(54)
        page.translation_text.textChanged.connect(page._translation_changed)
        page.translation_text.hide()
        # Timeline/List inline editing are the primary paths. The text widgets
        # are reparented into the compact Style panel below, so the central
        # video no longer gives up height to a duplicate editor.
        page.cue_editor.hide()
        page.center_splitter.setStretchFactor(0, 1)
        page.center_splitter.setSizes([648])
        page.upper_splitter.addWidget(page.center_splitter)

        page.context_panel = QFrame()
        page.context_panel.setObjectName("contextPanel")
        page.context_panel.setMinimumWidth(360)
        # 2026-10-11: the splitter may widen the tool panel (clip candidates are
        # long texts); 520 left no room to drag it wider on large screens.
        page.context_panel.setMaximumWidth(760)
        page.context_panel.setMinimumHeight(120)
        context_layout = QVBoxLayout(page.context_panel)
        context_layout.setContentsMargins(0, 0, 0, 0)
        context_layout.setSpacing(0)
        context_header = QHBoxLayout()
        context_header.setContentsMargins(10, 5, 6, 0)
        context_title = QLabel("工具面板")
        context_title.setObjectName("sectionTitle")
        context_header.addWidget(context_title)
        context_header.addStretch(1)
        # 2026-09-06（用户四图反馈·图四）：面板头的「字幕显示」（文A 图标）按钮删除
        # ——与工具栏「双语」按钮重复；单语/双语切换与 AI 翻译入口都从工具栏走。
        # mono/bilingual_display_action 保留：菜单语义动作仍被 _set_bilingual_mode 使用。
        collapse = page._tool_button("fa5s.chevron-right", "收起右侧面板", page._collapse_context_panel)
        context_header.addWidget(collapse)
        context_layout.addLayout(context_header)
        page.context_drawer = QTabWidget()
        page.context_drawer.setObjectName("contextDrawer")
        # Keep tab geometry inside a narrow context drawer. The page toggles
        # scroll buttons only when measured tab content exceeds the available
        # width, so wide layouts retain the clean non-scrolling baseline.
        # Expanding tabs share the full drawer width so the tool group sits
        # centered instead of piling up at the left edge.
        page.context_drawer.tabBar().setUsesScrollButtons(False)
        page.context_drawer.tabBar().setExpanding(True)
        page.context_drawer.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        page.context_drawer.setIconSize(QSize(18, 18))
        page._context_tab_mode = ""
        page.context_drawer.addTab(self._scroll_context_panel(self._ai_panel()), QIcon(), "AI设计")
        # 二十七轮（agy 复审）：样式面板内容随特效字幕模式伸缩，常驻细滚动条
        # 明示可滚——展开快速调整时不再像"布局截断"。
        style_scroll = self._scroll_context_panel(page._style_panel_p213())
        style_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        page.context_drawer.addTab(style_scroll, QIcon(), "样式")
        page.video_transform_tab_index = page.context_drawer.addTab(
            self._scroll_context_panel(self._video_transform_panel()), QIcon(), "视频"
        )
        from .studio_highlight_ui import HighlightAssistantPanel
        page.highlight_panel = HighlightAssistantPanel()
        page.highlight_tab_index = page.context_drawer.addTab(
            self._self_scrolling_context_panel(page.highlight_panel, page.highlight_panel.settings_area),
            QIcon(), "剪辑助手"
        )
        from .studio_media_pool_ui import StudioMediaPoolPanel

        page.media_pool_panel = StudioMediaPoolPanel(page)
        page.media_pool_tab_index = page.context_drawer.addTab(
            self._scroll_context_panel(page.media_pool_panel), QIcon(), "素材"
        )
        for index, tip in enumerate(("AI设计", "样式", "视频", "剪辑助手", "素材")):
            page.context_drawer.setTabToolTip(index, tip)
        install_themed_tabs(page.context_drawer, [
            ("fa5s.magic", "secondary"), ("fa5s.palette", "secondary"),
            ("fa5s.expand-arrows-alt", "secondary"), ("fa5s.cut", "secondary"),
            ("fa5s.photo-video", "secondary"),
        ])
        page.context_drawer.currentChanged.connect(page._remember_context_tab)
        from PySide6.QtWidgets import QStackedWidget
        page.context_stack = QStackedWidget(page.context_panel)
        page.context_stack.addWidget(page.context_drawer)
        context_layout.addWidget(page.context_stack, 1)
        page.upper_splitter.addWidget(page.context_panel)
        page.upper_splitter.setStretchFactor(0, 0)
        page.upper_splitter.setStretchFactor(1, 1)
        page.upper_splitter.setStretchFactor(2, 0)
        page.upper_splitter.setSizes([320, 680, 440])
        page.upper_splitter.splitterMoved.connect(
            lambda *_args: (
                page._update_editor_compactness(),
                page._update_cue_table_layout(),
            )
        )
        # QSplitter already resizes all children in the same geometry pass.
        # Keep the only lightweight adaptive label update on the horizontal
        # splitter; never force layouts or drain posted events while dragging.
        page.workspace_splitter.addWidget(page.upper_splitter)

        timeline_host = QFrame()
        timeline_host.setObjectName("timelineHost")
        timeline_layout = QVBoxLayout(timeline_host)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(0)
        timeline_toolbar = QHBoxLayout()
        # Parent controls as they are created; removing an unparented layout
        # item during construction can invalidate its native style resources.
        timeline_layout.addLayout(timeline_toolbar)
        from .project_range_ui import ProjectRangeBar
        page.project_range_bar = ProjectRangeBar(lambda:page.project,
            lambda:page.timeline.playhead_ms, lambda ms:page._seek(ms/1000.0),
            page.undo_stack, page)
        timeline_layout.addWidget(page.project_range_bar)
        # 2026-10-09 (M16, user): I and O already mark the range on the
        # ruler in green; the in/out row, clear-range, auto-avoid, save-frame
        # and cover controls leave this extra row. The range is named and
        # cleared from the timeline context menu, auto-avoid lives in the
        # timeline options menu, frame/cover become icon buttons.
        page.project_range_bar.hide()
        page.auto_stacking_toggle=QCheckBox('新字幕自动避让')
        page.auto_stacking_toggle.setObjectName('timelineToggleChip')
        page.auto_stacking_toggle.setChecked(True)
        bind_text(page.auto_stacking_toggle, '仅为新生成字幕保存初始避让位置；人工排版后保持位置。右键可按明确范围重新排版，一次撤销。', property='toolTip')
        def toggle_stacking(checked):
            if page.project:
                page.project.studio_state['auto_subtitle_stacking']=bool(checked)
                page._changed()
        page.auto_stacking_toggle.toggled.connect(toggle_stacking)
        page.auto_stacking_toggle.setContextMenuPolicy(Qt.CustomContextMenu)
        def fill_stacking_menu(menu):
            from .theme_visual_bounds import start_studio_calibration
            from .subtitle_layout_ui import open_layout_preview
            def rearrange(scope):
                if not page.project:return
                from .studio_edit_sequence import source_cue_id_of
                current_id = source_cue_id_of(str(page.selected_cue_id or ''))
                current = next((c for c in page.project.cues if c.id == current_id), None)
                if scope == 'all':ids=[c.id for c in page.project.cues]
                elif scope == 'speaker':ids=[c.id for c in page.project.cues if current and c.speaker_id == current.speaker_id]
                elif scope == 'selected':
                    rows=page.cue_table.selectionModel().selectedRows()
                    ids=[str(page.cue_model.data(page.cue_model.index(row.row(),0),Qt.UserRole)) for row in rows]
                else:ids=[page.selected_cue_id] if page.selected_cue_id else []
                open_layout_preview(page, ids)
            for label,scope in [('当前字幕','current'),('已选字幕','selected'),('当前说话人字幕','speaker'),('全部字幕','all')]:
                menu.addAction(f'预览重新排版{label}（可撤销）…',lambda _checked=False,s=scope:rearrange(s))
            menu.addSeparator()
            from .display_handoff_ui import bridge_short_gaps, open_handoff_preview
            menu.addAction('预览说话人交接边界（可撤销）…', lambda: open_handoff_preview(page))
            bridge = menu.addAction('衔接 0.5 秒以内的字幕间隙（防闪烁，可撤销）', lambda: bridge_short_gaps(page))
            bridge.setToolTip(tr('上一条字幕的结束接到下一条的开始；下一条的开始时间不变'))
            menu.addAction('测量重叠 HTML 主题装饰…', lambda: start_studio_calibration(page))

        def stacking_menu(point):
            from PySide6.QtWidgets import QMenu
            menu = QMenu(page.auto_stacking_toggle)
            fill_stacking_menu(menu)
            menu.exec(page.auto_stacking_toggle.mapToGlobal(point))
        page.auto_stacking_toggle.customContextMenuRequested.connect(stacking_menu)
        def refresh_stacking():
            if not page.project:return
            from .subtitle_stacking import project_stack_layout
            control=page.auto_stacking_toggle
            control.blockSignals(True)
            control.setChecked(page.project.studio_state.get('auto_subtitle_stacking',True))
            control.blockSignals(False)
            warnings=project_stack_layout(page.project).warnings
            bind_text(control, '新字幕自动避让 ⚠' if warnings else '新字幕自动避让')
            bind_text(control, '\n'.join(warnings[:8]) if warnings else '仅影响新生成字幕的初始布局；保存的人工位置保持不变。右键可按范围重新排版，一次撤销。', property='toolTip')
        page.project_range_bar._timer.timeout.connect(refresh_stacking)
        page.auto_stacking_toggle.setParent(page)
        page.auto_stacking_toggle.hide()
        page._fill_stacking_menu = fill_stacking_menu
        timeline_toolbar.setContentsMargins(12, 6, 10, 6)
        timeline_title = QLabel("时间轴")
        timeline_title.setObjectName("sectionTitle")
        timeline_toolbar.addWidget(timeline_title)
        timeline_toolbar.addSpacing(10)
        page.media_pool_button = page._tool_button(
            "fa5s.photo-video",
            "打开媒体池",
            lambda: page._toggle_drawer(page.media_pool_tab_index),
        )
        timeline_toolbar.addWidget(page.media_pool_button)
        page.add_video_track_button = page._tool_button(
            "fa5s.layer-group", "新建视频轨", page._add_video_track
        )
        timeline_toolbar.addWidget(page.add_video_track_button)
        from .studio_track_delete import add_subtitle_track
        page.add_subtitle_track_button = page._tool_button(
            'fa5s.closed-captioning', '新建字幕轨 · 按 T 在此轨添加字幕', lambda: add_subtitle_track(page))
        timeline_toolbar.addWidget(page.add_subtitle_track_button)
        page.add_subtitle_button = page._tool_button(
            'fa5s.plus', '添加字幕 (T) · 在播放头创建字幕块', page._add_subtitle_at_playhead)
        page.add_subtitle_button.setText(tr('添加字幕'))
        page.add_subtitle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        timeline_toolbar.addWidget(page.add_subtitle_button)
        page.selection_tool_button = page._tool_button("fa5s.mouse-pointer", "选择工具 (V)", lambda: page._set_timeline_tool("selection"))
        page.track_forward_tool_button = page._tool_button("fa5s.arrow-right", "轨道向前选择 (A) · Shift 单轨", lambda: page._set_timeline_tool("track_forward"))
        page.razor_tool_button = page._tool_button("fa5s.cut", "剃刀工具 (C)——移动鼠标预览切点与前后文字，点击切开；Esc 取消", lambda: page._set_timeline_tool("razor"))
        # 2026-09-03（用户需求重做）：合并工具点选字幕后按住向左/右拖动即定向
        # 合并；再点击另一条字幕则两点配对。不再拿播放头处的旧选中当合并对象。
        page.merge_tool_button = page._tool_button("fa5s.link", "合并工具 (B)——点选字幕后拖动方向合并", lambda: page._set_timeline_tool("merge"))
        for button in (page.selection_tool_button, page.track_forward_tool_button, page.razor_tool_button, page.merge_tool_button):
            button.setCheckable(True)
            timeline_toolbar.addWidget(button)
        page.selection_tool_button.setChecked(True)
        from .studio_transition_ui import menu as transition_menu
        transition_button=page._tool_button('fa5s.adjust','转场 · Ctrl+D 视频 / Ctrl+Shift+D 音频',lambda:None)
        transition_button.setPopupMode(QToolButton.InstantPopup)
        transition_button.setMenu(transition_menu(page))
        timeline_toolbar.addWidget(transition_button)
        page.clip_selection_count=QLabel('')
        timeline_toolbar.addWidget(page.clip_selection_count)
        timeline_toolbar.addWidget(page._toolbar_divider())
        timeline_toolbar.addWidget(page._tool_button("fa5s.cut", "拆分当前字幕 (Ctrl+Shift+S)", page._split_current))
        timeline_toolbar.addWidget(page._tool_button("fa5s.link", "与下一条合并 (Ctrl+Shift+M)", page._merge_next))
        timeline_toolbar.addWidget(page._tool_button("fa5s.step-backward", "波纹向前合并 (Shift+Q)", lambda: page.cue_controller.merge_with_neighbor(-1)))
        timeline_toolbar.addWidget(page._tool_button("fa5s.step-forward", "波纹向后合并 (Shift+W)", lambda: page.cue_controller.merge_with_neighbor(1)))
        timeline_toolbar.addWidget(page._tool_button("fa5s.trash-alt", "删除当前字幕 (Delete)", page._delete_current))
        timeline_toolbar.addWidget(page._toolbar_divider())
        page.smart_align_button = page._tool_button("fa5s.magic", "智能修轴当前字幕", page._smart_align_current)
        timeline_toolbar.addWidget(page.smart_align_button)
        page.loop_cue_button = page._tool_button("fa5s.sync-alt", "循环当前字幕（前后留 250/300ms）", page._toggle_loop_current)
        timeline_toolbar.addWidget(page.loop_cue_button)
        timeline_toolbar.addWidget(page._toolbar_divider())
        page.ai_optimize_button = page._tool_button("fa5s.magic", "AI 优化当前字幕", lambda: page._toggle_drawer(0))
        page.reasr_button = page._tool_button("fa5s.microphone", "重新识别当前字幕", page._reasr_current)
        page.cue_more_button = page._tool_button("fa5s.ellipsis-h", "更多当前字幕操作", page._show_cue_more_menu)
        for button in (page.ai_optimize_button, page.reasr_button, page.cue_more_button):
            timeline_toolbar.addWidget(button)
        timeline_toolbar.addWidget(page._toolbar_divider())
        transport_start = page._tool_button("fa5s.step-backward", "上一帧 (Left)", lambda: page._frame_step(True))
        timeline_toolbar.addWidget(transport_start)
        page.play_button = page._tool_button("fa5s.play", "播放或暂停 (Space)", page._toggle_playback)
        page.play_button.setProperty("transportRole", "play")
        # Glyph in the on-accent colour at about half the circle, so it reads as
        # centred with room around it (2026-10-14: 24 px in a 34 px circle).
        install_themed_icon(page.play_button, "fa5s.play", "on_accent")
        page.play_button.setIconSize(QSize(16, 16))
        timeline_toolbar.addWidget(page.play_button)
        timeline_toolbar.addWidget(page._tool_button("fa5s.step-forward", "下一帧 (Right)", lambda: page._frame_step(False)))
        page.position_label = QLabel("00:00:00.000")
        page.position_label.setObjectName("timelineTimecode")
        page.position_label.setMinimumWidth(112)
        timeline_toolbar.addWidget(page.position_label)
        page.timecode_input = QLineEdit()
        page.timecode_input.setObjectName("timelineTimecodeInput")
        page.timecode_input.setPlaceholderText("hh:mm:ss.ms")
        page.timecode_input.setText("00:00:00.000")
        page.timecode_input.setFixedWidth(128)
        bind_text(page.timecode_input, '输入时间码并回车跳转（mm:ss.ms 或 hh:mm:ss.ms）', property='toolTip')
        page.timecode_input.returnPressed.connect(page._go_to_timecode)
        timeline_toolbar.addWidget(page.timecode_input)
        # 五十二轮：当前时间/总时长构成读数层级——当前可输入（chip）、总时长 muted。
        page.timeline_duration_label = QLabel("")
        page.timeline_duration_label.setObjectName("timelineDuration")
        bind_text(page.timeline_duration_label, '时间轴总时长（当前时间可编辑跳转）', property='toolTip')
        timeline_toolbar.addWidget(page.timeline_duration_label)
        page.speed_box = StudioComboBox()
        page.speed_box.setFixedWidth(68)
        for value in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0, 8.0):
            page.speed_box.addItem(f"{value:g}x", value)
        page.speed_box.setCurrentIndex(page.speed_box.findData(1.0))
        page.speed_box.currentIndexChanged.connect(
            lambda: page._set_speed(float(page.speed_box.currentData()))
        )
        timeline_toolbar.addWidget(page.speed_box)
        timeline_toolbar.addWidget(_icon_label("fa5s.volume-up"))
        page.volume_slider = QSlider(Qt.Orientation.Horizontal)
        page.volume_slider.setRange(0, 100)
        page.volume_slider.setValue(70)
        page.volume_slider.setFixedWidth(72)
        bind_text(page.volume_slider, '播放音量', property='toolTip')
        page.volume_slider.valueChanged.connect(page._set_volume)
        timeline_toolbar.addWidget(page.volume_slider)
        page.audio_diagnostic_button=QPushButton('声音诊断', page)
        page.audio_diagnostic_button.hide()
        bind_text(page.audio_diagnostic_button, '启动最多 120 秒本应用状态诊断；再次点击标记异常，不录音', property='toolTip')
        from .audio_diagnostic_marker import AudioDiagnosticMarker
        page.audio_diagnostic_marker=AudioDiagnosticMarker(page,page.audio_diagnostic_button)
        timeline_toolbar.addStretch(1)
        timeline_toolbar.addWidget(page._toolbar_divider())
        view_start = page._tool_button("fa5s.search-minus", "缩小时间轴 (Ctrl+滚轮)", lambda: page._zoom_timeline(1.25))
        timeline_toolbar.addWidget(view_start)
        timeline_toolbar.addWidget(page._tool_button("fa5s.search-plus", "放大时间轴 (Ctrl+滚轮)", lambda: page._zoom_timeline(0.8)))
        fit_button = page._tool_button("fa5s.compress-arrows-alt", "时间轴适应窗口", page._fit_timeline)
        page.timeline_fit_button = fit_button
        timeline_toolbar.addWidget(fit_button)
        page.waveform_toggle = QCheckBox("显示波形")
        page.waveform_toggle.setObjectName("timelineToggleChip")
        page.waveform_toggle.setChecked(True)
        bind_text(page.waveform_toggle, '显示或隐藏紧凑波形轨道', property='toolTip')
        timeline_toolbar.addWidget(page.waveform_toggle)
        page.filmstrip_toggle = QCheckBox('缩略图')
        page.filmstrip_toggle.setObjectName("timelineToggleChip")
        page.filmstrip_toggle.setChecked(True)
        bind_text(page.filmstrip_toggle, '显示视频缩略图；按视口在后台生成，播放时暂停生成', property='toolTip')
        def toggle_filmstrip(checked):
            page.timeline.filmstrip_visible=bool(checked)
            if page.project:page.project.studio_state['video_thumbnails_visible']=bool(checked)
            if not checked:page.timeline._thumbnails.set_view([])
            else: page.timeline.thumbnail_requests_enabled = True  # 重新勾选即恢复请求（2026-09-18 III：打开路径会临时禁用）
            page.timeline.update()
        page.filmstrip_toggle.toggled.connect(toggle_filmstrip)
        timeline_toolbar.addWidget(page.filmstrip_toggle)
        page.follow_playhead_toggle = QCheckBox("跟随播放头")
        page.follow_playhead_toggle.setObjectName("timelineToggleChip")
        page.follow_playhead_toggle.setChecked(True)
        bind_text(page.follow_playhead_toggle, '开启时连续跟随；关闭时仅越界翻页，播放头左对齐。字幕选择保持不变。', property='toolTip')
        page.follow_playhead_toggle.toggled.connect(page._follow_toggle_changed)
        timeline_toolbar.addWidget(page.follow_playhead_toggle)
        page.snap_toggle = QCheckBox("吸附")
        page.snap_toggle.setObjectName("timelineToggleChip")
        page.snap_toggle.setChecked(True)
        bind_text(page.snap_toggle, '拖动字幕时吸附到播放头、相邻边界和静音点（快捷键 S）', property='toolTip')
        page.snap_toggle.toggled.connect(page._toggle_timeline_snap)
        timeline_toolbar.addWidget(page.snap_toggle)
        for toggle, icon_name in ((page.waveform_toggle, 'fa5s.wave-square'), (page.filmstrip_toggle, 'fa5s.film'),
                                  (page.follow_playhead_toggle, 'fa5s.crosshairs'), (page.snap_toggle, 'fa5s.magnet')):
            install_themed_icon(toggle, icon_name, 'secondary')
            toggle.setIconSize(QSize(15, 15))
        from .frame_export_ui import install_frame_button
        install_frame_button(page, timeline_toolbar)
        from .cover_studio import install_cover_button
        install_cover_button(page, timeline_toolbar)
        for button in (page.save_frame_button, page.make_cover_button):
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setIconSize(QSize(18, 18))
        bind_text(page.make_cover_button, '制作封面：当前截图、新建封面或选择模板', property='toolTip')
        page.timeline_options_button = page._tool_button('fa5s.sliders-h', '时间轴选项 · 新字幕自动避让与重新排版', lambda: None)
        page.timeline_options_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        options_menu = create_studio_menu(page.timeline_options_button)

        def update_options_menu():
            options_menu.clear()
            control = page.auto_stacking_toggle
            action = options_menu.addAction(control.text())
            action.setCheckable(True)
            action.setChecked(control.isChecked())
            action.setEnabled(page.project is not None)
            action.setToolTip(control.toolTip())
            action.toggled.connect(control.setChecked)
            options_menu.addSeparator()
            fill_stacking_menu(options_menu)

        options_menu.aboutToShow.connect(update_options_menu)
        options_menu.setToolTipsVisible(True)
        page.timeline_options_button.setMenu(options_menu)
        timeline_toolbar.addWidget(page.timeline_options_button)
        # Keep the functional command groups stable. Single-cue
        # commands move into a menu without changing their callbacks.
        hidden_timeline=[]
        for i in range(timeline_toolbar.count()):
            widget=timeline_toolbar.itemAt(i).widget()
            if isinstance(widget,QToolButton) and widget.property('commandSource') in {
                '拆分当前字幕 (Ctrl+Shift+S)', '与下一条合并 (Ctrl+Shift+M)',
                '波纹向前合并 (Shift+Q)', '波纹向后合并 (Shift+W)',
                '删除当前字幕 (Delete)', '智能修轴当前字幕',
                '循环当前字幕（前后留 250/300ms）', 'AI 优化当前字幕', '重新识别当前字幕'}:
                hidden_timeline.append(widget)
        for widget in hidden_timeline:
            timeline_toolbar.removeWidget(widget);widget.setParent(page);widget.hide()
        page._timeline_overflow_widgets=hidden_timeline
        cue_menu=create_studio_menu(page.cue_more_button)
        def update_cue_menu():
            cue_menu.clear()
            for source in hidden_timeline:
                action=cue_menu.addAction(source.icon(),source.toolTip())
                action.setEnabled(source.isEnabled())
                action.triggered.connect(lambda _checked=False, button=source:button.click())
            cue_menu.addSeparator()
            # AI 断句 moved here from its own bar button (2026-10-08).
            cue_menu.addAction('AI 断句 · 选中范围试跑', lambda: page.run_sentence_refine(whole_project=False))
            cue_menu.addAction('AI 断句 · 全工程执行', lambda: page.run_sentence_refine(whole_project=True))
            retry = cue_menu.addAction('AI 断句 · 仅重试失败范围', lambda: page.run_sentence_refine(whole_project=False, retry_failed=True))
            retry.setEnabled(bool(page.project and (page.project.studio_state.get('ai_sentence_refine') or {}).get('failed_cue_ids')))
            cancel = cue_menu.addAction('取消本次 AI 断句', page.cancel_sentence_refine)
            worker = getattr(page, '_refine_worker', None)
            cancel.setEnabled(bool(worker is not None and worker.isRunning()))
            cue_menu.addSeparator();cue_menu.addAction('所有字幕操作…',page._show_cue_more_menu)
        cue_menu.aboutToShow.connect(update_cue_menu)
        page.cue_more_button.clicked.disconnect()
        page.cue_more_button.setMenu(cue_menu)
        page.cue_more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        timeline_toolbar.removeWidget(page.position_label);page.position_label.hide()
        # Stripped groups leave empty dividers; one delimiter at each side of
        # transport is enough and avoids isolated vertical lines.
        for i in reversed(range(timeline_toolbar.count())):
            widget=timeline_toolbar.itemAt(i).widget()
            if isinstance(widget,QFrame) and not isinstance(widget,QLabel):
                timeline_toolbar.removeWidget(widget);widget.hide()
        timeline_toolbar.insertStretch(timeline_toolbar.indexOf(page.cue_more_button)+1,1)
        timeline_toolbar.setSpacing(4)
        page._timeline_command_layout = timeline_toolbar
        for index in range(timeline_toolbar.count()):
            widget = timeline_toolbar.itemAt(index).widget()
            if isinstance(widget, QPushButton):
                widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            if isinstance(widget, QCheckBox):
                widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        bind_text(page.waveform_toggle, '波形')
        bind_text(page.follow_playhead_toggle, '跟随')
        from .studio_toolbar_layout import install_command_groups
        install_command_groups(page,timeline_layout,timeline_toolbar,transport_start,view_start,
                               toggles_start=page.waveform_toggle, output_start=page.save_frame_button)
        page.timeline = WaveformTimeline()
        page.timeline.interaction_changed.connect(
            page._resource_governor.set_dragging
        )
        page.timeline.cue_selected.connect(page._timeline_cue_clicked)
        page.timeline.subtitle_visibility_changed.connect(page._subtitle_visibility_changed)
        page.timeline.subtitle_lock_changed.connect(page._schedule_autosave)
        page.timeline.selection_changed.connect(page._timeline_selection_changed)
        page.timeline.group_move_committed.connect(page._move_selected_clip_group)
        page.timeline.group_copy_committed.connect(page._copy_selected_clip_group)
        page.timeline.selection_count_changed.connect(lambda n:bind_text(page.clip_selection_count,'已选 {count} 个片段',count=n) if n else page.clip_selection_count.clear())
        from .studio_transition_ui import show_properties
        page.timeline.transition_selected.connect(lambda key:show_properties(page,key))
        from .timeline_scrub import TimelineScrub
        page._timeline_scrub = TimelineScrub(page)
        page.timeline.seek_requested.connect(page._timeline_scrub.request)
        page.timeline.scrub_finished.connect(page._timeline_scrub.finish)
        page.timeline.snap_changed.connect(page.snap_toggle.setChecked)
        from .studio_timing_preview import CueTimingPreview
        page._cue_timing_preview = CueTimingPreview(page)
        page.timeline.timing_edit_started.connect(page._cue_timing_preview.start)
        page.timeline.timing_preview_changed.connect(page._cue_timing_preview.update)
        page.timeline.timing_edit_committed.connect(lambda values: page.cue_controller.commit_timeline_edit(values))
        page.timeline.timing_edit_finished.connect(page._cue_timing_preview.finish)
        page.timeline.speaker_changed.connect(page._timeline_speaker_changed)
        page.timeline.context_menu_requested.connect(page._show_timeline_menu)
        page.timeline.razor_split_requested.connect(page._split_at)
        page.timeline.merge_pair_requested.connect(page._merge_pair_clicked)
        page.timeline.video_razor_requested.connect(page._razor_video_at)
        page.timeline.video_clip_razor_requested.connect(page._razor_video_clip_at)
        page.timeline.edit_blocked.connect(page.save_state.setText)
        page.timeline.video_lock_toggled.connect(page._toggle_video_lock)
        page.timeline.video_track_action_requested.connect(page._video_track_action)
        page.timeline.audio_track_action_requested.connect(page._audio_track_action)
        from .studio_track_delete import delete_track, track_menu
        page.timeline.track_delete_requested.connect(lambda kind,track_id:delete_track(page,kind,track_id))
        page.timeline.track_menu_requested.connect(lambda kind,track_id,pos:track_menu(page,kind,track_id,pos))
        page.timeline.video_track_menu_requested.connect(page._show_video_track_menu)
        page.timeline.video_clip_selected.connect(page._video_clip_selected)
        page.timeline.video_clip_move_committed.connect(page._video_clip_move_committed)
        page.timeline.video_track_reorder_requested.connect(page._video_track_reorder_to)
        page.timeline.video_clip_reassign_committed.connect(page._video_clip_reassign_committed)
        page.timeline.video_segment_lift_requested.connect(page._video_segment_lift_requested)
        page.timeline.video_track_swap_requested.connect(page._video_track_swap_requested)
        page.timeline.video_clip_trim_committed.connect(page._video_clip_trim_committed)
        page.timeline.candidate_clicked.connect(page._on_candidate_clicked)
        page.highlight_panel.preview_requested.connect(lambda _flag: page._on_candidate_clicked(page.highlight_panel.current_id()))
        page.highlight_panel.add_to_bin_requested.connect(lambda cue_id: page._set_candidate_status(cue_id, "accepted"))
        page.highlight_panel.ignore_requested.connect(lambda cue_id: page._set_candidate_status(cue_id, "ignored"))
        page.highlight_panel.remove_from_bin_requested.connect(page._remove_candidate_from_bin)
        page.highlight_panel.candidate_move_requested.connect(page._move_candidate_in_bin)
        page.highlight_panel.clear_bin_requested.connect(page._clear_candidate_bin)
        page.highlight_panel.generate_requested.connect(page._generate_highlight_edit)
        page.highlight_panel.restore_requested.connect(page._restore_full_sequence)
        page.highlight_panel.analyze_requested.connect(page._analyze_highlights)
        page.highlight_panel.cancel_requested.connect(page._cancel_highlight_analysis)
        page.highlight_panel.xml_selected.connect(page._import_danmaku_xml)
        page.highlight_panel.xml_unbind_requested.connect(page._unbind_danmaku_xml)
        page.highlight_panel.add_mark_in_out_requested.connect(page._add_io_candidate)
        # 四十四轮：自动剪口播气口。
        page.highlight_panel.autocut_detect_requested.connect(page._detect_autocut_silence)
        page.highlight_panel.autocut_apply_requested.connect(page._apply_autocut)
        page.highlight_panel.autocut_cancel_requested.connect(page._cancel_autocut)
        page.highlight_panel.autocut_preview_requested.connect(page._preview_autocut_seam)
        page.timeline.text_edit_committed.connect(page._timeline_text_edited)
        page.waveform_toggle.toggled.connect(page.timeline.set_waveform_visible)
        timeline_layout.addWidget(page.timeline, 1)
        timeline_host.setMinimumHeight(260)
        page.workspace_splitter.addWidget(timeline_host)
        page.workspace_splitter.setStretchFactor(0, 3)
        page.workspace_splitter.setStretchFactor(1, 2)
        page.workspace_splitter.setSizes([560, 380])
        page.workspace_host = QWidget(page)
        workspace_layers = QStackedLayout(page.workspace_host)
        workspace_layers.setContentsMargins(0, 0, 0, 0)
        workspace_layers.setStackingMode(QStackedLayout.StackingMode.StackAll)
        workspace_layers.addWidget(page.workspace_splitter)
        outer.addWidget(page.workspace_host, 1)
        page.export_workspace = None

        page.studio_empty = QFrame(page.workspace_host)
        page.studio_empty.setObjectName("studioEmptyState")
        empty_layout = QVBoxLayout(page.studio_empty)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        page.project_library_scroll = QScrollArea()
        page.project_library_scroll.setObjectName("projectLibraryScroll")
        page.project_library_scroll.setWidgetResizable(True)
        page.project_library_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page.project_library_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        library_page = QWidget()
        library_page.setObjectName("projectLibraryPage")
        page.project_library_scroll.viewport().setObjectName("projectLibraryViewport")
        library_layout = QVBoxLayout(library_page)
        library_layout.setContentsMargins(42, 24, 42, 48)
        library_layout.setSpacing(16)
        page.project_library_scroll.setWidget(library_page)
        empty_layout.addWidget(page.project_library_scroll)

        # Brand/header area mirrors the selected Project Library reference:
        # product identity first, then the resume action and recent projects.
        page.project_library_header = QFrame()
        page.project_library_header.setObjectName("projectLibraryHeader")
        page.project_library_header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_layout = QVBoxLayout(page.project_library_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(14)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        from .main_ui_branding import HeaderMascot
        page.project_library_mascot = HeaderMascot(full_artwork=True)
        page.project_library_mascot.setParent(page.project_library_header)
        page.project_library_mascot.hide()
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        page.project_library_brand = QLabel("工程库")
        page.project_library_brand.setObjectName("projectLibraryBrand")
        brand_text.addWidget(page.project_library_brand)
        page.project_library_brand_meta = QLabel("继续编辑，或开始新的字幕创作。")
        page.project_library_brand_meta.setObjectName("projectLibraryBrandMeta")
        brand_text.addWidget(page.project_library_brand_meta)
        brand_row.addLayout(brand_text, 0)
        brand_row.addStretch(1)
        header_actions = QWidget()
        header_actions.setObjectName("projectLibraryHeaderActions")
        header_actions.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        header_actions_layout = QHBoxLayout(header_actions)
        header_actions_layout.setContentsMargins(0, 0, 0, 0)
        header_actions_layout.setSpacing(10)
        page.project_import_button = QPushButton("导入工程")
        page.project_import_button.setObjectName("hubToolbarButton")
        install_themed_icon(page.project_import_button, "fa5s.folder-open")
        page.project_import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.project_import_button.setMinimumHeight(42)
        page.project_import_button.setMinimumWidth(118)
        page.project_import_button.clicked.connect(page.open_project_dialog)
        header_actions_layout.addWidget(page.project_import_button)
        page.project_new_button = QPushButton("新建工程")
        page.project_new_button.setObjectName("hubPrimary")
        install_themed_icon(page.project_new_button, "fa5s.file-video", "on_accent")
        page.project_new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.project_new_button.setMinimumHeight(42)
        page.project_new_button.setMinimumWidth(132)
        page.project_new_button.clicked.connect(page._create_blank_studio)
        header_actions_layout.addWidget(page.project_new_button)
        brand_row.addWidget(header_actions, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_layout.addLayout(brand_row)
        intro_row = QVBoxLayout()
        intro_row.setSpacing(3)
        page.project_library_eyebrow = QLabel("工程库")
        page.project_library_eyebrow.setObjectName("projectLibraryEyebrow")
        page.project_library_eyebrow.setParent(page.project_library_header)
        page.project_library_eyebrow.hide()
        page.project_library_title = QLabel("继续字幕编辑")
        page.project_library_title.setObjectName("projectLibraryTitle")
        page.project_library_title.setParent(page.project_library_header)
        page.project_library_title.hide()
        page.project_library_subtitle = QLabel("打开已有工程，继续编辑字幕。")
        page.project_library_subtitle.setObjectName("projectLibrarySubtitle")
        page.project_library_subtitle.setParent(page.project_library_header)
        page.project_library_subtitle.hide()
        library_layout.addWidget(page.project_library_header)

        page.resume_hero = QFrame()
        page.resume_hero.setObjectName("resumeProjectCard")
        page.resume_hero.setMinimumHeight(280)
        page.resume_hero.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        resume_layout = QHBoxLayout(page.resume_hero)
        resume_layout.setContentsMargins(22, 16, 16, 16)
        resume_layout.setSpacing(18)
        page.resume_info = QFrame()
        page.resume_info.setObjectName("resumeProjectInfo")
        page.resume_info.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        page.resume_info.setMinimumWidth(260)
        resume_info_layout = QVBoxLayout(page.resume_info)
        resume_info_layout.setContentsMargins(8, 8, 8, 8)
        resume_info_layout.setSpacing(12)
        # Center the copy beside the cover instead of leaving a gap under it.
        resume_info_layout.addStretch(1)
        page.resume_eyebrow = QLabel("最近编辑")
        page.resume_eyebrow.setObjectName("resumeProjectEyebrow")
        resume_info_layout.addWidget(page.resume_eyebrow)
        page.resume_title = QLabel("还没有打开过工程")
        page.resume_title.setObjectName("resumeProjectTitle")
        page.resume_title.setWordWrap(True)
        page.resume_title.setMinimumHeight(44)
        resume_info_layout.addWidget(page.resume_title)
        page.resume_meta = QLabel("导入视频或打开 .2byteproj，开始你的第一批字幕。")
        page.resume_meta.setObjectName("resumeProjectMeta")
        page.resume_meta.setWordWrap(True)
        resume_info_layout.addWidget(page.resume_meta)
        # Real project state as a semantic pill; the source file stays plain text.
        resume_status_row = QHBoxLayout()
        resume_status_row.setSpacing(10)
        page.resume_status_pill = QLabel("")
        page.resume_status_pill.setObjectName("resumeProjectStatusPill")
        page.resume_status_pill.hide()
        resume_status_row.addWidget(page.resume_status_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        page.resume_status = QLabel("等待开始")
        page.resume_status.setObjectName("resumeProjectStatus")
        page.resume_status.setWordWrap(True)
        resume_status_row.addWidget(page.resume_status, 1)
        resume_info_layout.addLayout(resume_status_row)
        resume_actions = QHBoxLayout()
        resume_actions.setSpacing(8)
        page.resume_continue_button = QPushButton("继续编辑")
        page.resume_continue_button.setObjectName("hubPrimary")
        install_themed_icon(page.resume_continue_button, "fa5s.play", "on_accent")
        page.resume_continue_button.setEnabled(False)
        page.resume_continue_button.clicked.connect(lambda: page._open_recent_project_card(getattr(page, "_resume_target", "")))
        resume_actions.addWidget(page.resume_continue_button)
        page.resume_details_button = QPushButton("查看详情")
        page.resume_details_button.setObjectName("hubSecondary")
        page.resume_details_button.setEnabled(False)
        page.resume_details_button.clicked.connect(lambda: page._show_recent_project_details(getattr(page, "_resume_target", "")))
        resume_actions.addWidget(page.resume_details_button)
        resume_actions.addStretch(1)
        resume_info_layout.addLayout(resume_actions)
        resume_info_layout.addStretch(1)
        resume_layout.addWidget(page.resume_info, 1)
        page.resume_preview = QFrame()
        page.resume_preview.setObjectName("resumeProjectPreview")
        page.resume_preview.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        preview_grid = QGridLayout(page.resume_preview)
        preview_grid.setContentsMargins(0, 0, 0, 0)
        preview_grid.setSpacing(0)
        page.resume_preview_image = CoverPreviewLabel()
        page.resume_preview_image.setObjectName("resumeProjectPreviewImage")
        page.resume_preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.resume_preview_image.set_corner_radius(10)
        page.resume_preview_image.set_fit_mode("contain")
        page.resume_preview_image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        preview_grid.addWidget(page.resume_preview_image, 0, 0)
        resume_layout.addWidget(page.resume_preview, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        library_layout.addWidget(page.resume_hero)

        library_toolbar = QHBoxLayout()
        library_toolbar.setSpacing(10)
        page.all_projects_heading = QLabel("最近工程")
        page.all_projects_heading.setObjectName("projectLibrarySectionTitle")
        page.all_projects_heading.setAlignment(Qt.AlignmentFlag.AlignLeft)
        library_toolbar.addWidget(page.all_projects_heading)
        library_toolbar.addStretch(1)
        # 五十二轮：排序/搜索/视图切换统一为一个 toolbar——同高(40)、同圆角(10)、
        # 同基线，整组不再高低不齐。
        page.project_sort = StudioComboBox()
        page.project_sort.setObjectName("projectSort")
        page.project_sort.setMinimumHeight(40)
        page.project_sort.setMinimumWidth(128)
        page.project_sort.addItem("最近使用", "recent")
        page.project_sort.addItem("最近创建", "created")
        page.project_sort.addItem("名称", "name")
        page.project_sort.currentIndexChanged.connect(lambda _index: page._refresh_studio_empty_state())
        library_toolbar.addWidget(page.project_sort)
        page.project_search = QLineEdit()
        page.project_search.setObjectName("projectLibrarySearch")
        bind_text(page.project_search, '搜索工程...', property='placeholderText')
        page.project_search.setClearButtonEnabled(True)
        page.project_search.setMinimumHeight(40)
        page.project_search.setMaximumWidth(280)
        search_action = page.project_search.addAction(_icon("fa5s.search"), QLineEdit.ActionPosition.LeadingPosition)
        install_themed_icon(search_action, "fa5s.search", "muted")
        page.project_search.textChanged.connect(lambda _text: page._refresh_studio_empty_state())
        library_toolbar.addWidget(page.project_search)
        page.project_view_group = QButtonGroup(page)
        page.project_view_group.setExclusive(True)
        view_switcher = QFrame()
        view_switcher.setObjectName("projectViewSwitcher")
        view_switcher_layout = QHBoxLayout(view_switcher)
        view_switcher_layout.setContentsMargins(2, 2, 2, 2)
        view_switcher_layout.setSpacing(2)
        page.project_card_view_button = QToolButton()
        page.project_card_view_button.setObjectName("projectViewButton")
        # 五十二轮：视图切换图标走 themed role 注册（随主题重着色）。此前
        # _icon() 在创建时烘焙主题色、切主题不刷新——暗色 hub 下残留深色
        # 图标≈不可见（用户"卡片/列表切换图标几乎看不见"根因）。
        install_themed_icon(page.project_card_view_button, "fa5s.th-large")
        bind_text(page.project_card_view_button, '卡片视图', property='toolTip')
        page.project_card_view_button.setCheckable(True)
        page.project_card_view_button.clicked.connect(lambda: page._set_project_library_view("card"))
        page.project_view_group.addButton(page.project_card_view_button)
        view_switcher_layout.addWidget(page.project_card_view_button)
        page.project_list_view_button = QToolButton()
        page.project_list_view_button.setObjectName("projectViewButton")
        install_themed_icon(page.project_list_view_button, "fa5s.list")
        bind_text(page.project_list_view_button, '紧凑列表视图', property='toolTip')
        page.project_list_view_button.setCheckable(True)
        page.project_list_view_button.clicked.connect(lambda: page._set_project_library_view("list"))
        page.project_view_group.addButton(page.project_list_view_button)
        view_switcher_layout.addWidget(page.project_list_view_button)
        library_toolbar.addWidget(view_switcher)
        page.project_view_switcher = view_switcher
        page.project_manage_button = QPushButton("管理")
        page.project_manage_button.setObjectName("hubToolbarButton")
        install_themed_icon(page.project_manage_button, "fa5s.tasks")
        page.project_manage_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.project_manage_button.setMinimumHeight(40)
        page.project_manage_button.setCheckable(True)
        bind_text(page.project_manage_button, '批量选择工程，可一键清理空工程', property='toolTip')
        page.project_manage_button.clicked.connect(
            lambda checked=False: page._set_library_manage_mode(bool(checked))
        )
        library_toolbar.addWidget(page.project_manage_button)
        library_layout.addLayout(library_toolbar)

        # Batch-manage bar: visible only in selection mode. Selection is keyed
        # by resolved project path so sort/search stays live while managing.
        page.project_manage_bar = QFrame()
        page.project_manage_bar.setObjectName("libraryManageBar")
        manage_bar_layout = QHBoxLayout(page.project_manage_bar)
        manage_bar_layout.setContentsMargins(16, 10, 16, 10)
        manage_bar_layout.setSpacing(8)
        page.project_manage_count_label = QLabel("已选 0 项")
        page.project_manage_count_label.setObjectName("libraryManageCount")
        manage_bar_layout.addWidget(page.project_manage_count_label)
        manage_bar_layout.addStretch(1)
        page.project_select_empty_button = QPushButton("选中空工程")
        page.project_select_empty_button.setObjectName("libraryManageAction")
        bind_text(page.project_select_empty_button, '选中 0 条字幕且无源媒体的工程', property='toolTip')
        page.project_select_empty_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.project_select_empty_button.clicked.connect(lambda: page._library_select_empty_projects())
        manage_bar_layout.addWidget(page.project_select_empty_button)
        page.project_select_all_button = QPushButton("全选")
        page.project_select_all_button.setObjectName("libraryManageAction")
        page.project_select_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.project_select_all_button.clicked.connect(lambda: page._library_select_displayed(select_all=True))
        manage_bar_layout.addWidget(page.project_select_all_button)
        page.project_delete_button = QPushButton("删除所选")
        page.project_delete_button.setObjectName("libraryManageDanger")
        install_themed_icon(page.project_delete_button, "fa5s.trash-alt")
        page.project_delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.project_delete_button.setEnabled(False)
        page.project_delete_button.clicked.connect(lambda: page._delete_selected_library_projects())
        manage_bar_layout.addWidget(page.project_delete_button)
        page.project_manage_exit_button = QPushButton("完成")
        page.project_manage_exit_button.setObjectName("libraryManageAction")
        page.project_manage_exit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.project_manage_exit_button.clicked.connect(lambda: page._set_library_manage_mode(False))
        manage_bar_layout.addWidget(page.project_manage_exit_button)
        page._library_manage_esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), page.project_manage_bar)
        page._library_manage_esc_shortcut.activated.connect(lambda: page._set_library_manage_mode(False))
        page.project_manage_bar.hide()
        library_layout.addWidget(page.project_manage_bar)

        page.all_projects_stack = QStackedWidget()
        page.all_projects_stack.setObjectName("projectLibraryViewStack")
        page.all_projects_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        page.all_projects_stack.setMinimumHeight(360)
        page.all_projects_host = QWidget()
        page.all_projects_host.setObjectName("projectGridHost")
        page.all_projects_layout = QGridLayout(page.all_projects_host)
        page.all_projects_layout.setContentsMargins(0, 0, 0, 0)
        page.all_projects_layout.setHorizontalSpacing(24)
        page.all_projects_layout.setVerticalSpacing(16)
        page.all_projects_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        page.all_projects_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        page.all_projects_stack.addWidget(page.all_projects_host)
        page.project_list_host = QWidget()
        page.project_list_host.setObjectName("projectListHost")
        page.project_list_layout = QVBoxLayout(page.project_list_host)
        page.project_list_layout.setContentsMargins(0, 0, 0, 0)
        page.project_list_layout.setSpacing(8)
        page.project_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        page.all_projects_stack.addWidget(page.project_list_host)
        page.all_projects_stack.setCurrentIndex(0)
        page.project_card_view_button.setChecked(True)
        library_layout.addWidget(page.all_projects_stack)
        page.project_library_empty = QLabel("没有找到匹配的工程")
        page.project_library_empty.setObjectName("projectLibrarySubtitle")
        page.project_library_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.project_library_empty.hide()
        library_layout.addWidget(page.project_library_empty)
        page.hub_loading_label = QLabel()
        page.hub_loading_label.setObjectName("projectLibrarySubtitle")
        page.hub_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.hub_loading_label.hide()
        library_layout.addWidget(page.hub_loading_label)
        library_layout.addStretch(1)
        workspace_layers.addWidget(page.studio_empty)
        workspace_layers.setCurrentWidget(page.studio_empty)
        page.project_library_scroll.viewport().installEventFilter(page)
        page.studio_empty.show()
        page.studio_empty.raise_()
        QTimer.singleShot(0, page._refresh_studio_empty_state)
        for field, visible in page._editor_field_visibility.items():
            page._set_editor_field_visible(field, visible)
        QTimer.singleShot(0, page._update_editor_compactness)
        QTimer.singleShot(0, page._update_cue_table_layout)
        from .design.presentation import prepare_controls, field_width
        prepare_controls(page)
        for editor in (page.project_search,):
            field_width(editor, 'preferred', size='compact')
        QTimer.singleShot(0, page._update_context_tab_labels)

    def _cue_list_panel(self) -> QFrame:
        page = self.page
        CueBadgeDelegate = self._cue_badge_delegate_type
        CueIndexDelegate = self._cue_index_delegate_type
        CueTableModel = self._cue_table_model_type
        panel = QFrame()
        panel.setObjectName("cueListPanel")
        # 1920px at 175% DPI is only ~1097 logical px. Keep all three major
        # regions visible while retaining the normal 380px list width at 100%.
        panel.setMinimumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 9, 8, 8)
        layout.setSpacing(7)
        title = QLabel("字幕列表")
        title.setObjectName("sectionTitle")
        title_row = QHBoxLayout()
        title_row.addWidget(title, 1)
        page.cue_proofread_button = QPushButton("AI 校对")
        page.cue_proofread_button.setObjectName("studioButton")
        install_themed_icon(page.cue_proofread_button, "fa5s.spell-check", "secondary")
        bind_text(page.cue_proofread_button, 'AI 校对')
        bind_text(page.cue_proofread_button, '打开当前工程的 AI 词库校对，勾选建议后应用', property='toolTip')
        page.cue_proofread_button.clicked.connect(page.glossary_proofread_requested.emit)
        title_row.addWidget(page.cue_proofread_button)
        layout.addLayout(title_row)
        # 四十二轮：后台识别状态芯片——识别启动后弹窗关闭，运行/完成/失败
        # 状态与取消按钮都落在这里，用户可以继续看视频编辑工程。
        page.recognition_chip = QFrame()
        page.recognition_chip.setObjectName("contextCard")
        chip_layout = QHBoxLayout(page.recognition_chip)
        chip_layout.setContentsMargins(10, 6, 8, 6)
        chip_layout.setSpacing(8)
        page.recognition_chip_label = QLabel("识别中")
        page.recognition_chip_label.setObjectName("studioSaveState")
        page.recognition_chip_label.setWordWrap(True)
        chip_layout.addWidget(page.recognition_chip_label, 1)
        page.recognition_cancel_button = QPushButton("取消识别")
        page.recognition_cancel_button.setObjectName("studioButton")
        page.recognition_cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(page.recognition_cancel_button, '安全取消当前识别任务（在阶段边界退出）', property='toolTip')
        page.recognition_cancel_button.clicked.connect(page.recognition_cancel_requested.emit)
        chip_layout.addWidget(page.recognition_cancel_button)
        page.recognition_chip.hide()
        layout.addWidget(page.recognition_chip)
        filters = QGridLayout()
        filters.setHorizontalSpacing(4)
        filters.setVerticalSpacing(4)
        page.cue_filter_group = QButtonGroup(page)
        page.cue_filter_group.setExclusive(True)
        page.cue_filter_buttons: dict[str, QPushButton] = {}
        for index, (key, caption) in enumerate(
            (("all", "全部"), ("priority", "建议确认"), ("critical", "需要检查"))
        ):
            button = QPushButton(caption)
            button.setObjectName("filterChip")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=key: page._set_cue_filter(value))
            page.cue_filter_group.addButton(button)
            page.cue_filter_buttons[key] = button
            filters.addWidget(button, index // 2, index % 2)
        page.cue_filter_buttons["all"].setChecked(True)
        page.review_entry_button = QPushButton("▶ 开始审核")
        page.review_entry_button.setObjectName("reviewEntryButton")
        bind_text(page.review_entry_button, '进入优先审核；快捷键 R', property='toolTip')
        page.review_entry_button.clicked.connect(lambda: page._set_review_mode(not page._review_mode))
        filters.addWidget(page.review_entry_button, 1, 1)
        layout.addLayout(filters)
        page.continuous_review_toggle = QCheckBox("连续审核")
        bind_text(page.continuous_review_toggle, '播放当前审核字幕前后语境，并在片段结束后暂停', property='toolTip')
        page.continuous_review_toggle.toggled.connect(page._set_continuous_review)
        layout.addWidget(page.continuous_review_toggle)
        search_row = QHBoxLayout()
        page.cue_search = QLineEdit()
        page.cue_search.setObjectName("cueSearch")
        bind_text(page.cue_search, '搜索文本、说话人...', property='placeholderText')
        page.cue_search.setClearButtonEnabled(True)
        page.cue_search.textChanged.connect(lambda value: page.cue_model.set_query(value))
        search_row.addWidget(page.cue_search, 1)
        filter_button = page._tool_button("fa5s.filter", "筛选当前字幕列表", page._show_filter_menu)
        page.cue_filter_button = filter_button
        search_row.addWidget(filter_button)
        page.cue_view_button = page._tool_button("fa5s.table", "表格视图 · 关闭后按双行阅读显示（时间、说话人、状态在上，句子在下）",
                                                  lambda: None)
        page.cue_view_button.setCheckable(True)
        search_row.addWidget(page.cue_view_button)
        layout.addLayout(search_row)

        page.cue_table = ResponsiveCueTableView()
        page.cue_table.setObjectName("cueTable")
        page.cue_model = CueTableModel(parent=page.cue_table)
        page.cue_table.setModel(page.cue_model)
        page.cue_model.text_edit_requested.connect(
            lambda cue_id, text: page._timeline_text_edited(cue_id, False, text)
        )
        page.cue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        page.cue_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        page.cue_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        page.cue_table.setTabKeyNavigation(True)
        page.cue_table.setAlternatingRowColors(True)
        page.cue_table.setShowGrid(False)
        page.cue_table.verticalHeader().hide()
        page.cue_table.verticalHeader().setDefaultSectionSize(42)
        page.cue_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        badge_delegate = CueBadgeDelegate(page.cue_table)
        page.cue_table.setItemDelegateForColumn(2, badge_delegate)
        page.cue_table.setItemDelegateForColumn(4, badge_delegate)
        page.cue_table.setItemDelegateForColumn(0, CueIndexDelegate(page.cue_table))
        page.cue_table.clicked.connect(page._table_activated)
        page.cue_table.selectionModel().selectionChanged.connect(
            page._cue_table_selection_changed
        )
        page.cue_table.clicked.connect(page._cue_table_clicked)
        page.cue_table.selectionModel().currentChanged.connect(
            page._cue_table_current_changed
        )
        page.cue_table.first_selected_rows_painted.connect(
            page._selection_first_visual
        )
        page.cue_table.doubleClicked.connect(page._begin_list_inline_edit)
        header = page.cue_table.horizontalHeader()
        for column, width in ((0, 36), (1, 88), (2, 66), (4, 58)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            page.cue_table.setColumnWidth(column, width)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        from .studio_cue_table import CueReadingDelegate
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QStyledItemDelegate
        page.cue_reading_delegate = CueReadingDelegate(page.cue_table)
        page._cue_text_delegate = QStyledItemDelegate(page.cue_table)

        def set_cue_list_view(mode: str, *, remember: bool = True) -> None:
            reading = mode != "table"
            table = page.cue_table
            table.reading = reading
            table.setItemDelegateForColumn(3, page.cue_reading_delegate if reading else page._cue_text_delegate)
            table.horizontalHeader().setVisible(not reading)
            table.setAlternatingRowColors(not reading)
            table.setWordWrap(False)
            table.verticalHeader().setDefaultSectionSize(
                CueReadingDelegate.row_height(table.font()) if reading else 42)
            table.setProperty("cueView", "reading" if reading else "table")
            table.style().unpolish(table)
            table.style().polish(table)
            table.apply_responsive_layout()
            button = page.cue_view_button
            button.blockSignals(True)
            button.setChecked(not reading)
            button.blockSignals(False)
            if remember:
                QSettings("2ByteASR", "2ByteASR").setValue("studio/cue_list_view", "reading" if reading else "table")
            table.viewport().update()

        page._set_cue_list_view = set_cue_list_view
        page.cue_view_button.toggled.connect(lambda checked: set_cue_list_view("table" if checked else "reading"))
        set_cue_list_view(str(QSettings("2ByteASR", "2ByteASR").value("studio/cue_list_view", "reading") or "reading"),
                          remember=False)
        page.cue_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        layout.addWidget(page.cue_table, 1)
        page.cue_zero_state = QFrame()
        page.cue_zero_state.setObjectName("studioCueZeroState")
        zero_layout = QVBoxLayout(page.cue_zero_state)
        zero_layout.setContentsMargins(18, 24, 18, 24)
        zero_layout.setSpacing(9)
        zero_layout.addStretch(1)
        zero_title = QLabel("暂无字幕")
        zero_title.setObjectName("sectionTitle")
        zero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zero_layout.addWidget(zero_title)
        zero_note = QLabel("可使用当前识别方案生成字幕，或导入已有字幕文件。")
        zero_note.setObjectName("studioSaveState")
        zero_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zero_note.setWordWrap(True)
        zero_layout.addWidget(zero_note)
        page.cue_recognize_button = QPushButton("识别字幕")
        page.cue_recognize_button.setObjectName("studioPrimary")
        page.cue_recognize_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.cue_recognize_button.clicked.connect(page._open_recognition_sheet)
        zero_layout.addWidget(page.cue_recognize_button)
        # 四十三轮：识别期间"暂无字幕"区显示运行状态（用户点名——顶部芯片
        # 太难看到）。含取消与"查看详细进度"（跳主页进度页，可返回 Studio）。
        page.recognition_zero_card = QFrame()
        page.recognition_zero_card.setObjectName("contextCard")
        zero_recognition_layout = QVBoxLayout(page.recognition_zero_card)
        zero_recognition_layout.setContentsMargins(12, 10, 12, 10)
        zero_recognition_layout.setSpacing(7)
        page.recognition_zero_label = QLabel("识别中")
        page.recognition_zero_label.setObjectName("studioSaveState")
        page.recognition_zero_label.setWordWrap(True)
        zero_recognition_layout.addWidget(page.recognition_zero_label)
        zero_recognition_row = QHBoxLayout()
        page.recognition_zero_cancel = QPushButton("取消识别")
        page.recognition_zero_cancel.setObjectName("studioButton")
        page.recognition_zero_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(page.recognition_zero_cancel, '安全取消当前识别任务（在阶段边界退出）', property='toolTip')
        page.recognition_zero_cancel.clicked.connect(page.recognition_cancel_requested.emit)
        zero_recognition_row.addWidget(page.recognition_zero_cancel)
        page.recognition_zero_detail = QPushButton("查看详细进度")
        page.recognition_zero_detail.setObjectName("studioButton")
        page.recognition_zero_detail.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(page.recognition_zero_detail, '跳转到主页的识别进度页查看阶段与日志，可返回 Studio', property='toolTip')
        page.recognition_zero_detail.clicked.connect(page.recognition_detail_requested.emit)
        zero_recognition_row.addWidget(page.recognition_zero_detail)
        zero_recognition_layout.addLayout(zero_recognition_row)
        page.recognition_zero_card.hide()
        zero_layout.addWidget(page.recognition_zero_card)
        page.cue_import_subtitles_button = QPushButton("导入 SRT / ASS")
        page.cue_import_subtitles_button.setObjectName("studioButton")
        page.cue_import_subtitles_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.cue_import_subtitles_button.clicked.connect(page._open_subtitle_import_dialog)
        zero_layout.addWidget(page.cue_import_subtitles_button)
        zero_layout.addStretch(1)
        page.cue_zero_state.hide()
        layout.addWidget(page.cue_zero_state, 1)
        page.cue_empty_state = QLabel("没有需要检查的字幕\n当前优先审核队列已处理完成。")
        page.cue_empty_state.setObjectName("studioEmptyHint")
        page.cue_empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.cue_empty_state.setWordWrap(True)
        page.cue_empty_state.hide()
        layout.addWidget(page.cue_empty_state, 1)

        footer = QHBoxLayout()
        footer.addWidget(QLabel("跳转"))
        page.jump_spin = QSpinBox()
        page.jump_spin.setRange(1, 1)
        page.jump_spin.setFixedWidth(70)
        page.jump_spin.editingFinished.connect(page._jump_to_row)
        footer.addWidget(page.jump_spin)
        page.cue_total_label = QLabel("/ 0")
        page.cue_total_label.setObjectName("studioSaveState")
        footer.addWidget(page.cue_total_label)
        footer.addStretch(1)
        previous = QPushButton("上一条")
        previous.setObjectName("studioButton")
        previous.clicked.connect(lambda: page._step_cue(-1))
        footer.addWidget(previous)
        following = QPushButton("下一条")
        following.setObjectName("studioButton")
        following.clicked.connect(lambda: page._step_cue(1))
        footer.addWidget(following)
        more = page._tool_button("fa5s.ellipsis-h", "更多字幕列表操作", page._show_cue_more_menu)
        footer.addWidget(more)
        layout.addLayout(footer)
        return panel

    def _video_transform_panel(self) -> QWidget:
        page = self.page
        panel = QWidget()
        panel.setObjectName("videoInspector")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 16)
        layout.setSpacing(9)
        title = QLabel("视频")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        page.video_transform_selection_label = QLabel("在时间线选择一个视频片段")
        page.video_transform_selection_label.setObjectName("videoSelectionSummary")
        page.video_transform_selection_label.setWordWrap(True)
        layout.addWidget(page.video_transform_selection_label)
        from .studio_transition_ui import create_inspector
        create_inspector(page,layout)

        motion_box = QGroupBox("运动")
        motion_box.setObjectName("videoInspectorSection")
        grid = QGridLayout(motion_box)
        grid.setContentsMargins(10, 6, 10, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        def spin(name: str, minimum: float, maximum: float, suffix: str = "") -> ScrubDoubleSpinBox:
            # ADR-0005（四十五轮）：数值行支持按住左右拖拽调值（Premiere 逻辑）。
            control = ScrubDoubleSpinBox()
            control.setObjectName(name)
            control.setRange(minimum, maximum)
            control.setDecimals(2)
            control.setSingleStep(1.0)
            control.setSuffix(suffix)
            # 五十轮（用户反馈）：XY/缩放/锚点全部数值控件统一宽度——
            # 按各自数值域自适应 sizeHint 会导致同行控件参差。
            control.setFixedWidth(96)
            control.valueChanged.connect(page._video_transform_control_preview)
            control.editingFinished.connect(page._video_transform_control_committed)
            return control

        controls = (
            ("位置 X", "video_position_x", -400.0, 500.0, "%"),
            ("位置 Y", "video_position_y", -400.0, 500.0, "%"),
            ("缩放 X", "video_scale_x", 1.0, 2000.0, "%"),
            ("缩放 Y", "video_scale_y", 1.0, 2000.0, "%"),
            ("旋转", "video_rotation", -360.0, 360.0, "°"),
            ("不透明度", "video_opacity", 0.0, 100.0, "%"),
            ("锚点 X", "video_anchor_x", 0.0, 100.0, "%"),
            ("锚点 Y", "video_anchor_y", 0.0, 100.0, "%"),
        )
        page.video_transform_controls = []

        page._video_axis_pairs = []

        def add_pair(row: int, first: int, second: int, middle: QWidget | None = None) -> None:
            """X and Y side by side; a narrow drawer stacks Y under X."""
            label_a, name_a, min_a, max_a, suffix_a = controls[first]
            grid.addWidget(QLabel(label_a.split()[0]), row, 0)
            pair = QWidget()
            pair.setObjectName("videoAxisPair")
            fields = QGridLayout(pair)
            fields.setContentsMargins(0, 0, 0, 0)
            fields.setHorizontalSpacing(6)
            fields.setVerticalSpacing(6)

            def axis_group(axis: str, control: QWidget, extra: QWidget | None = None) -> QWidget:
                group = QWidget()
                row_layout = QHBoxLayout(group)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)
                label = QLabel(axis); label.setObjectName("videoAxisLabel")
                row_layout.addWidget(label)
                row_layout.addWidget(control)
                if extra is not None:
                    row_layout.addWidget(extra)
                group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                return group

            control_a = spin(name_a, min_a, max_a, suffix_a)
            setattr(page, name_a, control_a)
            page.video_transform_controls.append(control_a)
            label_b, name_b, min_b, max_b, suffix_b = controls[second]
            control_b = spin(name_b, min_b, max_b, suffix_b)
            setattr(page, name_b, control_b)
            page.video_transform_controls.append(control_b)
            group_x = axis_group("X", control_a)
            group_y = axis_group("Y", control_b, middle)
            fields.addWidget(group_x, 0, 0)
            fields.addWidget(group_y, 0, 1)
            fields.setColumnStretch(2, 1)
            grid.addWidget(pair, row, 1)
            page._video_axis_pairs.append((fields, group_x, group_y))

        # 五十轮（用户反馈）：缩放默认等比（链锁 ON），改 X 自动带 Y；按钮可关闭。
        page.video_scale_link = QToolButton()
        page.video_scale_link.setObjectName("videoScaleLink")
        page.video_scale_link.setCheckable(True)
        page.video_scale_link.setChecked(True)
        page.video_scale_link.setFixedSize(24, 24)
        bind_text(page.video_scale_link, '等比缩放：锁定时修改 X/Y 任一值，另一值同步', property='toolTip')
        install_themed_icon(page.video_scale_link, "fa5s.link", "primary")

        def _scale_link_toggled(checked: bool) -> None:
            install_themed_icon(page.video_scale_link, "fa5s.link" if checked else "fa5s.unlink", "primary")

        page.video_scale_link.toggled.connect(_scale_link_toggled)

        add_pair(0, 0, 1)
        add_pair(1, 2, 3, middle=page.video_scale_link)

        def _sync_linked_scale(source: ScrubDoubleSpinBox, target: ScrubDoubleSpinBox) -> None:
            if not page.video_scale_link.isChecked():
                return
            if getattr(page, "_updating_video_transform_ui", False):
                return
            target.blockSignals(True)
            target.setValue(source.value())
            target.blockSignals(False)

        page.video_scale_x.valueChanged.connect(
            lambda _v: _sync_linked_scale(page.video_scale_x, page.video_scale_y)
        )
        page.video_scale_y.valueChanged.connect(
            lambda _v: _sync_linked_scale(page.video_scale_y, page.video_scale_x)
        )
        row = 2
        for index in (4,):
            label, name, minimum, maximum, suffix = controls[index]
            grid.addWidget(QLabel(label), row, 0)
            control = spin(name, minimum, maximum, suffix)
            setattr(page, name, control)
            page.video_transform_controls.append(control)
            single = QWidget()
            single_layout = QHBoxLayout(single)
            single_layout.setContentsMargins(0, 0, 0, 0)
            single_layout.setSpacing(6)
            axis_spacer = QLabel("")
            axis_spacer.setObjectName("videoAxisLabel")
            single_layout.addWidget(axis_spacer)
            single_layout.addWidget(control)
            single_layout.addStretch(1)
            grid.addWidget(single, row, 1)
            row += 1
        # 锚点 X/Y 同行（Premiere 式双值行）。
        add_pair(row, 6, 7)
        row += 1

        def reflow_axis_pairs() -> None:
            """Side by side when the drawer is wide enough; else Y under X.

            Measured from the panel (= drawer viewport) width: the group box
            itself never shrinks below the side-by-side minimum.
            """
            outer = layout.contentsMargins()
            inner = grid.contentsMargins()
            label_column = grid.cellRect(0, 0).width() if grid.cellRect(0, 0).isValid() else 48
            available = (panel.width() - outer.left() - outer.right() - inner.left() - inner.right()
                         - 4 - label_column - grid.horizontalSpacing())
            for fields, group_x, group_y in page._video_axis_pairs:
                needed = group_x.sizeHint().width() + fields.horizontalSpacing() + group_y.sizeHint().width()
                stacked = needed > available
                position = fields.getItemPosition(fields.indexOf(group_y))[:2]
                if stacked and position != (1, 0):
                    fields.removeWidget(group_y)
                    fields.addWidget(group_y, 1, 0)
                elif not stacked and position != (0, 1):
                    fields.removeWidget(group_y)
                    fields.addWidget(group_y, 0, 1)

        class _AxisReflow(QObject):
            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.Resize:
                    QTimer.singleShot(0, reflow_axis_pairs)
                return False

        page._video_axis_reflow = _AxisReflow(panel)
        panel.installEventFilter(page._video_axis_reflow)
        grid.addWidget(QLabel("适配"), row, 0)
        page.video_fit_mode = QComboBox()
        page.video_fit_mode.addItem("完整显示", "contain")
        page.video_fit_mode.addItem("填满画布", "cover")
        page.video_fit_mode.addItem("拉伸", "stretch")
        bind_text(page.video_fit_mode, '按所选方式适配整个画布，并重置位置、缩放与旋转；可撤销。', property='toolTip')
        page.video_fit_mode.activated.connect(page._video_fit_mode_committed)
        grid.addWidget(page.video_fit_mode, row, 1)
        row += 1
        page.video_blend_mode = QComboBox()
        for blend_label, blend_value in (
            ("正常", "normal"),
            ("屏幕", "screen"),
            ("正片叠底", "multiply"),
            ("叠加", "overlay"),
            ("柔光", "softLight"),
            ("线性减淡", "addition"),
        ):
            page.video_blend_mode.addItem(blend_label, blend_value)
        page.video_blend_mode.activated.connect(page._video_effects_control_committed)
        blend_box = QGroupBox("透明度与叠加")
        blend_box.setObjectName("videoInspectorSection")
        blend_layout = QFormLayout(blend_box)
        blend_layout.setContentsMargins(10, 6, 10, 8)
        page.video_opacity = spin('video_opacity', 0., 100., '%')
        page.video_transform_controls.append(page.video_opacity)
        blend_layout.addRow('不透明度', page.video_opacity)
        blend_layout.addRow("混合模式", page.video_blend_mode)
        layout.addWidget(motion_box)
        layout.addWidget(blend_box)

        # ADR-0005（四十五轮）：绿幕抠像（Ultra Key）。
        chroma_box = QGroupBox("绿幕抠像")
        chroma_box.setObjectName("videoInspectorSection")
        chroma_form = QFormLayout(chroma_box)
        chroma_form.setContentsMargins(10, 6, 10, 8)
        page.video_key_enabled = QCheckBox("启用抠像")
        page.video_key_enabled.toggled.connect(page._video_effects_control_committed)
        chroma_form.addRow("", page.video_key_enabled)
        key_color_row = QHBoxLayout()
        page.video_key_color = QPushButton()
        page.video_key_color.setFixedSize(44, 24)
        page.video_key_color.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(page.video_key_color, '点击选择键控颜色（默认抠绿）', property='toolTip')
        page.video_key_color.clicked.connect(page._video_key_color_clicked)
        page.video_key_color_hex = QLabel("#00FF00")
        key_color_row.addWidget(page.video_key_color)
        key_color_row.addWidget(page.video_key_color_hex)
        key_color_row.addStretch(1)
        chroma_form.addRow("键控颜色", key_color_row)

        def key_spin(name: str, maximum: float) -> ScrubDoubleSpinBox:
            control = ScrubDoubleSpinBox()
            control.setObjectName(name)
            control.setRange(0.0, maximum)
            control.setDecimals(0)
            control.setSingleStep(1.0)
            control.setSuffix(" %")
            control.valueChanged.connect(page._video_effects_control_preview)
            control.editingFinished.connect(page._video_effects_control_committed)
            return control

        page.video_key_similarity = key_spin("video_key_similarity", 100.0)
        page.video_key_similarity.setValue(32)
        bind_text(page.video_key_similarity, '颜色距离阈值：越大抠得越狠', property='toolTip')
        chroma_form.addRow("相似度", page.video_key_similarity)
        page.video_key_smoothness = key_spin("video_key_smoothness", 100.0)
        page.video_key_smoothness.setValue(10)
        bind_text(page.video_key_smoothness, '边缘渐变带宽：越大过渡越柔和', property='toolTip')
        chroma_form.addRow("平滑度", page.video_key_smoothness)
        page.video_key_spill = QCheckBox("抑制颜色溢出（边缘去绿边）")
        page.video_key_spill.setChecked(True)
        page.video_key_spill.toggled.connect(page._video_effects_control_committed)
        chroma_form.addRow("", page.video_key_spill)
        page.video_canvas_hint = QLabel("拖动数值快速调节；也可在画面中拖动、缩放片段。")
        page.video_canvas_hint.setObjectName("contextEmpty")
        page.video_canvas_hint.setWordWrap(True)
        grid.addWidget(page.video_canvas_hint, row, 0, 1, 2)
        page.video_key_hint = QLabel("对叠加素材抠绿幕：选颜色→调相似度；预览即时生效。")
        page.video_key_hint.setObjectName("contextEmpty")
        page.video_key_hint.setWordWrap(True)
        chroma_form.addRow("", page.video_key_hint)
        layout.addWidget(chroma_box)

        audio_box = QGroupBox("声音与混音")
        audio_box.setObjectName("videoInspectorSection")
        audio_layout = QVBoxLayout(audio_box)
        audio_layout.setSpacing(10)
        page.video_audio_enabled = QCheckBox("此片段启用音频")
        page.video_audio_enabled.toggled.connect(page._video_clip_audio_toggled)
        audio_layout.addWidget(page.video_audio_enabled)
        page.video_audio_solo = QCheckBox("S · Solo / 独听此轨")
        page.video_audio_solo.toggled.connect(page._video_audio_solo_toggled)
        audio_layout.addWidget(page.video_audio_solo)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("混音方式"))
        page.video_audio_mode = QComboBox()
        # 2026-09-06（四图反馈·图二）：全部混音=取消唯一 master，V1/V2 同时出声。
        page.video_audio_mode.addItem("所有轨道混音", "mix_all")
        page.video_audio_mode.addItem("旧版指定声音（兼容）", "manual")
        page.video_audio_mode.activated.connect(page._video_audio_mode_changed)
        mode_row.addWidget(page.video_audio_mode, 1)
        audio_layout.addLayout(mode_row)
        master_row = QHBoxLayout()
        master_row.addWidget(QLabel("旧版指定轨"))
        page.video_audio_master = QComboBox()
        page.video_audio_master.activated.connect(page._video_audio_master_changed)
        master_row.addWidget(page.video_audio_master, 1)
        audio_layout.addLayout(master_row)
        page.video_audio_owner_label = QLabel("当前声音：-")
        page.video_audio_owner_label.setWordWrap(True)
        audio_layout.addWidget(page.video_audio_owner_label)
        layout.addWidget(audio_box)
        # Retain legacy inspector state bindings for old projects, while all
        # user-facing sound operations live on the corresponding A lane.
        audio_box.hide()
        # Defaults for newly applied transitions: secondary, collapsed, last.
        from .studio_transition_ui import create_default_durations
        create_default_durations(page, layout)
        audio_hint = QLabel('声音开关、Solo 和音量请在对应的 A 波形行调整。')
        audio_hint.setWordWrap(True)
        audio_hint.setObjectName('contextEmpty')
        layout.addWidget(audio_hint)
        layout.addStretch(1)
        for control in [
            *page.video_transform_controls, page.video_fit_mode, page.video_audio_enabled, page.video_audio_solo,
            page.video_blend_mode, page.video_key_enabled, page.video_key_color,
            page.video_key_similarity, page.video_key_smoothness, page.video_key_spill,
        ]:
            control.setEnabled(False)
        # Nothing is selected yet: blank fields, not "缩放 1.00%" / "不透明度 0.00%".
        show_placeholders = getattr(page, "_show_video_transform_placeholders", None)
        if callable(show_placeholders):
            show_placeholders(True)
        return panel

    def _scroll_context_panel(self, panel: QWidget) -> QScrollArea:
        page = self.page
        area = QScrollArea()
        area.setObjectName("contextScroll")
        area.viewport().setObjectName("contextViewport")
        area.viewport().setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        if not panel.objectName():
            panel.setObjectName("contextContent")
        panel.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setMinimumWidth(0)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(panel)
        if not hasattr(page, "_wheel_scroll_owners"):
            page._wheel_scroll_owners = {}
        for control_type in (QComboBox, QAbstractSpinBox, QSlider):
            for control in panel.findChildren(control_type):
                control.installEventFilter(page)
                page._wheel_scroll_owners[control] = area
        return area


    def _self_scrolling_context_panel(self, panel: QWidget, area: QScrollArea) -> QWidget:
        """A tab whose panel owns its scroll regions (no outer scroll around them).

        The clip assistant's candidate list must be the one main scroll region;
        an outer scroll area around it nested list-in-scroll-in-scroll.
        """
        page = self.page
        if not panel.objectName():
            panel.setObjectName("contextContent")
        panel.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        panel.setMinimumWidth(0)
        if not hasattr(page, "_wheel_scroll_owners"):
            page._wheel_scroll_owners = {}
        for control_type in (QComboBox, QAbstractSpinBox, QSlider):
            for control in area.widget().findChildren(control_type):
                control.installEventFilter(page)
                page._wheel_scroll_owners[control] = area
        return panel

    def _ai_panel(self) -> QWidget:
        page = self.page
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        heading = QLabel("AI 字幕设计")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        page.ai_empty_state = QLabel("先描述字幕视觉要求，再生成三套可编辑的视觉与动效方案。")
        page.ai_empty_state.setObjectName("contextEmpty")
        page.ai_empty_state.setWordWrap(True)
        layout.addWidget(page.ai_empty_state)

        provider_card, provider_layout = page._style_section("生成服务", expanded=True)
        provider_grid = QGridLayout()
        provider_grid.setHorizontalSpacing(8)
        provider_grid.setVerticalSpacing(6)
        provider_grid.addWidget(QLabel("服务商"), 0, 0)
        page.ai_provider = StudioComboBox()
        models = page.runtime_settings.get("models", {})
        current_service = get_active_service(page.runtime_settings)
        if current_service not in AI_SERVICE_SPECS or "structured_output" not in AI_SERVICE_SPECS[
            current_service
        ].get("capabilities", ()):
            current_service = "custom"
        for service_id, spec in AI_SERVICE_SPECS.items():
            if "structured_output" not in spec.get("capabilities", ()):
                continue
            page.ai_provider.addItem(str(spec["label"]), service_id)
        page.ai_provider.setCurrentIndex(max(0, page.ai_provider.findData(current_service)))
        provider_grid.addWidget(page.ai_provider, 0, 1)
        provider_grid.addWidget(QLabel("模型"), 1, 0)
        page.ai_model = StudioComboBox()
        page.ai_model.setEditable(True)
        service = AI_SERVICE_SPECS.get(current_service, AI_SERVICE_SPECS["custom"])
        resolved = active_service_values(page.runtime_settings, stage="polish")
        configured_model = str(resolved.get("model") or models.get("polish_model") or "")
        model_values = list(service_model_catalog(page.runtime_settings, current_service))
        if configured_model and configured_model not in model_values:
            model_values.insert(0, configured_model)
        for model_id in dict.fromkeys(item for item in model_values if item):
            page.ai_model.addItem(model_id, model_id)
        page.ai_model.setCurrentText(configured_model or str(service.get("model") or ""))
        provider_grid.addWidget(page.ai_model, 1, 1)
        page.ai_provider_capabilities = QLabel()
        page.ai_provider_capabilities.setObjectName("contextMeta")
        page.ai_provider_capabilities.setWordWrap(True)
        provider_grid.addWidget(page.ai_provider_capabilities, 2, 0, 1, 2)
        page.ai_provider_health = QLabel("状态：未检测")
        page.ai_provider_health.setObjectName("contextMeta")
        page.ai_provider_health.setWordWrap(True)
        provider_details=QWidget()
        details_layout=QVBoxLayout(provider_details)
        details_layout.setContentsMargins(0,0,0,0)
        details_layout.addWidget(page.ai_provider_health)
        page.ai_network_detail_toggle=QPushButton("技术详情 / 网络诊断")
        page.ai_network_detail_toggle.setCheckable(True)
        details_layout.addWidget(page.ai_network_detail_toggle)
        page.ai_network_detail=QPlainTextEdit()
        page.ai_network_detail.setReadOnly(True)
        page.ai_network_detail.setMaximumHeight(150)
        page.ai_network_detail.hide()
        page.ai_network_detail_toggle.toggled.connect(page.ai_network_detail.setVisible)
        details_layout.addWidget(page.ai_network_detail)
        provider_grid.addWidget(provider_details, 3, 0, 1, 2)
        page.ai_provider_credential = QLabel("凭据：正在解析")
        page.ai_provider_credential.setObjectName("contextMeta")
        page.ai_provider_settings = QPushButton("前往设置")
        page.ai_provider_settings.setObjectName("studioButton")
        page.ai_provider_settings.clicked.connect(page._open_ai_provider_settings)
        provider_grid.addWidget(page.ai_provider_credential, 4, 0)
        provider_grid.addWidget(page.ai_provider_settings, 4, 1)
        page.ai_provider_status = StatusBadge("REQUESTING")
        bind_text(page.ai_provider_status, '● 检测中')
        provider_grid.addWidget(page.ai_provider_status, 5, 0, 1, 2)
        provider_layout.addLayout(provider_grid)
        page.ai_provider.currentIndexChanged.connect(page._ai_design_provider_changed)
        page.ai_model.currentTextChanged.connect(page._ai_design_model_changed)
        page._refresh_ai_design_provider_summary()
        layout.addWidget(provider_card)
        page.ai_provider_section = provider_card

        prompt_card, prompt_layout = page._style_section("视觉设计要求", expanded=True)
        prompt_hint = QLabel(
            "在下面输入框里描述你想要的字幕风格，然后点「生成字幕设计」："
        )
        prompt_hint.setObjectName("contextMeta")
        prompt_hint.setWordWrap(True)
        prompt_layout.addWidget(prompt_hint)
        page.ai_prompt = QPlainTextEdit()
        page.ai_prompt.setObjectName("aiPromptInput")
        bind_text(page.ai_prompt, '输入主题即可，例如：初音未来风格 / Minecraft像素风格。\n也可以补充构图、色彩、动作或参考；系统会展开成完整作品。', property='placeholderText')
        # 十六轮用户反馈：原框过高且不像输入框——收敛为两行高的明确输入区。
        page.ai_prompt.setMinimumHeight(58)
        page.ai_prompt.setMaximumHeight(88)
        prompt_layout.addWidget(page.ai_prompt)
        # 二十三轮：效果范围双模式——特效字幕（元素集中字幕带，不碍画面）/
        # 全画面动效（大出入场+元素遍布画面）。默认特效字幕。
        scope_row = QHBoxLayout()
        page.ai_effect_scope = QComboBox()
        page.ai_effect_scope.addItem("效果范围：特效字幕（元素集中在字幕附近）", "subtitle")
        page.ai_effect_scope.addItem("效果范围：动效丰富视频画面（全画面大动效）", "fullscreen")
        scope_row.addWidget(page.ai_effect_scope, 1)
        prompt_layout.addLayout(scope_row)
        page.ai_candidate_mode = QComboBox()
        for label,value in [('先生成1个完整候选','single'),('比较3个组件草案（一次设计请求）','drafts'),('生成3个完整候选','full3')]:
            page.ai_candidate_mode.addItem(label,value)
        bind_text(page.ai_candidate_mode, '草案来自可运行定义，可直接采用；后续只按明确选择增补。3个完整候选会增加模型调用与费用。', property='toolTip')
        prompt_layout.addWidget(page.ai_candidate_mode)
        page.ai_candidate_concurrency = QComboBox()
        from .i18n_widgets import add_combo_item
        for count in (1,2,3):add_combo_item(page.ai_candidate_concurrency, tr('完整候选并发：{count}', count=count), count)
        page.ai_candidate_concurrency.setCurrentIndex(1)
        prompt_layout.addWidget(page.ai_candidate_concurrency)
        page.ai_wait_mode = QComboBox()
        for label, value in [('完整设计 · 最长30分钟','long30'),('完整设计 · 最长15分钟','long15'),
                             ('复杂设计 · 最长60分钟','long60'),('使用设置中的自定义时限','configured')]:
            page.ai_wait_mode.addItem(label,value)
        bind_text(page.ai_wait_mode, '总预算包含生成与技术修复。网络活动、收到正文和完成候选分别显示；可随时安全取消并保留草稿。', property='toolTip')
        page.ai_wait_mode.setCurrentIndex(max(0,page.ai_wait_mode.findData(
            models.get('ai_design_wait_mode','long30'))))
        prompt_layout.addWidget(page.ai_wait_mode)
        layout.addWidget(prompt_card)
        page.ai_prompt_section = prompt_card

        actions = QVBoxLayout()
        actions.setSpacing(7)
        page.ai_design_target_label = QLabel('当前设计对象：未选择字幕')
        page.ai_design_target_label.setWordWrap(True)
        actions.addWidget(page.ai_design_target_label)
        page.ai_generate = QPushButton("生成字幕设计")
        page.ai_generate.setObjectName("studioPrimary")
        page.ai_generate.clicked.connect(page._request_ai_suggestion)
        actions.addWidget(page.ai_generate)
        page.ai_resume_saved_button=QPushButton('继续已保存的 AI 草稿…')
        page.ai_resume_saved_button.setObjectName('studioButton')
        page.ai_resume_saved_button.clicked.connect(lambda:page._theme_drafts().open_saved_response())
        actions.addWidget(page.ai_resume_saved_button)
        probe_row = QHBoxLayout()
        probe_row.setSpacing(7)
        page.ai_test_connection = QPushButton("测试连接")
        page.ai_test_connection.setObjectName("studioButton")
        page.ai_test_connection.clicked.connect(
            lambda: page._start_ai_provider_probe(
                str(page.ai_provider.currentData() or "custom"), force=True
            )
        )
        probe_row.addWidget(page.ai_test_connection, 1)
        page.ai_refresh_models = QPushButton("刷新模型")
        page.ai_refresh_models.setObjectName("studioButton")
        page.ai_refresh_models.clicked.connect(lambda: page._start_ai_provider_probe(
            str(page.ai_provider.currentData() or 'custom'),refresh_models=True))
        probe_row.addWidget(page.ai_refresh_models)
        page.ai_copy_diagnostics = QPushButton("复制诊断")
        page.ai_copy_diagnostics.setObjectName("studioButton")
        page.ai_copy_diagnostics.clicked.connect(page._copy_ai_provider_diagnostics)
        probe_row.addWidget(page.ai_copy_diagnostics)
        # 2026-09-02: 「本地备选」按钮移除——旧 ASS 动效回退已被内置网页主题
        # 兜底取代（生成失败时自动套 fallback_web_theme）。保留兼容属性，
        # flow 侧的 getattr(...) 引用照常工作但永不显示。
        page.ai_use_local_fallback = QPushButton("本地备选")
        page.ai_use_local_fallback.setObjectName("studioButton")
        page.ai_use_local_fallback.hide()
        actions.addLayout(probe_row)
        account_row=QHBoxLayout()
        page.ai_cli_login=QPushButton("打开官方 Codex 登录")
        page.ai_cli_logout=QPushButton("退出 Codex 登录")
        page.ai_cli_login.clicked.connect(lambda:page._ai_cli_account_action("login"))
        page.ai_cli_logout.clicked.connect(lambda:page._ai_cli_account_action("logout"))
        for button in (page.ai_cli_login,page.ai_cli_logout):
            button.setObjectName("studioButton")
            button.setVisible(str(page.ai_provider.currentData())=="codex_cli")
            account_row.addWidget(button)
        actions.addLayout(account_row)
        page.ai_application_status = QLabel('当前字幕尚未应用方案')
        page.ai_application_status.setObjectName('cardMeta')
        page.ai_application_status.setWordWrap(True)
        actions.addWidget(page.ai_application_status)
        result_row = QHBoxLayout()
        result_row.setSpacing(7)
        apply_scope = QComboBox()
        apply_scope.setObjectName("studioCombo")
        apply_scope.addItem("应用到当前字幕", "current")
        apply_scope.addItem("应用到该说话人", "speaker")
        apply_scope.addItem("应用到全部字幕", "all")
        page.ai_apply_scope = apply_scope
        result_row.addWidget(apply_scope, 1)
        actions.addLayout(result_row)
        apply_button = QPushButton("应用到当前字幕")
        page.ai_apply_button = apply_button
        apply_button.setEnabled(False)
        apply_button.setObjectName("studioPrimary")
        apply_button.setMinimumHeight(40)
        apply_button.setStyleSheet('min-height:40px;')
        apply_button.clicked.connect(page._apply_ai_preview)
        actions.addWidget(apply_button)
        result_row = QHBoxLayout()
        save_button = QPushButton("保存样式")
        page.ai_save_style_button = save_button
        save_button.setEnabled(False)
        save_button.setObjectName("studioButton")
        save_button.clicked.connect(page._save_ai_design_presets)
        result_row.addWidget(save_button, 1)
        ignore_button = QPushButton("清除")
        ignore_button.setObjectName("studioButton")
        ignore_button.clicked.connect(page._ignore_ai_preview)
        result_row.addWidget(ignore_button, 1)
        actions.addLayout(result_row)
        page.ai_transform_hint = QLabel('可编辑主题 · 拖动字幕移动，拖动角点等比缩放；双击改字。')
        page.ai_transform_hint.setObjectName('cardMeta')
        page.ai_transform_hint.setWordWrap(True)
        page.ai_transform_hint.hide()
        actions.addWidget(page.ai_transform_hint)
        page.ai_local_polish_button = QPushButton('本地精修文字…')
        page.ai_local_polish_button.setObjectName('studioButton')
        from .theme_local_polish import open_polish_dialog
        page.ai_local_polish_button.clicked.connect(lambda: open_polish_dialog(page))
        page.ai_local_polish_button.setEnabled(False)
        actions.addWidget(page.ai_local_polish_button)
        from .theme_application_ui import install_application_status
        install_application_status(page)
        layout.addLayout(actions)

        suggestion_card, suggestion_layout = page._context_card("设计草稿")
        page.ai_suggestion_card = suggestion_card
        page.ai_suggestion_title = QLabel("尚未生成当前视觉方案")
        page.ai_suggestion_title.setObjectName("cardMeta")
        suggestion_layout.addWidget(page.ai_suggestion_title)
        page.ai_gradient_swatch = QLabel()
        page.ai_gradient_swatch.setFixedHeight(18)
        page.ai_gradient_swatch.setStyleSheet("background:#343a38; border-radius:4px;")
        page.ai_gradient_swatch.hide()
        suggestion_layout.addWidget(page.ai_gradient_swatch)
        # 2026-09-02（十六轮用户指定）：单条大幅演示带——只保留字幕与近旁特效
        # （裁掉 16:9 上半空白），入场→持续→出场真实帧循环播放，看得更大更清楚。
        storyboard_wrap = QWidget()
        storyboard_wrap.setObjectName("aiStoryboardWrap")
        storyboard_col = QVBoxLayout(storyboard_wrap)
        storyboard_col.setContentsMargins(0, 2, 0, 2)
        storyboard_col.setSpacing(2)
        demo = QLabel("渲染中…")
        demo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        demo.setMinimumSize(300, 190)
        demo.setStyleSheet("background:#101018; border-radius:6px; color:#7f8aa0;")
        demo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        storyboard_col.addWidget(demo, 1)
        demo_caption = QLabel("特效字幕动画演示 · 入场 → 持续 → 出场（循环）")
        demo_caption.setObjectName("cardMeta")
        demo_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        storyboard_col.addWidget(demo_caption)
        six_grid = QGridLayout()
        six_grid.setSpacing(4)
        page.ai_storyboard_six_labels = []
        for index in range(6):
            label = bind_text(QLabel(), '分镜 {value0}', value0=index + 1)
            label.setMinimumSize(90,55)
            label.setMaximumHeight(90)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            label.setStyleSheet('background:#171b22; color:#a0a8b4;')
            six_grid.addWidget(label,index//3,index%3)
            page.ai_storyboard_six_labels.append(label)
        storyboard_col.addLayout(six_grid)
        page.ai_web_theme_demo_label = demo
        # 兼容旧 automation 引用：单框语义（十六轮起不再是三格）。
        page.ai_web_theme_storyboard_labels = [demo]
        storyboard_wrap.hide()
        suggestion_layout.addWidget(storyboard_wrap)
        page.ai_web_theme_storyboard_wrap = storyboard_wrap
        page.ai_variant_row = QVBoxLayout()
        page.ai_variant_buttons: list[QPushButton] = []
        suggestion_layout.addLayout(page.ai_variant_row)
        page.ai_preview = QPlainTextEdit()
        page.ai_preview.setObjectName("contextText")
        page.ai_preview.setReadOnly(True)
        bind_text(page.ai_preview, '生成后，这里会显示视觉设计配方，不会修改字幕文本。', property='placeholderText')
        page.ai_preview.setMinimumHeight(90)
        page.ai_preview.setMaximumHeight(180)
        suggestion_layout.addWidget(page.ai_preview)
        page.ai_confidence = QLabel("设计草稿是 AI 输出，不是输入框。")
        page.ai_confidence.setObjectName("cardMeta")
        page.ai_confidence.setWordWrap(True)
        suggestion_layout.addWidget(page.ai_confidence)
        concepts_toggle = QPushButton('展开三个概念方向与评分依据')
        concepts_toggle.setObjectName('studioButton')
        concepts_toggle.setCheckable(True)
        page.ai_concept_details = QPlainTextEdit()
        page.ai_concept_details.setReadOnly(True)
        page.ai_concept_details.setMaximumHeight(200)
        page.ai_concept_details.hide()
        concepts_toggle.toggled.connect(page.ai_concept_details.setVisible)
        suggestion_layout.addWidget(concepts_toggle)
        suggestion_layout.addWidget(page.ai_concept_details)
        page.ai_concept_choice=StudioComboBox()
        bind_text(page.ai_concept_choice, '选择已保存的方向；不会重新请求候选', property='toolTip')
        page.ai_concept_choice.hide()
        page.ai_concept_choice.currentIndexChanged.connect(lambda _index:page._theme_drafts().select_concept(page.ai_concept_choice.currentData()))
        suggestion_layout.addWidget(page.ai_concept_choice)
        page.ai_quality_details = QLabel('校验结果将在六帧渲染后显示')
        page.ai_quality_details.setObjectName('cardMeta')
        page.ai_quality_details.setWordWrap(True)
        suggestion_layout.addWidget(page.ai_quality_details)
        repair_grid = QGridLayout()
        page.ai_directed_repair_buttons = []
        for index,(label,request,art_revision) in enumerate((
            ('修复动画','保留所有框体、角色、文字、配色和已认可动作意图，修复完整主体进出与低频持续细节：框体不能首帧硬切出现或末瞬消失。按主题设计可辨识的事件，不能只把上下渐隐换个方向。CRT可整机捕获、屏内一次失锁校正及线到点关机；木刻可刚性叠板扣合、刻槽显露、字纹随板收合。已否定主动作与扫白亮带允许相关HTML/CSS/MotionSpec修订，不属于保护项，显式用户锁仍保留。固定木纹/刻槽不循环或扫白，发光材质按真实时间变化；1.5/3/6秒保留核心事件，短句减少次要动作与行程，结束清场不能代替退出。',False),
            ('调整位置','把主字幕放到下三分之一安全区，避免长中文和说话人裁切；保留舞台构图',False),
            ('降低遮挡','仅调整不必要的外溢与留白；保留有实际承托的主题框、角色辨识、认可动效和可读性，不能以去框完成降低遮挡',False),
            ('增强设计感','保留主题框体、角色辨识、构图比例、接触关系和完整动效，分别增强框体与文字本身材质。CRT字需栅格磷光、微色差和玻璃后显像；木刻字需阴刻暗边、压印高光、纸木纹耦合和油墨厚薄；冰雪字需霜面冷反光。协调颜色、字体、框边厚度和装饰衔接，不去框或清空动作。必须比当前稿有具体可见提升，不能只恢复旧结构；动作问题使用“修复动画”。',True))):
            button = QPushButton(label)
            button.setObjectName('studioButton')
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False,text=request,art=art_revision:page._theme_drafts().repair(text,art_revision=art))
            repair_grid.addWidget(button,index//2,index%2)
            page.ai_directed_repair_buttons.append(button)
        suggestion_layout.addLayout(repair_grid)
        retry_row = QHBoxLayout()
        page.ai_retry_render_button = QPushButton('重试预览')
        page.ai_retry_theme_code_button = QPushButton('重试主题代码')
        page.ai_retry_theme_code_button.setEnabled(False)
        page.ai_retry_theme_code_button.clicked.connect(lambda:page._theme_drafts().retry_theme_code())
        page.ai_cancel_render_button = QPushButton('取消当前请求')
        page.ai_draft_diagnostics_button = QPushButton('复制草稿诊断')
        for button in (page.ai_retry_theme_code_button,page.ai_retry_render_button,page.ai_cancel_render_button,page.ai_draft_diagnostics_button):
            button.setObjectName('studioButton')
            retry_row.addWidget(button)
        page.ai_retry_render_button.setEnabled(False)
        page.ai_cancel_render_button.setEnabled(False)
        page.ai_retry_render_button.clicked.connect(lambda:page._theme_drafts().render())
        page.ai_cancel_render_button.clicked.connect(lambda:page._theme_drafts().cancel())
        def copy_draft_diagnostics():
            import json
            QApplication.clipboard().setText(json.dumps(page._theme_drafts().diagnostics(),ensure_ascii=False,indent=2))
        page.ai_draft_diagnostics_button.clicked.connect(copy_draft_diagnostics)
        suggestion_layout.addLayout(retry_row)
        page.ai_local_theme_button=QPushButton('使用本地稳定模板生成')
        page.ai_local_theme_button.setObjectName('studioButton')
        page.ai_local_theme_button.setEnabled(False)
        page.ai_local_theme_button.clicked.connect(lambda:page._theme_drafts().use_local_template())
        suggestion_layout.addWidget(page.ai_local_theme_button)
        page.ai_progress_bar = QProgressBar()
        page.ai_progress_bar.setTextVisible(False)
        page.ai_progress_bar.setRange(0, 100)
        page.ai_progress_bar.setValue(0)
        page.ai_progress_bar.setVisible(False)
        suggestion_layout.addWidget(page.ai_progress_bar)
        page.ai_stream_console = QPlainTextEdit()
        page.ai_stream_console.setObjectName("aiStreamConsole")
        page.ai_stream_console.setReadOnly(True)
        page.ai_stream_console.setMinimumHeight(150)
        page.ai_stream_console.setMaximumHeight(320)
        page.ai_stream_console.setMaximumBlockCount(800)
        page.ai_stream_console.setVisible(False)
        bind_text(page.ai_stream_console, 'AI 输出流（HTML/CSS 代码将实时显示在这里）', property='placeholderText')
        page.ai_stream_console.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        suggestion_layout.addWidget(page.ai_stream_console)
        suggestion_layout.setStretchFactor(page.ai_stream_console, 1)
        page.ai_raw_response_button = QPushButton("查看 AI 原始 JSON")
        page.ai_raw_response_button.setObjectName("studioButton")
        page.ai_raw_response_button.setCursor(Qt.CursorShape.PointingHandCursor)
        page.ai_raw_response_button.clicked.connect(page._show_ai_raw_response)
        # 2026-09-02：常显——用户需要每次运行的 JSON 记录来复盘与改进。
        page.ai_raw_response_button.setVisible(True)
        suggestion_layout.addWidget(page.ai_raw_response_button)
        # 特效字幕档案（十六轮：自然语言修改框已移入样式面板的「特效字幕调整」，
        # 这里只保留档案导出/导入）。
        refine_row = QWidget()
        refine_layout = QHBoxLayout(refine_row)
        refine_layout.setContentsMargins(0, 4, 0, 0)
        refine_layout.setSpacing(6)
        page.ai_export_archive_button = QPushButton("导出档案")
        page.ai_export_archive_button.setEnabled(False)
        page.ai_export_archive_button.setObjectName("studioButton")
        bind_text(page.ai_export_archive_button, '导出为独立档案（theme.html 双击即可播放动画演示 + theme.json）', property='toolTip')
        page.ai_export_archive_button.clicked.connect(page._export_ai_theme_archive)
        refine_layout.addWidget(page.ai_export_archive_button, 1)
        page.ai_import_archive_button = QPushButton("导入档案")
        page.ai_import_archive_button.setObjectName("studioButton")
        bind_text(page.ai_import_archive_button, '从 .2byte-theme 档案（theme.html/theme.json）载入主题', property='toolTip')
        page.ai_import_archive_button.clicked.connect(page._import_ai_theme_archive)
        # Existing archives must be importable before any AI draft exists.
        # The draft card and refinement row are deliberately hidden initially.
        layout.addWidget(page.ai_import_archive_button)
        page.ai_workshop_button = QPushButton("AI 字幕工坊…")
        page.ai_workshop_button.setObjectName("studioButton")
        bind_text(page.ai_workshop_button, '对话式精修已应用的特效字幕：预览真实动画 + 自然语言修改（也可双击视频画面）', property='toolTip')
        page.ai_workshop_button.clicked.connect(page._open_web_theme_workshop)
        refine_layout.addWidget(page.ai_workshop_button, 1)
        page.ai_refine_row = refine_row
        refine_row.hide()
        suggestion_layout.addWidget(refine_row)
        suggestion_card.hide()
        layout.addWidget(suggestion_card)
        # Compatibility fields remain for old automation hooks, but the
        # duplicate visual-design surface is no longer user-visible.
        page.ai_style_prompt = QLineEdit(panel)
        page.ai_style_prompt.hide()
        page.ai_style_result = QLabel(panel)
        page.ai_style_result.hide()
        layout.addStretch(1)
        return panel
