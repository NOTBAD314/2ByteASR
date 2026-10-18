"""A draft, an explicit scope and one undoable motion application."""
from __future__ import annotations

import copy
from dataclasses import replace
from types import SimpleNamespace

from PySide6.QtCore import Qt, QElapsedTimer, QTimer, QRectF, QPointF
from PySide6.QtGui import QPixmap, QFont, QFontMetricsF, QPainter, QColor, QPalette
from PySide6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QSizePolicy

from .studio_theme import StudioComboBox
from .i18n import tr
from .effect_dsl import builtin_effects, validate_effect
from .motion_application import authored_motion_tracks, motion_command, overrides_style_motion
from .word_animation import WORD_MODES, word_part, build_word_animation


_SHARED_RASTER = None


def _shared_rasterizer():
    """Cards share one bounded frame cache instead of 64 MiB each."""
    global _SHARED_RASTER
    if _SHARED_RASTER is None:
        from .caption_scene import SceneRasterizer
        _SHARED_RASTER = SceneRasterizer()
    return _SHARED_RASTER


class MotionSample(QLabel):
    def __init__(self, parent, shared=False):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setMaximumHeight(84)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setObjectName('motionPreview')
        # A neutral video stage keeps white caption fills legible in light UI.
        self.setStyleSheet('QLabel#motionPreview { border-radius: 7px; background: qlineargradient('
                           'x1:0, y1:0, x2:0, y2:1, stop:0 #283A4F, stop:1 #161F2B); }')
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.draw_frame)
        self.snapshot = None
        self.rasterizer = None
        self.shared = shared
        self.auto_play = True
        self.poster_fraction = None
        self.poster_ms = None
        #: (entry_ms, exit_ms) draws a timing strip: entry · hold · exit.
        self.phases = None
        self.font_pixel_size = 22

    def set_snapshot(self, snapshot):
        self.snapshot = snapshot
        if self.shared:
            self.rasterizer = _shared_rasterizer()
        else:
            if self.rasterizer:
                self.rasterizer.close()
            from .caption_scene import SceneRasterizer
            self.rasterizer = SceneRasterizer()
        self.clock.start()
        if self.isVisible() and self.auto_play:
            self.timer.start()
        self.draw_frame()

    def showEvent(self, event):
        super().showEvent(event)
        if self.snapshot and self.auto_play:
            self.clock.start()
            self.timer.start()
        self.draw_frame()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.draw_frame()

    def draw_frame(self):
        if not self.snapshot or not self.isVisible():
            return
        snap = self.snapshot
        duration = max(1, snap.end_ms-snap.start_ms)
        elapsed = self.clock.elapsed() % (min(duration, 6000)+650)
        local = min(duration-1, elapsed * max(1, duration/6000))
        if not self.auto_play and not self.timer.isActive():
            # A reading hold erased every preset's identity in the library.
            # Sample an actual action, never six identical completed lines.
            mode=(snap.word_animation or {}).get('mode')
            local = duration * ({'word_mist':.94,'word_sweep':.19,'word_pulse':.93,
                'word_echo':.28,'word_float':.875,'word_dust':.94}.get(mode,.88))
            if self.poster_fraction is not None: local = duration*self.poster_fraction
            if self.poster_ms is not None: local = min(duration-1, max(0, self.poster_ms))
        # Render at device pixels: high-DPI screens otherwise show soft cards.
        dpr = max(1., float(self.devicePixelRatioF()))
        logical_width, logical_height = max(100, self.width()), max(1, self.height())
        width, height = round(logical_width*dpr), round(logical_height*dpr)
        # This is a local composition using the selected cue and its measured
        # intervals. Placement is centered only inside this labelled preview.
        face = QFont(snap.font_family)
        face.setPixelSize(self.font_pixel_size)
        face.setWeight(QFont.Weight(snap.font_weight))
        metrics = QFontMetricsF(face)
        font = self.font_pixel_size * min(1., (logical_width-20)/max(1., max(metrics.horizontalAdvance(line) for line in snap.text.split('\n'))))
        font *= dpr
        ratio = font/max(1., snap.font_size)
        recipe = copy.deepcopy(snap.style_recipe)
        for track in recipe.get('visualGraph', {}).get('motionGraph', {}).get('tracks', []):
            if track.get('property') in {'x', 'y'}:
                for key in track.get('keyframes', []):
                    key['value'] *= ratio
        sample = replace(snap, position_x=width/2, position_y=height/2,
                         playres_x=width, playres_y=height, font_size=font,
                         anchor_x=.5, anchor_y=.5, alignment=5, scale_x=1, scale_y=1,
                         rotation=0, resolved_caption=None, style_recipe=recipe,
                         letter_spacing=snap.letter_spacing*ratio,
                         strokes=tuple({**s, 'width':s['width']*ratio} for s in snap.strokes),
                         shadow={**snap.shadow, **{k:float(snap.shadow.get(k, 0))*ratio for k in ('offsetX','offsetY','blur','spread')}},
                         glow={**snap.glow, 'blur':float(snap.glow.get('blur', 0))*ratio})
        prepared = SimpleNamespace(snapshot=sample, snapshot_hash=sample.stable_hash())
        image = self.rasterizer.native_frame(prepared, local, width, height)
        if self.phases:
            image = image.copy()
            self._paint_phases(image, local, duration, dpr)
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(dpr)
        self.setPixmap(pixmap)

    def _paint_phases(self, image, local, duration, dpr):
        """A thin strip shows where entry, reading and exit fall in this cue."""
        entry, leave = self.phases
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        inset, thick = 10*dpr, 3*dpr
        top = image.height()-7*dpr
        span = max(1., image.width()-2*inset)
        accent = self.palette().color(QPalette.Highlight)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 46))
        painter.drawRoundedRect(QRectF(inset, top, span, thick), thick/2, thick/2)
        painter.setBrush(accent)
        if entry > 0:
            painter.drawRoundedRect(QRectF(inset, top, span*min(1., entry/duration), thick), thick/2, thick/2)
        if leave > 0:
            width = span*min(1., leave/duration)
            painter.drawRoundedRect(QRectF(inset+span-width, top, width, thick), thick/2, thick/2)
        painter.setBrush(QColor('#FFFFFF'))
        painter.drawEllipse(QPointF(inset+span*min(1., local/duration), top+thick/2), 3.2*dpr, 3.2*dpr)
        painter.end()


class MotionWorkflow:
    def __init__(self, controller, layout):
        self.controller = controller
        self.page = page = controller.page
        self.dirty = False
        self.pending_motion = False
        page.motion_word_mode = StudioComboBox()
        for label, value in [('整句显示', 'none'), ('逐词出现', 'word_reveal'),
                             ('蓝白卡拉 OK', 'karaoke_wipe'), ('卡拉 OK · 依次点亮', 'karaoke_highlight'), ('只高亮当前词', 'word_current')]:
            page.motion_word_mode.addItem(tr(label), value)
        from .letter_motion import PRESETS
        for key, (label, _, _) in PRESETS.items():
            page.motion_word_mode.addItem(tr(label), key)
        page.motion_word_color = StudioComboBox()
        for label, value in [('卡拉 OK 蓝', '#4D9FFF'), ('暖黄', '#FFD166'), ('天蓝', '#7DD3FC'), ('薄荷', '#86EFAC'), ('粉红', '#FDA4AF')]:
            page.motion_word_color.addItem(tr(label), value)
        for key, (label, _, color) in PRESETS.items():
            if page.motion_word_color.findData(color) < 0:
                page.motion_word_color.addItem({'word_mist':'冰蓝','word_sweep':'香槟金','word_pulse':'青瓷','word_echo':'淡紫','word_float':'蔷薇粉','word_dust':'柔金'}[key], color)
        page.motion_word_mode.setParent(page.motion_legacy)
        page.motion_word_mode.hide()
        title_row = QHBoxLayout()
        title = QLabel(tr('本条预览')); title.setObjectName('cardMeta')
        title_row.addWidget(title, 1)
        title_row.addWidget(page.motion_replay_button)
        page.motion_replay_button.setText(tr('播放'))
        page.motion_library_button.setText(tr('更多预设…'))
        title_row.addWidget(page.motion_library_button)
        layout.addLayout(title_row)
        page.motion_sample = MotionSample(page)
        page.motion_sample.setFixedHeight(78)
        page.motion_panel.responsive_preview = page.motion_sample
        layout.addWidget(page.motion_sample)
        layout.addWidget(page.graph_motion_summary)
        page.motion_scope = StudioComboBox()
        for label, value in [('当前字幕', 'current'), ('已选字幕', 'selected'),
                             ('当前说话人', 'speaker'), ('全部字幕', 'all')]:
            page.motion_scope.addItem(tr(label), value)
        page.motion_status = QLabel()
        page.motion_status.setObjectName('cardMeta')
        page.motion_status.setWordWrap(True)
        page.motion_apply = QPushButton(tr('应用动效'))
        page.motion_apply.setObjectName('studioPrimaryButton')
        page.motion_apply.clicked.connect(self.apply)
        scope_row = QHBoxLayout()
        scope_row.addWidget(page.motion_scope, 1)
        scope_row.addWidget(page.motion_apply, 1)
        from .motion_inspector_ui import MotionInspector
        page.motion_inspector = MotionInspector(self)
        layout.addWidget(page.motion_inspector, 1)
        layout.addWidget(page.motion_status)
        layout.addLayout(scope_row)
        page.motion_word_mode.currentIndexChanged.connect(self.draft_changed)
        page.motion_word_color.currentIndexChanged.connect(self.draft_changed)
        page.motion_scope.currentIndexChanged.connect(self.update_status)
        for name in ('effect_duration', 'effect_out_duration', 'effect_delay', 'effect_scale',
                     'effect_offset_x', 'effect_offset_y', 'effect_blur', 'effect_overshoot', 'effect_accel', 'effect_loop_duration'):
            getattr(page, name).valueChanged.connect(self.motion_changed)

    def targets(self):
        page = self.page
        project = page.project
        current = page.session._cue_lookup.get(page.selected_cue_id)
        if project is None or current is None:
            return []
        scope = page.motion_scope.currentData()
        if scope == 'all':
            return list(project.cues)
        if scope == 'speaker':
            return [c for c in project.cues if c.speaker_id == current.speaker_id]
        if scope == 'selected':
            rows = page.cue_table.selectionModel().selectedRows()
            ids = {str(page.cue_model.data(page.cue_model.index(i.row(), 0), Qt.UserRole)) for i in rows}
            return [c for c in project.cues if c.id in ids]
        return [current]

    def supported(self, cue):
        return not (self.page.project.style_recipes.get(cue.style_id) or {}).get('webTheme')

    def motion_effect(self):
        """The draft entry/exit/loop, with the panel's direction choices."""
        page = self.page
        effect = page._effect_from_controls(str(page.effect_preset.currentData() or 'none'))
        inspector = getattr(page, 'motion_inspector', None)
        if inspector is not None:
            for stage in ('entry', 'exit'):
                direction = inspector.direction(stage)
                if direction and effect[stage]['type'] != 'none':
                    effect[stage]['direction'] = direction
        return validate_effect(effect)

    def word_settings(self):
        return {'type': str(self.page.motion_word_mode.currentData() or 'none'),
                'color': str(self.page.motion_word_color.currentData() or '#FFD166')}

    def draft_changed(self, *_):
        if self.page._updating_style_ui:
            return
        self.dirty = True
        self.page._motion_contract_dirty = False
        self.page._pending_motion_replay_cue_id = ''
        self.update_status()
        self.page.motion_inspector.sync()
        self.preview()

    def motion_changed(self, *_):
        if self.page._updating_style_ui:
            return
        self.pending_motion = True
        self.draft_changed()

    def update_status(self, *_):
        targets = self.targets()
        eligible = [c for c in targets if self.supported(c)]
        mode = self.page.motion_word_mode.currentData()
        self.page.motion_word_color.setEnabled(mode in WORD_MODES - {'word_reveal'})
        message = ''
        if len(eligible) != len(targets):
            message += (tr('当前字幕是网页主题，保留主题自带动画；上方用示例文字预览。')
                        if len(targets) == 1 else
                        tr(' {count} 条网页主题保留主题自带动画。', count=len(targets)-len(eligible)))
        if mode in WORD_MODES:
            part = {'entry': self.word_settings()}
            missing = sum(not build_word_animation(self.page.project, c, effect=part).get('spans') for c in eligible)
            message += tr('按已有字词时间同步。')
            if missing:
                message += tr(' {count} 条缺少字词时间，保持整句。', count=missing)
        self.page.motion_status.setText(message)
        self.page.motion_status.setVisible(bool(message))
        self.page.motion_apply.setEnabled(bool(eligible))
        self.page.motion_apply.setText(tr('应用到 {count} 条字幕', count=len(eligible)))

    def load(self):
        page = self.page
        cue = page.session._cue_lookup.get(page.selected_cue_id)
        if cue is None:
            return
        effect = validate_effect(page.project.effects.get(cue.effect_id, {}))
        word = word_part(effect)
        page._set_combo_data(page.motion_word_mode, word.get('type', 'none'))
        page._set_combo_data(page.motion_word_color, word.get('color', '#FFD166'))
        entry = effect['entry']['type']
        recipe = page.project.style_recipes.get(cue.style_id, {})
        authored = authored_motion_tracks(recipe.get('visualGraph'))
        # Same rule as preview and export: an AI recipe's compat entrance
        # (pop, no motion_override) still means the graph motion plays.
        if authored and not overrides_style_motion(effect, authored):
            page._set_combo_data(page.effect_preset, 'visual_graph')
        else:
            page._set_combo_data(page.effect_preset, 'none' if entry in WORD_MODES else entry)
            page.graph_motion_summary.hide()
        page._load_motion_controls(cue.effect_id)
        self.dirty = self.pending_motion = False
        self.update_status()
        self.page.motion_inspector.load_effect(effect)
        self.preview(saved=True)

    def preview(self, *, saved=False):
        from .visual_snapshot import build_visual_cue_snapshot
        page = self.page
        cue = page.session._cue_lookup.get(page.selected_cue_id)
        if cue is None:
            page.motion_sample.snapshot = None
            page.motion_sample.clear()
            return
        if not self.supported(cue):
            # A web theme keeps its own animation; still show what the draft
            # looks like, on neutral sample text rather than an empty box.
            from .motion_inspector_ui import demo_project
            project = demo_project({'entry': {'type': 'none'}, 'exit': {'type': 'none'}}, text='示例字幕')
            command = motion_command(project, ['card'], motion=self.motion_effect(), words=self.word_settings())
            if command:
                command.redo()
            self._show(project, 'card')
            return
        project = page.project
        if not saved:
            project = copy.copy(project)
            project.cues = [copy.copy(c) for c in project.cues]
            if hasattr(project, '_studio_state_runtime'):
                del project._studio_state_runtime
            command = motion_command(project, [cue.id],
                motion=self.motion_effect() if self.pending_motion else None,
                words=self.word_settings())
            if command:
                project.effects = command.after_effects
                next(c for c in project.cues if c.id == cue.id).effect_id = command.after[cue.id][1]
        self._show(project, cue.id)

    def _show(self, project, cue_id):
        from .visual_snapshot import build_visual_cue_snapshot
        cue = next(c for c in project.cues if c.id == cue_id)
        effect = validate_effect(project.effects.get(cue.effect_id, {}))
        def length(part):
            return part.get('duration', 0)+part.get('delay', 0) if part['type'] not in WORD_MODES | {'none'} else 0
        sample = self.page.motion_sample
        sample.phases = (length(effect['entry']), length(effect['exit']))
        sample.set_snapshot(build_visual_cue_snapshot(project, cue_id))

    def apply(self):
        page = self.page
        targets = [c.id for c in self.targets() if self.supported(c)]
        if not targets:
            self.update_status()
            return
        command = motion_command(page.project, targets,
            motion=self.motion_effect() if self.pending_motion else None,
            words=self.word_settings(), changed=page._changed)
        if command:
            page.session.undo_stack.push(command)
        page._load_style_inspector()
        page.motion_status.setText(tr('已应用到 {count} 条字幕，可撤销。点「播放」再看一遍。', count=len(targets)))
        page._show_studio_hint(tr('字幕动效已应用到 {count} 条', count=len(targets)))
