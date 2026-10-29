"""The motion tool page: stage bar, parameters, category chips and live cards.

Cards are rendered by the real caption renderer. Every stage choice stays a
draft until 「应用」, through the existing scoped motion workflow.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSignalBlocker, Signal, QRect, QSize, QPoint, QTimer
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout,
                              QGridLayout, QStackedWidget, QDoubleSpinBox, QSlider,
                              QScrollArea, QFrame, QSizePolicy, QLayout)

from ..i18n import tr
from .effect_dsl import validate_effect
from .letter_motion import PRESETS
from .motion_catalog import CATEGORIES, ENTRY, EXIT, LOOP, spec, signature_progress

WORDS = [
    ('none', '整句显示', 'karaoke', '整句一起显示，不按字词变化'),
    ('karaoke_wipe', '蓝白卡拉 OK', 'karaoke', '白字常显，蓝色沿语音连续扫过'),
    ('word_reveal', '逐词出现', 'karaoke', '说到哪个词，哪个词出现'),
    ('karaoke_highlight', '依次点亮', 'karaoke', '说过的词依次变色'),
    ('word_current', '当前词高亮', 'karaoke', '只有正在说的词变色'),
    ('word_pop', '逐词弹出', 'beat', '每个词出声时弹出来'),
    ('word_current_pop', '当前词放大', 'beat', '正在说的词放大并变色'),
    ('word_punch', '逐词重击', 'beat', '每个词出声时闪白一击'),
    ('word_ripple', '回声点亮', 'beat', '每个词出声时荡开一圈回声'),
    *[(key, label, 'curated', hint) for key, (label, hint, _) in PRESETS.items()],
]
STAGES = ('entry', 'exit', 'loop', 'words')
STAGE_TITLES = {'entry': '入场', 'exit': '出场', 'loop': '循环', 'words': '逐词'}
_SPECS = {'entry': ENTRY, 'exit': EXIT, 'loop': LOOP}
CHOICES = {**{stage: [(m.key, m.label) for m in items] for stage, items in _SPECS.items()},
           'words': [(key, label) for key, label, _, _ in WORDS]}
CATEGORY = {**{(m.stage, m.key): m.category for items in _SPECS.values() for m in items},
            **{('words', key): category for key, _, category, _ in WORDS}}
HINTS = {**{(m.stage, m.key): m.hint for items in _SPECS.values() for m in items},
         **{('words', key): hint for key, _, _, hint in WORDS}}
STRENGTHS = [('low', '轻'), ('medium', '标准'), ('high', '强')]
ARROWS = [('left', '←'), ('right', '→'), ('up', '↑'), ('down', '↓')]
TILE_HEIGHT, PREVIEW_HEIGHT = 84, 52
# 2026-10-23 (user's design A): the stage track, chips, segments and tiles are
# styled with the other soft controls in design/soft_qss.py (theme colours).


def demo_project(effect, text='字幕动效', duration=2400):
    """A neutral one-cue project with measured words, for cards and examples."""
    from ..projects.studio_project import SubtitleProject, StudioMedia, StudioCue, SubtitleStyle
    project = SubtitleProject(media=StudioMedia(path='motion-card', duration_ms=duration),
        styles=[SubtitleStyle('default', '字幕', font_family='Microsoft YaHei', font_size=72,
                              primary_color='#FFFFFFFF', outline_width=1, shadow=0)],
        cues=[StudioCue('card', 0, duration, text, effect_id='card', evidence_refs=['card'])],
        asr_evidence={'card': {'words': [dict(text=char, start_ms=200+i*500, end_ms=550+i*500)
                                        for i, char in enumerate(text.replace(' ', ''))]}})
    project.effects['card'] = validate_effect(effect)
    return project


def stage_effect(stage, key, *, color=None):
    """The card's effect: one stage only, at its own default timing."""
    effect = {'entry': {'type': 'none'}, 'exit': {'type': 'none'}}
    item = spec(stage, key) if stage != 'words' else None
    if stage in {'entry', 'exit'} and key != 'none':
        if item and not item.legacy:
            effect[stage] = {'type': key}
        else:
            from .effect_dsl import builtin_effects
            effect[stage] = {**builtin_effects()[key]['entry'], 'duration': 650}
            if stage == 'exit' and key == 'scale':
                effect[stage]['scale_from'] = 65
    elif stage == 'loop' and key != 'none':
        effect['loop'] = {'type': key, 'duration': item.duration if item else 1200}
    elif stage == 'words':
        effect['word_highlight'] = {'type': key, 'color': color or ('#4D9FFF' if key == 'karaoke_wipe' else
                                   PRESETS[key][2] if key in PRESETS else '#7DD3FC')}
    return validate_effect(effect)


def poster_ms(stage, key, effect, duration=2400):
    """A moment where the motion is visibly underway, never the settled line."""
    if stage == 'entry':
        length = effect['entry'].get('duration', 400)
        return length*signature_progress(stage, key)
    if stage == 'exit':
        length = effect['exit'].get('duration', 400)
        return duration-length*(1-signature_progress(stage, key))
    if stage == 'loop':
        period = effect.get('loop', {}).get('duration', 1200)
        return 900+period*.3
    return {'word_mist': .94, 'word_sweep': .19, 'word_pulse': .93, 'word_echo': .28,
            'word_float': .875, 'word_dust': .94}.get(key, .45)*duration


class FlowLayout(QLayout):
    """Chips wrap to the next line in a narrow panel instead of clipping."""
    def __init__(self, parent=None, spacing=5):
        super().__init__(parent)
        self.items, self._spacing = [], spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, index): return self.items[index] if 0 <= index < len(self.items) else None
    def takeAt(self, index): return self.items.pop(index) if 0 <= index < len(self.items) else None
    def expandingDirections(self): return Qt.Orientations()
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self._place(QRect(0, 0, width, 0), apply=False)
    def sizeHint(self): return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def _place(self, rect, *, apply):
        x, y, line = rect.x(), rect.y(), 0
        for item in self.items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x > rect.x() and x+hint.width() > rect.right()+1:
                x, y, line = rect.x(), y+line+self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width()+self._spacing
            line = max(line, hint.height())
        return y+line-rect.y()


class MotionPanel(QWidget):
    """Keep at least one full row of cards usable in a short workspace."""
    def resizeEvent(self, event):
        super().resizeEvent(event)
        preview = getattr(self, 'responsive_preview', None)
        if preview is not None:
            preview.setVisible(self.height() >= 420)


class StageButton(QPushButton):
    """Stage name over the current choice, painted directly so app-wide
    label rules cannot clip or recolour the second line."""
    def __init__(self, title, parent):
        super().__init__(parent)
        self.setObjectName('motionStage')
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.title_text, self.value_text, self.active = tr(title), '', False
        self.setAccessibleName(self.title_text)

    def set_value(self, text, active):
        self.value_text, self.active = text, active
        self.setToolTip(f'{self.title_text}：{text}')
        self.setAccessibleDescription(text)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        rect = self.rect().adjusted(5, 3, -5, -4)
        color = self.palette().color(self.foregroundRole())
        muted = QColor(color); muted.setAlphaF(.58)
        title_font = QFont(self.font()); title_font.setPixelSize(11); title_font.setWeight(QFont.Normal)
        value_font = QFont(self.font()); value_font.setPixelSize(13); value_font.setWeight(QFont.DemiBold)
        half = rect.height()//2
        painter.setFont(title_font); painter.setPen(muted)
        painter.drawText(QRect(rect.left(), rect.top(), rect.width(), half), Qt.AlignHCenter | Qt.AlignBottom, self.title_text)
        painter.setFont(value_font); painter.setPen(color if self.active else muted)
        value = QFontMetrics(value_font).elidedText(self.value_text, Qt.ElideRight, rect.width())
        painter.drawText(QRect(rect.left(), rect.top()+half+1, rect.width(), rect.height()-half-1),
                         Qt.AlignHCenter | Qt.AlignTop, value)
        painter.end()


class StageBar(QWidget):
    """Four stages, each showing what is currently chosen for it."""
    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # One filled track; the open stage is the raised chip (design A).
        self.setObjectName('motionStageBar')
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self); row.setContentsMargins(3, 3, 3, 3); row.setSpacing(2)
        self.buttons = []
        for i, stage in enumerate(STAGES):
            button = StageButton(STAGE_TITLES[stage], self)
            button.clicked.connect(lambda _=False, i=i: self.setCurrentIndex(i))
            row.addWidget(button)
            self.buttons.append(button)
        self._index = -1
        self.setCurrentIndex(0)

    def count(self): return len(self.buttons)
    def currentIndex(self): return self._index
    def tabText(self, index): return self.buttons[index].title_text
    def setTabToolTip(self, index, text): self.buttons[index].setToolTip(text)

    def setCurrentIndex(self, index):
        index = max(0, min(len(self.buttons)-1, int(index)))
        for i, button in enumerate(self.buttons):
            button.setChecked(i == index)
        if index != self._index:
            self._index = index
            self.currentChanged.emit(index)


class MotionEffectTile(QPushButton):
    def __init__(self, stage, key, label, parent):
        super().__init__(parent)
        self.stage, self.key = stage, key
        self.setObjectName('motionEffectTile')
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(86)
        self.setFixedHeight(TILE_HEIGHT)
        self.setAccessibleName(tr(label))
        self.setToolTip(tr(HINTS.get((stage, key), '')))
        box = QVBoxLayout(self); box.setContentsMargins(4, 4, 4, 4); box.setSpacing(3)
        from .motion_controls_ui import MotionSample
        self.preview = MotionSample(self, shared=True)
        self.preview.setFixedHeight(PREVIEW_HEIGHT)
        self.preview.set_corner_radius(9)
        self.preview.auto_play = False
        self.preview.font_pixel_size = 19
        self.preview.setAttribute(Qt.WA_TransparentForMouseEvents)
        box.addWidget(self.preview)
        self.caption = caption = QLabel(tr(label)); caption.setObjectName('motionTileLabel'); caption.setAlignment(Qt.AlignCenter)
        caption.setAttribute(Qt.WA_TransparentForMouseEvents)
        box.addWidget(caption)
        # The chosen tile: a tinted fill, an accent ring and a check (design A).
        self.check = QLabel(self.preview)
        self.check.setObjectName('motionTileCheck')
        self.check.setFixedSize(18, 18)
        self.check.setAlignment(Qt.AlignCenter)
        self.check.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.check.move(5, 5)
        self.check.hide()
        item = spec(stage, key) if stage != 'words' else None
        badge = '逐字' if item and item.per_char else '方向' if item and item.directional else (
            '语音' if stage == 'words' and key != 'none' else '')
        self.badge = None
        if badge:
            self.badge = QLabel(tr(badge), self.preview); self.badge.setObjectName('motionBadge')
            self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.badge.setAlignment(Qt.AlignCenter)
            self.badge.ensurePolished()
            metrics = self.badge.fontMetrics()
            self.badge.setFixedSize(metrics.horizontalAdvance(self.badge.text())+12, metrics.height()+2)
        self.color = None
        self._built = False

    def build(self):
        """Renderer work happens only when a card is first shown."""
        if self._built:
            return
        from .visual_snapshot import build_visual_cue_snapshot
        self._built = True
        effect = stage_effect(self.stage, self.key, color=self.color)
        project = demo_project(effect)
        self.preview.poster_ms = poster_ms(self.stage, self.key, effect)
        self.preview.set_snapshot(build_visual_cue_snapshot(project, 'card'))

    def recolor(self, color):
        if self.stage == 'words' and color != self.color:
            self.color, self._built = color, False
            if self.isVisible():
                self.build()

    def showEvent(self, event):
        super().showEvent(event)
        self.build()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.badge is not None:
            self.badge.move(self.preview.width()-self.badge.width()-4, 4)

    def set_selected(self, selected):
        self.setChecked(selected)
        if self.check.isHidden() == selected:
            if selected:
                import qtawesome as qta
                from ..design.ui_theme import theme_definition
                from ..design.theme_manager import theme_key
                color = theme_definition(theme_key()).text_on_accent
                self.check.setPixmap(qta.icon('fa5s.check', color=color).pixmap(10, 10))
            self.check.setVisible(selected)
            self.caption.setProperty('selected', bool(selected))
            self.caption.style().unpolish(self.caption); self.caption.style().polish(self.caption)
        self.preview.auto_play = selected
        if selected and self.isVisible():
            self.build()
            self.preview.clock.start(); self.preview.timer.start()
        elif not self.underMouse():
            self.preview.timer.stop(); self.preview.draw_frame()

    def enterEvent(self, event):
        self.build()
        self.preview.clock.start(); self.preview.timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.isChecked():
            self.preview.timer.stop(); self.preview.draw_frame()
        super().leaveEvent(event)


def _chip(text, parent, name='motionChip'):
    button = QPushButton(tr(text), parent)
    button.setObjectName(name)
    button.setCheckable(True)
    button.setCursor(Qt.PointingHandCursor)
    button.setFocusPolicy(Qt.TabFocus)
    return button


class MotionInspector(QWidget):
    def __init__(self, workflow):
        super().__init__()
        self.workflow, self.page = workflow, workflow.page
        self.stages = STAGES
        self._cards, self.grids, self.hosts, self.chips = {}, {}, {}, {}
        # 2026-10-22: the ~80 effect tiles (each a live preview with its own
        # style sheet and timer) were built with the Studio page and both
        # crashes of the user's 22:01/22:03 sessions happened while building
        # them. They are built per stage when the 动效 page is first shown.
        self._grid_hosts, self._tiles_built, self._tiles_allowed = {}, set(), False
        self.category = dict.fromkeys(STAGES, 'all')
        self.directions = {'entry': None, 'exit': None}
        self.columns = 0
        self._register_choices()
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(10)
        self.tabs = StageBar(self)
        self.tabs.setAccessibleName(tr('动效分类'))
        layout.addWidget(self.tabs)
        # Parameters for the stage in front, in one card (design A): duration,
        # strength, direction, the word colour and what the stage does.
        from ..design.soft_widgets import UnitField, soft_card
        self.params_card, params = soft_card(margins=(12, 10, 12, 10), spacing=8)
        self.duration_row = QWidget(); row = QHBoxLayout(self.duration_row); row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.duration_label = QLabel(tr('持续时间')); self.duration_label.setObjectName('softLabel')
        row.addWidget(self.duration_label)
        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(1, 80); self.slider.setAccessibleName(tr('动效持续时间'))
        row.addWidget(self.slider, 1)
        self.seconds = QDoubleSpinBox(); self.seconds.setDecimals(2); self.seconds.setRange(.01, 4.)
        self.seconds.setSingleStep(.05); self.seconds.setSuffix(tr(' 秒'))
        self.seconds.setKeyboardTracking(False); self.seconds.setAccessibleName(tr('动效持续时间（秒）'))
        self.seconds_field = UnitField(self.seconds)
        self.seconds_field.setFixedWidth(92)
        row.addWidget(self.seconds_field)
        params.addWidget(self.duration_row)
        self.tuning_row = QWidget(); tuning = QHBoxLayout(self.tuning_row)
        tuning.setContentsMargins(0, 0, 0, 0); tuning.setSpacing(8)
        self.strength_label = QLabel(tr('强度')); self.strength_label.setObjectName('softLabel')
        tuning.addWidget(self.strength_label)
        strength_track = QFrame(self.tuning_row); strength_track.setObjectName('softSegmented')
        track_row = QHBoxLayout(strength_track); track_row.setContentsMargins(3, 3, 3, 3); track_row.setSpacing(2)
        self.strength_buttons = {}
        for value, text in STRENGTHS:
            button = _chip(text, strength_track, 'motionSegment')
            button.setMinimumWidth(44)
            button.clicked.connect(lambda _=False, value=value: self.set_strength(value))
            track_row.addWidget(button); self.strength_buttons[value] = button
        tuning.addWidget(strength_track)
        tuning.addStretch(1)
        self.direction_label = QLabel(tr('方向')); self.direction_label.setObjectName('softLabel'); tuning.addWidget(self.direction_label)
        self.direction_buttons = {}
        for value, text in ARROWS:
            button = _chip(text, self.tuning_row, 'motionDirection')
            button.setAccessibleName(tr({'left': '从左', 'right': '从右', 'up': '从上', 'down': '从下'}[value]))
            button.clicked.connect(lambda _=False, value=value: self.set_direction(value))
            tuning.addWidget(button); self.direction_buttons[value] = button
        params.addWidget(self.tuning_row)
        self.color_row = QWidget()
        color_layout = QHBoxLayout(self.color_row); color_layout.setContentsMargins(0, 0, 0, 0); color_layout.setSpacing(8)
        color_label = QLabel(tr('强调颜色')); color_label.setObjectName('softLabel')
        color_layout.addWidget(color_label); color_layout.addWidget(self.page.motion_word_color, 1)
        params.addWidget(self.color_row)
        self.explanation = QLabel(); self.explanation.setObjectName('softMeta'); self.explanation.setWordWrap(True)
        params.addWidget(self.explanation)
        layout.addWidget(self.params_card)
        # Category chips and the card grid share one scroll area per stage.
        self.stack = QStackedWidget()
        self.cards_scroll = QScrollArea(); self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.NoFrame)
        self.cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cards_scroll.setMinimumHeight(TILE_HEIGHT+40)
        self.cards_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cards_scroll.setWidget(self.stack)
        layout.addWidget(self.cards_scroll, 1)
        for stage in STAGES:
            host = QWidget(); column = QVBoxLayout(host); column.setContentsMargins(0, 0, 4, 0); column.setSpacing(8)
            chips = QWidget(); flow = FlowLayout(chips)
            self.chips[stage] = {}
            for category, text in [('all', '全部'), *CATEGORIES[stage]]:
                chip = _chip(text, chips)
                chip.clicked.connect(lambda _=False, stage=stage, category=category: self.filter(stage, category))
                flow.addWidget(chip); self.chips[stage][category] = chip
            column.addWidget(chips)
            grid_host = QWidget(); grid = QGridLayout(grid_host); grid.setContentsMargins(0, 0, 0, 0); grid.setSpacing(7)
            grid.setAlignment(Qt.AlignTop)
            self.grids[stage] = grid
            self._grid_hosts[stage] = grid_host
            column.addWidget(grid_host)
            column.addStretch(1)
            self.hosts[stage] = host
            self.stack.addWidget(host)
        self.tabs.currentChanged.connect(self.stage_changed)
        self.seconds.valueChanged.connect(self.duration_changed)
        self.slider.valueChanged.connect(lambda value: self.seconds.setValue(value*.05))
        self.page.motion_word_color.currentIndexChanged.connect(self._recolor_words)
        for stage in STAGES:
            self.chips[stage]['all'].setChecked(True)
        self.reflow(3)
        self.stage_changed(0)

    def _register_choices(self):
        """Hidden draft combos carry every catalog key (new ones included)."""
        page = self.page
        for stage, combo in (('entry', page.effect_preset), ('exit', page.effect_exit),
                             ('loop', page.effect_loop), ('words', page.motion_word_mode)):
            for key, label in CHOICES[stage]:
                if combo.findData(key) < 0:
                    combo.addItem(tr(label), key)

    @property
    def cards(self):
        """Every tile, built on first use (internal code reads ``_cards``)."""
        missing = [stage for stage in STAGES if stage not in self._tiles_built]
        if missing:
            self._tiles_allowed = True
            for stage in missing:
                self._build_tiles(stage)
            self.reflow(self.columns or 3)
        return self._cards

    def _build_tiles(self, stage):
        if stage in self._tiles_built:
            return False
        self._tiles_built.add(stage)
        host = self._grid_hosts[stage]
        for key, label in CHOICES[stage]:
            tile = MotionEffectTile(stage, key, label, host)
            tile.clicked.connect(lambda _=False, stage=stage, key=key: self.choose(stage, key))
            self._cards[stage, key] = tile
        if stage == 'words':
            self._recolor_words()
        return True

    def _ensure_current_tiles(self):
        if self._tiles_allowed and self._build_tiles(self.stages[self.tabs.currentIndex()]):
            self.reflow(self.columns or 3)
            self.fit_stack()
            self.sync()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._tiles_allowed:
            self._tiles_allowed = True
            self._ensure_current_tiles()

    # ------------------------------------------------------------ layout --
    def reflow(self, columns):
        changed = self.columns != columns
        self.columns = columns
        for stage, choices in CHOICES.items():
            if stage not in self._tiles_built:
                continue
            grid = self.grids[stage]
            while grid.count():
                grid.takeAt(0)
            shown = [key for key, _ in choices
                     if self.category[stage] in ('all', CATEGORY.get((stage, key)))]
            for key, _ in choices:
                self._cards[stage, key].setVisible(key in shown)
            for i, key in enumerate(shown):
                grid.addWidget(self._cards[stage, key], i//columns, i % columns)
            for column in range(columns):
                grid.setColumnStretch(column, 1)
        if changed:
            self.fit_stack()

    def fit_stack(self):
        stage = self.stages[self.tabs.currentIndex()]
        host = self.hosts[stage]
        # Re-filtering re-adds tiles; until the layouts recompute, the cached
        # hint is the previous filter's (全部 after 柔和 sized for 9 tiles and
        # the 33 fixed-height tiles were drawn on top of each other).
        for layout in (self.grids[stage], host.layout()):
            layout.invalidate()
            layout.activate()
        for i in range(self.stack.count()):
            widget = self.stack.widget(i)
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred if widget is host else QSizePolicy.Ignored)
        self.stack.setFixedHeight(host.sizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow(3 if self.width() >= 290 else 2)
        QTimer.singleShot(0, self.fit_stack)

    def filter(self, stage, category):
        self.category[stage] = category
        for name, chip in self.chips[stage].items():
            chip.setChecked(name == category)
        self.reflow(self.columns)
        self.fit_stack()
        self.cards_scroll.verticalScrollBar().setValue(0)

    def stage_changed(self, index):
        self.stack.setCurrentIndex(index)
        if self._tiles_allowed and self._build_tiles(self.stages[index]):
            self.reflow(self.columns or 3)
        self.fit_stack(); self.sync()
        self.cards_scroll.verticalScrollBar().setValue(0)

    # ------------------------------------------------------------- state --
    def selected(self, stage):
        return str(getattr(self.page, {'entry': 'effect_preset', 'exit': 'effect_exit',
                                      'loop': 'effect_loop', 'words': 'motion_word_mode'}[stage]).currentData() or 'none')

    def direction(self, stage):
        item = spec(stage, self.selected(stage))
        if not item or not item.directional:
            return None
        return self.directions.get(stage) or item.directional

    def load_effect(self, effect):
        """Restore direction choices from a saved cue effect."""
        for stage in ('entry', 'exit'):
            self.directions[stage] = (effect.get(stage) or {}).get('direction')
        self.sync()

    def choose(self, stage, key):
        page = self.page
        item = spec(stage, key) if stage != 'words' else None
        if stage == 'entry':
            # Loading an entrance must not replace the independently chosen exit/loop.
            exit_index, exit_duration = page.effect_exit.currentIndex(), page.effect_out_duration.value()
            page._updating_style_ui = True
            try:
                page._set_combo_data(page.effect_preset, key); self.workflow.controller._load_motion_controls(key, include_other_stages=False)
                page.effect_exit.setCurrentIndex(exit_index); page.effect_out_duration.setValue(exit_duration)
            finally: page._updating_style_ui = False
            self.directions['entry'] = None
            self.workflow.motion_changed()
        elif stage in {'exit', 'loop'}:
            control = page.effect_exit if stage == 'exit' else page.effect_loop
            duration = page.effect_out_duration if stage == 'exit' else page.effect_loop_duration
            with QSignalBlocker(control): page._set_combo_data(control, key)
            if item and not item.legacy:
                # Curated presets start at the timing they were designed for.
                with QSignalBlocker(duration): duration.setValue(item.duration)
            if stage == 'exit':
                self.directions['exit'] = None
            self.workflow.motion_changed()
        else:
            with QSignalBlocker(page.motion_word_mode): page._set_combo_data(page.motion_word_mode, key)
            if key == 'karaoke_wipe': page._set_combo_data(page.motion_word_color, '#4D9FFF')
            elif key in PRESETS: page._set_combo_data(page.motion_word_color, PRESETS[key][2])
            self.workflow.draft_changed()
        self.sync()

    def set_strength(self, value):
        self.page._set_combo_data(self.page.effect_strength, value)
        self.sync()

    def set_direction(self, value):
        stage = self.stages[self.tabs.currentIndex()]
        if stage in self.directions:
            self.directions[stage] = value
            self.workflow.motion_changed()
        self.sync()

    def duration_control(self):
        return getattr(self.page, {'entry': 'effect_duration', 'exit': 'effect_out_duration',
                                  'loop': 'effect_loop_duration'}.get(self.stages[self.tabs.currentIndex()], 'effect_duration'))

    def duration_changed(self, seconds):
        control = self.duration_control()
        control.setValue(round(seconds*1000))
        with QSignalBlocker(self.slider): self.slider.setValue(round(seconds/.05))

    def _recolor_words(self, *_):
        color = str(self.page.motion_word_color.currentData() or '')
        for (stage, key), tile in self._cards.items():
            if stage == 'words' and key not in PRESETS and key != 'karaoke_wipe':
                tile.recolor(color)

    def summary(self, stage):
        key = self.selected(stage)
        label = dict(CHOICES[stage]).get(key)
        if label is None:
            label = 'AI 动效' if key == 'visual_graph' else key
        return tr(label), key not in {'none', 'visual_graph'}

    def sync(self):
        page = self.page; stage = self.stages[self.tabs.currentIndex()]
        for (card_stage, key), card in self._cards.items():
            card.set_selected(self.selected(card_stage) == key)
        for i, name in enumerate(self.stages):
            text, active = self.summary(name)
            self.tabs.buttons[i].set_value(text, active)
        current = self.selected(stage)
        timed = stage != 'words'
        self.duration_row.setVisible(timed)
        self.duration_label.setText(tr('循环周期' if stage == 'loop' else '持续时间'))
        with QSignalBlocker(self.seconds):
            self.seconds.setMinimum(.12 if stage == 'loop' else .01)
            self.seconds.setValue(self.duration_control().value()/1000)
        with QSignalBlocker(self.slider): self.slider.setValue(round(self.seconds.value()/.05))
        self.duration_row.setEnabled(current not in {'none', 'visual_graph'})
        self.tuning_row.setVisible(timed)
        strength = str(page.effect_strength.currentData() or 'medium')
        for value, button in self.strength_buttons.items():
            button.setChecked(value == strength)
            button.setEnabled(current not in {'none', 'visual_graph'})
        direction = self.direction(stage) if stage in self.directions else None
        for widget in (self.direction_label, *self.direction_buttons.values()):
            widget.setVisible(direction is not None)
        for value, button in self.direction_buttons.items():
            button.setChecked(value == direction)
        self.color_row.setVisible(stage == 'words' and current not in {'none', 'word_reveal', 'word_pop'})
        hint = HINTS.get((stage, current), '')
        self.explanation.setText(tr({'entry': '字幕开始时播放', 'exit': '字幕结束前播放', 'loop': '入场后循环，出场前收起',
                                    'words': '跟随语音中的字词时间'}[stage]) + (' · '+tr(hint) if hint and current != 'none' else ''))
        self.tabs.setTabToolTip(self.tabs.currentIndex(), self.explanation.text())
