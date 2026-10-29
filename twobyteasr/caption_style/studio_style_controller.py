"""Style and motion orchestration for Subtitle Studio."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Mapping

from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from .studio_font_combo import LazyFontComboBox

from ..i18n import bind_text, tr

# Style panel layers (Codex 2026-10-24; Chinese-source catalog keys since 2026-10-25).
LAYER_TITLES = {"original": "原文", "translation": "译文", "group": "整组"}


class _PromptEdit(QPlainTextEdit):
    """二十八轮：AI 修改意见输入框——多行大输入（用户要求"更明显+更大"）。

    兼容 QLineEdit 的 .text()/.setText() 消费方（ai_flow 意见汇总/测试）。
    """

    def text(self) -> str:  # noqa: D102 - QLineEdit API 兼容
        return self.toPlainText()

    def setText(self, value: str) -> None:  # noqa: D102
        self.setPlainText(str(value or ""))

from .effect_dsl import (
    EASING_PRESETS,
    POSITION_EFFECT_TYPES,
    builtin_effects,
    preset_effect,
    validate_effect,
)
from .motion_library import MotionPreset, MotionPresetStore
from ..caption_design.studio_ai import AIDesignSuggestion
from ..projects.studio_project import SubtitleStyle
from ..timeline.studio_commands import (
    MutationOrigin,
    SetCuePresentationCommand,
    SetCuesPresentationCommand,
    cue_by_id,
)
from .font_system import resolve_style_font
from .style_resolution import appearance_overrides_for_style, resolve_cue_visual
from ..design.studio_theme import (
    MOTION_UI_PRESETS,
    STYLE_FIELD_HEIGHT,
    StudioComboBox,
    apply_secondary_surface_theme,
    create_studio_menu,
)
from ..studio.studio_widgets import ScrubDoubleSpinBox, ScrubSpinBox
from .style_presets import BUILTIN_PRESETS, StylePresetStore
from .style_recipe import (
    FillSpec,
    MOTION_MODE_EXPLICIT,
    StyleRecipe,
    compile_native_recipe,
    motion_mode,
    normalize_glow_contract,
    normalize_motion_contract,
    normalize_shadow_contract,
    route_recipe,
)
from ..timeline.selection_scope import SelectionMode, SelectionScope
from ..design.ui_theme import BORDER_ACTIVE, BORDER_STRONG
from .studio_style_widgets import (
    STYLE_LABEL_GAP,
    STYLE_ROW_INSET,
    ElidedComboBox,
    StyleGridLabel,
    StyleLabelColumn,
)
from ..design.controls import (
    AngleDisc,
    CompactNumericField,
    offset_to_polar,
    polar_to_offset,
)


def _sync_background_enable(page, enabled: bool) -> None:
    """Set the background switch without counting it as a user toggle."""
    checkbox = getattr(page, "style_background", None)
    if checkbox is None:
        return
    checkbox.blockSignals(True)
    checkbox.setChecked(bool(enabled))
    checkbox.blockSignals(False)


def _restore_background_from_color(page) -> None:
    """Picking a background color switches the background on."""
    from PySide6.QtGui import QColor

    if getattr(page, "_updating_style_ui", False):
        return
    text = str(getattr(page, "style_back_color", None) and page.style_back_color.text() or "")
    if not QColor(text).isValid():
        return
    _sync_background_enable(page, True)
    page._background_edited = True


def _background_switched(page) -> None:
    """The user flipped the background switch: an edit the graph panel must
    follow (the switch's own toggled connection then commits it)."""
    if not getattr(page, "_updating_style_ui", False):
        page._background_edited = True


def _refresh_appearance_summaries(page) -> None:
    """Keep the five Appearance property-row summaries scannable."""
    rows = getattr(page, "_appearance_rows", None)
    if not rows:
        return

    def compact_hex(value: str) -> str:
        color = QColor(str(value or "#FFFFFF"))
        if not color.isValid():
            return str(value or "-")
        return color.name(QColor.NameFormat.HexRgb).upper()

    spec = getattr(page, "_fill_spec", None)
    if spec is not None:
        if spec.kind == "solid":
            rows["fill"].set_summary(tr("纯色 {color}", color=compact_hex(spec.color)))
            rows["fill"].set_chip_colors([spec.color])
        else:
            kind_label = "径向渐变" if spec.kind == "radial-gradient" else "线性渐变"
            colors = [str(stop.get("color", "#FFFFFF")) for stop in spec.stops]
            angle = float(getattr(spec, "angle", 0) or 0)
            rows["fill"].set_summary(tr("{kind} · {count}色 · {angle:.0f}°", kind=tr(kind_label), count=len(colors), angle=angle))
            rows["fill"].set_chip_colors(colors)

    outline_width = float(page.style_outline_width.value())
    if outline_width <= 0:
        rows["outline"].set_summary(tr("已关闭"))
        rows["outline"].set_chip_colors([])
    else:
        outline_color = str(page.style_outline_color.text() or "#000000")
        chips = [outline_color]
        summary = f"{compact_hex(outline_color)} · {outline_width:g}"
        if getattr(page, "style_outline2", None) is not None and page.style_outline2.isChecked():
            second_color = str(page.style_outline2_color.text() or "#FFFFFF")
            second_width = float(page.style_outline2_width.value())
            if second_width > 0:
                summary = tr("双层 {color} · {width:g} + {second_color} · {second_width:g}", color=compact_hex(outline_color), width=outline_width, second_color=compact_hex(second_color), second_width=second_width)
                chips.append(second_color)
        rows["outline"].set_summary(summary)
        rows["outline"].set_chip_colors(chips)

    if page.style_background.isChecked():
        back_color = str(page.style_back_color.text() or "#000000")
        rows["background"].set_summary("开启")
        rows["background"].set_chip_colors([back_color])
    else:
        rows["background"].set_summary(tr("已关闭"))
        rows["background"].set_chip_colors([])

    shadow = float(page.style_shadow.value())
    if hasattr(page, "style_shadow_opacity"):
        opacity = float(page.style_shadow_opacity.value())
        blur = float(page.style_shadow_blur.value())
        angle, distance = offset_to_polar(
            page.style_shadow_offset_x.value(), page.style_shadow_offset_y.value()
        )
        shadow_on = opacity > 0 and (blur > 0 or shadow > 0 or distance > 0)
        rows["shadow"].set_summary(
            tr("不透明度 {opacity:g}% · 距离 {distance:.0f}px · 模糊 {blur:g}px", opacity=opacity, distance=distance, blur=blur)
            if shadow_on else tr("已关闭")
        )
        shadow_color = str(page.style_shadow_color.text() or "#FF000000") if hasattr(page, "style_shadow_color") else "#FF000000"
        rows["shadow"].set_chip_colors([shadow_color] if shadow_on else [])
    else:
        rows["shadow"].set_summary(tr("黑色 · {shadow:g}", shadow=shadow) if shadow > 0 else tr("已关闭"))

    if page.style_glow.isChecked():
        glow_color = str(page.style_glow_color.text() or "#FF0000")
        rows["glow"].set_summary(f"{compact_hex(glow_color)} · {float(page.style_glow_strength.value()):g}")
        rows["glow"].set_chip_colors([glow_color])
    else:
        rows["glow"].set_summary(tr("已关闭"))
        rows["glow"].set_chip_colors([])
    sync_shadow = getattr(page, "_sync_shadow_switch", None)
    if callable(sync_shadow):
        sync_shadow()


class StudioStyleController:
    """Coordinate Style/Motion UI against canonical ``StudioSession`` state."""

    __slots__ = ("page", "session", "_preset_apply_marker", "_edit_draft", "_motion_workflow", "_control_baseline")

    def __init__(self, page, session):
        self.page = page
        self.session = session
        self._preset_apply_marker = None
        self._edit_draft = None
        self._control_baseline = None


    def _apply_ai_style_draft(self) -> None:
        page = self.page
        draft = getattr(page, "_ai_style_draft", None)
        if draft is None or not self.session.project or not self.session.selected_cue_id:
            return
        page._apply_style_recipe(self.session.selected_cue_id, draft)

    def _style_panel_p213(self) -> QWidget:
        steps = self._style_panel_steps()
        while True:
            try:
                next(steps)
            except StopIteration as done:
                return done.value

    def _style_panel_steps(self):
        page = self.page
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 12)
        layout.setSpacing(6)
        page._updating_style_ui = False
        page._style_debounce_timer = page._new_style_timer()
        page._style_debounce_timer.setSingleShot(True)
        page._style_debounce_timer.setInterval(180)
        page._style_debounce_timer.timeout.connect(page._commit_style_now)

        panel_header = QFrame()
        panel_header.setObjectName("stylePanelHeader")
        panel_header_layout = QVBoxLayout(panel_header)
        panel_header_layout.setContentsMargins(4, 5, 4, 7)
        panel_header_layout.setSpacing(1)
        panel_header_title = QLabel("字幕样式")
        panel_header_title.setObjectName("stylePanelHeaderTitle")
        panel_header_meta = QLabel("自动预览 · 默认应用到当前字幕")
        panel_header_meta.setObjectName("stylePanelHeaderMeta")
        panel_header_layout.addWidget(panel_header_title)
        panel_header_layout.addWidget(panel_header_meta)
        panel_header.hide()

        # 2026-10-09 (M16, user): less vertical waste — the apply scope
        # (used constantly) leads, the preview is slimmer and shows the
        # selected line ("Aa" switches to the sample), presets are one row
        # and every appearance property is one line.
        # 2026-10-17 (user: "文字元素不太整齊"): one label column for the
        # whole tab. Labels outside a section start at the section headers
        # and end where the in-section labels end, so every control (scope
        # chips, preset, font, swatches) starts on the same vertical line.
        page._style_label_column = label_column = StyleLabelColumn()

        def outer_label(text: str) -> QLabel:
            return label_column.add(StyleGridLabel(text), extra=STYLE_ROW_INSET)

        def section_label(text: str) -> QLabel:
            return label_column.add(StyleGridLabel(text))

        def grid_width(field: QWidget, minimum: int) -> None:
            # prepare_controls() would pin 80 px spin boxes and 180 px combos
            # here; with the label column 字号/字距/B I U and 预设/样式库 then
            # overlap at the default panel width.
            field.setProperty("fieldWidth", "styleGrid")
            field.setProperty("controlSize", "compact")
            field.setMinimumWidth(minimum)

        def in_control_column(widget: QWidget, *, extra: int = 0) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            row.addWidget(label_column.control_indent(extra=extra))
            row.addWidget(widget, 1)
            return row

        scope_card = QFrame()
        scope_card.setObjectName("styleScopeBar")
        scope_layout = QVBoxLayout(scope_card)
        scope_layout.setContentsMargins(6, 0, 6, 0)
        scope_layout.setSpacing(4)
        scope_row = QHBoxLayout()
        scope_row.setContentsMargins(0, 0, 0, 0)
        scope_row.setSpacing(STYLE_LABEL_GAP)
        scope_caption = outer_label("应用到")
        scope_row.addWidget(scope_caption)
        page.style_scope = page._new_style_scope_selector()
        page.style_scope.addItem("当前字幕", "current")
        page.style_scope.addItem("已选择字幕", "selected")
        page.style_scope.addItem("当前说话人", "speaker")
        page.style_scope.addItem("全部字幕", "all")
        page.style_scope.set_single_row({"current": "当前", "selected": "已选", "speaker": "说话人", "all": "全部"})
        page.style_scope.setCurrentIndex(max(0, page.style_scope.findData("selected")))
        bind_text(page.style_scope, '选择后，后续样式调整会自动作用于该范围', property='toolTip')
        scope_row.addWidget(page.style_scope, 1)
        scope_layout.addLayout(scope_row)
        page.style_apply_geometry = QCheckBox("套用预设时包含位置与缩放")
        page.style_apply_geometry.setObjectName("styleInlineCheck")
        page.style_apply_geometry.setChecked(False)
        bind_text(page.style_apply_geometry, '勾选后，批量应用样式时同步应用当前的位置、边距与缩放；关闭则保留每条字幕各自的几何。', property='toolTip')
        # Under the scope chips it qualifies (control column).
        scope_layout.addLayout(in_control_column(page.style_apply_geometry, extra=STYLE_ROW_INSET))
        layout.addWidget(scope_card)

        page.style_preview = page._new_style_preview()
        page.style_preview.setObjectName("stylePreview")
        page.style_preview.setMinimumHeight(54)
        page.style_preview.setMaximumHeight(60)
        page.style_preview.enable_sample_toggle()
        layout.addWidget(page.style_preview)
        # 2026-10-18 (user): the video layer already shows the caption; the
        # sample only pushed 外观 down. Kept (hidden) because the motion
        # preview copies its shadow / glow state.
        page.style_preview.hide()

        yield '字幕预览'
        advanced_card, advanced_layout = page._style_section("复杂视觉效果")
        advanced_top = QHBoxLayout()
        page.advanced_style_badge = QLabel("高保真")
        page.advanced_style_badge.setStyleSheet("background:#e8e1f2;color:#5f4b7e;border:1px solid #cbbdde;border-radius:9px;padding:2px 8px;font-weight:750")
        page.advanced_style_status = QLabel()
        page.advanced_style_status.setObjectName("cardMeta")
        advanced_top.addWidget(page.advanced_style_badge)
        advanced_top.addWidget(page.advanced_style_status, 1)
        advanced_layout.addLayout(advanced_top)
        gallery = QHBoxLayout()
        gallery.setSpacing(4)
        for label, prompt in (
            ("Cyberpunk", "赛博朋克 Cyberpunk HUD 多层描边 glow glitch"),
            ("Gaming", "Gaming Impact punch 游戏冲击"),
            ("Soft Neon", "Soft Neon 柔光霓虹 tracking"),
        ):
            button = QPushButton(label)
            button.setObjectName("studioButton")
            button.clicked.connect(lambda _checked=False, value=prompt: page._apply_advanced_gallery_preset(value))
            gallery.addWidget(button, 1)
        advanced_layout.addLayout(gallery)
        page.advanced_saved_host = QWidget()
        page.advanced_saved_layout = QHBoxLayout(page.advanced_saved_host)
        page.advanced_saved_layout.setContentsMargins(0, 0, 0, 0)
        page.advanced_saved_layout.setSpacing(4)
        advanced_layout.addWidget(page.advanced_saved_host)
        page.advanced_style_chips = QLabel("多层 Stroke · Glow · Motion")
        page.advanced_style_chips.setObjectName("cardMeta")
        advanced_layout.addWidget(page.advanced_style_chips)
        page.advanced_preview_image = QLabel("选择高级样式生成低成本缓存预览")
        page.advanced_preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.advanced_preview_image.setMinimumHeight(72)
        page.advanced_preview_image.setMaximumHeight(96)
        page.advanced_preview_image.setStyleSheet("background:#30332f;color:#f1eee6;border:1px solid #555b55;border-radius:7px")
        advanced_layout.addWidget(page.advanced_preview_image)
        preview_controls = QHBoxLayout()
        preview_controls.addWidget(QLabel("预览质量"))
        page.advanced_preview_quality = StudioComboBox()
        for label, value in (
            ("自动", "auto"),
            ("草稿 · 主体 640", "draft"),
            ("标准 · 核心效果 960", "balanced"),
            ("完整 · 全效果 1280", "high"),
        ):
            page.advanced_preview_quality.addItem(label, value)
        bind_text(page.advanced_preview_quality, '仅影响预览。Noita 草稿关闭火星和细纹，标准保留核心炼金层，完整显示全部；采用后后台生成透明缓存，准备好后播放自动使用。文字/样式/时间/位置变化会重新生成，原 HTML 和最终导出保留完整效果。', property='toolTip')
        page.advanced_preview_quality.currentIndexChanged.connect(page._advanced_preview_quality_changed)
        preview_controls.addWidget(page.advanced_preview_quality, 1)
        replay_advanced = QPushButton("▶ 重播效果")
        replay_advanced.clicked.connect(page._replay_advanced_preview)
        preview_controls.addWidget(replay_advanced)
        advanced_layout.addLayout(preview_controls)
        font_row = QHBoxLayout()
        page.advanced_font_status = QLabel("优先使用 Windows 已安装字体")
        page.advanced_font_status.setObjectName("cardMeta")
        font_row.addWidget(page.advanced_font_status, 1)
        advanced_layout.addLayout(font_row)
        advanced_actions = QHBoxLayout()
        page.ai_style_entry = QPushButton("AI 设计字幕样式")
        page.ai_style_entry.setObjectName("studioPrimary")
        bind_text(page.ai_style_entry, '打开 AI 设计，用一句话生成视觉与动效方案', property='toolTip')
        page.ai_style_entry.clicked.connect(page._open_ai_design_from_style)
        advanced_actions.addWidget(page.ai_style_entry)
        page.clear_advanced_button = QPushButton("移除高级样式")
        page.clear_advanced_button.setObjectName("studioButton")
        bind_text(page.clear_advanced_button, '去掉复杂视觉与动效，恢复普通字幕预览', property='toolTip')
        page.clear_advanced_button.clicked.connect(page._clear_advanced_style)
        advanced_actions.addWidget(page.clear_advanced_button)
        advanced_layout.addLayout(advanced_actions)
        # ---- 特效字幕调整（十六轮用户指定；二十七轮重排）--------------------
        # AI 特效字幕的外观不走实时改值：这里选的字体/字号/颜色会汇总成
        # 修改意见发给 AI 重绘主题；可按范围批量修改/套用。仅当当前 cue 是
        # 特效字幕时显示（_update_web_adjust_visibility 同时隐藏下方原生
        # 参数分区——那些对 web cue 无效，旧版同屏挤成一团）。
        # 二十七轮布局原则（用户反馈"太挤没重点，第一眼看不知道怎么操作"；
        # agy 可用性复审后定稿）：主题身份头（含作用对象）→ 唯一橙色主按钮
        # （工坊）→ 快速修改一行（输入+发送，次级样式）→ 修改意见回显 →
        # 范围/套用/恢复（操作闭环必须留在折叠区之上——展开快速调整也不
        # 会把它们推出滚动视口）→ 最后才是折叠的参数快速调整。
        yield '高级字幕样式'
        web_card, web_layout = page._style_section("AI 特效字幕调整")
        page.web_adjust_identity = QLabel("当前特效：—")
        page.web_adjust_identity.setObjectName("cardMeta")
        page.web_adjust_identity.setWordWrap(True)
        web_layout.addWidget(page.web_adjust_identity)
        page.web_adjust_workshop = QPushButton("打开 AI 字幕工坊…（对话式精修）")
        page.web_adjust_workshop.setObjectName("studioButton")
        page.web_adjust_workshop.setMinimumHeight(38)
        bind_text(page.web_adjust_workshop, '预览当前字幕的真实特效动画，用自然语言和 AI 对话式修改；也可双击视频画面直接进入', property='toolTip')
        page.web_adjust_workshop.clicked.connect(page._open_web_theme_workshop)
        web_layout.addWidget(page.web_adjust_workshop)
        # 二十八轮（用户反馈）：输入框更大更明显——多行输入+通栏发送按钮；
        # 整卡纵向 Expanding+尾部 stretch，卡片刚好占满工具面板高度。
        web_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        page.web_adjust_extra = _PromptEdit()
        bind_text(page.web_adjust_extra, '对 AI 说：要改什么？\n例如：主色改成枪灰、背景更透明、入场更快', property='placeholderText')
        page.web_adjust_extra.setMinimumHeight(72)
        page.web_adjust_extra.setMaximumHeight(150)
        page.web_adjust_extra.setTabChangesFocus(True)
        page.web_adjust_extra.textChanged.connect(
            lambda: page._assemble_web_adjust_opinion()
        )
        web_layout.addWidget(page.web_adjust_extra)
        page.web_adjust_send = QPushButton("发送修改给 AI")
        # 二十八轮（agy 二审）：发送=唯一橙色主按钮——它与大输入框是一个
        # 操作单元；工坊降为次级（仍在首位、通栏、够醒目）。
        page.web_adjust_send.setObjectName("studioPrimary")
        page.web_adjust_send.setMinimumHeight(36)
        page.web_adjust_send.clicked.connect(page._send_web_adjust_request)
        web_layout.addWidget(page.web_adjust_send)
        # 操作闭环（范围/套用/恢复）紧跟发送——意见回显只是反馈文案，
        # 放到所有控件之后，保证折叠区内之上全部可见（agy 二审：截断）。
        web_row2 = QHBoxLayout()
        page.web_adjust_scope = QComboBox()
        bind_text(page.web_adjust_scope, '决定「发送修改」让 AI 重绘哪些字幕，以及「套用此特效到范围」的作用对象；范围里没有特效主题的字幕不会被改动', property='toolTip')
        page.web_adjust_scope.addItem("仅当前特效字幕", "current")
        page.web_adjust_scope.addItem("该说话人的特效字幕", "speaker")
        page.web_adjust_scope.addItem("全部特效字幕", "all")
        web_row2.addWidget(page._style_field("修改范围", page.web_adjust_scope), 2)
        page.web_adjust_apply_all = QPushButton("套用此特效到范围")
        page.web_adjust_apply_all.setObjectName("studioButton")
        bind_text(page.web_adjust_apply_all, '把当前这条特效字幕的主题应用到修改范围内的全部字幕', property='toolTip')
        page.web_adjust_apply_all.clicked.connect(page._apply_web_theme_to_scope)
        web_row2.addWidget(page.web_adjust_apply_all, 1)
        web_layout.addLayout(web_row2)
        page.web_adjust_restore = QPushButton("恢复普通字幕样式")
        page.web_adjust_restore.setObjectName("studioButton")
        bind_text(page.web_adjust_restore, '去掉特效字幕主题，恢复为普通字幕（随时可再从 AI 面板重新生成）', property='toolTip')
        page.web_adjust_restore.clicked.connect(page._clear_advanced_style)
        web_layout.addWidget(page.web_adjust_restore)
        page.web_adjust_opinion = QLabel("")
        page.web_adjust_opinion.setObjectName("contextMeta")
        page.web_adjust_opinion.setWordWrap(True)
        web_layout.addWidget(page.web_adjust_opinion)
        # 折叠的参数快速调整（默认收起——主路径是上面的自然语言修改；
        # 放在卡片末尾，展开也不影响上方的操作闭环）。
        page.web_adjust_quick_toggle = QPushButton("▸ 快速调整：字体 / 字号 / 颜色")
        page.web_adjust_quick_toggle.setObjectName("studioButton")
        page.web_adjust_quick_toggle.setCheckable(True)
        page.web_adjust_quick_host = QWidget()
        quick_layout = QVBoxLayout(page.web_adjust_quick_host)
        quick_layout.setContentsMargins(0, 4, 0, 0)
        quick_layout.setSpacing(6)

        def _toggle_quick_adjust(checked: bool) -> None:
            page.web_adjust_quick_host.setVisible(checked)
            bind_text(page.web_adjust_quick_toggle, '{value0}快速调整：字体 / 字号 / 颜色', value0='▾ ' if checked else '▸ ')

        page.web_adjust_quick_toggle.toggled.connect(_toggle_quick_adjust)
        web_layout.addWidget(page.web_adjust_quick_toggle)
        web_row1 = QHBoxLayout()
        page.web_adjust_font = LazyFontComboBox()
        page.web_adjust_font.setEditable(True)
        page.web_adjust_font.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        bind_text(page.web_adjust_font, '目标字体（发给 AI，不直接生效）', property='toolTip')
        page.web_adjust_font.currentTextChanged.connect(
            lambda _text: page._assemble_web_adjust_opinion()
        )
        # 字体名列给两倍伸缩（长字体名不被压缩截断），字号/颜色固定窄列。
        web_row1.addWidget(page._style_field("目标字体", page.web_adjust_font), 2)
        page._web_adjust_color_value = "#FFFFFF"
        page.web_adjust_size = QSpinBox()
        page.web_adjust_size.setRange(20, 160)
        page.web_adjust_size.setValue(58)
        bind_text(page.web_adjust_size, '目标字号（发给 AI，不直接生效）', property='toolTip')
        page.web_adjust_size.valueChanged.connect(
            lambda _value: page._assemble_web_adjust_opinion()
        )
        web_row1.addWidget(page._style_field("目标字号", page.web_adjust_size), 1)
        page.web_adjust_color = QPushButton("文字颜色 #FFFFFF")
        page.web_adjust_color.setObjectName("studioButton")

        def _pick_web_color():
            dialog = page._create_style_color_dialog(page.web_adjust_color)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                color = dialog.selectedColor()
                if color.isValid():
                    page._web_adjust_color_value = color.name(
                        QColor.NameFormat.HexRgb
                    ).upper()
                    bind_text(page.web_adjust_color, '文字颜色 {value0}', value0=page._web_adjust_color_value)
                    page._assemble_web_adjust_opinion()

        page.web_adjust_color.clicked.connect(_pick_web_color)
        web_row1.addWidget(page._style_field("颜色", page.web_adjust_color), 1)
        quick_layout.addLayout(web_row1)
        web_hint = QLabel(
            "字体/字号/颜色会作为修改意见发给 AI 重绘主题，不会直接改字幕；"
            "也可直接在上方输入自然语言。"
        )
        web_hint.setObjectName("contextMeta")
        web_hint.setWordWrap(True)
        quick_layout.addWidget(web_hint)
        page.web_adjust_quick_host.hide()
        web_layout.addWidget(page.web_adjust_quick_host)
        # 二十八轮：尾部弹性——卡片纵向占满面板，余量收在折叠区下方而不是
        # 面板底部留白。
        web_layout.addStretch(1)
        web_card.hide()
        page.web_adjust_host = web_card
        layout.addWidget(advanced_card)
        advanced_card.hide()
        layout.addWidget(web_card)
        page._update_advanced_style_status({})
        page._refresh_saved_ai_styles()

        yield '特效调整'
        preset_card = QFrame()
        preset_card.setObjectName("styleInlineSection")
        preset_layout = QVBoxLayout(preset_card)
        preset_layout.setContentsMargins(6, 2, 6, 2)
        preset_layout.setSpacing(0)
        page.style_preset = ElidedComboBox()
        bind_text(page.style_preset, '选择或管理字幕样式预设', property='toolTip')
        page._refresh_style_presets()
        page.style_preset.currentIndexChanged.connect(page._load_style_inspector)
        # EVERY user-driven index change applies the preset (popup click,
        # wheel, keyboard). Programmatic refreshes run with signals blocked
        # or under _updating_style_ui and stay display-only. `activated`
        # shares the same transaction through a one-shot marker, so a popup
        # click applies exactly once.
        page.style_preset.currentIndexChanged.connect(page._preset_index_changed)
        page.style_preset.activated.connect(page._preset_activated)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(STYLE_LABEL_GAP)
        # A long preset name is elided instead of pushing into 样式库.
        page.style_preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        page.style_preset.setMinimumContentsLength(6)
        grid_width(page.style_preset, 110)
        preset_caption = outer_label("预设")
        preset_row.addWidget(preset_caption)
        preset_row.addWidget(page.style_preset, 1)
        preset_more = QToolButton()
        preset_more.setObjectName("studioTool")
        preset_more.setText("...")
        bind_text(preset_more, '管理样式预设', property='toolTip')
        preset_menu = create_studio_menu(preset_more)
        for caption, slot in (
            ("新建", page._new_style_preset),
            ("复制", page._duplicate_style_preset),
            ("重命名", page._rename_style_preset),
            ("删除", page._delete_style_preset),
            ("保存为新预设", page._duplicate_style_preset),
            ("管理预设", page._open_style_preset_manager),
        ):
            preset_menu.addAction(caption, slot)
        preset_more.setMenu(preset_menu)
        preset_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        page.style_library_button = QPushButton("样式库")
        page.style_library_button.setObjectName("styleLibraryButton")
        bind_text(page.style_library_button, '打开样式库', property='toolTip')
        from ..design.themed_icons import install_themed_icon
        install_themed_icon(page.style_library_button, "fa5s.swatchbook", "accent")
        page.style_library_button.clicked.connect(page._open_style_library)
        preset_row.addWidget(page.style_library_button)
        preset_row.addWidget(preset_more, 0, Qt.AlignmentFlag.AlignVCenter)
        preset_layout.addLayout(preset_row)
        layout.addWidget(preset_card)

        yield '样式预设'
        typography_card, typography_layout = page._style_section("文字")
        # Same insets as a property row's content: labels and right edges
        # line up with 外观 (填充…发光).
        typography_layout.setContentsMargins(STYLE_ROW_INSET, 0, 8, 0)
        page.style_font = page._new_lazy_font_combo()
        page.style_font.setEditable(True)
        page.style_font.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        page.style_font.fontPicked.connect(lambda _family, _weight: page._style_control_changed("font_family"))
        font_row = QHBoxLayout()
        font_row.setSpacing(STYLE_LABEL_GAP)
        font_caption = section_label("字体")
        font_row.addWidget(font_caption)
        # prepare_controls() would cap the combo at 360 px; a wider panel then
        # centred label + combo and broke the label column.
        grid_width(page.style_font, 120)
        font_row.addWidget(page.style_font, 1)
        typography_layout.addLayout(font_row)
        page.style_font_warning = QLabel()
        page.style_font_warning.setWordWrap(True)
        page.style_font_warning.setObjectName("cardMeta")
        page.style_font_warning.hide()
        typography_layout.addWidget(page.style_font_warning)
        text_grid = QGridLayout()
        text_grid.setContentsMargins(0, 0, 0, 0)
        text_grid.setHorizontalSpacing(STYLE_LABEL_GAP)
        page.style_font_size = ScrubSpinBox()
        page.style_font_size.setRange(8, 500)
        page.style_spacing = ScrubSpinBox()
        page.style_spacing.setRange(-100, 200)
        size_caption = section_label("字号")
        spacing_caption = QLabel("字距")
        spacing_caption.setObjectName("styleInlineLabel")
        grid_width(page.style_font_size, 58)
        grid_width(page.style_spacing, 58)
        text_grid.addWidget(size_caption, 0, 0)
        text_grid.addWidget(page.style_font_size, 0, 1)
        text_grid.addWidget(spacing_caption, 0, 2)
        text_grid.addWidget(page.style_spacing, 0, 3)
        text_grid.setColumnStretch(1, 1)
        text_grid.setColumnStretch(3, 1)
        page.style_bold = QToolButton()
        page.style_italic = QToolButton()
        page.style_underline = QToolButton()
        for control, text_value, tip in (
            (page.style_bold, "B", "粗体"),
            (page.style_italic, "I", "斜体"),
            (page.style_underline, "U", "下划线"),
        ):
            control.setObjectName("styleEmphasis")
            control.setText(text_value)
            control.setToolTip(tip)
            control.setCheckable(True)
        emphasis_host = QWidget()
        emphasis_row = QHBoxLayout(emphasis_host)
        emphasis_row.setContentsMargins(0, 0, 0, 0)
        emphasis_row.setSpacing(4)
        emphasis_row.addWidget(page.style_bold)
        emphasis_row.addWidget(page.style_italic)
        emphasis_row.addWidget(page.style_underline)
        text_grid.addWidget(emphasis_host, 0, 4)
        typography_layout.addLayout(text_grid)
        layout.addWidget(typography_card)

        yield '字幕文字'
        appearance_card, appearance_layout = page._style_section("外观")
        page.style_fill_color = page._new_style_color_edit()
        page.style_outline_color = page._new_style_color_edit()
        page.style_back_color = page._new_style_color_edit()
        for editor, placeholder in (
            (page.style_fill_color, "#FFFFFF"),
            (page.style_outline_color, "#000000"),
            (page.style_back_color, "#000000"),
        ):
            editor.setReadOnly(True)
            editor.setPlaceholderText(placeholder)
        page.style_fill_swatch = page._style_color_control(page.style_fill_color)
        page.style_outline_swatch = page._style_color_control(page.style_outline_color)
        page.style_back_swatch = page._style_color_control(page.style_back_color)
        page._fill_spec = FillSpec.solid("#FFFFFFFF")
        page.style_outline_width = ScrubDoubleSpinBox()
        page.style_outline_width.setRange(0.0, 20.0)
        page.style_outline_width.setDecimals(1)
        page.style_outline_width.setSingleStep(0.1)
        page.style_shadow = ScrubDoubleSpinBox()
        page.style_shadow.setRange(0.0, 20.0)
        page.style_shadow.setDecimals(1)
        page.style_shadow.setSingleStep(0.1)
        page.style_shadow_opacity = ScrubDoubleSpinBox(); page.style_shadow_opacity.setRange(0, 100); page.style_shadow_opacity.setDecimals(0); page.style_shadow_opacity.setValue(45)
        page.style_shadow_offset_x = ScrubDoubleSpinBox(); page.style_shadow_offset_x.setRange(-100, 100); page.style_shadow_offset_x.setDecimals(2); page.style_shadow_offset_x.setValue(4)
        page.style_shadow_offset_y = ScrubDoubleSpinBox(); page.style_shadow_offset_y.setRange(-100, 100); page.style_shadow_offset_y.setDecimals(2); page.style_shadow_offset_y.setValue(4)
        page.style_shadow_blur = ScrubDoubleSpinBox(); page.style_shadow_blur.setRange(0, 40); page.style_shadow_blur.setDecimals(0); page.style_shadow_blur.setValue(8)
        page.style_shadow_spread = ScrubDoubleSpinBox(); page.style_shadow_spread.setRange(0, 20); page.style_shadow_spread.setDecimals(0); page.style_shadow_spread.setValue(0)
        # 2026-10-18 (user): background is switched on/off like shadow and glow
        # (was a 透明 button); the switch is the background checkbox itself.
        page.style_background = QCheckBox()
        page.style_background.setObjectName("styleSwitch")
        page.style_fill_button = page.style_fill_swatch.findChild(page._style_color_button_type())
        page.style_outline_button = page.style_outline_swatch.findChild(page._style_color_button_type())
        page.style_back_button = page.style_back_swatch.findChild(page._style_color_button_type())
        page.style_shadow_color = page._new_style_color_edit()
        page.style_shadow_color.setReadOnly(True)
        page.style_shadow_color.setText("#FF000000")
        page.style_shadow_swatch = page._style_color_control(page.style_shadow_color)
        page.style_shadow_button = page.style_shadow_swatch.findChild(page._style_color_button_type())
        bind_text(page.style_background, '开启或关闭字幕背景框；点选背景色也会开启', property='toolTip')
        page.style_glow = QCheckBox("发光")
        bind_text(page.style_glow, '在文字边缘增加柔和光晕，提高高亮和霓虹效果。', property='toolTip')
        page.style_glow_color = page._new_style_color_edit()
        page.style_glow_color.setReadOnly(True)
        page.style_glow_color.setText("#FF0000")
        page.style_glow_color.setPlaceholderText("#FF0000")
        page.style_glow_swatch = page._style_color_control(page.style_glow_color)
        page.style_glow_button = page.style_glow_swatch.findChild(page._style_color_button_type())
        page.style_glow_strength = ScrubDoubleSpinBox()
        page.style_glow_strength.setRange(0.0, 20.0)
        page.style_glow_strength.setDecimals(1)
        page.style_glow_strength.setSingleStep(0.1)
        page.style_glow_strength.setValue(5.0)

        # Five scannable property rows; complex editors expand on click.
        StylePropertyRow = __import__("twobyteasr.studio.studio_ui", fromlist=["StylePropertyRow"]).StylePropertyRow

        # Square color swatches (the color is the control, 2026-10-18).
        swatch_width = STYLE_FIELD_HEIGHT

        def inline_swatch(host):
            # The swatch only (its label would repeat the row's summary).
            host.setFixedSize(swatch_width, swatch_width)
            return host

        fill_row = StylePropertyRow("填充", on_activate=page._open_fill_editor)
        fill_row.set_inline(True, summary=True, expandable=False)
        fill_row.inline_layout().addWidget(inline_swatch(page.style_fill_swatch))
        appearance_layout.addWidget(fill_row)

        outline_row = StylePropertyRow("描边")
        outline_row.set_inline(True, summary=False, expandable=True)
        outline_stack = QVBoxLayout()
        outline_stack.setContentsMargins(0, 0, 0, 0)
        outline_stack.setSpacing(8)
        page.style_outline_swatch.setMinimumHeight(28)
        page.style_outline_width.setMinimumHeight(28)
        page.style_outline_width.setMinimumWidth(64)
        outline_row.inline_layout().addWidget(inline_swatch(page.style_outline_swatch))
        # No 宽度 caption: next to the stroke swatch the number is obviously its width.
        bind_text(page.style_outline_width, '描边宽度', property='toolTip')
        outline_row.inline_layout().addWidget(CompactNumericField(page.style_outline_width, unit="px"))
        layer2 = QHBoxLayout()
        layer2.setSpacing(8)
        page.style_outline2 = QCheckBox("第二层")
        page.style_outline2.setObjectName("styleInlineCheck")
        bind_text(page.style_outline2, '在第一层之上再叠一层描边（例如黑边外套白边）；预览与 Remotion 渲染保持一致', property='toolTip')
        page.style_outline2.setMinimumHeight(28)
        page.style_outline2_color = page._new_style_color_edit()
        page.style_outline2_color.setReadOnly(True)
        page.style_outline2_color.setPlaceholderText("#FFFFFF")
        page.style_outline2_swatch = page._style_color_control(page.style_outline2_color)
        page.style_outline2_button = page.style_outline2_swatch.findChild(page._style_color_button_type())
        page.style_outline2_width = ScrubDoubleSpinBox()
        page.style_outline2_width.setRange(0.0, 20.0)
        page.style_outline2_width.setDecimals(1)
        page.style_outline2_width.setSingleStep(0.1)
        page.style_outline2_swatch.setMinimumHeight(28)
        page.style_outline2_width.setMinimumHeight(28)
        page.style_outline2_width.setMinimumWidth(64)
        layer2.addWidget(page.style_outline2)
        outline_stack.addLayout(layer2)
        page.style_outline2_fields = QWidget()
        layer2_fields = QHBoxLayout(page.style_outline2_fields)
        layer2_fields.setContentsMargins(0, 0, 0, 0)
        layer2_fields.setSpacing(8)
        layer2_fields.addWidget(inline_swatch(page.style_outline2_swatch))
        layer2_fields.addWidget(CompactNumericField(page.style_outline2_width, unit="px"))
        outline_stack.addWidget(page.style_outline2_fields)
        page.style_outline2_fields.hide()
        outline_row.content_layout().addLayout(outline_stack)
        for button in (page.style_outline_button, page.style_outline2_button):
            if button is not None:
                button.setMinimumHeight(28)
                button.setMaximumHeight(16777215)
        appearance_layout.addWidget(outline_row)

        background_row = StylePropertyRow("背景")
        background_row.set_inline(True, summary=False, expandable=False)
        background_editor = background_row.inline_layout()
        background_editor.addWidget(inline_swatch(page.style_back_swatch))
        background_row.set_trailing(page.style_background)
        page.style_background.toggled.connect(lambda _checked: _background_switched(page))
        appearance_layout.addWidget(background_row)

        shadow_row = StylePropertyRow("阴影")
        shadow_row.set_inline(True, summary=True, expandable=True)
        page.style_shadow.hide()
        page.style_shadow_offset_x.hide()
        page.style_shadow_offset_y.hide()
        page.style_shadow_angle = AngleDisc()
        page.style_shadow_angle.scrubStarted.connect(page._begin_style_scrub)
        page.style_shadow_angle.scrubFinished.connect(page._finish_style_scrub)
        page.style_shadow_angle_value = ScrubDoubleSpinBox()
        page.style_shadow_angle_value.setRange(0, 359)
        page.style_shadow_angle_value.setDecimals(0)
        page.style_shadow_angle_value.setValue(45)
        page.style_shadow_angle_value.valueChanged.connect(page.style_shadow_angle.setAngle)
        def sync_angle_number(angle):
            blocker = QSignalBlocker(page.style_shadow_angle_value)
            page.style_shadow_angle_value.setValue(angle % 360)
        page.style_shadow_angle.angleChanged.connect(sync_angle_number)
        page.style_shadow_distance = ScrubDoubleSpinBox()
        page.style_shadow_distance.setRange(0, 140)
        page.style_shadow_distance.setDecimals(0)
        page.style_shadow_distance.setValue(6)
        page._shadow_polar_syncing = False

        def _sync_offsets_from_polar(_page=page) -> None:
            if getattr(_page, "_shadow_polar_syncing", False):
                return
            _page._shadow_polar_syncing = True
            try:
                offset_x, offset_y = polar_to_offset(
                    _page.style_shadow_angle.angle(), _page.style_shadow_distance.value()
                )
                _page.style_shadow_offset_x.setValue(offset_x)
                _page.style_shadow_offset_y.setValue(offset_y)
            finally:
                _page._shadow_polar_syncing = False
            _page._queue_style_commit()

        def _sync_polar_from_offsets(_page=page) -> None:
            if getattr(_page, "_shadow_polar_syncing", False):
                return
            _page._shadow_polar_syncing = True
            try:
                angle, distance = offset_to_polar(
                    _page.style_shadow_offset_x.value(), _page.style_shadow_offset_y.value()
                )
                _page.style_shadow_angle.setAngle(angle)
                _page.style_shadow_distance.setValue(round(distance))
            finally:
                _page._shadow_polar_syncing = False

        page._sync_shadow_polar_from_offsets = _sync_polar_from_offsets
        page.style_shadow_angle.angleChanged.connect(lambda *_args: _sync_offsets_from_polar())
        page.style_shadow_distance.valueChanged.connect(lambda *_args: _sync_offsets_from_polar())
        page.style_shadow_offset_x.valueChanged.connect(lambda *_args: _sync_polar_from_offsets())
        page.style_shadow_offset_y.valueChanged.connect(lambda *_args: _sync_polar_from_offsets())
        # On/off maps onto opacity (0 = no shadow, as the summary already
        # reads it); the last opacity comes back when switched on again.
        page.style_shadow_switch = QCheckBox()
        page.style_shadow_switch.setObjectName("styleSwitch")
        bind_text(page.style_shadow_switch, '开启或关闭阴影', property='toolTip')
        page._shadow_last_opacity = 45.0

        def shadow_enabled(_page=page) -> bool:
            return _page.style_shadow_opacity.value() > 0 and (
                _page.style_shadow_blur.value() > 0 or _page.style_shadow_distance.value() > 0
                or _page.style_shadow.value() > 0)

        def sync_shadow_switch(*_args, _page=page) -> None:
            blocker = QSignalBlocker(_page.style_shadow_switch)
            _page.style_shadow_switch.setChecked(shadow_enabled())
            del blocker

        def toggle_shadow(checked: bool, _page=page) -> None:
            if checked:
                if _page.style_shadow_opacity.value() <= 0:
                    _page.style_shadow_opacity.setValue(_page._shadow_last_opacity or 45)
                if _page.style_shadow_blur.value() <= 0 and _page.style_shadow_distance.value() <= 0:
                    _page.style_shadow_distance.setValue(6)
            else:
                if _page.style_shadow_opacity.value() > 0:
                    _page._shadow_last_opacity = _page.style_shadow_opacity.value()
                _page.style_shadow_opacity.setValue(0)

        page.style_shadow_switch.toggled.connect(toggle_shadow)
        page._sync_shadow_switch = sync_shadow_switch
        # Switches share the rows' trailing slot so every swatch lines up.
        shadow_row.set_trailing(page.style_shadow_switch)
        shadow_row.inline_layout().addWidget(inline_swatch(page.style_shadow_swatch))
        # 2026-10-18 (user): the disc shows and sets the direction itself (its
        # centre reads the angle), so no 方向 box; distance / opacity / blur /
        # spread sit in a 2 x 2 grid beside the disc, as tall as the disc.
        page.style_shadow_angle_value.setParent(shadow_row.content)  # kept for sync, never top-level
        page.style_shadow_angle_value.hide()
        page.style_shadow_angle.setFixedSize(112, 112)
        shadow_grid = QGridLayout()
        shadow_grid.setContentsMargins(0, 0, 0, 0)
        shadow_grid.setHorizontalSpacing(10)
        shadow_grid.setVerticalSpacing(8)
        shadow_grid.addWidget(page.style_shadow_angle, 0, 0, 2, 1, Qt.AlignmentFlag.AlignVCenter)
        for index, (control, label, unit) in enumerate((
            (page.style_shadow_distance, "距离", "px"),
            (page.style_shadow_opacity, "不透明度", "%"),
            (page.style_shadow_blur, "模糊", "px"),
            (page.style_shadow_spread, "扩散", "px"),
        )):
            grid_width(control, 44)
            shadow_grid.addWidget(CompactNumericField(control, label=label, unit=unit), index // 2, 1 + index % 2)
        shadow_grid.setColumnStretch(1, 1)
        shadow_grid.setColumnStretch(2, 1)
        shadow_row.content_layout().addLayout(shadow_grid)
        appearance_layout.addWidget(shadow_row)

        glow_row = StylePropertyRow("发光")
        glow_row.set_inline(True, summary=False, expandable=False)
        page.style_glow.setObjectName("styleSwitch")
        page.style_glow.setText("")
        glow_row.set_trailing(page.style_glow)
        glow_row.inline_layout().addWidget(inline_swatch(page.style_glow_swatch))
        # No 半径 caption (2026-10-18): next to the glow swatch it reads as the radius.
        bind_text(page.style_glow_strength, '发光半径', property='toolTip')
        glow_row.inline_layout().addWidget(CompactNumericField(page.style_glow_strength, unit="px"))
        appearance_layout.addWidget(glow_row)

        page._appearance_rows = {
            "fill": fill_row, "outline": outline_row, "background": background_row,
            "shadow": shadow_row, "glow": glow_row,
        }
        exclusive = [fill_row, outline_row, background_row, shadow_row, glow_row]
        for row in exclusive:
            row.set_exclusive_group(exclusive)
            label_column.add_row(row)
        page.style_outline2.toggled.connect(
            lambda checked, _page=page: _page.style_outline2_fields.setVisible(bool(checked))
        )
        page._refresh_appearance_row_summaries = lambda: _refresh_appearance_summaries(page)
        # 点选背景色即恢复背景框（取消"透明"）——颜色即开关。
        page.style_back_color.textChanged.connect(
            lambda _text, _page=page: _restore_background_from_color(_page)
        )
        for control, signal in (
            (page.style_outline_width, "valueChanged"),
            (page.style_shadow, "valueChanged"),
            (page.style_shadow_opacity, "valueChanged"),
            (page.style_shadow_offset_x, "valueChanged"),
            (page.style_shadow_offset_y, "valueChanged"),
            (page.style_shadow_blur, "valueChanged"),
            (page.style_shadow_spread, "valueChanged"),
            (page.style_background, "toggled"),
            (page.style_glow, "toggled"),
            (page.style_glow_strength, "valueChanged"),
        ):
            getattr(control, signal).connect(lambda *_args, _page=page: _refresh_appearance_summaries(_page))
        page.style_shadow.valueChanged.connect(
            lambda value, _page=page: _page.style_shadow_button.setEnabled(float(value) > 0)
        )
        page.style_glow.toggled.connect(page._glow_toggled)
        layout.addWidget(appearance_card)

        from .motion_inspector_ui import MotionPanel
        page.motion_panel = MotionPanel()
        effect_card = page.motion_panel
        effect_layout = QVBoxLayout(effect_card)
        effect_layout.setContentsMargins(10, 8, 10, 12)
        effect_layout.setSpacing(8)
        page.motion_preview = page._new_style_preview()
        page.motion_preview.setObjectName("motionPreview")
        page.motion_preview.setMinimumHeight(68)
        page.motion_preview.setMaximumHeight(74)
        effect_layout.addWidget(page.motion_preview)
        page.graph_motion_summary = QLabel()
        page.graph_motion_summary.setObjectName("cardMeta")
        page.graph_motion_summary.setWordWrap(True)
        page.graph_motion_summary.hide()
        effect_layout.addWidget(page.graph_motion_summary)
        page.motion_replay_button = replay_motion = QPushButton("播放本条")
        replay_motion.setObjectName("studioButton")
        replay_motion.setIcon(page._style_icon("fa5s.redo-alt"))
        replay_motion.clicked.connect(lambda: page._replay_motion())
        page.motion_library_button = QPushButton("动效预设库…")
        page.motion_library_button.setObjectName("studioButton")
        page.motion_library_button.setIcon(page._style_icon("fa5s.play-circle"))
        page.motion_library_button.clicked.connect(page._open_motion_browser)
        motion_actions = QHBoxLayout()
        motion_actions.setSpacing(6)
        motion_actions.addWidget(replay_motion, 1)
        motion_actions.addWidget(page.motion_library_button, 1)
        effect_layout.addLayout(motion_actions)

        page.motion_preset = StudioComboBox()
        for label, preset_id in (
            ("无", "none"),
            ("AI 动效 / 自定义动效", "visual_graph"),
            ("柔和对白", "soft_dialogue"),
            ("游戏高能", "game_energy"), ("快速弹入", "quick_pop"),
            ("轻盈上浮", "light_float"), ("强调字幕", "emphasis"),
            ("逐词强调", "word_highlight"),
        ):
            page.motion_preset.addItem(label, preset_id)

        page.effect_preset = StudioComboBox()
        for label, effect_id in (
            ("无", "none"),
            ("AI 动效 / 自定义动效", "visual_graph"),
            ("柔和淡入", "soft_fade"),
            ("柔和弹入", "soft_pop"),
            ("快速强调", "punch"),
            ("轻微上浮", "float_up"),
            ("轻落入场", "drop_in"),
            ("柔和滑入", "slide_soft"),
            ("模糊显现", "blur_reveal"),
            ("指定词强调", "emphasis"),
            ("逐词强调", "karaoke_highlight"),
            ("柔和回弹", "bounce_lite"),
            ("兼容 · 淡入淡出", "fade"),
            ("兼容 · 弹出", "pop"),
            ("兼容 · 滑入", "slide"),
            ("兼容 · 缩放", "scale"),
        ):
            page.effect_preset.addItem(label, effect_id)
        # Old effects remain addressable for existing projects without
        # crowding the P25 picker for new users.
        for legacy_id in ("fade", "pop", "slide", "scale"):
            legacy_index = page.effect_preset.findData(legacy_id)
            if legacy_index >= 0:
                page.effect_preset.view().setRowHidden(legacy_index, True)
        for legacy_id in ('karaoke_highlight', 'emphasis', 'blur_reveal', 'visual_graph'):
            page.effect_preset.view().setRowHidden(page.effect_preset.findData(legacy_id), True)
        page.effect_exit = StudioComboBox()
        for label, effect_type in (
            ("无", "none"),
            ("轻微淡出", "soft_fade"),
            ("缩小退出", "scale"),
            ("兼容 · 淡出", "fade"),
        ):
            page.effect_exit.addItem(label, effect_type)
        legacy_exit_index = page.effect_exit.findData("fade")
        if legacy_exit_index >= 0:
            page.effect_exit.view().setRowHidden(legacy_exit_index, True)
        page.effect_duration = ScrubSpinBox()
        page.effect_duration.setRange(1, 4000)
        page.effect_duration.setValue(180)
        page.effect_duration.setSuffix(" ms")
        page.effect_out_duration = ScrubSpinBox()
        page.effect_out_duration.setRange(1, 4000)
        page.effect_out_duration.setValue(140)
        page.effect_out_duration.setSuffix(" ms")
        page.effect_loop = StudioComboBox()
        for label, value in (("无", "none"), ("呼吸", "loop_breathe"), ("漂浮", "loop_float"), ("摇曳", "loop_sway")):
            page.effect_loop.addItem(label, value)
        page.effect_loop_duration = ScrubSpinBox()
        page.effect_loop_duration.setRange(120, 4000)
        page.effect_loop_duration.setValue(1200)
        page.effect_strength = StudioComboBox()
        for label, value in (("轻微", "low"), ("标准", "medium"), ("强烈", "high")):
            page.effect_strength.addItem(label, value)
        page.effect_strength.setCurrentIndex(page.effect_strength.findData("medium"))
        page.effect_curve = StudioComboBox()
        for label, value in (("柔和", "soft"), ("平滑", "smooth"), ("利落", "snappy")):
            page.effect_curve.addItem(label, value)
        effect_grid = QGridLayout()
        effect_grid.setContentsMargins(0, 0, 0, 0)
        effect_grid.setHorizontalSpacing(7)
        effect_grid.setVerticalSpacing(5)
        page.motion_preset.hide()
        effect_grid.addWidget(page._style_field("入场", page.effect_preset), 1, 0)
        effect_grid.addWidget(page._style_field("出场", page.effect_exit), 1, 1)
        effect_grid.addWidget(page._style_field("强度", page.effect_strength), 2, 0)
        effect_grid.addWidget(page._style_field("持续时间", page.effect_duration), 2, 1)
        effect_layout.addLayout(effect_grid)

        page.motion_advanced_button = QToolButton()
        page.motion_advanced_button.setObjectName("styleSectionHeader")
        bind_text(page.motion_advanced_button, '›  高级设置')
        page.motion_advanced_button.setCheckable(True)
        effect_layout.addWidget(page.motion_advanced_button)
        page.motion_advanced = QWidget()
        advanced_grid = QGridLayout(page.motion_advanced)
        advanced_grid.setContentsMargins(0, 0, 0, 0)
        advanced_grid.setHorizontalSpacing(7)
        advanced_grid.setVerticalSpacing(5)
        page.effect_delay = ScrubSpinBox()
        page.effect_delay.setRange(0, 2000)
        page.effect_delay.setSuffix(" ms")
        page.effect_scale = ScrubSpinBox()
        page.effect_scale.setRange(10, 400)
        page.effect_offset_x = ScrubSpinBox()
        page.effect_offset_x.setRange(-1000, 1000)
        page.effect_offset_y = ScrubSpinBox()
        page.effect_offset_y.setRange(-1000, 1000)
        page.effect_blur = ScrubDoubleSpinBox()
        page.effect_blur.setRange(0, 30)
        page.effect_blur.setDecimals(1)
        page.effect_overshoot = ScrubSpinBox()
        page.effect_overshoot.setRange(10, 400)
        page.effect_accel = ScrubDoubleSpinBox()
        page.effect_accel.setRange(0.1, 5.0)
        page.effect_accel.setDecimals(2)
        page.effect_accel.setValue(EASING_PRESETS["soft"])
        for row, (label, control) in enumerate((
            ("曲线", page.effect_curve),
            ("延迟", page.effect_delay), ("起始缩放", page.effect_scale),
            ("水平偏移", page.effect_offset_x), ("垂直偏移", page.effect_offset_y),
            ("模糊", page.effect_blur), ("回弹峰值", page.effect_overshoot),
            ("Easing", page.effect_accel), ("出场时长", page.effect_out_duration),
        )):
            advanced_grid.addWidget(page._style_field(label, control), row // 2, row % 2)
        page.motion_advanced.hide()
        page.motion_advanced_button.toggled.connect(page._toggle_motion_advanced)
        effect_layout.addWidget(page.motion_advanced)
        # Keep controller fields for project hydration / custom presets, while
        # the dedicated inspector owns the visible stage cards and timing UI.
        page.motion_legacy = QWidget(effect_card)
        legacy_layout = QVBoxLayout(page.motion_legacy)
        while effect_layout.count():
            item = effect_layout.takeAt(0)
            if item.widget(): legacy_layout.addWidget(item.widget())
            elif item.layout(): legacy_layout.addLayout(item.layout())
        for control in (page.motion_preset, page.effect_loop, page.effect_loop_duration):
            legacy_layout.addWidget(control)
        page.motion_legacy.hide()
        from .motion_controls_ui import MotionWorkflow
        self._motion_workflow = MotionWorkflow(self, effect_layout)
        page.motion_preview.hide()
        # Existing shortcuts continue to open the dedicated tool page.
        page.motion_jump_button = QPushButton(tr('打开动效'))
        page.motion_jump_button.setParent(panel)
        page.motion_jump_button.hide()
        page.motion_jump_button.clicked.connect(lambda: page.context_drawer.setCurrentIndex(page.motion_tab_index))

        yield '字幕动效'
        position_card, position_layout = page._style_section("高级位置与对齐", expanded=False)
        # 2026-10-24 (user): the per-caption 位置与变换 (原文 / 译文 position,
        # scale, rotation, anchor) lives on the 视频 tab, where clips move;
        # 应用到 leads this tab again.
        page.style_alignment = StudioComboBox()
        for label, value in (
            ("左下", 1), ("居中下", 2), ("右下", 3),
            ("左中", 4), ("居中", 5), ("右中", 6),
            ("左上", 7), ("居中上", 8), ("右上", 9),
        ):
            page.style_alignment.addItem(label, value)
        page.style_anchor_buttons = {}
        # Same label column as 文字 / 外观 (was captions stacked above).
        position_layout.setContentsMargins(STYLE_ROW_INSET, 0, 8, 0)
        alignment_row = QHBoxLayout()
        alignment_row.setSpacing(STYLE_LABEL_GAP)
        alignment_row.addWidget(section_label("对齐"))
        grid_width(page.style_alignment, 120)
        alignment_row.addWidget(page.style_alignment, 1)
        position_layout.addLayout(alignment_row)
        position_grid = QGridLayout()
        position_grid.setContentsMargins(0, 0, 0, 0)
        position_grid.setHorizontalSpacing(STYLE_LABEL_GAP)
        page.style_position_x = ScrubSpinBox()
        page.style_position_y = ScrubSpinBox()
        for control in (page.style_position_x, page.style_position_y):
            control.setRange(0, 16384)
            grid_width(control, 58)
        position_y_caption = QLabel("Y")
        position_y_caption.setObjectName("styleInlineLabel")
        position_grid.addWidget(section_label("X"), 0, 0)
        position_grid.addWidget(page.style_position_x, 0, 1)
        position_grid.addWidget(position_y_caption, 0, 2)
        position_grid.addWidget(page.style_position_y, 0, 3)
        position_grid.setColumnStretch(1, 1)
        position_grid.setColumnStretch(3, 1)
        position_layout.addLayout(position_grid)
        page.position_edit_button = QPushButton("在画面中拖动字幕")
        page.position_edit_button.setObjectName("studioButton")
        page.position_edit_button.setCheckable(True)
        page.position_edit_button.setChecked(True)
        page.position_edit_button.setIcon(page._style_icon("fa5s.arrows-alt"))
        page.position_edit_button.toggled.connect(page._toggle_position_edit)
        position_layout.addLayout(in_control_column(page.position_edit_button))
        margin_row = QGridLayout()
        margin_row.setContentsMargins(0, 0, 0, 0)
        margin_row.setHorizontalSpacing(5)
        margin_row.setVerticalSpacing(5)
        page.style_margin_l = ScrubSpinBox()
        page.style_margin_r = ScrubSpinBox()
        page.style_margin_v = ScrubSpinBox()
        for index, (control, prefix) in enumerate((
            (page.style_margin_l, "左 "),
            (page.style_margin_r, "右 "),
            (page.style_margin_v, "垂直 "),
        )):
            control.setRange(0, 1000)
            control.setPrefix(prefix)
            control.setSuffix(" px")
            grid_width(control, 58)
            margin_row.addWidget(control, index // 2, index % 2)
        margin_row.setColumnStretch(0, 1)
        margin_row.setColumnStretch(1, 1)
        margin_host = QWidget()
        margin_host.setLayout(margin_row)
        position_layout.addLayout(in_control_column(margin_host))
        layout.addWidget(position_card)

        yield '字幕位置'
        current_card, current_layout = page._style_section("当前字幕", expanded=False)
        current_layout.setContentsMargins(STYLE_ROW_INSET, 0, 8, 0)
        page.current_cue_section_button = current_card.findChild(QToolButton, "styleSectionHeader")
        page.cue_text.setMinimumHeight(42)
        page.cue_text.setMaximumHeight(64)
        page.translation_text.setMinimumHeight(42)
        page.translation_text.setMaximumHeight(58)
        page.current_text_layer_label = QLabel(tr("当前操作：原文"))
        current_layout.addWidget(page.current_text_layer_label)
        from ..studio.caption_text_tools import CaptionTextTools
        page.original_text_tools = CaptionTextTools(page, page.cue_text, 'original')
        page.translation_text_tools = CaptionTextTools(page, page.translation_text, 'translation')
        current_layout.addWidget(QLabel(tr("原文")))
        current_layout.addWidget(page.original_text_tools)
        current_layout.addWidget(page.cue_text)
        current_layout.addWidget(QLabel(tr("译文")))
        current_layout.addWidget(page.translation_text_tools)
        current_layout.addWidget(page.translation_text)
        page.translation_style_button = QPushButton(tr("译文显示样式…"))
        from ..studio.studio_bilingual import open_style_dialog
        page.translation_style_button.clicked.connect(lambda: open_style_dialog(page))
        page.translation_style_button.hide()
        current_layout.addWidget(page.translation_style_button)
        current_layout.addWidget(page.editor_metadata)
        layout.addWidget(current_card)
        # 二十七轮：原生参数分区宿主登记——当前 cue 是 AI 特效字幕时整组
        # 隐藏（_update_web_adjust_visibility 反转可见性），面板只留 AI 调整卡。
        page.style_native_hosts = [
            preset_card, typography_card, appearance_card,
            scope_card, position_card, current_card,
        ]

        layout.addStretch(1)

        numeric_fields = {
            "font_size": ("font_size",), "spacing": ("spacing",),
            "margin_l": ("margin_l",), "margin_r": ("margin_r",), "margin_v": ("margin_v",),
            "position_x": ("position_x",), "position_y": ("position_y",),
            "outline_width": ("outline_width",), "outline2_width": ("outline2_width",),
            "shadow": (), "shadow_opacity": ("shadow.opacity",),
            "shadow_offset_x": ("shadow.offset_x",), "shadow_offset_y": ("shadow.offset_y",),
            "shadow_angle_value": ("shadow.offset_x", "shadow.offset_y"),
            "shadow_distance": ("shadow.offset_x", "shadow.offset_y"),
            "shadow_blur": ("shadow.blur_radius",), "shadow_spread": ("shadow.spread",),
            "glow_strength": ("glow.radius",),
        }
        for name, fields in numeric_fields.items():
            control = getattr(page, "style_" + name)
            control.valueChanged.connect(lambda _value, fields=fields: page._queue_style_commit(*fields))
            control.editingFinished.connect(page._commit_style_now)
            # textEdited also covers intermediate input (empty, '-' or '1.').
            # Such input must not be replaced by a selection/preview refresh.
            control.lineEdit().textEdited.connect(lambda _text, fields=fields: page._queue_style_commit(*fields))
            control.scrubStarted.connect(page._begin_style_scrub)
            control.scrubFinished.connect(page._finish_style_scrub)
        page.style_font.lineEdit().textEdited.connect(lambda _text: page._queue_style_commit("font_family"))
        page.style_font.lineEdit().editingFinished.connect(page._commit_style_now)
        for name, fields in (("bold", ("bold",)), ("italic", ("italic",)), ("underline", ("underline",)),
                             ("background", ("border_style",)), ("outline2", ("outline2_width", "outline2_color"))):
            getattr(page, "style_" + name).toggled.connect(
                lambda _checked, fields=fields: page._style_control_changed(*fields))
        page.style_outline2.toggled.connect(page._sync_outline2_controls)
        page.style_alignment.currentIndexChanged.connect(page._sync_style_anchor)
        page.style_alignment.currentIndexChanged.connect(lambda _index: page._style_control_changed("alignment"))
        page.effect_preset.currentIndexChanged.connect(page._effect_changed)
        page.motion_preset.currentIndexChanged.connect(page._motion_preset_changed)
        page.effect_exit.currentIndexChanged.connect(page._motion_control_changed)
        page.effect_strength.currentIndexChanged.connect(page._motion_control_changed)
        page.effect_curve.currentIndexChanged.connect(page._motion_curve_changed)
        page.style_layer = QComboBox()
        for value, title in LAYER_TITLES.items():
            page.style_layer.addItem(title, value)
        scope_layout.addWidget(page.style_layer)
        page.style_scope_summary = QLabel()
        scope_layout.addWidget(page.style_scope_summary)
        page.style_layer.currentIndexChanged.connect(lambda index: self._layer_changed(index))
        page.style_scope.currentIndexChanged.connect(page._scope_changed)
        for compact_control in (
            page.style_preset, page.style_font, page.style_font_size, page.style_spacing,
            page.style_outline_width, page.style_shadow, page.style_shadow_opacity,
            page.style_shadow_offset_x, page.style_shadow_offset_y, page.style_shadow_blur,
            page.style_shadow_angle_value, page.style_shadow_distance,
            page.style_shadow_spread, page.effect_preset,
            page.motion_preset, page.effect_duration, page.effect_exit, page.effect_strength,
            page.effect_curve, page.style_back_button, page.style_fill_button,
            page.style_outline_button, page.style_shadow_button,
            page.style_alignment,
        ):
            compact_control.setFixedHeight(STYLE_FIELD_HEIGHT)
        page.style_scope.setFixedHeight(STYLE_FIELD_HEIGHT - 6)
        page._style_single_shot(0, page._load_style_inspector)
        return panel

    def _set_style_alignment(self, alignment: int) -> None:
        page = self.page
        index = page.style_alignment.findData(int(alignment))
        if index >= 0:
            page.style_alignment.setCurrentIndex(index)

    def _sync_style_anchor(self, _index: int = -1) -> None:
        page = self.page
        alignment = int(page.style_alignment.currentData() or 2)
        for value, button in page.style_anchor_buttons.items():
            button.setChecked(value == alignment)

    def _queue_style_commit(self, *_args) -> None:
        page = self.page
        if page._updating_style_ui or getattr(page, '_shadow_polar_syncing', False):
            return
        targets = tuple(self._style_target_ids())

        self._record_style_fields(_args)
        self._edit_draft = {
            "project": self.session.project,
            "cue_id": self.session.selected_cue_id,
            "targets": targets,
            "layer": page.style_layer.currentData() if hasattr(page, "style_layer") else "original",
            "shadow": self._shadow_from_controls(),
        }
        # Keep the LIVE preview on the pointer/key event path.  The debounced
        # commit below is only for undo/project mutation and Fidelity work.
        page._refresh_style_preview()
        if page._scrub_active:
            page._commit_style_now()
            return
        page._style_debounce_timer.start()

    def _begin_style_scrub(self) -> None:
        page = self.page
        page._style_debounce_timer.stop()
        page._scrub_active = True
        self.session.undo_stack.beginMacro("拖动调整样式")

    def _finish_style_scrub(self) -> None:
        page = self.page
        if not page._scrub_active:
            return
        page._scrub_active = False
        try:
            page._commit_style_now()
        finally:
            self.session.undo_stack.endMacro()

    def _commit_style_now(self) -> None:
        page = self.page
        page._style_debounce_timer.stop()
        draft = self._edit_draft
        if page._updating_style_ui or draft is None:
            return
        for name,control in vars(page).items():
            if (name.startswith('style_') and hasattr(control,'hasAcceptableInput')
                    and control.hasFocus() and not control.hasAcceptableInput()):return
        if draft['project'] is not self.session.project or draft['cue_id'] != self.session.selected_cue_id:
            self._edit_draft = None
            page._load_style_inspector()
            return
        # Keep the one draft alive through Command/Undo's synchronous refresh.
        # The project receives exactly the values the user is still editing.
        try:
            page._style_control_changed()
        finally:
            self._edit_draft = None
        page._load_style_inspector()

    def _effect_changed(self, _index: int = -1) -> None:
        page = self.page
        if page._updating_style_ui:
            return
        effect_id = str(page.effect_preset.currentData() or "none")
        if effect_id == "visual_graph":
            return
        self._load_motion_controls(effect_id, include_other_stages=False)
        page._preview_motion_preset(effect_id)
        page._motion_contract_dirty = True
        page._pending_motion_replay_cue_id = self.session.selected_cue_id
        self._motion_workflow.motion_changed()

    def _motion_preset_changed(self, _index: int = -1) -> None:
        page = self.page
        if page._updating_style_ui:
            return
        if str(page.motion_preset.currentData() or "none") == "visual_graph":
            return
        values = MOTION_UI_PRESETS.get(str(page.motion_preset.currentData() or "none"))
        if values is None:
            return
        page._updating_style_ui = True
        try:
            page._set_combo_data(page.effect_preset, values["entry"])
            page._load_motion_controls(values["entry"])
            page._set_combo_data(page.effect_exit, values["exit"])
            page.effect_duration.setValue(values["duration"])
            page.effect_out_duration.setValue(values["out"])
            page._set_combo_data(page.effect_strength, values["strength"])
            page._set_combo_data(page.effect_curve, values["curve"])
            page.effect_accel.setValue(EASING_PRESETS[values["curve"]])
        finally:
            page._updating_style_ui = False
        effect = page._effect_from_controls(values["entry"])
        page.motion_preview.play_motion(effect)
        page._motion_contract_dirty = True
        page._pending_motion_replay_cue_id = self.session.selected_cue_id
        self._motion_workflow.motion_changed()

    def _open_motion_browser(self) -> None:
        page = self.page
        style = page._selected_style_source(use_cue_style=True)
        if style is None:
            page._show_studio_hint(tr('先选择一条字幕，再打开动效库'))
            return
        motion, preview = self._current_motion_for_library()
        dialog = page._new_motion_browser_dialog(style, page.window(),
            current_motion=motion, current_preview_effect_id=preview)
        dialog.motion_selected.connect(page._apply_motion_library_preset)
        dialog.exec()

    def _current_motion_for_library(self) -> tuple[dict[str, object], str]:
        page = self.page
        if hasattr(self, '_motion_workflow') and page.effect_preset.currentData() != 'visual_graph':
            effect_id = str(page.effect_preset.currentData() or 'none')
            effect = page._effect_from_controls(effect_id)
            effect['word_highlight'] = self._motion_workflow.word_settings()
            return {'nativeEffect': validate_effect(effect)}, effect_id if effect_id in builtin_effects() else 'none'
        cue = self.session._cue_lookup.get(self.session.selected_cue_id)
        payload = self.session.project.style_recipes.get(cue.style_id) if self.session.project and cue else None
        if isinstance(payload, Mapping) and payload:
            recipe = StyleRecipe.from_dict(payload)
            if recipe.visual_graph.get('motionGraph', {}).get('tracks'):
                return {'mode': 'explicit', 'origin': 'visual_graph',
                        'graph': copy.deepcopy(recipe.visual_graph['motionGraph'])}, 'soft_fade'
            if any(key in recipe.motion for key in ("entrance", "hold", "exit")):
                return copy.deepcopy(recipe.motion), "soft_fade"
        effect_id = str(page.effect_preset.currentData() or "none")
        effect = page._effect_from_controls(effect_id)

        def advanced_part(part: Mapping[str, object] | None) -> dict[str, object]:
            value = copy.deepcopy(dict(part or {}))
            if "duration" in value:
                value["duration_ms"] = value.pop("duration")
            return value

        return {
            "entrance": advanced_part(effect.get("entry")),
            "hold": {},
            "exit": advanced_part(effect.get("exit")),
        }, effect_id if effect_id in builtin_effects() else "soft_fade"

    def _apply_motion_library_preset(self, preset_id: str) -> None:
        page = self.page
        preset = MotionPresetStore().all().get(str(preset_id))
        if preset is None or not self.session.project:
            return
        if isinstance(preset.motion.get('nativeEffect'), Mapping):
            effect = validate_effect(preset.motion['nativeEffect'])
            targets = [c.id for c in self._motion_workflow.targets() if self._motion_workflow.supported(c)]
            from .motion_application import motion_command
            from .word_animation import word_part
            command = motion_command(self.session.project, targets, motion=effect,
                words=word_part(effect) or {'type': 'none'}, changed=page._changed,
                language=page.motion_language.currentData())
            if command:
                self.session.undo_stack.push(command)
            page._load_style_inspector()
            return
        if preset.native_effect_id:
            from .word_animation import WORD_MODES
            if preset.native_effect_id in WORD_MODES:
                page._set_combo_data(page.motion_word_mode, preset.native_effect_id)
                from .letter_motion import PRESETS
                if preset.native_effect_id in PRESETS:
                    page._set_combo_data(page.motion_word_color, PRESETS[preset.native_effect_id][2])
                self._motion_workflow.draft_changed()
                self._motion_workflow.apply()
                return
            index = page.effect_preset.findData(preset.native_effect_id)
            if index >= 0:
                page._updating_style_ui = True
                page.effect_preset.setCurrentIndex(index)
                page._load_motion_controls(preset.native_effect_id)
                page._updating_style_ui = False
                page.motion_preview.play_motion(builtin_effects()[preset.preview_effect_id])
                self._motion_workflow.motion_changed()
                self._motion_workflow.apply()
                return
        page._apply_advanced_motion(preset)

    def _apply_advanced_motion(self, preset: MotionPreset) -> None:
        page = self.page
        cue_ids = [c.id for c in self._motion_workflow.targets() if self._motion_workflow.supported(c)]
        if not self.session.project or not cue_ids:
            return
        existing_styles = {style.id: style for style in self.session.project.styles}
        styles = list(self.session.project.styles)
        recipes = dict(self.session.project.style_recipes)
        mapped: dict[str, str] = {}
        effect_ids: dict[str, str] = {}
        effects = dict(self.session.project.effects)
        groups: dict[str, list[str]] = {}
        for cue_id in cue_ids:
            cue = cue_by_id(self.session.project, cue_id)
            groups.setdefault(cue.style_id, []).append(cue_id)
            # A preceding native override must not mask the newly chosen
            # authored motion. Speech timing remains independent.
            from .word_animation import word_part
            clean = validate_effect({'entry': {'type': 'none'}, 'exit': {'type': 'none'},
                                     'word_highlight': word_part(effects.get(cue.effect_id, {}))})
            key = 'cue-motion-' + hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()[:16]
            effects[key] = clean
            effect_ids[cue_id] = key
        for source_id, group_ids in groups.items():
            source = existing_styles.get(source_id)
            if source is None:
                continue
            target_id = f"{source_id}-motion-{preset.id}-{hashlib.sha1(chr(0).join(sorted(group_ids)).encode('utf-8')).hexdigest()[:6]}"
            derived = copy.deepcopy(source)
            derived.id = target_id
            styles = [item for item in styles if item.id != target_id] + [derived]
            source_recipe = recipes.get(source_id)
            if isinstance(source_recipe, Mapping):
                recipe = StyleRecipe.from_dict(source_recipe)
            else:
                recipe = page._base_recipe_for_style(source)
            recipe.engine = "remotion"
            recipe.motion = copy.deepcopy(preset.motion)
            recipe.motion['mode'] = 'explicit'
            if recipe.visual_graph or preset.motion.get('graph'):
                from ..caption_design.visual_design_graph import graph_from_style_recipe
                authored = copy.deepcopy(recipe.visual_graph) if recipe.visual_graph else graph_from_style_recipe(recipe).to_dict()
                recipe.visual_graph = {}
                authored['motionGraph'] = copy.deepcopy(preset.motion.get('graph') or
                    graph_from_style_recipe(recipe).to_dict()['motionGraph'])
                recipe.visual_graph = authored
                recipe.motion.update(origin='visual_graph', graph=copy.deepcopy(authored['motionGraph']))
            recipes[target_id] = recipe.to_dict()
            for cue_id in group_ids:
                mapped[cue_id] = target_id
        if not mapped:
            return
        language=page.motion_language.currentData()
        transforms={}
        for cue_id in cue_ids:
            cue=cue_by_id(self.session.project,cue_id)
            transform=copy.deepcopy(cue.transform or {})
            layers=transform.setdefault('language_layers',{})
            translated=layers.setdefault('translation',{})
            prior=transform.get('language_motion',{})
            if language=='original':
                translated.setdefault('style_id',cue.style_id)
                translated_effect=prior.get('translation_effect_id','none')
            else:
                translated['style_id']=mapped[cue_id]
                clean=validate_effect({'entry':{'type':'none'},'exit':{'type':'none'}})
                translated_effect='cue-motion-'+hashlib.sha256(json.dumps(clean,sort_keys=True).encode()).hexdigest()[:16]
                effects[translated_effect]=clean
                if language=='translation':
                    mapped[cue_id]=cue.style_id
                    effect_ids[cue_id]=cue.effect_id
            transform['language_motion']={'linked':language=='linked','translation_effect_id':translated_effect,'word_fallback':'whole_sentence'}
            transforms[cue_id]=transform
        first = cue_by_id(self.session.project, cue_ids[0])
        self.session.undo_stack.push(SetCuesPresentationCommand(
            self.session.project, cue_ids, style_id=mapped[cue_ids[0]], style_ids=mapped,
            effect_id=effect_ids[first.id], effect_ids=effect_ids, styles=styles,
            effects=effects, style_recipes=recipes,transform_overrides=transforms,
            text=f"应用 Motion: {preset.name}", changed=page._changed,
        ))
        page.motion_preview.play_motion(builtin_effects()[preset.preview_effect_id])
        selected_recipe = recipes.get(mapped.get(self.session.selected_cue_id, ""))
        if isinstance(selected_recipe, Mapping):
            page._load_advanced_motion_controls(selected_recipe)
        selected = self.session._cue_lookup.get(self.session.selected_cue_id)
        payload = self.session.project.style_recipes.get(selected.style_id, {}) if selected else {}
        if isinstance(payload, Mapping):
            page._queue_advanced_preview(payload, force=True)
        page._load_style_inspector()

    def _toggle_motion_advanced(self, expanded: bool) -> None:
        page = self.page
        page.motion_advanced.setVisible(bool(expanded))
        bind_text(page.motion_advanced_button, '{value0}  高级设置', value0='⌄' if expanded else '›')

    def _preview_motion_preset(self, effect_id: str) -> None:
        page = self.page
        effect = builtin_effects().get(str(effect_id))
        if effect is not None:
            for preview in (
                getattr(page, "style_preview", None),
                getattr(page, "motion_preview", None),
            ):
                if preview is not None:
                    preview.play_motion(effect)

    def _activate_motion_preset(self, effect_id: str) -> None:
        page = self.page
        index = page.effect_preset.findData(str(effect_id))
        if index < 0:
            return
        if index == page.effect_preset.currentIndex():
            page._load_motion_controls(effect_id)
            page._preview_motion_preset(effect_id)
            page._style_control_changed()
        else:
            page.effect_preset.setCurrentIndex(index)

    def _motion_source(self, effect_id: str) -> dict:
        page = self.page
        if self.session.project and effect_id in self.session.project.effects:
            try:
                return validate_effect(self.session.project.effects[effect_id])
            except (TypeError, ValueError):
                pass
        return copy.deepcopy(preset_effect(effect_id) or builtin_effects()["none"])

    def _load_motion_controls(self, effect_id: str, *, include_other_stages: bool = True) -> None:
        page = self.page
        effect = page._motion_source(effect_id)
        entry = effect.get("entry", {"type": "none"})
        exit_part = effect.get("exit", {"type": "none"})
        loop_part = effect.get("loop", {"type": "none"})
        controls = (
            page.effect_duration, page.effect_out_duration, page.effect_delay,
            page.effect_scale, page.effect_offset_x, page.effect_offset_y,
            page.effect_blur, page.effect_overshoot, page.effect_accel,
            page.effect_exit, page.effect_strength, page.effect_curve,
            page.effect_loop, page.effect_loop_duration,
        )
        for control in controls:
            control.blockSignals(True)
        try:
            active = entry.get("type") != "none"
            page.effect_duration.setEnabled(active)
            page.effect_duration.setValue(int(entry.get("duration", 180)))
            if include_other_stages:
                page.effect_out_duration.setValue(int(exit_part.get("duration", 140)))
                page._set_combo_data(page.effect_loop, loop_part.get("type", "none"))
                page.effect_loop_duration.setValue(int(loop_part.get("duration", 1200)))
            page.effect_delay.setValue(int(entry.get("delay", 0)))
            page.effect_scale.setValue(int(entry.get("scale_from", 100)))
            page.effect_offset_x.setValue(int(entry.get("offset_x", 0)))
            page.effect_offset_y.setValue(int(entry.get("offset_y", 0)))
            page.effect_blur.setValue(float(entry.get("blur", 0)))
            page.effect_overshoot.setValue(int(entry.get("overshoot", 100)))
            page.effect_accel.setValue(float(entry.get("accel", 1.0)))
            if include_other_stages:
                page._set_combo_data(page.effect_exit, str(exit_part.get("type") or "none"))
            page._set_combo_data(page.effect_strength, str(entry.get("strength") or "medium"))
            page._set_combo_data(page.effect_curve, str(entry.get("easing") or "soft"))
        finally:
            for control in controls:
                control.blockSignals(False)

    def _refresh_motion_inspector(self, recipe) -> None:
        page = self.page
        summary = getattr(page, "graph_motion_summary", None)
        if summary is None:
            return
        from .style_recipe import MOTION_SOURCE_VISUAL_GRAPH, motion_source
        from ..caption_design.visual_design_graph import VisualDesignGraph

        payload = recipe.to_dict() if hasattr(recipe, "to_dict") else recipe
        motion = payload.get("motion") if isinstance(payload, Mapping) else {}
        graph_payload = payload.get("visualGraph") if isinstance(payload, Mapping) else {}
        source = motion_source(
            motion if isinstance(motion, Mapping) else {},
            visual_graph=graph_payload if isinstance(graph_payload, Mapping) else {},
        )
        if source != MOTION_SOURCE_VISUAL_GRAPH:
            summary.hide()
            return
        tracks = []
        try:
            graph = VisualDesignGraph.from_dict(graph_payload)
            labels = {
                "x": "位移 X", "y": "位移 Y", "scale": "缩放", "opacity": "透明度",
                "rotation": "旋转", "rgb_offset": "RGB 分离", "slice_offset": "切片位移",
                "scanline_opacity": "扫描线", "flicker": "闪烁", "ray_scale": "射线展开",
                "burst_scale": "爆裂缩放", "shake_x": "震动 X", "shake_y": "震动 Y",
            }
            for track in graph.motion_graph.tracks:
                name = labels.get(track.property, track.property)
                tracks.append(f"• {track.target} · {name}")
            effects = [item.primitive for item in graph.effect_layers]
            decorations = [item.primitive for item in graph.decoration_layers]
        except (TypeError, ValueError):
            tracks = ["• Graph Motion"]
            effects = []
            decorations = []
        extra = []
        if effects:
            extra.append("效果：" + "、".join(effects))
        if decorations:
            extra.append("装饰：" + "、".join(decorations))
        bind_text(summary, '动效 · AI / Graph Motion\n{value0}', value0='\n'.join(tracks[:8] + extra))
        summary.show()
        page._set_combo_data(page.effect_preset, "visual_graph")
        if hasattr(page, "motion_preset"):
            page._set_combo_data(page.motion_preset, "visual_graph")
        page._set_combo_data(page.effect_exit, "none")

    def _load_advanced_motion_controls(self, payload: Mapping[str, object]) -> None:
        page = self.page
        try:
            recipe = StyleRecipe.from_dict(payload)
            motion = recipe.motion
        except (TypeError, ValueError):
            return
        self._refresh_motion_inspector(recipe)
        from .style_recipe import MOTION_SOURCE_VISUAL_GRAPH, motion_source
        if motion_source(motion, visual_graph=recipe.visual_graph) == MOTION_SOURCE_VISUAL_GRAPH:
            return
        entrance = motion.get("entrance", motion.get("entry", {}))
        if not isinstance(entrance, Mapping):
            return
        duration = entrance.get("duration_ms", entrance.get("durationMs", entrance.get("duration", 180)))
        raw_strength = entrance.get("strength", entrance.get("glitch_intensity", 1.0))
        if isinstance(raw_strength, str) and raw_strength in {"low", "medium", "high"}:
            strength = raw_strength
        else:
            try:
                numeric = float(raw_strength)
            except (TypeError, ValueError):
                numeric = 1.0
            strength = "low" if numeric < 0.82 else ("high" if numeric > 1.18 else "medium")
        page.effect_duration.blockSignals(True)
        page.effect_strength.blockSignals(True)
        try:
            page.effect_duration.setValue(max(1, int(duration)))
            page._set_combo_data(page.effect_strength, strength)
        finally:
            page.effect_duration.blockSignals(False)
            page.effect_strength.blockSignals(False)

    def _motion_curve_changed(self, _index: int = -1) -> None:
        page = self.page
        if page._updating_style_ui:
            return
        easing = str(page.effect_curve.currentData() or "soft")
        page.effect_accel.blockSignals(True)
        page.effect_accel.setValue(EASING_PRESETS[easing])
        page.effect_accel.blockSignals(False)
        page._motion_control_changed()

    def _motion_control_changed(self, *_args) -> None:
        page = self.page
        if page._updating_style_ui:
            return
        summary = getattr(page, "graph_motion_summary", None)
        effect_id = str(page.effect_preset.currentData() or "none")
        if effect_id == "visual_graph":
            page._updating_style_ui = True
            page._set_combo_data(page.effect_preset, 'none')
            page._updating_style_ui = False
            effect_id = 'none'
        if summary is not None:
            summary.hide()
        effect = page._effect_from_controls(effect_id)
        for preview in (
            getattr(page, "style_preview", None),
            getattr(page, "motion_preview", None),
        ):
            if preview is not None:
                preview.play_motion(effect)
        page._motion_contract_dirty = True
        page._pending_motion_replay_cue_id = self.session.selected_cue_id
        self._motion_workflow.motion_changed()

    def _effect_from_controls(self, effect_id: str) -> dict:
        page = self.page
        effect = page._motion_source(effect_id)
        entry = copy.deepcopy(effect.get("entry", {"type": effect_id}))
        entry_type = str(entry.get("type") or effect_id)
        entry.update({
            "duration": page.effect_duration.value(),
            "delay": page.effect_delay.value(),
            "easing": str(page.effect_curve.currentData() or "soft"),
            "accel": page.effect_accel.value(),
            "strength": str(page.effect_strength.currentData() or "medium"),
        })
        if entry_type in {"pop", "scale", "soft_pop", "punch", "bounce_lite", "emphasis"}:
            entry["scale_from"] = page.effect_scale.value()
            entry["overshoot"] = page.effect_overshoot.value()
        if entry_type in POSITION_EFFECT_TYPES:
            entry["offset_x"] = page.effect_offset_x.value()
            entry["offset_y"] = page.effect_offset_y.value()
        if entry_type == "blur_reveal":
            entry["blur"] = page.effect_blur.value()
        exit_type = str(page.effect_exit.currentData() or "none")
        if exit_type == "none":
            exit_part = {"type": "none"}
        else:
            exit_part = validate_effect({"type": exit_type})["entry"]
            exit_part["duration"] = (
                page.effect_duration.value()
                if effect_id == "fade" and exit_type == "fade"
                else page.effect_out_duration.value()
            )
            if exit_type == "scale": exit_part["scale_from"] = 65
            exit_part["easing"] = str(page.effect_curve.currentData() or "soft")
            exit_part["accel"] = page.effect_accel.value()
            exit_part["strength"] = str(page.effect_strength.currentData() or "medium")
        payload = {"entry": entry, "exit": exit_part,
                   "loop": {"type": str(page.effect_loop.currentData() or "none"),
                            "duration": page.effect_loop_duration.value(),
                            "strength": str(page.effect_strength.currentData() or "medium")}}
        if "word_highlight" in effect:
            payload["word_highlight"] = copy.deepcopy(effect["word_highlight"])
        return validate_effect(payload)

    def _fill_type_changed(self, _index: int = -1) -> None:
        page = self.page
        if not hasattr(page, "style_fill_type"):
            return
        kind = str(page.style_fill_type.currentData() or "solid")
        gradient = kind in {"linear-gradient", "radial-gradient"}
        page.gradient_editor.setVisible(gradient)
        page.gradient_status.setVisible(gradient)
        if gradient:
            (bind_text(page.gradient_status, '⚡ 复杂视觉 · 自动使用高保真渲染') if kind == 'linear-gradient' else bind_text(page.gradient_status, '⚡ 径向复杂视觉 · 自动使用高保真渲染'))
        page._refresh_style_preview()
        if not page._updating_style_ui:
            page._style_control_changed()

    def _gradient_changed(self, _value: dict) -> None:
        page = self.page
        if page._updating_style_ui:
            return
        page._refresh_style_preview()
        if not getattr(page, "_gradient_scrubbing", False):
            page._style_control_changed()

    def _gradient_scrub_started(self) -> None:
        page = self.page
        page._gradient_scrubbing = True

    def _gradient_scrub_finished(self) -> None:
        page = self.page
        if not getattr(page, "_gradient_scrubbing", False):
            return
        page._gradient_scrubbing = False
        page._style_control_changed()

    def _gradient_color_requested(self, index: int) -> None:
        page = self.page
        if index < 0 or index >= len(page.gradient_editor._stops):
            return
        stop = page.gradient_editor._stops[index]
        editor = QLineEdit(stop.color, page)
        dialog = page._create_style_color_dialog(editor)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.selectedColor()
            if selected.isValid():
                stop.color = selected.name(QColor.NameFormat.HexArgb)
            page.gradient_editor._sync_stop_controls()
            page.gradient_editor.update()
            page.gradient_editor._emit()

    def _current_gradient(self) -> dict | None:
        page = self.page
        spec = getattr(page, "_fill_spec", FillSpec.solid("#FFFFFFFF"))
        return None if spec.kind == "solid" else spec.to_dict()

    def _style_recipe_for_style(self, style, gradient: dict | None) -> dict:
        page = self.page
        fill = gradient if gradient is not None else str(style.primary_color or "#FFFFFFFF")
        shadow = self._shadow_from_controls(style.shadow)
        outline: dict[str, Any] = {
            "color": style.outline_color,
            "width": style.outline_width,
            "shadow": shadow,
        }
        stroke_layers = style.stroke_layers()
        if len(stroke_layers) > 1:
            # Native ASS carries one Outline per style; the layered stack is a
            # Remotion capability, so its presence routes the style there.
            outline["layers"] = stroke_layers
        glow = normalize_glow_contract({
            "enabled": bool(
                getattr(page, "style_glow", None)
                and page.style_glow.isChecked()
            ),
            "color": (
                page.style_glow_color.text()
                if hasattr(page, "style_glow_color")
                else style.outline_color
            ),
            "radius": (
                float(page.style_glow_strength.value())
                if hasattr(page, "style_glow_strength")
                else 0.0
            ),
        })
        recipe = StyleRecipe(
            name=str(style.name or "自定义样式"),
            engine="remotion" if gradient is not None else "native",
            typography={
                "fontFamily": style.font_family, "fontSize": style.font_size,
                "fontWeight": style.font_weight, "fontStyleName": style.font_style_name,
                "fontFile": style.font_file, "fontFaceIndex": style.font_face_index,
                "bold": style.bold, "italic": style.italic, "underline": style.underline,
                "spacing": style.spacing, "scaleX": style.scale_x, "scaleY": style.scale_y,
            },
            layout={
                "alignment": style.alignment, "marginL": style.margin_l,
                "marginR": style.margin_r, "marginV": style.margin_v,
                "positionX": style.position_x, "positionY": style.position_y,
            },
            colors={"fill": fill, "outline": style.outline_color, "background": style.back_color},
            outline=outline,
            background={"enabled": style.border_style == 3, "color": style.back_color},
            motion=self._motion_contract_from_controls(),
            effects={"glow": glow},
        )
        # ASS owns only a scalar hard offset. Opacity, blur and spread require
        # the layered live graph, otherwise the inspector would persist values
        # that the renderer cannot display.
        rich_shadow = bool(
            shadow.get("enabled")
            and (
                float(shadow.get("blur_radius") or 0) > 0
                or float(shadow.get("spread") or 0) > 0
                or abs(float(shadow.get("opacity") or 0) - 1.0) > 0.001
            )
        )
        if rich_shadow:
            from ..caption_design.visual_design_graph import graph_from_style_recipe

            recipe.engine = "remotion"
            recipe.visual_graph = graph_from_style_recipe(recipe).to_dict()
        return recipe.to_dict()

    def _shadow_from_controls(self, fallback: float = 0.0) -> dict[str, Any]:
        page = self.page
        if not hasattr(page, "style_shadow_blur"):
            return normalize_shadow_contract(fallback)
        opacity = float(page.style_shadow_opacity.value()) / 100.0
        offset_x = float(page.style_shadow_offset_x.value())
        offset_y = float(page.style_shadow_offset_y.value())
        blur = float(page.style_shadow_blur.value())
        spread = float(page.style_shadow_spread.value())
        color = str(page.style_shadow_color.text() if hasattr(page, "style_shadow_color") else "#FF000000")
        # 2026-09-02 修复：必须携带 strength（距离主滑条）。此前只传形状字段，
        # 用户仅拉距离时 normalize 判 enabled=False 且 strength=0 →
        # style.shadow=0，ASS Shadow 恒 0（视频层无阴影）。
        strength = float(page.style_shadow.value())
        if strength > 0 and not (offset_x or offset_y):
            offset_x = offset_y = strength
        return normalize_shadow_contract({
            "strength": strength,
            "enabled": strength > 0 or (opacity > 0 and bool(offset_x or offset_y or blur or spread)),
            "color": color or "#FF000000",
            "opacity": opacity,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "blur_radius": blur,
            "spread": spread,
            "strength": max(abs(offset_x), abs(offset_y), blur / 1.5, spread),
        })

    def _motion_contract_from_controls(self) -> dict[str, object]:
        page = self.page
        effect_id = str(page.effect_preset.currentData() or "none")
        effect = page._effect_from_controls(effect_id)

        def advanced_part(part: object) -> dict[str, object]:
            if not isinstance(part, Mapping):
                return {}
            value = copy.deepcopy(dict(part))
            if "duration" in value:
                value["duration_ms"] = value.pop("duration")
            return value

        return normalize_motion_contract({
            "entrance": advanced_part(effect.get("entry")),
            "hold": {},
            "exit": advanced_part(effect.get("exit")),
        })

    def _style_color_control(self, editor: QLineEdit) -> QWidget:
        page = self.page
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        swatch = page._new_style_color_button()
        bind_text(swatch, '选择颜色并输入精确色值', property='toolTip')
        is_fill = editor is getattr(page, "style_fill_color", None)
        swatch.clicked.connect(lambda: page._open_fill_editor() if is_fill else page._open_style_color_dialog(editor))
        if isinstance(editor, page._style_color_edit_type()):
            editor.clicked.connect(lambda: page._open_fill_editor() if is_fill else page._open_style_color_dialog(editor))
        bind_text(editor, '精确颜色值', property='toolTip')
        editor.textChanged.connect(lambda value, button=swatch: page._update_color_swatch(button, value))
        editor.hide()
        layout.addWidget(swatch, 1)
        page._update_color_swatch(swatch, editor.text())
        return host

    def _open_fill_editor(self) -> None:
        page = self.page
        current = getattr(
            page, "_fill_spec",
            FillSpec.solid(page.style_fill_color.text() or "#FFFFFFFF"),
        )
        dialog = page._new_fill_editor_dialog(current.to_dict(), page)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        fill = FillSpec.from_value(dialog.value())
        page._updating_style_ui = True
        try:
            page._fill_spec = fill
            fallback = fill.color if fill.kind == "solid" else str(fill.stops[0].get("color") or "#FFFFFFFF")
            page.style_fill_color.setText(fallback)
            if page.style_fill_button is not None:
                page.style_fill_button.set_fill_value(fill)
        finally:
            page._updating_style_ui = False
        page._refresh_style_preview()
        page._apply_fill_spec(fill)

    def _apply_fill_spec(self, fill: FillSpec) -> None:
        from .scoped_style import style_patch_command
        page = self.page
        if not self.session.project: return
        layer_control = getattr(page, 'style_layer', None)
        fields = {'primary_color': fill.color} if fill.kind == 'solid' else {}
        command = style_patch_command(self.session.project, self._style_target_ids(), fields,
            recipe_patch={'colors': {'fill': fill.to_dict()}},
            layer=layer_control.currentData() if layer_control is not None else 'original', changed=page._changed)
        if command is not None: self.session.undo_stack.push(command)
        page._load_style_inspector()

    def _update_color_swatch(self, button: QToolButton, value: str) -> None:
        page = self.page
        try:
            _refresh_appearance_summaries(page)
        except Exception:
            pass
        color = QColor(value)
        if isinstance(button, page._style_color_button_type()):
            label = "透明" if color.isValid() and color.alpha() == 0 else "白色" if color.isValid() and color.lightness() > 180 else "黑色" if color.isValid() and color.lightness() < 40 else "颜色"
            enabled = True
            if hasattr(page, "style_back_button") and button is page.style_back_button:
                enabled = bool(getattr(page, "style_background", None) and page.style_background.isChecked())
            button.set_color_value(value, label, enabled=enabled)
            return
        fill = color.name(QColor.NameFormat.HexArgb if color.alpha() < 255 else QColor.NameFormat.HexRgb) if color.isValid() else "#ffffff"
        if color.alpha() == 0:
            label = "透明"
        elif color.red() > 238 and color.green() > 238 and color.blue() > 238:
            label = "白"
        elif color.red() < 24 and color.green() < 24 and color.blue() < 24:
            label = "黑"
        else:
            label = "颜色"
        foreground = "#292a27" if color.lightness() > 145 else "#fffefa"
        button.setText(label)
        button.setStyleSheet(
            f"QToolButton {{ background: {fill}; color: {foreground}; border: 1px solid {BORDER_STRONG}; "
            "border-radius: 5px; padding: 0 8px; font-weight: 600; }}"
            f"QToolButton:hover {{ border-color: {BORDER_ACTIVE}; }}"
        )

    def _set_style_color(self, editor: QLineEdit, value: str) -> None:
        page = self.page
        editor.setText(value)
        fields = {page.style_fill_color: "primary_color", page.style_outline_color: "outline_color",
                  page.style_outline2_color: "outline2_color", page.style_back_color: "back_color",
                  page.style_shadow_color: "shadow.color", page.style_glow_color: "glow.color"}
        page._style_control_changed(fields[editor])

    def _open_style_color_dialog(self, editor: QLineEdit) -> None:
        page = self.page
        dialog = page._create_style_color_dialog(editor)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        color = dialog.selectedColor()
        if color.isValid():
            page._set_style_color(editor, color.name(QColor.NameFormat.HexArgb))

    def _create_style_color_dialog(self, editor: QLineEdit):
        page = self.page
        from ..design.color_picker import SimpleColorDialog

        initial = QColor(editor.text())
        dialog = SimpleColorDialog(
            initial if initial.isValid() else QColor("#ffffff"),
            page,
            title="选择字幕颜色",
            common_colors=(
                "#FFFFFF", "#000000", "#FFF4B8", "#F4C86A", "#B9DDFF",
                "#BFE6C5", "#F3B8CE", "#CBB9E8", "#F2A65A",
            ),
        )
        apply_secondary_surface_theme(dialog)
        return dialog

    def _apply_ai_preview(self) -> None:
        page = self.page
        pending_web = getattr(page, "_pending_web_theme", None)
        if (
            pending_web is not None
            and self.session.project
            and self.session.selected_cue_id
        ):
            theme = copy.deepcopy(dict(pending_web.theme))
            target_ids = self._ai_apply_scope_cue_ids()
            if not target_ids:
                return
            applied = 0
            for cue_id in target_ids:
                if self._apply_web_theme(cue_id, copy.deepcopy(theme)):
                    applied += 1
            if applied:
                drafts = getattr(page, '_theme_draft_coordinator', None)
                if drafts is not None and drafts.current is not None:
                    drafts.record_application()
                    drafts._set_phase('APPLIED', '已应用当前草稿')
                # 二十四轮：范围套用后排队条带预热（每条 cue 先后有帧）。
                warm = getattr(page, "_queue_web_strip_warm", None)
                if callable(warm):
                    warm(target_ids)
                scope_label = {
                    1: f"网页主题「{pending_web.name}」已应用到当前字幕",
                }.get(applied) or (
                    f"网页主题「{pending_web.name}」已应用到 {applied} 条字幕"
                )
                page._show_studio_hint(scope_label)
                return
        suggestion = page._pending_suggestion
        if (
            not self.session.project
            or not isinstance(suggestion, AIDesignSuggestion)
            or suggestion.cue_id != self.session.selected_cue_id
        ):
            return
        if not page._apply_style_recipe(suggestion.cue_id, suggestion.recipe):
            return
        page._pending_suggestion = None

    def _ai_apply_scope_cue_ids(self) -> list[str]:
        """Resolve the AI panel's apply-scope combo to target cue ids."""
        page = self.page
        project = self.session.project
        if project is None or not project.cues:
            return []
        combo = getattr(page, "ai_apply_scope", None)
        scope = str(combo.currentData() or "current") if combo is not None else "current"
        selected_id = str(self.session.selected_cue_id or "")
        if scope == "all":
            return [cue.id for cue in project.cues]
        if scope == "speaker":
            from ..timeline.studio_design_target import design_cue
            current = design_cue(project, selected_id)
            if current is None:
                return [selected_id] if selected_id else []
            return [
                cue.id for cue in project.cues
                if cue.speaker_id == current.speaker_id
            ]
        return [selected_id] if selected_id else []

    def _apply_web_theme(self, cue_id: str, theme: dict, *, preserve_overrides=None) -> bool:
        """Apply a web visual theme (HTML+CSS) as an Advanced StyleRecipe.

        The recipe carries the sanitized theme document; the native mirror
        style keeps project interchange working (mpv fallback, old builds)
        using the theme palette while the real rendering goes through the
        Remotion/Chromium pipeline.
        """
        from ..caption_design.web_theme import WebThemeDocument, WebThemeValidationError

        page = self.page
        if not self.session.project:
            return False
        try:
            document = WebThemeDocument.from_dict(dict(theme))
        except (WebThemeValidationError, TypeError, ValueError) as exc:
            if hasattr(page, "advanced_font_status"):
                bind_text(page.advanced_font_status, '⚠ 网页主题无效，未应用：{exc}', exc=exc)
            return False
        if preserve_overrides is None:
            from ..caption_design.theme_draft import canonical_theme
            owner=getattr(page,'_theme_draft_coordinator',None)
            preserve_overrides=bool(owner and getattr(owner,'preserve_manual_overrides',False)
                and owner.project is self.session.project and owner.current
                and owner.current.theme_json==canonical_theme(document.to_dict()))
        mirror = document.native_mirror_style()
        base = (
            page._selected_style_source(use_cue_style=True)
            or self.session.project.styles[0]
        )
        # 十八轮：镜像（mpv 预热近似）字体跟随主题外观——取主题字体栈里
        # 第一个本机已安装的字体名；没有可用的才回退工程当前字体。
        stack = [
            entry.strip().strip('"').strip("'")
            for entry in str(
                (document.appearance or {}).get("fontFamily")
                or mirror.get("font_family") or ""
            ).split(",")
            if entry.strip() and entry.strip().casefold() not in {"monospace", "sans-serif", "serif"}
        ]
        installed_fonts = {family.casefold(): family for family in QFontDatabase.families()}
        theme_font = next(
            (installed_fonts[entry.casefold()] for entry in stack if entry.casefold() in installed_fonts),
            "",
        )
        recipe = StyleRecipe(
            name=document.name,
            engine="remotion",
            typography={
                "fontFamily": theme_font or base.font_family,
                "fontSize": float(mirror.get("font_size", base.font_size)),
                "bold": True,
            },
            colors={
                "fill": mirror["primary_color"],
                "outline": mirror["outline_color"],
                "background": mirror["back_color"],
            },
            outline={
                "color": mirror["outline_color"],
                "width": float(mirror["outline_width"]),
                "layers": [
                    {"color": mirror["outline_color"], "width": float(mirror["outline_width"])},
                    {"color": mirror["outline2_color"], "width": float(mirror["outline2_width"])},
                ],
            },
            web_theme=document.to_dict(),
        )
        applied = self._apply_style_recipe(cue_id, recipe,preserve_overrides=preserve_overrides)
        # Applying a project style must not replace a request-owned draft,
        # including through either range button or after partial application.
        coordinator = getattr(page, '_theme_draft_coordinator', None)
        owns_draft = bool(coordinator is not None and coordinator.current is not None
                          and coordinator.project is page.project)
        if applied and not owns_draft:
            # 2026-09-02：保存最近应用的 web 主题，让 AI 面板的「应用/保存样式」
            # 按钮对网页主题路线可用（应用=套到当前选中 cue；保存=入样式库，
            # 特效字幕库会渲染真实预览卡）。
            from types import SimpleNamespace

            page._pending_web_theme = SimpleNamespace(
                cue_id=str(cue_id),
                theme=document.to_dict(),
                name=str(document.name),
                recipe=copy.deepcopy(recipe),
            )
        return applied

    def _apply_style_recipe(self, cue_id: str, recipe, *, preserve_overrides=False) -> bool:
        page = self.page
        if not self.session.project:
            return False
        from ..caption_design.visual_design_graph import VisualDesignGraph
        graph = recipe.visual_graph if isinstance(recipe.visual_graph, Mapping) else {}
        graph_motion = graph.get("motionGraph", {}) if isinstance(graph, Mapping) else {}
        graph_tracks = (
            graph_motion.get("tracks", []) if isinstance(graph_motion, Mapping) else []
        )
        has_explicit_motion = bool(
            motion_mode(recipe.motion) == MOTION_MODE_EXPLICIT or graph_tracks
        )
        if graph:
            # The stored graph is cue-relative design intent; cue binding is
            # owned by CompiledLiveScene.compile at render time. An invalid
            # graph fails the apply explicitly — never silently store an
            # unvalidated payload.
            try:
                VisualDesignGraph.from_dict(graph).validate()
            except (TypeError, ValueError) as exc:
                if hasattr(page, "advanced_font_status"):
                    bind_text(page.advanced_font_status, '⚠ AI 方案图形无效，未应用：{exc}', exc=exc)
                return False
            recipe.motion = {
                **dict(recipe.motion or {}),
                "mode": "explicit",
                "origin": "visual_graph",
            }
            has_explicit_motion = bool(graph_tracks)
        route = route_recipe(recipe)
        recipe_id = "ai-recipe-" + hashlib.sha1(
            json.dumps(recipe.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        if route.engine != "native":
            # Keep a native-compatible style record for project interchange.
            # Visual ownership suppresses it for this Advanced cue.
            source = copy.deepcopy(page._selected_style_source(use_cue_style=True) or self.session.project.styles[0])
            typography = recipe.typography
            requested_font = str(typography.get("fontFamily", source.font_family))
            source.font_family = requested_font
            source.font_weight = int(typography.get('fontWeight', 0))
            source.font_style_name = str(typography.get('fontStyleName', ''))
            source.font_file = str(typography.get('fontFile', ''))
            source.font_face_index = int(typography.get('fontFaceIndex', 0))
            from .font_metadata import resolve_local_face
            _, warning = resolve_local_face(requested_font, source.font_weight, source.font_style_name,
                                            bool(typography.get('bold', source.bold)),
                                            source.font_file, source.font_face_index)
            if hasattr(page, "advanced_font_status"):
                bind_text(page.advanced_font_status, warning or '字体字面已验证，原始选择保留')
            source.font_size = float(typography.get("fontSize", source.font_size))
            source.bold = bool(typography.get("bold", source.bold))
            source.spacing = float(typography.get("spacing", source.spacing))
            fill = recipe.colors.get("fill", source.primary_color)
            fill_spec = FillSpec.from_value(fill)
            fill_is_solid = fill_spec.kind == "solid"
            if fill_is_solid:
                fill = fill_spec.color
            elif isinstance(fill, Mapping):
                # The native style is only an interchange mirror. Advanced
                # recipes retain their gradient/texture graph as the source
                # of truth while the mirror uses its first visible color.
                stops = fill.get("stops") or []
                fill = (
                    stops[0].get("color", source.primary_color)
                    if stops and isinstance(stops[0], Mapping)
                    else source.primary_color
                )
            source.primary_color = str(fill)
            # Native SubtitleStyle is only an interchange mirror. Gradient
            # recipes stay authoritative; never write the first-stop color
            # back over fill.type / stops / angle.
            if fill_is_solid and isinstance(fill, str) and QColor(fill).isValid():
                source.primary_color = QColor(fill).name(QColor.NameFormat.HexArgb)
                recipe.colors["fill"] = source.primary_color
                if isinstance(recipe.visual_graph, Mapping):
                    graph_copy = copy.deepcopy(dict(recipe.visual_graph))
                    text_layer = graph_copy.get("textLayer")
                    if isinstance(text_layer, dict):
                        text_layer["fill"] = {"type": "solid", "color": source.primary_color}
                    recipe.visual_graph = graph_copy
            elif not fill_is_solid:
                recipe.colors["fill"] = fill_spec.to_dict()
                source.primary_color = str(
                    fill_spec.stops[0].get("color") if fill_spec.stops else source.primary_color
                )
                if isinstance(recipe.visual_graph, Mapping):
                    graph_copy = copy.deepcopy(dict(recipe.visual_graph))
                    text_layer = graph_copy.get("textLayer")
                    if isinstance(text_layer, dict):
                        text_layer["fill"] = fill_spec.to_dict()
                    recipe.visual_graph = graph_copy
            outline = recipe.outline
            if isinstance(outline.get("layers"), list) and outline["layers"]:
                outline = outline["layers"][0]
            source.outline_color = str(outline.get("color", source.outline_color))
            source.outline_width = float(outline.get("width", source.outline_width))
            layers = recipe.outline.get("layers") if isinstance(recipe.outline, Mapping) else None
            if isinstance(layers, list) and len(layers) > 1 and isinstance(layers[1], Mapping):
                source.outline2_color = str(layers[1].get("color", "#FFFFFFFF"))
                source.outline2_width = float(layers[1].get("width", 0) or 0)
            source.id = f"{recipe_id}-style"
            source.name = recipe.name
            plan_style = source
            plan_effect = validate_effect(
                builtin_effects()["pop" if has_explicit_motion else "none"]
            )
            bind_text(page.ai_confidence, warning or '复杂视觉方案已保存；正在生成当前字幕的高保真预览。')
            page.ai_preview.appendPlainText("\n当前字幕的预览与最终视频使用同一视觉配方。")
        else:
            plan = compile_native_recipe(recipe, style_id=f"{recipe_id}-style")
            plan_style = plan.style
            plan_effect = plan.effect
        effect_id = f"{recipe_id}-motion"
        styles = [item for item in self.session.project.styles if item.id != plan_style.id] + [plan_style]
        effects = dict(self.session.project.effects)
        effects[effect_id] = plan_effect
        recipes = dict(self.session.project.style_recipes)
        # The routing lookup is keyed by cue.style_id.  Storing under the
        # recipe hash alone made a freshly applied Advanced recipe reopen as
        # Native and silently skipped Remotion at export time.
        recipes[plan_style.id] = recipe.to_dict()
        page._pending_motion_replay_cue_id = cue_id if has_explicit_motion else ""
        self.session.undo_stack.push(
            SetCuePresentationCommand(
                self.session.project,
                cue_id,
                cue_changes={
                    "style_id": plan_style.id,
                    "base_preset_id": plan_style.id,
                    "appearance_override": copy.deepcopy(cue_by_id(self.session.project,cue_id).appearance_override) if preserve_overrides else {},
                    "effect_id": effect_id,
                },
                styles=styles,
                effects=effects,
                style_recipes=recipes,
                text="Apply AI StyleRecipe",
                changed=page._changed,
                origin=MutationOrigin.LLM,
            )
        )
        page._updating_style_ui = True
        try:
            index = page.style_preset.findData(plan_style.id)
            if index < 0:
                page.style_preset.addItem(f"AI · {recipe.name}", plan_style.id)
                index = page.style_preset.count() - 1
                page._style_preset_base_labels[index] = f"AI · {recipe.name}"
            page.style_preset.setCurrentIndex(index)
            self._refresh_motion_inspector(recipe)
            motion = recipe.motion if isinstance(recipe.motion, Mapping) else {}
            entry = motion.get("entrance") if isinstance(motion.get("entrance"), Mapping) else motion.get("entry", {})
            entry = entry if isinstance(entry, Mapping) else {}
            from .style_recipe import MOTION_SOURCE_VISUAL_GRAPH, motion_source

            if motion_source(motion, visual_graph=recipe.visual_graph if isinstance(recipe.visual_graph, Mapping) else {}) != MOTION_SOURCE_VISUAL_GRAPH:
                effect_type = str(entry.get("type") or motion.get("preset") or "none")
                if page.effect_preset.findData(effect_type) >= 0:
                    page._set_combo_data(page.effect_preset, effect_type)
                duration = entry.get("duration_ms", entry.get("duration", motion.get("duration")))
                if duration is not None:
                    page.effect_duration.setValue(max(1, min(4000, int(duration))))
        finally:
            page._updating_style_ui = False
        page._refresh_style_preview()
        (bind_text(page.ai_confidence, '✓ 视觉方案已保存；预览与成片使用同一渲染链') if route.engine != 'native' else bind_text(page.ai_confidence, '✓ 字幕样式已应用并进入实时预览'))
        if hasattr(page, "advanced_style_status"):
            page._update_advanced_style_status(recipe.to_dict())
        if route.engine != "native":
            # Applying a different graph to the currently active cue must
            # invalidate by graph identity, not only by cue id. Otherwise the
            # previous LIVE/Fidelity frame can remain foreground until another
            # seek or selection change happens.
            page._advanced_preview_state.generation += 1
            page._advanced_preview_state.identity = None
            page._advanced_preview_expected_key = ""
            page._advanced_preview_snapshot = None
            page._advanced_active_cue_id = ""
            page.ensure_active_subtitle_renderer(reason="style_recipe_commit")
            page._queue_advanced_preview(
                copy.deepcopy(recipe.to_dict()), force=True, delay_ms=0
            )
        return True

    def _persist_ai_design(self, suggestion: AIDesignSuggestion) -> None:
        page = self.page
        recipe = suggestion.recipe
        digest = hashlib.sha1(recipe.name.encode("utf-8")).hexdigest()[:8]
        style_id = f"ai-{digest}"
        style = SubtitleStyle(
            style_id, recipe.name,
            font_family=str(recipe.typography.get("fontFamily") or "Microsoft YaHei UI"),
            font_size=float(recipe.typography.get("fontSize") or 52),
            bold=bool(recipe.typography.get("bold", True)),
        )
        try:
            StylePresetStore().upsert(style, recipe.to_dict(), source="ai")
        except (TypeError, ValueError) as exc:
            page._show_studio_hint(tr('样式预设未保存：{value0}', value0=exc))
        motion = recipe.motion if isinstance(recipe.motion, Mapping) else {}
        entrance = motion.get("entrance") if isinstance(motion.get("entrance"), Mapping) else {}
        kind = str(entrance.get("type") or motion.get("preset") or "soft_fade")
        preview_id = kind if kind in builtin_effects() else "soft_fade"
        motion_id = f"ai-{digest}-motion"
        try:
            MotionPresetStore().upsert(MotionPreset(
                motion_id, recipe.name, copy.deepcopy(dict(motion)),
                preview_effect_id=preview_id, system=False,
                description="AI 生成动效",
            ))
        except (TypeError, ValueError) as exc:
            page._show_studio_hint(tr('动效预设未保存：{value0}', value0=exc))
        page._refresh_saved_ai_styles()
        page._refresh_style_presets()

    def _refresh_saved_ai_styles(self) -> None:
        page = self.page
        layout = getattr(page, "advanced_saved_layout", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        store = StylePresetStore()
        recipes = store.load_recipes()
        saved = [style for style in store.load_user().values() if str(style.id).startswith("ai-")]
        if not saved:
            empty = QLabel("AI 生成的高级样式会显示在这里")
            empty.setObjectName("cardMeta")
            layout.addWidget(empty)
            layout.addStretch(1)
            return
        for style in saved[:8]:
            button = QPushButton(style.name)
            button.setObjectName("studioButton")
            bind_text(button, '应用已保存的 AI 样式', property='toolTip')
            payload = recipes.get(style.id)
            button.clicked.connect(
                lambda _checked=False, recipe_payload=payload, name=style.name: page._apply_saved_ai_style(recipe_payload, name)
            )
            layout.addWidget(button)
        layout.addStretch(1)

    def _apply_saved_ai_style(self, recipe_payload, name: str) -> None:
        page = self.page
        if not self.session.project or not self.session.selected_cue_id or not isinstance(recipe_payload, Mapping):
            return
        recipe = StyleRecipe.from_dict(recipe_payload)
        recipe.name = name or recipe.name
        page._apply_style_recipe(self.session.selected_cue_id, recipe)

    def _clear_advanced_style(self) -> None:
        page = self.page
        if not self.session.project or not self.session.selected_cue_id:
            return
        cue = cue_by_id(self.session.project, self.session.selected_cue_id)
        recipes = dict(self.session.project.style_recipes)
        payload = recipes.get(cue.style_id)
        if not payload:
            for key in list(recipes):
                if cue.style_id.startswith(key) or key.startswith(str(cue.style_id).split("-fill-")[0]):
                    payload = recipes.get(key)
                    break
        if not payload or route_recipe(payload).engine != "remotion":
            page._show_studio_hint(tr('当前字幕没有复杂视觉效果'))
            return
        recipes.pop(cue.style_id, None)
        base_id = str(cue.base_preset_id or "default")
        store_style = StylePresetStore().all().get(base_id)
        styles = list(self.session.project.styles)
        if store_style is not None:
            restored = copy.deepcopy(store_style)
            restored.id = base_id
            styles = [item for item in styles if item.id != base_id] + [restored]
        elif not any(item.id == base_id for item in styles):
            base_id = cue.style_id
        self.session.undo_stack.push(
            SetCuePresentationCommand(
                self.session.project,
                cue.id,
                cue_changes={
                    "style_id": base_id,
                    "base_preset_id": base_id,
                    "appearance_override": {},
                    "effect_id": "none",
                },
                styles=styles,
                effects=self.session.project.effects,
                style_recipes=recipes,
                text="移除高级样式",
                changed=page._changed,
            )
        )
        if hasattr(page, "advanced_style_status"):
            page._update_advanced_style_status({})
        if hasattr(page, "advanced_preview_image"):
            bind_text(page.advanced_preview_image, '已恢复普通字幕')
        if hasattr(page, "advanced_cue_overlay"):
            page.advanced_cue_overlay.hide()
        page._show_studio_hint(tr('已移除复杂视觉效果，预览回到基础模式'))
        page._load_style_inspector()
        page._refresh_style_preview()
        page._refresh_ass_preview()

    def _refresh_style_presets(self, selected_id: str = "") -> None:
        page = self.page
        current = selected_id or str(page.style_preset.currentData() or "") if hasattr(page, "style_preset") else selected_id
        if not hasattr(page, "style_preset"):
            return
        # Pure display refresh: clear()/addItem()/setCurrentIndex() must not
        # emit currentIndexChanged into the preset-apply transaction.
        page.style_preset.blockSignals(True)
        try:
            page.style_preset.clear()
            page._style_preset_base_labels = {}
            store = StylePresetStore()
            styles = store.all()
            metadata = store.load_metadata()
            builtin_ids = [style_id for style_id in BUILTIN_PRESETS if style_id in styles]
            custom_ids = sorted(
                (style_id for style_id in styles if style_id not in BUILTIN_PRESETS and str(metadata.get(style_id, {}).get("source") or "") != "ai"),
                key=lambda style_id: styles[style_id].name.casefold(),
            )
            ai_ids = sorted(
                (style_id for style_id in styles if str(metadata.get(style_id, {}).get("source") or "") == "ai"),
                key=lambda style_id: str(metadata.get(style_id, {}).get("created_at") or ""),
                reverse=True,
            )
            for style_id in [*builtin_ids, *custom_ids, *ai_ids]:
                style = styles[style_id]
                label = f"AI · {style.name}" if style_id in ai_ids else style.name
                page.style_preset.addItem(label, style_id)
                page._style_preset_base_labels[page.style_preset.count() - 1] = label
            index = page.style_preset.findData(current)
            if index >= 0:
                page.style_preset.setCurrentIndex(index)
        finally:
            page.style_preset.blockSignals(False)

    def _open_style_library(self) -> None:
        page = self.page
        from .style_library import StyleLibraryDialog

        dialog = StyleLibraryDialog(page)
        dialog.styleSelected.connect(page._apply_style_library_preset)
        dialog.exec()
        page._refresh_style_presets(str(page.style_preset.currentData() or ""))

    def _apply_style_library_preset(self, style_id: str) -> None:
        page = self.page
        page._refresh_style_presets(str(style_id))
        index = page.style_preset.findData(str(style_id))
        if index >= 0:
            page.style_preset.setCurrentIndex(index)
            page._preset_activated(index)

    def _preset_name(self, title: str, initial: str) -> str:
        page = self.page
        value, accepted = QInputDialog.getText(page, title, tr('预设名称'), text=initial)
        return value.strip() if accepted else ""

    def _clone_selected_preset(self, title: str, suffix: str) -> None:
        page = self.page
        source = StylePresetStore().all().get(str(page.style_preset.currentData() or "default"))
        if not source:
            return
        name = page._preset_name(title, source.name + suffix)
        if not name:
            return
        style = page._style_from_controls(copy.deepcopy(source)) if hasattr(page, "style_font") else copy.deepcopy(source)
        style.id = "user-" + uuid.uuid4().hex[:12]
        style.name = name
        recipe = None
        if self.session.project and self.session.selected_cue_id:
            cue = self.session._cue_lookup.get(self.session.selected_cue_id)
            recipe = copy.deepcopy(self.session.project.style_recipes.get(cue.style_id)) if cue else None
        if recipe is None and page._current_gradient() is not None:
            recipe = page._style_recipe_for_style(style, page._current_gradient())
        StylePresetStore().upsert(style, recipe)
        page._refresh_style_presets(style.id)

    def _new_style_preset(self) -> None:
        page = self.page
        page._clone_selected_preset("新建样式预设", " 新预设")

    def _duplicate_style_preset(self) -> None:
        page = self.page
        page._clone_selected_preset("复制样式预设", " 副本")

    def _rename_style_preset(self) -> None:
        page = self.page
        style_id = str(page.style_preset.currentData() or "")
        if style_id in BUILTIN_PRESETS:
            bind_text(page.save_state, '内置样式不能重命名')
            return
        style = StylePresetStore().load_user().get(style_id)
        if not style:
            return
        name = page._preset_name("重命名样式预设", style.name)
        if name:
            style.name = name
            StylePresetStore().upsert(style)
            page._refresh_style_presets(style.id)

    def _delete_style_preset(self) -> None:
        page = self.page
        style_id = str(page.style_preset.currentData() or "")
        StylePresetStore().delete(style_id)
        page._refresh_style_presets()
        (bind_text(page.save_state, '已隐藏内置预设 · 可在预设管理器恢复') if style_id in BUILTIN_PRESETS else bind_text(page.save_state, '已删除自定义预设'))

    def _selected_style_source(self, *, use_cue_style: bool = True):
        page = self.page
        style_id = str(page.style_preset.currentData() or "default")
        if self.session.project:
            cue = self.session._cue_lookup.get(self.session.selected_cue_id)
            if cue is not None and use_cue_style:
                return resolve_cue_visual(self.session.project, cue).style
            if not use_cue_style:
                # Dropdown picks must load the pristine preset definition. The
                # project copy with the same id can be mutated by earlier scoped
                # edits; using it made every preset appear to keep the previous
                # font/colors, i.e. "switching presets did nothing".
                source = StylePresetStore().all().get(style_id)
                if source is not None:
                    return copy.deepcopy(source)
            cue_uses_selected_preset = bool(
                cue
                and (
                    cue.style_id == style_id
                    or cue.style_id.startswith(style_id + "-scope-")
                    or cue.style_id.startswith(style_id + "-canvas-")
                )
            )
            if cue_uses_selected_preset and use_cue_style:
                cue_style = next(
                    (item for item in self.session.project.styles if item.id == cue.style_id),
                    None,
                )
                if cue_style is not None:
                    return copy.deepcopy(cue_style)
            project_style = next((item for item in self.session.project.styles if item.id == style_id), None)
            if project_style is not None:
                return copy.deepcopy(project_style)
        source = StylePresetStore().all().get(style_id)
        return copy.deepcopy(source) if source is not None else None

    def _preset_index_changed(self, index: int) -> None:
        """User changed the preset combo (wheel/keyboard/popup): apply it now."""
        self._apply_user_preset(index)

    def _preset_activated(self, index: int) -> None:
        """User picked a preset: apply it immediately to the current scope."""
        self._apply_user_preset(index)

    def _apply_user_preset(self, index: int) -> None:
        page = self.page
        # A preset switch is itself a complete AppearanceTransaction: an older
        # delayed numeric commit firing afterwards would reapply stale
        # inspector values and undo the preset's stroke. Cancel it before any
        # early return so no queued commit can outlive the switch.
        timer = getattr(page, "_style_debounce_timer", None)
        if timer is not None:
            timer.stop()
        marker_key = (int(index), str(self.session.selected_cue_id or ""))
        if getattr(self, "_preset_apply_marker", None) == marker_key:
            # The sibling signal (currentIndexChanged vs activated) of the
            # same user action already ran this transaction.
            self._preset_apply_marker = None
            return
        if page._updating_style_ui or index < 0:
            return
        self._edit_draft = None
        if not self.session.project or not self.session.selected_cue_id:
            return
        self._preset_apply_marker = marker_key
        QTimer.singleShot(0, self._clear_preset_apply_marker)
        page._apply_style(replace_preset=True)
        label = page.style_preset.itemText(index)
        from ..studio.presentation_scope import report_scope,capture_scope
        report_scope(page,capture_scope(page),label=tr('预设「{value0}」',value0=label))

    def _clear_preset_apply_marker(self) -> None:
        self._preset_apply_marker = None


    def _load_style_inspector(
        self,
        _index: int = -1,
        *,
        selected_ids: set[str] | None = None,
        selection_scope: SelectionScope | None = None,
    ) -> None:
        page = self.page
        if getattr(page, '_close_requested', False):
            return
        if not hasattr(page, "style_font"):
            return
        if page._updating_style_ui:
            return
        if self._edit_draft is not None:
            draft = self._edit_draft
            if (_index < 0 and draft['project'] is self.session.project
                    and draft['cue_id'] == self.session.selected_cue_id):
                return
            self._edit_draft = None
            page._style_debounce_timer.stop()
        if _index >= 0 and not page._updating_style_ui:
            page._style_dirty = False
            page._update_style_dirty_label()
        style = page._selected_style_source(use_cue_style=_index < 0)
        layer = getattr(page, 'style_layer', None)
        cue = self.session._cue_lookup.get(self.session.selected_cue_id)
        if cue is not None and layer is not None:
            from .scoped_style import effective_layer_style
            style = effective_layer_style(self.session.project, cue, layer.currentData())
            paired = bool(self.session.project.generation_metadata.get('translations', {}).get(cue.id))
            for name in ('style_position_x','style_position_y','style_alignment','style_margin_l','style_margin_r','style_margin_v'):
                control = getattr(page,name,None)
                if control is not None:
                    control.setEnabled(not paired or layer.currentData() == 'group')
                    if paired: bind_text(control, '双语位置与对齐：先选择「整组」', property='toolTip')
        summary = getattr(page, 'style_scope_summary', None)
        if summary is not None:
            bind_text(summary, '选中的 {count} 条字幕 · {layer}', count=len(self._style_target_ids()),
                      layer=tr(LAYER_TITLES.get(layer.currentData(), '原文')))
        if style is None:
            return
        page._updating_style_ui = True
        # Blocking the controls (not only the slot guard) prevents polar X/Y
        # synchronization and other observers from reading a half-loaded row.
        blocked = [QSignalBlocker(control) for name, control in vars(page).items()
                   if name.startswith(('style_', 'effect_', 'motion_'))
                   and hasattr(control, 'blockSignals')]
        try:
            # Keep the project font visible even when it is not installed on
            # this machine. setCurrentText() with NoInsert can silently leave
            # the first system font selected instead.
            page.style_font.setEditText(style.font_family)
            from .font_metadata import resolve_local_face
            _, warning = resolve_local_face(style.font_family, style.font_weight, style.font_style_name,
                                            style.bold, style.font_file, style.font_face_index)
            if hasattr(page, 'style_font_warning'):
                page.style_font_warning.setText(warning)
                page.style_font_warning.setVisible(bool(warning))
            bind_text(page.style_font, tr(warning) if warning else tr('{family} / {style} / {weight}', family=style.font_family, style=style.font_style_name, weight=style.font_weight or tr('自动')), property='toolTip')
            page.style_font_size.setValue(style.font_size)
            page.style_spacing.setValue(style.spacing)
            page.style_bold.setChecked(style.bold)
            page.style_italic.setChecked(style.italic)
            page.style_underline.setChecked(style.underline)
            page.style_alignment.setCurrentIndex(
                max(0, page.style_alignment.findData(style.alignment))
            )
            page._sync_style_anchor()
            play_res_x = max(1, int(self.session.project.render_settings.get("play_res_x", 1920))) if self.session.project else 1920
            play_res_y = max(1, int(self.session.project.render_settings.get("play_res_y", 1080))) if self.session.project else 1080
            horizontal = (style.margin_l, play_res_x // 2, play_res_x - style.margin_r)
            vertical = (play_res_y - style.margin_v, play_res_y // 2, style.margin_v)
            column = (style.alignment - 1) % 3
            row = (style.alignment - 1) // 3
            page.style_position_x.setValue(
                horizontal[column] if style.position_x is None else style.position_x
            )
            page.style_position_y.setValue(
                vertical[row] if style.position_y is None else style.position_y
            )
            if hasattr(page, "position_overlay") and not page.position_overlay._dragging:
                page.position_overlay.set_video_position(
                    page.style_position_x.value(),
                    page.style_position_y.value(),
                    play_res_x,
                    play_res_y,
                )
                page.position_overlay.set_font_spec(
                    style.font_family,
                    style.font_size,
                    style.spacing,
                    style.alignment,
                    scale_x=style.scale_x,
                    scale_y=style.scale_y,
                    outline_width=style.outline_width,
                    shadow=style.shadow,
                    margin_l=style.margin_l,
                    margin_r=style.margin_r,
                    bold=style.bold,
                    italic=style.italic,
                    underline=style.underline,
                    strokes=style.stroke_layers(),
                )
                page._sync_transform_visual_overlay()
            page.style_margin_l.setValue(style.margin_l)
            page.style_margin_r.setValue(style.margin_r)
            page.style_margin_v.setValue(style.margin_v)
            page.style_fill_color.setText(style.primary_color)
            page.style_outline_color.setText(style.outline_color)
            page.style_outline_width.setValue(style.outline_width)
            if hasattr(page, "style_outline2"):
                page.style_outline2.setChecked(bool(style.outline2_width > 0))
                page.style_outline2_color.setText(style.outline2_color or "#FFFFFF")
                page.style_outline2_width.setValue(style.outline2_width if style.outline2_width > 0 else 1.5)
                page.style_outline2_color.setEnabled(style.outline2_width > 0)
                page.style_outline2_width.setEnabled(style.outline2_width > 0)
                if hasattr(page, "style_outline2_fields"):
                    page.style_outline2_fields.setVisible(bool(style.outline2_width > 0))
            # resolve_cue_visual returns the base preset's id; the rich shadow
            # belongs to the selected cue's derived/AI recipe, not that base.
            cue = self.session._cue_lookup.get(self.session.selected_cue_id)
            recipe_id = cue.style_id if cue is not None and _index < 0 else style.id
            recipe = self.session.project.style_recipes.get(recipe_id, {}) if self.session.project else {}
            if cue is not None and layer is not None and layer.currentData() == 'translation':
                from .bilingual_layout import _translation_appearance
                from .style_resolution import recipe_for_cue
                shown = _translation_appearance(cue, copy.deepcopy(cue))
                recipe = recipe_for_cue(self.session.project.style_recipes, shown) or {}
            supports_shadow = not (isinstance(recipe,Mapping) and bool(recipe.get('webTheme')))
            for name in ('style_shadow_distance','style_shadow_angle','style_shadow_angle_value','style_shadow_blur','style_shadow_opacity',
                         'style_shadow_offset_x','style_shadow_offset_y','style_shadow_spread'):
                control=getattr(page,name,None)
                if control is not None:
                    control.setEnabled(supports_shadow)
                    (bind_text(control, '左右拖动调整数值；双击可直接输入', property='toolTip') if supports_shadow else bind_text(control, '网页主题的阴影由主题 HTML/CSS 控制；请在 AI 面板中修改主题，数值控件不支持直接覆盖。', property='toolTip'))
            page.style_shadow.setValue(style.shadow)
            shadow_payload = recipe.get("outline", {}).get("shadow", {}) if isinstance(recipe, Mapping) else {}
            # Legacy/native styles only persist the scalar compatibility
            # shadow.  An empty recipe mapping must therefore fall back to
            # that scalar instead of normalizing to a disabled shadow.
            shadow_source = shadow_payload if isinstance(shadow_payload, Mapping) and shadow_payload else style.shadow
            shadow_payload = normalize_shadow_contract(shadow_source)
            page.style_shadow_color.setText(str(shadow_payload.get("color") or "#FF000000"))
            page.style_shadow_opacity.setValue(round(float(shadow_payload.get("opacity", 0.45) or 0) * 100))
            page.style_shadow_offset_x.setValue(float(shadow_payload.get("offset_x", style.shadow) or 0))
            page.style_shadow_offset_y.setValue(float(shadow_payload.get("offset_y", style.shadow) or 0))
            sync_polar = getattr(page, "_sync_shadow_polar_from_offsets", None)
            if callable(sync_polar):
                sync_polar()
            page.style_shadow_blur.setValue(float(shadow_payload.get("blur_radius", style.shadow * 1.5) or 0))
            page.style_shadow_spread.setValue(float(shadow_payload.get("spread", 0) or 0))
            page.style_background.setChecked(style.border_style == 3)
            page._background_edited = False
            page.style_back_color.setText(style.back_color)
            if _index >= 0 and not recipe:
                # Dropdown-driven preset load: gradient/glow presets ship with a
                # saved recipe; without it every gradient preset reopens solid.
                saved_recipe = StylePresetStore().load_recipes().get(style.id)
                if isinstance(saved_recipe, Mapping):
                    recipe = dict(saved_recipe)
            if hasattr(page, "position_overlay") and not page.position_overlay._dragging:
                graph = recipe.get("visualGraph") if isinstance(recipe, Mapping) else {}
                if isinstance(graph, Mapping) and graph:
                    from ..caption_design.visual_design_graph import VisualDesignGraph, visual_composition_bounds

                    try:
                        visual = VisualDesignGraph.from_dict(graph)
                        _x, _y, width, height = visual_composition_bounds((0, 0, 100, 40), visual)
                        overflow = max((width - 100) / 200.0, (height - 40) / 80.0, 0.18)
                    except (TypeError, ValueError):
                        overflow = 0.35
                    # 四十三轮：拖拽/缩放选框以字幕文字为准（用户实录"文字框比
                    # 完整字幕大了至少一倍"）。视觉合成边界（粒子/装置外扩）
                    # 上限收紧到 0.22——选框 ≈ 文字的 1.45 倍，仍给特效留手柄余量。
                    overflow = min(float(overflow), 0.22)
                    page.position_overlay.set_composition_overflow(overflow)
                else:
                    page.position_overlay.set_composition_overflow(0.0)
            page._update_advanced_style_status(recipe if isinstance(recipe, Mapping) else {})
            fill = recipe.get("colors", {}).get("fill") if isinstance(recipe, dict) else None
            glow = recipe.get("effects", {}).get("glow", {}) if isinstance(recipe, dict) else {}
            if hasattr(page, "style_glow") and isinstance(glow, dict):
                page.style_glow.setChecked(bool(glow.get("enabled", False)))
                page.style_glow_strength.setValue(float(glow.get("blur", 0.0) or 0.0))
                if hasattr(page, "style_glow_color"):
                    page.style_glow_color.setText(str(glow.get("color") or style.outline_color or "#FF0000"))
            page._fill_spec = FillSpec.from_value(fill if fill is not None else style.primary_color)
            if getattr(page, "style_fill_button", None) is not None:
                page.style_fill_button.set_fill_value(page._fill_spec)
            if hasattr(page, "style_back_button"):
                page._update_color_swatch(page.style_back_button, style.back_color)
            if hasattr(page, "style_preview"):
                set_text = getattr(page.style_preview, "set_sample_text", None)
                if callable(set_text):
                    set_text(self._preview_cue_text())
                page.style_preview.set_style(style)
                page.style_preview.set_strokes(style.stroke_layers())
                page.style_preview.set_gradient(fill if isinstance(fill, dict) else None)
                page.style_preview.set_glow(glow if isinstance(glow, dict) else None)
                if hasattr(page, "motion_preview"):
                    page.motion_preview.set_style(style)
                    page.motion_preview.set_strokes(style.stroke_layers())
                    page.motion_preview.set_gradient(fill if isinstance(fill, dict) else None)
                    page.motion_preview.set_glow(glow if isinstance(glow, dict) else None)
            page._style_loaded_values = self._inspector_values(style)

            # Compare submitted controls with exactly what this inspector
            # displayed, not with another cue or with rounded native defaults.
            self._control_baseline = {
                "project": self.session.project,
                "cue_id": self.session.selected_cue_id,
                "style": page._style_from_controls(style),
                "shadow": self._shadow_from_controls(),
                "glow": self._glow_from_controls(),
                "edited_fields": set(),
            }
            page._apply_mixed_style_display(
                style,
                selected_ids=selected_ids,
                selection_scope=selection_scope,
            )
            if isinstance(recipe, Mapping) and recipe:
                self._load_advanced_motion_controls(recipe)
            if hasattr(self, "_motion_workflow"):
                self._motion_workflow.load()
        finally:
            for blocker in blocked:
                blocker.unblock()
            page._updating_style_ui = False
            _refresh_appearance_summaries(page)
            if hasattr(page,'caption_transform_panel'):
                panel = page.caption_transform_panel
                panel._needs_refresh = True
                page._sync_video_tab_selection()
                if panel.isVisible():
                    panel.refresh()
                else:
                    # The hidden video tab need not lay out every caption on
                    # selection. Keep the active canvas overlay current; the
                    # panel refreshes when its tab becomes visible.
                    panel.sync_overlay()

    def _apply_mixed_style_display(
        self,
        fallback_style,
        *,
        selected_ids: set[str] | None = None,
        selection_scope: SelectionScope | None = None,
    ) -> None:
        page = self.page
        """Show mixed values without replacing the source used for edits."""
        if not self.session.project or not hasattr(page, "style_font_size"):
            return
        scope = selection_scope
        if scope is not None and scope.mode == SelectionMode.ALL:
            cues = self.session.project.cues
            selected_count = scope.count()
        else:
            ids = (
                selected_ids
                if selected_ids is not None
                else (
                    scope.materialize(
                        [cue.id for cue in self.session.project.cues]
                    )
                    if scope is not None
                    else page.selected_cue_ids()
                )
            )
            chosen = set(ids)
            cues = (
                cue
                for cue in self.session.project.cues
                if cue.id in chosen
            )
            selected_count = len(ids)
        if selected_count < 2:
            return
        from .scoped_style import effective_layer_style
        layer_control = getattr(page, 'style_layer', None)
        layer = layer_control.currentData() if layer_control is not None else 'original'
        # Appearance mixed markers do not need each cue's position/scale.
        from .caption_layer_transform import layer_values
        faces={};styles=[]
        for cue in cues:
            key=(cue.style_id,cue.base_preset_id,cue.speaker_id,
                 json.dumps(cue.appearance_override,sort_keys=True,ensure_ascii=False),
                 cue.transform.get('font_size'),layer_values(cue,layer).get('font_size'))
            if key not in faces:faces[key]=effective_layer_style(self.session.project,cue,layer)
            styles.append(faces[key])
        names = {'font_family':'字体', 'font_size':'字号', 'primary_color':'颜色', 'bold':'粗体',
                 'italic':'斜体', 'underline':'下划线', 'outline_width':'描边', 'outline_color':'描边色',
                 'shadow':'阴影', 'border_style':'背景', 'back_color':'背景色', 'alignment':'对齐', 'spacing':'字距'}
        mixed = [title for field,title in names.items() if len({str(getattr(item, field)) for item in styles}) > 1]
        summary = getattr(page, 'style_scope_summary', None)
        if summary is not None and mixed:
            from ..i18n import join_text
            bind_text(summary, '选中的 {count} 条字幕 · 混合值：{fields}', count=selected_count,
                      fields=join_text([tr(title) for title in mixed]))
        for attribute, control in (("font_size", page.style_font_size), ("spacing", page.style_spacing)):
            values = {getattr(item, attribute) for item in styles}
            if len(values) > 1:
                control.lineEdit().setText("混合")
        for attribute, host in (("primary_color", page.style_fill_swatch), ("outline_color", page.style_outline_swatch), ("back_color", page.style_back_swatch)):
            values = {str(getattr(item, attribute)) for item in styles}
            button = host.findChild(page._style_color_button_type())
            if button is not None and len(values) > 1:
                button.set_color_value(next(iter(values)), "混合", enabled=True)

    def _style_from_controls(self, source):
        page = self.page
        style = copy.deepcopy(source)
        style.font_family = page.style_font.currentText().strip() or style.font_family
        if style.font_family != source.font_family:
            style.font_weight, style.font_style_name, style.font_file, style.font_face_index = 0, "", "", 0
        style.font_size = page.style_font_size.value()
        style.spacing = page.style_spacing.value()
        style.bold = page.style_bold.isChecked()
        if style.bold != source.bold:
            style.font_weight, style.font_style_name = (700 if style.bold else 400), ""
        style.italic = page.style_italic.isChecked()
        style.underline = page.style_underline.isChecked()
        style.alignment = int(page.style_alignment.currentData() or 2)
        style.position_x = page.style_position_x.value()
        style.position_y = page.style_position_y.value()
        style.margin_l = page.style_margin_l.value()
        style.margin_r = page.style_margin_r.value()
        style.margin_v = page.style_margin_v.value()
        for attribute, control in (
            ("primary_color", page.style_fill_color),
            ("outline_color", page.style_outline_color),
            ("back_color", page.style_back_color),
        ):
            value = control.text().strip()
            if QColor(value).isValid():
                setattr(style, attribute, value.upper())
        style.outline_width = page.style_outline_width.value()
        if hasattr(page, "style_outline2"):
            enabled2 = page.style_outline2.isChecked() and page.style_outline2_width.value() > 0
            style.outline2_width = page.style_outline2_width.value() if enabled2 else 0.0
            style.outline2_color = page.style_outline2_color.text().strip() if enabled2 else ""
        shadow = self._shadow_from_controls(page.style_shadow.value())
        style.shadow = float(shadow.get("strength", page.style_shadow.value()) or 0.0)
        style.border_style = 3 if page.style_background.isChecked() else 1
        style.validate()
        return style

    def _commit_canvas_style(self, *, position: tuple[int, int] | None = None, font_size: float | None = None) -> None:
        page = self.page
        if not self.session.project or not self.session.selected_cue_id:
            return
        cue = cue_by_id(self.session.project, self.session.selected_cue_id)
        if position is None and font_size is None:
            return
        target_ids = page._style_target_ids()
        if len(target_ids) > 1:
            from .style_resolution import resolve_cue_visual
            from .visual_snapshot import _anchor
            from ..timeline.studio_commands import SetCuesPresentationCommand
            wanted = set(target_ids)
            targets = [c for c in self.session.project.cues if c.id in wanted]
            anchor = resolve_cue_visual(self.session.project, cue).style
            width = int(self.session.project.render_settings.get('play_res_x', 1920))
            height = int(self.session.project.render_settings.get('play_res_y', 1080))
            anchor_x, anchor_y, *_ = _anchor(anchor, width, height)
            selected_payload = self.session.project.style_recipes.get(cue.style_id, {})
            origin_size = (getattr(page.position_overlay,'_origin_font_size',anchor.font_size)
                           if selected_payload.get('webTheme') else anchor.font_size)
            ratio = max(1.0, float(font_size))/max(1.0, origin_size) if font_size is not None else 1.0
            transforms = {}
            for item in targets:
                style = resolve_cue_visual(self.session.project, item).style
                transform = copy.deepcopy(item.transform or {})
                payload = self.session.project.style_recipes.get(item.style_id, {})
                if position is not None:
                    x, y, *_ = _anchor(style, width, height)
                    point = (round(x + position[0] - anchor_x), round(y + position[1] - anchor_y))
                    transform.update(position_x=point[0], position_y=point[1])
                    if payload.get('webTheme'):
                        from .web_placement import moved_placement
                        transform['web_placement'] = moved_placement(self.session.project, item, point)
                if font_size is not None:
                    if payload.get('webTheme'):
                        from .web_placement import scaled_placement
                        transform['web_placement'] = scaled_placement(self.session.project, item, ratio)
                    else:
                        transform['font_size'] = max(1.0, style.font_size * ratio)
                transforms[item.id] = transform
            self.session.undo_stack.push(SetCuesPresentationCommand(
                self.session.project, transforms, style_id=cue.style_id, effect_id=cue.effect_id,
                style_ids={c.id:c.style_id for c in targets}, effect_ids={c.id:c.effect_id for c in targets},
                transform_overrides=transforms, text='调整字幕位置' if position is not None else '调整字幕字号', changed=page._changed,
                merge_enabled=False))
            return
        transform = copy.deepcopy(cue.transform)
        if position is not None:
            transform["position_x"], transform["position_y"] = map(int, position)
            payload = self.session.project.style_recipes.get(cue.style_id, {})
            if payload.get('webTheme'):
                from .web_placement import moved_placement
                transform['web_placement'] = moved_placement(self.session.project, cue, position)
        if font_size is not None:
            payload = self.session.project.style_recipes.get(cue.style_id, {})
            if payload.get('webTheme'):
                from .web_placement import scaled_placement
                origin = max(.01,float(page.position_overlay._origin_font_size))
                transform['web_placement'] = scaled_placement(self.session.project,cue,
                    float(font_size)/origin,getattr(page,'_web_resize_anchor',None))
            else:
                transform["font_size"] = max(1.0, float(font_size))
        from ..timeline.studio_commands import SetCueFieldsCommand
        self.session.undo_stack.push(SetCueFieldsCommand(
            self.session.project,
            cue.id,
            {"transform": transform},
            text="调整字幕位置" if position is not None else "缩放特效字幕" if payload.get('webTheme') else "调整字幕字号",
            changed=page._changed,
        ))

    def _inspector_values(self, style):
        from dataclasses import asdict
        values = asdict(self._style_from_controls(style))
        for key in ('id', 'name'):
            values.pop(key, None)
        return {'fields': values, 'recipe': {
            'outline': {'shadow': self._shadow_from_controls(style.shadow)},
            'effects': {'glow': normalize_glow_contract({
                'enabled': bool(self.page.style_glow.isChecked()),
                'color': self.page.style_glow_color.text(),
                'radius': float(self.page.style_glow_strength.value())})},
            'colors': {'fill': self._current_gradient() or self.page._fill_spec.to_dict()},
        }}

    def _apply_property_changes(self):
        from .scoped_style import property_patch, style_patch_command
        page = self.page
        before = getattr(page, '_style_loaded_values', None)
        source = page._selected_style_source(use_cue_style=True)
        if before is None or source is None:
            return
        after = self._inspector_values(source)
        patch = property_patch(before, after)
        baseline = self._control_baseline
        explicit = set(baseline['edited_fields']) if baseline and baseline['project'] is self.session.project and baseline['cue_id'] == self.session.selected_cue_id else set()
        for field in explicit:
            if '.' not in field and field in after.get('fields', {}):
                patch.setdefault('fields', {})[field] = copy.deepcopy(after['fields'][field])
            elif field.startswith(('shadow.', 'glow.')):
                group, key = field.split('.', 1)
                parent = 'outline' if group == 'shadow' else 'effects'
                value = after.get('recipe', {}).get(parent, {}).get(group, {})
                if key in value:
                    patch.setdefault('recipe', {}).setdefault(parent, {}).setdefault(group, {})[key] = copy.deepcopy(value[key])
        fields = patch.get('fields', {})
        if 'font_family' in fields:
            fields.update(font_weight=0, font_style_name='', font_file='', font_face_index=0)
        if 'bold' in fields:
            fields.update(font_weight=700 if fields['bold'] else 400, font_style_name='')
        if 'primary_color' in explicit:
            patch.setdefault('recipe', {}).setdefault('colors', {})['fill'] = copy.deepcopy(after['recipe']['colors']['fill'])
        layer_control = getattr(page, 'style_layer', None)
        command = style_patch_command(self.session.project, self._style_target_ids(),
            patch.get('fields', {}), recipe_patch=patch.get('recipe', {}),
            layer=self._edit_draft.get('layer','original') if self._edit_draft is not None else layer_control.currentData() if layer_control is not None else 'original', changed=page._changed)
        if command is not None:
            self.session.undo_stack.push(command)
        page._style_loaded_values = after
        if self._control_baseline:
            self._control_baseline['edited_fields'].clear()

    def _style_control_changed(self, *_args) -> None:
        page = self.page
        if page._updating_style_ui or not self.session.project or not self.session.selected_cue_id:
            return
        self._record_style_fields(_args)
        page._style_dirty = True
        page._update_style_dirty_label()
        if hasattr(page, "style_back_button"):
            page._update_color_swatch(page.style_back_button, page.style_back_color.text())
        page._refresh_style_preview()
        self._apply_property_changes()

    def _glow_toggled(self, enabled: bool) -> None:
        page = self.page
        if enabled and page.style_glow_strength.value() <= 0:
            page.style_glow_strength.setValue(5.0)
        page._style_control_changed("glow.enabled")

    def _layer_changed(self, *_args) -> None:
        if self.page._updating_style_ui: return
        panel=getattr(self.page,'caption_transform_panel',None)
        if panel is not None:
            panel.end_gesture(cancel=True)
            if panel.global_link.isChecked() and self.page.style_layer.currentData()!='group':
                with QSignalBlocker(panel.global_link):panel.global_link.setChecked(False)
                panel.link_changed(False)
        if self._edit_draft is not None: self._commit_style_now()
        self._edit_draft = None
        self.page._load_style_inspector()

    def _scope_changed(self, *_args) -> None:
        if not self.page._updating_style_ui:
            panel=getattr(self.page,'caption_transform_panel',None)
            if panel is not None:
                panel.end_gesture(cancel=True)
                if panel.global_link.isChecked() and self.page.style_scope.currentData()!='all':
                    with QSignalBlocker(panel.global_link):panel.global_link.setChecked(False)
                    panel.link_changed(False)
            if self._edit_draft is not None: self._commit_style_now()
            self._edit_draft = None
            self.page._load_style_inspector()

    def _sync_outline2_controls(self, enabled: bool) -> None:
        page = self.page
        if getattr(page, "style_outline2_width", None) is None:
            return
        page.style_outline2_color.setEnabled(bool(enabled))
        page.style_outline2_width.setEnabled(bool(enabled))
        fields = getattr(page, "style_outline2_fields", None)
        if fields is not None:
            fields.setVisible(bool(enabled))
        if enabled and page.style_outline2_width.value() <= 0:
            page.style_outline2_width.setValue(1.5)
        if enabled and not QColor(page.style_outline2_color.text()).isValid():
            page.style_outline2_color.setText("#FFFFFFFF")

    def _refresh_style_preview(self) -> None:
        page = self.page
        if not hasattr(page, "style_preview"):
            return
        source = page._selected_style_source()
        if source is None:
            return
        set_text = getattr(page.style_preview, "set_sample_text", None)
        if callable(set_text):
            set_text(self._preview_cue_text())
        try:
            style = page._style_from_controls(source)
            page.style_preview.set_style(style)
            page.style_preview.set_strokes(style.stroke_layers())
            page.style_preview.set_gradient(page._current_gradient())
            page.style_preview.set_shadow(self._shadow_from_controls(style.shadow))
            page.style_preview.set_glow({
                "enabled": page.style_glow.isChecked(),
                "color": page.style_glow_color.text() if hasattr(page, "style_glow_color") else style.outline_color,
                "blur": page.style_glow_strength.value(),
                "opacity": 1.0,
            } if hasattr(page, "style_glow") else None)
            if hasattr(page, "motion_preview"):
                page.motion_preview.set_style(style)
                page.motion_preview.set_strokes(style.stroke_layers())
                page.motion_preview.set_gradient(page._current_gradient())
                page.motion_preview.set_shadow(page.style_preview._shadow)
                page.motion_preview.set_glow(page.style_preview._glow)
            if hasattr(page, "position_overlay"):
                page.position_overlay.set_video_position(
                    int(style.position_x if style.position_x is not None else page.style_position_x.value()),
                    int(style.position_y if style.position_y is not None else page.style_position_y.value()),
                    max(1, int(self.session.project.render_settings.get("play_res_x", 1920))) if self.session.project else 1920,
                    max(1, int(self.session.project.render_settings.get("play_res_y", 1080))) if self.session.project else 1080,
                )
                page.position_overlay.set_font_spec(
                    style.font_family, style.font_size, style.spacing, style.alignment,
                    scale_x=style.scale_x, scale_y=style.scale_y,
                    outline_width=style.outline_width, shadow=style.shadow,
                    margin_l=style.margin_l, margin_r=style.margin_r,
                    bold=style.bold, italic=style.italic, underline=style.underline,
                    strokes=style.stroke_layers(),
                )
                page._sync_transform_visual_overlay()
                page.position_overlay.update()
        except (AttributeError, TypeError, ValueError):
            page.style_preview.set_style(source)
            if hasattr(page, "motion_preview"):
                page.motion_preview.set_style(source)

    def _preview_cue_text(self) -> str:
        """Text of the selected line for the style preview (M16)."""
        page = self.page
        project = self.session.project
        cue_id = str(getattr(page, "selected_cue_id", "") or "")
        if project is None or not cue_id:
            return ""
        from ..timeline.studio_edit_sequence import source_cue_id_of
        source = source_cue_id_of(cue_id)
        cue = next((item for item in project.cues if item.id == source), None)
        return str(cue.text) if cue is not None else ""

    def _update_style_dirty_label(self) -> None:
        page = self.page
        if not hasattr(page, "style_preset"):
            return
        index = page.style_preset.currentIndex()
        if index < 0:
            return
        base = getattr(page, "_style_preset_base_labels", {}).get(index, page.style_preset.itemText(index).replace(" · 已修改", ""))
        page.style_preset.setItemText(index, base + (" · 已修改" if getattr(page, "_style_dirty", False) else ""))

    def _style_target_ids(self) -> list[str]:
        from ..studio.presentation_scope import capture_scope
        ids=None
        if self._edit_draft is not None and self._edit_draft.get('project') is self.session.project:
            ids=self._edit_draft.get('targets',())
        layer=self._edit_draft.get('layer') if self._edit_draft else None
        scope=capture_scope(self.page,ids=ids,layer=layer)
        self.page._last_presentation_scope=scope
        return list(scope.cue_ids)

    def _glow_from_controls(self) -> dict:
        page = self.page
        return normalize_glow_contract({
            "enabled": page.style_glow.isChecked(),
            "color": page.style_glow_color.text(),
            "radius": page.style_glow_strength.value(),
        })

    def _record_style_fields(self, fields) -> None:
        baseline = self._control_baseline
        if (baseline and baseline['project'] is self.session.project
                and baseline['cue_id'] == self.session.selected_cue_id):
            baseline['edited_fields'].update(field for field in fields if isinstance(field, str))


    def _copy_subtitle_style(self) -> None:
        page = self.page
        if not self.session.project or not self.session.selected_cue_id:
            return
        cue = cue_by_id(self.session.project, self.session.selected_cue_id)
        style = next((item for item in self.session.project.styles if item.id == cue.style_id), None)
        if style is None:
            return
        page._copied_style_payload = {
            "style": copy.deepcopy(style),
            "recipe": copy.deepcopy(self.session.project.style_recipes.get(cue.style_id)),
            "effect_id": cue.effect_id,
            "effect": copy.deepcopy(self.session.project.effects.get(cue.effect_id)),
        }
        page._show_studio_hint(tr('已复制字幕样式（不含文字、时间、说话人与位置）'))

    def _paste_subtitle_style(self) -> None:
        page = self.page
        payload = page._copied_style_payload
        if not self.session.project or not payload:
            return
        cue_ids = page.selected_cue_ids()
        source = copy.deepcopy(payload["style"])
        existing = {item.id: item for item in self.session.project.styles}
        styles = list(self.session.project.styles)
        recipes = dict(self.session.project.style_recipes)
        mapped: dict[str, str] = {}
        recipe_payload = payload.get("recipe")
        for cue_id in cue_ids:
            cue = cue_by_id(self.session.project, cue_id)
            previous = existing.get(cue.style_id)
            style = copy.deepcopy(source)
            style.id = f"pasted-{hashlib.sha1((self.session.selected_cue_id + cue_id).encode('utf-8')).hexdigest()[:12]}"
            if previous is not None:
                for name in ("position_x", "position_y", "alignment", "margin_l", "margin_r", "margin_v"):
                    setattr(style, name, getattr(previous, name))
            styles = [item for item in styles if item.id != style.id] + [style]
            mapped[cue_id] = style.id
            if isinstance(recipe_payload, Mapping):
                recipe = copy.deepcopy(dict(recipe_payload))
                layout = recipe.setdefault("layout", {})
                layout.update({
                    "positionX": style.position_x, "positionY": style.position_y,
                    "alignment": style.alignment, "marginL": style.margin_l,
                    "marginR": style.margin_r, "marginV": style.margin_v,
                })
                recipes[style.id] = recipe
        effect_id = str(payload.get("effect_id") or "none")
        effects = dict(self.session.project.effects)
        if payload.get("effect") is not None:
            effects[effect_id] = copy.deepcopy(payload["effect"])
        command = SetCuesPresentationCommand(
            self.session.project, cue_ids, style_id=source.id, style_ids=mapped, effect_id=effect_id,
            styles=styles, effects=effects, style_recipes=recipes,
            text="Paste subtitle style", changed=page._changed,
        )
        self.session.undo_stack.push(command)
        page._show_studio_hint(tr('已粘贴样式到 {value0} 条字幕', value0=len(cue_ids)))

    def _trace_subtitle_preset(self, preset_id: str, cue_ids, cue_count_before: int, *, scope: str) -> None:
        """[SubtitlePreset]：样式事务后一条诊断——cue 集合与显示项必须不变。"""
        page = self.page
        project = self.session.project
        if project is None:
            return
        try:
            from .style_recipe import recipe_payload_for_style, route_recipe
            advanced = sum(
                1 for cue in project.cues
                if isinstance(
                    recipe_payload_for_style(project.style_recipes, cue.style_id), Mapping
                )
                and route_recipe(
                    recipe_payload_for_style(project.style_recipes, cue.style_id)
                ).engine == "remotion"
            )
        except Exception:
            advanced = -1
        page._studio_trace(
            "SubtitlePreset",
            preset=str(preset_id),
            scope=str(scope),
            targets=len(cue_ids),
            cue_count_before=int(cue_count_before),
            cue_count_after=len(project.cues),
            model_rows=(page.cue_model.rowCount() if hasattr(page, "cue_model") else -1),
            timeline_items=(len(page.timeline._cues_by_start) if hasattr(page, "timeline") else -1),
            advanced_routed_cues=int(advanced),
            ass_events=(len(project.cues) - len(getattr(page, "_advanced_ass_hidden", set()))),
        )

    def _apply_style(self, *, replace_preset: bool = False) -> None:
        page = self.page
        if not self.session.project:
            return
        cue_ids = page._style_target_ids()
        draft = self._edit_draft
        if draft and draft['project'] is self.session.project and draft['cue_id'] == self.session.selected_cue_id:
            valid = {cue.id for cue in self.session.project.cues}
            cue_ids = [cue_id for cue_id in draft.get('targets', draft.get('cue_ids', ())) if cue_id in valid]
        if not cue_ids:
            from ..studio.presentation_scope import report_scope,capture_scope
            report_scope(page,capture_scope(page),applied=0)
            return
        if replace_preset:
            preset_id=str(page.style_preset.currentData() or 'default')
            patch=StylePresetStore().load_patch(preset_id)
            if not patch:
                source=page._selected_style_source(use_cue_style=False)
                if source is None:return
                from dataclasses import asdict
                patch=asdict(source)
                stored=self.session.project.style_recipes.get(source.id)
                if stored:patch['recipe']=copy.deepcopy(stored)
            from .scoped_preset import preset_command as layer_preset_command
            from ..studio.presentation_scope import capture_scope,report_scope
            snapshot=capture_scope(page,ids=cue_ids)
            command=layer_preset_command(self.session.project,cue_ids,patch,layer=snapshot.layer,
                apply_geometry=page.style_apply_geometry.isChecked(),changed=page._changed)
            if command is not None:self.session.undo_stack.push(command)
            page.ensure_active_subtitle_renderer(reason='scoped_preset')
            page._load_style_inspector()
            report_scope(page,snapshot)
            return
        preset_id = str(page.style_preset.currentData() or "default")
        if replace_preset:
            from ..exports.preset_application import preset_command
            patch = StylePresetStore().load_patch(preset_id)
            if patch:
                command = preset_command(self.session.project, cue_ids, patch,
                    apply_geometry=bool(getattr(page, 'style_apply_geometry', None)
                                        and page.style_apply_geometry.isChecked()), changed=page._changed)
                cue_count_before = len(self.session.project.cues)
                if command is not None:
                    self.session.undo_stack.push(command)
                self._trace_subtitle_preset(preset_id, cue_ids, cue_count_before,
                                            scope=str(page.style_scope.currentData() or "current"))
                # 2026-09-19：补丁路径此前在此提前 return，跳过了非补丁路径的
                # 前台归属重提交与面板重水合——当前字幕要"切走再切回"才刷新。
                # 与 style_route_commit 相同的尾部：remotion 重新出帧、native
                # 撤掉旧高级帧，再重载检查器。
                selected_after = self.session._cue_lookup.get(self.session.selected_cue_id)
                payload_after = self.session.project.style_recipes.get(selected_after.style_id, {}) if selected_after else {}
                if payload_after and route_recipe(payload_after).engine == "remotion":
                    page._queue_advanced_preview(payload_after, delay_ms=0)
                elif hasattr(page, "_revoke_advanced_preview"):
                    page._revoke_advanced_preview(reason="preset_patch_commit_native")
                if hasattr(page, "ensure_active_subtitle_renderer"):
                    page.ensure_active_subtitle_renderer(reason="preset_patch")
                if hasattr(page, "_activate_selected_advanced_if_needed"):
                    page._activate_selected_advanced_if_needed(force=True)
                if hasattr(page, "_load_style_inspector"):
                    page._load_style_inspector()
                return
        # A shared user recipe remains the source for a scoped batch edit too.
        # Dropping it when more than one cue is targeted rebuilt rich legacy
        # recipes from the preset store (which may not contain this project).
        source_cue_id = (self.session.selected_cue_id
                         if self.session.selected_cue_id in cue_ids else cue_ids[0])
        current_cue = cue_by_id(self.session.project, source_cue_id)
        current_recipe_payload = self.session.project.style_recipes.get(current_cue.style_id) if current_cue else None
        preserve_advanced = bool(
            not replace_preset
            and
            current_cue and isinstance(current_recipe_payload, Mapping) and current_recipe_payload
            and route_recipe(current_recipe_payload).engine == "remotion"
        )
        # Applying the dropdown selection must use that preset even when the
        # current Cue has a project-derived style. Effective Cue styles are
        # used for inspection, not as a duplicate preset definition.
        preset = page._selected_style_source(use_cue_style=preserve_advanced)
        if not preset:
            return
        # A preset click materializes the pristine preset exactly once. Manual
        # controls then become explicit overrides; stale controls are never
        # folded back into a preset-switch transaction.
        if hasattr(page, "style_font") and not replace_preset:
            preset = page._style_from_controls(preset)
        selected_cue = cue_by_id(self.session.project, self.session.selected_cue_id)
        from .visual_snapshot import _anchor
        selected_style = resolve_cue_visual(self.session.project, selected_cue).style
        play_width = int(self.session.project.render_settings.get('play_res_x', 1920))
        play_height = int(self.session.project.render_settings.get('play_res_y', 1080))
        previous_x, previous_y, _, _ = _anchor(selected_style, play_width, play_height)
        next_x, next_y, _, _ = _anchor(preset, play_width, play_height)
        position_edited = not replace_preset and (
            abs(next_x-previous_x) > .5 or abs(next_y-previous_y) > .5)
        # Derive scope/cue variants from the stable preset identity. Using the
        # selected cue's already-derived id appended another '-cue-...' level
        # on every edit, retaining hundreds of obsolete recipes and making
        # each later commit validate/copy all of them again.
        target_style_id = preset_id
        if preserve_advanced:
            preset.id = target_style_id
        scope = str(page.style_scope.currentData() or "current")
        base_preset = StylePresetStore().all().get(preset_id)
        project_base = next((s for s in self.session.project.styles if s.id == preset_id), None)
        # Manual edits cannot rewrite the appearance base of unselected peers.
        # In particular, an imported user preset may be absent from this
        # machine's store; the edited controls are never its pristine source.
        base_source = (project_base if not replace_preset and project_base is not None
                       else base_preset if base_preset is not None else preset)
        pristine_base = copy.deepcopy(base_source)
        pristine_base.id = preset_id
        appearance_override = (
            {}
            if replace_preset
            else appearance_overrides_for_style(pristine_base, preset)
        )
        # SubtitleStyle.shadow is only an ASS-compatible scalar fallback.  The
        # inspector owns a richer independent contract (opacity/offset/blur/
        # spread), so persisting that scalar as an appearance override would
        # later collapse all five controls back onto one value.
        appearance_override.pop("shadow", None)
        style_modified = False
        if base_preset is not None:
            comparable = tuple(
                field for field in preset.__dataclass_fields__
                if field not in {"id", "name"}
            )
            style_modified = any(getattr(preset, field) != getattr(base_preset, field) for field in comparable)
        shared_outside_scope = any(c.id not in cue_ids and c.style_id == target_style_id
                                   for c in self.session.project.cues)
        if (scope != "all" and len(cue_ids) < len(self.session.project.cues)
                and (style_modified or preserve_advanced or shared_outside_scope)):
            signature = hashlib.sha1("\0".join(sorted(cue_ids)).encode("utf-8")).hexdigest()[:10]
            target_style_id = f"{preset_id}-scope-{signature}"
            preset.id = target_style_id
        styles = [item for item in self.session.project.styles if item.id != target_style_id] + [preset]
        if target_style_id != preset_id:
            styles = [item for item in styles if item.id != preset_id] + [pristine_base]
        style_recipes = dict(self.session.project.style_recipes)
        gradient = page._current_gradient()
        if gradient is None and isinstance(current_recipe_payload, Mapping):
            # An inspector reload (window resize / selection churn) can reset
            # the transient _fill_spec display back to solid while the project
            # recipe still owns a gradient. Stroke/shadow/layout commits must
            # never flatten that gradient; keep the persisted fill.
            prior_fill = (current_recipe_payload.get("colors") or {}).get("fill")
            if isinstance(prior_fill, Mapping) and str(prior_fill.get("type", "")).endswith("gradient"):
                gradient = dict(prior_fill)
        saved_recipe = StylePresetStore().load_recipes().get(preset_id)
        if preserve_advanced:
            recipe = StyleRecipe.from_dict(current_recipe_payload)
            recipe.typography.update({
                "fontFamily": preset.font_family, "fontSize": preset.font_size,
                "bold": preset.bold, "italic": preset.italic,
                "spacing": preset.spacing, "scaleX": preset.scale_x, "scaleY": preset.scale_y,
                # A new family must not keep the old one's face (2026-10-18:
                # 优设标题黑 kept Source Han's "Heavy / 900" and was reported missing).
                "fontWeight": preset.font_weight, "fontStyleName": preset.font_style_name,
                "fontFile": preset.font_file, "fontFaceIndex": preset.font_face_index,
            })
            recipe.layout.update({
                "alignment": preset.alignment, "marginL": preset.margin_l,
                "marginR": preset.margin_r, "marginV": preset.margin_v,
                "positionX": preset.position_x, "positionY": preset.position_y,
            })
            if getattr(page, "_motion_contract_dirty", False):
                recipe.motion = self._motion_contract_from_controls()
                # An explicit built-in motion selection replaces graph
                # choreography while retaining the graph's visual appearance
                # (strokes, panel, decorations, and effects).  Leaving the
                # old tracks in place makes motion_source() keep reporting
                # visual_graph and the inspector silently restores that item.
                if isinstance(recipe.visual_graph, Mapping):
                    visual_graph = copy.deepcopy(dict(recipe.visual_graph))
                    motion_graph = visual_graph.get("motionGraph")
                    if isinstance(motion_graph, dict):
                        motion_graph["tracks"] = []
                    recipe.visual_graph = visual_graph
            if gradient is not None:
                recipe.colors["fill"] = gradient
            elif FillSpec.from_value(recipe.colors.get("fill", preset.primary_color)).kind == "solid":
                recipe.colors["fill"] = preset.primary_color
            # Advanced fill and native style controls share one presentation
            # transaction.  Keep the existing advanced recipe, but update the
            # outline/background fields the user actually changed so Gradient
            # + Stroke cannot leave two conflicting truths.
            recipe.colors["outline"] = preset.outline_color
            recipe.colors["background"] = preset.back_color
            recipe.outline["color"] = preset.outline_color
            recipe.outline["width"] = preset.outline_width
            recipe.outline["shadow"] = self._shadow_from_controls(preset.shadow)
            recipe.effects["glow"] = normalize_glow_contract({
                "enabled": bool(page.style_glow.isChecked()),
                "color": page.style_glow_color.text(),
                "radius": float(page.style_glow_strength.value()),
            })
            stroke_layers = preset.stroke_layers()
            if len(stroke_layers) > 1:
                recipe.outline["layers"] = stroke_layers
            elif isinstance(recipe.outline.get("layers"), list) and recipe.outline["layers"]:
                first_layer = copy.deepcopy(dict(recipe.outline["layers"][0]))
                first_layer.update({
                    "color": preset.outline_color,
                    "width": preset.outline_width,
                })
                recipe.outline["layers"][0] = first_layer
            if isinstance(recipe.visual_graph, Mapping) and recipe.visual_graph:
                visual_graph = copy.deepcopy(dict(recipe.visual_graph))
                text_layer = visual_graph.get("textLayer")
                if isinstance(text_layer, dict):
                    font = text_layer.setdefault("font", {})
                    if isinstance(font, dict):
                        font.update({
                            "family": preset.font_family,
                            "size": preset.font_size,
                            "weight": 700 if preset.bold else 400,
                            "italic": preset.italic,
                        })
                    text_layer["strokes"] = copy.deepcopy(stroke_layers)
                    text_layer["shadow"] = copy.deepcopy(recipe.outline["shadow"])
                    text_layer["letterSpacing"] = preset.spacing
                    text_layer["alignment"] = preset.alignment
                if getattr(page, "_background_edited", False):
                    # Renderers paint the background from the graph's panel;
                    # an AI panel is only touched when the user edits it.
                    from ..caption_design.visual_design_graph import apply_background_to_graph

                    visual_graph = apply_background_to_graph(
                        visual_graph,
                        enabled=preset.border_style == 3,
                        color=preset.back_color,
                    )
                recipe.visual_graph = visual_graph
            recipe.background.update({
                "enabled": preset.border_style == 3,
                "color": preset.back_color,
            })
            style_recipes[target_style_id] = recipe.to_dict()
        elif replace_preset and isinstance(saved_recipe, Mapping):
            # A preset owns its authored rich shadow/graph. Inspector controls
            # still describe the previous cue during this transaction.
            style_recipes[target_style_id] = copy.deepcopy(dict(saved_recipe))
        elif gradient is not None or preset.shadow > 0 or page.style_glow.isChecked() or len(preset.stroke_layers()) > 1:
            candidate_recipe = page._style_recipe_for_style(preset, gradient)
            if getattr(page, "_motion_contract_dirty", False):
                # The first edit to a legacy/native style can materialize a
                # Remotion recipe because its rich shadow is representable
                # only in the graph.  That graph must not also retain the old
                # choreography after the user picked a built-in preset.
                candidate_graph = candidate_recipe.get("visualGraph")
                if isinstance(candidate_graph, Mapping):
                    candidate_graph = copy.deepcopy(dict(candidate_graph))
                    candidate_motion = candidate_graph.get("motionGraph")
                    if isinstance(candidate_motion, dict):
                        candidate_motion["tracks"] = []
                    candidate_recipe["visualGraph"] = candidate_graph
            style_recipes[target_style_id] = candidate_recipe
        elif isinstance(saved_recipe, Mapping):
            style_recipes[target_style_id] = copy.deepcopy(dict(saved_recipe))
        else:
            style_recipes.pop(target_style_id, None)
        effect = "none" if replace_preset else current_cue.effect_id
        effects = dict(self.session.project.effects)
        batch_style_ids: dict[str, str] = {}
        # 2026-09-19：勾选"同时应用位置与缩放"时，几何跟随当前有效样式
        # 传播；未勾选时保留每条目标字幕自己的几何。transform 里的几何键
        # （\pos/\fscx 逐事件覆盖）在应用几何时一并清理，否则压住新样式。
        apply_geometry_checked = bool(
            getattr(page, "style_apply_geometry", None)
            and page.style_apply_geometry.isChecked()
            and (position_edited or replace_preset)
        )
        geometry_fields = ("position_x", "position_y", "alignment", "margin_l", "margin_r", "margin_v", "scale_x", "scale_y")
        transform_overrides: dict[str, dict | None] = {}
        # Inspector coordinates are the final submitted video anchors. Scope
        # applies exactly to cue_ids; an initial allocation can never offset
        # these coordinates a second time or move another arranged caption.
        if position_edited or (apply_geometry_checked and len(cue_ids) > 1):
            for cue_id in cue_ids:
                cue = cue_by_id(self.session.project, cue_id)
                transform = copy.deepcopy(cue.transform or {})
                transform.update(position_x=next_x, position_y=next_y)
                transform_overrides[cue_id] = transform
        if len(cue_ids) > 1:
            existing_styles = {item.id: item for item in self.session.project.styles}
            common_recipe = copy.deepcopy(style_recipes.get(target_style_id))
            additions = []
            # 2026-10-21: one kept-geometry copy per previous style, not per
            # subtitle. 2,000 cues on the same style made 2,000 identical
            # copies that every later commit froze, thawed and snapshot.
            scoped_by_previous: dict[str, str] = {}
            for cue_id in cue_ids:
                cue = cue_by_id(self.session.project, cue_id)
                previous_style = existing_styles.get(cue.style_id)
                preserve_position = bool(
                    not replace_preset
                    and not apply_geometry_checked
                    and
                    previous_style is not None and any(
                        getattr(previous_style, name) != getattr(preset, name)
                        for name in geometry_fields
                    )
                )
                if not preserve_position:
                    batch_style_ids[cue_id] = target_style_id
                    if apply_geometry_checked and (not replace_preset) and cue_id not in transform_overrides:
                        cleaned = dict(cue.transform) if cue.transform else {}
                        transform_overrides[cue_id] = {
                            key: value
                            for key, value in cleaned.items()
                            if key not in {"position_x", "position_y", "scale_x", "scale_y"}
                        } or None
                    continue
                source_key = previous_style.id
                if source_key in scoped_by_previous:
                    batch_style_ids[cue_id] = scoped_by_previous[source_key]
                    continue
                scoped = copy.deepcopy(preset)
                scoped.id = f"{target_style_id}-cue-{hashlib.sha1(source_key.encode('utf-8')).hexdigest()[:8]}"
                scoped_by_previous[source_key] = scoped.id
                if previous_style is not None:
                    scoped.position_x = previous_style.position_x
                    scoped.position_y = previous_style.position_y
                    scoped.alignment = previous_style.alignment
                    scoped.margin_l = previous_style.margin_l
                    scoped.margin_r = previous_style.margin_r
                    scoped.margin_v = previous_style.margin_v
                    scoped.scale_x = previous_style.scale_x
                    scoped.scale_y = previous_style.scale_y
                batch_style_ids[cue_id] = scoped.id
                additions.append(scoped)
                if isinstance(common_recipe, Mapping):
                    scoped_recipe = copy.deepcopy(dict(common_recipe))
                    layout = scoped_recipe.setdefault("layout", {})
                    layout.update({
                        "positionX": scoped.position_x, "positionY": scoped.position_y,
                        "alignment": scoped.alignment, "marginL": scoped.margin_l,
                        "marginR": scoped.margin_r, "marginV": scoped.margin_v,
                    })
                    style_recipes[scoped.id] = scoped_recipe
            ids = set(batch_style_ids.values())
            styles = [item for item in styles if item.id not in ids or item.id == target_style_id] + additions
        # Copies this apply leaves without any subtitle or speaker go with it;
        # undo restores them with the rest of the previous presentation.
        from .style_cleanup import without_unused_derived,layer_style_ids
        targets = set(cue_ids)
        referenced = {cue.style_id for cue in self.session.project.cues if cue.id not in targets}
        referenced.update(speaker.style_id for speaker in self.session.project.speakers)
        referenced.update(batch_style_ids.get(cue_id, target_style_id) for cue_id in cue_ids)
        referenced.update(layer_style_ids(self.session.project.cues))
        styles, style_recipes, _removed = without_unused_derived(styles, style_recipes, referenced)
        if all(
            cue_by_id(self.session.project, cue_id).style_id == target_style_id
            and cue_by_id(self.session.project, cue_id).effect_id == effect
            and cue_by_id(self.session.project, cue_id).base_preset_id == preset_id
            and cue_by_id(self.session.project, cue_id).appearance_override == appearance_override
            for cue_id in cue_ids
        ) and self.session.project.styles == styles and self.session.project.effects == effects and self.session.project.style_recipes == style_recipes and not (
            len(cue_ids)>1 and apply_geometry_checked
            and self.session.project.studio_state.get('auto_subtitle_stacking',True)
        ):
            return
        text_before = {cue_id: cue_by_id(self.session.project, cue_id).text for cue_id in cue_ids}
        cue_count_before = len(self.session.project.cues)
        if len(cue_ids) == 1:
            command = SetCuePresentationCommand(
                    self.session.project,
                    cue_ids[0],
                    cue_changes={
                        "style_id": target_style_id,
                        "base_preset_id": preset_id,
                        "appearance_override": appearance_override,
                        "effect_id": effect,
                        **({'transform': transform_overrides[cue_ids[0]]}
                           if cue_ids[0] in transform_overrides else {}),
                    },
                    styles=styles,
                    effects=effects,
                    style_recipes=style_recipes,
                    text="Apply style",
                    changed=page._changed,
                )
        else:
            command = SetCuesPresentationCommand(
                self.session.project,
                cue_ids,
                style_id=target_style_id,
                effect_id=effect,
                effect_ids=None if replace_preset else {c.id: c.effect_id for c in self.session.project.cues if c.id in cue_ids},
                style_ids=batch_style_ids,
                base_preset_id=preset_id,
                appearance_override=appearance_override,
                styles=styles,
                effects=effects,
                style_recipes=style_recipes,
                transform_overrides=transform_overrides or None,
                text="Apply style to subtitles",
                changed=page._changed,
                merge_enabled=False,
            )
            if apply_geometry_checked:
                from .subtitle_stacking import stack_batch_presentation
                stack_batch_presentation(command)
        self.session.undo_stack.push(command)
        self._trace_subtitle_preset(preset_id, cue_ids, cue_count_before,
                                    scope=str(page.style_scope.currentData() or "current"))
        page._motion_contract_dirty = False
        page._background_edited = False
        selected_after = self.session._cue_lookup.get(self.session.selected_cue_id)
        payload_after = self.session.project.style_recipes.get(selected_after.style_id, {}) if selected_after else {}
        # Every presentation transaction commits the same foreground owner.
        # Native switches must revoke queued Advanced work just as eagerly as
        # Remotion switches queue their new identity.
        if payload_after and route_recipe(payload_after).engine == "remotion":
            page._queue_advanced_preview(payload_after, delay_ms=0)
        elif hasattr(page, "_revoke_advanced_preview"):
            page._revoke_advanced_preview(reason="style_route_commit_native")
        if hasattr(page, "ensure_active_subtitle_renderer"):
            page.ensure_active_subtitle_renderer(reason="style_route_commit")
        # Style presets are presentation-only. Keep this invariant explicit so
        # a future layer/preset refactor cannot create empty text targets.
        for cue_id, text_before_value in text_before.items():
            if cue_by_id(self.session.project, cue_id).text != text_before_value:
                raise RuntimeError("style application changed subtitle text")
        # Applying appearance must never split authored text or timing.
