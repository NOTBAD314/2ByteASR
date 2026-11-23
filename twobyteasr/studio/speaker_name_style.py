"""Per-speaker name colour, face and weight, like game subtitles (2026-11-20).

The speaker manager opens this for one speaker. Choices are previewed in the
dialog and applied as one undoable step; empty choices follow the caption.
"""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFontComboBox, QFormLayout,
                               QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget)

from ..i18n import tr

# Bright enough to read over game footage; the speaker manager's own swatches
# are muted UI colours.
NAME_SWATCHES = ("#FFD166", "#FF7AA2", "#7FD8FF", "#9BE37A", "#FFA552", "#C9A2FF", "#FF5A5A", "#FFFFFF")


def name_style_of(speaker) -> dict:
    return {'name_color': str(getattr(speaker, 'name_color', '') or ''),
            'name_font': str(getattr(speaker, 'name_font', '') or ''),
            'name_bold': bool(getattr(speaker, 'name_bold', False))}


def name_html(name: str, style: dict, *, fallback_color: str = '', fallback_font: str = '') -> str:
    """Rich-text name as it will look; empty fields use the fallbacks."""
    css = []
    color = style.get('name_color') or fallback_color
    font = style.get('name_font') or fallback_font
    if color:
        css.append(f'color:{escape(color, quote=True)}')
    if font:
        css.append("font-family:'" + escape(font, quote=True).replace("'", '') + "'")
    if style.get('name_bold'):
        css.append('font-weight:700')
    return f'<span style="{";".join(css)}">{escape(name)}</span>'


def caption_style_for(project, speaker):
    styles = {style.id: style for style in getattr(project, 'styles', ())}
    return styles.get(getattr(speaker, 'style_id', 'default')) or styles.get('default')


class SpeakerNameStyleDialog(QDialog):
    def __init__(self, project, speaker, display_name: str, sample: str, speaker_color: str,
                 names_shown: bool, parent=None):
        super().__init__(parent)
        self.setObjectName('speakerNameStyleDialog')
        self.setWindowTitle(tr('{name} 的名字样式', name=display_name))
        self._name = display_name + '：'
        self._sample = sample or tr('好可怕，好可怕。')
        self._speaker_color = speaker_color
        caption = caption_style_for(project, speaker)
        self._body_color = getattr(caption, 'primary_color', '#FFFFFF') or '#FFFFFF'
        self._body_font = getattr(caption, 'font_family', '') or ''
        self._outline = getattr(caption, 'outline_color', '#000000') or '#000000'
        self.style = name_style_of(speaker)
        self.initial = dict(self.style)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        note = QLabel(tr('名字可用自己的颜色和字体，像游戏字幕一样；未设定的部分跟随字幕样式。'
                         '预览、字幕压制与 ASS 导出都会用到，SRT 等纯文字格式只保留名字。'))
        note.setWordWrap(True)
        note.setObjectName('speakerMeta')
        layout.addWidget(note)

        self.preview = QLabel()
        self.preview.setObjectName('speakerNameStylePreview')
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(64)
        self.preview.setWordWrap(True)
        # A dark, video-like strip: the colours are meant for footage.
        self.preview.setStyleSheet('QLabel#speakerNameStylePreview{background:#1b1d22;border-radius:10px;'
                                   'padding:12px 16px;font-size:20px;}')
        layout.addWidget(self.preview)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        colors = QWidget()
        row = QHBoxLayout(colors)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.follow_color = QCheckBox(tr('跟随字幕'))
        self.follow_color.setObjectName('speakerNameFollowColor')
        row.addWidget(self.follow_color)
        self.swatches = []
        for value in NAME_SWATCHES:
            button = QToolButton()
            button.setObjectName('speakerNameSwatch')
            button.setFixedSize(24, 24)
            button.setToolTip(value)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty('swatch', value)
            button.clicked.connect(lambda _=False, color=value: self.set_color(color))
            row.addWidget(button)
            self.swatches.append(button)
        self.speaker_color_button = QPushButton(tr('用说话人颜色'))
        self.speaker_color_button.setObjectName('speakerNameUseSpeakerColor')
        self.speaker_color_button.setEnabled(QColor(speaker_color).isValid())
        self.speaker_color_button.clicked.connect(lambda: self.set_color(QColor(self._speaker_color).name()))
        row.addWidget(self.speaker_color_button)
        self.more_color = QPushButton(tr('更多颜色…'))
        self.more_color.setObjectName('speakerNameMoreColor')
        self.more_color.clicked.connect(self._more_color)
        row.addWidget(self.more_color)
        row.addStretch(1)
        form.addRow(tr('名字颜色'), colors)

        fonts = QWidget()
        font_row = QHBoxLayout(fonts)
        font_row.setContentsMargins(0, 0, 0, 0)
        font_row.setSpacing(8)
        self.follow_font = QCheckBox(tr('跟随字幕'))
        self.follow_font.setObjectName('speakerNameFollowFont')
        font_row.addWidget(self.follow_font)
        self.font_box = QFontComboBox()
        self.font_box.setObjectName('speakerNameFont')
        font_row.addWidget(self.font_box, 1)
        form.addRow(tr('名字字体'), fonts)

        self.bold = QCheckBox(tr('名字加粗'))
        self.bold.setObjectName('speakerNameBold')
        form.addRow('', self.bold)
        layout.addLayout(form)

        self.show_names = QCheckBox(tr('同时开启「字幕前显示名字」'))
        self.show_names.setObjectName('speakerNameAlsoShow')
        self.show_names.setChecked(True)
        self.show_names.setVisible(not names_shown)
        layout.addWidget(self.show_names)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.reset_button = buttons.addButton(tr('恢复跟随字幕'), QDialogButtonBox.ButtonRole.ResetRole)
        self.reset_button.clicked.connect(self.reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()
        self.follow_color.toggled.connect(self._follow_color_toggled)
        self.follow_font.toggled.connect(self._follow_font_toggled)
        self.font_box.currentFontChanged.connect(lambda font: self._set('name_font', font.family()))
        self.bold.toggled.connect(lambda value: self._set('name_bold', bool(value)))

    # ------------------------------------------------------------------ state
    def _load(self):
        for widget in (self.follow_color, self.follow_font, self.font_box, self.bold):
            widget.blockSignals(True)
        self.follow_color.setChecked(not self.style['name_color'])
        self.follow_font.setChecked(not self.style['name_font'])
        if self.style['name_font']:
            self.font_box.setCurrentText(self.style['name_font'])
        elif self._body_font:
            self.font_box.setCurrentText(self._body_font)
        self.font_box.setEnabled(bool(self.style['name_font']))
        self.bold.setChecked(self.style['name_bold'])
        for widget in (self.follow_color, self.follow_font, self.font_box, self.bold):
            widget.blockSignals(False)
        self._refresh()

    def _set(self, key, value):
        self.style[key] = value
        self._refresh()

    def set_color(self, color: str):
        value = QColor(color)
        if not value.isValid():
            return
        self.style['name_color'] = value.name().upper()
        self.follow_color.blockSignals(True)
        self.follow_color.setChecked(False)
        self.follow_color.blockSignals(False)
        self._refresh()

    def _follow_color_toggled(self, follow):
        if follow:
            self.style['name_color'] = ''
        elif not self.style['name_color']:
            self.style['name_color'] = NAME_SWATCHES[0]
        self._refresh()

    def _follow_font_toggled(self, follow):
        self.font_box.setEnabled(not follow)
        self.style['name_font'] = '' if follow else self.font_box.currentFont().family()
        self._refresh()

    def _more_color(self):
        from ..design.color_picker import SimpleColorDialog
        from ..design.studio_theme import apply_secondary_surface_theme
        current = QColor(self.style['name_color'] or self._body_color)
        dialog = SimpleColorDialog(current, self, title=tr('选择名字颜色'), common_colors=NAME_SWATCHES)
        apply_secondary_surface_theme(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_color().isValid():
            self.set_color(dialog.selected_color().name())

    def reset(self):
        self.style = {'name_color': '', 'name_font': '', 'name_bold': False}
        self._load()

    def _refresh(self):
        current = self.style['name_color'].upper()
        for button in self.swatches:
            value = button.property('swatch')
            ring = '#ffffff' if value.upper() == current else 'rgba(0,0,0,0.25)'
            width = 3 if value.upper() == current else 1
            button.setStyleSheet(f'QToolButton{{background:{value};border:{width}px solid {ring};border-radius:12px;}}')
        body_font = ("font-family:'" + escape(self._body_font, quote=True).replace("'", '') + "';") if self._body_font else ''
        self.preview.setText(
            name_html(self._name, self.style, fallback_color=self._body_color, fallback_font=self._body_font)
            + f'<span style="color:{escape(self._body_color, quote=True)};{body_font}">{escape(self._sample)}</span>')

    def changes(self) -> dict:
        return {key: value for key, value in self.style.items() if value != self.initial.get(key)}
