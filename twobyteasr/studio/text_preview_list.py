"""A resettable text-result model; thousands of rows do not own Qt items.

The small item facade keeps the dialog's existing checkbox/navigation API.
One model reset replaces the result batch, avoiding QListWidget's expensive
native per-item destruction under the application's Windows stylesheet.
"""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QListView


class PreviewItem:
    def __init__(self, text=''):
        self._roles = {Qt.DisplayRole: str(text)}
        self._flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        self._model = None
        self._row = -1

    def data(self, role):
        return self._roles.get(role)

    def setData(self, role, value):
        if self._roles.get(role) == value:
            return
        self._roles[role] = value
        if self._model is not None:
            index = self._model.index(self._row)
            self._model.dataChanged.emit(index,index,[int(role)])
            self._model.view.itemChanged.emit(self)

    def text(self):
        return self.data(Qt.DisplayRole)

    def setText(self, text):
        self.setData(Qt.DisplayRole,str(text))

    def flags(self):
        return self._flags

    def setFlags(self, flags):
        self._flags = flags

    def checkState(self):
        return self._roles.get(Qt.CheckStateRole, Qt.Unchecked)

    def setCheckState(self, state):
        self.setData(Qt.CheckStateRole,Qt.CheckState(state))

    def setToolTip(self, text):
        self.setData(Qt.ToolTipRole,str(text))


class _PreviewModel(QAbstractListModel):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.items = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        value = self.items[index.row()].data(role)
        return value.value if isinstance(value,Qt.CheckState) else value

    def flags(self,index):
        return self.items[index.row()].flags() if index.isValid() else Qt.NoItemFlags

    def setData(self,index,value,role=Qt.EditRole):
        if index.isValid() and role==Qt.CheckStateRole:
            self.items[index.row()].setCheckState(value)
            return True
        return False

    def replace(self,items):
        self.beginResetModel()
        for item in self.items:
            item._model = None
        self.items = list(items)
        for row,item in enumerate(self.items):
            item._model,item._row = self,row
        self.endResetModel()


class TextPreviewList(QListView):
    itemClicked = Signal(object)
    itemDoubleClicked = Signal(object)
    itemChanged = Signal(object)
    currentItemChanged = Signal(object,object)

    def __init__(self,parent=None):
        super().__init__(parent)
        self._items = _PreviewModel(self)
        self.setModel(self._items)
        self.clicked.connect(lambda index:self.itemClicked.emit(self.item(index.row())))
        self.doubleClicked.connect(lambda index:self.itemDoubleClicked.emit(self.item(index.row())))
        self.selectionModel().currentChanged.connect(lambda current,previous:self.currentItemChanged.emit(
            self.item(current.row()) if current.isValid() else None,
            self.item(previous.row()) if previous.isValid() else None))

    def count(self):
        return len(self._items.items)

    def item(self,row):
        return self._items.items[row] if 0 <= row < self.count() else None

    def replace_items(self,items):
        self._items.replace(items)

    def clear(self):
        self.replace_items([])

    def addItem(self,item):
        row=self.count()
        self._items.beginInsertRows(QModelIndex(),row,row)
        item._model,item._row=self._items,row
        self._items.items.append(item)
        self._items.endInsertRows()

    def takeItem(self,row):
        item=self.item(row)
        if item is None:
            return None
        self._items.beginRemoveRows(QModelIndex(),row,row)
        self._items.items.pop(row)
        item._model=None
        for index in range(row,self.count()):
            self._items.items[index]._row=index
        self._items.endRemoveRows()
        return item

    def currentRow(self):
        return self.currentIndex().row()

    def currentItem(self):
        return self.item(self.currentRow())

    def setCurrentItem(self,item):
        self.setCurrentIndex(self._items.index(item._row))

    def setCurrentRow(self,row):
        self.setCurrentIndex(self._items.index(row))

    def scrollToItem(self,item):
        self.scrollTo(self._items.index(item._row))

    def visualItemRect(self,item):
        return self.visualRect(self._items.index(item._row))
