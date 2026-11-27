"""Cover template picker: a list on the left, the chosen template large on the right (2026-11-27).

User (2026-11-27): the old picker (a grid of small icons, a row of four equal buttons, a check box,
the Windows frame) was neither practical nor good-looking. From three drafts they picked
「B 大圖預覽」 (``tmp/cover-ui-drafts-20261127``):

* the window is the app's own rounded frame (``CandyChrome``);
* left: search, 最近使用 / 收藏 / 全部 chips, 「空白新建」, then one row per template;
* right: the template's name with 收藏 / 重新命名 / 複製 / 刪除 icons, a large preview that can
  switch between 模板原圖 and 換上當前畫面, and the template's main text layers as fields, so the
  titles are typed before the editor opens; chips say which layers stay and that the base image
  is replaced;
* renaming happens in place and deleting asks inside the preview, not in system dialogs.

Metadata stays independent of editor windows. ``selected`` is the chosen entry (or
``{'blank': True}``) and ``selected_texts`` maps text-layer ids to what was typed.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..app.candy_chrome import CandyChrome
from ..i18n import bind_text, tr
from .cover_widgets import PillSwitch, Segmented, icon_button, text_button

ROW_HEIGHT = 66
THUMB = QSize(92, 52)
PREVIEW = QSize(560, 232)


def _theme():
    from ..design.theme_manager import theme_definition, theme_key
    return theme_definition(theme_key())


def rounded_pixmap(image: QImage, size: QSize, radius: float, ratio: float, fill: QColor) -> QPixmap:
    """``image`` contained in ``size`` on a rounded ``fill`` plate (letterboxed, never cropped)."""
    pixmap = QPixmap(round(size.width() * ratio), round(size.height() * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
    painter.setClipPath(path)
    painter.fillRect(QRectF(0, 0, size.width(), size.height()), fill)
    if not image.isNull():
        scaled = image.scaled(round(size.width() * ratio), round(size.height() * ratio),
                              Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        w, h = scaled.width() / ratio, scaled.height() / ratio
        painter.drawImage(QRectF((size.width() - w) / 2, (size.height() - h) / 2, w, h), scaled)
    painter.end()
    return pixmap


def shape_name(width, height) -> str:
    return '横版' if width > height else '竖版' if width < height else '方形'


class TemplateRowDelegate(QStyledItemDelegate):
    """One template row: rounded thumbnail, name, size, a gold star when it is a favourite."""

    def __init__(self, picker):
        super().__init__(picker.cards)
        self.picker = picker

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, painter, option, index):
        t = self.picker.theme
        from ..design.ui_theme import blend_hex
        entry = index.data(Qt.ItemDataRole.UserRole)
        rect = QRectF(option.rect).adjusted(1, 2, -1, -2)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            painter.setBrush(QColor(t.surface_elevated))
            painter.setPen(QPen(QColor(t.accent), 1.2) if selected else Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 13, 13)
        pixmap = self.picker.thumbnail(entry)
        top = rect.top() + (rect.height() - THUMB.height()) / 2
        painter.drawPixmap(int(rect.left() + 6), int(top), pixmap)
        text_left = rect.left() + 6 + THUMB.width() + 10
        star = 22 if entry.get('favorite') else 0
        width = rect.right() - text_left - 6 - star
        from ..design.typography import heavy_font
        name_font = heavy_font(QFont(option.font))
        name_font.setPixelSize(13)
        painter.setFont(name_font)
        painter.setPen(QColor(t.text))
        name = painter.fontMetrics().elidedText(entry.get('name', ''), Qt.TextElideMode.ElideRight, int(width))
        painter.drawText(QRectF(text_left, rect.top() + 12, width, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        small = QFont(option.font)
        small.setPixelSize(12)
        painter.setFont(small)
        painter.setPen(QColor(t.text_muted))
        w, h = int(entry.get('width', 0)), int(entry.get('height', 0))
        painter.drawText(QRectF(text_left, rect.top() + 33, width, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         f'{tr(shape_name(w, h))} · {w} × {h}')
        if star:
            from ..design.themed_icons import cached_icon_pixmap
            ratio = painter.device().devicePixelRatioF() if painter.device() else 1
            icon = cached_icon_pixmap('fa5s.star', blend_hex(t.warning, '#e0b03c', .5), QSize(13, 13), device_pixel_ratio=ratio)
            painter.drawPixmap(int(rect.right() - 22), int(rect.center().y() - 7), icon)
        painter.restore()


class TemplatePicker(QDialog):
    def __init__(self, library, settings, parent=None, *, local=False, has_frame=False, frame=None):
        super().__init__(parent)
        self.library, self.settings = library, settings
        self.local = local
        self.has_frame = has_frame
        self.frame = frame
        self.selected = None
        self.selected_texts = {}
        self.texts = {}            # entry id -> {layer id: text typed here}
        self._documents = {}       # entry id -> loaded template copy (or None when it cannot load)
        self._thumbs = {}
        self._fields = []          # [(layer id, QPlainTextEdit)]
        self._showing_fields_for = None
        self.theme = _theme()
        self.setObjectName('coverTemplatePicker')
        self.setModal(True)
        self.chrome = CandyChrome(self, '封面模板', 'fa5s.images', maximizable=False)
        self.resize(*CandyChrome.outer_size(900, 620))
        body = self.chrome.layout
        body.setContentsMargins(0, 6, 0, 0)
        body.setSpacing(0)
        split = QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)
        body.addLayout(split, 1)
        split.addWidget(self._build_left())
        split.addLayout(self._build_right(), 1)
        body.addWidget(self._build_foot())
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(180)
        self._preview_timer.timeout.connect(self.render_preview)
        self.cards.currentItemChanged.connect(lambda *_: self.show_current())
        self.cards.itemDoubleClicked.connect(self.use)
        self.search.textChanged.connect(self.refresh)
        self.restyle()
        self.refresh()

    # ---------- layout ----------
    def _build_left(self):
        left = QFrame()
        left.setObjectName('pickerLeft')
        left.setFixedWidth(300)
        column = QVBoxLayout(left)
        column.setContentsMargins(14, 6, 10, 12)
        column.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName('pickerSearch')
        self.search.setClearButtonEnabled(True)
        bind_text(self.search, '搜索主播、系列或模板名称', property='placeholderText')
        column.addWidget(self.search)
        chips = QHBoxLayout()
        chips.setSpacing(5)
        self.filter_group = QButtonGroup(self)
        self.filter_buttons = []
        for index in range(3):
            chip = QPushButton()
            chip.setObjectName('pickerChip')
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            self.filter_group.addButton(chip, index)
            self.filter_buttons.append(chip)
            chips.addWidget(chip)
        chips.addStretch(1)
        start = int(self.settings.value('cover/template_filter', 0) or 0)
        self.filter_buttons[start if 0 <= start < 3 else 0].setChecked(True)
        self.filter_group.idClicked.connect(self._filter_changed)
        column.addLayout(chips)
        self.blank_button = QPushButton()
        self.blank_button.setObjectName('pickerNew')
        from ..design.themed_icons import install_themed_icon
        install_themed_icon(self.blank_button, 'fa5s.plus', 'accent')
        self.blank_button.setIconSize(QSize(16, 16))
        bind_text(self.blank_button, '  空白新建 · 从当前画面开始' if self.has_frame else '  空白新建 · 不套模板')
        self.blank_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.blank_button.clicked.connect(self.blank)
        column.addWidget(self.blank_button)
        self.cards = QListWidget()
        self.cards.setObjectName('pickerList')
        self.cards.setViewMode(QListView.ViewMode.ListMode)
        self.cards.setUniformItemSizes(True)
        self.cards.setMouseTracking(True)
        self.cards.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.cards.setItemDelegate(TemplateRowDelegate(self))
        self.cards.setIconSize(THUMB)
        column.addWidget(self.cards, 1)
        self.empty = QLabel()
        self.empty.setObjectName('pickerEmpty')
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bind_text(self.empty, '还没有模板。编辑封面后点击“保存为模板”，即可保留所有图层和位置。' if self.local else
                  '还没有模板。编辑封面后选择“保存为模板”，也可导入 XCF / PSD。')
        column.addWidget(self.empty)
        return left

    def _build_right(self):
        right = QVBoxLayout()
        right.setContentsMargins(22, 4, 22, 14)
        right.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.name_label = QLabel()
        self.name_label.setObjectName('pickerName')
        self.name_label.setMinimumWidth(80)
        bar.addWidget(self.name_label, 1)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName('pickerNameEdit')
        self.name_edit.hide()
        self.name_edit.returnPressed.connect(self._finish_rename)
        self.name_edit.editingFinished.connect(self._finish_rename)
        bar.addWidget(self.name_edit, 1)
        self.size_label = QLabel()
        self.size_label.setObjectName('pickerSize')
        bar.addWidget(self.size_label)
        bar.addSpacing(6)
        self.favorite_button = icon_button('fa5s.star', '收藏 / 取消收藏', checkable=True)
        self.favorite_button.clicked.connect(self.favorite)
        self.rename_button = icon_button('fa5s.pen', '重命名')
        self.rename_button.clicked.connect(self.rename)
        self.duplicate_button = icon_button('fa5s.copy', '复制')
        self.duplicate_button.clicked.connect(self.duplicate)
        self.delete_button = icon_button('fa5s.trash-alt', '删除')
        self.delete_button.clicked.connect(self.delete)
        for button in (self.favorite_button, self.rename_button, self.duplicate_button, self.delete_button):
            bar.addWidget(button)
        right.addLayout(bar)

        self.stage = QFrame()
        self.stage.setObjectName('pickerStage')
        self.stage.setFixedHeight(PREVIEW.height() + 66)
        stage = QGridLayout(self.stage)
        stage.setContentsMargins(10, 10, 10, 10)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stage.setVerticalSpacing(6)
        stage.addWidget(self.preview, 1, 0)
        self.before_after = Segmented([('模板原图', 'before'), ('换上当前画面', 'after')])
        self.before_after.set_value('after')
        self.before_after.changed.connect(lambda _value: self.render_preview())
        self.before_after.setVisible(self.local and self.frame is not None)
        stage.addWidget(self.before_after, 0, 0, Qt.AlignmentFlag.AlignLeft)
        self.confirm = QFrame()
        self.confirm.setObjectName('pickerConfirm')
        confirm = QVBoxLayout(self.confirm)
        confirm.setContentsMargins(22, 16, 22, 16)
        confirm.setSpacing(6)
        self.confirm_title = QLabel()
        self.confirm_title.setObjectName('coverSectionTitle')
        self.confirm_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        confirm.addWidget(self.confirm_title)
        note = QLabel()
        note.setObjectName('coverHint')
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bind_text(note, '旧版本仍留在本机，可以找回。')
        confirm.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        keep = text_button('留着')
        keep.clicked.connect(lambda: self.confirm.hide())
        remove = text_button('移出', kind='primary')
        remove.clicked.connect(self._delete_confirmed)
        buttons.addWidget(keep)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        confirm.addLayout(buttons)
        self.confirm.hide()
        stage.addWidget(self.confirm, 0, 0, 2, 1, Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self.stage)

        self.fields_host = QWidget()
        self.fields = QGridLayout(self.fields_host)
        self.fields.setContentsMargins(0, 0, 0, 0)
        self.fields.setHorizontalSpacing(10)
        self.fields.setVerticalSpacing(4)
        right.addWidget(self.fields_host)
        self.keeps_host = QWidget()
        self.keeps = QHBoxLayout(self.keeps_host)
        self.keeps.setContentsMargins(0, 0, 0, 0)
        self.keeps.setSpacing(6)
        right.addWidget(self.keeps_host)
        right.addStretch(1)
        return right

    def _build_foot(self):
        foot = QFrame()
        foot.setObjectName('pickerFoot')
        foot.setFixedHeight(64)
        row = QHBoxLayout(foot)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(10)
        self.replace = PillSwitch()
        self.replace.setChecked(True)
        self.replace_label = QLabel()
        self.replace_label.setObjectName('pickerFootTitle')
        milliseconds = (self.frame.source.get('milliseconds') if self.frame is not None else None)
        when = f' {_clock(milliseconds)}' if milliseconds is not None else ''
        bind_text(self.replace_label, '换上当前画面{when}', when=when)
        self.replace_note = QLabel()
        self.replace_note.setObjectName('pickerFootNote')
        bind_text(self.replace_note, '保留模板标题和贴图')
        self.replace_label.setBuddy(self.replace)
        if self.local:
            self.replace.setChecked(self.has_frame and str(self.settings.value('cover/use_current_frame', 'true')).lower() not in ('false', '0'))
            self.replace.toggled.connect(lambda value: self.settings.setValue('cover/use_current_frame', value))
        else:
            bind_text(self.replace_label, '换入本次 Studio 冻结帧（保留模板构图）')
        self.replace.setVisible(self.has_frame or not self.local)
        self.replace_label.setVisible(self.has_frame or not self.local)
        self.replace_note.setVisible(self.has_frame and self.local)
        self.replace.toggled.connect(self._replace_toggled)
        row.addWidget(self.replace)
        row.addWidget(self.replace_label)
        row.addWidget(self.replace_note)
        self.last = QCheckBox()
        bind_text(self.last, '下次按上次模板开始')
        self.last.setChecked(str(self.settings.value('cover/start_last_template', 'false')).lower() == 'true')
        self.last.toggled.connect(lambda value: self.settings.setValue('cover/start_last_template', value))
        row.addWidget(self.last)
        if self.local:
            self.last.hide()
        row.addStretch(1)
        cancel = text_button('取消', kind='ghost')
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.use_button = text_button('开始编辑', kind='primary', icon='fa5s.arrow-right')
        self.use_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.use_button.setDefault(True)
        self.use_button.clicked.connect(self.use)
        row.addWidget(self.use_button)
        return foot

    def restyle(self):
        from ..design.candy_chrome_qss import build_candy_chrome_qss
        from ..design.cover_qss import build_picker_qss
        from ..design.typography import emphasis_qss
        root = 'QDialog#coverTemplatePicker'
        self.setStyleSheet(emphasis_qss(build_candy_chrome_qss(root, self.theme)) + build_picker_qss(root, self.theme))
        self.replace.set_theme(self.theme.accent, self.theme.border_strong)

    # ---------- data ----------
    def current(self):
        item = self.cards.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def thumbnail(self, entry) -> QPixmap:
        key = (entry.get('id'), entry.get('updated'), entry.get('thumbnail'))
        if key not in self._thumbs:
            image = QImage(str(self.library.asset(entry, 'thumbnail')))
            ratio = self.devicePixelRatioF() or 1
            from ..design.ui_theme import blend_hex
            self._thumbs[key] = rounded_pixmap(image, THUMB, 9, ratio, QColor(blend_hex(self.theme.surface, self.theme.app_background, .6)))
        return self._thumbs[key]

    def _filter_changed(self, index):
        self.settings.setValue('cover/template_filter', index)
        self.refresh()

    def refresh(self, *_):
        selected = self.current()
        entries = list(self.library.entries())
        favorites = sum(1 for entry in entries if entry.get('favorite'))
        for button, (label, count) in zip(self.filter_buttons, [('最近使用', len(entries)), ('收藏', favorites), ('全部', len(entries))]):
            bind_text(button, '{label} {count}', label=tr(label), count=count)
        mode = max(0, self.filter_group.checkedId())
        query = self.search.text().casefold()
        shown = [entry for entry in entries if query in entry['name'].casefold()
                 and (mode != 1 or entry.get('favorite'))]
        if mode == 2:
            shown.sort(key=lambda entry: entry['name'].casefold())
        self.cards.blockSignals(True)
        self.cards.clear()
        for entry in shown:
            item = QListWidgetItem(('★ ' if entry.get('favorite') else '') + entry['name'] + f'\n{entry["width"]} × {entry["height"]}')
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setSizeHint(QSize(260, ROW_HEIGHT))
            self.cards.addItem(item)
            if selected and selected['id'] == entry['id']:
                self.cards.setCurrentItem(item)
        if self.cards.currentItem() is None and self.cards.count():
            self.cards.setCurrentRow(0)
        self.cards.blockSignals(False)
        self.empty.setVisible(not self.cards.count())
        self.cards.setVisible(bool(self.cards.count()))
        self.show_current()

    def show_current(self):
        entry = self.current()
        self.confirm.hide()
        self._cancel_rename()
        has = entry is not None
        for widget in (self.favorite_button, self.rename_button, self.duplicate_button, self.delete_button, self.use_button):
            widget.setEnabled(has)
        if not has:
            bind_text(self.name_label, '选择一个模板' if self.cards.count() == 0 and self.library.entries() else '还没有模板')
            self.size_label.clear()
            self.preview.clear()
            self._build_fields(None, None)
            self._build_keeps(None)
            return
        self.name_label.setText(entry['name'])
        w, h = int(entry['width']), int(entry['height'])
        self.size_label.setText(f'{tr(shape_name(w, h))} · {w} × {h}')
        self.favorite_button.setChecked(bool(entry.get('favorite')))
        document = self._document(entry)
        self._build_fields(entry, document)
        self._build_keeps(document)
        self.render_preview()

    def _document(self, entry):
        if entry['id'] not in self._documents:
            document = None
            if hasattr(self.library, 'load_copy'):
                try:
                    document = self.library.load_copy(entry)
                except Exception:  # noqa: BLE001 - a broken template still shows its thumbnail
                    document = None
            self._documents[entry['id']] = document
        return self._documents[entry['id']]

    def _text_layers(self, document):
        layers = [layer for layer in document.layers if layer.kind == 'text' and layer.visible and not layer.locked]
        layers.sort(key=lambda layer: -float(layer.style.get('size', 0)))
        return layers[:2]

    def _build_fields(self, entry, document):
        while self.fields.count():
            widget = self.fields.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self._fields = []
        layers = self._text_layers(document) if document is not None else []
        self.fields_host.setVisible(bool(layers))
        typed = self.texts.get(entry['id'], {}) if entry else {}
        for column, layer in enumerate(layers):
            label = QLabel()
            label.setObjectName('pickerFieldLabel')
            label.setText(layer.name)
            if column == 0:
                hint = QLabel()
                hint.setObjectName('pickerFieldHint')
                bind_text(hint, '先填好，进去就不用再找')
                head = QWidget()
                head_row = QHBoxLayout(head)
                head_row.setContentsMargins(0, 0, 0, 0)
                head_row.setSpacing(8)
                head_row.addWidget(label)
                head_row.addWidget(hint)
                head_row.addStretch(1)
                label = head
            editor = QPlainTextEdit()
            editor.setPlainText(typed.get(layer.id, layer.text))
            editor.setFixedHeight(60)
            editor.setTabChangesFocus(True)
            editor.textChanged.connect(lambda key=layer.id, box=editor: self._typed(key, box))
            self.fields.addWidget(label, 0, column)
            self.fields.addWidget(editor, 1, column)
            self._fields.append((layer.id, editor))
        if len(layers) == 1:
            self.fields.setColumnStretch(1, 1)
            self.fields.setColumnStretch(0, 1)

    def _build_keeps(self, document):
        while self.keeps.count():
            widget = self.keeps.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        if document is None:
            self.keeps_host.hide()
            return
        self.keeps_host.show()
        title = QLabel()
        title.setObjectName('coverHint')
        title.setObjectName('pickerKeepTitle')
        bind_text(title, '会保留')
        self.keeps.addWidget(title)
        kept = [layer for layer in reversed(document.layers) if layer.id != document.background_id]
        for layer in kept[:4]:
            chip = QLabel(('🔒 ' if layer.locked else '✓ ') + layer.name)
            chip.setObjectName('pickerKeep')
            self.keeps.addWidget(chip)
        if len(kept) > 4:
            more = QLabel()
            more.setObjectName('coverHint')
            bind_text(more, '等 {count} 层', count=len(kept))
            self.keeps.addWidget(more)
        if self.has_frame and document.background_id:
            swap_title = QLabel()
            swap_title.setObjectName('coverHint')
            swap_title.setObjectName('pickerKeepTitle')
            bind_text(swap_title, '会换掉')
            self.keeps.addSpacing(6)
            self.keeps.addWidget(swap_title)
            swap = QLabel()
            swap.setObjectName('pickerSwap')
            bind_text(swap, '底图 → 当前画面' if self.replace.isChecked() else '底图 → 模板底图')
            self.keeps.addWidget(swap)
        self.keeps.addStretch(1)

    def _typed(self, layer_id, box):
        entry = self.current()
        if entry is None:
            return
        self.texts.setdefault(entry['id'], {})[layer_id] = box.toPlainText()
        self._preview_timer.start()

    def _replace_toggled(self, value):
        self.before_after.set_value('after' if value else 'before')
        self._build_keeps(self._document(self.current()) if self.current() else None)
        self.render_preview()

    def preview_document(self, entry):
        """The template copy as the editor will open it: typed titles, and the current frame
        when 换上当前画面 is on and shown."""
        document = self._document(entry)
        if document is None:
            return None
        document = document.snapshot()
        for layer_id, text in self.texts.get(entry['id'], {}).items():
            layer = document.layer(layer_id)
            if layer is not None:
                layer.text = text
        if self.frame is not None and self.replace.isChecked() and self.before_after.value() == 'after':
            try:
                self.library.replace_frame(document, self.frame)
            except Exception:  # noqa: BLE001 - preview only
                pass
        return document

    def render_preview(self):
        entry = self.current()
        if entry is None:
            return
        image = QImage()
        document = self.preview_document(entry)
        if document is not None:
            try:
                from .cover_render import CoverRenderer
                image = CoverRenderer().render(document)
            except Exception:  # noqa: BLE001 - fall back to the stored thumbnail
                image = QImage()
        if image.isNull():
            image = QImage(str(self.library.asset(entry, 'thumbnail')))
        ratio = self.devicePixelRatioF() or 1
        bounds = QSize(min(PREVIEW.width(), self.stage.width() - 24) if self.stage.width() > 100 else PREVIEW.width(), PREVIEW.height())
        if image.isNull():
            self.preview.clear()
            return
        size = image.size().scaled(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        self.preview.setPixmap(rounded_pixmap(image, size, 8, ratio, QColor('#000000')))

    # ---------- actions ----------
    def favorite(self):
        entry = self.current()
        if entry:
            entry['favorite'] = not entry.get('favorite')
            self.library.metadata(entry)
            self.refresh()

    def rename(self):
        entry = self.current()
        if not entry:
            return
        self.name_label.hide()
        self.name_edit.setText(entry['name'])
        self.name_edit.show()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _cancel_rename(self):
        if not self.name_edit.isHidden():
            self.name_edit.blockSignals(True)
            self.name_edit.hide()
            self.name_edit.blockSignals(False)
            self.name_label.show()

    def _finish_rename(self):
        if self.name_edit.isHidden():
            return
        entry, name = self.current(), self.name_edit.text().strip()
        self._cancel_rename()
        if entry and name and name != entry['name']:
            entry['name'] = name
            self.library.metadata(entry)
            self.refresh()

    def duplicate(self):
        entry = self.current()
        if entry:
            copy = self.library.duplicate(entry)
            self.refresh()
            for index in range(self.cards.count()):
                if self.cards.item(index).data(Qt.ItemDataRole.UserRole)['id'] == copy['id']:
                    self.cards.setCurrentRow(index)
                    break

    def delete(self):
        entry = self.current()
        if entry:
            bind_text(self.confirm_title, '把“{value0}”移出模板库？', value0=entry['name'])
            self.confirm.show()
            self.confirm.raise_()

    def _delete_confirmed(self):
        entry = self.current()
        self.confirm.hide()
        if entry:
            entry['deleted'] = True
            self.library.metadata(entry)
            self.refresh()

    def use(self, *_):
        self.selected = self.current()
        if self.selected:
            typed = self.texts.get(self.selected['id'], {})
            document = self._document(self.selected)
            original = {layer.id: layer.text for layer in document.layers} if document is not None else {}
            self.selected_texts = {key: value for key, value in typed.items() if original.get(key) != value}
            self.accept()

    def blank(self):
        self.selected = {'blank': True}
        self.selected_texts = {}
        self.accept()

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            if not self.confirm.isHidden():
                self.confirm.hide()
                return
            if not self.name_edit.isHidden():
                self._cancel_rename()
                return
        super().keyPressEvent(event)


def _clock(milliseconds) -> str:
    seconds = int(milliseconds or 0) // 1000
    return f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'


__all__ = ['TemplatePicker', 'rounded_pixmap']
