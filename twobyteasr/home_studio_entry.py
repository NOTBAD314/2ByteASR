"""A quiet, cached project-cover backdrop for the Home Studio entrance."""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame

from .theme_manager import theme_key
from .ui_theme import theme_definition

from .i18n import bind_text


def studio_paper_colors(theme):
    """The entrance shares the active theme, including its painted motif."""
    if theme.key == "plum":
        return "#554537", "#66523F", "#B89970", "#FFF0D1", "#E0C8A5"
    if theme.key == "warm":
        return "#F2E3C4", "#F8EBD2", "#BE9A60", "#46351F", "#78603F"
    if theme.key == "grape":
        return "#593344", "#714053", "#B9819C", "#FFF1F6", "#E6BFD1"
    if theme.key == "lavender":
        return "#494361", "#5A5274", "#A79BC4", "#FAF3FF", "#D9CEE9"
    if theme.key == "slate":
        return "#3B5558", "#49676A", "#8CB7B5", "#F0FCF7", "#C5DEDA"
    return theme.surface_elevated, theme.selected, theme.border_strong, theme.text, theme.text_secondary


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
        from .project_display_name import display_project_name
        return display_project_name(record), str(cover) if cover else ""
    return "", ""


class StudioEntryCard(QFrame):
    clicked = Signal()
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cover = QImage()
        self._cover_key = None
        self._pressed = False
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
