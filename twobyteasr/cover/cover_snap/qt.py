"""Removable Qt adapter; the host owns document changes and undo history."""
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QPushButton

from ...i18n import bind_text
from .geometry import snap_axis


class EdgeSnapController(QObject):
    def __init__(self, view, controls):
        super().__init__(view)
        self.view = view
        self.enabled = False
        self.active_id = None
        self.horizontal = self.vertical = None
        self.modifiers = Qt.NoModifier
        self.button = QPushButton()
        bind_text(self.button, '边框吸附：关闭')
        bind_text(self.button, '拖动单张图片时吸附画布四边；按住 Alt 暂停，拖远可脱离', property='toolTip')
        self.button.setCheckable(True)
        self.button.toggled.connect(self.set_enabled)
        controls.addWidget(self.button)
        view.drag_constraint = self

    def set_enabled(self, enabled):
        self.enabled = enabled
        bind_text(self.button, '边框吸附：开启' if enabled else '边框吸附：关闭')
        self.clear()

    def begin(self):
        self.clear()
        view = self.view
        if len(view.session.selected) != 1:
            return
        key = next(iter(view.session.selected))
        layer = view.session.document.layer(key)
        if layer and layer.kind == 'image' and layer.visible and not layer.locked:
            self.active_id = key

    def position(self, item, proposed):
        view = self.view
        if (not self.enabled or item.layer.id != self.active_id or
                view.before_drag is None or view.resize_drag or view.pan_point is not None):
            return proposed
        if self.modifiers & Qt.AltModifier:
            self.horizontal = self.vertical = None
            return proposed
        document = view.session.document
        bounds = item.boundingRect()
        transform = view.transform()
        self.horizontal = snap_axis(proposed.x()+bounds.left(), bounds.width(),
                                    document.width, abs(transform.m11()), self.horizontal)
        self.vertical = snap_axis(proposed.y()+bounds.top(), bounds.height(),
                                  document.height, abs(transform.m22()), self.vertical)
        return QPointF(self.horizontal.position-bounds.left() if self.horizontal else proposed.x(),
                       self.vertical.position-bounds.top() if self.vertical else proposed.y())

    def paint(self, painter):
        document = self.view.session.document
        painter.save()
        pen = QPen(self.view.palette().highlight().color(), 1, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        if self.horizontal:
            x = self.horizontal.edge
            painter.drawLine(QPointF(x, 0), QPointF(x, document.height))
        if self.vertical:
            y = self.vertical.edge
            painter.drawLine(QPointF(0, y), QPointF(document.width, y))
        painter.restore()

    def clear(self):
        self.active_id = None
        self.horizontal = self.vertical = None
        self.view.viewport().update()

    def detach(self):
        """Remove controls and callbacks without touching document coordinates."""
        if self.view.drag_constraint is not self:
            return
        self.clear()
        self.view.drag_constraint = None
        self.button.toggled.disconnect(self.set_enabled)
        self.button.hide()
        self.button.deleteLater()
        self.deleteLater()


def install(view, controls):
    if isinstance(view.drag_constraint, EdgeSnapController):
        return view.drag_constraint
    return EdgeSnapController(view, controls)
