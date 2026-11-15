"""Native resize callbacks must not synchronously reshape home card layouts."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from twobyteasr.app.ui_recognition import RecognitionRoleCard


def test_model_card_size_changes_settle_after_native_resize_returns():
    app = QApplication.instance() or QApplication([])

    class ObservedCard(RecognitionRoleCard):
        def __init__(self):
            self.in_resize = False
            self.nested_updates = []
            self.updates = 0
            super().__init__('primary')

        def resizeEvent(self, event):
            self.in_resize = True
            try:
                super().resizeEvent(event)
            finally:
                self.in_resize = False

        def _sync_model_slot_height(self):
            if self.in_resize:
                self.nested_updates.append('name-height')
            self.updates += 1
            return super()._sync_model_slot_height()

        def _layout_status(self):
            if self.in_resize:
                self.nested_updates.append('status-layout')
            return super()._layout_status()

    card = ObservedCard()
    card.set_state('Qwen3-ForcedAligner Ultra + Local Head', '本地', '已就绪', 'good')
    card.resize(350, 240)
    card.show()
    for _ in range(4):
        app.processEvents()
    card.nested_updates.clear()
    before = card.updates
    for width in range(351, 371):
        card.resize(width, 240)
    assert not card.nested_updates, card.nested_updates
    for _ in range(4):
        app.processEvents()
    assert card.updates > before
    assert card.model_label.height() >= card.model_label.fontMetrics().lineSpacing()
    card.close()
    card.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
