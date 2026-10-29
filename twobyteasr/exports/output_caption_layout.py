"""Read-only output caption layout and its lightweight export-dialog preview."""
from __future__ import annotations

from copy import copy

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ..i18n import tr


def display_project(project, cues=None):
    """Materialize only the requested rows without cloning the full ASR corpus."""
    from ..caption_style.bilingual_layout import project_display_cues
    shown = copy(project)
    shown.__dict__.pop('_studio_state_runtime', None)
    shown.cues = project_display_cues(project, cues)
    shown.studio_state = dict(project.studio_state, bilingual={'mode': 'original'},
                             bilingual_mode=False, show_speaker_names=False)
    from ..subtitle_rules.punctuation_style import mark_cues_styled
    mark_cues_styled(shown)
    return shown


def layout_snapshots(project, cues=None):
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    shown = display_project(project, cues)
    output = getattr(project, '_output_canvas', {}).get('output', (None, None))
    return [build_visual_cue_snapshot(shown, cue.id, resolved_cue=cue,
                                      width=output[0], height=output[1]) for cue in shown.cues]


def require_layout_fit(project):
    """An impossible layout is a visible export error, never truncated video."""
    from ..caption_style.resolved_caption_style import resolve_caption_style
    shown = display_project(project)
    width = int(shown.render_settings.get('play_res_x', 1920))
    height = int(shown.render_settings.get('play_res_y', 1080))
    failed = []
    for cue in shown.cues:
        caption = resolve_caption_style(shown.styles, shown.speakers, cue, shown.style_recipes, width, height)
        if caption.requires_split:
            failed.append(cue.id)
    if failed:
        raise ValueError(tr('有 {count} 条字幕超出输出画布。请调整字号、边距或文字后重试。字幕：{cues}',
                            count=len(failed), cues=', '.join(failed[:5])))


def render_layout(project, cues, width, height):
    from ..rendering.advanced_live_renderer import render_live_snapshot
    snapshots = layout_snapshots(project, cues)
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor('#101010'))
    painter = QPainter(image)
    try:
        for snapshot in snapshots:
            if snapshot is not None:
                painter.drawImage(0, 0, render_live_snapshot(snapshot, width=width, height=height))
    finally:
        painter.end()
    return image, snapshots


class OutputCaptionLayoutPreview(QFrame):
    """One GUI-owned static view; no player, worker or mutable session alias."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('outputCaptionLayout')
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 4, 0, 4); layout.setSpacing(6)
        self.title = QLabel(tr('输出字幕排版')); self.title.setObjectName('exportCardTitle')
        self.description = QLabel(); self.description.setWordWrap(True); self.description.setObjectName('exportRangeLabel')
        self.image = QLabel(); self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(160); self.image.setMaximumHeight(260)
        self.status = QLabel(); self.status.setWordWrap(True)
        for widget in (self.title, self.description, self.image, self.status):
            layout.addWidget(widget)
        self._project = self._index = None
        self._milliseconds = 0
        self._output = (1920, 1080)
        self._last_ids = None
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(120)
        self._timer.timeout.connect(self._draw)

    def set_project(self, project, width, height, milliseconds=0):
        from ..playback.playback_plan import IntervalIndex
        self._project = project
        self._index = IntervalIndex(project.cues, lambda row: row.start_ms, lambda row: row.end_ms)
        self._output = (max(1, int(width)), max(1, int(height)))
        self._last_ids = None
        self._milliseconds = max(0, int(milliseconds))
        info = getattr(project, '_output_canvas', {})
        rule = tr('比例已改变：保留设计高度与字号，按输出宽度重新换行') if info.get('relayout') else tr('比例一致：保留工程断行，只缩放显示')
        self.description.setText(f'{width} × {height} · {rule}\n'+tr('当前字幕的静态排版；黑底为示意，视频沿用片段的适应／填充设置。'))
        if self.isVisible():
            self._timer.start()

    def set_time(self, milliseconds):
        self._milliseconds = max(0, int(milliseconds))
        if self._index is None:
            return
        ids = tuple(cue.id for cue in self._index.at(self._milliseconds))
        if ids != self._last_ids and self.isVisible() and not self._timer.isActive():
            self._timer.start()

    def clear_view(self):
        self._timer.stop()
        self._project = self._index = None
        self._last_ids = None
        self.image.clear()
        self.status.clear()

    def _draw(self):
        if self._project is None or not self.isVisible():
            return
        cues = self._index.at(self._milliseconds)
        self._last_ids = tuple(cue.id for cue in cues)
        width, height = self._output
        scale = min(640/width, 260/height)
        try:
            image, snapshots = render_layout(self._project, cues, max(1, round(width*scale)), max(1, round(height*scale)))
            self.image.setPixmap(QPixmap.fromImage(image))
            overflow = [s.cue_id for s in snapshots if s and s.resolved_caption.requires_split]
            self.status.setText(tr('当前字幕超出输出画布，请调整字号、边距或文字。') if overflow else
                                tr('当前时点没有字幕') if not snapshots else '')
            self.setProperty('layoutOverflow', bool(overflow))
        except Exception as exc:
            self.image.clear()
            self.status.setText(tr('排版预览失败：{error}', error=str(exc)))

    def showEvent(self, event):
        super().showEvent(event)
        if self._project is not None:
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)
