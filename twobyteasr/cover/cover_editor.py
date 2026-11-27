"""Offline cover workbench with an independent document and undo context."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading
import time

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QColorDialog,
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
    QToolBar, QToolButton, QMenu, QGridLayout, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget, QSizePolicy, QFrame)

from .cover_canvas import CoverSession, CoverView
from .cover_document import CoverDocument, valid_size
from .cover_render import export_image, image_filter, load_image_file, read_image_bytes, text_font

from ..i18n import bind_text

from ..i18n import tr


class CoverJob(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def start(self, function):
        def run():
            from shiboken6 import isValid
            try:
                value = function()
            except Exception as exc:
                if isValid(self):
                    self.failed.emit(str(exc))
            else:
                if isValid(self):
                    self.finished.emit(value)
        threading.Thread(target=run, name='cover-file-io', daemon=True).start()


class CoverLayerDelegate(QStyledItemDelegate):
    """A layer row (2026-11-27): rounded highlight, thumbnail, name, then an eye and a lock that
    toggle the layer's visibility and lock with one click each."""
    ROW = 40

    def __init__(self,editor):
        super().__init__(editor.layers);self.editor=editor

    def sizeHint(self,option,index):
        return QSize(option.rect.width(),self.ROW)

    def _rects(self,rect):
        cy=rect.center().y()
        return QRect(rect.right()-58,cy-12,24,24),QRect(rect.right()-30,cy-12,24,24)

    def paint(self,painter,option,index):
        from ..design.themed_icons import cached_icon_pixmap
        from ..design.ui_theme import blend_hex
        t=self.editor.theme
        layer=self.editor.session.document.layer(index.data(Qt.UserRole))
        rect=option.rect.adjusted(1,1,-1,-1)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        selected=bool(option.state&QStyle.State_Selected);hover=bool(option.state&QStyle.State_MouseOver)
        if selected or hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.accent_soft if selected else blend_hex(t.surface_elevated,t.text,.07)))
            painter.drawRoundedRect(QRectF(rect),11,11)
        visible=layer.visible if layer else True
        plate=QRectF(rect.left()+8,rect.center().y()-13,40,26)
        painter.setPen(Qt.NoPen);painter.setBrush(QColor(blend_hex(t.surface,t.app_background,.6)))
        painter.drawRoundedRect(plate,6,6)
        icon=index.data(Qt.DecorationRole)
        if icon is not None and not icon.isNull():
            painter.setOpacity(1 if visible else .45)
            icon.paint(painter,plate.toRect().adjusted(1,1,-1,-1))
            painter.setOpacity(1)
        eye,lock=self._rects(rect)
        font=QFont(option.font);font.setPixelSize(13)
        if selected:
            from ..design.typography import heavy_font
            heavy_font(font)
        painter.setFont(font)
        painter.setPen(QColor(t.text if visible else t.text_muted))
        text_rect=QRect(int(plate.right())+10,rect.top(),eye.left()-int(plate.right())-14,rect.height())
        painter.drawText(text_rect,Qt.AlignVCenter|Qt.AlignLeft,painter.fontMetrics().elidedText(index.data(Qt.DisplayRole) or '',Qt.ElideRight,text_rect.width()))
        ratio=painter.device().devicePixelRatioF() if painter.device() else 1
        if layer:
            eye_icon=cached_icon_pixmap('fa5s.eye' if layer.visible else 'fa5s.eye-slash',t.text_muted,QSize(14,14),device_pixel_ratio=ratio)
            lock_icon=cached_icon_pixmap('fa5s.lock' if layer.locked else 'fa5s.lock-open',t.accent if layer.locked else blend_hex(t.text_muted,t.surface,.35),QSize(13,13),device_pixel_ratio=ratio)
            painter.drawPixmap(eye.left()+5,eye.top()+5,eye_icon)
            painter.drawPixmap(lock.left()+5,lock.top()+5,lock_icon)
        painter.restore()

    def updateEditorGeometry(self,editor,option,index):
        rect=option.rect
        editor.setGeometry(QRect(rect.left()+56,rect.top()+6,max(60,rect.width()-56-64),rect.height()-12))

    def editorEvent(self,event,model,option,index):
        if event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton:
            eye,lock=self._rects(option.rect.adjusted(1,1,-1,-1))
            point=event.position().toPoint()
            key=index.data(Qt.UserRole)
            layer=self.editor.session.document.layer(key)
            if layer and lock.contains(point):
                self.editor.session.edit('图层锁定',lambda doc:setattr(doc.layer(key),'locked',not layer.locked))
                return True
            if layer and eye.contains(point):
                self.editor.session.edit('图层名称 / 显示',lambda doc:setattr(doc.layer(key),'visible',not layer.visible))
                return True
        return super().editorEvent(event,model,option,index)


class CoverPropertyStack(QStackedWidget):
    def sizeHint(self):
        return self.currentWidget().sizeHint() if self.currentWidget() else super().sizeHint()

    def minimumSizeHint(self):
        return self.currentWidget().minimumSizeHint() if self.currentWidget() else super().minimumSizeHint()

    def setCurrentIndex(self,index):
        super().setCurrentIndex(index)
        self.updateGeometry()


class CoverEditor(QDialog):
    """A separate top-level modal prevents Studio shortcuts and edits leaking in."""

    def __init__(self, document=None, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName('coverEditor')
        self.resize(1280, 820)
        self.setMinimumSize(800, 520)
        self.settings = QSettings('2ByteASR', '2ByteASR')
        self.session = CoverSession(document, self)
        self.frame_document = document.snapshot() if document is not None and document.source.get('captured_at') else None
        self.session.saved_signature = ''
        self.busy = False
        self._refreshing = False
        self._close_after_save = False
        self._after_save = None
        self.last_export = ''
        self.metrics = []
        self.jobs = set()
        from .cover_local_library import LocalCoverLibrary
        self.library = LocalCoverLibrary()
        self._build()
        self.refresh_theme_palette()
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(2500)
        self._autosave.timeout.connect(self.save_local_draft)
        self.session.changed.connect(self._autosave.start)
        self.session.changed.connect(self.refresh)
        self.session.undo.indexChanged.connect(self.refresh)
        self.view.selection_changed.connect(self.refresh)
        self.view.edit_text.connect(self.edit_text)
        self.view.files_dropped.connect(self.add_images)
        self.refresh()
        geometry = self.settings.value('cover/geometry')
        if geometry:
            self.restoreGeometry(geometry)
        QTimer.singleShot(0, self.view.fit_canvas)

    def _build(self):
        # 2026-11-27 (user picked draft 「A 圓角工具箱」): the same layout as before, in the app's
        # rounded frame. Top: 檔案 / 模板 menus and undo / redo in rounded groups, then on the
        # right only 換一幀畫面, 儲存 PSD and the primary 匯出圖片. Left: a rail of round tool
        # buttons. Middle: the canvas on a soft mat with a floating zoom pill and the 「在首頁
        # 看起來」 preview. Right: the layer list (thumbnail, eye, lock) and the properties as
        # sliders, colour dots and segmented choices. 開啟圖片 / 開啟資料夾 appear after an export.
        from ..app.candy_chrome import CandyChrome
        from .cover_widgets import FeedPreview, ZoomPill, icon_button, text_button
        self.chrome = CandyChrome(self, '未命名封面 · 2ByteASR 封面', 'fa5s.image')
        self.restyle()
        layout = self.chrome.layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.cover_actions = {}
        def action(key, label, slot, shortcut=None):
            item = QAction(label, self)
            if shortcut:
                item.setShortcut(shortcut)
            item.triggered.connect(slot)
            self.addAction(item)
            self.cover_actions[key] = item
            return item
        action('new', '新建', self.new_document, QKeySequence.New)
        action('open', '打开', self.open_dialog, QKeySequence.Open)
        action('image', '添加图片', lambda: self.add_images())
        action('text', '添加文字', self.add_text)
        action('undo', '撤销', self.undo, QKeySequence.Undo)
        action('redo', '重做', self.redo, QKeySequence.Redo)
        action('save', '保存 PSD', self.save_dialog, QKeySequence.Save)
        action('save_as', '另存为', lambda: self.save_dialog(save_as=True), QKeySequence.SaveAs)
        action('export', '导出图片', self.export_dialog, 'Ctrl+E')
        action('templates', '选择模板', self.choose_template)
        action('save_template', '保存为模板', self.save_template_dialog)
        draft = self.library.draft()
        if draft and draft.get('kind') == '2bytecover':
            action('restore', '恢复草稿', lambda:self.open_document(self.library.root/draft['file'],draft=True))
        action('lock', '锁定 / 解锁', self.toggle_lock)
        action('sidebar', '图层 / 属性', lambda: self.sidebar.setVisible(not self.sidebar.isVisible()))

        top = QHBoxLayout()
        top.setContentsMargins(14, 2, 14, 10)
        self.toolbar = QToolBar()
        self.toolbar.setObjectName('coverToolbar')
        self.toolbar.setMovable(False)
        top.addWidget(self.toolbar)
        layout.addLayout(top)
        def group(*widgets):
            frame = QFrame()
            frame.setObjectName('coverToolGroup')
            row = QHBoxLayout(frame)
            row.setContentsMargins(3, 3, 3, 3)
            row.setSpacing(2)
            for widget in widgets:
                row.addWidget(widget)
            return frame
        def menu_button(text, icon, keys):
            from ..design.themed_icons import install_themed_icon
            button = QToolButton()
            bind_text(button, '{name} ▾', name=tr(text))
            install_themed_icon(button, icon, 'secondary')
            button.setIconSize(QSize(14, 14))
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setPopupMode(QToolButton.InstantPopup)
            button.setCursor(Qt.PointingHandCursor)
            menu = QMenu(button)
            for key in keys:
                if key in self.cover_actions:
                    menu.addAction(self.cover_actions[key])
            button.setMenu(menu)
            return button
        self.file_button = menu_button('文件', 'fa5s.file', ('new', 'open', 'save_as'))
        self.template_button = menu_button('模板', 'fa5s.th-large', ('templates', 'save_template', 'restore'))
        self.toolbar.addWidget(group(self.file_button, self.template_button))
        self.undo_button = icon_button('fa5s.undo', '撤销 Ctrl+Z', size=30, icon_size=14)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = icon_button('fa5s.redo', '重做 Ctrl+Y', size=30, icon_size=14)
        self.redo_button.clicked.connect(self.redo)
        self.toolbar.addWidget(group(self.undo_button, self.redo_button))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)
        self.frame_slot = QHBoxLayout()
        self.frame_slot.setContentsMargins(0, 0, 0, 0)
        frame_host = QWidget()
        frame_host.setLayout(self.frame_slot)
        self.toolbar.addWidget(frame_host)
        self.save_button = text_button('保存 PSD', icon='fa5s.save')
        self.save_button.clicked.connect(self.cover_actions['save'].trigger)
        self.toolbar.addWidget(self.save_button)
        self.export_button = text_button('导出图片', icon='fa5s.download', kind='primary')
        self.export_button.clicked.connect(self.cover_actions['export'].trigger)
        self.toolbar.addWidget(self.export_button)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        layout.addLayout(body, 1)
        self.tools = QFrame()
        self.tools.setObjectName('coverRail')
        rail = QVBoxLayout(self.tools)
        rail.setContentsMargins(8, 2, 8, 8)
        rail.setSpacing(4)
        self.rail_buttons = {}
        for key, icon, tip, slot in [('text', 'fa5s.font', '添加文字', self.cover_actions['text'].trigger),
                                     ('image', 'fa5s.image', '添加图片', self.cover_actions['image'].trigger),
                                     ('background', 'fa5s.exchange-alt', '更换底图（保留标题和贴图）', lambda: self.add_images(background=True)),
                                     (None, None, None, None),
                                     ('lock', 'fa5s.lock', '锁定 / 解锁选中的图层', self.toggle_lock)]:
            if key is None:
                line = QFrame()
                line.setObjectName('coverRailSeparator')
                line.setFixedSize(24, 1)
                rail.addWidget(line, 0, Qt.AlignHCenter)
                continue
            button = icon_button(icon, tip, size=42, icon_size=17)
            button.clicked.connect(slot)
            self.rail_buttons[key] = button
            rail.addWidget(button, 0, Qt.AlignHCenter)
        rail.addStretch(1)
        body.addWidget(self.tools)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        body.addWidget(self.splitter, 1)

        canvas_host = QFrame()
        canvas_host.setObjectName('coverMat')
        stack = QGridLayout(canvas_host)
        stack.setContentsMargins(0, 0, 0, 0)
        self.view = CoverView(self.session)
        self.view.fit_padding = (30, 26, 30, 168)
        # Room to centre the canvas in the free area above the floating bar; no scroll bars
        # (pan with Space + drag or the middle button, zoom with the wheel or the pill).
        self.view.scene_margin = 1.0
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.sync_document()
        stack.addWidget(self.view, 0, 0)
        def floating(widget, alignment):
            holder = QWidget()
            holder.setAttribute(Qt.WA_TranslucentBackground)
            row = QHBoxLayout(holder)
            row.setContentsMargins(14, 12, 14, 12)
            row.addWidget(widget)
            holder.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
            stack.addWidget(holder, 0, 0, alignment)
            return holder
        self.zoom_pill = ZoomPill(self.view)
        floating(self.zoom_pill, Qt.AlignLeft | Qt.AlignBottom)
        try:
            from .cover_snap.qt import install
        except ModuleNotFoundError as exc:
            if exc.name not in (f'{__package__}.cover_snap', f'{__package__}.cover_snap.qt'):
                raise
        else:
            self._cover_snap = install(self.view, self.zoom_pill.tail)
        self.feed_preview = FeedPreview(self.session)
        floating(self.feed_preview, Qt.AlignRight | Qt.AlignBottom)
        self.splitter.addWidget(canvas_host)

        sidebar = self.sidebar = QWidget()
        sidebar.setMinimumWidth(300)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 0, 14, 10)
        side.setSpacing(10)
        layers_card = QFrame()
        layers_card.setObjectName('coverCard')
        layers_box = QVBoxLayout(layers_card)
        layers_box.setContentsMargins(10, 10, 10, 10)
        layers_box.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        layers_title = QLabel()
        layers_title.setObjectName('coverSectionTitle')
        bind_text(layers_title, '图层')
        head.addWidget(layers_title)
        head.addStretch(1)
        hint = QLabel()
        hint.setObjectName('coverHint')
        bind_text(hint, '拖动排序')
        head.addWidget(hint)
        layers_box.addLayout(head)
        self.layers = QListWidget()
        self.layers.setObjectName('coverLayers')
        self.layers.setItemDelegate(CoverLayerDelegate(self))
        self.layers.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.layers.setEditTriggers(QAbstractItemView.EditKeyPressed | QAbstractItemView.DoubleClicked)
        self.layers.setMinimumHeight(120)
        self.layers.setMaximumHeight(212)
        self.layers.setIconSize(QSize(40, 26))
        self.layers.setMouseTracking(True)
        self.layers.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.layers.setDragDropMode(QAbstractItemView.InternalMove)
        self.layers.setDefaultDropAction(Qt.MoveAction)
        self.layers.model().rowsMoved.connect(lambda: QTimer.singleShot(0, self.reorder_from_list))
        self.layers.itemSelectionChanged.connect(self.layer_selection)
        self.layers.itemChanged.connect(self.layer_item_changed)
        self.layers.installEventFilter(self)
        layers_box.addWidget(self.layers)
        layer_buttons = QHBoxLayout()
        layer_buttons.setSpacing(6)
        for text, icon, slot in [('复制', 'fa5s.copy', self.session.duplicate_selected), ('删除', 'fa5s.trash-alt', self.session.delete_selected)]:
            button = text_button(text, icon=icon)
            button.setMinimumHeight(30)
            button.clicked.connect(slot)
            layer_buttons.addWidget(button)
        layers_box.addLayout(layer_buttons)
        side.addWidget(layers_card)

        properties_card = QFrame()
        properties_card.setObjectName('coverCard')
        properties_box = QVBoxLayout(properties_card)
        properties_box.setContentsMargins(12, 10, 4, 6)
        properties_box.setSpacing(4)
        self.property_title = QLabel('画布')
        self.property_title.setObjectName('coverSectionTitle')
        properties_box.addWidget(self.property_title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        property_host = QWidget()
        property_host.setMinimumWidth(0)
        properties = QVBoxLayout(property_host)
        properties.setContentsMargins(0, 4, 6, 6)
        properties.setSpacing(6)
        self._build_properties(properties)
        properties.addStretch()
        self.scroll.setWidget(property_host)
        properties_box.addWidget(self.scroll, 1)
        side.addWidget(properties_card, 1)
        self.splitter.addWidget(sidebar)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([930, 320])

        status_bar = QFrame()
        status_bar.setObjectName('coverStatusBar')
        bottom = QHBoxLayout(status_bar)
        bottom.setContentsMargins(16, 5, 14, 7)
        bottom.setSpacing(8)
        self.status = QLabel('封面编辑只影响独立封面工程。')
        self.status.setObjectName('coverStatus')
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.open_image = text_button('打开图片', icon='fa5s.image', kind='ghost')
        self.open_image.setMinimumHeight(28)
        self.open_image.clicked.connect(lambda: self.open_result())
        bottom.addWidget(self.open_image)
        self.open_folder = text_button('打开文件夹', icon='fa5s.folder-open', kind='ghost')
        self.open_folder.setMinimumHeight(28)
        self.open_folder.clicked.connect(lambda: self.open_result(folder=True))
        bottom.addWidget(self.open_folder)
        layout.addWidget(status_bar)

    def _build_properties(self, properties):
        from .cover_widgets import Segmented, SliderRow, SwatchRow, form_row, icon_button, text_button
        self.common = QWidget()
        common = QVBoxLayout(self.common)
        common.setContentsMargins(0, 0, 0, 6)
        common.setSpacing(6)
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(lambda: self.change_layer('name', self.name_edit.text(), '重命名'))
        common.addWidget(form_row('名称', self.name_edit))
        self.geometry = {}
        geometry_host = QWidget()
        geometry_grid = QGridLayout(geometry_host)
        geometry_grid.setContentsMargins(0, 0, 0, 0)
        geometry_grid.setHorizontalSpacing(6)
        geometry_grid.setVerticalSpacing(6)
        geometry_grid.setColumnStretch(1, 1)
        geometry_grid.setColumnStretch(3, 1)
        for index, (key, label) in enumerate([('x', 'X'), ('y', 'Y'), ('width', 'W'), ('height', 'H')]):
            box = self.number(-32768 if key in ('x', 'y') else 8, 32768, ' px')
            box.setMinimumWidth(72)
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            box.editingFinished.connect(lambda field=key, widget=box: self.change_geometry(field, widget.value()))
            self.geometry[key] = box
            title = QLabel(label)
            title.setObjectName('coverRowLabel')
            title.setFixedWidth(14 if index % 2 else 46)
            geometry_grid.addWidget(title, index//2, (index%2)*2)
            geometry_grid.addWidget(box, index//2, (index%2)*2+1)
        common.addWidget(geometry_host)
        self.aspect = QCheckBox('等比缩放')
        bind_text(self.aspect, '勾选时：拖动角点、边柄或修改宽高都保持比例。取消后可单独拉宽或拉高。', property='toolTip')
        self.aspect.toggled.connect(lambda checked: self.change_layer('keep_aspect', checked, '保持比例'))
        self.locked = QCheckBox('锁定图层')
        self.locked.toggled.connect(lambda checked: self.change_layer('locked', checked, '锁定图层'))
        checks = QWidget()
        checks_row = QHBoxLayout(checks)
        checks_row.setContentsMargins(54, 0, 0, 0)
        checks_row.setSpacing(14)
        checks_row.addWidget(self.aspect)
        checks_row.addWidget(self.locked)
        checks_row.addStretch(1)
        common.addWidget(checks)
        self.opacity = SliderRow(0, 100, suffix=' %')
        self.opacity.moved.connect(lambda value: self.change_layer('opacity', value/100, '不透明度', 'opacity'))
        self.opacity.committed.connect(lambda value: self.change_layer('opacity', value/100, '不透明度', 'opacity'))
        common.addWidget(form_row('不透明', self.opacity))
        properties.addWidget(self.common)
        self.pages = CoverPropertyStack()
        properties.addWidget(self.pages)

        self.canvas_page = QWidget()
        canvas = QVBoxLayout(self.canvas_page)
        canvas.setContentsMargins(0, 0, 0, 0)
        canvas.setSpacing(8)
        self.preset = Segmented([('16:9', (1920, 1080)), ('1:1', (1080, 1080)), ('9:16', (1080, 1920))])
        bind_text(self.preset, '常用尺寸；其他尺寸直接改下面的宽高，再点“应用”', property='toolTip')
        self.preset.changed.connect(lambda _value: self.canvas_preset())
        canvas.addWidget(form_row('尺寸', self.preset))
        self.canvas_width = self.number(16, 16384, ' px')
        self.canvas_height = self.number(16, 16384, ' px')
        for box in (self.canvas_width, self.canvas_height):
            box.setDecimals(0)
            box.setMinimumWidth(70)
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        size_host = QWidget()
        size_row = QHBoxLayout(size_host)
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(6)
        size_row.addWidget(self.canvas_width, 1)
        times = QLabel('×')
        times.setObjectName('coverRowLabel')
        size_row.addWidget(times)
        size_row.addWidget(self.canvas_height, 1)
        canvas.addWidget(form_row('', size_host))
        self.fit_mode = Segmented([('适应', 'fit'), ('填满', 'fill'), ('原尺寸', 'original')])
        self.fit_mode.changed.connect(lambda _value: self.resize_canvas())
        bind_text(self.fit_mode, '适应：完整显示底图；填充：居中裁切铺满；原尺寸：居中不缩放', property='toolTip')
        canvas.addWidget(form_row('底图', self.fit_mode))
        resize = text_button('应用尺寸', kind='soft')
        bind_text(resize, '应用画布尺寸与底图布局', property='toolTip')
        resize.clicked.connect(self.resize_canvas)
        canvas.addWidget(resize)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        replace = text_button('换张底图…', icon='fa5s.image')
        bind_text(replace, '更换底图，保留标题和贴图', property='toolTip')
        replace.clicked.connect(lambda: self.add_images(background=True))
        buttons.addWidget(replace)
        self.background_button = text_button('背景色', icon='fa5s.fill-drip')
        bind_text(self.background_button, '设置画布背景色 / 透明度', property='toolTip')
        self.background_button.clicked.connect(self.canvas_background)
        buttons.addWidget(self.background_button)
        canvas.addLayout(buttons)
        self.source_label = QLabel()
        self.source_label.setObjectName('coverHint')
        self.source_label.setWordWrap(True)
        canvas.addWidget(self.source_label)
        canvas.addStretch(1)
        self.pages.addWidget(self.canvas_page)

        self.image_page = QWidget()
        image_layout = QVBoxLayout(self.image_page)
        image_layout.setAlignment(Qt.AlignTop)
        image_layout.setSpacing(8)
        image_layout.setContentsMargins(0, 0, 0, 0)
        relink = text_button('替换 / 重新定位素材…', icon='fa5s.image')
        relink.clicked.connect(self.relink_image)
        image_layout.addWidget(relink)
        image_tools = QHBoxLayout()
        image_tools.setSpacing(6)
        for title, mode in [('适应', 'fit'), ('填满', 'fill'), ('恢复', 'original')]:
            button = text_button(title)
            button.setMinimumHeight(30)
            button.clicked.connect(lambda checked=False, value=mode: self.fit_selected(value))
            image_tools.addWidget(button)
        center_layer = icon_button('fa5s.crosshairs', '移回画布中央', size=32, icon_size=14)
        center_layer.clicked.connect(lambda: self.fit_selected('center'))
        image_tools.addWidget(center_layer)
        image_layout.addLayout(image_tools)
        self.pages.addWidget(self.image_page)

        self.text_page = QWidget()
        text_layout = QVBoxLayout(self.text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(8)
        self.text_edit = QPlainTextEdit()
        bind_text(self.text_edit, '输入中文标题；Enter 换行', property='placeholderText')
        self.text_edit.setMinimumHeight(58)
        self.text_edit.setMaximumHeight(78)
        self.text_edit.setUndoRedoEnabled(False)
        self.text_edit.installEventFilter(self)
        self._text_commit_timer = QTimer(self)
        self._text_commit_timer.setSingleShot(True)
        self._text_commit_timer.setInterval(0)
        self._text_commit_timer.timeout.connect(self.text_changed)
        self.text_edit.textChanged.connect(self._queue_text_change)
        text_layout.addWidget(self.text_edit)
        from .cover_font_picker import FontFamilyCombo
        from ..caption_style.font_metadata import local_faces
        self.font_faces = local_faces()
        self.font_family = FontFamilyCombo(self.font_faces)
        self.font_family.setMinimumContentsLength(6)
        self.font_family.activated.connect(self.choose_font)
        self.font_family.lineEdit().editingFinished.connect(self.choose_font)
        self.font_family.completer().activated[str].connect(self.choose_font_completion)
        text_layout.addWidget(form_row('字体', self.font_family))
        self.font_weight = QComboBox()
        self.font_weight.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.font_weight.setMinimumContentsLength(6)
        self.font_weight.activated.connect(self.choose_weight)
        text_layout.addWidget(form_row('字重', self.font_weight))
        self.font_warning = QLabel()
        self.font_warning.setObjectName('coverHint')
        self.font_warning.setWordWrap(True)
        text_layout.addWidget(self.font_warning)
        self.text_numbers = {}
        def slider(key, low, high, zero=''):
            row = SliderRow(low, high, zero_text=zero)
            row.moved.connect(lambda value, field=key: self.change_style(field, value, merge=True))
            row.committed.connect(lambda value, field=key: self.change_style(field, value, merge=True))
            self.text_numbers[key] = row
            return row
        text_layout.addWidget(form_row('字号', slider('size', 8, 600)))
        self.text_color = SwatchRow(title='文字颜色')
        self.text_color.picked.connect(lambda value: self.change_style('color', value))
        text_layout.addWidget(form_row('颜色', self.text_color))
        stroke_host = QWidget()
        stroke_row = QHBoxLayout(stroke_host)
        stroke_row.setContentsMargins(0, 0, 0, 0)
        stroke_row.setSpacing(6)
        stroke_row.addWidget(slider('stroke', 0, 40, tr('无')), 1)
        self.color_buttons = {}
        self.stroke_color = self._color_dot('stroke_color', '描边颜色')
        stroke_row.addWidget(self.stroke_color)
        text_layout.addWidget(form_row('描边', stroke_host))
        shadow_host = QWidget()
        shadow_row = QHBoxLayout(shadow_host)
        shadow_row.setContentsMargins(0, 0, 0, 0)
        shadow_row.setSpacing(6)
        self.shadow_preset = Segmented([('无', 'none'), ('柔和', 'soft'), ('硬投影', 'hard'), ('发光', 'glow')])
        self.shadow_preset.changed.connect(self.apply_shadow_preset)
        shadow_row.addWidget(self.shadow_preset)
        self.shadow_color = self._color_dot('shadow_color', '阴影颜色')
        shadow_row.addWidget(self.shadow_color)
        shadow_row.addStretch(1)
        text_layout.addWidget(form_row('阴影', shadow_host))
        self.shadow_more = QPushButton()
        self.shadow_more.setObjectName('coverGhost')
        self.shadow_more.setCheckable(True)
        self.shadow_more.setCursor(Qt.PointingHandCursor)
        bind_text(self.shadow_more, '阴影细调 ▾')
        text_layout.addWidget(self.shadow_more, 0, Qt.AlignLeft)
        self.shadow_details = QWidget()
        details = QVBoxLayout(self.shadow_details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(6)
        details.addWidget(form_row('模糊', slider('shadow_blur', 0, 100)))
        details.addWidget(form_row('横移', slider('shadow_x', -200, 200)))
        details.addWidget(form_row('纵移', slider('shadow_y', -200, 200)))
        self.shadow_details.hide()
        self.shadow_more.toggled.connect(self.shadow_details.setVisible)
        text_layout.addWidget(self.shadow_details)
        self.alignment = Segmented([('左对齐', 'left', 'fa5s.align-left'), ('居中', 'center', 'fa5s.align-center'),
                                    ('右对齐', 'right', 'fa5s.align-right')], icon_only=True)
        self.alignment.changed.connect(lambda value: self.change_style('alignment', value))
        align_host = QWidget()
        align_row = QHBoxLayout(align_host)
        align_row.setContentsMargins(0, 0, 0, 0)
        align_row.addWidget(self.alignment)
        align_row.addStretch(1)
        text_layout.addWidget(form_row('对齐', align_host))
        self.pages.addWidget(self.text_page)
        self.multi_page = QLabel('已选中多个图层。\n在画布中一起拖动，或复制 / 删除。\n锁定的图层不会移动或删除。')
        self.multi_page.setObjectName('coverHint')
        self.multi_page.setWordWrap(True)
        self.pages.addWidget(self.multi_page)
        self.text_color.set_theme(self.theme.accent, self.theme.border_strong)

    def _color_dot(self, field, title):
        from .cover_widgets import Swatch
        dot = Swatch('#000000')
        bind_text(dot, title, property='toolTip')
        dot.clicked.connect(lambda: self.choose_text_color(field))
        dot.ring, dot.edge = QColor(self.theme.accent), QColor(self.theme.border_strong)
        self.color_buttons[field] = dot
        return dot

    def add_frame_action(self, text, slot, tip=''):
        """A 「換一幀畫面」 button left of 保存 PSD (Studio adds it; the editor alone has none)."""
        from .cover_widgets import text_button
        self.frame_action = QAction(text, self)
        self.frame_action.triggered.connect(slot)
        self.addAction(self.frame_action)
        self.frame_button = text_button(text, icon='fa5s.camera', kind='soft')
        if tip:
            bind_text(self.frame_button, tip, property='toolTip')
        self.frame_button.clicked.connect(self.frame_action.trigger)
        self.frame_slot.addWidget(self.frame_button)
        return self.frame_action

    def restyle(self):
        from ..design.candy_chrome_qss import build_candy_chrome_qss
        from ..design.cover_qss import build_editor_qss
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        self.theme = theme_definition(theme_key())
        from ..design.typography import emphasis_qss
        root = 'QDialog#coverEditor'
        self.setStyleSheet(emphasis_qss(build_candy_chrome_qss(root, self.theme)) + build_editor_qss(root, self.theme))

    def refresh_theme_palette(self):
        self.restyle()
        if hasattr(self, 'text_color'):
            self.text_color.set_theme(self.theme.accent, self.theme.border_strong)
            for dot in self.color_buttons.values():
                dot.ring, dot.edge = QColor(self.theme.accent), QColor(self.theme.border_strong)
            from ..design.ui_theme import blend_hex
            self.feed_preview.set_line_color(blend_hex(self.theme.surface_elevated, self.theme.text, .14))
            self.view.mat_color = QColor(blend_hex(self.theme.surface, self.theme.app_background, .55))
            self.view.viewport().update()
            self.layers.viewport().update()

    @staticmethod
    def number(low, high, suffix):
        box = QDoubleSpinBox()
        box.setRange(low, high)
        box.setDecimals(1)
        box.setSuffix(suffix)
        box.setKeyboardTracking(False)
        return box

    def selected_layer(self):
        return self.session.document.layer(next(iter(self.session.selected))) if len(self.session.selected) == 1 else None

    def refresh(self, *_):
        self._refreshing = True
        doc = self.session.document
        name = Path(self.session.filename).name if self.session.filename else '未命名封面'
        bind_text(self, '{value0}{name} · 2ByteASR 封面', property='windowTitle', value0='● ' if self.session.dirty else '', name=name)
        bind_text(self.chrome.title, '{value0}{name} · 2ByteASR 封面', value0='● ' if self.session.dirty else '', name=name)
        self.cover_actions['undo'].setEnabled(self.session.undo.canUndo())
        self.cover_actions['redo'].setEnabled(self.session.undo.canRedo())
        self.undo_button.setEnabled(self.session.undo.canUndo())
        self.redo_button.setEnabled(self.session.undo.canRedo())
        self.open_image.setEnabled(bool(self.last_export))
        self.open_folder.setEnabled(bool(self.last_export))
        self.open_image.setVisible(bool(self.last_export))
        self.open_folder.setVisible(bool(self.last_export))
        self.layers.blockSignals(True)
        self.layers.clear()
        for layer in reversed(doc.layers):
            item = QListWidgetItem(layer.name)
            try:
                preview = self.view.renderer.layer_image(doc, layer)
                item.setIcon(QIcon(QPixmap.fromImage(preview.scaled(80, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))))
            except (ValueError, OSError):
                pass
            item.setSizeHint(QSize(120, CoverLayerDelegate.ROW))
            item.setData(Qt.UserRole, layer.id)
            item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
            bind_text(item, ('已锁定 · ' if layer.locked else '') + ('可编辑文字' if layer.kind == 'text' else '图片图层'), property='toolTip')
            self.layers.addItem(item)
            item.setSelected(layer.id in self.session.selected)
        self.layers.blockSignals(False)
        layer = self.selected_layer()
        self.cover_actions['lock'].setEnabled(bool(self.session.selected))
        self.rail_buttons['lock'].setEnabled(bool(self.session.selected))
        (bind_text(self.cover_actions['lock'], '解锁图层') if layer and layer.locked else bind_text(self.cover_actions['lock'], '锁定图层'))
        self.common.setVisible(layer is not None)
        if layer is None:
            (bind_text(self.property_title, '多选图层') if self.session.selected else bind_text(self.property_title, '画布 · {value0} × {value1} px', value0=doc.width, value1=doc.height))
            self.pages.setCurrentIndex(3 if self.session.selected else 0)
            self.canvas_width.setValue(doc.width)
            self.canvas_height.setValue(doc.height)
            self.fit_mode.set_value(doc.background_fit)
            self.preset.set_value((doc.width, doc.height) if (doc.width, doc.height) in ((1920, 1080), (1080, 1080), (1080, 1920)) else None)
            source = doc.source
            bind_text(self.source_label, (f"来源时间：{source.get('milliseconds', 0) / 1000:.3f} 秒\n" if 'milliseconds' in source else '') + ('底图包含软件字幕；这些文字已成为图片像素。' if source.get('subtitles') else '标题以独立文字图层保存，可继续修改。'))
        else:
            bind_text(self.property_title, ('文字' if layer.kind == 'text' else '图片') + (' · 已锁定' if layer.locked else ''))
            if self.name_edit.text() != layer.name:
                self.name_edit.setText(layer.name)
            for key, box in self.geometry.items():
                value = self.view.items_by_id[layer.id].boundingRect().height() if layer.kind == 'text' and key == 'height' else getattr(layer, key)
                box.setValue(value)
                box.setEnabled(not layer.locked and not (layer.kind == 'text' and key == 'height'))
            self.aspect.setChecked(layer.keep_aspect)
            self.aspect.setVisible(layer.kind == 'image')
            self.opacity.setValue(layer.opacity*100)
            self.locked.setChecked(layer.locked)
            self.pages.setCurrentIndex(2 if layer.kind == 'text' else 1)
            self.pages.currentWidget().setEnabled(not layer.locked)
            if layer.kind == 'text':
                if self.text_edit.toPlainText() != layer.text:
                    self.text_edit.setPlainText(layer.text)
                self.font_family.show_family(layer.style.get('family', 'Source Han Sans SC'))
                self.refresh_weights(layer)
                _, warning, face = text_font(layer.style)
                from .cover_font_picker import style_label
                self.font_warning.setText(warning or f'{face.display_family or face.family} · {style_label(face.display_style or face.style)} · {face.weight}')
                for key, box in self.text_numbers.items():
                    box.setValue(float(layer.style.get(key, 0)))
                self.text_color.set_current(layer.style.get('color', '#ffffff'))
                for key, dot in self.color_buttons.items():
                    dot.color = layer.style.get(key, '#000000')
                    dot.update()
                self.shadow_preset.set_value(self.shadow_kind(layer.style))
                self.alignment.set_value(layer.style.get('alignment', 'left'))
        self._refreshing = False

    def toggle_lock(self):
        ids = self.session.selected.copy()
        layers = [layer for layer in self.session.document.layers if layer.id in ids]
        value = not all(layer.locked for layer in layers)
        self.session.edit('锁定 / 解锁', lambda doc: [setattr(layer, 'locked', value) for layer in doc.layers if layer.id in ids])

    def reorder_from_list(self):
        ids = [self.layers.item(i).data(Qt.UserRole) for i in reversed(range(self.layers.count()))]
        if set(ids) != {layer.id for layer in self.session.document.layers}:
            return
        self.session.edit('拖动图层排序', lambda doc: setattr(doc, 'layers', [doc.layer(key) for key in ids]))

    def fit_selected(self, mode):
        layer = self.selected_layer()
        if not layer or layer.locked or layer.kind != 'image':
            return
        def update(doc):
            item = doc.layer(layer.id)
            image = read_image_bytes(doc.assets[item.asset])
            if mode != 'center':
                ratio = 1 if mode == 'original' else (max if mode == 'fill' else min)(doc.width/image.width(), doc.height/image.height())
                item.width, item.height = image.width()*ratio, image.height()*ratio
            item.x, item.y = (doc.width-item.width)/2, (doc.height-item.height)/2
        self.session.edit('恢复图层构图', update)

    def refresh_weights(self, layer):
        family = str(layer.style.get('family', ''))
        values = {(face.weight, face.style) for face in self.font_faces if family.casefold() in {a.casefold() for a in face.aliases}}
        requested = (int(layer.style.get('weight', 900)), layer.style.get('font_style', 'Heavy'))
        self.font_weight.clear()
        for weight, style in sorted(values):
            from .cover_font_picker import style_label
            self.font_weight.addItem(f'{style_label(style)} · {weight}', (weight, style))
        if requested not in values:
            from ..i18n_widgets import add_combo_item
            add_combo_item(self.font_weight, tr('缺失 · {name} / {id}', name=requested[1], id=requested[0]), requested)
        self.font_weight.setCurrentIndex(max(0, self.font_weight.findData(requested)))

    def layer_selection(self):
        if self._refreshing:
            return
        self.session.selected = {item.data(Qt.UserRole) for item in self.layers.selectedItems()}
        self.view.sync_document()
        self.refresh()

    def layer_item_changed(self, item):
        if self._refreshing:
            return
        key, name, visible = item.data(Qt.UserRole), item.text(), item.checkState() == Qt.Checked
        def update(doc):
            layer = doc.layer(key)
            layer.name, layer.visible = name, visible
        self.session.edit('图层名称 / 显示', update)

    def change_layer(self, field, value, label, merge=''):
        layer = self.selected_layer()
        if self._refreshing or layer is None or (layer.locked and field not in ('locked', 'name')):
            return
        key = layer.id
        self.session.edit(label, lambda doc: setattr(doc.layer(key), field, value), f'{merge}:{key}' if merge else '')

    def change_geometry(self, field, value):
        layer = self.selected_layer()
        if self._refreshing or layer is None or layer.locked:
            return
        key = layer.id
        def update(doc):
            item = doc.layer(key)
            if field in ('width', 'height') and item.keep_aspect and item.kind == 'image':
                ratio = value/getattr(item, field)
                other = 'height' if field == 'width' else 'width'
                ratio = min(ratio, 32768/getattr(item, other))
                value_adjusted = getattr(item, field)*ratio
                setattr(item, other, getattr(item, other)*ratio)
                setattr(item, field, value_adjusted)
            else:
                setattr(item, field, value)
        self.session.edit('调整尺寸 / 位置', update)

    def change_style(self, field, value, merge=False):
        layer = self.selected_layer()
        if self._refreshing or layer is None or layer.kind != 'text' or layer.locked:
            return
        if field in ('size', 'stroke', 'shadow_blur', 'shadow_x', 'shadow_y'):
            value = float(value)
        self.session.edit('文字样式', lambda doc: doc.layer(layer.id).style.update({field: value}),
                          f'style:{layer.id}:{field}' if merge else '')

    @staticmethod
    def shadow_kind(style):
        if not style.get('shadow'):
            return 'none'
        if float(style.get('shadow_blur', 0)) == 0:
            return 'hard'
        if float(style.get('shadow_x', 0)) == 0 and float(style.get('shadow_y', 0)) == 0:
            return 'glow'
        return 'soft'

    def apply_shadow_preset(self, kind):
        """无 / 柔和 / 硬投影 / 发光, sized from the font size so a big title gets a big shadow."""
        layer = self.selected_layer()
        if self._refreshing or layer is None or layer.kind != 'text' or layer.locked:
            return
        size = float(layer.style.get('size', 96))
        values = {'none': dict(shadow=False),
                  'soft': dict(shadow=True, shadow_blur=float(min(100, round(size*.12))), shadow_x=0.0,
                               shadow_y=float(min(200, round(size*.05))), shadow_color='#a0000000'),
                  'hard': dict(shadow=True, shadow_blur=0.0, shadow_x=float(min(200, round(size*.04))),
                               shadow_y=float(min(200, round(size*.05))), shadow_color='#ff141414'),
                  'glow': dict(shadow=True, shadow_blur=float(min(100, round(size*.2))), shadow_x=0.0, shadow_y=0.0,
                               shadow_color='#e04fe3a5')}[kind]
        self.session.edit('阴影样式', lambda doc: doc.layer(layer.id).style.update(values))

    def text_changed(self):
        layer = self.selected_layer()
        if self._refreshing or layer is None or layer.locked:
            return
        text = self.text_edit.toPlainText()
        self.session.edit('编辑文字', lambda doc: setattr(doc.layer(layer.id), 'text', text), 'text:'+layer.id)

    def _queue_text_change(self):
        if not self._refreshing:
            # Do not rebuild property controls while an IME commit is still
            # updating QTextDocument's preedit layout and selection.
            self._text_commit_timer.start()

    def flush_text(self):
        if self._text_commit_timer.isActive():
            self._text_commit_timer.stop()
            self.text_changed()

    def choose_font(self):
        layer = self.selected_layer()
        if self._refreshing or not layer or layer.kind != 'text' or layer.locked:
            return
        family = self.font_family.family()
        if not family:
            self.font_family.show_family(layer.style.get('family', 'Source Han Sans SC'))
            return
        matches = [face for face in self.font_faces if family.casefold() in {a.casefold() for a in face.aliases}]
        def update(doc):
            style = doc.layer(layer.id).style
            style['family'] = family
            if matches:
                face = min(matches, key=lambda f: abs(f.weight-int(style.get('weight', 900))))
                style.update(weight=face.weight, font_style=face.style)
        self.session.edit('选择字体', update)
        self.font_family.show_family(self.session.document.layer(layer.id).style['family'])

    def choose_font_completion(self, name):
        self.font_family.setEditText(name)
        self.choose_font()

    def choose_weight(self):
        layer = self.selected_layer()
        if self._refreshing or not layer:
            return
        weight, style = self.font_weight.currentData()
        self.session.edit('选择真实字重', lambda doc: doc.layer(layer.id).style.update(weight=weight, font_style=style))

    def choose_text_color(self, field):
        layer = self.selected_layer()
        if not layer:
            return
        color = self.pick_color(QColor(layer.style.get(field, '#ffffff')), '颜色与透明度')
        if color is not None:
            self.change_style(field, color.name(QColor.HexArgb))

    def canvas_background(self):
        color = self.pick_color(QColor(self.session.document.background), '画布背景 · Alpha 0 为透明')
        if color is not None:
            self.session.edit('画布背景', lambda doc: setattr(doc, 'background', color.name(QColor.HexArgb)))

    def pick_color(self, initial, title):
        from ..design.color_picker import SimpleColorDialog
        from ..design.studio_theme import apply_secondary_surface_theme
        from .cover_widgets import SwatchRow
        dialog = SimpleColorDialog(initial, self, title=tr(title), common_colors=SwatchRow.COLORS)
        apply_secondary_surface_theme(dialog)
        if dialog.exec() == QDialog.Accepted and dialog.selected_color().isValid():
            return dialog.selected_color()
        return None

    def canvas_preset(self):
        size = self.preset.value()
        if size:
            self.canvas_width.setValue(size[0])
            self.canvas_height.setValue(size[1])
            self.resize_canvas()
        else:
            self.canvas_width.setFocus()
            self.canvas_width.selectAll()

    def resize_canvas(self):
        try:
            width, height = valid_size(self.canvas_width.value(), self.canvas_height.value())
            mode = self.fit_mode.value() or self.session.document.background_fit
            def update(doc):
                doc.width, doc.height, doc.background_fit = width, height, mode
                background = doc.layer(doc.background_id)
                if background and background.asset in doc.assets:
                    image = read_image_bytes(doc.assets[background.asset])
                    doc.fit_background((image.width(), image.height()))
            self.session.edit('画布尺寸与底图布局', update)
            self.view.fit_canvas()
        except (ValueError, OSError) as exc:
            self.error(str(exc))

    def reorder(self, direction):
        selected = self.session.selected.copy()
        def update(doc):
            indices = range(len(doc.layers)-2, -1, -1) if direction > 0 else range(1, len(doc.layers))
            for index in indices:
                other = index+direction
                if doc.layers[index].id in selected and doc.layers[other].id not in selected:
                    doc.layers[index], doc.layers[other] = doc.layers[other], doc.layers[index]
        self.session.edit('调整图层顺序', update)

    def add_text(self):
        selected = []
        self.session.edit('添加文字', lambda doc: selected.append(doc.add_text().id))
        self.session.selected = set(selected)
        self.view.sync_document()
        self.refresh()
        self.edit_text(selected[0])

    def edit_text(self, layer_id):
        layer = self.session.document.layer(layer_id)
        if layer and not layer.locked:
            self.session.selected = {layer_id}
            self.view.sync_document()
            self.refresh()
            self.text_edit.setFocus()
            self.text_edit.selectAll()
            self.scroll.ensureWidgetVisible(self.text_edit)

    def add_images(self, filenames=None, *, background=False, relink=None, new=False):
        if self.busy:
            return
        if not filenames:
            filenames, _ = QFileDialog.getOpenFileNames(self, '选择本地图片', self.directory('image_directory'), image_filter())
        if not filenames:
            return
        paths = list(filenames[:1] if background or relink or new else filenames)
        def work():
            return [(path, *load_image_file(path)) for path in paths]
        def finish(results):
            selected = []
            if new:
                image = results[0][2]
                document = CoverDocument(width=image.width(), height=image.height())
                document.add_image(results[0][1], Path(results[0][0]).name, (image.width(), image.height()), background=True)
                self.session.reset(document)
            else:
                def update(doc):
                    for path, data, image in results:
                        if relink:
                            layer = doc.layer(relink)
                            layer.asset = doc.add_asset(data, Path(path).name)
                            selected.append(layer.id)
                        else:
                            layer = doc.add_image(data, Path(path).name, (image.width(), image.height()), background=background)
                            selected.append(layer.id)
                self.session.edit('更换底图' if background else '重新定位素材' if relink else '添加图片', update)
                self.session.selected = set(selected)
                self.view.sync_document()
            self.settings.setValue('cover/image_directory', str(Path(paths[0]).parent))
            self.refresh()
            if new or background:
                self.view.fit_canvas()
        self.run_job('读取图片', work, finish)

    def relink_image(self):
        layer = self.selected_layer()
        if layer and not layer.locked:
            self.add_images(relink=layer.id)

    def undo(self):
        self.flush_text()
        self.session.undo.undo()
        self.refresh()

    def redo(self):
        self.flush_text()
        self.session.undo.redo()
        self.refresh()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Undo):
                self.undo()
                return True
            if event.matches(QKeySequence.Redo):
                self.redo()
                return True
            if watched is self.layers and self.layers.state() != QAbstractItemView.EditingState:
                if event.matches(QKeySequence.Delete):
                    self.session.delete_selected()
                    return True
                if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_D:
                    self.session.duplicate_selected()
                    return True
        return super().eventFilter(watched, event)

    def directory(self, key):
        directory = str(self.settings.value('cover/'+key, ''))
        if directory and not Path(directory).is_dir():
            bind_text(self.status, '上次目录已不可用；请在文件窗口选择新目录。')
            return str(Path.home()/'Pictures')
        return directory or str(Path.home()/'Pictures')

    def run_job(self, label, function, finished):
        if self.busy:
            return False
        self.busy = True
        self.toolbar.setEnabled(False)
        self.splitter.setEnabled(False)
        started = time.perf_counter()
        self.status.setText(label+'…')
        job = CoverJob(self)
        self.jobs.add(job)
        def cleanup():
            self.busy = False
            self.toolbar.setEnabled(True)
            self.splitter.setEnabled(True)
            self.jobs.discard(job)
            job.deleteLater()
        def success(value):
            cleanup()
            elapsed = time.perf_counter()-started
            self.metrics.append(dict(action=label, elapsed_seconds=elapsed))
            bind_text(self.status, '{label}成功 · {elapsed:.3f} 秒', label=label, elapsed=elapsed)
            try:
                finished(value)
            except Exception as exc:
                self.error(str(exc))
        def failure(message):
            cleanup()
            self._close_after_save = False
            self._after_save = None
            self.metrics.append(dict(action=label, elapsed_seconds=time.perf_counter()-started, error=message))
            self.error(label+'失败：'+message)
        job.finished.connect(success)
        job.failed.connect(failure)
        job.start(function)
        return True

    def error(self, message):
        bind_text(self.status, '{value0}；可更改路径或素材后重试。', value0=message)

    def maybe_discard(self, continuation=None):
        if self.busy:
            bind_text(self.status, '文件操作正在完成，请稍候。')
            return False
        if not self.session.dirty:
            return True
        choice = QMessageBox.warning(self, tr('封面有未保存修改'), tr('保存可编辑封面工程后再继续？'),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if choice == QMessageBox.Save:
            self._after_save = continuation
            self.save_dialog()
            return False
        return choice == QMessageBox.Discard

    def new_document(self):
        if not self.maybe_discard(self.new_document):
            return
        self.session.reset(CoverDocument())
        self.frame_document = None
        self.view.fit_canvas()

    def open_dialog(self):
        if not self.maybe_discard(self.open_dialog):
            return
        path, _ = QFileDialog.getOpenFileName(self, tr('打开可编辑封面'), self.directory('psd_directory'), '封面 (*.psd *.2bytecover)')
        if path:
            self.open_document(path)

    def open_document(self, path, draft=False):
        def finish(document):
            self.session.reset(document, '' if draft else path)
            self.settings.setValue('cover/project_directory', str(Path(path).parent))
            self.view.fit_canvas()
            if document.warnings:
                self.status.setText('\n'.join(document.warnings))
        from .cover_psd import load_local_psd
        return self.run_job('恢复草稿' if draft else '打开封面工程', lambda: load_local_psd(path) if str(path).lower().endswith('.psd') else CoverDocument.load(path), finish)

    def save_dialog(self, checked=False, *, save_as=False):
        path = self.session.filename
        if save_as or not path or not path.lower().endswith('.psd'):
            path, selected_filter = QFileDialog.getSaveFileName(self, tr('保存可编辑 PSD'),
                str(Path(self.directory('psd_directory'))/(Path(path).stem+'.psd' if path else '我的封面.psd')),
                'Photoshop 文档 (*.psd);;旧封面工程 (*.2bytecover)')
            if path and Path(path).suffix.lower() not in ('.psd','.2bytecover'):
                path += '.2bytecover' if '2bytecover' in selected_filter else '.psd'
        if not path:
            self._close_after_save = False
            self._after_save = None
            return False
        return self.save_document(path)

    def save_document(self, path):
        self.flush_text()
        snapshot = self.session.document.snapshot()
        def finish(_):
            self.session.filename = str(path)
            self.session.saved_signature = snapshot.signature()
            if not self.session.dirty:
                self.session.undo.setClean()
            self.settings.setValue('cover/'+('psd_directory' if str(path).lower().endswith('.psd') else 'project_directory'), str(Path(path).parent))
            self.settings.setValue('cover/last_project', str(path))
            self.refresh()
            if self._close_after_save and not self.session.dirty:
                self._close_after_save = False
                self.close()
            elif self._after_save and not self.session.dirty:
                continuation, self._after_save = self._after_save, None
                continuation()
        from .cover_psd import save_psd
        return self.run_job('保存 PSD' if str(path).lower().endswith('.psd') else '保存封面工程',
                            lambda: save_psd(snapshot,path) if str(path).lower().endswith('.psd') else snapshot.save(path), finish)

    def save_local_draft(self):
        if self.busy:
            self._autosave.start();return
        if not self.session.dirty:return
        snapshot=self.session.document.snapshot()
        def work():
            import tempfile
            with tempfile.TemporaryDirectory(prefix='cover-draft-') as folder:
                path=Path(folder)/'draft.2bytecover';snapshot.save(path)
                return self.library.save_draft(path.read_bytes(),kind='2bytecover',document=snapshot.id,filename=self.session.filename)
        # Draft writes never set saved_signature or claim a manual save.
        job=CoverJob(self);self.jobs.add(job)
        def finish(_):self.jobs.discard(job);job.deleteLater()
        job.finished.connect(finish);job.failed.connect(finish);job.start(work)

    def choose_template(self):
        self.flush_text()
        if self.busy:
            return
        from .cover_templates_ui import TemplatePicker
        picker = TemplatePicker(self.library, self.settings, self, local=True, has_frame=self.frame_document is not None,
                                frame=self.frame_document)
        if picker.exec() != QDialog.Accepted:
            return
        if picker.selected.get('blank'):
            before=self.session.document.snapshot()
            self.session.document=CoverDocument(id=before.id)
            self.session.commit(before,'应用空白模板')
            self.view.fit_canvas()
        else:
            self.apply_template(picker.selected, replace=picker.replace.isChecked(), texts=picker.selected_texts)

    def apply_template(self, entry, *, replace=False, texts=None):
        """Open a copy of ``entry``; ``texts`` maps text-layer ids to titles typed in the picker."""
        frame = self.frame_document.snapshot() if replace and self.frame_document is not None else None
        texts = dict(texts or {})
        def load():
            document = self.library.load_copy(entry)
            if frame is not None:
                self.library.replace_frame(document, frame)
            for key, text in texts.items():
                layer = document.layer(key)
                if layer is not None and layer.kind == 'text':
                    layer.text = text
            return document
        def finish(document):
            # Template application is one reversible document transaction.
            before = self.session.document.snapshot()
            document.id = before.id
            self.session.document = document
            self.session.commit(before, '应用模板和底图')
            self.view.fit_canvas()
            self.library.mark_used(entry)
            bind_text(self.status, '已打开模板副本：{value0}；保存封面不会覆盖模板。', value0=entry['name'])
            if frame is not None:self._show_frame_obstructions()
        return self.run_job('打开模板', load, finish)

    def use_frozen_frame(self, document):
        self.flush_text()
        self.session.edit('更新当前视频帧', lambda current:self.library.replace_frame(current,document))
        self.frame_document=document.snapshot()
        bind_text(self.status, '底图已更新至 {value0:.3f} 秒；标题与贴图保留，可撤销。', value0=document.source.get('milliseconds', 0) / 1000)
        self._show_frame_obstructions()

    def _show_frame_obstructions(self):
        names=self.library.frame_obstructions(self.session.document)
        if names:
            bind_text(self.status, '当前帧位于底层，但被不透明设计图层遮挡：{value0}。这些设计层已保留；在右侧图层列表取消其可见勾选即可看到当前帧。', value0='、'.join(names))

    def save_template_dialog(self):
        if self.busy:
            return
        self.flush_text()
        dialog,layout=self._small_dialog('保存为模板',(420,180))
        hint=QLabel();hint.setObjectName('coverHint');bind_text(hint, '模板名称（保留标题、贴图和位置）');layout.addWidget(hint)
        name=QLineEdit(Path(self.session.filename).stem if self.session.filename else '我的封面模板')
        layout.addWidget(name)
        include=QCheckBox('同时把本次视频截图存入模板底图')
        include.setVisible(bool(self.session.document.source.get('project_id')))
        layout.addWidget(include)
        self._dialog_buttons(dialog,layout,'保存')
        self.fit_small(dialog)
        if dialog.exec()==QDialog.Accepted and name.text().strip():
            self.save_template(name.text(),include_frame=include.isChecked())

    def _small_dialog(self, title, size):
        """A small question window in the app's rounded shell (2026-11-27: no Windows frame).

        User (2026-11-27, round 2): the first version wasted space and its title was in 猫啃. The
        title is 思源黑体 Heavy now and the window is only as tall as what it shows (``fit_small``).
        """
        from ..app.rounded_dialog import RoundedDialogShell
        from ..design.cover_qss import build_cover_common_qss
        from ..design.typography import TITLE_FONT_STACK
        dialog = QDialog(self)
        dialog.setObjectName('coverSmallDialog')
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 4, 0)
        layout.setSpacing(10)
        dialog.shell = RoundedDialogShell(dialog, content, title=tr(title), size=size, margins=(22, 14, 16, 16))
        dialog.shell.title_label.setStyleSheet(f'font-family: {TITLE_FONT_STACK}; font-size: 18px; font-weight: 800; '
                                               f'color: {self.theme.text}; background: transparent;')
        dialog.setStyleSheet(build_cover_common_qss('QDialog#coverSmallDialog', self.theme))
        return dialog, layout

    @staticmethod
    def fit_small(dialog):
        """Shrink a small dialog to its content's height (keeps its width)."""
        dialog.setMinimumHeight(0)
        dialog.layout().activate()
        dialog.resize(dialog.width(), dialog.sizeHint().height())

    @staticmethod
    def _dialog_buttons(dialog, layout, accept_text):
        from .cover_widgets import text_button
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = text_button('取消', kind='ghost')
        cancel.clicked.connect(dialog.reject)
        accept = text_button(accept_text, kind='primary')
        accept.setDefault(True)
        accept.clicked.connect(dialog.accept)
        row.addWidget(cancel)
        row.addWidget(accept)
        layout.addLayout(row)

    def save_template(self, name, *, include_frame=False):
        self.flush_text()
        snapshot = self.session.document.snapshot()
        if not include_frame and snapshot.source.get('project_id') and snapshot.source.get('captured_at'):
            snapshot.layers=[layer for layer in snapshot.layers if layer.id!=snapshot.background_id]
            snapshot.background_id='';snapshot.source={}
        def work():
            from PySide6.QtCore import QBuffer, QIODevice
            from .cover_render import CoverRenderer
            preview = CoverRenderer().render(snapshot).scaled(448, 252, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            if not preview.save(buffer, 'PNG'):
                raise ValueError('无法生成模板缩略图')
            return self.library.save_native(name, snapshot, bytes(buffer.data()))
        def finish(entry):
            bind_text(self.status, '模板已保存：{value0}；下次可从“选择模板”打开。', value0=entry['name'])
        return self.run_job('保存模板', work, finish)

    def export_dialog(self):
        if self.busy:
            return
        from .cover_widgets import Segmented, SliderRow, Swatch, form_row
        dialog, layout = self._small_dialog('导出封面图片', (430, 200))
        format_box = Segmented([('PNG · 保留透明区域', 'png'), ('JPEG · 合成背景色', 'jpg')])
        format_box.set_value(str(self.settings.value('cover/export_format', 'png')) if str(self.settings.value('cover/export_format', 'png')) in ('png', 'jpg') else 'png')
        layout.addWidget(format_box)
        quality = SliderRow(1, 100, suffix=' %')
        quality.set_value(int(self.settings.value('cover/jpeg_quality', 95)))
        quality_row = form_row('JPEG 质量', quality, label_width=64)
        layout.addWidget(quality_row)
        color = QColor(self.session.document.jpeg_background)
        color_button = Swatch(color.name())
        color_button.ring, color_button.edge = QColor(self.theme.accent), QColor(self.theme.border_strong)
        def choose():
            nonlocal color
            value = self.pick_color(color, 'JPEG 背景色')
            if value is not None:
                color = value
                color_button.color = color.name()
                color_button.update()
        color_button.clicked.connect(choose)
        color_host = QWidget()
        color_row = QHBoxLayout(color_host)
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.addWidget(color_button)
        color_row.addStretch(1)
        background_row = form_row('JPEG 背景', color_host, label_width=64)
        layout.addWidget(background_row)
        def follow(value):
            quality_row.setVisible(value == 'jpg')
            background_row.setVisible(value == 'jpg')
            self.fit_small(dialog)
        format_box.changed.connect(follow)
        self._dialog_buttons(dialog, layout, '导出')
        follow(format_box.value())
        if dialog.exec() != QDialog.Accepted:
            return
        self.settings.setValue('cover/export_format', format_box.value())
        suffix = '.jpg' if format_box.value() == 'jpg' else '.png'
        path, _ = QFileDialog.getSaveFileName(self, tr('导出封面图片'),
            str(Path(self.directory('export_directory'))/('我的封面'+suffix)), 'JPEG (*.jpg *.jpeg)' if suffix == '.jpg' else 'PNG (*.png)')
        if not path:
            return
        if Path(path).suffix.lower() not in ('.png', '.jpg', '.jpeg'):
            path += suffix
        self.session.edit('JPEG 背景色', lambda doc: setattr(doc, 'jpeg_background', color.name()))
        self.export_document(path, int(quality.value()))

    def export_document(self, path, quality=95):
        self.flush_text()
        snapshot = self.session.document.snapshot()
        def finish(receipt):
            self.last_export = receipt['path']
            self.settings.setValue('cover/export_directory', str(Path(path).parent))
            self.settings.setValue('cover/jpeg_quality', quality)
            bind_text(self.status, '已导出 {value0} × {value1} · {value2}', value0=receipt['width'], value1=receipt['height'], value2=Path(path).name)
            self.refresh()
        return self.run_job('导出图片', lambda: export_image(snapshot, path, quality=quality), finish)

    def open_result(self, folder=False):
        if self.last_export:
            path = Path(self.last_export)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if folder else path)))

    def reject(self):
        self.close()

    def closeEvent(self, event):
        self.flush_text()
        if self.busy:
            bind_text(self.status, '文件操作正在完成，请稍候再关闭。')
            event.ignore()
            return
        if self.session.dirty:
            choice = QMessageBox.warning(self, tr('封面有未保存修改'), tr('保存可编辑封面工程后关闭？'),
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if choice == QMessageBox.Cancel:
                event.ignore()
                return
            if choice == QMessageBox.Save:
                self._close_after_save = True
                self.save_dialog()
                event.ignore()
                return
        self.settings.setValue('cover/geometry', self.saveGeometry())
        self.settings.sync()
        self._autosave.stop()
        event.accept()
