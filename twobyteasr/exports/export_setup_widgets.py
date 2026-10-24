"""Soft-filled pieces of the 导出字幕视频 setup page (design A, 2026-10-23).

The page keeps its existing controls; these helpers only regroup and dress
them the way the user picked on the redesign canvas: captions inside filled
fields, preset chips bound to the preset dropdown, one file-name well with the
prefix and suffix as chips, facts as pills, cards without frame lines.
Everything is scoped to ``QWidget#exportSetupPage`` and appended after the
older outlined export sheet, so these rules win at equal specificity.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QWidget)

from ..design.soft_qss import control_icons
from ..design.soft_widgets import CaptionField, WrapLayout, _repolish
from ..design.ui_theme import ThemeDefinition, blend_hex

#: Height of a control inside a caption field (the caption sits above it).
FIELD_HEIGHT = 22


def captioned(caption: str, field: QWidget, *, label: QLabel | None = None,
              role: str | None = None) -> CaptionField:
    """Wrap ``field`` in a filled caption field.

    ``label`` reuses an existing caption label whose text the page changes
    later (``CRF`` / ``CQ / CQP``); ``role`` keeps the field's old
    ``fieldWidth`` contract once the wrapper has made it flexible.
    """
    frame = CaptionField("" if label is not None else caption, field)
    if label is not None:
        lines = frame.layout()
        lines.removeWidget(frame.caption)
        frame.caption.deleteLater()
        label.setObjectName("softCaption")
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lines.insertWidget(0, label)
        frame.caption = label
    field.setMinimumHeight(FIELD_HEIGHT)
    field.setMaximumHeight(FIELD_HEIGHT)
    if role:
        field.setProperty("fieldWidth", role)
    field._caption_host = frame
    return frame


def show_field(field: QWidget, visible: bool) -> None:
    """Show or hide a field together with the caption field around it."""
    field.setVisible(visible)
    host = getattr(field, "_caption_host", None)
    if host is not None:
        host.setVisible(visible)


class PresetChips(QWidget):
    """The export presets as a row of chips bound to the preset dropdown.

    The dropdown stays the model (and the object the page reads); a chip
    click sets its index like a user pick. Rows wrap instead of clipping when
    a long interface language or saved user presets need more room.
    """

    def __init__(self, combo: QComboBox, parent: QWidget | None = None):
        super().__init__(parent)
        self.combo = combo
        self.flow = WrapLayout(self, spacing=6, fill=False)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.idClicked.connect(self._picked)
        self.buttons: list[QPushButton] = []
        self.trailing: QWidget | None = None
        model = combo.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.dataChanged, model.modelReset):
            signal.connect(self.rebuild)
        combo.currentIndexChanged.connect(self.sync)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.rebuild()

    def rebuild(self, *_args) -> None:
        texts = [self.combo.itemText(index) for index in range(self.combo.count())]
        if texts == [button.text() for button in self.buttons]:
            self.sync()
            return
        for button in self.buttons:
            self.group.removeButton(button)
            self.flow.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.buttons = []
        for index, text in enumerate(texts):
            button = QPushButton(text, self)
            button.setObjectName("exportPresetChip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("flexibleWidth", True)
            self.group.addButton(button, index)
            self.flow.insertWidget(index, button)
            self.buttons.append(button)
        self.sync()
        self.updateGeometry()

    def set_trailing(self, widget: QWidget) -> None:
        """A command that follows the last chip (the preset menu)."""
        self.trailing = widget
        self.flow.addWidget(widget)

    def sync(self, *_args) -> None:
        current = self.combo.currentIndex()
        for index, button in enumerate(self.buttons):
            button.blockSignals(True)
            button.setChecked(index == current)
            button.blockSignals(False)

    def _picked(self, index: int) -> None:
        if index != self.combo.currentIndex():
            self.combo.setCurrentIndex(index)
        self.combo.activated.emit(index)
        self.sync()


class _WellFocus(QObject):
    """Mark the file-name well while one of its boxes has keyboard focus."""

    def __init__(self, well: QFrame, *editors: QWidget):
        super().__init__(well)
        self.well = well
        for editor in editors:
            editor.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            focused = any(child.hasFocus() for child in self.well.findChildren(QWidget))
            if bool(self.well.property("focused")) != focused:
                self.well.setProperty("focused", focused)
                _repolish(self.well)
        return False


def name_well(prefix: QComboBox, name: QWidget, suffix: QComboBox, extension: QLabel) -> QFrame:
    """One filled well: [prefix chip] name [suffix chip] .ext"""
    well = QFrame()
    well.setObjectName("exportNameWell")
    row = QHBoxLayout(well)
    row.setContentsMargins(6, 0, 10, 0)
    row.setSpacing(6)
    for affix in (prefix, suffix):
        affix.setObjectName("exportAffix")
        affix.setCursor(Qt.CursorShape.IBeamCursor)
        affix.editTextChanged.connect(lambda _text, combo=affix: fit_affix(combo))
        fit_affix(affix)
    name.setMinimumHeight(30)
    name.setMaximumHeight(30)
    name.setMinimumWidth(60)
    extension.setObjectName("exportNameExtension")
    row.addWidget(prefix)
    row.addWidget(name, 1)
    row.addWidget(suffix)
    row.addWidget(extension)
    well.setMinimumHeight(44)
    well.setMaximumHeight(44)
    well.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _WellFocus(well, prefix.lineEdit(), name, suffix.lineEdit())
    return well


def fit_affix(combo: QComboBox) -> None:
    """A prefix / suffix chip as wide as its text (or its placeholder)."""
    edit = combo.lineEdit()
    text = combo.currentText()
    shown = text or (edit.placeholderText() if edit is not None else "")
    metrics = combo.fontMetrics()
    width = metrics.horizontalAdvance(shown) + 44
    combo.setFixedWidth(max(64, min(220, width)))
    combo.setFixedHeight(30)
    empty = not text
    if combo.property("empty") != empty:
        combo.setProperty("empty", empty)
        _repolish(combo)


def fill_pills(flow: WrapLayout, host: QWidget, texts: list[str], name: str = "exportSummaryChip") -> list[QLabel]:
    """Show ``texts`` as quiet pills in ``flow``; labels are reused in place."""
    labels = [flow.itemAt(index).widget() for index in range(flow.count())]
    labels = [label for label in labels if isinstance(label, QLabel)]
    while len(labels) < len(texts):
        label = QLabel(host)
        label.setObjectName(name)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        flow.addWidget(label)
        labels.append(label)
    for label, text in zip(labels, texts):
        label.setText(text)
        label.show()
    for label in labels[len(texts):]:
        label.hide()
    host.updateGeometry()
    return labels[:len(texts)]


def source_is_audio_only(project) -> bool:
    """True when no media in the project has a picture (an MP3 project):
    the export then draws subtitles on a black frame."""
    assets = list(getattr(project, "media_pool", None) or [])
    if not assets:
        return False
    return all((getattr(asset, "video_metadata", None) or {}).get("has_video") is False for asset in assets)


def export_setup_qss(t: ThemeDefinition) -> str:
    """The setup page in the soft-filled style (cards on the page background,
    filled wells inside the cards)."""
    light = t.is_light
    card = t.surface
    fill = blend_hex(card, t.text, 0.065 if light else 0.08)
    fill_hover = blend_hex(card, t.text, 0.10 if light else 0.13)
    fill_strong = blend_hex(card, t.text, 0.15 if light else 0.2)
    fill_disabled = blend_hex(card, t.text, 0.035)
    raised = t.surface_elevated if light else blend_hex(card, t.text, 0.2)
    chip = blend_hex(card, t.accent, 0.14 if light else 0.24)
    chip_hover = blend_hex(card, t.accent, 0.22 if light else 0.34)
    primary_disabled = blend_hex(card, t.accent, 0.42)
    page_fill = blend_hex(t.app_background, t.text, 0.06 if light else 0.08)
    content = t.zone_colors.get("content", t.accent)
    native_tint = blend_hex(t.app_background, content, 0.17 if light else 0.24)
    advanced_tint = blend_hex(t.app_background, t.info, 0.17 if light else 0.24)
    icon = control_icons(t)
    chevron_accent = icon["chevron"]
    S = "QWidget#exportSetupPage"
    fields = ("QComboBox", "QLineEdit", "QAbstractSpinBox")
    caption = f"{S} QFrame#softCaptionField"
    seg = f"{S} QFrame#softSegmented"
    track = f"{S} QFrame#exportChoiceTrack"
    rng = f"{S} QWidget#projectRangeBar"
    return f"""
/* ---- cards: a raised fill, rounded, no frame line ---- */
{S} QFrame[exportCard="true"], {S} QFrame[softCard="true"], {S} QFrame#exportPreviewPanel, {S} QFrame#exportFooter {{
    background: {card}; border: 0; border-radius: 16px;
}}
{S} QFrame[softCard="true"] QFrame[softCard="true"] {{ background: transparent; border-radius: 0; }}
{S} QLabel#exportCardTitle, {S} QLabel#softCardTitle {{ background: transparent; color: {t.text}; font-size: 15px; font-weight: 800; }}
{S} QLabel#softCardTitle[nested="true"] {{ font-size: 13px; font-weight: 700; }}
{S} QLabel#exportCardIcon {{ background: {chip}; border-radius: 9px; }}
{S} QLabel#exportCardMeta, {S} QLabel#cardMeta, {S} QLabel#softCardSummary, {S} QLabel#exportEstimate {{
    background: transparent; color: {t.text_muted}; font-size: 12px; font-weight: 500;
}}
{S} QLabel#softCardSummary {{ font-weight: 600; }}
{S} QLabel#exportFieldLabel {{ background: transparent; color: {t.text_secondary}; font-size: 12px; font-weight: 700; }}
{S} QPushButton#softFoldHeader, {S} QPushButton#softFoldHeader:hover, {S} QPushButton#softFoldHeader:pressed,
{S} QPushButton#softFoldHeader:checked, {S} QPushButton#softFoldHeader:focus {{
    background: transparent; border: 0; border-radius: 0; padding: 0; min-height: 28px; max-height: 32px;
}}
{S} QToolButton#softFoldArrow {{ background: transparent; border: 0; padding: 0; }}

/* ---- fields: filled wells, no outline ---- */
{", ".join(f"{S} {f}" for f in fields)} {{
    background: {fill}; color: {t.text}; border: 1px solid transparent; border-radius: 10px;
    padding: 0 10px; selection-background-color: {t.accent}; selection-color: {t.text_on_accent};
}}
{", ".join(f"{S} {f}:hover" for f in fields)} {{ background: {fill_hover}; border-color: transparent; }}
{", ".join(f"{S} {f}:focus" for f in fields)} {{ border-color: {t.accent}; }}
{", ".join(f"{S} {f}:disabled" for f in fields)} {{ background: {fill_disabled}; color: {t.disabled}; }}
{S} QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 20px; height: 20px;
    margin-right: 5px; border: 0; border-radius: 9px; background: {chip};
}}
{S} QComboBox::down-arrow {{ image: url({chevron_accent}); width: 10px; height: 10px; }}
{S} QComboBox QLineEdit {{ background: transparent; border: 0; padding: 0; border-radius: 0; }}
{S} QAbstractSpinBox::up-button, {S} QAbstractSpinBox::down-button {{ width: 0; border: 0; }}

/* ---- caption inside the field ---- */
{caption} {{ background: {fill}; border: 1px solid transparent; border-radius: 11px; }}
{caption}:hover {{ background: {fill_hover}; }}
{caption}[focused="true"] {{ border-color: {t.accent}; }}
{caption}[off="true"] {{ background: {fill_disabled}; }}
{caption} QLabel#softCaption {{ background: transparent; color: {t.text_muted}; font-size: 11px; font-weight: 600; }}
{", ".join(f"{caption} {f}, {caption} {f}:hover, {caption} {f}:focus, {caption} {f}:disabled" for f in fields)} {{
    background: transparent; border: 0; border-radius: 0; padding: 0; font-weight: 600;
}}
{caption} QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 14px; height: 14px;
    margin-right: 0; background: transparent; border: 0;
}}
{caption} QComboBox::down-arrow {{ image: url({icon['chevron_muted']}); width: 11px; height: 11px; }}
{caption} QComboBox::down-arrow:disabled {{ image: url({icon['chevron_disabled']}); }}

/* ---- the file name: prefix chip, name, suffix chip in one well ---- */
{S} QFrame#exportNameWell {{ background: {fill}; border: 1px solid transparent; border-radius: 12px; }}
{S} QFrame#exportNameWell[focused="true"] {{ border-color: {t.accent}; }}
{S} QFrame#exportNameWell QLineEdit, {S} QFrame#exportNameWell QLineEdit:hover, {S} QFrame#exportNameWell QLineEdit:focus {{
    background: transparent; border: 0; padding: 0 2px; font-size: 15px; font-weight: 700;
}}
{S} QComboBox#exportAffix, {S} QComboBox#exportAffix:hover, {S} QComboBox#exportAffix:focus {{
    background: {chip}; color: {t.accent_text}; border: 1px solid transparent; border-radius: 9px;
    padding: 0 2px 0 9px; font-size: 13px; font-weight: 700;
}}
{S} QComboBox#exportAffix:hover {{ background: {chip_hover}; }}
{S} QComboBox#exportAffix[empty="true"] {{ background: transparent; color: {t.text_muted}; border: 1px solid {fill_strong}; }}
{S} QComboBox#exportAffix[empty="true"]:hover {{ background: {fill_hover}; }}
{S} QComboBox#exportAffix QLineEdit {{ color: {t.accent_text}; font-size: 13px; font-weight: 700; }}
{S} QComboBox#exportAffix[empty="true"] QLineEdit {{ color: {t.text_muted}; font-weight: 600; }}
{S} QComboBox#exportAffix::drop-down {{ width: 16px; height: 16px; margin-right: 2px; background: transparent; }}
{S} QLabel#exportNameExtension {{ background: transparent; color: {t.text_muted}; font-size: 14px; font-weight: 600; }}

/* ---- buttons: tonal fills, the export in the accent ---- */
{S} QPushButton, {S} QToolButton {{
    background: {fill}; color: {t.text}; border: 1px solid transparent; border-radius: 10px;
    min-height: 32px; padding: 0 14px; font-weight: 600;
}}
{S} QPushButton:hover, {S} QToolButton:hover {{ background: {fill_hover}; color: {t.text}; border-color: transparent; }}
{S} QPushButton:pressed, {S} QToolButton:pressed {{ background: {fill_strong}; }}
{S} QPushButton:focus, {S} QToolButton:focus {{ border-color: {t.focus}; }}
{S} QPushButton:disabled, {S} QToolButton:disabled {{ background: {fill_disabled}; color: {t.disabled}; }}
{S} QToolButton::menu-indicator {{ image: none; width: 0; }}
{S} QToolButton#exportPresetMenu {{ min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; padding: 0; }}
{S} QPushButton[exportTone="tint"] {{ background: {chip}; color: {t.accent_text}; }}
{S} QPushButton[exportTone="tint"]:hover {{ background: {chip_hover}; color: {t.accent_text}; }}
{S} QPushButton[exportTone="ghost"] {{ background: transparent; color: {t.text_secondary}; }}
{S} QPushButton[exportTone="ghost"]:hover {{ background: {fill}; color: {t.text}; }}
{S} QPushButton[exportSize="sm"] {{ min-height: 28px; max-height: 28px; padding: 0 11px; border-radius: 9px; font-size: 12px; }}
{S} QPushButton#exportBackButton {{
    background: {card}; color: {t.text}; border: 1px solid transparent; border-radius: 11px;
    min-height: 36px; max-height: 36px; padding: 0 14px; font-weight: 600;
}}
{S} QPushButton#exportBackButton:hover {{ background: {raised}; color: {t.text}; }}
{S} QPushButton#exportQueueButton {{ font-size: 15px; font-weight: 600; border-radius: 13px; }}
{S} QPushButton#exportStartButton {{
    background: {t.accent}; color: {t.text_on_accent}; border-radius: 13px; font-size: 15px; font-weight: 700;
}}
{S} QPushButton#exportStartButton:hover {{ background: {t.accent_hover}; color: {t.text_on_accent}; }}
{S} QPushButton#exportStartButton:pressed {{ background: {t.accent_pressed}; color: {t.text_on_accent}; }}
{S} QPushButton#exportStartButton:disabled {{ background: {primary_disabled}; color: {t.text_on_accent}; }}
{S} QPushButton#exportPlayButton {{
    background: {t.accent}; color: {t.text_on_accent}; border: 1px solid transparent; border-radius: 19px;
    min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; padding: 0;
}}
{S} QPushButton#exportPlayButton:hover {{ background: {t.accent_hover}; }}

/* ---- presets as chips ---- */
{S} QPushButton#exportPresetChip {{
    background: {fill}; color: {t.text_secondary}; border: 1px solid transparent; border-radius: 15px;
    min-height: 30px; max-height: 30px; padding: 0 11px; font-weight: 600;
}}
{S} QPushButton#exportPresetChip:hover {{ background: {fill_hover}; color: {t.text}; }}
{S} QPushButton#exportPresetChip:checked {{ background: {chip}; color: {t.accent_text}; }}

/* ---- segments: the chosen one raised ---- */
{seg} {{ background: {fill}; border: 0; border-radius: 11px; }}
{seg}[collapsed="true"] {{ background: transparent; }}
{seg} QPushButton {{
    background: transparent; color: {t.text_secondary}; border: 0; border-radius: 8px;
    min-height: 30px; max-height: 30px; padding: 0 10px; font-weight: 600;
}}
{seg} QPushButton:hover {{ background: {fill_hover}; color: {t.text}; }}
{seg} QPushButton:checked {{ background: {raised}; color: {t.accent_text}; }}
{seg} QPushButton:disabled {{ background: transparent; color: {t.disabled}; }}
{track} {{ background: {fill}; border: 0; border-radius: 11px; }}
{track} QRadioButton {{
    background: transparent; color: {t.text_secondary}; border: 0; border-radius: 8px;
    min-height: 30px; max-height: 30px; padding: 0 10px; font-weight: 600; spacing: 0;
}}
{track} QRadioButton::indicator {{ width: 0; height: 0; margin: 0; border: 0; background: transparent; image: none; }}
{track} QRadioButton:hover {{ background: {fill_hover}; color: {t.text}; }}
{track} QRadioButton:checked {{ background: {raised}; color: {t.accent_text}; }}

/* ---- check boxes and switches ---- */
{S} QCheckBox {{ background: transparent; color: {t.text}; spacing: 8px; padding: 3px 2px; }}
{S} QCheckBox::indicator {{ width: 18px; height: 18px; border: 0; border-radius: 5px; background: {fill_strong}; image: none; }}
{S} QCheckBox::indicator:hover {{ background: {blend_hex(fill_strong, t.text, 0.06)}; }}
{S} QCheckBox::indicator:checked {{ background: {t.accent}; image: url({icon['check']}); }}
{S} QCheckBox::indicator:disabled {{ background: {fill_disabled}; }}
{S} QCheckBox[softSwitch="true"]::indicator {{ width: 36px; height: 20px; border-radius: 0; background: transparent; image: url({icon['switch_off']}); }}
{S} QCheckBox[softSwitch="true"]::indicator:checked {{ background: transparent; image: url({icon['switch_on']}); }}

/* ---- range: one filled segment per point ---- */
{rng} QFrame#rangeSegment {{ background: {fill}; border: 0; border-radius: 11px; }}
{rng} QPushButton#rangeMark {{
    background: {raised}; color: {t.accent_text}; border: 0; border-radius: 8px;
    min-height: 28px; max-height: 28px; padding: 0 9px; margin: 3px 0 3px 3px; font-weight: 700;
}}
{rng} QPushButton#rangeMark:hover {{ background: {chip}; }}
{rng} QLineEdit#rangeField, {rng} QLineEdit#rangeField:hover {{ background: transparent; border: 0; padding: 0 6px; font-weight: 600; }}
{rng} QLineEdit#rangeField:focus {{ background: transparent; border: 0; }}
{rng} QPushButton#rangeJump {{ background: transparent; border: 0; border-radius: 8px; min-height: 28px; max-height: 28px; padding: 0; margin: 3px 3px 3px 0; }}
{rng} QPushButton#rangeJump:hover {{ background: {fill_hover}; }}
{S} QLabel#rangeStatus {{ background: transparent; color: {t.text_muted}; font-size: 12px; }}
{S} QPushButton#rangeClear {{ background: transparent; color: {t.text_secondary}; min-height: 30px; max-height: 30px; padding: 0 10px; border-radius: 9px; }}
{S} QPushButton#rangeClear:hover {{ background: {fill}; color: {t.text}; }}

/* ---- facts as pills ---- */
{S} QLabel#exportSummaryChip {{
    background: {fill}; color: {t.text_secondary}; border-radius: 13px; padding: 0 11px;
    min-height: 26px; max-height: 26px; font-size: 12px; font-weight: 600;
}}
{S} QLabel#exportSourcePill {{
    background: {fill}; color: {t.text_muted}; border-radius: 13px; padding: 0 11px;
    min-height: 26px; max-height: 26px; font-size: 12px; font-weight: 700;
}}
{S} QLabel#exportRendererBadge {{
    background: {native_tint}; color: {content}; border: 0; border-radius: 13px; padding: 0 12px;
    min-height: 26px; max-height: 26px; font-size: 12px; font-weight: 700;
}}
{S} QLabel#exportRendererBadge[rendererKind="advanced"] {{ background: {advanced_tint}; color: {t.info}; }}
{S} QLabel#exportOutputIcon {{ background: {chip}; border-radius: 9px; }}
{S} QLabel#exportOutputPath {{ background: transparent; color: {t.text_secondary}; font-size: 13px; }}
{S} QLabel#exportRangeLabel {{ background: transparent; color: {t.danger}; font-size: 12px; font-weight: 600; }}
{S} QFrame#exportRule {{ background: {blend_hex(card, t.text, 0.08)}; border: 0; min-height: 1px; max-height: 1px; }}
{S} QFrame#exportPreviewHost {{ background: {t.media}; border: 0; border-radius: 12px; }}
{S} QSplitter::handle {{ background: transparent; }}
{S} QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
{S} QScrollBar::handle:vertical {{ background: {page_fill}; border-radius: 3px; min-height: 40px; }}
{S} QScrollBar::add-line:vertical, {S} QScrollBar::sub-line:vertical {{ height: 0; }}
"""


__all__ = [
    "FIELD_HEIGHT", "PresetChips", "captioned", "export_setup_qss", "fill_pills", "fit_affix",
    "name_well", "show_field", "source_is_audio_only",
]
