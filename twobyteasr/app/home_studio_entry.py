"""A quiet, cached project-cover backdrop for the Home Studio entrance."""
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, Signal, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QImageReader, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import QFrame, QSizePolicy, QToolButton, QWidget

from .ui_zoom import px as _zpx  # painted text follows the interface zoom
from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_definition

from ..i18n import bind_text


def studio_paper_colors(theme):
    """The entrance shares the active theme, including its painted motif."""
    # 2026-10-14: each theme states its card colors in ui_theme.THEME_TRAITS
    # (studio_paper); themes that do not get a quiet brand wash over the card.
    return theme.studio_paper


def latest_studio_entry(records):
    """Use recent-open order and the same canonical cover as the project library."""
    for item in records if isinstance(records, list) else []:
        record = item if isinstance(item, dict) else {"path": str(item)}
        value = str(record.get("path") or "")
        project = Path(value)
        if not value or not project.is_file():
            continue
        canonical = project.parent / "preview" / "project-cover.jpg"
        cover_value = str(record.get("cover_path") or "")
        cover = Path(cover_value) if cover_value else None
        if cover and not cover.is_absolute():
            cover = project.parent / cover
        if canonical.is_file():
            cover = canonical
        from ..projects.project_display_name import display_project_name
        return display_project_name(record), str(cover) if cover else ""
    return "", ""


def _edited_text(record) -> str:
    from datetime import datetime
    for key in ("last_opened", "modified", "updated_at"):
        raw = str(record.get(key) or "")
        try:
            stamp = datetime.fromisoformat(raw) if raw else None
        except ValueError:
            stamp = None
        if stamp is not None:
            return (stamp.astimezone() if stamp.tzinfo else stamp).strftime("%m-%d %H:%M")
    return ""


def recent_studio_entries(records, limit=12):
    """Openable recent projects in recent-open order, with the library's cover rule."""
    entries = []
    seen = set()
    for item in records if isinstance(records, list) else []:
        record = item if isinstance(item, dict) else {"path": str(item)}
        key = str(Path(str(record.get("path") or "")).resolve()).casefold()
        if key in seen:
            continue
        seen.add(key)
        name, cover = latest_studio_entry([record])
        if not name:
            continue
        entries.append({"path": str(record.get("path") or ""), "name": name, "cover": cover,
                        "count": int(record.get("cue_count", 0) or 0), "edited": _edited_text(record)})
        if len(entries) >= limit:
            break
    return entries


def _load_cover(path, cache):
    """(key, QImage) for ``path``; reuses ``cache`` while mtime/size match."""
    try:
        stat = Path(path).stat() if path and Path(path).is_file() else None
        key = (path, stat.st_mtime_ns, stat.st_size) if stat else None
    except OSError:
        key = None
    if key == cache[0]:
        return cache
    image = QImage()
    if key:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(1280, 720, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
    return key, image


class _HoverButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)


def _entry_meta(entry):
    from ..i18n import tr
    count = entry.get("count", 0)
    edited = entry.get("edited", "")
    return tr('{count} 条字幕 · {edited}', count=count, edited=edited) if edited else tr('{count} 条字幕', count=count)


class RecentProjectHero(_HoverButton):
    """The latest project as one cover with a soft scrim and its name/info:
    a project entrance, not a poster (2026-10-08). Empty: a quiet placeholder."""

    open_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeRecentHero")
        self.setProperty("uiZoomOwnSize", True)  # cover keeps its own 16:10 cap
        self.entry = {}
        self._cover = (None, QImage())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.clicked.connect(lambda: self.open_requested.emit(self.entry.get("path", "")))

    def sizeHint(self):
        return QSize(420, 170)

    def minimumSizeHint(self):
        return QSize(200, 150)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # The cover follows the window, but never taller than 16:10.
        cap = max(150, int(self.width() * 0.625))
        cap = min(cap, getattr(self, '_budget_height', cap))
        if self.maximumHeight() != cap:
            self.setMaximumHeight(cap)

    def set_entry(self, entry):
        self.entry = dict(entry or {})
        self.setAccessibleName(self.entry.get("name", ""))
        self.setToolTip(self.entry.get("path", ""))
        self._cover = _load_cover(self.entry.get("cover") or "", self._cover)
        self.update()

    def paintEvent(self, _event):
        from ..i18n import tr
        from ..design.ui_theme import blend_hex
        theme = theme_definition(theme_key())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        shape = QPainterPath()
        shape.addRoundedRect(rect, 14, 14)
        p.save()
        p.setClipPath(shape)
        image = self._cover[1]
        if not image.isNull():
            factor = max(rect.width() / image.width(), rect.height() / image.height())
            w, h = image.width() * factor, image.height() * factor
            p.drawImage(QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h), image)
        else:
            fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
            zone = theme.zone_colors["studio"]
            fill.setColorAt(0, QColor(blend_hex(theme.surface, zone, 0.26)))
            fill.setColorAt(1, QColor(blend_hex(theme.surface, zone, 0.08)))
            p.fillRect(rect, fill)
            import qtawesome as qta
            glyph = 40
            p.setOpacity(0.55)
            p.drawPixmap(int(rect.center().x() - glyph / 2), int(rect.center().y() - glyph / 2 - 24),
                         qta.icon("fa5s.closed-captioning", color=zone).pixmap(glyph, glyph))
            p.setOpacity(1)
        if self.entry:
            # Soft scrim: clear at the top, dark under the text in every theme.
            scrim = QLinearGradient(rect.left(), rect.top() + rect.height() * 0.35, rect.left(), rect.bottom())
            scrim.setColorAt(0, QColor(12, 10, 18, 0))
            scrim.setColorAt(1, QColor(12, 10, 18, 215))
            p.fillRect(rect, scrim)
        p.restore()
        edge = theme.focus if self.hasFocus() else (theme.accent_text if self._hovered else theme.border)
        p.setPen(QPen(QColor(edge), 2 if self.hasFocus() else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)
        font = QFont(self.font())
        left, width = rect.x() + 20, rect.width() - 40
        if not self.entry:
            font.setPixelSize(_zpx(15))
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            p.setPen(QColor(theme.text_secondary))
            p.drawText(QRectF(rect.x(), rect.center().y() + 4, rect.width(), 22), Qt.AlignmentFlag.AlignCenter,
                       tr('还没有工程'))
            font.setPixelSize(_zpx(13))
            font.setWeight(QFont.Weight.Normal)
            p.setFont(font)
            p.setPen(QColor(theme.text_muted))
            p.drawText(QRectF(rect.x(), rect.center().y() + 28, rect.width(), 20), Qt.AlignmentFlag.AlignCenter,
                       tr('识别完成后会自动建立工程'))
            p.end()
            return
        bottom = rect.bottom() - 18
        font.setPixelSize(_zpx(13))
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 200))
        meta = _entry_meta(self.entry)
        p.drawText(QRectF(left, bottom - 20, width, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(font).elidedText(meta, Qt.TextElideMode.ElideRight, int(width)))
        font.setPixelSize(_zpx(20))
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(left, bottom - 50, width, 28), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(font).elidedText(self.entry.get("name", ""), Qt.TextElideMode.ElideMiddle, int(width)))
        font.setPixelSize(_zpx(12))
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 170))
        p.drawText(QRectF(left, bottom - 74, width, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   tr('继续编辑') + "  →")
        p.end()


class RecentProjectRow(_HoverButton):
    """One recent project line: clear name, quieter count and time. The
    current row (the one the cover shows) carries the Studio zone accent."""

    hovered = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeRecentRow")
        self.entry = {}
        self.current = False

    def set_entry(self, entry):
        self.entry = dict(entry)
        self.setAccessibleName(self.entry.get("name", ""))
        self.setToolTip(self.entry.get("path", ""))
        self.update()

    def set_current(self, current):
        if bool(current) != self.current:
            self.current = bool(current)
            self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hovered.emit(True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.hovered.emit(False)

    def paintEvent(self, _event):
        from ..design.ui_theme import blend_hex
        theme = theme_definition(theme_key())
        zone = theme.zone_colors["studio"]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0, 2, 0, -2)
        if self.current or self._hovered or self.hasFocus():
            fill = blend_hex(theme.surface, zone, 0.2 if self._hovered else 0.13)
            edge = theme.focus if self.hasFocus() else blend_hex(theme.surface, zone, 0.55 if self._hovered else 0.3)
            p.setPen(QPen(QColor(edge), 1))
            p.setBrush(QColor(fill))
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        if self.current:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(zone))
            p.drawRoundedRect(QRectF(rect.x() + 6, rect.y() + 9, 3, rect.height() - 18), 1.5, 1.5)
        font = QFont(self.font())
        font.setPixelSize(_zpx(12))
        font.setWeight(QFont.Weight.Normal)
        meta = _entry_meta(self.entry)
        meta_width = min(QFontMetrics(font).horizontalAdvance(meta) + 4, int(rect.width() * 0.42))
        p.setFont(font)
        muted = QColor(theme.text_muted)
        muted.setAlpha(200)
        p.setPen(muted)
        p.drawText(QRectF(rect.right() - 14 - meta_width, rect.y(), meta_width, rect.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(font).elidedText(meta, Qt.TextElideMode.ElideRight, meta_width))
        font.setPixelSize(_zpx(15))
        font.setWeight(QFont.Weight.DemiBold if self.current else QFont.Weight.Medium)
        name_width = int(rect.width() - 22 - meta_width - 24)
        p.setFont(font)
        p.setPen(QColor(theme.text))
        p.drawText(QRectF(rect.x() + 20, rect.y(), name_width, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(font).elidedText(self.entry.get("name", ""), Qt.TextElideMode.ElideMiddle, name_width))
        p.end()


class RecentProjectList(QWidget):
    """Recent projects as rows; the first is the current one (shown on the
    cover). Hovering a row previews it on the cover; a click opens it."""

    open_requested = Signal(str)
    preview_requested = Signal(int)
    ROW = 44

    def __init__(self, parent=None, limit=4):
        super().__init__(parent)
        self.limit = limit
        self.rows = []
        self.entries = []
        self.setProperty('uiZoomOwnSize', True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(320, self.row_height() * len(self.entries))

    def row_height(self):
        return _zpx(self.ROW)

    def apply_ui_zoom(self, _factor):
        self._show_entries()
        parent = self.parentWidget()
        if hasattr(parent, 'schedule_recent_fit'):
            parent.schedule_recent_fit()

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_entries(self, entries):
        self._all_entries = list(entries)
        self._show_entries()
        parent = self.parentWidget()
        if hasattr(parent, 'schedule_recent_fit'):
            parent.schedule_recent_fit()

    def set_limit(self, limit):
        if self.limit != limit:
            self.limit = limit
            self._show_entries()

    def _show_entries(self):
        self.entries = getattr(self, '_all_entries', [])[:self.limit]
        while len(self.rows) < len(self.entries):
            row = RecentProjectRow(self)
            index = len(self.rows)
            row.clicked.connect(lambda _=False, r=row: self.open_requested.emit(r.entry.get("path", "")))
            row.hovered.connect(lambda inside, i=index: self.preview_requested.emit(i if inside else -1))
            self.rows.append(row)
        for index, row in enumerate(self.rows):
            if index < len(self.entries):
                row.set_entry(self.entries[index])
                row.setGeometry(0, index * self.row_height(), self.width(), self.row_height())
                row.show()
            else:
                row.hide()
        self.set_current(-1)
        self.updateGeometry()

    def set_current(self, index):
        for position, row in enumerate(self.rows):
            row.set_current(position == index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for index, row in enumerate(self.rows[:len(self.entries)]):
            row.setGeometry(0, index * self.row_height(), self.width(), self.row_height())


class StudioEntryPin(QObject):
    """Keep the original left card visible; its button remains inside it."""

    def __init__(self, window):
        super().__init__(window)
        self.window_owner = window
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self.sync)
        window.settings_scroll.viewport().installEventFilter(self)
        window.settings_scroll.verticalScrollBar().valueChanged.connect(self.schedule_sync)
        window.pages.currentChanged.connect(self.sync)
        self.set_card()

    def set_card(self):
        window = self.window_owner
        card = window.studio_entry_card
        old = getattr(self, 'card', None)
        if old is not None and old is not card:
            old.hide()
            old.deleteLater()
        self.card = card
        card.setProperty('uiZoomOwnSize', True)
        card.setParent(window.settings_scroll.viewport())
        card.installEventFilter(self)
        window.studio_entry_slot.installEventFilter(self)
        window.settings_scroll.widget().installEventFilter(self)
        self.schedule_sync()

    def schedule_sync(self, *_args):
        if not self._sync_timer.isActive():
            self._sync_timer.start(0)

    def sync(self, *_args):
        window = self.window_owner
        home = window.pages.currentWidget() is window.settings_scroll and window.settings_scroll.isVisible()
        self.card.setVisible(home)
        if not home:
            return
        card, viewport, slot = self.card, window.settings_scroll.viewport(), window.studio_entry_slot
        origin = slot.mapTo(viewport,QPoint())
        # The slot scrolls with the settings page. The left card's top follows
        # it until reaching the viewport top, while the card bottom stays in
        # the viewport. No extra row is inserted above the global action bar.
        top = max(0,min(origin.y(),max(0,viewport.height()-_zpx(300))))
        height = max(1,viewport.height()-top-_zpx(6))
        card.setGeometry(origin.x(),top,slot.width(),height)
        card.raise_()
        card.schedule_recent_fit()

    def eventFilter(self, obj, event):
        if event.type() in {QEvent.Resize, QEvent.Show, QEvent.Hide, QEvent.LayoutRequest, QEvent.FontChange}:
            self.schedule_sync()
        return False


class StudioEntryCard(QFrame):
    clicked = Signal()
    refresh_requested = Signal()

    def set_recent_layout(self, header, hero, caption, recent, footer):
        self._recent_layout_parts = (header, hero, caption, recent, footer)
        self._recent_fit = QTimer(self)
        self._recent_fit.setSingleShot(True)
        self._recent_fit.setInterval(0)
        self._recent_fit.timeout.connect(self._fit_recent_rows)

    def schedule_recent_fit(self):
        timer = getattr(self, '_recent_fit', None)
        if timer is not None and not timer.isActive():
            timer.start()

    def _fit_recent_rows(self):
        header, hero, caption, recent, footer = self._recent_layout_parts
        layout = self.layout()
        margins = layout.contentsMargins()
        spacing = max(0, layout.spacing())
        width = max(1, self.width() - margins.left() - margins.right())
        # Size from the card budget, never from the previous row count or the
        # hero's current allocation (which would feed back into itself).
        internal_footer = footer.parentWidget() is self
        budget = (self.height() - margins.top() - margins.bottom()
                  - header.sizeHint().height() - (footer.sizeHint().height() if internal_footer else 0)
                  - caption.sizeHint().height() - spacing * (4 if internal_footer else 3))
        cover_height = min(max(hero.minimumSizeHint().height(), round(width * .625)),
                           max(hero.minimumSizeHint().height(), round(budget * .58)))
        hero._budget_height = cover_height
        if hero.maximumHeight() != cover_height:
            hero.setMaximumHeight(cover_height)
        available = budget - cover_height
        rows = max(0, int(available // recent.row_height()))
        recent.set_limit(min(len(getattr(recent, '_all_entries', [])), rows))
        caption.setVisible(bool(recent.entries))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_recent_fit()

    def changeEvent(self, event):
        super().changeEvent(event)
        self.schedule_recent_fit()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cover = QImage()
        self._cover_key = None
        self._pressed = False
        # Home (2026-10-08) shows real recent covers instead of the painted backdrop.
        self.show_backdrop = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        bind_text(self, '进入字幕工作台', property='accessibleName')
        # Only visible Home polls metadata/stat values, also catching async covers.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1500)
        self._refresh_timer.timeout.connect(self.refresh_requested)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_requested.emit()
        self._refresh_timer.start()

    def hideEvent(self, event):
        self._refresh_timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        activate = self._pressed and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint())
        self._pressed = False
        if activate:
            event.accept()
            self.clicked.emit()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if not event.isAutoRepeat():
                self.clicked.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def set_cover_path(self, path: str) -> None:
        target = Path(path) if path else None
        try:
            stat = target.stat() if target and target.is_file() else None
            key = (str(target), stat.st_mtime_ns, stat.st_size) if stat else None
        except OSError:
            key = None
        if key == self._cover_key:
            return
        self._cover_key = key
        self._cover = QImage()
        if key:
            reader = QImageReader(str(target))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                reader.setScaledSize(size.scaled(960, 540, Qt.AspectRatioMode.KeepAspectRatio))
            self._cover = reader.read()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.show_backdrop:
            return
        theme = theme_definition(theme_key())
        paper, highlight, edge, ink, muted = studio_paper_colors(theme)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        clip = QPainterPath(); clip.addRoundedRect(rect, 18, 18)
        p.setClipPath(clip)
        # Quiet horizontal fibres are cheap to paint and stay behind the text.
        p.setPen(QPen(QColor(edge), .5))
        p.setOpacity(.07)
        for y in range(8, self.height(), 5):
            p.drawLine(0, y, self.width(), y)
        p.setOpacity(1)
        if not self._cover.isNull():
            factor = max(rect.width()/self._cover.width(), rect.height()/self._cover.height())
            w, h = self._cover.width()*factor, self._cover.height()*factor
            p.setOpacity(.17)
            p.drawImage(QRectF(rect.center().x()-w/2, rect.center().y()-h/2, w, h), self._cover)
            p.setOpacity(1)
            fade = QLinearGradient(rect.topLeft(), rect.bottomRight())
            start = QColor(paper); start.setAlpha(220)
            end = QColor(paper); end.setAlpha(20)
            fade.setColorAt(0, start); fade.setColorAt(1, end)
            p.fillRect(rect, fade)
        # A restrained timeline motif also gives empty libraries a visual identity.
        if self.height() > 260:
            p.setOpacity(.18)
            p.setPen(QPen(QColor(edge), 2))
            p.setBrush(QColor(highlight))
            x, y = self.width()*.52, self.height()*.32
            w, h = self.width()*.6, self.height()*.46
            p.drawRoundedRect(QRectF(x, y, w, h), 16, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(muted))
            for index, length in enumerate((.65, .82)):
                p.drawRoundedRect(QRectF(x+18+index*9, y+h*.45+index*22, w*length, 14), 5, 5)
            for index in range(20):
                amplitude = (5, 10, 17, 9, 23, 13, 6)[index % 7]
                p.drawRoundedRect(QRectF(x+20+index*8, y+h*.45+57-amplitude/2, 3, amplitude), 1.5, 1.5)
            triangle = QPainterPath()
            triangle.moveTo(x+20, y+16); triangle.lineTo(x+20, y+32)
            triangle.lineTo(x+34, y+24); triangle.closeSubpath()
            p.drawPath(triangle)
            p.setPen(QPen(QColor(theme.warning), 2))
            p.drawLine(int(x+w*.38), int(y+15), int(x+w*.38), int(y+h-12))
        p.end()
