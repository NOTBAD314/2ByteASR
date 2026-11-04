"""One virtualized asset model/view for list and thumbnail presentations."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt, QTimer, Signal, QRectF
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QListView, QStyledItemDelegate, QStyle)

from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_definition
from ..timeline.source_selection import SourceSelection, source_capabilities
from ..timeline.studio_media_pool import media_usage
from .studio_source_monitor import source_mime
from .video_filmstrip import FilmstripCache, FilmstripView


def duration_text(ms):
    seconds = max(0, int(ms))//1000
    hours, seconds = divmod(seconds, 3600); minutes, seconds = divmod(seconds, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


class MediaPoolModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []; self.usage = {}; self.signature = None

    def refresh(self, project):
        items = list(project.media_pool) if project else []
        usage = media_usage(project) if project else {}
        signature = tuple((a.asset_id, a.display_name, a.canonical_source, a.duration_ms, a.offline,
                           repr(a.video_metadata), repr(a.audio_metadata), usage.get(a.asset_id)) for a in items)
        if signature == self.signature:
            return
        self.beginResetModel()
        self.items, self.usage, self.signature = items, usage, signature
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        asset = self.items[index.row()]
        state = '文件缺失' if asset.offline else '已使用' if self.usage.get(asset.asset_id) else '未使用'
        video, audio = source_capabilities(asset)
        kind = '视频+音频' if video and audio else '视频 · 无音轨' if video else '音频'
        if role == Qt.ItemDataRole.DisplayRole:
            return asset.display_name
        if role == Qt.ItemDataRole.UserRole:
            return asset.asset_id
        if role == Qt.ItemDataRole.UserRole+1:
            return asset
        if role == Qt.ItemDataRole.UserRole+2:
            return f'{kind} · {duration_text(asset.duration_ms)} · {state}'
        if role == Qt.ItemDataRole.ToolTipRole:
            return f'{asset.display_name}\n{kind} · {duration_text(asset.duration_ms)} · {state}\n{asset.canonical_source}\n双击源预览 · 拖动当前选段到时间线'
        if role == Qt.ItemDataRole.UserRole+3:
            return ' '.join((asset.display_name, asset.canonical_source, kind, state))

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled


class MediaPoolDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view); self.view = view

    def sizeHint(self, option, index):
        width = self.view.card_width
        return QSize(width, round((width-16)*9/16)+62) if self.view.thumbnail_mode else QSize(180, 55)

    def paint(self, painter, option, index):
        asset = index.data(Qt.ItemDataRole.UserRole+1)
        if asset is None:
            return
        painter.save(); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = theme_definition(theme_key())
        rect = QRectF(option.rect).adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setBrush(QColor(theme.surface)); painter.setPen(QPen(QColor(theme.accent if selected else theme.border), 2 if selected else 1))
        painter.drawRoundedRect(rect, 8, 8)
        thumb = QRectF(rect.left()+6, rect.top()+6, rect.width()-12, max(24, rect.height()-58)) if self.view.thumbnail_mode else QRectF(rect.left()+6, rect.top()+6, 65, rect.height()-12)
        painter.fillRect(thumb, QColor(theme.input_surface))
        video, audio = source_capabilities(asset)
        image = self.view.thumbnails.get(asset.canonical_source, self.view.sample_time(asset)) if video else None
        if image is not None and not image.isNull():
            size = image.size().scaled(thumb.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(thumb.center().x()-size.width()/2, thumb.center().y()-size.height()/2, size.width(), size.height())
            painter.drawPixmap(target, image, QRectF(image.rect()))
        elif video:
            painter.setPen(QColor(theme.text))
            painter.drawText(thumb, Qt.AlignmentFlag.AlignCenter, '文件缺失' if asset.offline else '▶ 视频')
        else:
            key = self.view.wave_keys.get(asset.asset_id, '')
            peaks = self.view.wave_cache.memory.get(key)
            painter.setPen(QPen(QColor(theme.accent), 1))
            if peaks is not None and len(peaks):
                stride = max(1, len(peaks)//max(1, round(thumb.width())))
                samples = peaks[::stride]
                for i, (lo, hi) in enumerate(samples):
                    x = thumb.left()+i/max(1,len(samples)-1)*thumb.width()
                    painter.drawLine(round(x), round(thumb.center().y()-float(hi)*thumb.height()*.4),
                                     round(x), round(thumb.center().y()-float(lo)*thumb.height()*.4))
            else:
                painter.drawText(thumb, Qt.AlignmentFlag.AlignCenter, '♫ 音频' + (' · 波形加载中' if self.view.thumbnail_mode else ''))
        name_rect = QRectF(rect.left()+8, thumb.bottom()+4, rect.width()-16, 23) if self.view.thumbnail_mode else QRectF(thumb.right()+8, rect.top()+5, rect.right()-thumb.right()-14, 23)
        state = '文件缺失' if asset.offline else '已使用' if self.view.page.media_pool_panel.model.usage.get(asset.asset_id) else ''
        if state:
            badge = QRectF(thumb.left()+3, thumb.top()+3, min(thumb.width()-6, 62), 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.danger if asset.offline else theme.accent))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(QColor(theme.surface))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, state)
        painter.setPen(QColor(theme.text))
        name = painter.fontMetrics().elidedText(asset.display_name, Qt.TextElideMode.ElideRight, int(name_rect.width()))
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        painter.setPen(QColor(theme.text_muted))
        kind = '视+音' if video and audio else '视频' if video else '音频'
        meta = f'{kind}   {duration_text(asset.duration_ms)}'
        painter.drawText(name_rect.translated(0, 23), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(meta, Qt.TextElideMode.ElideRight, int(name_rect.width())))
        painter.restore()


class MediaPoolView(QListView):
    visible_assets = Signal(object)

    def __init__(self, page, wave_cache, parent=None):
        super().__init__(parent)
        self.page, self.wave_cache = page, wave_cache
        self.card_width = 172; self.thumbnail_mode = True
        self.wave_keys = {}
        self.thumbnails = FilmstripCache(self, memory_bytes=16*1024*1024)
        self.thumbnails.updated.connect(lambda *_: self.viewport().update())
        wave_cache.ready.connect(lambda *_: self.viewport().update())
        self.setObjectName('mediaPoolAssets'); self.setMinimumHeight(140)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True); self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setItemDelegate(MediaPoolDelegate(self))
        self.setUniformItemSizes(True); self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(60)
        self.timer.timeout.connect(self._publish_visible)
        self.verticalScrollBar().valueChanged.connect(lambda *_: self.timer.start())
        self.set_presentation(True, 172)

    def dragEnterEvent(self, event):
        self.page.media_pool_panel.dragEnterEvent(event)

    def dragMoveEvent(self, event):
        self.page.media_pool_panel.dragMoveEvent(event)

    def dropEvent(self, event):
        # The pool owns an external-file drop even when it lands on a card.
        # Do not forward it to Studio's explicit timeline insertion route.
        self.page.media_pool_panel.dropEvent(event)

    def set_presentation(self, thumbnails, size):
        self.thumbnail_mode, self.card_width = bool(thumbnails), int(size)
        self.setViewMode(QListView.ViewMode.IconMode if thumbnails else QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.LeftToRight if thumbnails else QListView.Flow.TopToBottom)
        self.setWrapping(bool(thumbnails))
        self.setMovement(QListView.Movement.Static)
        self.setGridSize(QSize(size, round((size-16)*9/16)+62) if thumbnails else QSize())
        self.doItemsLayout(); self.viewport().update(); self.timer.start()

    @staticmethod
    def sample_time(asset):
        return max(0, min(max(0, asset.duration_ms-100), round(asset.duration_ms*.2), 10000))

    def _publish_visible(self):
        if not self.isVisible() or self.model() is None:
            self.thumbnails.set_view(())
            return
        views, assets = [], []
        viewport = self.viewport().rect()
        for row in range(self.model().rowCount()):
            index = self.model().index(row, 0)
            if not self.visualRect(index).intersects(viewport):
                continue
            asset = index.data(Qt.ItemDataRole.UserRole+1)
            assets.append(asset)
            if not asset.offline and source_capabilities(asset)[0]:
                sample = self.sample_time(asset)
                views.append(FilmstripView(asset.canonical_source, (sample,), owner=asset.asset_id,
                    source_in_ms=0, source_out_ms=asset.duration_ms, lod_ms=1000))
            elif not asset.offline and self.thumbnail_mode:
                key, _ = self.wave_cache.request(asset.canonical_source, 0, 0, asset.duration_ms)
                self.wave_keys[asset.asset_id] = key
        self.thumbnails.set_view(views)
        self.visible_assets.emit(assets)

    def resizeEvent(self, event):
        super().resizeEvent(event); self.timer.start()

    def showEvent(self, event):
        super().showEvent(event); self.timer.start()

    def hideEvent(self, event):
        self.thumbnails.set_view(()); super().hideEvent(event)

    def startDrag(self, actions):
        project, index = self.page.project, self.currentIndex()
        if project is None or not index.isValid():
            return
        try:
            selection = SourceSelection.capture(project, index.data(Qt.ItemDataRole.UserRole))
            drag = QDrag(self); drag.setMimeData(source_mime(project, selection))
            drag.exec(Qt.DropAction.CopyAction)
        except (ValueError, KeyError) as exc:
            self.setToolTip(str(exc))

    def shutdown(self):
        self.timer.stop(); self.thumbnails.close()
