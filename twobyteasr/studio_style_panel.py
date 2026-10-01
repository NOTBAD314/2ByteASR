"""Style inspector panel, style preset manager, and canvas style handlers
for Subtitle Studio."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from PySide6.QtCore import (QSize, QTimer, Qt)
from PySide6.QtGui import (QFontDatabase, QKeySequence, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QToolButton, QTreeWidgetItem, QVBoxLayout, QWidget)
from .font_system import RECOMMENDED_OPEN_SOURCE_FONTS
from .motion_library import MotionPreset
from .selection_scope import SelectionScope
from .studio_ai import style_recipe_for_prompt
from .studio_fill_editors import (FillEditorDialog, GradientEditor)
from .studio_font_combo import LazyFontComboBox
from .studio_motion_browser import MotionBrowserDialog
from .studio_style_widgets import (StyleColorButton, StylePreview, StyleScopeSelector, _PresetManagerTree, _StyleColorEdit)
from .studio_theme import (StudioComboBox, create_studio_menu, studio_message_box)
from .studio_widgets import (ScrubDoubleSpinBox, ScrubSpinBox, _icon)
from .style_presets import (BUILTIN_PRESETS, StylePresetStore)
from .style_recipe import (FillSpec, StyleRecipe)
from .themed_icons import install_themed_icon
from .ui_theme import INK

from .i18n import bind_text

from .i18n import tr

class StudioStylePanelMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _style_section(self, title: str, *, expanded: bool = True) -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("styleSection")
        outer = QVBoxLayout(section)
        outer.setContentsMargins(4, 2, 4, 6)
        outer.setSpacing(4)
        header = QToolButton()
        header.setObjectName("styleSectionHeader")
        header.setCheckable(True)
        header.setChecked(expanded)
        header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        header.setText(title)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(5)

        def toggle(visible: bool) -> None:
            header.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)
            body.setVisible(visible)

        header.toggled.connect(toggle)
        outer.addWidget(header)
        outer.addWidget(body)
        # Collapse after mounting: setVisible(True) before parenting would
        # flash a real blank top-level window (the P0 startup regression).
        if not expanded:
            body.setVisible(False)
        return section, body_layout

    def _new_style_timer(self) -> QTimer:
        return QTimer(self)

    @staticmethod
    def _style_single_shot(delay_ms: int, callback) -> None:
        QTimer.singleShot(delay_ms, callback)

    @staticmethod
    def _new_style_preview() -> StylePreview:
        return StylePreview()

    def _new_lazy_font_combo(self) -> LazyFontComboBox:
        combo = LazyFontComboBox()
        combo.interaction_runtime_audit = self._interaction_runtime_audit
        return combo

    @staticmethod
    def _new_style_color_edit() -> _StyleColorEdit:
        return _StyleColorEdit()

    @staticmethod
    def _style_color_edit_type():
        return _StyleColorEdit

    @staticmethod
    def _new_style_scope_selector() -> StyleScopeSelector:
        return StyleScopeSelector()

    @staticmethod
    def _new_style_color_button() -> StyleColorButton:
        return StyleColorButton()

    @staticmethod
    def _style_color_button_type():
        return StyleColorButton

    @staticmethod
    def _new_motion_browser_dialog(*args, **kwargs) -> MotionBrowserDialog:
        return MotionBrowserDialog(*args, **kwargs)

    @staticmethod
    def _new_fill_editor_dialog(*args, **kwargs) -> FillEditorDialog:
        return FillEditorDialog(*args, **kwargs)

    @staticmethod
    def _style_icon(name: str, color: str | None = None):
        if color is not None:
            return _icon(name, color)
        from .themed_icons import themed_icon
        return themed_icon(name)

    @staticmethod
    def _style_field(label: str, control: QWidget) -> QWidget:
        host = QWidget()
        field_layout = QVBoxLayout(host)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(2)
        caption = QLabel(label)
        caption.setObjectName("styleFieldLabel")
        field_layout.addWidget(caption)
        field_layout.addWidget(control)
        return host

    def _generate_ai_style_draft(self) -> None:
        prompt = self.ai_style_prompt.text().strip() or "未来科技感字幕"
        try:
            self._ai_style_draft = style_recipe_for_prompt(prompt)
            recipe = self._ai_style_draft
            typography = recipe.typography
            colors = recipe.colors
            motion = recipe.motion
            bind_text(self.ai_style_result, '{value0} · Engine: {value1}\n字体 {value2} · {value3}px · 填充 {value4} · 描边 {value5} · 动效 {value6}', value0=recipe.name, value1=recipe.engine, value2=typography.get('fontFamily', '-'), value3=typography.get('fontSize', '-'), value4=colors.get('fill', '-'), value5=colors.get('outline', '-'), value6=motion.get('preset', 'none'))
        except ValueError as exc:
            self._ai_style_draft = None
            bind_text(self.ai_style_result, '无法生成受支持的样式：{exc}', exc=exc)

    def _apply_ai_style_draft(self) -> None:
        return self.style_controller._apply_ai_style_draft()

    def _style_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(7)
        self._updating_style_ui = False
        self._style_debounce_timer = QTimer(self)
        self._style_debounce_timer.setSingleShot(True)
        self._style_debounce_timer.setInterval(180)
        self._style_debounce_timer.timeout.connect(self._style_control_changed)

        preset_card, preset_layout = self._style_section("样式预设")
        self.style_preset = StudioComboBox()
        self._refresh_style_presets()
        self.style_preset.currentIndexChanged.connect(self._load_style_inspector)
        # activated fires only for real user picks (not programmatic refresh),
        # so preset switching applies immediately without surprising applies
        # during _refresh_style_presets.
        self.style_preset.activated.connect(self._preset_activated)
        preset_actions = QHBoxLayout()
        preset_actions.setSpacing(5)
        preset_actions.addWidget(self.style_preset, 1)
        preset_more = QToolButton()
        preset_more.setObjectName("studioTool")
        preset_more.setText("...")
        bind_text(preset_more, '管理样式预设', property='toolTip')
        preset_menu = create_studio_menu(preset_more)
        for caption, slot in (
            ("新建", self._new_style_preset),
            ("复制", self._duplicate_style_preset),
            ("重命名", self._rename_style_preset),
            ("删除", self._delete_style_preset),
            ("保存为新预设", self._duplicate_style_preset),
            ("管理预设", self._open_style_preset_manager),
        ):
            preset_menu.addAction(caption, slot)
        preset_more.setMenu(preset_menu)
        preset_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        preset_actions.addWidget(preset_more)
        preset_layout.addLayout(preset_actions)
        layout.addWidget(preset_card)

        typography_card, typography_layout = self._style_section("文字")
        self.style_font = LazyFontComboBox()
        self.style_font.interaction_runtime_audit = self._interaction_runtime_audit
        self.style_font.setEditable(True)
        self.style_font.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.style_font.fontPicked.connect(lambda _family, _weight: self._style_control_changed())
        typography_layout.addWidget(self._style_field("字体", self.style_font))
        size_row = QGridLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setHorizontalSpacing(7)
        self.style_font_size = ScrubSpinBox()
        self.style_font_size.setRange(8, 500)
        self.style_spacing = ScrubSpinBox()
        self.style_spacing.setRange(-100, 200)
        size_row.addWidget(self._style_field("字号", self.style_font_size), 0, 0)
        size_row.addWidget(self._style_field("字距", self.style_spacing), 0, 1)
        typography_layout.addLayout(size_row)
        emphasis_row = QHBoxLayout()
        emphasis_row.setSpacing(5)
        self.style_bold = QToolButton()
        self.style_italic = QToolButton()
        self.style_underline = QToolButton()
        for control, text, tip in (
            (self.style_bold, "B", "粗体"),
            (self.style_italic, "I", "斜体"),
            (self.style_underline, "U", "下划线"),
        ):
            control.setObjectName("styleEmphasis")
            control.setText(text)
            control.setToolTip(tip)
            control.setCheckable(True)
            emphasis_row.addWidget(control)
        emphasis_row.addStretch(1)
        typography_layout.addLayout(emphasis_row)
        layout.addWidget(typography_card)

        position_card, position_layout = self._style_section("位置与对齐")
        self.style_alignment = StudioComboBox()
        for label, value in (
            ("左下", 1), ("居中下", 2), ("右下", 3),
            ("左中", 4), ("居中", 5), ("右中", 6),
            ("左上", 7), ("居中上", 8), ("右上", 9),
        ):
            self.style_alignment.addItem(label, value)
        self.style_alignment.hide()
        anchor_row = QHBoxLayout()
        anchor_row.setSpacing(10)
        anchor_grid = QGridLayout()
        anchor_grid.setSpacing(3)
        self.style_anchor_group = QButtonGroup(self)
        self.style_anchor_group.setExclusive(True)
        self.style_anchor_buttons = {}
        for display_row, values in enumerate(((7, 8, 9), (4, 5, 6), (1, 2, 3))):
            for column, value in enumerate(values):
                button = QToolButton()
                button.setObjectName("styleAnchor")
                button.setCheckable(True)
                button.setText("●")
                button.setToolTip(self.style_alignment.itemText(self.style_alignment.findData(value)))
                button.clicked.connect(
                    lambda _checked=False, alignment=value: self._set_style_alignment(alignment)
                )
                self.style_anchor_group.addButton(button, value)
                self.style_anchor_buttons[value] = button
                anchor_grid.addWidget(button, display_row, column)
        anchor_row.addLayout(anchor_grid)
        anchor_row.addStretch(1)
        anchor_label = QLabel("锚点")
        anchor_label.setObjectName("fieldLabel")
        position_layout.addWidget(anchor_label)
        position_layout.addLayout(anchor_row)

        position_row = QGridLayout()
        position_row.setContentsMargins(0, 0, 0, 0)
        position_row.setHorizontalSpacing(7)
        self.style_position_x = QSpinBox()
        self.style_position_y = QSpinBox()
        for control in (self.style_position_x, self.style_position_y):
            control.setRange(0, 16384)
        position_row.addWidget(self._style_field("X", self.style_position_x), 0, 0)
        position_row.addWidget(self._style_field("Y", self.style_position_y), 0, 1)
        position_layout.addLayout(position_row)
        self.position_edit_button = QPushButton("在画面中拖动字幕")
        self.position_edit_button.setObjectName("studioButton")
        self.position_edit_button.setCheckable(True)
        self.position_edit_button.setChecked(True)
        self.position_edit_button.setIcon(_icon("fa5s.arrows-alt"))
        self.position_edit_button.toggled.connect(self._toggle_position_edit)
        position_layout.addWidget(self.position_edit_button)
        advanced_button = QToolButton()
        advanced_button.setObjectName("styleSectionHeader")
        bind_text(advanced_button, '高级位置设置')
        advanced_button.setCheckable(True)
        advanced_button.setArrowType(Qt.ArrowType.RightArrow)
        advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        position_layout.addWidget(advanced_button)
        advanced_host = QWidget()
        advanced_host.hide()
        margin_row = QHBoxLayout()
        margin_row.setContentsMargins(0, 0, 0, 0)
        margin_row.setSpacing(5)
        self.style_margin_l = QSpinBox()
        self.style_margin_r = QSpinBox()
        self.style_margin_v = QSpinBox()
        for control, prefix in (
            (self.style_margin_l, "左 "),
            (self.style_margin_r, "右 "),
            (self.style_margin_v, "垂直 "),
        ):
            control.setRange(0, 1000)
            control.setPrefix(prefix)
            control.setSuffix(" px")
            margin_row.addWidget(control)
        advanced_host.setLayout(margin_row)
        advanced_button.toggled.connect(advanced_host.setVisible)
        advanced_button.toggled.connect(
            lambda visible: advanced_button.setArrowType(
                Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
            )
        )
        position_layout.addWidget(advanced_host)
        layout.addWidget(position_card)

        appearance_card, appearance_layout = self._style_section("外观")
        self.style_fill_color = QLineEdit()
        self.style_fill_color.setPlaceholderText("#FFFFFF")
        self.style_outline_color = QLineEdit()
        self.style_outline_color.setPlaceholderText("#000000")
        self.style_fill_swatch = self._style_color_control(self.style_fill_color)
        self.style_outline_swatch = self._style_color_control(self.style_outline_color)
        self.style_fill_type = StudioComboBox()
        self.style_fill_type.addItem("纯色", "solid")
        self.style_fill_type.addItem("线性渐变", "linear-gradient")
        self.style_fill_type.addItem("径向渐变（高级）", "radial-gradient")
        self.style_fill_type.currentIndexChanged.connect(self._fill_type_changed)
        fill_type_row = QHBoxLayout()
        fill_type_row.addWidget(self._style_field("填充类型", self.style_fill_type), 1)
        fill_type_row.addWidget(self._style_field("纯色", self.style_fill_swatch), 2)
        appearance_layout.addLayout(fill_type_row)
        self.gradient_editor = GradientEditor()
        self.gradient_editor.setObjectName("gradientEditor")
        self.gradient_editor.gradientChanged.connect(self._gradient_changed)
        self.gradient_editor.colorRequested.connect(self._gradient_color_requested)
        self._gradient_scrubbing = False
        self.gradient_editor.angle_spin.scrubStarted.connect(self._gradient_scrub_started)
        self.gradient_editor.angle_spin.scrubFinished.connect(self._gradient_scrub_finished)
        self.gradient_editor.hide()
        appearance_layout.addWidget(self.gradient_editor)
        self.gradient_status = QLabel("视频预览：基础效果")
        self.gradient_status.setObjectName("cardMeta")
        self.gradient_status.hide()
        appearance_layout.addWidget(self.gradient_status)
        stroke_row = QHBoxLayout()
        stroke_row.setSpacing(7)
        self.style_outline_width = ScrubDoubleSpinBox()
        self.style_outline_width.setRange(0.0, 20.0)
        self.style_outline_width.setDecimals(1)
        self.style_outline_width.setSingleStep(0.1)
        self.style_shadow = ScrubDoubleSpinBox()
        self.style_shadow.setRange(0.0, 20.0)
        self.style_shadow.setDecimals(1)
        self.style_shadow.setSingleStep(0.1)
        stroke_row.addWidget(self._style_field("描边颜色", self.style_outline_swatch), 1)
        stroke_row.addWidget(self._style_field("粗细", self.style_outline_width))
        appearance_layout.addLayout(stroke_row)
        background_row = QHBoxLayout()
        background_row.setSpacing(7)
        self.style_background = QCheckBox("背景框")
        self.style_back_color = QLineEdit()
        self.style_back_color.setPlaceholderText("#000000")
        self.style_back_swatch = self._style_color_control(self.style_back_color)
        background_row.addWidget(self.style_back_swatch, 1)
        background_row.addWidget(self._style_field("阴影", self.style_shadow))
        background_row.addWidget(self.style_background)
        appearance_layout.addLayout(background_row)
        layout.addWidget(appearance_card)

        effect_card, effect_layout = self._style_section("说话人样式与动效", expanded=False)
        self.effect_preset = StudioComboBox()
        for label, effect_id in (
            ("无", "none"),
            ("AI 动效 / 自定义动效", "visual_graph"),
            ("淡入淡出", "fade"),
            ("弹出", "pop"),
            ("滑入", "slide"),
            ("缩放", "scale"),
        ):
            self.effect_preset.addItem(label, effect_id)
        effect_layout.addWidget(self._style_field("动效", self.effect_preset))
        layout.addWidget(effect_card)

        scope_card, scope_layout = self._style_section("应用范围", expanded=False)
        self.style_scope = StudioComboBox()
        self.style_scope.addItem("当前字幕", "current")
        self.style_scope.addItem("选中字幕", "selected")
        self.style_scope.addItem("该说话人", "speaker")
        self.style_scope.addItem("全片", "all")
        scope_layout.addWidget(self.style_scope)
        layout.addWidget(scope_card)
        apply_button = QPushButton("应用样式与动效")
        apply_button.setObjectName("studioPrimary")
        apply_button.clicked.connect(self._apply_style)
        layout.addWidget(apply_button)
        layout.addStretch(1)
        for control in (
            self.style_font_size,
            self.style_spacing,
            self.style_margin_l,
            self.style_margin_r,
            self.style_margin_v,
            self.style_position_x,
            self.style_position_y,
            self.style_outline_width,
            self.style_shadow,
        ):
            control.valueChanged.connect(self._queue_style_commit)
            control.editingFinished.connect(self._commit_style_now)
            control.scrubStarted.connect(self._begin_style_scrub)
            control.scrubFinished.connect(self._finish_style_scrub)
        for control in (self.style_fill_color, self.style_outline_color, self.style_back_color, self.style_glow_color):
            control.textEdited.connect(self._queue_style_commit)
            control.editingFinished.connect(self._commit_style_now)
        self.style_font.lineEdit().textEdited.connect(self._queue_style_commit)
        self.style_font.lineEdit().editingFinished.connect(self._commit_style_now)
        for control in (self.style_bold, self.style_italic, self.style_underline, self.style_background):
            control.toggled.connect(self._style_control_changed)
        self.style_alignment.currentIndexChanged.connect(self._sync_style_anchor)
        self.style_alignment.currentIndexChanged.connect(self._style_control_changed)
        QTimer.singleShot(0, self, self._load_style_inspector)
        return panel

    def _style_panel_p213(self) -> QWidget:
        return self.style_controller._style_panel_p213()

    def _set_style_alignment(self, alignment: int) -> None:
        return self.style_controller._set_style_alignment(alignment)

    def _sync_style_anchor(self, _index: int = -1) -> None:
        return self.style_controller._sync_style_anchor(_index)

    def _queue_style_commit(self, *_args) -> None:
        return self.style_controller._queue_style_commit(*_args)

    def _begin_style_scrub(self) -> None:
        return self.style_controller._begin_style_scrub()

    def _finish_style_scrub(self) -> None:
        return self.style_controller._finish_style_scrub()

    def _commit_style_now(self) -> None:
        return self.style_controller._commit_style_now()

    def _effect_changed(self, _index: int = -1) -> None:
        return self.style_controller._effect_changed(_index)

    def _motion_preset_changed(self, _index: int = -1) -> None:
        return self.style_controller._motion_preset_changed(_index)

    def _open_motion_browser(self) -> None:
        return self.style_controller._open_motion_browser()

    def _open_style_library(self) -> None:
        return self.style_controller._open_style_library()

    def _apply_style_library_preset(self, style_id: str) -> None:
        return self.style_controller._apply_style_library_preset(style_id)

    def _current_motion_for_library(self) -> tuple[dict[str, object], str]:
        return self.style_controller._current_motion_for_library()

    def _apply_motion_library_preset(self, preset_id: str) -> None:
        return self.style_controller._apply_motion_library_preset(preset_id)

    def _apply_advanced_motion(self, preset: MotionPreset) -> None:
        return self.style_controller._apply_advanced_motion(preset)

    def _toggle_motion_advanced(self, expanded: bool) -> None:
        return self.style_controller._toggle_motion_advanced(expanded)

    def _preview_motion_preset(self, effect_id: str) -> None:
        return self.style_controller._preview_motion_preset(effect_id)

    def _activate_motion_preset(self, effect_id: str) -> None:
        return self.style_controller._activate_motion_preset(effect_id)

    @staticmethod
    def _set_combo_data(control: QComboBox, value: str) -> None:
        index = control.findData(str(value))
        if index >= 0:
            control.setCurrentIndex(index)

    def _motion_source(self, effect_id: str) -> dict:
        return self.style_controller._motion_source(effect_id)

    def _load_motion_controls(self, effect_id: str) -> None:
        return self.style_controller._load_motion_controls(effect_id)

    def _load_advanced_motion_controls(self, payload: Mapping[str, object]) -> None:
        return self.style_controller._load_advanced_motion_controls(payload)

    def _motion_curve_changed(self, _index: int = -1) -> None:
        return self.style_controller._motion_curve_changed(_index)

    def _motion_control_changed(self, *_args) -> None:
        return self.style_controller._motion_control_changed(*_args)

    def _effect_from_controls(self, effect_id: str) -> dict:
        return self.style_controller._effect_from_controls(effect_id)

    def _fill_type_changed(self, _index: int = -1) -> None:
        return self.style_controller._fill_type_changed(_index)

    def _gradient_changed(self, _value: dict) -> None:
        return self.style_controller._gradient_changed(_value)

    def _gradient_scrub_started(self) -> None:
        return self.style_controller._gradient_scrub_started()

    def _gradient_scrub_finished(self) -> None:
        return self.style_controller._gradient_scrub_finished()

    def _gradient_color_requested(self, index: int) -> None:
        return self.style_controller._gradient_color_requested(index)

    def _current_gradient(self) -> dict | None:
        return self.style_controller._current_gradient()

    def _style_recipe_for_style(self, style, gradient: dict | None) -> dict:
        return self.style_controller._style_recipe_for_style(style, gradient)

    def _style_color_control(self, editor: QLineEdit) -> QWidget:
        return self.style_controller._style_color_control(editor)

    def _open_fill_editor(self) -> None:
        return self.style_controller._open_fill_editor()

    @staticmethod
    def _base_recipe_for_style(style) -> StyleRecipe:
        return StyleRecipe(
            name=str(style.name or "自定义样式"),
            engine="native",
            typography={
                "fontFamily": style.font_family, "fontSize": style.font_size,
                "fontWeight": style.font_weight, "fontStyleName": style.font_style_name,
                "fontFile": style.font_file, "fontFaceIndex": style.font_face_index,
                "bold": style.bold, "italic": style.italic,
                "underline": style.underline, "spacing": style.spacing,
                "scaleX": style.scale_x, "scaleY": style.scale_y,
            },
            layout={
                "alignment": style.alignment, "marginL": style.margin_l,
                "marginR": style.margin_r, "marginV": style.margin_v,
                "positionX": style.position_x, "positionY": style.position_y,
            },
            colors={
                "fill": style.primary_color, "outline": style.outline_color,
                "background": style.back_color,
            },
            outline={
                "color": style.outline_color, "width": style.outline_width,
                "shadow": style.shadow,
            },
            background={"enabled": style.border_style == 3, "color": style.back_color},
        )

    def _apply_fill_spec(self, fill: FillSpec) -> None:
        return self.style_controller._apply_fill_spec(fill)

    def _update_color_swatch(self, button: QToolButton, value: str) -> None:
        return self.style_controller._update_color_swatch(button, value)

    def _set_style_color(self, editor: QLineEdit, value: str) -> None:
        return self.style_controller._set_style_color(editor, value)

    def _open_style_color_dialog(self, editor: QLineEdit) -> None:
        return self.style_controller._open_style_color_dialog(editor)

    def _create_style_color_dialog(self, editor: QLineEdit) -> QColorDialog:
        return self.style_controller._create_style_color_dialog(editor)

    def _install_recommended_fonts(self) -> None:
        """Enable bundled OFL fonts only after explicit user confirmation."""
        details = "\n".join(
            f"• {font.family} — {font.license_name}\n  {font.project_url}"
            for font in RECOMMENDED_OPEN_SOURCE_FONTS
        )
        answer = QMessageBox.question(
            self,
            tr('启用开源字体'),
            tr('仅在你确认后，2ByteASR 才会启用随应用提供的字体文件。\n不会联网下载，也不会修改 Windows 系统字体。\n\n{value0}\n\n继续检查并启用？', value0=details),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        font_roots = (
            Path(__file__).resolve().parent / "assets" / "fonts",
            Path(__file__).resolve().parent.parent / "assets" / "fonts",
        )
        loaded: list[str] = []
        for root in font_roots:
            if not root.is_dir():
                continue
            for path in sorted((*root.glob("*.otf"), *root.glob("*.ttf"))):
                font_id = QFontDatabase.addApplicationFont(str(path))
                if font_id >= 0:
                    loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
        if loaded:
            bind_text(self.advanced_font_status, '已启用：{value0}', value0=' / '.join(dict.fromkeys(loaded)))
            QMessageBox.information(self, tr('字体已启用'), tr('已为本次应用会话启用开源字体。'))
        else:
            bind_text(self.advanced_font_status, '未随包提供 · 当前使用安全回退字体')
            QMessageBox.information(
                self,
                tr('未找到随包字体'),
                tr('当前安装包没有包含字体文件，2ByteASR 将继续使用安全回退字体。\n\n可从以下官方项目自行获取：\n{value0}', value0=details),
            )

    def _refresh_style_presets(self, selected_id: str = "") -> None:
        return self.style_controller._refresh_style_presets(selected_id)

    def _preset_name(self, title: str, initial: str) -> str:
        return self.style_controller._preset_name(title, initial)

    def _clone_selected_preset(self, title: str, suffix: str) -> None:
        return self.style_controller._clone_selected_preset(title, suffix)

    def _new_style_preset(self) -> None:
        return self.style_controller._new_style_preset()

    def _duplicate_style_preset(self) -> None:
        return self.style_controller._duplicate_style_preset()

    def _rename_style_preset(self) -> None:
        return self.style_controller._rename_style_preset()

    def _delete_style_preset(self) -> None:
        return self.style_controller._delete_style_preset()

    def _open_style_preset_manager(self) -> None:
        host = self.window()
        store = StylePresetStore()
        content = QWidget()
        content.setObjectName("stylePresetManager")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        hint = QLabel("内置预设可从当前资料库隐藏并恢复；自定义与 AI 预设还可收藏、重命名、导入或导出。")
        hint.setObjectName("studioSaveState")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search = QLineEdit()
        search.setObjectName("stylePresetSearch")
        bind_text(search, '搜索预设名称…', property='placeholderText')
        search.setClearButtonEnabled(True)
        search_row.addWidget(search, 1)
        count_label = QLabel()
        count_label.setObjectName("stylePresetCount")
        search_row.addWidget(count_label)
        layout.addLayout(search_row)

        batch_row = QHBoxLayout()
        batch_toggle = QPushButton("批量选择")
        batch_toggle.setObjectName("studioButton")
        batch_toggle.setCheckable(True)
        batch_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        install_themed_icon(batch_toggle, "fa5s.check-square", "secondary")
        batch_row.addWidget(batch_toggle)
        batch_hint = QLabel("选择当前筛选结果中的预设")
        batch_hint.setObjectName("studioSaveState")
        batch_hint.hide()
        batch_row.addWidget(batch_hint)
        batch_row.addStretch(1)
        layout.addLayout(batch_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        filter_group = QButtonGroup(content)
        filter_group.setExclusive(True)
        filter_buttons = {}
        for label, key in (
            ("全部", "all"),
            ("收藏", "favorite"),
            ("内置", "builtin"),
            ("自定义", "custom"),
            ("AI 生成", "ai"),
        ):
            button = QPushButton(label)
            button.setObjectName("stylePresetFilter")
            button.setProperty("filterKey", key)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            filter_group.addButton(button)
            filter_buttons[key] = button
            filter_row.addWidget(button)
        filter_buttons["all"].setChecked(True)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        tree = _PresetManagerTree()
        tree.setObjectName("stylePresetTree")
        tree.setHeaderLabels(["预设"])
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(False)
        tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tree.setUniformRowHeights(True)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(tree, 1)
        view_state = {"loading": False, "filter": "all", "batch": False}

        def refresh() -> None:
            view_state["loading"] = True
            tree.clear()
            styles = store.all()
            metadata = store.load_metadata()
            needle = search.text().strip().casefold()
            rows = []
            for style_id, style in styles.items():
                system = style_id in BUILTIN_PRESETS
                meta = metadata.get(style_id, {})
                source = "builtin" if system else ("ai" if str(meta.get("source")) == "ai" or style_id.startswith("ai-") else "custom")
                favorite = bool(meta.get("favorite"))
                if needle and needle not in f"{style.name} {style_id}".casefold():
                    continue
                active_filter = view_state["filter"]
                if active_filter == "favorite" and not favorite:
                    continue
                if active_filter not in {"all", "favorite"} and source != active_filter:
                    continue
                rows.append((not favorite, source != "builtin", style.name.casefold(), style_id, style, source, favorite))
            rows.sort()
            source_labels = {"builtin": "内置", "custom": "自定义", "ai": "AI 生成"}
            for _not_favorite, _not_builtin, _name, style_id, style, source, favorite in rows:
                item = QTreeWidgetItem(
                    tree,
                    [f"{'★' if favorite else '☆'}  {style.name}\n     {source_labels[source]} · {style.font_family} · {style.font_size}px"],
                )
                item.setData(0, Qt.ItemDataRole.UserRole, style_id)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, source)
                item.setData(0, Qt.ItemDataRole.UserRole + 2, favorite)
                if view_state["batch"]:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setSizeHint(0, QSize(0, 56))
                item.setToolTip(0, f"{style.font_family} · {style.font_size}px")
                if source == "builtin":
                    item.setToolTip(0, "删除会隐藏内置预设，不会修改安装包资源")
            bind_text(count_label, '{value0} 个预设', value0=len(rows))
            tree.setEnabled(bool(rows))
            view_state["loading"] = False

        def selected_ids() -> list[str]:
            if view_state["batch"]:
                return [
                    str(tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole) or "")
                    for index in range(tree.topLevelItemCount())
                    if tree.topLevelItem(index).checkState(0) == Qt.CheckState.Checked
                ]
            return [
                str(item.data(0, Qt.ItemDataRole.UserRole) or "")
                for item in tree.selectedItems()
                if str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            ]

        def current_user_id() -> str:
            selected = selected_ids()
            if len(selected) == 1:
                return selected[0] if selected[0] not in BUILTIN_PRESETS else ""
            return ""

        search.textChanged.connect(lambda _text: refresh())
        for key, button in filter_buttons.items():
            button.toggled.connect(
                lambda checked, value=key: (
                    view_state.__setitem__("filter", value),
                    refresh(),
                ) if checked else None
            )

        def set_batch_mode(enabled: bool) -> None:
            view_state["batch"] = bool(enabled)
            (bind_text(batch_toggle, '退出批量选择') if enabled else bind_text(batch_toggle, '批量选择'))
            batch_hint.setVisible(bool(enabled))
            tree.setSelectionMode(
                QAbstractItemView.SelectionMode.NoSelection
                if enabled else QAbstractItemView.SelectionMode.ExtendedSelection
            )
            refresh()
            update_actions()

        batch_toggle.toggled.connect(set_batch_mode)

        library_actions = QHBoxLayout()
        library_actions.setSpacing(8)
        import_button = QPushButton("导入")
        export_button = QPushButton("导出")
        restore_builtins = QPushButton("恢复内置")
        for button, icon in (
            (import_button, "fa5s.file-import"),
            (export_button, "fa5s.file-export"),
            (restore_builtins, "fa5s.undo-alt"),
        ):
            button.setObjectName("studioButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            install_themed_icon(button, icon, "secondary")
            library_actions.addWidget(button)
        library_actions.addStretch(1)
        layout.addLayout(library_actions)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        favorite = QPushButton("收藏")
        delete_selected = QPushButton("删除所选")
        hide_builtins = QPushButton("隐藏内置")
        delete_ai = QPushButton("删除全部 AI 生成")
        rename = QPushButton("重命名")
        for button, icon in (
            (favorite, "fa5s.star"),
            (rename, "fa5s.edit"),
            (delete_selected, "fa5s.trash-alt"),
            (hide_builtins, "fa5s.eye-slash"),
            (delete_ai, "fa5s.trash-alt"),
        ):
            button.setObjectName("studioButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            install_themed_icon(button, icon, "secondary")
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        def update_actions() -> None:
            ids = selected_ids()
            selected = [
                tree.topLevelItem(index)
                for index in range(tree.topLevelItemCount())
                if str(tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole) or "") in ids
            ]
            one = selected[0] if len(selected) == 1 else None
            style_id = str(one.data(0, Qt.ItemDataRole.UserRole) or "") if one else ""
            all_favorite = bool(selected) and all(
                bool(item.data(0, Qt.ItemDataRole.UserRole + 2)) for item in selected
            )
            favorite.setEnabled(bool(ids))
            (bind_text(favorite, '取消收藏') if all_favorite else bind_text(favorite, '收藏'))
            rename.setEnabled(bool(style_id and style_id not in BUILTIN_PRESETS))
            delete_selected.setEnabled(bool(ids))
            export_button.setEnabled(bool(ids) or not view_state["batch"])
            hide_builtins.setEnabled(bool(ids) and all(item in BUILTIN_PRESETS for item in ids))

        def toggle_favorite() -> None:
            ids = selected_ids()
            if not ids:
                return
            metadata = store.load_metadata()
            favorite_builtins = store.favorite_builtin_ids()
            all_favorite = all(
                style_id in favorite_builtins
                if style_id in BUILTIN_PRESETS
                else bool(metadata.get(style_id, {}).get("favorite"))
                for style_id in ids
            )
            state = not all_favorite
            for style_id in ids:
                store.set_favorite(style_id, state)
            refresh()
            self._refresh_style_presets(ids[0] if len(ids) == 1 else "")

        tree.itemSelectionChanged.connect(update_actions)
        tree.itemChanged.connect(
            lambda *_args: update_actions() if not view_state["loading"] else None
        )
        favorite.clicked.connect(toggle_favorite)

        def after_mutation(selected_id: str = "") -> None:
            refresh()
            self._refresh_style_presets(selected_id)

        def delete_checked() -> None:
            count = store.delete_many(selected_ids())
            after_mutation()
            self._show_studio_hint((tr('已删除 {value0} 个预设', value0=count) if count else tr('没有选中可删除的预设')))

        def hide_selected_builtins() -> None:
            ids = [style_id for style_id in selected_ids() if style_id in BUILTIN_PRESETS]
            for style_id in ids:
                store.hide_builtin(style_id)
            after_mutation()
            self._show_studio_hint(tr('已隐藏 {value0} 个内置预设', value0=len(ids)))

        def delete_all_ai() -> None:
            if not bool(delete_ai.property("confirmDeleteAll")):
                delete_ai.setProperty("confirmDeleteAll", True)
                bind_text(delete_ai, '再次点击确认删除全部 AI')
                QTimer.singleShot(5000, lambda: (delete_ai.setProperty("confirmDeleteAll", False), bind_text(delete_ai, '删除全部 AI 生成')))
                return
            delete_ai.setProperty("confirmDeleteAll", False)
            count = store.delete_all_ai(keep_favorites=False)
            bind_text(delete_ai, '删除全部 AI 生成')
            after_mutation()
            self._show_studio_hint(tr('已删除 {value0} 个 AI 预设', value0=count))

        def rename_current() -> None:
            style_id = current_user_id()
            if not style_id:
                self._show_studio_hint(tr('请选择一个自定义或 AI 预设'))
                return
            style = store.load_user().get(style_id)
            name, accepted = QInputDialog.getText(self, tr('重命名预设'), tr('名称'), text=style.name if style else "")
            if accepted and str(name).strip():
                store.rename(style_id, str(name))
                after_mutation(style_id)

        def export_selected() -> None:
            path, _ = QFileDialog.getSaveFileName(self, tr('导出样式预设'), "2byteasr-style-presets.json", "JSON (*.json)")
            if path:
                count = store.export_file(path, selected_ids() or None)
                self._show_studio_hint(tr('已导出 {value0} 个预设', value0=count))

        def import_presets() -> None:
            path, _ = QFileDialog.getOpenFileName(self, tr('导入样式预设'), "", "JSON (*.json)")
            if path:
                try:
                    count = store.import_file(path)
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    studio_message_box(self, QMessageBox.Icon.Warning, tr('导入失败'), str(exc))
                    return
                after_mutation()
                self._show_studio_hint(tr('已导入 {value0} 个预设', value0=count))

        delete_selected.clicked.connect(delete_checked)
        hide_builtins.clicked.connect(hide_selected_builtins)
        delete_ai.clicked.connect(delete_all_ai)
        rename.clicked.connect(rename_current)
        export_button.clicked.connect(export_selected)
        import_button.clicked.connect(import_presets)
        restore_builtins.clicked.connect(
            lambda: (
                self._show_studio_hint(tr('已恢复 {value0} 个内置预设', value0=store.restore_builtins())),
                after_mutation(),
            )
        )
        delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), content)
        delete_shortcut.activated.connect(delete_checked)
        def select_all_visible() -> None:
            if view_state["batch"]:
                view_state["loading"] = True
                try:
                    for index in range(tree.topLevelItemCount()):
                        tree.topLevelItem(index).setCheckState(0, Qt.CheckState.Checked)
                finally:
                    view_state["loading"] = False
                update_actions()
            else:
                tree.selectAll()

        tree.select_all_requested.connect(select_all_visible)
        refresh()
        update_actions()
        self._style_preset_manager = content
        self._style_preset_manager_tree = tree
        self._style_preset_manager_search = search
        self._style_preset_manager_filters = filter_buttons
        self._style_preset_manager_favorite = favorite
        self._style_preset_manager_batch_toggle = batch_toggle
        self._style_preset_manager_hide_builtins = hide_builtins
        modal = getattr(host, "_modal_host", None)
        if modal is not None:
            modal.show_content(content, title="管理样式预设", size=(760, 650), min_size=(620, 520))

    def _selected_style_source(self, *, use_cue_style: bool = True):
        return self.style_controller._selected_style_source(use_cue_style=use_cue_style)

    def _load_style_inspector(
        self,
        _index: int = -1,
        *,
        selected_ids: set[str] | None = None,
        selection_scope: SelectionScope | None = None,
    ) -> None:
        return self.style_controller._load_style_inspector(
            _index,
            selected_ids=selected_ids,
            selection_scope=selection_scope,
        )

    def _apply_mixed_style_display(
        self,
        fallback_style,
        *,
        selected_ids: set[str] | None = None,
        selection_scope: SelectionScope | None = None,
    ) -> None:
        return self.style_controller._apply_mixed_style_display(
            fallback_style,
            selected_ids=selected_ids,
            selection_scope=selection_scope,
        )

    def _style_from_controls(self, source):
        return self.style_controller._style_from_controls(source)

    def _style_control_changed(self, *_args) -> None:
        return self.style_controller._style_control_changed(*_args)

    def _glow_toggled(self, enabled: bool) -> None:
        return self.style_controller._glow_toggled(enabled)

    def _scope_changed(self, *_args) -> None:
        return self.style_controller._scope_changed(*_args)

    def _refresh_style_preview(self) -> None:
        return self.style_controller._refresh_style_preview()

    def _update_style_dirty_label(self) -> None:
        return self.style_controller._update_style_dirty_label()

    def _style_target_ids(self) -> list[str]:
        return self.style_controller._style_target_ids()

    def _copy_subtitle_style(self) -> None:
        return self.style_controller._copy_subtitle_style()

    def _paste_subtitle_style(self) -> None:
        return self.style_controller._paste_subtitle_style()

    def _apply_style(self, *, replace_preset: bool = False) -> None:
        with self._interaction_runtime_audit.measure("Preset" if replace_preset else "Style"):
            return self.style_controller._apply_style(replace_preset=replace_preset)

    def _preset_activated(self, index: int) -> None:
        return self.style_controller._preset_activated(index)

    def _preset_index_changed(self, index: int) -> None:
        return self.style_controller._preset_index_changed(index)

    def _sync_outline2_controls(self, enabled: bool) -> None:
        return self.style_controller._sync_outline2_controls(enabled)
