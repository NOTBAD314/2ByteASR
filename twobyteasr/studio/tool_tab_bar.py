"""Full icon-and-text tool entries; narrow drawers wrap as a single grid."""
from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QSizePolicy, QPushButton, QWidget


class ToolTabSelector(QWidget):
    def __init__(self, drawer, parent=None):
        super().__init__(parent)
        self.drawer=drawer
        self.setObjectName('contextToolSelector')
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.grid=QGridLayout(self)
        self.grid.setContentsMargins(0,0,0,0)
        self.grid.setSpacing(4)
        self.group=QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons=[]
        self._columns=0
        self._theme=None
        for index in range(drawer.count()):
            button=QPushButton(self)
            button.setAutoDefault(False)
            button.setObjectName('contextToolTab')
            button.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index:drawer.setCurrentIndex(i))
            self.group.addButton(button,index)
            self.buttons.append(button)
        drawer.currentChanged.connect(self.sync)
        self._restyle()
        self.sync()

    def _restyle(self):
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        key=theme_key()
        if key==self._theme:return
        self._theme=key
        t=theme_definition(key)
        self.setStyleSheet(f'''QPushButton#contextToolTab {{ color:{t.text_muted}; background:transparent;
            border:0; border-radius:9px; padding:4px 8px; min-height:32px; font-weight:600; }}
            QPushButton#contextToolTab:hover {{ color:{t.text}; background:{t.selected}; }}
            QPushButton#contextToolTab:checked {{ color:{t.accent}; background:{t.accent_soft}; font-weight:700; }}''')

    def sync(self, *_args):
        for index,button in enumerate(self.buttons):
            button.setText(self.drawer.tabText(index))
            button.setAccessibleName(self.drawer.tabText(index))
            button.setToolTip(self.drawer.tabToolTip(index))
            button.setIcon(self.drawer.tabIcon(index))
            button.setIconSize(self.drawer.iconSize())
            button.setChecked(index==self.drawer.currentIndex())
        self._reflow()

    def _minimum_cell(self):
        return max((QFontMetrics(b.font()).horizontalAdvance(b.text())+b.iconSize().width()+32
                    for b in self.buttons),default=80)

    def _reflow(self):
        if not self.buttons:return
        self._restyle()
        cell=self._minimum_cell()
        columns=next((n for n in (6,3,2,1) if n*cell+(n-1)*4<=self.width()),1)
        if columns!=self._columns:
            while self.grid.count():self.grid.takeAt(0)
            for old in range(6):self.grid.setColumnStretch(old,0)
            for index,button in enumerate(self.buttons):self.grid.addWidget(button,index//columns,index%columns)
            for column in range(columns):self.grid.setColumnStretch(column,1)
            self._columns=columns
        rows=(len(self.buttons)+columns-1)//columns
        height=max(b.sizeHint().height() for b in self.buttons)*rows+4*(rows-1)
        if self.height()!=height:self.setFixedHeight(height)

    def sizeHint(self):
        return QSize(self._minimum_cell()*6+20,max((b.sizeHint().height() for b in self.buttons),default=40))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._reflow()

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange,QEvent.FontChange,QEvent.PaletteChange):
            QTimer.singleShot(0,self.sync)
