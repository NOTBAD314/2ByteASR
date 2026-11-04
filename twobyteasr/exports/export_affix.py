"""Small editable MRU input; records only confirmed, exact strings."""
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QComboBox

HISTORY_LIMIT = 20


def recent_affixes(history, current=''):
    values = [current, *(history if isinstance(history, list) else [])]
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value))[:HISTORY_LIMIT]


class ExportAffixCombo(QComboBox):
    confirmed = Signal()

    def __init__(self, current, history, placeholder, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setCompleter(None)
        self._history = recent_affixes(history, current)
        self._fill(current)
        self.lineEdit().setPlaceholderText(placeholder)
        self.lineEdit().editingFinished.connect(self.confirm)
        self.activated.connect(self.confirm)

    def _fill(self, current):
        blocker = QSignalBlocker(self)
        super().clear()
        self.addItems(['', *self._history])
        self.setEditText(current)
        del blocker

    def confirm(self, *_):
        current = self.currentText()
        self._history = recent_affixes(self._history, current)
        if [self.itemText(i) for i in range(self.count())] != ['', *self._history]:
            self._fill(current)
        self.confirmed.emit()

    def history(self):
        return list(self._history)

    # Preserve the existing export callers' text-field interface.
    def text(self):
        return self.currentText()

    def setText(self, value):
        self.setEditText(value)

    def clear(self):
        self.setEditText('')
