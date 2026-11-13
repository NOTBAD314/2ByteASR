# SPDX-License-Identifier: GPL-3.0-only
"""Cards of the home model picker (2026-11-12, user picked design B).

One card per model, two per row: logo and name, one line of what it is
good at, a few chips (price for cloud models, size for local ones, speakers,
languages), the accuracy bar and the buttons. The card keeps the names the
picker, its tests and audits use (``action``, ``configure``, ``download``,
``state_badge``, the ``selected`` property and the same signals as the
Workshop row card). All colours come from the picker's style sheet.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..i18n import bind_text
from ..design.elided_label import ElidedLabel
from .model_picker_copy import picker_copy
from ..design.typography import emphasized

_LANGUAGE_MARKS = (('zh', '中'), ('yue', '粤'), ('en', '英'), ('ja', '日'), ('ko', '韩'))


def language_chip_text(model_key: str) -> str:
    """``中 · 粤 · 英 · 日 · 韩`` for what the model handles well or usably."""
    from .model_languages import language_support
    try:
        support = language_support(model_key) or {}
    except Exception:
        return ''
    tiers = support.get('tiers') or {}
    marks = [mark for code, mark in _LANGUAGE_MARKS if tiers.get(code) in ('strong', 'usable')]
    if tiers.get('dialects') == 'strong':
        marks.append('方言')
    text = ' · '.join(marks)
    more = str(support.get('more') or '')
    if more:
        count = f'共 {more} 种' if '+' in more else f'+{more} 种'
        text = f'{text} · {count}' if text else count
    return text


class _Chip(QLabel):
    def __init__(self, text: str, tone: str = 'muted', parent=None):
        super().__init__(text, parent)
        self.setObjectName('pickerChip')
        self.setProperty('tone', tone)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class _AccuracyBar(QWidget):
    """准确度 ▬▬▬▬▬▬▬ 90 (or 暂无 without a reference score)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        caption = bind_text(QLabel(), '准确度')
        caption.setObjectName('pickerMetricCaption')
        self.track = QFrame()
        self.track.setObjectName('pickerMetricTrack')
        self.track.setFixedHeight(6)
        self.fill = QFrame(self.track)
        self.fill.setObjectName('pickerMetricFill')
        self.value = QLabel()
        self.value.setObjectName('pickerMetricValue')
        row.addWidget(caption)
        row.addWidget(self.track, 1)
        row.addWidget(self.value)
        self.score = None

    def set_score(self, score, tooltip: str = ''):
        self.score = None if score is None else max(0, min(100, int(score)))
        if self.score is None:
            bind_text(self.value, '暂无')
            self.value.setProperty('empty', True)
        else:
            self.value.setText(str(self.score))
            self.value.setProperty('empty', False)
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)
        self.setToolTip(tooltip)
        self._place()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def _place(self):
        width = round(self.track.width() * (self.score or 0) / 100)
        self.fill.setGeometry(0, 0, width, self.track.height())
        self.fill.setVisible(bool(self.score))


class PickerCard(QFrame):
    selected = Signal(str)
    action_requested = Signal(str)
    download_requested = Signal(str)
    uninstall_requested = Signal(str)
    api_configure_requested = Signal(str)
    diarize_toggled = Signal(bool)

    def __init__(self, model, role: str, *, recommended: bool, logo, accuracy: dict, online: bool,
                 size_text: str = '', diarization: bool = False, parent=None):
        super().__init__(parent)
        self.model = model
        self.role = role
        self.online = bool(online)
        self.recommended = bool(recommended)
        copy = picker_copy(model.key, role)
        self.tags = set(copy.tags) | ({'speakers'} if diarization and role == 'primary' else set())
        self.setObjectName('pickerCard')
        self.setProperty('selected', False)
        self.setProperty('recommended', self.recommended)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setMinimumHeight(84)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.monogram = QLabel()
        self.monogram.setObjectName('pickerLogo')
        self.monogram.setFixedSize(44, 44)
        self.monogram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo(self.monogram, QSize(34, 34))
        head.addWidget(self.monogram, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(1)
        self.title_label = QLabel(model.name)
        self.title_label.setObjectName('pickerName')
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bind_text(self.title_label, model.name)
        names.addWidget(self.title_label)
        self.subline = QLabel()
        self.subline.setObjectName('pickerSubline')
        self.subline.setProperty('recommended', self.recommended)
        if self.recommended:
            bind_text(self.subline, '★ 推荐')
        elif not self.online and size_text:
            self.subline.setText(size_text)
        else:
            bind_text(self.subline, '云端' if self.online else '本机')
        names.addWidget(self.subline)
        head.addLayout(names, 1)
        self.state_badge = QLabel()
        self.state_badge.setObjectName('pickerState')
        self.state_badge.setProperty('tone', 'muted')
        head.addWidget(self.state_badge, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)

        self.summary_label = QLabel(copy.line or model.summary)
        self.summary_label.setObjectName('pickerLine')
        self.summary_label.setWordWrap(True)
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.summary_label)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        if self.online and copy.price:
            chips.addWidget(_Chip(copy.price, 'price'))
        if not self.online and size_text:
            chips.addWidget(_Chip(size_text))
        if 'speakers' in self.tags and model.key != 'qwen_cloud_filetrans':
            chips.addWidget(bind_text(_Chip(''), '分说话人'))
        languages = language_chip_text(model.key)
        self.language_chip = None
        if languages:
            language_chip = ElidedLabel(languages, mode=Qt.TextElideMode.ElideRight, minimum=0)
            language_chip.setObjectName('pickerChip')
            language_chip.setProperty('tone', 'muted')
            language_chip.setWordWrap(False)
            language_chip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.language_chip = language_chip
            chips.addWidget(language_chip, 1)
        else:
            chips.addStretch(1)
        root.addLayout(chips)

        # Qwen Audio 3.1 separates speakers only when asked (2026-11-12, user:
        # its speaker labels are poor); the switch sits on its card.
        self.diarize = None
        if model.key == 'qwen_cloud_filetrans' and role == 'primary':
            from ..app.settings_widgets import PillSwitch
            line = QHBoxLayout()
            line.setSpacing(10)
            label = bind_text(QLabel(), '区分说话人')
            label.setObjectName('pickerOption')
            hint = bind_text(QLabel(), '默认关闭：只出文字和字级时间')
            hint.setObjectName('pickerOptionHint')
            hint.setWordWrap(True)
            hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.diarize = PillSwitch(False)
            bind_text(self.diarize, '区分说话人', property='accessibleName')
            self.diarize.toggled.connect(self.diarize_toggled)
            line.addWidget(label)
            line.addWidget(hint, 1)
            line.addWidget(self.diarize)
            root.addLayout(line)

        self.accuracy_bar = _AccuracyBar()
        score = accuracy.get('score') if accuracy.get('available') else None
        self.accuracy_bar.set_score(score, str(accuracy.get('tooltip') or ''))
        root.addWidget(self.accuracy_bar)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.action = QPushButton()
        self.action.setObjectName('pickerAction')
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.clicked.connect(lambda: self.action_requested.emit(model.key))
        self.download = bind_text(QPushButton(), '下载')
        self.download.setObjectName('pickerSecondary')
        self.download.clicked.connect(lambda: self.download_requested.emit(model.key))
        self.download.setVisible(bool(getattr(model, 'variants', ())))
        self.configure = bind_text(QPushButton(), '配置 Key')
        self.configure.setObjectName('pickerSecondary')
        bind_text(self.configure, '打开该服务的模型、地址与 API Key 配置窗口', property='toolTip')
        self.configure.setCursor(Qt.CursorShape.PointingHandCursor)
        self.configure.clicked.connect(lambda: self.api_configure_requested.emit(model.api_preset or ''))
        self.configure.setVisible(bool(model.api_preset))
        self.uninstall = QPushButton()   # never shown in the picker; kept for shared callers
        self.uninstall.hide()
        for button in (self.action, self.download, self.configure):
            button.setAutoDefault(False)
            button.setMinimumHeight(36)
            buttons.addWidget(button, 1)
        root.addLayout(buttons)

    # ----------------------------------------------------------- state
    def set_action_state(self, text, enabled):
        text, enabled = str(text), bool(enabled)
        if self.action.text() != text:
            self.action.setText(text)
        if self.action.isEnabled() != enabled:
            self.action.setEnabled(enabled)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.model.key)
        super().mousePressEvent(event)

    def _repolish(self, widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def set_selected(self, selected: bool):
        selected = bool(selected)
        if self.property('selected') is selected:
            return
        self.setProperty('selected', selected)
        self.action.setProperty('current', selected)
        self._repolish(self)
        self._repolish(self.action)

    def set_state_badge(self, text: str, tone: str = 'muted'):
        tone = tone if tone in {'ready', 'missing', 'muted', 'current'} else 'muted'
        if (self.state_badge.text(), self.state_badge.property('tone')) == (text, tone):
            return
        self.state_badge.setText(str(text or ''))
        self.state_badge.setProperty('tone', tone)
        self.state_badge.setVisible(bool(text))
        self._repolish(self.state_badge)

    def sync_configure_button(self, state: str) -> None:
        """An unconfigured API card's main button already says 配置: no second one."""
        visible = bool(self.model.api_preset) and state != 'configure'
        if self.configure.isHidden() == visible:
            self.configure.setVisible(visible)

    def set_uninstall_available(self, visible: bool, enabled: bool = True):
        self.uninstall.setVisible(False)

    def set_diarize(self, enabled: bool):
        if self.diarize is not None and self.diarize.isChecked() != bool(enabled):
            self.diarize.blockSignals(True)
            self.diarize.setChecked(bool(enabled))
            self.diarize.blockSignals(False)

    def matches(self, filter_key: str) -> bool:
        if filter_key in ('', 'all'):
            return True
        if filter_key == 'cloud':
            return self.online
        if filter_key == 'local':
            return not self.online
        return filter_key in self.tags


@emphasized
def build_picker_qss(t) -> str:
    from ..design.ui_theme import blend_hex

    def tone(color, light, dark):
        return blend_hex(t.surface, color, light if t.is_light else dark)
    quiet = tone(t.text, 0.07, 0.12)
    hover = tone(t.text, 0.11, 0.17)
    card = t.surface_elevated
    rest = blend_hex(t.surface, t.surface_elevated, 0.5)
    price = t.accent_soft
    return f"""
QWidget#modelPickerPanel {{ background: transparent; }}
QLabel#pickerTitle {{ font-size: 21px; font-weight: 900; color: {t.text}; background: transparent; }}
QLabel#pickerCurrent {{ font-size: 12px; color: {t.text_muted}; background: transparent; }}
QPushButton#pickerClose {{ background: {quiet}; color: {t.text}; border: 0; border-radius: 18px;
    min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; padding: 0; font-size: 16px; }}
QPushButton#pickerClose:hover {{ background: {hover}; }}
QPushButton#pickerFilter {{ min-height: 30px; max-height: 30px; padding: 0 14px; border-radius: 15px;
    background: transparent; color: {t.text}; border: 1px solid {t.border}; font-size: 12.5px; }}
QPushButton#pickerFilter:hover {{ background: {quiet}; }}
QPushButton#pickerFilter:checked {{ background: {t.text}; color: {t.surface}; border-color: {t.text}; font-weight: 700; }}
QScrollArea#workshopScroll {{ background: transparent; border: 0; }}
QWidget#workshopScrollHost {{ background: transparent; }}
QFrame#pickerCard {{ background: {rest}; border: 2px solid {t.border}; border-radius: 22px; }}
QFrame#pickerCard:hover {{ border-color: {t.border_strong}; }}
QFrame#pickerCard[selected="true"] {{ background: {card}; border: 2px solid {t.accent}; }}
QLabel#pickerLogo {{ background: transparent; border-radius: 14px; }}
QLabel#pickerName {{ font-size: 16px; font-weight: 900; color: {t.text}; background: transparent; }}
QLabel#pickerSubline {{ font-size: 11.5px; color: {t.text_muted}; background: transparent; }}
QLabel#pickerSubline[recommended="true"] {{ color: {t.focus}; font-weight: 700; }}
QLabel#pickerState {{ font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 10px;
    color: {t.text_secondary}; background: {quiet}; }}
QLabel#pickerState[tone="current"] {{ color: {t.success}; background: {tone(t.success, 0.16, 0.26)}; }}
QLabel#pickerState[tone="ready"] {{ color: {t.text_secondary}; background: {quiet}; }}
QLabel#pickerState[tone="missing"] {{ color: {t.text_muted}; background: transparent; border: 1px solid {t.border}; }}
QLabel#pickerLine {{ font-size: 14px; font-weight: 500; color: {t.text_secondary}; background: transparent; }}
QLabel#pickerChip {{ font-size: 12px; padding: 3px 9px; border-radius: 10px; color: {t.text_secondary};
    background: {quiet}; }}
QLabel#pickerChip[tone="price"] {{ color: {getattr(t, "accent_text", t.accent) if not t.is_light else t.accent}; background: {price}; font-weight: 700; }}
QLabel#pickerOption {{ font-size: 13px; font-weight: 600; color: {t.text}; background: transparent; }}
QLabel#pickerOptionHint {{ font-size: 11.5px; color: {t.text_muted}; background: transparent; }}
QLabel#pickerMetricCaption {{ font-size: 12px; color: {t.text_muted}; background: transparent; }}
QFrame#pickerMetricTrack {{ background: {tone(t.text, 0.12, 0.2)}; border: 0; border-radius: 3px; }}
QFrame#pickerMetricFill {{ background: {t.success}; border: 0; border-radius: 3px; }}
QLabel#pickerMetricValue {{ font-size: 13px; font-weight: 900; color: {t.text}; background: transparent; }}
QLabel#pickerMetricValue[empty="true"] {{ font-size: 12px; font-weight: 400; color: {t.text_muted}; }}
QPushButton#pickerAction {{ background: {t.accent}; color: {t.text_on_accent if hasattr(t, 'text_on_accent') else '#ffffff'};
    border: 0; border-radius: 12px; padding: 0 14px; font-size: 13px; font-weight: 700; }}
QPushButton#pickerAction:hover {{ background: {t.accent_hover}; }}
QPushButton#pickerAction[current="true"] {{ background: transparent; color: {t.text_secondary};
    border: 1px solid {t.border}; font-weight: 500; }}
QPushButton#pickerAction[current="true"]:hover {{ background: {quiet}; }}
QPushButton#pickerAction:disabled {{ background: {quiet}; color: {t.disabled}; }}
QPushButton#pickerSecondary {{ background: {quiet}; color: {t.text}; border: 0; border-radius: 12px;
    padding: 0 14px; font-size: 13px; }}
QPushButton#pickerSecondary:hover {{ background: {hover}; }}
QLabel#pickerFooterNote {{ font-size: 12px; color: {t.text_muted}; background: transparent; }}
QPushButton#pickerDone {{ background: {t.accent}; color: #ffffff; border: 0; border-radius: 14px;
    min-height: 42px; padding: 0 26px; font-size: 14px; font-weight: 700; }}
QPushButton#pickerDone:hover {{ background: {t.accent_hover}; }}
"""


__all__ = ['PickerCard', 'build_picker_qss', 'language_chip_text']
