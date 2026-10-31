"""Lazy font combo box and its contrast-aware popup delegate."""

from __future__ import annotations
from collections import OrderedDict
import time

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal, QSignalBlocker, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import QListView, QLineEdit, QStyle, QStyleOptionFrame, QStyleOptionViewItem, QStyledItemDelegate, QToolTip

from .font_system import system_font_inventory
from .font_picker_preview import FontPreviewRequest,draw_font_preview,preview_face,preview_pixels
from ..design.studio_theme import StudioComboBox, apply_secondary_surface_theme

from ..i18n import bind_text


class FontPreviewEdit(QLineEdit):
    """One searchable edit/hit area, with real glyphs when it is collapsed."""
    def __init__(self,combo):
        super().__init__(combo);self.combo=combo

    def paintEvent(self,event):
        combo=self.combo
        if combo.view().isVisible() or combo._editing_query:
            return super().paintEvent(event)
        painter=QPainter(self);option=QStyleOptionFrame();self.initStyleOption(option)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_PanelLineEdit,option,painter,self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing,True)
        visible=QRectF(self.contentsRect()).intersected(QRectF(combo.rect()).translated(-self.x(),-self.y()))
        combo._last_font_preview=draw_font_preview(painter,visible.adjusted(2,3,-2,-3),
            self.text(),combo.preview_request_for(self.text(),current=True),self.font(),
            option.palette.color(QPalette.ColorRole.Text))
        painter.end()

    def event(self,event):
        if event.type()==QEvent.Type.ToolTip:
            state=self.combo._last_font_preview
            text=self.combo.toolTip() or self.text()
            if state.get('actual'):text+='\n预览字体：'+state['actual']+' / '+state.get('actual_style','')
            if state and not state.get('name_uses_target'):text+='\n名称使用界面字体保持可读'
            if state.get('sample_uses_ui_prefix'):text+='\n「示例」使用界面字体；英文和数字使用所选字体'
            if state.get('sample')!='示例ABC123':text+='\n可用示例：'+(state.get('sample')or '无法预览实际字体')
            QToolTip.showText(event.globalPos(),text,self);return True
        return super().event(event)

    def keyPressEvent(self,event):
        if (event.text() and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.AltModifier)
                or event.key() in (Qt.Key.Key_Backspace,Qt.Key.Key_Delete)
                or event.matches(QKeySequence.StandardKey.SelectAll)):
            self.combo._editing_query=True
        super().keyPressEvent(event)

    def inputMethodEvent(self,event):
        if event.preeditString()or event.commitString():self.combo._editing_query=True
        super().inputMethodEvent(event)

class FontFamilyDelegate(QStyledItemDelegate):
    """Renders each font row in its own family, theme-readable."""

    def __init__(self, combo: "LazyFontComboBox", parent=None):
        super().__init__(parent)
        self._combo = combo

    def sizeHint(self, option, index) -> QSize:
        return QSize(240, 34)

    @staticmethod
    def _channel_luminance(value: int) -> float:
        channel = max(0.0, min(1.0, value / 255.0))
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    @classmethod
    def _contrast_ratio(cls, foreground: QColor, background: QColor) -> float:
        foreground_luminance = (
            0.2126 * cls._channel_luminance(foreground.red())
            + 0.7152 * cls._channel_luminance(foreground.green())
            + 0.0722 * cls._channel_luminance(foreground.blue())
        )
        background_luminance = (
            0.2126 * cls._channel_luminance(background.red())
            + 0.7152 * cls._channel_luminance(background.green())
            + 0.0722 * cls._channel_luminance(background.blue())
        )
        lighter = max(foreground_luminance, background_luminance)
        darker = min(foreground_luminance, background_luminance)
        return (lighter + 0.05) / (darker + 0.05)

    @staticmethod
    def _blend(foreground: QColor, background: QColor, weight: float) -> QColor:
        weight = max(0.0, min(1.0, weight))
        return QColor(
            round(foreground.red() * weight + background.red() * (1.0 - weight)),
            round(foreground.green() * weight + background.green() * (1.0 - weight)),
            round(foreground.blue() * weight + background.blue() * (1.0 - weight)),
        )

    @classmethod
    def _readable_disabled_text(cls, palette: QPalette, background: QColor) -> QColor:
        disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        if cls._contrast_ratio(disabled, background) >= 3.0:
            return disabled
        enabled = palette.color(QPalette.ColorRole.Text)
        for weight in (0.64, 0.72, 0.82, 1.0):
            candidate = cls._blend(enabled, background, weight)
            if cls._contrast_ratio(candidate, background) >= 3.0:
                return candidate
        return enabled

    def paint(self, painter: QPainter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        family = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        enabled = bool(opt.state & QStyle.StateFlag.State_Enabled)
        selected = enabled and bool(opt.state & QStyle.StateFlag.State_Selected)
        hovered = enabled and not selected and bool(opt.state & QStyle.StateFlag.State_MouseOver)
        base = opt.palette.color(QPalette.ColorRole.Base)
        if selected:
            background = opt.palette.color(QPalette.ColorRole.Highlight)
            color = opt.palette.color(QPalette.ColorRole.HighlightedText)
        elif hovered:
            background = opt.palette.color(QPalette.ColorRole.AlternateBase)
            color = opt.palette.color(QPalette.ColorRole.Text)
        elif enabled:
            background = base
            color = opt.palette.color(QPalette.ColorRole.Text)
        else:
            background = base
            color = self._readable_disabled_text(opt.palette, background)

        # QSS/native item controls can disagree about the popup palette. Own
        # the complete row so a dark theme can never leave a native white fill
        # behind light preview text.
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base)
        painter.drawRect(opt.rect)
        if background != base:
            state_rect = QRectF(opt.rect).adjusted(1.0, 1.0, -1.0, -1.0)
            painter.setBrush(background)
            painter.drawRoundedRect(state_rect, 4.0, 4.0)
        painter.restore()
        if not family:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = opt.rect.adjusted(10, 0, -8, 0)
        painter.setPen(color)
        recent = family in self._combo.recent_families()
        tag_width = 0
        if recent:
            tag_text = "最近"
            tag_font = QFont(opt.font)
            tag_font.setPointSize(max(8, opt.font.pointSize() - 2))
            metrics = QFontMetrics(tag_font)
            tag_width = metrics.horizontalAdvance(tag_text) + 12
            tag_rect = QRectF(rect.right() - tag_width, rect.center().y() - 9, tag_width, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            accent = opt.palette.color(QPalette.ColorRole.Link)
            painter.setBrush(accent)
            painter.drawRoundedRect(tag_rect, 4, 4)
            painter.setFont(tag_font)
            painter.setPen(opt.palette.color(QPalette.ColorRole.BrightText))
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag_text)
        content=QRectF(rect.left(),rect.top()+3,rect.width()-(tag_width+12 if recent else 0),rect.height()-6)
        request=self._combo.preview_request_for(family)
        state=draw_font_preview(painter,content,family,request,opt.font,color,allow_load=False)
        self._combo._last_font_rows[family]=state
        if state['loading']:self._combo.queue_font_preview(request,preview_pixels(opt.font))
        while len(self._combo._last_font_rows)>32:self._combo._last_font_rows.pop(next(iter(self._combo._last_font_rows)))
        painter.restore()

    def helpEvent(self,event,view,option,index):
        family=str(index.data(Qt.ItemDataRole.DisplayRole)or '')
        face,warning=preview_face(self._combo.preview_request_for(family),preview_pixels(option.font))
        detail=(f'{face.metadata.full_name} / {face.metadata.style} / {face.metadata.weight}' if face else '无法预览实际字体')
        if face and not face.covers(family):detail+='\n名称用界面字体显示；示例使用目标字体'
        if face and not face.covers('示例'):detail+='\n「示例」使用界面字体；英文和数字使用所选字体'
        if face and face.sample()!='ABC123':detail+='\n可用示例：'+(face.sample()or '无文字示例')
        QToolTip.showText(event.globalPos(),family+'\n'+detail+('\n'+warning if warning else ''),view)
        return True


class LazyFontComboBox(StudioComboBox):
    """Searchable in-inspector font dropdown.

    No top-level dialog: typing in the combo filters the list, each row is
    rendered in its own family, and recent picks stay pinned with a badge.
    """

    fontPicked = Signal(str, int)

    MAX_RECENT = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fonts_loaded = False
        self._font_load_pending = True
        self._recent_fonts = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei"]
        self._all_families: list[str] = []
        self._family_aliases={}
        self._suppress_filter = False
        self._editing_query=False
        self._committed_family='Microsoft YaHei UI'
        self._preview_request=FontPreviewRequest(self._committed_family)
        self._last_font_preview={};self._last_font_rows={}
        self._pending_font_previews=OrderedDict()
        self._font_preview_timer=QTimer(self);self._font_preview_timer.setSingleShot(True)
        self._font_preview_timer.timeout.connect(self._prepare_visible_font)
        view = QListView()
        view.setObjectName("fontFamilyPopup")
        view.setItemDelegate(FontFamilyDelegate(self, view))
        view.setMinimumHeight(340)
        apply_secondary_surface_theme(view)
        self.setView(view)
        self.refresh_theme_palette()
        self.setMaxVisibleItems(18)
        self.addItem("Microsoft YaHei UI")
        self.activated.connect(lambda index: self.commit_family(self.itemText(index)))

    def recent_families(self) -> set[str]:
        return set(self._recent_fonts)

    def committed_family(self):
        return self._committed_family

    def setEditable(self, editable: bool) -> None:
        super().setEditable(editable)
        if editable and self.lineEdit() is not None:
            if not isinstance(self.lineEdit(),FontPreviewEdit):self.setLineEdit(FontPreviewEdit(self))
            # This picker owns its filtered popup. A second QCompleter popup
            # can consume Return or accept a family while merely browsing.
            self.setCompleter(None)
            bind_text(self.lineEdit(), '输入或搜索字体…', property='placeholderText')
            if not self.lineEdit().property('fontSearchConnected'):
                self.lineEdit().setProperty('fontSearchConnected',True)
                self.lineEdit().textEdited.connect(self._filter_families)
                self.lineEdit().installEventFilter(self)

    def setEditText(self,text):
        super().setEditText(text)
        if not self._suppress_filter and not self._editing_query and not self.view().isVisible():
            self._committed_family=str(text)

    def setCurrentText(self,text):
        super().setCurrentText(text)
        if not self._suppress_filter and not self._editing_query and not self.view().isVisible():
            self._committed_family=self.currentText()

    def set_preview_face(self,family,*,weight=0,style='',bold=False,filename='',face_index=0):
        self._preview_request=FontPreviewRequest(str(family),int(weight),str(style),bool(bold),str(filename),int(face_index))
        self._committed_family=str(family);self._editing_query=False
        if self.lineEdit() is not None:self.lineEdit().update()

    def preview_request_for(self,family,*,current=False):
        hint=self._preview_request
        if current and str(family).casefold()==hint.family.casefold():return hint
        return FontPreviewRequest(str(family),bold=hint.bold)

    def popup_content_width(self,metrics):
        # Measure labels in the already-available UI font; no font files are
        # opened while sizing the entire model.
        longest=max((metrics.horizontalAdvance(f)for f in self._all_families),default=180)
        return max(self.width(),min(640,max(420,round(longest*1.3)+180)))

    def queue_font_preview(self,request,pixels):
        if not self.view().isVisible():return
        self._pending_font_previews[(request,pixels)]=None
        while len(self._pending_font_previews)>32:self._pending_font_previews.popitem(last=False)
        if not self._font_preview_timer.isActive():self._font_preview_timer.start(0)

    def _prepare_visible_font(self):
        if not self.view().isVisible():self._pending_font_previews.clear();return
        started=time.perf_counter();prepared=0
        while self._pending_font_previews:
            if prepared and (prepared>=4 or time.perf_counter()-started>=.008):break
            (request,pixels),_=self._pending_font_previews.popitem(last=False)
            index=self.findText(request.family)
            if index<0:continue
            rect=self.view().visualRect(self.model().index(index,0))
            if not rect.intersects(self.view().viewport().rect()):continue
            face,_=preview_face(request,pixels)
            if face is not None:
                face.sample()
                if face.covers('示例'):face.shape('示例'+face.sample())
                if face.covers(request.family):face.shape(request.family)
            self.view().viewport().update(rect)
            prepared+=1
        if self._pending_font_previews:self._font_preview_timer.start(0)

    def eventFilter(self, watched, event) -> bool:
        # The whole combo frame must open the list: clicking the text field is
        # the largest target, not only the arrow button. Typing still filters
        # the open list because focus goes back to the edit.
        # 2026-10-18 (user: the list "马上又消失", several clicks needed): the
        # list used to open on the press, so the same click's release landed
        # on the freshly opened popup and closed it (or picked the font under
        # the pointer). Open on the release; the press only focuses the edit.
        if watched is self.lineEdit() and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            if event.button() == Qt.MouseButton.LeftButton and not self.view().isVisible():
                self.lineEdit().setFocus(Qt.FocusReason.MouseFocusReason)
                self._open_on_release = True
                return True
        if watched is self.lineEdit() and event.type() == QEvent.Type.MouseButtonRelease:
            if getattr(self, "_open_on_release", False) and event.button() == Qt.MouseButton.LeftButton:
                self._open_on_release = False
                if not self.view().isVisible() and self.lineEdit().rect().contains(event.position().toPoint()):
                    self.showPopup()
                return True
        return super().eventFilter(watched, event)

    def showPopup(self) -> None:
        audit = getattr(self, "interaction_runtime_audit", None)
        if audit is None:
            self._show_font_popup()
            return
        with audit.measure("Font", allow_new_top_levels=True):
            self._show_font_popup()

    def _show_font_popup(self) -> None:
        current = self._committed_family or self.currentText()
        self._load_full_font_list()
        # Opening the list must show every font. Filtering by the current text
        # here forced users to delete the field content before other families
        # became visible.
        self.refresh_theme_palette()
        apply_secondary_surface_theme(self.view())
        self._suppress_filter = True
        if self._fonts_loaded:
            self._rebuild_items("")
            index=self.findText(current)
            if index>=0:
                with QSignalBlocker(self):self.setCurrentIndex(index)
            self.setEditText(current)
        try:
            super().showPopup()
            if self.lineEdit() is not None:self.lineEdit().setFocus(Qt.FocusReason.PopupFocusReason)
        finally:
            # Qt may emit textChanged while creating/selecting the popup view.
            # Keep that programmatic emission from narrowing the freshly
            # opened all-font list back to the current family.
            self._suppress_filter = False

    def hidePopup(self) -> None:
        self._font_preview_timer.stop();self._pending_font_previews.clear()
        super().hidePopup()
        self._editing_query=False
        if self._committed_family:
            previous=self._suppress_filter;self._suppress_filter=True
            with QSignalBlocker(self):self.setEditText(self._committed_family)
            self._suppress_filter=previous
        if self.lineEdit() is not None:self.lineEdit().update()

    def _load_full_font_list(self) -> None:
        if self._fonts_loaded:
            return
        inventory = system_font_inventory()
        families = [entry.family for entry in inventory]
        if not families:
            families = sorted(
                {str(item).strip() for item in QFontDatabase().families() if str(item).strip()},
                key=str.casefold,
            )
        self._all_families = families
        from .font_metadata import _faces_by_alias
        index=_faces_by_alias()
        self._family_aliases={family.casefold():tuple({alias.casefold() for face in index.get(family.casefold(),())
                                for alias in (*face.aliases,face.display_family) if alias})for family in families}
        for aliases in tuple(self._family_aliases.values()):
            for alias in aliases:self._family_aliases.setdefault(alias,aliases)
        self._fonts_loaded = True
        self._suppress_filter = True
        self._rebuild_items("")
        self._suppress_filter = False

    def _filter_families(self, text: str) -> None:
        if self._suppress_filter:
            return
        self._editing_query=True
        if not self._fonts_loaded:self._load_full_font_list()
        self._rebuild_items(text, keep_popup=True)
        if self.hasFocus()or self.lineEdit()is not None and self.lineEdit().hasFocus():
            previous=self._suppress_filter;self._suppress_filter=True
            try:
                if not self.view().isVisible():super().showPopup()
                else:
                    from ..design.combo_popup import place_native_popup
                    place_native_popup(self.view().window())
                self.lineEdit().setFocus(Qt.FocusReason.PopupFocusReason)
            finally:self._suppress_filter=previous

    def _rebuild_items(self, filter_text: str, keep_popup: bool = False) -> None:
        self._font_preview_timer.stop();self._pending_font_previews.clear()
        needle = str(filter_text).strip().casefold()
        current = str(filter_text)
        def matches(family):
            return not needle or needle in family.casefold()or any(needle in a for a in self._family_aliases.get(family.casefold(),()))
        candidates = [family for family in self._all_families if matches(family)]
        if not needle:
            recent = [family for family in self._recent_fonts if family in self._all_families or family in ("Microsoft YaHei UI",)]
            rest = [family for family in candidates if family not in self._recent_fonts]
            ordered = recent + rest
        else:
            recent = [family for family in self._recent_fonts if matches(family)]
            rest = [family for family in candidates if family not in self._recent_fonts]
            ordered = recent + rest
        if self._committed_family and self._committed_family not in ordered and matches(self._committed_family):
            ordered.insert(0,self._committed_family)
        previous_suppression = self._suppress_filter
        self._suppress_filter = True
        blocked=self.blockSignals(True)
        self.clear()
        self.addItems(ordered[:400] if needle else ordered)
        self.setEditText(current)
        self.blockSignals(blocked)
        self._suppress_filter = previous_suppression

    def commit_family(self, family: str) -> None:
        family = str(family).strip()
        if not family:
            return
        if self.findText(family) < 0:
            self._suppress_filter = True
            self.addItem(family)
            self._suppress_filter = False
        self._suppress_filter = True
        self.setCurrentText(family)
        self.setEditText(family)
        self._suppress_filter = False
        self._committed_family=family;self._editing_query=False
        self._recent_fonts[:] = [family] + [value for value in self._recent_fonts if value != family][: self.MAX_RECENT - 1]
        if self.view().isVisible():self.hidePopup()
        self.fontPicked.emit(family, 400)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and self.findText(self.currentText().strip()) >= 0:
            self.commit_family(self.currentText().strip())
            event.accept()
            return
        super().keyPressEvent(event)
