"""Offline cover workbench with an independent document and undo context."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading
import time

from PySide6.QtCore import QEvent, QObject, QRect, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QColorDialog,
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
    QToolBar, QToolButton, QMenu, QGridLayout, QStyledItemDelegate, QVBoxLayout, QWidget, QSizePolicy)

from .cover_canvas import CoverSession, CoverView
from .cover_document import CoverDocument, valid_size
from .cover_render import export_image, image_filter, load_image_file, read_image_bytes, text_font

from .i18n import bind_text

from .i18n import tr


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
    def __init__(self,editor):
        super().__init__(editor.layers);self.editor=editor
        import qtawesome as qta
        self.icons=[qta.icon('fa5s.lock-open',color='#849a8c'),qta.icon('fa5s.lock',color='#dfc482')]

    def paint(self,painter,option,index):
        super().paint(painter,option,index)
        layer=self.editor.session.document.layer(index.data(Qt.UserRole))
        if layer:self.icons[int(layer.locked)].paint(painter,QRect(option.rect.right()-23,option.rect.center().y()-7,14,14))

    def editorEvent(self,event,model,option,index):
        if event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton and event.position().x()>option.rect.right()-28:
            key=index.data(Qt.UserRole)
            layer=self.editor.session.document.layer(key)
            if layer:self.editor.session.edit('图层锁定',lambda doc:setattr(doc.layer(key),'locked',not layer.locked))
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        self.toolbar = QToolBar()
        self.toolbar.setMovable(False)
        layout.addWidget(self.toolbar)
        self.cover_actions = {}
        def action(key, label, slot, shortcut=None):
            item = QAction(label, self)
            if shortcut:
                item.setShortcut(shortcut)
            item.triggered.connect(slot)
            self.toolbar.addAction(item)
            self.cover_actions[key] = item
            return item
        action('new', '新建', self.new_document, QKeySequence.New)
        action('open', '打开', self.open_dialog, QKeySequence.Open)
        self.toolbar.addSeparator()
        action('image', '添加图片', lambda: self.add_images())
        action('text', '添加文字', self.add_text)
        self.toolbar.addSeparator()
        action('undo', '撤销', self.undo, QKeySequence.Undo)
        action('redo', '重做', self.redo, QKeySequence.Redo)
        self.toolbar.addSeparator()
        action('save', '保存 PSD', self.save_dialog, QKeySequence.Save)
        action('save_as', '另存为', lambda: self.save_dialog(save_as=True), QKeySequence.SaveAs)
        action('export', '导出图片', self.export_dialog, 'Ctrl+E')
        action('templates', '选择模板', self.choose_template)
        action('save_template', '保存为模板', self.save_template_dialog)
        draft = self.library.draft()
        if draft and draft.get('kind') == '2bytecover':
            action('restore', '恢复草稿', lambda:self.open_document(self.library.root/draft['file'],draft=True))
        file_menu = QMenu(self)
        for key in ('new', 'open', 'save_as'):
            self.toolbar.removeAction(self.cover_actions[key])
            file_menu.addAction(self.cover_actions[key])
        file_button = QToolButton()
        bind_text(file_button, '文件')
        file_button.setMenu(file_menu)
        file_button.setPopupMode(QToolButton.InstantPopup)
        self.toolbar.insertWidget(self.toolbar.actions()[0], file_button)
        action('lock', '锁定 / 解锁', self.toggle_lock)
        action('sidebar', '图层 / 属性', lambda: self.sidebar.setVisible(not self.sidebar.isVisible()))
        toolrow = QHBoxLayout()
        self.tools = QToolBar()
        self.tools.setOrientation(Qt.Vertical)
        import qtawesome as qta
        for key, icon in [('image', 'fa5s.image'), ('text', 'fa5s.font'), ('undo', 'fa5s.undo'), ('redo', 'fa5s.redo')]:
            self.toolbar.removeAction(self.cover_actions[key])
            self.cover_actions[key].setIcon(qta.icon(icon, color='#b9c6c0'))
            self.cover_actions[key].setToolTip(self.cover_actions[key].text())
            self.tools.addAction(self.cover_actions[key])
        self.tools.setToolButtonStyle(Qt.ToolButtonIconOnly)
        toolrow.addWidget(self.tools)
        self.splitter = QSplitter(Qt.Horizontal)
        toolrow.addWidget(self.splitter, 1)
        layout.addLayout(toolrow, 1)
        canvas_host = QWidget()
        center = QVBoxLayout(canvas_host)
        center.setContentsMargins(0, 0, 0, 0)
        self.view = CoverView(self.session)
        center.addWidget(self.view, 1)
        zoom_row = QHBoxLayout()
        fit = QPushButton('适应窗口')
        fit.clicked.connect(self.view.fit_canvas)
        zoom_row.addWidget(fit)
        actual = QPushButton('100%')
        actual.clicked.connect(lambda: self.view.set_zoom(1))
        zoom_row.addWidget(actual)
        self.zoom_label = QLabel()
        self.view.zoom_changed.connect(lambda value: bind_text(self.zoom_label, '查看 {value0:.0f}%', value0=value * 100))
        zoom_row.addWidget(self.zoom_label)
        help_label = QLabel('等比开关控制缩放 · 滚轮查看')
        help_label.setWordWrap(True)
        zoom_row.addWidget(help_label, 1, Qt.AlignRight)
        center.addLayout(zoom_row)
        self.splitter.addWidget(canvas_host)
        sidebar = self.sidebar = QWidget()
        sidebar.setMinimumWidth(248)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(6, 0, 0, 0)
        side.setSpacing(4)
        side.addWidget(QLabel('图层 · 拖动排序'))
        self.layers = QListWidget()
        self.layers.setItemDelegate(CoverLayerDelegate(self))
        self.layers.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.layers.setEditTriggers(QAbstractItemView.EditKeyPressed | QAbstractItemView.DoubleClicked)
        self.layers.setMinimumHeight(82)
        self.layers.setMaximumHeight(140)
        self.layers.setIconSize(QSize(40, 28))
        self.layers.setDragDropMode(QAbstractItemView.InternalMove)
        self.layers.setDefaultDropAction(Qt.MoveAction)
        self.layers.model().rowsMoved.connect(lambda: QTimer.singleShot(0, self.reorder_from_list))
        self.layers.itemSelectionChanged.connect(self.layer_selection)
        self.layers.itemChanged.connect(self.layer_item_changed)
        self.layers.installEventFilter(self)
        side.addWidget(self.layers)
        layer_buttons = QHBoxLayout()
        for text, slot in [('锁定 / 解锁', self.toggle_lock), ('复制', self.session.duplicate_selected), ('删除', self.session.delete_selected)]:
            button = QPushButton(text)
            button.clicked.connect(slot)
            layer_buttons.addWidget(button)
        side.addLayout(layer_buttons)
        self.property_title = QLabel('画布')
        side.addWidget(self.property_title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        property_host = QWidget()
        properties = QVBoxLayout(property_host)
        properties.setContentsMargins(0, 2, 8, 6)
        self.common = QWidget()
        common_form = QFormLayout(self.common)
        common_form.setContentsMargins(0, 0, 0, 6)
        common_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(lambda: self.change_layer('name', self.name_edit.text(), '重命名'))
        common_form.addRow('名称', self.name_edit)
        self.geometry = {}
        geometry_host = QWidget()
        geometry_grid = QGridLayout(geometry_host)
        geometry_grid.setContentsMargins(0, 0, 0, 0)
        geometry_grid.setSpacing(4)
        geometry_grid.setColumnStretch(1, 1)
        geometry_grid.setColumnStretch(3, 1)
        for index, (key, label) in enumerate([('x', 'X'), ('y', 'Y'), ('width', 'W'), ('height', 'H')]):
            box = self.number(-32768 if key in ('x', 'y') else 8, 32768, ' px')
            box.setMinimumWidth(72)
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            box.editingFinished.connect(lambda field=key, widget=box: self.change_geometry(field, widget.value()))
            self.geometry[key] = box
            geometry_grid.addWidget(QLabel(label), index//2, (index%2)*2)
            geometry_grid.addWidget(box, index//2, (index%2)*2+1)
        common_form.addRow(geometry_host)
        self.aspect = QCheckBox('等比缩放')
        bind_text(self.aspect, '勾选时：拖动角点、边柄或修改宽高都保持比例。取消后可单独拉宽或拉高。', property='toolTip')
        self.aspect.toggled.connect(lambda checked: self.change_layer('keep_aspect', checked, '保持比例'))
        common_form.addRow('', self.aspect)
        self.opacity = self.number(0, 100, ' %')
        self.opacity.editingFinished.connect(lambda: self.change_layer('opacity', self.opacity.value()/100, '不透明度'))
        common_form.addRow('不透明度', self.opacity)
        self.locked = QCheckBox('锁定图层')
        self.locked.toggled.connect(lambda checked: self.change_layer('locked', checked, '锁定图层'))
        common_form.addRow('', self.locked)
        properties.addWidget(self.common)
        self.pages = CoverPropertyStack()
        properties.addWidget(self.pages)
        properties.addStretch()
        self.canvas_page = QWidget()
        canvas_form = QFormLayout(self.canvas_page)
        canvas_form.setContentsMargins(0, 0, 0, 0)
        self.preset = QComboBox()
        for title, size in [('自定义', None), ('1920 × 1080', (1920, 1080)), ('2560 × 1440', (2560, 1440)),
                             ('1280 × 720', (1280, 720)), ('1600 × 900', (1600, 900)), ('1080 × 1080', (1080, 1080))]:
            self.preset.addItem(title, size)
        self.preset.activated.connect(self.canvas_preset)
        canvas_form.addRow('画布尺寸', self.preset)
        self.canvas_width = self.number(16, 16384, ' px')
        self.canvas_height = self.number(16, 16384, ' px')
        canvas_form.addRow('宽度', self.canvas_width)
        canvas_form.addRow('高度', self.canvas_height)
        self.fit_mode = QComboBox()
        for title, key in [('适应 · 完整显示底图', 'fit'), ('填充 · 居中裁切底图', 'fill'), ('原尺寸 · 居中不缩放', 'original')]:
            self.fit_mode.addItem(title, key)
        canvas_form.addRow('底图布局', self.fit_mode)
        resize = QPushButton('应用画布尺寸与底图布局')
        resize.clicked.connect(self.resize_canvas)
        canvas_form.addRow(resize)
        self.background_button = QPushButton('设置画布背景色 / 透明度')
        self.background_button.clicked.connect(self.canvas_background)
        canvas_form.addRow(self.background_button)
        replace = QPushButton('更换底图…（保留标题和贴图）')
        replace.clicked.connect(lambda: self.add_images(background=True))
        canvas_form.addRow(replace)
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        canvas_form.addRow(self.source_label)
        self.pages.addWidget(self.canvas_page)
        self.image_page = QWidget()
        image_layout = QVBoxLayout(self.image_page)
        image_layout.setAlignment(Qt.AlignTop)
        image_layout.setSpacing(4)
        image_layout.setContentsMargins(0, 0, 0, 0)
        relink = QPushButton('替换 / 重新定位素材…')
        relink.clicked.connect(self.relink_image)
        image_layout.addWidget(relink)
        image_tools = QHBoxLayout()
        for title, mode in [('适应', 'fit'), ('填满', 'fill'), ('恢复', 'original')]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, value=mode: self.fit_selected(value))
            image_tools.addWidget(button)
        image_layout.addLayout(image_tools)
        center_layer = QPushButton('移回画布中央')
        center_layer.clicked.connect(lambda: self.fit_selected('center'))
        image_layout.addWidget(center_layer)
        self.pages.addWidget(self.image_page)
        self.text_page = QWidget()
        text_form = QFormLayout(self.text_page)
        text_form.setContentsMargins(0, 0, 0, 0)
        self.text_edit = QPlainTextEdit()
        bind_text(self.text_edit, '输入中文标题；Enter 换行', property='placeholderText')
        self.text_edit.setMinimumHeight(56)
        self.text_edit.setMaximumHeight(76)
        self.text_edit.setUndoRedoEnabled(False)
        self.text_edit.installEventFilter(self)
        self._text_commit_timer = QTimer(self)
        self._text_commit_timer.setSingleShot(True)
        self._text_commit_timer.setInterval(0)
        self._text_commit_timer.timeout.connect(self.text_changed)
        self.text_edit.textChanged.connect(self._queue_text_change)
        text_form.addRow(self.text_edit)
        from .cover_font_picker import FontFamilyCombo
        from .font_metadata import local_faces
        self.font_faces = local_faces()
        self.font_family = FontFamilyCombo(self.font_faces)
        self.font_family.activated.connect(self.choose_font)
        self.font_family.lineEdit().editingFinished.connect(self.choose_font)
        self.font_family.completer().activated[str].connect(self.choose_font_completion)
        text_form.addRow('字体', self.font_family)
        self.font_weight = QComboBox()
        self.font_weight.activated.connect(self.choose_weight)
        text_form.addRow('真实字重', self.font_weight)
        self.font_warning = QLabel()
        self.font_warning.setWordWrap(True)
        text_form.addRow(self.font_warning)
        self.text_numbers = {}
        for key, label, low, high in [('size', '字号', 8, 2048), ('stroke', '描边宽度', 0, 100),
                                     ('shadow_blur', '阴影模糊', 0, 100), ('shadow_x', '阴影横移', -200, 200), ('shadow_y', '阴影纵移', -200, 200)]:
            box = self.number(low, high, ' px')
            box.editingFinished.connect(lambda field=key, widget=box: self.change_style(field, widget.value()))
            self.text_numbers[key] = box
            text_form.addRow(label, box)
        self.color_buttons = {}
        for key, title in [('color', '文字颜色'), ('stroke_color', '描边颜色'), ('shadow_color', '阴影颜色')]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, field=key: self.choose_text_color(field))
            self.color_buttons[key] = button
            text_form.addRow(button)
        self.shadow_toggle = QCheckBox('显示基础阴影')
        self.shadow_toggle.toggled.connect(lambda checked: self.change_style('shadow', checked))
        text_form.addRow(self.shadow_toggle)
        self.alignment = QComboBox()
        for title, key in [('左对齐', 'left'), ('居中', 'center'), ('右对齐', 'right')]:
            self.alignment.addItem(title, key)
        self.alignment.activated.connect(lambda: self.change_style('alignment', self.alignment.currentData()))
        text_form.addRow('多行对齐', self.alignment)
        self.pages.addWidget(self.text_page)
        self.multi_page = QLabel('已选中多个图层。\n在画布中一起拖动，或复制 / 删除。\n锁定的图层不会移动或删除。')
        self.multi_page.setWordWrap(True)
        self.pages.addWidget(self.multi_page)
        self.scroll.setWidget(property_host)
        side.addWidget(self.scroll, 1)
        self.splitter.addWidget(sidebar)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([948, 312])
        bottom = QHBoxLayout()
        self.status = QLabel('封面编辑只影响独立封面工程。')
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.open_image = QPushButton('打开图片')
        self.open_image.clicked.connect(lambda: self.open_result())
        bottom.addWidget(self.open_image)
        self.open_folder = QPushButton('打开文件夹')
        self.open_folder.clicked.connect(lambda: self.open_result(folder=True))
        bottom.addWidget(self.open_folder)
        layout.addLayout(bottom)
        self.refresh_theme_palette()

    def refresh_theme_palette(self):
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        theme = theme_definition(theme_key())
        sheet = '''QDialog#coverEditor, QWidget { background:#202623; color:#d9e1dd; font-size:12px; }
            QToolBar { border:0; spacing:3px; } QToolButton, QPushButton { min-height:22px; padding:2px 6px;
                background:#303a34; border:1px solid #425048; border-radius:3px; }
            QToolButton:hover, QPushButton:hover { background:#40594b; }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { min-height:22px; padding:1px; background:#171d19; border:1px solid #47554c; }
            QPlainTextEdit, QListWidget { background:#171d19; border:1px solid #3c4941; }
            QListWidget::item { color:#d9e1dd; padding-right:26px; }
            QListWidget::item:selected { background:#355341; color:#ffffff; } QLabel { border:0; padding:0; }
            QGraphicsView#coverCanvas { background:#141917; border:1px solid #46544b; border-radius:0; }
            QScrollArea { border:0; } QSplitter::handle { background:#46544b; width:4px; }'''
        for source, target in {'#202623':theme.app_background, '#d9e1dd':theme.text,
                '#303a34':theme.surface, '#425048':theme.border, '#40594b':theme.accent_soft,
                '#171d19':theme.input_surface, '#47554c':theme.border_strong, '#3c4941':theme.border,
                '#355341':theme.selected, '#ffffff':theme.text, '#141917':theme.media,
                '#46544b':theme.border_strong}.items():
            sheet = sheet.replace(source, target)
        self.setStyleSheet(sheet)

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
        self.cover_actions['undo'].setEnabled(self.session.undo.canUndo())
        self.cover_actions['redo'].setEnabled(self.session.undo.canRedo())
        self.open_image.setEnabled(bool(self.last_export))
        self.open_folder.setEnabled(bool(self.last_export))
        self.layers.blockSignals(True)
        self.layers.clear()
        for layer in reversed(doc.layers):
            item = QListWidgetItem(layer.name)
            try:
                preview = self.view.renderer.layer_image(doc, layer)
                item.setIcon(QIcon(QPixmap.fromImage(preview.scaled(80, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))))
            except (ValueError, OSError):
                pass
            item.setSizeHint(QSize(120, 34))
            item.setData(Qt.UserRole, layer.id)
            item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
            bind_text(item, ('已锁定 · ' if layer.locked else '') + ('可编辑文字' if layer.kind == 'text' else '图片图层'), property='toolTip')
            self.layers.addItem(item)
            item.setSelected(layer.id in self.session.selected)
        self.layers.blockSignals(False)
        layer = self.selected_layer()
        self.cover_actions['lock'].setEnabled(bool(self.session.selected))
        (bind_text(self.cover_actions['lock'], '解锁图层') if layer and layer.locked else bind_text(self.cover_actions['lock'], '锁定图层'))
        self.common.setVisible(layer is not None)
        if layer is None:
            (bind_text(self.property_title, '多选图层') if self.session.selected else bind_text(self.property_title, '画布 · {value0} × {value1} px', value0=doc.width, value1=doc.height))
            self.pages.setCurrentIndex(3 if self.session.selected else 0)
            self.canvas_width.setValue(doc.width)
            self.canvas_height.setValue(doc.height)
            self.fit_mode.setCurrentIndex(max(0, self.fit_mode.findData(doc.background_fit)))
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
                for key, button in self.color_buttons.items():
                    value = layer.style.get(key, '#ffffff')
                    bind_text(button, {'color': '文字', 'stroke_color': '描边', 'shadow_color': '阴影'}[key] + '  ' + value)
                self.shadow_toggle.setChecked(bool(layer.style.get('shadow')))
                self.alignment.setCurrentIndex(max(0, self.alignment.findData(layer.style.get('alignment'))))
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
            from .i18n_widgets import add_combo_item
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

    def change_layer(self, field, value, label):
        layer = self.selected_layer()
        if self._refreshing or layer is None or (layer.locked and field not in ('locked', 'name')):
            return
        key = layer.id
        self.session.edit(label, lambda doc: setattr(doc.layer(key), field, value))

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

    def change_style(self, field, value):
        layer = self.selected_layer()
        if self._refreshing or layer is None or layer.kind != 'text' or layer.locked:
            return
        self.session.edit('文字样式', lambda doc: doc.layer(layer.id).style.update({field: value}))

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
        color = QColorDialog.getColor(QColor(layer.style.get(field, '#ffffff')), self, '颜色与透明度', QColorDialog.ShowAlphaChannel)
        if color.isValid():
            self.change_style(field, color.name(QColor.HexArgb))

    def canvas_background(self):
        color = QColorDialog.getColor(QColor(self.session.document.background), self, '画布背景 · Alpha 0 为透明', QColorDialog.ShowAlphaChannel)
        if color.isValid():
            self.session.edit('画布背景', lambda doc: setattr(doc, 'background', color.name(QColor.HexArgb)))

    def canvas_preset(self):
        size = self.preset.currentData()
        if size:
            self.canvas_width.setValue(size[0])
            self.canvas_height.setValue(size[1])

    def resize_canvas(self):
        try:
            width, height = valid_size(self.canvas_width.value(), self.canvas_height.value())
            mode = self.fit_mode.currentData()
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
        picker = TemplatePicker(self.library, self.settings, self, local=True, has_frame=self.frame_document is not None)
        if picker.exec() != QDialog.Accepted:
            return
        if picker.selected.get('blank'):
            before=self.session.document.snapshot()
            self.session.document=CoverDocument(id=before.id)
            self.session.commit(before,'应用空白模板')
            self.view.fit_canvas()
        else:
            self.apply_template(picker.selected, replace=picker.replace.isChecked())

    def apply_template(self, entry, *, replace=False):
        frame = self.frame_document.snapshot() if replace and self.frame_document is not None else None
        def load():
            document = self.library.load_copy(entry)
            if frame is not None:
                self.library.replace_frame(document, frame)
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
        dialog=QDialog(self);bind_text(dialog, '保存为模板', property='windowTitle');layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel('模板名称（保留标题、贴图和位置）'))
        name=QLineEdit(Path(self.session.filename).stem if self.session.filename else '我的封面模板')
        layout.addWidget(name)
        include=QCheckBox('同时把本次视频截图存入模板底图')
        include.setVisible(bool(self.session.document.source.get('project_id')))
        layout.addWidget(include)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()==QDialog.Accepted and name.text().strip():
            self.save_template(name.text(),include_frame=include.isChecked())

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
        dialog = QDialog(self)
        bind_text(dialog, '导出封面图片', property='windowTitle')
        form = QFormLayout(dialog)
        format_box = QComboBox()
        format_box.addItems(['PNG · 保留透明区域', 'JPEG · 合成背景色'])
        form.addRow('格式', format_box)
        quality = QSpinBox()
        quality.setRange(1, 100)
        quality.setValue(int(self.settings.value('cover/jpeg_quality', 95)))
        quality.setSuffix(' %')
        form.addRow('JPEG 质量', quality)
        color = QColor(self.session.document.jpeg_background)
        color_button = QPushButton(color.name())
        def choose():
            nonlocal color
            value = QColorDialog.getColor(color, dialog, 'JPEG 背景色')
            if value.isValid():
                color = value
                color_button.setText(color.name())
        color_button.clicked.connect(choose)
        form.addRow('JPEG 背景', color_button)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        suffix = '.jpg' if format_box.currentIndex() else '.png'
        path, _ = QFileDialog.getSaveFileName(self, tr('导出封面图片'),
            str(Path(self.directory('export_directory'))/('我的封面'+suffix)), 'JPEG (*.jpg *.jpeg)' if suffix == '.jpg' else 'PNG (*.png)')
        if not path:
            return
        if Path(path).suffix.lower() not in ('.png', '.jpg', '.jpeg'):
            path += suffix
        self.session.edit('JPEG 背景色', lambda doc: setattr(doc, 'jpeg_background', color.name()))
        self.export_document(path, quality.value())

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
