"""Cover undo context and interactive pixel-space Qt scene."""
from __future__ import annotations

from copy import deepcopy
import time

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView

from .cover_document import CoverDocument, new_id
from .cover_render import CoverRenderer


class DocumentChange(QUndoCommand):
    def __init__(self, session, before, after, label, merge_key=''):
        super().__init__(label)
        self.session, self.before, self.after = session, before, after
        self.merge_key, self.stamp = merge_key, time.monotonic()

    def id(self):
        return 701 if self.merge_key else -1

    def mergeWith(self, other):
        if (not self.merge_key or self.merge_key != other.merge_key or
                other.stamp-self.stamp > .8):
            return False
        self.after, self.stamp = other.after, other.stamp
        return True

    def undo(self):
        self.session.apply(self.before)

    def redo(self):
        self.session.apply(self.after)


class CoverSession(QObject):
    changed = Signal()

    def __init__(self, document=None, parent=None):
        super().__init__(parent)
        self.document = (document or CoverDocument()).snapshot()
        self.undo = QUndoStack(self)
        self.undo.setUndoLimit(100)
        self.filename = ''
        self.saved_signature = self.document.signature()
        self.selected = set()

    @property
    def dirty(self):
        return self.document.signature() != self.saved_signature

    def apply(self, document):
        self.document = document.snapshot()
        self.selected.intersection_update(layer.id for layer in self.document.layers)
        self.changed.emit()

    def reset(self, document, filename=''):
        self.undo.clear()
        self.document = document
        self.filename = str(filename)
        self.selected.clear()
        self.saved_signature = document.signature() if filename else ''
        self.changed.emit()

    def commit(self, before, label, merge_key=''):
        used = {layer.asset for layer in self.document.layers if layer.asset}
        self.document.assets = {key: value for key, value in self.document.assets.items() if key in used}
        self.document.asset_names = {key: value for key, value in self.document.asset_names.items() if key in used}
        after = self.document.snapshot()
        if before.signature() != after.signature():
            self.undo.push(DocumentChange(self, before, after, label, merge_key))

    def edit(self, label, operation, merge_key=''):
        before = self.document.snapshot()
        try:
            operation(self.document)
        except BaseException:
            self.apply(before)
            raise
        self.commit(before, label, merge_key)

    def delete_selected(self):
        ids = {layer.id for layer in self.document.layers if layer.id in self.selected and not layer.locked}
        def operation(document):
            document.layers = [layer for layer in document.layers if layer.id not in ids]
            if document.background_id in ids:
                document.background_id = ''
        self.edit('删除图层', operation)

    def duplicate_selected(self):
        selected = set()
        def operation(document):
            for layer in list(document.layers):
                if layer.id in self.selected:
                    copy = deepcopy(layer)
                    copy.id = new_id()
                    copy.name += ' 副本'
                    copy.x += 24
                    copy.y += 24
                    copy.locked = False
                    document.layers.append(copy)
                    selected.add(copy.id)
        self.edit('复制图层', operation)
        self.selected = selected
        self.changed.emit()


class LayerItem(QGraphicsObject):
    def __init__(self, view, layer):
        super().__init__()
        self.view, self.layer = view, layer
        self.rect = QRectF()
        self.image = None
        self.error = ''
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.update_layer(layer)

    def boundingRect(self):
        return self.rect

    def update_layer(self, layer):
        self.prepareGeometryChange()
        self.layer = layer
        self.error = ''
        try:
            self.image = self.view.renderer.layer_image(self.view.session.document, layer)
            self.rect = self.view.renderer.layer_rect(self.view.session.document, layer)
        except (ValueError, OSError) as exc:
            self.image = None
            self.rect = QRectF(0, 0, layer.width, layer.height)
            self.error = str(exc)
        self.setVisible(layer.visible)
        self.setFlag(QGraphicsItem.ItemIsMovable, not layer.locked)
        self.setPos(layer.x, layer.y)
        self.setOpacity(layer.opacity)
        self.update()

    def paint(self, painter, option, widget=None):
        if self.image is not None:
            painter.drawImage(self.rect, self.image, QRectF(self.image.rect()))
        else:
            painter.fillRect(self.rect, QColor('#ebd9cd'))
            painter.setPen(QColor('#6d352e'))
            painter.drawText(self.rect.adjusted(8, 8, -8, -8), Qt.AlignCenter | Qt.TextWordWrap, '素材不可用\n选择图层后重新定位')

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and not self.view.syncing:
            layer = self.view.session.document.layer(self.layer.id)
            if layer and not layer.locked:
                layer.x, layer.y = value.x(), value.y()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        if self.layer.kind == 'text':
            self.view.edit_text.emit(self.layer.id)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class CoverView(QGraphicsView):
    selection_changed = Signal()
    edit_text = Signal(str)
    files_dropped = Signal(list)
    zoom_changed = Signal(float)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.renderer = CoverRenderer()
        self.items_by_id = {}
        self.syncing = False
        self.before_drag = None
        self.resize_drag = None
        self.pan_point = None
        self.space_down = False
        self.auto_fit = True
        self.hover_handle = None
        self.setMouseTracking(True)
        self.setScene(QGraphicsScene(self))
        self.setObjectName('coverCanvas')
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setAcceptDrops(True)
        self.setMinimumSize(260, 180)
        self.scene().selectionChanged.connect(self.on_selection)
        self.session.changed.connect(self.sync_document)
        self.sync_document()
        # setScene()/setDragMode() can reset the native viewport's tracking.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def sync_document(self):
        self.syncing = True
        document = self.session.document
        wanted = {layer.id for layer in document.layers}
        for key in list(self.items_by_id):
            if key not in wanted:
                item = self.items_by_id.pop(key)
                self.scene().removeItem(item)
                item.deleteLater()
        for z, layer in enumerate(document.layers):
            item = self.items_by_id.get(layer.id)
            if item is None:
                item = LayerItem(self, layer)
                self.items_by_id[layer.id] = item
                self.scene().addItem(item)
            else:
                item.update_layer(layer)
            item.setZValue(z)
            item.setSelected(layer.id in self.session.selected)
        self.scene().setSceneRect(-document.width*.25, -document.height*.25, document.width*1.5, document.height*1.5)
        self.renderer.release_unused(document)
        self.syncing = False
        self.viewport().update()

    def on_selection(self):
        if self.syncing:
            return
        self.session.selected = {item.layer.id for item in self.scene().selectedItems() if isinstance(item, LayerItem)}
        self.selection_changed.emit()
        self.viewport().update()

    def fit_canvas(self):
        self.auto_fit = True
        self.fitInView(QRectF(0, 0, self.session.document.width, self.session.document.height).adjusted(-24, -24, 24, 24), Qt.KeepAspectRatio)
        self.zoom_changed.emit(self.transform().m11())

    def set_zoom(self, value):
        self.auto_fit = False
        value = max(.02, min(8., float(value)))
        self.resetTransform()
        self.scale(value, value)
        self.zoom_changed.emit(value)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit:
            self.fit_canvas()

    def wheelEvent(self, event):
        self.auto_fit = False
        current = self.transform().m11()
        factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
        if .02 <= current*factor <= 8:
            self.scale(factor, factor)
            self.zoom_changed.emit(current*factor)
        event.accept()

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, self.palette().window())
        doc = self.session.document
        canvas = QRectF(0, 0, doc.width, doc.height)
        painter.save()
        painter.setClipRect(canvas)
        painter.fillRect(canvas, QColor('#e1e6e2'))
        step = 16/max(.02, self.transform().m11())
        visible = rect.intersected(canvas)
        left, top = int(visible.left()/step), int(visible.top()/step)
        for y in range(top, int(visible.bottom()/step)+1):
            for x in range(left, int(visible.right()/step)+1):
                if (x+y) % 2:
                    painter.fillRect(QRectF(x*step, y*step, step, step), QColor('#f6f8f5'))
        painter.fillRect(canvas, QColor(doc.background))
        painter.restore()

    def drawForeground(self, painter, rect):
        doc = self.session.document
        # Dim outside the canvas; it is never part of an export.
        painter.save()
        shade = QColor(35, 48, 43, 100)
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width(), max(0, -rect.top())), shade)
        painter.fillRect(QRectF(rect.left(), doc.height, rect.width(), max(0, rect.bottom()-doc.height)), shade)
        painter.fillRect(QRectF(rect.left(), 0, max(0, -rect.left()), doc.height), shade)
        painter.fillRect(QRectF(doc.width, 0, max(0, rect.right()-doc.width), doc.height), shade)
        pen = QPen(QColor('#4f806b'), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(0, 0, doc.width, doc.height))
        handle_size = 10/max(.02, self.transform().m11())
        for item in self.scene().selectedItems():
            bounds = item.sceneBoundingRect()
            painter.drawRect(bounds)
            if len(self.session.selected) == 1 and not item.layer.locked:
                painter.setBrush(QColor('#ffffff'))
                for index, point in enumerate(self.handle_points(bounds)):
                    painter.setBrush(QColor('#79b69b') if self.hover_handle == index else QColor('#ffffff'))
                    painter.drawRect(QRectF(point.x()-handle_size/2, point.y()-handle_size/2, handle_size, handle_size))
                painter.setBrush(Qt.NoBrush)
        painter.restore()

    @staticmethod
    def handle_points(bounds):
        return [bounds.topLeft(), bounds.topRight(), bounds.bottomLeft(), bounds.bottomRight(),
                QPointF(bounds.center().x(), bounds.top()), QPointF(bounds.right(), bounds.center().y()),
                QPointF(bounds.center().x(), bounds.bottom()), QPointF(bounds.left(), bounds.center().y())]

    def hit_handle(self, point):
        if len(self.session.selected) != 1:
            return None
        key = next(iter(self.session.selected))
        item = self.items_by_id.get(key)
        if item is None or item.layer.locked or not item.isVisible():
            return None
        candidates = []
        for index, handle in enumerate(self.handle_points(item.sceneBoundingRect())):
            delta = self.mapFromScene(handle)-point
            if abs(delta.x()) <= 10 and abs(delta.y()) <= 10:
                candidates.append((delta.x()**2+delta.y()**2, index))
        # Nearest centre wins overlapping hit regions; deterministic tie break.
        return min(candidates)[1] if candidates else None

    def handle_cursor(self, index):
        return [Qt.SizeFDiagCursor, Qt.SizeBDiagCursor, Qt.SizeBDiagCursor, Qt.SizeFDiagCursor,
                Qt.SizeVerCursor, Qt.SizeHorCursor, Qt.SizeVerCursor, Qt.SizeHorCursor][index]

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (self.space_down and event.button() == Qt.LeftButton):
            self.pan_point = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self.before_drag = self.session.document.snapshot()
            if len(self.session.selected) == 1:
                key = next(iter(self.session.selected))
                item = self.items_by_id[key]
                if not item.layer.locked:
                    bounds = item.sceneBoundingRect()
                    index = self.hit_handle(event.position().toPoint())
                    if index is not None:
                        proportional = index < 4 if item.layer.kind == 'text' else item.layer.keep_aspect
                        self.resize_drag = (key, index, bounds, self.mapToScene(event.position().toPoint()), proportional)
                        self.viewport().grabMouse()
                        self.setCursor(self.handle_cursor(index))
                        event.accept()
                        return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pan_point is not None:
            point = event.position().toPoint()
            delta = point-self.pan_point
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y())
            self.pan_point = point
            event.accept()
            return
        if self.resize_drag:
            key, corner, bounds, start, proportional = self.resize_drag
            original = self.before_drag.layer(key)
            layer = self.session.document.layer(key)
            delta = self.mapToScene(event.position().toPoint())-start
            horizontal = corner in (0, 1, 2, 3, 5, 7)
            vertical = corner in (0, 1, 2, 3, 4, 6)
            left, top = corner in (0, 2, 7), corner in (0, 1, 4)
            width = max(8., bounds.width()+delta.x()*(-1 if left else 1)) if horizontal else bounds.width()
            height = max(8., bounds.height()+delta.y()*(-1 if top else 1)) if vertical else bounds.height()
            if proportional:
                rx, ry = width/bounds.width(), height/bounds.height()
                ratio = rx if abs(rx-1) >= abs(ry-1) else ry
                maximum = min(32768/bounds.width(), 32768/bounds.height())
                minimum = max(8/bounds.width(), 8/bounds.height())
                if layer.kind == 'text':
                    minimum = max(minimum, 8/float(original.style.get('size', 96)))
                    for field, limit in [('size', 2048), ('stroke', 100), ('shadow_blur', 100), ('shadow_x', 200), ('shadow_y', 200)]:
                        value = abs(float(original.style.get(field, 0)))
                        if value:
                            maximum = min(maximum, limit/value)
                ratio = max(minimum, min(maximum, ratio))
                width, height = bounds.width()*ratio, bounds.height()*ratio
            width, height = min(32768, width), min(32768, height)
            layer.width, layer.height = width, height
            if layer.kind == 'text' and proportional:
                ratio = width/bounds.width()
                layer.style = deepcopy(original.style)
                for field in ('size', 'stroke', 'shadow_blur', 'shadow_x', 'shadow_y'):
                    layer.style[field] = float(original.style.get(field, 0))*ratio
            layer.x = bounds.right()-width if left else bounds.left()
            layer.y = bounds.bottom()-height if top else bounds.top()
            if proportional and not horizontal:
                layer.x = bounds.center().x()-width/2
            if proportional and not vertical:
                layer.y = bounds.center().y()-height/2
            self.sync_document()
            event.accept()
            return
        self.hover_handle = self.hit_handle(event.position().toPoint())
        super().mouseMoveEvent(event)
        if self.hover_handle is not None:
            self.setCursor(self.handle_cursor(self.hover_handle))
        elif not event.buttons():
            self.unsetCursor()
        self.viewport().update()

    def mouseReleaseEvent(self, event):
        if self.pan_point is not None:
            self.pan_point = None
            self.unsetCursor()
            event.accept()
            return
        was_resize = self.resize_drag is not None
        self.resize_drag = None
        if was_resize:
            self.viewport().releaseMouse()
            self.unsetCursor()
        if not was_resize:
            super().mouseReleaseEvent(event)
        if self.before_drag is not None:
            before, self.before_drag = self.before_drag, None
            self.session.commit(before, '缩放图层' if was_resize else '移动图层')
        self.viewport().update()

    def focusOutEvent(self, event):
        self.space_down = False
        if self.resize_drag:
            self.resize_drag = None
            self.viewport().releaseMouse()
            if self.before_drag is not None:
                before, self.before_drag = self.before_drag, None
                self.session.commit(before, '缩放图层')
        self.pan_point = None
        self.unsetCursor()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.space_down = True
            self.setCursor(Qt.OpenHandCursor)
        elif event.matches(QKeySequence.Delete):
            self.session.delete_selected()
        elif event.matches(QKeySequence.SelectAll):
            for item in self.items_by_id.values():
                item.setSelected(item.layer.visible and not item.layer.locked)
        elif event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_D:
            self.session.duplicate_selected()
        elif event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if event.modifiers() & Qt.ShiftModifier else 1
            dx = step if event.key() == Qt.Key_Right else -step if event.key() == Qt.Key_Left else 0
            dy = step if event.key() == Qt.Key_Down else -step if event.key() == Qt.Key_Up else 0
            def move(document):
                for layer in document.layers:
                    if layer.id in self.session.selected and not layer.locked:
                        layer.x += dx
                        layer.y += dy
            self.session.edit('微调位置', move, 'nudge:'+','.join(sorted(self.session.selected)))
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.space_down = False
            self.unsetCursor()
        else:
            super().keyReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
