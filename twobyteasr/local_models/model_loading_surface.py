"""One low-cost loading veil for the complete model list, owned by its viewport."""
from time import perf_counter

from PySide6.QtCore import QObject, QEvent, QPoint, QRectF, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class _SkeletonVeil(QWidget):
    def __init__(self, viewport, cards):
        super().__init__(viewport)
        self.cards = cards
        self.opacity = 1.0
        self._shapes = None
        self.setObjectName('modelLoadingVeil')
        self.setAccessibleName('正在准备模型列表')
        self.setGeometry(viewport.rect())

    def paintEvent(self, event):
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition, blend_hex
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.opacity)
        painter.fillRect(self.rect(), QColor(theme.surface))
        painter.setPen(QColor(theme.border))
        if self._shapes is None:
            # Freeze the quiet first frame while native card layouts settle
            # underneath it. Construction must not move the visible skeleton.
            self._shapes = [(QRectF(card.mapTo(self.parentWidget(), QPoint()), card.size()),
                             hasattr(card, 'role')) for card in self.cards.values() if not card.isHidden()]
        for rect, picker in self._shapes:
            if not rect.intersects(QRectF(self.rect())):
                continue
            inset = rect.adjusted(1, 1, -1, -1)
            painter.setBrush(QColor(blend_hex(theme.surface, theme.surface_elevated, .5)))
            painter.drawRoundedRect(inset, 22 if picker else 14, 22 if picker else 14)
            painter.setPen(QColor('transparent'))
            quiet = QColor(blend_hex(theme.surface, theme.text, .07 if theme.is_light else .12))
            painter.setBrush(quiet)
            x, y, width, height = rect.x(), rect.y(), rect.width(), rect.height()
            painter.drawRoundedRect(QRectF(x+17, y+17, 42, 42), 13, 13)
            painter.drawRoundedRect(QRectF(x+72, y+20, max(24, width*.42), 13), 6, 6)
            painter.drawRoundedRect(QRectF(x+72, y+42, max(24, width*.25), 8), 4, 4)
            if picker:
                for offset, proportion in ((83,.82),(113,.62),(146,.88)):
                    painter.drawRoundedRect(QRectF(x+18,y+offset,width*proportion,9),4,4)
                painter.drawRoundedRect(QRectF(x+18,y+height-44,width-36,28),13,13)
            else:
                painter.drawRoundedRect(QRectF(x+72,y+66,max(24,width*.5),8),4,4)
                painter.drawRoundedRect(QRectF(x+width-100,y+height/2-15,82,30),12,12)

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()


class ModelListReveal(QObject):
    """Build all static cards behind one veil, then reveal once. No probe wait.

    GUI-only timers belong to the page. Hide stops construction and any fade;
    reopening resumes existing widgets without spawning detection tasks.
    """
    def __init__(self, scroll, cards):
        super().__init__(scroll)
        self.scroll, self.cards = scroll, cards
        self.ready = False
        self.generation = 0
        self.veil = _SkeletonVeil(scroll.viewport(), cards)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._next)
        self.fade = QVariantAnimation(self)
        self.fade.setStartValue(1.)
        self.fade.setEndValue(0.)
        self.fade.valueChanged.connect(self._opacity)
        self.fade.finished.connect(self._revealed)
        scroll.viewport().installEventFilter(self)
        self.veil.hide()
        self.started = None
        self.building = False          # cards are being built behind the veil right now

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show:
            self.schedule()
        elif event.type() == QEvent.Type.Resize:
            self.veil.setGeometry(obj.rect())
            self.veil._shapes = None
            if not self.ready:
                self.veil.update()
        elif event.type() == QEvent.Type.Hide:
            self.generation += 1
            self.timer.stop()
            self.fade.stop()
            self.veil.hide()
        return False

    def schedule(self, *_):
        if self.ready or not self.scroll.isVisible():
            return
        if self.fade.state() == self.fade.State.Running:
            return
        if all(card._card is not None for card in self.cards.values()):
            self._revealed()
            return
        if self.started is None:
            self.started = perf_counter()
        self.building = True
        self.veil.opacity = 1.
        self.veil.setGeometry(self.scroll.viewport().rect())
        self.veil.show()
        self.veil.raise_()
        if not self.timer.isActive() and self.fade.state() != self.fade.State.Running:
            self.timer.start(0)

    def _next(self):
        if not self.scroll.isVisible():
            return
        started = perf_counter()
        # 2026-11-19: behind the old page's picture (design.transitions.PageHold) nobody watches
        # the list fill, so it is built in bigger steps and shown complete.
        from ..design.transitions import is_held
        budget = .03 if is_held(self.scroll) else .004     # the hold's time limit still gets its turn
        for card in self.cards.values():
            if card._card is None:
                card.materialize()
                if perf_counter()-started >= budget:
                    self.timer.start(0)
                    return
        # One final event-loop turn settles the complete grid under the veil.
        generation = self.generation
        QTimer.singleShot(0, self, lambda: self._complete()
                         if generation == self.generation else None)

    def _complete(self):
        if not self.scroll.isVisible():
            return
        from ..design.ui_motion import motion_duration
        from ..design.transitions import is_held
        duration = 0 if is_held(self.scroll) else motion_duration(160)
        self.fade.setDuration(duration)
        if duration:
            self.fade.start()
        else:
            self._revealed()

    def _opacity(self, value):
        self.veil.opacity = float(value)
        self.veil.update()

    def _revealed(self):
        self.ready = True
        self.building = False
        self.veil.hide()
