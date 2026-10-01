"""Local thumbnail template picker; metadata is independent of editor windows."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QComboBox,QListWidget,
    QListWidgetItem,QListView,QPushButton,QCheckBox,QInputDialog,QMessageBox,QLabel)

from .i18n import bind_text

from .i18n import tr


class TemplatePicker(QDialog):
    def __init__(self,library,settings,parent=None,*,local=False,has_frame=False):
        super().__init__(parent)
        self.library,self.settings=library,settings
        self.selected=None
        bind_text(self, '封面模板', property='windowTitle')
        self.resize(830,570)
        layout=QVBoxLayout(self)
        top=QHBoxLayout()
        self.search=QLineEdit();bind_text(self.search, '搜索主播、系列或模板名称', property='placeholderText')
        self.filter=QComboBox();self.filter.addItems(['最近使用','收藏','全部模板'])
        top.addWidget(self.search,1);top.addWidget(self.filter);layout.addLayout(top)
        self.cards=QListWidget();self.cards.setViewMode(QListView.IconMode)
        self.cards.setResizeMode(QListView.Adjust);self.cards.setMovement(QListView.Static)
        self.cards.setIconSize(QSize(224,126));self.cards.setGridSize(QSize(245,175));self.cards.setWordWrap(True)
        layout.addWidget(self.cards,1)
        self.empty=QLabel('还没有模板。编辑封面后点击“保存为模板”，即可保留所有图层和位置。' if local else
                         '还没有模板。编辑封面后选择“保存为模板”，也可导入 XCF / PSD。')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        tools=QHBoxLayout()
        for title,action in [('收藏 / 取消',self.favorite),('重命名',self.rename),('复制',self.duplicate),('删除',self.delete)]:
            button=QPushButton(title);button.clicked.connect(action);tools.addWidget(button)
        layout.addLayout(tools)
        self.replace=QCheckBox('换入本次 Studio 冻结帧（保留模板构图）');self.replace.setChecked(True)
        if local:
            bind_text(self.replace, '使用当前视频帧作为底图（保留模板标题和贴图）')
            self.replace.setChecked(has_frame and str(settings.value('cover/use_current_frame','true')).lower() not in ('false','0'))
            self.replace.setVisible(has_frame)
            self.replace.toggled.connect(lambda value:settings.setValue('cover/use_current_frame',value))
        layout.addWidget(self.replace)
        self.last=QCheckBox('下次按上次模板开始')
        self.last.setChecked(str(settings.value('cover/start_last_template','false')).lower()=='true')
        self.last.toggled.connect(lambda value:settings.setValue('cover/start_last_template',value))
        layout.addWidget(self.last)
        if local:self.last.hide()
        bottom=QHBoxLayout();bottom.addStretch()
        blank=QPushButton('空白新建');blank.clicked.connect(self.blank);bottom.addWidget(blank)
        cancel=QPushButton('取消');cancel.clicked.connect(self.reject);bottom.addWidget(cancel)
        use=QPushButton('使用模板');use.clicked.connect(self.use);bottom.addWidget(use)
        layout.addLayout(bottom)
        self.cards.itemDoubleClicked.connect(self.use)
        self.search.textChanged.connect(self.refresh);self.filter.currentIndexChanged.connect(self.refresh)
        from .studio_theme import apply_secondary_surface_theme
        apply_secondary_surface_theme(self)
        self.refresh()

    def current(self):
        item=self.cards.currentItem()
        return item.data(Qt.UserRole) if item else None

    def refresh(self,*_):
        selected=self.current();self.cards.clear()
        for entry in self.library.entries():
            if self.search.text().casefold() not in entry['name'].casefold():continue
            if self.filter.currentIndex()==1 and not entry.get('favorite'):continue
            item=QListWidgetItem(QIcon(str(self.library.asset(entry,'thumbnail'))),
                ('★ ' if entry.get('favorite') else '')+entry['name']+f'\n{entry["width"]} × {entry["height"]}')
            item.setData(Qt.UserRole,entry);self.cards.addItem(item)
            if selected and selected['id']==entry['id']:self.cards.setCurrentItem(item)
        self.empty.setVisible(not self.cards.count())

    def favorite(self):
        entry=self.current()
        if entry:entry['favorite']=not entry.get('favorite');self.library.metadata(entry);self.refresh()

    def rename(self):
        entry=self.current()
        if not entry:return
        name,ok=QInputDialog.getText(self,tr('重命名模板'),tr('名称'),text=entry['name'])
        if ok and name.strip():entry['name']=name.strip();self.library.metadata(entry);self.refresh()

    def duplicate(self):
        entry=self.current()
        if entry:self.library.duplicate(entry);self.refresh()

    def delete(self):
        entry=self.current()
        if entry and QMessageBox.question(self,tr('删除模板'),tr('从模板库移除“{value0}”？旧版本仍留在本机。', value0=entry['name']))==QMessageBox.Yes:
            entry['deleted']=True;self.library.metadata(entry);self.refresh()

    def use(self,*_):
        self.selected=self.current()
        if self.selected:self.accept()

    def blank(self):
        self.selected={'blank':True};self.accept()
